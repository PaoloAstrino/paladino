# Performance Tuning Guide

## Local High-Performance Configuration

This guide provides optimization strategies for running Paladino on a single workstation (16-32GB RAM).

## Neo4j Memory Configuration

### For 16GB RAM Workstation

Edit your `docker-compose.yml` or Neo4j configuration:

```yaml
environment:
  - NEO4J_server_memory_heap_initial__size=4G
  - NEO4J_server_memory_heap_max__size=4G
  - NEO4J_server_memory_pagecache_size=6G
  - NEO4J_server_tx__state_memory__allocation=OFF_HEAP
```

### For 32GB RAM Workstation

```yaml
environment:
  - NEO4J_server_memory_heap_initial__size=8G
  - NEO4J_server_memory_heap_max__size=8G
  - NEO4J_server_memory_pagecache_size=16G
  - NEO4J_server_tx__state_memory__allocation=OFF_HEAP
```

## Storage Optimization

### NVMe SSD Placement

Ensure Neo4j data directory is on an NVMe SSD:

```yaml
volumes:
  - /path/to/nvme/neo4j_data:/data
```

**Expected Performance:**
- Random read latency: <100μs
- Sequential read: >2GB/s

### Bulk Loading

For initial data loads, use `neo4j-admin import`:

```bash
docker exec -it paladino-neo4j neo4j-admin database import full \
  --nodes=Company=companies.csv \
  --nodes=Tender=tenders.csv \
  --relationships=WINS=wins.csv \
  neo4j
```

**Benefits:**
- 10-100x faster than transactional loading
- Bypasses transaction log overhead

## Query Optimization

### Index Usage

Verify index usage with `EXPLAIN`:

```cypher
EXPLAIN MATCH (c:Company {regione: "Veneto"})
RETURN c
```

Look for `NodeIndexSeek` in the execution plan.

### Query Caching

Enable query caching in Neo4j:

```yaml
environment:
  - NEO4J_dbms_query__cache__size=1000
```

## Monitoring

### Memory Usage

Check current memory allocation:

```cypher
CALL dbms.listPools()
```

### Query Performance

Monitor slow queries:

```cypher
CALL dbms.listQueries()
YIELD query, elapsedTimeMillis
WHERE elapsedTimeMillis > 1000
RETURN query, elapsedTimeMillis
ORDER BY elapsedTimeMillis DESC
```

## Maintenance

### Version Node Pruning

Archive old `Version` nodes to Parquet if they exceed 20% of total nodes:

```python
# Export to Parquet
import polars as pl
from paladino.db import get_driver

with get_driver() as driver:
    with driver.session() as session:
        result = session.run("""
            MATCH (v:Version)
            WHERE v.change_date < date() - duration({months: 6})
            RETURN v
        """)
        
        df = pl.DataFrame([dict(r['v']) for r in result])
        df.write_parquet("version_archive.parquet")
```

## Benchmarks

Expected performance on 16GB RAM workstation:

| Operation | Target | Actual |
|-----------|--------|--------|
| 10k tender query | <1s | TBD |
| Company lookup by CF | <50ms | TBD |
| Multi-hop query (3 hops) | <2s | TBD |
| Bulk load (100k nodes) | <5min | TBD |
