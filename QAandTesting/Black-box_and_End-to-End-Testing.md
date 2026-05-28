# T8.3 – Black-box / End-to-End Testing Report

## Project

NLP for Medical Records – Speech to SOAP Pipeline

## Test Type

Black-box End-to-End Testing

## Environment

* OS: Windows (localhost)
* Backend: Flask (Python)
* Frontend: React
* AI Pipeline: STT + NLP Summarization + SOAP Generation
* Optional RAG: ChromaDB

---

## Objective

The objective of this testing phase was to validate the system from an end-user perspective without inspecting internal implementation details.

The following areas were evaluated:

* Audio upload functionality
* Backend processing pipeline
* Transcript generation
* SOAP note generation
* Error handling
* API stability
* Input validation
* System robustness

---

## Executed Test Cases

| ID    | Test Case                   | Result  |
| ----- | --------------------------- | ------- |
| TC-01 | Valid MP3 Upload            | Failed* |
| TC-02 | Valid WAV Upload            | Passed  |
| TC-03 | Invalid File Upload         | Passed  |
| TC-04 | Missing File Upload         | Passed  |
| TC-05 | Empty Filename              | Passed  |
| TC-06 | Unsupported Extension       | Passed  |
| TC-07 | Zero-byte Audio File        | Failed* |
| TC-08 | Large Audio Upload          | Failed* |
| TC-09 | Invalid Content Type        | Passed  |
| TC-10 | Consecutive Requests        | Passed  |
| TC-11 | Health Endpoint Consistency | Passed  |
| TC-12 | Uppercase Invalid Extension | Passed  |
| TC-13 | Multiple Invalid Uploads    | Passed  |
| TC-14 | Incorrect HTTP Method       | Passed  |

---

## Failure Analysis

Three test cases failed because the external Gladia Speech-to-Text service was unavailable due to missing API credentials during execution.

Observed response:

HTTP 401 Unauthorized

Affected tests:

* TC-01 Valid MP3 Upload
* TC-07 Zero-byte Audio Upload
* TC-08 Large Audio Upload

The failures were caused by external infrastructure dependency rather than defects in application routing or validation logic.

---

## Observations

* ChromaDB file locking occasionally occurs on Windows during rapid backend restarts.
* Startup latency is increased by dependency initialization (LangChain, NLTK, SciPy).
* External API availability directly affects transcription-related tests.

---

## Test Statistics

| Metric       | Result |
| ------------ | ------ |
| Total Tests  | 14     |
| Passed       | 11     |
| Failed       | 3      |
| Success Rate | 78.6%  |

---

## Final Result

STATUS: PARTIALLY SUCCESSFUL

The application successfully passed all validation, error-handling, and stability tests. Three tests dependent on external STT infrastructure failed because API credentials were unavailable during execution.
