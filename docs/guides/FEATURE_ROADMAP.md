# 🛡️ Paladino: Current Capabilities & Feature Roadmap

**Document Date:** February 23, 2026  
**Purpose:** Inventory of implemented features and high-priority improvements

---

## Table of Contents

1. [Current Capabilities](#current-capabilities)
2. [Feature Improvement Categories](#feature-improvement-categories)
3. [Quick Wins](#quick-wins)
4. [Strategic Priorities](#strategic-priorities)

---

## Current Capabilities

### ✅ 1. Interactive Investigation (REPL Mode)

Users can launch the Investigator shell and perform:

- **Natural Language Queries** (Italian/English)
  - *"Mostra aziende che hanno vinto più gare in Sicilia"*
  - *"Quali progetti sono finanziati da PNRR?"*
  - *"Quali buyer hanno emesso più gare?"*

- **Pre-built Template Queries** (8 available)
  - Companies by region with tender counts
  - High-risk companies with anomaly flags
  - Top vendors by win count & total value
  - PNRR project analysis & funding sources
  - Regional spending breakdown
  - Network centrality/influence ranking
  - Project funding by source type
  - Tender-to-project linkage analysis

- **Result Export Formats**
  - JSON (raw data)
  - CSV (spreadsheet-compatible)
  - Markdown reports (formatted narratives)

---

### ✅ 2. REST API Server

Production-ready FastAPI endpoints:

```
POST   /query              Natural language questions
POST   /template           Structured templated queries
GET    /templates          List all available templates
GET    /health             System status & Neo4j connectivity
GET    /docs               Interactive Swagger UI
```

**Example Usage:**
```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Top 10 companies by tender wins", "limit": 10}'
```

---

### ✅ 3. Risk Analytics & Anomaly Detection

**Automated Risk Scoring (0.0 to 1.0):**

| Factor | Weight | Description |
|--------|--------|-------------|
| Single-bidder ratio | 40% | High % of unopposed tender wins |
| Market dominance | 30% | PageRank centrality (hub behavior) |
| Buyer concentration | 30% | Dependency on few buyers (favoritism indicator) |

**Graph Algorithms Available:**
- PageRank (identify influential companies)
- Louvain community detection (find market clusters)
- Betweenness centrality (network bridges)

**Anomaly Flags:**
- `high_single_bidder_ratio` - Wins without competition
- `market_dominance_high` - Hub topology
- `high_buyer_concentration` - Loyalty to few buyers

---

### ✅ 4. Multi-Source ETL Pipelines

**Integrated Data Sources:**

| Source | Volume | Status |
|--------|--------|--------|
| ANAC (Procurement Tenders) | 97K+ records | ✅ Complete |
| OpenCUP (Funded Projects) | 9.7M records | ✅ Complete |
| ISTAT (Demographics) | Bulk datasets | ✅ Complete |
| PNRR (Funding Source) | Metadata | ✅ Complete |
| Demanio/ARERA/MIT | Public assets | ✅ Partial |
| Registro Imprese | Company data | ✅ Integrated |

**Key Capabilities:**
- Download & cache data from external sources
- Transform & normalize across schemas
- Load into Neo4j graph
- Data quality validation
- **Cross-source entity linking:** 2,166+ tender↔project matches already mapped

---

### ✅ 5. System Administration

**Operator Capabilities:**

- **Graph Statistics Dashboard**
  - Node counts by type (Company, Tender, Project, etc.)
  - Relationship counts by type
  - Graph health metrics

- **LLM Configuration Wizard**
  - Ollama (local models)
  - OpenAI, Groq, Anthropic, custom APIs
  - Interactive model selection

- **Maintenance CLI**
  - Run individual ETL pipelines
  - Entity resolution (LLM judge)
  - GDS analytics suite
  - Schema initialization & validation

---

---

## Feature Improvement Categories

### **Category 1: Enhanced Intelligence & Insights**

#### 1.1 Advanced Risk Dashboard
**Problem:** Executives need visual risk heat maps by region/sector  
**Solution:** Build interactive dashboard showing:
- Regional risk scores (choropleth map)
- Risk by sector (ATECO classification)
- Timeline trends (quarterly/annual)
- Top 10 highest-risk companies
- Anomaly clustering

**Effort:** Medium (3-4 weeks)  
**Impact:** 🔴🔴🔴 High (enables decision-making)

---

#### ✅ 1.2 Temporal/Time-Series Analysis *(Implemented Feb 2026)*
**Problem:** Can't identify sudden spikes in suspicious procurement patterns  
**Solution:** Track over time:
- Single-bidder tender ratio trends
- Buyer concentration changes
- Company network evolution
- Sector-level spending volatility
- Seasonal patterns

**Use Case:** "Did this company's anomalies appear suddenly or gradually?"

**Effort:** Medium (2-3 weeks)  
**Impact:** 🔴🔴🔴 High (fraud detection)

**Delivered:**
- `paladino/analytics/temporal_analytics.py` — `TemporalAnalyzer` (7 methods)
- `scripts/migrate_date_types.py` — idempotent date migration
- `scripts/run_temporal_analysis.py` — CLI orchestrator (`--step all|migrate|trends|spikes|seasonal|sector|history`)
- Fixed `anac_loader.py` to store dates as native Neo4j `date` types
- Oracle section #9 (spike alerts), 4 new GraphRAG templates, `RiskEngine.save_risk_snapshot()`
- **31 new unit tests** (183 total passing)

---

#### 1.3 Supply Chain & Ownership Graph
**Problem:** Can't trace company→subcontractor→supplier networks  
**Solution:** Integrate:
- Board member overlaps (collusion risk)
- Beneficial owner analysis (shell company detection)
- Supply chain relationships
- Corporate structure hierarchies

**Business Case:** Detect carousel fraud (company A→B→C→A kickback schemes)

**Effort:** High (4-6 weeks)  
**Impact:** 🔴🔴🔴 High (reveals hidden relationships)

---

#### 1.4 Fraud Pattern Library
**Problem:** No pre-built detectors for known red flags  
**Solution:** Implement rule engine for:
- **Carousel fraud:** Cyclical payment patterns
- **Bid-rigging:** Identical bids from competitors
- **Ghost companies:** Zero employees, high spending
- **Political connections:** Board members = government officials
- **Geographic anomalies:** Tender issued in region A, winner from region Z without geographic justification

**Effort:** High (6-8 weeks)  
**Impact:** 🔴🔴🔴 High (actionable alerts)

---

### **Category 2: User Experience & Accessibility**

#### 2.1 Web Dashboard UI
**Problem:** REPL interface limits adoption; business users prefer GUI  
**Solution:**
- React frontend with:
  - Graph visualization (D3.js/Cypher visualization)
  - Filters & drill-downs
  - Company detail pages
  - Risk score heatmaps
  - Search results explorer
  - Export buttons

**Business Impact:** 10x more accessible to non-technical users

**Effort:** High (6-8 weeks for MVP)  
**Impact:** 🔴🔴 Medium (enables mass adoption)

---

#### 2.2 Multi-Language Support
**Problem:** EU/international users need localized interfaces  
**Solution:**
- Localization for UI (English, French, German)
- Query translation (allow Italian queries → English for LLM)
- Multi-language documentation

**Effort:** Medium (2-3 weeks)  
**Impact:** 🔴 Low-Medium (nice-to-have)

---

#### 2.3 Saved Investigations & Session Persistence
**Problem:** Users lose work when REPL closes  
**Solution:**
- SQLite session store
- Save queries with results
- Query history & replay
- Shared investigation templates
- Team collaboration (future)

**Effort:** Low (1-2 weeks)  
**Impact:** 🔴 Low-Medium (improves usability)

---

#### 2.4 Bulk Export & BI Integration
**Problem:** Researchers need Excel/Power BI exports  
**Solution:**
- Export to Excel with formatting
- CSV with metadata
- Power Query connectors
- Pivot table templates
- Scheduled exports

**Effort:** Low (1-2 weeks)  
**Impact:** 🔴 Low-Medium (analyst workflows)

---

### **Category 3: Data Quality & Completeness**

#### 3.1 Improved Entity Resolution (v2.0)
**Problem:** Currently ~49K companies; likely higher duplicates due to name variations  
**Solution:**
- Enhanced LLM-judge with:
  - Sector-specific matching (ATECO codes)
  - Address normalization
  - Email/phone comparisons
  - Web search validation
  - Cross-source confidence scoring

**Expected Impact:** Could increase unique companies from 49K → 70K+ (40% more)

**Effort:** High (6-8 weeks)  
**Impact:** 🔴🔴 Medium (data completeness)

---

#### 3.2 Beneficial Owner Tracking ✅
**Status:** Implemented (Feature 3.2 — 3 phases)  
**Problem:** Can't identify true company owners; shell corporations invisible  

**Implementation Phases:**

**Phase 1 — Data Source Integration** (completed)
- `paladino/etl/corporate/infocamere_downloader.py` — ANAC OpenData catalogue fetcher; ATOKA + OpenCorporates stubs; graceful degradation without API keys
- `paladino/etl/corporate/incremental_sync.py` — `CorporateSyncTracker`: persists `SyncCheckpoint` nodes; enables delta-only reprocessing
- `paladino/etl/corporate/__init__.py` — exports `RegistroImpreseFetcher`, `CorporateSyncTracker`
- `scripts/run_supply_chain_etl.py` — new `--step fetch-corporate-data` invokes `RegistroImpreseFetcher` then saves sync checkpoint

**Phase 2 — Enhanced Shell Company Detection** (completed)
- `paladino/analytics/shell_company_detector.py` — `ShellCompanyDetector` with 7-factor weighted model:
  - `legacy (0.30)` = existing tender-win + employee + depth heuristic
  - `vat_anomaly (0.15)` = wins contracts but VAT registration inactive
  - `dormancy (0.15)` = no financial filings for ≥ 2 years
  - `board_conc (0.15)` = single director on ≥ 20 boards
  - `supplier_only (0.10)` = company appears only as sub-contractor, never prime
  - `address_flag (0.10)` = shares registered address with other shell suspects
  - `depth_bonus (0.05)` = extra penalty for ownership chains deeper than 5 hops
  - **Thresholds**: ≥ 0.50 → `HIGH_RISK`, ≥ 0.35 → `MEDIUM_RISK`
- `paladino/constants.py` — new: `SHELL_VAT_ANOMALY_WEIGHT`, `SHELL_DORMANCY_YEARS`, `SHELL_BOARD_CONCENTRATION_MAX`, `SHELL_SCORE_FLAG_THRESHOLD`, `SHELL_SCORE_ALERT_THRESHOLD`
- `paladino/analytics/fraud_patterns.py` — new detector: `detect_shell_company_network()` clusters HIGH_RISK companies sharing directors or addresses; registered in `run_all_detectors()` as detector 14
- `paladino/analytics/ownership_graph.py` — new method: `score_shell_companies_enhanced()` delegates to `ShellCompanyDetector`; legacy `score_shell_companies()` preserved for backward compatibility

**Phase 3 — UBO Reports & API** (completed)
- `paladino/app/ubo_report_generator.py` — `UBOReportGenerator.generate(company_id, format)` supporting `json` | `md` | `csv`; assembles ownership chain, UBO extraction, shell risk score, fraud patterns, directors, supply chain
- `paladino/app/api.py` — new endpoint: `POST /ubo-report` (models: `UBOReportRequest`, `UBOReportResponse`)

**Tests:**
- `tests/test_infocamere_downloader.py` — 12 test cases; fully offline (HTTP mocked)
- `tests/test_shell_company_detector.py` — 15 test cases; mock Neo4j driver
- `tests/test_ubo_report_generator.py` — 18 test cases covering JSON / MD / CSV formats

**New graph elements:**
- `ShellRiskScore` nodes (linked via `HAS_SHELL_SCORE`)
- `SyncCheckpoint` nodes (incremental ETL tracking)
- `FraudPattern` of type `shell_company_network`

**Sources:**
- Registro Imprese / ANAC OpenData (free)
- ATOKA API (paid, optional via `ATOKA_API_KEY`)
- OpenCorporates API (paid, optional via `OPENCORPORATES_API_KEY`)

**Effort:** High (6-8 weeks estimated)  
**Impact:** 🔴🔴 High (fraud detection, EU AML compliance)

---

#### 3.3 Data Freshness & Incremental Updates
**Problem:** Current ETL does full reload; ANAC/OpenCUP data changes daily  
**Solution:**
- Delta sync (only new/modified records)
- Scheduled daily updates
- Change tracking (audit trail)
- Data versioning

**Effort:** Medium (3-4 weeks)  
**Impact:** 🔴 Low-Medium (operational efficiency)

---

#### 3.4 Complete Asset Integration (Demanio/ARERA/MIT)
**Problem:** Asset data is partially integrated; geographic coverage incomplete  
**Solution:**
- Full address normalization
- Spatial indexing (lat/lon)
- INVOLVES_ASSET relationship completeness
- Asset type classification

**Effort:** Medium (2-3 weeks)  
**Impact:** 🔴 Low-Medium (regional analysis)

---

### **Category 4: Advanced Analytics & Reasoning**

#### 4.1 Multi-Hop GraphRAG Queries
**Problem:** Current templates are basic; need truly complex reasoning  
**Solution:** Enable complex questions like:
- *"Companies that won PNRR+ANAC tenders AND have board members in high-risk sectors AND operate in regions with demographic decline"*
- *"Tenders issued by buyers who personally benefit from winner companies"*
- *"Suppliers to companies that later received government contracts"*

**Requires:** Enhanced GraphRAG agent with multi-step reasoning

**Effort:** High (6-8 weeks)  
**Impact:** 🔴🔴🔴 High (reveals deep connections)

---

#### 4.2 Anomaly Explanation Engine ✅
**Status:** Implemented (Feature 4.2)  
**Problem:** Users see risk score but don't know why  

**Implementation:**

- `paladino/analytics/anomaly_explainer.py` — `AnomalyExplainer` class
  - `explain(company_id)` → `ExplanationResult` assembling all contributing signals from the graph:
    - **Single-bidder win rate** — raw ratio, contribution to score, sentence citing actual tender count and percentage, source links (`Tender:<id>`)
    - **Market dominance (PageRank)** — centrality score vs. 0.50 threshold, human-readable verdict
    - **Buyer concentration** — dominant buyer name + ratio, flags dependency/favoritism
    - **Fraud pattern citations** — all `FraudPattern` nodes linked via `FLAGGED_BY`, with severity, confidence and description
    - **Shell company risk** — reads cached `ShellRiskScore` node or runs `ShellCompanyDetector` live
    - **Trend direction** — compares current score to `Version` history → `WORSENING | STABLE | IMPROVING`
    - **Evidence citation chain** — every claim traced back to its source graph node (Tender, Buyer, FraudPattern)
  - Auto-generated summary: *"This company scored 0.73 because: (1) 68% single-bidder wins, (2) PageRank = 0.58, (3) 90% buyer concentration."*
  - Renders to `json` | `md` | `text` via `ExplanationResult.render(format)`

- `paladino/app/api.py` — two new endpoints (tag: `Anomaly Explanation`):
  - `GET /explain/{company_id}?format=json` — quick lookup
  - `POST /explain` — full control (`ExplainRequest`: company_id, format, include_shell_risk)
  - `ExplainResponse` model: company_id, company_name, risk_score, risk_tier, trend, summary, report, generated_at

- `tests/test_anomaly_explainer.py` — 35 test cases; fully offline (mock Neo4j connection)
  - Factor values, contributions, sentences, source links
  - Trend classification (WORSENING / IMPROVING / STABLE)
  - Rendering in all three formats
  - Edge cases: no tenders, no fraud patterns, no history, company not found

**Example output:**
```
"This company scored 0.73 because: (1) 67% single-bidder wins,
 (2) PageRank = 0.58 (market dominance), (3) 90% buyer concentration."
```

**Effort:** Medium (3-4 weeks estimated)  
**Impact:** 🔴🔴 High (explainability — makes risk scores actionable)

---

#### 4.3 Predictive Risk Scoring
**Problem:** Can only assess historical behavior  
**Solution:**
- ML model trained on historical fraud patterns
- Predict risk for *new* tenders before they're issued
- Forecast company behavior changes
- Alert on trend reversals

**Effort:** High (8-10 weeks)  
**Impact:** 🔴🔴 Medium (proactive detection)

---

#### 4.4 Recommendation Engine ✅
**Status:** Implemented (Feature 4.4)  
**Problem:** Users don't know "what to look at next"

**Implementation:**

- `paladino/analytics/recommendation_engine.py` — `RecommendationEngine` class
  - `recommend(company_id, strategies, limit, min_similarity)` → `RecommendationResult`
  - Four graph-native strategies, all pure-Cypher (no external ML required):
    - **`content`** — feature-overlap similarity: same 2-digit ATECO sector (0.30) + same region (0.25) + risk-score proximity within ±0.15 (0.20) + anomaly-flags Jaccard (0.25)
    - **`community`** — same Louvain `community_id` property → co-cluster market actors (fixed score 0.85)
    - **`anomaly`** — Jaccard similarity on `anomaly_flags` arrays; only candidates sharing ≥ 1 flag retrieved
    - **`sector_trending`** — top-risk companies in same 2-digit ATECO sector, ordered by `risk_score` descending
  - `_merge()` deduplication: companies appearing in multiple strategies keep the highest similarity score; all matching strategies and shared features are accumulated
  - `RecommendationResult.render(format)` → `json` | `md` | `text`
  - `Recommendation` dataclass: `company_id`, `company_name`, `cf`, `risk_score`, `similarity_score`, `reason`, `strategies`, `shared_features`

- `paladino/app/api.py` — two new endpoints (tag: `Recommendations`):
  - `GET /recommend/{company_id}?strategies=content,community&limit=10&min_similarity=0.0&format=json`
  - `POST /recommend` — full control (`RecommendRequest`: company_id, strategies, limit, min_similarity, format)
  - `RecommendResponse` model: source_company_id, source_company_name, source_risk_score, source_risk_tier, recommendations, strategies_used, format, report, generated_at
  - Validators: unknown strategies → 422; invalid format → 422

- `tests/test_recommendation_engine.py` — 37 test cases; fully offline (mock Neo4j)
  - `TestRiskTier`, `TestJaccard`, `TestAteco2` — utility function coverage
  - `TestMerge` — 5 deduplication tests
  - `TestContentBased`, `TestCommunityBased`, `TestAnomalyBased`, `TestSectorTrending` — per-strategy tests
  - `TestRecommend` — 9 integration tests: result type, source fields, company-not-found, invalid strategy, limit, min_similarity filter, single strategy, source self-exclusion
  - `TestRendering` — 9 tests: JSON (valid + keys + strategies), MD (heading + company names + badge), text (source name + numbered list), invalid format
  - `TestEdgeCases` — 4 tests: empty results, as_dict round-trip, zero-risk source, strategy isolation

**Example output:**
```json
{
  "source_company_name": "COSTRUZIONI ROSSI SRL",
  "source_risk_tier": "HIGH",
  "recommendations": [
    {
      "company_name": "EDIL BIANCHI SPA",
      "similarity_score": 0.81,
      "strategies": ["community", "content"],
      "reason": "Same Louvain community (#5); same ATECO sector (41); similar risk score (delta 0.04).",
      "shared_features": ["community:5", "ATECO:41", "risk_delta<0.15"]
    }
  ]
}
```

**Effort:** Medium (4-5 weeks estimated)  
**Impact:** 🔴 Low-Medium (discovery feature — guides investigators to related actors)

---

### **Category 5: Integration & Interoperability**

#### 5.1 Slack/Teams Bot Integration
**Problem:** Alerts stay in isolation; users miss new anomalies  
**Solution:**
- Webhook bot for alerts
- "/paladino risk-spike Sicilia" command
- Scheduled daily digest
- Custom alert rules

**Effort:** Medium (2-3 weeks)  
**Impact:** 🔴 Low-Medium (notification)

---

#### 5.2 Embedded Analytics Widget
**Problem:** Journalists/analysts want to embed Paladino on their platforms  
**Solution:**
- iframe-able query interface
- Embeddable charts
- Standalone widget SDK
- Share query results as URLs

**Effort:** High (4-6 weeks)  
**Impact:** 🔴🔴 Medium (distribution)

---

#### 5.3 CSV/Custom Data Import ✅ *implemented*
**Problem:** Users have their own company/tender datasets  
**Solution:**
- CSV upload pipeline with auto-delimiter detection (`,` `;` `\t` `|`)
- Fuzzy column → graph-field mapping (Company `cf`/`nome`/`ateco`/`regione`, Tender `cig`/`oggetto`/`importo`/`buyer_name`)
- `column_map` override dict for non-standard headers
- MERGE into existing graph (Company / Tender / CustomRecord nodes)
- `dry_run` mode for preview without writes
- `POST /ingest/csv` FastAPI endpoint

**Files:** `paladino/etl/csv_importer.py`, `paladino/etl/universal_ingestor.py` (`import_csv()`), `paladino/app/api.py` (`POST /ingest/csv`), `tests/test_csv_importer.py`

**Effort:** Medium (3-4 weeks) → delivered  
**Impact:** 🔴🔴 Medium (extensibility)

---

#### 5.4 Real-Time Notifications
**Problem:** Users must manually check for new high-risk tenders  
**Solution:**
- Pub/Sub architecture
- Email/SMS alerts
- Webhook triggers
- User-defined alert rules

**Example:** Alert when tender issued matching criteria: `region="Sicilia" AND category="construction" AND value>500000`

**Effort:** Medium (3-4 weeks)  
**Impact:** 🔴 Low-Medium (real-time)

---

### **Category 6: Compliance & Trust**

#### 6.1 Data Provenance Certificates
**Problem:** Users need to prove "this came from official ISTAT"  
**Solution:**
- Downloadable provenance report per node
- Timestamp + source chain
- Cryptographic signature (optional)

**Effort:** Low (1 week)  
**Impact:** 🔴 Low (compliance)

---

#### 6.2 Access Control & Multi-Tenant Support
**Problem:** Currently local-first; enterprise users need role-based access  
**Solution:**
- User authentication (OAuth2/OIDC)
- Role-based access control (RBAC)
  - Admin (full access)
  - Analyst (query + export)
  - Viewer (read-only dashboards)
  - Limited (restricted to region/sector)
- Audit logs (who accessed what, when)
- Multi-organization support

**Effort:** High (6-8 weeks)  
**Impact:** 🔴🔴 Medium (enterprise readiness)

---

#### 6.3 GDPR Compliance Report Generator
**Problem:** Data controllers need proof of GDPR compliance  
**Solution:**
- Generate compliance certificate
- Data retention policies
- Deletion audit trail
- Purpose limitation statements
- Consent log

**Effort:** Low (1-2 weeks)  
**Impact:** 🔴 Low (compliance)

---

---

## Quick Wins

**These 3 features can be delivered in 1-2 weeks each with high utility:**

### ⚡ 1. Investigation History & Session Persistence
**What:** Save and resume REPL sessions

**How:**
- SQLite local DB to store sessions
- Save/load commands: `session save my_investigation`
- Query history with timestamps
- Export full session transcript

**Files to Modify:**
- `paladino/app/investigator.py` (add session manager)
- `paladino/db.py` (add SQLite session store)

**Impact:** Users don't lose work on REPL exit

---

### ⚡ 2. Saved Queries / Favorites
**What:** Users can save and share custom queries

**How:**
- JSON files with query metadata
- Save: `query save --name "Top vendors in Lombardia" --query "..."`
- Load: `query load top_vendors_lombardia`
- Share via GitHub/email

**Files to Modify:**
- `paladino/app/graphrag_agent.py` (query persistence)
- `paladino/app/investigator.py` (CLI commands)

**Impact:** Reusable queries for team

---

### ⚡ 3. Sector-Grouped Risk Dashboard
**What:** Top N companies by risk, grouped by sector

**How:**
- Query per sector (using ATECO codes)
- Generate CSV with risk breakdown
- Create pivot table template
- Visual sector heatmap (matplotlib/seaborn)

**Files to Modify:**
- `paladino/analytics/risk_engine.py` (add sector grouping)
- `paladino/app/report_generator.py` (add sector report)

**Impact:** Executives see risk at sector level

---

---

## Strategic Priorities

### **For Maximum Business Impact (Rank Order)**

1. **Web Dashboard UI** (6-8 weeks)
   - *Why:* REPL limits adoption; businesses need visual interface
   - *Outcome:* 10x more users can access Paladino
   - *Tech:* React + D3.js + FastAPI

2. **Advanced GraphRAG Queries** (6-8 weeks)
   - *Why:* Current templates too simplistic; miss complex relationships
   - *Outcome:* Answer real investigative questions
   - *Tech:* Enhance LangChain agent with multi-hop reasoning

3. **Entity Resolution 2.0** (6-8 weeks)
   - *Why:* More complete company coverage unlocks better analysis
   - *Outcome:* 40%+ more companies found + linked
   - *Tech:* Enhanced LLM judge + sector-specific matching

4. **Fraud Pattern Library** (6-8 weeks)
   - *Why:* Current anomaly detection generic; need specific red flags
   - *Outcome:* Detect carousel fraud, bid-rigging, shell companies
   - *Tech:* Rule engine + ML classifiers

5. **Beneficial Owner Tracking** (6-8 weeks)
   - *Why:* Shell corporations & hidden ownership invisible
   - *Outcome:* Identify true decision-makers
   - *Tech:* Ownership graph integration

---

### **For Safety & Compliance (Rank Order)**

1. **Anomaly Explainability** ✅ (3-4 weeks — *implemented*)
   - *Why:* Risk scores without explanations aren't actionable
   - *Outcome:* Users understand *why* something is risky
   - *Tech:* Narrative generation + evidence chains

2. **Access Control** (6-8 weeks)
   - *Why:* Local-first doesn't scale to teams/enterprises
   - *Outcome:* RBAC, audit logs, multi-org support
   - *Tech:* OAuth2 + role-based middleware

3. **Provenance Tracking Enhancement** (1-2 weeks)
   - *Why:* Already built but underdeveloped
   - *Outcome:* Downloadable certifications
   - *Tech:* Metadata reports + signatures

---

### **For Operational Efficiency (Rank Order)**

1. **Data Freshness & Incremental Updates** (3-4 weeks)
   - *Why:* Current full reload is inefficient
   - *Outcome:* Daily updates with delta sync
   - *Tech:* Change data capture

2. **Session Persistence** (1-2 weeks)
   - *Why:* Users lose work on REPL exit
   - *Outcome:* Save/resume investigations
   - *Tech:* SQLite session store

3. **Real-Time Notifications** (3-4 weeks)
   - *Why:* Manual checking misses new anomalies
   - *Outcome:* Alerts via email/Slack
   - *Tech:* Pub/Sub + webhooks

---

## Summary Table

| Feature | Effort | Impact | Priority |
|---------|--------|--------|----------|
| **Web Dashboard UI** | High | 🔴🔴 | 🥇 #1 |
| **Advanced GraphRAG Queries** | High | 🔴🔴🔴 | 🥇 #2 |
| **Entity Resolution v2** | High | 🔴🔴 | 🥇 #3 |
| **Fraud Pattern Library** | High | 🔴🔴🔴 | 🥇 #4 |
| **Beneficial Owner Tracking** | High | 🔴🔴 | 🥇 #5 |
| **Anomaly Explainability** | Medium | 🔴🔴 | ✅ Done |
| **Recommendation Engine** | Medium | 🔴 | ✅ Done |
| **CSV / Custom Data Import** | Medium | 🔴🔴 | ✅ Done |
| **Access Control** | High | 🔴🔴 | 🥈 #7 |
| Session Persistence | Low | 🔴 | ⚡ QUICK WIN |
| Saved Queries | Low | 🔴 | ⚡ QUICK WIN |
| Sector Risk Dashboard | Low | 🔴 | ⚡ QUICK WIN |

---

**Next Steps:** Choose which feature to implement first, and I'll provide detailed technical specifications + implementation plan.
