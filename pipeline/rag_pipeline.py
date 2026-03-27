import csv
import hashlib
import json
import os
import shutil
from typing import Optional, List

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter


DEFAULT_KB_PATH = "../data/knowledge_base"
DEFAULT_CHROMA_PATH = "../data/chroma_db"
DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_BATCH_SIZE = 500
MANIFEST_NAME = "rag_manifest.json"


def _normalize_whitelist(csv_whitelist: Optional[List[str]]) -> List[str]:
    return sorted(csv_whitelist or [])


def _collect_processed_files(kb_path: str, csv_whitelist: Optional[List[str]]) -> List[str]:
    files = []
    whitelist = set(csv_whitelist or [])
    whitelist_enabled = len(whitelist) > 0

    for root, _, fnames in os.walk(kb_path):
        for fname in fnames:
            lower = fname.lower()
            include = False

            if lower.endswith(".txt"):
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


def _build_fingerprint(
    kb_path: str,
    csv_whitelist: Optional[List[str]],
    rag_limit: Optional[int],
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
    batch_size: int,
) -> str:
    file_entries = []

    for rel in _collect_processed_files(kb_path, csv_whitelist):
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
        "csv_whitelist": _normalize_whitelist(csv_whitelist),
        "rag_limit": rag_limit,
        "embedding_model": embedding_model,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "batch_size": batch_size,
        "version": 1,
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _manifest_path(chroma_path: str) -> str:
    return os.path.join(chroma_path, MANIFEST_NAME)


def _load_manifest(chroma_path: str) -> Optional[dict]:
    path = _manifest_path(chroma_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_manifest(chroma_path: str, manifest: dict) -> None:
    os.makedirs(chroma_path, exist_ok=True)
    with open(_manifest_path(chroma_path), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def _vectorstore_count(vectorstore: Chroma) -> int:
    try:
        if hasattr(vectorstore, "_collection") and vectorstore._collection is not None:
            return int(vectorstore._collection.count())
    except Exception:
        pass
    return 0


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

                    if has_term and has_definition:
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

    embedding_fn = HuggingFaceEmbeddings(model_name=embedding_model)

    current_fingerprint = _build_fingerprint(
        kb_path=kb_path,
        csv_whitelist=csv_whitelist,
        rag_limit=rag_limit,
        embedding_model=embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        batch_size=batch_size,
    )

    existing_manifest = _load_manifest(chroma_path)
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
            doc_count = _vectorstore_count(vectorstore)
            if doc_count > 0:
                print(f"[RAG] Reusing existing Chroma index ({doc_count} vectors).")
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
    txt_docs = txt_loader.load()
    if txt_docs:
        print(f"[RAG] Loaded {len(txt_docs)} .txt file(s)")

    csv_docs = load_csv_documents(kb_path=kb_path, limit=rag_limit, only=csv_whitelist)

    if not txt_docs and not csv_docs:
        print("[RAG] No documents found in knowledge base - RAG disabled.")
        return None

    txt_splits: List[Document] = []
    if txt_docs:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        txt_splits = splitter.split_documents(txt_docs)

    print(f"[RAG] Embedding {len(txt_splits)} txt chunks + {len(csv_docs)} CSV rows...")

    if os.path.exists(chroma_path):
        shutil.rmtree(chroma_path)

    os.makedirs(chroma_path, exist_ok=True)

    first_batch = txt_splits if txt_splits else csv_docs[:batch_size]
    if not first_batch:
        print("[RAG] No content to index after preprocessing.")
        return None

    vectorstore = Chroma.from_documents(
        documents=first_batch,
        embedding=embedding_fn,
        persist_directory=chroma_path,
    )

    csv_start = 0 if txt_splits else batch_size
    total_csv = len(csv_docs)

    for i in range(csv_start, total_csv, batch_size):
        batch = csv_docs[i : i + batch_size]
        vectorstore.add_documents(batch)
        total_batches = (total_csv // batch_size) + 1
        print(f"[RAG]   CSV batch {i // batch_size + 1}/{total_batches} done", end="\r")

    try:
        if hasattr(vectorstore, "persist"):
            vectorstore.persist()
    except Exception:
        pass

    print()
    print(f"[RAG] Ready - {len(txt_splits)} txt chunks + {total_csv} CSV rows indexed.")

    _save_manifest(
        chroma_path,
        {
            "fingerprint": current_fingerprint,
            "indexed_at_epoch": int(__import__("time").time()),
            "kb_path": kb_path,
            "chroma_path": chroma_path,
        },
    )

    return vectorstore


def get_relevant_context(query: str, vectorstore, k: int = 3) -> str:
    if vectorstore is None:
        return ""
    results = vectorstore.similarity_search(query, k=k)
    if not results:
        return ""
    return "\n\n".join([doc.page_content for doc in results])


def build_context_block(rag_context: str, enrich_context: str) -> str:
    parts = []

    if rag_context:
        parts.append(f"Relevant medical reference information:\n{rag_context}")

    if enrich_context:
        parts.append(enrich_context)

    return "\n\n".join(parts) + "\n" if parts else ""