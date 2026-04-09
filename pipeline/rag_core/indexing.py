import csv
import hashlib
import json
import os
import re
import shutil
from typing import List, Optional

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

from .config import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_CHROMA_PATH,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_EMBED_MODEL,
    DEFAULT_KB_PATH,
    DRUG_HEADER_RE,
    DRUG_SECTION_RE,
    MANIFEST_NAME,
    PREFER_BIOMED_EMBEDDINGS,
)

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter


def build_embedding_function(embedding_model: str = DEFAULT_EMBED_MODEL):
    """Create embedding function and return (embedding_fn, effective_model_name)."""
    encode_kwargs = {"normalize_embeddings": True}
    if embedding_model == DEFAULT_EMBED_MODEL and PREFER_BIOMED_EMBEDDINGS:
        preferred_model = "NeuML/pubmedbert-base-embeddings"
        try:
            embedding_fn = HuggingFaceEmbeddings(model_name=preferred_model, encode_kwargs=encode_kwargs)
            return embedding_fn, preferred_model
        except Exception:
            pass

    embedding_fn = HuggingFaceEmbeddings(model_name=embedding_model, encode_kwargs=encode_kwargs)
    return embedding_fn, embedding_model


def vectorstore_count(vectorstore: Chroma) -> int:
    try:
        if hasattr(vectorstore, "_collection") and vectorstore._collection is not None:
            return int(vectorstore._collection.count())
    except Exception:
        pass
    return 0


def load_existing_vectorstore(
    chroma_path: str = DEFAULT_CHROMA_PATH,
    embedding_model: str = DEFAULT_EMBED_MODEL,
):
    """Load an existing Chroma index from disk without triggering any rebuild."""
    if not os.path.exists(chroma_path):
        print(f"[RAG] No existing Chroma directory at: {chroma_path}")
        return None

    try:
        embedding_fn, effective_embedding_model = build_embedding_function(embedding_model)
        vectorstore = Chroma(
            persist_directory=chroma_path,
            embedding_function=embedding_fn,
        )
        doc_count = vectorstore_count(vectorstore)
        if doc_count <= 0:
            print("[RAG] Existing Chroma index is empty.")
            return None

        print(
            f"[RAG] Loaded existing Chroma index ({doc_count} vectors) "
            f"using embeddings: {effective_embedding_model}"
        )
        return vectorstore
    except Exception as ex:
        print(f"[RAG] Failed to load existing Chroma index: {ex}")
        return None


def prepare_drug_documents(doc: Document) -> List[Document]:
    """Parse drugs.txt into one Document per (drug, section)."""
    content = doc.page_content
    out = []
    current_drug = None
    current_section = None
    current_lines = []

    def _flush():
        if not current_drug or not current_lines:
            return

        seen_sentences = set()
        unique_lines = []
        for line in current_lines:
            for sent in re.split(r"(?<=[.!?])\s+", line):
                s = sent.strip()
                if not s:
                    continue
                key = re.sub(r"\s+", " ", s.lower())
                if key not in seen_sentences:
                    seen_sentences.add(key)
                    unique_lines.append(s)

        if not unique_lines:
            return

        text = f"drug: {current_drug}\nsection: {current_section}\n" + " ".join(unique_lines)
        out.append(
            Document(
                page_content=text,
                metadata={
                    **doc.metadata,
                    "drug": current_drug,
                    "section": current_section,
                    "doc_type": "drug_monograph",
                },
            )
        )

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_m = DRUG_HEADER_RE.match(line)
        if header_m:
            _flush()
            current_drug = header_m.group(1)
            current_section = None
            current_lines = []
            continue

        section_m = DRUG_SECTION_RE.match(line)
        if section_m and current_drug:
            _flush()
            current_section = section_m.group(1).strip()
            rest = line[section_m.end() :].strip()
            current_lines = [rest] if rest else []
            continue

        if current_drug:
            current_lines.append(line)

    _flush()
    return out


def prepare_txt_documents(txt_docs: List[Document]) -> List[Document]:
    prepared: List[Document] = []

    for doc in txt_docs:
        content = doc.page_content or ""
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if not lines:
            continue

        source = str(doc.metadata.get("source", ""))
        source_name = os.path.basename(source).lower()
        is_drug_doc = "drug" in source_name

        if "icd" in source_name or source_name.endswith("icd10_codes.txt"):
            continue

        if is_drug_doc:
            prepared.extend(prepare_drug_documents(doc))
            continue

        prepared.append(doc)

    return prepared


def normalize_whitelist(csv_whitelist: Optional[List[str]]) -> List[str]:
    return sorted(csv_whitelist or [])


