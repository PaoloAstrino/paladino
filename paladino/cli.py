"""
Paladino CLI Entry Point
Provides a unified interface for the Paladino ecosystem.
"""

import io
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import requests

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from subprocess import CalledProcessError, TimeoutExpired

import click
import questionary
from rich import box
from rich.console import Console
from rich.panel import Panel

from paladino.constants import (
    CLI_TIMEOUT,
    DEFAULT_HOST,
    DEFAULT_PORT,
    ETL_SCRIPTS,
    PALADIN_ART,
    PALADINO_THEME,
)


class MenuChoice:
    """Enum-like class for menu choices to avoid magic strings."""

    INVESTIGATE = "Launch Investigator 🔍 (Detective Shell)"
    START_BACKEND = "Start Backend Engine ⚔️ (API Server)"
    STATS = "Strategic Stats 📊 (Graph Health)"
    MAINTENANCE = "Maintenance Tools ⚙️ (Data Pipelines)"
    LLM_SETUP = "LLM Configuration 🤖 (Ollama/API)"
    REFRESH = "Refresh Dashboard 🔄"
    EXIT = "Stand Down 🚪 (Exit)"


class MaintenanceChoice:
    """Enum-like class for maintenance menu choices."""

    ANAC_ETL = "Run ANAC ETL Pipeline"
    OPENCUP_ETL = "Run OpenCUP ETL Pipeline"
    ISTAT_ETL = "Run ISTAT ETL Pipeline"
    ENTITY_RESOLUTION = "Run Entity Resolution (LLM Judge)"
    GDS_ANALYTICS = "Run GDS Analytics (PageRank/Louvain)"
    FRAUD_DETECTION = "Run Fraud Pattern Detection 🔴"
    SUPPLY_CHAIN_ETL = "Run Supply Chain ETL 🔗"
    TEMPORAL_ANALYSIS = "Run Temporal Analysis 📈"
    CONFIDENCE_PROPAGATION = "Run Confidence Propagation Sweep 🛡️"
    TEMPORAL_ORACLE = "Run Temporal Oracle (Network Drift) 🔮"
    BACK = "Back to Strategic Hub 🔙"


console = Console(theme=PALADINO_THEME)
SCRIPT_DIR = Path(__file__).parent.parent / "scripts"


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.0", prog_name="Paladino")
@click.pass_context
def main(ctx: click.Context) -> None:
    """🛡️ Paladino: Italian Public Funds Knowledge Graph CLI.

    Entry point for the Paladino ecosystem. If no subcommand is specified,
    launches the interactive Strategic Hub menu. Otherwise, executes the
    specified subcommand.

    Args:
        ctx: Click context object
    """
    if ctx.invoked_subcommand is None:
        # Fast Lane: Launch Investigator first
        console.print(Panel(PALADIN_ART, border_style="magenta", box=box.DOUBLE, expand=False))

        console.print("[brand]DIRECT INVESTIGATION MODE ACTIVATED[/brand]")
        console.print(
            "[info]Opening the Detective Shell... (Type 'q' to return to Strategic Hub)[/info]\n"
        )

        ctx.invoke(investigate)

        # After investigation, enter the circular Hub
        show_master_menu(ctx, should_show_banner=True)


def show_master_menu(ctx: click.Context, should_show_banner: bool = True) -> None:
    """Display the Grand Master interactive menu in a loop.

    Args:
        ctx: Click context for invoking subcommands
        should_show_banner: If True, display the ASCII art banner before menu
    """
    while True:
        if should_show_banner:
            console.print(Panel(PALADIN_ART, border_style="magenta", box=box.DOUBLE, expand=False))

        console.print("[brand]PALADINO STRATEGIC HUB[/brand]")
        console.print("[info]Mode: Interactive Command & Control[/info]\n")

        choice = questionary.select(
            "What is your next move, Knight?",
            choices=[
                MenuChoice.INVESTIGATE,
                MenuChoice.START_BACKEND,
                MenuChoice.STATS,
                MenuChoice.MAINTENANCE,
                MenuChoice.LLM_SETUP,
                MenuChoice.REFRESH,
                MenuChoice.EXIT,
            ],
            style=questionary.Style(
                [
                    ("highlighted", "fg:#00ffff bold"),
                    ("pointer", "fg:#ff00ff bold"),
                    ("selected", "fg:#ff00ff"),
                ]
            ),
        ).ask()

        if choice is None:  # Handle Ctrl+C in menu
            break

        if choice == MenuChoice.INVESTIGATE:
            ctx.invoke(investigate)
            should_show_banner = True  # Redraw art after REPL session
        elif choice == MenuChoice.START_BACKEND:
            ctx.invoke(work, port=DEFAULT_PORT, host=DEFAULT_HOST, show_banner=True)
        elif choice == MenuChoice.STATS:
            ctx.invoke(stats)
            should_show_banner = False  # Don't redraw art for quick stats
        elif choice == MenuChoice.MAINTENANCE:
            show_maintenance_menu()
            should_show_banner = True
        elif choice == MenuChoice.LLM_SETUP:
            setup_llm_config()
            should_show_banner = True
        elif choice == MenuChoice.REFRESH:
            console.clear()
            should_show_banner = True
        elif choice == MenuChoice.EXIT:
            console.print(
                "[brand]Paladino standing down. System state preserved. Farewell, Knight.[/brand]"
            )
            sys.exit(0)


