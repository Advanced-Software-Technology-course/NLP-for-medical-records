# T8.3 – Black-box / End-to-End Testing Report

## Project
**NLP for Medical Records – Speech to SOAP Pipeline**

## Test Type
Black-box End-to-End Testing

## Environment
- **OS:** Windows (localhost)
- **Backend:** Flask (Python)
- **Frontend:** React
- **AI Pipeline:** STT + NLP summarization + SOAP generation
- **Optional RAG:** ChromaDB

---

## Objective

The goal of this test was to validate the system from a **user perspective**, ensuring complete functional integrity across the following vectors:

- **Audio Acquisition:** Capability to upload various audio formats via the frontend.
- **Pipeline Processing:** Validating backend transcription and NLP summarization.
- **Output Integrity:** Ensuring the generated SOAP notes are clinically relevant and correctly structured.
- **Robustness:** Testing edge cases and system stability under invalid input.

---

## System Setup

### 1. Start Backend
```bash
python backend/app.py
```

### 2. Start Frontend
```bash
cd frontend
npm install
npm start
```

### 3. Application Access
- **URL:** `http://localhost:3000`

---

## Test Cases

### Test Case 1 – Valid MP3 Audio Upload
| Metric | Details |
| :--- | :--- |
| **Input** | `data/test_audio/test_audio.mp3` |
| **Steps** | 1. Open frontend in browser<br>2. Upload MP3 file<br>3. Submit request<br>4. Monitor processing status |
| **Expected Result** | Transcript is generated; SOAP note is generated successfully; API returns 200 OK. |
| **Actual Result** | Transcript successfully generated; SOAP note accurately reflects audio; UI displays results correctly. |
| **Status** |  **PASS** |

### Test Case 2 – Valid WAV Audio Upload
| Metric | Details |
| :--- | :--- |
| **Input** | `data/eka_dataset_audio/audio_sample/audio_0.wav` |
| **Expected Result** | Identical processing behavior as MP3; high-fidelity transcription. |
| **Actual Result** | File processed successfully; Transcript and SOAP note generated correctly; UI displayed outputs correctly. |
| **Status** |  **PASS** |

### Test Case 3 – Invalid File Upload
| Metric | Details |
| :--- | :--- |
| **Inputs Tested** | `.txt` file, empty file, corrupted audio file. |
| **Expected Result** | Graceful failure; Clear error message displayed; System remains stable. |
| **Actual Result** | Informative error messages shown to user; No backend/frontend crashes; Stable system state maintained. |
| **Status** |  **PASS** |

---

## Observations & Optimization Notes

- **OS Specifics:** Identified a **ChromaDB file locking issue** on Windows when the backend is restarted rapidly. This is a known interaction between Windows file handling and SQLite/ChromaDB.
- **Performance:** Noted **slow startup times** due to heavy dependency loading (LangChain, SciPy, NLTK).
- **Resilience:** Observed occasional fallback to `sentence-transformers` embeddings when the primary model endpoint is unavailable.

---

## Summary

| Component | Status |
| :--- | :--- |
| **Audio Upload** |  PASS |
| **Transcript Generation** |  PASS |
| **SOAP Generation** |  PASS |
| **Edge Case Handling** |  PASS |
| **System Stability** |  PASS |

### Final Result

> **STATUS: SUCCESS**
>
> The system successfully passes black-box end-to-end testing. All core user workflows are functional, and invalid inputs are handled safely without system failure. Ready for deployment/staging.
