"""
migrate_date_types.py
=====================
One-shot idempotent migration that converts ISO-8601 string dates stored on
``Tender`` and ``WINS`` relationship properties into native Neo4j ``date``
types.

Background
----------
Original ANAC loader wrote dates as plain strings (e.g. "2024-03-15" or
"2024-03-15T00:00:00Z").  Native ``date`` types are required for temporal
queries, quarterly bucketing via ``.month``, and arithmetic like
``date() - duration(...)``.

The migration is safe to run multiple times.  The idempotency guard
``apoc.meta.cypher.type(x) <> 'DATE'`` (or the simpler string-contains check
used below when APOC is unavailable) ensures already-migrated values are
skipped.

Usage
-----
    python scripts/migrate_date_types.py           # live run with progress
    python scripts/migrate_date_types.py --dry-run # count only, no writes
    python scripts/migrate_date_types.py --batch-size 500

Exit codes
----------
    0  success (or dry-run)
    1  fatal error
"""

from __future__ import annotations

import argparse
import sys
from typing import Tuple

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table

# ──────────────────────────────────────────────────────────────────────
# Bootstrap — ensure project root is on sys.path when run directly
# ──────────────────────────────────────────────────────────────────────
try:
    from paladino.db import Neo4jConnection
    from paladino.config import get_settings
except ImportError:
    import pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from paladino.db import Neo4jConnection
    from paladino.config import get_settings

_console = Console()

# ──────────────────────────────────────────────────────────────────────
# Idempotency helper — a value still needs migration if it is either:
#   a) a string that contains 'T' (datetime ISO format), OR
#   b) a string at all (Cypher: toString(x) = x means it's a string)
#
# We use a simple STARTS WITH '20' AND (... CONTAINS 'T') pattern that
# works without APOC and handles "2024-03-15T00:00:00Z" and the less-
# common "2024-03-15" string form.
# ──────────────────────────────────────────────────────────────────────

_MIGRATION_STEPS: list[dict] = [
    {
        "name": "Tender.data_aggiudicazione",
        "count_query": """
            MATCH (t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND toString(t.data_aggiudicazione) = t.data_aggiudicazione
            RETURN count(t) AS n
        """,
        "migrate_query": """
            MATCH (t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND toString(t.data_aggiudicazione) = t.data_aggiudicazione
            WITH t LIMIT $batch_size
            SET t.data_aggiudicazione = date(substring(t.data_aggiudicazione, 0, 10))
            RETURN count(t) AS updated
        """,
    },
    {
        "name": "Tender.data_apertura",
        "count_query": """
            MATCH (t:Tender)
            WHERE t.data_apertura IS NOT NULL
              AND toString(t.data_apertura) = t.data_apertura
            RETURN count(t) AS n
        """,
        "migrate_query": """
            MATCH (t:Tender)
            WHERE t.data_apertura IS NOT NULL
              AND toString(t.data_apertura) = t.data_apertura
            WITH t LIMIT $batch_size
            SET t.data_apertura = date(substring(t.data_apertura, 0, 10))
            RETURN count(t) AS updated
        """,
    },
    {
        "name": "WINS.data",
        "count_query": """
            MATCH ()-[w:WINS]->()
            WHERE w.data IS NOT NULL
              AND toString(w.data) = w.data
            RETURN count(w) AS n
        """,
        "migrate_query": """
            MATCH ()-[w:WINS]->()
            WHERE w.data IS NOT NULL
              AND toString(w.data) = w.data
            WITH w LIMIT $batch_size
            SET w.data = date(substring(w.data, 0, 10))
            RETURN count(w) AS updated
        """,
    },
]


def _count_pending(conn: Neo4jConnection, step: dict) -> int:
    rows = conn.run_query(step["count_query"], {})
    return rows[0]["n"] if rows else 0


def _run_batch(conn: Neo4jConnection, step: dict, batch_size: int) -> int:
    """Execute one batch migration; return number of nodes/rels updated."""
    rows = conn.run_query(step["migrate_query"], {"batch_size": batch_size})
    return rows[0]["updated"] if rows else 0


def _migrate_step(
    conn: Neo4jConnection,
    step: dict,
    batch_size: int,
    dry_run: bool,
) -> Tuple[int, int]:
    """
    Migrate all pending nodes for one field in batches.

    Returns (total_pending, total_migrated).
    """
    total_pending = _count_pending(conn, step)
    if total_pending == 0:
        return 0, 0

    if dry_run:
        return total_pending, 0

    total_migrated = 0
    with Progress(
        SpinnerColumn(),
        TextColumn(f"  Migrating [bold]{step['name']}[/bold]"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=_console,
        transient=True,
    ) as progress:
        task = progress.add_task("migrating", total=total_pending)

        while True:
            updated = _run_batch(conn, step, batch_size)
            if updated == 0:
                break
            total_migrated += updated
            progress.update(task, advance=updated)

    return total_pending, total_migrated


def run_migration(
    conn: Neo4jConnection,
    batch_size: int = 1000,
    dry_run: bool = False,
) -> bool:
    """
    Execute all three migration steps.

    Returns ``True`` on success.
    """
    _console.rule("[bold cyan]Paladino — Date Type Migration[/bold cyan]")

    if dry_run:
        _console.print(
            Panel(
                "[yellow]DRY-RUN mode — no writes will be performed.[/yellow]\n"
                "Run without [bold]--dry-run[/bold] to apply changes.",
                border_style="yellow",
            )
        )

    summary_table = Table(title="Migration Summary", show_header=True, header_style="bold magenta")
    summary_table.add_column("Field", style="cyan")
    summary_table.add_column("Pending", justify="right")
    summary_table.add_column("Migrated", justify="right")
    summary_table.add_column("Status", justify="center")

    all_ok = True

    for step in _MIGRATION_STEPS:
        _console.print(f"\n[bold]Checking:[/bold] {step['name']} …")
        try:
            pending, migrated = _migrate_step(conn, step, batch_size, dry_run)
        except Exception as exc:
            logger.error(f"Migration error for {step['name']}: {exc}")
            _console.print(f"  [red]ERROR: {exc}[/red]")
            summary_table.add_row(step["name"], "?", "0", "[red]ERROR[/red]")
            all_ok = False
            continue

        if pending == 0:
            status = "[green]✓ up-to-date[/green]"
            _console.print(f"  [green]Already up-to-date (0 strings found)[/green]")
        elif dry_run:
            status = f"[yellow]{pending} pending[/yellow]"
            _console.print(f"  [yellow]{pending} records need migration[/yellow]")
        else:
            status = f"[green]✓ {migrated}/{pending}[/green]"
            _console.print(f"  [green]Migrated {migrated} / {pending} records[/green]")

        summary_table.add_row(
            step["name"],
            str(pending),
            "—" if dry_run else str(migrated),
            status,
        )

    _console.print()
    _console.print(summary_table)

    if all_ok and not dry_run:
        _console.print(
            Panel(
                "[green]Migration complete![/green]\n\n"
                "Temporal analytics and fraud window queries are now active.\n"
                "Re-run [bold]python scripts/run_temporal_analysis.py[/bold] to see trends.",
                title="[green]Success[/green]",
                border_style="green",
            )
        )
    return all_ok


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate ISO-string dates to native Neo4j date types."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count pending records without writing anything.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        metavar="N",
        help="Nodes to migrate per transaction (default: 1000).",
    )
    args = parser.parse_args()

    settings = get_settings()
    conn = Neo4jConnection(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )

    try:
        ok = run_migration(conn, batch_size=args.batch_size, dry_run=args.dry_run)
    finally:
        conn.close()

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
