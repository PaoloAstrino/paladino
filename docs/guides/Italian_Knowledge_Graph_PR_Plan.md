# PR Plan: Italian Public Funds & Entities Knowledge Graph
## Multi-Source Integration (ANAC, OpenCUP, ISTAT, Demanio, ARERA, MIT)

**Project Duration:** 12-16 weeks  
**Target Release:** Multi-source MVP with GraphRAG agent  
**Last Updated:** February 2026

---

## Executive Summary

This PR plan outlines the development of a federated knowledge graph integrating Italy's public spending data across 6+ official sources. The system will enable sophisticated cross-source analysis of procurement (ANAC), funded projects (OpenCUP), corporate structures (Registro Imprese), socio-economic context (ISTAT), and public assets (Demanio, ARERA, MIT).

**Key Deliverable:** A GraphRAG-powered agent capable of answering multi-source questions like *"Which companies won ANAC tenders AND have PNRR projects in regions with demographic decline?"*

---

## Phase Breakdown (8 PRs across 12-16 weeks)

### Phase 1: Core Infrastructure & ANAC Foundation (Weeks 1-2)
**Status:** Foundation Layer  
**PR #1: Project Setup, Schema Design & Neo4j Infrastructure**

**Objectives:**
- Initialize project repository with CI/CD pipeline
- Design extensible ontology for multi-source data
- Set up Neo4j infrastructure (Local High-Performance tuning)
- Create comprehensive schema documentation

**Deliverables:**
```
├── repository/
│   ├── docker-compose.yml (Neo4j, Polars worker, API)
│   ├── pyproject.toml (dependencies locked)
│   ├── .github/workflows/ (tests, linting, schema validation)
│   └── README.md (architecture overview)
├── schema/
│   ├── schema.cypher (full multi-source node & relationship definitions)
│   ├── ontology.md (semantic layer, namespace documentation)
│   ├── constraints.cypher (uniqueness, mandatory properties)
│   └── indexes.cypher (performance optimization)
├── docs/
│   ├── PERFORMANCE_TUNING.md (Neo4j local optimization)
│   ├── DATA_MODEL.md (nodo/relazioni per fonte)
│   └── PROVENANCE_SPEC.md (auditabilità, source tracking)
└── tests/
    └── test_schema_validation.py (schema validation on import)
```

**Technical Decisions:**
- **Graph DB:** Neo4j (Local Deployment via Docker)
- **Ontology Approach:** OWL-lite (RDFS-compatible, not full OWL for performance)
- **Local Performance:** Optimized for 16GB-32GB RAM workstations (Page Cache/Heap tuning)
- **Namespace Strategy:** 
  - `:AnacTender`, `:OpencupProject`, `:IstatContext`, etc.
  - Entity resolution via `source` property + `confidence` score
- **Provenance Model:**
  - Every node/edge has `{source: ["ANAC"], datasetVersion: "2026-01", retrievalDate: date, confidence: 0.95}`
  - Lineage tracking for audit trails

**Code Snippets (Highlights):**

```cypher
// schema.cypher excerpt

CREATE CONSTRAINT unique_company_cf ON (c:Company) ASSERT c.cf IS UNIQUE;
CREATE CONSTRAINT unique_tender_cig ON (t:Tender) ASSERT t.cig IS UNIQUE;
CREATE INDEX idx_company_source ON (c:Company) FOR EACH (c.source);

CREATE TEXT INDEX idx_company_name ON NODES (c:Company) FOR (c.nomeNormalizzato);
CREATE POINT INDEX idx_asset_location ON (a:Asset) FOR (a.location);
```

```python
# schema_validator.py excerpt
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class ProvenanceMetadata(BaseModel):
    source: List[str]  # ["ANAC", "OpenCUP", "ISTAT"]
    dataset_version: str  # "2026-01"
    retrieval_date: datetime
    confidence: float = Field(ge=0, le=1)

class NodeBase(BaseModel):
    id: str
    labels: List[str]
    properties: dict
    provenance: ProvenanceMetadata

def validate_node_schema(node: dict, node_type: str) -> bool:
    """Validates node against expected schema per source"""
    pass
```

**PR Checklist:**
- [ ] Docker Compose working locally (Neo4j 5.x + Python 3.11)
- [ ] Local RAM/Cache settings optimized for large graph processing
- [ ] Schema files complete & syntactically valid
- [ ] Uniqueness constraints + indexes in place
- [ ] Unit tests for schema validation (>80% coverage)
- [ ] Architecture document + data model diagram
- [ ] CI/CD pipeline configured (GitHub Actions)
- [ ] Code of Conduct + contribution guide

**Review Criteria:**
- Scalability: Schema designed for 50M+ nodes?
- Provenance: Every node/edge traceable to source?
- Performance: Local indexes optimized for SSD latency?

---

### Phase 2: ANAC ETL Pipeline (Weeks 3-4)
**Status:** Data Ingestion  
**PR #2: ANAC OCDS Download, Transform & Load**

**Objectives:**
- Implement automated OCDS JSON → graph transformation
- Handle ANAC-specific data quality issues (missing fields, date formats)
- Bulk load 200k+ tenders/contracts (2020-2026)
- Implement idempotent updates (versioning)

**Data Sources:**
- ANAC OCDS: https://dati.anticorruzione.it/opendata/ocds
- Format: JSON release packages (monthly/annual)
- Records: ~200k tenders, ~600k contracts (2020-2026)

**Deliverables:**
```
├── etl/
│   ├── anac/
│   │   ├── __init__.py
│   │   ├── download.py (OCDS JSON fetch + cache)
│   │   ├── transform.py (OCDS → normalized schema)
│   │   ├── quality_checks.py (validation + flags)
│   │   └── loader.py (Neo4j batch insert via Bolt)
│   └── common/
│       ├── normalizers.py (company names, dates, geo)
│       └── helpers.py (logging, error handling)
├── data/
│   ├── anac/
│   │   ├── raw/ (downloaded JSON)
│   │   ├── processed/ (transformed CSVs)
│   │   └── metadata.json (provenance log)
├── tests/
│   ├── test_anac_download.py
│   ├── test_anac_transform.py
│   ├── test_anac_quality.py
│   └── test_anac_loader.py
└── scripts/
    └── run_anac_etl.sh (orchestration)
```

**ETL Workflow:**

