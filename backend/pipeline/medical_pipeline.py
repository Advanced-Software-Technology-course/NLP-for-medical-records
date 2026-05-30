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
"""

import sys
import requests
import argparse
import json
import os
import time
import mimetypes
from openai import OpenAI
from collections.abc import Sequence

from pipeline.rag_pipeline import (   
    setup_knowledge_base,
    get_relevant_context,
    build_context_block,
)

# ── CONFIG ────────────────────────────────────────────────────────────────────

KB_PATH     = "../data/knowledge_base"
CHROMA_PATH = "../data/chroma_db"
CUSTOM_VOCABULARY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "custom_vocabulary.json"))
RAG_LIMIT    = None   # set via --rag-limit; None = load everything
CSV_WHITELIST = [     # filenames to include in RAG; empty list = load all
    "webbeteg_fogalomtar.csv",
]

GROQ_PRIMARY_MODEL = "llama-3.3-70b-versatile"
GROQ_FALLBACK_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b",
    "llama-3.1-8b-instant",
]


def _is_rate_limit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code == 429 or getattr(response, "status_code", None) == 429:
        return True

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            error_code = str(error.get("code", "")).lower()
            error_type = str(error.get("type", "")).lower()
            error_message = str(error.get("message", "")).lower()
            if error_code in {"rate_limit_exceeded", "429"}:
                return True
            if error_type in {"rate_limit", "tokens", "quota", "insufficient_quota"}:
                return True
            if "rate limit" in error_message or "too many requests" in error_message:
                return True

    message = str(exc).lower()
    return (
        "rate limit" in message
        or "rate_limit" in message
        or "429" in message
        or "too many requests" in message
        or "tokens per day" in message
        or "tokens per minute" in message
        or "requests per minute" in message
        or "rate_limit_exceeded" in message
        or "insufficient_quota" in message
    )


def _chat_completion_with_fallback(
    client: OpenAI,
    messages: Sequence[dict],
    *,
    max_tokens: int,
    temperature: float,
    primary_model: str = GROQ_PRIMARY_MODEL,
    fallback_models: list[str] | None = None,
):
    models = [primary_model]
    if fallback_models:
        for model in fallback_models:
            if model and model not in models:
                models.append(model)

    last_error: Exception | None = None

    for model in models:
        try:
            print(f"[Groq] Trying model: {model}")
            return client.chat.completions.create(
                model=model,
                messages=list(messages),
                max_tokens=max_tokens,
                temperature=temperature,
            ), model
        except Exception as exc:
            last_error = exc
            if _is_rate_limit_error(exc):
                print(f"[Groq] Rate limit on {model}; trying fallback model. Details: {exc}")
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("No Groq model candidates were available.")


def _load_custom_vocabulary_config() -> dict:
    if not os.path.exists(CUSTOM_VOCABULARY_PATH):
        return {}

    try:
        with open(CUSTOM_VOCABULARY_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}

# ── PROMPT TEMPLATES ──────────────────────────────────────────────────────────

SUMMARY_PROMPT_TEMPLATE = """You are a clinical documentation assistant.
Given the following doctor-patient consultation transcript, generate a concise medical summary.
Skip pleasantries and small talk, and focus on the medically relevant information.
Keep it in the original language of the transcript.

Prioritize fidelity to the transcript over completeness. If a fact is not explicitly stated, omit it rather than guessing.

{context_block}

Include:
- Chief complaint
- Key symptoms mentioned
- Relevant medical history (if mentioned)
- Diagnosis or working diagnosis (if mentioned)
- Treatment plan or next steps (if mentioned)

Preserve exact qualifiers and negations in exam findings. Do not collapse wording like "not palpable" or "present via Doppler" into a generic absence or normal finding.

Flag any parts you are uncertain about with '[UNCERTAIN]'. Use it only where the transcript is genuinely ambiguous, incomplete, or contradictory. Do not attach '[UNCERTAIN]' to facts that are explicitly stated.

Transcript:
{transcript}

Summary:"""

EVALUATOR_PROMPT_TEMPLATE = """You are a clinical documentation auditor.
Compare the candidate summary to the transcript and list only factual mismatches or missing critical facts.
Use the transcript as the single source of truth.
If there are no issues, respond with exactly: NO_ISSUES

Transcript:
{transcript}

Candidate summary:
{summary}

