from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from typing import Any, List, Optional

from langchain_core.documents import Document

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


def _load_chroma():
    from langchain_community.vectorstores import Chroma

    return Chroma


def _load_directory_loader():
    from langchain_community.document_loaders import DirectoryLoader, TextLoader

    return DirectoryLoader, TextLoader


def _load_txt_documents_simple(kb_path: str) -> List[Document]:
    docs: List[Document] = []
    for root, _, fnames in os.walk(kb_path):
        for fname in fnames:
            if not fname.lower().endswith(".txt"):
                continue
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    content = handle.read()
            except Exception:
                continue

            docs.append(Document(page_content=content, metadata={"source": path}))
    return docs


def _load_huggingface_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings


class _HashEmbeddingFunction:
    """Deterministic fallback embedding function for environments that cannot load HF models."""

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", (text or "").lower())

    def _vectorize(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = self._tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            weight = 1.0 + (len(token) % 3) * 0.1
            vector[index] += weight

        norm = sum(value * value for value in vector) ** 0.5
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    def embed_documents(self, texts):
        return [self._vectorize(text) for text in texts]

    def embed_query(self, text):
        return self._vectorize(text)


def build_embedding_function(embedding_model: str = DEFAULT_EMBED_MODEL):
    """Create embedding function and return (embedding_fn, effective_model_name)."""
    # Prefer lightweight local Sentence-Transformers (no API tokens)
    try:
        from sentence_transformers import SentenceTransformer

        class _STWrapper:
            def __init__(self, model_name: str):
                self.model_name = model_name
                # convert_to_numpy returns numpy arrays
                self.model = SentenceTransformer(model_name)

            def _normalize(self, vectors):
                try:
                    import numpy as np

                    arr = np.array(vectors, dtype=float)
                    norms = (arr * arr).sum(axis=1) ** 0.5
                    norms[norms == 0] = 1.0
                    arr = arr / norms[:, None]
                    return arr.tolist()
                except Exception:
                    return vectors

            def embed_documents(self, texts):
                if not texts:
                    return []
                vecs = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
                return self._normalize(vecs)

            def embed_query(self, text):
                vec = self.model.encode([text], convert_to_numpy=True, show_progress_bar=False)
                return self._normalize(vec)[0]

        try:
            embedding_fn = _STWrapper(embedding_model)
            return embedding_fn, embedding_model
        except Exception as ex:
            print(f"[RAG] sentence-transformers failed: {ex}")
    except Exception:
        # sentence-transformers not available; try HuggingFace embeddings next
        pass

    # Fallback: try LangChain HuggingFaceEmbeddings (may require torchcodec/ffmpeg)
    try:
        HuggingFaceEmbeddings = _load_huggingface_embeddings()
        if embedding_model == DEFAULT_EMBED_MODEL and PREFER_BIOMED_EMBEDDINGS:
            preferred_model = "NeuML/pubmedbert-base-embeddings"
            try:
                embedding_fn = HuggingFaceEmbeddings(model_name=preferred_model, encode_kwargs={"normalize_embeddings": True})
                return embedding_fn, preferred_model
            except Exception:
                pass

        try:
            embedding_fn = HuggingFaceEmbeddings(model_name=embedding_model, encode_kwargs={"normalize_embeddings": True})
            return embedding_fn, embedding_model
        except Exception as ex:
            print(f"[RAG] HuggingFace embeddings failed: {ex}")
    except Exception:
        pass

    print("[RAG] Falling back to hash embeddings (no local embedding models available).")
    return _HashEmbeddingFunction(), embedding_model


def vectorstore_count(vectorstore: Any) -> int:
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
        Chroma = _load_chroma()
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


def _download_precompiled_index(chroma_path: str) -> bool:
    """Download pre-compiled index from GitHub release. Returns True if successful."""
    RELEASE_URL = "https://github.com/saxovia/kb_for_medical_nlp/releases/download/DB/chroma_db.zip"
    
    try:
        import requests
        import zipfile
        
        os.makedirs(chroma_path, exist_ok=True)
        zip_path = os.path.join(os.path.dirname(chroma_path), "chroma_db_download.zip")
        
        print("[RAG] Attempting to download pre-compiled index...")
        with requests.get(RELEASE_URL, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            
            with open(zip_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = min(100, int(downloaded / total * 100))
                            print(f"[RAG]   Download progress: {pct}%", end="\r")
        
        print("\n[RAG] Download complete. Extracting...")
        
        # Extract to parent dir, then move chroma_db to target location
        parent_dir = os.path.dirname(chroma_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(parent_dir)
        
        # Clean up zip
        os.remove(zip_path)
        
        print(f"[RAG] Pre-compiled index extracted to {chroma_path}")
        return True
        
    except Exception as ex:
        print(f"[RAG] Download failed: {ex}")
        return False


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
    Chroma = _load_chroma()

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
            print("[RAG] No manifest found. Attempting to download pre-compiled index...")
        else:
            print("[RAG] Knowledge base changed. Attempting to download pre-compiled index...")
        
        # Try to download before rebuilding
        if not force_rebuild and _download_precompiled_index(chroma_path):
            try:
                vectorstore = Chroma(
                    persist_directory=chroma_path,
                    embedding_function=embedding_fn,
                )
                doc_count = vectorstore_count(vectorstore)
                if doc_count > 0:
                    print(f"[RAG] Successfully loaded downloaded index ({doc_count} vectors).")
                    return vectorstore
            except Exception as ex:
                print(f"[RAG] Could not load downloaded index: {ex}. Proceeding to rebuild...")
        
        if not force_rebuild and existing_manifest is None:
            print("[RAG] Building from scratch (no pre-compiled index available)...")
        elif not force_rebuild:
            print("[RAG] Building from scratch (download failed or skipped)...")

    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
    except Exception as ex:
        print(f"[RAG] Falling back to simple splitter because text splitters failed: {ex}")

        class RecursiveCharacterTextSplitter:  # type: ignore[no-redef]
            """Minimal splitter fallback to avoid heavy dependencies."""

            def __init__(self, chunk_size: int, chunk_overlap: int):
                self.chunk_size = max(1, int(chunk_size))
                self.chunk_overlap = max(0, int(chunk_overlap))

            def split_documents(self, docs: List[Document]) -> List[Document]:
                out: List[Document] = []
                for doc in docs:
                    text = doc.page_content or ""
                    if not text:
                        continue

                    start = 0
                    length = len(text)
                    while start < length:
                        end = min(length, start + self.chunk_size)
                        chunk = text[start:end]
                        out.append(Document(page_content=chunk, metadata=dict(doc.metadata)))
                        if end >= length:
                            break
                        start = max(0, end - self.chunk_overlap)
                return out

    try:
        DirectoryLoader, TextLoader = _load_directory_loader()
        txt_loader = DirectoryLoader(
            kb_path,
            glob="**/*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
        )
        txt_docs_raw = txt_loader.load()
    except Exception as ex:
        print(f"[RAG] Falling back to simple TXT loader because loader import failed: {ex}")
        txt_docs_raw = _load_txt_documents_simple(kb_path)
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
