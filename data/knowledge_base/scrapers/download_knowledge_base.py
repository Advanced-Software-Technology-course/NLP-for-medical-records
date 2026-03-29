# scripts/download_knowledge_base.py
"""
Knowledge Base Downloader
--------------------------
Downloads and saves reference data for the medical RAG pipeline:
  1. ICD-10-CM codes
  2. Drug information + interactions (OpenFDA + DDIs)
  3. Lab reference ranges (LOINC)
  5. English medical abbreviations
  6. Hungarian medical glossary (webbeteg.hu scrape)

Usage:
    python download_knowledge_base.py [--only icd drugs labs guidelines abbrev hu]
"""

import argparse
import csv
import io
import os
import subprocess
import sys
import time
import re
from urllib.parse import quote_plus
import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KB_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))  # .../data/knowledge_base
os.makedirs(KB_DIR, exist_ok=True)

def kb(filename: str) -> str:
    return os.path.join(KB_DIR, filename)


# ─────────────────────────────────────────────────────────────────────────────
# 1. ICD-10 CODES
# ─────────────────────────────────────────────────────────────────────────────

def download_icd10():
    print("\n── ICD-10 codes ──────────────────────────────────────────────────")
    url = "https://raw.githubusercontent.com/Bobrovskiy/ICD-10-CSV/master/2019/diagnosis.csv"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    df = pd.read_csv(io.StringIO(response.text))
    out = kb("icd10_codes.txt")

    with open(out, "w", encoding="utf-8") as f:
        f.write("# ICD-10-CM Codes\n")
        f.write("# Source: CMS.gov via Bobrovskiy/ICD-10-CSV (GitHub)\n\n")
        for _, row in df.iterrows():
            f.write(f"{row['CodeWithSeparator']}: {row['LongDescription']}\n")

    print(f"{len(df)} ICD-10 codes saved → {out}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. DRUG INFORMATION + INTERACTIONS  (OpenFDA)
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_fda_labels(drug: str, limit: int = 20) -> list[dict]:
    """
    Pull multiple likely-matching labels for a drug using targeted OpenFDA fields.
    """
    q = (
        f'(openfda.generic_name:"{drug}" OR '
        f'openfda.brand_name:"{drug}" OR '
        f'openfda.substance_name:"{drug}")'
    )
    url = f"https://api.fda.gov/drug/label.json?search={quote_plus(q)}&limit={limit}"
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return r.json().get("results", [])
    except Exception:
        pass
    return []


def _clean(text_list, max_chars=None) -> str:
    if not text_list:
        return ""
    
    # Deduplicate at sentence level before joining
    seen = set()
    unique_sentences = []
    for block in text_list:
        for sent in re.split(r'(?<=[.!?])\s+', block.replace("\n", " ")):
            s = sent.strip()
            if not s:
                continue
            key = re.sub(r'\s+', ' ', s.lower())
            if key not in seen:
                seen.add(key)
                unique_sentences.append(s)
    
    text = " ".join(unique_sentences)
    if max_chars is None:
        return text
    return text[:max_chars] + ("..." if len(text) > max_chars else "")

def _discover_drugs_from_openfda(limit: int = 1500, min_count: int = 20) -> list[str]:
    """
    Build drug universe dynamically from OpenFDA frequency counts.
    """
    url = f"https://api.fda.gov/drug/label.json?count=openfda.generic_name.exact&limit={limit}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    items = r.json().get("results", [])

    drugs = []
    for row in items:
        term = (row.get("term") or "").strip().lower()
        count = int(row.get("count", 0))
        if not term or count < min_count:
            continue
        # split combined generic names
        for part in re.split(r"[;,/|+]", term):
            p = part.strip()
            if p and len(p) >= 3:
                drugs.append(p)

    # unique stable
    seen = set()
    out = []
    for d in drugs:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def download_drugs():
    print("\n-- Drug information  ----")
    out_labels = kb("drugs.txt")

    drugs = _discover_drugs_from_openfda(limit=2000, min_count=30)
    print(f"  Discovered {len(drugs)} drug names from OpenFDA")

    with open(out_labels, "w", encoding="utf-8") as f:
        f.write("# Drug Information\n# Source: OpenFDA drug label API\n\n")
        for drug in drugs:
            labels = _fetch_fda_labels(drug, limit=10)
            f.write(f"=== {drug.upper()} ===\n")
            f.write(f"Matched labels: {len(labels)}\n")
            if not labels:
                f.write("No matching label data found.\n\n")
                continue

            sections = {
                "Purpose": [],
                "Indications": [],
                "Dosage": [],
                "Warnings": [],
                "Contraindications": [],
                "Interactions (label)": [],
            }
            for d in labels:
                sections["Purpose"].extend(d.get("purpose", []))
                sections["Indications"].extend(d.get("indications_and_usage", []))
                sections["Dosage"].extend(d.get("dosage_and_administration", []))
                sections["Warnings"].extend(d.get("warnings", []))
                sections["Contraindications"].extend(d.get("contraindications", []))
                sections["Interactions (label)"].extend(d.get("drug_interactions", []))

            for k, v in sections.items():
                txt = _clean(v)
                if txt:
                    f.write(f"{k}: {txt}\n")
            f.write("\n")
            time.sleep(0.1)

    print(f"\nDrugs written -> {out_labels}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. LAB REFERENCE RANGES
# ─────────────────────────────────────────────────────────────────────────────

LOINC_DATA_PATH = os.path.join(SCRIPT_DIR + "/..", "Loinc.csv")  # You need to download this separately from https://loinc.org/downloads/

def download_lab_ranges():
    df = pd.read_csv(LOINC_DATA_PATH, dtype=str)
    
    # Tighter class filter — drop rare research panels
    valid_classes = ['CHEM', 'HEM', 'COAG', 'UA']  # drop TOX, SERO unless needed
    
    # Additional: only keep quantitative results (not ordinal/nominal)
    # SCALE_TYP = Qn means quantitative — these have meaningful reference ranges
    mask = (
        (df['CLASSTYPE'] == "1") &
        (df['CLASS'].isin(valid_classes)) &
        (df['EXAMPLE_UNITS'].notna()) &
        (df['SCALE_TYP'] == 'Qn') &          # quantitative only
        (df['STATUS'] == 'ACTIVE') &           # drop retired codes
        (df['ORDER_OBS'].isin(['Order', 'Observation', 'Both']))  # exclude panels/headers
    )
    
    lab_df = df[mask].copy()
    
    # Deduplicate: same component+system often has multiple LOINC codes
    # Keep the one with the most complete data
    lab_df['_completeness'] = (
        lab_df['DefinitionDescription'].notna().astype(int) +
        lab_df['EXAMPLE_UNITS'].notna().astype(int)
    )
    lab_df = (
        lab_df
        .sort_values('_completeness', ascending=False)
        .drop_duplicates(subset=['COMPONENT', 'SYSTEM'])
        .drop(columns=['_completeness'])
    )
    
    def create_fact(row):
        name = row['COMPONENT']
        units = row['EXAMPLE_UNITS']
        system = row['SYSTEM']
        desc = row['DefinitionDescription'] if pd.notna(row.get('DefinitionDescription', float('nan'))) else ""
        return f"Test: {name} | System: {system} | Units: {units} | Info: {desc[:100]}"
    
    lab_df['reference_fact'] = lab_df.apply(create_fact, axis=1)
    
    out_csv = kb("clinical_lab_facts.csv")
    lab_df[["LOINC_NUM", "LONG_COMMON_NAME", "reference_fact"]].to_csv(out_csv, index=False)
    print(f"Filtered {len(df)} → {len(lab_df)} lab rows (deduped by component+system)")

# ─────────────────────────────────────────────────────────────────────────────
# 4. ENGLISH MEDICAL ABBREVIATIONS
# ─────────────────────────────────────────────────────────────────────────────

def download_abbreviations():
    print("\n── Medical abbreviations ────────────────────────────────────────")
    url = "https://raw.githubusercontent.com/lisavirginia/clinical-abbreviations/master/metainventory/Metainventory_Version1.0.0.csv"
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()

        raw = response.text

        # This source can contain malformed rows and varying delimiters.
        parse_attempts = [
            {"sep": ","},
            {"sep": ";"},
            {"sep": "\t"},
            {"sep": "|"},
        ]

        def _norm_col(col: str) -> str:
            return re.sub(r"[^a-z0-9]", "", str(col).lower())

        df = None
        sf_col = None
        lf_col = None

        for attempt in parse_attempts:
            try:
                candidate = pd.read_csv(
                    io.StringIO(raw),
                    engine="python",
                    on_bad_lines="skip",
                    dtype=str,
                    **attempt,
                )
            except Exception:
                continue

            if candidate.empty:
                continue

            col_map = {_norm_col(c): c for c in candidate.columns}
            sf_col = col_map.get("sf") or col_map.get("abbreviation") or col_map.get("abbr")
            lf_col = (
                col_map.get("lf")
                or col_map.get("longform")
                or col_map.get("fullname")
                or col_map.get("meaning")
                or col_map.get("definition")
            )

            if sf_col and lf_col:
                df = candidate
                break

        if df is None or not sf_col or not lf_col:
            raise ValueError("Could not find abbreviation/definition columns in source CSV")

        df_clean = (
            df[[sf_col, lf_col]]
            .dropna()
            .rename(columns={sf_col: "SF", lf_col: "LF"})
        )
        df_clean["SF"] = df_clean["SF"].astype(str).str.strip()
        df_clean["LF"] = df_clean["LF"].astype(str).str.strip()
        df_clean = df_clean[(df_clean["SF"] != "") & (df_clean["LF"] != "")]
        df_clean = df_clean.drop_duplicates(subset="SF")

        out = kb("abbreviations_en.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write("# English Medical Abbreviations\n")
            f.write("# Source: Medical Abbreviation Meta-Inventory (Apache 2.0)\n\n")
            for _, row in df_clean.iterrows():
                f.write(f"{row['SF']} - {row['LF']}\n")

        print(f"{len(df_clean)} abbreviations saved → {out}")
    except Exception as e:
        print(f"Failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. HUNGARIAN MEDICAL GLOSSARY (webbeteg.hu)
# ─────────────────────────────────────────────────────────────────────────────

BASE_URL = "https://www.webbeteg.hu/keresok/fogalomtar/oldal/{}"
TOTAL_PAGES = 143
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _get_page(page_num: int) -> str:
    resp = requests.get(BASE_URL.format(page_num), headers=HEADERS, timeout=10)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


def _parse_entries(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for row in soup.select("table tr"):
        cols = row.find_all("td")
        if len(cols) == 2:
            term = cols[0].get_text(strip=True)
            definition = cols[1].get_text(strip=True)
            if term:
                entries.append({"term": term, "definition": definition})
    return entries


def download_hungarian_glossary():
    print("\n── Hungarian medical glossary (webbeteg.hu) ─────────────────────")
    all_entries = []
    out = kb("webbeteg_fogalomtar.csv")

    for page in range(1, TOTAL_PAGES + 1):
        print(f"  Scraping page {page}/{TOTAL_PAGES}…", end="\r")
        try:
            html = _get_page(page)
            entries = _parse_entries(html)
            all_entries.extend(entries)
        except Exception as e:
            print(f"\n  ✗ Error on page {page}: {e}")
        time.sleep(0.5)

    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["term", "definition"])
        writer.writeheader()
        writer.writerows(all_entries)

    print(f"\n{len(all_entries)} entries saved → {out}")



# HIGH priority — keep always
HIGH_PRIORITY = {
    "risk or severity of bleeding",
    "risk or severity of adverse effects", 
    "risk or severity of toxicity",
    "risk or severity of hypoglycemia",
    "risk or severity of hypotension",
    "risk or severity of serotonin syndrome",
    "risk or severity of qt prolongation",
    "anticoagulant activities",        # always clinically significant
    "hypoglycemic activities",
    "cardiotoxic activities",
    "neurotoxic activities",
    "nephrotoxic activities",
    "hepatotoxic activities",

}

# LOW priority — drop these
LOW_PRIORITY = {
    "serum concentration",             # pharmacokinetic, not directly dangerous
    "metabolism",
    "excretion",
    "absorption",
    "protein binding",
}
# Clean DDI data
def _ddi_priority(interaction_type: str) -> str:
    t = re.sub(r'\s+', ' ', interaction_type.lower().strip())
    

    #assign high priority for HIGH_PRIORITY keywords
    for hp in HIGH_PRIORITY:
        if hp in t:
            return "high"
    
    #assign low priority for LOW_PRIORITY keywords
    for lp in LOW_PRIORITY:
        if lp in t:
            return "low"

    return "medium"  # keep by default if unclear

def clean_ddi_csv(input_path: str, output_path: str):
    df = pd.read_csv(input_path, dtype=str)

    # Normalize text
    df['drug1_name'] = df['drug1_name'].str.strip().str.lower()
    df['drug2_name'] = df['drug2_name'].str.strip().str.lower()
    df['interaction_type'] = df['interaction_type'].str.strip().str.lower()

    # Drop unusable rows
    df = df.dropna(subset=['drug1_name', 'drug2_name', 'interaction_type'])
    df = df[df['drug1_name'] != df['drug2_name']]
    df = df[df['drug1_name'].str.len() >= 3]
    df = df[df['drug2_name'].str.len() >= 3]

    before = len(df)

    # Score priority before any dedup
    df['_priority'] = df['interaction_type'].apply(_ddi_priority)
    df['_rank'] = df['_priority'].map({"high": 0, "medium": 1, "low": 2})

    # Drop low priority rows entirely
    df = df[df['_priority'] != 'low']

    # Canonical pair ordering (A,B) == (B,A)
    df['_a'] = df[['drug1_name', 'drug2_name']].min(axis=1)
    df['_b'] = df[['drug1_name', 'drug2_name']].max(axis=1)

    # Per pair keep only the highest-priority interaction, then clean up
    df = (
        df.sort_values('_rank')
          .drop_duplicates(subset=['_a', '_b'])
    )
    df['drug1_name'] = df['_a']
    df['drug2_name'] = df['_b']
    df = df.drop(columns=['_a', '_b', '_priority', '_rank'])

    after = len(df)
    print(f"DDI: {before} → {after} rows after priority filter + dedup")
    print(df['interaction_type'].value_counts().head(20))

    df.to_csv(output_path, index=False)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

STEPS = {
    #"icd":        ("ICD-10 codes",           download_icd10),
    #"drugs":      ("Drug info",download_drugs),
    #"labs":       ("Lab reference ranges",    download_lab_ranges),
    #"abbrev":     ("Medical abbreviations",   download_abbreviations),
    #"hu":         ("Hungarian glossary",      download_hungarian_glossary),
    "ddi_clean":  ("Clean DDI CSV",           lambda: clean_ddi_csv(kb("DDI_data.csv"), kb("DDI_data_clean.csv"))),
}


def main():
    parser = argparse.ArgumentParser(description="Download medical knowledge base for RAG.")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=list(STEPS.keys()),
        metavar="STEP",
        help=f"Run only these steps: {', '.join(STEPS.keys())} (default: all)",
    )
    args = parser.parse_args()

    selected = args.only if args.only else list(STEPS.keys())

    print(f"Knowledge base directory: {KB_DIR}")
    print(f"Steps to run: {', '.join(selected)}\n")

    for key in selected:
        label, fn = STEPS[key]
        print(f"{'─'*60}")
        print(f"{label}")
        try:
            fn()
        except Exception as e:
            print(f"FAILED: {e}")

    print(f"\n{'='*60}")
    print("Knowledge base download complete.")
    print(f"  Files saved to: {KB_DIR}")


if __name__ == "__main__":
    main()