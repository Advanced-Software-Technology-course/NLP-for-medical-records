"""
Medical Consultation Transcription & Summarization Pipeline
------------------------------------------------------------
Uses:
  - Gladia API for transcription
  - Groq (Llama 3.3 70B) via OpenAI API for summarization

Requirements:
    - Python 3.8+
    - openai Python package (`pip install openai`)
    - A Groq API token (visit https://www.groq.com/ to get started)
    - A Gladia API token (visit https://gladia.io/ to get started)

Usage:
    # From audio file:
    python medical_pipeline.py --audio ../data/test_audio/test_audio.mp3

    # From existing transcript text file:
    python medical_pipeline.py --transcript ../data/test_transcripts/test_transcript_en.txt

"""


import sys
import requests
import argparse
import json
import os
import time
import mimetypes
from openai import OpenAI
#from datasets import load_dataset

# ── CONFIG ────────────────────────────────────────────────────────────────────

SUMMARY_PROMPT_TEMPLATE = """You are a clinical documentation assistant. 
Given the following doctor-patient consultation transcript, generate a concise medical summary. Skip pleasantries and small talk, and focus on the medically relevant information. Keep it in the original language of the transcript.

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
Given the following doctor-patient consultation transcript, generate SOAP notes. Focus on extracting the Subjective, Objective, Assessment, and Plan sections based on the information provided in the transcript. Keep it in the original language of the transcript.
Transcript:
{transcript}
SOAP Notes:"""


# ── TRANSCRIPTION ─────────────────────────────────────────────────────────────

def transcribe_audio(audio_path: str, gladia_token: str) -> str:
    """
    Transcribe audio with diarization using Gladia API.
    Returns a formatted transcript with speaker labels, e.g.:
      "SPEAKER_0: How long have you had this pain?\nSPEAKER_1: About three days."
    """
    print(f"[1/2] Transcribing via Gladia: {audio_path}")

    if not os.path.exists(audio_path):
        print(f"Error: File {audio_path} not found.")
        sys.exit(1)

    headers = {"x-gladia-key": gladia_token}

    # ── Step 1: Upload the audio file ────────────────────────────────────────
    mime_type, _ = mimetypes.guess_type(audio_path)
    mime_type = mime_type or "audio/mpeg"  # fallback

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

    # ── Step 2: Request transcription + diarization ───────────────────────────
    transcribe_response = requests.post(
        "https://api.gladia.io/v2/transcription/",
        headers=headers,
        json={
            "audio_url": audio_url,
            "diarization": True,            # speaker labels ON
            "diarization_config": {
                "number_of_speakers": 2,    # adjust if more speakers expected
                "min_speakers": 1,
                "max_speakers": 3,
            },
        },
    )

    if transcribe_response.status_code not in (200, 201):
        print(f"Transcription request failed: {transcribe_response.status_code} - {transcribe_response.text}")
        sys.exit(1)

    result_url = transcribe_response.json()["result_url"]

    # ── Step 3: Poll until done ───────────────────────────────────────────────
    print("[1/2] Waiting for transcription...")
    while True:
        poll = requests.get(result_url, headers=headers)
        result = poll.json()
        status = result.get("status")

        if status == "done":
            break
        elif status == "error":
            print(f"Transcription error: {result}")
            sys.exit(1)

        time.sleep(3)  # wait 3s between polls, Gladia is async

    # ── Step 4: Format output with speaker labels ─────────────────────────────
    utterances = result["result"]["transcription"].get("utterances", [])

    sentence_confidences = []
    if utterances:
        # diarization succeeded — format as "SPEAKER_X: text"
        lines = []
        for utt in utterances:
            speaker = f"SPEAKER_{utt['speaker']}"
            lines.append(f"{speaker}: {utt['text'].strip()}")
            conf = utt.get("confidence", None)
            sentence_confidences.append({
                "confidence": conf,
                "confidence_percent": round(conf * 100) if conf is not None else None,
                "start": utt.get("start"),
                "end": utt.get("end"),
            })
        transcript = "\n".join(lines)
    else:
        # fallback — no diarization data, return plain transcript
        transcript = result["result"]["transcription"]["full_transcript"]
        print("[1/2] Warning: no diarization data returned, using plain transcript.")

    avg_confidence = (
        sum(s["confidence"] for s in sentence_confidences if s["confidence"] is not None)
        / len(sentence_confidences)
        if sentence_confidences else 0.0
    )

    print(f"[2/2] Transcription complete ({len(transcript)} characters)\n")
    return transcript, sentence_confidences, avg_confidence

