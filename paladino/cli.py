"""
Paladino CLI Entry Point
Provides a unified interface for the Paladino ecosystem.
"""

import io
import subprocess
import sys
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

    if decision.route == "structured":
        message = (
            "[warning]Detected known structured source. Use dedicated ETL scripts instead "
            f"(hint: {decision.handler})[/warning]"
        )
        if decision.next_command:
            message += f"\n[info]Suggested script: {decision.next_command}[/info]"
        console.print(message)
        return

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


if __name__ == "__main__":
    main()
