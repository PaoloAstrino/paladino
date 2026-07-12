# Requirements: Tier 3 - Diff API Refinement

## Overview
This feature upgrades the `get_diff` engine from a simple property-comparer to a "Structural Detective." It identifies changes not just in what an entity *is*, but in how it is *connected* to the rest of the procurement network.

## Problem
The current Diff API is "blind" to network changes. If a company changes its CEO or signs a new contract between 2024 and 2025, the current API returns "no changes" because the Company node properties might be identical, even though its relationships have shifted.

## Goals
- Detect **Membership Changes**: New or removed relationships (e.g., a new `SHAREHOLDER_OF` or `WINS` link).
- Detect **Relationship Property Changes**: Changes in metadata on the links themselves (e.g., an owner increasing their quota from 20% to 51%).
- Provide a unified "Network Delta" JSON response.

## Non-goals
- Deep recursive diffs (N-hops) due to computational cost on a personal laptop.
- Visual diff rendering (this is an API-level refinement; UI comes later).

## User Stories
- **As a forensic analyst,** I want to see a list of new shareholders that joined a company in the last 6 months.
- **As a risk manager,** I want to know if a company's relationship to a specific high-risk "Buyer" was added recently.

## Technical Considerations
- Must execute two topological queries: `MATCH (n {id: $id})-[r]-(m)` as of Date A and Date B.
- Use a "Membership Signature" (Relationship Type + Target ID) to track additions/removals.
- Performance: 1-hop structural checks are fast but requires careful indexing on `valid_from/to` for relationships.
