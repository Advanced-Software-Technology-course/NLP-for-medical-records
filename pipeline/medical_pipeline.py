"""
Medical Consultation Transcription & Summarization Pipeline
------------------------------------------------------------
Uses:
  - Gladia API for transcription + diarization (single request, rate-limit friendly)
  - Local post-processing: aggressive merging & confidence boosting for boundary fragments
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
    python medical_pipeline.py --audio ... --denoise  # enable noise reduction on audio before transcription
    python medical_pipeline.py --audio ... --transcription-only  # stop after transcription and merging
    python medical_pipeline.py --audio ... --chunked-transcription  # use overlapping chunks + merge post-processing
"""

from __future__ import annotations

import sys
import requests
import argparse
import json
import os
import time
import mimetypes
import importlib.util
import re
from functools import lru_cache
from typing import List, Optional
from openai import OpenAI
from pathlib import Path

RAG_IMPORT_ERROR = None
try:
    from rag_pipeline import (
        setup_knowledge_base,
        load_existing_vectorstore,
        get_relevant_context,
        suggest_icd_codes_local,
    )
except Exception as ex:
    setup_knowledge_base = None
    load_existing_vectorstore = None
    get_relevant_context = None
    suggest_icd_codes_local = None
    RAG_IMPORT_ERROR = ex

# ── CONFIG ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))

KB_PATH = os.path.join(PROJECT_ROOT, "data", "knowledge_base")
ICD_CODES_PATH = os.path.join(PROJECT_ROOT, "data", "icd10_codes.txt")
CHROMA_PATH = os.path.join(PROJECT_ROOT, "data", "chroma_db")
DEFAULT_AUDIO_PATH = os.path.join(PROJECT_ROOT, "data", "test_audio", "test_audio.mp3")
DEFAULT_OUTPUT_PATH = os.path.join(PROJECT_ROOT, "output.json")
UTTERANCE_WORDS_PATH = os.path.join(PROJECT_ROOT, "data", "utterance_words.txt")
RAG_LIMIT    = None   # set via --rag-limit; None = load everything
CSV_WHITELIST = [     # filenames to include in RAG; empty list = load all
    "clinical_lab_facts.csv",
    "DDI_data_clean.csv",
]
SCORE_CLAMP_FLOOR = 0.75  # confidence floor for exact phrase matches during export


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

