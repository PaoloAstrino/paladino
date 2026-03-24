"""
Supply-Chain & Ownership Graph ETL
====================================
Orchestrates the three sub-pipelines that build the supply-chain and
corporate-ownership layers of the Paladino Knowledge Graph.

Steps
-----
subcontractors
    Parse PNRR_Subappaltatori_Gare.csv and create SUBCONTRACTS_TO edges
    linking each prime-contractor (winner) to its sub-contractors.

corporate
    Discover, parse, and load corporate CSV files from data/corporate/raw/.
    Populates Person nodes, REPRESENTS (director) edges, SHAREHOLDER_OF and
    SHARES_UBO edges.  Prints rich guidance if no files are found.

analytics
    Run GDS supply-chain SCC, ownership PageRank, and the three new fraud
    detectors (carousel_fraud, board_overlap_collusion,
    subcontractor_concentration) that depend on supply-chain data.

fetch-corporate-data
    Download fresh CSV files from ANAC OpenData (and ATOKA/OpenCorporates if
    API keys are configured) into data/corporate/raw/.
    Saves a SyncCheckpoint in Neo4j so subsequent runs are incremental.
    Does NOT load them — run the ``corporate`` step afterwards.

all (default)
    Runs all three steps in order (fetch-corporate-data → subcontractors →
    corporate → analytics).

Usage
-----
    python scripts/run_supply_chain_etl.py
    python scripts/run_supply_chain_etl.py --step fetch-corporate-data
    python scripts/run_supply_chain_etl.py --step subcontractors
    python scripts/run_supply_chain_etl.py --step corporate
    python scripts/run_supply_chain_etl.py --step analytics
    python scripts/run_supply_chain_etl.py --step all --dry-run
"""

import argparse
import sys
from pathlib import Path

# ── ensure project root is on PYTHONPATH ──────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _print_header(title: str) -> None:
    console.print()
    console.print(f"[bold cyan]{'─' * 60}[/bold cyan]")
    console.print(f"[bold white]  {title}[/bold white]")
    console.print(f"[bold cyan]{'─' * 60}[/bold cyan]")


def _check_neo4j(settings) -> bool:
    """Return True if Neo4j is reachable, else print a guidance panel."""
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception as exc:
        console.print(
            Panel(
                f"[red]Cannot connect to Neo4j[/red]: {exc}\n\n"
                "Make sure the database is running, then check these settings:\n"
                "  [bold]NEO4J_URI[/bold]      → " + settings.neo4j_uri + "\n"
                "  [bold]NEO4J_USER[/bold]     → " + settings.neo4j_user + "\n"
                "  [bold]NEO4J_PASSWORD[/bold] → (set in your .env file)\n\n"
                "Quick start:\n"
                "  [bold white]docker-compose up -d[/bold white]  (uses docker-compose.yml in project root)",
                title="[red]Neo4j Unreachable[/red]",
                border_style="red",
            )
        )
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Step 0 — Fetch corporate data
# ──────────────────────────────────────────────────────────────────────────────


