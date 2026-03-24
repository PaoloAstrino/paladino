# 🦇 Universal Ingestion Engine (The "Civic Gotham" Plan)

**Document Date:** February 23, 2026  
**Project:** Paladino  
**Objective:** Transform Paladino from a structured data analyzer into a comprehensive intelligence platform capable of ingesting, understanding, and linking unstructured "dark data" (PDFs, audio, web pages, images) from the Italian Public Administration.

---

## 🌟 Vision: The Hybrid Approach

**⚠️ IMPORTANT REMINDER:** This Universal Ingestion Engine is designed **exclusively for unstructured or semi-structured "dark data"** (PDFs, audio, web pages, images, raw text). It is **NOT** meant to replace the existing, highly optimized ETL pipelines for structured open data (like ANAC, OpenCUP, ISTAT, PNRR). Those sources already have dedicated, fast, and deterministic ingestion scripts (e.g., `run_anac_etl.py`, `run_opencup_etl.py`).

To ensure Paladino remains accessible to everyone (journalists, citizens, small municipalities) while scaling for enterprise/government use, the ingestion engine will use a **Hybrid Architecture**:

*   **Local-First (Privacy & Zero Cost):** Uses open-source models running locally (Ollama, Llama-3, faster-whisper) for sensitive data or low-budget deployments.
*   **API-Fallback (Maximum Accuracy & Scale):** Uses commercial APIs (OpenAI GPT-4o, Claude 3.5, Google Cloud) for complex documents, OCR, and massive scale.

---

## 🧠 The "Smart Router" (Format Detection)

Before processing any file, the system must determine if it's a known structured format or a new unstructured source. The `UniversalIngestor` will act as a gatekeeper:

1.  **Signature Matching:** Check if the file matches known schemas (e.g., OpenCUP CSV headers, ANAC JSON structure).
2.  **Routing Decision:**
    *   *If Known Structured Data:* Immediately route to the existing, fast ETL pipelines (e.g., `paladino/etl/opencup.py`). Bypass the LLM entirely to save time and compute.
    *   *If Unknown/Unstructured Data:* Route to the Universal Ingestion Engine (Extractors -> LLM NER -> Graph Loader).

---

## 🏗️ Architecture Overview

The pipeline consists of 4 main stages:

1.  **The Router (`UniversalIngestor`)**: Accepts any file or URL, detects the MIME type, and routes it to the correct extractor.
2.  **The Extractors**: Convert raw files into normalized Markdown/Text.
3.  **The LLM NER Pipeline**: Uses `LLMManager` to perform Named Entity Recognition (NER) and Relationship Extraction, outputting a standardized JSON.
4.  **The Graph Loader**: Inserts the extracted entities into Neo4j, attaching strict **Provenance** metadata (source file, timestamp, confidence score).

---

## ✅ Execution Status (Current)

### Implemented in code

- [x] `UniversalIngestor` with smart routing and known-source detection
- [x] Route guard to prevent misuse on known structured sources (ANAC/OpenCUP/ISTAT/PNRR)
- [x] `PDFExtractor` (PyMuPDF)
- [x] `TextExtractor` (txt/markdown/html fallback)
- [x] `WebExtractor` (Trafilatura)
- [x] `UnstructuredNERPipeline` using existing `LLMManager` with JSON-enforced extraction
- [x] `UnstructuredGraphLoader` with provenance fields:
  - `_source_file`
  - `_extraction_date`
  - `_extraction_method`
  - `_confidence_score`
- [x] Demo script: `scripts/demo_universal_ingestion.py`
- [x] Dependencies added: `pymupdf`, `trafilatura`

### Pending for Phase 1 hardening

- [x] OCR fallback for scanned PDFs (`Tesseract`)
- [x] Unit tests for router signatures and guardrails (`tests/unit/test_universal_ingestor.py`)
- [x] Better routing-to-script mapping (emit exact script command for known source)
- [x] Optional chunking for long documents before LLM extraction

### Validation snapshot

- `pytest tests/unit/test_universal_ingestor.py -v` → **5 passed**
- `pytest tests/unit/test_ner_pipeline.py -v` → validates chunk merge behavior on long content
- `scripts/demo_universal_ingestion.py --source data/pnnr/PNRR_Soggetti.csv` routes to `existing_pnrr_etl` (structured bypass confirmed)
- Demo runtime tuning supported:
  - `--max-chars` for chunk size
  - `--chunk-overlap` for overlap between chunks
- Live schema apply completed successfully (`preflight --for schema` + `scripts/init_schema.py`)
- Real E2E URL validation completed with active Ollama backend
- Real E2E TXT validation completed with Neo4j load path
- Semantic mapping upgraded: extracted entities now link to existing `Company`/`Tender`/`Project` by identifiers (`piva/cf/cig/cup`)

