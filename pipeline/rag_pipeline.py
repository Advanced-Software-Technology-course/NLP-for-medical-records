import csv
import difflib
import hashlib
import json
import os
import re
import shutil
import unicodedata
from typing import Optional, List

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

try:
    from rapidfuzz import fuzz, process
except Exception:
    fuzz = None
    process = None

DEFAULT_KB_PATH = "../data/knowledge_base"
DEFAULT_ICD_CODES_PATH = "../data/icd10_codes.txt"
DEFAULT_CHROMA_PATH = "../data/chroma_db"
DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_BATCH_SIZE = 2000
MANIFEST_NAME = "rag_manifest.json"
PREFER_BIOMED_EMBEDDINGS = os.getenv("RAG_PREFER_BIOMED_EMBEDDINGS", "0").strip().lower() in {
    "1", "true", "yes", "on"
}

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
    encode_kwargs = {'normalize_embeddings': True}
    if embedding_model == DEFAULT_EMBED_MODEL and PREFER_BIOMED_EMBEDDINGS:
        # Prefer a biomedical model when available.
        preferred_model = "NeuML/pubmedbert-base-embeddings"
        try:
            embedding_fn = HuggingFaceEmbeddings(model_name=preferred_model, encode_kwargs=encode_kwargs)
            return embedding_fn, preferred_model
        except Exception:
            pass

    embedding_fn = HuggingFaceEmbeddings(model_name=embedding_model, encode_kwargs=encode_kwargs)
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


def _extract_medical_entities(text: str, max_terms: int = 10) -> list[str]:
    """Pure regex-based extraction to replace scispaCy."""
    candidates = []
    seen = set()

    def _add(token: str):
        t = token.strip()
        if len(t) < 3: return
        key = t.lower()
        if key not in seen:
            seen.add(key)
            candidates.append(t)

    # 1. Match known medical abbreviations (EKG, MRI, etc.)
    for m in KNOWN_MED_ABBREV_RE.finditer(text):
        _add(m.group(0).upper())

    # 2. Match Latin-style medical terms (e.g., Gastritis, Nephropathy)
    for m in LATIN_MED_SUFFIX_RE.finditer(text):
        _add(m.group(0).lower())

    # 3. Match long words (8+ chars) which are often clinical descriptions
    for m in re.finditer(r"\b[a-zA-Z\u00C0-\u017F]{8,}\b", text):
        _add(m.group(0).lower())

    return candidates[:max_terms]



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
        if "icd" in source_name or source_name.endswith("icd10_codes.txt"):
            continue
        if is_drug_doc:
            prepared.extend(_prepare_drug_documents(doc))
            continue

        # ICD code lists are intentionally excluded from the vector DB.
        if "icd" in source_name or source_name.endswith("icd10_codes.txt"):
            print(f"[RAG] Skipping ICD-10 TXT from vector DB: {source_name}")
            continue

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

MEDICATION_FOCUS_RE = re.compile(
    r"\b(medication|medicine|drug|dose|dosage|tablet|pill|capsule|prescription|"
    r"interaction|side\s*effect|contraindication|allergy\s*to)\b",
    re.IGNORECASE,
)

def _transcript_mentions_labs(transcript: str) -> bool:
    return bool(LAB_TRIGGER_RE.search(transcript))


def _query_likely_medication_focused(text: str) -> bool:
    return bool(MEDICATION_FOCUS_RE.search(text or ""))


MED_QUERY_DRUG_RE = re.compile(
    r"\b(?:taking|on|use|using|used|prescribed|medication|medicine|drug)\s+([a-zA-Z][a-zA-Z0-9\-]{2,})\b",
    re.IGNORECASE,
)
DDI_PAIR_RE = re.compile(r"drug_pair:\s*([^+\n]+)\+\s*([^\n]+)", re.IGNORECASE)


def _extract_query_medication_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for m in MED_QUERY_DRUG_RE.finditer(text or ""):
        term = m.group(1).strip().lower()
        if len(term) >= 3:
            terms.add(term)
    return terms


def _extract_ddi_pair_terms(doc: Document) -> set[str]:
    content = doc.page_content or ""
    m = DDI_PAIR_RE.search(content)
    if not m:
        return set()
    a = m.group(1).strip().lower()
    b = m.group(2).strip().lower()
    out = set()
    if len(a) >= 3:
        out.add(a)
    if len(b) >= 3:
        out.add(b)
    return out

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


