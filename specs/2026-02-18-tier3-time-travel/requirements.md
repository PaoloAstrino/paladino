# Requirements: Tier 3 - Time-Travel & Historical Analytics

## Overview
This feature introduces a temporal dimension to the Paladino knowledge graph. It allows users to query the state of the procurement network as it existed at any point in time and compare changes between two snapshots.

## Problem
Currently, the graph is a "snapshot" of the most recent data. Analysts cannot easily see how a company's risk score evolved, how tender amounts were revised, or which entities entered/left a cartel over time.

## Goals
- Implement a `valid_from` / `valid_to` pattern for selective high-value properties (amounts, risk, ownership).
- Provide an `AS OF` query mechanism to simplify temporal lookups.
- Create a `Diff API` to generate structured comparisons between two dates.

## Non-goals
- Full history of every single property (too much overhead).
- Real-time time-travel (we focus on batch/versioned snapshots).
- Automatic database-level temporal tables (we implement logic in Cypher/Application layer).

## User Stories
- **As an analyst,** I want to ask "What was the ownership structure of ACME SRL in June 2024?" to see if a politically exposed person was present.
- **As a fraud detector,** I want to see how a company's risk score changed over the last 12 months.
- **As a manager,** I want a diff report showing all changes to a specific tender's financial data.

## Technical Considerations
- Use `valid_from` (DateTime) and `valid_to` (DateTime, default NULL for current) on nodes/relationships.
- Indexing on temporal fields is mandatory for performance.
- Cypher query rewriter needed to inject `WHERE n.valid_from <= $target_date AND (n.valid_to > $target_date OR n.valid_to IS NULL)`.

## Open Questions
- How do we handle "soft deletes"? (Likely by setting `valid_to` to the current date).
- Should we use Neo4j 5.x native temporal types? (Yes, for consistency).
