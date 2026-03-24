"""
run_temporal_analysis.py
========================
CLI orchestrator for Paladino's temporal / time-series analytics.

Steps
-----
    all        Run every step below
    migrate    Migrate string dates to native Neo4j date types (idempotent)
    trends     Tender volume + single-bidder ratio trend for a company or graph
    spikes     Detect sudden-spike companies across the whole graph
    seasonal   Month-by-month seasonal procurement pattern
    sector     Sector spending volatility for one ATECO prefix
    history    Risk-score snapshot history for a company

Usage examples
--------------
    python scripts/run_temporal_analysis.py
    python scripts/run_temporal_analysis.py --step all
    python scripts/run_temporal_analysis.py --step spikes --threshold 3.0
    python scripts/run_temporal_analysis.py --step trends --company CF123
    python scripts/run_temporal_analysis.py --step sector --sector C28
    python scripts/run_temporal_analysis.py --step history --company CF123
    python scripts/run_temporal_analysis.py --step migrate --dry-run
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ──────────────────────────────────────────────────────────────────────
# Bootstrap
# ──────────────────────────────────────────────────────────────────────
try:
    from paladino.analytics.temporal_analytics import TemporalAnalyzer
    from paladino.config import get_settings
    from paladino.db import Neo4jConnection
    from scripts.analysis.migrate_date_types import run_migration
except ImportError:
    import pathlib

    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
    from paladino.analytics.temporal_analytics import TemporalAnalyzer
    from paladino.config import get_settings
    from paladino.db import Neo4jConnection
    from scripts.analysis.migrate_date_types import run_migration

_console = Console()

VALID_STEPS = ("all", "migrate", "trends", "spikes", "seasonal", "sector", "history")


# ──────────────────────────────────────────────────────────────────────
# Display helpers
# ──────────────────────────────────────────────────────────────────────


def _fmt_value(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1_000_000:
        return f"€{v / 1_000_000:.1f}M"
    if v >= 1_000:
        return f"€{v / 1_000:.1f}K"
    return f"€{v:.0f}"


def _print_trends(rows: list[dict], company_id: str | None) -> None:
    title = f"Tender Volume Trend — {company_id}" if company_id else "Tender Volume Trend (Graph)"
    t = Table(title=title, show_header=True, header_style="bold cyan")
    if not company_id:
        t.add_column("Year")
        t.add_column("Q")
        t.add_column("Tenders", justify="right")
        t.add_column("Total Value", justify="right")
        t.add_column("Avg Value", justify="right")
        for r in rows:
            t.add_row(
                str(r.get("year", "?")),
                str(r.get("quarter", "?")),
                str(r.get("tender_count", "?")),
                _fmt_value(r.get("total_value")),
                _fmt_value(r.get("avg_value")),
            )
    else:
        t.add_column("Year")
        t.add_column("Q")
        t.add_column("Tenders", justify="right")
        t.add_column("Total Value", justify="right")
        _console.print(t)
        return
    _console.print(t)


def _print_single_bidder(rows: list[dict]) -> None:
    t = Table(title="Single-Bidder Ratio Trend", show_header=True, header_style="bold cyan")
    t.add_column("Company")
    t.add_column("Year")
    t.add_column("Q")
    t.add_column("Wins", justify="right")
    t.add_column("Unopposed", justify="right")
    t.add_column("Ratio", justify="right")
    for r in rows:
        ratio = r.get("single_bidder_ratio", 0.0)
        style = "red" if ratio >= 0.8 else ("yellow" if ratio >= 0.5 else "")
        t.add_row(
            r.get("company_name") or r.get("company_id", "?"),
            str(r.get("year", "?")),
            str(r.get("quarter", "?")),
            str(r.get("total_wins", "?")),
            str(r.get("single_bidder_wins", "?")),
            f"[{style}]{ratio:.1%}[/{style}]" if style else f"{ratio:.1%}",
        )
    _console.print(t)


def _print_spikes(rows: list[dict], metric: str) -> None:
    t = Table(
        title=f"Sudden Spikes — {metric}",
        show_header=True,
        header_style="bold red",
    )
    t.add_column("Company")
    t.add_column("Peak Qtr", justify="center")
    t.add_column("Latest", justify="right")
    t.add_column("Prior Mean", justify="right")
    t.add_column("Spike ×", justify="right")
    for r in rows:
        ratio = r.get("spike_ratio", 0.0)
        latest_qtr = f"{r.get('latest_year', '?')} Q{r.get('latest_quarter', '?')}"
        t.add_row(
            r.get("company_name") or r.get("company_id", "?"),
            latest_qtr,
            _fmt_value(r.get("latest_value"))
            if metric == "total_value"
            else str(int(r.get("latest_value", 0))),
            _fmt_value(r.get("prior_mean"))
            if metric == "total_value"
            else str(round(r.get("prior_mean", 0), 1)),
            f"[bold red]{ratio:.2f}×[/bold red]",
        )
    _console.print(t)


def _print_seasonal(rows: list[dict]) -> None:
    t = Table(title="Seasonal Procurement Pattern", show_header=True, header_style="bold cyan")
    t.add_column("Month")
    t.add_column("Tenders", justify="right")
    t.add_column("Avg/Year", justify="right")
    t.add_column("Total Value", justify="right")
    for r in rows:
        count = r.get("tender_count", 0)
        total = r.get("total_value")
        style = "red bold" if count == max(rr.get("tender_count", 0) for rr in rows) else ""
        t.add_row(
            r.get("month_name", str(r.get("month", "?"))),
            f"[{style}]{count}[/{style}]" if style else str(count),
            str(r.get("avg_per_year", "?")),
            _fmt_value(total),
        )
    _console.print(t)


def _print_sector(rows: list[dict], ateco_prefix: str) -> None:
    t = Table(
        title=f"Sector Spending Volatility — ATECO {ateco_prefix}",
        show_header=True,
        header_style="bold cyan",
    )
    t.add_column("Year")
    t.add_column("Q")
    t.add_column("Companies", justify="right")
    t.add_column("Total Spend", justify="right")
    t.add_column("Std Dev", justify="right")
    for r in rows:
        t.add_row(
            str(r.get("year", "?")),
            str(r.get("quarter", "?")),
            str(r.get("company_count", "?")),
            _fmt_value(r.get("total_value")),
            _fmt_value(r.get("stddev_value")),
        )
    _console.print(t)


def _print_history(rows: list[dict], company_id: str) -> None:
    if not rows:
        _console.print(
            Panel(
                f"No risk-score snapshots found for [bold]{company_id}[/bold].\n\n"
                "Run [bold]RiskEngine.run_global_analysis()[/bold] at least once to\n"
                "generate snapshots stored as Version nodes.",
                title="[yellow]No history[/yellow]",
                border_style="yellow",
            )
        )
        return
    t = Table(
        title=f"Risk Score History — {company_id}",
        show_header=True,
        header_style="bold cyan",
    )
    t.add_column("Date")
    t.add_column("Risk Score", justify="right")
    t.add_column("Anomaly Flags")
    for r in rows:
        score = r.get("risk_score", 0.0)
        style = "red" if score >= 0.7 else "yellow" if score >= 0.4 else "green"
        t.add_row(
            str(r.get("change_date", "?")),
            f"[{style}]{score:.3f}[/{style}]",
            str(r.get("anomaly_flags") or "—"),
        )
    _console.print(t)


# ──────────────────────────────────────────────────────────────────────
# Step runners
# ──────────────────────────────────────────────────────────────────────


def step_migrate(conn: Neo4jConnection, dry_run: bool) -> None:
    _console.rule("[bold]Step: Date Migration[/bold]")
    run_migration(conn, dry_run=dry_run)


def step_trends(
    ta: TemporalAnalyzer,
    company_id: str | None,
    quarters: int,
) -> None:
    _console.rule("[bold]Step: Tender Volume Trends[/bold]")
    rows = ta.get_tender_volume_trend(company_id=company_id, quarters=quarters)
    if rows:
        _print_trends(rows, company_id)

    _console.rule("[bold]Step: Single-Bidder Ratio Trend[/bold]")
    sb_rows = ta.get_single_bidder_trend(company_id=company_id, quarters=quarters)
    if sb_rows:
        _print_single_bidder(sb_rows)


def step_spikes(
    ta: TemporalAnalyzer,
    threshold: float,
    quarters: int,
) -> None:
    _console.rule("[bold]Step: Sudden Spike Detection[/bold]")
    for metric in ("tender_count", "total_value"):
        rows = ta.detect_sudden_spikes(metric=metric, threshold=threshold, quarters=quarters)
        if rows:
            _print_spikes(rows, metric)
        else:
            _console.print(f"[dim]No {metric} spikes above {threshold}× threshold.[/dim]")


def step_seasonal(ta: TemporalAnalyzer, years: int) -> None:
    _console.rule("[bold]Step: Seasonal Patterns[/bold]")
    rows = ta.get_seasonal_patterns(years=years)
    if rows:
        _print_seasonal(rows)


def step_sector(ta: TemporalAnalyzer, ateco_prefix: str, quarters: int) -> None:
    _console.rule(f"[bold]Step: Sector Volatility — {ateco_prefix}[/bold]")
    rows = ta.get_sector_spending_volatility(ateco_prefix=ateco_prefix, quarters=quarters)
    if rows:
        _print_sector(rows, ateco_prefix)


def step_history(ta: TemporalAnalyzer, company_id: str) -> None:
    _console.rule(f"[bold]Step: Risk Score History — {company_id}[/bold]")
    rows = ta.get_risk_score_history(company_id=company_id)
    _print_history(rows, company_id)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paladino Temporal Analysis — detect procurement spikes and trends"
    )
    parser.add_argument(
        "--step",
        choices=VALID_STEPS,
        default="all",
        help="Analysis step to run (default: all)",
    )
    parser.add_argument(
        "--quarters",
        type=int,
        default=8,
        metavar="N",
        help="Number of past quarters to include (default: 8)",
    )
    parser.add_argument(
        "--company",
        metavar="CF",
        help="Codice Fiscale / company ID to scope trends and history",
    )
    parser.add_argument(
        "--sector",
        metavar="ATECO",
        help="ATECO code prefix for sector volatility step",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=2.0,
        help="Spike threshold multiplier (default: 2.0)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=3,
        help="Years window for seasonal pattern analysis (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="For migrate step: count only, no writes",
    )
    args = parser.parse_args()

    settings = get_settings()
    conn = Neo4jConnection(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )
    ta = TemporalAnalyzer(conn)

    try:
        step = args.step
        if step in ("all", "migrate"):
            step_migrate(conn, dry_run=args.dry_run)

        if step in ("all", "trends"):
            if step == "trends" and not args.company:
                _console.print(
                    "[yellow]Tip:[/yellow] Pass [bold]--company CF[/bold] to scope trends to one winner."
                )
            step_trends(ta, company_id=args.company, quarters=args.quarters)

        if step in ("all", "spikes"):
            step_spikes(ta, threshold=args.threshold, quarters=args.quarters)

        if step in ("all", "seasonal"):
            step_seasonal(ta, years=args.years)

        if step in ("all", "sector"):
            if step == "all" and not args.sector:
                _console.print(
                    "[dim]Skipping sector step in 'all' mode — pass --sector ATECO to include it.[/dim]"
                )
            elif args.sector:
                step_sector(ta, ateco_prefix=args.sector, quarters=args.quarters)

        if step == "history":
            if not args.company:
                _console.print("[red]--company CF is required for the 'history' step.[/red]")
                sys.exit(1)
            step_history(ta, company_id=args.company)

        _console.rule("[green]Temporal analysis complete[/green]")

    except KeyboardInterrupt:
        _console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(0)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
