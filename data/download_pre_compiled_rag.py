
import os
import zipfile
import requests

RELEASE_URL = "https://github.com/saxovia/kb_for_medical_nlp/releases/download/DB/chroma_db.zip"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = SCRIPT_DIR

def download_index():
    zip_path = os.path.join(OUTPUT_DIR, "chroma_db.zip")
    print("Downloading pre-built index...")
    
    with requests.get(RELEASE_URL, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    print(f"  {downloaded/total*100:.1f}%", end="\r")
    
    print("\nExtracting...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(OUTPUT_DIR)
    os.remove(zip_path)
    print(f"Index ready at {OUTPUT_DIR}/chroma_db")

if __name__ == "__main__":
    download_index()