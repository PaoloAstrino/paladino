// ============================================================================
// PALADINO - Comment System Migration Script
// ============================================================================
// Run this script on Neo4j to set up the Comment/Annotation system.
// This creates all necessary constraints and indexes for the Comment node type.
//
// Usage:
//   1. Open Neo4j Browser
//   2. Run: :source schema/migrate_comments.cypher
//   OR
//   1. Use cypher-shell: cypher-shell -f schema/migrate_comments.cypher
// ============================================================================

// ============================================================================
// STEP 1: Create Constraints
// ============================================================================
// Constraints must be created before indexes for optimal performance.

// Unique comment ID constraint
CREATE CONSTRAINT unique_comment_id IF NOT EXISTS
FOR (c:Comment) REQUIRE c.id IS UNIQUE;

// Mandatory property constraints
CREATE CONSTRAINT comment_id_exists IF NOT EXISTS
FOR (c:Comment) REQUIRE c.id IS NOT NULL;

CREATE CONSTRAINT comment_entity_id_exists IF NOT EXISTS
FOR (c:Comment) REQUIRE c.entity_id IS NOT NULL;

CREATE CONSTRAINT comment_entity_type_exists IF NOT EXISTS
FOR (c:Comment) REQUIRE c.entity_type IS NOT NULL;

CREATE CONSTRAINT comment_content_exists IF NOT EXISTS
FOR (c:Comment) REQUIRE c.content IS NOT NULL;

CREATE CONSTRAINT comment_author_exists IF NOT EXISTS
FOR (c:Comment) REQUIRE c.author IS NOT NULL;

CREATE CONSTRAINT comment_created_at_exists IF NOT EXISTS
FOR (c:Comment) REQUIRE c.created_at IS NOT NULL;

// ============================================================================
// STEP 2: Create Indexes
// ============================================================================
// Indexes optimize query performance for common access patterns.

// Full-text search index (MUST be created after constraints)
// This enables efficient text search across comment content
CREATE TEXT INDEX idx_comment_content IF NOT EXISTS
FOR (c:Comment) ON (c.content);

// Basic lookup indexes for filtering
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

// Composite index for common entity-based queries
CREATE INDEX idx_comment_entity IF NOT EXISTS
FOR (c:Comment) ON (c.entity_id, c.entity_type);

// Temporal indexes for sorting
CREATE INDEX idx_comment_created_at IF NOT EXISTS
FOR (c:Comment) ON (c.created_at);

CREATE INDEX idx_comment_edited_at IF NOT EXISTS
FOR (c:Comment) ON (c.edited_at);

// Index for threaded comment lookups
CREATE INDEX idx_comment_parent_id IF NOT EXISTS
FOR (c:Comment) ON (c.parent_comment_id);

// Composite index for entity listing with sorting
CREATE INDEX idx_comment_entity_created IF NOT EXISTS
FOR (c:Comment) ON (c.entity_id, c.entity_type, c.created_at);

// ============================================================================
// STEP 3: Verify Installation
// ============================================================================
// Run these queries to verify the migration was successful:

// Check constraints
// SHOW CONSTRAINTS WHERE name CONTAINS 'comment'

// Check indexes
// SHOW INDEXES WHERE name CONTAINS 'comment'

// Test creating a sample comment
// CREATE (c:Comment {
//     id: "sample-comment-" + randomUUID(),
//     entity_id: "12345678901",
//     entity_type: "Company",
//     author: "system",
//     content: "Sample comment for testing",
//     parent_comment_id: null,
//     tags: ["sample", "test"],
//     mentions: [],
//     is_deleted: false,
//     created_at: datetime(),
//     edited_at: null,
//     source: "migration",
//     confidence: 1.0
// })
// RETURN c

// ============================================================================
// STEP 4: Rollback (if needed)
// ============================================================================
// To drop all comment constraints and indexes, run:

// DROP CONSTRAINT unique_comment_id;
// DROP CONSTRAINT comment_id_exists;
// DROP CONSTRAINT comment_entity_id_exists;
// DROP CONSTRAINT comment_entity_type_exists;
// DROP CONSTRAINT comment_content_exists;
// DROP CONSTRAINT comment_author_exists;
// DROP CONSTRAINT comment_created_at_exists;

// DROP INDEX idx_comment_content;
// DROP INDEX idx_comment_entity_id;
// DROP INDEX idx_comment_entity_type;
// DROP INDEX idx_comment_author;
// DROP INDEX idx_comment_tags;
// DROP INDEX idx_comment_is_deleted;
// DROP INDEX idx_comment_entity;
// DROP INDEX idx_comment_created_at;
// DROP INDEX idx_comment_edited_at;
// DROP INDEX idx_comment_parent_id;
// DROP INDEX idx_comment_entity_created;

// ============================================================================
// PERFORMANCE NOTES
// ============================================================================
// - Full-text index creation may take time for large datasets
// - Composite indexes optimize multi-field WHERE clauses
// - The entity+created_at index optimizes pagination queries
// - Monitor index creation progress with: SHOW INDEXES YIELD * WHERE state <> 'ONLINE'
// ============================================================================
