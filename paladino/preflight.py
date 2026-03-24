"""
Preflight Diagnostic Tool - Environment & Dependency Validation.
Ensures the local workstation is ready for Paladino operations.
"""

import shutil
import sys

import psutil
from loguru import logger
from rich.console import Console
from rich.table import Table

from paladino.db import Neo4jConnection


class PreflightChecker:
    """
    Checks for Python, Docker, Neo4j, and GDS availability.
    """

    def __init__(self, console: Console = None):
        self.console = console or Console()
        self.results: list[tuple[str, str, str]] = []

    def check_python(self) -> bool:
        version = sys.version.split()[0]
        status = "✅" if sys.version_info >= (3, 11) else "❌"
        self.results.append(("Python 3.11+", version, status))
        return sys.version_info >= (3, 11)

    def check_memory(self) -> bool:
        total_gb = psutil.virtual_memory().total / (1024**3)
        status = "✅" if total_gb >= 15.5 else "⚠️"
        self.results.append(("System RAM (16GB+)", f"{total_gb:.1f} GB", status))
        return total_gb >= 15.5

    def check_docker(self) -> bool:
        docker_path = shutil.which("docker")
        status = "✅" if docker_path else "⚠️"
        self.results.append(("Docker Engine", "Detected" if docker_path else "Not Found", status))
        return bool(docker_path)

    def check_neo4j(self) -> bool:
        """Connects to Neo4j and checks for required plugins (APOC, GDS)."""
        try:
            conn = Neo4jConnection()

            # Check GDS and APOC via Cypher
            query = "SHOW FUNCTIONS YIELD name WHERE name STARTS WITH 'gds' OR name STARTS WITH 'apoc' RETURN count(*) as count"
            res = conn.run_query(query)
            count = res[0]["count"] if res else 0

            status = "✅" if count > 0 else "❌"
            self.results.append(("Neo4j + GDS/APOC", f"{count} functions found", status))
            conn.close()
            return count > 0
        except Exception as e:
            self.results.append(("Neo4j Connection", "FAILED", "❌"))
            logger.error(f"Neo4j Connection Error: {e}")
            return False

    def run_all(self):
        """Execute all diagnostics and print a summary table."""
        self.console.print("\n[bold cyan]🛡️ PALADINO PREFLIGHT DIAGNOSTICS[/bold cyan]")
        self.console.print("[dim]Checking system readiness for forensic operations...[/dim]\n")

        self.check_python()
        self.check_memory()
        self.check_docker()
        self.check_neo4j()

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Requirement", style="dim")
        table.add_column("Detected", justify="right")
        table.add_column("Status", justify="center")

        for req, val, status in self.results:
            table.add_row(req, val, status)

        self.console.print(table)

        all_passed = all(
            r[2] == "✅"
            for r in self.results
            if r[0] != "System RAM (16GB+)" and r[0] != "Docker Engine"
        )

        if all_passed:
            self.console.print(
                "\n[bold green]System is READY. Knight, you may proceed.[/bold green]\n"
            )
        else:
            self.console.print(
                "\n[bold red]System dependencies missing. Check the Neo4j or Python configuration.[/bold red]\n"
            )


if __name__ == "__main__":
    checker = PreflightChecker()
    checker.run_all()
