"""
Tests for ShellCompanyDetector (shell_company_detector.py).

Uses a mock Neo4j driver so tests run without a live database.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from paladino.analytics.shell_company_detector import ShellCompanyDetector, ShellRiskScore


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_driver(rows: list[dict] | None = None) -> MagicMock:
    """Return a mock driver whose session.run() yields *rows*."""
    mock_result  = MagicMock()
    mock_result.__iter__ = MagicMock(return_value=iter(rows or []))

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run = MagicMock(return_value=mock_result)

    mock_driver = MagicMock()
    mock_driver.session = MagicMock(return_value=mock_session)
    return mock_driver


# One realistic row of raw metrics
_HIGH_RISK_ROW = {
    "cf":                   "12345678901",
    "name":                 "GUSCIO SRL",
    "tender_wins":          15,
    "max_employees":        1,
    "chain_depth":          7,
    "vat_active":           False,    # VAT anomaly
    "last_filing_year":     2019,     # 5+ years ago → dormant
    "director_board_count": 25,       # board overconcentration
    "sub_only":             True,
    "address_shared_count": 4,
}

_LOW_RISK_ROW = {
    "cf":                   "98765432109",
    "name":                 "NORMALE SPA",
    "tender_wins":          2,
    "max_employees":        150,
    "chain_depth":          1,
    "vat_active":           True,
    "last_filing_year":     2024,
    "director_board_count": 3,
    "sub_only":             False,
    "address_shared_count": 0,
}


# ─────────────────────────────────────────────────────────────────────────────
# ShellRiskScore unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestShellRiskScore:
    def test_as_dict_keys(self):
        s = ShellRiskScore(
            company_id="123",
            company_name="TEST SRL",
            shell_score=0.75,
            risk_tier="HIGH_RISK",
            factors={"tender_wins": 10},
            weights={"legacy": 0.3},
            component_scores={"legacy": 0.2},
        )
        d = s.as_dict()
        assert "shell_score" in d
        assert "risk_tier" in d
        assert "component_scores" in d
        assert d["risk_tier"] == "HIGH_RISK"

    def test_score_rounded_in_as_dict(self):
        s = ShellRiskScore(
            company_id="x", company_name="y",
            shell_score=0.123456789, risk_tier="HIGH_RISK",
        )
        assert len(str(s.as_dict()["shell_score"])) <= 8  # rounded to 4dp


# ─────────────────────────────────────────────────────────────────────────────
# ShellCompanyDetector._compute_score
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeScore:
    def setup_method(self):
        self.detector = ShellCompanyDetector(driver=MagicMock())

    def test_high_risk_row_classifies_as_high_risk(self):
        score = self.detector._compute_score(_HIGH_RISK_ROW)
        assert score.risk_tier == "HIGH_RISK"
        assert score.shell_score >= 0.50

    def test_low_risk_row_classifies_as_low_risk(self):
        score = self.detector._compute_score(_LOW_RISK_ROW)
        assert score.risk_tier == "LOW_RISK"
        assert score.shell_score < 0.35

    def test_score_in_valid_range(self):
        for row in [_HIGH_RISK_ROW, _LOW_RISK_ROW]:
            score = self.detector._compute_score(row)
            assert 0.0 <= score.shell_score <= 1.0

    def test_all_components_present(self):
        score = self.detector._compute_score(_HIGH_RISK_ROW)
        expected = {"legacy", "vat_anomaly", "dormancy", "board_conc",
                    "supplier_only", "address_flag", "depth_bonus"}
        assert set(score.component_scores.keys()) == expected

    def test_weights_sum_to_one(self):
        total = sum(ShellCompanyDetector._WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_missing_fields_handled_gracefully(self):
        """score_single should not raise on a sparse row."""
        sparse = {"cf": "111", "name": "SPARSE SRL"}
        score = self.detector._compute_score(sparse)
        assert 0.0 <= score.shell_score <= 1.0

    def test_vat_anomaly_fires_when_inactive_and_wins(self):
        row = {**_LOW_RISK_ROW, "tender_wins": 5, "vat_active": False}
        score = self.detector._compute_score(row)
        assert score.component_scores["vat_anomaly"] > 0

    def test_dormancy_fires_after_threshold(self):
        import datetime
        old_year = datetime.datetime.now().year - 5
        row = {**_LOW_RISK_ROW, "last_filing_year": old_year}
        score = self.detector._compute_score(row)
        assert score.component_scores["dormancy"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# ShellCompanyDetector.score_all / score_single
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreAll:
    def test_score_all_returns_sorted_results(self):
        driver  = _make_mock_driver([_HIGH_RISK_ROW, _LOW_RISK_ROW])
        detector = ShellCompanyDetector(driver=driver)
        results  = detector.score_all(limit=10)
        assert len(results) == 2
        assert results[0].shell_score >= results[1].shell_score

    def test_score_all_empty_graph(self):
        driver  = _make_mock_driver([])
        detector = ShellCompanyDetector(driver=driver)
        results  = detector.score_all()
        assert results == []

    def test_score_all_graceful_db_error(self):
        driver = MagicMock()
        driver.session.side_effect = Exception("DB offline")
        detector = ShellCompanyDetector(driver=driver)
        results  = detector.score_all()
        assert results == []

    def test_get_high_risk_filter(self):
        driver  = _make_mock_driver([_HIGH_RISK_ROW, _LOW_RISK_ROW])
        detector = ShellCompanyDetector(driver=driver)
        all_res = detector.score_all()
        high    = detector.get_high_risk(all_res, threshold=0.50)
        assert all(r.shell_score >= 0.50 for r in high)

    def test_get_medium_risk_filter(self):
        driver  = _make_mock_driver([_HIGH_RISK_ROW, _LOW_RISK_ROW])
        detector = ShellCompanyDetector(driver=driver)
        all_res = detector.score_all()
        medium  = detector.get_medium_risk(all_res, low_threshold=0.35, high_threshold=0.50)
        assert all(0.35 <= r.shell_score < 0.50 for r in medium)
