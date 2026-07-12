// ============================================================================
// PALADINO - Merge Rollback System Migration Script
// ============================================================================
// Run this script on Neo4j to set up the MergeRollback node type for audit
// and rollback capabilities for entity merge operations.
//
// Usage:
//   1. Open Neo4j Browser
//   2. Run: :source schema/migrate_merge_rollback.cypher
//   OR
//   1. Use cypher-shell: cypher-shell -f schema/migrate_merge_rollback.cypher
// ============================================================================

// ============================================================================
// STEP 1: Create Constraints
// ============================================================================
// Constraints must be created before indexes for optimal performance.

// Unique rollback ID constraint
CREATE CONSTRAINT unique_merge_rollback_id IF NOT EXISTS
FOR (r:MergeRollback) REQUIRE r.id IS UNIQUE;

// Mandatory property constraints
CREATE CONSTRAINT merge_rollback_id_exists IF NOT EXISTS
FOR (r:MergeRollback) REQUIRE r.id IS NOT NULL;

CREATE CONSTRAINT merge_rollback_created_at_exists IF NOT EXISTS
FOR (r:MergeRollback) REQUIRE r.created_at IS NOT NULL;

CREATE CONSTRAINT merge_rollback_target_id_exists IF NOT EXISTS
FOR (r:MergeRollback) REQUIRE r.target_id IS NOT NULL;

CREATE CONSTRAINT merge_rollback_source_ids_exists IF NOT EXISTS
FOR (r:MergeRollback) REQUIRE r.source_ids IS NOT NULL;

// ============================================================================
// STEP 2: Create Indexes
// ============================================================================
// Indexes optimize query performance for common access patterns.
// Note: Some indexes may already exist in indexes.cypher

// Lookup indexes for filtering
CREATE INDEX idx_merge_rollback_id IF NOT EXISTS
FOR (r:MergeRollback) ON (r.id);

CREATE INDEX idx_merge_rollback_created IF NOT EXISTS
FOR (r:MergeRollback) ON (r.created_at);

CREATE INDEX idx_merge_rollback_target_id IF NOT EXISTS
FOR (r:MergeRollback) ON (r.target_id);

CREATE INDEX idx_merge_rollback_status IF NOT EXISTS
FOR (r:MergeRollback) ON (r.status);

// Composite index for audit queries (status + created_at for filtering completed/rolled-back merges)
CREATE INDEX idx_merge_rollback_status_created IF NOT EXISTS
FOR (r:MergeRollback) ON (r.status, r.created_at);

// ============================================================================
// STEP 3: Verify Installation
// ============================================================================
// Run these queries to verify the migration was successful:

// Check constraints
// SHOW CONSTRAINTS WHERE name CONTAINS 'merge_rollback'

// Check indexes
// SHOW INDEXES WHERE name CONTAINS 'merge_rollback'

// Test creating a sample rollback snapshot
// CREATE (r:MergeRollback {
//     id: "merge_" + datetime().epochMillis + "_test123",
//     created_at: datetime(),
//     target_id: "1",
//     source_ids: ["2", "3"],
//     labels: ["Company"],
//     target_snapshot: {id: "1", cf: "12345678901", nome_normalizzato: "ACME SRL"},
//     source_snapshots: [
//         {id: "2", properties: {cf: "12345678901", nome_normalizzato: "ACME S.R.L."}},
//         {id: "3", properties: {cf: "12345678901", nome_normalizzato: "ACME"}}
//     ],
//     status: "COMPLETED",
//     merged_count: 2,
//     relationships_updated: 5
// })
// RETURN r

// ============================================================================
// STEP 4: Rollback (if needed)
// ============================================================================
// To drop all merge rollback constraints and indexes, run:

// DROP CONSTRAINT unique_merge_rollback_id;
// DROP CONSTRAINT merge_rollback_id_exists;
// DROP CONSTRAINT merge_rollback_created_at_exists;
// DROP CONSTRAINT merge_rollback_target_id_exists;
// DROP CONSTRAINT merge_rollback_source_ids_exists;

// DROP INDEX idx_merge_rollback_id;
// DROP INDEX idx_merge_rollback_created;
// DROP INDEX idx_merge_rollback_target_id;
// DROP INDEX idx_merge_rollback_status;
// DROP INDEX idx_merge_rollback_status_created;

// ============================================================================
// PERFORMANCE NOTES
// ============================================================================
// - The status+created_at composite index optimizes audit log queries
// - Index on target_id enables quick lookups of all merges involving a specific entity
// - Monitor index creation progress with: SHOW INDEXES YIELD * WHERE state <> 'ONLINE'
// ============================================================================