def run_fetch_corporate(settings, dry_run: bool = False) -> None:
    """
    Download fresh corporate CSV files from configured remote sources.

    Sources tried (in order, all graceful on failure):
      1. ANAC OpenData catalogue  (no auth required)
      2. ATOKA API                (requires ATOKA_API_KEY env-var)
      3. OpenCorporates           (requires OPENCORPORATES_API_KEY env-var)

    All downloaded files land in ``data/corporate/raw/`` and are picked up
    automatically by the next ``--step corporate`` run.
    """
    _print_header("Step 0 / 3 — Fetch Corporate Data  (Registro Imprese / ANAC)")

    from paladino.etl.corporate.infocamere_downloader import RegistroImpreseFetcher

    fetcher = RegistroImpreseFetcher(data_dir=settings.data_dir, dry_run=dry_run)
    summary = fetcher.fetch_all()
    fetcher.print_summary(summary)

    if not dry_run and summary.successful:
        # Record the sync checkpoint so the corporate loader can do delta loads
        try:
            from paladino.db import Neo4jConnection
            from paladino.etl.corporate.incremental_sync import CorporateSyncTracker

            conn = Neo4jConnection(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
            tracker = CorporateSyncTracker(conn)
            tracker.record_sync(rows_written=summary.total_rows)
            conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[sync] Could not save sync checkpoint: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 — Subcontractors
# ──────────────────────────────────────────────────────────────────────────────


def run_subcontractors(settings, dry_run: bool = False) -> int:
    """
    Load PNRR subcontractor data and create SUBCONTRACTS_TO edges.

    Returns number of edges created (0 on dry-run or error).
    """
    _print_header("Step 1 / 3 — Subcontractor ETL  (SUBCONTRACTS_TO edges)")

    import polars as pl
    from neo4j import GraphDatabase

    from paladino.etl.pnnr_loader import PnnrNeo4jLoader
    from paladino.etl.pnnr_transform import PnnrTransformer

    sub_path = settings.data_dir / "pnnr" / "PNRR_Subappaltatori_Gare.csv"

    if not sub_path.exists():
        console.print(
            Panel(
                f"[yellow]File not found[/yellow]: {sub_path}\n\n"
                "This file is published by ANAC on the open-data portal:\n"
                "  [link=https://dati.anticorruzione.it/]https://dati.anticorruzione.it/[/link]\n\n"
                "Download the CSV and place it at:\n"
                f"  [bold]{sub_path}[/bold]\n\n"
                "The file is semicolon-delimited and contains columns like:\n"
                "  CIG, CUP, Codice Fiscale/P.IVA Sub-Appaltatore, "
                "Denominazione Sub-Appaltatore, …",
                title="[yellow]PNRR_Subappaltatori_Gare.csv missing[/yellow]",
                border_style="yellow",
            )
        )
        return 0

    logger.info(f"Reading subcontractors — {sub_path}")
    df = pl.read_csv(sub_path, separator=";", ignore_errors=True)
    logger.info(f"  {len(df):,} rows read")

    transformer = PnnrTransformer()
    data = transformer.transform_subappaltatori(df)

    sub_df = data["sub_contracts"]
    companies_df = data["companies"]

    console.print(
        f"[green]✓[/green] Transformed: "
        f"{len(companies_df):,} companies, {len(sub_df):,} subcontract rows"
    )

    if dry_run:
        console.print("[dim]--dry-run: skipping Neo4j writes[/dim]")
        return 0

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    loader = PnnrNeo4jLoader(driver)

    n_companies = loader.load_companies(companies_df)
    n_sub = loader.load_sub_contracts(sub_df)
    n_edges = loader.load_subcontracts_to(sub_df)

    driver.close()

    table = Table(title="Subcontractor ETL Results", box=box.SIMPLE)
    table.add_column("Operation", style="cyan")
    table.add_column("Records", justify="right", style="bold green")
    table.add_row("Companies merged", str(n_companies))
    table.add_row("SUB_CONTRACTOR_ON edges", str(n_sub))
    table.add_row("SUBCONTRACTS_TO edges (new)", str(n_edges))
    console.print(table)

    return n_edges


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 — Corporate ETL
# ──────────────────────────────────────────────────────────────────────────────


def run_corporate(settings, dry_run: bool = False) -> dict:
    """
    Discover and load corporate CSV files (directors, shareholders).

    Returns dict with counts (all 0 on dry-run or when no files found).
    """
    _print_header("Step 2 / 3 — Corporate ETL  (Persons, REPRESENTS, SHAREHOLDER_OF)")

    from paladino.db import Neo4jConnection
    from paladino.etl.corporate import (
        CorporateLoader,
        CorporateSourceDiscovery,
        CorporateTransformer,
    )

    discovery = CorporateSourceDiscovery(settings.data_dir)
    result = discovery.discover()
    discovery.print_summary(result)  # rich panel with guidance if nothing found

    if not result.source_files:
        return {"persons": 0, "represents": 0, "shareholdings": 0}

    transformer = CorporateTransformer()
    frames = transformer.transform_all(result.source_files)

    console.print(
        f"[green]✓[/green] Transformed: "
        f"{len(frames['persons_df']):,} persons, "
        f"{len(frames['represents_df']):,} director-links, "
        f"{len(frames['shareholding_df']):,} shareholding rows"
    )

    if dry_run:
        console.print("[dim]--dry-run: skipping Neo4j writes[/dim]")
        return {"persons": 0, "represents": 0, "shareholdings": 0}

    conn = Neo4jConnection()
    loader = CorporateLoader(conn)
    counts = loader.load_all(
        frames["persons_df"],
        frames["represents_df"],
        frames["shareholding_df"],
    )
    conn.close()
    return counts


# ──────────────────────────────────────────────────────────────────────────────
# Step 3 — Analytics
# ──────────────────────────────────────────────────────────────────────────────


def run_analytics(dry_run: bool = False) -> None:
    """
    Run GDS projections (supply-chain SCC, ownership PageRank) and the three
    supply-chain fraud detectors.
    """
    _print_header("Step 3 / 3 — Supply-Chain & Ownership Analytics")

    from paladino.analytics.fraud_patterns import FraudPatternLibrary
    from paladino.analytics.gds_manager import GDSManager
    from paladino.db import Neo4jConnection

    if dry_run:
        console.print("[dim]--dry-run: skipping analytics[/dim]")
        return

    conn = Neo4jConnection()

    # GDS projections
    gds = GDSManager(conn)
    console.print("[cyan]→[/cyan] Projecting supply-chain graph…")
    ok_sc = gds.project_supply_chain_graph()
    if ok_sc:
        n_scc = gds.run_supply_chain_scc()
        console.print(f"  [green]✓[/green] SCC written to {n_scc:,} nodes")

    console.print("[cyan]→[/cyan] Projecting ownership graph…")
    ok_own = gds.project_ownership_graph()
    if ok_own:
        n_pr = gds.run_ownership_pagerank()
        console.print(f"  [green]✓[/green] Ownership PageRank written to {n_pr:,} nodes")

    # Fraud detectors
    lib = FraudPatternLibrary(conn)

    console.print("[cyan]→[/cyan] Running carousel_fraud detector…")
    carousels = lib.detect_carousel_fraud()
    console.print(
        f"  [{'red' if carousels else 'green'}]"
        f"{'⚠' if carousels else '✓'}[/] "
        f"{len(carousels)} finding(s)"
    )

    console.print("[cyan]→[/cyan] Running board_overlap_collusion detector…")
    overlaps = lib.detect_board_overlap_collusion()
    console.print(
        f"  [{'red' if overlaps else 'green'}]"
        f"{'⚠' if overlaps else '✓'}[/] "
        f"{len(overlaps)} finding(s)"
    )

    console.print("[cyan]→[/cyan] Running subcontractor_concentration detector…")
    concentrations = lib.detect_subcontractor_concentration()
    console.print(
        f"  [{'red' if concentrations else 'green'}]"
        f"{'⚠' if concentrations else '✓'}[/] "
        f"{len(concentrations)} finding(s)"
    )

    conn.close()

    # Summary
    total = len(carousels) + len(overlaps) + len(concentrations)
    if total:
        console.print(
            Panel(
                f"[red]⚠ {total} supply-chain fraud finding(s) detected.[/red]\n\n"
                "Use the Paladino CLI → Investigate → Oracle to review details,\n"
                "or query FraudPattern nodes directly in Neo4j Browser.",
                title="[red]Supply-Chain Fraud Alerts[/red]",
                border_style="red",
            )
        )
    else:
        console.print(
            Panel(
                "[green]No supply-chain fraud patterns found.[/green]\n"
                "This may mean data is not yet loaded — "
                "run --step subcontractors first.",
                border_style="green",
            )
        )


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Paladino — Supply-Chain & Ownership Graph ETL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step",
        choices=["all", "fetch-corporate-data", "subcontractors", "corporate", "analytics"],
        default="all",
        help="Which pipeline step(s) to run (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and transform data but skip all Neo4j writes",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    console.print()
    console.print(
        Panel(
            "[bold magenta]Paladino — Supply-Chain & Ownership Graph ETL[/bold magenta]\n"
            f"Step: [bold]{args.step}[/bold]"
            + ("  [yellow](DRY RUN)[/yellow]" if args.dry_run else ""),
            border_style="magenta",
        )
    )

    # Load settings
    from paladino.config import settings

    # Gate all Neo4j-writing steps on connectivity
    if not args.dry_run:
        if not _check_neo4j(settings):
            console.print("[red]Aborting — fix Neo4j connection first.[/red]")
            sys.exit(1)

    run_fetch = args.step in ("all", "fetch-corporate-data")
    run_sub = args.step in ("all", "subcontractors")
    run_corp = args.step in ("all", "corporate")
    run_an = args.step in ("all", "analytics")

    if run_fetch:
        run_fetch_corporate(settings, dry_run=args.dry_run)

    if run_sub:
        run_subcontractors(settings, dry_run=args.dry_run)

    if run_corp:
        run_corporate(settings, dry_run=args.dry_run)

    if run_an:
        run_analytics(dry_run=args.dry_run)

    console.print()
    console.print("[bold green]Supply-Chain ETL complete.[/bold green]")
    console.print()


if __name__ == "__main__":
    main()
