# Deprecated

import requests
from bs4 import BeautifulSoup
import csv
import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "https://www.pharmindex-online.hu/adattarak/orvosi-kifejezesek"
TOTAL_PAGES = 589
OUTPUT_FILE = "orvosi_kifejezesek.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_page(page_num):
    url = BASE_URL if page_num == 1 else f"{BASE_URL}?p={page_num}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text

def parse_entries(html):
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    for row in soup.find_all("div", class_="datastore-result"):
        term_div = row.find("div", class_="col-sm-3")
        desc_div = row.find("div", class_="col-sm-9")
        if term_div and desc_div:
            term = term_div.get_text(strip=True)
            description = desc_div.get_text(separator=" ", strip=True)
            if term:
                entries.append({"term": term, "description": description})

    return entries

def main():
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
        writer = csv.DictWriter(f, fieldnames=["term", "description"])
        writer.writeheader()
        writer.writerows(all_entries)

    print(f"\nDone! {len(all_entries)} entries saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
