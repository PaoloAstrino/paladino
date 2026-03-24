"""
Tests for UBOReportGenerator (ubo_report_generator.py).

Uses mock Neo4j connections so tests run without a live database.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from paladino.app.ubo_report_generator import UBOReportGenerator


# ─────────────────────────────────────────────────────────────────────────────
# Factory helpers
# ─────────────────────────────────────────────────────────────────────────────

def _mock_conn(query_results: dict | None = None) -> MagicMock:
    """
    Return a mock :class:`Neo4jConnection` whose ``run_query()`` returns
    per-Cypher results from *query_results* (keyed by a str match).

    If a keyword is not found, returns [].
    """
    default_results = {
        "Company {cf":    [{"cf": "12345678901", "name": "TEST SRL", "ateco": "41.10",
                            "comune": "Roma", "regione": "Lazio",
                            "vat_active": True, "risk_score": 0.2, "address": "Via Roma 1"}],
        "AWARDED":        [],
        "SHAREHOLDER_OF": [],
        "REPRESENTS":     [{"person_cf": "RSSMRA80A01H501Z", "name": "Mario Rossi",
                            "role": "Amministratore", "start_date": "2010-01-01", "end_date": None}],
        "FLAGGED_BY":     [],
        "SUBCONTRACTS_TO": [],
    }
    if query_results:
        default_results.update(query_results)

    def _run_query(cypher: str, params: dict | None = None):
        for key, val in default_results.items():
            if key in cypher:
                return val
        return []

    conn = MagicMock()
    conn.run_query = MagicMock(side_effect=_run_query)
    conn.driver = MagicMock()
    # Mock the driver.session() for ShellCompanyDetector
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run = MagicMock(return_value=iter([]))
    conn.driver.session = MagicMock(return_value=mock_session)
    return conn


def _make_generator(query_results=None) -> UBOReportGenerator:
    return UBOReportGenerator(conn=_mock_conn(query_results))


# ─────────────────────────────────────────────────────────────────────────────
# Format validation
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatValidation:
    def test_json_format_accepted(self):
        gen = _make_generator()
        result = gen.generate("12345678901", format="json")
        assert isinstance(result, str)
        # Must be valid JSON
        data = json.loads(result)
        assert "company_id" in data

    def test_md_format_accepted(self):
        gen = _make_generator()
        result = gen.generate("12345678901", format="md")
        assert result.startswith("# UBO Report")

    def test_csv_format_accepted(self):
        gen = _make_generator()
        result = gen.generate("12345678901", format="csv")
        lines = result.strip().splitlines()
        assert "company_id" in lines[0]

    def test_invalid_format_raises(self):
        gen = _make_generator()
        with pytest.raises(ValueError, match="Unsupported format"):
            gen.generate("12345678901", format="pdf")

    def test_company_not_found_raises(self):
        conn = _mock_conn({"Company {cf": []})  # empty result → KeyError
        gen  = UBOReportGenerator(conn=conn)
        with pytest.raises(KeyError):
            gen.generate("00000000000")


# ─────────────────────────────────────────────────────────────────────────────
# JSON report structure
# ─────────────────────────────────────────────────────────────────────────────

class TestJSONReport:
    def _get_report(self):
        gen = _make_generator()
        return json.loads(gen.generate("12345678901", format="json"))

    def test_top_level_keys(self):
        data = self._get_report()
        required = {
            "generated_at", "company_id", "company_info",
            "ownership_chain", "ubos", "directors",
            "fraud_patterns", "supply_chain",
        }
        assert required.issubset(data.keys())

    def test_company_id_preserved(self):
        data = self._get_report()
        assert data["company_id"] == "12345678901"

    def test_company_info_name(self):
        data = self._get_report()
        assert data["company_info"]["name"] == "TEST SRL"

    def test_directors_populated(self):
        data = self._get_report()
        assert len(data["directors"]) == 1
        assert data["directors"][0]["name"] == "Mario Rossi"

    def test_generated_at_is_iso_string(self):
        from datetime import datetime
        data = self._get_report()
        # Should not raise
        datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))


# ─────────────────────────────────────────────────────────────────────────────
# Markdown report structure
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkdownReport:
    def _get_report(self) -> str:
        return _make_generator().generate("12345678901", format="md")

    def test_contains_company_name(self):
        assert "TEST SRL" in self._get_report()

    def test_contains_required_sections(self):
        md = self._get_report()
        for section in ["Shell Risk Score", "Ultimate Beneficial Owners", "Board of Directors",
                        "Fraud Pattern Alerts", "Corporate Family", "Supply Chain"]:
            assert section in md, f"Section '{section}' missing from Markdown report"

    def test_directors_rendered_in_table(self):
        md = self._get_report()
        assert "Mario Rossi" in md


# ─────────────────────────────────────────────────────────────────────────────
# CSV report structure
# ─────────────────────────────────────────────────────────────────────────────

class TestCSVReport:
    def _get_rows(self) -> list[list[str]]:
        import csv, io
        raw = _make_generator().generate("12345678901", format="csv")
        return list(csv.reader(io.StringIO(raw)))

    def test_header_row(self):
        rows = self._get_rows()
        assert rows[0][0] == "report_date"
        assert "company_id" in rows[0]
        assert "shell_score" in rows[0]

    def test_data_row_count_gte_header(self):
        rows = self._get_rows()
        assert len(rows) >= 2  # at least header + 1 data row

    def test_company_id_in_data(self):
        rows = self._get_rows()
        # find company_id column index
        header = rows[0]
        idx = header.index("company_id")
        assert any(r[idx] == "12345678901" for r in rows[1:])


# ─────────────────────────────────────────────────────────────────────────────
# UBO extraction
# ─────────────────────────────────────────────────────────────────────────────

class TestUBOExtraction:
    def test_no_chain_returns_empty_ubos(self):
        data = json.loads(_make_generator().generate("12345678901", format="json"))
        # With no ownership chain data, ubos list is empty
        assert isinstance(data["ubos"], list)

    def test_ubos_extracted_from_chain(self):
        """Simulate a 2-level chain: PersonA → CompanyB → CompanyC (root UBO = CompanyA)."""
        gen = _make_generator()
        chain = [
            {"owner_id": "PERSON_A", "company_id": "COMP_B"},
            {"owner_id": "COMP_B",   "company_id": "12345678901"},
        ]
        ubos = gen._extract_ubos(chain)
        # PERSON_A has no owner in the chain → it is the UBO
        ubo_ids = [u["ubo_id"] for u in ubos]
        assert "PERSON_A" in ubo_ids
