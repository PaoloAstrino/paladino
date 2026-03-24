# Provenance Specification

## Overview

Paladino implements comprehensive provenance tracking to ensure all data is auditable and traceable to its original source.

## Provenance Metadata

Every node and relationship includes provenance metadata:

```python
{
    "source": ["ANAC", "OpenCUP"],      # List of data sources
    "datasetVersion": "2026-01",         # Dataset version identifier
    "retrievalDate": "2026-02-09T18:00:00Z",  # When data was retrieved
    "confidence": 0.95                   # Confidence score (0-1)
}
```

## Source Identifiers

| Source | Identifier | Description |
|--------|-----------|-------------|
| ANAC | `"ANAC"` | Procurement tenders (OCDS) |
| OpenCUP | `"OpenCUP"` | Funded projects |
| Registro Imprese | `"RegistroImprese"` | Company registry |
| ISTAT | `"ISTAT"` | Socio-economic statistics |
| Demanio | `"Demanio"` | Public real estate |
| ARERA | `"ARERA"` | Energy/utility assets |
| MIT | `"MIT"` | Transport infrastructure |

## Multi-Source Entities

When an entity appears in multiple sources, the `source` field is a list:

```cypher
CREATE (c:Company {
  cf: "12345678901",
  nomeNormalizzato: "ACME SRL",
  source: ["ANAC", "RegistroImprese"],  // Multi-source
  confidence: 0.98
})
```

## Confidence Scoring

Confidence scores indicate data quality and match certainty:

| Score | Meaning | Example |
|-------|---------|---------|
| 1.0 | Exact match | CF exact match across sources |
| 0.95 | High confidence | Direct OCDS data |
| 0.85 | Good match | Temporal + amount matching |
| 0.75 | Fuzzy match | Semantic similarity matching |
| <0.75 | Low confidence | Requires manual review |

## Temporal Versioning

Changes to entities are tracked via `Version` nodes:

```cypher
MATCH (t:Tender {cig: "Z1234567890"})
CREATE (v:Version {
  id: randomUUID(),
  entityId: t.cig,
  propertyChanged: "importo",
  oldValue: "150000",
  newValue: "175000",
  changeDate: datetime(),
  source: "ANAC"
})
CREATE (t)-[:HAS_HISTORY]->(v)
```

## Audit Trail

All data modifications are logged with:
- **Who**: System/user identifier
- **What**: Entity and property changed
- **When**: Timestamp
- **Why**: Source dataset update

## Lineage Queries

### Find all sources for a company

```cypher
MATCH (c:Company {cf: "12345678901"})
RETURN c.source as sources, c.confidence
```

### Track tender amount history

```cypher
MATCH (t:Tender {cig: "Z1234567890"})-[:HAS_HISTORY]->(v:Version)
WHERE v.propertyChanged = "importo"
RETURN v.changeDate, v.oldValue, v.newValue, v.source
ORDER BY v.changeDate
```

### Find low-confidence matches

```cypher
MATCH (n)
WHERE n.confidence < 0.80
RETURN labels(n) as type, n.id, n.confidence
ORDER BY n.confidence
LIMIT 100
```

## Data Quality Flags

Entities may have quality flags:

```python
{
  "anomalyFlags": [
    "missing_piva",
    "single_bidder",
    "amount_outlier"
  ]
}
```

## Compliance

This provenance model supports:
- **GDPR**: Data lineage for deletion requests
- **Audit**: Full traceability for public spending
- **Reproducibility**: Dataset version tracking
