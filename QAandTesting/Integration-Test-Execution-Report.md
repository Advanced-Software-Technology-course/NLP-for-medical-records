# T8.4 – Integration Test Execution Report

## Project
NLP for Medical Records – Speech to SOAP Pipeline

## Test Type
Integration Testing (React + Flask + AI Pipeline)

## Environment
- OS: Windows (localhost)
- Frontend: React
- Backend: Flask API
- AI Pipeline: Speech-to-text + NLP summarization + SOAP generation
- Optional RAG: ChromaDB

---

## Objective

This testing phase validates that:

- React frontend communicates correctly with Flask backend
- Flask backend correctly triggers AI pipeline
- JSON responses are returned correctly
- All fields are rendered in UI
- No API errors occur
- No console errors or broken requests exist

---

## System Setup

### Start backend
```bash
python backend/app.py
Start frontend
cd frontend
npm install
npm start
Application URL

http://localhost:3000

Integration Flow

React → Flask API → AI Pipeline → JSON Response → UI Rendering

Test Case 1 – Full Audio Upload Flow (MP3)
Input

data/test_audio/test_audio.mp3

Steps
Upload audio via React UI
Submit request
Wait for backend processing
Observe UI output
Expected Result
Backend returns valid JSON response
Transcript field is displayed
SOAP note field is displayed
No API errors
No frontend console errors
Actual Result
Valid JSON response received
Transcript displayed correctly
SOAP note displayed correctly
UI rendered successfully
No broken API calls observed
Status

PASS

Test Case 2 – WAV File Integration
Input

data/eka_dataset_audio/audio_sample/audio_0.wav

Expected Result
Same pipeline execution as MP3
Actual Result
File processed successfully
Output rendered correctly in UI
Status

PASS

Test Case 3 – API Stability Check
Expected Result
All API requests return HTTP 200 on success
No failed fetch requests
No CORS issues
Actual Result
API calls executed successfully
No network errors observed
Backend responses stable
Status

PASS

Test Case 4 – Frontend Rendering Validation
Expected Result
Transcript is displayed correctly
SOAP note is displayed correctly
No UI freezing or crashes
Actual Result
All fields rendered correctly
UI remained stable during processing
No rendering errors observed
Status

PASS

Test Case 5 – Invalid Input Handling
Inputs Tested
.txt file
empty file
corrupted audio file
Expected Result
Backend returns error response
Frontend displays error message
System remains stable
Actual Result
Error handled correctly
Error message displayed in UI
No crashes observed in backend or frontend
Status

PASS

Observed Issues
ChromaDB SQLite lock issue on Windows during rapid backend restarts
sentence-transformers embedding fallback behavior in some runs
Slow backend startup due to heavy dependency loading (LangChain, SciPy, NLTK)
Summary
Component	Status
React ↔ Flask Communication	PASS
API Response Handling	PASS
AI Pipeline Execution	PASS
UI Rendering	PASS
Error Handling	PASS
Final Result

The integration between React, Flask, and the AI pipeline is fully functional. The system successfully processes audio end-to-end and correctly renders all outputs in the frontend without errors.


---

If you want next step, I can also:
- :contentReference[oaicite:0]{index=0}
- or :contentReference[oaicite:1]{index=1}
- or :contentReference[oaicite:2]{index=2}