---

## 🗺️ Implementation Phases

### Phase 1: Text & PDF (The Foundation)
*Focus: Bandi di gara, Determine, Contratti, Verbali.*

*   **Extractors:** 
    *   `PyMuPDF` / `pdfplumber` for native PDFs.
    *   `Tesseract OCR` for scanned PDFs.
*   **LLM Task:** Extract `Person`, `Company`, `Location`, `Amount`, `CIG`, `CUP`.
*   **Deliverables:**
    *   `paladino/etl/universal_ingestor.py`
    *   `paladino/etl/extractors/pdf_extractor.py`
    *   `paladino/etl/ner_pipeline.py`
    *   `scripts/demo_universal_ingestion.py`

### Phase 2: Web & News (Contextualization)
*Focus: Albo Pretorio, News articles, Investigative journalism.*

*   **Extractors:**
    *   `trafilatura` (Local) for clean article extraction.
    *   `Firecrawl` / `Jina Reader API` (Cloud) for complex JS-heavy sites.
*   **LLM Task:** Link news events to existing companies/tenders in the graph.
*   **Deliverables:**
    *   `paladino/etl/extractors/web_extractor.py`

### Phase 3: Audio (Advanced Multimodal - Audio First)
*Focus: Consigli Comunali recordings, audizioni, meeting audio.*

> Decision update: Vision extraction is intentionally deferred. Phase 3 currently focuses only on audio ingestion/transcription.

*   **Extractors:**
  *   `faster-whisper` (Local) / `OpenAI Whisper`-compatible API fallback for audio transcription.
*   **Deliverables:**
    *   `paladino/etl/extractors/audio_extractor.py`

### Phase 3.1 (Deferred): Vision Extraction

*Status:* Deferred by product decision.

*   **Future Extractors:**
  *   `LLaVA` via Ollama (Local) / `GPT-4o Vision` (API) for image understanding.
*   **Future Deliverable:**
  *   `paladino/etl/extractors/vision_extractor.py`

---

## 🛠️ Technical Specifications

### 1. Standardized LLM JSON Output Schema
Regardless of the source, the `ner_pipeline.py` will force the LLM to output this exact JSON structure:

```json
{
  "entities": [
    {
      "id": "ent_01",
      "type": "Company",
      "properties": {
        "name": "Edilizia Rossi SRL",
        "vat_number": "01234567890"
      },
      "confidence": 0.95
    },
    {
      "id": "ent_02",
      "type": "Person",
      "properties": {
        "name": "Mario Bianchi",
        "role": "Dirigente"
      },
      "confidence": 0.88
    }
  ],
  "relationships": [
    {
      "source_id": "ent_02",
      "target_id": "ent_01",
      "type": "WORKS_FOR",
      "confidence": 0.90
    }
  ]
}
```

### 2. Graph Provenance (Crucial for Auditability)
Every node and relationship created by this engine MUST include the following properties in Neo4j:
*   `_source_file`: e.g., "determina_sindaco_123.pdf"
*   `_extraction_date`: ISO 8601 timestamp
*   `_extraction_method`: e.g., "ollama_llama3_8b" or "openai_gpt4o"
*   `_confidence_score`: Float between 0.0 and 1.0

### 3. Entity Resolution (The "Merge" Step)
Before creating new nodes, the system must query Neo4j to see if the entity already exists (e.g., matching VAT number or exact Company Name). 
*   If it exists: Create a new `MENTIONED_IN` relationship to the document.
*   If it doesn't exist: Create the new node and flag it as `status: "unverified_extracted"`.

---

## 🚀 Next Steps for Development

1.  **Phase 1 Hardening Status:** ✅ Completed
  - OCR fallback implemented
  - Router and NER unit tests implemented
  - Chunking and merge enabled for long docs
2.  **Live Schema Apply (Environment):**
  - Run `paladino preflight --for schema`
  - Run `python scripts/init_schema.py`
3.  **Real End-to-End Validation (Non-mocked):**
  - TXT/PDF path + optional Neo4j load
  - URL path + extraction + NER
4.  **Phase 2 Completion (Web Production Grade):**
  - Keep Trafilatura primary ✅
  - Add JS-heavy fallback connectors (Jina Reader / Firecrawl) ✅
5.  **Phase 3 Audio-first Stabilization:**
  - Validate faster-whisper transcription quality on real files
  - Tune transcription model/device settings for workstation limits

Operational reference:
- See `docs/UNIVERSAL_INGESTION_RUNBOOK.md` for rollout, monitoring, troubleshooting, and rollback.
