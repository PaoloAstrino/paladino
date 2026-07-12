# Validation: Tier 3 - Temporal Template Integration

## Acceptance Criteria
- [ ] Every template in `CypherQueryTemplates` contains `$as_of` parameters for all node matches.
- [ ] Calling a template without an `as_of` parameter in the `params` dict defaults to the current UTC time.
- [ ] Historical queries return only nodes that were valid at that time.
- [ ] No syntax errors in updated Cypher strings.

## How to Test Manually
1. **Current State:** Run `@top_vendors` in the REPL. Note results.
2. **Historical State:** Run `@top_vendors --as-of 2020-01-01`. It should return zero results (assuming data starts later).
3. **Partial History:** Update a company's risk score today. Run `@high_risk --as-of <yesterday>`. The company should appear with its *old* risk score (or not at all if it wasn't high risk then).

## Definition of Done
- [ ] All core templates refactored.
- [ ] `GraphRAGAgent.query` updated for default injection.
- [ ] REPL supports `--as-of` for template commands.
- [ ] Tests passing.
