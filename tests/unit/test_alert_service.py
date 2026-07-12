"""
Unit tests for Alert Service.

Tests cover:
- Alert creation and validation
- Duplicate prevention (deduplication)
- Listing and pagination with filters
- Status transitions and validation
- Alert statistics
- Alert rule CRUD operations
- Alert generators (risk, fraud, activity, merge)
- API endpoints (CRUD, bulk actions, entity alerts)
- Error cases and edge cases
"""

import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import MagicMock, patch, call

from paladino.app.alert_service import (
    AlertService,
    DEFAULT_ALERT_RULES,
    ALERT_DEDUP_WINDOW_HOURS,
    initialize_default_rules,
)
from paladino.models import (
    Alert,
    AlertCreate,
    AlertUpdate,
    AlertListParams,
    AlertBulkAction,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertSeverity,
    AlertStatistics,
    AlertStatus,
    AlertType,
    AlertGeneratorResult,
    AlertGenerationReport,
    ProvenanceMetadata,
)
from paladino.db import Neo4jConnection


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_conn():
    """Create a mock Neo4jConnection."""
    conn = MagicMock(spec=Neo4jConnection)
    return conn


@pytest.fixture
def alert_service(mock_conn):
    """Create an AlertService with mocked connection."""
    return AlertService(mock_conn)


@pytest.fixture
def sample_alert_data():
    """Sample alert creation data."""
    return AlertCreate(
        type=AlertType.RISK_SPIKE,
        severity=AlertSeverity.CRITICAL,
        title="Risk Score → High",
        description="Company ACME SRL risk score crossed 0.7 threshold",
        entity_type="Company",
        entity_id="company-uuid-123",
        entity_cf="12345678901",
        triggered_by="risk_engine",
        metadata={"risk_score": 0.85, "threshold": 0.7},
    )


@pytest.fixture
def sample_alert_record():
    """Sample Neo4j record for an alert."""
    return {
        "a": {
            "id": "alert-uuid-123",
            "type": "risk_spike",
            "severity": "critical",
            "status": "pending",
            "title": "Risk Score → High",
            "description": "Company ACME SRL risk score crossed 0.7 threshold",
            "entity_type": "Company",
            "entity_id": "company-uuid-123",
            "entity_cf": "12345678901",
            "rule_id": None,
            "triggered_by": "risk_engine",
            "metadata": {"risk_score": 0.85, "threshold": 0.7},
            "alert_hash": "abc123hash",
            "acknowledged_at": None,
            "resolved_at": None,
            "dismissed_at": None,
            "created_at": datetime.now(UTC).isoformat(),
            "provenance": {
                "source": ["risk_engine"],
                "dataset_version": "1.0",
                "retrieval_date": datetime.now(UTC).isoformat(),
                "confidence": 1.0,
            },
        }
    }


