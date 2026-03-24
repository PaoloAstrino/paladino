"""
Unit tests for the three supply-chain / corporate-network fraud detectors.

Detectors under test
--------------------
- FraudPatternLibrary.detect_carousel_fraud
- FraudPatternLibrary.detect_board_overlap_collusion
- FraudPatternLibrary.detect_subcontractor_concentration

Strategy: mock Neo4jConnection.run_query — no real database needed.
Each detector is exercised with:
  1. A "data present" scenario where the mock returns meaningful rows.
  2. A "no data" scenario where the edge-count check returns 0.
"""

from unittest.mock import MagicMock

from paladino.analytics.fraud_patterns import FraudPatternLibrary

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_lib(side_effect=None, return_value=None):
    """Build a FraudPatternLibrary with a mocked connection."""
    conn = MagicMock()
    if side_effect is not None:
        conn.run_query.side_effect = side_effect
    elif return_value is not None:
        conn.run_query.return_value = return_value
    else:
        conn.run_query.return_value = []
    lib = FraudPatternLibrary(conn)
    lib.run_id = "test-run"
    return lib, conn


# ──────────────────────────────────────────────────────────────────────────────
# detect_carousel_fraud
# ──────────────────────────────────────────────────────────────────────────────


class TestDetectCarouselFraud:
    def _edge_check_side_effect(self, n_edges: int, scc_rows: list):
        """
        First call = edge-count check query.
        Second call = SCC query (primary path) or empty for fallback.
        Subsequent calls = fallback path query, _create_fraud_pattern_node,
        _link_entity_to_pattern, _bump_entity_risk_score.
        """
        calls = [
            [{"n": n_edges}],  # edge-count check
        ]
        if scc_rows:
            calls.append(scc_rows)  # SCC primary
        else:
            calls.append([])  # SCC primary (empty → triggers fallback)
        calls.append([])  # fallback path query
        # create_fraud_pattern_node
        calls.append([{"id": "pat-1"}])
        return iter(calls)

    def test_returns_empty_when_no_edges(self):
        lib, conn = _make_lib(side_effect=iter([[{"n": 0}]]))
        result = lib.detect_carousel_fraud()
        assert result == []

    def test_detects_cycle_via_scc(self):
        scc_row = {
            "scc_id": 42,
            "cycle_ids": ["A", "B", "C"],
            "cycle_names": ["Alfa Srl", "Beta Srl", "Gamma Srl"],
            "cycle_length": 3,
            "cigs": ["CIG1", "CIG2", "CIG3"],
        }

        def side_effect(*args, **kwargs):
            # Track call count manually
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 5}]  # edge-count check → edges exist
            if side_effect.count == 2:
                return [scc_row]  # SCC query → cycle found
            return [{"id": "pat-1"}]  # _create_fraud_pattern_node + others

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_carousel_fraud()

        assert len(result) == 1
        assert result[0]["pattern"] == "carousel_fraud"
        assert result[0]["cycle_length"] == 3
        assert "Alfa Srl" in result[0]["cycle_names"]

    def test_returns_empty_when_no_cycles_at_all(self):
        # Edge check returns > 0, but both SCC and path fallback return []
        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 10}]  # edges exist
            return []  # no cycles in either query

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_carousel_fraud()
        assert result == []

    def test_multiple_cycles_returned(self):
        cycle_a = {
            "scc_id": 1,
            "cycle_ids": ["A", "B", "C"],
            "cycle_names": ["A Srl", "B Srl", "C Srl"],
            "cycle_length": 3,
            "cigs": [],
        }
        cycle_b = {
            "scc_id": 2,
            "cycle_ids": ["D", "E", "F", "G"],
            "cycle_names": ["D Srl", "E Srl", "F Srl", "G Srl"],
            "cycle_length": 4,
            "cigs": [],
        }

        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 20}]
            if side_effect.count == 2:
                return [cycle_a, cycle_b]
            return [{"id": "pat-x"}]

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_carousel_fraud()
        assert len(result) == 2
        assert {r["cycle_length"] for r in result} == {3, 4}


