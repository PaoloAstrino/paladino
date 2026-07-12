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
//
// TWO USE CASES:
//
// 1. General History Tracking (HAS_HISTORY relationship):
//    Properties:
//      id:               UUID
//      entityId:         ID of the entity that changed
//      propertyChanged:  Name of the property that changed
//      oldValue:         Previous value (as string)
//      newValue:         New value (as string)
//      changeDate:       datetime of change
//      snapshotType:     Type of snapshot: 'general', 'risk_score', etc.
//
// 2. Risk Score Snapshots (HAS_VERSION relationship):
//    Created by RiskEngine.save_risk_snapshot() after each risk analysis run.
//    Enables temporal analytics via TemporalAnalyzer.get_risk_score_history().
//    Properties:
//      id:               UUID (unique snapshot identifier)
//      entityId:         Company.id that this snapshot belongs to
//      risk_score:       FLOAT (0.0-1.0) - The risk score at snapshot time
//      change_date:      datetime - When the snapshot was created
//      snapshot_type:    STRING - Always 'risk_score' for risk snapshots
//      anomaly_flags:    LIST<STRING> - Active anomaly flags at snapshot time (optional)
//
//    Risk Tier Classification (computed at query time):
//      - HIGH:   risk_score >= 0.7
//      - MEDIUM: 0.4 <= risk_score < 0.7
//      - LOW:    risk_score < 0.4
//
//    Example Risk Snapshot:
//    CREATE (v:Version {
//      id: "snap-uuid-123",
//      entityId: "company-uuid-456",
//      risk_score: 0.75,
//      change_date: datetime("2024-01-15T10:30:00Z"),
//      snapshot_type: "risk_score",
//      anomaly_flags: ["high_single_bidder_ratio", "market_dominance_high"]
//    })

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

// --- Comment Nodes ---
// User/system annotations attached to any entity (Company, Tender, Project, etc.)
// Supports threaded conversations, entity mentions, and tagging.
// Properties:
//   id:               UUID
//   entity_id:        ID of the entity this comment is attached to
//   entity_type:      Type of entity: Company, Tender, Project, Person, Asset, Buyer, FraudPattern
//   author:           Author identifier (username or system)
//   content:          Comment text (max 10000 chars)
//   parent_comment_id: UUID of parent comment (null for top-level comments)
//   tags:             List of tag strings for categorization
//   mentions:         List of entity IDs mentioned in content (e.g., @Company:12345678901)
//   is_deleted:       Soft delete flag (default: false)
//   created_at:       datetime of creation
//   edited_at:        datetime of last edit (null if never edited)
//   source:           Comment source: user, system, import (default: user)
//   confidence:       Confidence score 0.0-1.0 (default: 1.0)
//   provenance:       ProvenanceMetadata object for audit trail

// --- MergeRollback Nodes ---
// Audit and rollback snapshots for entity merge operations.
// Created before merging duplicate entities to enable rollback if needed.
// Properties:
//   id:                 UUID (format: "merge_{timestamp}_{short_uuid}")
//   created_at:         datetime of snapshot creation
//   target_id:          ID of the target entity (surviving node after merge)
//   source_ids:         List of source entity IDs that were merged away
//   labels:             List of Neo4j labels for the merged entities (e.g., ["Company"])
//   target_snapshot:    Full properties of target node BEFORE merge
//   source_snapshots:   List of {id, properties} for each source node BEFORE merge
//   status:             Merge status: 'COMPLETED', 'ROLLED_BACK', 'FAILED'
//   merged_count:       Number of source nodes successfully merged
//   relationships_updated: Count of relationships re-pointed during merge
//   rolled_back_at:     datetime of rollback (if status = 'ROLLED_BACK')
//   merge_reason:       Optional reason for the merge operation

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
// Used for general property change tracking.

// Entity → Version (Risk Score Snapshots)
// (:Company)-[:HAS_VERSION]->(:Version {snapshot_type: 'risk_score'})
// Used specifically for risk score temporal tracking.
// Created by RiskEngine.save_all_risk_snapshots() after each analysis run.
// Enables trend analysis via TemporalAnalyzer.get_risk_trend_analysis().
// Properties on relationship: None (relationship is implicit via Version.entityId)

