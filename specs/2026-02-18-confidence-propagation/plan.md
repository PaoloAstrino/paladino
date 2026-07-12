# Development Plan: Tier 3 - Confidence Propagation

## 1. Schema & Node Preparation
- [ ] Add `derived_confidence` field to `NodeBase` in `paladino/models.py`.
- [ ] Update `paladino/schema_manager.py` to index `derived_confidence`.
- [ ] Ensure all relationship models (WINS, PART_OF_PROJECT, etc.) have a `confidence` field.

## 2. Propagation Engine (GDS/Cypher)
- [ ] Create `paladino/analytics/confidence_engine.py`.
- [ ] Implement `Propagator.initialize_derived_scores()`: Sets `derived_confidence = confidence` as a baseline.
- [ ] Implement `Propagator.run_propagation_sweep()`: A multi-pass Cypher job that updates scores based on the "Weakest Link" logic.
- [ ] Add `run_confidence_propagation` to `GDSManager` (if using GDS for complex flows).

## 3. Integration & UI
- [ ] Update `GraphRAGAgent` to include confidence scores in its generated insights.
- [ ] Add a `confidence-sweep` command to `paladino/cli.py`.
- [ ] Add a `GET /analytics/confidence-stats` endpoint to `paladino/app/api.py` to see the distribution of trust across the graph.

## 4. Validation
- [ ] Create a test scenario with a chain of nodes (A -> B -> C) with decreasing confidence and verify propagation.
- [ ] Verify that high-confidence registry data is never "downgraded" by low-confidence noise (unless they are logically linked).
