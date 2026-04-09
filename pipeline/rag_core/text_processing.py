import re
import unicodedata

from langchain_core.documents import Document

from .config import (
    DDI_PAIR_RE,
    HU_MARKERS,
    HU_TO_EN_MEDICAL_TERMS,
    KNOWN_MED_ABBREV_RE,
    LAB_TRIGGER_RE,
    LATIN_MED_SUFFIX_RE,
    MEDICATION_FOCUS_RE,
    MED_QUERY_DRUG_RE,
    SYMPTOM_KEYWORDS,
)


def extract_medical_entities(text: str, max_terms: int = 10) -> list[str]:
    """Pure regex-based extraction to replace scispaCy."""
    candidates = []
    seen = set()

    def _add(token: str):
        t = token.strip()
        if len(t) < 3:
            return
        key = t.lower()
        if key not in seen:
            seen.add(key)
            candidates.append(t)

    for m in KNOWN_MED_ABBREV_RE.finditer(text):
        _add(m.group(0).upper())

    for m in LATIN_MED_SUFFIX_RE.finditer(text):
        _add(m.group(0).lower())

    for m in re.finditer(r"\b[a-zA-Z\u00C0-\u017F]{8,}\b", text):
        _add(m.group(0).lower())

    return candidates[:max_terms]


def transcript_mentions_labs(transcript: str) -> bool:
    return bool(LAB_TRIGGER_RE.search(transcript))


def query_likely_medication_focused(text: str) -> bool:
    return bool(MEDICATION_FOCUS_RE.search(text or ""))


def extract_query_medication_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for m in MED_QUERY_DRUG_RE.finditer(text or ""):
        term = m.group(1).strip().lower()
        if len(term) >= 3:
            terms.add(term)
    return terms


def extract_ddi_pair_terms(doc: Document) -> set[str]:
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


def tokenize_for_overlap(text: str) -> set:
    return set(re.findall(r"[a-zA-Z0-9\u00C0-\u017F]{3,}", (text or "").lower()))


def lexical_overlap_ratio(query_text: str, doc_text: str) -> float:
    q = tokenize_for_overlap(query_text)
    d = tokenize_for_overlap(doc_text)
    if not q or not d:
        return 0.0
    return len(q.intersection(d)) / len(q)


def truncate_snippet(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", (text or "")).strip()
    if len(compact) <= max_chars:
        return compact

    cut = compact[:max_chars]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + " ..."


def doc_category(doc: Document) -> str:
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


def strip_speaker_tags(text: str) -> str:
    return re.sub(r"\bSPEAKER_\d+:\s*", "", text, flags=re.IGNORECASE)


def norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def norm_for_match(text: str) -> str:
    return norm_space(strip_accents((text or "").lower()))


def symptom_keyword_matches_text(keyword: str, normalized_text: str, normalized_tokens: list[str]) -> bool:
    """Match symptom keywords against normalized text, tolerant to Hungarian inflected forms."""
    kw = norm_for_match(keyword)
    if not kw:
        return False

    if re.search(r"\b" + re.escape(kw) + r"\b", normalized_text):
        return True

    parts = [p for p in kw.split() if p]
    if not parts:
        return False

    if len(parts) == 1:
        stem = parts[0]
        if len(stem) >= 4 and any(tok.startswith(stem) for tok in normalized_tokens):
            return True
        return False

    for part in parts:
        if len(part) < 3:
            continue
        if not any(tok.startswith(part) for tok in normalized_tokens):
            return False
    return True


def detect_language(text: str) -> str:
    low = (text or "").lower()
    if not low:
        return "en"

    accent_hits = sum(low.count(ch) for ch in "áéíóöőúüű")
    tokens = re.findall(r"[a-zA-Z\u00C0-\u017F]{2,}", low)
    hu_hits = sum(1 for t in tokens if t in HU_MARKERS)

    if accent_hits >= 2 or hu_hits >= 2:
        return "hu"
    return "en"


def translate_hu_to_en_text(text: str) -> str:
    out = norm_space(text)
    pairs = sorted(HU_TO_EN_MEDICAL_TERMS.items(), key=lambda x: len(x[0]), reverse=True)
    for hu, en in pairs:
        pattern = r"\b" + re.escape(hu) + r"\b"
        out = re.sub(pattern, en, out, flags=re.IGNORECASE)
    return out


def extract_chief_complaint(text: str, max_len: int = 280) -> str:
    lines = [norm_space(x) for x in text.splitlines() if norm_space(x)]
    if not lines:
        return ""
    complaint = " ".join(lines[:2])
    return complaint[:max_len].strip()


def extract_symptom_sentences(text: str, max_items: int = 4) -> list[str]:
    sentences = re.split(r"[.!?\n;]+", text)
    out = []
    seen = set()

    for s in sentences:
        s_clean = norm_space(s)
        if not s_clean:
            continue
        low = norm_for_match(s_clean)
        tokens = re.findall(r"[a-z0-9\u00C0-\u017F]+", low)
        if any(symptom_keyword_matches_text(k, low, tokens) for k in SYMPTOM_KEYWORDS):
            key = low[:200]
            if key not in seen:
                seen.add(key)
                out.append(s_clean[:220])
        if len(out) >= max_items:
            break

    return out


def extract_symptom_terms(text: str, max_items: int = 8) -> list[str]:
    clean = norm_space(strip_speaker_tags(text))
    clean_match = norm_for_match(clean)
    if not clean:
        return []

    clean_tokens = re.findall(r"[a-z0-9\u00C0-\u017F]+", clean_match)

    out = []
    seen = set()
    sorted_keywords = sorted(SYMPTOM_KEYWORDS, key=len, reverse=True)
    for kw in sorted_keywords:
        if symptom_keyword_matches_text(kw, clean_match, clean_tokens):
            key = kw.lower()
            if key not in seen:
                seen.add(key)
                out.append(kw)
        if len(out) >= max_items:
            break

    return out


def build_retrieval_queries(transcript: str, max_queries: int = 4) -> list[str]:
    clean = strip_speaker_tags(transcript)
    clean = norm_space(clean)
    language = detect_language(clean)

    retrieval_text = clean
    if language == "hu":
        retrieval_text = translate_hu_to_en_text(clean)

    queries = []

    complaint = extract_chief_complaint(retrieval_text)
    if complaint:
        queries.append(f"possible clinical diagnosis for: {complaint}")

    symptom_sentences = extract_symptom_sentences(retrieval_text, max_items=3)
    for s in symptom_sentences:
        queries.append(f"clinical symptoms: {s}")

    entities = extract_medical_entities(retrieval_text, max_terms=10)
    if entities:
        queries.append("medical conditions: " + ", ".join(entities[:5]))
        queries.append("differential diagnosis: " + ", ".join(entities[5:10]))

    if retrieval_text:
        queries.append(retrieval_text[:500])

    if language == "hu" and clean:
        queries.append(clean[:500])

    uniq = []
    seen = set()
    for q in queries:
        key = q.lower().strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(q)

    return uniq[:max_queries]
