"""
Paladino Investigator REPL
Encapsulates the interactive investigative terminal.
"""

import sys
import json
import csv
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger

from paladino.db import get_driver
from paladino.schema_manager import SchemaManager
from paladino.app.graphrag_agent import GraphRAGAgent
from paladino.constants import PALADIN_ART, PALADINO_THEME
from paladino.errors import LLMConnectionError

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.status import Status
from rich import box

console = Console(theme=PALADINO_THEME)


def draw_paladin(console: Optional[Console] = None):
    """Draw a colorful pixel art Paladin using ANSI background codes."""
    # ANSI color codes (Background)
    reset = "\033[0m"
    silver = "\033[48;5;250m  "  # Armor
    dark_silver = "\033[48;5;244m  "  # Armor shadows
    gold = "\033[48;5;220m  "    # Helmet/Details
    red = "\033[48;5;160m  "     # Cape
    skin = "\033[48;5;223m  "    # Face
    empty = "  "                 # Empty space

    # Paladin pixel art schema
    pixel_art = [
        [empty, empty, gold, gold, gold, empty, empty],
        [empty, gold, silver, gold, silver, gold, empty],
        [red, silver, silver, silver, silver, silver, red],
        [red, silver, silver, gold, silver, silver, red],
        [red, silver, silver, silver, silver, silver, red],
        [empty, dark_silver, empty, empty, empty, dark_silver, empty],
        [empty, dark_silver, empty, empty, empty, dark_silver, empty]
    ]

    out = ["\n    --- IL TUO PALADINO ---"]
    for row in pixel_art:
        line = "".join(row)
        out.append(f"    {line}{reset}")
    out.append("    -----------------------\n")
    
    if console:
        for line in out:
            console.print(line)
    else:
        for line in out:
            print(line)