```python
# etl/anac/download.py excerpt
import requests
import json
from datetime import datetime, timedelta
from pathlib import Path

class AnacOcdsDownloader:
    BASE_URL = "https://dati.anticorruzione.it/opendata/ocds"
    
    def __init__(self, cache_dir: Path = Path("data/anac/raw")):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_releases(self, year: int, month: int):
        """Fetch monthly OCDS release package"""
        url = f"{self.BASE_URL}/releases/{year}/{month:02d}.json"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        cache_path = self.cache_dir / f"anac_{year}_{month:02d}.json"
        with open(cache_path, 'w') as f:
            json.dump(response.json(), f)
        
        return cache_path
    
    def fetch_all_releases(self, start_date: datetime, end_date: datetime):
        """Fetch all releases in date range"""
        current = start_date
        files = []
        while current <= end_date:
            try:
                file = self.fetch_releases(current.year, current.month)
                files.append(file)
            except Exception as e:
                print(f"Failed to fetch {current.year}-{current.month}: {e}")
            current += timedelta(days=32)
            current = current.replace(day=1)
        return files
```

```python
# etl/anac/transform.py excerpt
import polars as pl
from typing import Dict, List
from datetime import datetime

class AnacOcdsTransformer:
    """Transform OCCS JSON → normalized Tender/Company/Contract nodes"""
    
    def __init__(self):
        self.source = "ANAC"
        self.dataset_version = "2026-01"
        self.retrieval_date = datetime.now().isoformat()
    
    def extract_tenders(self, ocds_data: dict) -> pl.DataFrame:
        """Extract tender nodes from OCDS release"""
        tenders = []
        
        for record in ocds_data.get("records", []):
            release = record.get("releases", [{}])[0]  # Latest release
            
            tender_data = {
                "cig": release.get("ocid"),  # Codice Identificativo Gara
                "ocid": release.get("ocid"),
                "oggetto": release.get("tender", {}).get("title"),
                "importo": release.get("tender", {}).get("value", {}).get("amount"),
                "dataAggiudicazione": release.get("tender", {}).get("awardCriteria", {}).get("date"),
                "procedura": release.get("tender", {}).get("procurementMethod"),
                "dataApertura": release.get("tender", {}).get("openingDate"),
                "source": self.source,
                "datasetVersion": self.dataset_version,
                "retrievalDate": self.retrieval_date,
                "confidence": 0.95,
            }
            tenders.append(tender_data)
        
        return pl.DataFrame(tenders).filter(pl.col("importo") > 40000)  # Filter >40k€
    
    def extract_companies_from_tenders(self, ocds_data: dict) -> pl.DataFrame:
        """Extract company nodes (winners) from OCDS"""
        companies = []
        
        for record in ocds_data.get("records", []):
            release = record.get("releases", [{}])[0]
            contracts = release.get("contracts", [])
            
            for contract in contracts:
                for award in contract.get("awards", []):
                    for supplier in award.get("suppliers", []):
                        company = {
                            "cf": supplier.get("id"),  # Codice fiscale or VAT
                            "nomeNormalizzato": self._normalize_name(supplier.get("name")),
                            "source": [self.source],
                            "datasetVersion": self.dataset_version,
                        }
                        companies.append(company)
        
        return pl.DataFrame(companies).unique(subset=["cf"])
    
    def extract_wins(self, ocds_data: dict) -> pl.DataFrame:
        """Extract WINS relationships (Company -> Tender)"""
        wins = []
        
        for record in ocds_data.get("records", []):
            release = record.get("releases", [{}])[0]
            tender_cig = release.get("ocid")
            contracts = release.get("contracts", [])
            
            for contract in contracts:
                for award in contract.get("awards", []):
                    for supplier in award.get("suppliers", []):
                        win = {
                            "company_cf": supplier.get("id"),
                            "tender_cig": tender_cig,
                            "importo": award.get("value", {}).get("amount"),
                            "data": award.get("date"),
                            "percentuale": self._calc_percentage(award),
                            "source": self.source,
                            "confidence": 0.95,
                        }
                        wins.append(win)
        
        return pl.DataFrame(wins)
    
    def _normalize_name(self, name: str) -> str:
        """Normalize company name for matching"""
        return name.upper().strip() if name else ""
    
    def _calc_percentage(self, award: dict) -> float:
        """Calculate award percentage vs tender amount"""
        pass
    
    def transform(self, ocds_json_path: str) -> Dict[str, pl.DataFrame]:
        """Full transformation pipeline"""
        with open(ocds_json_path) as f:
            ocds_data = json.load(f)
        
        return {
            "tenders": self.extract_tenders(ocds_data),
            "companies": self.extract_companies_from_tenders(ocds_data),
            "wins": self.extract_wins(ocds_data),
            "buyers": self.extract_buyers(ocds_data),
        }
```

```python
# etl/anac/loader.py excerpt
from neo4j import GraphDatabase
from typing import Dict
import polars as pl

class AnacNeo4jLoader:
    def __init__(self, uri: str, auth: tuple):
        self.driver = GraphDatabase.driver(uri, auth=auth)
    
    def load_tenders(self, df: pl.DataFrame, batch_size: int = 1000):
        """Bulk load tender nodes"""
        with self.driver.session() as session:
            for i in range(0, len(df), batch_size):
                batch = df[i:i+batch_size]
                session.run("""
                    UNWIND $rows as row
                    MERGE (t:Tender {cig: row.cig})
                    SET t += row,
                        t.source = ["ANAC"],
                        t.retrievalDate = datetime($retrieval_date)
                """, rows=batch.to_dicts(), retrieval_date=datetime.now())
                print(f"Loaded {min(i+batch_size, len(df))}/{len(df)} tenders")
    
    def load_wins(self, df: pl.DataFrame, batch_size: int = 1000):
        """Bulk load WINS relationships"""
        with self.driver.session() as session:
            for i in range(0, len(df), batch_size):
                batch = df[i:i+batch_size]
                session.run("""
                    UNWIND $rows as row
                    MATCH (c:Company {cf: row.company_cf})
                    MATCH (t:Tender {cig: row.tender_cig})
                    MERGE (c)-[w:WINS {data: row.data}]->(t)
                    SET w += row
                """, rows=batch.to_dicts())
                print(f"Loaded {min(i+batch_size, len(df))}/{len(df)} wins")
```

**Quality Checks:**

```python
# etl/anac/quality_checks.py excerpt
class AnacQualityValidator:
    def __init__(self, df: pl.DataFrame, context: str = "tenders"):
        self.df = df
        self.context = context
        self.issues = []
    
    def check_missing_values(self, critical_cols: List[str]):
        """Flag rows with missing critical values"""
        for col in critical_cols:
            missing = self.df.filter(pl.col(col).is_null()).height
            if missing > 0:
                self.issues.append({
                    "type": "missing_value",
                    "column": col,
                    "count": missing,
                    "severity": "high" if col in ["cig", "importo"] else "medium",
                })
    
    def check_date_formats(self):
        """Validate ISO 8601 date formats"""
        pass
    
    def check_outliers(self):
        """Identify statistical outliers (z-score > 3)"""
        pass
    
    def generate_report(self) -> Dict:
        """Produce quality report with flags"""
        return {
            "total_records": self.df.height,
            "issues": self.issues,
            "pass": len(self.issues) == 0,
        }
```

