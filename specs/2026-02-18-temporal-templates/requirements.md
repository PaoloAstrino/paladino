# Requirements: Tier 3 - Temporal Template Integration

## Overview
This feature updates the built-in Cypher templates in `GraphRAGAgent` to be "Time-Aware." It allows analysts to use standard investigative reports (e.g., "Top Vendors") but filtered for a specific historical date.

## Problem
Currently, templates in `CypherQueryTemplates.TEMPLATES` only return current data. Even if a user asks "Who were the top vendors in 2024?", the template ignores the date and returns the 2026 state.

## Goals
- Explicitly update all core templates to include `$as_of` filters.
- Ensure that `$as_of` has a default value (current time) so existing calls don't break.
- Maintain the "Weakest Link" logic within templates where multiple nodes are matched.

## Non-goals
- Auto-detecting dates in natural language for templates (Intent Classifier already does this for params).
- Rewriting templates dynamically (User requested Manual/Static approach for better control).

## User Stories
- **As an auditor,** I want to run the "Regional Concentration" report as of 2024-01-01 to compare it with the 2025-01-01 report.
- **As a developer,** I want to call `agent.query("top_vendors", {"as_of": "2024-06-01"})` and get historical results.

## Technical Considerations
- All `MATCH` clauses must be followed by `WHERE` checks on `valid_from` and `valid_to`.
- Default value for `$as_of` must be injected if not provided.
- Performance: Ensure that temporal indices created in Phase 17.1 are utilized.