// Municipality → Municipality (Evolution)
// (:Municipality)-[:EVOLVED_INTO]->(:Municipality)
// Properties: date, reason

// Any Entity → Comment (Annotated with)
// (:Company|:Tender|:Project|:Person|:Asset|:Buyer|:FraudPattern)-[:HAS_COMMENT]->(:Comment)
// Implicit relationship via Comment.entity_id and Comment.entity_type properties
// Comments can also reply to other comments via parent_comment_id

// Comment → Comment (Reply thread)
// (:Comment)-[:REPLY_TO]->(:Comment)
// Implicit relationship via Comment.parent_comment_id property

// MergeRollback → Entity (Audit trail)
// (:MergeRollback)-[:SNAPSHOT_OF]->(:Company|:Tender|:Project|:Person)
// Implicit relationship via MergeRollback.target_id and source_ids properties
// Used for audit trail and rollback operations

// --- Notebook Nodes ---
// Investigation notebooks for analyst workspace (Jupyter-style).
// Properties:
//   id:               UUID
//   title:            String (max 200 chars)
//   description:      String (max 2000 chars)
//   status:           'draft' | 'active' | 'completed' | 'archived'
//   template_name:    String (optional, name of template used)
//   linked_entity_ids: List<String> (entity IDs linked to this investigation)
//   linked_alert_ids:  List<String> (alert IDs linked to this investigation)
//   tags:             List<String> (investigation tags)
//   cell_count:       Integer (number of cells in notebook)
//   author:           String (author identifier, default: 'user')
//   created_at:       DateTime
//   updated_at:       DateTime (null if never updated)
//   completed_at:     DateTime (null if not completed)

// --- NotebookCell Nodes ---
// Individual cells within an investigation notebook.
// Properties:
//   id:               UUID
//   notebook_id:      UUID (parent notebook ID)
//   cell_type:        'markdown' | 'cypher_query' | 'results_table' | 'visualization' | 'code'
//   content:          String (cell content: markdown text or Cypher query)
//   position:         Integer (order in notebook, 0-based)
//   title:            String (optional, max 200 chars)
//   execution_result: Dict (optional, last execution output as JSON)
//   execution_count:  Integer (number of times cell was executed)
//   last_executed_at: DateTime (null if never executed)
//   linked_entity_id: String (optional, entity linked to this specific cell)
//   created_at:       DateTime
//   updated_at:       DateTime (null if never updated)

// --- NotebookChangeHistory Nodes ---
// Audit trail for notebook changes.
// Properties:
//   id:               UUID
//   notebook_id:      UUID (parent notebook ID)
//   change_type:      String ('notebook_created', 'cell_added', 'cell_updated', 'cell_deleted',
//                            'cell_executed', 'metadata_updated', 'notebook_archived', 'cells_reordered')
//   cell_id:          String (optional, cell involved in change)
//   details:          String (JSON dict with change details)
//   changed_at:       DateTime

// ============================================================================
// RELATIONSHIP TYPES (continued)
// ============================================================================

// NotebookCell → Notebook
// (:NotebookCell)-[:BELONGS_TO]->(:Notebook)
// Implicit via NotebookCell.notebook_id property

// NotebookCell → Entity (Linked to specific entity)
// (:NotebookCell)-[:LINKED_TO]->(:Company|:Tender|:Person|:Project|:Asset|:Buyer)
// Implicit via NotebookCell.linked_entity_id property

// Notebook → ChangeHistory
// (:Notebook)-[:HAS_CHANGE_HISTORY]->(:NotebookChangeHistory)
// Implicit via NotebookChangeHistory.notebook_id property

// ============================================================================
// INDEXES
// ============================================================================

