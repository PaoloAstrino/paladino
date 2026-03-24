"""
Unit tests for paladino.analytics.temporal_analytics
=====================================================
All Neo4j calls are mocked — no live database required.

Pattern mirrors test_fraud_patterns.py: patch ``Neo4jConnection.run_query``
at the instance level via ``MagicMock``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from paladino.analytics.temporal_analytics import TemporalAnalyzer, _warn_no_dates

# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.run_query = MagicMock(return_value=[])
    return conn


@pytest.fixture
def ta(mock_conn):
    return TemporalAnalyzer(mock_conn)


# ──────────────────────────────────────────────────────────────────────
# _warn_no_dates — must never raise
# ──────────────────────────────────────────────────────────────────────


class TestWarnEmpty:
    def test_no_raise(self):
        """_warn_no_dates() must not raise for any query name."""
        _warn_no_dates("some_query")
        _warn_no_dates("")
        _warn_no_dates("a" * 200)


# ──────────────────────────────────────────────────────────────────────
# get_tender_volume_trend
# ──────────────────────────────────────────────────────────────────────


class TestGetTenderVolumeTrend:
    _MOCK_ROWS = [
        {
            "year": 2023,
            "quarter": 1,
            "tender_count": 5,
            "total_value": 100_000,
            "avg_value": 20_000,
        },
        {
            "year": 2023,
            "quarter": 2,
            "tender_count": 7,
            "total_value": 140_000,
            "avg_value": 20_000,
        },
        {
            "year": 2023,
            "quarter": 3,
            "tender_count": 12,
            "total_value": 300_000,
            "avg_value": 25_000,
        },
    ]

    def test_returns_rows(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._MOCK_ROWS
        result = ta.get_tender_volume_trend()
        assert len(result) == 3
        assert result[0]["quarter"] == 1

    def test_empty_returns_empty(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        result = ta.get_tender_volume_trend()
        assert result == []

    def test_company_id_forwarded(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_tender_volume_trend(company_id="CF001")
        call_kwargs = mock_conn.run_query.call_args
        params = call_kwargs[0][1]
        assert params.get("company_id") == "CF001"

    def test_quarters_forwarded(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_tender_volume_trend(quarters=4)
        call_kwargs = mock_conn.run_query.call_args
        params = call_kwargs[0][1]
        assert params.get("months") == 12

    def test_default_quarters_is_eight(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_tender_volume_trend()
        params = mock_conn.run_query.call_args[0][1]
        assert params.get("months") == 24  # 8 quarters × 3 months


# ──────────────────────────────────────────────────────────────────────
# get_single_bidder_trend
# ──────────────────────────────────────────────────────────────────────


class TestGetSingleBidderTrend:
    _MOCK_ROWS = [
        {
            "company_id": "CF001",
            "company_name": "Acme Costruzioni",
            "year": 2023,
            "quarter": 1,
            "total_wins": 10,
            "single_bidder_wins": 8,
            "single_bidder_ratio": 0.8,
        },
        {
            "company_id": "CF001",
            "company_name": "Acme Costruzioni",
            "year": 2023,
            "quarter": 2,
            "total_wins": 12,
            "single_bidder_wins": 12,
            "single_bidder_ratio": 1.0,
        },
    ]

    def test_returns_ratio_rows(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._MOCK_ROWS
        result = ta.get_single_bidder_trend()
        assert len(result) == 2
        assert result[1]["single_bidder_ratio"] == 1.0

    def test_empty_returns_empty(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        result = ta.get_single_bidder_trend()
        assert result == []

    def test_company_filter_applied(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_single_bidder_trend(company_id="CF001")
        query = mock_conn.run_query.call_args[0][0]
        # When company_id is given, the query should contain the company filter
        assert "company_id" in query or "$company_id" in query

    def test_quarters_param_correct(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_single_bidder_trend(quarters=6)
        params = mock_conn.run_query.call_args[0][1]
        assert params["months"] == 18


# ──────────────────────────────────────────────────────────────────────
# detect_sudden_spikes
# ──────────────────────────────────────────────────────────────────────


class TestDetectSuddenSpikes:
    """
    Spike math: latest_value > threshold × mean(prior_values)

    Setup: company CF001 has quarterly counts [2, 2, 3, 10].
    Mean of [2, 2, 3] = 2.33.  Latest = 10.  Ratio = 4.29 → spike at ×2.
    """

    _SPIKE_ROWS = [
        {
            "company_id": "CF001",
            "company_name": "Alpha",
            "year": 2022,
            "quarter": 3,
            "tender_count": 2,
            "total_value": 40_000,
        },
        {
            "company_id": "CF001",
            "company_name": "Alpha",
            "year": 2022,
            "quarter": 4,
            "tender_count": 2,
            "total_value": 40_000,
        },
        {
            "company_id": "CF001",
            "company_name": "Alpha",
            "year": 2023,
            "quarter": 1,
            "tender_count": 3,
            "total_value": 60_000,
        },
        {
            "company_id": "CF001",
            "company_name": "Alpha",
            "year": 2023,
            "quarter": 2,
            "tender_count": 10,
            "total_value": 200_000,
        },
    ]

    _FLAT_ROWS = [
        {
            "company_id": "CF002",
            "company_name": "Beta",
            "year": 2022,
            "quarter": 3,
            "tender_count": 5,
            "total_value": 100_000,
        },
        {
            "company_id": "CF002",
            "company_name": "Beta",
            "year": 2022,
            "quarter": 4,
            "tender_count": 5,
            "total_value": 100_000,
        },
        {
            "company_id": "CF002",
            "company_name": "Beta",
            "year": 2023,
            "quarter": 1,
            "tender_count": 5,
            "total_value": 100_000,
        },
        {
            "company_id": "CF002",
            "company_name": "Beta",
            "year": 2023,
            "quarter": 2,
            "tender_count": 5,
            "total_value": 100_000,
        },
    ]

    def test_spike_detected(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._SPIKE_ROWS
        result = ta.detect_sudden_spikes(metric="tender_count", threshold=2.0)
        assert len(result) == 1
        assert result[0]["company_id"] == "CF001"
        assert result[0]["spike_ratio"] > 2.0

    def test_spike_ratio_math(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._SPIKE_ROWS
        result = ta.detect_sudden_spikes(metric="tender_count", threshold=2.0)
        assert result[0]["latest_value"] == 10
        assert abs(result[0]["prior_mean"] - (2 + 2 + 3) / 3) < 0.01

    def test_flat_data_no_false_positive(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._FLAT_ROWS
        result = ta.detect_sudden_spikes(metric="tender_count", threshold=2.0)
        assert result == []

    def test_empty_input_returns_empty(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        result = ta.detect_sudden_spikes()
        assert result == []

    def test_invalid_metric_raises(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        with pytest.raises(ValueError, match="metric must be"):
            ta.detect_sudden_spikes(metric="bad_metric")

    def test_result_sorted_by_spike_ratio_desc(self, ta, mock_conn):
        # Two companies — CF001 spikes at 4×, hypothetical CF003 spikes at 3×
        rows = self._SPIKE_ROWS + [
            {
                "company_id": "CF003",
                "company_name": "Gamma",
                "year": 2022,
                "quarter": 3,
                "tender_count": 2,
                "total_value": 40_000,
            },
            {
                "company_id": "CF003",
                "company_name": "Gamma",
                "year": 2022,
                "quarter": 4,
                "tender_count": 2,
                "total_value": 40_000,
            },
            {
                "company_id": "CF003",
                "company_name": "Gamma",
                "year": 2023,
                "quarter": 1,
                "tender_count": 2,
                "total_value": 40_000,
            },
            {
                "company_id": "CF003",
                "company_name": "Gamma",
                "year": 2023,
                "quarter": 2,
                "tender_count": 7,
                "total_value": 140_000,
            },
        ]
        mock_conn.run_query.return_value = rows
        result = ta.detect_sudden_spikes(metric="tender_count", threshold=2.0)
        # CF001 spike_ratio ~4.29 > CF003 spike_ratio ~3.5
        assert result[0]["company_id"] == "CF001"
        assert result[0]["spike_ratio"] > result[1]["spike_ratio"]

    def test_limit_respected(self, ta, mock_conn):
        # Build 50 identical spike companies
        rows = []
        for i in range(50):
            cf = f"CF{i:03d}"
            for q in range(1, 5):
                rows.append(
                    {
                        "company_id": cf,
                        "company_name": f"Co{i}",
                        "year": 2023,
                        "quarter": q,
                        "tender_count": 2 if q < 4 else 100,
                        "total_value": 10_000,
                    }
                )
        mock_conn.run_query.return_value = rows
        result = ta.detect_sudden_spikes(limit=10)
        assert len(result) <= 10

    def test_value_metric_spikes(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._SPIKE_ROWS
        result = ta.detect_sudden_spikes(metric="total_value", threshold=2.0)
        assert len(result) == 1
        assert result[0]["metric"] == "total_value"


# ──────────────────────────────────────────────────────────────────────
# get_seasonal_patterns
# ──────────────────────────────────────────────────────────────────────


class TestGetSeasonalPatterns:
    _MOCK_ROWS = [
        {"month": m, "tender_count": m * 10, "total_value": m * 100_000} for m in range(1, 13)
    ]

    def test_month_names_added(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._MOCK_ROWS
        result = ta.get_seasonal_patterns(years=3)
        assert len(result) == 12
        assert result[0]["month_name"] == "Gennaio"
        assert result[11]["month_name"] == "Dicembre"

    def test_avg_per_year_computed(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._MOCK_ROWS
        result = ta.get_seasonal_patterns(years=3)
        # Month 6 → tender_count 60; avg = 60/3 = 20.0
        assert result[5]["avg_per_year"] == 20.0

    def test_empty_returns_empty(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        result = ta.get_seasonal_patterns()
        assert result == []


# ──────────────────────────────────────────────────────────────────────
# get_risk_score_history
# ──────────────────────────────────────────────────────────────────────


class TestGetRiskScoreHistory:
    _MOCK_HISTORY = [
        {
            "company_id": "CF001",
            "risk_score": 0.85,
            "change_date": "2024-01-15",
            "anomaly_flags": None,
        },
        {
            "company_id": "CF001",
            "risk_score": 0.72,
            "change_date": "2023-10-15",
            "anomaly_flags": None,
        },
        {
            "company_id": "CF001",
            "risk_score": 0.55,
            "change_date": "2023-07-15",
            "anomaly_flags": None,
        },
    ]

    def test_returns_ordered_snapshots(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._MOCK_HISTORY
        result = ta.get_risk_score_history("CF001")
        assert len(result) == 3
        # Most recent first
        assert result[0]["risk_score"] > result[1]["risk_score"]

    def test_empty_returns_empty(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        result = ta.get_risk_score_history("CF001")
        assert result == []

    def test_snapshots_param_forwarded(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_risk_score_history("CF001", snapshots=5)
        params = mock_conn.run_query.call_args[0][1]
        assert params["snapshots"] == 5

    def test_company_id_forwarded(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_risk_score_history("CF999")
        params = mock_conn.run_query.call_args[0][1]
        assert params["company_id"] == "CF999"


# ──────────────────────────────────────────────────────────────────────
# get_buyer_concentration_trend
# ──────────────────────────────────────────────────────────────────────


class TestGetBuyerConcentrationTrend:
    _MOCK_HHI = [
        {"year": 2023, "quarter": 1, "buyer_count": 3, "hhi": 0.45},
        {"year": 2023, "quarter": 2, "buyer_count": 2, "hhi": 0.62},
        {"year": 2023, "quarter": 3, "buyer_count": 1, "hhi": 1.0},
    ]

    def test_returns_hhi_rows(self, ta, mock_conn):
        # First call returns empty (window-function fallback path),
        # second call returns the mock rows (reduce path)
        mock_conn.run_query.side_effect = [[], self._MOCK_HHI]
        result = ta.get_buyer_concentration_trend("CF001")
        assert len(result) == 3
        assert result[-1]["hhi"] == 1.0

    def test_empty_returns_empty(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        result = ta.get_buyer_concentration_trend("CF001")
        assert result == []

    def test_company_id_forwarded(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_buyer_concentration_trend("CF001", quarters=4)
        params = mock_conn.run_query.call_args[0][1]
        assert params["company_id"] == "CF001"
        assert params["months"] == 12


# ──────────────────────────────────────────────────────────────────────
# get_sector_spending_volatility
# ──────────────────────────────────────────────────────────────────────


class TestGetSectorSpendingVolatility:
    _MOCK_SECTORS = [
        {
            "ateco_prefix": "C28",
            "year": 2023,
            "quarter": 1,
            "company_count": 5,
            "total_value": 500_000,
            "stddev_value": 20_000,
        },
        {
            "ateco_prefix": "C28",
            "year": 2023,
            "quarter": 2,
            "company_count": 5,
            "total_value": 750_000,
            "stddev_value": 80_000,
        },
    ]

    def test_returns_sector_rows(self, ta, mock_conn):
        mock_conn.run_query.return_value = self._MOCK_SECTORS
        result = ta.get_sector_spending_volatility("C28")
        assert len(result) == 2
        assert result[0]["company_count"] == 5

    def test_empty_returns_empty(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        result = ta.get_sector_spending_volatility("C28")
        assert result == []

    def test_ateco_prefix_forwarded(self, ta, mock_conn):
        mock_conn.run_query.return_value = []
        ta.get_sector_spending_volatility("C41")
        params = mock_conn.run_query.call_args[0][1]
        assert params["ateco_prefix"] == "C41"
