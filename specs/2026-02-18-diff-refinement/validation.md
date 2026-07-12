# Validation: Tier 3 - Diff API Refinement

## Acceptance Criteria
- [ ] Diff response includes an `added_links` list with relationship type and target ID.
- [ ] Diff response includes a `removed_links` list.
- [ ] Relationship property changes (e.g., `quota`) are correctly identified in `changed_links`.
- [ ] The engine correctly ignores internal temporal metadata (`valid_from/to`) in the relationship diff.
- [ ] 1-hop structural diff completes in < 2 seconds for highly connected entities.

## How to Test Manually
1. **Initial State (Date A):** Create Company A and Tender T1. Link them via `WINS`.
2. **Shift State (Date B):** Delete the `WINS` link. Create Tender T2. Link Company A to T2 via `WINS`.
3. **Run Diff:** Call `/diff` for Company A between Date A and Date B.
4. **Expectation:** 
   - `removed_links` should contain the `WINS` link to T1.
   - `added_links` should contain the `WINS` link to T2.
5. **Quota Test:** Link Person P to Company A with `quota: 0.2`. Change it to `0.5`. Run diff.
   - `changed_links` should show `quota: {"old": 0.2, "new": 0.5}`.

## Definition of Done
- [ ] Analytics logic refined and verified.
- [ ] Pydantic models updated.
- [ ] API endpoint functional.
- [ ] REPL command `.diff` implemented.
