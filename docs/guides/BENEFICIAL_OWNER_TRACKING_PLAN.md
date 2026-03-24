# 🎯 Feature 3.2: Beneficial Owner Tracking — Implementation Plan

**Date:** February 24, 2026  
**Status:** Planning (groundwork from Feature 1.3 re-usable; gaps identified)  
**Est. Total Effort:** 5-7 weeks (3 phased releases)  
**Business Impact:** 🔴🔴 Medium-High — Enables shell company detection & fraud prosecution

---

## Executive Summary

Feature 1.3 (Supply Chain & Ownership Graph) delivered **50% of the infrastructure** needed for 3.2:
- ✅ Ownership chain traversal (`OwnershipGraphAnalyzer`)
- ✅ Shell company scoring algorithm
- ✅ UBO conflict detection (fraud detector)
- ✅ Corporate ETL framework & CSV parser

**This plan fills the gaps:**
- 🟡 API integrations (Registro Imprese, ATOKA, Infocamere)
- 🟡 Enhanced shell-company heuristics (VAT, bank patterns)
- 🟡 Beneficial owner report generator + certificates
- 🟡 Ownership visualization dashboard

---

## Current State (From Feature 1.3)

### What's Already Built

| Component | File | Status | Gaps |
|-----------|------|--------|------|
| **Ownership Chain Traversal** | `paladino/analytics/ownership_graph.py` | ✅ Complete | Works with loaded data only |
| **Shell Company Scoring** | `OwnershipGraphAnalyzer.score_shell_companies()` | ✅ Complete | Limited to 2 heuristics (tender wins + employees) |
| **Corporate ETL** | `paladino/etl/corporate/` | ✅ Framework ready | Manual CSV only; no API integrations |
| **UBO Conflict Detector** | `FraudPatternLibrary.detect_ubo_conflict()` | ✅ Complete | Part of fraud suite; needs reporting |
| **GDS Ownership PageRank** | `GDSManager.run_ownership_pagerank()` | ✅ Complete | Computes influence; lacks visualization |
| **Corporate Family Query** | `OwnershipGraphAnalyzer.get_corporate_family()` | ✅ Complete | Good for API; no dashboard |

### Data Ingestion Today
```
data/corporate/raw/
├── directors.csv          ← Manual drop-in  (supports: cf_azienda, cf_persona, ruolo)
├── shareholders.csv       ← Manual drop-in  (supports: cf_azienda, cf_socio, quota)
└── (future: ATOKA API)
```

**Limitations:**
- No automatic fetch from official sources
- Requires users to manually download & place files
- No data freshness / incremental updates

---

## Phase 1: Data Source Integrations (3 weeks)

### Goal
Enable **automatic data fetch** from Registro Imprese (+ API options for future).

### 1.1 Registro Imprese OpenData Integration

**Scope:**
- Implement downloader for Italian ANAI/Infocamere OpenData feed
- Parse directors + shareholding files
- Schedule daily incremental updates
- Auto-merge with existing corporate graph

**Files to Create/Modify:**
```
paladino/etl/corporate/
├── download.py                    (ADD: RegistroImprese downloader class)
├── infocamere_downloader.py       (NEW)
└── incremental_sync.py            (NEW)
```

**Key Decisions:**
1. **Data Source:** Use free OpenData feed from ANAI (published weekly)
   - Alternative (paid): Infocamere/Telemaco API for real-time updates
   - Plan: Free first, premium as optional module

2. **Incremental Updates:**
   - Track last_sync timestamp in Neo4j metadata
   - Only fetch records modified after last_sync
   - Idempotent MERGE to avoid duplicates

3. **Conflict Resolution:**
   - If same company/person has conflicting data (e.g., different employee count):
     - Keep most recent data but record provenance
     - Flag with `data_quality_score` (0.0–1.0)

**Effort:** 2–2.5 weeks  
**Deliverables:**
- `RegistroImpresDownloader` class
- CLI command: `paladino maintenance --step fetch-corporate-data`
- Integration tests

**Testing:**
- Mock 100-row sample from OpenData feed
- Unit tests for parser
- Integration test: verify all 3 relationship types created

---

### 1.2 ATOKA API Integration (Optional, For Later)

**Scope *(deferred to Phase 2 or 3)*:**
- Optional paid API for enriched director/shareholder data
- Triggers on-demand when `ATOKA_API_KEY` is set
- Augments graph with verified director histories, company status

**Why Deferred:**
- Free Registro Imprese sufficient for MVP
- ATOKA adds cost; prioritize free sources first

**Would Include:**
- `AtokaDirDownloader` class
- Rate-limiting (API quota: 10K calls/month per tier)
- Caching layer to avoid re-fetching

---

