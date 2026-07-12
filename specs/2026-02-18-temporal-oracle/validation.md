# Validation: Tier 3 - The Temporal Oracle

## Acceptance Criteria
- [ ] The system correctly identifies the date of the previous snapshot without user input.
- [ ] New `TemporalAlert` nodes are created only for significant changes (Risk delta > 0.3 or Community ID change).
- [ ] Alerts are linked via `HAS_TEMPORAL_ALERT` to the correct entity.
- [ ] Each alert node contains metadata: `type`, `old_value`, `new_value`, `delta`, and `comparison_dates`.
- [ ] The script handles the case where only one snapshot exists (graceful exit).

## How to Test Manually
1. **Load Baseline:** Load 10 companies with `valid_from` = 2024-01-01 and `risk_score` = 0.2.
2. **Load Update:** Load same 10 companies with `valid_from` = 2025-01-01 and `risk_score` = 0.6.
3. **Run Oracle:** Execute `python scripts/run_oracle.py --temporal`.
4. **Verify Graph:** Query `MATCH (a:TemporalAlert) RETURN a`. You should see 10 alerts for "risk_spike".
5. **Community Test:** Update `community_id` for 2 companies. Run Oracle again. Verify "community_migration" alerts.

## Definition of Done
- [ ] Oracle logic implemented and verified.
- [ ] `TemporalAlert` model integrated into `models.py`.
- [ ] Persistent nodes verified in Neo4j.
- [ ] CLI command functional.