def _doc_category(doc: Document) -> str:
    """Map a document to a broad knowledge category for diversity-aware retrieval."""
    meta = doc.metadata or {}
    doc_type = str(meta.get("doc_type", "")).lower()
    source = str(meta.get("source", "")).lower()

    if doc_type == "drug_monograph":
        return "drug_monograph"

    if source.endswith(".csv"):
        if "ddi" in source:
            return "drug_interactions"
        if "lab" in source or "loinc" in source:
            return "lab_reference"
        return "csv_reference"

    return "clinical_text"


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
        "version": 2,
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

    drug_docs       = [d for d in txt_docs if d.metadata.get("doc_type") == "drug_monograph"]
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
    "fajdalom", "fájdalom", "laz", "láz", "kohoges", "köhögés", "köhög", "fejfajas", "fejfájás",
    "hanyinger", "hányinger", "hanyas", "hányás", "szedules", "szédülés", "faradtsag", "fáradtság",
    "kiutes", "kiütés", "hasmenes", "hasmenés", "szekrekedes", "székrekedés", "hidegrazas", "hidegrázás",
    "nehezlegzes", "nehézlégzés", "mellkasi fajdalom", "mellkasi fájdalom", "hasi fajdalom", "hasi fájdalom",
    "torokfajas", "torokfájás", "fulladas", "fulladás", "légszomj", "legszomj",
}

HU_TO_EN_MEDICAL_TERMS = {
    "mellkasi fajdalom": "chest pain",
    "mellkasi fájdalom": "chest pain",
    "hasi fajdalom": "abdominal pain",
    "hasi fájdalom": "abdominal pain",
    "fajdalom": "pain",
    "fájdalom": "pain",
    "laz": "fever",
    "láz": "fever",
    "kohoges": "cough",
    "köhögés": "cough",
    "köhög": "cough",
    "fejfajas": "headache",
    "fejfájás": "headache",
    "hanyinger": "nausea",
    "hányinger": "nausea",
    "hanyas": "vomiting",
    "hányás": "vomiting",
    "szedules": "dizziness",
    "szédülés": "dizziness",
    "faradtsag": "fatigue",
    "fáradtság": "fatigue",
    "kiutes": "rash",
    "kiütés": "rash",
    "hasmenes": "diarrhea",
    "hasmenés": "diarrhea",
    "szekrekedes": "constipation",
    "székrekedés": "constipation",
    "hidegrazas": "chills",
    "hidegrázás": "chills",
    "nehezlegzes": "shortness of breath",
    "nehézlégzés": "shortness of breath",
    "legszomj": "shortness of breath",
    "légszomj": "shortness of breath",
    "torokfajas": "sore throat",
    "torokfájás": "sore throat",
}

HU_MARKERS = {
    "hogy", "vagy", "nem", "van", "volt", "mert", "az", "egy", "es", "és",
    "fajdalom", "fájdalom", "laz", "láz", "kohoges", "köhögés", "legszomj", "légszomj",
}


def _strip_speaker_tags(text: str) -> str:
    return re.sub(r"\bSPEAKER_\d+:\s*", "", text, flags=re.IGNORECASE)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def _norm_for_match(text: str) -> str:
    return _norm_space(_strip_accents((text or "").lower()))


def _symptom_keyword_matches_text(keyword: str, normalized_text: str, normalized_tokens: list[str]) -> bool:
    """Match symptom keywords against normalized text, tolerant to Hungarian inflected forms."""
    kw = _norm_for_match(keyword)
    if not kw:
        return False

    # First try strict phrase boundary matching.
    if re.search(r"\b" + re.escape(kw) + r"\b", normalized_text):
        return True

    # Hungarian inflection-tolerant fallback.
    parts = [p for p in kw.split() if p]
    if not parts:
        return False

    # Single-word symptom: allow token-prefix match (e.g., "legszomj" vs "legszomjam").
    if len(parts) == 1:
        stem = parts[0]
        if len(stem) >= 4 and any(tok.startswith(stem) for tok in normalized_tokens):
            return True
        return False

    # Multi-word symptom: each part should match at least one token by prefix.
    for part in parts:
        if len(part) < 3:
            continue
        if not any(tok.startswith(part) for tok in normalized_tokens):
            return False
    return True


