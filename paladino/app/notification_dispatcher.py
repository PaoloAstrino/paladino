"""
Notification Dispatcher for Paladino.

Dispatches alerts through multiple channels:
1. Desktop notifications (Windows toasts, macOS notifications, Linux notify-send)
2. Log file alerts (appends to audit_logs/alerts.log)
3. Webhook notifications (POST to configured URL)

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.app.notification_dispatcher import NotificationDispatcher
    from paladino.models import Alert, AlertSeverity, AlertType

    dispatcher = NotificationDispatcher()

    # Dispatch a single alert
    alert = Alert(
        id="alert-uuid",
        type=AlertType.FRAUD_PATTERN,
        severity=AlertSeverity.CRITICAL,
        title="Bid Rotation Detected",
        description="Companies X, Y, Z winning alternately",
        entity_type="Company",
        entity_id="company-uuid",
    )
    dispatcher.dispatch(alert)
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from paladino.config import settings
from paladino.models import Alert, AlertSeverity

# ─────────────────────────────────────────────────────────────────────────────
# Severity → notification priority mapping
# ─────────────────────────────────────────────────────────────────────────────

_SEVERITY_PRIORITY = {
    AlertSeverity.CRITICAL: 2,  # High priority — always show
    AlertSeverity.HIGH: 2,
    AlertSeverity.MEDIUM: 1,
    AlertSeverity.LOW: 0,
    AlertSeverity.INFO: 0,
}

# Minimum severity to trigger desktop notification
# Change to CRITICAL to only see critical alerts
_DESKTOP_MIN_SEVERITY = AlertSeverity.HIGH


class NotificationDispatcher:
    """
    Dispatches alerts through configured notification channels.

    Channels (tried in order, all are attempted):
    1. Desktop notifications (OS-native)
    2. Alert log file
    3. Webhook (if configured)
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        log_file: str | None = None,
        min_severity: AlertSeverity = _DESKTOP_MIN_SEVERITY,
    ) -> None:
        self.webhook_url = webhook_url or getattr(settings, "alert_webhook_url", None)
        self.log_file = log_file or str(Path("audit_logs") / "alerts.log")
        self.min_severity = min_severity

        # Lazy init notification backends
        self._toast_backend: str | None = None  # "windows", "plyer", "none"
        self._init_toast_backend()

    def dispatch(self, alert: Alert) -> dict[str, bool]:
        """
        Dispatch an alert through all configured channels.

        Args:
            alert: Alert model to dispatch

        Returns:
            Dict of channel → success status
        """
        results: dict[str, bool] = {}

        # 1. Desktop notification (for HIGH/CRITICAL)
        results["desktop"] = self._send_desktop(alert)

        # 2. Log file (all alerts)
        results["log_file"] = self._write_alert_log(alert)

        # 3. Webhook (if configured)
        if self.webhook_url:
            results["webhook"] = self._send_webhook(alert)
        else:
            results["webhook"] = False  # Not configured, not a failure

        return results

    def dispatch_batch(self, alerts: list[Alert]) -> list[dict[str, bool]]:
        """
        Dispatch multiple alerts.

        Args:
            alerts: List of alerts to dispatch

        Returns:
            List of result dicts (one per alert)
        """
        results = []
        for alert in alerts:
            results.append(self.dispatch(alert))
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Desktop Notifications
    # ──────────────────────────────────────────────────────────────────────────

    def _init_toast_backend(self) -> None:
        """Detect available desktop notification backend."""
        # Try Windows native first
        try:
            from windows_toasts import WindowsToaster
            self._toast_backend = "windows"
            logger.info("Notification dispatcher: using Windows native toasts")
            return
        except ImportError:
            pass

        # Try plyer (cross-platform)
        try:
            import plyer
            self._toast_backend = "plyer"
            logger.info("Notification dispatcher: using plyer notifications")
            return
        except ImportError:
            pass

        # Fallback: no desktop notifications
        self._toast_backend = "none"
        logger.warning(
            "Notification dispatcher: no desktop notification backend available. "
            "Install 'windows-toasts' (Windows) or 'plyer' (cross-platform)."
        )

    def _send_desktop(self, alert: Alert) -> bool:
        """Send a desktop notification if severity meets threshold."""
        if self._severity_rank(alert.severity) < self._severity_rank(self.min_severity):
            return True  # Skipped, not a failure

        if self._toast_backend == "windows":
            return self._send_windows_toast(alert)
        elif self._toast_backend == "plyer":
            return self._send_plyer_notification(alert)
        else:
            return False  # No backend available

    def _send_windows_toast(self, alert: Alert) -> bool:
        """Send Windows native toast notification."""
        try:
            from windows_toasts import Toast, ToastButton, ToastDisplayImage, ToastImage, ToastInputTextField, WindowsToaster

            severity_emoji = self._severity_emoji(alert.severity)
            title = f"{severity_emoji} {alert.severity.upper()}: {alert.title}"
            message = alert.description[:200] if alert.description else ""

            toast = Toast(
                [f"🛡️ Paladino Alert — {alert.type.value}"],
            )
            toast.SetAttributionText(f"Entity: {alert.entity_type} ({alert.entity_id or 'N/A'})")
            toast.AddText(title)
            toast.AddText(message)
            toast.SetDuration("long")

            toaster = WindowsToaster("Paladino")
            toaster.show_toast(toast)

            logger.info(f"Desktop notification sent: {alert.id[:8]}... [{alert.severity.value}] {alert.title}")
            return True
        except Exception as e:
            logger.warning(f"Windows toast notification failed: {e}")
            return False

    def _send_plyer_notification(self, alert: Alert) -> bool:
        """Send cross-platform notification via plyer."""
        try:
            from plyer import notification

            severity_emoji = self._severity_emoji(alert.severity)
            title = f"{severity_emoji} {alert.severity.upper()}: {alert.title}"
            message = alert.description[:200] if alert.description else ""

            notification.notify(
                title=title,
                message=message,
                app_name="Paladino",
                timeout=10,
            )
            return True
        except Exception as e:
            logger.warning(f"Plyer notification failed: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Log File Notifications
    # ──────────────────────────────────────────────────────────────────────────

    def _write_alert_log(self, alert: Alert) -> bool:
        """Append alert to structured log file."""
        try:
            log_path = Path(self.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            log_entry = {
                "timestamp": datetime.now(UTC).isoformat(),
                "alert_id": alert.id,
                "type": alert.type.value,
                "severity": alert.severity.value,
                "title": alert.title,
                "description": alert.description,
                "entity_type": alert.entity_type,
                "entity_id": alert.entity_id,
                "entity_cf": getattr(alert, "entity_cf", None),
                "status": alert.status.value if hasattr(alert, "status") and alert.status else "pending",
                "triggered_by": getattr(alert, "triggered_by", "system"),
            }

            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

            return True
        except Exception as e:
            logger.warning(f"Alert log write failed: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Webhook Notifications
    # ──────────────────────────────────────────────────────────────────────────

    def _send_webhook(self, alert: Alert) -> bool:
        """POST alert to configured webhook URL."""
        if not self.webhook_url:
            return False

        try:
            import requests

            payload = {
                "alert_id": alert.id,
                "type": alert.type.value,
                "severity": alert.severity.value,
                "title": alert.title,
                "description": alert.description,
                "entity_type": alert.entity_type,
                "entity_id": alert.entity_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }

            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning(f"Webhook notification failed: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _severity_rank(severity: AlertSeverity) -> int:
        """Convert severity to numeric rank for comparison."""
        ranks = {
            AlertSeverity.CRITICAL: 5,
            AlertSeverity.HIGH: 4,
            AlertSeverity.MEDIUM: 3,
            AlertSeverity.LOW: 2,
            AlertSeverity.INFO: 1,
        }
        return ranks.get(severity, 0)

    @staticmethod
    def _severity_emoji(severity: AlertSeverity) -> str:
        """Return emoji for severity level."""
        emojis = {
            AlertSeverity.CRITICAL: "🚨",
            AlertSeverity.HIGH: "⚠️",
            AlertSeverity.MEDIUM: "🔶",
            AlertSeverity.LOW: "🔵",
            AlertSeverity.INFO: "ℹ️",
        }
        return emojis.get(severity, "📋")
