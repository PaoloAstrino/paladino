# Design

## Theme
**Void Dark** (Linear-inspired interface). Optimized for local, dark-mode analytical workstations.

## Colors
Using custom hex values defined in `@theme` inside [index.css](file:///D:/Desktop/paladino/frontend/src/index.css):

*   `--color-canvas`: `#010102` (deep void black body background)
*   `--color-surface-1`: `#0f1011` (dark primary card/panel container)
*   `--color-surface-2`: `#141516` (sidebar background, inactive tabs)
*   `--color-surface-3`: `#18191a` (hover states, headers)
*   `--color-hairline`: `#23252a` (default thin 1px panel borders)
*   `--color-primary`: `#5e6ad2` (lavender-blue accent for active states/brand elements)
*   `--color-primary-hover`: `#828fff` (hover accent)
*   `--color-ink`: `#f7f8f8` (high-contrast primary white text)
*   `--color-ink-muted`: `#d0d6e0` (secondary light gray text)
*   `--color-ink-subtle`: `#8a8f98` (tertiary muted gray text)

## Typography
*   **Sans-serif (UI/Labels):** `Inter` / system-ui (letter-spacing: normal, text-wrap: balance on headers).
*   **Monospace (Data/Queries):** `JetBrains Mono` (used for CIG, CF, IBAN codes, Cypher blocks, and tabular outputs).
*   **Numbers:** Styled with `.tabular-nums` in tables to align decimal figures and identifiers perfectly.

## Key UI Components
*   **Sidebar Navigation:** Highly structured left sidebar with collapsing state, displaying local database stats at the bottom.
*   **Data Validation Grid:** Color-coded CSV upload validation table (errors marked in transparent red `bg-red-950/10` with high-contrast `text-red-400`).
*   **Visual Network Explorer:** Force-directed network diagram canvas (`ForceGraph2D`) with node color-coding:
    *   `Company`: Red (`#ef4444`) or Emerald (`#10b981`) depending on risk score.
    *   `Tender`: Lavender-blue (`#5e6ad2`).
    *   `Person`: Amber (`#f59e0b`).
*   **Investigative Notebooks:** Minimalist split cell layout with syntax textareas and sortable monospace query output grids.
