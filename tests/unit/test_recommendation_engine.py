"""
Tests for paladino.analytics.recommendation_engine — Feature 4.4.

All tests are fully offline: Neo4jConnection is mocked so no live graph
is needed during CI.  Each query is keyed by a Cypher snippet that the
production code must contain in the query string it sends to run_query().
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from paladino.analytics.recommendation_engine import (
    COMMUNITY_DEFAULT_SCORE,
    RISK_DELTA_THRESHOLD,
    Recommendation,
    RecommendationEngine,
    RecommendationResult,
    _ateco2,
    _jaccard,
    _merge,
    _risk_tier,
)


# ─────────────────────────────────────────────────────────────────────────────
# Canned graph data
# ─────────────────────────────────────────────────────────────────────────────

_SOURCE = {
    "company_id":   "src-001",
    "cf":           "12345678901",
    "company_name": "COSTRUZIONI ROSSI SRL",
    "risk_score":   0.72,
    "anomaly_flags": ["high_single_bidder_ratio", "market_dominance_high"],
    "community_id": 5,
    "ateco":        "41.20",
    "regione":      "Lombardia",
}

# Candidate company rows returned by content-based / community / anomaly queries
_CAND_SAME_SECTOR_REGION = {
    "company_id":    "cand-001",
    "company_name":  "EDIL BIANCHI SPA",
    "cf":            "98765432109",
    "risk_score":    0.65,
    "ateco":         "41.10",    # same 2-digit sector (41)
    "regione":       "Lombardia",
    "anomaly_flags": ["high_single_bidder_ratio"],
}

_CAND_DIFFERENT_SECTOR = {
    "company_id":    "cand-002",
    "company_name":  "TECH VERDI SRL",
    "cf":            "11223344556",
    "risk_score":    0.30,
    "ateco":         "62.01",    # different sector
    "regione":       "Toscana",
    "anomaly_flags": [],
}

_CAND_COMMUNITY_MEMBER = {
    "company_id": "cand-003",
    "company_name": "APPALTI NERI SRL",
    "cf":           "55667788990",
    "risk_score":   0.60,
}

_CAND_SECTOR_TRENDING = {
    "company_id":  "cand-004",
    "company_name": "COSTRUZIONI GRIGI SPA",
    "cf":           "44556677889",
    "risk_score":   0.80,
    "ateco":        "41.30",
}

_CAND_ANOMALY_MATCH = {
    "company_id":    "cand-005",
    "company_name":  "VIOLA APPALTI SRL",
    "cf":            "33445566778",
    "risk_score":    0.55,
    "anomaly_flags": ["high_single_bidder_ratio", "high_buyer_concentration"],
}


# ─────────────────────────────────────────────────────────────────────────────
# Mock factory
# ─────────────────────────────────────────────────────────────────────────────

def _make_conn(
    source_rows: Optional[List[Dict]] = None,
    content_rows: Optional[List[Dict]] = None,
    community_rows: Optional[List[Dict]] = None,
    anomaly_rows: Optional[List[Dict]] = None,
    sector_rows: Optional[List[Dict]] = None,
) -> MagicMock:
    """
    Build a mock Neo4jConnection whose run_query() dispatches by Cypher keyword.
    """
    conn = MagicMock()

    def _run_query(cypher: str, params: Dict = None) -> List[Dict]:
        # Source company lookup — keyed by "c.id = $cid OR c.cf = $cid"
        if "c.id = $cid OR c.cf = $cid" in cypher:
            return source_rows if source_rows is not None else [_SOURCE]
        # Content-based — returns up to 2 000 candidates
        if "LIMIT 2000" in cypher:
            return content_rows if content_rows is not None else []
        # Community-based — uses community_id param
        if "c.community_id = $cid" in cypher:
            return community_rows if community_rows is not None else []
        # Anomaly-based — uses anomaly_flags param
        if "anomaly_flags" in cypher and "$flags" in cypher:
            return anomaly_rows if anomaly_rows is not None else []
        # Sector trending — uses STARTS WITH $ateco2
        if "STARTS WITH $ateco2" in cypher:
            return sector_rows if sector_rows is not None else []
        return []

    conn.run_query.side_effect = _run_query
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# TestRiskTier
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskTier:
    def test_high_boundary(self):
        assert _risk_tier(0.70) == "HIGH"

    def test_high_above(self):
        assert _risk_tier(0.99) == "HIGH"

    def test_medium_boundary(self):
        assert _risk_tier(0.40) == "MEDIUM"

    def test_medium_range(self):
        assert _risk_tier(0.55) == "MEDIUM"

    def test_low(self):
        assert _risk_tier(0.0) == "LOW"


# ─────────────────────────────────────────────────────────────────────────────
# TestJaccard
# ─────────────────────────────────────────────────────────────────────────────

class TestJaccard:
    def test_identical_lists(self):
        assert _jaccard(["a", "b"], ["a", "b"]) == 1.0

    def test_no_overlap(self):
        assert _jaccard(["a"], ["b"]) == 0.0

    def test_partial_overlap(self):
        result = _jaccard(["a", "b", "c"], ["b", "c", "d"])
        assert abs(result - 2 / 4) < 1e-9  # |{b,c}| / |{a,b,c,d}|

    def test_empty_both(self):
        assert _jaccard([], []) == 0.0

    def test_empty_one(self):
        assert _jaccard(["a"], []) == 0.0

    def test_none_inputs(self):
        assert _jaccard(None, None) == 0.0  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# TestAteco2
# ─────────────────────────────────────────────────────────────────────────────

class TestAteco2:
    def test_normal(self):
        assert _ateco2("41.20") == "41"

    def test_two_digit(self):
        assert _ateco2("62") == "62"

    def test_single_char(self):
        assert _ateco2("4") is None

    def test_none(self):
        assert _ateco2(None) is None

    def test_empty_string(self):
        assert _ateco2("") is None


# ─────────────────────────────────────────────────────────────────────────────
# TestMerge (deduplication helper)
# ─────────────────────────────────────────────────────────────────────────────

def _make_rec(company_id: str, score: float, strategy: str) -> Recommendation:
    return Recommendation(
        company_id=company_id,
        company_name="Test SRL",
        cf="00000000001",
        risk_score=0.5,
        similarity_score=score,
        reason="test reason.",
        strategies=[strategy],
        shared_features=[f"feat:{strategy}"],
    )


class TestMerge:
    def test_new_entry(self):
        registry: Dict[str, Recommendation] = {}
        rec = _make_rec("c1", 0.7, "content")
        _merge(registry, rec, "content")
        assert "c1" in registry
        assert registry["c1"].similarity_score == 0.7

    def test_keeps_higher_score(self):
        registry: Dict[str, Recommendation] = {}
        _merge(registry, _make_rec("c1", 0.5, "content"), "content")
        _merge(registry, _make_rec("c1", 0.8, "community"), "community")
        assert registry["c1"].similarity_score == 0.8

    def test_accumulates_strategies(self):
        registry: Dict[str, Recommendation] = {}
        _merge(registry, _make_rec("c1", 0.5, "content"), "content")
        _merge(registry, _make_rec("c1", 0.6, "community"), "community")
        assert "community" in registry["c1"].strategies
        assert "content" in registry["c1"].strategies

    def test_no_strategy_duplicate(self):
        registry: Dict[str, Recommendation] = {}
        _merge(registry, _make_rec("c1", 0.5, "content"), "content")
        _merge(registry, _make_rec("c1", 0.6, "content"), "content")
        assert registry["c1"].strategies.count("content") == 1

    def test_accumulates_shared_features(self):
        registry: Dict[str, Recommendation] = {}
        r1 = _make_rec("c1", 0.5, "content")
        r1.shared_features = ["ATECO:41"]
        r2 = _make_rec("c1", 0.6, "community")
        r2.shared_features = ["community:5"]
        _merge(registry, r1, "content")
        _merge(registry, r2, "community")
        assert "ATECO:41" in registry["c1"].shared_features
        assert "community:5" in registry["c1"].shared_features


# ─────────────────────────────────────────────────────────────────────────────
# TestContentBased
# ─────────────────────────────────────────────────────────────────────────────

class TestContentBased:
    def _engine(self, content_rows):
        conn = _make_conn(content_rows=content_rows)
        return RecommendationEngine(conn)

    def test_same_sector_and_region_scores_above_half(self):
        engine = self._engine([_CAND_SAME_SECTOR_REGION])
        recs = engine._content_based(_SOURCE)
        assert len(recs) == 1
        rec = recs[0]
        # ATECO (0.30) + region (0.25) + risk_close (0.20) = 0.75 minimum
        assert rec.similarity_score >= 0.55

    def test_different_sector_no_ateco_contribution(self):
        engine = self._engine([_CAND_DIFFERENT_SECTOR])
        recs = engine._content_based(_SOURCE)
        # No ATECO, no region, risk far apart — low/zero score expected
        if recs:
            assert recs[0].similarity_score < 0.30

    def test_empty_candidates_returns_empty(self):
        engine = self._engine([])
        assert engine._content_based(_SOURCE) == []

    def test_shared_features_populated(self):
        engine = self._engine([_CAND_SAME_SECTOR_REGION])
        recs = engine._content_based(_SOURCE)
        assert any("ATECO" in f for f in recs[0].shared_features)

    def test_reason_mentions_ateco_sector(self):
        engine = self._engine([_CAND_SAME_SECTOR_REGION])
        recs = engine._content_based(_SOURCE)
        assert "ATECO" in recs[0].reason or "sector" in recs[0].reason.lower()

    def test_capped_at_50_results(self):
        # Flood with 100 identical candidates — should cap at 50
        many = [dict(_CAND_SAME_SECTOR_REGION, company_id=f"c{i}", cf=f"{i:011d}") for i in range(100)]
        engine = self._engine(many)
        assert len(engine._content_based(_SOURCE)) <= 50


# ─────────────────────────────────────────────────────────────────────────────
# TestCommunityBased
# ─────────────────────────────────────────────────────────────────────────────

class TestCommunityBased:
    def _engine(self, community_rows=None, source_override=None):
        src = [source_override or _SOURCE]
        conn = _make_conn(source_rows=src, community_rows=community_rows)
        return RecommendationEngine(conn)

    def test_returns_community_neighbour(self):
        engine = self._engine(community_rows=[_CAND_COMMUNITY_MEMBER])
        recs = engine._community_based(_SOURCE)
        assert len(recs) == 1
        assert recs[0].similarity_score == COMMUNITY_DEFAULT_SCORE

    def test_reason_mentions_community(self):
        engine = self._engine(community_rows=[_CAND_COMMUNITY_MEMBER])
        recs = engine._community_based(_SOURCE)
        assert "community" in recs[0].reason.lower()

    def test_no_community_id_returns_empty(self):
        source_no_community = dict(_SOURCE, community_id=None)
        engine = self._engine(community_rows=[_CAND_COMMUNITY_MEMBER], source_override=source_no_community)
        recs = engine._community_based(source_no_community)
        assert recs == []

    def test_shared_features_includes_community(self):
        engine = self._engine(community_rows=[_CAND_COMMUNITY_MEMBER])
        recs = engine._community_based(_SOURCE)
        assert any("community" in f for f in recs[0].shared_features)


# ─────────────────────────────────────────────────────────────────────────────
# TestAnomalyBased
# ─────────────────────────────────────────────────────────────────────────────

class TestAnomalyBased:
    def _engine(self, anomaly_rows=None):
        conn = _make_conn(anomaly_rows=anomaly_rows)
        return RecommendationEngine(conn)

    def test_returns_matched_candidate(self):
        engine = self._engine(anomaly_rows=[_CAND_ANOMALY_MATCH])
        recs = engine._anomaly_based(_SOURCE)
        assert len(recs) >= 1

    def test_score_is_jaccard(self):
        engine = self._engine(anomaly_rows=[_CAND_ANOMALY_MATCH])
        recs = engine._anomaly_based(_SOURCE)
        # source flags: ["high_single_bidder_ratio", "market_dominance_high"]
        # cand flags:   ["high_single_bidder_ratio", "high_buyer_concentration"]
        # intersection: 1, union: 3  → Jaccard = 1/3
        assert abs(recs[0].similarity_score - 1 / 3) < 1e-9

    def test_no_flags_on_source_returns_empty(self):
        source_no_flags = dict(_SOURCE, anomaly_flags=[])
        conn = _make_conn(anomaly_rows=[_CAND_ANOMALY_MATCH])
        engine = RecommendationEngine(conn)
        assert engine._anomaly_based(source_no_flags) == []

    def test_shared_features_list_flags(self):
        engine = self._engine(anomaly_rows=[_CAND_ANOMALY_MATCH])
        recs = engine._anomaly_based(_SOURCE)
        assert any("flag:" in f for f in recs[0].shared_features)


# ─────────────────────────────────────────────────────────────────────────────
# TestSectorTrending
# ─────────────────────────────────────────────────────────────────────────────

class TestSectorTrending:
    def _engine(self, sector_rows=None):
        conn = _make_conn(sector_rows=sector_rows)
        return RecommendationEngine(conn)

    def test_returns_trending_company(self):
        engine = self._engine(sector_rows=[_CAND_SECTOR_TRENDING])
        recs = engine._sector_trending(_SOURCE)
        assert len(recs) == 1

    def test_similarity_score_equals_risk_score(self):
        engine = self._engine(sector_rows=[_CAND_SECTOR_TRENDING])
        recs = engine._sector_trending(_SOURCE)
        assert recs[0].similarity_score == _CAND_SECTOR_TRENDING["risk_score"]

    def test_no_ateco_returns_empty(self):
        source_no_ateco = dict(_SOURCE, ateco=None)
        engine = self._engine(sector_rows=[_CAND_SECTOR_TRENDING])
        assert engine._sector_trending(source_no_ateco) == []

    def test_reason_mentions_sector(self):
        engine = self._engine(sector_rows=[_CAND_SECTOR_TRENDING])
        recs = engine._sector_trending(_SOURCE)
        assert "sector" in recs[0].reason.lower() or "ATECO" in recs[0].reason

    def test_shared_features_include_ateco(self):
        engine = self._engine(sector_rows=[_CAND_SECTOR_TRENDING])
        recs = engine._sector_trending(_SOURCE)
        assert any("ATECO" in f for f in recs[0].shared_features)


# ─────────────────────────────────────────────────────────────────────────────
# TestRecommend (full integration — offline)
# ─────────────────────────────────────────────────────────────────────────────

class TestRecommend:
    def _engine_full(self):
        conn = _make_conn(
            content_rows=[_CAND_SAME_SECTOR_REGION],
            community_rows=[_CAND_COMMUNITY_MEMBER],
            anomaly_rows=[_CAND_ANOMALY_MATCH],
            sector_rows=[_CAND_SECTOR_TRENDING],
        )
        return RecommendationEngine(conn)

    def test_returns_recommendation_result(self):
        engine = self._engine_full()
        result = engine.recommend("src-001")
        assert isinstance(result, RecommendationResult)

    def test_source_fields_populated(self):
        engine = self._engine_full()
        result = engine.recommend("src-001")
        assert result.source_company_id == _SOURCE["company_id"]
        assert result.source_company_name == _SOURCE["company_name"]
        assert abs(result.source_risk_score - _SOURCE["risk_score"]) < 1e-6

    def test_risk_tier_correct(self):
        engine = self._engine_full()
        result = engine.recommend("src-001")
        assert result.source_risk_tier == "HIGH"

    def test_strategies_used_sorted(self):
        engine = self._engine_full()
        result = engine.recommend("src-001")
        assert result.strategies_used == sorted(result.strategies_used)

    def test_company_not_found_raises_key_error(self):
        conn = _make_conn(source_rows=[])
        engine = RecommendationEngine(conn)
        with pytest.raises(KeyError):
            engine.recommend("nonexistent")

    def test_invalid_strategy_raises_value_error(self):
        conn = _make_conn()
        engine = RecommendationEngine(conn)
        with pytest.raises(ValueError, match="Unknown strategy"):
            engine.recommend("src-001", strategies=["bogus"])

    def test_limit_respected(self):
        # Four candidates from four strategies → limit=2 → max 2 returned
        conn = _make_conn(
            content_rows=[_CAND_SAME_SECTOR_REGION],
            community_rows=[_CAND_COMMUNITY_MEMBER],
            anomaly_rows=[_CAND_ANOMALY_MATCH],
            sector_rows=[_CAND_SECTOR_TRENDING],
        )
        engine = RecommendationEngine(conn)
        result = engine.recommend("src-001", limit=2)
        assert len(result.recommendations) <= 2

    def test_min_similarity_filter(self):
        conn = _make_conn(
            content_rows=[_CAND_SAME_SECTOR_REGION],
            community_rows=[],
            anomaly_rows=[],
            sector_rows=[],
        )
        engine = RecommendationEngine(conn)
        result = engine.recommend("src-001", min_similarity=0.99, strategies=["content"])
        # CAND_SAME_SECTOR_REGION scores ~0.75, so none should survive at 0.99
        all_pass = all(r.similarity_score >= 0.99 for r in result.recommendations)
        assert all_pass

    def test_single_strategy_only(self):
        engine = self._engine_full()
        result = engine.recommend("src-001", strategies=["community"])
        # All results must come from the community strategy
        assert result.strategies_used == ["community"]
        for rec in result.recommendations:
            assert "community" in rec.strategies

    def test_source_excluded_from_recommendations(self):
        # Return the source itself as a candidate — should be filtered out
        source_as_cand = dict(_SOURCE, company_id="src-001")
        conn = _make_conn(content_rows=[source_as_cand])
        engine = RecommendationEngine(conn)
        result = engine.recommend("src-001", strategies=["content"])
        ids = [r.company_id for r in result.recommendations]
        assert "src-001" not in ids


# ─────────────────────────────────────────────────────────────────────────────
# TestRendering
# ─────────────────────────────────────────────────────────────────────────────

def _make_result(n_recs: int = 2) -> RecommendationResult:
    recs = [
        Recommendation(
            company_id=f"cand-{i:03d}",
            company_name=f"Test Company {i}",
            cf=f"{i:011d}",
            risk_score=0.5 + i * 0.1,
            similarity_score=0.8 - i * 0.1,
            reason=f"reason {i}.",
            strategies=["content"],
            shared_features=[f"ATECO:41", f"regione:Lombardia"],
        )
        for i in range(n_recs)
    ]
    return RecommendationResult(
        source_company_id="src-001",
        source_company_name="SOURCE SRL",
        source_risk_score=0.72,
        source_risk_tier="HIGH",
        recommendations=recs,
        strategies_used=["content", "community"],
    )


class TestRendering:
    def test_json_valid(self):
        result = _make_result()
        rendered = result.render("json")
        parsed = json.loads(rendered)
        assert "source_company_id" in parsed
        assert "recommendations" in parsed

    def test_json_recommendations_count(self):
        result = _make_result(3)
        parsed = json.loads(result.render("json"))
        assert len(parsed["recommendations"]) == 3

    def test_json_includes_strategies_used(self):
        result = _make_result()
        parsed = json.loads(result.render("json"))
        assert parsed["strategies_used"] == ["content", "community"]

    def test_md_contains_heading(self):
        result = _make_result()
        md = result.render("md")
        assert "# Recommendations for SOURCE SRL" in md

    def test_md_contains_company_names(self):
        result = _make_result(2)
        md = result.render("md")
        assert "Test Company 0" in md
        assert "Test Company 1" in md

    def test_md_contains_risk_badge(self):
        result = _make_result()
        md = result.render("md")
        assert "🔴" in md or "🟡" in md or "🟢" in md

    def test_text_contains_source_name(self):
        result = _make_result()
        text = result.render("text")
        assert "SOURCE SRL" in text

    def test_text_numbered_list(self):
        result = _make_result(3)
        text = result.render("text")
        assert "  1." in text
        assert "  2." in text
        assert "  3." in text

    def test_invalid_format_raises(self):
        result = _make_result()
        with pytest.raises(ValueError, match="Unknown format"):
            result.render("xlsx")


# ─────────────────────────────────────────────────────────────────────────────
# TestEdgeCases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_no_recommendations_at_all(self):
        conn = _make_conn(content_rows=[], community_rows=[], anomaly_rows=[], sector_rows=[])
        engine = RecommendationEngine(conn)
        result = engine.recommend("src-001")
        assert result.recommendations == []
        assert result.source_company_id == _SOURCE["company_id"]

    def test_as_dict_round_trip(self):
        result = _make_result(1)
        d = result.as_dict()
        assert d["source_company_id"] == "src-001"
        assert len(d["recommendations"]) == 1
        assert isinstance(d["recommendations"][0]["similarity_score"], float)

    def test_zero_risk_source(self):
        source_zero = dict(_SOURCE, risk_score=0.0, anomaly_flags=[])
        conn = _make_conn(source_rows=[source_zero], content_rows=[], community_rows=[], anomaly_rows=[], sector_rows=[])
        engine = RecommendationEngine(conn)
        result = engine.recommend("src-001")
        assert result.source_risk_score == 0.0
        assert result.source_risk_tier == "LOW"

    def test_community_only_strategy_skips_others(self):
        """community strategy should not trigger content/anomaly/sector queries."""
        call_log: List[str] = []

        def _tracking_query(cypher: str, params: Dict = None) -> List[Dict]:
            call_log.append(cypher)
            if "c.id = $cid OR c.cf = $cid" in cypher:
                return [_SOURCE]
            if "c.community_id = $cid" in cypher:
                return [_CAND_COMMUNITY_MEMBER]
            return []

        conn = MagicMock()
        conn.run_query.side_effect = _tracking_query
        engine = RecommendationEngine(conn)
        engine.recommend("src-001", strategies=["community"])

        # Verify that the content LIMIT 2000 query was NEVER called
        for cypher in call_log:
            assert "LIMIT 2000" not in cypher
