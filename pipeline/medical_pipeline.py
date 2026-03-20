"""
Medical Consultation Transcription & Summarization Pipeline
------------------------------------------------------------
Uses:
  - Gladia API for transcription + diarization
  - Groq (Llama 3.3 70B) via OpenAI API for summarization
  - ChromaDB + HuggingFace Embeddings for RAG
  - Super55 cache for medical term enrichment & abbreviation expansion

Requirements:
    pip install openai requests langchain langchain-community langchain-huggingface chromadb sentence-transformers beautifulsoup4

Usage:
    python medical_pipeline.py --audio ../data/test_audio/test_audio.mp3
    python medical_pipeline.py --transcript ../data/test_transcripts/test_transcript_en.txt
    python medical_pipeline.py --transcript ... --no-rag
    python medical_pipeline.py --transcript ... --no-enrich   # skip super55 enrichment
"""

import sys
import csv
import requests
import argparse
import json
import os
import time
import mimetypes
from openai import OpenAI

# RAG Imports
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

try:
    # langchain >= 0.2
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    # langchain < 0.2 fallback
    from langchain.text_splitter import RecursiveCharacterTextSplitter

# ── Medical Term Enrichment (super55 cache + abbreviation expansion) ──────────
from medical_term_enrichment import MedicalTermEnricher

# ── CONFIG ────────────────────────────────────────────────────────────────────

KB_PATH     = "../data/knowledge_base"
CHROMA_PATH = "../data/chroma_db"
RAG_LIMIT    = None   # set via --rag-limit; None = load everything
CSV_WHITELIST = [     # filenames to include in RAG; empty list = load all
    "webbeteg_fogalomtar.csv",
]

# Enricher is a singleton — initialised once, reused across all steps
_enricher: MedicalTermEnricher | None = None

def get_enricher() -> MedicalTermEnricher:
    global _enricher
    if _enricher is None:
        _enricher = MedicalTermEnricher(
            db_path="../data/super55_cache.db",
            request_delay=2.5,
            max_live_lookups=20,   # max live fetches per pipeline run
        )
    return _enricher

# ── PROMPT TEMPLATES ──────────────────────────────────────────────────────────

SUMMARY_PROMPT_TEMPLATE = """You are a clinical documentation assistant.
Given the following doctor-patient consultation transcript, generate a concise medical summary.
Skip pleasantries and small talk, and focus on the medically relevant information.
Keep it in the original language of the transcript.

{context_block}

Include:
- Chief complaint
- Key symptoms mentioned
- Relevant medical history (if mentioned)
- Diagnosis or working diagnosis (if mentioned)
- Treatment plan or next steps (if mentioned)

Flag any parts you are uncertain about with '[UNCERTAIN]'.

Transcript:
{transcript}

Summary:"""


SOAP_PROMPT_TEMPLATE = """You are a clinical documentation assistant.
Given the following doctor-patient consultation transcript, generate SOAP notes.
Focus on extracting the Subjective, Objective, Assessment, and Plan sections.
Keep it in the original language of the transcript.

{context_block}

Transcript:
{transcript}

SOAP Notes:"""

# ── KNOWLEDGE BASE (RAG) ──────────────────────────────────────────────────────