def _detect_language(text: str) -> str:
    low = (text or "").lower()
    if not low:
        return "en"

    accent_hits = sum(low.count(ch) for ch in "áéíóöőúüű")
    tokens = re.findall(r"[a-zA-Z\u00C0-\u017F]{2,}", low)
    hu_hits = sum(1 for t in tokens if t in HU_MARKERS)

    if accent_hits >= 2 or hu_hits >= 2:
        return "hu"
    return "en"


def _translate_hu_to_en_text(text: str) -> str:
    out = _norm_space(text)
    pairs = sorted(HU_TO_EN_MEDICAL_TERMS.items(), key=lambda x: len(x[0]), reverse=True)
    for hu, en in pairs:
        pattern = r"\b" + re.escape(hu) + r"\b"
        out = re.sub(pattern, en, out, flags=re.IGNORECASE)
    return out


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
        low = _norm_for_match(s_clean)
        tokens = re.findall(r"[a-z0-9\u00C0-\u017F]+", low)
        if any(_symptom_keyword_matches_text(k, low, tokens) for k in SYMPTOM_KEYWORDS):
            key = low[:200]
            if key not in seen:
                seen.add(key)
                out.append(s_clean[:220])
        if len(out) >= max_items:
            break

    return out


def _extract_symptom_terms(text: str, max_items: int = 8) -> list[str]:
    clean = _norm_space(_strip_speaker_tags(text))
    clean_match = _norm_for_match(clean)
    if not clean:
        return []

    clean_tokens = re.findall(r"[a-z0-9\u00C0-\u017F]+", clean_match)

    out = []
    seen = set()
    # Match longer multi-word symptoms first to avoid splitting e.g. chest pain.
    sorted_keywords = sorted(SYMPTOM_KEYWORDS, key=len, reverse=True)
    for kw in sorted_keywords:
        if _symptom_keyword_matches_text(kw, clean_match, clean_tokens):
            key = kw.lower()
            if key not in seen:
                seen.add(key)
                out.append(kw)
        if len(out) >= max_items:
            break

    return out


