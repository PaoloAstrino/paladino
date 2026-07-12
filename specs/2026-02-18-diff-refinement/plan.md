# Development Plan: Tier 3 - Diff API Refinement

## 1. Analytics Layer Update
- [ ] Refactor `TemporalAnalyzer.get_diff` in `paladino/analytics/temporal_analytics.py`.
- [ ] Add `_get_structural_state(entity_id, date)`: Returns a map of relationship signatures and their properties.
- [ ] Implement membership comparison logic (Set symmetric difference for added/removed links).
- [ ] Implement relationship property diffing for links that exist in both snapshots.

## 2. Model & API Update
- [ ] Update `DiffDelta` in `paladino/models.py` to include `added_links`, `removed_links`, and `changed_links`.
- [ ] Ensure `PropertyChange` model is reused for relationship properties.
- [ ] Update the `POST /diff` endpoint in `paladino/app/api.py` to return the enriched structural data.

## 3. REPL Integration
- [ ] Add a `.diff <id> --from <date> --to <date>` command to the `Investigator` shell.
- [ ] Format the structural diff output using a dedicated Rich table.

## 4. Validation
- [ ] Test scenario: Company A wins Tender X (Date A), then loses Tender X and wins Tender Y (Date B).
- [ ] Test scenario: Person P has 20% quota (Date A) and 40% quota (Date B).
- [ ] Verify performance for entities with > 100 relationships.