## Phase 2: Enhanced Shell Company Detection (2 weeks)

### Goal
**Improve shell-company flagging** beyond basic heuristics (tender-wins + employee count).

### 2.1 Expand Heuristic Set

**Current Heuristics (from 1.3):**
```python
shell_score = (win_factor + emp_factor + depth_factor) / 3.0
  win_factor   = tender_wins / 100
  emp_factor   = 1.0 if employees ≤ 5 else 0.0
  depth_factor = 1.0 if ownership_depth ≥ 3 else 0.5 if ≥1 else 0.0
```

**New Heuristics to Add:**
1. **VAT Anomaly**
   - Company has 0 VAT registrations but wins government contracts
   - Suggests recent creation or shell status
   - Weight: 15%

2. **Dormancy Flag**
   - Last financial statement > 2 years old
   - Or never filed financial statements
   - Weight: 15%

3. **Board Concentration**
   - Same person on > 20 company boards
   - Or > 50% of active companies are one-person boards
   - Weight: 15%

4. **Supplier-Only Pattern**
   - Company only ever appears as subcontractor, never as prime
   - Or 95%+ of revenue from single customer
   - Weight: 10%

5. **Missing Address Red Flags**
   - No registered address or shared address (mailbox rental)
   - Weight: 10%

**Updated Formula:**
```python
shell_score = (
    0.30 * legacy_score          # existing win/emp/depth
  + 0.15 * vat_anomaly_score
  + 0.15 * dormancy_score
  + 0.15 * board_concentration_score
  + 0.10 * supplier_only_score
  + 0.10 * address_flag_score
  + 0.05 * ownership_depth_bonus    # deeper chains = riskier
)
# threshold: shell_score > 0.5 → flag as shell candidate
```

**Files to Create/Modify:**
```
paladino/analytics/
├── shell_company_detector.py    (NEW)  ← Advanced heuristics
└── ownership_graph.py           (EDIT) ← Integrate new detector
```

**Data Requirements:**
- VAT records (from ISTAT or external source)
- Financial statement dates (from Registro Imprese)
- Address classifications (mailbox vs. real)

**Effort:** 1.5–2 weeks  
**Deliverables:**
- `ShellCompanyDetector` class with 5+ methods
- Neo4j stored procedures for scalar heuristics
- Unit tests (mock data scenarios)
- Calibration on known shell companies (if available)

---

### 2.2 Integrate into Fraud Pattern Library

**Scope:**
- New fraud detector: `detect_shell_company_network()`
- Flags networks of shells controlled by same UBO
- Example: UBO controls 15 companies, all with shell_score > 0.7
- Creates `FraudPattern` node linking all companies

**Files to Modify:**
```
paladino/analytics/fraud_patterns.py  ← Add shell_network detector
```

**Effort:** Part of Phase 2 (0.5–1 week)  
**Deliverables:**
- New detector method
- Integration into `run_all_detectors()`
- Test coverage

---

## Phase 3: Beneficial Owner Reports & Dashboard (2 weeks)

### Goal
**Generate actionable reports & visual dashboards** for analysts.

### 3.1 Beneficial Owner Report Generator

**Scope:**
Create multi-format beneficial owner reports on demand.

**Report Contents:**

```
╔════════════════════════════════════════════════════════════════╗
║            BENEFICIAL OWNER ANALYSIS REPORT                   ║
║  Company: Alfa Srl  (CF: 12345678901)                          ║
║  Generated: 2026-02-24  |  Data Sources: Registro Imprese      ║
╠════════════════════════════════════════════════════════════════╣

1. ULTIMATE BENEFICIAL OWNERS (UBOs)
   ├─ Mario Rossi (CF: RSSMRA65B20H501J)
   │  └─ Ownership Chain Depth: 2
   │  └─ Total Companies Controlled: 15
   │  └─ Risk Indicator: ⚠️ HIGH (15 companies, avg shell_score 0.68)
   │
   └─ Lucia Bianchi (via BianchiHolding Srl) (50% quota)
      └─ Ownership Chain Depth: 3
      └─ Controlled Companies: 8

2. SHELL COMPANY ASSESSMENT
   └─ Shell Score: 0.72 (HIGH RISK)
   └─ Flags:
      • 12 tender wins without competition (single-bidder 95%)
      • Ownership depth: 3 levels
      • Board concentration: 1 person on 5 boards
      • VAT: Never registered
      • Address: Shared mailbox (Via Roma 123, Milano)

3. CORPORATE FAMILY
   Siblings under same UBO (Mario Rossi):
   ├─ Beta Srl      (CF: ...) — Government contractor
   ├─ Gamma Srl     (CF: ...) — Supplier to public sector
   ├─ Delta Srl     (CF: ...) — Shell candidate (score 0.81)
   └─ [11 more companies]

4. FRAUD INDICATORS
   ├─ UBO Conflict: 3 tenders where Alfa won despite buyer-founder overlap
   ├─ Board Overlaps: Shares 2 board members with Delta Srl (competitor)
   └─ Carousel Risk: Not detected

5. RECOMMENDATIONS
   🔴 HIGH PRIORITY
   • Request beneficial owner disclosure under EU UBO registry
   • Cross-check board member backgrounds vs. conflict of interest
   • Audit last 3 tenders (high single-bidder ratio)

6. AUDIT TRAIL
   Last Updated: 2026-02-24 14:32:10 UTC
   Data Sources: Registro Imprese (2026-02-20), ANAC Tenders (2026-02-23)
   Certifying Officer: paladino-v1.0
   [Digital Signature: ...]
```

