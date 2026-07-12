# Development Plan: Tier 4 - Production Stress Test

## 1. Instrumentation & Benchmarking
- [ ] Create `scripts/benchmarks/run_benchmark.py`.
- [ ] Implement `Profiler`: Wrapper for `cProfile` and Neo4j `PROFILE` command.
- [ ] Baseline run: Measure current performance on a 100k node sample.

## 2. ETL Optimization
- [ ] Update `paladino/etl/base_loader.py` to use `polars.scan_csv()` for streaming.
- [ ] Optimize Neo4j transaction handling: Use explicit `begin_transaction()` with periodic commits.
- [ ] Implement `ParallelLoader` if needed (multi-threaded ingest).

## 3. Query & Analytics Tuning
- [ ] Analyze `TemporalCypherRewriter` regex performance; switch to pre-compiled patterns or faster parser if bottlenecked.
- [ ] Optimize `ConfidenceEngine`: Use Cypher projections for the propagation loop to avoid Python overhead.
- [ ] Ensure all temporal lookups are backed by `(valid_from, id)` composite indexes.

## 4. Full Scale Load
- [ ] Execute load of `PNRR_Soggetti.csv` (550MB).
- [ ] Execute `oracle-temporal` on the full graph.
- [ ] Run a suite of 50 "Stress Queries" (NL + Templates) and record latencies.

## 5. Reporting
- [ ] Generate `PERFORMANCE_REPORT.md` with final throughput and latency stats.