class InvestigativeREPL:
    """Enhanced interactive shell for graph investigation."""

    def __init__(self, console: Optional[Console] = None):
        """Initialize the investigative REPL with Rich UI.
        
        Args:
            console: Optional Rich Console instance. Creates a new one if not provided.
        """
        self.console = console or Console(theme=PALADINO_THEME)
        self.context = {}  # Initialize context

        # Only draw/print banner if not in a test context where console is usually mocked
        if not console:
            # We already print the banner from scripts/investigate.py if it's the main entry point
            # If called directly, print the banner.
            # print(PALADIN_ART) # This is now handled by draw_paladin if not console
            self.console.print(Panel(Text("Paladino Terminal Investigator", justify="center", style="bold green"), border_style="magenta", box=box.DOUBLE))
            self.console.print("[brand]Initializing connection to the Knowledge Graph...[/brand]")
        
        with Status("Connecting to Neo4j...", console=self.console, spinner="simpleDots"):
            try:
                # Initialize components
                self.driver = get_driver()
                # Assuming package structure
                lib_path = Path(__file__).parent.parent.parent
                schema_dir = lib_path / "paladino" / "schema"
                if not schema_dir.exists():
                     # Fallback if run from different context
                     schema_dir = Path("schema")
                
                schema_manager = SchemaManager(self.driver, schema_dir)
                schema_metadata = schema_manager.get_schema_metadata()
                self.agent = GraphRAGAgent(self.driver, schema_metadata=schema_metadata)
            except Exception as e:
                self.console.print(f"[error]Failed to connect: {e}[/error]")
                sys.exit(1)
        
        self.console.print("\n[success]✅ System Ready[/success]\n")

        # Ensure LLM is reachable before entering the REPL
        self._ensure_llm_running()

        # Welcome guide for new users
        self._show_welcome_guide()
    
    def _ensure_llm_running(self) -> None:
        """Check the LLM backend is reachable.

        If Ollama is the backend and it is offline, the user is offered three
        options:
          1. Auto-start Ollama via ``ollama serve`` (background process).
          2. Open the LLM config wizard to switch to an API key.
          3. Continue anyway (every query will fail until they fix it).
        """
        import requests as _req
        import questionary
        from paladino.config import settings

        # If an external API key is set, skip the Ollama check.
        if settings.llm_api_key:
            return

        base_url = (settings.llm_api_base or settings.ollama_base_url).rstrip("/")

        # Try a quick ping on the Ollama /api/tags endpoint.
        try:
            r = _req.get(f"{base_url}/api/tags", timeout=3)
            r.raise_for_status()
            return  # Ollama is up — nothing to do
        except Exception:
            pass

        # ── Ollama is not running ─────────────────────────────────────────────
        self.console.print(
            "\n[warning]⚠️  Ollama is not running "
            f"(checked: {base_url}/api/tags).[/warning]"
        )

        action = questionary.select(
            "LLM service is offline. What do you want to do?",
            choices=[
                "Auto-start Ollama now  (ollama serve)",
                "Configure a different LLM  (API key / model)",
                "Continue anyway  (queries will fail until Ollama is running)",
            ],
            style=questionary.Style([
                ('highlighted', 'fg:#00ffff bold'),
                ('pointer',     'fg:#ff00ff bold'),
            ])
        ).ask()

        if action is None or action.startswith("Continue anyway"):
            self.console.print(
                "[dim]Continuing without LLM. "
                "Run [bold]ollama serve[/bold] in a separate terminal, "
                "then retry your question.[/dim]"
            )
            return

        if action.startswith("Configure"):
            # Import lazily to avoid circular import
            try:
                from paladino.cli import setup_llm_config
                setup_llm_config()
            except Exception as e:
                self.console.print(f"[error]Could not open LLM wizard: {e}[/error]")
            return

        # ── Auto-start path ───────────────────────────────────────────────────
        self.console.print("[info]Starting Ollama in the background…[/info]")
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            self.console.print(
                "[error]❌ 'ollama' command not found.\n"
                "Install Ollama from [link=https://ollama.ai]https://ollama.ai[/link] "
                "then run [bold]ollama pull llama3.2[/bold].[/error]"
            )
            return

        # Poll until Ollama answers or we time out (15 s)
        self.console.print("[info]Waiting for Ollama to start", end="")
        ready = False
        for _ in range(15):
            time.sleep(1)
            self.console.print(".", end="", highlight=False)
            try:
                r = _req.get(f"{base_url}/api/tags", timeout=2)
                if r.status_code < 500:
                    ready = True
                    break
            except Exception:
                pass
        self.console.print("")  # newline

        if ready:
            self.console.print("[success]✅ Ollama started successfully![/success]")
        else:
            self.console.print(
                "[error]❌ Ollama did not respond within 15 s.\n"
                "Try running [bold]ollama serve[/bold] manually in another terminal.[/error]"
            )

    def _show_welcome_guide(self):
        """Display a welcome guide for first-time users."""
        welcome = Panel(
            "[bold cyan]👋 Welcome to Paladino Investigator![/bold cyan]\n\n"
            "[white]Your AI-powered detective for Italian public funds data.[/white]\n\n"
            "[bold yellow]📊 What's in the graph?[/bold yellow]\n"
            "  • 9.7M+ Public Projects (OpenCUP, PNRR)\n"
            "  • 97K+ Tenders (ANAC procurement)\n"
            "  • 55K+ Companies & their relationships\n"
            "  • Risk scores & fraud detection ready\n\n"
            "[bold green]🚀 Quick Start - Try these queries:[/bold green]\n"
            "  [cyan]1.[/cyan] [white]'Show me top 10 companies by tender wins'[/white]\n"
            "  [cyan]2.[/cyan] [white]'Which projects are funded by PNRR?'[/white]\n"
            "  [cyan]3.[/cyan] [white]'Companies with high risk scores in Sicilia'[/white]\n"
            "  [cyan]4.[/cyan] [white]'@top_vendors' (use @ for templates)\n\n"
            "[bold magenta]💡 Pro Tips:[/bold magenta]\n"
            "  • Type [yellow]'help'[/yellow] for full command list\n"
            "  • Type [yellow]'stats'[/yellow] to see graph size\n"
            "  • Type [yellow]'templates'[/yellow] to see all templates\n"
            "  • Press [yellow]Ctrl+C[/yellow] to exit\n\n"
            "[dim]Query in Italian or English - the AI understands both![/dim]",
            title="🛡️ PALADINO INVESTIGATION GUIDE",
            border_style="bright_magenta",
            box=box.DOUBLE_EDGE
        )
        self.console.print(welcome)
    
    def show_stats(self):
        """Display graph statistics using Rich tables."""
        self.console.print("\n[highlight]📊 Graph Infrastructure Statistics[/highlight]")
        
        with Status("Counting nodes and relationships...", spinner="dots", console=self.console):
            with self.driver.session() as session:
                # Node counts
                nodes_res = list(session.run("MATCH (n) RETURN labels(n)[0] as label, count(n) as count ORDER BY count DESC"))
                # Relationship counts
                rels_res = list(session.run("MATCH ()-[r]->() RETURN type(r) as type, count(r) as count ORDER BY count DESC"))
                # GDS
                gds_res = session.run("MATCH (n) WHERE n.centrality_score IS NOT NULL RETURN count(n) as nodes_with_centrality, avg(n.centrality_score) as avg_centrality").single()

        # Nodes Table
        nodes_table = Table(title="Knowledge Nodes", box=box.SIMPLE)
        nodes_table.add_column("Type", style="cyan")
        nodes_table.add_column("Count", justify="right", style="green")
        for r in nodes_res[:8]:
            nodes_table.add_row(r["label"] or "Unknown", f"{r['count']:,}")
        
        # Rels Table
        rels_table = Table(title="Graph Connections", box=box.SIMPLE)
        rels_table.add_column("Relation", style="magenta")
        rels_table.add_column("Count", justify="right", style="green")
        for r in rels_res[:8]:
            rels_table.add_row(r["type"], f"{r['count']:,}")

        self.console.print(nodes_table)
        self.console.print(rels_table)
        
        if gds_res and gds_res["nodes_with_centrality"] > 0:
            self.console.print(Panel(
                f"PageRank Active Nodes: [bold]{gds_res['nodes_with_centrality']:,}[/bold]\n"
                f"Average Network Influence: [bold]{gds_res['avg_centrality']:.6f}[/bold]",
                title="Intelligence Layer", border_style="yellow"
            ))

    def show_templates(self):
        """Display templates in a clean menu."""
        table = Table(title="Investigative Templates", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim")
        table.add_column("Template ID", style="cyan")
        
        templates = self.agent.templates.list_templates()
        for i, t in enumerate(templates, 1):
            table.add_row(str(i), t)
        
        self.console.print(table)
        self.console.print("\n[info]Tip: Invoke via @name, e.g. [bold]@top_vendors[/bold][/info]")

    def format_results(self, results: List[Dict], title="Investigation Results", limit: Optional[int] = None) -> Optional[str]:
        """Format results as a Rich Table and return as a string."""
        if not results:
            return "[warning]No records found for this investigation path.[/warning]"
        
        table = Table(title=title, box=box.HEAVY_EDGE, header_style="bold cyan")
        
        # Get columns from the first record keys
        keys = list(results[0].keys())
        for key in keys:
            table.add_column(key.replace("_", " ").title())
        
        display_results = results[:limit] if limit else results
        for record in display_results:
            row_items = []
            for key in keys:
                val = record.get(key)
                if isinstance(val, (int, float)) and val > 1000:
                    str_val = f"{val:,.2f}" if isinstance(val, float) else f"{val:,}"
                else:
                    str_val = str(val) if val is not None else "[dim]null[/dim]"
                
                # Truncate for table
                if len(str_val) > 40:
                    str_val = str_val[:37] + "..."
                row_items.append(str_val)
            table.add_row(*row_items)
            
        with self.console.capture() as capture:
            self.console.print(table)
        return capture.get()

    def process_query(self, question: str):
        """Process natural language query with visual feedback."""
        self.console.rule(f"[highlight]Investigation: {question}[/highlight]")

        with Status("Analyzing question & generating Cypher...", spinner="bouncingBall", console=self.console):
            try:
                result = self.agent.natural_language_query(question)
            except LLMConnectionError as e:
                self.console.print(f"\n[warning]⚠️  {e.message}[/warning]")
                if e.hint:
                    self.console.print(f"[cyan]{e.hint}[/cyan]")
                self.console.print(
                    "[dim]Tip: run [bold]ollama serve[/bold] in a separate terminal, "
                    "or open [bold]LLM Configuration[/bold] from the main menu.[/dim]"
                )
                return
            except Exception as e:
                self.console.print(f"[error]Intelligence Error: {e}[/error]")
                return

        if "error" in result:
            # Show helpful error message
            self.console.print(f"\n[warning]⚠️ {result['error']}[/warning]")
            
            # Show help if available
            if "help" in result:
                self.console.print(f"[cyan]💡 {result['help']}[/cyan]")
            
            # Show missing params if available
            if "missing_params" in result:
                self.console.print(f"[yellow]Required: {result['missing_params']}[/yellow]")
            
            # Show example if available
            if "example" in result:
                self.console.print(f"[dim]{result['example']}[/dim]")
            
            return

        # Strategy Info
        method = result.get("method", "unknown")
        if method == "template":
            self.console.print(f"[info]Strategy: Pattern Matching (Template: {result.get('template')})[/info]")
        else:
            self.console.print(f"[info]Strategy: Real-time Cypher Reasoning[/info]")
            if result.get("cypher"):
                self.console.print(Panel(result['cypher'], title="Generated Logic", border_style="dim blue"))

        # Results
        res_list = result.get("results", [])
        formatted_table_str = self.format_results(res_list, title=f"Match Count: {result.get('count', 0)}")
        if formatted_table_str:
            self.console.print(formatted_table_str)

        # Insight
        if "insight" in result:
            self.console.print(Panel(Text(result["insight"], style="italic"), title="Detective Insight", border_style="magenta"))
        
        # Store query for export
        self.session_queries.append({
            'query': question,
            'results': res_list,
            'timestamp': datetime.now().isoformat()
        })

    def export_results(self, format: str = 'json', filename: str = None):
        """Export last query results."""
        import json, csv
        from pathlib import Path
        
        if not self.session_queries:
            self.console.print("[yellow]No queries to export[/yellow]")
            return
        
        last_query = self.session_queries[-1]
        results = last_query.get('results', [])
        
        if not results:
            self.console.print("[yellow]No results to export[/yellow]")
            return
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"export_{timestamp}"
        
        output_dir = Path.cwd() / "exports"
        output_dir.mkdir(exist_ok=True)
        
        if format == 'json':
            output_path = output_dir / f"{filename}.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            self.console.print(f"[green]✓ Exported to {output_path}[/green]")
        
        elif format == 'csv':
            output_path = output_dir / f"{filename}.csv"
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=results[0].keys())
                writer.writeheader()
                writer.writerows(results)
            self.console.print(f"[green]✓ Exported to {output_path}[/green]")
        
        else:
            self.console.print(f"[red]Unknown format: {format}[/red]")

    def save_session(self, filename: str = None):
        """Save complete session to JSON."""
        import json
        from pathlib import Path
        
        if not self.session_queries:
            self.console.print("[yellow]No queries to save[/yellow]")
            return
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"session_{timestamp}.json"
        
        output_dir = Path.cwd() / "exports"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / filename
        
        session_data = {
            'timestamp': datetime.now().isoformat(),
            'total_queries': len(self.session_queries),
            'queries': self.session_queries
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)
        
        self.console.print(f"[green]✓ Session saved to {output_path}[/green]")

    def generate_report(self, filename: str = None):
        """Generate Markdown investigation report."""
        from pathlib import Path
        
        if not self.session_queries:
            self.console.print("[yellow]No queries for report[/yellow]")
            return
        
        if not filename:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"report_{timestamp}.md"
        
        output_dir = Path.cwd() / "reports"
        output_dir.mkdir(exist_ok=True)
        output_path = output_dir / filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# 🛡️ Paladino Investigation Report\n\n")
            f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**Total Queries:** {len(self.session_queries)}\n\n")
            f.write("---\n\n")
            
            for i, query_data in enumerate(self.session_queries, 1):
                f.write(f"## Query {i}\n\n")
                f.write(f"```\n{query_data['query']}\n```\n\n")
                
                results = query_data.get('results', [])
                if results:
                    f.write(f"**Results:** {len(results)} rows\n\n")
                    if results:
                        headers = list(results[0].keys())
                        f.write("| " + " | ".join(headers) + " |\n")
                        f.write("| " + " | ".join(["---"] * len(headers)) + " |\n")
                        for row in results[:20]:
                            f.write("| " + " | ".join(str(v) for v in row.values()) + " |\n")
                        if len(results) > 20:
                            f.write(f"\n*... and {len(results) - 20} more rows*\n")
                f.write("\n")
        
        self.console.print(f"[green]✓ Report generated: {output_path}[/green]")
        self.console.print(f"[cyan]📄 Open with: code {output_path}[/cyan]")

    def run(self):
        """The core REPL loop."""
        # Session tracking for exports
        self.session_queries = []
        
        try:
            while True:
                user_input = self.console.input("\n[brand]PALADINO 🔍 > [/brand]").strip()

                if not user_input: continue

                cmd = user_input.lower()
                if cmd in ['exit', 'quit', 'q']:
                    self.console.print("[brand]Returning to Paladino Main Hub...[/brand]")
                    return
                elif cmd == 'stats': self.show_stats()
                elif cmd == 'templates': self.show_templates()
                elif cmd == 'clear': self.console.clear()
                elif cmd == 'help': self.show_help()
                elif cmd.startswith('.export'):
                    # Export last results
                    parts = user_input.split()
                    format = 'json'
                    filename = None
                    if len(parts) > 1:
                        format = parts[1].lower()
                    if len(parts) > 2:
                        filename = parts[2]
                    self.export_results(format, filename)
                elif cmd.startswith('.save'):
                    # Save session
                    filename = user_input.split()[1] if len(user_input.split()) > 1 else None
                    self.save_session(filename)
                elif cmd.startswith('.report'):
                    # Generate full report
                    filename = user_input.split()[1] if len(user_input.split()) > 1 else None
                    self.generate_report(filename)
                elif cmd.startswith('search '):
                    keyword = user_input[7:].strip()
                    if keyword:
                        with Status(f"Searching for '{keyword}'...", spinner="bouncingBall", console=self.console):
                            res = self.agent.thematic_search(keyword)
                            # Flatten 'data' for table display
                            flat_res = []
                            for r in res:
                                item = {"type": r['type'], "score": round(r['score'], 2)}
                                item.update(r['data'])
                                flat_res.append(item)
                            
                            formatted = self.format_results(flat_res, title=f"Thematic Search: {keyword}")
                            if formatted: self.console.print(formatted)
                            
                            # Store query for export
                            self.session_queries.append({
                                'query': f'search: {keyword}',
                                'results': flat_res,
                                'timestamp': datetime.now().isoformat()
                            })
                elif user_input.startswith('@'):
                    template_name = user_input[1:].strip()
                    if template_name in self.agent.templates.list_templates():
                        with Status(f"Executing {template_name}...", spinner="growVertical", console=self.console):
                            try:
                                res = self.agent.query(template_name, {}, limit=15)
                                formatted_table_str = self.format_results(res, title=f"Template: {template_name}")
                                if formatted_table_str: self.console.print(formatted_table_str)
                                
                                # Store query for export
                                self.session_queries.append({
                                    'query': f'template: {template_name}',
                                    'results': res,
                                    'timestamp': datetime.now().isoformat()
                                })
                            except Exception as e:
                                self.console.print(f"[error]Query Failed: {e}[/error]")
                    else:
                        self.console.print(f"[warning]Template '{template_name}' unknown.[/warning]")
                else:
                    self.process_query(user_input)
        except (KeyboardInterrupt, EOFError):
            self.console.print("\n[brand]Emergency exit sequence initiated.[/brand]")
        finally:
            if hasattr(self, 'driver'): self.driver.close()

    def show_help(self):
        """Show command summary table with examples."""
        # Commands table
        table = Table(title="Investigation Commands", box=box.ROUNDED, show_header=True, header_style="bold magenta")
        table.add_column("Command", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Example", style="dim")

        table.add_row("NL Question", "Ask in natural language", "'Show top 10 companies by tender wins'")
        table.add_row("search <key>", "Keyword search", "search scuola")
        table.add_row("@template", "Run template", "@top_vendors")
        table.add_row("stats", "Graph statistics", "stats")
        table.add_row("templates", "List templates", "templates")
        table.add_row("help", "Show this help", "help")
        table.add_row("clear", "Clear screen", "clear")
        table.add_row(".export", "Export results", ".export csv")
        table.add_row(".save", "Save session", ".save my_investigation")
        table.add_row(".report", "Generate report", ".report")
        table.add_row("exit/q", "Exit session", "q")

        self.console.print(table)
        
        # Example queries panel
        examples = Panel(
            "[bold yellow]📋 Example Queries to Try:[/bold yellow]\n\n"
            "[cyan]General:[/cyan]\n"
            "  • 'What is this graph about?'\n"
            "  • 'Show me PNRR funded projects'\n"
            "  • 'Which companies won the most tenders?'\n\n"
            "[cyan]Risk Analysis:[/cyan]\n"
            "  • 'Companies with high risk scores'\n"
            "  • 'Show me anomalies in Sicilia region'\n"
            "  • 'Single bidder trends for company XYZ'\n\n"
            "[cyan]Templates (use @):[/cyan]\n"
            "  • '@top_vendors' - Top companies by wins\n"
            "  • '@pnrr_projects' - PNRR fund analysis\n"
            "  • '@high_risk_companies' - Risk flag overview\n\n"
            "[dim]💡 Tip: Be specific! Include company names (CF), regions, or timeframes for better results.[/dim]",
            title="🚀 Quick Start Examples",
            border_style="green",
            box=box.SIMPLE
        )
        self.console.print(examples)
        self.console.print("\n[cyan]💡 Use .export csv to export results for Excel[/cyan]")