SUMMARY_PROMPT_TEMPLATE = """You are an expert clinical documentation assistant.
Given the following doctor-patient consultation transcript, generate a medical summary.
Skip pleasantries and small talk, and focus on the medically relevant information, the 'why' behind medical decisions, and the distinction between subjective and objective data.
Output language must be strictly: {output_language}.
Do not mix languages.
Do not add parenthetical translations like "X (Y)" unless that parenthetical translation already exists in the transcript.
Always include physical examination results in Key Symptoms. If there isn't have a immediate action item mentioned, include the details anyway. Include lifestyle changes and states.
Always use the clinical variant of medical terms (e.g. "hypertension" instead of "high blood pressure", "dyspnea" instead of "shortness of breath", etc.) unless only the layman's term is used in the transcript and the clinical term is not mentioned at all.

Retrieved context from medical knowledge base (if any):
{context_block}

Include:
- Chief complaint: The primary reason for the visit.
- Key symptoms mentioned: A narrative summary of the current issue, including relevant 'pertinent negatives' (symptoms the patient denies, like fevers or chest pain).
- Relevant medical history (if mentioned): Past diagnoses and their current status/control.
- Physical Examination & Vitals: Include vitals (especially if abnormal) and objective findings (heart sounds, lung sounds, musculoskeletal tests, etc.).
- Diagnosis or working diagnosis (if mentioned): The working diagnosis and the evidence supporting it.
- Treatment plan or next steps (if mentioned): Medications (with dosages), lifestyle advice, and follow-up timeline. Match each action to a specific diagnosis.

Always flag any parts you are uncertain about with '[UNCERTAIN]', even if only a little bit. Use it liberally for anything that is not explicitly stated or is ambiguous in the transcript.

Transcript:
{transcript}

Example format of summary (but adapt to content, and keep it concise):
'''
**Chief Complaint:** Headache, abdominal pain, and fatigue.

**History of Present Illness:**
The patient reports intermittent, intense retro-orbital headaches exacerbated by bright light. These are accompanied by occasional nausea. Also notes crampy post-prandial abdominal pain.
- **Pertinent Negatives:** Denies vomiting, fever, or unintentional weight loss.

**Relevant Medical History:**
- Hypothyroidism: Managed with Euthyrox 75 mcg. Last labs >12 months ago.
- Family History: Maternal migraines.
- Social: High caffeine intake (5+ cups/day) and high work stress.

**Physical Examination & Vitals:**
- Vitals: [UNCERTAIN - check transcript for BP].
- Abdomen: Soft, non-distended, mild tenderness to palpation in the epigastric region. No guarding.
- Neuro: Normal gait, no cranial nerve deficits.
- Cardiovascular: [UNCERTAIN - mention if heart sounds were heard].

**Assessment & Rationale:**
1. Migraine: Suggested by unilateral location, photophobia, and family history.
2. Dyspepsia: Likely related to high caffeine and fatty food intake.
3. Fatigue: Etiology uncertain; consider poorly controlled hypothyroidism or iron deficiency.

**Treatment Plan & Next Steps:**
- Diagnostics: Order TSH, CBC, and Ferritin to investigate fatigue.
- Medication: Ibuprofen 400mg PRN for acute headache.
- Lifestyle: Reduce coffee to <2 cups/day; maintain a food and symptom diary.
- Follow-up: Return in 2 weeks for lab review.
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


def _normalize_phrase_text(text: str) -> str:
    """Normalize phrase text for matching against the export whitelist."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", (text or "").casefold())
    return re.sub(r"\s+", " ", cleaned).strip()


@lru_cache(maxsize=1)
def _load_utterance_phrase_whitelist() -> set[str]:
    """Load the phrase whitelist used to floor export confidence values."""
    path = Path(UTTERANCE_WORDS_PATH)
    if not path.exists():
        print(f"[Export] Whitelist file not found: {path}")
        return set()

    phrases = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            normalized = _normalize_phrase_text(line)
            if normalized:
                phrases.add(normalized)
    return phrases


def _apply_utterance_confidence_floor(
    sentence_confidences: list,
    floor: float = SCORE_CLAMP_FLOOR,
) -> list:
    """Floor confidence values for exact phrase matches when exporting."""
    whitelist = _load_utterance_phrase_whitelist()
    if not whitelist or not sentence_confidences:
        return sentence_confidences

    exported = []
    clamped_count = 0

    for seg in sentence_confidences:
        seg_copy = dict(seg)
        text = seg_copy.get("text", "")
        normalized_text = _normalize_phrase_text(text)

        if normalized_text in whitelist:
            conf = seg_copy.get("confidence")
            if conf is None or conf < floor:
                seg_copy["confidence"] = floor
                seg_copy["confidence_percent"] = round(floor * 100, 1)
                clamped_count += 1

        exported.append(seg_copy)

    if clamped_count:
        print(f"[Export] Applied {floor * 100:.0f}% confidence floor to {clamped_count} utterance phrase(s).")

    return exported


# ── TRANSCRIPTION ─────────────────────────────────────────────────────────────


def validate_audio_format(audio_path: str) -> str:
    """Check audio format; convert if needed. Returns path to valid audio."""
    valid_formats = {'.mp3', '.wav', '.m4a', '.flac', '.ogg'}
    path = Path(audio_path)
    
    if path.suffix.lower() not in valid_formats:
        print(f"⚠ Warning: {path.suffix} may not be supported by Gladia.")
        # Could auto-convert here using pydub if needed
    
    return str(path)


def _load_preprocess_dependencies():
    """Load optional audio preprocessing dependencies on demand."""
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
        import soundfile as sf  # type: ignore
        return librosa, np, sf
    except ModuleNotFoundError as ex:
        print(
            "[Preprocess] Optional dependency missing "
            f"({ex.name}). Install preprocessing extras or use --skip-preprocess."
        )
        return None

