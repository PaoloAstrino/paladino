"""
Tests for RegistroImpreseFetcher (infocamere_downloader.py).

Uses temporary directories and a tiny HTTP mock to avoid any real network
calls.  All tests are runnable offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from paladino.etl.corporate.infocamere_downloader import (
    DownloadResult,
    FetchSummary,
    RegistroImpreseFetcher,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Temporary data root directory."""
    (tmp_path / "corporate" / "raw").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def fetcher(data_dir: Path) -> RegistroImpreseFetcher:
    return RegistroImpreseFetcher(data_dir=data_dir, dry_run=False)


@pytest.fixture
def dry_run_fetcher(data_dir: Path) -> RegistroImpreseFetcher:
    return RegistroImpreseFetcher(data_dir=data_dir, dry_run=True)


# ─────────────────────────────────────────────────────────────────────────────
# DownloadResult / FetchSummary unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestDownloadResult:
    def test_defaults(self):
        r = DownloadResult(source="test", success=True)
        assert r.rows_written == 0
        assert r.file_path is None
        assert r.error is None

    def test_failed_result(self):
        r = DownloadResult(source="test", success=False, error="oops")
        assert not r.success
        assert r.error == "oops"


class TestFetchSummary:
    def test_empty_summary(self):
        s = FetchSummary()
        assert s.total_rows == 0
        assert s.successful == []
        assert s.failed == []

    def test_counts(self):
        s = FetchSummary(
            downloads=[
                DownloadResult(source="A", success=True, rows_written=100),
                DownloadResult(source="B", success=False, error="err"),
                DownloadResult(source="C", success=False, skipped=True, skip_reason="no key"),
            ]
        )
        assert len(s.successful) == 1
        assert len(s.failed) == 1  # only non-skipped failures
        assert s.total_rows == 100


# ─────────────────────────────────────────────────────────────────────────────
# RegistroImpreseFetcher — ATOKA / OpenCorporates skipped without keys
# ─────────────────────────────────────────────────────────────────────────────


class TestFetcherApiKeyGating:
    def test_atoka_skipped_without_key(self, fetcher, monkeypatch):
        monkeypatch.delenv("ATOKA_API_KEY", raising=False)
        result = fetcher._fetch_atoka()
        assert result.skipped is True
        assert "ATOKA_API_KEY" in result.skip_reason

    def test_opencorporates_skipped_without_key(self, fetcher, monkeypatch):
        monkeypatch.delenv("OPENCORPORATES_API_KEY", raising=False)
        result = fetcher._fetch_opencorporates()
        assert result.skipped is True


# ─────────────────────────────────────────────────────────────────────────────
# ANAC catalogue fetch (mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestAnacFetch:
    def _make_catalogue_response(self, ids: list[str]) -> bytes:
        return json.dumps({"result": ids}).encode()

    def _make_package_response(self, dataset_id: str, csv_url: str) -> bytes:
        return json.dumps({"result": {"resources": [{"format": "CSV", "url": csv_url}]}}).encode()

    def test_anac_returns_skipped_when_no_matching_datasets(self, fetcher):
        catalogue = json.dumps({"result": ["irrelevant_dataset_1"]}).encode()
        with patch(
            "paladino.etl.corporate.infocamere_downloader._http_get", return_value=catalogue
        ):
            results = fetcher._fetch_anac_subjects()
        assert all(r.skipped for r in results)

    def test_anac_network_failure(self, fetcher):
        with patch("paladino.etl.corporate.infocamere_downloader._http_get", return_value=None):
            results = fetcher._fetch_anac_subjects()
        assert len(results) == 1
        assert not results[0].success
        assert "dati.anticorruzione.it" in results[0].error

    def test_download_skipped_when_file_fresh(self, fetcher, data_dir):
        """File downloaded < 24h ago should be skipped."""
        dest = data_dir / "corporate" / "raw" / "test.csv"
        dest.write_text("cf,name\n12345,COMPANY\n")  # create fresh file

        csv_url = "https://example.com/test.csv"
        meta_response = self._make_package_response("soggetti_test", csv_url).decode()

        with patch("paladino.etl.corporate.infocamere_downloader._http_get") as mock_get:
            # Return metadata; should not be called for the actual CSV
            mock_get.return_value = meta_response.encode()
            result = fetcher._download_anac_dataset("soggetti_test")

        assert result.skipped is True

    def test_dry_run_does_not_write(self, dry_run_fetcher, data_dir):
        """dry_run=True must not write any files."""
        csv_url = "https://example.com/soggetti.csv"
        meta_bytes = self._make_package_response("soggetti_2024", csv_url)
        csv_bytes = b"cf,nome\n12345678901,SRL TEST\n"

        call_count = [0]

        def _mock_get(url, *args, **kwargs):
            call_count[0] += 1
            if "package_show" in url:
                return meta_bytes
            return csv_bytes

        with patch("paladino.etl.corporate.infocamere_downloader._http_get", side_effect=_mock_get):
            result = dry_run_fetcher._download_anac_dataset("soggetti_2024")

        assert result.skipped is True
        assert result.skip_reason == "dry-run"
        # Nothing written
        assert list((data_dir / "corporate" / "raw").glob("*.csv")) == []


# ─────────────────────────────────────────────────────────────────────────────
# fetch_all integration test (fully mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchAll:
    def test_fetch_all_returns_summary(self, fetcher):
        with patch.object(
            fetcher,
            "_fetch_anac_subjects",
            return_value=[
                DownloadResult(source="ANAC/soggetti_2024", success=True, rows_written=250)
            ],
        ):
            summary = fetcher.fetch_all()

        assert summary.total_rows == 250
        assert len(summary.successful) >= 1
        assert summary.elapsed_seconds >= 0

    def test_print_summary_executes_without_error(self, fetcher):
        summary = FetchSummary(
            downloads=[
                DownloadResult(
                    source="ANAC", success=True, rows_written=50, file_path=Path("test.csv")
                ),
                DownloadResult(source="ATOKA", success=False, skipped=True, skip_reason="No key"),
            ]
        )
        # Should not raise
        fetcher.print_summary(summary)