# ──────────────────────────────────────────────────────────────────────────────
# detect_board_overlap_collusion
# ──────────────────────────────────────────────────────────────────────────────


class TestDetectBoardOverlapCollusion:
    def test_returns_empty_when_no_represents_edges(self):
        lib, conn = _make_lib(side_effect=iter([[{"n": 0}]]))
        result = lib.detect_board_overlap_collusion()
        assert result == []

    def test_detects_overlap(self):
        overlap_row = {
            "company1_id": "cf-1",
            "company1_name": "Rossi SpA",
            "company2_id": "cf-2",
            "company2_name": "Verdi Srl",
            "buyer_id": "ente-1",
            "buyer_name": "Comune di Milano",
            "shared_count": 2,
            "shared_names": ["Mario Rossi", "Luigi Bianchi"],
        }

        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 10}]  # REPRESENTS edges exist
            if side_effect.count == 2:
                return [overlap_row]  # main overlap query
            return [{"id": "pat-boc"}]  # _create_fraud_pattern_node + writes

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_board_overlap_collusion()

        assert len(result) == 1
        r = result[0]
        assert r["pattern"] == "board_overlap_collusion"
        assert r["company1"] == "Rossi SpA"
        assert r["company2"] == "Verdi Srl"
        assert r["shared_count"] == 2
        assert "Mario Rossi" in r["shared_persons"]

    def test_returns_empty_when_no_overlaps(self):
        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 5}]
            return []

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_board_overlap_collusion()
        assert result == []

    def test_multiple_pairs_returned(self):
        row_template = {
            "buyer_id": "b1",
            "buyer_name": "Ente",
            "shared_names": ["X"],
        }
        pairs = [
            {
                **row_template,
                "company1_id": f"c{i}",
                "company1_name": f"Azienda {i} SpA",
                "company2_id": f"c{i + 1}",
                "company2_name": f"Azienda {i + 1} Srl",
                "shared_count": 3,
            }
            for i in range(3)
        ]

        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 30}]
            if side_effect.count == 2:
                return pairs
            return [{"id": "px"}]

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_board_overlap_collusion()
        assert len(result) == 3

    def test_min_shared_param_forwarded_to_query(self):
        """BOARD_OVERLAP_MIN_SHARED constant must be forwarded to the query."""
        from paladino.constants import BOARD_OVERLAP_MIN_SHARED

        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 10}]
            return []

        lib, conn = _make_lib(side_effect=side_effect)
        lib.detect_board_overlap_collusion()

        # The second call (overlap query) must include min_shared
        calls = conn.run_query.call_args_list
        assert len(calls) >= 2
        second_call_params = calls[1][0][1]  # positional arg dict
        assert second_call_params.get("min_shared") == BOARD_OVERLAP_MIN_SHARED


# ──────────────────────────────────────────────────────────────────────────────
# detect_subcontractor_concentration
# ──────────────────────────────────────────────────────────────────────────────