**PR Checklist:**
- [ ] ANAC downloader working (tested on 6 months of data)
- [ ] Transform pipeline produces valid node/edge DataFrames
- [ ] Quality checks detect >95% of known data issues
- [ ] Loader tested on 50k+ records
- [ ] Idempotent updates (CIG-based MERGE)
- [ ] Integration tests with embedded Neo4j (testcontainers)
- [ ] Documentation: ETL architecture + data dictionary
- [ ] Error handling + retry logic (network failures)

**Metrics to Track:**
- Download speed (MB/s)
- Transform latency (records/sec)
- Load latency (records/sec)
- Data quality score (% clean vs flagged)
- Duplicate resolution rate

---

### Phase 3: OpenCUP ETL & CUP-CIG Matching (Weeks 5-6)
**Status:** Data Ingestion  
**PR #3: OpenCUP Integration + Tender-Project Linking**

**Objectives:**
- Ingest OpenCUP project dataset (CSV/JSON)
- Implement CUP-CIG matching to link projects ↔ tenders
- Create Project nodes + FUNDED_BY relationships
- Handle matching ambiguities (1:N, N:1 cases)

**Data Source:**
- OpenCUP: https://www.opencup.gov.it/portale/web/opencup/opendata
- Format: CSV (downloadable) or XML/JSON API
- Records: ~150k active projects (2020-2026)

**Deliverables:**
```
├── etl/
│   └── opencup/
│       ├── __init__.py
│       ├── download.py (CSV fetch + parse)
│       ├── transform.py (→ Project nodes)
│       └── matching.py (CUP-CIG linker)
├── tests/
│   ├── test_opencup_download.py
│   ├── test_opencup_transform.py
│   └── test_matching.py (CUP-CIG + N-N cases)
└── scripts/
    └── run_opencup_etl.sh
```

**CUP-CIG Matching Logic:**

```python
# etl/opencup/matching.py
import polars as pl
from typing import Tuple, Dict, List

class CupCigMatcher:
    """Link OpenCUP projects (CUP) to ANAC tenders (CIG)"""
    
    def __init__(self, tenders_df: pl.DataFrame, projects_df: pl.DataFrame):
        """
        Args:
            tenders_df: DataFrame with columns [cig, oggetto, importo, dataAggiudicazione, ...]
            projects_df: DataFrame with columns [cup, descrizione, importoPrevisto, stato, ...]
        """
        self.tenders = tenders_df
        self.projects = projects_df
        self.matches = []
        self.ambiguities = []
    
    def match_by_explicit_mapping(self) -> pl.DataFrame:
        """
        Strategy 1: Explicit CUP-CIG mapping (some ANAC tenders have CUP field)
        """
        merged = self.tenders.join(
            self.projects.select(["cup"]),
            left_on="cup_field",  # If ANAC tender has CUP
            right_on="cup",
            how="inner"
        )
        return merged
    
    def match_by_temporal_proximity(self, date_tolerance_days: int = 30) -> List[Dict]:
        """
        Strategy 2: Match tenders + projects with:
        - Temporal overlap (award date ≈ project start)
        - Similar amount (±20%)
        - Same buyer/location
        """
        matches = []
        
        for tender_row in self.tenders.iter_rows(named=True):
            tender_date = tender_row["dataAggiudicazione"]
            tender_amount = tender_row["importo"]
            tender_buyer = tender_row["buyer_cf"]
            
            # Find projects with compatible date/amount/location
            candidates = self.projects.filter(
                (pl.col("dataInizio").is_between(
                    tender_date - timedelta(days=date_tolerance_days),
                    tender_date + timedelta(days=date_tolerance_days)
                )) &
                (pl.col("importoPrevisto").is_between(
                    tender_amount * 0.8,
                    tender_amount * 1.2
                ))
            )
            
            if candidates.height == 1:
                # Unambiguous match
                matches.append({
                    "cig": tender_row["cig"],
                    "cup": candidates.row(0)[0],  # Assuming CUP is first col
                    "confidence": 0.85,
                    "method": "temporal_proximity",
                })
            elif candidates.height > 1:
                # Ambiguous: flag for manual review or higher-order matching
                self.ambiguities.append({
                    "cig": tender_row["cig"],
                    "cup_candidates": candidates["cup"].to_list(),
                    "candidate_count": candidates.height,
                })
        
        return matches
    
    def match_by_semantic_similarity(self, embedding_model: str = "distiluse-base-multilingual-v2") -> List[Dict]:
        """
        Strategy 3: Use NLP embeddings to match tender descriptions ↔ project descriptions
        """
        from sentence_transformers import SentenceTransformer
        
        model = SentenceTransformer(embedding_model)
        
        # Embed tender objects & project descriptions
        tender_embeddings = model.encode(self.tenders["oggetto"].to_list())
        project_embeddings = model.encode(self.projects["descrizione"].to_list())
        
        # Cosine similarity matrix
        from sklearn.metrics.pairwise import cosine_similarity
        similarity_matrix = cosine_similarity(tender_embeddings, project_embeddings)
        
        matches = []
        for i, tender_row in self.tenders.iter_rows(named=True):
            best_match_idx = similarity_matrix[i].argmax()
            best_score = similarity_matrix[i][best_match_idx]
            
            if best_score > 0.75:  # Threshold
                project_cup = self.projects.row(best_match_idx)[0]
                matches.append({
                    "cig": tender_row["cig"],
                    "cup": project_cup,
                    "confidence": float(best_score),
                    "method": "semantic_similarity",
                })
        
        return matches
    
    def match_all(self, strategies: List[str] = ["explicit", "temporal", "semantic"]) -> Dict:
        """
        Execute all strategies and deduplicate/rank results
        """
        all_matches = []
        
        if "explicit" in strategies:
            all_matches.extend(self.match_by_explicit_mapping().to_dicts())
        if "temporal" in strategies:
            all_matches.extend(self.match_by_temporal_proximity())
        if "semantic" in strategies:
            all_matches.extend(self.match_by_semantic_similarity())
        
        # Deduplicate: same CIG-CUP pair
        matches_df = pl.DataFrame(all_matches).unique(subset=["cig", "cup"])
        
        # For CIGs with multiple CUPs, keep highest confidence
        matches_dedup = matches_df.sort_by("confidence", descending=True).unique(
            subset=["cig"], keep="first"
        )
        
        return {
            "matches": matches_dedup.to_dicts(),
            "ambiguities": self.ambiguities,
            "match_rate": matches_dedup.height / self.tenders.height,
        }
```