def check_audio_quality(audio_path: str) -> dict:
    """Analyze audio for potential issues."""
    deps = _load_preprocess_dependencies()
    if deps is None:
        return None
    librosa, np, _ = deps

    try:
        y, sr = librosa.load(audio_path, sr=None)
        
        # Calculate metrics
        duration = librosa.get_duration(y=y, sr=sr)
        rms_energy = np.sqrt(np.mean(y**2))
        peak_amplitude = np.max(np.abs(y))
        
        issues = []
        if duration < 5:
            issues.append("Audio too short (<5 sec)")
        if rms_energy < 0.01:
            issues.append("Audio is very quiet (low RMS energy)")
        if peak_amplitude > 0.95:
            issues.append("Audio may be clipped/distorted (peak near 1.0)")
        
        return {
            "duration_sec": round(duration, 2),
            "rms_energy": round(float(rms_energy), 4),
            "peak_amplitude": round(float(peak_amplitude), 4),
            "issues": issues
        }
    except Exception as e:
        print(f"⚠ Could not analyze audio: {e}")
        return None

def preprocess_audio(
    audio_path: str,
    output_path: str = None,
    target_sr: int = 16000,
    normalize: bool = True,
    reduce_noise: bool = True,
) -> str:
    """
    Preprocess audio: resample, normalize, optionally denoise.
    
    Returns:
        Path to preprocessed audio (original path if no changes needed)
    """
    print("── Pre-Audio Processing ──")

    deps = _load_preprocess_dependencies()
    if deps is None:
        print("[Preprocess] Skipping audio preprocessing due to missing dependencies.\n")
        return audio_path
    librosa, np, sf = deps
    
    # Load audio
    y, sr = librosa.load(audio_path, sr=None)
    modified = False
    
    # 1. Resample to target SR
    if sr != target_sr:
        print(f"Resampling: {sr}Hz → {target_sr}Hz")
        y = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
        sr = target_sr
        modified = True
    
    # 2. Normalize volume (peak normalization)
    if normalize:
        peak = np.max(np.abs(y))
        if peak > 0:
            print(f"Normalizing audio (peak {peak:.3f} → 0.95)")
            y = y / peak * 0.95  # Leave headroom
            modified = True
    
    # 3. Reduce noise (spectral gating - simple approach)
    if reduce_noise:
        # Simple noise gate: zero out very quiet frames
        frame_energy = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=1)
        threshold = np.median(frame_energy) * 0.1
        
        # Convert back to time domain
        S = librosa.stft(y)
        mag = np.abs(S)
        noise_gate = mag > threshold
        S_gated = S * noise_gate
        y_gated = librosa.istft(S_gated)
        
        # Only use if it helps
        if np.mean(np.abs(y_gated)) > np.mean(np.abs(y)) * 0.5:
            y = y_gated
            print("Applied noise gate")
            modified = True
    
    # Save if modified
    if modified:
        if output_path is None:
            output_path = audio_path.replace(Path(audio_path).suffix, "_processed.wav")
        
        sf.write(output_path, y, sr)
        print(f"Saved preprocessed audio to: {output_path}\n")
        return output_path
    
    print("No preprocessing needed\n")
    return audio_path


# ── AUDIO CHUNKING WITH OVERLAP ───────────────────────────────────────────────

