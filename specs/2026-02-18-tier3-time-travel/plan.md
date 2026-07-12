# Development Plan: Tier 3 - Time-Travel & Historical Analytics

## 1. Schema & Data Model
- [ ] Update `paladino/models.py` to include `valid_from` and `valid_to` in `NodeBase`.
- [ ] Update `paladino/schema_manager.py` to create indices on `valid_from` and `valid_to`.
- [ ] Create a migration script `scripts/migrate_to_temporal.py` to initialize existing data with `valid_from=retrievalDate`.

## 2. Cypher Temporal Rewriting
- [ ] Create `paladino/app/temporal_rewriter.py` to inject temporal filters into Cypher queries.
- [ ] Update `GraphRAGAgent` to support an optional `as_of` parameter in `natural_language_query`.
- [ ] Implement `TemporalAnalyzer.get_entity_state_at(entity_id, target_date)` logic.

## 3. Diff API & Services
- [ ] Implement `TemporalAnalyzer.get_diff(entity_id, date_a, date_b)` to return a structured delta.
- [ ] Add `GET /diff/{entity_id}` and `POST /query/as-of` endpoints to `paladino/app/api.py`.
- [ ] Update `REPL` (Investigator) to support `as-of` queries via a new flag (e.g., `query --as-of 2024-01-01 "Show ACME owners"`).

## 4. Documentation & Examples
- [ ] Add examples to `docs/guides/temporal_queries.md`.
- [ ] Update API docs (OpenAPI/Swagger) with the new temporal parameters.
