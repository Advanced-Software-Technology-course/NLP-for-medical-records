"""
Medical Consultation Transcription & Summarization Pipeline
------------------------------------------------------------
Uses:
  - Gladia API for transcription + diarization
  - Groq (Llama 3.3 70B) via OpenAI API for summarization
    - ChromaDB + HuggingFace Embeddings for RAG

Requirements:
    pip install openai requests langchain langchain-community langchain-huggingface chromadb sentence-transformers

Usage:
    python medical_pipeline.py --audio ../data/test_audio/test_audio.mp3
    python medical_pipeline.py --transcript ../data/test_transcripts/test_transcript_en.txt
    python medical_pipeline.py --transcript ... --no-rag
    python medical_pipeline.py --transcript ... --rebuild-rag  # force rebuild of ChromaDB vectorstore
    python medical_pipeline.py --transcript ...  # auto-downloads precompiled Chroma on first run if missing
    python medical_pipeline.py --transcript ... --use-precompiled-rag  # download/load precompiled Chroma index instead of rebuilding
"""

import sys
import requests
import argparse
import json
import os
import time
import mimetypes
import importlib.util
import re
from openai import OpenAI

from rag_pipeline import (
    setup_knowledge_base,
    load_existing_vectorstore,
    get_relevant_context,
    build_context_block,
    suggest_icd_codes_local,
)

# ── CONFIG ────────────────────────────────────────────────────────────────────

KB_PATH     = "../data/knowledge_base"
ICD_CODES_PATH = "../data/icd10_codes.txt"
CHROMA_PATH = "../data/chroma_db"
RAG_LIMIT    = None   # set via --rag-limit; None = load everything
CSV_WHITELIST = [     # filenames to include in RAG; empty list = load all
    "clinical_lab_facts.csv",
    "DDI_data_clean.csv",
]


def _download_precompiled_rag(force_download: bool = False):
    """Download/extract a precompiled Chroma index via data/download_pre_compiled_rag.py."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    chroma_dir_abs = os.path.abspath(os.path.join(script_dir, CHROMA_PATH))

    if os.path.exists(chroma_dir_abs) and os.listdir(chroma_dir_abs) and not force_download:
        print(f"[RAG] Existing precompiled index found at {chroma_dir_abs}. Skipping download.")
        return
    print("-" * 50)
    print("\n")
    print("[RAG]! ALERT ! THIS WILL TAKE A WHILE (at most 10 mins). ONLY HAPPENS ON FIRST RUN OR IF --rebuild-rag IS USED.")
    print("This isn't a problem in production env since you'd build the index ahead of time, but for local testing it means the script will appear to hang for a while during the download/extract step. Please be patient and wait for the completion message before running any other steps or interrupting.")
    print("\n")
    print("-" * 50)
    downloader_path = os.path.abspath(
        os.path.join(script_dir, "..", "data", "download_pre_compiled_rag.py")
    )
    if not os.path.exists(downloader_path):
        raise FileNotFoundError(f"Precompiled RAG downloader not found: {downloader_path}")

    spec = importlib.util.spec_from_file_location("download_pre_compiled_rag", downloader_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load precompiled RAG downloader module.")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "download_index"):
        raise AttributeError("download_pre_compiled_rag.py does not define download_index().")

    print("[RAG] Downloading precompiled Chroma index...")
    module.download_index()
    print("[RAG] Precompiled index download/extract complete.")


def _chroma_dir_missing_or_empty() -> bool:
    """Return True when the configured Chroma directory does not exist or is empty."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    chroma_dir_abs = os.path.abspath(os.path.join(script_dir, CHROMA_PATH))
    return not (os.path.exists(chroma_dir_abs) and os.listdir(chroma_dir_abs))

# ── PROMPT TEMPLATES ──────────────────────────────────────────────────────────

