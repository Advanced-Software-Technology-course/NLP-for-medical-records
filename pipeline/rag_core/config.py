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

DRUG_SECTION_RE = re.compile(
    r"^(Indications|Dosage|Warnings|Contraindications|Interactions.*?):\s*",
    re.IGNORECASE,
)
DRUG_HEADER_RE = re.compile(r"^===\s*(.+?)\s*===$")

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
