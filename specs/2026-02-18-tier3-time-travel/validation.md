# Validation: Tier 3 - Time-Travel & Historical Analytics

## Acceptance Criteria
- [ ] Any node created after this update has `valid_from` populated automatically.
- [ ] Users can query the graph as of a specific date and get results that exclude future nodes or expired nodes.
- [ ] The `/diff` API correctly identifies added, removed, or changed properties for a given entity between two dates.
- [ ] Performance penalty for `AS OF` queries is < 20% compared to standard queries on same-sized datasets.

## How to Test Manually
1. **Load Baseline:** Load a set of tenders with `valid_from` = 2024-01-01.
2. **Update Data:** Load an update for one tender with a different amount and `valid_from` = 2025-01-01. The old record should now have `valid_to` = 2025-01-01.
3. **Point-in-Time Query:** Query with `as-of 2024-06-01` and verify the old amount is returned.
4. **Current Query:** Query without `as-of` (default current) and verify the new amount is returned.
5. **Diff Test:** Call `/diff` between 2024 and 2025 and verify the amount change is explicitly listed.

## Definition of Done
- [ ] All acceptance criteria met.
- [ ] Unit tests for `TemporalRewriter` passing.
- [ ] Integration tests for `/diff` and `AS OF` API endpoints passing.
- [ ] Migration script verified on sample data.
- [ ] Documentation updated.