**Neo4j Loader:**

```python
# etl/opencup/loader.py
class OpencupNeo4jLoader:
    def __init__(self, driver):
        self.driver = driver
    
    def load_projects(self, df: pl.DataFrame):
        """Load Project nodes"""
        with self.driver.session() as session:
            session.run("""
                UNWIND $rows as row
                MERGE (p:Project {cup: row.cup})
                SET p += row,
                    p.source = ["OpenCUP"],
                    p.retrievalDate = datetime($retrieval_date)
            """, rows=df.to_dicts(), retrieval_date=datetime.now())
    
    def load_cup_cig_links(self, matches: List[Dict]):
        """Load PART_OF relationships linking projects to tenders"""
        with self.driver.session() as session:
            session.run("""
                UNWIND $matches as match
                MATCH (p:Project {cup: match.cup})
                MATCH (t:Tender {cig: match.cig})
                CREATE (t)-[rel:PART_OF_PROJECT {confidence: match.confidence}]->(p)
                SET rel.source = "CUP-CIG_Matching"
            """, matches=matches)
```

**PR Checklist:**
- [ ] OpenCUP downloader working
- [ ] Transform pipeline validated on 10k+ projects
- [ ] Matching strategies tested (explicit, temporal, semantic)
- [ ] Ambiguity flagging: manual review interface (or docs)
- [ ] Match rate >70% on test dataset
- [ ] Temporal tolerance tuned (±30 days default)
- [ ] Loader working (idempotent merges)
- [ ] Unit tests >80% coverage

**Matching Success Metrics:**
- Match rate (% of tenders matched to projects)
- Confidence score distribution
- Ambiguity rate (% requiring manual review)
- Precision/recall (validate on known matches)

---

### Phase 4: Registro Imprese & Entity Resolution (Weeks 7-8)
**Status:** Data Enrichment  
**PR #4: Corporate Structure Enrichment + Entity Resolution**

**Objectives:**
- Ingest public company data (Registro Imprese, ISTAT)
- Implement entity resolution (CF/PIva deduplication cross-source)
- Create SHARES_UBO relationships (shareholder networks)
- Add sector/size classification

**Data Sources:**
- Registro Imprese: Limited public data (visure pagate) or ISTAT fallback
- ⚠️ **Note:** Titolari Effettivi (UBO) closed to public (privacy law, May 2024)
- ISTAT: Company demographics, sector codes (ATECO)

**Deliverables:**
```
├── etl/
│   └── corporate/
│       ├── download.py (Registro Imprese API + ISTAT)
│       ├── entity_resolution.py (CF/PIva matching)
│       └── enrichment.py (sector classification, size)
├── ml/
│   └── entity_resolution_model.py (semantic matching)
└── tests/
    └── test_entity_resolution.py
```

**Entity Resolution Pipeline:**

```python
# etl/corporate/entity_resolution.py
import polars as pl
from typing import List, Tuple, Dict
import Levenshtein

class EntityResolver:
    """Resolve duplicate company entities across sources"""
    
    def __init__(self, driver):
        self.driver = driver
        self.resolver_scores = {}
    
    def blocking_by_cf_piva(self) -> List[List[str]]:
        """
        Blocking strategy 1: Group by CF or PIVA
        Returns list of candidate pairs (company IDs)
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (c1:Company)--(c2:Company)
                WHERE c1.cf = c2.cf OR c1.piva = c2.piva
                  AND c1.id < c2.id  // Avoid duplicates
                RETURN collect(distinct [c1.id, c2.id]) as pairs
            """)
            return result.single()[0]
    
    def blocking_by_name_similarity(self, threshold: float = 0.85) -> List[Tuple[str, str]]:
        """
        Blocking strategy 2: Jaccard similarity on company names
        """
        pairs = []
        
        with self.driver.session() as session:
            companies = session.run("""
                MATCH (c:Company)
                WHERE c.nomeNormalizzato IS NOT NULL
                RETURN c.id, c.nomeNormalizzato
                LIMIT 50000
            """).to_df()
        
        for i, row1 in companies.iterrows():
            for j, row2 in companies.iterrows():
                if i >= j:
                    continue
                
                # Jaccard similarity on word tokens
                words1 = set(row1["nomeNormalizzato"].split())
                words2 = set(row2["nomeNormalizzato"].split())
                
                intersection = len(words1 & words2)
                union = len(words1 | words2)
                jaccard = intersection / union if union > 0 else 0
                
                if jaccard >= threshold:
                    pairs.append((row1["id"], row2["id"], jaccard))
        
        return pairs
    
    def score_pair(self, id1: str, id2: str) -> float:
        """
        Match score between two company entities
        Combines: CF/PIVA match, name similarity, location match
        """
        with self.driver.session() as session:
            c1, c2 = session.run("""
                MATCH (c1:Company {id: $id1}), (c2:Company {id: $id2})
                RETURN c1 {.cf, .piva, .nomeNormalizzato, .provincia},
                       c2 {.cf, .piva, .nomeNormalizzato, .provincia}
            """, id1=id1, id2=id2).single()
        
        score = 0.0
        
        # CF match: highest confidence
        if c1["cf"] and c2["cf"] and c1["cf"] == c2["cf"]:
            score = 0.99
        # PIVA match
        elif c1["piva"] and c2["piva"] and c1["piva"] == c2["piva"]:
            score = 0.98
        else:
            # Name + location similarity
            name_sim = Levenshtein.ratio(
                c1["nomeNormalizzato"], c2["nomeNormalizzato"]
            )
            location_sim = 1.0 if c1["provincia"] == c2["provincia"] else 0.5
            score = 0.7 * name_sim + 0.3 * location_sim
        
        return score
    
    def resolve_clusters(self, pairs: List[Tuple[str, str]], threshold: float = 0.85) -> Dict[str, str]:
        """
        Cluster entities based on pairwise scores
        Returns mapping: {entity_id -> canonical_id}
        """
        from collections import defaultdict, deque
        
        # Build adjacency for connected components
        graph = defaultdict(set)
        all_ids = set()
        
        for id1, id2 in pairs:
            score = self.score_pair(id1, id2)
            if score >= threshold:
                graph[id1].add(id2)
                graph[id2].add(id1)
                all_ids.add(id1)
                all_ids.add(id2)
        
        # BFS to find connected components
        visited = set()
        clusters = []
        
        for node in all_ids:
            if node in visited:
                continue
            
            cluster = set()
            queue = deque([node])
            
            while queue:
                current = queue.popleft()
                if current in visited:
                    continue
                visited.add(current)
                cluster.add(current)
                queue.extend(graph[current])
            
            clusters.append(cluster)
        
        # For each cluster, pick canonical ID (lowest alphabetically or by confidence)
        mapping = {}
        for cluster in clusters:
            canonical = min(cluster)  # Could use other logic
            for entity_id in cluster:
                mapping[entity_id] = canonical
        
        return mapping
    
    def merge_entities(self, mapping: Dict[str, str]):
        """
        Merge duplicate entities in Neo4j
        Duplicates → absorbed into canonical entity
        """
        with self.driver.session() as session:
            # For each duplicate → canonical mapping
            for dup_id, canonical_id in mapping.items():
                if dup_id == canonical_id:
                    continue
                
                session.run("""
                    MATCH (dup:Company {id: $dup_id})
                    MATCH (canonical:Company {id: $canonical_id})
                    
                    // Merge properties (canonical wins)
                    SET canonical += dup
                    
                    // Redirect all relationships
                    MATCH (dup)-[r]->(other)
                    CREATE (canonical)-[newR:MERGED_FROM]->(other)
                    SET newR = r, newR.original_source = dup_id
                    DELETE r
                    
                    // Delete duplicate node
                    DELETE dup
                """, dup_id=dup_id, canonical_id=canonical_id)
```

