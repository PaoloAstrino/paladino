// ============================================================================
// PALADINO - Constraints Definition
// ============================================================================
// Uniqueness constraints and mandatory properties for data integrity
// ============================================================================

// ============================================================================
// COMPANY CONSTRAINTS
// ============================================================================

// Unique Codice Fiscale
CREATE CONSTRAINT unique_company_cf IF NOT EXISTS
FOR (c:Company) REQUIRE c.cf IS UNIQUE;

// Unique Partita IVA (when present)
CREATE CONSTRAINT unique_company_piva IF NOT EXISTS
FOR (c:Company) REQUIRE c.piva IS UNIQUE;

// Mandatory properties
CREATE CONSTRAINT company_id_exists IF NOT EXISTS
FOR (c:Company) REQUIRE c.id IS NOT NULL;

// ============================================================================
// TENDER CONSTRAINTS
// ============================================================================

// Unique CIG (Codice Identificativo Gara)
CREATE CONSTRAINT unique_tender_cig IF NOT EXISTS
FOR (t:Tender) REQUIRE t.cig IS UNIQUE;

// Mandatory properties
CREATE CONSTRAINT tender_id_exists IF NOT EXISTS
FOR (t:Tender) REQUIRE t.id IS NOT NULL;

CREATE CONSTRAINT tender_importo_exists IF NOT EXISTS
FOR (t:Tender) REQUIRE t.importo IS NOT NULL;

// ============================================================================
// PROJECT CONSTRAINTS
// ============================================================================

// Unique CUP (Codice Unico Progetto)
CREATE CONSTRAINT unique_project_cup IF NOT EXISTS
FOR (p:Project) REQUIRE p.cup IS UNIQUE;

// Mandatory properties
CREATE CONSTRAINT project_id_exists IF NOT EXISTS
FOR (p:Project) REQUIRE p.id IS NOT NULL;

// ============================================================================
// VERSION CONSTRAINTS (Temporal History)
// ============================================================================

CREATE CONSTRAINT version_id_exists IF NOT EXISTS
FOR (v:Version) REQUIRE v.id IS NOT NULL;

CREATE CONSTRAINT version_entity_exists IF NOT EXISTS
FOR (v:Version) REQUIRE v.entityId IS NOT NULL;

// ============================================================================
// BUYER CONSTRAINTS
// ============================================================================

CREATE CONSTRAINT unique_buyer_cf IF NOT EXISTS
FOR (b:Buyer) REQUIRE b.cf IS UNIQUE;

// ============================================================================
// ASSET CONSTRAINTS
// ============================================================================

CREATE CONSTRAINT asset_id_exists IF NOT EXISTS
FOR (a:Asset) REQUIRE a.id IS NOT NULL;

// ============================================================================
// MUNICIPALITY CONSTRAINTS
// ============================================================================

CREATE CONSTRAINT unique_municipality_code IF NOT EXISTS
FOR (m:Municipality) REQUIRE m.cod_istat IS UNIQUE;

// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
// PERSON CONSTRAINTS
// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

CREATE CONSTRAINT unique_person_cf IF NOT EXISTS
FOR (p:Person) REQUIRE p.cf IS UNIQUE;

// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
// ASSET CONSTRAINTS
// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

CREATE CONSTRAINT unique_asset_id IF NOT EXISTS
FOR (a:Asset) REQUIRE a.id_immobile IS UNIQUE;

// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
// SECTOR CONSTRAINTS (ATECO)
// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

CREATE CONSTRAINT unique_ateco_code IF NOT EXISTS
FOR (s:Sector) REQUIRE s.cod_ateco IS UNIQUE;

// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::
// FRAUD PATTERN CONSTRAINTS
// = :::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

CREATE CONSTRAINT unique_fraud_pattern_id IF NOT EXISTS
FOR (f:FraudPattern) REQUIRE f.id IS UNIQUE;

CREATE CONSTRAINT fraud_pattern_name_exists IF NOT EXISTS
FOR (f:FraudPattern) REQUIRE f.pattern_name IS NOT NULL;

// ============================================================================
// UNIVERSAL INGESTION CONSTRAINTS
// ============================================================================

// Stable key for extracted entities (used by unstructured loader)
CREATE CONSTRAINT unique_entity_canonical_key IF NOT EXISTS
FOR (e:Entity) REQUIRE e.canonical_key IS UNIQUE;

// One source node per ingested file/url
CREATE CONSTRAINT unique_source_document_source IF NOT EXISTS
FOR (d:SourceDocument) REQUIRE d.source IS UNIQUE;