SUMMARY_PROMPT_TEMPLATE = """You are a clinical documentation assistant.
Given the following doctor-patient consultation transcript, generate a concise medical summary.
Skip pleasantries and small talk, and focus on the medically relevant information.
Output language must be strictly: {output_language}.
Do not mix languages.
Do not add parenthetical translations like "X (Y)" unless that parenthetical translation already exists in the transcript.
Always include physical examination results in Key Symptoms.

Retrieved context from medical knowledge base (if any):
{context_block}

Include:
- Chief complaint
- Key symptoms mentioned
- Relevant medical history (if mentioned)
- Diagnosis or working diagnosis (if mentioned)
- Treatment plan or next steps (if mentioned)

Flag any parts you are uncertain about with '[UNCERTAIN]'. Use it liberally for anything that is not explicitly stated or is ambiguous in the transcript.

Transcript:
{transcript}

Example format of summary (but adapt to content, and keep it concise):
'''
**Chief Complaint:** The patient presents with complaints of headache/migraine, abdominal pain, and fatigue/weakness.

**Key Symptoms:**
- Headache: intermittent, intense, mostly in the temples and behind the eyes, worsened by bright light, more frequent in the afternoon and evening.
- Abdominal pain: crampy, mid and lower abdomen, worsened after eating, especially fatty foods and coffee.
- Fatigue/weakness: persistent, waking up tired, poor sleep quality.
- Nausea: occasional, no vomiting, described as an unsettled feeling in the stomach.

**Relevant Medical History:**
- Known medical condition: hypothyroidism, managed with Euthyrox 75 micrograms.
- Last thyroid level check: approximately last spring.
- Family history: mother had migraines.

**Diagnosis or Working Diagnosis:**
- Migraine: suggested by unilateral temple pain, light sensitivity, nausea, and family history.
- [UNCERTAIN] Irritable bowel syndrome or functional dyspepsia: probable causes for abdominal pain, related to high coffee intake and stress.
- [UNCERTAIN] Thyroid dysfunction: potential contributor to fatigue and headaches, given the lack of recent thyroid level checks.

**Treatment Plan or Next Steps:**
- Laboratory tests: full panel including TSH, full blood count, liver and kidney function, iron, and ferritin.
- Lifestyle modifications: reduce coffee intake to one or two cups a day, short walks after meals.
- Medication: Ibuprofen for headaches, with consideration for migraine-specific treatment if headaches continue.
- Follow-up: scheduled for two weeks to review lab results and assess symptom progression.
'''

Summary:"""


SOAP_PROMPT_TEMPLATE = """You are a clinical documentation assistant.
Given the following doctor-patient consultation transcript, generate SOAP notes.
Focus on extracting the Subjective, Objective, Assessment, and Plan sections.
Output language must be strictly: {output_language}.
Do not mix languages.
Do not add parenthetical translations like "X (Y)" unless that parenthetical translation already exists in the transcript.

Retrieved context from medical knowledge base (if any):
{context_block}

Transcript:
{transcript}

Example format of SOAP notes (but adapt to content):
'''
**S (Subjective):**
The patient reports feeling off for a while, with symptoms worsening over the past week. They complain of a headache that has been present for about two weeks, described as intense and located on the temples and behind the eyes, worsening in the afternoon and evening. The patient also experiences sensitivity to light, but not noise, and has had a few episodes of nausea without vomiting. Additionally, they report abdominal pain, mostly in the middle and lower abdomen, which worsens after eating, especially fatty foods and coffee. The patient also complains of fatigue, waking up tired, and having difficulty sleeping, averaging about 5 hours of sleep per night. They attribute their fatigue to stress, work overtime, and their husband's recent illness. The patient has a family history of migraines, takes Euthyrox for thyroid issues, and has not had their thyroid levels checked since last spring.

**O (Objective):**
On examination, the abdomen is tender in the central and right lower quadrant. The patient's blood pressure is slightly elevated at 145/90. The physical examination does not reveal any acutely concerning findings.

**A (Assessment):**
The patient's symptoms are consistent with migraines, given the unilateral temple pain, light sensitivity, nausea, and family history. The abdominal pain is likely related to high coffee intake and stress, possibly indicating irritable bowel syndrome or functional dyspepsia. The fatigue and sleep disturbance could be stress-related, but the patient's thyroid levels should be checked, as they have not been evaluated since last spring.

**P (Plan):**
The plan includes ordering a full panel of blood tests, including TSH, full blood count, liver and kidney function, iron, and ferritin. The patient is advised to reduce coffee intake to one or two cups a day and take short walks after meals. Ibuprofen is recommended for headache management, with the possibility of migraine-specific treatment if symptoms persist. The patient is scheduled to return in two weeks with lab results for further evaluation and management.
'''

SOAP Notes:"""


