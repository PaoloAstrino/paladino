# Technical Architecture & Implementation Reference

## Table of Contents
1. [System Architecture](#system-architecture)
2. [Data Model Deep Dive](#data-model-deep-dive)
3. [ETL Architecture](#etl-architecture)
4. [Entity Resolution Strategies](#entity-resolution-strategies)
5. [Query Optimization](#query-optimization)
6. [Deployment & Scaling](#deployment--scaling)

---

## System Architecture

### High-Level Architecture Diagram (Text)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Data Sources (External)                       │
├────────────┬──────────────┬──────────────┬──────────┬──────┬────────┤
│   ANAC     │   OpenCUP    │  Registro    │  ISTAT   │Demanio│ARERA  │
│  OCDS API  │  CSV/API     │   Imprese    │  API     │  API  │ Data  │
│  200k rec  │  150k rec    │  Limited (*)  │ Bulk data│Spatial│Energy │
└────────────┴──────────────┴──────────────┴──────────┴──────┴────────┘
                               ↓ Downloads
                        ┌──────────────┐
                        │  Data Cache  │
                        │ (S3/GCS)     │
                        └──────────────┘
                               ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    ETL Pipeline (Polars-based)                      │
├────────┬────────────┬────────────┬─────────────┬──────────┬────────┤
│Download│ Transform  │  Validate  │   Enrich   │ Resolve  │ Merge  │
│ & Cache├(normalization,          │ (sectors,  │(dedup)   │(IDG)   │
│        │ aggregation)│(quality)   │ anomaly)   │          │        │
└────────┴────────────┴────────────┴─────────────┴──────────┴────────┘
                               ↓ Cypher Scripts
┌─────────────────────────────────────────────────────────────────────┐
│                    Neo4j Knowledge Graph                            │
│  ┌─────────┬──────────┬──────────┬──────────┬──────────┬────────┐  │
│  │Company  │ Tender   │ Project  │ Context  │  Asset   │ Sector │  │
│  │Nodes    │ Nodes    │ Nodes    │ Nodes    │ Nodes    │ Nodes  │  │
│  └─────────┴──────────┴──────────┴──────────┴──────────┴────────┘  │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Relationships: WINS, PART_OF, FUNDED_BY, LOCATED_IN, etc.  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ Full-Text Indexes, Spatial Indexes, Temporal Indexes       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                               ↓ API/Queries
        ┌──────────────────────────────────────────┐
        │  Query Layer (Cypher + LangChain Agent)  │
        └──────────────────────────────────────────┘
                               ↓
        ┌──────────────────────────────────────────┐
        │  GraphRAG Agent (Multi-hop Reasoning)    │
        │  ├─ Anomaly Detection                    │
        │  ├─ Risk Scoring                         │
        │  └─ Cross-source Analysis                │
        └──────────────────────────────────────────┘
                               ↓
        ┌──────────────────────────────────────────┐
        │     FastAPI Server (Local REST API)      │
        │  Endpoints: /query, /companies, /anomalies
        └──────────────────────────────────────────┘
                               ↓
        ┌──────────────────────────────────────────┐
        │  Frontend (React Dashboard)              │
        │  ├─ Query Builder                        │
        │  ├─ Visualization (Graph + Tables)       │
        │  └─ Anomaly Explorer                     │
        └──────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Technology |
|-----------|-----------------|------------|
| **Data Download** | Fetch from ANAC, OpenCUP, ISTAT, etc. (cached) | Requests, Polars |
| **Transform** | Normalize schemas, compute derived fields | Polars, Python |
| **Validate** | Quality checks, flag issues | Polars, Pydantic |
| **Enrich** | Add sectors, risk scores, context | Scikit-learn, Custom |
| **Resolve** | Entity deduplication, clustering | Custom algorithms |
| **Load** | Bulk insert to Neo4j (idempotent) | Neo4j Bolt driver |
| **Index/Query** | Optimize queries, expose via API | Neo4j Cypher |
| **Agent** | Multi-hop reasoning, NL→Query | LangChain, GPT-4 |
| **API** | REST endpoints, caching, validation | FastAPI, Redis |
| **Frontend** | Interactive explorer | React, D3.js |

---

## Data Model Deep Dive

### Node Types with Full Property Schemas

#### **Company Node**

```cypher
CREATE CONSTRAINT unique_company_cf ON (c:Company) ASSERT c.cf IS UNIQUE;
CREATE CONSTRAINT unique_company_piva ON (c:Company) ASSERT c.piva IS UNIQUE;
CREATE INDEX idx_company_nome ON NODES (c:Company) FOR (c.nomeNormalizzato);

// Node structure:
node Company {
  // Identifiers (Unique)
  id: String (UUID, internal)
  cf: String (Codice Fiscale) [UNIQUE]
  piva: String (Partita IVA) [UNIQUE, nullable]
  
  // Names
  nomeNormalizzato: String (uppercase, stripped)
  nomeOriginale: String
  
  // Location
  provincia: String (2-letter code)
  regione: String
  comune: String
  indirizzo: String
  
  // Classification
  ateco: String (6-digit sector code, e.g., "64.99")
  ateco_desc: String (human-readable)
  dimensione: String enum ["microimpresa", "PMI", "Grande"]
  
  // Financial/Status
  formaGiuridica: String (e.g., "Società a responsabilità limitata")
  dataCostituzione: Date
  dataEstinzione: Date (if defunct)
  
  // Risk & Analytics
  riskScore: Float [0-1]
  anomalyFlags: List<String>
  concentration_ratio: Float (% of wins in region)
  
  // Provenance
  source: List<String> ["ANAC", "RegistroImprese", "ISTAT"]
  datasetVersion: String (e.g., "2026-01")
  retrievalDate: DateTime
  confidence: Float [0-1] (overall match confidence)
  lastUpdated: DateTime
  
  // Relationships tracked
  tenderWinCount: Integer (cached)
  averageWinAmount: Float (cached)
}

#### **Version Node (Temporal History)**

```cypher
node Version {
  id: String (UUID)
  entityId: String (CIG, CUP, or CF)
  property_changed: String
  old_value: String
  new_value: Date/Float/String
  change_date: DateTime
  source: String
}
// Linked via (Entity)-[HAS_HISTORY]->(Version)
```
```

#### **Tender Node**

```cypher
CREATE CONSTRAINT unique_tender_cig ON (t:Tender) ASSERT t.cig IS UNIQUE;
CREATE INDEX idx_tender_date ON NODES (t:Tender) FOR (t.dataAggiudicazione);

node Tender {
  // Identifiers
  id: String (UUID)
  cig: String (Codice Identificativo Gara) [UNIQUE]
  ocid: String (OCDS ID)
  
  // Content
  oggetto: String (tender title/description)
  descrizioneEstesa: String (full text, searchable)
  
  // Financial
  importo: Float (in EUR)
  importoSMA: Float (base amount before award)
  importoRibasso: Float (discount)
  
  // Procedure & Timing
  procedura: String enum ["open", "restricted", "negotiated", "competitive_dialogue"]
  dataApertura: Date (tender publication)
  dataAggiudicazione: Date (award date) [indexed for temporal queries]
  dataInizioLavori: Date (contract start)
  dataFineProgettuale: Date (planned end)
  dataFineEffettiva: Date (actual end)
  durata_giorni: Integer (duration)
  
  // Classification
  categorie_cpc: List<String> (product/service codes)
  lotti: Integer (number of lots)
  
  // Anomalies/Flags
  red_flags: List<String>
  single_bidder: Boolean (only 1 offer received?)
  winner_count: Integer (normally 1, >1 for lots)
  
  // Provenance
  source: String "ANAC"
  datasetVersion: String
  retrievalDate: DateTime
  confidence: Float
}
```

#### **Project Node (OpenCUP)**

```cypher
CREATE CONSTRAINT unique_project_cup ON (p:Project) ASSERT p.cup IS UNIQUE;

node Project {
  // Identifiers
  id: String (UUID)
  cup: String (Codice Unico Progetto) [UNIQUE]
  cupa: String (old format, if present)
  
  // Content
  titolo: String
  descrizione: String (full project scope)
  
  // Categorization
  settore: String enum [
    "INFRASTRUTTURE_TRASPORTI",
    "AMBIENTE_ENERGIA",
    "RICERCA_INNOVAZIONE",
    "COESIONE_TERRITORIALE",
    "SOCIALE_SALUTE",
    etc.
  ]
  
  // Financing
  importoPrevisto: Float (original budget)
  importoFinanziato: Float (approved budget)
  importoDPCM: Float (central gov allocation)
  importoRegione: Float (regional co-financing)
  fondiComunitari: List<String> ["PNRR", "FESR", "FSE", etc.]
  
  // Timeline
  dataInizio: Date
  dataFine: Date
  stato: String enum [
    "In programmazione",
    "In attuazione",
    "Concluso",
    "Sospeso",
    "Cancellato"
  ]
  percentualeCompletamento: Float [0-100]
  
  // Location
  provincia: String
  regione: String
  coordinate: Point (geospatial)
  
  // Provenance
  source: String "OpenCUP"
  datasetVersion: String
  retrievalDate: DateTime
}
```

#### **DatasetContext Node (ISTAT)**

```cypher
node DatasetContext {
  // Identifiers
  id: String (UUID)
  cod_istat: String (ISTAT geographic code)
  
  // Location reference
  tipo_geo: String enum ["comune", "provincia", "regione"]
  geo_name: String
  geo_code: String
  
  // Metric data
  metrica: String (e.g., "popolazione", "pil_procapite", "disoccupazione")
  valore: Float or String (the actual value)
  anno: Integer
  
  // Metadata
  fonte: String "ISTAT" or "Regione_X"
  datasetVersion: String
  retrievalDate: DateTime
  quality: Float [0-1]
}

#### **ISTAT Taxonomic Stability Strategy**
To handle the evolution of Italian municipalities (fusions, code changes):
1. **Evolution Graph:** Map `(m:Municipality)-[:EVOLVED_INTO]->(m2:Municipality)`
2. **Canonical Identifiers:** Use the latest ISTAT code as the primary key, maintaining historical codes as aliases.
3. **Temporal Mapping:** Queries automatically traverse the evolution path if a historical code is provided.
```

#### **Asset Node (Demanio/ARERA/MIT)**

```cypher
node Asset {
  // Identifiers
  id: String (UUID)
  codice: String (original asset code)
  
  // Type
  tipo: String enum [
    "immobile",
    "infrastruttura_trasporto",
    "rete_energia",
    "rete_acqua",
    "terreno"
  ]
  descrizione: String
  
  // Location & Physical Data
  indirizzo: String
  provincia: String
  regione: String
  coordinate: Point
  superficie_mq: Float
  
  // Financial/Administrative
  valore_catastale: Float
  valore_mercato: Float
  stato_manutenz: String enum ["ottimo", "buono", "mediocre", "pessimo"]
  
  // Provenance
  source: String enum ["Demanio", "ARERA", "MIT"]
  datasetVersion: String
}
```

### Relationship Types

```cypher
// Company → Tender
(Company)-[WINS {
  data: Date,
  importo: Float,
  percentuale_del_importo: Float,
  numero_ricorsi: Integer,
  source: String,
  confidence: Float
}]->(Tender)

// Tender → Buyer
(Tender)-[AWARDED_BY {
  data: Date
}]->(Buyer)

// Tender → Project (via CUP-CIG matching)
(Tender)-[PART_OF_PROJECT {
  confidence: Float,
  matching_method: String enum ["explicit", "temporal", "semantic"],
  match_date: DateTime
}]->(Project)

// Project → Funding Source
(Project)-[FUNDED_BY {
  importo: Float,
  percentuale: Float,
  fonte: String
}]->(FundingSource)

// Company → Location (via ISTAT context)
(Company)-[LOCATED_IN {
  distance_km: Float
}]->(DatasetContext)

// Project → Asset
(Project)-[INVOLVES_ASSET {
  ruolo: String enum ["principale", "secondario"],
  tipo_intervento: String
}]->(Asset)

// Company → Company (via shareholder/UBO relationships)
(Company)-[SHARES_UBO {
  percentuale: Float,
  cf_persona: String,
  ruolo: String
}]->(Company)

// Company → Sector
(Company)-[OPERATES_IN_SECTOR {
  peso: Float
}]->(Sector {cod: String, descrizione: String})

// Provenance relationships
(Node)-[HAS_PROVENANCE {
  retrieved_at: DateTime
}]->(Provenance {
  source: String,
  dataset_version: String,
  confidence: Float
})
```

---

## ETL Architecture

### Pipeline Flow & Error Handling

```python
# Pseudocode for complete ETL flow

class ETLOrchestrator:
    def run_full_pipeline(self):
        sources = ["anac", "opencup", "registro", "istat", "demanio"]
        
        for source in sources:
            try:
                # Phase 1: Download
                raw_data = self.download(source)
                
                # Phase 2: Validate
                validation_report = self.validate(raw_data)
                if validation_report.critical_issues > 0:
                    self.logger.error(f"{source}: Critical issues, aborting")
                    self.slack_notify("ETL_FAILED", source)
                    continue
                
                # Phase 3: Transform
                normalized = self.transform(raw_data)
                
                # Phase 4: Enrich
                enriched = self.enrich(normalized)
                
                # Phase 5: Resolve (deduplicate)
                if source != "anac":  # ANAC is baseline
                    enriched = self.resolve_duplicates(enriched)
                
                # Phase 6: Load (idempotent)
                load_stats = self.load(enriched, source)
                
                # Phase 7: Verify
                if not self.verify_load(source, load_stats):
                    self.logger.error(f"{source}: Verification failed, rolling back")
                    continue
                
                # Phase 8: Index refresh
                self.refresh_indexes()
                
                # Logging
                self.audit_log.record({
                    "source": source,
                    "timestamp": datetime.now(),
                    "records_loaded": load_stats.count,
                    "duration_sec": load_stats.duration,
                })
                
                self.slack_notify("ETL_SUCCESS", source, load_stats)
                
            except Exception as e:
                self.logger.exception(f"ETL failed for {source}")
                self.slack_notify("ETL_ERROR", source, str(e))
                # Continue with next source (resilience)
```

### Transformation Logic for Each Source

**ANAC OCDS → Graph Nodes:**

```python
def transform_anac_ocds(release: dict) -> Dict[str, List[dict]]:
    """
    OCCS JSON release → [Tender, Company, Buyer, Contract] nodes
    """
    
    result = {
        "tenders": [],
        "companies": [],
        "buyers": [],
        "contracts": [],
    }
    
    # Each OCDS release has records
    for record in release.get("records", []):
        # Usually 1 release per record (latest)
        release_data = record.get("releases", [{}])[0]
        
        # === TENDER NODE ===
        tender = {
            "cig": release_data.get("ocid"),
            "ocid": release_data.get("ocid"),
            "oggetto": release_data.get("tender", {}).get("title"),
            "importo": extract_amount(release_data),
            "dataAggiudicazione": extract_date(release_data, "award_date"),
            "procedura": release_data.get("tender", {}).get("procurementMethod"),
            "source": "ANAC",
            "datasetVersion": "2026-01",
            "retrievalDate": datetime.now(),
        }
        result["tenders"].append(tender)
        
        # === COMPANY NODES (from supplier) ===
        for contract in release_data.get("contracts", []):
            for award in contract.get("awards", []):
                for supplier in award.get("suppliers", []):
                    company = {
                        "cf": supplier.get("id"),  # CF or VAT
                        "piva": normalize_piva(supplier.get("id")),
                        "nomeNormalizzato": normalize_name(supplier.get("name")),
                        "source": ["ANAC"],
                    }
                    result["companies"].append(company)
                    
                    # === WINS RELATIONSHIP ===
                    win = {
                        "company_cf": supplier.get("id"),
                        "tender_cig": tender["cig"],
                        "importo": award.get("value", {}).get("amount"),
                        "data": award.get("date"),
                    }
                    result["wins"].append(win)
        
        # === BUYER NODE ===
        buyer_data = release_data.get("parties", [{}])[0]  # Usually buyer is first
        buyer = {
            "cf": buyer_data.get("id"),
            "nome": buyer_data.get("name"),
            "tipo": buyer_data.get("classification", {}).get("scheme"),
        }
        result["buyers"].append(buyer)
    
    return result
```

### Data Quality Checks

```python
class DataQualityValidator:
    
    # Critical fields (MUST be present)
    CRITICAL_FIELDS = {
        "tenders": ["cig", "importo"],
        "companies": ["cf"],
        "projects": ["cup"],
    }
    
    # Expected value ranges/distributions
    VALID_RANGES = {
        "importo_eur": (1000, 1_000_000_000),  # 1k to 1B EUR
        "dataAggiudicazione": (date(2020, 1, 1), date.today()),
    }
    
    def quality_report(self, df: pl.DataFrame, source: str) -> Dict:
        report = {
            "total_records": len(df),
            "issues": [],
        }
        
        # Check critical fields
        for field in self.CRITICAL_FIELDS.get(source, []):
            missing = df[field].is_null().sum()
            if missing > 0:
                report["issues"].append({
                    "type": "missing_critical_field",
                    "field": field,
                    "count": missing,
                    "severity": "critical" if missing > len(df) * 0.01 else "warning",
                })
        
        # Check value ranges
        for field, (min_val, max_val) in self.VALID_RANGES.items():
            if field in df.columns:
                out_of_range = df[(df[field] < min_val) | (df[field] > max_val)]
                if len(out_of_range) > 0:
                    report["issues"].append({
                        "type": "out_of_range",
                        "field": field,
                        "count": len(out_of_range),
                        "severity": "medium",
                    })
        
        # Compute quality score
        critical_issues = len([i for i in report["issues"] if i["severity"] == "critical"])
        report["quality_score"] = max(0, 1.0 - (critical_issues / max(1, len(df)) * 0.1))
        
        return report
```

---

## Entity Resolution Strategies

### Blocking Strategies (Reduce Comparison Space)

```python
class BlockingStrategies:
    """Pre-filter candidate pairs before expensive scoring"""
    
    @staticmethod
    def blocking_exact_match(df: pl.DataFrame) -> List[Tuple[str, str]]:
        """
        Exact match on critical field (CF, PIVA, or both)
        High precision, low recall
        """
        pairs = []
        grouped = df.group_by(["cf"]).agg(pl.col("id"))
        
        for group in grouped.rows():
            ids = group[1]
            if len(ids) > 1:
                pairs.extend(combinations(ids, 2))
        
        return pairs
    
    @staticmethod
    def blocking_token_based(df: pl.DataFrame, min_overlap: int = 2) -> List[Tuple]:
        """
        Tokenize company names; pairs share N+ tokens
        Medium precision, medium recall
        """
        from itertools import combinations
        
        # Index company names by token
        token_to_companies = defaultdict(list)
        
        for row in df.iter_rows(named=True):
            tokens = row["nomeNormalizzato"].split()
            for token in tokens:
                token_to_companies[token].append(row["id"])
        
        # Find pairs sharing N tokens
        pairs = set()
        for companies in token_to_companies.values():
            if len(companies) > 1:
                for id1, id2 in combinations(sorted(companies), 2):
                    pairs.add((id1, id2))
        
        return list(pairs)
    
    @staticmethod
    def blocking_phonetic(df: pl.DataFrame) -> List[Tuple]:
        """
        Phonetic (Soundex/Metaphone) on company names
        Lower precision, higher recall (catches typos)
        """
        from fuzzywuzzy import fuzz
        
        pairs = []
        
        for i, row1 in df.iter_rows(named=True):
            for j, row2 in df.iter_rows(named=True):
                if i >= j:
                    continue
                
                ratio = fuzz.token_sort_ratio(
                    row1["nomeNormalizzato"],
                    row2["nomeNormalizzato"]
                )
                
                if ratio > 80:  # >80% similarity
                    pairs.append((row1["id"], row2["id"], ratio))
        
        return pairs
```

### Scoring Functions (Rank Candidate Pairs)

```python
class EntityScoringFunctions:
    """Score similarity between candidate entity pairs"""
    
    @staticmethod
    def cf_score(cf1: str, cf2: str) -> float:
        """CF exact match → 0.99, else 0"""
        return 0.99 if cf1 and cf1 == cf2 else 0.0
    
    @staticmethod
    def name_similarity_score(name1: str, name2: str) -> float:
        """Levenshtein ratio on names"""
        from Levenshtein import ratio
        return ratio(name1.upper(), name2.upper())
    
    @staticmethod
    def location_score(prov1: str, prov2: str) -> float:
        """Same provincia → 1.0, else 0.3"""
        return 1.0 if prov1 and prov1 == prov2 else 0.3
    
    @staticmethod
    def sector_score(ateco1: str, ateco2: str) -> float:
        """Same ATECO sector → 1.0; same 2-digit → 0.5"""
        if not ateco1 or not ateco2:
            return 0.5  # Neutral
        
        if ateco1 == ateco2:
            return 1.0
        elif ateco1[:2] == ateco2[:2]:
            return 0.5
        else:
            return 0.0
    
    @staticmethod
    def combined_score(
        cf_score, name_score, location_score, sector_score,
        weights=(0.5, 0.3, 0.1, 0.1)
    ) -> float:
        """
        Weighted combination
        CF dominates (50%), then name (30%), location (10%), sector (10%)
        """
        return (
            cf_score * weights[0] +
            name_score * weights[1] +
            location_score * weights[2] +
            sector_score * weights[3]
        )
```

### Clustering Algorithm

```python
class EntityClusterer:
    """Group similar entities into clusters"""
    
    def hierarchical_cluster(
        self, pairs: List[Tuple[str, str, float]], threshold: float = 0.85
    ) -> Dict[str, str]:
        """
        Hierarchical clustering to form entity clusters
        Returns mapping: {entity_id -> canonical_id}
        """
        from scipy.cluster.hierarchy import linkage, fcluster
        import numpy as np
        
        # Build distance matrix from scores
        all_ids = set()
        for id1, id2, score in pairs:
            all_ids.add(id1)
            all_ids.add(id2)
        
        id_to_idx = {id_: idx for idx, id_ in enumerate(sorted(all_ids))}
        
        # Create condensed distance matrix
        distances = []
        for id1, id2, score in pairs:
            dist = 1.0 - score  # Convert similarity to distance
            distances.append(dist)
        
        if len(distances) == 0:
            return {}  # No clusters
        
        # Hierarchical clustering
        Z = linkage(distances, method="average")
        cluster_labels = fcluster(Z, threshold, criterion="distance")
        
        # Map to canonical entity
        mapping = {}
        for cluster_id in set(cluster_labels):
            members = [
                id_ for id_, label in zip(all_ids, cluster_labels)
                if label == cluster_id
            ]
            canonical = min(members)  # Lowest ID as canonical
            for member in members:
                mapping[member] = canonical
        
        return mapping
```

---

## Query Optimization

### Index Strategy

```cypher
// Text search on company names
CREATE TEXT INDEX idx_company_name ON NODES (c:Company) FOR (c.nomeNormalizzato);
CREATE TEXT INDEX idx_tender_oggetto ON NODES (t:Tender) FOR (t.oggetto);
CREATE TEXT INDEX idx_project_descrizione ON NODES (p:Project) FOR (p.descrizione);

// Point/Spatial indexes (if using Neo4j Spatial or PostGIS hybrid)
CREATE POINT INDEX idx_project_location ON NODES (p:Project) FOR (p.coordinate);
CREATE POINT INDEX idx_asset_location ON NODES (a:Asset) FOR (a.coordinate);

// Date indexes for temporal queries
CREATE INDEX idx_tender_date ON NODES (t:Tender) FOR (t.dataAggiudicazione);
CREATE INDEX idx_project_start ON NODES (p:Project) FOR (p.dataInizio);

// Lookup indexes for filtering
CREATE INDEX idx_company_cf ON NODES (c:Company) FOR (c.cf);
CREATE INDEX idx_company_regione ON NODES (c:Company) FOR (c.regione);
CREATE INDEX idx_tender_importo ON NODES (t:Tender) FOR (t.importo);
CREATE INDEX idx_project_status ON NODES (p:Project) FOR (p.stato);

// Composite indexes for common join filters
CREATE INDEX idx_company_regione_sector ON NODES (c:Company) FOR (c.regione, c.ateco);
```

### Example: Complex Multi-Hop Query

**Question:** *"Show me companies in Veneto with >5 ANAC wins totaling >€500k, that also have active PNRR projects"*

**Naive Cypher (slow):**
```cypher
MATCH (c:Company {regione: "Veneto"})
MATCH (c)-[w:WINS]->(t:Tender)
MATCH (t)-[po:PART_OF_PROJECT]->(p:Project)
MATCH (p)-[fb:FUNDED_BY]->(fs:FundingSource {tipo: "PNRR"})
WHERE p.stato = "In attuazione"
  AND w.importo > 0
RETURN c, collect(distinct t) as tenders, collect(distinct p) as projects
```

**Optimized Cypher (faster):**
```cypher
// Strategy: Filter early on indexed columns
MATCH (c:Company {regione: "Veneto"})
WHERE c.tenderWinCount >= 5  // Pre-computed, cached property
WITH c WHERE c.averageWinAmount * c.tenderWinCount > 500000  // Early filter

MATCH (c)-[w:WINS]->(t:Tender)
WITH c, t, w WHERE w.importo > 0

// Aggregation to reduce cardinality
WITH c, sum(w.importo) as total_amount, count(t) as win_count
WHERE total_amount > 500000 AND win_count >= 5

// Only then join to projects
MATCH (c)-[:LOCATED_IN]->(:DatasetContext)
MATCH (p:Project {stato: "In attuazione"})
MATCH (p)-[:FUNDED_BY]->(fs:FundingSource {tipo: "PNRR"})
WHERE p.regione = c.regione  // Further filter by region

RETURN c, win_count, total_amount, collect(distinct p.cup) as pnrr_projects
LIMIT 100
```

**Optimization Tricks:**
1. **Use cached properties** (tenderWinCount, averageWinAmount)
2. **Filter by indexed columns first** (regione, stato, tipo)
3. **Aggregate early** to reduce downstream cardinality
4. **Spatial proximity filters** (POINT distance) before complex joins
5. **LIMIT result sets** (pagination)

---

## Deployment & Scaling

### Deployment Architecture (Production)

```
┌─────────────────────────────────────────────────────────────┐
│                    GCP / AWS Cloud                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐  ┌──────────────────┐                │
│  │  Cloud Scheduler │──→ ETL Trigger      │ (Weekly)       │
│  └──────────────────┘  └──────────────────┘                │
│          ↓                                                  │
│  ┌──────────────────────────────────────┐                 │
│  │   Cloud Run (ETL Container)          │                 │
│  │   ├─ Download sources                │                 │
│  │   ├─ Transform + Enrich              │                 │
│  │   └─ Load to Neo4j                   │                 │
│  └──────────────────────────────────────┘                 │
│          ↓                                                  │
│  ┌──────────────────────────────────────┐                 │
│  │   Neo4j AuraDB (Managed)             │                 │
│  │   ├─ Primary instance (write)        │                 │
│  │   └─ Read replica (HA setup)         │                 │
│  └──────────────────────────────────────┘                 │
│          ↓                                                  │
│  ┌──────────────────────────────────────┐                 │
│  │   Redis (Cache Layer)                │                 │
│  │   ├─ Query result cache              │                 │
│  │   └─ Session store                   │                 │
│  └──────────────────────────────────────┘                 │
│          ↓                                                  │
│  ┌──────────────────────────────────────┐                 │
│  │   Cloud Run (API Container)          │                 │
│  │   ├─ FastAPI server                  │                 │
│  │   ├─ GraphRAG agent                  │                 │
│  │   └─ Load balanced (autoscale)       │                 │
│  └──────────────────────────────────────┘                 │
│          ↓                                                  │
│  ┌──────────────────────────────────────┐                 │
│  │   Cloud Storage (Data Lake)          │                 │
│  │   ├─ Raw downloads (ANAC, OpenCUP)   │                 │
│  │   ├─ Processed datasets              │                 │
│  │   └─ Backup + audit logs             │                 │
│  └──────────────────────────────────────┘                 │
│          ↓                                                  │
│  ┌──────────────────────────────────────┐                 │
│  │   Cloud Logging + Monitoring         │                 │
│  │   ├─ ETL logs (structured)           │                 │
│  │   ├─ Query performance metrics       │                 │
│  │   └─ Alerting (Slack/PagerDuty)      │                 │
│  └──────────────────────────────────────┘                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Scaling Considerations

**For 1M+ nodes:**

1. **Database Sharding** (if needed)
   - By region (Veneto, Piemonte, etc.)
   - By entity type (companies vs tenders)
   - Federation queries via Neo4j Fabric (Enterprise)

2. **Query Caching**
   - Redis for hot queries (company profiles, anomalies)
   - TTL: 1 day for fact data, 1 hour for derived metrics

3. **Read Replicas**
   - Neo4j HA setup (primary + replicas)
   - Route read queries to replicas
   - Heavy aggregations on replicas

4. **Async Processing**
   - Long-running queries → Celery tasks (task queue)
   - Return job ID, user polls for results
   - Export to CSV/JSON async

5. **Columnar Analytics** (Optional, for OLAP)
   - ClickHouse or DuckDB for analytical queries
   - Nightly denormalization from Neo4j → ClickHouse
   - Fast aggregations over large datasets

### Monitoring & Alerting

```python
# Monitoring setup (using Prometheus + Grafana or equivalent)

class MetricsCollector:
    def __init__(self):
        self.metrics = {
            "etl_duration_sec": Histogram("ETL pipeline duration (seconds)"),
            "records_loaded": Counter("Total records loaded"),
            "data_quality_score": Gauge("Data quality score (0-1)"),
            "query_latency_ms": Histogram("API query latency (ms)"),
            "graph_node_count": Gauge("Total nodes in graph"),
            "graph_relationship_count": Gauge("Total relationships"),
            "cache_hit_rate": Gauge("Redis cache hit rate (%)"),
            "neo4j_heap_usage": Gauge("Neo4j heap usage (%)"),
        }
    
    def record_etl_metric(self, source: str, duration_sec: float, record_count: int):
        self.metrics["etl_duration_sec"].observe(duration_sec)
        self.metrics["records_loaded"].inc(record_count)
        self.logger.info(f"ETL {source}: {record_count} records in {duration_sec}s")

# Alerting rules (Prometheus AlertManager)
ALERT_RULES = """
groups:
  - name: etl_alerts
    interval: 5m
    rules:
      - alert: ETL_FAILURE
        expr: etl_last_success_time_ago > 86400  # 24h
        for: 1h
        annotations:
          summary: "ETL failed for {{ $labels.source }}"

      - alert: DATA_QUALITY_DROP
        expr: data_quality_score < 0.80
        annotations:
          summary: "Data quality dropped below 80%"

      - alert: QUERY_LATENCY_HIGH
        expr: histogram_quantile(0.95, query_latency_ms) > 2000
        annotations:
          summary: "p95 query latency > 2 seconds"
"""
```

---

## Conclusion

This technical architecture provides a scalable, auditable, multi-source knowledge graph for Italian public spending. Key design principles:

1. **Federated** – Multiple independent sources merged gracefully
2. **Provenance-rich** – Full lineage tracking for auditability
3. **Scalable** – Supports 1M+ nodes with sub-2s query latency
4. **AI-ready** – Designed for GraphRAG reasoning + anomaly detection
5. **Production-hardened** – Error handling, monitoring, deployment automation

---

## Local Performance Tuning (Single Workstation)

For high-performance execution on a laptop or workstation:

| Parameter | Recommended Setting (16GB RAM) | Recommended Setting (32GB RAM) |
|-----------|--------------------------------|--------------------------------|
| `dbms.memory.heap.initial_size` | 4G | 8G |
| `dbms.memory.heap.max_size` | 4G | 8G |
| `dbms.memory.pagecache.size` | 6G | 16G |
| `dbms.tx_state.memory_allocation` | OFF_HEAP | OFF_HEAP |

**Optimization Rules:**
1. **NVMe Placement:** Ensure Neo4j data directory is on an NVMe SSD to minimize IO wait during graph traversal.
2. **Bulk Loading:** Use `neo4j-admin database import` for initial bulk loads to bypass the transaction log overhead.
3. **Pruning:** Regularly prune the `Version` nodes if they exceed 20% of the total node count, archiving to Parquet if needed.

---

**End of Technical Architecture Document**
