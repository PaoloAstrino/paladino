"""
Unit tests for the Notification Dispatcher.
"""

import json
import tempfile
from datetime import datetime, UTC
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from paladino.app.notification_dispatcher import NotificationDispatcher
from paladino.models import Alert, AlertSeverity, AlertStatus, AlertType


@pytest.fixture
def sample_alert():
    """Create a sample alert for testing."""
    return Alert(
        id="test-alert-uuid",
        type=AlertType.FRAUD_PATTERN,
        severity=AlertSeverity.CRITICAL,
        status=AlertStatus.PENDING,
        title="Bid Rotation Detected",
        description="Companies X, Y, Z winning alternately in 5 tenders",
        entity_type="Company",
        entity_id="company-123",
        entity_cf="MRARSS80A00A000A",
        rule_id="rule-1",
        triggered_by="fraud_detector",
        metadata={},
        alert_hash="abc123",
        acknowledged_at=None,
        resolved_at=None,
        dismissed_at=None,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def temp_log_file():
    """Create a temporary log file path."""
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
        yield f.name
    Path(f.name).unlink(missing_ok=True)


# ──────────────────────────────────────────────────────────────
# Severity helpers
# ──────────────────────────────────────────────────────────────


def test_severity_rank():
    assert NotificationDispatcher._severity_rank(AlertSeverity.CRITICAL) == 5
    assert NotificationDispatcher._severity_rank(AlertSeverity.HIGH) == 4
    assert NotificationDispatcher._severity_rank(AlertSeverity.MEDIUM) == 3
    assert NotificationDispatcher._severity_rank(AlertSeverity.LOW) == 2
    assert NotificationDispatcher._severity_rank(AlertSeverity.INFO) == 1


def test_severity_emoji():
    assert NotificationDispatcher._severity_emoji(AlertSeverity.CRITICAL) == "🚨"
    assert NotificationDispatcher._severity_emoji(AlertSeverity.HIGH) == "⚠️"
    assert NotificationDispatcher._severity_emoji(AlertSeverity.MEDIUM) == "🔶"
    assert NotificationDispatcher._severity_emoji(AlertSeverity.LOW) == "🔵"
    assert NotificationDispatcher._severity_emoji(AlertSeverity.INFO) == "ℹ️"


# ──────────────────────────────────────────────────────────────
# Log file notifications
# ──────────────────────────────────────────────────────────────


def test_write_alert_log(sample_alert, temp_log_file):
    """Alert should be written to log file."""
    dispatcher = NotificationDispatcher(log_file=temp_log_file)
    result = dispatcher._write_alert_log(sample_alert)

    assert result is True
    log_path = Path(temp_log_file)
    assert log_path.exists()

    content = log_path.read_text(encoding="utf-8")
    entry = json.loads(content.strip())
    assert entry["alert_id"] == "test-alert-uuid"
    assert entry["severity"] == "critical"
    assert entry["title"] == "Bid Rotation Detected"


def test_write_alert_log_creates_directory():
    """Log file should create parent directories if needed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "subdir" / "alerts.log"
        dispatcher = NotificationDispatcher(log_file=str(log_path))
        alert = Alert(
            id="test-1", type=AlertType.RISK_SPIKE, severity=AlertSeverity.HIGH,
            status=AlertStatus.PENDING, title="Test", description="Test alert",
            entity_type="Company", entity_id="c1", created_at=datetime.now(UTC),
        )
        result = dispatcher._write_alert_log(alert)
        assert result is True
        assert log_path.exists()


# ──────────────────────────────────────────────────────────────
# Desktop notifications
# ──────────────────────────────────────────────────────────────


def test_desktop_notification_skipped_for_low_severity(sample_alert, temp_log_file):
    """Low severity alerts should not trigger desktop notifications."""
    alert = Alert(
        id="low-alert", type=AlertType.MERGE_CANDIDATE, severity=AlertSeverity.LOW,
        status=AlertStatus.PENDING, title="Possible Duplicate", description="Test dup",
        entity_type="Company", entity_id="c1", created_at=datetime.now(UTC),
    )
    dispatcher = NotificationDispatcher(log_file=temp_log_file, min_severity=AlertSeverity.HIGH)

    # Desktop should be skipped (below threshold)
    result = dispatcher._send_desktop(alert)
    assert result is True  # True means "skipped gracefully", not "failed"


def test_desktop_notification_attempts_for_critical(sample_alert, temp_log_file):
    """Critical alerts should attempt desktop notification."""
    dispatcher = NotificationDispatcher(log_file=temp_log_file)

    # With no desktop backend available, should return False (not raise)
    result = dispatcher._send_desktop(sample_alert)
    assert result is False  # No backend installed in test env


# ──────────────────────────────────────────────────────────────
# Webhook notifications
# ──────────────────────────────────────────────────────────────


def test_webhook_not_configured(sample_alert, temp_log_file):
    """Webhook should return False when not configured."""
    dispatcher = NotificationDispatcher(log_file=temp_log_file)
    result = dispatcher._send_webhook(sample_alert)
    assert result is False


def test_webhook_success(sample_alert, temp_log_file):
    """Webhook should POST to configured URL."""
    with patch("requests.post") as mock_post:
        mock_post.return_value = MagicMock()
        mock_post.return_value.raise_for_status = MagicMock()

        dispatcher = NotificationDispatcher(
            log_file=temp_log_file,
            webhook_url="http://example.com/webhook",
        )
        result = dispatcher._send_webhook(sample_alert)
        assert result is True
        mock_post.assert_called_once()


def test_webhook_failure(sample_alert, temp_log_file):
    """Webhook failure should return False, not raise."""
    with patch("requests.post", side_effect=Exception("Connection refused")):
        dispatcher = NotificationDispatcher(
            log_file=temp_log_file,
            webhook_url="http://localhost:9999",
        )
        result = dispatcher._send_webhook(sample_alert)
        assert result is False


# ──────────────────────────────────────────────────────────────
# Full dispatch pipeline
# ──────────────────────────────────────────────────────────────


def test_dispatch_all_channels(sample_alert, temp_log_file):
    """Dispatch should attempt all channels and return results."""
    dispatcher = NotificationDispatcher(log_file=temp_log_file)
    results = dispatcher.dispatch(sample_alert)

    assert "desktop" in results
    assert "log_file" in results
    assert "webhook" in results

    # Log file should always succeed
    assert results["log_file"] is True
    # Desktop will be False (no backend) or True (skipped for severity check)
    assert isinstance(results["desktop"], bool)
    # Webhook False (not configured)
    assert results["webhook"] is False


def test_dispatch_batch(sample_alert, temp_log_file):
    """Dispatch batch should process all alerts."""
    dispatcher = NotificationDispatcher(log_file=temp_log_file)
    alerts = [
        Alert(
            id=f"alert-{i}", type=AlertType.FRAUD_PATTERN, severity=AlertSeverity.HIGH,
            status=AlertStatus.PENDING, title=f"Alert {i}", description=f"Desc {i}",
            entity_type="Company", entity_id=f"c{i}", created_at=datetime.now(UTC),
        )
        for i in range(3)
    ]

    results = dispatcher.dispatch_batch(alerts)
    assert len(results) == 3
    for r in results:
        assert "log_file" in r
        assert r["log_file"] is True


# ──────────────────────────────────────────────────────────────
# Backend detection
# ──────────────────────────────────────────────────────────────


def test_init_no_backend_available():
    """When no notification backend is available, should fall back to 'none'."""
    # In test environment, neither windows_toasts nor plyer is installed
    dispatcher = NotificationDispatcher()
    # Should not raise, should gracefully fall back
    assert dispatcher._toast_backend in ("none", "windows", "plyer")
    # If no backend, _send_desktop should return False without raising
    alert = Alert(
        id="t1", type=AlertType.FRAUD_PATTERN, severity=AlertSeverity.CRITICAL,
        status=AlertStatus.PENDING, title="T", description="D",
        entity_type="Company", entity_id="c1", created_at=datetime.now(UTC),
    )
    if dispatcher._toast_backend == "none":
        result = dispatcher._send_desktop(alert)
        assert result is False