**Enrichment:**

```python
# etl/corporate/enrichment.py
class CompanyEnricher:
    """Enrich company nodes with sector, size, risk scores"""
    
    def add_sector_classification(self, driver):
        """Add ATECO sector labels from ISTAT"""
        with driver.session() as session:
            session.run("""
                MATCH (c:Company)
                WHERE c.ateco IS NOT NULL
                WITH c, substring(c.ateco, 0, 2) as sector_code
                MATCH (s:Sector {cod: sector_code})
                CREATE (c)-[:OPERATES_IN_SECTOR]->(s)
            """)
    
    def compute_risk_score(self, driver):
        """Add risk score based on ANAC history"""
        with driver.session() as session:
            session.run("""
                MATCH (c:Company)
                OPTIONAL MATCH (c)-[w:WINS]->(t:Tender)
                WITH c, count(w) as tender_count, avg(t.importo) as avg_amount
                
                // Risk factors: low diversity (few tenders), high concentration
                SET c.riskScore = CASE
                    WHEN tender_count = 0 THEN 0.5
                    WHEN tender_count < 5 THEN 0.6
                    WHEN tender_count >= 10 THEN 0.3
                    ELSE 0.4
                END
            """)
```

**PR Checklist:**
- [ ] Entity resolution blocking tested on 50k+ companies
- [ ] Pairwise scoring with >3 strategies (CF, name, location)
- [ ] Cluster merging implemented + tested
- [ ] Neo4j merge safe (no data loss)
- [ ] ISTAT sector classification applied
- [ ] Risk scoring algorithm documented
- [ ] Unit tests >75% coverage
- [ ] Ambiguous pair flagging (confidence <0.9)

**Entity Resolution Metrics:**
- Precision/recall on known duplicates
- Cluster size distribution
- Merge success rate

---

### Phase 5: ISTAT & Regional Context (Weeks 9-10)
**Status:** Data Enrichment  
**PR #5: Socio-economic Context + Temporal Analysis**

**Objectives:**
- Ingest ISTAT demographic/economic data (by comune, provincia, regione)
- Create DatasetContext nodes (population, GDP, unemployment)
- Link companies ↔ regions via LOCATED_IN relationships
- Implement temporal indexing (year-based)
- Detect anomalies (e.g., small town with massive tenders)

**Data Source:**
- ISTAT API: https://esploradati.istat.it/databrowser
- Datasets: Demographics, economic indicators, sector employment by region

**Deliverables:**
```
├── etl/
│   └── istat/
│       ├── download.py (ISTAT API client)
│       ├── transform.py (→ DatasetContext nodes)
│       └── anomaly_detection.py (z-score, isolation forest)
├── ml/
│   └── outlier_detection.py
└── tests/
    └── test_istat_anomalies.py
```

**ISTAT Ingestion:**

```python
# etl/istat/download.py
import requests
import polars as pl

class IstatApiClient:
    BASE_URL = "https://esploradati.istat.it/api/v1"
    
    def get_population_by_comune(self, year: int) -> pl.DataFrame:
        """Fetch population data by Italian comune"""
        response = requests.get(
            f"{self.BASE_URL}/population",
            params={"year": year, "format": "json"}
        )
        data = response.json()
        return pl.from_dicts(data["records"])
    
    def get_economic_indicators(self, year: int) -> pl.DataFrame:
        """Regional economic indicators (GDP, unemployment, etc.)"""
        pass
    
    def get_sector_employment(self, year: int, regione: str) -> pl.DataFrame:
        """Employment by sector (ATECO) in region"""
        pass
```

**Anomaly Detection:**

```python
# etl/istat/anomaly_detection.py
import polars as pl
from sklearn.ensemble import IsolationForest
import numpy as np

class AnomalyDetector:
    """Identify companies/tenders that deviate from regional norms"""
    
    def compute_z_scores(self, driver) -> List[Dict]:
        """
        Z-score per feature:
        - Tender amount by region
        - Win rate by company size
        - Tender concentration per buyer
        """
        with driver.session() as session:
            # Aggregate tenders by regione
            df = session.run("""
                MATCH (t:Tender)-[:AWARDED_BY]->(b:Buyer)
                WHERE b.regione IS NOT NULL
                RETURN b.regione as regione, 
                       collect(t.importo) as amounts
            """).to_df()
        
        anomalies = []
        
        for row in df.itertuples():
            amounts = np.array(row.amounts)
            mean = amounts.mean()
            std = amounts.std()
            
            # Flag outliers (z > 3)
            z_scores = np.abs((amounts - mean) / std)
            outlier_indices = np.where(z_scores > 3)[0]
            
            for idx in outlier_indices:
                anomalies.append({
                    "regione": row.regione,
                    "importo": amounts[idx],
                    "z_score": z_scores[idx],
                    "severity": "high" if z_scores[idx] > 5 else "medium",
                })
        
        return anomalies
    
    def isolation_forest_detect(self, driver) -> List[Dict]:
        """
        Multivariate anomaly detection using Isolation Forest
        Features: amount, buyer size, company history, regional avg
        """
        with driver.session() as session:
            df = session.run("""
                MATCH (c:Company)-[w:WINS]->(t:Tender)
                MATCH (t)-[:AWARDED_BY]->(b:Buyer)
                MATCH (c)-[:LOCATED_IN]->(ctx:DatasetContext)
                RETURN 
                    t.cig as cig,
                    t.importo as amount,
                    size([(c)-[:WINS]->(:Tender)]) as company_win_count,
                    b.nome as buyer,
                    ctx.popolazione as regional_pop
            """).to_df()
        
        # Prepare feature matrix
        features = df[["amount", "company_win_count", "regional_pop"]].fillna(0)
        X = features.values
        
        # Fit Isolation Forest
        iso_forest = IsolationForest(contamination=0.05, random_state=42)
        predictions = iso_forest.fit_predict(X)
        
        anomalies = []
        for i, pred in enumerate(predictions):
            if pred == -1:  # Anomaly
                anomalies.append({
                    "cig": df.iloc[i]["cig"],
                    "score": iso_forest.score_samples([X[i]])[0],
                    "features": {
                        "amount": float(df.iloc[i]["amount"]),
                        "company_history": int(df.iloc[i]["company_win_count"]),
                    }
                })
        
        return anomalies
```

