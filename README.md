# 🛡️ Paladino - Italian Public Funds Knowledge Graph

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](http://mypy-lang.org/)
[![Citation](https://img.shields.io/badge/cite-CITATION.cff-orange.svg)](CITATION.cff)

> **Multi-source knowledge graph integrating Italy's public spending data (ANAC, OpenCUP, ISTAT, Demanio, ARERA, MIT)**

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Documentation](#documentation)
- [Development](#development)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)
- [Citation](#citation)

---

## Overview

Paladino builds a federated knowledge graph to enable sophisticated cross-source analysis of Italian public spending:

- **🏛️ Procurement** - ANAC tenders and awards
- **📊 Funded Projects** - OpenCUP project tracking
- **🏢 Corporate Structures** - Company relationships and ownership
- **📈 Socio-Economic Context** - ISTAT demographics
- **🏗️ Public Assets** - Demanio, ARERA, MIT property data

**Key Feature:** GraphRAG-powered agent for multi-hop reasoning queries like:

> "Which companies won ANAC tenders AND have PNRR projects in regions with demographic decline?"

## Features

- 🔍 **Semantic Search** - Vector embeddings for natural language queries
- 🤖 **GraphRAG Agent** - LLM-powered query generation with security controls
- 📊 **Risk Analytics** - Automated anomaly detection for procurement patterns
- 🔄 **Entity Resolution** - LLM-judge deduplication across sources
- 🛡️ **Provenance Tracking** - Full audit trail for all data
- 💻 **Local-First** - Runs on a single workstation (16-32GB RAM)
- 🔒 **Offline-Capable** - No cloud dependencies required

## Quick Start

### Prerequisites

- Docker Desktop
- Python 3.11+
- 16GB+ RAM recommended

### Setup

```bash
# 1. Clone repository
git clone https://github.com/YOUR_USERNAME/paladino.git
cd paladino

# 2. Start Neo4j
docker-compose up -d

# 3. Install dependencies
pip install -e ".[dev]"

# 4. Configure environment
cp .env.example .env
# Edit .env with your Neo4j credentials

# 5. Initialize schema
python scripts/init_schema.py

# 6. Run tests
pytest

# 7. Launch the CLI
paladino
```

### Usage

```bash
# Interactive investigation mode
paladino investigate

# Start the API server
paladino work --port 8000

# View graph statistics
paladino stats

# Check env prerequisites before schema/ingestion tasks
paladino preflight --for all

# Configure LLM (choose from Ollama models or set API key)
paladino configure-llm

# Run ETL pipelines
python scripts/run_anac_etl.py

# Ingest unstructured source (PDF/TXT/URL) with smart routing
paladino ingest-unstructured --source path/to/document.pdf

# Audio-first Phase 3: transcribe and ingest audio files
paladino ingest-unstructured --source path/to/meeting_audio.mp3

# Tune chunking for long documents
paladino ingest-unstructured --source path/to/long_report.txt --max-chars 8000 --chunk-overlap 300
```

### Universal Ingestion API

```bash
# Process unstructured source
curl -X POST http://localhost:8000/ingest/unstructured \
  -H "Content-Type: application/json" \
  -d '{"source": "path/to/note.txt", "to_neo4j": false, "max_chars": 12000, "chunk_overlap": 400}'

# Known structured sources are bypassed with ETL routing hints
curl -X POST http://localhost:8000/ingest/unstructured \
  -H "Content-Type: application/json" \
  -d '{"source": "data/pnnr/PNRR_Soggetti.csv"}'

# Web extraction fallback chain: Trafilatura -> Jina Reader -> Firecrawl (if FIRECRAWL_API_KEY set)
```

### OCR Requirements (for scanned PDFs)

- Python packages are installed via project dependencies: `pytesseract`, `Pillow`.
- System binary required: Tesseract OCR must be installed and available in PATH.
- Windows install tip: install "Tesseract OCR" and ensure `tesseract.exe` is resolvable from terminal.

### LLM Runtime Requirements (for real extraction)

- Local mode: run Ollama and ensure `http://localhost:11434` is reachable.
- API mode: set `PALADINO_LLM_API_KEY` and `PALADINO_LLM_API_BASE`.
- Without an available LLM backend, ingestion can extract raw text but cannot complete NER/relationship extraction.

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌─────────────┐
│  Data Sources   │ ──► │  ETL Pipeline    │ ──► │  Neo4j      │ ──► │  GraphRAG   │
│  ANAC, OpenCUP  │     │  (Polars)        │     │  Graph      │     │  Agent      │
│  ISTAT, Demanio │     │                  │     │             │     │             │
└─────────────────┘     └──────────────────┘     └─────────────┘     └─────────────┘
                                                                        │
                                                                        ▼
                                                               ┌─────────────┐
                                                               │  FastAPI    │
                                                               │  REST API   │
                                                               └─────────────┘
```

## Documentation

### Project Documentation

| Document | Description |
|----------|-------------|
| [Contributing Guide](CONTRIBUTING.md) | How to contribute to Paladino |
| [Code of Conduct](CODE_OF_CONDUCT.md) | Community guidelines and expectations |
| [Security Policy](SECURITY.md) | Reporting vulnerabilities |
| [Changelog](CHANGELOG.md) | Version history and changes |
| [License](LICENSE) | MIT License |

### Technical Documentation

| Document | Description |
|----------|-------------|
| [Performance Tuning](docs/PERFORMANCE_TUNING.md) | Optimization guide for large datasets |
| [Data Model](docs/DATA_MODEL.md) | Complete schema reference |
| [Provenance Spec](docs/PROVENANCE_SPEC.md) | Data lineage tracking |
| [Universal Ingestion Runbook](docs/UNIVERSAL_INGESTION_RUNBOOK.md) | Deployment and operations checklist |
| [Architecture Decision Records](docs/ADRs/) | Architectural decisions and rationale |

## Development

### Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=paladino

# Specific test file
pytest tests/unit/test_llm_manager.py
```

### Code Quality

```bash
# Linting
ruff check paladino/

# Type checking
mypy paladino/

# Formatting
black paladino/
```

### Project Structure

```
paladino/
├── schema/              # Neo4j schema definitions
├── etl/                 # ETL pipelines per source
├── ml/                  # Entity resolution models
├── app/                 # GraphRAG agent & API
├── analytics/           # Risk analytics & GDS
├── tests/               # Test suite
├── docs/                # Documentation
└── scripts/             # Utility scripts
```

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for:

- Development setup instructions
- Coding standards and style guide
- Testing requirements
- Pull request process

Before contributing, please read our [Code of Conduct](CODE_OF_CONDUCT.md) to help maintain a welcoming and inclusive community.

### Ways to Contribute

- 🐛 Report bugs
- ✨ Request features
- 📝 Improve documentation
- 💻 Submit code fixes
- 🧪 Add test cases

## Security

We take security seriously. Please see our [Security Policy](SECURITY.md) for:

- How to report vulnerabilities
- Security best practices
- Supported versions

**Important:** Never commit `.env` files or credentials to the repository.

For security-related code changes, please review the [CODEOWNERS](.github/CODEOWNERS) file for required reviewers.

## License

This project is licensed under the [MIT License](LICENSE).

## Citation

If you use Paladino in your research, please cite it using the [CITATION.cff](CITATION.cff) file:

```bibtex
@software{paladino,
  title = {Paladino: Italian Public Funds Knowledge Graph},
  version = {0.1.0},
  year = {2026},
  license = {MIT},
  url = {https://github.com/paladino-project/paladino}
}
```

## Acknowledgments

- Data sources: ANAC, OpenCUP, ISTAT
- Built with: Neo4j, Polars, FastAPI, LangChain
- Inspired by: GraphRAG research

---

<p align="center">
  <strong>🛡️ Paladino - Justice & Data</strong>
</p>