// Notebook indexes
// CREATE INDEX notebook_status_idx FOR (n:Notebook) ON (n.status)
// CREATE INDEX notebook_template_name_idx FOR (n:Notebook) ON (n.template_name)
// CREATE INDEX notebook_created_at_idx FOR (n:Notebook) ON (n.created_at)
// CREATE INDEX notebook_updated_at_idx FOR (n:Notebook) ON (n.updated_at)

// NotebookCell indexes
// CREATE INDEX notebookcell_notebook_id_idx FOR (c:NotebookCell) ON (c.notebook_id)
// CREATE INDEX notebookcell_cell_type_idx FOR (c:NotebookCell) ON (c.cell_type)
// CREATE INDEX notebookcell_position_idx FOR (c:NotebookCell) ON (c.position)

// NotebookChangeHistory indexes
// CREATE INDEX notebookchange_notebook_id_idx FOR (h:NotebookChangeHistory) ON (h.notebook_id)
// CREATE INDEX notebookchange_changed_at_idx FOR (h:NotebookChangeHistory) ON (h.changed_at)

// --- Alert Nodes ---
// Proactive fraud detection and monitoring notifications.
// Created automatically by alert generators or manually by analysts.
// Properties:
//   id:               UUID
//   type:             Alert type: 'risk_spike' | 'fraud_pattern' | 'sanction_match' | 'activity_spike' | 'merge_candidate'
//   severity:         Alert severity: 'critical' | 'high' | 'medium' | 'low' | 'info'
//   status:           Alert status: 'pending' | 'acknowledged' | 'resolved' | 'dismissed'
//   title:            Short alert title (max 200 chars)
//   description:      Detailed alert description (max 2000 chars)
//   entity_type:      Type of entity this alert is about: Company, Tender, Buyer, Person
//   entity_id:        ID of the entity this alert is about
//   entity_cf:        Codice Fiscale of the entity (if applicable)
//   rule_id:          ID of the alert rule that triggered this (optional)
//   triggered_by:     What triggered this alert: system, rule, manual
//   metadata:         Additional context data (JSON dict)
//   alert_hash:       Hash for deduplication (prevents spam within 24h window)
//   acknowledged_at:  datetime when alert was acknowledged (null if not)
//   resolved_at:      datetime when alert was resolved (null if not)
//   dismissed_at:     datetime when alert was dismissed (null if not)
//   created_at:       datetime when alert was created
//   provenance:       ProvenanceMetadata object for audit trail

// --- AlertRule Nodes ---
// Custom alert rule definitions for configurable alert generation.
// Properties:
//   id:               UUID
//   name:             Rule name (max 100 chars)
//   description:      Rule description (max 500 chars)
//   alert_type:       Type of alert this rule generates
//   trigger_condition: Trigger condition (Cypher or expression, max 2000 chars)
//   threshold:        Numeric threshold for triggering (optional)
//   severity:         Default severity for alerts from this rule
//   enabled:          Boolean - whether rule is active
//   created_at:       datetime when rule was created
//   updated_at:       datetime when rule was last updated (null if never)

// Entity → Alert (Has Alert relationship)
// (:Company|:Tender|:Buyer|:Person)-[:HAS_ALERT]->(:Alert)
// Created when an alert is generated for an entity
// Properties: None (relationship is implicit via Alert.entity_id and Alert.entity_type)

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

// ============================================================================
// GRAPH VISUALIZATION SYSTEM
// ============================================================================
// The graph visualization system (graph_service.py) provides interactive network
// graph exploration for analysts. It supports:
//   - Entity-centered subgraph queries with configurable depth
//   - Filtered graph queries (by type, risk, date)
//   - Shortest path finding between entities
//   - Layout algorithms (force-directed, radial, hierarchical, circular)
//   - Risk-based coloring and centrality-based sizing
//   - Export to JSON, GraphML, SVG, PNG
//   - Predefined templates for common investigation views
//
// All graph queries are bounded by:
//   - MAX_DEPTH = 5 (prevents runaway traversal)
//   - MAX_NODES = 500 (prevents memory issues)
//   - Query timeouts via Neo4j session configuration
// ============================================================================

// --- Graph Query Patterns ---

