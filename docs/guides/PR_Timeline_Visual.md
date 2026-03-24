# Italian Public Funds Knowledge Graph - PR Timeline & Dependencies

## Visual Phase Timeline

```
PHASE 1: Infrastructure (Week 1-2)
┌─────────────────────────────────┐
│ PR #1: Schema + Neo4j Setup     │
│ - Ontology design               │
│ - Constraint definitions        │
│ - CI/CD pipeline                │
│ Duration: 2 weeks               │
└─────────────────────────────────┘
         ↓
         
PHASE 2: ANAC Foundation (Week 3-4)
┌─────────────────────────────────┐
│ PR #2: ANAC OCDS ETL            │
│ - Download/cache OCDS JSON      │
│ - Transform → graph schema      │
│ - Load 200k+ tenders            │
│ Duration: 2 weeks               │
│ Depends: PR #1                  │
└─────────────────────────────────┘
         ↓
         
PHASE 3: OpenCUP + Matching (Week 5-6)
┌─────────────────────────────────┐
│ PR #3: OpenCUP + CUP-CIG Link   │
│ - Download 150k projects        │
│ - 3-strategy matching engine    │
│ - 70%+ match rate target        │
│ Duration: 2 weeks               │
│ Depends: PR #1, PR #2           │
└─────────────────────────────────┘
         ↓
         
PHASE 4: Company Enrichment (Week 7-8)
┌─────────────────────────────────┐
│ PR #4: Entity Resolution        │
│ - Blocking + scoring            │
│ - Multi-source merge            │
│ - Risk scoring model            │
│ Duration: 2 weeks               │
│ Depends: PR #1, PR #2, PR #3    │
└─────────────────────────────────┘
         ↓
         
PHASE 5: Regional Context (Week 9-10)
┌─────────────────────────────────┐
│ PR #5: ISTAT + Anomaly Detection│
│ - Download ISTAT datasets       │
│ - Demographic/economic context  │
│ - Z-score + Isolation Forest    │
│ Duration: 2 weeks               │
│ Depends: PR #1, PR #4           │
└─────────────────────────────────┘
         ↓
         
PHASE 6: Asset Integration (Week 11-12)
┌─────────────────────────────────┐
│ PR #6: Demanio/ARERA/MIT        │
│ - Asset node ingestion          │
│ - Address + spatial matching    │
│ - INVOLVES_ASSET relationships  │
│ Duration: 2 weeks               │
│ Depends: PR #1, PR #5           │
└─────────────────────────────────┘
         ↓
         
PHASE 7: Cross-Source Resolution (Week 13-14)
┌─────────────────────────────────┐
│ PR #7: Provenance + Audit       │
│ - Cross-source duplicate merge  │
│ - Full lineage tracking         │
│ - Audit log infrastructure      │
│ Duration: 2 weeks               │
│ Depends: PR #1, PR #4, PR #6    │
└─────────────────────────────────┘
         ↓
         
PHASE 8: GraphRAG Agent (Week 15-16)
┌─────────────────────────────────┐
│ PR #8: Agent + API + Dashboard  │
│ - GraphRAG multi-hop reasoning  │
│ - FastAPI endpoints             │
│ - Query caching + optimization  │
│ Duration: 2 weeks               │
│ Depends: PR #1-7 (all)          │
└─────────────────────────────────┘
```

## Parallel Work Opportunities

Teams can work in parallel on some phases. Here's the dependency DAG:

```
                          PR #1 (Schema)
                              ↓
                    ┌─────────┴─────────┐
                    ↓                   ↓
                  PR #2               (planning)
                 (ANAC)                   ↓
                    ↓                   PR #5
                    ├─→ PR #3         (ISTAT)
                    │   (OpenCUP)        ↓
                    │     ↓              ↓
                    └─→ PR #4 ←─────────┘
                       (Entity)
                         ↓
                       PR #6
                      (Assets)
                         ↓
                       PR #7
                    (Cross-src)
                         ↓
                       PR #8
                      (Agent)
```

## Parallel Workstream Assignments

