// ============================================================================
// PALADINO - Italian Public Funds Knowledge Graph
// Schema Definition (Neo4j 5.x)
// ============================================================================
// This file defines all node types and relationships for the multi-source
// knowledge graph integrating ANAC, OpenCUP, ISTAT, Demanio, ARERA, and MIT.
// ============================================================================

// ============================================================================
// NODE LABELS
// ============================================================================

// --- Company Nodes ---
// Represents companies/organizations from multiple sources
// Primary sources: ANAC (winners), Registro Imprese, ISTAT
// Properties defined in constraints.cypher

// --- Tender Nodes ---
// ANAC procurement tenders (Gare d'appalto)
// Unique identifier: CIG (Codice Identificativo Gara)

// --- Project Nodes ---
// OpenCUP funded projects
// Unique identifier: CUP (Codice Unico Progetto)

// --- DatasetContext Nodes ---
// ISTAT socio-economic context data
// Linked to geographic entities (Comune, Provincia, Regione)

// --- Asset Nodes ---
// Public assets from Demanio, ARERA, MIT
// Types: immobile, infrastruttura, rete_energia, etc.

// --- Version Nodes ---
// Temporal history tracking for data updates/rectifications
// Linked to any entity that changes over time

// --- Buyer Nodes ---
// Public administration entities that issue tenders
// Sources: ANAC

// --- FundingSource Nodes ---
// Funding sources for projects (PNRR, FESR, FSE, etc.)

// --- Sector Nodes ---
// ATECO sector classification

// --- Municipality Nodes ---
// ISTAT municipality entities with evolution tracking

// --- FraudPattern Nodes ---
// Named fraud detection results persisted for auditability and querying.
// Created by FraudPatternLibrary after analysis runs.
// Properties:
//   id:               UUID
//   pattern_name:     e.g. "bid_rotation", "split_tendering"
//   severity:         low | medium | high | critical
//   description:      Human-readable description of the pattern
//   evidence_summary: JSON-serialized dict of supporting evidence
//   detected_at:      datetime of detection
//   run_id:           UUID of the analysis run (for batch grouping)

// ============================================================================
// RELATIONSHIP TYPES
// ============================================================================

// Company → Tender
// (:Company)-[:WINS]->(:Tender)
// Properties: data, importo, percentuale_del_importo, confidence

// Tender → Buyer
// (:Tender)-[:AWARDED_BY]->(:Buyer)
// Properties: data

// Tender → Project
// (:Tender)-[:PART_OF_PROJECT]->(:Project)
// Properties: confidence, matching_method, match_date

// Project → FundingSource
// (:Project)-[:FUNDED_BY]->(:FundingSource)
// Properties: importo, percentuale, fonte

// Company → DatasetContext
// (:Company)-[:LOCATED_IN]->(:DatasetContext)
// Properties: distance_km

// Project → Asset
// (:Project)-[:INVOLVES_ASSET]->(:Asset)
// Properties: ruolo, tipo_intervento

// Company → Company (Shareholding)
// (:Company)-[:SHARES_UBO]->(:Company)
// Properties: percentuale, cf_persona, ruolo

// Any entity → FraudPattern (Flagged by a named fraud detector)
// (:Company|:Tender|:Buyer)-[:FLAGGED_BY]->(:FraudPattern)
// Properties: detected_at, score (0.0-1.0), evidence (JSON string)

// Company → Company (Supply chain — prime contractor to subcontractor)
// (:Company)-[:SUBCONTRACTS_TO {cig, cup, ruolo, ateco, importo, data_estrazione, source}]->(:Company)
// Populated by the PNRR Subappaltatori ETL (data/pnnr/PNRR_Subappaltatori_Gare.csv).
// Multiple relationships can exist between the same pair (one per CIG).

// Company → Company (Generic supply relationship)
// (:Company)-[:SUPPLIES_TO {importo, category, data, confidence, source}]->(:Company)
// Populated by future Registro Imprese / custom CSV imports.

// Person / Company → Company (Board membership)
// (:Person)-[:REPRESENTS {ruolo, data_inizio, data_fine, source}]->(:Company)
// Corporate director / administrator link.
// Source: Registro Imprese (when available), PNRR soggetti role fields.

// Person / Company → Company (Ownership)
// (:Person|:Company)-[:SHAREHOLDER_OF {quota, data_rilevazione, source}]->(:Company)
// Ownership percentage 0-100. Used by SHARES_UBO traversal and shell-company detection.

// Company → Company (UBO / indirect common owner — pre-computed convenience edge)
// (:Company)-[:SHARES_UBO {percentuale, cf_persona, ruolo}]->(:Company)
// Set by the corporate ETL when two companies share a beneficial owner.
// Also used directly in detect_ubo_conflict() in FraudPatternLibrary.

// Company → Sector
// (:Company)-[:OPERATES_IN_SECTOR]->(:Sector)
// Properties: peso

// Entity → Version (History)
// (:Company|:Tender|:Project)-[:HAS_HISTORY]->(:Version)

// Municipality → Municipality (Evolution)
// (:Municipality)-[:EVOLVED_INTO]->(:Municipality)
// Properties: date, reason

// ============================================================================
// SAMPLE DATA STRUCTURE
// ============================================================================

// Example Company node:
// CREATE (c:Company {
//   id: "uuid-123",
//   cf: "12345678901",
//   piva: "IT12345678901",
//   nomeNormalizzato: "ACME SRL",
//   nomeOriginale: "Acme S.r.l.",
//   provincia: "VE",
//   regione: "Veneto",
//   ateco: "64.99",
//   source: ["ANAC", "RegistroImprese"],
//   datasetVersion: "2026-01",
//   retrievalDate: datetime(),
//   confidence: 0.95
// })

// Example Tender node:
// CREATE (t:Tender {
//   id: "uuid-456",
//   cig: "Z1234567890",
//   oggetto: "Fornitura servizi IT",
//   importo: 150000.0,
//   dataAggiudicazione: date("2024-03-15"),
//   procedura: "open",
//   source: "ANAC",
//   datasetVersion: "2026-01"
// })

// Example relationship:
// MATCH (c:Company {cf: "12345678901"})
// MATCH (t:Tender {cig: "Z1234567890"})
// CREATE (c)-[:WINS {
//   data: date("2024-03-15"),
//   importo: 150000.0,
//   confidence: 0.95
// }]->(t)