// 1. Entity-Centered Subgraph (depth-limited BFS)
// Used by: get_entity_graph()
// Pattern: Start from a center entity, traverse relationships up to N hops
// Cypher pattern:
//   MATCH (center {id: $center_id})
//   MATCH path = (center)-[*1..depth]-(n)
//   WHERE n.id IS NOT NULL
//   RETURN DISTINCT n, relationships(path) AS rels
//
// Performance: Uses id index for center lookup, limits results with LIMIT

// 2. Filtered Graph Query (no center)
// Used by: get_filtered_graph()
// Pattern: Match all nodes matching filter criteria, return connected subgraph
// Cypher pattern:
//   MATCH (n)
//   WHERE n.id IS NOT NULL AND <filter_conditions>
//   WITH n LIMIT $max_nodes
//   MATCH (n)-[r]-(m)
//   WHERE m.id IN [x IN collect(DISTINCT n) | x.id]
//   RETURN n, r, m
//
// Performance: Requires appropriate indexes on filtered properties

// 3. Shortest Path
// Used by: get_path_between()
// Pattern: Find shortest path between two entities
// Cypher pattern:
//   MATCH path = shortestPath(
//     (source {id: $source_id})-[*1..max_depth]-(target {id: $target_id})
//   )
//   RETURN path
//
// Performance: Neo4j's shortestPath is optimized; max_depth limits search space

// 4. 1-Hop Neighbors
// Used by: get_neighbors()
// Pattern: Get all direct connections of an entity
// Cypher pattern:
//   MATCH (center {id: $entity_id})
//   MATCH (center)-[r]-(neighbor)
//   WHERE neighbor.id IS NOT NULL
//   RETURN center, r, neighbor
//
// Performance: Fast single-hop query, uses id index

// 5. Community Subgraph
// Used by: get_community_graph()
// Pattern: Get all nodes and edges within a Louvain community
// Cypher pattern:
//   MATCH (n {community_id: $community_id})
//   WITH n LIMIT $max_nodes
//   MATCH (n)-[r]-(m {community_id: $community_id})
//   RETURN n, r, m
//
// Performance: Requires community_id index on relevant node labels

// --- Recommended Indexes for Graph Traversal ---

// Core indexes (required for performance)
// CREATE INDEX entity_id_idx IF NOT EXISTS FOR (n) ON (n.id)
// CREATE INDEX company_cf_idx IF NOT EXISTS FOR (c:Company) ON (c.cf)
// CREATE INDEX tender_cig_idx IF NOT EXISTS FOR (t:Tender) ON (t.cig)
// CREATE INDEX project_cup_idx IF NOT EXISTS FOR (p:Project) ON (p.cup)

// Risk score index (for risk-based filtering)
// CREATE INDEX company_risk_score_idx IF NOT EXISTS FOR (c:Company) ON (c.risk_score)

// Community index (for community graph queries)
// CREATE INDEX company_community_idx IF NOT EXISTS FOR (c:Company) ON (c.community_id)

// Date indexes (for date range filtering)
// CREATE INDEX company_created_at_idx IF NOT EXISTS FOR (c:Company) ON (c.created_at)
// CREATE INDEX tender_created_at_idx IF NOT EXISTS FOR (t:Tender) ON (t.created_at)

// Full-text index for entity search (optional, improves search performance)
// CREATE FULLTEXT INDEX entity_search_idx IF NOT EXISTS
//   FOR (c:Company|t:Tender|p:Project) ON EACH [c.nome_normalizzato, t.oggetto, p.titolo]

// --- Layout Algorithm Documentation ---

// 1. Force-Directed (default)
//    - Simulates repulsion between all nodes and attraction along edges
//    - Produces organic, clustered layouts
//    - Best for: General exploration, finding communities
//    - Complexity: O(N^2) per iteration, 50 iterations default
//    - Parameters: k (ideal spring length), temperature (cooling)

// 2. Radial
//    - Places center node at origin, neighbors in concentric circles
//    - Best for: Entity-centered views, showing degrees of separation
//    - Complexity: O(N + E) via BFS
//    - Parameters: radius per hop (200px default)

