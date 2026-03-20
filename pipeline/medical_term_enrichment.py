"""
Medical Term Enrichment Module
-------------------------------
Lookup priority for every candidate term extracted from a transcript:

  1. Local CSV dictionary  — searches the scraped CSVs in KB_PATH first
  2. SQLite cache          — previously fetched super55 results
  3. super55.com live      — only if steps 1+2 both miss

Hungarian-only: only Latin/Greek medical vocab or Hungarian-accented words
are considered. Plain English filler words are ignored entirely.
"""

import csv
import os
import re
import sqlite3
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ── CONFIG ────────────────────────────────────────────────────────────────────

SUPER55_SEARCH_URL = "https://www.super55.com/index.php?s=1&q={}"
SUPER55_DETAIL_URL = "https://www.super55.com/index.php?q={}&l=1&t=12&r=0"
REQUEST_DELAY      = 2.5
MIN_TERM_LENGTH    = 3
CACHE_DB_PATH      = "../data/super55_cache.db"
KB_PATH            = "../data/knowledge_base"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── STOPWORDS ─────────────────────────────────────────────────────────────────

STOPWORDS = {
    "a", "az", "es", "vagy", "de", "hogy", "van", "volt", "lesz",
    "nem", "igen", "is", "mar", "meg", "csak", "ez", "egy", "ill",
    "ami", "aki", "ott", "itt", "arra", "erre", "mert", "mint",
    "tehat", "akkor", "utan", "elott", "alatt", "felett",
    "illetve", "valamint", "mivel", "ezert", "viszont", "azonban",
    "the", "and", "or", "of", "in", "is", "was", "are", "with",
    "for", "to", "be", "has", "have", "had", "this", "that", "its",
    "but", "not", "from", "by", "as", "at", "an", "it", "on", "do",
    "did", "will", "would", "could", "should", "may", "might", "must",
    "about", "after", "before", "during", "while", "when", "where",
    "which", "who", "what", "how", "all", "any", "also", "just",
    "been", "being", "into", "than", "then", "there", "their", "they",
    "your", "you", "yes", "okay", "right", "actually", "already",
    "anything", "something", "nothing", "everything",
    "going", "getting", "take", "taking", "feel", "feeling", "think",
    "know", "see", "seem", "said", "say", "want", "need", "like",
    "well", "good", "fine", "sure", "because", "since", "even",
    "still", "back", "over", "here", "around", "away", "added",
    "acutely", "afternoon", "alcohol", "ask", "regular", "today",
    "speaker", "beteg", "orvos", "doktor", "patient", "doctor",
    "symptoms", "treatment", "diagnosis", "medication",
}

LATIN_ENDINGS = (
    "itis", "osis", "emia", "uria", "ectomy", "otomy", "plasty",
    "scopy", "algia", "pathy", "logy", "graphy", "metry",
    "ae", "oe", "yx", "ix", "oma", "ase", "ine",
)

KNOWN_ABBREV_PATTERN = re.compile(
    r"\b("
    r"EKG|EEG|MRI|CT|UH|BP|HR|RR|SpO2|BMI|BNO|"
    r"i\.v\.|p\.o\.|s\.c\.|i\.m\.|"
    r"Hgb|WBC|RBC|CRP|PCT|INR|TSH|T3|T4|"
    r"COPD|HTN|DM|CHF|MI|PE|DVT|UTI|GERD|"
    r"bid|tid|qid|qd|prn|sos|stat"
    r")\b",
    re.IGNORECASE,
)


# ── HUNGARIAN-ONLY FILTER ─────────────────────────────────────────────────────

def _is_hungarian_medical(token: str) -> bool:
    t = token.lower().strip()
    if t in STOPWORDS:
        return False
    if len(t) < MIN_TERM_LENGTH:
        return False
    if not re.search(r"[a-z\xe1\xe9\xed\xf3\xf6\u0151\xfa\xfc\u0171]", t):
        return False

    has_accent   = bool(re.search(r"[\xe1\xe9\xed\xf3\xf6\u0151\xfa\xfc\u0171]", t))
    is_latin     = any(t.endswith(e) for e in LATIN_ENDINGS)
    is_abbrev    = token.upper() == token and len(token) <= 6
    is_multiword = " " in t

    if has_accent or is_latin or is_abbrev or is_multiword:
        return True
    return len(t) >= 9


