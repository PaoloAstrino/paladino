# Development Plan: Tier 3 - Temporal Template Integration

## 1. Template Refactoring
- [ ] Update `paladino/app/graphrag_agent.py`: `CypherQueryTemplates.TEMPLATES`.
- [ ] Refactor `companies_by_region` to include `$as_of` filters.
- [ ] Refactor `top_vendors_by_value` to include `$as_of` filters.
- [ ] Refactor `risk_summary_by_sector` to include `$as_of` filters.
- [ ] Refactor `single_bidder_monopolies` to include `$as_of` filters.

## 2. Agent Integration
- [ ] Update `GraphRAGAgent.query()` method to automatically inject the current timestamp as `$as_of` if the parameter is missing.
- [ ] Ensure `execute_custom_cypher` does NOT double-apply filters if a template already has them (templates will be marked or handled carefully).

## 3. UI/UX
- [ ] Update `Investigator` (REPL) to pass `@as-of` context to template calls (e.g., `@top_vendors --as-of 2024-01-01`).

## 4. Validation
- [ ] Create a unit test for each updated template.
- [ ] Verify that current-date queries return the same results as before the update.