def load_csv_documents(kb_path: str, limit: int = None, only: list = None) -> list:
    """
    Walk kb_path for *.csv files and convert each row into a LangChain Document.

    Supported CSV layouts (auto-detected by column names):
      1. term + definition   e.g. orvosi_kifejezesek.csv
      2. term + translation  e.g. webbeteg_fogalomtar.csv, super55 exports
      3. Generic             all columns joined as "col: value" pairs

    Each Document carries metadata: {"source": filename, "row": row_index}
    """
    docs = []

    for root, _, files in os.walk(kb_path):
        for fname in files:
            if not fname.lower().endswith(".csv"):
                continue

            fpath = os.path.join(root, fname)
            if only and fname not in only:
                print(f"[RAG] Skipping CSV: {fname} (not in whitelist)")
                continue
            print(f"[RAG] Loading CSV: {fname}")
            row_count = 0

            with open(fpath, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames or []
                cols = [c.lower().strip() for c in fieldnames]

                has_term        = "term" in cols
                has_definition  = "definition" in cols
                has_translation = "translation" in cols

                for i, row in enumerate(reader):
                    if limit and row_count >= limit:
                        break
                    if has_term and has_definition:
                        term = row.get("term", "").strip()
                        defn = row.get("definition", "").strip()
                        if not term:
                            continue
                        text = f"term: {term}\ndefinition: {defn}"

                    elif has_term and has_translation:
                        term        = row.get("term", "").strip()
                        translation = row.get("translation", "").strip()
                        if not term:
                            continue
                        text = f"term: {term}\ntranslation: {translation}"

                    else:
                        parts = [f"{col}: {val.strip()}" for col, val in row.items() if val and val.strip()]
                        if not parts:
                            continue
                        text = "\n".join(parts)

                    docs.append(Document(
                        page_content=text,
                        metadata={"source": fname, "row": i}
                    ))
                    row_count += 1

            print(f"[RAG]   -> {row_count} rows loaded from {fname}")

    return docs


def setup_knowledge_base(rag_limit: int = None):
    """
    Loads .txt AND .csv documents from KB_PATH, chunks them, and builds a
    local ChromaDB vector store. Returns the vectorstore, or None if nothing found.

    Supported files in KB_PATH (and subdirectories):
      *.txt  plain text reference documents
      *.csv  term/definition or term/translation tables (auto-detected)
             e.g. orvosi_kifejezesek.csv, webbeteg_fogalomtar.csv
    """
    print(f"[RAG] Loading knowledge base from {KB_PATH}...")

    if not os.path.exists(KB_PATH):
        os.makedirs(KB_PATH)
        print(f"[RAG] Created {KB_PATH} — add .txt / .csv reference files there.")
        return None

    # Load .txt files
    txt_loader = DirectoryLoader(KB_PATH, glob="**/*.txt", loader_cls=TextLoader)
    txt_docs   = txt_loader.load()
    if txt_docs:
        print(f"[RAG] Loaded {len(txt_docs)} .txt file(s)")

    # Load .csv files
    global RAG_LIMIT
    if rag_limit is not None:
        RAG_LIMIT = rag_limit
    csv_docs = load_csv_documents(KB_PATH, limit=RAG_LIMIT, only=CSV_WHITELIST)

    if not txt_docs and not csv_docs:
        print("[RAG] No documents found in knowledge base — RAG disabled.")
        return None

    embedding_fn = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    # .txt files: chunk normally then embed
    txt_splits = []
    if txt_docs:
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        txt_splits = text_splitter.split_documents(txt_docs)

    # CSV rows are already tiny (one term+definition per doc) — skip chunking,
    # embed in batches of 500 to avoid memory/timeout issues with 30k+ rows
    BATCH_SIZE = 500

    print(f"[RAG] Embedding {len(txt_splits)} txt chunks + {len(csv_docs)} CSV rows...")

    # Seed the vectorstore with txt chunks first (or first CSV batch if no txt)
    first_batch = txt_splits if txt_splits else csv_docs[:BATCH_SIZE]
    remaining   = csv_docs   if txt_splits else csv_docs[BATCH_SIZE:]

    vectorstore = Chroma.from_documents(
        documents=first_batch,
        embedding=embedding_fn,
        persist_directory=CHROMA_PATH
    )

    # Add CSV rows in batches
    csv_start = 0 if txt_splits else BATCH_SIZE
    total_csv = len(csv_docs)
    for i in range(csv_start, total_csv, BATCH_SIZE):
        batch = csv_docs[i : i + BATCH_SIZE]
        vectorstore.add_documents(batch)
        print(f"[RAG]   CSV batch {i // BATCH_SIZE + 1}/{(total_csv // BATCH_SIZE) + 1} done", end="\r")

    print()  # newline after batch progress
    print(
        f"[RAG] Ready — {len(txt_splits)} txt chunks + {total_csv} CSV rows indexed.\n"
    )
    return vectorstore


def get_relevant_context(query: str, vectorstore) -> str:
    if vectorstore is None:
        return ""
    results = vectorstore.similarity_search(query, k=3)
    if not results:
        return ""
    return "\n\n".join([doc.page_content for doc in results])


def build_context_block(rag_context: str, enrich_context: str) -> str:
    """
    Merges ChromaDB RAG context and super55 term enrichment context
    into a single prompt-ready block.
    """
    parts = []

    if rag_context:
        parts.append(f"Relevant medical reference information:\n{rag_context}")

    if enrich_context:
        parts.append(enrich_context)   # already formatted by MedicalTermEnricher

    return "\n\n".join(parts) + "\n" if parts else ""

# ── TRANSCRIPTION ─────────────────────────────────────────────────────────────

def transcribe_audio(audio_path: str, gladia_token: str) -> str:
    """Transcribe audio with diarization using Gladia API."""
    print("── Step 1/4: Transcription ──")
    print(f"Transcribing: {audio_path}")

    if not os.path.exists(audio_path):
        print(f"Error: File {audio_path} not found.")
        sys.exit(1)

    headers = {"x-gladia-key": gladia_token}

    mime_type, _ = mimetypes.guess_type(audio_path)
    mime_type = mime_type or "audio/mpeg"

    with open(audio_path, "rb") as f:
        upload_response = requests.post(
            "https://api.gladia.io/v2/upload",
            headers=headers,
            files={"audio": (os.path.basename(audio_path), f, mime_type)},
        )

    if upload_response.status_code not in (200, 201):
        print(f"Upload failed: {upload_response.status_code} - {upload_response.text}")
        sys.exit(1)

    audio_url = upload_response.json()["audio_url"]

    transcribe_response = requests.post(
        "https://api.gladia.io/v2/transcription/",
        headers=headers,
        json={
            "audio_url": audio_url,
            "diarization": True,
            "diarization_config": {
                "number_of_speakers": 2,
                "min_speakers": 1,
                "max_speakers": 3,
            },
        },
    )

    if transcribe_response.status_code not in (200, 201):
        print(f"Transcription request failed: {transcribe_response.status_code} - {transcribe_response.text}")
        sys.exit(1)

    result_url = transcribe_response.json()["result_url"]
    print("Waiting for Gladia to process audio...")

    while True:
        poll = requests.get(result_url, headers=headers)
        result = poll.json()
        status = result.get("status")
        if status == "done":
            break
        elif status == "error":
            print(f"Transcription error: {result}")
            sys.exit(1)
        time.sleep(3)

    utterances = result["result"]["transcription"].get("utterances", [])

    if utterances:
        lines = [f"SPEAKER_{utt['speaker']}: {utt['text'].strip()}" for utt in utterances]
        transcript = "\n".join(lines)
        confidences = [utt.get("confidence") for utt in utterances if utt.get("confidence")]
        if confidences:
            avg = sum(confidences) / len(confidences)
            print(f"Average transcription confidence: {avg * 100:.1f}%")
    else:
        transcript = result["result"]["transcription"]["full_transcript"]
        print("Warning: no diarization data, using plain transcript.")

    print(f"Transcription complete ({len(transcript)} characters)\n")
    return transcript


def load_transcript(transcript_path: str) -> str:
    print("── Step 1/4: Load Transcript ──")
    print(f"Loading from: {transcript_path}")
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read()
    print(f"Loaded ({len(transcript)} characters)\n")
    return transcript

# ── ENRICHMENT ────────────────────────────────────────────────────────────────

def enrich_transcript(transcript: str) -> str:
    """
    Step 2: Extract medical terms from the transcript, look up unknowns
    on super55 (cache-first), and return a formatted context block.
    """
    print("── Step 2/4: Medical Term Enrichment ──")
    enricher = get_enricher()
    context = enricher.build_rag_context(transcript)
    if context:
        print(f"[Enricher] Built context ({len(context)} chars)\n")
    else:
        print("[Enricher] No enrichment context generated.\n")
    return context

# ── SUMMARIZATION ─────────────────────────────────────────────────────────────

def summarize_transcript(
    transcript: str,
    groq_token: str,
    rag_context: str = "",
    enrich_context: str = ""
) -> str:
    print("── Step 3/4: Summary ──")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_token)

    context_block = build_context_block(rag_context, enrich_context)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        transcript=transcript,
        context_block=context_block
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.3
    )

    summary = response.choices[0].message.content.strip()

    # Post-process: expand any abbreviations the LLM used
    enricher = get_enricher()
    summary = enricher.expand_abbreviations(summary)

    print("Summary complete.\n")
    return summary


