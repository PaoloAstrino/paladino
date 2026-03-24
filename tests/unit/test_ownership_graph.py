"""
Unit tests for OwnershipGraphAnalyzer.

Strategy: mock Neo4jConnection.run_query — no real database needed.
Each public method is tested with:
  1. A row that exercises the happy-path return value.
  2. An empty-result scenario that should return [] (and *not* raise).
"""

from unittest.mock import MagicMock, patch
import pytest

from paladino.analytics.ownership_graph import OwnershipGraphAnalyzer


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_analyzer(return_value=None, side_effect=None):
    conn = MagicMock()
    if side_effect is not None:
        conn.run_query.side_effect = side_effect
    else:
        conn.run_query.return_value = return_value if return_value is not None else []
    return OwnershipGraphAnalyzer(conn), conn


# ──────────────────────────────────────────────────────────────────────────────
# get_ownership_chain
# ──────────────────────────────────────────────────────────────────────────────

class TestGetOwnershipChain:

    def test_returns_rows_from_query(self):
        row = {
            "owner_type": "Company",
            "owner_name": "Holding Alfa SpA",
            "owner_cf": "12345678901",
            "hops": 1,
            "chain_names": ["Target Srl", "Holding Alfa SpA"],
        }
        analyzer, conn = _make_analyzer(return_value=[row])
        result = analyzer.get_ownership_chain("target-cf")
        assert result == [row]
        conn.run_query.assert_called_once()

    def test_returns_empty_list_when_no_data(self):
        analyzer, _ = _make_analyzer(return_value=[])
        result = analyzer.get_ownership_chain("some-cf")
        assert result == []

    def test_forwards_company_id(self):
        """max_depth is interpolated via f-string; only company_id is a param."""
        analyzer, conn = _make_analyzer(return_value=[])
        analyzer.get_ownership_chain("TEST-CF", max_depth=5)
        params = conn.run_query.call_args[0][1]
        assert params["company_id"] == "TEST-CF"
        # depth is baked into the Cypher f-string, not a separate param
        assert "max_depth" not in params


# ──────────────────────────────────────────────────────────────────────────────
# get_supply_chain
# ──────────────────────────────────────────────────────────────────────────────

class TestGetSupplyChain:

    def test_downstream_returns_rows(self):
        row = {
            "entity_type": "Company",
            "entity_name": "Sub-Appaltatore Beta Srl",
            "entity_id":   "sub-1",
            "hops":        1,
            "cig":         "CIG-ABC",
        }
        analyzer, conn = _make_analyzer(return_value=[row])
        result = analyzer.get_supply_chain("prime-cf", direction="downstream")
        assert len(result) == 1
        assert result[0]["entity_name"] == "Sub-Appaltatore Beta Srl"

    def test_upstream_direction_baked_into_cypher(self):
        """Direction is embedded in the f-string query; only company_id is a param."""
        analyzer, conn = _make_analyzer(return_value=[])
        analyzer.get_supply_chain("prime-cf", direction="upstream")
        # The Cypher string itself should contain the reversed pattern
        cypher_string = conn.run_query.call_args[0][0]
        assert "root {id: $company_id}" in cypher_string
        # For upstream the node comes before root in the pattern
        assert cypher_string.index("node") < cypher_string.index("root")

    def test_returns_empty_gracefully(self):
        analyzer, _ = _make_analyzer(return_value=[])
        result = analyzer.get_supply_chain("cf-x")
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# find_board_overlaps
# ──────────────────────────────────────────────────────────────────────────────

class TestFindBoardOverlaps:

    def test_returns_overlap_rows(self):
        row = {
            "company1":      "Rossi SpA",
            "company2":      "Verdi Srl",
            "shared_count":  3,
            "shared_persons": ["Mario Rossi"],
        }
        analyzer, conn = _make_analyzer(return_value=[row])
        result = analyzer.find_board_overlaps()
        assert len(result) == 1
        assert result[0]["shared_count"] == 3

    def test_returns_empty_when_no_represents(self):
        analyzer, _ = _make_analyzer(return_value=[])
        result = analyzer.find_board_overlaps()
        assert result == []

    def test_min_shared_forwarded(self):
        analyzer, conn = _make_analyzer(return_value=[])
        analyzer.find_board_overlaps(min_shared=4)
        params = conn.run_query.call_args[0][1]
        assert params.get("min_shared") == 4