**Files to Create:**
```
paladino/app/
├── ubo_report_generator.py    (NEW)  ← Report composition
└── ubo_visualizer.py          (NEW)  ← Export formats (JSON, PDF, MD, CSV)
```

**Formats to Support:**
1. **JSON** — Machine-readable, API responses
2. **Markdown** — GitHub, documentation, email
3. **PDF** — Official documents, audit trails
4. **CSV** — Bulk export for spreadsheet analysis

**Effort:** 1 week  
**Deliverables:**
- `UBOReportGenerator` class
- Export to 4+ formats
- Digital signature capability (optional)
- Unit tests

---

### 3.2 Ownership Structure Dashboard (Future: Post-Phase 3)

**Scope *(deferred to separate feature or Phase 4)*:**
- Web UI showing ownership hierarchies
- Interactive graph visualization (D3.js)
- Drill-down to individual relationships
- Risk heatmap overlay

**Why Deferred:**
- Requires web frontend (separate effort)
- Overlaps with Feature 2.1 (Web Dashboard UI)
- Core analysis (3.1) more valuable first

**Would Include:**
- React component for ownership tree
- Neo4j Cypher integration for real-time queries
- Risk coloring (red/yellow/green based on shell_score)

---

## Success Criteria

### Phase 1 Complete
- [ ] Registro Imprese auto-download working
- [ ] Directors & shareholding data merged into graph
- [ ] CLI: `paladino maintenance --step fetch-corporate-data`
- [ ] At least 50K new director records loaded
- [ ] Data quality test: spot-check 100 companies for accuracy

### Phase 2 Complete
- [ ] Shell company detection expands from 2→5 heuristics
- [ ] `shell_score` now incorporates VAT, dormancy, board concentration
- [ ] New fraud detector: `detect_shell_company_network()`
- [ ] Unit tests cover all 5 heuristics
- [ ] Calibration: validation against known shell companies

### Phase 3 Complete
- [ ] Report generator produces all 4 formats (JSON, MD, PDF, CSV)
- [ ] Sample reports generated for 10+ companies
- [ ] Digital signature / tamper-proof capability
- [ ] API endpoint: `POST /api/ubo-report?company_id=...`
- [ ] Markdown reports render correctly in GitHub

---

## Technical Debt & Known Risks

### Risk: Data Quality From Registro Imprese
- **Issue:** OpenData feed may have stale/duplicate records
- **Mitigation:**
  - Implement data quality scoring (confidence_score per record)
  - Flag conflicting records for manual review
  - Prefer most recent + largest Delta companies

### Risk: Performance With Deep Ownership Chains
- **Issue:** Traversing 10+ levels of SHAREHOLDER_OF relationships is expensive
- **Current Workaround:** GDS PageRank pre-computes influence; query caches results
- **Future Optimization:** Materialized view (aggregate UBO ID at write-time)

### Risk: False Positives in Shell Detection
- **Issue:** Legitimate contractors may trigger shell heuristics (e.g., specialized vendor)
- **Mitigation:**
  - Separate `shell_score` (0.0–1.0) from boolean `is_shell` flag
  - Flag as "shell candidate" with confidence bands: [0.5–0.7], [0.7–0.85], [0.85–1.0]
  - Require manual analyst review before enforcement

### Risk: Registro Imprese Data Lag
- **Issue:** Public data may be 1–2 months behind real changes
- **Approach:** Accept for MVP, implement paid API tier (Infocamere) later if needed

---

## Effort Breakdown

| Phase | Component | Weeks | FTE |
|-------|-----------|-------|-----|
| **1** | Registro Imprese Downloader | 2.0 | 1 |
| **1** | Incremental Sync & Conflict Resolution | 0.5 | 0.5 |
| **2** | Enhanced Shell Detection (5 heuristics) | 1.5 | 1 |
| **2** | Shell Network Fraud Detector | 0.5 | 0.5 |
| **3** | Report Generator | 1.0 | 1 |
| **3** | Export Formats (JSON/MD/PDF/CSV) | 1.0 | 1 |
| Testing & Buffer | — | 1.0 | 1 |
| **TOTAL** | — | **7.5 weeks** | ~1.5 FTE |