Return format:
- One short bullet per issue
- Each bullet: "Issue: ... | Fix: ..."
"""

REFINER_PROMPT_TEMPLATE = """You are a clinical documentation editor.
Revise the candidate summary using the transcript and the issue list.
Rules:
- Use the transcript as the single source of truth.
- Fix only the issues listed.
- Do not add new facts.
- Preserve exact qualifiers and negations (e.g., "not palpable", "present via Doppler").
- Keep section headers and overall structure.
- Keep [UNCERTAIN] only where the transcript is genuinely ambiguous.

Transcript:
{transcript}

Issues:
{issues}

Candidate summary:
{summary}

Revised summary:
"""


SOAP_PROMPT_TEMPLATE = """You are a clinical documentation assistant.
Given the following doctor-patient consultation transcript, generate SOAP notes.
Focus on extracting the Subjective, Objective, Assessment, and Plan sections.
Keep it in the original language of the transcript.

{context_block}

Transcript:
{transcript}

SOAP Notes:"""


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

    request_payload = {
        "audio_url": audio_url,
        "diarization": True,
        "diarization_config": {
            "number_of_speakers": 2,
            "min_speakers": 1,
            "max_speakers": 3,
        },
    }
    request_payload.update(_load_custom_vocabulary_config())

    transcribe_response = requests.post(
        "https://api.gladia.io/v2/transcription/",
        headers=headers,
        json=request_payload,
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
    rag_context: str = ""
) -> str:
    print("── Step 3/4: Summary ──")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_token, max_retries=0)

    context_block = build_context_block(rag_context, "")
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        transcript=transcript,
        context_block=context_block
    )

    response, used_model = _chat_completion_with_fallback(
        client,
        [{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.3,
        fallback_models=GROQ_FALLBACK_MODELS,
    )
    print(f"[Groq] Summary model used: {used_model}")

    summary = response.choices[0].message.content.strip()

    print("── Step 3b/4: Summary Evaluation ──")
    eval_prompt = EVALUATOR_PROMPT_TEMPLATE.format(
        transcript=transcript,
        summary=summary,
    )
    eval_response, eval_model = _chat_completion_with_fallback(
        client,
        [{"role": "user", "content": eval_prompt}],
        max_tokens=400,
        temperature=0.0,
        primary_model=GROQ_FALLBACK_MODELS[0],
        fallback_models=GROQ_FALLBACK_MODELS[1:],
    )
    print(f"[Groq] Evaluation model used: {eval_model}")
    eval_text = eval_response.choices[0].message.content.strip()

    if "no_issues" in eval_text.casefold():
        print("Summary evaluation: no issues found.\n")
        print("Summary complete.\n")
        return summary

    print("── Step 3c/4: Summary Refinement ──")
    refine_prompt = REFINER_PROMPT_TEMPLATE.format(
        transcript=transcript,
        summary=summary,
        issues=eval_text,
    )
    refine_response, refine_model = _chat_completion_with_fallback(
        client,
        [{"role": "user", "content": refine_prompt}],
        max_tokens=700,
        temperature=0.0,
        primary_model=GROQ_FALLBACK_MODELS[0],
        fallback_models=GROQ_FALLBACK_MODELS[1:],
    )
    print(f"[Groq] Refinement model used: {refine_model}")
    refined_summary = refine_response.choices[0].message.content.strip()

    print("Summary complete.\n")
    return refined_summary


def summarize_soap_notes(
    transcript: str,
    groq_token: str,
    rag_context: str = ""
) -> str:
    print("── Step 4/4: SOAP Notes ──")
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_token, max_retries=0)

    context_block = build_context_block(rag_context, "")
    prompt = SOAP_PROMPT_TEMPLATE.format(
        transcript=transcript,
        context_block=context_block
    )

    response, used_model = _chat_completion_with_fallback(
        client,
        [{"role": "user", "content": prompt}],
        max_tokens=512,
        temperature=0.3,
        fallback_models=GROQ_FALLBACK_MODELS,
    )
    print(f"[Groq] SOAP model used: {used_model}")

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
    rag_context = ""
    if not args.no_rag:
        vectorstore = setup_knowledge_base(rag_limit=args.rag_limit, force_rebuild=args.rebuild_rag, csv_whitelist=CSV_WHITELIST, kb_path=KB_PATH, chroma_path=CHROMA_PATH)
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
        rag_context=rag_context
    )

    # ── Step 4: SOAP Notes ────────────────────────────────────────────────────
    soap_notes = summarize_soap_notes(
        transcript, groq_token,
        rag_context=rag_context
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