// 3. Hierarchical
//    - Topological sort assigns layers, nodes placed in rows
//    - Best for: Supply chains, organizational structures
//    - Complexity: O(N + E) via Kahn's algorithm
//    - Handles cycles by assigning unplaced nodes to layer 0

// 4. Circular
//    - All nodes placed evenly on a circle
//    - Best for: Small graphs, comparison views
//    - Complexity: O(N)
//    - Parameters: radius (400px default)

// --- Styling Rules ---

// Risk-based coloring:
//   score 0.0 → green (#00ff00)
//   score 0.5 → yellow (#ffff00)
//   score 1.0 → red (#ff0000)
//   No score → type-based default color

// Type-based colors:
//   Company:       #3B82F6 (Blue)
//   Tender:        #10B981 (Green)
//   Project:       #8B5CF6 (Purple)
//   Person:        #F59E0B (Amber)
//   Buyer:         #EF4444 (Red)
//   Asset:         #06B6D4 (Cyan)
//   FraudPattern:  #DC2626 (Dark red)
//   Comment:       #6B7280 (Gray)
//   Alert:         #F97316 (Orange)

// Centrality-based sizing:
//   size = 10 + centrality * 80
//   Range: 10px (isolated) to 90px (fully connected)
//   Centrality = degree / max_degree in subgraph

// --- Performance Guidelines ---

// 1. Always specify depth (1-5, default 2)
//    - Depth 1: Direct connections only (fastest)
//    - Depth 2: Friends of friends (recommended for exploration)
//    - Depth 3+: Use with caution, can explode combinatorially

// 2. Always specify max_nodes (10-500, default 500)
//    - Prevents memory issues with large subgraphs
//    - Results are truncated at this limit
//    - Response includes 'truncated' flag if limit was hit

// 3. Use filters to reduce result set
//    - Filter by node_types to exclude irrelevant entities
//    - Filter by edge_types to focus on specific relationships
//    - Filter by min_risk_score to focus on high-risk entities

// 4. Use templates for common views
//    - Templates pre-configure depth, types, and filters
//    - "Company Network": depth=2, company+tender+buyer+person
//    - "Fraud Pattern View": depth=2, company+fraud_pattern+person
//    - "Full Overview": depth=1, all types, max 100 nodes

// 5. Export considerations
//    - JSON: Fast, includes all properties, best for programmatic use
//    - GraphML: Compatible with Gephi, Cytoscape, yEd
//    - SVG/PNG: Requires matplotlib + networkx, best for reports
//    - Image export uses spring_layout (networkx), not backend layout

// --- Predefined Graph Templates ---

// 1. Company Network
//    - Center: Company entity
//    - Depth: 2
//    - Node types: company, tender, buyer, person
//    - Edge types: wins, issues, represents
//    - Use case: Investigate a company's procurement ecosystem

// 2. Fraud Pattern View
//    - Center: Any entity (or none for global view)
//    - Depth: 2
//    - Node types: company, fraud_pattern, person
//    - Edge types: flagged_by, represents
//    - Use case: Analyze fraud pattern connections

// 3. Supply Chain
//    - Center: Company entity
//    - Depth: 3
//    - Node types: company, tender
//    - Edge types: wins, related_to
//    - Use case: Trace upstream/downstream relationships

// 4. Risk Hotspot
//    - Center: None (global view)
//    - Depth: 2
//    - Node types: company, person, buyer
//    - Edge types: wins, issues, represents, owns, flagged_by
//    - Use case: Identify high-risk entity clusters

// 5. Project Ecosystem
//    - Center: Project entity
//    - Depth: 2
//    - Node types: project, tender, company
//    - Edge types: part_of, wins
//    - Use case: Explore project funding and execution chain

// 6. Full Overview
//    - Center: None (sampled global view)
//    - Depth: 1
//    - Node types: all (company, tender, project, person, buyer, asset)
//    - Edge types: all (wins, issues, part_of, represents, owns, related_to)
//    - Max nodes: 100
//    - Use case: High-level graph overview