def show_maintenance_menu() -> None:
    """Display the maintenance sub-menu for ETL and analytics tasks."""
    while True:
        choice = questionary.select(
            "Maintenance Command Center:",
            choices=[
                MaintenanceChoice.ANAC_ETL,
                MaintenanceChoice.OPENCUP_ETL,
                MaintenanceChoice.ISTAT_ETL,
                MaintenanceChoice.ENTITY_RESOLUTION,
                MaintenanceChoice.GDS_ANALYTICS,
                MaintenanceChoice.FRAUD_DETECTION,
                MaintenanceChoice.SUPPLY_CHAIN_ETL,
                MaintenanceChoice.TEMPORAL_ANALYSIS,
                MaintenanceChoice.BACK,
            ],
        ).ask()

        if choice == MaintenanceChoice.BACK or choice is None:
            return

        if choice == MaintenanceChoice.CONFIDENCE_PROPAGATION:
            # Call the click command directly
            ctx.invoke(confidence_sweep_cmd)
            continue

        if choice == MaintenanceChoice.TEMPORAL_ORACLE:
            ctx.invoke(oracle_temporal_cmd)
            continue

        script_name = ETL_SCRIPTS.get(choice.split(" (")[0])  # Extract key from display text
        if script_name:
            script_path = SCRIPT_DIR / script_name
            _run_script(script_path, choice)


def _run_script(script_path: Path, task_name: str) -> None:
    """Run an ETL or analytics script with proper error handling.

    Args:
        script_path: Path to the script to execute
        task_name: Human-readable task name for status messages
    """
    if not script_path.exists():
        console.print(f"[error]Script not found: {script_path}[/error]")
        return

    console.print(f"[info]Executing {script_path.name}...[/info]")
    try:
        subprocess.run(
            [sys.executable, str(script_path)],
            check=True,
            timeout=CLI_TIMEOUT,
            capture_output=False,  # Stream output to terminal
        )
        console.print(f"\n[success]✅ Task {task_name} completed successfully.[/success]")
    except TimeoutExpired:
        console.print(f"[error]⏱️ Task timed out after {CLI_TIMEOUT}s[/error]")
    except CalledProcessError as e:
        console.print(f"[error]❌ Task failed with exit code {e.returncode}[/error]")
    except FileNotFoundError:
        console.print(f"[error]Python interpreter not found: {sys.executable}[/error]")
    except KeyboardInterrupt:
        console.print("[warning]Task interrupted by user.[/warning]")

    # Pause before returning to menu
    input("\nPress Enter to return to Maintenance...")


@main.command()
@click.option(
    "--port",
    default=DEFAULT_PORT,
    type=click.IntRange(1, 65535),
    help="Port to run the API server on.",
)
@click.option("--host", default=DEFAULT_HOST, type=str, help="Host to run the API server on.")
@click.option("--show-banner", is_flag=True, default=True, help="Show welcome banner on startup.")
def work(port: int, host: str, show_banner: bool = True) -> None:
    """⚔️ Start the Paladino ecosystem (API and system services).

    Args:
        port: Port to run the API server on (1-65535)
        host: Host to run the API server on
        show_banner: If False, skip welcome banner (used when called from menu)
    """
    if show_banner:
        from paladino.app.investigator import draw_paladin

        draw_paladin(console)
        console.print(Panel(PALADIN_ART, border_style="magenta", box=box.DOUBLE))

    console.print("[brand]Activating Paladino Engine...[/brand]")
    console.print("[info]Mode: Local-First / Single-User[/info]")
    console.print(f"[warning]API Endpoint: http://{host}:{port}[/warning]")
    console.print(f"[warning]Interactive Docs: http://{host}:{port}/docs[/warning]")
    console.print(
        "[success]Systems live. Press Ctrl+C to stop engine and return to hub.[/success]\n"
    )

    import uvicorn

    try:
        uvicorn.run("paladino.app.api:app", host=host, port=port, reload=False, log_level="error")
    except KeyboardInterrupt:
        pass  # Returning to menu handled by caller


@main.command()
def investigate() -> None:
    """🔍 Launch the Paladino Investigator REPL.

    Opens an interactive REPL for querying the knowledge graph using
    natural language or direct Cypher queries.
    """
    from paladino.app.investigator import InvestigativeREPL

    repl = None
    try:
        repl = InvestigativeREPL(console=console)
        repl.run()
    except KeyboardInterrupt:
        pass
    finally:
        if repl and hasattr(repl, "driver"):
            repl.driver.close()


