# Requirements: Tier 3 - Confidence Propagation

## Overview
This feature implements a recursive "Trust Model" across the knowledge graph. It ensures that data derived from multiple sources (e.g., a "Merged Company" or a "Risk Alert") accurately reflects the reliability of its constituent parts.

## Problem
Currently, nodes have a `confidence` score, but these scores are static. If we merge two companies where one has 1.0 confidence (Official Registry) and the other 0.75 (Fuzzy Match), the resulting merged entity needs a mathematically sound way to represent its combined trust.

## Goals
- Implement a batch propagation engine to calculate "Derived Confidence" for complex entities and relationships.
- Use the "Weakest Link" (Minimum) principle: an insight is only as strong as its weakest supporting evidence.
- Store pre-computed `derived_confidence` on nodes to ensure fast querying.

## Non-goals
- Bayesian probability networks (too complex for MVP).
- Real-time propagation on every write (too expensive for large graphs).

## User Stories
- **As an investigator,** I want to see a "Trust Score" on every fraud alert so I can prioritize alerts based on official data over fuzzy matches.
- **As a data engineer,** I want to run a weekly "Trust Sweep" that updates the confidence of all entities based on new evidence.

## Technical Considerations
- GDS (Graph Data Science) can be used to propagate scores across the topology.
- Relationships must also carry confidence (e.g., a `PART_OF_PROJECT` link found via temporal matching might only have 0.8 confidence).
- Formula: `Node.derived_confidence = min(Node.source_confidence, min(Neighbor.derived_confidence * Relationship.confidence))`.
