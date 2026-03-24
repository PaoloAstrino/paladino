"""
ANAC OCDS downloader - Fetch procurement data from ANAC OpenData.
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from loguru import logger
from tqdm import tqdm

from paladino.errors import DownloadError, RateLimitedError

# Maximum retries for transient errors (5xx, network issues)
_MAX_RETRIES = 4
# Base delay in seconds for exponential backoff (doubles each attempt)
_BACKOFF_BASE = 2


def _download_with_retry(
    session: requests.Session, url: str, timeout: int = 60
) -> requests.Response:
    """
    GET *url* with automatic retry and exponential backoff.

    Strategy:
      • 404 → raise immediately (data doesn't exist, no point retrying).
      • 429 → read Retry-After header, sleep, then retry.
      • 5xx → exponential backoff (2 s, 4 s, 8 s, 16 s).
      • Network error → same backoff as 5xx.

    Raises:
        RateLimitedError: if 429 persists after all retries.
        DownloadError: for 404 or persistent 5xx / network failures.
    """
    last_exc: Exception = RuntimeError("No attempts made")

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=timeout)

            # ── 404: resource doesn't exist ──────────────────────────────────
            if response.status_code == 404:
                raise DownloadError(
                    message=f"Resource not found (404): {url}",
                    hint="The ANAC server has no data for this date. Try an earlier period.",
                )

            # ── 429: rate limited ────────────────────────────────────────────
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", _BACKOFF_BASE * attempt))
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Rate-limited (429) on {url}. Waiting {retry_after}s (attempt {attempt}/{_MAX_RETRIES})…"
                    )
                    time.sleep(retry_after)
                    last_exc = RateLimitedError(
                        message=f"ANAC server rate-limited (429): {url}",
                        hint=f"Retry after {retry_after}s.",
                    )
                    continue
                raise RateLimitedError(
                    message=f"ANAC server rate-limited after {_MAX_RETRIES} attempts: {url}",
                    hint="Wait a few minutes before trying again.",
                )

            # ── 5xx: server error ────────────────────────────────────────────
            if response.status_code >= 500:
                wait = _BACKOFF_BASE**attempt
                if attempt < _MAX_RETRIES:
                    logger.warning(
                        f"Server error {response.status_code} for {url}. Retrying in {wait}s (attempt {attempt}/{_MAX_RETRIES})…"
                    )
                    time.sleep(wait)
                    last_exc = DownloadError(message=f"HTTP {response.status_code} from {url}")
                    continue
                raise DownloadError(
                    message=f"ANAC server returned HTTP {response.status_code} after {_MAX_RETRIES} attempts.",
                    hint=f"URL: {url}. The ANAC service may be down — try again later.",
                )

            response.raise_for_status()
            return response

        except (DownloadError, RateLimitedError):
            raise
        except requests.exceptions.ConnectionError as e:
            wait = _BACKOFF_BASE**attempt
            if attempt < _MAX_RETRIES:
                logger.warning(f"Connection error for {url}: {e}. Retrying in {wait}s…")
                time.sleep(wait)
                last_exc = e
                continue
            raise DownloadError(
                message=f"Cannot connect to ANAC server: {url}",
                hint="Check your internet connection.",
            ) from e
        except requests.exceptions.Timeout as e:
            wait = _BACKOFF_BASE**attempt
            if attempt < _MAX_RETRIES:
                logger.warning(f"Timeout for {url}. Retrying in {wait}s…")
                time.sleep(wait)
                last_exc = e
                continue
            raise DownloadError(
                message=f"Request timed out after {_MAX_RETRIES} attempts: {url}",
                hint="The ANAC server is slow. Try again later or increase timeout.",
            ) from e
        except requests.exceptions.RequestException as e:
            raise DownloadError(message=f"Download failed: {e}", hint=str(url)) from e

    raise DownloadError(
        message=f"Download failed after {_MAX_RETRIES} retries: {url}"
    ) from last_exc


class AnacOcdsDownloader:
    """Download ANAC OCDS release packages."""

    BASE_URL = "https://dati.anticorruzione.it/opendata/ocds"

    def __init__(self, cache_dir: Path | None = None):
        """
        Initialize downloader.

        Args:
            cache_dir: Directory for caching downloaded files
        """
        self.cache_dir = cache_dir or Path("data/anac/raw")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Paladino/0.1.0 (Italian Knowledge Graph)"})

    def fetch_release(self, year: int, month: int) -> Path | None:
        """
        Fetch a single monthly OCDS release package.

        Args:
            year: Year (e.g., 2024)
            month: Month (1-12)

        Returns:
            Path to cached file, or None if download failed
        """
        cache_path = self.cache_dir / f"anac_{year}_{month:02d}.json"

        # Check cache
        if cache_path.exists():
            logger.debug(f"Using cached file: {cache_path}")
            return cache_path

        # Download
        url = f"{self.BASE_URL}/releases/{year}/{month:02d}.json"
        logger.info(f"Downloading {year}-{month:02d} from {url}")

        try:
            response = _download_with_retry(self.session, url)

            # Parse JSON — guard against corrupted responses
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError) as e:
                logger.error(f"Response from {url} is not valid JSON: {e}")
                return None

            # Save to cache
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            logger.success(
                f"Downloaded {cache_path.name} ({cache_path.stat().st_size / 1024 / 1024:.1f} MB)"
            )
            return cache_path

        except DownloadError as e:
            logger.warning(f"{e.message}" + (f" | {e.hint}" if e.hint else ""))
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading {year}-{month:02d}: {e}")
            return None

    def fetch_date_range(
        self, start_date: datetime, end_date: datetime, skip_existing: bool = True
    ) -> list[Path]:
        """
        Fetch all releases in a date range.

        Args:
            start_date: Start date
            end_date: End date
            skip_existing: Skip already cached files

        Returns:
            List of paths to downloaded files
        """
        files = []
        current = start_date.replace(day=1)

        # Generate list of months
        months = []
        while current <= end_date:
            months.append((current.year, current.month))
            current += timedelta(days=32)
            current = current.replace(day=1)

        logger.info(f"Fetching {len(months)} months from {start_date.date()} to {end_date.date()}")

        # Download with progress bar
        for year, month in tqdm(months, desc="Downloading ANAC data"):
            file_path = self.fetch_release(year, month)
            if file_path:
                files.append(file_path)

        logger.success(f"Downloaded {len(files)}/{len(months)} files")
        return files

    def fetch_recent(self, months: int = 6) -> list[Path]:
        """
        Fetch recent N months of data.

        Args:
            months: Number of recent months to fetch

        Returns:
            List of paths to downloaded files
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=months * 31)

        return self.fetch_date_range(start_date, end_date)

    def get_cached_files(self) -> list[Path]:
        """
        Get all JSON files in the cache directory.

        Returns:
            List of paths
        """
        # Supports both automated ('anac_*.json') and manual ('ocds_*.json') filenames
        files = list(self.cache_dir.glob("*.json"))
        return sorted([f for f in files if f.is_file()])

    def clear_cache(self):
        """Remove all cached files."""
        for file in self.get_cached_files():
            file.unlink()
            logger.debug(f"Deleted {file.name}")

        logger.info("Cache cleared")
