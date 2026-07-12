# Development Plan: Tier 3 - The Temporal Oracle

## 1. Core Logic
- [ ] Create `paladino/analytics/temporal_oracle.py`.
- [ ] Implement `Oracle.find_snapshot_boundaries()`: Returns `(date_last, date_current)`.
- [ ] Implement `Oracle.detect_risk_spikes()`: Cypher query to find delta in `risk_score` > 0.3.
- [ ] Implement `Oracle.detect_community_migration()`: Cypher query to find changes in `community_id`.

## 2. Persistence Layer
- [ ] Define `TemporalAlert` model in `paladino/models.py`.
- [ ] Implement `Oracle.persist_alerts()`: Creates `TemporalAlert` nodes and `HAS_TEMPORAL_ALERT` relationships.
- [ ] Add `TEMPORAL_ALERT` relationship type to `GraphEdgeType` enum.

## 3. CLI & Integration
- [ ] Add `oracle-temporal` command to `paladino/cli.py`.
- [ ] Update `scripts/run_oracle.py` to optionally include the temporal scan.
- [ ] Update `Investigator` (REPL) to show recent temporal alerts in the `stats` command.

## 4. Validation
- [ ] Test scenario: Manually create two versions of a Company node with different `risk_score` and `valid_from`. Run Oracle and verify alert creation.
- [ ] Test scenario: Change `community_id` for a group of companies and verify migration detection.
