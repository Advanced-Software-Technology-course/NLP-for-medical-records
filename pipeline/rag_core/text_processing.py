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
    NEGATION_PATTERNS,
    SYMPTOM_ALIASES,
)

DDI_INTENT_RE = re.compile(
    r"\b(interaction|drug interaction|contraindicat|do not combine|avoid together|drug\s*pair|co-administer|qt prolong|adverse effect)\b",
    re.IGNORECASE,
)


def deduplicate_symptoms(symptoms: list[str]) -> list[str]:
    """Remove duplicate symptoms after normalization."""
    seen_normalized = set()
    deduplicated = []

    for symptom in symptoms:
        normalized = norm_for_match(symptom)
        if normalized and normalized not in seen_normalized:
            seen_normalized.add(normalized)
            deduplicated.append(symptom)

    return deduplicated


def normalize_symptom_key(text: str) -> str:
    """Normalize symptom labels for matching and deduplication."""
    return norm_for_match(text).replace("-", " ").strip()



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


def classify_retrieval_intent(text: str) -> dict:
    """Heuristic intent classifier for retrieval routing."""
    lab_focused = transcript_mentions_labs(text)
    medication_focused = query_likely_medication_focused(text) or bool(extract_query_medication_terms(text))
    ddi_focused = bool(DDI_INTENT_RE.search(text or ""))

    normalized = norm_for_match(text)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    symptom_focused = any(
        symptom_keyword_matches_text(keyword, normalized, tokens)
        for keyword in SYMPTOM_KEYWORDS
    )

    return {
        "lab_focused": lab_focused,
        "medication_focused": medication_focused,
        "symptom_focused": symptom_focused,
        "ddi_focused": ddi_focused,
    }


def extract_symptom_terms_from_text(text: str, max_items: int = 8) -> list[str]:
    """Extract symptom keywords from the full text without speaker heuristics."""
    clean = norm_for_match(text)
    if not clean:
        return []

    tokens = re.findall(r"[a-z0-9]+", clean)
    out = []
    seen = set()
    for kw in sorted(SYMPTOM_KEYWORDS, key=len, reverse=True):
        if symptom_keyword_matches_text(kw, clean, tokens):
            key = normalize_symptom_key(kw)
            if key not in seen:
                seen.add(key)
                out.append(kw)
        if len(out) >= max_items:
            break
    return out


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


def _alias_variants(keyword: str) -> list[str]:
    """Return normalized alias variants for a symptom keyword."""
    normalized = normalize_symptom_key(keyword)
    variants = [normalized]
    for alias in SYMPTOM_ALIASES.get(normalized, ()):
        alias_norm = normalize_symptom_key(alias)
        if alias_norm and alias_norm not in variants:
            variants.append(alias_norm)
    return variants


def _token_matches_alias(token: str, alias: str) -> bool:
    token_n = normalize_symptom_key(token)
    alias_n = normalize_symptom_key(alias)
    if not token_n or not alias_n:
        return False
    if token_n == alias_n:
        return True
    if len(alias_n) >= 4 and token_n.startswith(alias_n):
        return True
    return False


def _alias_matches_tokens(tokens: list[str], alias: str) -> bool:
    alias_parts = [p for p in normalize_symptom_key(alias).split() if p]
    if not alias_parts:
        return False

    if len(alias_parts) == 1:
        return any(_token_matches_alias(token, alias_parts[0]) for token in tokens)

    for start in range(0, max(0, len(tokens) - len(alias_parts) + 1)):
        window = tokens[start:start + len(alias_parts)]
        if all(any(_token_matches_alias(token, part) for token in window) for part in alias_parts):
            return True
    return False


def symptom_keyword_matches_text(keyword: str, normalized_text: str, normalized_tokens: list[str]) -> bool:
    """Match symptom keywords against normalized text using explicit aliases."""
    for alias in _alias_variants(keyword):
        if re.search(r"\b" + re.escape(alias) + r"\b", normalized_text):
            return True
        if _alias_matches_tokens(normalized_tokens, alias):
            return True
    return False


def _find_keyword_token_span(tokens: list[str], keyword: str) -> tuple[int, int] | None:
    """Find the first token span matching a keyword, if any."""
    for alias in _alias_variants(keyword):
        alias_parts = [p for p in alias.split() if p]
        if not alias_parts:
            continue

        if len(alias_parts) == 1:
            for idx, token in enumerate(tokens):
                if _token_matches_alias(token, alias_parts[0]):
                    return idx, idx
            continue

        span_len = len(alias_parts)
        for start in range(0, max(0, len(tokens) - span_len + 1)):
            window = tokens[start:start + span_len]
            if all(any(_token_matches_alias(token, part) for token in window) for part in alias_parts):
                return start, start + span_len - 1

    return None


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
        tokens = re.findall(r"[a-z0-9]+", low)
        if any(symptom_keyword_matches_text(k, low, tokens) for k in SYMPTOM_KEYWORDS):
            key = low[:200]
            if key not in seen:
                seen.add(key)
                out.append(s_clean[:220])
        if len(out) >= max_items:
            break

    return out


def extract_symptom_terms(text: str, max_items: int = 8) -> list[str]:
    """Extract symptoms only from patient speaker (auto-detected)."""
    return extract_patient_symptoms(text, max_items=max_items)


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


