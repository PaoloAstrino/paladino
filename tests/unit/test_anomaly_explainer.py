"""
Tests for AnomalyExplainer (anomaly_explainer.py).

All tests run offline — Neo4j is replaced by a lightweight mock that returns
canned query results keyed by Cypher snippet.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from paladino.analytics.anomaly_explainer import (
    AnomalyExplainer,
    ExplanationResult,
    FactorExplanation,
    _risk_tier,
)

# ─────────────────────────────────────────────────────────────────────────────
# Mock connection factory
# ─────────────────────────────────────────────────────────────────────────────

_COMPANY_ROW = {
    "company_id": "CMP001",
    "cf": "12345678901",
    "company_name": "COSTRUZIONI ROSSI SRL",
    "risk_score": 0.73,
    "anomaly_flags": ["high_single_bidder_ratio", "market_dominance_high"],
    "centrality_score": 0.58,
    "community_id": 42,
}

_SBR_ROW = {
    "total_wins": 15,
    "single_bidder_wins": 10,
    "ratio": 0.667,
    "sample_tender_ids": ["T001", "T002", "T003"],
}

_CENTRALITY_ROW = {"centrality_score": 0.58}

_BUYER_CONC_ROW = {
    "concentration_ratio": 0.90,
    "top_buyer_id": "B001",
    "top_buyer_name": "COMUNE DI ROMA",
}

_FRAUD_PATTERN_ROW = {
    "pattern_id": "fp-uuid-001",
    "pattern_name": "bid_rotation",
    "severity": "high",
    "confidence": 0.85,
    "description": "Company participates in bid-rotation ring.",
    "created_at": "2026-01-15T10:00:00",
    "entity_score": 0.80,
    "evidence_json": "{}",
}

_HISTORY_ROWS = [
    {
        "risk_score": 0.68,
        "change_date": "2026-01-01",
        "anomaly_flags": ["high_single_bidder_ratio"],
    },
    {"risk_score": 0.55, "change_date": "2025-10-01", "anomaly_flags": []},
]


def _make_conn(overrides: dict | None = None) -> MagicMock:
    """
    Return a mock Neo4jConnection whose run_query() returns per-Cypher results.
    *overrides* replaces specific keyword-keyed defaults.
    """
    defaults = {
        "WHERE c.id = $cid OR c.cf": [_COMPANY_ROW],
        "t.single_bidder": [_SBR_ROW],
        "centrality_score": [_CENTRALITY_ROW],
        "concentration_ratio": [_BUYER_CONC_ROW],
        "FLAGGED_BY": [_FRAUD_PATTERN_ROW],
        "HAS_SHELL_SCORE": [],  # no cached shell score
        "HAS_VERSION": _HISTORY_ROWS,
        "v.risk_score": _HISTORY_ROWS,  # Alternative match for history query
    }
    if overrides:
        defaults.update(overrides)

    def _run(cypher: str, params=None):
        for k, v in defaults.items():
            if k in cypher:
                return v
        return []

    conn = MagicMock()
    conn.run_query = MagicMock(side_effect=_run)
    conn.driver = MagicMock()
    # Prevent ShellCompanyDetector from calling real Neo4j
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.run = MagicMock(return_value=iter([]))
    conn.driver.session = MagicMock(return_value=mock_session)
    return conn


def _explainer(overrides=None) -> AnomalyExplainer:
    return AnomalyExplainer(_make_conn(overrides), include_shell_risk=False)


# ─────────────────────────────────────────────────────────────────────────────
# _risk_tier helper
# ─────────────────────────────────────────────────────────────────────────────


class TestRiskTier:
    def test_high(self):
        assert _risk_tier(0.75) == "HIGH"

    def test_medium(self):
        assert _risk_tier(0.55) == "MEDIUM"

    def test_low(self):
        assert _risk_tier(0.20) == "LOW"

    def test_boundary_high(self):
        assert _risk_tier(0.70) == "HIGH"

    def test_boundary_medium(self):
        assert _risk_tier(0.40) == "MEDIUM"


# ─────────────────────────────────────────────────────────────────────────────
# FactorExplanation
# ─────────────────────────────────────────────────────────────────────────────


class TestFactorExplanation:
    def test_instantiation(self):
        f = FactorExplanation(
            factor="single_bidder_ratio",
            label="SBR",
            value=0.68,
            weight=0.4,
            contribution=0.272,
            sentence="68% single-bidder.",
        )
        assert f.sources == []

    def test_non_empty_sources(self):
        f = FactorExplanation(
            factor="x",
            label="x",
            value=0.1,
            weight=0.3,
            contribution=0.03,
            sentence="s",
            sources=["Tender:T1"],
        )
        assert "Tender:T1" in f.sources


# ─────────────────────────────────────────────────────────────────────────────
# AnomalyExplainer.explain — structure & content
# ─────────────────────────────────────────────────────────────────────────────


class TestExplainResult:
    def _get(self) -> ExplanationResult:
        return _explainer().explain("CMP001")

    def test_returns_explanation_result(self):
        r = self._get()
        assert isinstance(r, ExplanationResult)

    def test_company_fields_populated(self):
        r = self._get()
        assert r.company_id == "CMP001"
        assert r.company_name == "COSTRUZIONI ROSSI SRL"
        assert r.risk_score == pytest.approx(0.73, abs=1e-4)

    def test_risk_tier_high(self):
        r = self._get()
        assert r.risk_tier == "HIGH"

    def test_three_factors_present(self):
        r = self._get()
        factor_names = {f.factor for f in r.factors}
        assert "single_bidder_ratio" in factor_names
        assert "market_dominance" in factor_names
        assert "buyer_concentration" in factor_names

    def test_factors_sorted_by_contribution(self):
        r = self._get()
        scores = [f.contribution for f in r.factors]
        assert scores == sorted(scores, reverse=True)

    def test_fraud_patterns_populated(self):
        r = self._get()
        assert len(r.fraud_patterns) >= 1
        assert r.fraud_patterns[0]["pattern_name"] == "bid_rotation"

    def test_summary_contains_score(self):
        r = self._get()
        assert "0.73" in r.summary

    def test_summary_is_non_empty(self):
        r = self._get()
        assert len(r.summary) > 20

    def test_trend_worsening(self):
        # current 0.73 > previous 0.68 → WORSENING
        r = self._get()
        assert r.trend == "WORSENING"

    def test_trend_improving(self):
        # inject history where previous score is higher than current
        high_history = [
            {"risk_score": 0.90, "change_date": "2026-01-01", "anomaly_flags": []},
            {"risk_score": 0.85, "change_date": "2025-10-01", "anomaly_flags": []},
        ]
        r = _explainer({"HAS_VERSION": high_history}).explain("CMP001")
        assert r.trend == "IMPROVING"

    def test_trend_stable(self):
        same_history = [
            {"risk_score": 0.73, "change_date": "2026-01-01", "anomaly_flags": []},
        ]
        r = _explainer({"HAS_VERSION": same_history}).explain("CMP001")
        # Only 1 snapshot → STABLE (not enough data)
        assert r.trend == "STABLE"

    def test_evidence_chain_populated(self):
        r = self._get()
        assert len(r.evidence_chain) >= 1

    def test_generated_at_is_iso(self):
        from datetime import datetime

        r = self._get()
        datetime.fromisoformat(r.generated_at.replace("Z", "+00:00"))

    def test_company_not_found_raises(self):
        exp = _explainer({"WHERE c.id = $cid OR c.cf": []})
        with pytest.raises(KeyError):
            exp.explain("NONEXISTENT")


# ─────────────────────────────────────────────────────────────────────────────
# Individual factor explanations
# ─────────────────────────────────────────────────────────────────────────────


class TestFactors:
    def _factors(self) -> dict:
        return {f.factor: f for f in _explainer().explain("CMP001").factors}

    def test_single_bidder_value(self):
        f = self._factors()["single_bidder_ratio"]
        assert f.value == pytest.approx(0.667, abs=1e-3)

    def test_single_bidder_contribution(self):
        f = self._factors()["single_bidder_ratio"]
        assert f.contribution == pytest.approx(0.667 * 0.40, abs=1e-3)

    def test_single_bidder_sentence_has_pct(self):
        f = self._factors()["single_bidder_ratio"]
        assert "%" in f.sentence or "single-bidder" in f.sentence.lower()

    def test_centrality_sentence_contains_pagerank(self):
        f = self._factors()["market_dominance"]
        assert (
            "pagerank" in f.sentence.lower()
            or "centrality" in f.sentence.lower()
            or "0.58" in f.sentence
        )

    def test_buyer_conc_sentence_contains_buyer_name(self):
        f = self._factors()["buyer_concentration"]
        assert "COMUNE DI ROMA" in f.sentence

    def test_factor_sources_link_tenders(self):
        f = self._factors()["single_bidder_ratio"]
        assert any("Tender:" in s for s in f.sources)


# ─────────────────────────────────────────────────────────────────────────────
# ExplanationResult — serialisation & rendering
# ─────────────────────────────────────────────────────────────────────────────


class TestRendering:
    def _result(self) -> ExplanationResult:
        return _explainer().explain("CMP001")

    def test_json_render_is_valid(self):
        r = self._result()
        data = json.loads(r.render("json"))
        assert data["company_id"] == "CMP001"
        assert "factors" in data

    def test_json_dict_keys(self):
        r = self._result()
        data = json.loads(r.render("json"))
        expected = {
            "company_id",
            "company_name",
            "risk_score",
            "risk_tier",
            "summary",
            "factors",
            "fraud_patterns",
            "evidence_chain",
            "trend",
            "risk_history",
            "generated_at",
        }
        assert expected.issubset(data.keys())

    def test_markdown_starts_with_heading(self):
        r = self._result()
        md = r.render("md")
        assert md.startswith("# Anomaly Explanation")

    def test_markdown_contains_company_name(self):
        r = self._result()
        assert "COSTRUZIONI ROSSI SRL" in r.render("md")

    def test_markdown_contains_fraud_section(self):
        r = self._result()
        assert "Fraud Pattern" in r.render("md")

    def test_text_render_has_score(self):
        r = self._result()
        txt = r.render("text")
        assert "0.73" in txt or "COSTRUZIONI" in txt

    def test_invalid_format_raises(self):
        r = self._result()
        with pytest.raises(ValueError, match="Unsupported format"):
            r.render("pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Edge cases — missing data
# ─────────────────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_no_tenders(self):
        r = _explainer(
            {
                "t.single_bidder": [],
                "concentration_ratio": [],
            }
        ).explain("CMP001")
        # Should still produce a result
        assert isinstance(r, ExplanationResult)
        factor_names = {f.factor for f in r.factors}
        assert "single_bidder_ratio" not in factor_names
        assert "buyer_concentration" not in factor_names

    def test_no_fraud_patterns(self):
        r = _explainer({"FLAGGED_BY": []}).explain("CMP001")
        assert r.fraud_patterns == []

    def test_no_history(self):
        r = _explainer({"HAS_VERSION": []}).explain("CMP001")
        assert r.trend == "STABLE"
        assert r.risk_history == []

    def test_zero_risk_score(self):
        zero_company = {**_COMPANY_ROW, "risk_score": 0.0}
        r = _explainer({"WHERE c.id = $cid OR c.cf": [zero_company]}).explain("CMP001")
        assert r.risk_score == 0.0
        assert r.risk_tier == "LOW"