def load_transcript(transcript_path: str) -> str:
    """Load an existing transcript from a text file."""
    print(f"[1/2] Loading transcript from: {transcript_path}")
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = f.read()
    print(f"[2/2] Transcript loaded ({len(transcript)} characters)\n")
    return transcript

# ── SUMMARIZATION ─────────────────────────────────────────────────────────────

def summarize_transcript(transcript: str, groq_token: str = None) -> str:

    print("[1/2] Connecting to Groq...")

    client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=groq_token
)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)}],
        max_tokens=512,
        temperature=0.3
    )

    summary = response.choices[0].message.content.strip()
    print("[2/2] Summary received.\n")
    return summary

def summarize_soap_notes(transcript: str, groq_token: str = None) -> str:
    """Summarize transcript into SOAP notes format."""

    print("[1/2] Connecting to Groq for SOAP notes...")
    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=groq_token
    )
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": SOAP_PROMPT_TEMPLATE.format(transcript=transcript)}],
        max_tokens=512,
        temperature=0.3
    )
    soap_notes = response.choices[0].message.content.strip()
    print("[2/2] SOAP notes received.\n")
    return soap_notes

# ── OUTPUT ────────────────────────────────────────────────────────────────────

def save_output(transcript: str, summary: str, soap_notes: str, output_path: str = "output.json"):
    """Save transcript and summary to a JSON file."""
    output = {
        "transcript": transcript,
        "summary": summary,
        "soap_notes": soap_notes
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Output saved to: {output_path}")

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Medical consultation transcription & summarization pipeline.")

    parser.add_argument("--audio", type=str, default="../data/test_audio/test_audio.mp3",
                        help="Path to audio file (default: ../data/test_audio/test_audio.mp3)")
    parser.add_argument("--transcript", type=str, default=None,
                        help="Path to existing transcript (.txt) — skips transcription if provided")
    parser.add_argument("--output", type=str, default="../output.json",
                        help="Output file path (default: ../output.json)")

    args = parser.parse_args()
    #read JSON file for API token
    with open("../.api_token.json", "r") as f:
        api_tokens = json.load(f)
        groq_token = api_tokens.get("groq-token")
        if not groq_token or groq_token == "your-groq-api-token":
            print("Groq API token not found in api_token.json. Please add it under 'groq-token'. To start off, visit the Groq website to get your API token: https://www.groq.com/")
            sys.exit(1)
        gladia_token = api_tokens.get("gladia-token")
        if not gladia_token or gladia_token == "your-gladia-api-token":
            print("Gladia API token not found in api_token.json. Please add it under 'gladia-token'. To start off, visit the Gladia website to get your API token: https://gladia.io/")
            sys.exit(1)

    # Step 1: Get transcript
    if args.audio:
        transcript = transcribe_audio(args.audio, gladia_token=gladia_token)
    else:
        transcript = load_transcript(args.transcript)

    # Step 2: Summarize
    summary = summarize_transcript(transcript, groq_token=groq_token)

    # Step 3: Generate SOAP notes
    soap_notes = summarize_soap_notes(transcript, groq_token=groq_token)
    
    # Step 4: Save and print
    save_output(transcript, summary, soap_notes, output_path=args.output)

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