# ──────────────────────────────────────────────────────────────────────────────
# detect_carousel_paths
# ──────────────────────────────────────────────────────────────────────────────

class TestDetectCarouselPaths:

    def test_returns_scc_based_results(self):
        row = {
            "scc_id":       7,
            "cycle_ids":    ["A", "B", "C"],
            "cycle_names":  ["A Srl", "B Srl", "C Srl"],
            "cycle_length": 3,
        }
        analyzer, conn = _make_analyzer(return_value=[row])
        result = analyzer.detect_carousel_paths()
        assert len(result) == 1
        assert result[0]["cycle_length"] == 3

    def test_empty_returns_empty_list(self):
        analyzer, _ = _make_analyzer(return_value=[])
        result = analyzer.detect_carousel_paths()
        assert result == []

    def test_length_baked_into_cypher(self):
        """min_len/max_len are f-string interpolated; only limit is a param."""
        analyzer, conn = _make_analyzer(return_value=[])
        analyzer.detect_carousel_paths(min_len=4, max_len=8)
        params = conn.run_query.call_args[0][1]
        # limit is always passed as a param
        assert "limit" in params
        # min/max are NOT separate params
        assert "min_len" not in params
        assert "max_len" not in params


# ──────────────────────────────────────────────────────────────────────────────
# score_shell_companies
# ──────────────────────────────────────────────────────────────────────────────

class TestScoreShellCompanies:

    def test_returns_scored_rows(self):
        row = {
            "company_id":    "cf-shell",
            "company_name":  "Ghost Lavori Srl",
            "tender_wins":   5,
            "employees":     1,
            "shell_score":   0.92,
        }
        analyzer, conn = _make_analyzer(return_value=[row])
        result = analyzer.score_shell_companies()
        assert len(result) == 1
        assert result[0]["shell_score"] == 0.92

    def test_empty_result_graceful(self):
        analyzer, _ = _make_analyzer(return_value=[])
        result = analyzer.score_shell_companies()
        assert result == []


# ──────────────────────────────────────────────────────────────────────────────
# get_corporate_family
# ──────────────────────────────────────────────────────────────────────────────

class TestGetCorporateFamily:

    def test_returns_structured_family(self):
        """When siblings are found the method returns a nested dict, not a list."""
        row = {
            "ubo_id":      "ubo-1",
            "ubo_name":    "Mario Rossi",
            "ubo_type":    "Person",
            "sibling_id":  "cf-sibling",
            "sibling_name": "Sibling SpA",
            "risk_score":  0.4,
        }
        analyzer, conn = _make_analyzer(return_value=[row])
        result = analyzer.get_corporate_family("root-id")
        assert isinstance(result, dict)
        assert "ubos" in result
        assert len(result["ubos"]) == 1
        assert result["ubos"][0]["ubo_name"] == "Mario Rossi"

    def test_empty_result_returns_stub_dict(self):
        """When no siblings found the method returns a stub dict (never raises)."""
        analyzer, _ = _make_analyzer(return_value=[])
        result = analyzer.get_corporate_family("solo-company")
        assert isinstance(result, dict)
        assert result["company_id"] == "solo-company"
        assert result["ubos"] == []
        assert result["siblings"] == []

    def test_company_id_forwarded(self):
        analyzer, conn = _make_analyzer(return_value=[])
        analyzer.get_corporate_family("cf-123")
        params = conn.run_query.call_args[0][1]
        assert params.get("company_id") == "cf-123"


# ──────────────────────────────────────────────────────────────────────────────
# _warn_empty  (module-level function)
# ──────────────────────────────────────────────────────────────────────────────

class TestWarnEmpty:

    def test_does_not_raise(self):
        """_warn_empty must never raise regardless of inputs."""
        from paladino.analytics.ownership_graph import _warn_empty
        _warn_empty("test_query")
        _warn_empty("test_query", reason="No REPRESENTS edges")
        _warn_empty("test_query", reason=None)

    def test_accepts_arbitrary_reason_string(self):
        from paladino.analytics.ownership_graph import _warn_empty
        # should print a panel but not raise
        _warn_empty("my_detector", reason="x" * 500)
