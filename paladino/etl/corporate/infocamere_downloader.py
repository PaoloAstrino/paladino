"""
Infocamere / Registro Imprese OpenData downloader.

Fetches Italian company director and shareholding data from free public
sources and (optionally) the ATOKA commercial API, then writes the raw
CSVs into ``data/corporate/raw/`` so the existing ``CorporateTransformer``
can pick them up on the next ETL run.

Supported sources (tried in order, all gracefully skipped when unavailable):
──────────────────────────────────────────────────────────────────────────────
1. ANAC / ANAI OpenData catalogue   (free, no auth required)
   Endpoint: https://dati.anticorruzione.it/opendata
   Contains: procurement subjects, directors of winning companies, PNRR data.

2. Local mirror / pre-downloaded files   (zero network calls)
   Place any CSV that matches the corporate schema in  data/corporate/raw/
   and this module will detect and stage it automatically.

3. ATOKA API   (paid, requires ATOKA_API_KEY env-var)
   https://atoka.io/it/prodotti/api/
   Provides verified director and shareholder data for Italian companies.

4. OpenCorporates API   (limited free tier, requires OPENCORPORATES_API_KEY)
   https://opencorporates.com
   International company registry.

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.etl.corporate.infocamere_downloader import RegistroImpreseFetcher

    fetcher = RegistroImpreseFetcher(data_dir=Path("data"))
    result  = fetcher.fetch_all()
    fetcher.print_summary(result)

Or via the CLI::

    python scripts/run_supply_chain_etl.py --step fetch-corporate-data
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import json

from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich import box

_console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# Data-classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DownloadResult:
    """Outcome of a single download attempt."""
    source:       str
    success:      bool
    file_path:    Optional[Path] = None
    rows_written: int = 0
    error:        Optional[str] = None
    skipped:      bool = False
    skip_reason:  Optional[str] = None


@dataclass
class FetchSummary:
    """Aggregated summary of a full fetch run."""
    downloads:      List[DownloadResult] = field(default_factory=list)
    started_at:     Optional[datetime] = None
    finished_at:    Optional[datetime] = None

    @property
    def successful(self) -> List[DownloadResult]:
        return [d for d in self.downloads if d.success]

    @property
    def failed(self) -> List[DownloadResult]:
        return [d for d in self.downloads if not d.success and not d.skipped]

    @property
    def total_rows(self) -> int:
        return sum(d.rows_written for d in self.downloads)

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ANAC OpenData helpers
# ─────────────────────────────────────────────────────────────────────────────

# ANAC dataset catalogue — we look for datasets related to company subjects
_ANAC_CATALOGUE_URL = "https://dati.anticorruzione.it/opendata/api/3/action/package_list"
_ANAC_DATASET_BASE  = "https://dati.anticorruzione.it/opendata/api/3/action/package_show?id="

# Names/keywords that identify procurement-subject datasets
_SUBJECT_KEYWORDS = [
    "soggetti", "aggiudicatari", "imprese", "operatori_economici",
    "subappaltatori", "partecipanti",
]

_REQUEST_TIMEOUT_SEC = 30
_RETRY_ATTEMPTS = 3
_RETRY_DELAY_SEC = 5


def _http_get(url: str, timeout: int = _REQUEST_TIMEOUT_SEC) -> Optional[bytes]:
    """Attempt a GET request; return bytes or None on failure."""
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            req = Request(url, headers={"User-Agent": "paladino/1.0 (Italian public spending analysis)"})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except HTTPError as exc:
            logger.warning(f"HTTP {exc.code} fetching {url} (attempt {attempt})")
        except URLError as exc:
            logger.warning(f"URL error fetching {url}: {exc.reason} (attempt {attempt})")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Unexpected error fetching {url}: {exc} (attempt {attempt})")
        if attempt < _RETRY_ATTEMPTS:
            time.sleep(_RETRY_DELAY_SEC)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main fetcher
# ─────────────────────────────────────────────────────────────────────────────

class RegistroImpreseFetcher:
    """
    Download and stage Registro Imprese / corporate-structure data.

    All methods degrade gracefully — network failures and missing API keys
    produce informative skipped/error entries rather than exceptions.

    Parameters
    ----------
    data_dir:
        Project root data directory (e.g. ``Path("data")``).
        Downloaded files land in ``data_dir / "corporate" / "raw"``.
    dry_run:
        When True, print what would be downloaded but skip all writes.
    """

    def __init__(
        self,
        data_dir: Path,
        dry_run: bool = False,
    ) -> None:
        self.data_dir  = data_dir
        self.raw_dir   = data_dir / "corporate" / "raw"
        self.dry_run   = dry_run
        self._atoka_key     = os.environ.get("ATOKA_API_KEY", "")
        self._opencorp_key  = os.environ.get("OPENCORPORATES_API_KEY", "")

    # ── public API ───────────────────────────────────────────────────────────

    def fetch_all(self) -> FetchSummary:
        """
        Run all configured fetchers in sequence and return a summary.

        Order: ANAC OpenData → ATOKA (if key) → OpenCorporates (if key).
        Local CSVs already in raw_dir are detected by discovery, not here.
        """
        summary = FetchSummary(started_at=datetime.now(timezone.utc))

        if not self.dry_run:
            self.raw_dir.mkdir(parents=True, exist_ok=True)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=_console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Fetching corporate data…", total=3)

            # 1. ANAC OpenData
            progress.update(task, description="[cyan]Fetching ANAC OpenData subjects…")
            summary.downloads.extend(self._fetch_anac_subjects())
            progress.advance(task)

            # 2. ATOKA API
            progress.update(task, description="[cyan]Checking ATOKA API…")
            summary.downloads.append(self._fetch_atoka())
            progress.advance(task)

            # 3. OpenCorporates
            progress.update(task, description="[cyan]Checking OpenCorporates API…")
            summary.downloads.append(self._fetch_opencorporates())
            progress.advance(task)

        summary.finished_at = datetime.now(timezone.utc)
        return summary

    def print_summary(self, summary: FetchSummary) -> None:
        """Display a rich table of fetch results."""
        tbl = Table(title="Registro Imprese / Corporate Data Fetch", box=box.ROUNDED, show_lines=True)
        tbl.add_column("Source",       style="cyan")
        tbl.add_column("Status",       style="bold")
        tbl.add_column("Rows",         justify="right")
        tbl.add_column("File / Notes")

        for r in summary.downloads:
            if r.skipped:
                status = "[dim]SKIPPED[/dim]"
                note   = r.skip_reason or ""
            elif r.success:
                status = "[green]OK[/green]"
                note   = str(r.file_path.name) if r.file_path else ""
            else:
                status = "[red]FAILED[/red]"
                note   = r.error or ""
            tbl.add_row(r.source, status, str(r.rows_written), note)

        _console.print(tbl)
        _console.print(
            f"[dim]Total rows staged: {summary.total_rows:,}  |  "
            f"Elapsed: {summary.elapsed_seconds:.1f}s[/dim]"
        )

        if not summary.successful:
            _console.print(Panel(
                _NO_DATA_GUIDANCE,
                title="[bold yellow]No data fetched — manual setup required[/bold yellow]",
                border_style="yellow",
                expand=False,
            ))

    # ── ANAC OpenData ─────────────────────────────────────────────────────────

    def _fetch_anac_subjects(self) -> List[DownloadResult]:
        """
        Query the ANAC CKAN catalogue for subject/company datasets and
        download matching CSVs into raw_dir.

        Returns one DownloadResult per file attempted.
        """
        results: List[DownloadResult] = []

        logger.info("[fetch] Querying ANAC catalogue…")
        raw = _http_get(_ANAC_CATALOGUE_URL)
        if raw is None:
            return [DownloadResult(
                source="ANAC OpenData",
                success=False,
                error="Cannot reach dati.anticorruzione.it — check your internet connection",
            )]

        try:
            catalogue = json.loads(raw)
            dataset_ids: List[str] = catalogue.get("result", [])
        except (json.JSONDecodeError, KeyError) as exc:
            return [DownloadResult(source="ANAC OpenData", success=False, error=str(exc))]

        # Filter by subject-related keywords
        matching = [
            name for name in dataset_ids
            if any(kw in name.lower() for kw in _SUBJECT_KEYWORDS)
        ]
        logger.info(f"[fetch] ANAC catalogue: {len(dataset_ids)} datasets, {len(matching)} matching")

        if not matching:
            return [DownloadResult(
                source="ANAC OpenData",
                success=False,
                skipped=True,
                skip_reason="No matching subject datasets in catalogue",
            )]

        for dataset_id in matching[:5]:  # limit to avoid hammering the API
            result = self._download_anac_dataset(dataset_id)
            results.append(result)

        return results

    def _download_anac_dataset(self, dataset_id: str) -> DownloadResult:
        """Fetch metadata for one ANAC dataset and download its CSV resource."""
        meta_url = _ANAC_DATASET_BASE + dataset_id
        raw = _http_get(meta_url)
        if raw is None:
            return DownloadResult(
                source=f"ANAC/{dataset_id}",
                success=False,
                error="Failed to fetch dataset metadata",
            )

        try:
            meta = json.loads(raw)
            resources = meta.get("result", {}).get("resources", [])
        except (json.JSONDecodeError, KeyError) as exc:
            return DownloadResult(source=f"ANAC/{dataset_id}", success=False, error=str(exc))

        # Find CSV resource
        csv_resource = next(
            (r for r in resources if r.get("format", "").upper() in ("CSV", "TEXT/CSV")),
            None,
        )
        if not csv_resource:
            return DownloadResult(
                source=f"ANAC/{dataset_id}",
                success=False,
                skipped=True,
                skip_reason="No CSV resource in dataset",
            )

        url      = csv_resource["url"]
        filename = Path(url).name or f"{dataset_id}.csv"
        dest     = self.raw_dir / filename

        # Skip if already up-to-date (same-day download)
        if dest.exists():
            mtime = datetime.fromtimestamp(dest.stat().st_mtime, tz=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - mtime).total_seconds() / 3600
            if age_hours < 24:
                return DownloadResult(
                    source=f"ANAC/{dataset_id}",
                    success=True,
                    file_path=dest,
                    skipped=True,
                    skip_reason=f"Up-to-date (downloaded {age_hours:.0f}h ago)",
                )

        logger.info(f"[fetch] Downloading {url} → {dest.name}")
        if self.dry_run:
            return DownloadResult(
                source=f"ANAC/{dataset_id}",
                success=True,
                file_path=dest,
                skipped=True,
                skip_reason="dry-run",
            )

        data = _http_get(url)
        if data is None:
            return DownloadResult(
                source=f"ANAC/{dataset_id}",
                success=False,
                error=f"Download failed: {url}",
            )

        dest.write_bytes(data)
        # Count rows (subtract 1 for header)
        rows = max(0, data.count(b"\n") - 1)
        logger.info(f"[fetch] Saved {dest.name}  ({rows:,} rows)")
        return DownloadResult(
            source=f"ANAC/{dataset_id}",
            success=True,
            file_path=dest,
            rows_written=rows,
        )

    # ── ATOKA API ─────────────────────────────────────────────────────────────

    def _fetch_atoka(self) -> DownloadResult:
        """
        Download enriched director data from ATOKA for all Company CFs in the
        graph.  Skipped gracefully when ATOKA_API_KEY is not set.

        Real implementation requires a live Neo4j session to enumerate CF
        values; here we provide a stub that shows what the call would do.
        """
        if not self._atoka_key:
            return DownloadResult(
                source="ATOKA API",
                success=False,
                skipped=True,
                skip_reason="Set ATOKA_API_KEY env-var to activate (https://atoka.io)",
            )

        # TODO: Pull Company CFs from Neo4j, batch-call ATOKA /companies endpoint,
        #       write directors.csv + shareholders.csv to raw_dir.
        logger.info("[fetch] ATOKA API key detected — enrichment placeholder active")
        return DownloadResult(
            source="ATOKA API",
            success=False,
            skipped=True,
            skip_reason="ATOKA enrichment not yet implemented (stub)",
        )

    # ── OpenCorporates API ────────────────────────────────────────────────────

    def _fetch_opencorporates(self) -> DownloadResult:
        """
        Fetch company officer data from OpenCorporates.
        Skipped gracefully when OPENCORPORATES_API_KEY is not set.
        """
        if not self._opencorp_key:
            return DownloadResult(
                source="OpenCorporates API",
                success=False,
                skipped=True,
                skip_reason="Set OPENCORPORATES_API_KEY env-var to activate",
            )

        # TODO: Batch-call /companies/{jurisdiction}/{company_number}/officers
        return DownloadResult(
            source="OpenCorporates API",
            success=False,
            skipped=True,
            skip_reason="OpenCorporates enrichment not yet implemented (stub)",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Guidance text
# ─────────────────────────────────────────────────────────────────────────────

_NO_DATA_GUIDANCE = """\
[bold]No corporate data was downloaded.[/bold]  Possible reasons:

  1. [cyan]ANAC dati.anticorruzione.it is unreachable[/cyan]
     Check your internet connection; the portal may be temporarily down.

  2. [cyan]No matching datasets in the ANAC catalogue[/cyan]
     The keyword filter may need updating. Check the catalogue manually:
     [link=https://dati.anticorruzione.it/opendata]https://dati.anticorruzione.it/opendata[/link]

  3. [cyan]Paid API keys not configured[/cyan]
     For richer director/shareholder data:
       export ATOKA_API_KEY=<key>           # https://atoka.io
       export OPENCORPORATES_API_KEY=<key>  # https://opencorporates.com

[bold]Manual option (always works):[/bold]
  Drop any CSV matching the corporate schema into:
    [bold white]data/corporate/raw/[/bold white]

  Required columns for directors:   cf_azienda, cf_persona, ruolo
  Required columns for shareholders: cf_azienda, cf_azionista, quota

  Then re-run:  [bold white]python scripts/run_supply_chain_etl.py --step corporate[/bold white]
"""