### Team A (Data Ingestion) - Weeks 1-10
- **Lead:** ETL Specialist
- **Tasks:**
  - Week 1-2: PR #1 setup (share with Team B)
  - Week 3-4: PR #2 (ANAC) – 2 people
  - Week 5-6: PR #3 (OpenCUP) – 1 person
  - Week 7-8: PR #4 (Entity Res.) – 1-2 people
  - Week 9-10: PR #5 (ISTAT) – 1 person
  - **Parallel:** PR #5 can start Week 7-8

### Team B (Data Quality & Enrichment) - Weeks 7-14
- **Lead:** Data Quality Engineer
- **Tasks:**
  - Week 1-2: PR #1 setup (share with Team A)
  - Week 7-8: PR #4 (Entity Res. algorithms) – 2 people
  - Week 9-10: PR #5 (Anomaly detection) – 1-2 people
  - Week 11-12: PR #6 (Asset matching) – 1 person
  - Week 13-14: PR #7 (Provenance) – 1 person

### Team C (Application) - Weeks 15-16
- **Lead:** Backend/ML Engineer
- **Tasks:**
  - Week 15-16: PR #8 (Agent + API) – 2-3 people
  - Can start minimal prototype in Week 10-12

---

## PR Status Tracking Template

```markdown
## PR #N: [Title]

**Status:** ⏳ In Progress / ✅ Completed / ❌ Blocked

**Timeline:**
- Start Date: Week X, Day 1
- Target Completion: Week Y, Day 5
- Actual Completion: [TBD]

**Completion Checklist:**
- [ ] Code complete & reviewed
- [ ] Tests >75% coverage
- [ ] Documentation updated
- [ ] Integration tests passing
- [ ] Performance benchmarks met
- [ ] Merged to main

**Blockers:** None / [Description]
**Notes:** [Any relevant updates]
```

---

## Weekly Sync Agenda

### Format: 30-min standup (same time each week)

**Each team reports:**
1. What was accomplished this week?
2. What % of the PR is complete?
3. Any blockers or risks?
4. What's the plan for next week?

**Escalations:**
- Data availability delays (e.g., ANAC API downtime)
- Schema mismatches between sources
- Performance issues in Neo4j
- Dependency conflicts

### Sample Week 4 Standup

```
Team A (Ingest):
- PR #2 (ANAC) 85% complete
  - Downloaded 8 months of data
  - Transform pipeline stable
  - Quality checks 90% of records pass
- Blocker: Some OCDS records missing date fields
  - Mitigation: Default to NULL, flag for review

Team B (Quality):
- Prepping for PR #4 entity resolution algorithms
- Reviewed PR #2 data quality report
- Entity blocking heuristics drafted

Team C (App):
- Started GraphRAG proof-of-concept (early)
- Researching LLM for Cypher generation

Next Week:
- PR #2 merge expected
- PR #3 (OpenCUP) kicks off
- PR #4 design review scheduled
```

---

## Milestones & Gates

### ✅ Gate 1: ANAC Foundation (Week 4, end)
**Criteria:**
- PR #2 merged
- 200k+ tenders loaded
- Quality score >85%
- **Local Performance:** Latency <1s for 10k tender query on laptop hardware
- **Resilience:** CI/CD validated for local Docker environment

**Approval:** Data Lead signs off

---

### ✅ Gate 2: MVP Multi-Source (Week 8, end)
**Criteria:**
- PR #2, #3, #4 merged
- CUP-CIG match rate >70%
- Entity deduplication working
- Total nodes: 500k+ (tenders + companies + projects)
- All 8 main query patterns working

**Approval:** Product Owner

---

### ✅ Gate 3: Full Integration (Week 14, end)
**Criteria:**
- PR #1-7 merged
- 1M+ nodes in graph
- **Historical Integrity:** Updates to tenders/projects do not overwrite previous data (Version tracking)
- **ISTAT Stability:** Successful mapping across municipality historical changes
- Provenance 100% tracked
- 0 critical data issues
- 95%+ entity resolution accuracy

**Approval:** CTO

---

### ✅ Gate 4: Production Ready (Week 16, end)
**Criteria:**
- PR #8 merged
- GraphRAG agent >85% answer quality
- API latency <2s (p95)
- **Local Workstation Uptime:** Stable execution on designated machine
- Load test: 100 concurrent queries (simulated locally)

**Approval:** Release Manager

---

## Resource Allocation

