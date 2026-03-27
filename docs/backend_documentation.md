# Backend Documentation

## Quick Overview

| Item            | Value                                                          |
| --------------- | -------------------------------------------------------------- |
| Framework       | Flask                                                          |
| API Base        | /api                                                           |
| DB Engine       | SQLite (Flask-SQLAlchemy)                                      |
| DB Location     | C:/Users/<username>/AppData/Local/NLPMedicalRecords/medical.db |
| DB Creation     | Auto-created on first backend run                              |
| Tables Creation | Auto-created on first backend run via db.create_all()          |

## Backend Files

| File                  | Purpose                 | Key Contents                                                                               |
| --------------------- | ----------------------- | ------------------------------------------------------------------------------------------ |
| backend/app.py        | App entrypoint          | Creates Flask app, loads config, enables CORS, initializes DB, registers blueprints        |
| backend/config.py     | Runtime configuration   | Loads API tokens, builds AppData path, sets SQLite URI, creates uploads folder             |
| backend/db.py         | DB bootstrap            | SQLAlchemy instance + init_db(app) that runs create_all()                                  |
| backend/models.py     | Data model + API shape  | Consultation table model, SOAP parsing helper, to_dict() for frontend response shape       |
| backend/routes/api.py | API endpoints           | Audio upload/process route and history route; calls pipeline functions and persists output |
| backend/uploads/      | Temporary input storage | Uploaded audio files saved before pipeline processing                                      |

## Routes

| Method | Path         | Input                               | Processing                                                                                                      | Output                                                                 |
| ------ | ------------ | ----------------------------------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| POST   | /api/process | multipart/form-data with field file | Saves file -> transcribe_audio() -> summarize_transcript() -> summarize_soap_notes() -> insert Consultation row | 200 JSON: message + data (id, transcript, aiSummary, soap, created_at) |
| GET    | /api/history | None                                | Reads Consultation rows ordered by created_at desc                                                              | 200 JSON array of Consultation to_dict() objects                       |

## Route Communication Flow

| Step | Frontend -> Backend -> Pipeline -> DB                                                |
| ---- | ------------------------------------------------------------------------------------ |
| 1    | Frontend records audio and uploads to POST /api/process                              |
| 2    | Backend validates extension and saves file to backend/uploads                        |
| 3    | Backend calls pipeline.medical_pipeline.transcribe_audio(file, gladia_token)         |
| 4    | Backend calls pipeline.medical_pipeline.summarize_transcript(transcript, groq_token) |
| 5    | Backend calls pipeline.medical_pipeline.summarize_soap_notes(transcript, groq_token) |
| 6    | Backend stores transcript, summary, soap_notes in Consultation table                 |
| 7    | Backend returns normalized JSON for frontend rendering                               |

## Database Tables

### Table: consultation

| Column     | Type     | Null | Default         | Notes                       |
| ---------- | -------- | ---- | --------------- | --------------------------- |
| id         | Integer  | No   | Auto            | Primary key                 |
| transcript | Text     | Yes  | None            | Full transcript text        |
| summary    | Text     | Yes  | None            | AI summary text             |
| soap_notes | Text     | Yes  | None            | Raw SOAP text from pipeline |
| created_at | DateTime | Yes  | datetime.utcnow | Insert timestamp            |

## AppData Auto-Creation Behavior

| Behavior                                                               | Where It Happens                                 |
| ---------------------------------------------------------------------- | ------------------------------------------------ |
| Creates C:/Users/<username>/AppData/Local/NLPMedicalRecords if missing | backend/config.py -> get_app_data_dir()          |
| Points SQLite DB to medical.db in that folder                          | backend/config.py -> SQLALCHEMY_DATABASE_URI     |
| Creates DB tables automatically at startup                             | backend/db.py -> init_db(app) -> db.create_all() |