def summarize_soap_notes(
    transcript: str,
    groq_token: str,
    rag_context: str = "",
    enrich_context: str = ""
) -> str:
    print("── Step 4/4: SOAP Notes ──")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_token)

    context_block = build_context_block(rag_context, enrich_context)
    prompt = SOAP_PROMPT_TEMPLATE.format(
        transcript=transcript,
        context_block=context_block
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.3
    )

    soap_notes = response.choices[0].message.content.strip()

    # Post-process: expand any abbreviations the LLM used
    enricher = get_enricher()
    soap_notes = enricher.expand_abbreviations(soap_notes)

    print("SOAP notes complete.\n")
    return soap_notes

# ── OUTPUT ────────────────────────────────────────────────────────────────────

def save_output(
    transcript: str,
    summary: str,
    soap_notes: str,
    enrich_context: str = "",
    output_path: str = "../output.json"
):
    output = {
        "transcript":      transcript,
        "summary":         summary,
        "soap_notes":      soap_notes,
        "term_enrichment": enrich_context,   # save what was injected for debugging
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Output saved to: {output_path}")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Medical consultation transcription & summarization pipeline."
    )
    parser.add_argument("--audio",      type=str, default="../data/test_audio/test_audio.mp3")
    parser.add_argument("--transcript", type=str, default=None,
                        help="Path to existing transcript — skips transcription")
    parser.add_argument("--output",     type=str, default="../output.json")
    parser.add_argument("--no-rag",     action="store_true", help="Disable ChromaDB RAG")
    parser.add_argument("--no-enrich",  action="store_true", help="Disable super55 term enrichment")
    parser.add_argument("--rag-limit",   type=int, default=None,
                        help="Cap CSV rows per file for RAG (e.g. 500 for quick testing)")

    args = parser.parse_args()

    # Load API tokens
    with open("../.api_token.json", "r") as f:
        api_tokens  = json.load(f)
        groq_token  = api_tokens.get("groq-token")
        gladia_token = api_tokens.get("gladia-token")

    if not groq_token or groq_token == "your-groq-api-token":
        print("Groq API token missing.")
        sys.exit(1)
    if not gladia_token or gladia_token == "your-gladia-api-token":
        print("Gladia API token missing.")
        sys.exit(1)

    # ── Step 1: Transcript ────────────────────────────────────────────────────
    if args.transcript:
        transcript = load_transcript(args.transcript)
    else:
        transcript = transcribe_audio(args.audio, gladia_token=gladia_token)

    # ── Step 2: Enrichment (super55 cache) ────────────────────────────────────
    enrich_context = ""
    if not args.no_enrich:
        enrich_context = enrich_transcript(transcript)
    else:
        print("[Enricher] Skipped (--no-enrich)\n")

    # ── Step 3: ChromaDB RAG ──────────────────────────────────────────────────
    rag_context = ""
    if not args.no_rag:
        vectorstore = setup_knowledge_base(rag_limit=args.rag_limit)
        rag_context = get_relevant_context(transcript, vectorstore)
        if rag_context:
            print(f"[RAG] Retrieved {len(rag_context)} chars of context.\n")
        else:
            print("[RAG] No relevant context found.\n")
    else:
        print("[RAG] Skipped (--no-rag)\n")

    # ── Step 4: Summary ───────────────────────────────────────────────────────
    summary = summarize_transcript(
        transcript, groq_token,
        rag_context=rag_context,
        enrich_context=enrich_context
    )

    # ── Step 5: SOAP Notes ────────────────────────────────────────────────────
    soap_notes = summarize_soap_notes(
        transcript, groq_token,
        rag_context=rag_context,
        enrich_context=enrich_context
    )

    # ── Step 6: Save & Print ──────────────────────────────────────────────────
    save_output(transcript, summary, soap_notes, enrich_context, output_path=args.output)

    print("=" * 60)
    print("\nTRANSCRIPT:")
    print(transcript)
    print("\nSUMMARY:")
    print(summary)
    print("=" * 60)
    print("\nSOAP NOTES:")
    print(soap_notes)
    print("=" * 60)


if __name__ == "__main__":
    main()