**Realistic Timeline:** 6–7 weeks for one developer  
**With Polish:** 8–10 weeks for production-ready feature

---

## Dependencies & Prerequisites

### External APIs (Needed by Phase 1)
- [ ] ANAI OpenData feed URL (open access, free)
- [ ] Registro Imprese OpenData format documentation
- [ ] Sample CSV files (5 directors + 5 shareholders format)

### Internal Code (From Feature 1.3)
- ✅ `OwnershipGraphAnalyzer` — already done
- ✅ Corporate ETL framework — already done
- ✅ GDS Manager with PageRank — already done
- ⚠️  Need: Unit test coverage for new detectors

### Infrastructure
- ✅ Neo4j running (existing)
- ✅ Polars for CSV parsing (existing dependency)
- 🟡 Python-pptx for PDF generation (add to `pyproject.toml`)
- 🟡 ReportLab for advanced PDF (optional, add if needed)

---

## Rollout Strategy

### Phase 1 (Weeks 1–3)
- Merge code to `feature/registro-imprese` branch
- Release internal beta: `v0.2.0-beta.1`
- Manual testing against real Registro Imprese data
- Gather feedback on data quality

### Phase 2 (Weeks 4–5)
- Merge shell detection improvements
- Release `v0.2.0-beta.2`
- Calibrate heuristics against sample shell companies
- Document in Oracle (#15: "Shell Company Network Detection")

### Phase 3 (Weeks 6–7)
- Merge report generator
- Release `v0.2.0` (Feature Complete)
- Add API documentation
- Deploy to production

---

## Future Enhancements (Post-3.2)

1. **Dashboard UI** — Visualization of ownership trees (ties to Feature 2.1)
2. **Automated Daily Reports** — Email beneficial owner summaries to analysts
3. **Predictive UBO Changes** — ML model forecasting ownership restructuring
4. **Integration with GDPR** — Beneficial owner data subject request automation
5. **Premium API Tier** — Infocamere/Telemaco real-time data for paid users

---

## Files & Checklists

### Phase 1 Checklist
- [ ] `paladino/etl/corporate/infocamere_downloader.py` (new)
- [ ] `paladino/etl/corporate/incremental_sync.py` (new)
- [ ] `paladino/etl/corporate/download.py` — add `RegistroImpresDownloader` class
- [ ] `scripts/run_supply_chain_etl.py` — add `--step fetch-corporate-data` option
- [ ] `tests/unit/test_infocamiere_downloader.py` (new)
- [ ] `tests/integration/test_corporate_sync.py` (new)
- [ ] Update `README.md` with setup instructions for free data sources

### Phase 2 Checklist
- [ ] `paladino/analytics/shell_company_detector.py` (new)
- [ ] `paladino/analytics/ownership_graph.py` — integrate shell detector
- [ ] `paladino/analytics/fraud_patterns.py` — add `detect_shell_company_network()`
- [ ] `tests/unit/test_shell_company_detector.py` (new)
- [ ] `tests/unit/test_shell_network_detector.py` (new)
- [ ] Update Oracle templates with shell detection queries

### Phase 3 Checklist
- [ ] `paladino/app/ubo_report_generator.py` (new)
- [ ] `paladino/app/ubo_visualizer.py` (new)
- [ ] `paladino/app/api.py` — add `POST /ubo-report` endpoint
- [ ] `tests/unit/test_ubo_report_generator.py` (new)
- [ ] `tests/integration/test_ubo_api.py` (new)
- [ ] Sample reports generated & validated
- [ ] API documentation in Swagger

---

## Decision Questions for Stakeholders

1. **Data Freshness:** Acceptable to use weekly ANAI feed (1 week lag), or pay for daily Infocamere API?
   - **Recommendation:** Start free, add premium tier in Phase 3.

2. **Shell Score Threshold:** Where to set the "flag" boundary? (Currently assumed 0.5, but could be 0.6–0.7)
   - **Recommendation:** Calibrate on existing known-shell-company list if available.

3. **Priority:** Phase 3 (Report Generator) — high value but lower urgency than Phases 1–2?
   - **Recommendation:** Yes. Prioritize data + detection (1–2), delay reports to later.

4. **Export to Compliance Tools:** Should reports integrate with Excel/Tableau/Power BI?
   - **Recommendation:** CSV export now (built-in), formal BI connectors in future.

---

**Next Step:** Confirm stakeholder decisions above, then kick off Phase 1 development.