# ── TERM EXTRACTOR ────────────────────────────────────────────────────────────

def extract_medical_candidates(text: str) -> list:
    candidates = set()

    for m in KNOWN_ABBREV_PATTERN.finditer(text):
        candidates.add(m.group(0).upper())

    latin_re = re.compile(
        r"\b\w*(?:itis|osis|emia|uria|ectomy|otomy|plasty|scopy|"
        r"algia|pathy|logy|graphy|metry|oma|ase|ine|ae|oe|yx|ix)\w*\b",
        re.IGNORECASE,
    )
    for m in latin_re.finditer(text):
        w = m.group(0)
        if len(w) >= MIN_TERM_LENGTH and w.lower() not in STOPWORDS:
            candidates.add(w.lower())

    hu_re = re.compile(
        r"\b[a-z\xe1\xe9\xed\xf3\xf6\u0151\xfa\xfc\u0171A-Z\xc1\xc9\xcd\xd3\xd6\u0150\xda\xdc\u0170]*"
        r"[\xe1\xe9\xed\xf3\xf6\u0151\xfa\xfc\u0171]"
        r"[a-z\xe1\xe9\xed\xf3\xf6\u0151\xfa\xfc\u0171A-Z\xc1\xc9\xcd\xd3\xd6\u0150\xda\xdc\u0170]*\b"
    )
    for m in hu_re.finditer(text):
        w = m.group(0)
        if len(w) >= MIN_TERM_LENGTH and w.lower() not in STOPWORDS:
            candidates.add(w.lower())

    phrase_re = re.compile(
        r"\b([A-Z\xc1\xc9\xcd\xd3\xd6\u0150\xda\xdc\u0170]"
        r"[a-z\xe1\xe9\xed\xf3\xf6\u0151\xfa\xfc\u0171]+"
        r"(?:\s+[A-Za-z\xe1\xe9\xed\xf3\xf6\u0151\xfa\xfc\u0171\xc1\xc9\xcd\xd3\xd6\u0150\xda\xdc\u0170]+){1,2})\b"
    )
    for m in phrase_re.finditer(text):
        phrase = m.group(1)
        words  = phrase.split()
        if all(w.lower() not in STOPWORDS for w in words):
            candidates.add(phrase.lower())

    abbrevs = sorted([c for c in candidates if c.upper() == c and len(c) <= 6])
    rest    = sorted([c for c in candidates if c not in abbrevs])
    return abbrevs + rest


# ── CSV DICTIONARY ────────────────────────────────────────────────────────────

class CSVDictionary:
    """
    In-memory O(1) lookup built from all CSVs in KB_PATH at startup.
    Supports term+definition and term+translation column layouts.
    Also tries stripping Hungarian inflection suffixes on miss.
    """

    def __init__(self, kb_path: str = KB_PATH):
        self._data: dict = {}
        self._load(kb_path)

    def _load(self, kb_path: str):
        if not os.path.exists(kb_path):
            return
        total = 0
        for root, _, files in os.walk(kb_path):
            for fname in files:
                if not fname.lower().endswith(".csv"):
                    continue
                fpath  = os.path.join(root, fname)
                loaded = self._load_file(fpath, fname)
                total += loaded
                print(f"[CSV dict] {fname}: {loaded} terms loaded")
        print(f"[CSV dict] Total: {total} terms available for local lookup\n")

    def _load_file(self, fpath: str, fname: str) -> int:
        count = 0
        with open(fpath, encoding="utf-8") as f:
            reader    = csv.DictReader(f)
            cols      = [c.lower().strip() for c in (reader.fieldnames or [])]
            has_def   = "definition" in cols
            has_trans = "translation" in cols
            has_term  = "term" in cols

            for row in reader:
                term = row.get("term", "").strip()
                if not term:
                    continue

                if has_term and has_def:
                    value = row.get("definition", "").strip()
                elif has_term and has_trans:
                    value = row.get("translation", "").strip()
                else:
                    value = " | ".join(
                        v.strip() for k, v in row.items()
                        if k and k.lower() != "term" and v and v.strip()
                    )

                if value:
                    key = term.lower()
                    if key not in self._data or len(value) > len(self._data[key]["definition"]):
                        self._data[key] = {"definition": value, "source": fname}
                    count += 1
        return count

    def lookup(self, term: str) -> Optional[dict]:
        key = term.lower().strip()
        if key in self._data:
            return self._data[key]

        # Try stripping Hungarian inflection suffixes
        for suffix in ("anak", "enek", "aban", "eben", "aval", "evel",
                       "nak", "nek", "ban", "ben", "bol", "bel",
                       "hoz", "hez", "hoz", "nal", "nel", "tol", "toel",
                       "val", "vel", "ra", "re", "ba", "be", "on", "en",
                       "hoz", "ig", "ul", "ul", "as", "es",
                       "ja", "je", "a", "e", "i"):
            if key.endswith(suffix) and len(key) - len(suffix) >= MIN_TERM_LENGTH:
                stem = key[: -len(suffix)]
                if stem in self._data:
                    return self._data[stem]
        return None

    @property
    def size(self) -> int:
        return len(self._data)