def _parse_icd_code_lines(icd_path: str) -> list[tuple[str, str]]:
    if not os.path.exists(icd_path):
        return []

    parsed: list[tuple[str, str]] = []
    with open(icd_path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            code, desc = line.split(":", 1)
            code = code.strip()
            desc = desc.strip()
            if code and desc:
                parsed.append((code, desc))

    return parsed


def suggest_icd_codes_local(
    transcript: str,
    icd_path: str = DEFAULT_ICD_CODES_PATH,
    top_k: int = 3,
) -> list[dict]:
    """Suggest top ICD codes using local symptom extraction + fuzzy lookup."""
    language = _detect_language(transcript)
    symptom_terms = _extract_symptom_terms(transcript)
    if not symptom_terms:
        return []

    if language == "hu":
        mapped = []
        for term in symptom_terms:
            mapped_term = HU_TO_EN_MEDICAL_TERMS.get(_norm_for_match(term), term)
            mapped.append(mapped_term)
        symptom_terms = mapped

    icd_entries = _parse_icd_code_lines(icd_path)
    if not icd_entries:
        return []

    descriptions = [desc for _, desc in icd_entries]
    by_desc = {desc: code for code, desc in icd_entries}

    symptom_preferred_prefix = {
        "fever": ("R50",),
        "cough": ("R05",),
        "shortness of breath": ("R06",),
        "dyspnea": ("R06",),
        "chest pain": ("R07",),
        "abdominal pain": ("R10",),
    }

    infection_markers = {
        "infection", "infectious", "viral", "bacterial", "sepsis", "pneumonia",
        "influenza", "covid", "typhoid", "paratyphoid",
    }

    scored: dict[str, dict] = {}
    for symptom in symptom_terms:
        if process is not None and fuzz is not None:
            # Use a robust fuzzy scorer for partial phrase matching.
            best = process.extract(
                symptom,
                descriptions,
                scorer=fuzz.WRatio,
                limit=max(top_k * 3, 6),
            )
            matches = [(desc, float(score)) for desc, score, _ in best]
        else:
            # Fallback without extra dependency.
            matches = []
            symptom_l = symptom.lower()
            for desc in descriptions:
                ratio = difflib.SequenceMatcher(None, symptom_l, desc.lower()).ratio() * 100.0
                if symptom_l in desc.lower():
                    ratio = max(ratio, 95.0)
                matches.append((desc, ratio))
            matches.sort(key=lambda x: x[1], reverse=True)
            matches = matches[: max(top_k * 3, 6)]

        for desc, score in matches:
            code = by_desc.get(desc)
            if not code:
                continue

            score_adj = float(score)
            symptom_key = symptom.lower().strip()
            preferred = symptom_preferred_prefix.get(symptom_key, ())
            if preferred and any(code.startswith(pref) for pref in preferred):
                score_adj += 8.0

            # Penalize infectious disease codes for generic symptom-only matching.
            if symptom_key in {"fever", "cough", "shortness of breath", "chest pain"}:
                desc_low = desc.lower()
                code_upper = code.upper()
                if code_upper.startswith(("A", "B")) and any(m in desc_low for m in infection_markers):
                    score_adj -= 6.0

            key = f"{code}|{desc}"
            existing = scored.get(key)
            if existing is None or score_adj > existing["score"]:
                scored[key] = {
                    "code": code,
                    "description": desc,
                    "matched_symptom": symptom,
                    "score": round(float(score_adj), 2),
                }

    ranked = sorted(scored.values(), key=lambda x: x["score"], reverse=True)
    return ranked[:top_k]

def build_retrieval_queries(transcript: str, max_queries: int = 4) -> list[str]:
    clean = _strip_speaker_tags(transcript)
    clean = _norm_space(clean)
    language = _detect_language(clean)

    retrieval_text = clean
    if language == "hu":
        retrieval_text = _translate_hu_to_en_text(clean)

    queries = []

    # 1. Chief complaint anchor query (kept diagnosis-focused, not code-focused).
    complaint = _extract_chief_complaint(retrieval_text)
    if complaint:
        queries.append(f"possible clinical diagnosis for: {complaint}")

    # 2. Symptom Sentences (Contextual search)
    symptom_sentences = _extract_symptom_sentences(retrieval_text, max_items=3)
    for s in symptom_sentences:
        queries.append(f"clinical symptoms: {s}")

    entities = _extract_medical_entities(retrieval_text, max_terms=10)
    if entities:
        # We create two types of entity queries for better recall
        queries.append("medical conditions: " + ", ".join(entities[:5]))
        queries.append("differential diagnosis: " + ", ".join(entities[5:10]))

    # 4. Fallback: Short Transcript Chunk
    if retrieval_text:
        queries.append(retrieval_text[:500])

    # Keep one native-language fallback query for bilingual recall.
    if language == "hu" and clean:
        queries.append(clean[:500])

    # Unique & Truncate
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

from concurrent.futures import ThreadPoolExecutor


def _similarity_search_with_optional_filter(vectorstore, query: str, k: int, where: Optional[dict] = None):
    """Run similarity search, using metadata filter only when supported by the backend."""
    try:
        if where:
            return vectorstore.similarity_search_with_score(query, k=k, filter=where)
        return vectorstore.similarity_search_with_score(query, k=k)
    except TypeError:
        # Some vectorstore adapters may not accept `filter`; fall back to unfiltered search.
        return vectorstore.similarity_search_with_score(query, k=k)
    except Exception:
        return []

def get_relevant_context(
    query: str,
    vectorstore,
    final_k: int = 5,
    retrieve_k: int = 8,
    max_queries: int = 4,
    min_lexical_overlap: float = 0.1,
    max_chars_per_snippet: int = 280,
    include_icd_suggestions: bool = False,
    icd_path: str = DEFAULT_ICD_CODES_PATH,
    icd_top_k: int = 3,
) -> str:
    if vectorstore is None:
        return ""

    retrieval_queries = build_retrieval_queries(query, max_queries=max_queries)
    pool_k = max(retrieve_k * 2, 12)
    medication_focused = _query_likely_medication_focused(query)
    query_med_terms = _extract_query_medication_terms(query)
    allow_ddi = medication_focused or bool(query_med_terms)
    
    # 1. Threaded Search Task
    def _threaded_search(rq):
        try:
            # Return query + search results so scoring can remain query-aware.
            return rq, _similarity_search_with_optional_filter(vectorstore, rq, k=pool_k), False
        except Exception:
            return rq, [], False

    # 2. Fire all queries in parallel
    with ThreadPoolExecutor(max_workers=max_queries) as executor:
        # map returns results in the same order as retrieval_queries
        all_results = list(executor.map(_threaded_search, retrieval_queries))

    # Run category-targeted retrieval for key CSV sources to improve source diversity.
    targeted_filters = [{"source": "clinical_lab_facts.csv"}]
    if allow_ddi:
        targeted_filters.append({"source": "DDI_data_clean.csv"})
    targeted_k = max(4, retrieve_k // 2)
    for rq in retrieval_queries[:2]:
        for where in targeted_filters:
            raw = _similarity_search_with_optional_filter(vectorstore, rq, k=targeted_k, where=where)
            if raw:
                all_results.append((rq, raw, True))

    merged = {}

    # 3. Process the results we already fetched
    for rq, raw, is_targeted in all_results: # <--- Iterating through the pre-fetched results
        if not raw:
            continue

        try:
            # Determine score direction
            first_score = float(raw[0][1])
            last_score = float(raw[-1][1])
            lower_is_better = first_score <= last_score

            score_values = [float(s) for _, s in raw]
            s_min, s_max = min(score_values), max(score_values)
            s_span = (s_max - s_min) or 1.0

            docs_with_semantic = []
            for rank, (doc, score) in enumerate(raw):
                score = float(score)
                # Normalize
                if lower_is_better:
                    score_norm = (s_max - score) / s_span
                else:
                    score_norm = (score - s_min) / s_span

                rank_rrf = 1.0 / (rank + 1.0)
                semantic = 0.70 * score_norm + 0.30 * rank_rrf
                docs_with_semantic.append((doc, semantic))
        
        except Exception:
            # Fallback if scoring fails
            docs_with_semantic = [(doc, 1.0 / (rank + 1.0)) for rank, (doc, _) in enumerate(raw)]

        # 4. Lexical Filter and Merging
        for doc, semantic in docs_with_semantic:
            lex = _lexical_overlap_ratio(rq, doc.page_content)
            if not is_targeted and lex < min_lexical_overlap:
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

    def _rank_score(item: dict) -> float:
        return (
            0.65 * (item["semantic_sum"] / item["hits"])
            + 0.25 * item["lex_max"]
            + 0.10 * (item["hits"] / max_hits)
        )

    snippets = []
    seen_text = set()
    selected_records: list[dict] = []
    max_drug_monographs = max(2, final_k // 2) if medication_focused else 1
    max_lab_references = 2 if _transcript_mentions_labs(query) else 1

    # Prefer one high-quality snippet per available category first, then fill by score.
    category_top: dict[str, dict] = {}
    for item in ranked:
        cat = _doc_category(item["doc"])
        if cat not in category_top:
            category_top[cat] = item

    category_order = sorted(
        category_top.keys(),
        key=lambda cat: _rank_score(category_top[cat]),
        reverse=True,
    )

    selected_categories = []
    for cat in category_order:
        item = category_top[cat]
        if cat == "drug_monograph":
            # For symptom-focused queries, prevent drug warnings from dominating.
            existing_drug = sum(1 for rec in selected_records if rec["cat"] == "drug_monograph")
            if existing_drug >= max_drug_monographs:
                continue
        if cat == "lab_reference":
            existing_lab = sum(1 for rec in selected_records if rec["cat"] == "lab_reference")
            if existing_lab >= max_lab_references:
                continue
        if cat == "drug_interactions" and not allow_ddi:
            continue

        snippet = _truncate_snippet(item["doc"].page_content, max_chars_per_snippet)
        key = snippet.lower()
        if not snippet or key in seen_text:
            continue
        seen_text.add(key)
        snippets.append(snippet)
        selected_records.append({"item": item, "cat": cat, "snippet": snippet, "score": _rank_score(item)})
        selected_categories.append(cat)
        if len(snippets) >= final_k:
            break

    # Fill remaining slots by global score while keeping each category from dominating.
    if len(snippets) < final_k:
        max_per_category = max(2, (final_k + 1) // 2)
        selected_doc_ids = {id(category_top[cat]["doc"]) for cat in selected_categories}

        category_selected = {}
        for cat in selected_categories:
            category_selected[cat] = category_selected.get(cat, 0) + 1

        for item in ranked:
            if len(snippets) >= final_k:
                break

            doc = item["doc"]
            if id(doc) in selected_doc_ids:
                continue

            cat = _doc_category(doc)
            if cat == "drug_monograph":
                if category_selected.get(cat, 0) >= max_drug_monographs:
                    continue
            if cat == "lab_reference":
                if category_selected.get(cat, 0) >= max_lab_references:
                    continue
            if cat == "drug_interactions" and not allow_ddi:
                continue
            if category_selected.get(cat, 0) >= max_per_category:
                continue

            snippet = _truncate_snippet(doc.page_content, max_chars_per_snippet)
            key = snippet.lower()
            if not snippet or key in seen_text:
                continue

            seen_text.add(key)
            snippets.append(snippet)
            selected_doc_ids.add(id(doc))
            category_selected[cat] = category_selected.get(cat, 0) + 1
            selected_records.append({"item": item, "cat": cat, "snippet": snippet, "score": _rank_score(item)})

    # Reserve at least one DDI snippet when available and final_k allows diversity.
    if final_k >= 3 and allow_ddi:
        best_ddi = None
        for item in ranked:
            if _doc_category(item["doc"]) != "drug_interactions":
                continue
            if query_med_terms:
                pair_terms = _extract_ddi_pair_terms(item["doc"])
                if pair_terms and not (pair_terms.intersection(query_med_terms)):
                    continue
            best_ddi = item
            break
        has_ddi = any(rec["cat"] == "drug_interactions" for rec in selected_records)

        if best_ddi is not None and not has_ddi:
            ddi_snippet = _truncate_snippet(best_ddi["doc"].page_content, max_chars_per_snippet)
            ddi_key = ddi_snippet.lower()
            if ddi_snippet and ddi_key not in seen_text:
                ddi_record = {
                    "item": best_ddi,
                    "cat": "drug_interactions",
                    "snippet": ddi_snippet,
                    "score": _rank_score(best_ddi),
                }

                if len(selected_records) < final_k:
                    selected_records.append(ddi_record)
                    seen_text.add(ddi_key)
                else:
                    replace_candidates = [
                        rec for rec in selected_records if rec["cat"] != "drug_interactions"
                    ]
                    if replace_candidates:
                        # Replace the weakest non-DDI entry, preferring drug monograph replacement.
                        monograph_candidates = [rec for rec in replace_candidates if rec["cat"] == "drug_monograph"]
                        target_pool = monograph_candidates if monograph_candidates else replace_candidates
                        to_replace = min(target_pool, key=lambda rec: rec["score"])
                        selected_records.remove(to_replace)
                        selected_records.append(ddi_record)
                        seen_text.discard(to_replace["snippet"].lower())
                        seen_text.add(ddi_key)

    selected_records.sort(key=lambda rec: rec["score"], reverse=True)
    snippets = [rec["snippet"] for rec in selected_records[:final_k]]

    context = "\n\n".join(snippets)

    if include_icd_suggestions:
        codes = suggest_icd_codes_local(query, icd_path=icd_path, top_k=icd_top_k)
        if codes:
            lines = ["Suggested ICD-10 codes (local lookup):"]
            for item in codes:
                code = item.get("code", "")
                desc = item.get("description", "")
                symptom = item.get("matched_symptom", "")
                score = item.get("score", "")
                if code and desc:
                    lines.append(f"- {code}: {desc} (matched symptom: {symptom}, score={score})")
            if len(lines) > 1:
                context = f"{context}\n\n" + "\n".join(lines) if context else "\n".join(lines)

    return context


def build_context_block(
    rag_context: str,
    enrich_context: str,
    suggested_codes: Optional[List[dict]] = None,
) -> str:
    parts = []

    if rag_context:
        parts.append(f"Relevant medical reference information:\n{rag_context}")

    if suggested_codes:
        lines = ["Suggested Codes:"]
        for item in suggested_codes:
            code = item.get("code", "")
            desc = item.get("description", "")
            symptom = item.get("matched_symptom", "")
            if code and desc:
                lines.append(f"- {code}: {desc} (matched symptom: {symptom})")
        if len(lines) > 1:
            parts.append("\n".join(lines))

    if enrich_context:
        parts.append(enrich_context)

    return "\n\n".join(parts) + "\n" if parts else ""