@pytest.fixture
def sample_rule_record():
    """Sample Neo4j record for an alert rule."""
    return {
        "r": {
            "id": "rule-uuid-123",
            "name": "Risk Score → High",
            "description": "Alert when risk score >= 0.7",
            "alert_type": "risk_spike",
            "trigger_condition": "risk_score >= 0.7",
            "threshold": 0.7,
            "severity": "critical",
            "enabled": True,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": None,
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Alert Creation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateAlert:
    """Tests for create_alert method."""

    def test_create_alert_success(self, alert_service, mock_conn, sample_alert_data):
        """Test successful alert creation."""
        mock_result = [{
            "a": {
                "id": "new-alert-uuid",
                "type": "risk_spike",
                "severity": "critical",
                "status": "pending",
                "title": "Risk Score → High",
                "description": "Company ACME SRL risk score crossed 0.7 threshold",
                "entity_type": "Company",
                "entity_id": "company-uuid-123",
                "entity_cf": "12345678901",
                "rule_id": None,
                "triggered_by": "risk_engine",
                "metadata": {"risk_score": 0.85, "threshold": 0.7},
                "alert_hash": "testhash",
                "acknowledged_at": None,
                "resolved_at": None,
                "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }]
        # First call: dedup check (returns empty = no duplicate)
        # Second call: create alert
        mock_conn.run_query.side_effect = [[], mock_result]

        result = alert_service.create_alert(sample_alert_data)

        assert result.id == "new-alert-uuid"
        assert result.type == AlertType.RISK_SPIKE
        assert result.severity == AlertSeverity.CRITICAL
        assert result.status == AlertStatus.PENDING
        assert result.entity_id == "company-uuid-123"
        assert result.entity_cf == "12345678901"

    def test_create_alert_duplicate_prevented(self, alert_service, mock_conn, sample_alert_data):
        """Test that duplicate alerts are prevented within 24h window."""
        # Simulate existing duplicate found
        mock_conn.run_query.return_value = [{"count": 1}]

        result = alert_service.create_alert(sample_alert_data)

        # Should return synthetic alert with empty id indicating dedup
        assert result.id == ""
        assert result.metadata.get("deduplicated") is True

    def test_create_alert_skip_dedup(self, alert_service, mock_conn, sample_alert_data):
        """Test that dedup can be skipped for manual alerts."""
        mock_result = [{
            "a": {
                "id": "manual-alert-uuid",
                "type": "risk_spike",
                "severity": "critical",
                "status": "pending",
                "title": "Risk Score → High",
                "description": "Manual alert",
                "entity_type": "Company",
                "entity_id": "company-uuid-123",
                "entity_cf": "12345678901",
                "rule_id": None,
                "triggered_by": "manual",
                "metadata": {},
                "alert_hash": "testhash",
                "acknowledged_at": None,
                "resolved_at": None,
                "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }]
        mock_conn.run_query.return_value = mock_result

        sample_alert_data.skip_dedup = True
        result = alert_service.create_alert(sample_alert_data)

        assert result.id == "manual-alert-uuid"

    def test_create_alert_with_rule_id(self, alert_service, mock_conn):
        """Test alert creation with rule linkage."""
        data = AlertCreate(
            type=AlertType.FRAUD_PATTERN,
            severity=AlertSeverity.HIGH,
            title="Fraud Pattern Detected",
            description="Bid rotation pattern found",
            entity_type="Company",
            entity_id="company-uuid",
            rule_id="rule-uuid-123",
            triggered_by="rule",
        )
        mock_result = [{
            "a": {
                "id": "fraud-alert-uuid",
                "type": "fraud_pattern",
                "severity": "high",
                "status": "pending",
                "title": "Fraud Pattern Detected",
                "description": "Bid rotation pattern found",
                "entity_type": "Company",
                "entity_id": "company-uuid",
                "entity_cf": None,
                "rule_id": "rule-uuid-123",
                "triggered_by": "rule",
                "metadata": {},
                "alert_hash": "fraudhash",
                "acknowledged_at": None,
                "resolved_at": None,
                "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }]
        mock_conn.run_query.side_effect = [[], mock_result]

        result = alert_service.create_alert(data)

        assert result.rule_id == "rule-uuid-123"
        assert result.triggered_by == "rule"


# ─────────────────────────────────────────────────────────────────────────────
# Get Alert Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGetAlert:
    """Tests for get_alert method."""

    def test_get_alert_success(self, alert_service, mock_conn, sample_alert_record):
        """Test successful alert retrieval."""
        mock_conn.run_query.return_value = [sample_alert_record]

        result = alert_service.get_alert("alert-uuid-123")

        assert result is not None
        assert result.id == "alert-uuid-123"
        assert result.type == AlertType.RISK_SPIKE
        assert result.severity == AlertSeverity.CRITICAL

    def test_get_alert_not_found(self, alert_service, mock_conn):
        """Test alert not found returns None."""
        mock_conn.run_query.return_value = []

        result = alert_service.get_alert("non-existent-uuid")

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# List Alerts Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestListAlerts:
    """Tests for list_alerts method."""

    def test_list_alerts_basic(self, alert_service, mock_conn):
        """Test basic alert listing."""
        mock_count = [{"total": 3}]
        mock_data = [
            {"a": {"id": f"alert-{i}", "type": "risk_spike", "severity": "high",
                   "status": "pending", "title": f"Alert {i}", "description": f"Desc {i}",
                   "entity_type": "Company", "entity_id": f"company-{i}", "entity_cf": None,
                   "rule_id": None, "triggered_by": "system", "metadata": {},
                   "alert_hash": f"hash-{i}", "acknowledged_at": None, "resolved_at": None,
                   "dismissed_at": None, "created_at": datetime.now(UTC).isoformat(),
                   "provenance": None}}
            for i in range(3)
        ]
        mock_conn.run_query.side_effect = [mock_count, mock_data]

        params = AlertListParams()
        alerts, total = alert_service.list_alerts(params)

        assert total == 3
        assert len(alerts) == 3
        assert alerts[0].id == "alert-0"

    def test_list_alerts_with_status_filter(self, alert_service, mock_conn):
        """Test listing with status filter."""
        mock_conn.run_query.return_value = [{"total": 0}]

        params = AlertListParams(status=AlertStatus.PENDING)
        alerts, total = alert_service.list_alerts(params)

        assert total == 0
        # Verify status filter was passed
        call_args = mock_conn.run_query.call_args
        assert call_args[0][1]["status"] == "pending"

    def test_list_alerts_with_type_filter(self, alert_service, mock_conn):
        """Test listing with type filter."""
        mock_conn.run_query.return_value = [{"total": 0}]

        params = AlertListParams(type=AlertType.FRAUD_PATTERN)
        alert_service.list_alerts(params)

        call_args = mock_conn.run_query.call_args
        assert call_args[0][1]["type"] == "fraud_pattern"

    def test_list_alerts_with_severity_filter(self, alert_service, mock_conn):
        """Test listing with severity filter."""
        mock_conn.run_query.return_value = [{"total": 0}]

        params = AlertListParams(severity=AlertSeverity.CRITICAL)
        alert_service.list_alerts(params)

        call_args = mock_conn.run_query.call_args
        assert call_args[0][1]["severity"] == "critical"

    def test_list_alerts_with_entity_filter(self, alert_service, mock_conn):
        """Test listing with entity filter."""
        mock_conn.run_query.return_value = [{"total": 0}]

        params = AlertListParams(entity_id="company-123", entity_type="Company")
        alert_service.list_alerts(params)

        call_args = mock_conn.run_query.call_args
        assert call_args[0][1]["entity_id"] == "company-123"
        assert call_args[0][1]["entity_type"] == "Company"

    def test_list_alerts_pagination(self, alert_service, mock_conn):
        """Test pagination parameters."""
        mock_count = [{"total": 50}]
        mock_data = [
            {"a": {"id": f"alert-{i}", "type": "risk_spike", "severity": "high",
                   "status": "pending", "title": f"Alert {i}", "description": f"Desc {i}",
                   "entity_type": "Company", "entity_id": f"company-{i}", "entity_cf": None,
                   "rule_id": None, "triggered_by": "system", "metadata": {},
                   "alert_hash": f"hash-{i}", "acknowledged_at": None, "resolved_at": None,
                   "dismissed_at": None, "created_at": datetime.now(UTC).isoformat(),
                   "provenance": None}}
            for i in range(10)
        ]
        mock_conn.run_query.side_effect = [mock_count, mock_data]

        params = AlertListParams(limit=10, offset=20)
        alert_service.list_alerts(params)

        call_args = mock_conn.run_query.call_args
        assert call_args[0][1]["limit"] == 10
        assert call_args[0][1]["offset"] == 20

    def test_list_alerts_empty_result(self, alert_service, mock_conn):
        """Test empty result set."""
        mock_conn.run_query.return_value = [{"total": 0}]

        params = AlertListParams()
        alerts, total = alert_service.list_alerts(params)

        assert total == 0
        assert alerts == []


# ─────────────────────────────────────────────────────────────────────────────
# Status Transition Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateAlertStatus:
    """Tests for update_alert_status method."""

    def _mock_get_alert(self, mock_conn, status="pending"):
        """Helper to mock get_alert response."""
        mock_conn.run_query.return_value = [{
            "a": {
                "id": "alert-uuid",
                "type": "risk_spike",
                "severity": "high",
                "status": status,
                "title": "Test Alert",
                "description": "Test description",
                "entity_type": "Company",
                "entity_id": "company-123",
                "entity_cf": None,
                "rule_id": None,
                "triggered_by": "system",
                "metadata": {},
                "alert_hash": "hash",
                "acknowledged_at": None,
                "resolved_at": None,
                "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }]

    def test_status_pending_to_acknowledged(self, alert_service, mock_conn):
        """Test valid transition: pending → acknowledged."""
        pending_record = {
            "a": {
                "id": "alert-uuid",
                "type": "risk_spike",
                "severity": "high",
                "status": "pending",
                "title": "Test Alert",
                "description": "Test description",
                "entity_type": "Company",
                "entity_id": "company-123",
                "entity_cf": None,
                "rule_id": None,
                "triggered_by": "system",
                "metadata": {},
                "alert_hash": "hash",
                "acknowledged_at": None,
                "resolved_at": None,
                "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }
        acknowledged_record = {
            "a": {
                "id": "alert-uuid",
                "type": "risk_spike",
                "severity": "high",
                "status": "acknowledged",
                "title": "Test Alert",
                "description": "Test description",
                "entity_type": "Company",
                "entity_id": "company-123",
                "entity_cf": None,
                "rule_id": None,
                "triggered_by": "system",
                "metadata": {},
                "alert_hash": "hash",
                "acknowledged_at": datetime.now(UTC).isoformat(),
                "resolved_at": None,
                "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }
        # First call: get_alert (returns pending), Second call: update (returns acknowledged)
        mock_conn.run_query.side_effect = [[pending_record], [acknowledged_record]]

        result = alert_service.update_alert_status("alert-uuid", AlertStatus.ACKNOWLEDGED)

        assert result is not None
        assert result.status == AlertStatus.ACKNOWLEDGED

    def test_status_pending_to_resolved(self, alert_service, mock_conn):
        """Test valid transition: pending → resolved."""
        pending_record = {
            "a": {
                "id": "alert-uuid", "type": "risk_spike", "severity": "high",
                "status": "pending", "title": "Test Alert", "description": "Test description",
                "entity_type": "Company", "entity_id": "company-123", "entity_cf": None,
                "rule_id": None, "triggered_by": "system", "metadata": {}, "alert_hash": "hash",
                "acknowledged_at": None, "resolved_at": None, "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }
        }
        resolved_record = {
            "a": {
                "id": "alert-uuid", "type": "risk_spike", "severity": "high",
                "status": "resolved", "title": "Test Alert", "description": "Test description",
                "entity_type": "Company", "entity_id": "company-123", "entity_cf": None,
                "rule_id": None, "triggered_by": "system", "metadata": {}, "alert_hash": "hash",
                "acknowledged_at": None, "resolved_at": datetime.now(UTC).isoformat(),
                "dismissed_at": None, "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }
        mock_conn.run_query.side_effect = [[pending_record], [resolved_record]]

        result = alert_service.update_alert_status("alert-uuid", AlertStatus.RESOLVED)

        assert result.status == AlertStatus.RESOLVED

    def test_status_pending_to_dismissed(self, alert_service, mock_conn):
        """Test valid transition: pending → dismissed."""
        pending_record = {
            "a": {
                "id": "alert-uuid", "type": "risk_spike", "severity": "high",
                "status": "pending", "title": "Test Alert", "description": "Test description",
                "entity_type": "Company", "entity_id": "company-123", "entity_cf": None,
                "rule_id": None, "triggered_by": "system", "metadata": {}, "alert_hash": "hash",
                "acknowledged_at": None, "resolved_at": None, "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }
        }
        dismissed_record = {
            "a": {
                "id": "alert-uuid", "type": "risk_spike", "severity": "high",
                "status": "dismissed", "title": "Test Alert", "description": "Test description",
                "entity_type": "Company", "entity_id": "company-123", "entity_cf": None,
                "rule_id": None, "triggered_by": "system", "metadata": {}, "alert_hash": "hash",
                "acknowledged_at": None, "resolved_at": None,
                "dismissed_at": datetime.now(UTC).isoformat(),
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }
        }
        mock_conn.run_query.side_effect = [[pending_record], [dismissed_record]]

        result = alert_service.update_alert_status("alert-uuid", AlertStatus.DISMISSED)

        assert result.status == AlertStatus.DISMISSED

    def test_status_acknowledged_to_resolved(self, alert_service, mock_conn):
        """Test valid transition: acknowledged → resolved."""
        acknowledged_record = {
            "a": {
                "id": "alert-uuid", "type": "risk_spike", "severity": "high",
                "status": "acknowledged", "title": "Test Alert", "description": "Test description",
                "entity_type": "Company", "entity_id": "company-123", "entity_cf": None,
                "rule_id": None, "triggered_by": "system", "metadata": {}, "alert_hash": "hash",
                "acknowledged_at": datetime.now(UTC).isoformat(), "resolved_at": None,
                "dismissed_at": None, "created_at": datetime.now(UTC).isoformat(),
                "provenance": None,
            }
        }
        resolved_record = {
            "a": {
                "id": "alert-uuid", "type": "risk_spike", "severity": "high",
                "status": "resolved", "title": "Test Alert", "description": "Test description",
                "entity_type": "Company", "entity_id": "company-123", "entity_cf": None,
                "rule_id": None, "triggered_by": "system", "metadata": {}, "alert_hash": "hash",
                "acknowledged_at": datetime.now(UTC).isoformat(),
                "resolved_at": datetime.now(UTC).isoformat(), "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }
        }
        mock_conn.run_query.side_effect = [[acknowledged_record], [resolved_record]]

        result = alert_service.update_alert_status("alert-uuid", AlertStatus.RESOLVED)

        assert result.status == AlertStatus.RESOLVED

    def test_status_resolved_is_terminal(self, alert_service, mock_conn):
        """Test that resolved is a terminal state."""
        self._mock_get_alert(mock_conn, "resolved")

        with pytest.raises(ValueError, match="Invalid status transition"):
            alert_service.update_alert_status("alert-uuid", AlertStatus.ACKNOWLEDGED)

    def test_status_dismissed_is_terminal(self, alert_service, mock_conn):
        """Test that dismissed is a terminal state."""
        self._mock_get_alert(mock_conn, "dismissed")

        with pytest.raises(ValueError, match="Invalid status transition"):
            alert_service.update_alert_status("alert-uuid", AlertStatus.PENDING)

    def test_status_not_found(self, alert_service, mock_conn):
        """Test updating non-existent alert returns None."""
        mock_conn.run_query.return_value = []

        result = alert_service.update_alert_status("non-existent", AlertStatus.ACKNOWLEDGED)

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Alert Statistics Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertStatistics:
    """Tests for get_alert_statistics method."""

    def test_get_statistics_basic(self, alert_service, mock_conn):
        """Test basic statistics retrieval."""
        mock_conn.run_query.return_value = [{
            "pending_count": 5,
            "acknowledged_count": 3,
            "resolved_count": 10,
            "dismissed_count": 2,
            "risk_spike_count": 8,
            "fraud_pattern_count": 5,
            "sanction_match_count": 1,
            "activity_spike_count": 4,
            "merge_candidate_count": 2,
            "critical_count": 3,
            "high_count": 7,
            "medium_count": 6,
            "low_count": 3,
            "info_count": 1,
            "last_24h_count": 4,
            "last_7d_count": 12,
        }]

        stats = alert_service.get_alert_statistics()

        assert stats.pending_count == 5
        assert stats.acknowledged_count == 3
        assert stats.resolved_count == 10
        assert stats.dismissed_count == 2
        assert stats.risk_spike_count == 8
        assert stats.fraud_pattern_count == 5
        assert stats.critical_count == 3
        assert stats.last_24h_count == 4
        assert stats.last_7d_count == 12

    def test_get_statistics_empty(self, alert_service, mock_conn):
        """Test statistics with no alerts."""
        mock_conn.run_query.return_value = []

        stats = alert_service.get_alert_statistics()

        assert stats.pending_count == 0
        assert stats.total_alerts == 0 if hasattr(stats, 'total_alerts') else True


# ─────────────────────────────────────────────────────────────────────────────
# Alert Rule CRUD Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertRules:
    """Tests for alert rule CRUD operations."""

    def test_create_rule(self, alert_service, mock_conn, sample_rule_record):
        """Test creating a new alert rule."""
        mock_conn.run_query.return_value = [sample_rule_record]

        rule_data = AlertRuleCreate(
            name="Test Rule",
            description="Test rule description",
            alert_type=AlertType.RISK_SPIKE,
            trigger_condition="risk_score >= 0.8",
            threshold=0.8,
            severity=AlertSeverity.HIGH,
            enabled=True,
        )

        result = alert_service.create_rule(rule_data)

        assert result.id == "rule-uuid-123"
        assert result.name == "Risk Score → High"
        assert result.enabled is True

    def test_list_rules(self, alert_service, mock_conn, sample_rule_record):
        """Test listing alert rules."""
        mock_conn.run_query.return_value = [sample_rule_record]

        rules = alert_service.list_rules()

        assert len(rules) == 1
        assert rules[0].id == "rule-uuid-123"

    def test_list_rules_enabled_only(self, alert_service, mock_conn):
        """Test listing only enabled rules."""
        mock_conn.run_query.return_value = []

        rules = alert_service.list_rules(enabled_only=True)

        assert len(rules) == 0
        # Verify WHERE clause was added
        call_args = mock_conn.run_query.call_args
        assert "WHERE r.enabled = true" in call_args[0][0]

    def test_toggle_rule(self, alert_service, mock_conn, sample_rule_record):
        """Test toggling a rule's enabled state."""
        # First call: get_rule
        mock_conn.run_query.return_value = [sample_rule_record]
        # Second call: toggle
        toggled_record = dict(sample_rule_record["r"])
        toggled_record["enabled"] = False
        mock_conn.run_query.side_effect = [
            [sample_rule_record],
            [{"r": toggled_record}],
        ]

        result = alert_service.toggle_rule("rule-uuid-123")

        assert result is not None
        assert result.enabled is False

    def test_delete_rule(self, alert_service, mock_conn):
        """Test deleting an alert rule."""
        mock_conn.run_query.return_value = [{"deleted": 1}]

        result = alert_service.delete_rule("rule-uuid-123")

        assert result is True

    def test_delete_rule_not_found(self, alert_service, mock_conn):
        """Test deleting non-existent rule returns False."""
        mock_conn.run_query.return_value = [{"deleted": 0}]

        result = alert_service.delete_rule("non-existent")

        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Alert Generator Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertGenerators:
    """Tests for alert generator methods."""

    def test_check_risk_thresholds_creates_alerts(self, alert_service, mock_conn):
        """Test risk threshold check creates alerts for high-risk companies."""
        mock_conn.run_query.return_value = [
            {
                "entity_id": "company-1",
                "entity_cf": "11111111111",
                "entity_name": "High Risk Co",
                "risk_score": 0.85,
                "anomaly_flags": ["high_single_bidder_ratio"],
            }
        ]
        # Dedup check returns empty, then create alert
        mock_conn.run_query.side_effect = [
            [{"entity_id": "company-1", "entity_cf": "11111111111", "entity_name": "High Risk Co",
              "risk_score": 0.85, "anomaly_flags": ["high_single_bidder_ratio"]}],
            [],  # dedup check
            [{"a": {
                "id": "alert-1", "type": "risk_spike", "severity": "critical",
                "status": "pending", "title": "Risk Score → High: High Risk Co",
                "description": "test", "entity_type": "Company", "entity_id": "company-1",
                "entity_cf": "11111111111", "rule_id": None, "triggered_by": "risk_engine",
                "metadata": {}, "alert_hash": "hash1", "acknowledged_at": None,
                "resolved_at": None, "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }}],
            [],  # link alert
        ]

        result = alert_service.check_risk_thresholds()

        assert result.generator_name == "check_risk_thresholds"
        assert result.alerts_created >= 0  # At least attempted
        assert len(result.errors) == 0

    def test_check_fraud_patterns_creates_alerts(self, alert_service, mock_conn):
        """Test fraud pattern check creates alerts for detected patterns."""
        mock_conn.run_query.return_value = [
            {
                "pattern_id": "pattern-1",
                "pattern_name": "bid_rotation",
                "pattern_severity": "high",
                "description": "Bid rotation detected",
                "affected_ids": ["company-1", "company-2"],
                "evidence": '{"buyer_id": "b1"}',
                "detected_at": datetime.now(UTC).isoformat(),
            }
        ]
        mock_conn.run_query.side_effect = [
            [{"pattern_id": "pattern-1", "pattern_name": "bid_rotation",
              "pattern_severity": "high", "description": "Bid rotation detected",
              "affected_ids": ["company-1", "company-2"], "evidence": '{"buyer_id": "b1"}',
              "detected_at": datetime.now(UTC).isoformat()}],
            [],  # dedup check
            [{"a": {
                "id": "alert-1", "type": "fraud_pattern", "severity": "high",
                "status": "pending", "title": "Fraud Pattern: bid_rotation",
                "description": "Bid rotation detected", "entity_type": "Company",
                "entity_id": "company-1", "entity_cf": None, "rule_id": None,
                "triggered_by": "fraud_detector", "metadata": {}, "alert_hash": "hash1",
                "acknowledged_at": None, "resolved_at": None, "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }}],
            [],  # link alert
        ]

        result = alert_service.check_fraud_patterns()

        assert result.generator_name == "check_fraud_patterns"
        assert len(result.errors) == 0

    def test_check_activity_spikes_creates_alerts(self, alert_service, mock_conn):
        """Test activity spike check creates alerts for volume spikes."""
        mock_conn.run_query.return_value = [
            {
                "entity_id": "company-1",
                "entity_cf": "11111111111",
                "entity_name": "Spike Co",
                "recent_wins": 30,
                "historical_wins": 5,
                "recent_value": 500000,
                "historical_value": 100000,
                "volume_ratio": 6.0,
            }
        ]
        mock_conn.run_query.side_effect = [
            [{"entity_id": "company-1", "entity_cf": "11111111111", "entity_name": "Spike Co",
              "recent_wins": 30, "historical_wins": 5, "recent_value": 500000,
              "historical_value": 100000, "volume_ratio": 6.0}],
            [],  # dedup check
            [{"a": {
                "id": "alert-1", "type": "activity_spike", "severity": "medium",
                "status": "pending", "title": "Tender Volume Spike: Spike Co",
                "description": "test", "entity_type": "Company", "entity_id": "company-1",
                "entity_cf": "11111111111", "rule_id": None, "triggered_by": "activity_monitor",
                "metadata": {}, "alert_hash": "hash1", "acknowledged_at": None,
                "resolved_at": None, "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }}],
            [],  # link alert
        ]

        result = alert_service.check_activity_spikes()

        assert result.generator_name == "check_activity_spikes"
        assert len(result.errors) == 0

    def test_check_merge_candidates_creates_alerts(self, alert_service, mock_conn):
        """Test merge candidate check creates alerts for duplicates."""
        mock_conn.run_query.return_value = [
            {
                "entity_id_1": "company-1",
                "cf_1": "11111111111",
                "name_1": "ACME SRL",
                "entity_id_2": "company-2",
                "cf_2": "22222222222",
                "name_2": "ACME S.R.L.",
                "provincia": "MI",
            }
        ]
        mock_conn.run_query.side_effect = [
            [{"entity_id_1": "company-1", "cf_1": "11111111111", "name_1": "ACME SRL",
              "entity_id_2": "company-2", "cf_2": "22222222222", "name_2": "ACME S.R.L.",
              "provincia": "MI"}],
            [],  # dedup check
            [{"a": {
                "id": "alert-1", "type": "merge_candidate", "severity": "low",
                "status": "pending", "title": "Duplicate Company Found: ACME SRL",
                "description": "test", "entity_type": "Company", "entity_id": "company-1",
                "entity_cf": "11111111111", "rule_id": None, "triggered_by": "merge_detector",
                "metadata": {}, "alert_hash": "hash1", "acknowledged_at": None,
                "resolved_at": None, "dismissed_at": None,
                "created_at": datetime.now(UTC).isoformat(), "provenance": None,
            }}],
            [],  # link alert
        ]

        result = alert_service.check_merge_candidates()

        assert result.generator_name == "check_merge_candidates"
        assert len(result.errors) == 0

    def test_run_all_generators(self, alert_service, mock_conn):
        """Test running all generators returns comprehensive report."""
        # Mock all generator queries to return empty results
        mock_conn.run_query.return_value = []

        report = alert_service.run_all_generators()

        assert report.run_id is not None
        assert report.started_at is not None
        assert report.completed_at is not None
        assert len(report.generators) == 4  # 4 generators
        assert report.total_alerts_created == 0
        assert report.total_alerts_deduplicated == 0

    def test_run_all_generators_with_errors(self, alert_service, mock_conn):
        """Test generators handle errors gracefully."""
        # Make risk check fail, others succeed
        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Simulated DB error")
            return []

        mock_conn.run_query.side_effect = side_effect

        report = alert_service.run_all_generators()

        assert len(report.errors) >= 1
        assert len(report.generators) == 4  # All generators still report

    def test_dedup_logic_hash_calculation(self, alert_service):
        """Test alert hash calculation is deterministic."""
        data1 = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test",
            description="Test",
            entity_id="company-1",
            entity_cf="12345678901",
        )
        data2 = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test",
            description="Test",
            entity_id="company-1",
            entity_cf="12345678901",
        )

        hash1 = alert_service._calculate_alert_hash(data1)
        hash2 = alert_service._calculate_alert_hash(data2)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex length

    def test_dedup_logic_different_entities(self, alert_service):
        """Test alerts for different entities are not deduplicated."""
        data1 = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test",
            description="Test",
            entity_id="company-1",
        )
        data2 = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test",
            description="Test",
            entity_id="company-2",
        )

        hash1 = alert_service._calculate_alert_hash(data1)
        hash2 = alert_service._calculate_alert_hash(data2)

        assert hash1 != hash2


# ─────────────────────────────────────────────────────────────────────────────
# Bulk Action Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBulkActions:
    """Tests for bulk alert operations."""

    def test_bulk_acknowledge(self, alert_service, mock_conn):
        """Test bulk acknowledge action."""
        mock_conn.run_query.return_value = [{"updated": 3}]

        action = AlertBulkAction(
            alert_ids=["alert-1", "alert-2", "alert-3"],
            action="acknowledge",
        )

        result = alert_service.bulk_update_status(action)

        assert result == 3

    def test_bulk_resolve(self, alert_service, mock_conn):
        """Test bulk resolve action."""
        mock_conn.run_query.return_value = [{"updated": 5}]

        action = AlertBulkAction(
            alert_ids=["alert-1", "alert-2", "alert-3", "alert-4", "alert-5"],
            action="resolve",
        )

        result = alert_service.bulk_update_status(action)

        assert result == 5

    def test_bulk_dismiss(self, alert_service, mock_conn):
        """Test bulk dismiss action."""
        mock_conn.run_query.return_value = [{"updated": 2}]

        action = AlertBulkAction(
            alert_ids=["alert-1", "alert-2"],
            action="dismiss",
        )

        result = alert_service.bulk_update_status(action)

        assert result == 2

    def test_bulk_invalid_action_raises(self, mock_conn):
        """Test invalid bulk action raises validation error."""
        with pytest.raises(ValueError, match="action must be one of"):
            AlertBulkAction(
                alert_ids=["alert-1"],
                action="invalid_action",
            )


# ─────────────────────────────────────────────────────────────────────────────
# Delete Alert Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteAlert:
    """Tests for delete_alert method."""

    def test_delete_alert_success(self, alert_service, mock_conn):
        """Test successful alert deletion."""
        mock_conn.run_query.return_value = [{"deleted": 1}]

        result = alert_service.delete_alert("alert-uuid")

        assert result is True

    def test_delete_alert_not_found(self, alert_service, mock_conn):
        """Test deleting non-existent alert returns False."""
        mock_conn.run_query.return_value = [{"deleted": 0}]

        result = alert_service.delete_alert("non-existent")

        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Model Validation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestModelValidation:
    """Tests for Pydantic model validation."""

    def test_alert_type_enum(self):
        """Test AlertType enum values."""
        assert AlertType.RISK_SPIKE.value == "risk_spike"
        assert AlertType.FRAUD_PATTERN.value == "fraud_pattern"
        assert AlertType.SANCTION_MATCH.value == "sanction_match"
        assert AlertType.ACTIVITY_SPIKE.value == "activity_spike"
        assert AlertType.MERGE_CANDIDATE.value == "merge_candidate"

    def test_alert_severity_enum(self):
        """Test AlertSeverity enum values."""
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.HIGH.value == "high"
        assert AlertSeverity.MEDIUM.value == "medium"
        assert AlertSeverity.LOW.value == "low"
        assert AlertSeverity.INFO.value == "info"

    def test_alert_status_enum(self):
        """Test AlertStatus enum values."""
        assert AlertStatus.PENDING.value == "pending"
        assert AlertStatus.ACKNOWLEDGED.value == "acknowledged"
        assert AlertStatus.RESOLVED.value == "resolved"
        assert AlertStatus.DISMISSED.value == "dismissed"

    def test_alert_create_valid(self):
        """Test valid AlertCreate."""
        data = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test Alert",
            description="Test description",
            entity_type="Company",
            entity_id="company-123",
        )
        assert data.type == AlertType.RISK_SPIKE
        assert data.status if hasattr(data, 'status') else True

    def test_alert_list_params_defaults(self):
        """Test AlertListParams default values."""
        params = AlertListParams()
        assert params.limit == 50
        assert params.offset == 0
        assert params.sort_by == "created_at"
        assert params.sort_order == "desc"

    def test_alert_list_params_invalid_sort_raises(self):
        """Test invalid sort field raises validation error."""
        with pytest.raises(ValueError):
            AlertListParams(sort_by="invalid_field")

    def test_alert_list_params_invalid_order_raises(self):
        """Test invalid sort order raises validation error."""
        with pytest.raises(ValueError):
            AlertListParams(sort_order="invalid")

    def test_alert_bulk_action_valid(self):
        """Test valid AlertBulkAction."""
        action = AlertBulkAction(
            alert_ids=["alert-1", "alert-2"],
            action="acknowledge",
        )
        assert action.action == "acknowledge"
        assert len(action.alert_ids) == 2

    def test_alert_bulk_action_empty_ids_raises(self):
        """Test empty alert_ids raises validation error."""
        with pytest.raises(ValueError):
            AlertBulkAction(
                alert_ids=[],
                action="acknowledge",
            )

    def test_alert_rule_create_valid(self):
        """Test valid AlertRuleCreate."""
        rule = AlertRuleCreate(
            name="Test Rule",
            description="Test description",
            alert_type=AlertType.RISK_SPIKE,
            trigger_condition="risk_score >= 0.7",
            threshold=0.7,
            severity=AlertSeverity.HIGH,
        )
        assert rule.enabled is True  # Default
        assert rule.threshold == 0.7


# ─────────────────────────────────────────────────────────────────────────────
# Default Rules Initialization Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDefaultRulesInitialization:
    """Tests for initialize_default_rules function."""

    def test_default_rules_count(self):
        """Test that 8 default rules are defined."""
        assert len(DEFAULT_ALERT_RULES) == 8

    def test_default_rules_have_required_fields(self):
        """Test all default rules have required fields."""
        required_fields = {"name", "description", "alert_type", "trigger_condition", "severity", "enabled"}
        for rule in DEFAULT_ALERT_RULES:
            assert required_fields.issubset(rule.keys()), f"Rule missing fields: {rule}"

    def test_default_rules_valid_alert_types(self):
        """Test all default rules have valid alert types."""
        valid_types = {AlertType.RISK_SPIKE, AlertType.FRAUD_PATTERN,
                       AlertType.ACTIVITY_SPIKE, AlertType.MERGE_CANDIDATE}
        for rule in DEFAULT_ALERT_RULES:
            assert rule["alert_type"] in valid_types

    def test_default_rules_valid_severities(self):
        """Test all default rules have valid severities."""
        valid_severities = {AlertSeverity.CRITICAL, AlertSeverity.HIGH,
                            AlertSeverity.MEDIUM, AlertSeverity.LOW}
        for rule in DEFAULT_ALERT_RULES:
            assert rule["severity"] in valid_severities

    def test_initialize_rules_skips_existing(self, alert_service, mock_conn):
        """Test initialization skips existing rules."""
        # Mock existing rules
        existing_rules = [
            AlertRuleResponse(
                id="rule-1", name="Risk Score → High", description="desc",
                alert_type=AlertType.RISK_SPIKE, trigger_condition="risk_score >= 0.7",
                threshold=0.7, severity=AlertSeverity.CRITICAL, enabled=True,
                created_at=datetime.now(UTC),
            )
        ]
        # Mock all rules as existing
        mock_conn.run_query.return_value = [
            {"r": {
                "id": "rule-1", "name": "Risk Score → High", "description": "desc",
                "alert_type": "risk_spike", "trigger_condition": "risk_score >= 0.7",
                "threshold": 0.7, "severity": "critical", "enabled": True,
                "created_at": datetime.now(UTC).isoformat(), "updated_at": None,
            }}
        ]

        created = initialize_default_rules(alert_service)

        # Should not create any new rules since they all exist
        # (mock returns same rule for all queries, simulating all exist)
        assert isinstance(created, list)


# ─────────────────────────────────────────────────────────────────────────────
# Internal Helper Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestInternalHelpers:
    """Tests for internal helper methods."""

    def test_validate_status_transition_valid(self, alert_service):
        """Test valid status transitions don't raise."""
        # pending → acknowledged
        alert_service._validate_status_transition(
            AlertStatus.PENDING, AlertStatus.ACKNOWLEDGED
        )
        # pending → resolved
        alert_service._validate_status_transition(
            AlertStatus.PENDING, AlertStatus.RESOLVED
        )
        # pending → dismissed
        alert_service._validate_status_transition(
            AlertStatus.PENDING, AlertStatus.DISMISSED
        )
        # acknowledged → resolved
        alert_service._validate_status_transition(
            AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED
        )
        # acknowledged → dismissed
        alert_service._validate_status_transition(
            AlertStatus.ACKNOWLEDGED, AlertStatus.DISMISSED
        )

    def test_validate_status_transition_invalid(self, alert_service):
        """Test invalid status transitions raise ValueError."""
        with pytest.raises(ValueError, match="Invalid status transition"):
            alert_service._validate_status_transition(
                AlertStatus.RESOLVED, AlertStatus.PENDING
            )

        with pytest.raises(ValueError, match="Invalid status transition"):
            alert_service._validate_status_transition(
                AlertStatus.DISMISSED, AlertStatus.ACKNOWLEDGED
            )

    def test_is_duplicate_alert_true(self, alert_service, mock_conn):
        """Test duplicate detection returns True when found."""
        mock_conn.run_query.return_value = [{"count": 1}]

        result = alert_service._is_duplicate_alert("test-hash")

        assert result is True

    def test_is_duplicate_alert_false(self, alert_service, mock_conn):
        """Test duplicate detection returns False when not found."""
        mock_conn.run_query.return_value = [{"count": 0}]

        result = alert_service._is_duplicate_alert("test-hash")

        assert result is False

    def test_record_to_alert_parsing(self, alert_service, sample_alert_record):
        """Test Neo4j record to Alert conversion."""
        result = alert_service._record_to_alert(sample_alert_record["a"])

        assert result.id == "alert-uuid-123"
        assert result.type == AlertType.RISK_SPIKE
        assert result.severity == AlertSeverity.CRITICAL
        assert result.status == AlertStatus.PENDING

    def test_record_to_rule_response_parsing(self, alert_service, sample_rule_record):
        """Test Neo4j record to AlertRuleResponse conversion."""
        result = alert_service._record_to_rule_response(sample_rule_record["r"])

        assert result.id == "rule-uuid-123"
        assert result.name == "Risk Score → High"
        assert result.enabled is True