# ── SQLITE CACHE ──────────────────────────────────────────────────────────────

class TermCache:
    def __init__(self, db_path: str = CACHE_DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS terms (
                term        TEXT PRIMARY KEY,
                translation TEXT,
                definition  TEXT,
                source      TEXT DEFAULT 'super55',
                looked_up   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS abbreviations (
                abbrev      TEXT PRIMARY KEY,
                expansion   TEXT,
                source      TEXT DEFAULT 'super55',
                looked_up   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    def get(self, term: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT translation, definition FROM terms WHERE term = ?",
            (term.lower(),),
        ).fetchone()
        return {"translation": row[0], "definition": row[1]} if row else None

    def set(self, term: str, translation: str, definition: str = "", source: str = "super55"):
        self.conn.execute(
            "INSERT OR REPLACE INTO terms (term, translation, definition, source) VALUES (?,?,?,?)",
            (term.lower(), translation, definition, source),
        )
        self.conn.commit()

    def get_abbrev(self, abbrev: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT expansion FROM abbreviations WHERE abbrev = ?",
            (abbrev.upper(),),
        ).fetchone()
        return row[0] if row else None

    def set_abbrev(self, abbrev: str, expansion: str, source: str = "super55"):
        self.conn.execute(
            "INSERT OR REPLACE INTO abbreviations (abbrev, expansion, source) VALUES (?,?,?)",
            (abbrev.upper(), expansion, source),
        )
        self.conn.commit()

    def stats(self) -> dict:
        n_terms   = self.conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0]
        n_abbrevs = self.conn.execute("SELECT COUNT(*) FROM abbreviations").fetchone()[0]
        return {"cached_terms": n_terms, "cached_abbreviations": n_abbrevs}


# ── SUPER55 LIVE FETCHER ──────────────────────────────────────────────────────

class Super55Fetcher:
    def __init__(self, delay: float = REQUEST_DELAY):
        self.delay         = delay
        self._last_request = 0.0

    def _wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.time()

    def _get(self, url: str) -> Optional[str]:
        try:
            self._wait()
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.encoding = "utf-8"
            return resp.text if resp.status_code == 200 else None
        except Exception as e:
            print(f"  [super55] error: {e}")
            return None

    def search(self, term: str) -> dict:
        html = self._get(SUPER55_SEARCH_URL.format(requests.utils.quote(term)))
        if not html:
            return {"translation": "", "definition": ""}

        soup         = BeautifulSoup(html, "html.parser")
        translations = []
        for a in soup.select("a[href*='index.php?q=']"):
            href = a.get("href", "")
            if "l=1" in href and "r=0" in href:
                text = a.get_text(strip=True)
                if text.lower() == term.lower():
                    detail = self._fetch_detail(term)
                    if detail:
                        translations.insert(0, detail)
                else:
                    translations.append(text)

        return {"translation": " | ".join(translations[:5]), "definition": ""}

    def _fetch_detail(self, term: str) -> str:
        html = self._get(SUPER55_DETAIL_URL.format(requests.utils.quote(term)))
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        for b in soup.find_all("b"):
            text = b.get_text(strip=True)
            if text and text.lower() != term.lower() and len(text) > 1:
                return text
        return ""


# ── MAIN ENRICHER ─────────────────────────────────────────────────────────────

class MedicalTermEnricher:
    """
    Three-tier lookup — CSV first, cache second, super55 last resort.
    Only processes Hungarian/Latin medical terms.
    """

    def __init__(
        self,
        kb_path:          str   = KB_PATH,
        db_path:          str   = CACHE_DB_PATH,
        request_delay:    float = REQUEST_DELAY,
        max_live_lookups: int   = 15,
    ):
        print("[Enricher] Loading CSV dictionary...")
        self.csv_dict = CSVDictionary(kb_path)
        self.cache    = TermCache(db_path)
        self.fetcher  = Super55Fetcher(delay=request_delay)
        self.max_live = max_live_lookups

    def build_rag_context(self, transcript: str) -> str:
        print("[Enricher] Extracting medical terms from transcript...")
        candidates = extract_medical_candidates(transcript)
        candidates = [c for c in candidates if _is_hungarian_medical(c)]
        print(f"[Enricher] {len(candidates)} Hungarian/medical candidates after filtering.")

        enriched     = []
        live_fetches = 0
        csv_hits     = 0
        cache_hits   = 0

        for term in candidates:

            # Tier 1: CSV dictionary
            csv_result = self.csv_dict.lookup(term)
            if csv_result:
                enriched.append((term, csv_result["definition"], csv_result["source"]))
                csv_hits += 1
                continue

            # Tier 2: SQLite cache
            cached = self.cache.get(term)
            if cached is not None:
                if cached["translation"]:
                    enriched.append((term, cached["translation"], "cache"))
                    cache_hits += 1
                continue   # empty = previously confirmed no result

            # Tier 3: super55 live
            if live_fetches >= self.max_live:
                continue
            print(f"  [super55] {term}")
            result = self.fetcher.search(term)
            self.cache.set(term, result["translation"], result["definition"])
            live_fetches += 1
            if result["translation"]:
                enriched.append((term, result["translation"], "super55"))

        print(
            f"[Enricher] Resolved {len(enriched)} terms  "
            f"({csv_hits} CSV / {cache_hits} cache / {live_fetches} live)"
        )
        stats = self.cache.stats()
        print(f"[Enricher] Cache: {stats['cached_terms']} terms, {stats['cached_abbreviations']} abbrevs\n")
        return self._format_context(enriched)

    def expand_abbreviations(self, text: str) -> str:
        found        = {}
        live_fetches = 0

        for match in KNOWN_ABBREV_PATTERN.finditer(text):
            abbrev = match.group(0).upper()
            if abbrev in found:
                continue

            csv_result = self.csv_dict.lookup(abbrev)
            if csv_result:
                found[abbrev] = csv_result["definition"]
                continue

            expansion = self.cache.get_abbrev(abbrev)
            if expansion:
                found[abbrev] = expansion
                continue

            if live_fetches < 5:
                print(f"  [abbrev] {abbrev}")
                result = self.fetcher.search(abbrev)
                if result["translation"]:
                    self.cache.set_abbrev(abbrev, result["translation"])
                    found[abbrev] = result["translation"]
                else:
                    self.cache.set_abbrev(abbrev, "")
                live_fetches += 1

        if not found:
            return text

        footnote  = "\n\n--- Roviditesek / Abbreviations ---\n"
        footnote += "\n".join(f"  {k}: {v}" for k, v in sorted(found.items()))
        return text + footnote

    def lookup(self, term: str) -> Optional[str]:
        csv_result = self.csv_dict.lookup(term)
        if csv_result:
            return csv_result["definition"]
        cached = self.cache.get(term)
        if cached and cached["translation"]:
            return cached["translation"]
        result = self.fetcher.search(term)
        self.cache.set(term, result["translation"], result["definition"])
        return result["translation"] or None

    def _format_context(self, enriched: list) -> str:
        if not enriched:
            return ""
        lines = ["Orvosi kifejezesek / Medical term reference:"]
        for term, definition, source in enriched:
            lines.append(f"  * {term}: {definition}")
        return "\n".join(lines)