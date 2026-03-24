# Data Model

## Overview

The Paladino knowledge graph integrates data from 6+ Italian public sources into a unified graph model.

## Node Types

### Company

Represents companies and organizations from multiple sources.

**Properties:**
- `id`: UUID (unique)
- `cf`: Codice Fiscale (unique)
- `piva`: Partita IVA (unique, optional)
- `nomeNormalizzato`: Normalized company name
- `provincia`, `regione`: Location
- `ateco`: Sector code
- `riskScore`: Risk assessment (0-1)
- `source`: List of data sources
- `confidence`: Data confidence score

**Sources:** ANAC, Registro Imprese, ISTAT

### Tender

ANAC procurement tenders.

**Properties:**
- `id`: UUID
- `cig`: Codice Identificativo Gara (unique)
- `oggetto`: Tender description
- `importo`: Amount in EUR
- `dataAggiudicazione`: Award date
- `procedura`: Procurement method
- `redFlags`: List of anomaly flags

**Source:** ANAC

### Project

OpenCUP funded projects.

**Properties:**
- `id`: UUID
- `cup`: Codice Unico Progetto (unique)
- `titolo`: Project title
- `importoPrevisto`: Budget
- `fondiComunitari`: EU funds (PNRR, FESR, etc.)
- `stato`: Status (In programmazione, In attuazione, Concluso)
- `regione`: Region

**Source:** OpenCUP

### Version

Temporal history tracking for data changes.

**Properties:**
- `id`: UUID
- `entityId`: ID of changed entity
- `propertyChanged`: Property name
- `oldValue`, `newValue`: Change values
- `changeDate`: When the change occurred

### DatasetContext

ISTAT socio-economic context.

**Properties:**
- `codIstat`: ISTAT code
- `tipoGeo`: Geographic type (comune, provincia, regione)
- `metrica`: Metric name (popolazione, PIL, disoccupazione)
- `valore`: Metric value
- `anno`: Year

**Source:** ISTAT

### Asset

Public assets from Demanio, ARERA, MIT.

**Properties:**
- `id`: UUID
- `tipo`: Asset type (immobile, infrastruttura, rete_energia)
- `coordinate`: Geospatial point
- `valoreCatastale`: Cadastral value

**Sources:** Demanio, ARERA, MIT

## Relationships

### WINS

Company wins a tender.

```
(Company)-[:WINS]->(Tender)
```

**Properties:**
- `data`: Award date
- `importo`: Award amount
- `confidence`: Match confidence

### PART_OF_PROJECT

Tender is part of a project (via CUP-CIG matching).

```
(Tender)-[:PART_OF_PROJECT]->(Project)
```

**Properties:**
- `confidence`: Match confidence (0-1)
- `matchingMethod`: explicit, temporal, semantic

### FUNDED_BY

Project funded by a source.

```
(Project)-[:FUNDED_BY]->(FundingSource)
```

**Properties:**
- `importo`: Funding amount
- `percentuale`: Percentage of total

### LOCATED_IN

Company located in a geographic context.

```
(Company)-[:LOCATED_IN]->(DatasetContext)
```

### HAS_HISTORY

Entity has historical changes.

```
(Company|Tender|Project)-[:HAS_HISTORY]->(Version)
```

### EVOLVED_INTO

Municipality evolution (ISTAT code changes).

```
(Municipality)-[:EVOLVED_INTO]->(Municipality)
```

**Properties:**
- `date`: Evolution date
- `reason`: Reason (fusion, split, rename)

## Provenance Model

Every node includes provenance metadata:

```json
{
  "source": ["ANAC", "OpenCUP"],
  "datasetVersion": "2026-01",
  "retrievalDate": "2026-02-09T18:00:00Z",
  "confidence": 0.95
}
```

This enables:
- **Auditability**: Trace data to original source
- **Versioning**: Track dataset updates
- **Quality**: Confidence scoring for fuzzy matches

## Example Queries

### Find companies with PNRR projects

```cypher
MATCH (c:Company)-[:WINS]->(t:Tender)-[:PART_OF_PROJECT]->(p:Project)
WHERE "PNRR" IN p.fondiComunitari
RETURN c.nomeNormalizzato, count(p) as progetti_pnrr
ORDER BY progetti_pnrr DESC
LIMIT 10
```

### Track tender amount changes

```cypher
MATCH (t:Tender {cig: "Z1234567890"})-[:HAS_HISTORY]->(v:Version)
WHERE v.propertyChanged = "importo"
RETURN v.changeDate, v.oldValue, v.newValue
ORDER BY v.changeDate
```
