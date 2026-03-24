# Changelog

All notable changes to Paladino will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- CLI improvements:
  - Subprocess timeout protection (300s limit)
  - Proper exception handling for ETL script execution
  - Menu choice enums to avoid magic strings
  - Port validation (1-65535 range)
  - `--version` flag
- Security enhancements:
  - Regex-based Cypher injection blocklist with word boundaries
  - Generic error messages on health endpoint (no info leakage)
  - Parameterized Cypher queries in risk engine
  - SECURITY.md with vulnerability disclosure process
- Code quality:
  - Comprehensive type hints across all modules
  - Google-style docstrings for public APIs
  - Input validation for embeddings module
  - Fail-fast error handling in LLM manager
- Community files:
  - MIT LICENSE
  - CONTRIBUTING.md with development guidelines
  - CODE_OF_CONDUCT.md (Contributor Covenant 2.1)
  - GitHub issue templates (bug report, feature request)
  - GitHub pull request template

### Changed
- Refactored `risk_engine.py` to use parameterized queries instead of f-strings
- Updated `llm_manager.py` to raise exceptions instead of returning empty strings on error
- Moved `PALADIN_ART` and theme to shared `constants.py` module
- Explicit Click context passing in CLI (no more `get_current_context()`)
- Extracted stats functionality to standalone function (no full REPL overhead)
- Updated README with badges, architecture diagram, and improved documentation

### Fixed
- Cypher injection vulnerability with simple string matching (now uses regex)
- Race condition in batch checkpointing (atomic MERGE operations)
- Schema property name mismatch (camelCase → snake_case)
- Duplicate dependencies in `pyproject.toml`
- Test fixture pollution in `conftest.py`
- Import errors in `normalizer.py`
- Duplicate legal forms in `CompanyNormalizer.LEGAL_FORMS`

### Removed
- Hardcoded credentials from `config.py` (now required from environment)
- Duplicate `PALADIN_ART` constant from `investigator.py`

### Security
- **Critical**: Fixed Cypher injection vulnerability in LLM-generated queries
- **High**: Removed hardcoded Neo4j credentials
- **High**: Added subprocess timeout to prevent hanging ETL scripts
- **Medium**: Improved error handling to prevent information leakage

---

## [0.1.0] - 2026-02-18

### Added
- Initial release of Paladino
- Core infrastructure and Neo4j schema
- ANAC ETL pipeline for procurement data
- OpenCUP integration for project tracking
- ISTAT context for demographic data
- Entity resolution with LLM-judge deduplication
- GraphRAG agent for natural language queries
- FastAPI REST API with auto-generated docs
- Interactive CLI with Rich UI
- Risk analytics engine with anomaly detection
- Comprehensive test suite (85+ unit tests)
- Documentation (performance tuning, data model, provenance spec)

### Architecture
- Local-first design (16-32GB RAM optimized)
- Offline-capable (no cloud dependencies)
- Full provenance tracking for all data
- Polars-based ETL for efficient data processing
- Pydantic validation for type safety

### Tech Stack
- **Database**: Neo4j 5.16+
- **ETL**: Polars, Pandas
- **API**: FastAPI, Uvicorn
- **LLM**: LangChain, Ollama, OpenAI
- **CLI**: Click, Rich, Questionary
- **Testing**: pytest, mypy, ruff, black

---

## Legend

- **[Unreleased]**: Changes not yet released
- **[Added]**: New features
- **[Changed]**: Changes in existing functionality
- **[Deprecated]**: Soon-to-be removed features
- **[Removed]**: Removed features
- **[Fixed]**: Bug fixes
- **[Security]**: Security improvements

---

For more information on contributing, see [CONTRIBUTING.md](CONTRIBUTING.md).
For security issues, see [SECURITY.md](SECURITY.md).
