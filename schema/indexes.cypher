// ============================================================================
// PALADINO - Indexes Definition
// ============================================================================
// Performance optimization indexes for common query patterns
// ============================================================================

// ============================================================================
// TEXT SEARCH INDEXES
// ============================================================================

// Full-text search on company names
CREATE TEXT INDEX idx_company_name IF NOT EXISTS
FOR (c:Company) ON (c.nome_normalizzato);

// Full-text search on tender descriptions
CREATE TEXT INDEX idx_tender_oggetto IF NOT EXISTS
FOR (t:Tender) ON (t.oggetto);

// Full-text search on project descriptions
CREATE TEXT INDEX idx_project_descrizione IF NOT EXISTS
FOR (p:Project) ON (p.descrizione);

// ============================================================================
// LOOKUP INDEXES (Filtering)
// ============================================================================

// Company filters
CREATE INDEX idx_company_regione IF NOT EXISTS
FOR (c:Company) ON (c.regione);

CREATE INDEX idx_company_provincia IF NOT EXISTS
FOR (c:Company) ON (c.provincia);

CREATE INDEX idx_company_ateco IF NOT EXISTS
FOR (c:Company) ON (c.ateco);

CREATE INDEX idx_company_source IF NOT EXISTS
FOR (c:Company) ON (c.source);

// Composite index for common company queries
CREATE INDEX idx_company_regione_ateco IF NOT EXISTS
FOR (c:Company) ON (c.regione, c.ateco);

// Tender filters
CREATE INDEX idx_tender_importo IF NOT EXISTS
FOR (t:Tender) ON (t.importo);

CREATE INDEX idx_tender_procedura IF NOT EXISTS
FOR (t:Tender) ON (t.procedura);

CREATE INDEX idx_tender_source IF NOT EXISTS
FOR (t:Tender) ON (t.source);

// Project filters
CREATE INDEX idx_project_stato IF NOT EXISTS
FOR (p:Project) ON (p.stato);

CREATE INDEX idx_project_settore IF NOT EXISTS
FOR (p:Project) ON (p.settore);

CREATE INDEX idx_project_regione IF NOT EXISTS
FOR (p:Project) ON (p.regione);

// ============================================================================
// TEMPORAL INDEXES (Date-based queries)
// ============================================================================

// Tender award dates
CREATE INDEX idx_tender_date IF NOT EXISTS
FOR (t:Tender) ON (t.data_aggiudicazione);

// Project start dates
CREATE INDEX idx_project_start IF NOT EXISTS
FOR (p:Project) ON (p.data_inizio);

// Project end dates
CREATE INDEX idx_project_end IF NOT EXISTS
FOR (p:Project) ON (p.data_fine);

// Version change dates
CREATE INDEX idx_version_date IF NOT EXISTS
FOR (v:Version) ON (v.change_date);

// Composite temporal index for trend bucketing
// (enables efficient quarterly aggregation over award dates + amounts)
CREATE INDEX idx_tender_date_importo IF NOT EXISTS
FOR (t:Tender) ON (t.data_aggiudicazione, t.importo);

// ============================================================================
// SPATIAL INDEXES (Geospatial queries)
// ============================================================================

// Project locations
CREATE POINT INDEX idx_project_location IF NOT EXISTS
FOR (p:Project) ON (p.coordinate);

// Asset locations
CREATE POINT INDEX idx_asset_location IF NOT EXISTS
FOR (a:Asset) ON (a.coordinate);

// ============================================================================
// RELATIONSHIP INDEXES
// ============================================================================

// WINS relationship properties
CREATE INDEX idx_wins_importo IF NOT EXISTS
FOR ()-[w:WINS]-() ON (w.importo);

CREATE INDEX idx_wins_data IF NOT EXISTS
FOR ()-[w:WINS]-() ON (w.data);

// ============================================================================
// UNIVERSAL INGESTION INDEXES
// ============================================================================

CREATE INDEX idx_entity_type IF NOT EXISTS
FOR (e:Entity) ON (e.entity_type);

CREATE INDEX idx_entity_source_file IF NOT EXISTS
FOR (e:Entity) ON (e._source_file);

CREATE INDEX idx_source_document_type IF NOT EXISTS
FOR (d:SourceDocument) ON (d.source_type);

CREATE INDEX idx_source_document_extracted_at IF NOT EXISTS
FOR (d:SourceDocument) ON (d.extracted_at);

CREATE INDEX idx_related_to_relation_type IF NOT EXISTS
FOR ()-[r:RELATED_TO]-() ON (r.relation_type);

// ============================================================================
// PERFORMANCE NOTES
// ============================================================================
// - Text indexes enable CONTAINS/STARTS WITH queries
// - Composite indexes optimize multi-filter queries
// - Point indexes enable distance-based spatial queries
// - Relationship indexes improve aggregation performance
