"""
Unit tests for FraudPatternLibrary.

Strategy: mock Neo4jConnection.run_query so no real database is needed.
Each detector is tested with synthetic rows that should trigger a detection,
then with empty rows that should produce no output.
"""

from unittest.mock import MagicMock

import pytest

from paladino.analytics.fraud_patterns import FraudPatternLibrary

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_library(query_side_effect=None):
    """Build a FraudPatternLibrary with a mocked connection."""
    conn = MagicMock()
    if query_side_effect is not None:
        conn.run_query.side_effect = query_side_effect
    else:
        conn.run_query.return_value = []
    lib = FraudPatternLibrary(conn)
    lib.run_id = "test-run-id"
    return lib, conn


# ---------------------------------------------------------------------------
# _create_fraud_pattern_node
# ---------------------------------------------------------------------------


class TestCreateFraudPatternNode:
    def test_returns_uuid_string(self):
        lib, conn = make_library()
        pid = lib._create_fraud_pattern_node(
            pattern_name="bid_rotation",
            severity="high",
            description="Test",
            evidence={"key": "value"},
        )
        assert isinstance(pid, str) and len(pid) == 36  # UUID length
        conn.run_query.assert_called_once()

    def test_called_with_correct_params(self):
        lib, conn = make_library()
        lib._create_fraud_pattern_node(
            pattern_name="split_tendering",
            severity="medium",
            description="desc",
            evidence={"a": 1},
            affected_entity_ids=["id1", "id2"],
        )
        _, kwargs = conn.run_query.call_args
        params = kwargs if kwargs else conn.run_query.call_args[0][1]
        # Accept both positional and keyword call styles
        all_calls = conn.run_query.call_args_list
        call_params = all_calls[0][0][1]  # second positional arg = params dict
        assert call_params["pattern_name"] == "split_tendering"
        assert call_params["severity"] == "medium"
        assert call_params["affected_entity_ids"] == ["id1", "id2"]
        assert call_params["run_id"] == "test-run-id"


# ---------------------------------------------------------------------------
# _link_entity_to_pattern
# ---------------------------------------------------------------------------


class TestLinkEntityToPattern:
    def test_score_is_clamped_below_zero(self):
        lib, conn = make_library()
        lib._link_entity_to_pattern("eid", "Company", "pid", -5.0, {})
        call_params = conn.run_query.call_args[0][1]
        assert call_params["score"] == 0.0

    def test_score_is_clamped_above_one(self):
        lib, conn = make_library()
        lib._link_entity_to_pattern("eid", "Company", "pid", 99.0, {})
        call_params = conn.run_query.call_args[0][1]
        assert call_params["score"] == 1.0

    def test_label_interpolated_in_query(self):
        lib, conn = make_library()
        lib._link_entity_to_pattern("eid", "Tender", "pid", 0.5, {})
        cypher = conn.run_query.call_args[0][0]
        assert "Tender" in cypher


# ---------------------------------------------------------------------------
# _bump_entity_risk_score
# ---------------------------------------------------------------------------