@main.command()
def stats() -> None:
    """📊 Display real-time graph statistics.

    Shows node counts, relationship counts, and other graph health metrics
    without initializing the full REPL.
    """
    from rich.table import Table

    from paladino.db import get_driver

    console.print("[brand]Graph Statistics[/brand]\n")

    try:
        driver = get_driver()
        with driver.session() as session:
            # Node counts by label
            table = Table(title="Node Counts", show_header=True, header_style="bold magenta")
            table.add_column("Label", style="cyan")
            table.add_column("Count", style="green")

            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] as label, count(n) as count
                ORDER BY count DESC
            """)

            for record in result:
                table.add_row(record["label"] or "Unknown", str(record["count"]))

            console.print(table)

            # Relationship counts by type
            table = Table(
                title="Relationship Counts", show_header=True, header_style="bold magenta"
            )
            table.add_column("Type", style="cyan")
            table.add_column("Count", style="green")

            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) as type, count(r) as count
                ORDER BY count DESC
            """)

            for record in result:
                table.add_row(record["type"], str(record["count"]))

            console.print(table)

    except Exception as e:
        console.print(f"[error]Failed to retrieve stats: {e}[/error]")
        console.print("[info]Make sure Neo4j is running and configured correctly.[/info]")


def setup_llm_config() -> None:
    """Interactive LLM configuration wizard.

    Allows users to choose between:
    1. Ollama (local models) - selects from available models via `ollama list`
    2. External API (OpenAI/Groq/etc.) - configure API key and endpoint
    """
    from paladino.config import settings

    console.print(Panel("[brand]🤖 LLM Configuration Wizard[/brand]\n", border_style="cyan"))

    # Step 1: Choose provider
    provider = questionary.select(
        "Select LLM provider:",
        choices=[
            "Ollama (Local, Free)",
            "OpenRouter (Free & Paid Models)",
            "OpenAI API",
            "Groq API",
            "Anthropic API",
            "Custom OpenAI-compatible API",
        ],
        style=questionary.Style(
            [
                ("highlighted", "fg:#00ffff bold"),
                ("pointer", "fg:#ff00ff bold"),
            ]
        ),
    ).ask()

    if provider is None:
        console.print("[warning]Configuration cancelled.[/warning]")
        return

    env_path = Path(".env")
    env_content = ""

    # Read existing .env if it exists
    if env_path.exists():
        env_content = env_path.read_text(encoding="utf-8")

    if provider == "Ollama (Local, Free)":
        # Fetch available models
        console.print("[info]Fetching available Ollama models...[/info]")
        try:
            response = requests.get(f"{settings.ollama_base_url}/api/tags", timeout=10)
            response.raise_for_status()
            models_data = response.json()
            models = [m.get("name", "") for m in models_data.get("models", [])]

            if not models:
                console.print(
                    "[error]No Ollama models found. Run 'ollama pull llama3.2' first.[/error]"
                )
                return

            console.print(f"[success]Found {len(models)} model(s)[/success]")

            # Let user select model
            selected_model = questionary.select(
                "Select model to use:",
                choices=models,
                style=questionary.Style(
                    [
                        ("highlighted", "fg:#00ffff bold"),
                        ("pointer", "fg:#ff00ff bold"),
                    ]
                ),
            ).ask()

            if selected_model is None:
                return

            # Update .env
            env_lines = env_content.splitlines()
            new_env_lines = []

            for line in env_lines:
                if line.startswith("LLM_MODEL="):
                    new_env_lines.append(f'LLM_MODEL="{selected_model}"')
                elif line.startswith("LLM_API_KEY="):
                    new_env_lines.append('LLM_API_KEY=""')
                elif line.startswith("LLM_API_BASE="):
                    new_env_lines.append('LLM_API_BASE=""')
                elif line.startswith("OLLAMA_BASE_URL="):
                    new_env_lines.append(f'OLLAMA_BASE_URL="{settings.ollama_base_url}"')
                else:
                    new_env_lines.append(line)

            # Add missing lines
            if not any(line.startswith("LLM_MODEL=") for line in new_env_lines):
                new_env_lines.append(f'LLM_MODEL="{selected_model}"')
            if not any(line.startswith("OLLAMA_BASE_URL=") for line in new_env_lines):
                new_env_lines.append(f'OLLAMA_BASE_URL="{settings.ollama_base_url}"')

            env_path.write_text("\n".join(new_env_lines), encoding="utf-8")
            console.print(f"[success]✅ Ollama configured: {selected_model}[/success]")

        except requests.ConnectionError:
            console.print(
                "[error]❌ Cannot connect to Ollama. Is it running? (ollama serve)[/error]"
            )
            console.print("[info]Install: https://ollama.ai[/info]")
        except Exception as e:
            console.print(f"[error]Error: {e}[/error]")

    else:
        # External API configuration
        api_config = {
            "OpenRouter (Free & Paid Models)": {
                "base_url": "https://openrouter.ai/api/v1",
                "model_prompt": "Enter model name (e.g., meta-llama/llama-3.1-70b-instruct, mistralai/mistral-large, google/gemini-flash-1.5):",
                "key_name": "OPENROUTER_API_KEY",
                "env_key": "OPENROUTER_API_KEY",
            },
            "OpenAI API": {
                "base_url": "https://api.openai.com/v1",
                "model_prompt": "Enter model name (e.g., gpt-4o, gpt-3.5-turbo):",
                "key_name": "OPENAI_API_KEY",
                "env_key": "OPENAI_API_KEY",
            },
            "Groq API": {
                "base_url": "https://api.groq.com/openai/v1",
                "model_prompt": "Enter model name (e.g., llama-3.1-70b-versatile, mixtral-8x7b-32768):",
                "key_name": "GROQ_API_KEY",
                "env_key": "GROQ_API_KEY",
            },
            "Anthropic API": {
                "base_url": "https://api.anthropic.com/v1",
                "model_prompt": "Enter model name (e.g., claude-3-5-sonnet-20241022, claude-3-opus-20240229):",
                "key_name": "ANTHROPIC_API_KEY",
                "env_key": "ANTHROPIC_API_KEY",
            },
            "Custom OpenAI-compatible API": {
                "base_url": "",
                "model_prompt": "",
                "key_name": "",
                "env_key": "",
            },
        }

        config = api_config[provider]

        # Get custom base URL if needed
        if provider == "Custom OpenAI-compatible API":
            base_url = questionary.text(
                "Enter API base URL:",
                default="https://api.example.com/v1",
                style=questionary.Style(
                    [
                        ("highlighted", "fg:#00ffff bold"),
                    ]
                ),
            ).ask()
            if base_url is None:
                return
            config["base_url"] = base_url

            model = questionary.text(
                "Enter model name:",
                style=questionary.Style(
                    [
                        ("highlighted", "fg:#00ffff bold"),
                    ]
                ),
            ).ask()
            if model is None:
                return
        else:
            model = questionary.text(
                config["model_prompt"],
                style=questionary.Style(
                    [
                        ("highlighted", "fg:#00ffff bold"),
                    ]
                ),
            ).ask()
            if model is None:
                return

        # Get API key
        api_key = questionary.password(
            f"Enter {config['key_name']}:",
            style=questionary.Style(
                [
                    ("highlighted", "fg:#00ffff bold"),
                ]
            ),
        ).ask()
        if api_key is None:
            return

        # Update .env
        env_lines = [
            line
            for line in env_content.splitlines()
            if not any(
                skip in line
                for skip in [
                    "LLM_MODEL=",
                    "LLM_API_KEY=",
                    "LLM_API_BASE=",
                    "OPENAI_API_KEY=",
                    "OPENROUTER_API_KEY=",
                    "GROQ_API_KEY=",
                    "ANTHROPIC_API_KEY=",
                ]
            )
        ]

        env_lines.append(f'LLM_MODEL="{model}"')
        env_lines.append(f'LLM_API_BASE="{config["base_url"]}"')
        env_lines.append(f'LLM_API_KEY="{api_key}"')
        env_lines.append(f'{config["env_key"]}="{api_key}"')

        env_path.write_text("\n".join(env_lines), encoding="utf-8")
        console.print(f"[success]✅ {provider} configured: {model}[/success]")
        console.print("[info]Restart the application for changes to take effect.[/info]")