class TestDetectSubcontractorConcentration:
    def test_returns_empty_when_no_edges(self):
        lib, conn = _make_lib(side_effect=iter([[{"n": 0}]]))
        result = lib.detect_subcontractor_concentration()
        assert result == []

    def test_detects_concentration(self):
        conc_row = {
            "winner_id": "w-cf",
            "winner_name": "Appalti Generali SpA",
            "sub_id": "s-cf",
            "sub_name": "Servizi Fantomatici Srl",
            "pair_count": 7,
            "concentration_ratio": 0.87,
            "cigs": [f"CIG{i}" for i in range(7)],
        }

        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 8}]  # edges exist
            if side_effect.count == 2:
                return [conc_row]  # primary window-function query
            return [{"id": "pat-sc"}]  # create+link

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_subcontractor_concentration()

        assert len(result) == 1
        r = result[0]
        assert r["pattern"] == "subcontractor_concentration"
        assert r["winner"] == "Appalti Generali SpA"
        assert r["sub"] == "Servizi Fantomatici Srl"
        assert r["pair_count"] == 7
        assert abs(r["concentration_ratio"] - 0.87) < 1e-6

    def test_returns_empty_when_no_concentration_found(self):
        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 5}]
            return []  # both primary and fallback queries return []

        lib, conn = _make_lib(side_effect=side_effect)
        result = lib.detect_subcontractor_concentration()
        assert result == []

    def test_threshold_param_forwarded(self):
        from paladino.constants import SUBCONTRACTOR_CONCENTRATION_MAX

        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 10}]
            return []

        lib, conn = _make_lib(side_effect=side_effect)
        lib.detect_subcontractor_concentration()

        calls = conn.run_query.call_args_list
        assert len(calls) >= 2
        params = calls[1][0][1]
        assert abs(params.get("threshold", -1) - SUBCONTRACTOR_CONCENTRATION_MAX) < 1e-9

    def test_high_severity_risk_bump_called(self):
        """When a detection is made, _bump_entity_risk_score must be called."""
        conc_row = {
            "winner_id": "w1",
            "winner_name": "W",
            "sub_id": "s1",
            "sub_name": "S",
            "pair_count": 5,
            "concentration_ratio": 0.9,
            "cigs": [],
        }

        def side_effect(*args, **kwargs):
            side_effect.count = getattr(side_effect, "count", 0) + 1
            if side_effect.count == 1:
                return [{"n": 5}]
            if side_effect.count == 2:
                return [conc_row]
            return [{"id": "p-x"}]

        lib, conn = _make_lib(side_effect=side_effect)

        bump_called_with = []

        def fake_bump(entity_id, label, severity):
            bump_called_with.append((entity_id, label, severity))

        lib._bump_entity_risk_score = fake_bump
        lib.detect_subcontractor_concentration()

        # Both winner and sub should have been bumped with "high"
        assert any(x[0] == "w1" and x[2] == "high" for x in bump_called_with)
        assert any(x[0] == "s1" and x[2] == "high" for x in bump_called_with)


# ──────────────────────────────────────────────────────────────────────────────
# run_all_detectors — smoke test for the extended registry
# ──────────────────────────────────────────────────────────────────────────────


class TestRunAllDetectorsExtended:
    def test_registry_contains_13_detectors(self):
        """run_all_detectors must include the 3 new supply-chain detectors."""
        lib, _ = _make_lib()
        # Temporarily replace every detect_* to a no-op to count registrations
        called = []

        class _NopDetector:
            def __init__(self, name):
                self._name = name

            def __call__(self, *a, **kw):
                called.append(self._name)
                return []

        for attr in dir(lib):
            if attr.startswith("detect_"):
                object.__setattr__(lib, attr, _NopDetector(attr))

        lib.run_all_detectors()
        assert len(called) == 13, f"Expected 13 detectors, got {len(called)}: {called}"

    def test_new_detectors_present_in_registry(self):
        lib, _ = _make_lib()
        called = []

        def _record(name):
            def _fn(*a, **kw):
                called.append(name)
                return []

            return _fn

        lib.detect_carousel_fraud = _record("carousel_fraud")
        lib.detect_board_overlap_collusion = _record("board_overlap_collusion")
        lib.detect_subcontractor_concentration = _record("subcontractor_concentration")

        # Patch remaining detectors to no-ops so we don't hit the DB
        for attr in dir(lib):
            if attr.startswith("detect_") and attr not in (
                "detect_carousel_fraud",
                "detect_board_overlap_collusion",
                "detect_subcontractor_concentration",
            ):
                object.__setattr__(lib, attr, lambda *a, **kw: [])

        lib.run_all_detectors()

        assert "carousel_fraud" in called
        assert "board_overlap_collusion" in called
        assert "subcontractor_concentration" in called
