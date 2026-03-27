# scripts/download_knowledge_base.py
#download bs4:
import csv
import csv
import subprocess
import sys
import time
try:
    import bs4
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "beautifulsoup4"])


from bs4 import BeautifulSoup
import requests
import json
import os

print("Downloading ICD-10 CSV from GitHub...")
import pandas as pd, io

csv_url = "https://raw.githubusercontent.com/Bobrovskiy/ICD-10-CSV/master/2019/diagnosis.csv"
response = requests.get(csv_url)

df = pd.read_csv(io.StringIO(response.text))
# columns: Id, Code, CodeWithSeparator, ShortDescription, LongDescription

# Determine the absolute path to the data directory relative to this script
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, "../data/knowledge_base/icd10_codes.txt")

# Ensure the directory exists
os.makedirs(os.path.dirname(output_path), exist_ok=True)

with open(output_path, "w", encoding="utf-8") as f:
    f.write("# ICD-10-CM Codes\n")
    f.write("# Source: CMS.gov via Bobrovskiy/ICD-10-CSV (GitHub)\n\n")
    for _, row in df.iterrows():
        f.write(f"{row['CodeWithSeparator']}: {row['LongDescription']}\n")

print(f"Saved {len(df)} ICD-10 codes.")

# ── Drugs (from OpenFDA) ──────────────────────────────────────
# Fetch top common drugs, TBD with more complex queries if needed
print("Downloading drug information...")
common_drugs = [
    "amoxicillin", "ibuprofen", "metformin", "lisinopril",
    "atorvastatin", "omeprazole", "metoprolol", "amlodipine"
]

drugs_output_path = os.path.join(script_dir, "../data/knowledge_base/drugs.txt")
with open(drugs_output_path, "w", encoding="utf-8") as f:
    for drug in common_drugs:
        response = requests.get(
            f"https://api.fda.gov/drug/label.json?search={drug}&limit=1"
        )
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [{}])[0]
            purpose = results.get("purpose", [""])[0][:300]
            dosage = results.get("dosage_and_administration", [""])[0][:300]
            f.write(f"=== {drug.upper()} ===\n")
            f.write(f"Purpose: {purpose}\n")
            f.write(f"Dosage: {dosage}\n\n")

print("Drug info saved.")


print("Downloading English medical abbreviations (Meta-Inventory)...")

url = "https://raw.githubusercontent.com/lisavirginia/clinical-abbreviations/master/metainventory_2021/MetaInventory_2021.csv"
response = requests.get(url)

if response.status_code == 200:
    df = pd.read_csv(io.StringIO(response.text))
    # columns: SF (short form), LF (long form)
    # just take the most common sense per abbreviation
    df_clean = df.drop_duplicates(subset="SF")[["SF", "LF"]]

    abbreviations_output_path = os.path.join(script_dir, "../data/knowledge_base/abbreviations_en.txt")
    with open(abbreviations_output_path, "w", encoding="utf-8") as f:
        f.write("# English Medical Abbreviations\n")
        f.write("# Source: Medical Abbreviation and Acronym Meta-Inventory (Apache 2.0)\n\n")
        for _, row in df_clean.iterrows():
            f.write(f"{row['SF']} - {row['LF']}\n")

    print(f"Saved {len(df_clean)} English abbreviations.")
else:
    print(f"Failed to download: {response.status_code}")



sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "https://www.webbeteg.hu/keresok/fogalomtar/oldal/{}"
TOTAL_PAGES = 143
OUTPUT_FILE = "webbeteg_fogalomtar.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_page(page_num):
    resp = requests.get(BASE_URL.format(page_num), headers=HEADERS, timeout=10)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text

def parse_entries(html):
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    # Data is in a simple <table> - every <tr> has two <td>s: term and definition
    for row in soup.select("table tr"):
        cols = row.find_all("td")
        if len(cols) == 2:
            term = cols[0].get_text(strip=True)
            definition = cols[1].get_text(strip=True)
            if term:
                entries.append({"term": term, "definition": definition})

    return entries


all_entries = []

for page in range(1, TOTAL_PAGES + 1):
    print(f"Scraping page {page}/{TOTAL_PAGES}...")
    try:
        html = get_page(page)
        entries = parse_entries(html)
        all_entries.extend(entries)
        print(f"  -> {len(entries)} entries found")
    except Exception as e:
        print(f"  ERROR on page {page}: {e}")

    time.sleep(0.5)

with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["term", "definition"])
    writer.writeheader()
    writer.writerows(all_entries)

print(f"\nDone! {len(all_entries)} entries saved to {OUTPUT_FILE}")
