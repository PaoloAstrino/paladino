# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records (ADRs) for the Paladino project.

## What is an ADR?

An ADR is a document that captures an important architectural decision made along with its context and consequences. ADRs help us:

- Document why decisions were made
- Track the evolution of the architecture
- Onboard new team members
- Avoid revisiting settled decisions without good reason

## ADR Format

Each ADR follows a standard template located at `docs/ADRs/TEMPLATE.md`:

1. **Title**: Short descriptive name
2. **Status**: Proposed, Accepted, Deprecated, or Superseded
3. **Context**: The problem or opportunity being addressed
4. **Decision**: The change being proposed
5. **Consequences**: What becomes easier or more difficult
6. **Implementation**: Action items if applicable
7. **References**: Links to related resources

## ADR Index

| Number | Title | Status | Date |
|--------|-------|--------|------|
| 0001 | Template | Accepted | 2026-03-23 |

## Process for Creating ADRs

1. Copy `TEMPLATE.md` to `ADR-NNN.md` (next sequential number)
2. Fill in all sections
3. Submit as a PR for review
4. Once accepted, update the status and add to this index

## When to Create an ADR

Create an ADR when:

- Making a significant architectural change
- Choosing between multiple viable approaches
- Establishing a new pattern or convention
- Deprecating or replacing an existing approach

## References

- [Michael Nygard's ADR template](https://github.com/joelparkerhenderson/architecture-decision-record)
- [ThoughtWorks ADR guidance](https://www.thoughtworks.com/radar/techniques/architecture-decision-records)
