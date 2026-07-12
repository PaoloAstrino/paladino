# Requirements: Tier 3 - The Temporal Oracle

## Overview
The Temporal Oracle is a proactive analysis engine that scans the graph for "Network Drift." It identifies entities that have undergone suspicious topological or risk-based transformations between the current state and the previous data snapshot.

## Problem
Analysts currently have to manually compare dates or use the Diff API on specific nodes. There is no system-wide view of *who* changed most significantly. We need a way to answer: "Which companies suddenly became risky since our last load?"

## Goals
- **Automatic Comparison:** Automatically identify the "Last Snapshot" date and compare it with the "Current" state.
- **Risk Spike Detection:** Flag any entity whose `risk_score` increased by more than a configurable threshold (default 0.3).
- **Community Migration:** Flag entities that moved from one Louvain community to another, which may indicate a merger or a shift in cartel membership.
- **Persistent Evidence:** Create `TemporalAlert` nodes in Neo4j for each discovery, linked to the affected entities.

## Non-goals
- Tracking every single minor property change (use Diff API for that).
- Real-time alerting (this is a post-ETL batch process).

## User Stories
- **As an investigator,** I want to log in and see a list of "High Priority Temporal Alerts" showing companies that recently spiked in risk.
- **As a data scientist,** I want to query the graph for `(:Company)-[:HAS_TEMPORAL_ALERT]->(:TemporalAlert)` to find historical hotspots of network change.

## Technical Considerations
- Must determine "Last Date" by querying the max `valid_to` that is NOT null, or the previous unique `valid_from`.
- Uses complex Cypher to find nodes that exist in both snapshots but with different properties.
- Performance: Must handle large graphs by using indexed lookups on `valid_from` and `risk_score`.