def chunk_audio_with_overlap(
    audio_path: str,
    chunk_duration_sec: float = 30.0,
    overlap_duration_sec: float = 5.0,
    output_dir: str = None,
) -> list:
    """
    Split audio into overlapping chunks to preserve boundary context.
    
    Args:
        audio_path: Path to audio file
        chunk_duration_sec: Duration of each chunk in seconds (default 30s)
        overlap_duration_sec: Overlap between consecutive chunks in seconds (default 5s)
        output_dir: Directory to save chunks (default: temp folder)
    
    Returns:
        List of dicts: [{"path": str, "start": float, "end": float, "is_tail": bool}, ...]
        Each dict has the audio chunk path and its time boundaries in the original file.
    """
    deps = _load_preprocess_dependencies()
    if deps is None:
        print("[Chunking] Could not load librosa; returning single chunk.")
        return [{"path": audio_path, "start": 0.0, "end": None, "is_tail": True}]
    
    librosa, np, sf = deps
    
    # Load audio
    y, sr = librosa.load(audio_path, sr=None)
    duration = librosa.get_duration(y=y, sr=sr)
    
    if duration <= chunk_duration_sec:
        print(f"[Chunking] Audio shorter than chunk size ({duration:.1f}s ≤ {chunk_duration_sec}s). Using as single chunk.")
        return [{"path": audio_path, "start": 0.0, "end": duration, "is_tail": True}]
    
    # Setup output directory
    if output_dir is None:
        import tempfile
        output_dir = tempfile.gettempdir()
    
    os.makedirs(output_dir, exist_ok=True)
    base_name = Path(audio_path).stem
    
    # Calculate chunk boundaries
    chunks = []
    chunk_start = 0.0
    chunk_idx = 0
    
    while chunk_start < duration:
        chunk_end = min(chunk_start + chunk_duration_sec, duration)
        is_tail = chunk_end >= duration
        
        # Convert to samples
        start_sample = int(chunk_start * sr)
        end_sample = int(chunk_end * sr)
        
        # Extract audio chunk
        chunk_audio = y[start_sample:end_sample]
        
        # Save chunk
        chunk_path = os.path.join(output_dir, f"{base_name}_chunk_{chunk_idx:03d}.wav")
        sf.write(chunk_path, chunk_audio, sr)
        
        chunks.append({
            "path": chunk_path,
            "start": chunk_start,
            "end": chunk_end,
            "is_tail": is_tail,
            "chunk_idx": chunk_idx,
        })
        
        print(f"[Chunking] Chunk {chunk_idx}: {chunk_start:.1f}s - {chunk_end:.1f}s")
        
        # Move to next chunk (with overlap)
        chunk_start += chunk_duration_sec - overlap_duration_sec
        chunk_idx += 1
    
    print(f"[Chunking] Created {len(chunks)} overlapping chunks\n")
    return chunks


def _find_boundary_words(utterance_text: str) -> List[str]:
    """Extract last 1-2 words from utterance as boundary markers."""
    words = utterance_text.strip().split()
    return words[-2:] if len(words) > 1 else words


def _boost_boundary_confidence(
    utterance: dict,
    overlapping_utterances: List[dict],
    boost_factor: float = 1.15,
) -> dict:
    """
    Boost confidence for boundary words if they appear in overlapping chunks.
    
    If a word at the end of an utterance also appears at the start of the next
    overlapping chunk, we're more confident it's correct.
    """
    if utterance.get("confidence") is None:
        return utterance
    
    boundary_words = _find_boundary_words(utterance.get("text", ""))
    if not boundary_words:
        return utterance
    
    boundary_text = " ".join(boundary_words).lower()
    
    # Check if boundary appears in overlapping chunk
    for overlap_utt in overlapping_utterances:
        overlap_text = overlap_utt.get("text", "").lower()
        if boundary_text in overlap_text or any(w.lower() in overlap_text for w in boundary_words):
            # Confidence is higher if boundary verified in overlap
            old_conf = utterance["confidence"]
            new_conf = min(0.95, old_conf * boost_factor)
            utterance["confidence"] = new_conf
            utterance["confidence_percent"] = round(new_conf * 100, 1)
            utterance["boundary_verified"] = True
            print(f"  ✓ Boosted boundary word '{boundary_text}' confidence: {old_conf*100:.1f}% → {new_conf*100:.1f}%")
            break
    
    return utterance


