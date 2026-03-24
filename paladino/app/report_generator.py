#!/usr/bin/env python3
"""
Paladino Report Generator
Export query results and investigation sessions to various formats.
"""

import csv
import json
from datetime import datetime
from pathlib import Path

from rich.console import Console

console = Console()


class ReportGenerator:
    """Generate reports from Paladino investigations."""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path.cwd() / "reports"
        self.output_dir.mkdir(exist_ok=True)

    def export_to_json(self, data: list[dict], filename: str = None) -> Path:
        """Export results to JSON."""
        if not filename:
            filename = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        output_path = self.output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        console.print(f"[green]✓ Exported to {output_path}[/green]")
        return output_path

    def export_to_csv(self, data: list[dict], filename: str = None) -> Path:
        """Export results to CSV."""
        if not filename:
            filename = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        output_path = self.output_dir / filename
        if not data:
            console.print("[yellow]No data to export[/yellow]")
            return output_path

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=data[0].keys())
            writer.writeheader()
            writer.writerows(data)

        console.print(f"[green]✓ Exported to {output_path}[/green]")
        return output_path

    def generate_markdown_report(self, session_data: dict, filename: str = None) -> Path:
        """Generate a Markdown investigation report."""
        if not filename:
            filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        output_path = self.output_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("# 🛡️ Paladino Investigation Report\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Session ID:** {session_data.get('session_id', 'N/A')}\n\n")
            f.write("---\n\n")

            # Summary
            f.write("## 📊 Summary\n\n")
            f.write(f"- **Total Queries:** {len(session_data.get('queries', []))}\n")
            f.write(f"- **Duration:** {session_data.get('duration', 'N/A')}\n\n")

            # Queries and Results
            f.write("## 🔍 Queries & Results\n\n")
            for i, query in enumerate(session_data.get("queries", []), 1):
                f.write(f"### Query {i}\n\n")
                f.write(f"```\n{query.get('query', 'N/A')}\n```\n\n")

                results = query.get("results", [])
                if results:
                    f.write(f"**Results:** {len(results)} rows\n\n")
                    # Table header
                    headers = list(results[0].keys())
                    f.write("| " + " | ".join(headers) + " |\n")
                    f.write("| " + " | ".join(["---"] * len(headers)) + " |\n")
                    # Table rows (limit to 20)
                    for row in results[:20]:
                        f.write("| " + " | ".join(str(v) for v in row.values()) + " |\n")
                    if len(results) > 20:
                        f.write(f"\n*... and {len(results) - 20} more rows*\n")
                f.write("\n")

            # Insights
            if session_data.get("insights"):
                f.write("## 💡 Insights\n\n")
                for insight in session_data["insights"]:
                    f.write(f"- {insight}\n")
                f.write("\n")

        console.print(f"[green]✓ Report generated: {output_path}[/green]")
        return output_path

    def export_session(self, session_data: dict, format: str = "all") -> dict[str, Path]:
        """Export complete session in multiple formats."""
        exported = {}

        if format in ["json", "all"]:
            exported["json"] = self.export_to_json(
                session_data.get("queries", []),
                f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            )

        if format in ["csv", "all"]:
            # Flatten all results
            all_results = []
            for query in session_data.get("queries", []):
                results = query.get("results", [])
                for row in results:
                    row["_query"] = query.get("query", "")
                    all_results.append(row)

            exported["csv"] = self.export_to_csv(
                all_results, f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )

        if format in ["md", "markdown", "all"]:
            exported["markdown"] = self.generate_markdown_report(session_data)

        return exported


def main():
    """Demo/test the report generator."""
    generator = ReportGenerator()

    # Demo data
    session_data = {
        "session_id": "demo_001",
        "duration": "5 minutes",
        "queries": [
            {
                "query": "MATCH (c:Company)-[:WINS]->(t:Tender) RETURN c.nome_normalizzato, count(t) ORDER BY count(t) DESC LIMIT 10",
                "results": [
                    {"c.nome_normalizzato": "IMPRESA INESISTENTE", "count(t)": 168},
                    {"c.nome_normalizzato": "VIATRIS ITALIA", "count(t)": 60},
                ],
            }
        ],
        "insights": ["Top company has 168 tenders", "High concentration in top 10"],
    }

    # Export in all formats
    exported = generator.export_session(session_data, format="all")
    print(f"\nExported to: {exported}")


if __name__ == "__main__":
    main()
