import csv
import hashlib
import json
import os
import re
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
DEFAULT_BATCH_SIZE = 2000
MANIFEST_NAME = "rag_manifest.json"
ICD_LINE_RE = re.compile(
    r"^\s*([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)\s*:\s+(.+)$"
)

KNOWN_MED_ABBREV_RE = re.compile(
    r"\b(EKG|EEG|MRI|CT|UH|BP|HR|RR|SpO2|BMI|BNO|Hgb|WBC|RBC|CRP|PCT|INR|TSH|T3|T4|"
    r"COPD|HTN|DM|CHF|MI|PE|DVT|UTI|GERD)\b",
    re.IGNORECASE,
)

LATIN_MED_SUFFIX_RE = re.compile(
    r"\b\w*(?:itis|osis|emia|uria|ectomy|otomy|plasty|scopy|algia|pathy|logy|graphy|metry|"
    r"oma|ase|ine|ae|oe|yx|ix)\w*\b",
    re.IGNORECASE,
)


def _build_embedding_function(embedding_model: str = DEFAULT_EMBED_MODEL):
    """Create embedding function and return (embedding_fn, effective_model_name)."""
    if embedding_model == DEFAULT_EMBED_MODEL:
        # Prefer a biomedical model when available.
        preferred_model = "NeuML/pubmedbert-base-embeddings"
        try:
            embedding_fn = HuggingFaceEmbeddings(model_name=preferred_model)
            return embedding_fn, preferred_model
        except Exception:
            pass

    embedding_fn = HuggingFaceEmbeddings(model_name=embedding_model)
    return embedding_fn, embedding_model


def load_existing_vectorstore(
    chroma_path: str = DEFAULT_CHROMA_PATH,
    embedding_model: str = DEFAULT_EMBED_MODEL,
):
    """Load an existing Chroma index from disk without triggering any rebuild.

    Returns None if the path does not exist, cannot be loaded, or has zero vectors.
    """
    if not os.path.exists(chroma_path):
        print(f"[RAG] No existing Chroma directory at: {chroma_path}")
        return None

    try:
        embedding_fn, effective_embedding_model = _build_embedding_function(embedding_model)
        vectorstore = Chroma(
            persist_directory=chroma_path,
            embedding_function=embedding_fn,
        )
        doc_count = _vectorstore_count(vectorstore)
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


def _extract_medical_candidates_local(text: str, max_terms: int = 40) -> List[str]:
    candidates = []
    seen = set()

    def _add(token: str):
        t = token.strip()
        if len(t) < 3:
            return
        key = t.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(t)

    for m in KNOWN_MED_ABBREV_RE.finditer(text):
        _add(m.group(0).upper())

    for m in LATIN_MED_SUFFIX_RE.finditer(text):
        _add(m.group(0).lower())

    for m in re.finditer(r"\b[a-zA-Z\u00C0-\u017F]{8,}\b", text):
        _add(m.group(0).lower())

    return candidates[:max_terms]

def _is_icd_like_line(line: str) -> bool:
    return bool(ICD_LINE_RE.match((line or "").strip()))

DRUG_SECTION_RE = re.compile(
    r"^(Indications|Dosage|Warnings|Contraindications|Interactions.*?):\s*",
    re.IGNORECASE
)
DRUG_HEADER_RE = re.compile(r"^===\s*(.+?)\s*===$")

def _prepare_drug_documents(doc: Document) -> List[Document]:
    """
    Parse drugs.txt into one Document per (drug, section),
    deduplicating repeated label text within each section.
    """
    content = doc.page_content
    out = []
    current_drug = None
    current_section = None
    current_lines = []

    def _flush():
        if not current_drug or not current_lines:
            return
        # Deduplicate sentences within this section
        seen_sentences = set()
        unique_lines = []
        for line in current_lines:
            # Split on sentence boundaries
            for sent in re.split(r'(?<=[.!?])\s+', line):
                s = sent.strip()
                if not s:
                    continue
                key = re.sub(r'\s+', ' ', s.lower())
                if key not in seen_sentences:
                    seen_sentences.add(key)
                    unique_lines.append(s)
        if not unique_lines:
            return
        text = f"drug: {current_drug}\nsection: {current_section}\n" + " ".join(unique_lines)
        out.append(Document(
            page_content=text,
            metadata={**doc.metadata, "drug": current_drug, "section": current_section, "doc_type": "drug_monograph"},
        ))

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
            # Section body is the rest of the line after "SectionName: "
            rest = line[section_m.end():].strip()
            current_lines = [rest] if rest else []
            continue
        if current_drug:
            current_lines.append(line)

    _flush()
    return out