def _deduplicate_overlapping_utterances(
    utterances: list,
    time_tolerance_sec: float = 0.5,
) -> list:
    """
    Remove duplicate utterances from overlapping chunk regions.
    When chunks overlap, the same utterance appears multiple times with potentially
    different confidence scores. Keep the version with higher confidence.
    
    Args:
        utterances: List of utterance dicts from multiple chunks
        time_tolerance_sec: Consider utterances as duplicates if they're within this time window
    
    Returns:
        Deduplicated list keeping highest-confidence versions
    """
    if not utterances:
        return utterances
    
    seen = {}  # Key: (speaker, text_normalized) -> (index, confidence, full_dict)
    
    for idx, utt in enumerate(utterances):
        speaker = utt.get("speaker")
        text = (utt.get("text") or "").strip()
        if not text:
            continue
        
        # Normalize text for comparison (lowercase, remove punctuation)
        text_norm = text.lower()
        key = (speaker, text_norm)
        
        conf = utt.get("confidence")
        if conf is None:
            conf = 0.0
        
        if key not in seen:
            seen[key] = (idx, conf, utt)
        else:
            prev_idx, prev_conf, prev_utt = seen[key]
            # Keep the version with higher confidence
            if conf > prev_conf:
                seen[key] = (idx, conf, utt)
    
    # Rebuild list in original order, keeping only highest-confidence version of each duplicate
    kept_indices = {v[0] for v in seen.values()}
    result = [utt for idx, utt in enumerate(utterances) if idx in kept_indices]
    
    if len(result) < len(utterances):
        print(f"[Dedup] Removed {len(utterances) - len(result)} duplicate utterances from overlapping regions\n")
    
    return result


