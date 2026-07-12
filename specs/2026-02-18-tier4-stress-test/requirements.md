# Requirements: Tier 4 - Production Stress Test & Performance Tuning

## Overview
This phase marks the transition from "MVP" to "Production Ready." We will load the full 550MB PNRR dataset and optimize the system to handle millions of nodes and relationships while maintaining the unique forensic features (Temporal Rewriting, Confidence Propagation) under heavy load.

## Problem
A system that works on 10,000 nodes might crawl or crash when handling 10,000,000 nodes. Specifically:
- `TemporalCypherRewriter` regex overhead might slow down queries.
- Recursive Confidence Propagation might exceed RAM or stack limits.
- Polars-to-Neo4j ETL might bottleneck on single-threaded drivers.

## Goals
- **Load Scale:** Process 550MB of raw CSV data into Neo4j in under 15 minutes.
- **Latency Target:** 95% of NL-to-Cypher queries must execute in < 500ms on the full graph.
- **Memory Bound:** RAM usage must not exceed 16GB during peak ETL.
- **Deep Bottleneck Visibility:** Identify the slowest Cypher clauses and Python functions using profiling.

## Non-goals
- Scaling to a multi-node Neo4j Cluster (we remain local-first).
- Optimizing for real-time streaming (we remain batch-first).

## User Stories
- **As an analyst,** I want to query a database of 10M entities without waiting more than a few seconds for an answer.
- **As a system administrator,** I want to know that the nightly data load won't crash the laptop's memory.

## Technical Considerations
- **Neo4j Batching:** Aggressive use of `UNWIND` with batches of 10,000.
- **Polars Streaming:** Ensure `scan_csv` is used to avoid loading the full 550MB into Python RAM.
- **Indexing:** Ensure all CF, CIG, CUP, and IDs have unique constraints and range indexes.
