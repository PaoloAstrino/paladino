# Validation: Tier 4 - Production Stress Test

## Acceptance Criteria
- [ ] **Throughput:** ETL processes >= 10,000 entities/second on the 550MB dataset.
- [ ] **Query Latency:** Average response time for NL queries < 800ms (P95).
- [ ] **Memory Stability:** Peak RAM usage < 16GB during ETL and Confidence Propagation.
- [ ] **Data Integrity:** Count of nodes in Neo4j matches the row count in the CSV files.
- [ ] **Profiling Evidence:** All major bottlenecks identified and addressed (documented in `PERFORMANCE_REPORT.md`).

## How to Test
1. **Clean Start:** Wipe Neo4j database (`MATCH (n) DETACH DELETE n`).
2. **Run Benchmarked ETL:** `python scripts/benchmarks/run_benchmark.py --task etl --file data/pnnr/PNRR_Soggetti.csv`.
3. **Run Analytics Stress:** `python scripts/benchmarks/run_benchmark.py --task confidence`.
4. **Run Query Stress:** `python scripts/benchmarks/run_benchmark.py --task queries --count 50`.
5. **Inspect Profiler:** Review `benchmarks/output/profile.stats`.

## Definition of Done
- [ ] All ETL optimizations implemented.
- [ ] 550MB dataset successfully loaded.
- [ ] Sub-second query latency verified at scale.
- [ ] Performance report generated.