@main.command("configure-llm")
def configure_llm() -> None:
    """🤖 Launch interactive LLM configuration wizard.

    Choose between Ollama (local models) or external APIs (OpenAI, Groq, etc.)
    """
    setup_llm_config()


@main.command("load-samples")
def load_samples() -> None:
    """🧪 Load a small sample dataset (ANAC + OpenCUP) for testing."""
    import pandas as pd

    from paladino.etl.anac_loader import AnacLoader
    from paladino.etl.opencup_loader import OpenCupLoader

    anac_path = Path("data/samples/anac_sample.csv")
    opencup_path = Path("data/samples/opencup_sample.csv")

    if not anac_path.exists() or not opencup_path.exists():
        console.print("[error]Sample files not found in data/samples/[/error]")
        return

    console.print("[brand]Loading sample intelligence...[/brand]")

    # Load ANAC
    try:
        loader = AnacLoader()
        df_anac = pd.read_csv(anac_path)
        loader.load_batch(df_anac.to_dict("records"))
        console.print(f"[success]✓ Loaded {len(df_anac)} sample Tenders[/success]")
    except Exception as e:
        console.print(f"[error]ANAC load failed: {e}[/error]")

    # Load OpenCUP
    try:
        loader = OpenCupLoader()
        df_cup = pd.read_csv(opencup_path)
        loader.load_batch(df_cup.to_dict("records"))
        console.print(f"[success]✓ Loaded {len(df_cup)} sample Projects[/success]")
    except Exception as e:
        console.print(f"[error]OpenCUP load failed: {e}[/error]")

    console.print(
        "\n[success]Sample load complete. Launch 'paladino investigate' to explore.[/success]"
    )


@click.option(
    "--for",
    "target",
    default="all",
    type=click.Choice(["all", "schema", "ingest"], case_sensitive=False),
    help="Validation target: schema, ingest, or all.",
)
def preflight(target: str) -> None:
    """🧪 Validate environment prerequisites and system health."""
    from paladino.preflight import PreflightChecker

    checker = PreflightChecker(console=console)
    checker.run_all()