def _prepare_txt_documents(txt_docs: List[Document]) -> List[Document]:
    prepared: List[Document] = []

    for doc in txt_docs:
        content = doc.page_content or ""
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        if not lines:
            continue

        source = str(doc.metadata.get("source", ""))
        source_name = os.path.basename(source).lower()
        is_drug_doc = "drug" in source_name  # drugs.txt, drug_list.txt, etc.

        if is_drug_doc:
            prepared.extend(_prepare_drug_documents(doc))
            continue

        icd_hits = [(idx, ln) for idx, ln in enumerate(lines) if _is_icd_like_line(ln)]
        icd_ratio = (len(icd_hits) / len(lines)) if lines else 0.0

        # Treat known ICD files OR ICD-dense docs as code lists.
        is_icd_doc = ("icd" in source_name or source_name.endswith("icd10_codes.txt") or (len(icd_hits) >= 8 and icd_ratio >= 0.25))

        if is_icd_doc and icd_hits:
            for idx, line in icd_hits:
                md = dict(doc.metadata)
                md["doc_type"] = "icd_code"
                md["line_index"] = idx
                prepared.append(Document(page_content=line, metadata=md))
        else:
            prepared.append(doc)

    return prepared

LAB_TRIGGER_RE = re.compile(
    r"\b(CBC|WBC|RBC|Hgb|Hct|MCV|PLT|CRP|ESR|TSH|T3|T4|INR|PT|PTT|"
    r"ALT|AST|GGT|ALP|LDH|BUN|creatinine|eGFR|HbA1c|glucose|sodium|"
    r"potassium|chloride|bicarbonate|calcium|magnesium|phosphate|"
    r"albumin|bilirubin|troponin|BNP|procalcitonin|ferritin|"
    r"lab|result|reference\s+range|normal\s+range|level[s]?)\b",
    re.IGNORECASE,
)

def _transcript_mentions_labs(transcript: str) -> bool:
    return bool(LAB_TRIGGER_RE.search(transcript))

def _tokenize_for_overlap(text: str) -> set:
    return set(
    re.findall(r"[a-zA-Z0-9\u00C0-\u017F]{3,}", (text or "").lower())
    )

def _lexical_overlap_ratio(query_text: str, doc_text: str) -> float:
    q = _tokenize_for_overlap(query_text)
    d = _tokenize_for_overlap(doc_text)
    if not q or not d:
        return 0.0
    return len(q.intersection(d)) / len(q)


