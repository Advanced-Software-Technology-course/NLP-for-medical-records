# T8.3 – Black-box / End-to-End Testing Report

## Project
NLP for Medical Records – Speech to SOAP Pipeline

## Test Type
Black-box End-to-End Testing

## Environment
- OS: Windows (localhost)
- Backend: Flask (Python)
- Frontend: React
- AI Pipeline: STT + NLP summarization + SOAP generation
- Optional RAG: ChromaDB

---

## Objective

The goal of this test was to validate the system from a **user perspective**, ensuring that:

- Audio files can be uploaded via the frontend
- Backend processes audio correctly
- Transcript is generated successfully
- SOAP note is generated successfully
- Edge cases are handled properly
- System remains stable under invalid input

---

## System Setup

### Start Backend
```bash
python backend/app.py
Start Frontend
cd frontend
npm install
npm start
Application URL
http://localhost:3000
Test Case 1 – Valid MP3 Audio Upload
Input
data/test_audio/test_audio.mp3
Steps
Open frontend in browser
Upload MP3 file
Submit request
Wait for processing
Expected Result
Transcript is generated
SOAP note is generated
API returns success response
No crashes occur
Actual Result
Transcript successfully generated
SOAP note successfully generated
UI displays results correctly
API response returned successfully
Status

PASS

Test Case 2 – Valid WAV Audio Upload
Input
data/eka_dataset_audio/audio_sample/audio_0.wav
Expected Result

Same processing behavior as MP3

Actual Result
File processed successfully
Transcript and SOAP note generated correctly
UI displayed outputs correctly
Status

PASS

Test Case 3 – Invalid File Upload
Inputs Tested
.txt file
empty file
corrupted audio file
Expected Result
Clear error message displayed
System does not crash
Backend remains stable
Actual Result
Error message shown to user
No backend crash
No frontend crash
System remained stable
Status

PASS

Observed Issues
ChromaDB file locking issue on Windows when backend is restarted rapidly
Slow startup due to heavy dependency loading (LangChain, SciPy, NLTK)
Occasional fallback to sentence-transformers embeddings when model is unavailable
Summary
Component	Status
Audio Upload	PASS
Transcript Generation	PASS
SOAP Generation	PASS
Edge Case Handling	PASS
System Stability	PASS
Final Result

The system successfully passes black-box end-to-end testing. All core user workflows are functional, and invalid inputs are handled safely without system failure.


If you want, I can also:
- :contentReference[oaicite:0]{index=0}
- or :contentReference[oaicite:1]{index=1}
- or :contentReference[oaicite:2]{index=2}