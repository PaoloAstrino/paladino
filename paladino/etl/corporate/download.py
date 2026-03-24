"""
Corporate source discovery — find, validate, and document available data files.

This module never crashes. When a source is unavailable it prints a detailed,
human-friendly panel explaining where to obtain the data and continues with
whatever is available.

────────────────────────────────────────────────────────────────────────
SUPPORTED DATA SOURCES
────────────────────────────────────────────────────────────────────────

1. LOCAL CSV FILES  (free, no API key required)
   Drop *any* CSV into:  data/corporate/raw/
   The parser auto-detects column schemas across these known formats:

   a) Directors / board-member file
      Required columns (case-insensitive, underscores ignored):
        cf_azienda / company_cf / codice_fiscale_azienda
        cf_persona / person_cf / codice_fiscale_persona
        ruolo / role / carica
      Optional:
        cognome, nome, data_inizio, data_fine

   b) Shareholders file
      Required columns:
        cf_azionista / shareholder_cf / cf_socio
        cf_azienda / company_cf
        quota / percentuale / share
      Optional:
        data_rilevazione / data

   c) Generic Registro Imprese flat export
      The parser looks for any file containing BOTH a company-CF column
      AND a person-CF column together with a role/quota indicator.

2. ATOKA COMMERCIAL API  (paid)
   Set environment variable:  ATOKA_API_KEY=<your_key>
   The ETL will call the ATOKA REST API to enrich graph companies.
   Sign up at: https://atoka.io/it/prodotti/api/

3. INFOCAMERE / TELEMACO  (paid, IT only)
   Official Registro Imprese data provider.
   Download visure / elenchi from: https://www.telemaco.infocamere.it

4. OPEN CORPORATE DATA (free, limited)
   OpenCorporates REST API — set OPENCORPORATES_API_KEY env-var.
   Documentation: https://api.opencorporates.com/documentation/API-Reference

────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_console = Console()


# ─────────────────────────────────────────────────────────
# Data-classes
# ─────────────────────────────────────────────────────────


@dataclass
class SourceFile:
    """A single discovered CSV file with its detected schema type."""

    path: Path
    schema_type: str  # "directors" | "shareholders" | "generic" | "unknown"
    row_estimate: int = 0
    notes: str = ""


@dataclass
class DiscoveryResult:
    """Result of a discovery run — what was found and what was not."""

    local_files: list[SourceFile] = field(default_factory=list)
    atoka_active: bool = False
    opencorp_active: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def has_any_source(self) -> bool:
        return bool(self.local_files) or self.atoka_active or self.opencorp_active

    @property
    def total_rows(self) -> int:
        return sum(f.row_estimate for f in self.local_files)


# ─────────────────────────────────────────────────────────
# Column-name normalization helpers
# ─────────────────────────────────────────────────────────


def _norm(name: str) -> str:
    """Lower-case, strip spaces/underscores for fuzzy column matching."""
    return name.lower().replace(" ", "").replace("_", "").replace("-", "")


_COMPANY_CF_VARIANTS = {
    "cfazienda",
    "companycf",
    "codicefiscaleazienda",
    "cf",
    "aziendacf",
    "partitaiva",
    "piva",
    "vatnumber",
}
_PERSON_CF_VARIANTS = {
    "cfpersona",
    "personcf",
    "codicefiscalepersona",
    "cfamministratore",
    "cfdirettore",
    "cfsocio",
    "personalcf",
}
_SHAREHOLDERCF_VARIANTS = {
    "cfazionista",
    "shareholdercf",
    "cfsocio",
    "cfpartner",
} | _PERSON_CF_VARIANTS
_ROLE_VARIANTS = {"ruolo", "role", "carica", "incarico", "tipocarica"}
_QUOTA_VARIANTS = {"quota", "percentuale", "share", "ownership", "quotasociale"}


def _detect_schema(columns: list[str]) -> str:
    """Classify the file schema based on column names."""
    normed = {_norm(c) for c in columns}

    has_company_cf = bool(normed & _COMPANY_CF_VARIANTS)
    has_person_cf = bool(normed & _PERSON_CF_VARIANTS)
    has_shareholder = bool(normed & _SHAREHOLDERCF_VARIANTS)
    has_role = bool(normed & _ROLE_VARIANTS)
    has_quota = bool(normed & _QUOTA_VARIANTS)

    if has_company_cf and has_person_cf and has_role:
        return "directors"
    if has_company_cf and has_shareholder and has_quota:
        return "shareholders"
    if has_company_cf and (has_person_cf or has_shareholder):
        return "generic"
    return "unknown"


# ─────────────────────────────────────────────────────────
# Discovery class
# ─────────────────────────────────────────────────────────


class CorporateSourceDiscovery:
    """
    Scan for available corporate-structure data sources.

    Call :meth:`discover` to get a :class:`DiscoveryResult` and then call
    :meth:`print_summary` to display a human-readable status table on the
    console.  Both methods are safe to call with no data present.
    """

    # Where we look for user-provided CSV files
    LOCAL_RAW_DIRS: list[Path] = [
        Path("data/corporate/raw"),
        Path("data/registro_imprese"),
        Path("data/ownership"),
    ]

    def __init__(self, base_dir: Path | None = None) -> None:
        root = base_dir or Path.cwd()
        self._raw_dirs = [root / d for d in self.LOCAL_RAW_DIRS]

    # ── private helpers ──────────────────────────────────

    def _scan_local(self) -> list[SourceFile]:
        """Find all CSV files in the raw directories."""
        found: list[SourceFile] = []
        for raw_dir in self._raw_dirs:
            if not raw_dir.exists():
                continue
            for csv_path in raw_dir.glob("*.csv"):
                try:
                    with csv_path.open(encoding="utf-8-sig", errors="replace") as fh:
                        header = fh.readline().strip()
                        # Try both common delimiters
                        sep = ";" if header.count(";") > header.count(",") else ","
                        columns = [c.strip() for c in header.split(sep)]
                        schema = _detect_schema(columns)
                        # Rough row count
                        rows = sum(1 for _ in fh)
                    found.append(
                        SourceFile(
                            path=csv_path,
                            schema_type=schema,
                            row_estimate=rows,
                            notes=f"sep='{sep}', cols={len(columns)}",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Could not read {csv_path}: {exc}")
        return found

    def _check_apis(self) -> tuple[bool, bool]:
        atoka = bool(os.environ.get("ATOKA_API_KEY"))
        opencorp = bool(os.environ.get("OPENCORPORATES_API_KEY"))
        return atoka, opencorp

    # ── public API ───────────────────────────────────────

    def discover(self) -> DiscoveryResult:
        """Run discovery and return a :class:`DiscoveryResult`."""
        local = self._scan_local()
        atoka, opencorp = self._check_apis()

        result = DiscoveryResult(
            local_files=local,
            atoka_active=atoka,
            opencorp_active=opencorp,
        )

        # Warn about unknown-schema files so the user can fix column names
        for sf in local:
            if sf.schema_type == "unknown":
                result.warnings.append(
                    f"File '{sf.path.name}' has unrecognised columns — "
                    "it will be skipped. See download.py for required column names."
                )

        if not result.has_any_source:
            result.warnings.append("NO_SOURCES")

        return result

    def print_summary(self, result: DiscoveryResult) -> None:
        """Print a Rich status table to the console."""

        # ── source table ─────────────────────────────────
        tbl = Table(
            title="Corporate Structure Data Sources",
            box=box.ROUNDED,
            show_lines=True,
        )
        tbl.add_column("Source", style="cyan", no_wrap=True)
        tbl.add_column("Status", style="bold")
        tbl.add_column("Details")

        if result.local_files:
            for sf in result.local_files:
                status = (
                    "[green]FOUND[/green]"
                    if sf.schema_type != "unknown"
                    else "[yellow]SKIPPED[/yellow]"
                )
                tbl.add_row(
                    sf.path.name,
                    status,
                    f"type={sf.schema_type}  rows≈{sf.row_estimate:,}  {sf.notes}",
                )
        else:
            tbl.add_row(
                "Local CSV files",
                "[red]NOT FOUND[/red]",
                "No CSV files in data/corporate/raw/",
            )

        tbl.add_row(
            "ATOKA API",
            "[green]ACTIVE[/green]" if result.atoka_active else "[dim]not configured[/dim]",
            "Set ATOKA_API_KEY env-var to activate",
        )
        tbl.add_row(
            "OpenCorporates API",
            "[green]ACTIVE[/green]" if result.opencorp_active else "[dim]not configured[/dim]",
            "Set OPENCORPORATES_API_KEY env-var to activate",
        )

        _console.print(tbl)

        # ── fallback guidance when nothing is found ──────
        if not result.has_any_source or "NO_SOURCES" in result.warnings:
            _console.print(
                Panel(
                    _NO_SOURCE_GUIDANCE,
                    title="[bold yellow]ℹ️  No corporate data found — here's how to add it[/bold yellow]",
                    border_style="yellow",
                    expand=False,
                )
            )
        elif result.warnings:
            for w in result.warnings:
                if w != "NO_SOURCES":
                    _console.print(f"[yellow]⚠️  {w}[/yellow]")


# ─────────────────────────────────────────────────────────
# Fallback guidance text
# ─────────────────────────────────────────────────────────

_NO_SOURCE_GUIDANCE = """\
[bold]The Supply Chain ETL will run in skeleton mode[/bold] (0 persons, 0 edges)
until you provide at least one data source.

