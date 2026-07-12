"""
Unit tests for Alert/Notification System Pydantic models.

Tests cover:
- Enum validation (AlertType, AlertSeverity, AlertStatus)
- AlertCreate validation (required fields, max lengths, defaults)
- AlertUpdate validation (partial updates, field constraints)
- AlertListParams validation (sort_by, sort_order, filters, pagination)
- AlertBulkAction validation (valid/invalid actions, alert_ids constraints)
- AlertRuleCreate validation (required fields, defaults)
- AlertRuleResponse validation
- AlertStatistics validation
- AlertGeneratorResult and AlertGenerationReport validation
- Alert model field parsing
"""

import pytest
from datetime import datetime, UTC

from paladino.models import (
    Alert,
    AlertBulkAction,
    AlertCreate,
    AlertGenerationReport,
    AlertGeneratorResult,
    AlertListParams,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertSeverity,
    AlertStatistics,
    AlertStatus,
    AlertType,
    AlertUpdate,
    ProvenanceMetadata,
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestAlertTypeEnum:
    """Tests for AlertType enum."""

    def test_all_values(self):
        """Test all AlertType enum values."""
        assert AlertType.RISK_SPIKE.value == "risk_spike"
        assert AlertType.FRAUD_PATTERN.value == "fraud_pattern"
        assert AlertType.SANCTION_MATCH.value == "sanction_match"
        assert AlertType.ACTIVITY_SPIKE.value == "activity_spike"
        assert AlertType.MERGE_CANDIDATE.value == "merge_candidate"

    def test_count(self):
        """Test expected number of alert types."""
        assert len(AlertType) == 5

    def test_from_string(self):
        """Test constructing AlertType from string."""
        assert AlertType("risk_spike") == AlertType.RISK_SPIKE
        assert AlertType("fraud_pattern") == AlertType.FRAUD_PATTERN

    def test_invalid_value_raises(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            AlertType("invalid_type")


class TestAlertSeverityEnum:
    """Tests for AlertSeverity enum."""

    def test_all_values(self):
        """Test all AlertSeverity enum values."""
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.HIGH.value == "high"
        assert AlertSeverity.MEDIUM.value == "medium"
        assert AlertSeverity.LOW.value == "low"
        assert AlertSeverity.INFO.value == "info"

    def test_count(self):
        """Test expected number of severity levels."""
        assert len(AlertSeverity) == 5

    def test_from_string(self):
        """Test constructing AlertSeverity from string."""
        assert AlertSeverity("critical") == AlertSeverity.CRITICAL

    def test_invalid_value_raises(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            AlertSeverity("extreme")


class TestAlertStatusEnum:
    """Tests for AlertStatus enum."""

    def test_all_values(self):
        """Test all AlertStatus enum values."""
        assert AlertStatus.PENDING.value == "pending"
        assert AlertStatus.ACKNOWLEDGED.value == "acknowledged"
        assert AlertStatus.RESOLVED.value == "resolved"
        assert AlertStatus.DISMISSED.value == "dismissed"

    def test_count(self):
        """Test expected number of status values."""
        assert len(AlertStatus) == 4

    def test_from_string(self):
        """Test constructing AlertStatus from string."""
        assert AlertStatus("pending") == AlertStatus.PENDING

    def test_invalid_value_raises(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            AlertStatus("archived")


# =============================================================================
# AlertCreate Tests
# =============================================================================

class TestAlertCreate:
    """Tests for AlertCreate model validation."""

    def test_minimal_valid(self):
        """Test minimal valid AlertCreate."""
        data = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test Alert",
            description="Test description",
        )
        assert data.type == AlertType.RISK_SPIKE
        assert data.severity == AlertSeverity.HIGH
        assert data.title == "Test Alert"
        assert data.description == "Test description"
        assert data.triggered_by == "system"  # default
        assert data.skip_dedup is False  # default
        assert data.metadata == {}  # default
        assert data.entity_type is None
        assert data.entity_id is None
        assert data.entity_cf is None
        assert data.rule_id is None

    def test_full_valid(self):
        """Test AlertCreate with all fields."""
        data = AlertCreate(
            type=AlertType.FRAUD_PATTERN,
            severity=AlertSeverity.CRITICAL,
            title="Fraud Detected",
            description="Bid rotation pattern found",
            entity_type="Company",
            entity_id="company-123",
            entity_cf="12345678901",
            rule_id="rule-456",
            triggered_by="fraud_detector",
            metadata={"pattern": "bid_rotation", "confidence": 0.95},
            skip_dedup=True,
        )
        assert data.entity_type == "Company"
        assert data.entity_id == "company-123"
        assert data.entity_cf == "12345678901"
        assert data.rule_id == "rule-456"
        assert data.triggered_by == "fraud_detector"
        assert data.metadata == {"pattern": "bid_rotation", "confidence": 0.95}
        assert data.skip_dedup is True

    def test_title_empty_raises(self):
        """Test empty title raises validation error."""
        with pytest.raises(ValueError):
            AlertCreate(
                type=AlertType.RISK_SPIKE,
                severity=AlertSeverity.HIGH,
                title="",
                description="Valid description",
            )

    def test_title_max_length(self):
        """Test title at max length is valid."""
        data = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="A" * 200,
            description="Test description",
        )
        assert len(data.title) == 200

    def test_title_over_max_length_raises(self):
        """Test title exceeding max length raises validation error."""
        with pytest.raises(ValueError):
            AlertCreate(
                type=AlertType.RISK_SPIKE,
                severity=AlertSeverity.HIGH,
                title="A" * 201,
                description="Test description",
            )

    def test_description_empty_raises(self):
        """Test empty description raises validation error."""
        with pytest.raises(ValueError):
            AlertCreate(
                type=AlertType.RISK_SPIKE,
                severity=AlertSeverity.HIGH,
                title="Test",
                description="",
            )

    def test_description_max_length(self):
        """Test description at max length is valid."""
        data = AlertCreate(
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test",
            description="A" * 2000,
        )
        assert len(data.description) == 2000

    def test_description_over_max_length_raises(self):
        """Test description exceeding max length raises validation error."""
        with pytest.raises(ValueError):
            AlertCreate(
                type=AlertType.RISK_SPIKE,
                severity=AlertSeverity.HIGH,
                title="Test",
                description="A" * 2001,
            )

    def test_missing_required_type_raises(self):
        """Test missing type raises validation error."""
        with pytest.raises(ValueError):
            AlertCreate(
                severity=AlertSeverity.HIGH,
                title="Test",
                description="Test",
            )

    def test_missing_required_severity_raises(self):
        """Test missing severity raises validation error."""
        with pytest.raises(ValueError):
            AlertCreate(
                type=AlertType.RISK_SPIKE,
                title="Test",
                description="Test",
            )


# =============================================================================
# AlertUpdate Tests
# =============================================================================

class TestAlertUpdate:
    """Tests for AlertUpdate model validation."""

    def test_all_fields_none_valid(self):
        """Test AlertUpdate with all None fields is valid (partial update)."""
        data = AlertUpdate()
        assert data.title is None
        assert data.description is None
        assert data.metadata is None

    def test_update_title_only(self):
        """Test updating only title."""
        data = AlertUpdate(title="New Title")
        assert data.title == "New Title"
        assert data.description is None

    def test_update_description_only(self):
        """Test updating only description."""
        data = AlertUpdate(description="New description")
        assert data.description == "New description"
        assert data.title is None

    def test_update_metadata_only(self):
        """Test updating only metadata."""
        data = AlertUpdate(metadata={"key": "value"})
        assert data.metadata == {"key": "value"}

    def test_update_all_fields(self):
        """Test updating all fields."""
        data = AlertUpdate(
            title="New Title",
            description="New description",
            metadata={"updated": True},
        )
        assert data.title == "New Title"
        assert data.description == "New description"
        assert data.metadata == {"updated": True}

    def test_title_empty_raises(self):
        """Test empty title raises validation error."""
        with pytest.raises(ValueError):
            AlertUpdate(title="")

    def test_title_max_length(self):
        """Test title at max length is valid."""
        data = AlertUpdate(title="A" * 200)
        assert len(data.title) == 200

    def test_title_over_max_length_raises(self):
        """Test title exceeding max length raises validation error."""
        with pytest.raises(ValueError):
            AlertUpdate(title="A" * 201)

    def test_description_empty_raises(self):
        """Test empty description raises validation error."""
        with pytest.raises(ValueError):
            AlertUpdate(description="")

    def test_description_over_max_length_raises(self):
        """Test description exceeding max length raises validation error."""
        with pytest.raises(ValueError):
            AlertUpdate(description="A" * 2001)


# =============================================================================
# AlertListParams Tests
# =============================================================================

class TestAlertListParams:
    """Tests for AlertListParams model validation."""

    def test_defaults(self):
        """Test default values."""
        params = AlertListParams()
        assert params.limit == 50
        assert params.offset == 0
        assert params.sort_by == "created_at"
        assert params.sort_order == "desc"
        assert params.status is None
        assert params.type is None
        assert params.severity is None
        assert params.entity_id is None
        assert params.entity_type is None
        assert params.entity_cf is None
        assert params.rule_id is None
        assert params.date_from is None
        assert params.date_to is None

    def test_with_filters(self):
        """Test with all filters set."""
        now = datetime.now(UTC)
        params = AlertListParams(
            status=AlertStatus.PENDING,
            type=AlertType.FRAUD_PATTERN,
            severity=AlertSeverity.CRITICAL,
            entity_id="company-123",
            entity_type="Company",
            entity_cf="12345678901",
            rule_id="rule-456",
            date_from=now,
            date_to=now,
            limit=100,
            offset=50,
            sort_by="severity",
            sort_order="asc",
        )
        assert params.status == AlertStatus.PENDING
        assert params.type == AlertType.FRAUD_PATTERN
        assert params.severity == AlertSeverity.CRITICAL
        assert params.entity_id == "company-123"
        assert params.entity_type == "Company"
        assert params.entity_cf == "12345678901"
        assert params.rule_id == "rule-456"
        assert params.limit == 100
        assert params.offset == 50
        assert params.sort_by == "severity"
        assert params.sort_order == "asc"

    def test_sort_by_valid_fields(self):
        """Test all valid sort_by fields."""
        valid_fields = ["created_at", "severity", "type", "acknowledged_at", "resolved_at"]
        for field in valid_fields:
            params = AlertListParams(sort_by=field)
            assert params.sort_by == field

    def test_sort_by_invalid_raises(self):
        """Test invalid sort_by raises ValueError."""
        with pytest.raises(ValueError, match="sort_by must be one of"):
            AlertListParams(sort_by="invalid_field")

        with pytest.raises(ValueError, match="sort_by must be one of"):
            AlertListParams(sort_by="updated_at")

    def test_sort_order_valid(self):
        """Test valid sort_order values."""
        assert AlertListParams(sort_order="asc").sort_order == "asc"
        assert AlertListParams(sort_order="desc").sort_order == "desc"

    def test_sort_order_invalid_raises(self):
        """Test invalid sort_order raises ValueError."""
        with pytest.raises(ValueError, match="sort_order must be one of"):
            AlertListParams(sort_order="ascending")

        with pytest.raises(ValueError, match="sort_order must be one of"):
            AlertListParams(sort_order="random")

    def test_limit_min_raises(self):
        """Test limit below minimum raises ValueError."""
        with pytest.raises(ValueError):
            AlertListParams(limit=0)

    def test_limit_max_raises(self):
        """Test limit above maximum raises ValueError."""
        with pytest.raises(ValueError):
            AlertListParams(limit=201)

    def test_limit_boundary_valid(self):
        """Test limit at boundaries is valid."""
        assert AlertListParams(limit=1).limit == 1
        assert AlertListParams(limit=200).limit == 200

    def test_offset_min_raises(self):
        """Test negative offset raises ValueError."""
        with pytest.raises(ValueError):
            AlertListParams(offset=-1)

    def test_offset_zero_valid(self):
        """Test zero offset is valid."""
        assert AlertListParams(offset=0).offset == 0


# =============================================================================
# AlertBulkAction Tests
# =============================================================================

class TestAlertBulkAction:
    """Tests for AlertBulkAction model validation."""

    def test_valid_acknowledge(self):
        """Test valid acknowledge action."""
        action = AlertBulkAction(
            alert_ids=["alert-1", "alert-2"],
            action="acknowledge",
        )
        assert action.action == "acknowledge"
        assert len(action.alert_ids) == 2

    def test_valid_resolve(self):
        """Test valid resolve action."""
        action = AlertBulkAction(
            alert_ids=["alert-1"],
            action="resolve",
        )
        assert action.action == "resolve"

    def test_valid_dismiss(self):
        """Test valid dismiss action."""
        action = AlertBulkAction(
            alert_ids=["alert-1", "alert-2", "alert-3"],
            action="dismiss",
        )
        assert action.action == "dismiss"

    def test_invalid_action_raises(self):
        """Test invalid action raises ValueError."""
        with pytest.raises(ValueError, match="action must be one of"):
            AlertBulkAction(
                alert_ids=["alert-1"],
                action="delete",
            )

        with pytest.raises(ValueError, match="action must be one of"):
            AlertBulkAction(
                alert_ids=["alert-1"],
                action="archive",
            )

    def test_empty_alert_ids_raises(self):
        """Test empty alert_ids raises ValueError."""
        with pytest.raises(ValueError):
            AlertBulkAction(
                alert_ids=[],
                action="acknowledge",
            )

    def test_single_alert_id_valid(self):
        """Test single alert_id is valid."""
        action = AlertBulkAction(
            alert_ids=["alert-1"],
            action="acknowledge",
        )
        assert len(action.alert_ids) == 1

    def test_max_alert_ids(self):
        """Test max alert_ids (100) is valid."""
        action = AlertBulkAction(
            alert_ids=[f"alert-{i}" for i in range(100)],
            action="acknowledge",
        )
        assert len(action.alert_ids) == 100

    def test_over_max_alert_ids_raises(self):
        """Test over max alert_ids (101) raises ValueError."""
        with pytest.raises(ValueError):
            AlertBulkAction(
                alert_ids=[f"alert-{i}" for i in range(101)],
                action="acknowledge",
            )


# =============================================================================
# AlertRuleCreate Tests
# =============================================================================

class TestAlertRuleCreate:
    """Tests for AlertRuleCreate model validation."""

    def test_minimal_valid(self):
        """Test minimal valid AlertRuleCreate."""
        rule = AlertRuleCreate(
            name="Test Rule",
            description="Test description",
            alert_type=AlertType.RISK_SPIKE,
            trigger_condition="risk_score >= 0.7",
        )
        assert rule.name == "Test Rule"
        assert rule.description == "Test description"
        assert rule.alert_type == AlertType.RISK_SPIKE
        assert rule.trigger_condition == "risk_score >= 0.7"
        assert rule.threshold is None  # default
        assert rule.severity == AlertSeverity.MEDIUM  # default
        assert rule.enabled is True  # default

    def test_full_valid(self):
        """Test AlertRuleCreate with all fields."""
        rule = AlertRuleCreate(
            name="Custom Rule",
            description="Custom rule description",
            alert_type=AlertType.FRAUD_PATTERN,
            trigger_condition="pattern_name = 'bid_rotation'",
            threshold=0.85,
            severity=AlertSeverity.CRITICAL,
            enabled=False,
        )
        assert rule.threshold == 0.85
        assert rule.severity == AlertSeverity.CRITICAL
        assert rule.enabled is False

    def test_name_empty_raises(self):
        """Test empty name raises ValueError."""
        with pytest.raises(ValueError):
            AlertRuleCreate(
                name="",
                description="Test",
                alert_type=AlertType.RISK_SPIKE,
                trigger_condition="test",
            )

    def test_name_max_length(self):
        """Test name at max length is valid."""
        rule = AlertRuleCreate(
            name="A" * 100,
            description="Test",
            alert_type=AlertType.RISK_SPIKE,
            trigger_condition="test",
        )
        assert len(rule.name) == 100

    def test_name_over_max_length_raises(self):
        """Test name exceeding max length raises ValueError."""
        with pytest.raises(ValueError):
            AlertRuleCreate(
                name="A" * 101,
                description="Test",
                alert_type=AlertType.RISK_SPIKE,
                trigger_condition="test",
            )

    def test_description_empty_raises(self):
        """Test empty description raises ValueError."""
        with pytest.raises(ValueError):
            AlertRuleCreate(
                name="Test",
                description="",
                alert_type=AlertType.RISK_SPIKE,
                trigger_condition="test",
            )

    def test_description_over_max_length_raises(self):
        """Test description exceeding max length raises ValueError."""
        with pytest.raises(ValueError):
            AlertRuleCreate(
                name="Test",
                description="A" * 501,
                alert_type=AlertType.RISK_SPIKE,
                trigger_condition="test",
            )

    def test_trigger_condition_empty_raises(self):
        """Test empty trigger_condition raises ValueError."""
        with pytest.raises(ValueError):
            AlertRuleCreate(
                name="Test",
                description="Test",
                alert_type=AlertType.RISK_SPIKE,
                trigger_condition="",
            )

    def test_trigger_condition_over_max_length_raises(self):
        """Test trigger_condition exceeding max length raises ValueError."""
        with pytest.raises(ValueError):
            AlertRuleCreate(
                name="Test",
                description="Test",
                alert_type=AlertType.RISK_SPIKE,
                trigger_condition="A" * 2001,
            )


# =============================================================================
# AlertRuleResponse Tests
# =============================================================================

class TestAlertRuleResponse:
    """Tests for AlertRuleResponse model."""

    def test_valid(self):
        """Test valid AlertRuleResponse."""
        now = datetime.now(UTC)
        rule = AlertRuleResponse(
            id="rule-123",
            name="Test Rule",
            description="Test description",
            alert_type=AlertType.RISK_SPIKE,
            trigger_condition="risk_score >= 0.7",
            threshold=0.7,
            severity=AlertSeverity.HIGH,
            enabled=True,
            created_at=now,
        )
        assert rule.id == "rule-123"
        assert rule.name == "Test Rule"
        assert rule.alert_type == AlertType.RISK_SPIKE
        assert rule.severity == AlertSeverity.HIGH
        assert rule.enabled is True
        assert rule.updated_at is None

    def test_with_updated_at(self):
        """Test AlertRuleResponse with updated_at."""
        now = datetime.now(UTC)
        rule = AlertRuleResponse(
            id="rule-123",
            name="Test Rule",
            description="Test",
            alert_type=AlertType.FRAUD_PATTERN,
            trigger_condition="test",
            threshold=None,
            severity=AlertSeverity.MEDIUM,
            enabled=False,
            created_at=now,
            updated_at=now,
        )
        assert rule.updated_at == now


# =============================================================================
# AlertStatistics Tests
# =============================================================================

class TestAlertStatistics:
    """Tests for AlertStatistics model."""

    def test_all_zeros_valid(self):
        """Test AlertStatistics with all zeros is valid."""
        stats = AlertStatistics(
            pending_count=0,
            acknowledged_count=0,
            resolved_count=0,
            dismissed_count=0,
            risk_spike_count=0,
            fraud_pattern_count=0,
            sanction_match_count=0,
            activity_spike_count=0,
            merge_candidate_count=0,
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            info_count=0,
            last_24h_count=0,
            last_7d_count=0,
        )
        assert stats.pending_count == 0
        assert stats.generated_at is not None  # auto-generated

    def test_with_values(self):
        """Test AlertStatistics with non-zero values."""
        stats = AlertStatistics(
            pending_count=5,
            acknowledged_count=3,
            resolved_count=10,
            dismissed_count=2,
            risk_spike_count=8,
            fraud_pattern_count=5,
            sanction_match_count=1,
            activity_spike_count=4,
            merge_candidate_count=2,
            critical_count=3,
            high_count=7,
            medium_count=6,
            low_count=3,
            info_count=1,
            last_24h_count=4,
            last_7d_count=12,
        )
        assert stats.pending_count == 5
        assert stats.critical_count == 3
        assert stats.last_24h_count == 4
        assert stats.last_7d_count == 12

    def test_negative_count_raises(self):
        """Test negative count raises ValueError."""
        with pytest.raises(ValueError):
            AlertStatistics(
                pending_count=-1,
                acknowledged_count=0,
                resolved_count=0,
                dismissed_count=0,
                risk_spike_count=0,
                fraud_pattern_count=0,
                sanction_match_count=0,
                activity_spike_count=0,
                merge_candidate_count=0,
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                info_count=0,
                last_24h_count=0,
                last_7d_count=0,
            )


# =============================================================================
# AlertGeneratorResult Tests
# =============================================================================

class TestAlertGeneratorResult:
    """Tests for AlertGeneratorResult model."""

    def test_minimal_valid(self):
        """Test minimal valid AlertGeneratorResult."""
        result = AlertGeneratorResult(
            generator_name="check_risk_thresholds",
            alerts_created=5,
            alerts_deduplicated=2,
            execution_time_ms=150.5,
        )
        assert result.generator_name == "check_risk_thresholds"
        assert result.alerts_created == 5
        assert result.alerts_deduplicated == 2
        assert result.execution_time_ms == 150.5
        assert result.errors == []  # default

    def test_with_errors(self):
        """Test AlertGeneratorResult with errors."""
        result = AlertGeneratorResult(
            generator_name="check_fraud_patterns",
            alerts_created=0,
            alerts_deduplicated=0,
            execution_time_ms=50.0,
            errors=["DB connection failed", "Timeout"],
        )
        assert len(result.errors) == 2
        assert "DB connection failed" in result.errors

    def test_negative_alerts_raises(self):
        """Test negative alerts_created raises ValueError."""
        with pytest.raises(ValueError):
            AlertGeneratorResult(
                generator_name="test",
                alerts_created=-1,
                alerts_deduplicated=0,
                execution_time_ms=0,
            )

    def test_negative_execution_time_raises(self):
        """Test negative execution_time_ms raises ValueError."""
        with pytest.raises(ValueError):
            AlertGeneratorResult(
                generator_name="test",
                alerts_created=0,
                alerts_deduplicated=0,
                execution_time_ms=-10.0,
            )


# =============================================================================
# AlertGenerationReport Tests
# =============================================================================

class TestAlertGenerationReport:
    """Tests for AlertGenerationReport model."""

    def test_minimal_valid(self):
        """Test minimal valid AlertGenerationReport."""
        now = datetime.now(UTC)
        report = AlertGenerationReport(
            run_id="run-123",
            started_at=now,
            completed_at=now,
            total_alerts_created=10,
            total_alerts_deduplicated=3,
        )
        assert report.run_id == "run-123"
        assert report.generators == []  # default
        assert report.errors == []  # default

    def test_with_generators_and_errors(self):
        """Test report with generator results and errors."""
        now = datetime.now(UTC)
        report = AlertGenerationReport(
            run_id="run-456",
            started_at=now,
            completed_at=now,
            total_alerts_created=15,
            total_alerts_deduplicated=5,
            generators=[
                AlertGeneratorResult(
                    generator_name="check_risk_thresholds",
                    alerts_created=5,
                    alerts_deduplicated=1,
                    execution_time_ms=100.0,
                ),
                AlertGeneratorResult(
                    generator_name="check_fraud_patterns",
                    alerts_created=10,
                    alerts_deduplicated=4,
                    execution_time_ms=200.0,
                    errors=["Pattern DB timeout"],
                ),
            ],
            errors=["Pattern DB timeout"],
        )
        assert len(report.generators) == 2
        assert len(report.errors) == 1
        assert report.total_alerts_created == 15


# =============================================================================
# Alert Model Tests
# =============================================================================

class TestAlertModel:
    """Tests for Alert model."""

    def test_minimal_valid(self):
        """Test minimal valid Alert."""
        alert = Alert(
            id="alert-123",
            type=AlertType.RISK_SPIKE,
            severity=AlertSeverity.HIGH,
            title="Test Alert",
            description="Test description",
        )
        assert alert.id == "alert-123"
        assert alert.type == AlertType.RISK_SPIKE
        assert alert.severity == AlertSeverity.HIGH
        assert alert.status == AlertStatus.PENDING  # default
        assert alert.triggered_by == "system"  # default
        assert alert.metadata == {}  # default
        assert alert.acknowledged_at is None
        assert alert.resolved_at is None
        assert alert.dismissed_at is None

    def test_full_valid(self):
        """Test Alert with all fields."""
        now = datetime.now(UTC)
        alert = Alert(
            id="alert-456",
            type=AlertType.FRAUD_PATTERN,
            severity=AlertSeverity.CRITICAL,
            status=AlertStatus.ACKNOWLEDGED,
            title="Fraud Detected",
            description="Bid rotation pattern",
            entity_type="Company",
            entity_id="company-123",
            entity_cf="12345678901",
            rule_id="rule-789",
            triggered_by="fraud_detector",
            metadata={"pattern": "bid_rotation"},
            alert_hash="abc123hash",
            acknowledged_at=now,
            created_at=now,
            provenance=ProvenanceMetadata(
                source=["fraud_detector"],
                dataset_version="1.0",
                retrieval_date=now,
                confidence=0.95,
            ),
        )
        assert alert.entity_type == "Company"
        assert alert.entity_id == "company-123"
        assert alert.entity_cf == "12345678901"
        assert alert.rule_id == "rule-789"
        assert alert.triggered_by == "fraud_detector"
        assert alert.alert_hash == "abc123hash"
        assert alert.acknowledged_at == now
        assert alert.provenance is not None
        assert alert.provenance.source == ["fraud_detector"]

    def test_title_empty_raises(self):
        """Test empty title raises ValueError."""
        with pytest.raises(ValueError):
            Alert(
                id="alert-1",
                type=AlertType.RISK_SPIKE,
                severity=AlertSeverity.HIGH,
                title="",
                description="Test",
            )

    def test_description_empty_raises(self):
        """Test empty description raises ValueError."""
        with pytest.raises(ValueError):
            Alert(
                id="alert-1",
                type=AlertType.RISK_SPIKE,
                severity=AlertSeverity.HIGH,
                title="Test",
                description="",
            )

    def test_status_lifecycle_transitions(self):
        """Test Alert status reflects lifecycle correctly."""
        # Pending alert
        pending = Alert(
            id="1", type=AlertType.RISK_SPIKE, severity=AlertSeverity.HIGH,
            title="T", description="D", status=AlertStatus.PENDING,
        )
        assert pending.status == AlertStatus.PENDING
        assert pending.acknowledged_at is None

        # Acknowledged alert
        now = datetime.now(UTC)
        acknowledged = Alert(
            id="2", type=AlertType.RISK_SPIKE, severity=AlertSeverity.HIGH,
            title="T", description="D", status=AlertStatus.ACKNOWLEDGED,
            acknowledged_at=now,
        )
        assert acknowledged.status == AlertStatus.ACKNOWLEDGED
        assert acknowledged.acknowledged_at is not None

        # Resolved alert
        resolved = Alert(
            id="3", type=AlertType.RISK_SPIKE, severity=AlertSeverity.HIGH,
            title="T", description="D", status=AlertStatus.RESOLVED,
            acknowledged_at=now, resolved_at=now,
        )
        assert resolved.status == AlertStatus.RESOLVED
        assert resolved.resolved_at is not None

        # Dismissed alert
        dismissed = Alert(
            id="4", type=AlertType.RISK_SPIKE, severity=AlertSeverity.HIGH,
            title="T", description="D", status=AlertStatus.DISMISSED,
            dismissed_at=now,
        )
        assert dismissed.status == AlertStatus.DISMISSED
        assert dismissed.dismissed_at is not None
