"""
OpenCUP downloader - Fetch funded project data from OpenCUP.
"""

from pathlib import Path

import polars as pl
import requests
from loguru import logger


class OpencupDownloader:
    """Download OpenCUP project data."""

    # OpenCUP provides CSV exports
    BASE_URL = "https://www.opencup.gov.it/portale/web/opencup/opendata"

    def __init__(self, cache_dir: Path | None = None):
        """
        Initialize downloader.

        Args:
            cache_dir: Directory for caching downloaded files
        """
        self.cache_dir = cache_dir or Path("data/opencup/raw")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Paladino/0.1.0 (Italian Knowledge Graph)"})

    def fetch_projects_csv(self, year: int | None = None) -> Path | None:
        """
        Fetch OpenCUP projects CSV.

        Args:
            year: Optional year filter (e.g., 2024)

        Returns:
            Path to cached CSV file
        """
        filename = f"opencup_projects_{year}.csv" if year else "opencup_projects_all.csv"
        cache_path = self.cache_dir / filename

        # Check cache
        if cache_path.exists():
            logger.debug(f"Using cached file: {cache_path}")
            return cache_path

        # For now, use a mock URL (actual OpenCUP API may require authentication)
        # In production, this would download from the real API
        url = f"{self.BASE_URL}/progetti.csv"

        logger.info(f"Downloading OpenCUP projects from {url}")

        try:
            response = self.session.get(url, timeout=120)
            response.raise_for_status()

            # Save to cache
            with open(cache_path, "wb") as f:
                f.write(response.content)

            logger.success(
                f"Downloaded {cache_path.name} ({cache_path.stat().st_size / 1024 / 1024:.1f} MB)"
            )
            return cache_path

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download OpenCUP data: {e}")
            return None

    def load_csv_to_dataframe(self, csv_path: Path) -> pl.DataFrame:
        """
        Load OpenCUP CSV into Polars DataFrame.

        Args:
            csv_path: Path to CSV file

        Returns:
            Polars DataFrame
        """
        logger.info(f"Loading {csv_path.name} into DataFrame...")

        try:
            # OpenCUP CSVs are typically semicolon-delimited
            # Using infer_schema_length=0 to treat everything as strings initially
            # as these files are massive and inconsistent.
            df = pl.read_csv(
                csv_path,
                separator=";",
                encoding="utf-8-sig",
                null_values=["", "NULL", "N/A"],
                infer_schema_length=0,
                ignore_errors=True,
            )

            logger.success(f"Loaded {len(df)} rows from {csv_path.name}")
            return df

        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            return pl.DataFrame()

    def fetch_and_load(self, year: int | None = None) -> pl.DataFrame:
        """
        Fetch and load OpenCUP data in one step.

        Args:
            year: Optional year filter

        Returns:
            Polars DataFrame with project data
        """
        csv_path = self.fetch_projects_csv(year)

        if not csv_path:
            return pl.DataFrame()

        return self.load_csv_to_dataframe(csv_path)

    def get_cached_files(self) -> list[Path]:
        """Get list of all cached OpenCUP project files."""
        return sorted(self.cache_dir.glob("OpenCup_Progetti*.csv"))

    def clear_cache(self):
        """Remove all cached files."""
        for file in self.get_cached_files():
            file.unlink()
            logger.debug(f"Deleted {file.name}")

        logger.info("Cache cleared")
