# NLP for Medical Records

Medical consultation transcription, summarization, SOAP note generation, and consultation management platform built with Flask, React, SQLite, Gladia Speech-to-Text, Groq LLMs, and Retrieval-Augmented Generation (RAG).

---

## Overview

This project processes doctor–patient consultations and automatically generates:

* Speaker-diarized transcripts
* AI-generated consultation summaries
* SOAP notes
* ICD-10 code suggestions
* Historical consultation records
* Doctor and patient management

The system consists of:

* **React frontend** for user interaction
* **Flask backend API**
* **SQLite database**
* **Medical NLP pipeline**
* **RAG-powered medical knowledge retrieval**
* **Gladia transcription**
* **Groq Llama 3.3 summarization**

---

# Features

## Consultation Processing

* Upload consultation audio files
* Multi-format audio support:

  * MP3
  * WAV
  * M4A
  * FLAC
  * WEBM

## Transcription

* Gladia Speech-to-Text API
* Speaker diarization
* Confidence scoring
* Sentence-level confidence tracking

## AI Documentation

* Medical summaries
* SOAP note generation
* Language-aware prompting
* English and Hungarian support

## RAG Enhancement

* ChromaDB vector database
* HuggingFace embeddings
* Medical knowledge retrieval
* Context-aware summarization

## Clinical Support

* ICD-10 code suggestions
* Medical context retrieval
* Clinical terminology normalization

## Consultation Management

* Doctor management
* Patient management
* Consultation history
* Editable summaries
* Editable SOAP notes

---

# Architecture

```text
┌───────────────────────┐
│     React Frontend    │
└───────────┬───────────┘
            │ HTTP
            ▼
┌───────────────────────┐
│      Flask API        │
└───────────┬───────────┘
            │
            ├──────────────────────┐
            │                      │
            ▼                      ▼
┌──────────────────┐     ┌──────────────────┐
│    SQLite DB     │     │ Medical Pipeline │
└──────────────────┘     └────────┬─────────┘
                                  │
             ┌────────────────────┼────────────────────┐
             │                    │                    │
             ▼                    ▼                    ▼
      Gladia STT           ChromaDB RAG         Groq LLM
      + Diarization        + ICD Lookup         Summary/SOAP
```

---

# Project Structure (Most important parts)

```text
NLP-for-medical-records/
│
├── backend/
│   ├── routes/
│   │   └── api.py
│   ├── uploads/
│   ├── app.py
│   ├── config.py
│   ├── db.py
│   └── models.py
│
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── Comp/
│   │   ├── Pages/
│   │   ├── App.js
│   │   └── index.js
│   └── package.json
│
├── pipeline/
│   ├── medical_pipeline.py
│   ├── rag_pipeline.py
│   └── rag_core/
│
├── data/
│   ├── knowledge_base/
│   ├── chroma_db/
│   ├── icd10_codes.txt
│   └── test_audio/
│
├── evaluation/
├── QAandTesting/
├── docs/
│
├── requirements.txt
├── package.json
└── README.md
```

---

# Technology Stack

## Backend

* Flask
* Flask-CORS
* Flask-SQLAlchemy
* SQLite

## Frontend

* React
* React DOM

## AI / NLP

* Gladia API
* Groq API
* OpenAI-compatible client
* LangChain
* ChromaDB
* Sentence Transformers

## Data Processing

* Pandas
* NumPy
* Librosa
* SoundFile
* BeautifulSoup

## Testing

* Pytest
* Jest
* React Testing Library

---

# Prerequisites

Install:

## Python

Recommended:

```bash
Python 3.10+
```

Verify:

```bash
python --version
```

## Node.js

Recommended:

```bash
Node.js 18+
```

Verify:

```bash
node --version
npm --version
```

---

# API Keys Setup

The application requires:

## Gladia API

Used for:

* Audio upload
* Speech recognition
* Speaker diarization

Create account:

https://www.gladia.io/

---

## Groq API

Used for:

* Summary generation
* SOAP note generation

Create account:

https://console.groq.com/

---

# Create API Token File

Create a file in the project root:

```text
.api_token.json
```

Example:

```json
{
  "gladia-token": "YOUR_GLADIA_API_KEY",
  "groq-token": "YOUR_GROQ_API_KEY"
}
```

Project structure:

```text
NLP-for-medical-records/
│
├── .api_token.json
├── backend/
├── frontend/
└── pipeline/
```

Do not commit this file to source control.

---

# Installation

## Clone Repository

```bash
git clone <repository-url>
cd NLP-for-medical-records
```

---

## Install Python Dependencies

```bash
pip install -r requirements.txt
```

---

## Install Frontend Dependencies

```bash
cd frontend
npm install
```

Return to project root:

```bash
cd ..
```

---

# Running the Application

## Start Backend

From project root:

```bash
cd backend
python app.py
```

Backend runs on:

```text
http://localhost:5000
```

Health endpoint:

```text
GET /
```

Response:

```json
{
  "message": "Medical Records API is running"
}
```

---

## Start Frontend

Open a second terminal:

```bash
cd frontend
npm start
```

Frontend runs on:

```text
http://localhost:3000
```

---

# Running the NLP Pipeline Standalone

The pipeline can be executed independently from the web application.

---

## Process Audio File

```bash
python pipeline/medical_pipeline.py \
  --audio data/test_audio/test_audio.mp3
```

---

## Process Existing Transcript

```bash
python pipeline/medical_pipeline.py \
  --transcript transcript.txt
```

