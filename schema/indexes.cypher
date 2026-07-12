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
// MERGE & DEDUPLICATION INDEXES
// ============================================================================

// Uniqueness constraints for deduplication
CREATE CONSTRAINT company_cf_unique IF NOT EXISTS
FOR (c:Company) REQUIRE c.cf IS UNIQUE;

CREATE CONSTRAINT company_piva_unique IF NOT EXISTS
FOR (c:Company) REQUIRE c.piva IS UNIQUE;

// Index for merge review queries
CREATE INDEX idx_company_merge_candidates IF NOT EXISTS
FOR (c:Company) ON (c.nome_normalizzato, c.cod_istat);

// Index for rollback snapshots
CREATE INDEX idx_merge_rollback_id IF NOT EXISTS
FOR (r:MergeRollback) ON (r.id);

CREATE INDEX idx_merge_rollback_created IF NOT EXISTS
FOR (r:MergeRollback) ON (r.created_at);

// ============================================================================
// COMMENT INDEXES
// ============================================================================

// Full-text search on comment content
CREATE TEXT INDEX idx_comment_content IF NOT EXISTS
FOR (c:Comment) ON (c.content);

// Lookup indexes for filtering
CREATE INDEX idx_comment_entity_id IF NOT EXISTS
FOR (c:Comment) ON (c.entity_id);

CREATE INDEX idx_comment_entity_type IF NOT EXISTS
FOR (c:Comment) ON (c.entity_type);

CREATE INDEX idx_comment_author IF NOT EXISTS
FOR (c:Comment) ON (c.author);

CREATE INDEX idx_comment_tags IF NOT EXISTS
FOR (c:Comment) ON (c.tags);

CREATE INDEX idx_comment_is_deleted IF NOT EXISTS
FOR (c:Comment) ON (c.is_deleted);

// Composite index for common comment queries (entity filtering)
CREATE INDEX idx_comment_entity IF NOT EXISTS
FOR (c:Comment) ON (c.entity_id, c.entity_type);

// Temporal index for sorting
CREATE INDEX idx_comment_created_at IF NOT EXISTS
FOR (c:Comment) ON (c.created_at);

CREATE INDEX idx_comment_edited_at IF NOT EXISTS
FOR (c:Comment) ON (c.edited_at);

// Index for threaded comments (parent lookup)
CREATE INDEX idx_comment_parent_id IF NOT EXISTS
FOR (c:Comment) ON (c.parent_comment_id);

// Composite index for listing comments by entity with sorting
CREATE INDEX idx_comment_entity_created IF NOT EXISTS
FOR (c:Comment) ON (c.entity_id, c.entity_type, c.created_at);

// ============================================================================
// ALERT INDEXES
// ============================================================================

// Alert status filtering (most common filter)
CREATE INDEX idx_alert_status IF NOT EXISTS
FOR (a:Alert) ON (a.status);

// Alert type filtering
CREATE INDEX idx_alert_type IF NOT EXISTS
FOR (a:Alert) ON (a.type);

// Alert severity filtering
CREATE INDEX idx_alert_severity IF NOT EXISTS
FOR (a:Alert) ON (a.severity);

// Alert entity lookup
CREATE INDEX idx_alert_entity_id IF NOT EXISTS
FOR (a:Alert) ON (a.entity_id);

// Alert temporal sorting and date range queries
CREATE INDEX idx_alert_created_at IF NOT EXISTS
FOR (a:Alert) ON (a.created_at);

// Alert deduplication hash lookup
CREATE INDEX idx_alert_hash IF NOT EXISTS
FOR (a:Alert) ON (a.alert_hash);

// Composite index for common alert queries (status + created_at for dashboard)
CREATE INDEX idx_alert_status_created IF NOT EXISTS
FOR (a:Alert) ON (a.status, a.created_at);

// Composite index for entity-specific alert queries
CREATE INDEX idx_alert_entity_type_id IF NOT EXISTS
FOR (a:Alert) ON (a.entity_type, a.entity_id);

// Composite index for filtering by entity and sorting by date
CREATE INDEX idx_alert_entity_created IF NOT EXISTS
FOR (a:Alert) ON (a.entity_id, a.entity_type, a.created_at);

// Codice Fiscale lookup
CREATE INDEX idx_alert_entity_cf IF NOT EXISTS
FOR (a:Alert) ON (a.entity_cf);

// Rule ID lookup
CREATE INDEX idx_alert_rule_id IF NOT EXISTS
FOR (a:Alert) ON (a.rule_id);

// ============================================================================
// ALERT RULE INDEXES
// ============================================================================

// AlertRule enabled filtering (most common filter)
CREATE INDEX idx_alert_rule_enabled IF NOT EXISTS
FOR (r:AlertRule) ON (r.enabled);

// AlertRule type filtering
CREATE INDEX idx_alert_rule_type IF NOT EXISTS
FOR (r:AlertRule) ON (r.alert_type);

// AlertRule name lookup
CREATE INDEX idx_alert_rule_name IF NOT EXISTS
FOR (r:AlertRule) ON (r.name);

// ============================================================================
// PERFORMANCE NOTES
// ============================================================================
// - Text indexes enable CONTAINS/STARTS WITH queries
// - Composite indexes optimize multi-filter queries
// - Point indexes enable distance-based spatial queries
// - Relationship indexes improve aggregation performance
// - Uniqueness constraints prevent duplicate CF/P.IVA
