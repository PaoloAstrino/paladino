"""
ISTAT downloader - Fetch Italian geographic and socio-economic data.
"""

from pathlib import Path

import polars as pl
import requests
from loguru import logger


class IstatDownloader:
    """Download ISTAT data (municipalities, provinces, regions, indicators)."""

    # ISTAT provides CSV exports
    # ISTAT provides a unified CSV of all municipalities including province and region info
    UNIFIED_CSV_URL = (
        "https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.csv"
    )

    def __init__(self, cache_dir: Path | None = None):
        """
        Initialize downloader.

        Args:
            cache_dir: Directory for caching downloaded files
        """
        self.cache_dir = cache_dir or Path("data/istat/raw")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Paladino/0.1.0 (Italian Knowledge Graph)"})

    def fetch_unified_csv(self) -> Path | None:
        """
        Fetch the unified ISTAT CSV.

        Returns:
            Path to cached CSV file
        """
        cache_path = self.cache_dir / "istat_unified.csv"

        # Check cache
        if cache_path.exists():
            logger.debug(f"Using cached file: {cache_path}")
            return cache_path

        logger.info(f"Downloading ISTAT unified data from {self.UNIFIED_CSV_URL}")

        try:
            response = self.session.get(self.UNIFIED_CSV_URL, timeout=60)
            response.raise_for_status()

            # Save to cache
            with open(cache_path, "wb") as f:
                f.write(response.content)

            logger.success(
                f"Downloaded {cache_path.name} ({cache_path.stat().st_size / 1024:.1f} KB)"
            )
            return cache_path

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download ISTAT data: {e}")
            return None

    def fetch_municipalities_csv(self) -> Path | None:
        """Backward compatibility for municipalities CSV."""
        return self.fetch_unified_csv()

    def fetch_provinces_csv(self) -> Path | None:
        """Backward compatibility for provinces CSV."""
        return self.fetch_unified_csv()

    def fetch_regions_csv(self) -> Path | None:
        """Backward compatibility for regions CSV."""
        return self.fetch_unified_csv()

    def load_csv_to_dataframe(self, csv_path: Path) -> pl.DataFrame:
        """
        Load ISTAT CSV into Polars DataFrame.

        Args:
            csv_path: Path to CSV file

        Returns:
            Polars DataFrame
        """
        logger.info(f"Loading {csv_path.name} into DataFrame...")

        try:
            # ISTAT CSVs are typically semicolon-delimited and use latin-1/iso-8859-1
            df = pl.read_csv(
                csv_path,
                separator=";",
                encoding="latin-1",
                null_values=["", "NULL"],
                infer_schema_length=0,  # Avoid type issues during initial load
            )

            logger.success(f"Loaded {len(df)} records")
            return df

        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            return pl.DataFrame()

    def fetch_all(self) -> dict:
        """
        Fetch all ISTAT data (unified version).

        Returns:
            Dictionary with the same DataFrame for all components for transformer to handle
        """
        logger.info("Fetching unified ISTAT geographic data...")

        unified_path = self.fetch_unified_csv()
        if not unified_path:
            return {}

        df = self.load_csv_to_dataframe(unified_path)

        # We return the same DF for all, the transformer will extract unique regions/provinces/municipalities
        return {"municipalities": df, "provinces": df, "regions": df}

    def get_cached_files(self) -> list[Path]:
        """Get list of all cached ISTAT files."""
        return sorted(self.cache_dir.glob("istat_*.csv"))

    def clear_cache(self):
        """Remove all cached files."""
        for file in self.get_cached_files():
            file.unlink()
            logger.debug(f"Deleted {file.name}")

        logger.info("Cache cleared")