@main.command("ingest-unstructured")
@click.option("--source", required=True, type=str, help="Path or URL to ingest.")
@click.option(
    "--to-neo4j",
    is_flag=True,
    default=False,
    help="Load extracted entities into Neo4j.",
)
@click.option(
    "--resolve-connections",
    is_flag=True,
    default=False,
    help="Match extracted entities against existing Neo4j graph and discover connections.",
)
@click.option(
    "--max-chars",
    default=12000,
    type=click.IntRange(1, 200000),
    help="Maximum characters per LLM chunk.",
)
@click.option(
    "--chunk-overlap",
    default=400,
    type=click.IntRange(0, 50000),
    help="Chunk overlap in characters.",
)
def ingest_unstructured(
    source: str,
    to_neo4j: bool,
    resolve_connections: bool,
    max_chars: int,
    chunk_overlap: int,
) -> None:
    """📥 Ingest unstructured source (PDF/TXT/Web) into Paladino extraction pipeline."""
    if chunk_overlap >= max_chars:
        console.print("[error]--chunk-overlap must be smaller than --max-chars[/error]")
        raise click.Abort()

    from paladino.etl.universal_ingestor import UniversalIngestor

    ingestor = UniversalIngestor()
    decision = ingestor.route(source)

    console.print(
        f"[info]Routing decision:[/info] {decision.route} ({decision.reason}) -> {decision.handler}"
    )

    if decision.route == "structured" and decision.handler != "custom_csv_import":
        message = (
            "[warning]Detected known structured source. Use dedicated ETL scripts instead "
            f"(hint: {decision.handler})[/warning]"
        )
        if decision.next_command:
            message += f"\n[info]Suggested script: {decision.next_command}[/info]"
        console.print(message)
        return

    if resolve_connections:
        # Full pipeline: extract + resolve connections
        from paladino.etl.ner_pipeline import UnstructuredNERPipeline
        from paladino.llm_manager import LLMManager

        console.print("[info]Extracting and resolving connections…[/info]")
        llm = LLMManager()
        ner_pipeline = UnstructuredNERPipeline(
            llm_manager=llm,
            max_chars_per_chunk=max_chars,
            chunk_overlap=chunk_overlap,
        )
        report = ingestor.ingest_with_connections(
            source=source,
            ner_pipeline=ner_pipeline,
            llm_manager=llm,
        )

        console.print(f"[success]Extracted {report.entities_extracted} entities[/success]")
        console.print(f"[success]Matched {report.entities_matched} to existing graph[/success]")
        console.print(f"[success]Created {report.entities_created} new nodes[/success]")
        console.print(f"[success]Resolved {report.relationships_created} relationships[/success]")
        console.print(f"[success]Found {report.implicit_connections_found} implicit connections[/success]")

        if report.entity_matches:
            console.print("\n[info]Entity Matches:[/info]")
            for match in report.entity_matches:
                status = f"→ matched [{match.matched_neo4j_label}] ({match.match_method}, {match.confidence:.2f})" if match.matched_neo4j_id else "→ CREATED NEW"
                console.print(f"  {match.extracted_entity_type} '{match.extracted_entity_id}' {status}")

        if report.discovered_paths:
            console.print("\n[info]Discovered Paths:[/info]")
            for path in report.discovered_paths:
                console.print(f"  {path.from_entity} ↔ {path.to_entity} via {', '.join(path.via)} (length {path.path_length})")

        if report.implicit_connections:
            console.print("\n[info]Implicit Connections:[/info]")
            for conn in report.implicit_connections:
                console.print(f"  {conn.entity_a} ↔ {conn.entity_b} [{conn.discovery_type}] {conn.description}")

        if report.warnings:
            console.print("\n[warning]Warnings:[/warning]")
            for w in report.warnings:
                console.print(f"  ⚠ {w}")

        if to_neo4j:
            console.print("[info]Nodes already written to Neo4j via connection resolver.[/info]")
    else:
        # Extract only
        document = ingestor.ingest(source)
        console.print(
            f"[success]Extracted content from {document.source_type}: {document.source}[/success]"
        )

        from paladino.etl.ner_pipeline import UnstructuredNERPipeline

        pipeline = UnstructuredNERPipeline(
            max_chars_per_chunk=max_chars,
            chunk_overlap=chunk_overlap,
        )
        ner_result = pipeline.extract(document)

        console.print_json(data=ner_result.model_dump())

        if to_neo4j:
            from paladino.etl.unstructured_loader import UnstructuredGraphLoader

            loader = UnstructuredGraphLoader()
            stats = loader.load(document, ner_result)
            console.print(f"[success]Loaded to Neo4j: {stats}[/success]")


