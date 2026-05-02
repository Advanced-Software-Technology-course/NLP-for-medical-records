import os
import re

DEFAULT_KB_PATH = "../data/knowledge_base"
DEFAULT_ICD_CODES_PATH = "../data/icd10_codes.txt"
DEFAULT_CHROMA_PATH = "../data/chroma_db"
DEFAULT_EMBED_MODEL = "all-MiniLM-L6-v2"
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 200
DEFAULT_BATCH_SIZE = 2000
MANIFEST_NAME = "rag_manifest.json"

# Retrieval scoring weights and caps.
RETRIEVAL_SEMANTIC_WEIGHT = 0.65
RETRIEVAL_LEXICAL_WEIGHT = 0.25
RETRIEVAL_HITS_WEIGHT = 0.10
RETRIEVAL_SCORE_NORM_WEIGHT = 0.70
RETRIEVAL_RRF_WEIGHT = 0.30
RETRIEVAL_RRF_K = 1.0
RETRIEVAL_POOL_K_MIN = 12
RETRIEVAL_POOL_K_MULTIPLIER = 2
RETRIEVAL_TARGETED_K_MIN = 4
RETRIEVAL_MAX_MERGED_DOCS = 2000
RETRIEVAL_MAX_PER_CATEGORY_MIN = 2
RETRIEVAL_BM25_WEIGHT = 0.30

SYMPTOM_BONUS_PER_HIT = 0.2
SYMPTOM_BONUS_MAX = 0.8
SECTION_PENALTY = 0.35

CATEGORY_PRIORITY_SYMPTOM_CLINICAL = 0.3
CATEGORY_PRIORITY_SYMPTOM_LAB = -0.4
CATEGORY_PRIORITY_SYMPTOM_DDI = -0.5
CATEGORY_PRIORITY_MED_MONOGRAPH = 0.2

CATEGORY_ADJUST_SYMPTOM_CLINICAL = 0.35
CATEGORY_ADJUST_SYMPTOM_MONOGRAPH = 0.1
CATEGORY_ADJUST_SYMPTOM_LAB = -0.45
CATEGORY_ADJUST_SYMPTOM_DDI = -0.6
CATEGORY_ADJUST_MED_MONOGRAPH = 0.25

SOURCE_BONUS_SYMPTOM = 0.25
SOURCE_BONUS_GENERAL = 0.1

PREFER_BIOMED_EMBEDDINGS = os.getenv("RAG_PREFER_BIOMED_EMBEDDINGS", "0").strip().lower() in {
    "1", "true", "yes", "on"
}

def _compile_word_regex(terms: list[str], extra_fragments: list[str] | None = None) -> re.Pattern:
    escaped = [re.escape(term) for term in terms]
    fragments = extra_fragments or []
    body = "|".join(escaped + fragments)
    return re.compile(rf"\b(?:{body})\b", re.IGNORECASE)


KNOWN_MED_ABBREV_TERMS = [
    "EKG", "EEG", "MRI", "CT", "UH", "BP", "HR", "RR", "SpO2", "BMI", "BNO",
    "Hgb", "WBC", "RBC", "CRP", "PCT", "INR", "TSH", "T3", "T4",
    "COPD", "HTN", "DM", "CHF", "MI", "PE", "DVT", "UTI", "GERD",
]
KNOWN_MED_ABBREV_RE = _compile_word_regex(KNOWN_MED_ABBREV_TERMS)

LATIN_MED_SUFFIX_RE = re.compile(
    r"\b\w*(?:itis|osis|emia|uria|ectomy|otomy|plasty|scopy|algia|pathy|logy|graphy|metry|"
    r"oma|ase|ine|ae|oe|yx|ix)\w*\b",
    re.IGNORECASE,
)

DRUG_SECTION_RE = re.compile(
    r"^(Indications|Dosage|Warnings|Contraindications|Interactions.*?):\s*",
    re.IGNORECASE,
)
DRUG_HEADER_RE = re.compile(r"^===\s*(.+?)\s*===$")

LAB_TRIGGER_TERMS = [
    "CBC", "WBC", "RBC", "Hgb", "Hct", "MCV", "PLT", "CRP", "ESR", "TSH", "T3",
    "T4", "INR", "PT", "PTT", "ALT", "AST", "GGT", "ALP", "LDH", "BUN",
    "creatinine", "eGFR", "HbA1c", "glucose", "sodium", "potassium", "chloride",
    "bicarbonate", "calcium", "magnesium", "phosphate", "albumin", "bilirubin",
    "troponin", "BNP", "procalcitonin", "ferritin", "lab", "result",
]
LAB_TRIGGER_FRAGMENTS = ["reference\\s+range", "normal\\s+range", "level[s]?"]
LAB_TRIGGER_RE = _compile_word_regex(LAB_TRIGGER_TERMS, LAB_TRIGGER_FRAGMENTS)