def _has_negation_before_keyword(sentence: str, keyword: str, language: str = "en") -> bool:
    """Check if a symptom is negated near its mention."""
    normalized_sentence = normalize_symptom_key(sentence)
    neg_patterns = NEGATION_PATTERNS.get(language, []) + NEGATION_PATTERNS.get("en", [])
    neg_tokens = {normalize_symptom_key(item) for item in neg_patterns}

    clauses = [c for c in re.split(r"[;,\.!?]+", normalized_sentence) if c.strip()]
    for clause in clauses:
        tokens = re.findall(r"[a-z0-9]+", clause)
        keyword_span = _find_keyword_token_span(tokens, keyword)
        if keyword_span is None:
            continue

        start, end = keyword_span
        left_window = tokens[max(0, start - 4):start]
        right_window = tokens[end + 1:end + 3]
        clause_text = " ".join(tokens)

        for phrase in neg_patterns:
            phrase_norm = normalize_symptom_key(phrase)
            if phrase_norm and phrase_norm in clause_text:
                return True

        if any(tok in neg_tokens for tok in left_window):
            return True
        if any(tok in neg_tokens for tok in right_window):
            return True

        if any(phrase in clause_text for phrase in ("without", "lack of", "absence of", "no signs of", "no symptoms of")):
            return True

    return False


def detect_doctor_speaker(text: str) -> str:
    """Return the patient speaker ID using question/patient-language heuristics."""
    lines = text.strip().split('\n')
    speaker_0_lines = []
    speaker_1_lines = []
    
    for line in lines:
        if 'SPEAKER_0:' in line:
            speaker_0_lines.append(line.split(':', 1)[1].strip())
        elif 'SPEAKER_1:' in line:
            speaker_1_lines.append(line.split(':', 1)[1].strip())

    def question_score(lines_list: list[str]) -> int:
        return sum(line.count('?') for line in lines_list)
    
    def score_as_doctor(lines_list: list[str]) -> float:
        """Higher score = more likely to be doctor"""
        score = 0.0
        question_markers = {'czy', 'vagy', 'volt', 'van-e', 'had', 'ever'}
        second_person = {'you', 'your', 'szél', 'ön', 'te', 'volt-e', 'van-e'}
        first_person = {'i', 'have', 'am', 'én'}
        
        for line in lines_list:
            line_lower = line.lower()
            
            # Doctor traits
            if '?' in line:
                score += 2.0
            if any(marker in line_lower for marker in question_markers):
                score += 1.0
            if any(person in line_lower for person in second_person):
                score += 1.0
            
            # Patient traits (negative for doctor score)
            if any(person in line_lower for person in first_person):
                score -= 1.5
        
        return score / max(len(lines_list), 1)
    
    q0 = question_score(speaker_0_lines)
    q1 = question_score(speaker_1_lines)
    if q0 != q1:
        # The question-heavy speaker is the doctor, so return the other speaker.
        return "SPEAKER_0" if q1 > q0 else "SPEAKER_1"

    score_0 = score_as_doctor(speaker_0_lines)
    score_1 = score_as_doctor(speaker_1_lines)
    
    # Return the PATIENT (opposite of doctor)
    return "SPEAKER_0" if score_1 > score_0 else "SPEAKER_1"



def extract_patient_symptoms(text: str, max_items: int = 8) -> list[str]:
    """Extract symptoms only from the patient speaker (auto-detected)."""
    patient_speaker = detect_doctor_speaker(text)
    lines = text.strip().split('\n')
    
    reported_symptoms_raw = []
    seen = set()
    
    language = detect_language(text)

    for line in lines:
        # Only process patient speaker's statements
        if f'{patient_speaker}:' not in line:
            continue
        
        # Remove speaker tag
        content = line.split(':', 1)[1].strip()
        
        # Skip if it's a question (patient may ask but less likely)
        if '?' in content:
            continue
        
        clean = normalize_symptom_key(content)
        clean_tokens = re.findall(r"[a-z0-9]+", clean)
        
        # Extract symptoms only if not negated
        sorted_keywords = sorted(SYMPTOM_KEYWORDS, key=len, reverse=True)
        for kw in sorted_keywords:
            if symptom_keyword_matches_text(kw, clean, clean_tokens):
                if not _has_negation_before_keyword(content, kw, language):
                    key = normalize_symptom_key(kw)
                    if key not in seen:
                        seen.add(key)
                        reported_symptoms_raw.append(kw)
        
        if len(reported_symptoms_raw) >= max_items:
            break
    
    # Deduplicate variants (e.g., "fájdalom" vs "fajdalom")
    symptoms = deduplicate_symptoms(reported_symptoms_raw)
    normalized = {normalize_symptom_key(symptom) for symptom in symptoms}

    if "pain" in normalized and any(item in normalized for item in {"chest pain", "abdominal pain", "headache"}):
        symptoms = [symptom for symptom in symptoms if normalize_symptom_key(symptom) != "pain"]
        normalized = {normalize_symptom_key(symptom) for symptom in symptoms}

    if any(item in normalized for item in {"shortness of breath", "legszomj", "légszomj"}) and "dyspnea" in normalized:
        symptoms = [symptom for symptom in symptoms if normalize_symptom_key(symptom) != "dyspnea"]

    return symptoms[:max_items]