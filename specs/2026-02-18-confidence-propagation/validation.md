# Validation: Tier 3 - Confidence Propagation

## Acceptance Criteria
- [ ] Every node in the graph has a `derived_confidence` score between 0.0 and 1.0.
- [ ] Merged entities correctly reflect the minimum confidence of their source components.
- [ ] The propagation algorithm terminates within a reasonable time (e.g., < 5 minutes for 1M nodes).
- [ ] Users can query for "Only High Confidence" data using a simple Cypher filter on the pre-computed field.

## How to Test Manually
1. **Setup Test Data:**
   - Create Company A (Confidence 1.0).
   - Create Company B (Confidence 0.7).
   - Link them via a `SAME_AS` relationship (Confidence 0.9).
2. **Run Sweep:** Execute `python scripts/run_confidence_sweep.py`.
3. **Verify:** Check the `derived_confidence` of both companies. It should now be `min(1.0, 0.7, 0.9) = 0.7`.
4. **Complex Chain:** Test a 3-hop chain (Tender -> Project -> FundingSource) and verify the score at the end of the chain.

## Definition of Done
- [ ] All acceptance criteria met.
- [ ] `confidence_engine.py` implemented and unit tested.
- [ ] CLI command `confidence-sweep` functional.
- [ ] Documentation updated to explain the Trust Model.