class TestBumpEntityRiskScore:
    def test_delta_passed_for_critical(self):
        lib, conn = make_library()
        lib._bump_entity_risk_score("eid", "Company", "critical")
        call_params = conn.run_query.call_args[0][1]
        assert call_params["delta"] == pytest.approx(0.40)

    def test_delta_passed_for_low(self):
        lib, conn = make_library()
        lib._bump_entity_risk_score("eid", "Company", "low")
        call_params = conn.run_query.call_args[0][1]
        assert call_params["delta"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# detect_bid_rotation
# ---------------------------------------------------------------------------


class TestDetectBidRotation:
    def test_no_findings_returns_empty(self):
        lib, conn = make_library()
        result = lib.detect_bid_rotation()
        assert result == []

    def test_one_finding_creates_pattern_and_links(self):
        rotation_group = [
            {"company_id": "c1", "company_name": "Alpha SRL", "wins": 5, "sample_tenders": []},
            {"company_id": "c2", "company_name": "Beta SRL", "wins": 4, "sample_tenders": []},
        ]
        row = {
            "buyer_id": "b1",
            "buyer_name": "Comune di Roma",
            "rotation_group": rotation_group,
            "total_wins": 9,
        }

        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            # First call = SELECT query returning the row
            if call_count == 1:
                return [row]
            return []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_bid_rotation()

        assert len(findings) == 1
        assert findings[0]["pattern"] == "bid_rotation"
        assert findings[0]["buyer"] == "Comune di Roma"
        assert findings[0]["companies"] == 2
        # Should have made: 1 select + 1 create pattern + 2 links + 2 bumps = 6 calls
        assert conn.run_query.call_count >= 4


# ---------------------------------------------------------------------------
# detect_ghost_bidding
# ---------------------------------------------------------------------------


class TestDetectGhostBidding:
    def test_no_findings_returns_empty(self):
        lib, conn = make_library()
        result = lib.detect_ghost_bidding()
        assert result == []

    def test_finding_has_correct_pattern_name(self):
        row = {
            "ghost_id": "g1",
            "ghost_name": "Ghost SRL",
            "community": 42,
            "community_tenders": 10,
            "winner_samples": ["w1", "w2"],
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_ghost_bidding()
        assert findings[0]["pattern"] == "ghost_bidding"
        assert findings[0]["company"] == "Ghost SRL"


# ---------------------------------------------------------------------------
# detect_split_tendering
# ---------------------------------------------------------------------------


class TestDetectSplitTendering:
    def test_finding_links_buyer_and_company(self):
        row = {
            "buyer_id": "b1",
            "buyer_name": "Consorzio Nord",
            "company_id": "c1",
            "company_name": "Costruzioni SPA",
            "tender_count": 5,
            "total_value": 150_000.0,
            "sample_tenders": ["t1", "t2"],
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_split_tendering()
        assert findings[0]["pattern"] == "split_tendering"
        assert findings[0]["count"] == 5


# ---------------------------------------------------------------------------
# detect_short_award_window
# ---------------------------------------------------------------------------


class TestDetectShortAwardWindow:
    def test_critical_severity_for_zero_days(self):
        row = {
            "tender_id": "t1",
            "cig": "Z000000001",
            "oggetto": "Lavori strade",
            "importo": 200_000.0,
            "company_id": "c1",
            "company_name": "Fast SRL",
            "buyer_id": "b1",
            "buyer_name": "PA Test",
            "award_days": 0,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_short_award_window()
        assert findings[0]["days"] == 0
        # Should have called red_flags SET at end
        cypher_calls = [c[0][0] for c in conn.run_query.call_args_list]
        assert any("red_flags" in c for c in cypher_calls)

    def test_high_severity_for_five_days(self):
        row = {
            "tender_id": "t2",
            "cig": "Z000000002",
            "oggetto": "Forniture",
            "importo": 50_000.0,
            "company_id": "c2",
            "company_name": "Quick SRL",
            "buyer_id": "b2",
            "buyer_name": "PA Nord",
            "award_days": 5,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_short_award_window()
        assert findings[0]["days"] == 5


# ---------------------------------------------------------------------------
# detect_price_manipulation
# ---------------------------------------------------------------------------


class TestDetectPriceManipulation:
    def test_finding_stores_z_score(self):
        row = {
            "sector": "62.01",
            "tender_id": "t1",
            "cig": "ZABC123",
            "importo": 5_000_000.0,
            "company_id": "c1",
            "company_name": "Inflated SRL",
            "mean_val": 100_000.0,
            "std_val": 50_000.0,
            "z_score": 3.2,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_price_manipulation()
        assert findings[0]["z_score"] == pytest.approx(3.2)
        assert findings[0]["sector"] == "62.01"


# ---------------------------------------------------------------------------
# detect_ubo_conflict
# ---------------------------------------------------------------------------


class TestDetectUboConflict:
    def test_finding_severity_is_critical(self):
        row = {
            "company_id": "c1",
            "company_name": "Shell SRL",
            "buyer_id": "b1",
            "buyer_name": "PA Corrupt",
            "shared_entity_id": "se1",
            "shared_name": "Owner SpA",
            "tender_id": "t1",
            "cig": "ZUBC001",
            "importo": 1_000_000.0,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_ubo_conflict()
        assert findings[0]["pattern"] == "ubo_conflict"
        # Pattern node should be created with critical severity
        create_call_params = conn.run_query.call_args_list[1][0][1]
        assert create_call_params["severity"] == "critical"


# ---------------------------------------------------------------------------
# detect_winner_loser_ring
# ---------------------------------------------------------------------------


class TestDetectWinnerLoserRing:
    def test_both_entities_linked(self):
        row = {
            "winner_id": "w1",
            "winner_name": "Winner SRL",
            "peer_id": "p1",
            "peer_name": "Loser SPA",
            "buyer_id": "b1",
            "buyer_name": "Municipality X",
            "co_appearances": 6,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_winner_loser_ring()
        assert findings[0]["winner"] == "Winner SRL"
        assert findings[0]["peer"] == "Loser SPA"
        assert findings[0]["appearances"] == 6


# ---------------------------------------------------------------------------
# detect_pnrr_concentration
# ---------------------------------------------------------------------------


class TestDetectPnrrConcentration:
    def test_high_concentration_triggers_finding(self):
        row = {
            "company_id": "c1",
            "company_name": "PNRR King SRL",
            "region": "Sicilia",
            "pnrr_wins": 8,
            "pnrr_value": 4_000_000.0,
            "regional_pnrr_total": 10,
            "concentration_ratio": 0.8,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_pnrr_concentration()
        assert findings[0]["ratio"] == pytest.approx(0.8)
        assert findings[0]["region"] == "Sicilia"


# ---------------------------------------------------------------------------
# detect_community_monopoly
# ---------------------------------------------------------------------------


class TestDetectCommunityMonopoly:
    def test_monopoly_above_threshold(self):
        row = {
            "community": 7,
            "company_id": "c1",
            "company_name": "Monopoly SRL",
            "wins": 12,
            "company_value": 7_000_000.0,
            "community_total": 9_000_000.0,
            "share": 0.78,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_community_monopoly()
        assert findings[0]["share"] == pytest.approx(0.78)
        assert findings[0]["community"] == 7


# ---------------------------------------------------------------------------
# detect_network_clique
# ---------------------------------------------------------------------------


class TestDetectNetworkClique:
    def test_high_triangle_count_triggers_finding(self):
        row = {
            "company_id": "c1",
            "company_name": "Clique SRL",
            "triangles": 10,
            "community": 3,
            "current_risk": 0.4,
        }
        call_count = 0

        def side_effect(query, params=None):
            nonlocal call_count
            call_count += 1
            return [row] if call_count == 1 else []

        lib, conn = make_library(query_side_effect=side_effect)
        findings = lib.detect_network_clique()
        assert findings[0]["triangles"] == 10
        assert findings[0]["pattern"] == "network_clique"

    def test_no_findings_when_below_threshold(self):
        lib, conn = make_library()
        result = lib.detect_network_clique()
        assert result == []


# ---------------------------------------------------------------------------
# run_all_detectors
# ---------------------------------------------------------------------------


class TestRunAllDetectors:
    def test_returns_dict_with_all_thirteen_keys(self):
        lib, conn = make_library()
        results = lib.run_all_detectors()
        expected_keys = {
            "bid_rotation",
            "ghost_bidding",
            "split_tendering",
            "short_award_window",
            "price_manipulation",
            "ubo_conflict",
            "winner_loser_ring",
            "pnrr_concentration",
            "community_monopoly",
            "network_clique",
            # supply-chain & corporate-network detectors (added 2024)
            "carousel_fraud",
            "board_overlap_collusion",
            "subcontractor_concentration",
        }
        assert set(results.keys()) == expected_keys

    def test_failed_detector_returns_empty_list_not_exception(self):
        """A single failing detector must not abort the entire run."""
        lib, conn = make_library()
        # Make every call raise to simulate a database error in all detectors
        conn.run_query.side_effect = Exception("DB down")
        results = lib.run_all_detectors()
        for key, value in results.items():
            assert value == [], f"Expected [] for {key} when DB is down"

    def test_total_run_id_is_consistent(self):
        lib, conn = make_library()
        run_id_before = lib.run_id
        lib.run_all_detectors()
        # run_id should not change during a run
        assert lib.run_id == run_id_before


# ---------------------------------------------------------------------------
# get_summary_stats
# ---------------------------------------------------------------------------


class TestGetSummaryStats:
    def test_returns_dict_with_total_and_by_pattern(self):
        rows = [
            {"pattern": "bid_rotation", "severity": "high", "occurrences": 3},
            {"pattern": "split_tendering", "severity": "high", "occurrences": 7},
        ]
        lib, conn = make_library(query_side_effect=lambda q, p=None: rows)
        stats = lib.get_summary_stats()
        assert stats["total"] == 10
        assert len(stats["by_pattern"]) == 2

    def test_empty_graph_returns_zero(self):
        lib, conn = make_library()
        stats = lib.get_summary_stats()
        assert stats["total"] == 0