[cyan]── FREE OPTIONS ─────────────────────────────────────────────────────────[/cyan]

[bold]1. Drop your own CSV into:  data/corporate/raw/[/bold]
   The parser auto-detects two formats:

   [bold]Directors file[/bold] — must contain these columns (names are flexible):
     cf_azienda   : company Codice Fiscale
     cf_persona   : person Codice Fiscale
     ruolo        : role (e.g. "Amministratore Unico", "Presidente")
     cognome, nome, data_inizio, data_fine  [optional]

   [bold]Shareholders file[/bold] — must contain:
     cf_azionista : shareholder CF (person or company)
     cf_azienda   : owned company CF
     quota        : ownership percentage (0–100)
     data_rilevazione  [optional]

[bold]2. Export from your commercial visura provider[/bold]
   InfoCamere Telemaco:  https://www.telemaco.infocamere.it
   Save as CSV and drop into  data/corporate/raw/

[cyan]── PAID API OPTIONS ────────────────────────────────────────────────────[/cyan]

[bold]3. ATOKA API[/bold]   https://atoka.io/it/prodotti/api/
   export ATOKA_API_KEY=<your_key>
   Provides directors, shareholders, and financial data for IT companies.

[bold]4. OpenCorporates API[/bold]   https://opencorporates.com
   export OPENCORPORATES_API_KEY=<your_key>
   International company registry data, useful for multi-country analysis.

[cyan]── WHAT YOU GET ONCE DATA IS LOADED ────────────────────────────────────[/cyan]
  (:Person)-[:REPRESENTS]->(:Company)         board member links
  (:Person|:Company)-[:SHAREHOLDER_OF]->(:Company)  ownership chains
  (:Company)-[:SHARES_UBO]->(:Company)        pre-computed UBO convenience edges
  New fraud detectors:  board_overlap_collusion, carousel_fraud
  New GraphRAG queries: "Chi possiede X?", "Quali aziende condividono amministratori?"
"""