MEDICATION_FOCUS_TERMS = [
    "medication", "medicine", "drug", "dose", "dosage", "tablet", "pill", "capsule",
    "prescription", "interaction", "side effect", "contraindication", "allergy to",
]
MEDICATION_FOCUS_RE = _compile_word_regex(MEDICATION_FOCUS_TERMS)

MED_QUERY_DRUG_RE = re.compile(
    r"\b(?:taking|on|use|using|used|prescribed|medication|medicine|drug)\s+([a-zA-Z][a-zA-Z0-9\-]{2,})\b",
    re.IGNORECASE,
)
DDI_PAIR_RE = re.compile(r"drug_pair:\s*([^+\n]+)\+\s*([^\n]+)", re.IGNORECASE)

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

# Explicit symptom aliases used by the matcher to avoid over-broad fuzzy hits.
SYMPTOM_ALIASES = {
    "pain": ("pain", "fajdalom", "fajdalm", "fajdalmam", "fájdalom", "fájdalm", "fájdalmam"),
    "fever": ("fever", "laz", "láz"),
    "cough": ("cough", "kohog", "kohoges", "kohogese", "köhög", "köhögés", "köhögése"),
    "headache": ("headache", "fejfajas", "fejfájás"),
    "nausea": ("nausea", "hanyinger", "hányinger"),
    "vomiting": ("vomiting", "hanyas", "hányás"),
    "dizziness": ("dizziness", "szedules", "szédülés"),
    "fatigue": ("fatigue", "faradtsag", "fáradtság"),
    "rash": ("rash", "kiutes", "kiütés"),
    "diarrhea": ("diarrhea", "hasmenes", "hasmenés"),
    "constipation": ("constipation", "szekrekedes", "székrekedés"),
    "chills": ("chills", "hidegrazas", "hidegrázás"),
    "dyspnea": (
        "dyspnea", "shortness of breath", "legszomj", "légszomj",
        "legszomjam", "légszomjam", "nehezlegzes", "nehézlégzés", "fulladas", "fulladás",
    ),
    "chest pain": (
        "chest pain", "mellkasi fajdalom", "mellkasi fájdalom",
        "mellkasi fajdalm", "mellkasi fájdalm", "fajdalm", "fájdalm",
    ),
    "abdominal pain": ("abdominal pain", "hasi fajdalom", "hasi fájdalom", "hasi fajdalm", "hasi fájdalm"),
    "sore throat": ("sore throat", "torokfajas", "torokfájás"),
}

HU_TO_EN_MEDICAL_TERMS = { #TODO Rework
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

# Comprehensive negation patterns for robust denial detection.
NEGATION_PATTERNS = {
    "en": [
        "don't", "doesn't", "didn't", "do not", "does not", "did not",
        "no", "not", "never", "haven't", "has not", "have not", "hadn't", "had not",
        "none", "nothing", "nowhere", "no symptoms", "no signs",
        "without", "lack of", "absence of",
    ],
    "hu": [
        "nem", "nincs", "nincsen", "soha", "sem", "mégsem",
        "nem volt", "nem voltak", "nem lett", "nem voltak",
        "nincs", "nincsenek", "nem van", "nem voltak",
        "semmi", "semmilyen", "egyik sem",
        "nincs jele", "nincs tünete", "nincs jellegzetessége",
    ],
}

# Infection-aware ICD ranking rules.
ICD_INFECTION_PREFIXES = {
    "A", "B",  # ICD-10 Chapter I: Certain infectious and parasitic diseases
}

INFECTION_MARKERS = {
    "infection", "infectious", "viral", "bacterial", "sepsis", "pneumonia",
    "influenza", "covid", "typhoid", "paratyphoid",
}

# Symptoms that commonly appear with infections.
INFECTION_COMPATIBLE_SYMPTOMS = {
    "fever", "laz", "láz", "cough", "kohoges", "köhögés",
    "body ache", "malaise", "fatigue", "faradtsag", "fáradtság",
    "chills", "hidegrazas", "hidegrázás",
}

# Symptoms that suggest non-infectious causes.
NON_INFECTION_SYMPTOMS = {
    "chest pain", "mellkasi fajdalom", "mellkasi fájdalom",
    "shortness of breath", "legszomj", "légszomj", "dyspnea",
}