def collect_processed_files(kb_path: str, csv_whitelist: Optional[List[str]]) -> List[str]:
    files = []
    whitelist = set(csv_whitelist or [])
    whitelist_enabled = len(whitelist) > 0

    for root, _, fnames in os.walk(kb_path):
        for fname in fnames:
            lower = fname.lower()
            include = False

            if lower.endswith(".txt"):
                if "icd" in lower or lower.endswith("icd10_codes.txt"):
                    continue
                include = True
            elif lower.endswith(".csv"):
                if whitelist_enabled:
                    include = fname in whitelist
                else:
                    include = True

            if include:
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, kb_path).replace("\\", "/")
                files.append(rel)

    return sorted(files)


def build_fingerprint(
    kb_path: str,
    csv_whitelist: Optional[List[str]],
    rag_limit: Optional[int],
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
    batch_size: int,
) -> str:
    file_entries = []

    for rel in collect_processed_files(kb_path, csv_whitelist):
        abs_path = os.path.join(kb_path, rel.replace("/", os.sep))
        st = os.stat(abs_path)
        file_entries.append(
            {
                "path": rel,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
            }
        )

    payload = {
        "files": file_entries,
        "csv_whitelist": normalize_whitelist(csv_whitelist),
        "rag_limit": rag_limit,
        "embedding_model": embedding_model,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "batch_size": batch_size,
        "version": 2,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def manifest_path(chroma_path: str) -> str:
    return os.path.join(chroma_path, MANIFEST_NAME)


def load_manifest(chroma_path: str) -> Optional[dict]:
    path = manifest_path(chroma_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_manifest(chroma_path: str, manifest: dict) -> None:
    os.makedirs(chroma_path, exist_ok=True)
    with open(manifest_path(chroma_path), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def load_csv_documents(kb_path: str, limit: Optional[int] = None, only: Optional[List[str]] = None) -> List[Document]:
    docs: List[Document] = []

    for root, _, files in os.walk(kb_path):
        for fname in files:
            if not fname.lower().endswith(".csv"):
                continue

            if only and fname not in only:
                print(f"[RAG] Skipping CSV: {fname} (not in whitelist)")
                continue

            fpath = os.path.join(root, fname)
            print(f"[RAG] Loading CSV: {fname}")
            row_count = 0

            is_ddi = fname == "DDI_data_clean.csv"
            seen_ddi = set()

            with open(fpath, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                cols = [c.lower().strip() for c in fieldnames]

                has_term = "term" in cols
                has_definition = "definition" in cols
                has_translation = "translation" in cols

                for i, row in enumerate(reader):
                    if limit is not None and row_count >= limit:
                        break

                    if is_ddi:
                        d1 = (row.get("drug1_name") or "").strip().lower()
                        d2 = (row.get("drug2_name") or "").strip().lower()
                        itype = (row.get("interaction_type") or "").strip().lower()
                        if not d1 or not d2 or not itype:
                            continue
                        if d1 == d2 or len(d1) < 3 or len(d2) < 3:
                            continue

                        a, b = sorted((d1, d2))
                        ddi_key = (a, b)
                        if ddi_key in seen_ddi:
                            continue
                        seen_ddi.add(ddi_key)

                        text = f"drug_pair: {a} + {b}\ninteraction: {itype}"

                    elif has_term and has_definition:
                        term = (row.get("term") or "").strip()
                        definition = (row.get("definition") or "").strip()
                        if not term:
                            continue
                        text = f"term: {term}\ndefinition: {definition}"

                    elif has_term and has_translation:
                        term = (row.get("term") or "").strip()
                        translation = (row.get("translation") or "").strip()
                        if not term:
                            continue
                        text = f"term: {term}\ntranslation: {translation}"

                    else:
                        parts = [
                            f"{col}: {str(val).strip()}"
                            for col, val in row.items()
                            if val and str(val).strip()
                        ]
                        if not parts:
                            continue
                        text = "\n".join(parts)

                    docs.append(
                        Document(
                            page_content=text,
                            metadata={"source": fname, "row": i},
                        )
                    )
                    row_count += 1

            print(f"[RAG]   -> {row_count} rows loaded from {fname}")

    return docs


def setup_knowledge_base(
    rag_limit: Optional[int] = None,
    kb_path: str = DEFAULT_KB_PATH,
    chroma_path: str = DEFAULT_CHROMA_PATH,
    csv_whitelist: Optional[List[str]] = None,
    embedding_model: str = DEFAULT_EMBED_MODEL,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    batch_size: int = DEFAULT_BATCH_SIZE,
    force_rebuild: bool = False,
):
    print(f"[RAG] Loading knowledge base from {kb_path}...")

    if not os.path.exists(kb_path):
        os.makedirs(kb_path, exist_ok=True)
        print(f"[RAG] Created {kb_path} - add .txt / .csv reference files there.")
        return None

    embedding_fn, effective_embedding_model = build_embedding_function(embedding_model)

    current_fingerprint = build_fingerprint(
        kb_path=kb_path,
        csv_whitelist=csv_whitelist,
        rag_limit=rag_limit,
        embedding_model=effective_embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        batch_size=batch_size,
    )

    existing_manifest = load_manifest(chroma_path)
    manifest_matches = (
        existing_manifest is not None
        and existing_manifest.get("fingerprint") == current_fingerprint
    )

    if not force_rebuild and os.path.exists(chroma_path) and manifest_matches:
        try:
            vectorstore = Chroma(
                persist_directory=chroma_path,
                embedding_function=embedding_fn,
            )
            doc_count = vectorstore_count(vectorstore)
            if doc_count > 0:
                print(f"[RAG] Reusing existing Chroma index ({doc_count} vectors). No source changes detected.")
                return vectorstore
            print("[RAG] Existing index is empty. Rebuilding...")
        except Exception as ex:
            print(f"[RAG] Could not load existing index: {ex}. Rebuilding...")
    else:
        if force_rebuild:
            print("[RAG] Force rebuild requested.")
        elif existing_manifest is None:
            print("[RAG] No manifest found. Building index...")
        else:
            print("[RAG] Knowledge base changed. Rebuilding index...")

    txt_loader = DirectoryLoader(
        kb_path,
        glob="**/*.txt",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    txt_docs_raw = txt_loader.load()
    txt_docs = prepare_txt_documents(txt_docs_raw)

    if txt_docs:
        print(f"[RAG] Loaded {len(txt_docs_raw)} .txt file(s), prepared {len(txt_docs)} txt documents")
    csv_docs = load_csv_documents(kb_path=kb_path, limit=rag_limit, only=csv_whitelist)

    if not txt_docs and not csv_docs:
        print("[RAG] No documents found in knowledge base - RAG disabled.")
        return None

    drug_docs = [d for d in txt_docs if d.metadata.get("doc_type") == "drug_monograph"]
    normal_txt_docs = [d for d in txt_docs if d.metadata.get("doc_type") != "drug_monograph"]

    txt_splits: List[Document] = []
    if normal_txt_docs:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        txt_splits.extend(splitter.split_documents(normal_txt_docs))

    txt_splits.extend(drug_docs)

    if os.path.exists(chroma_path):
        shutil.rmtree(chroma_path)

    os.makedirs(chroma_path, exist_ok=True)

    total_txt = len(txt_splits)
    total_csv = len(csv_docs)

    if total_txt == 0 and total_csv == 0:
        print("[RAG] No content to index after preprocessing.")
        return None

    def _num_batches(n: int, bs: int) -> int:
        return (n + bs - 1) // bs if n > 0 else 0

    seed_from_txt = total_txt > 0
    seed_source = txt_splits if seed_from_txt else csv_docs
    seed_batch = seed_source[:batch_size]

    print(
        f"[RAG] Initializing index from {'TXT' if seed_from_txt else 'CSV'} "
        f"seed batch ({len(seed_batch)} docs)..."
    )
    vectorstore = Chroma.from_documents(
        documents=seed_batch,
        embedding=embedding_fn,
        persist_directory=chroma_path,
    )

    if total_txt > 0:
        txt_batches = _num_batches(total_txt, batch_size)
        print(f"[RAG] Indexing TXT chunks: {total_txt} docs in {txt_batches} batches")
        txt_start = batch_size
        for i in range(txt_start, total_txt, batch_size):
            batch = txt_splits[i : i + batch_size]
            vectorstore.add_documents(batch)
            batch_no = (i // batch_size) + 1
            print(f"[RAG]   TXT batch {batch_no}/{txt_batches} done")
        print("[RAG] Finished TXT indexing.")

    if total_csv > 0:
        csv_batches = _num_batches(total_csv, batch_size)
        print(f"[RAG] Indexing CSV rows: {total_csv} docs in {csv_batches} batches")
        csv_start = batch_size if not seed_from_txt else 0
        for i in range(csv_start, total_csv, batch_size):
            batch = csv_docs[i : i + batch_size]
            vectorstore.add_documents(batch)
            batch_no = (i // batch_size) + 1
            print(f"[RAG]   CSV batch {batch_no}/{csv_batches} done")
        print("[RAG] Finished CSV indexing.")

    try:
        if hasattr(vectorstore, "persist"):
            vectorstore.persist()
    except Exception:
        pass

    print()
    print(f"[RAG] Ready - {len(txt_splits)} txt chunks + {total_csv} CSV rows indexed.")

    save_manifest(
        chroma_path,
        {
            "fingerprint": current_fingerprint,
            "indexed_at_epoch": int(__import__("time").time()),
            "kb_path": kb_path,
            "chroma_path": chroma_path,
            "embedding_model": effective_embedding_model,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "batch_size": batch_size,
            "rag_limit": rag_limit,
            "csv_whitelist": normalize_whitelist(csv_whitelist),
        },
    )

    return vectorstore