def _merge_segments(
    sentence_confidences: list,
    low_confidence_threshold: float = 0.75,
    high_confidence_threshold: float = 0.85,
    max_words: int = 2,
    max_gap: float = 0.35,
    very_low_confidence_threshold: float = 0.30,
    single_word_threshold: float = 0.50,
) -> list:
    """
    Aggressively merge low-confidence and very short segments in multiple passes:
    
    Pass 1: Merge VERY low confidence segments (< 0.30) with previous segment
    Pass 2: Merge single-word segments with low confidence (< 0.50)
    Pass 3: Merge low-confidence short segments (< max_words, confidence < low_confidence_threshold)
    Pass 4: Merge high-confidence adjacent segments (both > high_confidence_threshold)
    
    Args:
        sentence_confidences: List of segment dicts with text, confidence, speaker, start, end
        low_confidence_threshold: Threshold for low-conf merging (default 0.75)
        high_confidence_threshold: Threshold for high-conf merging (default 0.85)
        max_words: Max words to consider "short" (default 2)
        max_gap: Max time gap for high-conf merging (default 0.35s)
        very_low_confidence_threshold: Threshold for "extremely low" confidence (default 0.30)
        single_word_threshold: Threshold for single-word segments (default 0.50)
    
    Returns: Merged sentence_confidences list
    """
    if not sentence_confidences or len(sentence_confidences) < 2:
        return sentence_confidences
    
    # Pass 1: AGGRESSIVELY merge VERY low confidence segments (< 0.30) with previous
    # These are almost certainly artifacts or boundary cutoffs
    merged = []
    
    for i, seg in enumerate(sentence_confidences):
        conf = seg.get("confidence")
        is_very_low = conf is not None and conf < very_low_confidence_threshold
        
        if is_very_low and merged and merged[-1].get("speaker") == seg.get("speaker"):
            # Merge with previous segment
            prev_seg = merged[-1]
            prev_text = prev_seg.get("text", "")
            curr_text = seg.get("text", "")
            
            prev_seg["text"] = f"{prev_text} {curr_text}".strip()
            
            # Update confidence (average)
            prev_conf = prev_seg.get("confidence")
            if prev_conf is not None and conf is not None:
                new_conf = (prev_conf + conf) / 2
                prev_seg["confidence"] = new_conf
                prev_seg["confidence_percent"] = round(new_conf * 100, 1)
            
            if seg.get("end"):
                prev_seg["end"] = seg["end"]
            
            print(f"  [Merge] Very low conf ({conf*100:.0f}%): '{curr_text}' → merged with previous")
        else:
            merged.append(seg)
    
    # Pass 2: AGGRESSIVELY merge single-word segments with low confidence (< 0.50)
    # Single words with < 50% confidence are likely cut-offs or artifacts
    result = []
    
    for i, seg in enumerate(merged):
        word_count = len((seg.get("text") or "").split())
        conf = seg.get("confidence")
        is_single_word_low = word_count == 1 and conf is not None and conf < single_word_threshold
        
        if is_single_word_low and result and result[-1].get("speaker") == seg.get("speaker"):
            # Merge with previous segment
            prev_seg = result[-1]
            prev_text = prev_seg.get("text", "")
            curr_text = seg.get("text", "")
            
            prev_seg["text"] = f"{prev_text} {curr_text}".strip()
            
            # Update confidence
            prev_conf = prev_seg.get("confidence")
            if prev_conf is not None and conf is not None:
                new_conf = (prev_conf + conf) / 2
                prev_seg["confidence"] = new_conf
                prev_seg["confidence_percent"] = round(new_conf * 100, 1)
            
            if seg.get("end"):
                prev_seg["end"] = seg["end"]
            
            print(f"  [Merge] Single word ({conf*100:.0f}%): '{curr_text}' → merged with previous")
        else:
            result.append(seg)
    
    # Pass 3: Merge low-confidence short segments with previous segment
    merged = []
    
    for i, seg in enumerate(result):
        word_count = len((seg.get("text") or "").split())
        conf = seg.get("confidence")
        is_short = word_count <= max_words
        is_low_conf = conf is not None and conf < low_confidence_threshold
        
        if is_short and is_low_conf and merged and merged[-1].get("speaker") == seg.get("speaker"):
            # Merge with previous (don't require previous to have higher confidence anymore)
            prev_seg = merged[-1]
            prev_text = prev_seg.get("text", "")
            curr_text = seg.get("text", "")
            
            prev_seg["text"] = f"{prev_text} {curr_text}".strip()
            
            # Update confidence
            prev_conf = prev_seg.get("confidence")
            if prev_conf is not None and conf is not None:
                new_conf = (prev_conf + conf) / 2
                prev_seg["confidence"] = new_conf
                prev_seg["confidence_percent"] = round(new_conf * 100, 1)
            
            if seg.get("end"):
                prev_seg["end"] = seg["end"]
        else:
            merged.append(seg)
    
    # Pass 4: Merge high-confidence adjacent segments from same speaker with small gap
    result = []
    
    for i, seg in enumerate(merged):
        if seg is None:  # Skip already-merged segments
            continue
            
        conf = seg.get("confidence")
        is_high_conf = conf is not None and conf > high_confidence_threshold
        
        if is_high_conf and i + 1 < len(merged):
            next_seg = merged[i + 1]
            if next_seg is None:  # Skip if next was already merged
                result.append(seg)
                continue
                
            next_conf = next_seg.get("confidence")
            is_next_high_conf = next_conf is not None and next_conf > high_confidence_threshold
            
            # Check if next segment is also high-conf, same speaker, and close in time
            if is_next_high_conf and next_seg.get("speaker") == seg.get("speaker"):
                seg_end = seg.get("end")
                next_start = next_seg.get("start")
                
                # Calculate gap if both timestamps exist
                gap = None
                if seg_end is not None and next_start is not None:
                    gap = next_start - seg_end
                
                # Merge if gap is small enough (or no timestamps to check)
                if gap is None or gap <= max_gap:
                    seg["text"] = f"{seg['text']} {next_seg['text']}"
                    seg["confidence"] = (conf + next_conf) / 2
                    seg["confidence_percent"] = round(seg["confidence"] * 100, 1)
                    if next_seg.get("end"):
                        seg["end"] = next_seg["end"]
                    # Skip next segment in iteration
                    merged[i + 1] = None
        
        result.append(seg)
    
    # Clean up None entries
    result = [s for s in result if s is not None]
    
    return result