**PR Checklist:**
- [ ] ISTAT API client working (test with 2-3 datasets)
- [ ] Transform pipeline → DatasetContext nodes
- [ ] Temporal indexing for year-over-year analysis
- [ ] Z-score anomaly detection validated
- [ ] Isolation Forest model tuned (contamination %)
- [ ] Anomaly flags stored + visualizable
- [ ] Tests >70% coverage
- [ ] Documentation: anomaly interpretation guide

**Context Metrics:**
- % of companies successfully linked to regions
- Anomaly rate (% flagged)
- Top anomalies by severity

---

### Phase 6: Asset Integration (Weeks 11-12)
**Status:** Data Enrichment  
**PR #6: Demanio/ARERA/MIT Asset Linking**

**Objectives:**
- Ingest public assets (Demanio properties, ARERA energy networks, MIT infrastructure)
- Link assets ↔ projects via location/codice matching
- Create INVOLVES_ASSET relationships
- Spatial indexing (if using PostGIS or Neo4j spatial plugin)

**Data Sources:**
- Demanio: https://dati.gov.it (immobili pubblici)
- ARERA: Energy market data
- MIT: Transport infrastructure

**Deliverables:**
```
├── etl/
│   └── assets/
│       ├── demanio_loader.py
│       ├── arera_loader.py
│       ├── mit_loader.py
│       └── spatial_matcher.py
└── tests/
    └── test_asset_matching.py
```

**Asset Matching:**

```python
# etl/assets/spatial_matcher.py
import polars as pl
from geopy.distance import geodesic

class AssetMatcher:
    """Link projects/tenders to public assets via spatial proximity"""
    
    def match_by_address_similarity(self, driver) -> List[Dict]:
        """
        Match projects to assets by address string similarity
        """
        with driver.session() as session:
            projects = session.run("""
                MATCH (p:Project)
                WHERE p.indirizzo IS NOT NULL
                RETURN p.cup, p.indirizzo, p.provincia
            """).to_df()
            
            assets = session.run("""
                MATCH (a:Asset)
                WHERE a.indirizzo IS NOT NULL
                RETURN a.id, a.indirizzo, a.provincia, a.tipo
            """).to_df()
        
        matches = []
        
        for _, proj in projects.iterrows():
            for _, asset in assets.iterrows():
                # Fuzzy match on address
                ratio = Levenshtein.ratio(
                    proj["indirizzo"].upper(),
                    asset["indirizzo"].upper()
                )
                
                # Exact match on provincia
                location_match = proj["provincia"] == asset["provincia"]
                
                if ratio > 0.85 and location_match:
                    matches.append({
                        "cup": proj["cup"],
                        "asset_id": asset["id"],
                        "confidence": ratio,
                    })
        
        return matches
    
    def match_by_spatial_proximity(self, driver, radius_km: float = 1.0) -> List[Dict]:
        """
        Match by geographic proximity (lat/lon)
        """
        with driver.session() as session:
            # Fetch projects with coordinates
            projects = session.run("""
                MATCH (p:Project)
                WHERE p.latitude IS NOT NULL AND p.longitude IS NOT NULL
                RETURN p.cup, p.latitude, p.longitude
            """).to_df()
            
            assets = session.run("""
                MATCH (a:Asset)
                WHERE a.latitude IS NOT NULL AND a.longitude IS NOT NULL
                RETURN a.id, a.latitude, a.longitude, a.tipo
            """).to_df()
        
        matches = []
        
        for _, proj in projects.iterrows():
            proj_coords = (proj["latitude"], proj["longitude"])
            
            for _, asset in assets.iterrows():
                asset_coords = (asset["latitude"], asset["longitude"])
                
                dist_km = geodesic(proj_coords, asset_coords).km
                
                if dist_km <= radius_km:
                    matches.append({
                        "cup": proj["cup"],
                        "asset_id": asset["id"],
                        "distance_km": dist_km,
                        "confidence": max(0, 1.0 - (dist_km / radius_km)),
                    })
        
        return matches
```

**PR Checklist:**
- [ ] Demanio/ARERA/MIT loaders working
- [ ] Address + spatial matching validated
- [ ] Asset-project linking >60% match rate
- [ ] Spatial indexes optimized (if applicable)
- [ ] Tests >70% coverage
- [ ] Asset metadata complete

---

### Phase 7: Cross-Source Entity Resolution + Provenance (Weeks 13-14)
**Status:** Data Quality  
**PR #7: Advanced Entity Resolution & Audit Trail**

**Objectives:**
- Final deduplication pass across all sources
- Implement full provenance tracking (source lineage)
- Create audit logs for compliance
- Merge duplicate nodes from different sources

**Deliverables:**
```
├── etl/
│   └── resolution/
│       ├── cross_source_resolver.py
│       ├── provenance_tracker.py
│       └── audit_logger.py
└── tests/
    └── test_provenance.py
```

**Cross-Source Resolution:**

```python
# etl/resolution/cross_source_resolver.py
class CrossSourceResolver:
    """Merge entities appearing in multiple sources"""
    
    def find_anac_opencup_duplicates(self, driver) -> List[Dict]:
        """
        Companies in ANAC (from wins) ↔ Companies from other sources
        Match via: CF/PIva + name similarity
        """
        with driver.session() as session:
            result = session.run("""
                MATCH (c1:Company)
                WHERE "ANAC" IN c1.source
                WITH c1
                MATCH (c2:Company)
                WHERE c1.cf = c2.cf OR c1.piva = c2.piva
                  AND c1 <> c2
                  AND NOT "ANAC" IN c2.source
                RETURN c1.cf as cf, c1.id as anac_id, c2.id as other_id, c2.source
            """)
            
            return result.data()
    
    def merge_cross_source_duplicates(self, driver, mapping: Dict[str, str]):
        """Merge companies across sources"""
        with driver.session() as session:
            for source_id, canonical_id in mapping.items():
                session.run("""
                    MATCH (dup:Company {id: $source_id})
                    MATCH (canonical:Company {id: $canonical_id})
                    
                    // Combine sources
                    SET canonical.source = 
                        canonical.source + [s IN dup.source WHERE NOT s IN canonical.source]
                    
                    // Keep earliest retrieval date
                    SET canonical.retrievalDate = 
                        CASE WHEN dup.retrievalDate < canonical.retrievalDate 
                        THEN dup.retrievalDate 
                        ELSE canonical.retrievalDate 
                        END
                    
                    // Redirect relationships
                    MATCH (dup)-[r]->(other)
                    CREATE (canonical)-[newR]->(other)
                    SET newR = r
                    DELETE r
                    
                    DELETE dup
                """, source_id=source_id, canonical_id=canonical_id)
```