---

## Disable RAG

```bash
python pipeline/medical_pipeline.py \
  --transcript transcript.txt \
  --no-rag
```

---

## Rebuild RAG Database

```bash
python pipeline/medical_pipeline.py \
  --transcript transcript.txt \
  --rebuild-rag
```

---

## Use Precompiled RAG

```bash
python pipeline/medical_pipeline.py \
  --transcript transcript.txt \
  --use-precompiled-rag
```

---

## Skip Audio Preprocessing

```bash
python pipeline/medical_pipeline.py \
  --audio sample.mp3 \
  --skip-preprocess
```

---

## Enable Noise Reduction

```bash
python pipeline/medical_pipeline.py \
  --audio sample.mp3 \
  --denoise
```

---

# Medical Pipeline Flow

## Step 1

Audio Upload


## Step 2

Audio Quality Analysis


## Step 3

Audio Preprocessing

* Resampling
* Normalization
* Noise reduction


## Step 4

Gladia Transcription

* Speech-to-text
* Diarization
* Confidence scoring


## Step 5

ICD-10 Lookup


## Step 6

RAG Context Retrieval


## Step 7

Groq Summary Generation


## Step 8

SOAP Note Generation


## Step 9

Database Storage

---

# Database

The application uses SQLite.

Database location:

### Windows

```text
%LOCALAPPDATA%/NLPMedicalRecords/medical.db
```

Generated automatically on first launch.

---

# Database Schema

## doctors

| Column     | Type     |
| ---------- | -------- |
| id         | Integer  |
| title      | String   |
| first_name | String   |
| last_name  | String   |
| created_at | DateTime |

---

## patients

| Column        | Type     |
| ------------- | -------- |
| id            | Integer  |
| title         | String   |
| first_name    | String   |
| last_name     | String   |
| date_of_birth | Date     |
| taj_number    | String   |
| created_at    | DateTime |

---

## consultations

| Column               | Type     |
| -------------------- | -------- |
| id                   | Integer  |
| doctor_id            | Integer  |
| patient_id           | Integer  |
| transcript           | Text     |
| summary              | Text     |
| soap_notes           | Text     |
| sentence_confidences | Text     |
| created_at           | DateTime |

---

# REST API

Base URL:

```text
http://localhost:5000/api
```

---

## Get Doctors

```http
GET /doctors
```

---

## Create Doctor

```http
POST /doctors
```

Body:

```json
{
  "title": "Dr.",
  "first_name": "John",
  "last_name": "Smith"
}
```

---

## Get Patients

```http
GET /patients
```

---

## Create Patient

```http
POST /patients
```

Body:

```json
{
  "title": "Mr.",
  "first_name": "John",
  "last_name": "Doe",
  "date_of_birth": "1980-05-10",
  "taj_number": "123456789"
}
```

---

## Process Consultation

```http
POST /process
```

Multipart form:

```text
file
doctor_id
patient_id
```

Returns:

```json
{
  "message": "Processing complete",
  "data": {
    "transcript": "...",
    "summary": "...",
    "soap_notes": "...",
    "sentence_confidences": []
  }
}
```

---

## Consultation History

```http
GET /history
```

---

## Update Consultation

```http
PATCH /consultations/{id}
```

Body:

```json
{
  "summary": "Updated summary",
  "soap": {
    "subjective": "...",
    "objective": "...",
    "assessment": "...",
    "plan": "..."
  }
}
```

---

# Retrieval-Augmented Generation (RAG)

The project supports medical knowledge retrieval using:

* LangChain
* ChromaDB
* HuggingFace Embeddings

---

## Knowledge Sources

Located in:

```text
data/knowledge_base/
```

Example sources:

```text
clinical_lab_facts.csv
DDI_data_clean.csv
```

---

## Vector Store

Stored in:

```text
data/chroma_db/
```

Generated automatically.

---

## ICD-10 Suggestions

The system performs local ICD matching using:

```text
data/icd10_codes.txt
```

Top matching codes are injected into prompts to improve clinical documentation quality.

---

# Output Example

Pipeline output:

```json
{
  "transcript": "...",
  "summary": "...",
  "soap_notes": "...",
  "transcription_confidence_avg": 0.93,
  "sentence_confidences": []
}
```

---

# Testing

## Backend Tests

```bash
pytest
```

---

## Frontend Tests

```bash
npm test
```

---

## Jest Tests

```bash
npm run test
```

---

# Common Issues

## Missing API Tokens

Error:

```text
Groq API token missing.
```

or

```text
Gladia API token missing.
```

Solution:

Verify:

```text
.api_token.json
```

contains valid keys.

---

## Port Already In Use

Backend:

```text
5000
```

Frontend:

```text
3000
```

Stop existing processes or change ports.

---

## Chroma Index Missing

Run:

```bash
python pipeline/medical_pipeline.py \
  --transcript sample.txt \
  --rebuild-rag
```

---

## Missing Python Packages

Reinstall:

```bash
pip install -r requirements.txt
```

---

# Development Notes

Generated artifacts:

```text
backend/uploads/
data/chroma_db/
output.json
```

These files should generally not be committed.

---

# Future Improvements

* Authentication and authorization
* Multi-user support
* PostgreSQL deployment
* Docker support
* Kubernetes deployment
* EHR integration
* FHIR support
* Multi-language expansion
* Fine-tuned clinical LLMs

---

# License

This project was developed as part of an academic software engineering project.

Add an appropriate license before public distribution.