def _boost_fragment_confidence(sentence_confidences: list, boost_factor: float = 1.20) -> list:
    """
    Intelligently boost confidence for sentence-fragment endings without extra API calls.
    
    Fragments (very short, low-confidence segments) at utterance boundaries are likely cut-off 
    words or artifacts. This function identifies them based on patterns and applies a confidence
    boost if they fit linguistic patterns (end with punctuation, follow longer utterances, etc.)
    
    Args:
        sentence_confidences: List of utterance dicts
        boost_factor: Multiplier for confidence boost (default 1.20 = +20%)
    
    Returns:
        Updated sentence_confidences list with boosted boundary fragments
    """
    if not sentence_confidences or len(sentence_confidences) < 2:
        return sentence_confidences
    
    for i, seg in enumerate(sentence_confidences):
        text = (seg.get("text") or "").strip()
        conf = seg.get("confidence")
        word_count = len(text.split())
        
        # Criteria for a likely boundary fragment:
        # - Single word or very short (2-3 words)
        # - Low confidence (< 60%)
        # - Ends with punctuation (., ?, !, , ; :)
        # - Follows a longer utterance from same speaker
        if (
            word_count <= 3
            and conf is not None
            and conf < 0.60
            and i > 0
            and (text.endswith(".") or text.endswith("?") or text.endswith("!") 
                 or text.endswith(",") or text.endswith(";") or text.endswith(":"))
        ):
            # Check if previous segment is from same speaker and is longer
            prev_seg = sentence_confidences[i - 1]
            if prev_seg.get("speaker") == seg.get("speaker"):
                prev_text = (prev_seg.get("text") or "").strip()
                prev_words = len(prev_text.split())
                
                if prev_words > 3:  # Previous is substantial
                    old_conf = conf
                    new_conf = min(0.90, conf * boost_factor)  # Cap at 90%
                    seg["confidence"] = new_conf
                    seg["confidence_percent"] = round(new_conf * 100, 1)
                    print(f"  [Fragment Boost] '{text}' ({old_conf*100:.0f}% → {new_conf*100:.0f}%) — likely sentence ending")
    
    return sentence_confidences