def _detect_transcript_language(transcript: str) -> str:
    """Return a coarse language code for prompt control ("hu" or "en")."""
    low = (transcript or "").lower()
    if not low:
        return "en"

    hu_markers = {
        "hogy", "vagy", "nem", "van", "volt", "mert", "beteg", "orvos", "fajdalom", "fájdalom",
        "laz", "láz", "kohoges", "köhög", "hanyinger", "hányinger", "legszomj", "légszomj",
    }
    accent_hits = sum(low.count(ch) for ch in "áéíóöőúüű")
    tokens = re.findall(r"[a-zA-Z\u00C0-\u017F]{2,}", low)
    hu_hits = sum(1 for t in tokens if t in hu_markers)

    if accent_hits >= 2 or hu_hits >= 2:
        return "hu"
    return "en"


def _prompt_language_name(transcript: str) -> str:
    return "Hungarian" if _detect_transcript_language(transcript) == "hu" else "English"


# ── TRANSCRIPTION ─────────────────────────────────────────────────────────────

def transcribe_audio(audio_path: str, gladia_token: str):
    """Transcribe audio with diarization using Gladia API.

    Returns:
      transcript: str
      sentence_confidences: list[dict]
      transcription_confidence_avg: float | None
    """
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
    sentence_confidences = []
    transcription_confidence_avg = None

    if utterances:
        lines = []
        for i, utt in enumerate(utterances):
            text = (utt.get("text") or "").strip()
            if not text:
                continue

            speaker = utt.get("speaker")
            conf = utt.get("confidence")
            try:
                conf = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf = None

            lines.append(f"SPEAKER_{speaker}: {text}")
            sentence_confidences.append(
                {
                    "sentence_index": i,
                    "speaker": speaker,
                    "text": text,
                    "confidence": conf,
                    "confidence_percent": round(conf * 100, 1) if conf is not None else None,
                    "start": utt.get("start"),
                    "end": utt.get("end"),
                }
            )

        transcript = "\n".join(lines)

        confidences = [s["confidence"] for s in sentence_confidences if s["confidence"] is not None]
        if confidences:
            transcription_confidence_avg = sum(confidences) / len(confidences)
            print(f"Average transcription confidence: {transcription_confidence_avg * 100:.1f}%")
    else:
        transcript = result["result"]["transcription"]["full_transcript"]
        print("Warning: no diarization data, using plain transcript.")

    print(f"Transcription complete ({len(transcript)} characters)\n")
    return transcript, sentence_confidences, transcription_confidence_avg

def load_transcript(transcript_path: str) -> str:
    print("── Step 1/4: Load Transcript ──")
    print(f"Loading from: {transcript_path}")
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read()
    print(f"Loaded ({len(transcript)} characters)\n")
    return transcript

# ── SUMMARIZATION ─────────────────────────────────────────────────────────────

def summarize_transcript(
    transcript: str,
    groq_token: str,
    rag_context: str = "",
    suggested_codes: list | None = None,
) -> str:
    print("── Step 3/4: Summary ──")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_token)
    output_language = _prompt_language_name(transcript)

    context_block = build_context_block(rag_context, "", suggested_codes=suggested_codes)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        transcript=transcript,
        context_block=context_block,
        output_language=output_language,
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900,
        temperature=0.2
    )

    summary = response.choices[0].message.content.strip()

    print("Summary complete.\n")
    return summary


def summarize_soap_notes(
    transcript: str,
    groq_token: str,
    rag_context: str = "",
    suggested_codes: list | None = None,
) -> str:
    print("── Step 4/4: SOAP Notes ──")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_token)
    output_language = _prompt_language_name(transcript)

    context_block = build_context_block(rag_context, "", suggested_codes=suggested_codes)
    prompt = SOAP_PROMPT_TEMPLATE.format(
        transcript=transcript,
        context_block=context_block,
        output_language=output_language,
    )

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900,
        temperature=0.2
    )

    soap_notes = response.choices[0].message.content.strip()

    print("SOAP notes complete.\n")
    return soap_notes

# ── OUTPUT ────────────────────────────────────────────────────────────────────