@main.command("notebook")
@click.option(
    "--from-ingestion",
    "report_file",
    type=str,
    default=None,
    help="Path to a ConnectionReport JSON file to create a notebook from.",
)
@click.option(
    "--from-alert",
    "alert_id",
    type=str,
    default=None,
    help="Alert ID to create a notebook from.",
)
@click.option("--title", type=str, default=None, help="Notebook title (auto-generated if omitted).")
@click.option("--entity-id", "-e", multiple=True, help="Entity IDs to link (CF, CIG, CUP, etc.).")
@click.option("--author", type=str, default="user", help="Notebook author.")
@click.option("--list-notebooks", is_flag=True, help="List existing notebooks.")
def notebook_cmd(
    report_file: str | None,
    alert_id: str | None,
    title: str | None,
    entity_id: tuple[str, ...],
    author: str,
    list_notebooks: bool,
) -> None:
    """📓 Investigation notebook management.

    Create a notebook from a connection discovery report:

        paladino notebook --from-ingestion report.json -e MRARSS80A01H501Z

    Create a notebook from an alert:

        paladino notebook --from-alert <alert-uuid>

    List all notebooks:

        paladino notebook --list
    """
    if list_notebooks:
        from paladino.db import Neo4jConnection
        from paladino.app.notebook_service import NotebookService

        conn = Neo4jConnection()
        service = NotebookService(conn)
        notebooks, total = service.list_notebooks(
            __import__("paladino.models", fromlist=["NotebookListParams"]).models.NotebookListParams()
        )

        if not notebooks:
            console.print("[info]No notebooks found.[/info]")
            return

        console.print(f"\n[info]Notebooks ({total}):[/info]\n")
        for nb in notebooks:
            console.print(f"  [bold]{nb.title}[/bold] [{nb.status}] (id: {nb.id[:8]}...)")
            console.print(f"    Author: {nb.author} | Created: {nb.created_at}")
            if nb.linked_entity_ids:
                console.print(f"    Entities: {', '.join(nb.linked_entity_ids[:5])}")
            console.print()
        return

    if alert_id:
        from paladino.db import Neo4jConnection
        from paladino.app.notebook_service import NotebookService
        from paladino.app.alert_service import AlertService
        from paladino.models import (
            NotebookCreate,
            NotebookCellCreate,
            NotebookCellType,
        )

        conn = Neo4jConnection()
        service = NotebookService(conn)
        alert_service = AlertService(conn)

        alert = alert_service.get_alert(alert_id)
        if not alert:
            console.print(f"[error]Alert not found: {alert_id}[/error]")
            conn.close()
            raise click.Abort()

        nb_title = title or f"Investigation: {alert.title}"

        console.print(f"[info]Creating notebook from alert: {alert.title} [{alert.severity.value}][/info]")

        entity_ids = [alert.entity_id] if alert.entity_id else list(entity_id)

        nb_resp = service.create_notebook(
            NotebookCreate(
                title=nb_title,
                description=f"Created from alert: {alert.title} [{alert.severity.value}]",
                linked_entity_ids=entity_ids,
                linked_alert_ids=[alert_id],
                tags=["from-alert", alert.type.value, alert.severity.value],
                author=author,
            )
        )

        # Build cells
        cells = [
            NotebookCellCreate(
                cell_type=NotebookCellType.MARKDOWN,
                content=(
                    f"## Alert Details\n\n"
                    f"**Type:** `{alert.type.value}`\n\n"
                    f"**Severity:** `{alert.severity.value}`\n\n"
                    f"**Description:** {alert.description}\n\n"
                    f"**Entity:** {alert.entity_type} ({alert.entity_id or 'N/A'})\n\n"
                    f"**Triggered by:** {alert.triggered_by or 'system'}"
                ),
                position=0,
                title="Alert Details",
            ),
        ]

        if alert.entity_id:
            cells.append(
                NotebookCellCreate(
                    cell_type=NotebookCellType.CYPHER_QUERY,
                    content=f"MATCH (n {{id: $entity_id}})\nRETURN labels(n) AS type, properties(n) AS details",
                    position=1,
                    title="Entity Details",
                    linked_entity_id=alert.entity_id,
                ),
            )
            cells.append(
                NotebookCellCreate(
                    cell_type=NotebookCellType.CONNECTION_INSIGHT,
                    content=f"Auto-discover implicit connections for {alert.entity_type}: {alert.entity_id}.",
                    position=2,
                    title="Discovered Connections",
                    linked_entity_id=alert.entity_id,
                ),
            )

        if alert.type.value == "fraud_pattern" and alert.entity_id:
            cells.append(
                NotebookCellCreate(
                    cell_type=NotebookCellType.CYPHER_QUERY,
                    content=(
                        f"MATCH (n {{id: '{alert.entity_id}'}})-[:FLAGGED_BY]->(fp:FraudPattern)\n"
                        f"RETURN fp.pattern_name, fp.severity, fp.description, fp.detected_at\n"
                        f"ORDER BY fp.detected_at DESC"
                    ),
                    position=len(cells),
                    title="Fraud Patterns",
                    linked_entity_id=alert.entity_id,
                ),
            )

        cells.append(
            NotebookCellCreate(
                cell_type=NotebookCellType.MARKDOWN,
                content="## Findings\n\nDocument investigation findings and conclusions here.",
                position=len(cells),
                title="Findings",
            ),
        )

        for cell_data in cells:
            service.add_cell(nb_resp.id, cell_data)

        console.print(f"[success]Notebook created: {nb_resp.id[:8]}...[/success]")
        console.print(f"[success]Title: {nb_resp.title}[/success]")
        console.print(f"[success]Cells: {len(cells)} (alert details, entity, connections, findings)[/success]")

        conn.close()
        return

    if not report_file:
        console.print("[info]Use --from-ingestion or --from-alert to create a notebook, or --list to browse existing.[/info]")
        return

    import json
    from pathlib import Path

    report_path = Path(report_file)
    if not report_path.exists():
        console.print(f"[error]Report file not found: {report_file}[/error]")
        raise click.Abort()

    try:
        report_data = json.loads(report_path.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[error]Invalid JSON in report: {e}[/error]")
        raise click.Abort()

    from paladino.db import Neo4jConnection
    from paladino.app.notebook_service import NotebookService
    from paladino.models import (
        NotebookCreate,
        NotebookCellCreate,
        NotebookCellType,
    )

    conn = Neo4jConnection()
    service = NotebookService(conn)

    nb_title = title or f"Investigation: {report_path.name}"
    entities = list(entity_id) if entity_id else []

    console.print(f"[info]Creating notebook: {nb_title}[/info]")

    # Create notebook
    nb_resp = service.create_notebook(
        NotebookCreate(
            title=nb_title,
            description=f"Created from ingestion report: {report_path.name}",
            linked_entity_ids=entities,
            tags=["from-ingestion", report_path.name],
            author=author,
        )
    )

    # Add cells
    cells = [
        NotebookCellCreate(
            cell_type=NotebookCellType.MARKDOWN,
            content=f"## Ingestion Summary\n\n**Source:** `{report_path.name}`\n\n"
                    f"- Entities extracted: {report_data.get('entities_extracted', 0)}\n"
                    f"- Matched to graph: {report_data.get('entities_matched', 0)}\n"
                    f"- Created new: {report_data.get('entities_created', 0)}\n"
                    f"- Relationships resolved: {report_data.get('relationships_created', 0)}\n"
                    f"- Implicit connections: {report_data.get('implicit_connections_found', 0)}",
            position=0,
            title="Overview",
        ),
        NotebookCellCreate(
            cell_type=NotebookCellType.CYPHER_QUERY,
            content=f"MATCH (n)\nWHERE '{report_path.name}' IN coalesce(n.source, [])\nRETURN labels(n) AS type, count(n) AS count\nORDER BY count DESC",
            position=1,
            title="Entities from Source",
        ),
    ]

    if entities:
        cells.append(
            NotebookCellCreate(
                cell_type=NotebookCellType.CONNECTION_INSIGHT,
                content=f"Auto-discover implicit connections between linked entities.",
                position=2,
                title="Discovered Connections",
                linked_entity_id=entities[0],
            ),
        )

    cells.append(
        NotebookCellCreate(
            cell_type=NotebookCellType.MARKDOWN,
            content="## Findings\n\nDocument key findings and conclusions here.",
            position=3,
            title="Findings",
        ),
    )

    for cell_data in cells:
        service.add_cell(nb_resp.id, cell_data)

    console.print(f"[success]Notebook created: {nb_resp.id[:8]}...[/success]")
    console.print(f"[success]Title: {nb_resp.title}[/success]")
    console.print(f"[success]Cells: {len(cells)} (overview, entities, connections, findings)[/success]")

    if report_data.get("implicit_connections"):
        console.print(f"\n[info]Implicit Connections ({len(report_data['implicit_connections'])}):[/info]")
        for conn in report_data["implicit_connections"]:
            console.print(f"  {conn['entity_a']} ↔ {conn['entity_b']} [{conn['discovery_type']}]")

    if report_data.get("entity_matches"):
        matched = [m for m in report_data["entity_matches"] if m.get("matched_neo4j_id")]
        created = [m for m in report_data["entity_matches"] if not m.get("matched_neo4j_id")]
        console.print(f"\n[info]Entity Matches: {len(matched)} matched, {len(created)} new[/info]")
        for m in matched[:10]:
            console.print(f"  {m['extracted_entity_type']} → {m['matched_neo4j_label']} ({m['match_method']}, conf={m['confidence']:.2f})")


@main.command("alerts")
@click.option("--pending", is_flag=True, help="Show only pending alerts.")
@click.option("--severity", type=str, default=None, help="Filter by severity (critical, high, medium, low, info).")
@click.option("--limit", type=int, default=20, help="Maximum alerts to show.")
@click.option("--dismiss", type=str, default=None, help="Dismiss alert by ID.")
@click.option("--acknowledge", type=str, default=None, help="Acknowledge alert by ID.")
@click.option("--run-generators", is_flag=True, help="Run all alert generators (fraud detection, risk analysis).")
@click.option("--watch", is_flag=True, help="Watch mode: run generators every 5 minutes and notify on new alerts.")
def alerts_cmd(
    pending: bool,
    severity: str | None,
    limit: int,
    dismiss: str | None,
    acknowledge: str | None,
    run_generators: bool,
    watch: bool,
) -> None:
    """🔔 Alert management — view, dismiss, and run fraud detection generators."""
    from paladino.db import Neo4jConnection
    from paladino.app.alert_service import AlertService
    from paladino.app.notification_dispatcher import NotificationDispatcher
    from paladino.models import AlertListParams, AlertStatus, AlertUpdate

    conn = Neo4jConnection()
    service = AlertService(conn)

    # Dismiss alert
    if dismiss:
        service.update_alert(dismiss, AlertUpdate(status=AlertStatus.DISMISSED))
        console.print(f"[success]Alert {dismiss[:8]}... dismissed.[/success]")
        conn.close()
        return

    # Acknowledge alert
    if acknowledge:
        service.update_alert(acknowledge, AlertUpdate(status=AlertStatus.ACKNOWLEDGED))
        console.print(f"[success]Alert {acknowledge[:8]}... acknowledged.[/success]")
        conn.close()
        return

    # Run generators
    if run_generators:
        console.print("[info]Running all alert generators…[/info]")
        report = service.run_all_generators()
        console.print(f"[success]Generators complete.[/success]")
        console.print(f"  Alerts created: {report.alerts_created}")
        console.print(f"  Patterns checked: {report.patterns_checked}")

        # Dispatch new alerts
        if report.alerts_created > 0:
            dispatcher = NotificationDispatcher()
            # Re-fetch pending alerts to dispatch
            new_alerts, _ = service.list_alerts(AlertListParams(status=AlertStatus.PENDING, limit=report.alerts_created))
            for alert in new_alerts:
                results = dispatcher.dispatch(alert)
                channels = [ch for ch, ok in results.items() if ok]
                emoji = "🚨" if alert.severity.value in ("critical", "high") else "📋"
                console.print(f"  {emoji} [{alert.severity.value}] {alert.title} → {', '.join(channels)}")

        conn.close()
        return

    # Watch mode
    if watch:
        import time as _time
        console.print("[info]Watch mode: checking every 5 minutes. Press Ctrl+C to stop.[/info]")
        try:
            while True:
                console.print(f"\n[dim]Checking alerts at {datetime.now().strftime('%H:%M:%S')}…[/dim]")
                report = service.run_all_generators()
                if report.alerts_created > 0:
                    dispatcher = NotificationDispatcher()
                    new_alerts, _ = service.list_alerts(AlertListParams(status=AlertStatus.PENDING, limit=report.alerts_created))
                    for alert in new_alerts:
                        results = dispatcher.dispatch(alert)
                        channels = [ch for ch, ok in results.items() if ok]
                        emoji = "🚨" if alert.severity.value in ("critical", "high") else "📋"
                        console.print(f"  {emoji} [{alert.severity.value}] {alert.title} → {', '.join(channels)}")
                else:
                    console.print("  [dim]No new alerts.[/dim]")
                _time.sleep(300)  # 5 minutes
        except KeyboardInterrupt:
            console.print("\n[info]Watch mode stopped.[/info]")
        conn.close()
        return

    # Default: list alerts
    status_filter = AlertStatus.PENDING if pending else None
    params = AlertListParams(status=status_filter, limit=limit)

    alerts_list, total = service.list_alerts(params)

    if not alerts_list:
        console.print("[info]No alerts found.[/info]")
        conn.close()
        return

    console.print(f"\n[info]Alerts ({total} total, showing {len(alerts_list)}):[/info]\n")
    for alert in alerts_list:
        emoji = {"critical": "🚨", "high": "⚠️", "medium": "🔶", "low": "🔵", "info": "ℹ️"}.get(
            alert.severity.value, "📋"
        )
        status_icon = {"pending": "⏳", "acknowledged": "👁️", "resolved": "✅", "dismissed": "❌"}.get(
            alert.status.value, "?"
        )
        console.print(
            f"  {status_icon} {emoji} [{alert.severity.value}] {alert.title} "
            f"[dim]({alert.id[:8]}… | {alert.entity_type}: {alert.entity_id or 'N/A'})[/dim]"
        )

    console.print(f"\n[dim]Dismiss: paladino alerts --dismiss <id>[/dim]")
    console.print(f"[dim]Acknowledge: paladino alerts --acknowledge <id>[/dim]")
    console.print(f"[dim]Run generators: paladino alerts --run-generators[/dim]")
    console.print(f"[dim]Watch mode: paladino alerts --watch[/dim]")

    conn.close()


@main.command("confidence-sweep")
@click.option("--passes", default=3, help="Number of propagation passes")
def confidence_sweep_cmd(passes: int) -> None:
    """🛡️ Run Trust Model propagation sweep."""
    console.print(Panel("🛡️ Running Confidence Propagation Sweep...", border_style="cyan"))
    
    from paladino.db import Neo4jConnection
    from paladino.analytics.confidence_engine import ConfidencePropagator
    
    try:
        conn = Neo4jConnection()
        propagator = ConfidencePropagator(conn)
        propagator.initialize_derived_scores()
        propagator.run_propagation_sweep(max_passes=passes)
        stats = propagator.get_confidence_stats()
        
        from rich.table import Table
        table = Table(title="Confidence Distribution")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Total Entities", str(stats.get('total')))
        table.add_row("Average Trust", f"{stats.get('average', 0):.4f}")
        table.add_row("High Trust (>= 0.95)", str(stats.get('high_trust')))
        table.add_row("Low Trust (< 0.75)", str(stats.get('low_trust')))
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]Sweep failed: {e}[/red]")
    finally:
        if 'conn' in locals():
            conn.close()


@main.command("oracle-temporal")
def oracle_temporal_cmd() -> None:
    """🔮 Run Temporal Oracle to detect significant network drift."""
    console.print(Panel("🔮 Running Temporal Oracle Scan...", border_style="magenta"))
    
    from paladino.db import Neo4jConnection
    from paladino.analytics.temporal_oracle import TemporalOracle
    
    try:
        conn = Neo4jConnection()
        oracle = TemporalOracle(conn)
        oracle.run_full_scan()
        console.print("[success]✅ Temporal Oracle scan completed. Check the graph for new TemporalAlert nodes.[/success]")
    except Exception as e:
        console.print(f"[error]Oracle failed: {e}[/error]")
    finally:
        if 'conn' in locals():
            conn.close()


if __name__ == "__main__":
    main()
