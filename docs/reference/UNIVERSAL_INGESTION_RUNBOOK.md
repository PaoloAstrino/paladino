# Universal Ingestion Runbook

Document Date: February 23, 2026  
Scope: Operational rollout and maintenance for the Universal Ingestion Engine

---

## 1) Purpose

This runbook defines how to deploy, validate, and operate Universal Ingestion safely.

Important boundary:
- Universal Ingestion is for unstructured/semi-structured sources (PDF, text, web).
- Structured sources (ANAC/OpenCUP/ISTAT/PNRR CSV/JSON) must stay on dedicated ETL pipelines.

---

## 2) Prerequisites

### Runtime
- Python 3.11+
- Neo4j running and reachable
- Project dependencies installed

### Environment
- PALADINO_NEO4J_USER
- PALADINO_NEO4J_PASSWORD
- Optional LLM settings:
  - PALADINO_LLM_MODEL
  - PALADINO_LLM_API_KEY
  - PALADINO_LLM_API_BASE
  - PALADINO_OLLAMA_BASE_URL

### OCR (for scanned PDF)
- Python packages: pytesseract, Pillow
- System binary: Tesseract OCR installed and available in PATH

---

## 3) Rollout Sequence

### Step A: Install/Update dependencies
- pip install -e .

### Step B: Apply schema updates
- paladino preflight --for schema
- python scripts/init_schema.py

Expected result:
- New constraints and indexes are present for Entity/SourceDocument/RELATED_TO.

### Step C: Validate endpoint and CLI wiring
- paladino preflight --for ingest
- paladino ingest-unstructured --source data/pnnr/PNRR_Soggetti.csv
  - Expected: structured bypass + suggested ETL script

- curl -X POST http://localhost:8000/ingest/unstructured -H "Content-Type: application/json" -d '{"source":"data/pnnr/PNRR_Soggetti.csv"}'
  - Expected: mode = structured_bypass

### Step D: Validate unstructured happy path
- paladino ingest-unstructured --source path/to/sample.txt --max-chars 8000 --chunk-overlap 300
  - Expected: unstructured processing response with entities/relationships JSON

---

## 4) Operational Modes

### CLI mode
- Command: paladino ingest-unstructured
- Use for analyst/local workflows and manual investigations.

### API mode
- Endpoint: POST /ingest/unstructured
- Use for automation, dashboards, external services.

---

## 5) Safety Guards (Must Keep)

- Structured bypass must remain enabled.
- chunk_overlap must always be lower than max_chars.
- Provenance fields must be written for every extracted node/relationship:
  - _source_file
  - _extraction_date
  - _extraction_method
  - _confidence_score

---

## 6) Monitoring and Checks

### Pre-release checks
- pytest tests/integration/test_api_endpoints.py -k "unstructured_ingest_endpoint" -v
- pytest tests/unit/test_universal_ingestor.py -v
- pytest tests/unit/test_ner_pipeline.py -v

### Post-release checks
- Verify /health endpoint
- Validate one structured bypass request and one unstructured request
- Confirm Entity and SourceDocument counts increase as expected

---

## 7) Troubleshooting

### Error: missing Neo4j credentials
Symptom:
- ValidationError for PALADINO_NEO4J_USER / PALADINO_NEO4J_PASSWORD

Action:
- Set env vars in shell, then re-run scripts/init_schema.py.

### Error: OCR fallback unavailable
Symptom:
- Runtime error about pytesseract/Pillow or missing tesseract binary

Action:
- pip install pillow pytesseract
- Install system Tesseract and add to PATH.

### Error: invalid chunk config
Symptom:
- API 422 or CLI validation error

Action:
- Set chunk_overlap < max_chars.

---

## 8) Rollback Plan

If ingestion causes unexpected behavior:
- Disable calls to /ingest/unstructured from clients.
- Use only dedicated ETL scripts for data updates.
- Keep schema as-is (constraints/indexes are additive and safe).
- Re-enable after fixing extraction pipeline issues.

---

## 9) Ownership

- Data Engineering: extractor/routing/schema changes
- API Team: endpoint contracts and input validation
- Analytics Team: entity mapping quality and downstream metrics
