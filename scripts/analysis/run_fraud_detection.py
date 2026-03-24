#!/usr/bin/env python3
"""
Standalone entry point: run the Fraud Pattern Library.

Usage
-----
    python scripts/run_fraud_detection.py [--detectors all] [--report]

Examples
--------
    # Run all 10 detectors, print summary
    python scripts/run_fraud_detection.py

    # Run only specific detectors
    python scripts/run_fraud_detection.py --detectors bid_rotation split_tendering

    # Run all and export findings to CSV
    python scripts/run_fraud_detection.py --report
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from paladino.db import Neo4jConnection
from paladino.analytics.fraud_patterns import FraudPatternLibrary

console = Console()

AVAILABLE_DETECTORS = [
    "bid_rotation",
    "ghost_bidding",
    "split_tendering",
    "short_award_window",
    "price_manipulation",
    "ubo_conflict",
    "winner_loser_ring",
    "pnrr_concentration",
    "community_monopoly",
    "network_clique",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Paladino Fraud Pattern Detection Runner"
    )
    parser.add_argument(
        "--detectors",
        nargs="+",
        default=["all"],
        choices=AVAILABLE_DETECTORS + ["all"],
        metavar="DETECTOR",
        help=f"Detectors to run. Default: all. Choices: {', '.join(AVAILABLE_DETECTORS)}",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Export all findings to a JSON file in the reports/ directory.",
    )
    return parser.parse_args()


def print_results_table(all_results: dict):
    """Print a Rich summary table of all detections."""
    table = Table(
        title="🔴 Fraud Pattern Detection Results",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("Detector",        style="bold yellow", min_width=22)
    table.add_column("Findings",        justify="right", style="bold red")
    table.add_column("Top Finding",     style="cyan", max_width=60)

    for detector_name, findings in all_results.items():
        count = len(findings)
        if count == 0:
            top = "[dim]— no findings —[/dim]"
        else:
            f = findings[0]
            # Build a short summary from whichever fields are present
            parts = []
            for key in ("buyer", "company", "cig", "winner", "peer", "region"):
                if key in f:
                    parts.append(f"{key}={f[key]!r}")
            top = ", ".join(parts[:3]) or str(findings[0])

        color = "red" if count > 0 else "green"
        table.add_row(
            detector_name,
            f"[{color}]{count}[/{color}]",
            top,
        )

    console.print(table)
    total = sum(len(v) for v in all_results.values())
    console.print(f"\n[bold]Total findings:[/bold] [red]{total}[/red]")


def export_report(results: dict, run_id: str):
    """Save all findings as a JSON report."""
    reports_dir = project_root / "reports"
    reports_dir.mkdir(exist_ok=True)

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = reports_dir / f"fraud_detection_{ts}.json"

    payload = {"run_id": run_id, "results": results}
    out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    console.print(f"\n[green]✓ Report saved:[/green] {out_path}")


def main():
    args = parse_args()

    console.print(Panel(
        "[bold magenta]🛡️  PALADINO — Fraud Pattern Detection[/bold magenta]\n"
        "[dim]Scanning the knowledge graph for procurement red flags...[/dim]",
        box=box.DOUBLE,
    ))

    conn = Neo4jConnection()
    try:
        library = FraudPatternLibrary(conn)

        run_all = "all" in args.detectors

        if run_all:
            console.print("[cyan]Running all 10 detectors...[/cyan]\n")
            all_results = library.run_all_detectors()
        else:
            console.print(f"[cyan]Running selected detectors: {', '.join(args.detectors)}[/cyan]\n")
            all_results = {}
            detector_map = {
                "bid_rotation":       library.detect_bid_rotation,
                "ghost_bidding":      library.detect_ghost_bidding,
                "split_tendering":    library.detect_split_tendering,
                "short_award_window": library.detect_short_award_window,
                "price_manipulation": library.detect_price_manipulation,
                "ubo_conflict":       library.detect_ubo_conflict,
                "winner_loser_ring":  library.detect_winner_loser_ring,
                "pnrr_concentration": library.detect_pnrr_concentration,
                "community_monopoly": library.detect_community_monopoly,
                "network_clique":     library.detect_network_clique,
            }
            for name in args.detectors:
                try:
                    all_results[name] = detector_map[name]()
                except Exception as exc:
                    logger.error(f"Detector '{name}' failed: {exc}")
                    all_results[name] = []

        print_results_table(all_results)

        if args.report:
            export_report(all_results, library.run_id)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