def save_output(
    transcript: str,
    summary: str,
    soap_notes: str,
    output_path: str = "../output.json",
    sentence_confidences: list | None = None,
    transcription_confidence_avg: float | None = None,
):
    output = {
        "transcript": transcript,
        "summary": summary,
        "soap_notes": soap_notes,
        "transcription_confidence_avg": transcription_confidence_avg,
        "transcription_confidence_avg_percent": (
            round(transcription_confidence_avg * 100, 1)
            if transcription_confidence_avg is not None
            else None
        ),
        "sentence_confidences": sentence_confidences or [],
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
    parser.add_argument("--rag-limit",   type=int, default=None,
                        help="Cap CSV rows per file for RAG (e.g. 500 for quick testing)")
    parser.add_argument("--rebuild-rag", action="store_true", help="Force rebuild Chroma index even if manifest matches")
    parser.add_argument(
        "--use-precompiled-rag",
        action="store_true",
        help="Download/load precompiled Chroma index instead of local rebuild/indexing",
    )
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

    run_time_start = time.time()
    print(f"Pipeline started at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(run_time_start))}\n")

    # ── Step 1: Transcript ────────────────────────────────────────────────────
    sentence_confidences = []
    transcription_confidence_avg = None

    if args.transcript:
        transcript = load_transcript(args.transcript)
    else:
        transcript, sentence_confidences, transcription_confidence_avg = transcribe_audio(
            args.audio, gladia_token=gladia_token
        )
    # ── Step 2: ChromaDB RAG ──────────────────────────────────────────────────
    suggested_codes = suggest_icd_codes_local(transcript, icd_path=ICD_CODES_PATH, top_k=3)
    if suggested_codes:
        print("[ICD] Local lookup suggested codes:")
        for item in suggested_codes:
            print(
                f"[ICD]   {item['code']}: {item['description']} "
                f"(matched symptom: {item['matched_symptom']}, score={item['score']})"
            )
        print()
    else:
        print("[ICD] No local suggested ICD codes found.\n")

    rag_context = ""
    if not args.no_rag:
        if args.use_precompiled_rag:
            try:
                _download_precompiled_rag(force_download=args.rebuild_rag)
                vectorstore = load_existing_vectorstore(chroma_path=CHROMA_PATH)
                if vectorstore is None:
                    print("[RAG] Failed to load precompiled index. Exiting.")
                    sys.exit(1)
            except Exception as ex:
                print(f"[RAG] Precompiled mode failed: {ex}")
                sys.exit(1)
        else:
            vectorstore = None

            # First-run behavior: if Chroma is missing, try downloading the precompiled
            # index before falling back to expensive local reindexing.
            if not args.rebuild_rag and _chroma_dir_missing_or_empty():
                print("[RAG] No local Chroma index found. Attempting precompiled download...")
                try:
                    _download_precompiled_rag(force_download=False)
                    vectorstore = load_existing_vectorstore(chroma_path=CHROMA_PATH)
                    if vectorstore is None:
                        print("[RAG] Precompiled download completed but index could not be loaded. Falling back to local rebuild.")
                except Exception as ex:
                    print(f"[RAG] Precompiled download failed: {ex}. Falling back to local rebuild.")

            if vectorstore is None:
                vectorstore = setup_knowledge_base(
                    rag_limit=args.rag_limit,
                    force_rebuild=args.rebuild_rag,
                    csv_whitelist=CSV_WHITELIST,
                    kb_path=KB_PATH,
                    chroma_path=CHROMA_PATH,
                )

        rag_context = get_relevant_context(transcript, vectorstore, final_k=5, retrieve_k=12, max_queries=8)
        if rag_context:
            print(f"[RAG] Retrieved {len(rag_context)} chars of context.\n")
        else:
            print("[RAG] No relevant context found.\n")
    else:
        print("[RAG] Skipped (--no-rag)\n")

    # ── Step 3: Summary ───────────────────────────────────────────────────────
    summary = summarize_transcript(
        transcript, groq_token,
        rag_context=rag_context,
        suggested_codes=suggested_codes,
    )

    # ── Step 4: SOAP Notes ────────────────────────────────────────────────────
    soap_notes = summarize_soap_notes(
        transcript, groq_token,
        rag_context=rag_context,
        suggested_codes=suggested_codes,
    )

    # ── Step 5: Save & Print ──────────────────────────────────────────────────
    save_output(
        transcript=transcript,
        summary=summary,
        soap_notes=soap_notes,
        output_path=args.output,
        sentence_confidences=sentence_confidences,
        transcription_confidence_avg=transcription_confidence_avg
    )

    print("=" * 60)
    print("\nTRANSCRIPT:")
    print(transcript)
    print("\nSUMMARY:")
    print(summary)
    print("=" * 60)
    print("\nSOAP NOTES:")
    print(soap_notes)
    print("=" * 60)

    run_time_end = time.time()
    duration = run_time_end - run_time_start
    print(f"\nPipeline completed at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(run_time_end))}")
    print(f"\nDuration: {duration:.1f} seconds.")

if __name__ == "__main__":
    main()