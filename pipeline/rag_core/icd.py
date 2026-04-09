import difflib
import os

from .config import DEFAULT_ICD_CODES_PATH, HU_TO_EN_MEDICAL_TERMS
from .text_processing import detect_language, extract_symptom_terms, norm_for_match

try:
    from rapidfuzz import fuzz, process
except Exception:
    fuzz = None
    process = None


def parse_icd_code_lines(icd_path: str) -> list[tuple[str, str]]:
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
    language = detect_language(transcript)
    symptom_terms = extract_symptom_terms(transcript)
    if not symptom_terms:
        return []

    if language == "hu":
        mapped = []
        for term in symptom_terms:
            mapped_term = HU_TO_EN_MEDICAL_TERMS.get(norm_for_match(term), term)
            mapped.append(mapped_term)
        symptom_terms = mapped

    icd_entries = parse_icd_code_lines(icd_path)
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
            best = process.extract(
                symptom,
                descriptions,
                scorer=fuzz.WRatio,
                limit=max(top_k * 3, 6),
            )
            matches = [(desc, float(score)) for desc, score, _ in best]
        else:
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