def _truncate_snippet(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if len(compact) <= max_chars:
        return compact

    cut = compact[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + " ..."


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

            is_ddi = fname == "DDI_data_clean.csv"
            seen_ddi = set()  # reset per file

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
    force_rebuild: bool = False
):
    print(f"[RAG] Loading knowledge base from {kb_path}...")

    if not os.path.exists(kb_path):
        os.makedirs(kb_path, exist_ok=True)
        print(f"[RAG] Created {kb_path} - add .txt / .csv reference files there.")
        return None

    # Choose an embedding model once and use the same effective model in the
    # fingerprint so unchanged inputs reliably reuse the existing index.
    embedding_fn, effective_embedding_model = _build_embedding_function(embedding_model)

    current_fingerprint = _build_fingerprint(
        kb_path=kb_path,
        csv_whitelist=csv_whitelist,
        rag_limit=rag_limit,
        embedding_model=effective_embedding_model,
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
    txt_docs = _prepare_txt_documents(txt_docs_raw)

    if txt_docs:
        print(f"[RAG] Loaded {len(txt_docs_raw)} .txt file(s), prepared {len(txt_docs)} txt documents")
    csv_docs = load_csv_documents(kb_path=kb_path, limit=rag_limit, only=csv_whitelist)

    if not txt_docs and not csv_docs:
        print("[RAG] No documents found in knowledge base - RAG disabled.")
        return None

    # ICD docs are already concise one-line docs; only chunk non-ICD docs.
    icd_docs        = [d for d in txt_docs if d.metadata.get("doc_type") == "icd_code"]
    drug_docs       = [d for d in txt_docs if d.metadata.get("doc_type") == "drug_monograph"]
    normal_txt_docs = [d for d in txt_docs if d.metadata.get("doc_type") not in ("icd_code", "drug_monograph")]

    txt_splits: List[Document] = []
    if normal_txt_docs:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        txt_splits.extend(splitter.split_documents(normal_txt_docs))

    txt_splits.extend(icd_docs)
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

    # Seed Chroma with a small first batch (required to initialize collection).
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

    # Index TXT in batches (including progress), if present.
    if total_txt > 0:
        txt_batches = _num_batches(total_txt, batch_size)
        print(f"[RAG] Indexing TXT chunks: {total_txt} docs in {txt_batches} batches")
        txt_start = batch_size  # first TXT batch already used as seed
        for i in range(txt_start, total_txt, batch_size):
            batch = txt_splits[i : i + batch_size]
            vectorstore.add_documents(batch)
            batch_no = (i // batch_size) + 1
            print(f"[RAG]   TXT batch {batch_no}/{txt_batches} done")
        print("[RAG] Finished TXT indexing.")

    # Index CSV in batches (including progress).
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

    _save_manifest(
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
            "csv_whitelist": _normalize_whitelist(csv_whitelist),
        },
    )

    return vectorstore


SYMPTOM_KEYWORDS = {
    # EN
    "pain", "fever", "cough", "headache", "nausea", "vomiting", "dizziness",
    "fatigue", "rash", "diarrhea", "constipation", "chills", "dyspnea",
    "shortness of breath", "chest pain", "abdominal pain", "sore throat",
    # HU
    "fajdalom", "laz", "kohoges", "fejfajas", "hanyinger", "hanyas",
    "szedules", "faradtsag", "kiutes", "hasmenes", "szekrekedes", "hidegrazas",
    "nehezlegzes", "mellkasi fajdalom", "hasi fajdalom", "torokfajas",
}


def _strip_speaker_tags(text: str) -> str:
    return re.sub(r"\bSPEAKER_\d+:\s*", "", text, flags=re.IGNORECASE)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_chief_complaint(text: str, max_len: int = 280) -> str:
    # Use first non-empty lines as a proxy for chief complaint.
    lines = [_norm_space(x) for x in text.splitlines() if _norm_space(x)]
    if not lines:
        return ""
    complaint = " ".join(lines[:2])
    return complaint[:max_len].strip()


def _extract_symptom_sentences(text: str, max_items: int = 4) -> list[str]:
    sentences = re.split(r"[.!?\n;]+", text)
    out = []
    seen = set()

    for s in sentences:
        s_clean = _norm_space(s)
        if not s_clean:
            continue
        low = s_clean.lower()
        if any(k in low for k in SYMPTOM_KEYWORDS):
            key = low[:200]
            if key not in seen:
                seen.add(key)
                out.append(s_clean[:220])
        if len(out) >= max_items:
            break

    return out


def _extract_medical_entities(text: str, max_terms: int = 12) -> list[str]:
    candidates = _extract_medical_candidates_local(text, max_terms=max_terms * 3)

    # Deduplicate while keeping order, and remove tiny/noisy tokens.
    out = []
    seen = set()
    for c in candidates:
        token = _norm_space(c)
        if len(token) < 3:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(token)
        if len(out) >= max_terms:
            break
    return out


def build_retrieval_queries(transcript: str, max_queries: int = 8) -> list[str]:
    clean = _strip_speaker_tags(transcript)
    clean = _norm_space(clean)

    queries = []

    complaint = _extract_chief_complaint(clean)
    if complaint:
        queries.append(f"chief complaint: {complaint}")

    symptom_sentences = _extract_symptom_sentences(clean, max_items=4)
    for s in symptom_sentences:
        queries.append(f"symptoms: {s}")

    entities = _extract_medical_entities(clean, max_terms=12)
    if entities:
        queries.append("medical entities: " + ", ".join(entities[:8]))

    # Keep a short fallback semantic query, not the whole transcript.
    if clean:
        queries.append(clean[:700])

    # Stable dedupe
    uniq = []
    seen = set()
    for q in queries:
        key = q.lower().strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(q)

    return uniq[:max_queries]



"""
Gets relevant context from the RAG vectorstore based on the transcript query, using a hybrid semantic + lexical scoring of retrieved documents. The retrieval queries are built by decomposing the transcript into chief complaint, symptom sentences, and medical entities, to improve recall of relevant information from the knowledge base. The final context is a concatenation of the top-ranked documents, which can then be fed into the LLM for response generation or enrichment.

"""

def get_relevant_context(
    query: str,
    vectorstore,
    final_k: int = 5,
    retrieve_k: int = 12,
    max_queries: int = 8,
    min_lexical_overlap: float = 0.10,
    max_chars_per_snippet: int = 280,
) -> str:
    if vectorstore is None:
        return ""

    final_k = max(3, min(5, int(final_k)))
    mentions_labs = _transcript_mentions_labs(query)
    retrieval_queries = build_retrieval_queries(query, max_queries=max_queries)

    if mentions_labs:
        lab_terms = [m.group(0) for m in LAB_TRIGGER_RE.finditer(query)][:6]
        retrieval_queries.append("lab test reference range: " + ", ".join(lab_terms))

    merged = {}

    for rq in retrieval_queries:
        try:
            raw = vectorstore.similarity_search_with_score(rq, k=retrieve_k)
            if not raw:
                continue

            # Figure out score direction from returned ordering:
            # if first <= last, treat it as distance (lower is better),
            # otherwise treat it as similarity/relevance (higher is better).
            first_score = float(raw[0][1])
            last_score = float(raw[-1][1])
            lower_is_better = first_score <= last_score

            score_values = [float(s) for _, s in raw]
            s_min, s_max = min(score_values), max(score_values)
            s_span = (s_max - s_min) or 1.0

            docs_with_semantic = []
            for rank, (doc, score) in enumerate(raw):
                score = float(score)

                # Normalize score to 0..1 where higher is better.
                if lower_is_better:
                    score_norm = (s_max - score) / s_span
                else:
                    score_norm = (score - s_min) / s_span

                rank_rrf = 1.0 / (rank + 1.0)

                # Blend numeric score + rank robustness.
                semantic = 0.70 * score_norm + 0.30 * rank_rrf
                docs_with_semantic.append((doc, semantic))

        except Exception:
            # Fallback if backend does not expose scores
            docs = vectorstore.similarity_search(rq, k=retrieve_k)
            docs_with_semantic = [
                (doc, 1.0 / (rank + 1.0))
                for rank, doc in enumerate(docs)
            ]

        for doc, semantic in docs_with_semantic:
            lex = _lexical_overlap_ratio(rq, doc.page_content)
            if lex < min_lexical_overlap:
                continue

            source = doc.metadata.get("source", "unknown")
            row = doc.metadata.get("row", -1)
            line_index = doc.metadata.get("line_index", -1)
            key = f"{source}|{row}|{line_index}|{hash(doc.page_content)}"

            if key not in merged:
                merged[key] = {
                    "doc": doc,
                    "hits": 1,
                    "semantic_sum": semantic,
                    "lex_max": lex,
                }
            else:
                item = merged[key]
                item["hits"] += 1
                item["semantic_sum"] += semantic
                item["lex_max"] = max(item["lex_max"], lex)

    if not merged:
        return ""

    max_hits = max(item["hits"] for item in merged.values())

    ranked = sorted(
        merged.values(),
        key=lambda item: (
            0.65 * (item["semantic_sum"] / item["hits"])  # avg semantic quality
            + 0.25 * item["lex_max"]                      # lexical support
            + 0.10 * (item["hits"] / max_hits)           # multi-query consistency
        ),
        reverse=True,
    )

    snippets = []
    seen_text = set()

    for item in ranked:
        snippet = _truncate_snippet(item["doc"].page_content, max_chars_per_snippet)
        key = snippet.lower()
        if not snippet or key in seen_text:
            continue
        seen_text.add(key)
        snippets.append(snippet)
        if len(snippets) >= final_k:
            break

    return "\n\n".join(snippets)


def build_context_block(rag_context: str, enrich_context: str) -> str:
    parts = []

    if rag_context:
        parts.append(f"Relevant medical reference information:\n{rag_context}")

    if enrich_context:
        parts.append(enrich_context)

    return "\n\n".join(parts) + "\n" if parts else ""