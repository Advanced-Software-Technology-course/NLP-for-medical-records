# T8.4 – Integration Test Execution Report

## Project

NLP for Medical Records – Speech to SOAP Pipeline

## Test Type

Integration Testing

## Environment

* Frontend: React
* Backend: Flask
* AI Pipeline: Speech-to-Text + NLP Summarization + SOAP Generation
* Optional RAG: ChromaDB

---

## Objective

To verify correct interaction between frontend components, backend APIs, and generated clinical outputs.

---

## Integration Flow

React Client → Flask API → AI Pipeline → JSON Response → UI Rendering

---

## Executed Test Cases

| ID    | Test Case                       | Result  |
| ----- | ------------------------------- | ------- |
| IT-01 | History to Summary Flow         | Passed  |
| IT-02 | Navigation Stability            | Passed  |
| IT-03 | Settings Page Rendering         | Passed  |
| IT-04 | Empty History Response          | Passed  |
| IT-05 | Initial Application Load        | Passed  |
| IT-06 | Backend Failure Handling        | Passed  |
| IT-07 | Multiple Consultation Records   | Passed  |
| IT-08 | Repeated Navigation Stability   | Passed  |
| IT-09 | Consultation Data Integrity     | Passed  |
| IT-10 | Empty SOAP Handling             | Passed  |
| IT-11 | Repeated History Navigation     | Passed  |
| IT-12 | Settings Round Trip Navigation  | Passed  |
| IT-13 | Transcript Rendering Validation | Failed* |

---

## Failure Analysis

### Failed Test Case: IT-13 (Loaded consultation contains transcript)

* **Error Triggered:** `TestingLibraryElementError: Found multiple elements with the role "button" and name /transcript/i`
* **Root Cause:** The DOM rendering strategy outputs multiple elements sharing matching accessibility text attributes (the back navigation icon link `← View transcript` and its structural layout components). `queryByRole` matches too broadly, breaking strict single-element assertion guarantees.
* **Remediation Required:** Refactor the test script block at line 343 to utilize `screen.queryAllByRole` or enforce unique element selectors via explicit test ID tags (`data-testid`).

---

## Observations

* No core React structural rendering failures or application crashes observed.
* Component state integrity remains functional during multiple navigation loops.
* API schema formats map cleanly to state storage properties without corruption.
* **UI Query Ambiguity:** Text labels within customized navigation UI elements interfere with default accessibility role lookups.

---

## Test Statistics

| Metric       | Result |
| ------------ | ------ |
| Total Tests  | 13     |
| Passed       | 12     |
| Failed       | 1      |
| Success Rate | 92.3%  |

---

## Final Result

STATUS: PARTIALLY SUCCESSFUL

Frontend-to-backend integration was mostly successful. Core application states, data safety workflows, and multi-endpoint parameters behave reliably under typical runtime execution. One test suite failure was identified as a structural test selector collision during element query simulation rather than a systemic application fault.