**Provenance Tracking:**

```python
# etl/resolution/provenance_tracker.py
class ProvenanceTracker:
    """Track data lineage for audit/compliance"""
    
    def add_node_provenance(self, driver, node_id: str, metadata: Dict):
        """
        Record provenance for a node
        metadata: {source: str, dataset_version: str, retrieval_date: date, confidence: float}
        """
        with driver.session() as session:
            session.run("""
                MATCH (n {id: $node_id})
                CREATE (prov:Provenance {
                    node_id: $node_id,
                    source: $source,
                    dataset_version: $dataset_version,
                    retrieval_date: datetime($retrieval_date),
                    confidence: $confidence,
                    recorded_at: datetime()
                })
                CREATE (n)-[:HAS_PROVENANCE]->(prov)
            """, node_id=node_id, **metadata)
    
    def trace_lineage(self, driver, node_id: str) -> Dict:
        """
        Retrieve full lineage for a node
        """
        with driver.session() as session:
            result = session.run("""
                MATCH (n {id: $node_id})-[:HAS_PROVENANCE]->(prov:Provenance)
                RETURN prov {.*} as provenance
                UNION
                MATCH (n {id: $node_id})-[r]->(:Provenance)
                RETURN collect({source: type(r), node: n.id})
            """, node_id=node_id)
            
            return result.data()
```

**Audit Logger:**

```python
# etl/resolution/audit_logger.py
import json
from datetime import datetime

class AuditLogger:
    """Log all data modifications for compliance"""
    
    def __init__(self, log_file: str = "audit.log"):
        self.log_file = log_file
    
    def log_merge(self, source_id: str, target_id: str, reason: str):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "merge",
            "source_id": source_id,
            "target_id": target_id,
            "reason": reason,
        }
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry) + "\n")
    
    def log_deletion(self, node_id: str, reason: str):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "delete",
            "node_id": node_id,
            "reason": reason,
        }
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(entry) + "\n")
```

**PR Checklist:**
- [ ] Cross-source duplicate detection tested
- [ ] Merges safe + reversible (via audit log)
- [ ] Provenance tracked for all nodes
- [ ] Audit log readable + queryable
- [ ] GDPR compliance audit trail
- [ ] Tests >80% coverage

---

### Phase 8: GraphRAG Agent & Advanced Queries (Weeks 15-16)
**Status:** Application Layer  
**PR #8: GraphRAG Agent + Query Interface**

**Objectives:**
- Implement GraphRAG agent (agentic graph reasoning)
- Build query interface supporting complex multi-source questions
- Add visualization dashboard
- Performance optimization (caching, query planning)

**Deliverables:**
```
├── app/
│   ├── graphrag_agent.py (agent logic)
│   ├── query_engine.py (Cypher generation)
│   ├── cache.py (Redis caching)
│   └── visualizers.py
├── api/
│   ├── fastapi_server.py
│   └── endpoints.py
├── frontend/
│   ├── dashboard.html
│   └── query_builder.js
└── tests/
    └── test_graphrag_agent.py
```

**GraphRAG Agent:**

```python
# app/graphrag_agent.py
from langchain.agents import AgentExecutor, Tool
from langchain.llms import ChatOpenAI
from langchain.prompts import PromptTemplate

class GraphRAGAgent:
    """Multi-hop reasoning agent for knowledge graph queries"""
    
    def __init__(self, driver, llm_model: str = "gpt-4"):
        self.driver = driver
        self.llm = ChatOpenAI(model=llm_model, temperature=0)
        self.tools = self._build_tools()
        self.executor = AgentExecutor.from_agent_and_tools(
            agent=..., tools=self.tools, verbose=True
        )
    
    def _build_tools(self):
        """Define tools for agent"""
        return [
            Tool(
                name="query_companies",
                func=self.query_companies,
                description="Find companies matching criteria (name, sector, location)"
            ),
            Tool(
                name="query_tenders",
                func=self.query_tenders,
                description="Find tenders by buyer, amount, procedure type"
            ),
            Tool(
                name="find_company_wins",
                func=self.find_company_wins,
                description="Get all tenders won by a company"
            ),
            Tool(
                name="find_anomalies",
                func=self.find_anomalies,
                description="Detect anomalous companies/tenders (high risk)"
            ),
            Tool(
                name="analyze_sector",
                func=self.analyze_sector,
                description="Analyze sector (concentration, market share, trends)"
            ),
            Tool(
                name="cross_source_analysis",
                func=self.cross_source_analysis,
                description="Correlate ANAC tenders with OpenCUP projects and ISTAT context"
            ),
        ]
    
    def query_companies(self, query: str, sector: str = None, regione: str = None):
        """Search companies"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (c:Company)
                WHERE c.nomeNormalizzato CONTAINS $query
                  AND ($sector IS NULL OR $sector IN c.sectors)
                  AND ($regione IS NULL OR c.regione = $regione)
                RETURN c {.cf, .piva, .nomeNormalizzato, .regione, .ateco}
                LIMIT 10
            """, query=query.upper(), sector=sector, regione=regione)
            return result.to_df().to_dict(orient="records")
    
    def find_anomalies(self, anomaly_type: str = "all"):
        """Find high-risk entities"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (c:Company)
                WHERE c.riskScore > 0.75
                RETURN c {.cf, .nomeNormalizzato, .riskScore} as company
                ORDER BY c.riskScore DESC
                LIMIT 20
            """)
            return result.to_df().to_dict(orient="records")
    
    def cross_source_analysis(self, company_name: str, regione: str = None):
        """
        Multi-hop reasoning: company → ANAC wins + OpenCUP projects 
        + regional context
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (c:Company {nomeNormalizzato: $company})
                OPTIONAL MATCH (c)-[w:WINS]->(t:Tender)-[:AWARDED_BY]->(b:Buyer)
                OPTIONAL MATCH (p:Project)-[:PART_OF_PROJECT]->(t)
                OPTIONAL MATCH (c)-[:LOCATED_IN]->(ctx:DatasetContext)
                
                WHERE $regione IS NULL OR c.regione = $regione
                
                RETURN {
                    company: c {.cf, .nomeNormalizzato, .regione},
                    tenders_won: count(distinct t),
                    tender_amount_total: sum(t.importo),
                    projects: collect(distinct p.cup),
                    regional_context: collect(distinct ctx {.tipo, .valore, .anno})
                } as analysis
            """, company=company_name.upper(), regione=regione)
            
            return result.to_df().to_dict(orient="records")
    
    def run_agent(self, question: str) -> str:
        """
        Run agent on natural language question
        Example: "Which companies in Veneto have ANAC tenders and PNRR projects?"
        """
        result = self.executor.run(question)
        return result
```

