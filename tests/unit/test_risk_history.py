"""
Unit tests for Risk Score History Tracking
==========================================
Tests for risk history, trend analysis, and dashboard functionality.
All Neo4j calls are mocked — no live database required.

Tests cover:
- Risk tier classification
- Trend calculation (delta, direction, volatility)
- Risk distribution over time
- Companies with risk changes
- API endpoints
- Edge cases (no history, single snapshot)
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from paladino.analytics.temporal_analytics import TemporalAnalyzer
from paladino.models import (
    RiskTier,
    RiskSnapshot,
    RiskTrendAnalysis,
    RiskDistribution,
    RiskChangeItem,
    RiskDashboardResponse,
    RiskHistoryResponse,
    RiskTrendResponse,
    TrendDirection,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_conn():
    """Create a mocked Neo4j connection."""
    conn = MagicMock()
    conn.run_query = MagicMock(return_value=[])
    conn.close = MagicMock()
    return conn


@pytest.fixture
def ta(mock_conn):
    """Create a TemporalAnalyzer with mocked connection."""
    return TemporalAnalyzer(mock_conn)


# =============================================================================
# Risk Tier Classification Tests
# =============================================================================


class TestRiskTierClassification:
    """Test risk tier classification logic."""

    def test_high_risk_threshold(self):
        """Scores >= 0.7 should be HIGH."""
        assert RiskTier.from_score(0.7) == RiskTier.HIGH
        assert RiskTier.from_score(0.85) == RiskTier.HIGH
        assert RiskTier.from_score(1.0) == RiskTier.HIGH

    def test_medium_risk_threshold(self):
        """Scores 0.4-0.69 should be MEDIUM."""
        assert RiskTier.from_score(0.4) == RiskTier.MEDIUM
        assert RiskTier.from_score(0.55) == RiskTier.MEDIUM
        assert RiskTier.from_score(0.69) == RiskTier.MEDIUM

    def test_low_risk_threshold(self):
        """Scores < 0.4 should be LOW."""
        assert RiskTier.from_score(0.39) == RiskTier.LOW
        assert RiskTier.from_score(0.1) == RiskTier.LOW
        assert RiskTier.from_score(0.0) == RiskTier.LOW

    def test_boundary_values(self):
        """Test exact boundary values."""
        # Exactly at boundaries
        assert RiskTier.from_score(0.7) == RiskTier.HIGH
        assert RiskTier.from_score(0.4) == RiskTier.MEDIUM
        # Just below boundaries
        assert RiskTier.from_score(0.699) == RiskTier.MEDIUM
        assert RiskTier.from_score(0.399) == RiskTier.LOW


# =============================================================================
# RiskSnapshot Model Tests
# =============================================================================


class TestRiskSnapshotModel:
    """Test RiskSnapshot Pydantic model."""

    def test_valid_snapshot(self):
        """Test creating a valid snapshot."""
        snapshot = RiskSnapshot(
            company_id="uuid-123",
            company_name="Test Company",
            risk_score=0.75,
            risk_tier=RiskTier.HIGH,
            change_date=datetime(2024, 1, 15),
            anomaly_flags=["high_single_bidder_ratio"],
        )
        assert snapshot.risk_score == 0.75
        assert snapshot.risk_tier == RiskTier.HIGH

    def test_auto_correct_tier(self):
        """Test that tier is auto-corrected if mismatched."""
        # Provide wrong tier - should be corrected
        snapshot = RiskSnapshot(
            company_id="uuid-123",
            risk_score=0.8,
            risk_tier=RiskTier.LOW,  # Wrong tier
            change_date=datetime(2024, 1, 15),
        )
        # Validator should correct to HIGH
        assert snapshot.risk_tier == RiskTier.HIGH

    def test_snapshot_with_null_flags(self):
        """Test snapshot with null anomaly flags."""
        snapshot = RiskSnapshot(
            company_id="uuid-123",
            risk_score=0.5,
            risk_tier=RiskTier.MEDIUM,
            change_date=datetime(2024, 1, 15),
        )
        assert snapshot.anomaly_flags == []


# =============================================================================
# get_risk_trend_analysis Tests
# =============================================================================


class TestGetRiskTrendAnalysis:
    """Test risk trend analysis calculations."""

    _MOCK_HISTORY = [
        {"company_id": "CF001", "risk_score": 0.85, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
        {"company_id": "CF001", "risk_score": 0.72, "change_date": datetime(2023, 10, 15), "anomaly_flags": None},
        {"company_id": "CF001", "risk_score": 0.55, "change_date": datetime(2023, 7, 15), "anomaly_flags": None},
        {"company_id": "CF001", "risk_score": 0.45, "change_date": datetime(2023, 4, 15), "anomaly_flags": None},
    ]

    def test_trend_increasing(self, ta, mock_conn):
        """Test detection of increasing trend."""
        mock_conn.run_query.side_effect = [
            self._MOCK_HISTORY,  # get_risk_score_history
            [{"name": "Test Company"}],  # company name
        ]
        result = ta.get_risk_trend_analysis("CF001")

        assert result["direction"] == "increasing"
        assert result["delta"] > 0
        assert result["current_score"] == 0.85
        assert result["current_tier"] == "high"

    def test_trend_decreasing(self, ta, mock_conn):
        """Test detection of decreasing trend."""
        decreasing_history = [
            {"company_id": "CF002", "risk_score": 0.3, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
            {"company_id": "CF002", "risk_score": 0.5, "change_date": datetime(2023, 10, 15), "anomaly_flags": None},
            {"company_id": "CF002", "risk_score": 0.7, "change_date": datetime(2023, 7, 15), "anomaly_flags": None},
        ]
        mock_conn.run_query.side_effect = [
            decreasing_history,
            [{"name": "Decreasing Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF002")

        assert result["direction"] == "decreasing"
        assert result["delta"] < 0

    def test_trend_stable(self, ta, mock_conn):
        """Test detection of stable trend."""
        stable_history = [
            {"company_id": "CF003", "risk_score": 0.5, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
            {"company_id": "CF003", "risk_score": 0.48, "change_date": datetime(2023, 10, 15), "anomaly_flags": None},
            {"company_id": "CF003", "risk_score": 0.52, "change_date": datetime(2023, 7, 15), "anomaly_flags": None},
        ]
        mock_conn.run_query.side_effect = [
            stable_history,
            [{"name": "Stable Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF003")

        assert result["direction"] == "stable"

    def test_volatility_calculation(self, ta, mock_conn):
        """Test volatility (standard deviation) calculation."""
        mock_conn.run_query.side_effect = [
            self._MOCK_HISTORY,
            [{"name": "Test Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF001")

        # Scores: [0.45, 0.55, 0.72, 0.85] - should have non-zero volatility
        assert result["volatility"] > 0
        assert isinstance(result["volatility"], float)

    def test_tier_crossing_detected(self, ta, mock_conn):
        """Test detection of tier boundary crossing."""
        # Company crosses from medium to high
        crossing_history = [
            {"company_id": "CF004", "risk_score": 0.75, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
            {"company_id": "CF004", "risk_score": 0.65, "change_date": datetime(2023, 10, 15), "anomaly_flags": None},
        ]
        mock_conn.run_query.side_effect = [
            crossing_history,
            [{"name": "Crossing Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF004")

        assert result["tier_crossed"] is True
        assert result["current_tier"] == "high"
        assert result["previous_tier"] == "medium"

    def test_significant_increase_flag(self, ta, mock_conn):
        """Test significant increase flag (delta > 0.3)."""
        # Large increase from 0.4 to 0.85
        large_increase = [
            {"company_id": "CF005", "risk_score": 0.85, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
            {"company_id": "CF005", "risk_score": 0.6, "change_date": datetime(2023, 10, 15), "anomaly_flags": None},
            {"company_id": "CF005", "risk_score": 0.4, "change_date": datetime(2023, 7, 15), "anomaly_flags": None},
        ]
        mock_conn.run_query.side_effect = [
            large_increase,
            [{"name": "Big Increase Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF005")

        assert result["significant_increase"] is True
        assert result["delta"] > 0.3

    def test_no_history_returns_defaults(self, ta, mock_conn):
        """Test behavior when no history exists."""
        mock_conn.run_query.return_value = []
        result = ta.get_risk_trend_analysis("CF999")

        assert result["snapshots_count"] == 0
        assert result["current_score"] is None
        assert result["direction"] == "stable"
        assert result["volatility"] == 0.0

    def test_single_snapshot_handling(self, ta, mock_conn):
        """Test behavior with only one snapshot."""
        single_history = [
            {"company_id": "CF006", "risk_score": 0.5, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
        ]
        mock_conn.run_query.side_effect = [
            single_history,
            [{"name": "Single Snapshot Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF006")

        assert result["snapshots_count"] == 1
        # With single snapshot, previous_score equals current (oldest = newest)
        assert result["previous_score"] == 0.5
        assert result["volatility"] == 0.0  # Can't calculate stdev with 1 sample


# =============================================================================
# get_risk_distribution_over_time Tests
# =============================================================================


class TestGetRiskDistributionOverTime:
    """Test risk distribution over time calculations."""

    _MOCK_DISTRIBUTION = [
        {
            "period": "2023-Q3",
            "year": 2023,
            "quarter": 3,
            "high_risk_count": 15,
            "medium_risk_count": 30,
            "low_risk_count": 55,
            "total_companies": 100,
            "avg_risk_score": 0.42,
            "median_risk_score": 0.38,
            "stddev_risk_score": 0.21,
            "high_risk_percent": 15.0,
            "medium_risk_percent": 30.0,
            "low_risk_percent": 55.0,
        },
        {
            "period": "2023-Q4",
            "year": 2023,
            "quarter": 4,
            "high_risk_count": 20,
            "medium_risk_count": 35,
            "low_risk_count": 45,
            "total_companies": 100,
            "avg_risk_score": 0.48,
            "median_risk_score": 0.45,
            "stddev_risk_score": 0.23,
            "high_risk_percent": 20.0,
            "medium_risk_percent": 35.0,
            "low_risk_percent": 45.0,
        },
    ]

    def test_returns_distribution_rows(self, ta, mock_conn):
        """Test that distribution data is returned correctly."""
        mock_conn.run_query.return_value = self._MOCK_DISTRIBUTION
        result = ta.get_risk_distribution_over_time(quarters=8)

        assert len(result) == 2
        assert result[0]["period"] == "2023-Q3"
        assert result[1]["high_risk_count"] == 20

    def test_empty_returns_empty(self, ta, mock_conn):
        """Test behavior when no distribution data exists."""
        mock_conn.run_query.return_value = []
        result = ta.get_risk_distribution_over_time()

        assert result == []

    def test_percentages_sum_to_100(self, ta, mock_conn):
        """Test that tier percentages sum to approximately 100."""
        mock_conn.run_query.return_value = self._MOCK_DISTRIBUTION
        result = ta.get_risk_distribution_over_time()

        for row in result:
            total_percent = (
                row["high_risk_percent"] + row["medium_risk_percent"] + row["low_risk_percent"]
            )
            assert abs(total_percent - 100.0) < 0.1  # Allow for rounding


# =============================================================================
# get_companies_with_risk_changes Tests
# =============================================================================


class TestGetCompaniesWithRiskChanges:
    """Test companies with risk changes detection."""

    _MOCK_CHANGES = [
        {
            "company_id": "CF001",
            "company_name": "Big Increase Co",
            "region": "Lombardia",
            "ateco": "64.99",
            "old_score": 0.35,
            "new_score": 0.75,
            "delta": 0.4,
            "old_tier": "low",
            "new_tier": "high",
        },
        {
            "company_id": "CF002",
            "company_name": "Moderate Increase Co",
            "region": "Lazio",
            "ateco": "41.20",
            "old_score": 0.5,
            "new_score": 0.7,
            "delta": 0.2,
            "old_tier": "medium",
            "new_tier": "high",
        },
        {
            "company_id": "CF003",
            "company_name": "Big Decrease Co",
            "region": "Veneto",
            "ateco": "68.10",
            "old_score": 0.8,
            "new_score": 0.4,
            "delta": -0.4,
            "old_tier": "high",
            "new_tier": "medium",
        },
    ]

    def test_increases_detected(self, ta, mock_conn):
        """Test detection of risk increases."""
        mock_conn.run_query.return_value = self._MOCK_CHANGES
        result = ta.get_companies_with_risk_changes()

        assert len(result["increases"]) == 2
        assert result["increases"][0]["delta"] > 0

    def test_decreases_detected(self, ta, mock_conn):
        """Test detection of risk decreases."""
        mock_conn.run_query.return_value = self._MOCK_CHANGES
        result = ta.get_companies_with_risk_changes()

        assert len(result["decreases"]) == 1
        assert result["decreases"][0]["delta"] < 0

    def test_critical_alerts_detected(self, ta, mock_conn):
        """Test detection of critical alerts (delta > 0.3)."""
        mock_conn.run_query.return_value = self._MOCK_CHANGES
        result = ta.get_companies_with_risk_changes()

        # CF001 has delta 0.4 > 0.3
        assert len(result["critical_alerts"]) >= 1
        assert result["critical_alerts"][0]["severity"] == "critical"

    def test_tier_crossings_detected(self, ta, mock_conn):
        """Test detection of tier crossings."""
        mock_conn.run_query.return_value = self._MOCK_CHANGES
        result = ta.get_companies_with_risk_changes()

        # Both CF001 and CF003 crossed tiers
        assert len(result["tier_crossings"]) >= 2

    def test_empty_returns_empty(self, ta, mock_conn):
        """Test behavior when no changes found."""
        mock_conn.run_query.return_value = []
        result = ta.get_companies_with_risk_changes()

        assert result["increases"] == []
        assert result["decreases"] == []
        assert result["critical_alerts"] == []
        assert result["tier_crossings"] == []

    def test_respects_min_delta(self, ta, mock_conn):
        """Test that min_delta filter is applied."""
        small_changes = [
            {
                "company_id": "CF004",
                "company_name": "Small Change Co",
                "region": None,
                "ateco": None,
                "old_score": 0.5,
                "new_score": 0.55,
                "delta": 0.05,
                "old_tier": "medium",
                "new_tier": "medium",
            },
        ]
        # With default min_delta=0.1, the query should filter out small changes
        # The SQL query has WHERE abs(new_score - old_score) >= $min_delta
        # So we need to return empty when min_delta=0.1 and delta=0.05
        mock_conn.run_query.return_value = []  # Query filters it out
        result = ta.get_companies_with_risk_changes(min_delta=0.1)
        assert result["increases"] == []

        # With min_delta=0.01, should be included
        mock_conn.run_query.return_value = small_changes
        result = ta.get_companies_with_risk_changes(min_delta=0.01)
        assert len(result["increases"]) == 1

    def test_respects_limit(self, ta, mock_conn):
        """Test that limit parameter is respected."""
        # Create 50 companies with increases
        many_changes = []
        for i in range(50):
            many_changes.append({
                "company_id": f"CF{i:03d}",
                "company_name": f"Company {i}",
                "region": "Lombardia",
                "ateco": "64.99",
                "old_score": 0.3,
                "new_score": 0.5,
                "delta": 0.2,
                "old_tier": "low",
                "new_tier": "medium",
            })

        mock_conn.run_query.return_value = many_changes
        result = ta.get_companies_with_risk_changes(limit=10)

        assert len(result["increases"]) <= 10


# =============================================================================
# RiskTrendAnalysis Model Tests
# =============================================================================


class TestRiskTrendAnalysisModel:
    """Test RiskTrendAnalysis Pydantic model."""

    def test_valid_trend_analysis(self):
        """Test creating a valid trend analysis."""
        trend = RiskTrendAnalysis(
            company_id="uuid-123",
            company_name="Test Company",
            current_score=0.75,
            current_tier=RiskTier.HIGH,
            previous_score=0.55,
            previous_tier=RiskTier.MEDIUM,
            delta=0.2,
            delta_percent=36.36,
            direction=TrendDirection.INCREASING,
            volatility=0.15,
            max_score=0.8,
            min_score=0.5,
            tier_crossed=True,
            significant_increase=False,
            snapshots_count=4,
        )
        assert trend.delta == 0.2
        assert trend.tier_crossed is True
        assert trend.direction == TrendDirection.INCREASING


# =============================================================================
# RiskDistribution Model Tests
# =============================================================================


class TestRiskDistributionModel:
    """Test RiskDistribution Pydantic model."""

    def test_valid_distribution(self):
        """Test creating a valid distribution."""
        dist = RiskDistribution(
            period="2024-Q1",
            year=2024,
            quarter=1,
            high_risk_count=25,
            medium_risk_count=50,
            low_risk_count=125,
            total_companies=200,
            avg_risk_score=0.42,
            median_risk_score=0.38,
            stddev_risk_score=0.21,
            high_risk_percent=12.5,
            medium_risk_percent=25.0,
            low_risk_percent=62.5,
        )
        assert dist.total_companies == 200
        assert dist.high_risk_percent == 12.5


# =============================================================================
# RiskChangeItem Model Tests
# =============================================================================


class TestRiskChangeItemModel:
    """Test RiskChangeItem Pydantic model."""

    def test_increase_item(self):
        """Test risk increase item."""
        item = RiskChangeItem(
            company_id="uuid-123",
            company_name="Increasing Co",
            region="Lombardia",
            ateco="64.99",
            old_score=0.35,
            new_score=0.75,
            delta=0.4,
            old_tier=RiskTier.LOW,
            new_tier=RiskTier.HIGH,
            tier_crossed=True,
            change_type="increase",
            severity="critical",
        )
        assert item.change_type == "increase"
        assert item.severity == "critical"
        assert item.tier_crossed is True

    def test_decrease_item(self):
        """Test risk decrease item."""
        item = RiskChangeItem(
            company_id="uuid-456",
            company_name="Decreasing Co",
            region="Lazio",
            ateco="41.20",
            old_score=0.8,
            new_score=0.4,
            delta=-0.4,
            old_tier=RiskTier.HIGH,
            new_tier=RiskTier.MEDIUM,
            tier_crossed=True,
            change_type="decrease",
            severity="critical",
        )
        assert item.change_type == "decrease"
        assert item.tier_crossed is True


# =============================================================================
# RiskDashboardResponse Model Tests
# =============================================================================


class TestRiskDashboardResponseModel:
    """Test RiskDashboardResponse Pydantic model."""

    def test_valid_dashboard(self):
        """Test creating a valid dashboard response."""
        dashboard = RiskDashboardResponse(
            total_companies=500,
            companies_with_risk=350,
            high_risk_count=50,
            medium_risk_count=100,
            low_risk_count=200,
            distribution_history=[],
            biggest_increases=[],
            biggest_decreases=[],
            critical_alerts=[],
            tier_crossings=[],
        )
        assert dashboard.total_companies == 500
        assert dashboard.companies_with_risk == 350


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_zero_risk_score(self, ta, mock_conn):
        """Test handling of zero risk score."""
        zero_history = [
            {"company_id": "CF001", "risk_score": 0.0, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
        ]
        mock_conn.run_query.side_effect = [
            zero_history,
            [{"name": "Zero Risk Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF001")

        assert result["current_score"] == 0.0
        assert result["current_tier"] == "low"

    def test_null_anomaly_flags(self, ta, mock_conn):
        """Test handling of null anomaly flags."""
        history_with_nulls = [
            {"company_id": "CF001", "risk_score": 0.5, "change_date": datetime(2024, 1, 15), "anomaly_flags": None},
            {"company_id": "CF001", "risk_score": 0.4, "change_date": datetime(2023, 10, 15), "anomaly_flags": None},
        ]
        mock_conn.run_query.side_effect = [
            history_with_nulls,
            [{"name": "Test Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF001")

        assert result["snapshots_count"] == 2

    def test_string_anomaly_flags(self, ta, mock_conn):
        """Test handling of string anomaly flags (single value)."""
        history_with_string = [
            {"company_id": "CF001", "risk_score": 0.5, "change_date": datetime(2024, 1, 15), "anomaly_flags": "flag1"},
        ]
        mock_conn.run_query.side_effect = [
            history_with_string,
            [{"name": "Test Company"}],
        ]
        result = ta.get_risk_trend_analysis("CF001")

        assert result["snapshots_count"] == 1
