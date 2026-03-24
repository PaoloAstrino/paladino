# 📊 Paladino Knowledge Graph Schema

Paladino uses a **Federated Digital Twin** approach to map Italian public spending.

## Core Ontology

```mermaid
graph TD
    %% Main Nodes
    C[Company]
    T[Tender]
    P[Project]
    B[Buyer]
    FS[FundingSource]
    M[Municipality]
    R[Region]

    %% Relationships
    C -- "WINS {importo, data}" --> T
    T -- "PART_OF_PROJECT" --> P
    B -- "ISSUES" --> T
    P -- "FUNDED_BY" --> FS
    C -- "LOCATED_IN" --> M
    M -- "IN_REGION" --> R
    P -- "LOCATED_IN" --> M

    %% Labels & Risk
    C -- "risk_score"
    T -- "red_flags"
```

## Data Integration Flow

1.  **ANAC (Procurement):** Tenders (CIG), Winners (CF), Buyers.
2.  **OpenCUP (Funding):** Strategic Projects (CUP), Multi-year budget, PNRR mapping.
3.  **ISTAT (Geo):** Population, demographic decline markers for context.
4.  **Deduplication:** Fuzzy entity resolution merges duplicate companies from different sources.

## Strategic Questions Solved
- *"Which companies win tenders in areas with declining population?"*
- *"Is there a concentration of PNRR funds in specific corporate clusters?"*
- *"Are there 'Single-Bidder' monopolies in high-value regional projects?"*