**Query Engine:**

```python
# app/query_engine.py
**Query Engine (Template-based GraphRAG):**

```python
# app/query_engine.py
class CypherQueryGenerator:
    """Translate natural language → optimized Cypher using validated templates"""
    
    def __init__(self, llm):
        self.llm = llm
        # Dictionary of validated Cypher templates
        self.templates = {
            "tender_by_region": "MATCH (c:Company {regione: $reg})-[w:WINS]->(t:Tender) ...",
            "cross_source_risk": "MATCH (p:Project {source: 'OpenCUP'})<-[:PART_OF_PROJECT]-(t:Tender) ...",
        }
    
    def generate_cypher(self, natural_question: str) -> str:
        """
        1. Classify intent into a template category
        2. Extract parameters (Region, Importo, etc.)
        3. Fill template or generate scoped Cypher
        """
        intent = self._classify_intent(natural_question)
        if intent in self.templates:
            return self._fill_template(intent, natural_question)
        
        # Fallback to restricted generation
        return self._generate_controlled_cypher(natural_question)

    def _generate_controlled_cypher(self, nl_query: str) -> str:
        """LLM generates Cypher with strict schema pruning and validation"""
        pass
```
```

**FastAPI Server:**

```python
# api/fastapi_server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Italian Public Funds Knowledge Graph")
agent = GraphRAGAgent(driver=neo4j_driver)

class QueryRequest(BaseModel):
    question: str
    filters: dict = {}

@app.post("/query")
async def query(req: QueryRequest):
    """Natural language query interface"""
    try:
        result = agent.run_agent(req.question)
        return {"answer": result, "confidence": 0.95}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/companies/{cf}")
async def get_company(cf: str):
    """Get company profile + relationships"""
    with neo4j_driver.session() as session:
        result = session.run("""
            MATCH (c:Company {cf: $cf})
            OPTIONAL MATCH (c)-[w:WINS]->(t:Tender)
            OPTIONAL MATCH (c)-[s:SHARES_UBO]->(c2:Company)
            RETURN c, collect({tender: t, wins: w}) as tenders, 
                   collect({shareholder: c2}) as shareholders
        """, cf=cf)
        
        return result.single()[0] if result.single() else {}

@app.get("/anomalies")
async def get_anomalies(min_score: float = 0.75):
    """List high-risk entities"""
    with neo4j_driver.session() as session:
        result = session.run("""
            MATCH (c:Company)
            WHERE c.riskScore > $min_score
            RETURN c ORDER BY c.riskScore DESC
            LIMIT 50
        """, min_score=min_score)
        
        return [record[0] for record in result]
```

**PR Checklist:**
- [ ] GraphRAG agent working on 5+ query types
- [ ] Cypher generation LLM-based
- [ ] Query caching (Redis) working
- [ ] FastAPI endpoints tested
- [ ] Query performance <2s for typical queries
- [ ] Dashboard prototype complete
- [ ] Documentation: example queries + agent reasoning
- [ ] Tests >75% coverage

---

## Cross-Cutting Concerns (All PRs)

### CI/CD Pipeline
- Automated testing (unit + integration)
- Code quality checks (Flake8, Pylint)
- Dependency security scanning
- Neo4j schema validation on each commit
- Docker image building + registry push

### Monitoring & Logging
- Structured logging (JSON, ELK stack optional)
- Metrics: ETL latency, data quality scores, query performance
- Alerting: data freshness checks, schema violations, anomaly spikes

### Documentation
- Architecture decision records (ADRs)
- Data dictionary per source
- Query cookbook (examples)
- Deployment guide (Docker, cloud)
- Troubleshooting guide

### Testing Strategy
- Unit tests: >75% coverage per PR
- Integration tests: full ETL pipeline on 1000s of records
- Schema validation tests: all node/edge constraints
- Query tests: known Q&A pairs
- Performance tests: query latency benchmarks

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| **Data Quality** | Quality checks per ETL phase + manual spot checks on 1% |
| **Privacy/GDPR** | Provenance tracking, audit logs, PII masking where needed |
| **Entity Resolution Errors** | Conservative blocking (high precision) + manual review for <90% confidence matches |
| **Performance Degradation** | Local Index strategy; caching + page cache tuning |
| **Data Versioning** | Use `Version` nodes to track tender/project rectifications (Phase 2+) |
| **GraphRAG Hallucination** | Use validated Cypher templates + verification layer (Phase 8) |
| **ISTAT Code Changes** | Mapping table for municipality evolution (Phase 5) |

---

## Success Criteria

**MVP (Phase 4, Week 8):**
- ✓ ANAC + OpenCUP fully ingested
- ✓ 200k+ tenders, 150k+ projects in graph
- ✓ >70% CUP-CIG match rate
- ✓ Entity resolution working on companies

**Extended (Phase 8, Week 16):**
- ✓ All 6 sources integrated
- ✓ GraphRAG agent answering multi-source queries
- ✓ Anomaly detection in production
- ✓ <2s query latency (p95)
- ✓ 95%+ audit trail completeness

---

## Timeline Overview

```
Week 1-2:   Infrastructure + Schema       (PR #1)
Week 3-4:   ANAC ETL                      (PR #2)
Week 5-6:   OpenCUP + CUP-CIG Matching    (PR #3)
Week 7-8:   Entity Resolution + Enrichment (PR #4)
Week 9-10:  ISTAT + Regional Context      (PR #5)
Week 11-12: Asset Integration             (PR #6)
Week 13-14: Cross-source Resolution       (PR #7)
Week 15-16: GraphRAG Agent + API          (PR #8)
```

---

## Next Steps

1. **Approve PR Plan** (this document)
2. **Set up repository + CI/CD** (PR #1 preparation)
3. **Begin Phase 1 development** (Schema design + Neo4j infrastructure)
4. **Assign team members** to parallel workstreams (ANAC, OpenCUP, Entity Resolution)
5. **Weekly sync** on blockers + progress

---

**Document Version:** 1.0  
**Last Updated:** February 9, 2026  
**Maintainer:** Data Engineering Team