def transcribe_audio(audio_path: str, gladia_token: str):
    """Transcribe audio with diarization using Gladia API.

    Returns:
      transcript: str
      sentence_confidences: list[dict]
            transcription_confidence_avg: Optional[float]
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
        "https://api.gladia.io/v2/pre-recorded",
        headers=headers,
        json={
            "audio_url": audio_url,
            "diarization": True,
            "diarization_config": {
                "number_of_speakers": 2,
                "min_speakers": 1,
                "max_speakers": 3,
            },
            "sentences": True
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

        # Boost confidence for sentence-ending fragments (local post-processing, no API calls)
        print("\n[Fragment Analysis] Identifying and boosting sentence-ending fragments...")
        sentence_confidences = _boost_fragment_confidence(sentence_confidences, boost_factor=1.20)

        # Floor known utterance phrases before any merge decisions so low-confidence
        # phrase fragments are treated as reliable enough to preserve on export.
        print("\n[Export Floor] Applying phrase confidence floor before merging...")
        sentence_confidences = _apply_utterance_confidence_floor(sentence_confidences, floor=SCORE_CLAMP_FLOOR)

        # Merge low-confidence short segments before building final transcript
        print("\n[Merge] Merging low-confidence and short segments...")
        sentence_confidences = _merge_segments(
            sentence_confidences,
            low_confidence_threshold=0.75,
            high_confidence_threshold=0.85,
            max_words=2,
            max_gap=0.35,
            very_low_confidence_threshold=0.30,
            single_word_threshold=0.50,
        )

        # Rebuild transcript from merged segments
        lines = [f"SPEAKER_{s['speaker']}: {s['text']}" for s in sentence_confidences]
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

# ── CONTEXT BUILDING ──────────────────────────────────────────────────────────

def build_context_block(
    rag_context: str = "",
    extra_context: str = "",
    suggested_codes: Optional[List[dict]] = None,
) -> str:
    """Build a formatted context block for prompt injection."""
    parts = []
    
    if rag_context:
        parts.append("## Medical Knowledge Base Context")
        parts.append(rag_context)
    
    if suggested_codes:
        parts.append("\n## Suggested ICD-10 Codes")
        for item in suggested_codes:
            code = item.get("code", "")
            desc = item.get("description", "")
            parts.append(f"- {code}: {desc}")
    
    if extra_context:
        parts.append(extra_context)
    
    return "\n".join(parts) if parts else ""

# ── SUMMARIZATION ─────────────────────────────────────────────────────────────

def summarize_transcript(
    transcript: str,
    groq_token: str,
    rag_context: str = "",
    suggested_codes: Optional[List[dict]] = None,
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
        max_tokens=2000,
        temperature=0.2
    )

    summary = response.choices[0].message.content.strip()

    print("Summary complete.\n")
    return summary


def summarize_soap_notes(
    transcript: str,
    groq_token: str,
    rag_context: str = "",
    suggested_codes: Optional[List[dict]] = None,
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
    output_path: str = DEFAULT_OUTPUT_PATH,
    sentence_confidences: Optional[List[dict]] = None,
    transcription_confidence_avg: Optional[float] = None,
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
    parser.add_argument("--audio",      type=str, default=DEFAULT_AUDIO_PATH)
    parser.add_argument("--transcript", type=str, default=None,
                        help="Path to existing transcript — skips transcription")
    parser.add_argument("--output",     type=str, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--no-rag",     action="store_true", help="Disable ChromaDB RAG")
    parser.add_argument("--rag-limit",   type=int, default=None,
                        help="Cap CSV rows per file for RAG (e.g. 500 for quick testing)")
    parser.add_argument("--rebuild-rag", action="store_true", help="Force rebuild Chroma index even if manifest matches")
    parser.add_argument(
        "--use-precompiled-rag",
        action="store_true",
        help="Download/load precompiled Chroma index instead of local rebuild/indexing",
    )
    parser.add_argument("--skip-preprocess", action="store_true", 
                       help="Skip pre-audio processing")
    parser.add_argument("--denoise", action="store_true", 
                       help="Enable noise reduction")
    parser.add_argument(
        "--transcription-only",
        action="store_true",
        help="Stop after transcription and save transcript/confidence output only",
    )

    args = parser.parse_args()

    # Load API tokens
    with open(os.path.join(PROJECT_ROOT, ".api_token.json"), "r") as f:
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

    # ── Step 0: Pre-Audio Processing ──────────────────────────────────────────
    if not args.transcript and not args.skip_preprocess:
        quality = check_audio_quality(args.audio)
        if quality:
            print("Audio Quality Report:")
            print(f"  Duration: {quality['duration_sec']}s")
            print(f"  RMS Energy: {quality['rms_energy']}")
            if quality['issues']:
                for issue in quality['issues']:
                    print(f"  ⚠ {issue}")
            print()
        
        args.audio = preprocess_audio(
            args.audio,
            target_sr=16000,
            normalize=True,
            reduce_noise=args.denoise,
        )

    # ── Step 1: Transcript ────────────────────────────────────────────────────
    sentence_confidences = []
    transcription_confidence_avg = None

    if args.transcript:
        transcript = load_transcript(args.transcript)
    else:
        transcript, sentence_confidences, transcription_confidence_avg = transcribe_audio(
            args.audio, gladia_token=gladia_token
        )

    if args.transcription_only:
        save_output(
            transcript=transcript,
            summary="",
            soap_notes="",
            output_path=args.output,
            sentence_confidences=sentence_confidences,
            transcription_confidence_avg=transcription_confidence_avg,
        )
        print("\nTRANSCRIPT:")
        print(transcript)
        if transcription_confidence_avg is not None:
            print(f"\nAverage transcription confidence: {transcription_confidence_avg * 100:.1f}%")
        return

    # ── Step 2: ChromaDB RAG ──────────────────────────────────────────────────
    if callable(suggest_icd_codes_local):
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
    else:
        suggested_codes = []
        print("[ICD] Skipped (optional RAG dependencies not installed).\n")

    rag_context = ""
    if not args.no_rag:
        if RAG_IMPORT_ERROR is not None or not all(
            [callable(load_existing_vectorstore), callable(get_relevant_context), callable(setup_knowledge_base)]
        ):
            print(f"[RAG] Skipped: optional dependencies unavailable ({RAG_IMPORT_ERROR})\n")
            rag_context = ""
        elif args.use_precompiled_rag:
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