```
Total: ~3-4 FTE over 16 weeks

Week 1-2:   2 people (Team A + B co-lead)
Week 3-4:   2 people (Team A: ANAC)
Week 5-6:   2 people (Team A: OpenCUP, Team B: prep)
Week 7-8:   3 people (Team A: final ingest, Team B: ER, Team C: prep)
Week 9-10:  3 people (Team A: ISTAT, Team B: anomaly, Team C: prep)
Week 11-12: 3 people (Team B: assets, Team C: early agent)
Week 13-14: 2 people (Team B: provenance, Team C: agent dev)
Week 15-16: 3 people (Team C: agent + API + dashboard)
```

---

## Budget Estimate

**Assuming €75/hr average salary equivalent:**

| Category | Hours | Cost |
|----------|-------|------|
| Development (code) | 400 | €30k |
| Testing | 100 | €7.5k |
| Documentation | 60 | €4.5k |
| Infrastructure (Neo4j cloud, APIs) | 200 hrs equivalent setup + 1yr | €5k-10k |
| **Total** | **760 hrs** | **€47-52k** |

---

## Risk Heat Map

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| ANAC API rate limiting | Medium | Medium | Cache aggressively, backoff strategy |
| Entity resolution accuracy <70% | Medium | High | Manual validation on 5%, iterative tuning |
| Neo4j performance at 1M nodes | Low | High | Index optimization Phase 1, sharding plan |
| Matching (CUP-CIG) <60% | Medium | High | Multi-strategy approach, manual fallback |
| Data quality flags >20% | Medium | Low | Quality checks Phase 2, document exceptions |
| Scope creep (more sources) | High | Medium | Prioritize 6 core sources, phase 2 for rest |
| Team churn | Low | High | Good documentation, knowledge transfer |

---

## Definition of Done (DoD) per PR

Every PR must satisfy:

1. **Code Quality**
   - [ ] >75% unit test coverage
   - [ ] Linting passes (Flake8, Black)
   - [ ] Type hints (MyPy clean)
   - [ ] Code review: ≥2 approvals

2. **Testing**
   - [ ] Unit tests pass
   - [ ] Integration tests pass (real/test data)
   - [ ] Edge cases documented + tested

3. **Documentation**
   - [ ] README for module
   - [ ] Data dictionary (for ETL PRs)
   - [ ] Query examples (for query PRs)
   - [ ] Deployment instructions

4. **Performance**
   - [ ] Benchmarks met (ETL: >1k rec/sec, Query: <2s)
   - [ ] No memory leaks (profiler check)
   - [ ] Logging + monitoring in place

5. **Safety**
   - [ ] Provenance tracking (source, version, confidence)
   - [ ] Audit log entries (for data modifications)
   - [ ] Error handling + retry logic

6. **Merge**
   - [ ] CI/CD passes
   - [ ] No conflicts
   - [ ] Schema validation passes
   - [ ] DB migration script tested (if applicable)

---

## Post-Launch (Phase 9+)

After Week 16, ongoing work:

- **Weeks 17-20:** Pilot testing (select users)
- **Weeks 21-24:** Production deployment + monitoring
- **Week 25+:** Maintenance, feature requests, data updates

---

## Appendix: Tools & Infrastructure

### Required Tools
- **Graph DB:** Neo4j 5.x (Community or Enterprise)
- **ETL:** Polars (Python)
- **NLP:** SentenceTransformers, Levenshtein
- **ML:** Scikit-learn (Isolation Forest), NumPy
- **API:** FastAPI, Uvicorn
- **Agent:** LangChain + GPT-4
- **CI/CD:** GitHub Actions
- **Version Control:** Git
- **Containerization:** Docker, Docker Compose

### Recommended Hosting (Cloud)
- **Neo4j:** Neo4j AuraDB (managed) or self-hosted on GCP/AWS
- **API:** GCP Cloud Run / AWS Lambda (serverless) or GCP Compute Engine
- **Redis (Cache):** GCP Memorystore or AWS ElastiCache
- **Logs/Monitoring:** ELK Stack or GCP Logging

---

## Sign-Off

- **Project Lead:** ________________ Date: ___________
- **Data Lead:** ________________ Date: ___________
- **CTO:** ________________ Date: ___________

