"""
Alert/Notification Service for Paladino.

Provides proactive fraud detection by notifying analysts when:
- Risk score crosses threshold (e.g., Medium → High)
- New fraud pattern detected (carousel, subcontractor concentration)
- New sanction/adverse media linked to monitored entity
- Significant activity spike (tender volume, value)
- Merge candidate found (duplicate entity)

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.app.alert_service import AlertService
    from paladino.db import Neo4jConnection

    conn = Neo4jConnection()
    service = AlertService(conn)

    # Create an alert
    alert = service.create_alert(AlertCreate(
        type=AlertType.RISK_SPIKE,
        severity=AlertSeverity.CRITICAL,
        title="Risk Score → High",
        description="Company ACME SRL risk score crossed 0.7 threshold",
        entity_type="Company",
        entity_id="company-uuid",
        entity_cf="12345678901",
    ))

    # List pending alerts
    alerts, total = service.list_alerts(AlertListParams(
        status=AlertStatus.PENDING,
        limit=20,
    ))

    # Run all alert generators
    report = service.run_all_generators()

    # Get dashboard statistics
    stats = service.get_alert_statistics()
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timedelta, UTC
from typing import Any

from loguru import logger

from paladino.db import Neo4jConnection
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


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Deduplication window: prevent duplicate alerts within this period
ALERT_DEDUP_WINDOW_HOURS = 24

# Default predefined alert rules
DEFAULT_ALERT_RULES: list[dict[str, Any]] = [
    {
        "name": "Risk Score → High",
        "description": "Alert when a company's risk score reaches or exceeds 0.7 (High threshold)",
        "alert_type": AlertType.RISK_SPIKE,
        "trigger_condition": "risk_score >= 0.7",
        "threshold": 0.7,
        "severity": AlertSeverity.CRITICAL,
        "enabled": True,
    },
    {
        "name": "Risk Tier Crossing",
        "description": "Alert when a company crosses risk tier boundaries (LOW→MEDIUM, MEDIUM→HIGH)",
        "alert_type": AlertType.RISK_SPIKE,
        "trigger_condition": "tier_change_detected",
        "threshold": None,
        "severity": AlertSeverity.HIGH,
        "enabled": True,
    },
    {
        "name": "Carousel Fraud",
        "description": "Alert when bid rotation pattern is detected by fraud detector",
        "alert_type": AlertType.FRAUD_PATTERN,
        "trigger_condition": "pattern_name = 'bid_rotation'",
        "threshold": None,
        "severity": AlertSeverity.CRITICAL,
        "enabled": True,
    },
    {
        "name": "Board Overlap Collusion",
        "description": "Alert when board overlap collusion pattern is detected",
        "alert_type": AlertType.FRAUD_PATTERN,
        "trigger_condition": "pattern_name = 'board_overlap'",
        "threshold": None,
        "severity": AlertSeverity.HIGH,
        "enabled": True,
    },
    {
        "name": "Subcontractor Concentration",
        "description": "Alert when >60% of subcontracting goes to a single company",
        "alert_type": AlertType.FRAUD_PATTERN,
        "trigger_condition": "pattern_name = 'subcontractor_concentration'",
        "threshold": 0.6,
        "severity": AlertSeverity.HIGH,
        "enabled": True,
    },
    {
        "name": "Single Bidder Spike",
        "description": "Alert when single bidder ratio exceeds 0.8 for a company",
        "alert_type": AlertType.ACTIVITY_SPIKE,
        "trigger_condition": "single_bidder_ratio > 0.8",
        "threshold": 0.8,
        "severity": AlertSeverity.MEDIUM,
        "enabled": True,
    },
    {
        "name": "Tender Volume Spike",
        "description": "Alert when tender volume exceeds 3x the average",
        "alert_type": AlertType.ACTIVITY_SPIKE,
        "trigger_condition": "volume > 3 * avg_volume",
        "threshold": 3.0,
        "severity": AlertSeverity.MEDIUM,
        "enabled": True,
    },
    {
        "name": "Duplicate Company Found",
        "description": "Alert when a potential duplicate company is detected (similarity > 0.85)",
        "alert_type": AlertType.MERGE_CANDIDATE,
        "trigger_condition": "similarity_score > 0.85",
        "threshold": 0.85,
        "severity": AlertSeverity.LOW,
        "enabled": True,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class AlertService:
    """
    Service layer for alert/notification operations.

    Handles all CRUD operations for alerts and alert rules,
    plus automated alert generation from risk/fraud/merge systems.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ── Alert CRUD ──────────────────────────────────────────────────────────

    def create_alert(self, alert_data: AlertCreate) -> Alert:
        """
        Create a new alert with deduplication check.

        Parameters
        ----------
        alert_data:
            AlertCreate schema with alert details.

        Returns
        -------
        Alert with the created alert details.

        Raises
        ------
        ValueError if title or description is invalid.
        """
        # Calculate alert hash for deduplication
        alert_hash = self._calculate_alert_hash(alert_data)

        # Check for duplicate unless explicitly skipped
        if not alert_data.skip_dedup and self._is_duplicate_alert(alert_hash):
            logger.debug(
                f"Duplicate alert skipped: {alert_data.type.value} - {alert_data.title}"
            )
            # Return a synthetic alert indicating it was deduplicated
            return Alert(
                id="",
                type=alert_data.type,
                severity=alert_data.severity,
                status=AlertStatus.PENDING,
                title=alert_data.title,
                description=alert_data.description,
                entity_type=alert_data.entity_type,
                entity_id=alert_data.entity_id,
                entity_cf=alert_data.entity_cf,
                rule_id=alert_data.rule_id,
                triggered_by=alert_data.triggered_by,
                metadata={"deduplicated": True},
                alert_hash=alert_hash,
            )

        alert_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Build provenance metadata
        provenance = ProvenanceMetadata(
            source=[alert_data.triggered_by],
            dataset_version="1.0",
            retrieval_date=now,
            confidence=1.0,
        )

        query = """
        CREATE (a:Alert {
            id: $id,
            type: $type,
            severity: $severity,
            status: $status,
            title: $title,
            description: $description,
            entity_type: $entity_type,
            entity_id: $entity_id,
            entity_cf: $entity_cf,
            rule_id: $rule_id,
            triggered_by: $triggered_by,
            metadata: $metadata,
            alert_hash: $alert_hash,
            acknowledged_at: null,
            resolved_at: null,
            dismissed_at: null,
            created_at: $created_at,
            provenance: $provenance
        })
        RETURN a
        """

        params = {
            "id": alert_id,
            "type": alert_data.type.value,
            "severity": alert_data.severity.value,
            "status": AlertStatus.PENDING.value,
            "title": alert_data.title,
            "description": alert_data.description,
            "entity_type": alert_data.entity_type,
            "entity_id": alert_data.entity_id,
            "entity_cf": alert_data.entity_cf,
            "rule_id": alert_data.rule_id,
            "triggered_by": alert_data.triggered_by,
            "metadata": alert_data.metadata,
            "alert_hash": alert_hash,
            "created_at": now.isoformat(),
            "provenance": provenance.model_dump(),
        }

        result = self.conn.run_query(query, params)
        if not result:
            raise RuntimeError("Failed to create alert")

        logger.info(
            f"Created alert {alert_id} [{alert_data.severity.value}] {alert_data.title}"
        )

        # Hook for future notification delivery
        self._send_notification(alert_id, alert_data)

        return self._record_to_alert(result[0]["a"])

    def get_alert(self, alert_id: str) -> Alert | None:
        """
        Get a single alert by ID.

        Parameters
        ----------
        alert_id:
            UUID of the alert.

        Returns
        -------
        Alert if found, None otherwise.
        """
        query = """
        MATCH (a:Alert {id: $alert_id})
        RETURN a
        """

        result = self.conn.run_query(query, {"alert_id": alert_id})
        if not result:
            return None

        return self._record_to_alert(result[0]["a"])

    def list_alerts(self, params: AlertListParams) -> tuple[list[Alert], int]:
        """
        List alerts with filtering and pagination.

        Parameters
        ----------
        params:
            AlertListParams with filters, pagination, and sorting.

        Returns
        -------
        Tuple of (list of Alert, total count).
        """
        # Build dynamic query based on filters
        where_clauses = []
        query_params: dict[str, Any] = {}

        if params.status:
            where_clauses.append("a.status = $status")
            query_params["status"] = params.status.value

        if params.type:
            where_clauses.append("a.type = $type")
            query_params["type"] = params.type.value

        if params.severity:
            where_clauses.append("a.severity = $severity")
            query_params["severity"] = params.severity.value

        if params.entity_id:
            where_clauses.append("a.entity_id = $entity_id")
            query_params["entity_id"] = params.entity_id

        if params.entity_type:
            where_clauses.append("a.entity_type = $entity_type")
            query_params["entity_type"] = params.entity_type

        if params.entity_cf:
            where_clauses.append("a.entity_cf = $entity_cf")
            query_params["entity_cf"] = params.entity_cf

        if params.rule_id:
            where_clauses.append("a.rule_id = $rule_id")
            query_params["rule_id"] = params.rule_id

        if params.date_from:
            where_clauses.append("a.created_at >= $date_from")
            query_params["date_from"] = params.date_from.isoformat()

        if params.date_to:
            where_clauses.append("a.created_at <= $date_to")
            query_params["date_to"] = params.date_to.isoformat()

        where_clause = " AND ".join(where_clauses) if where_clauses else "true"

        # Count query
        count_query = f"""
        MATCH (a:Alert)
        WHERE {where_clause}
        RETURN count(a) as total
        """

        count_result = self.conn.run_query(count_query, query_params)
        total = count_result[0]["total"] if count_result else 0

        if total == 0:
            return [], 0

        # Data query with pagination and sorting
        sort_direction = "ASC" if params.sort_order == "asc" else "DESC"
        data_query = f"""
        MATCH (a:Alert)
        WHERE {where_clause}
        RETURN a
        ORDER BY a.{params.sort_by} {sort_direction}
        SKIP $offset
        LIMIT $limit
        """

        query_params["offset"] = params.offset
        query_params["limit"] = params.limit

        result = self.conn.run_query(data_query, query_params)
        alerts = [self._record_to_alert(record["a"]) for record in result]

        return alerts, total

    def update_alert(self, alert_id: str, update_data: AlertUpdate) -> Alert | None:
        """
        Update an alert's title, description, or metadata.

        Parameters
        ----------
        alert_id:
            UUID of the alert to update.
        update_data:
            AlertUpdate with fields to update.

        Returns
        -------
        Alert if updated, None if alert not found.
        """
        if not any([update_data.title, update_data.description, update_data.metadata]):
            raise ValueError("No fields to update")

        # Get current alert
        current = self.get_alert(alert_id)
        if not current:
            return None

        set_clauses = []
        params: dict[str, Any] = {"alert_id": alert_id}

        if update_data.title is not None:
            set_clauses.append("a.title = $title")
            params["title"] = update_data.title

        if update_data.description is not None:
            set_clauses.append("a.description = $description")
            params["description"] = update_data.description

        if update_data.metadata is not None:
            set_clauses.append("a.metadata = $metadata")
            params["metadata"] = update_data.metadata

        set_clause = ", ".join(set_clauses)

        query = f"""
        MATCH (a:Alert {{id: $alert_id}})
        SET {set_clause}
        RETURN a
        """

        result = self.conn.run_query(query, params)
        if not result:
            return None

        logger.info(f"Updated alert {alert_id}")

        return self._record_to_alert(result[0]["a"])

    def update_alert_status(
        self, alert_id: str, new_status: AlertStatus
    ) -> Alert | None:
        """
        Update alert status with proper timestamp tracking.

        Status workflow:
        - pending → acknowledged (sets acknowledged_at)
        - acknowledged → resolved (sets resolved_at)
        - acknowledged → dismissed (sets dismissed_at)
        - pending → resolved (sets resolved_at)
        - pending → dismissed (sets dismissed_at)

        Parameters
        ----------
        alert_id:
            UUID of the alert.
        new_status:
            New status to set.

        Returns
        -------
        Alert if updated, None if alert not found.

        Raises
        ------
        ValueError if status transition is invalid.
        """
        current = self.get_alert(alert_id)
        if not current:
            return None

        # Validate status transitions
        self._validate_status_transition(current.status, new_status)

        now = datetime.now(UTC)
        set_clauses = ["a.status = $status"]
        params: dict[str, Any] = {"alert_id": alert_id, "status": new_status.value}

        # Set appropriate timestamp
        if new_status == AlertStatus.ACKNOWLEDGED:
            set_clauses.append("a.acknowledged_at = $timestamp")
            params["timestamp"] = now.isoformat()
        elif new_status == AlertStatus.RESOLVED:
            set_clauses.append("a.resolved_at = $timestamp")
            params["timestamp"] = now.isoformat()
        elif new_status == AlertStatus.DISMISSED:
            set_clauses.append("a.dismissed_at = $timestamp")
            params["timestamp"] = now.isoformat()

        set_clause = ", ".join(set_clauses)

        query = f"""
        MATCH (a:Alert {{id: $alert_id}})
        SET {set_clause}
        RETURN a
        """

        result = self.conn.run_query(query, params)
        if not result:
            return None

        logger.info(
            f"Alert {alert_id} status changed: {current.status.value} → {new_status.value}"
        )

        return self._record_to_alert(result[0]["a"])

    def bulk_update_status(self, action: AlertBulkAction) -> int:
        """
        Bulk update status for multiple alerts.

        Parameters
        ----------
        action:
            AlertBulkAction with alert IDs and action.

        Returns
        -------
        Number of alerts updated.
        """
        status_map = {
            "acknowledge": AlertStatus.ACKNOWLEDGED,
            "resolve": AlertStatus.RESOLVED,
            "dismiss": AlertStatus.DISMISSED,
        }
        new_status = status_map[action.action]
        now = datetime.now(UTC)

        timestamp_field = {
            AlertStatus.ACKNOWLEDGED: "acknowledged_at",
            AlertStatus.RESOLVED: "resolved_at",
            AlertStatus.DISMISSED: "dismissed_at",
        }[new_status]

        query = f"""
        MATCH (a:Alert)
        WHERE a.id IN $alert_ids
        SET a.status = $status,
            a.{timestamp_field} = $timestamp
        RETURN count(a) as updated
        """

        params = {
            "alert_ids": action.alert_ids,
            "status": new_status.value,
            "timestamp": now.isoformat(),
        }

        result = self.conn.run_query(query, params)
        updated = result[0]["updated"] if result else 0

        logger.info(
            f"Bulk action '{action.action}' updated {updated} alerts"
        )

        return updated

    def delete_alert(self, alert_id: str) -> bool:
        """
        Hard delete an alert (admin only).

        WARNING: This is irreversible. Use status transitions
        (resolve/dismiss) for normal operations.

        Parameters
        ----------
        alert_id:
            UUID of the alert to delete.

        Returns
        -------
        True if deleted, False if not found.
        """
        query = """
        MATCH (a:Alert {id: $alert_id})
        DETACH DELETE a
        """

        result = self.conn.run_query(query, {"alert_id": alert_id})
        # Neo4j returns summary with counters
        deleted = result[0].get("deleted", 0) if result else 0

        if deleted > 0:
            logger.info(f"Hard deleted alert {alert_id}")

        return deleted > 0

    def get_alert_statistics(self) -> AlertStatistics:
        """
        Get alert statistics for dashboard.

        Returns
        -------
        AlertStatistics with counts by status, type, severity, and time.
        """
        now = datetime.now(UTC)
        twenty_four_hours_ago = (now - timedelta(hours=24)).isoformat()
        seven_days_ago = (now - timedelta(days=7)).isoformat()

        # Single query to get all statistics
        query = """
        MATCH (a:Alert)
        WITH
            // By status
            sum(CASE WHEN a.status = 'pending' THEN 1 ELSE 0 END) as pending_count,
            sum(CASE WHEN a.status = 'acknowledged' THEN 1 ELSE 0 END) as acknowledged_count,
            sum(CASE WHEN a.status = 'resolved' THEN 1 ELSE 0 END) as resolved_count,
            sum(CASE WHEN a.status = 'dismissed' THEN 1 ELSE 0 END) as dismissed_count,
            // By type
            sum(CASE WHEN a.type = 'risk_spike' THEN 1 ELSE 0 END) as risk_spike_count,
            sum(CASE WHEN a.type = 'fraud_pattern' THEN 1 ELSE 0 END) as fraud_pattern_count,
            sum(CASE WHEN a.type = 'sanction_match' THEN 1 ELSE 0 END) as sanction_match_count,
            sum(CASE WHEN a.type = 'activity_spike' THEN 1 ELSE 0 END) as activity_spike_count,
            sum(CASE WHEN a.type = 'merge_candidate' THEN 1 ELSE 0 END) as merge_candidate_count,
            // By severity
            sum(CASE WHEN a.severity = 'critical' THEN 1 ELSE 0 END) as critical_count,
            sum(CASE WHEN a.severity = 'high' THEN 1 ELSE 0 END) as high_count,
            sum(CASE WHEN a.severity = 'medium' THEN 1 ELSE 0 END) as medium_count,
            sum(CASE WHEN a.severity = 'low' THEN 1 ELSE 0 END) as low_count,
            sum(CASE WHEN a.severity = 'info' THEN 1 ELSE 0 END) as info_count,
            // By time
            sum(CASE WHEN a.created_at >= $twenty_four_hours_ago THEN 1 ELSE 0 END) as last_24h_count,
            sum(CASE WHEN a.created_at >= $seven_days_ago THEN 1 ELSE 0 END) as last_7d_count
        RETURN pending_count, acknowledged_count, resolved_count, dismissed_count,
               risk_spike_count, fraud_pattern_count, sanction_match_count,
               activity_spike_count, merge_candidate_count,
               critical_count, high_count, medium_count, low_count, info_count,
               last_24h_count, last_7d_count
        """

        params = {
            "twenty_four_hours_ago": twenty_four_hours_ago,
            "seven_days_ago": seven_days_ago,
        }

        result = self.conn.run_query(query, params)
        if not result:
            return AlertStatistics(
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

        row = result[0]
        return AlertStatistics(
            pending_count=row.get("pending_count", 0),
            acknowledged_count=row.get("acknowledged_count", 0),
            resolved_count=row.get("resolved_count", 0),
            dismissed_count=row.get("dismissed_count", 0),
            risk_spike_count=row.get("risk_spike_count", 0),
            fraud_pattern_count=row.get("fraud_pattern_count", 0),
            sanction_match_count=row.get("sanction_match_count", 0),
            activity_spike_count=row.get("activity_spike_count", 0),
            merge_candidate_count=row.get("merge_candidate_count", 0),
            critical_count=row.get("critical_count", 0),
            high_count=row.get("high_count", 0),
            medium_count=row.get("medium_count", 0),
            low_count=row.get("low_count", 0),
            info_count=row.get("info_count", 0),
            last_24h_count=row.get("last_24h_count", 0),
            last_7d_count=row.get("last_7d_count", 0),
        )

    # ── Alert Rule CRUD ─────────────────────────────────────────────────────

    def create_rule(self, rule_data: AlertRuleCreate) -> AlertRuleResponse:
        """
        Create a custom alert rule.

        Parameters
        ----------
        rule_data:
            AlertRuleCreate schema with rule details.

        Returns
        -------
        AlertRuleResponse with the created rule details.
        """
        rule_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        query = """
        CREATE (r:AlertRule {
            id: $id,
            name: $name,
            description: $description,
            alert_type: $alert_type,
            trigger_condition: $trigger_condition,
            threshold: $threshold,
            severity: $severity,
            enabled: $enabled,
            created_at: $created_at,
            updated_at: null
        })
        RETURN r
        """

        params = {
            "id": rule_id,
            "name": rule_data.name,
            "description": rule_data.description,
            "alert_type": rule_data.alert_type.value,
            "trigger_condition": rule_data.trigger_condition,
            "threshold": rule_data.threshold,
            "severity": rule_data.severity.value,
            "enabled": rule_data.enabled,
            "created_at": now.isoformat(),
        }

        result = self.conn.run_query(query, params)
        if not result:
            raise RuntimeError("Failed to create alert rule")

        logger.info(f"Created alert rule {rule_id}: {rule_data.name}")

        return self._record_to_rule_response(result[0]["r"])

    def list_rules(self, enabled_only: bool = False) -> list[AlertRuleResponse]:
        """
        List all alert rules.

        Parameters
        ----------
        enabled_only:
            If True, only return enabled rules.

        Returns
        -------
        List of AlertRuleResponse.
        """
        where_clause = "WHERE r.enabled = true" if enabled_only else ""

        query = f"""
        MATCH (r:AlertRule)
        {where_clause}
        RETURN r
        ORDER BY r.name ASC
        """

        result = self.conn.run_query(query, {})
        return [self._record_to_rule_response(record["r"]) for record in result]

    def get_rule(self, rule_id: str) -> AlertRuleResponse | None:
        """
        Get a single alert rule by ID.

        Parameters
        ----------
        rule_id:
            UUID of the rule.

        Returns
        -------
        AlertRuleResponse if found, None otherwise.
        """
        query = """
        MATCH (r:AlertRule {id: $rule_id})
        RETURN r
        """

        result = self.conn.run_query(query, {"rule_id": rule_id})
        if not result:
            return None

        return self._record_to_rule_response(result[0]["r"])

    def update_rule(self, rule_id: str, rule_data: AlertRuleCreate) -> AlertRuleResponse | None:
        """
        Update an alert rule.

        Parameters
        ----------
        rule_id:
            UUID of the rule to update.
        rule_data:
            AlertRuleCreate with updated fields.

        Returns
        -------
        AlertRuleResponse if updated, None if rule not found.
        """
        current = self.get_rule(rule_id)
        if not current:
            return None

        now = datetime.now(UTC)

        query = """
        MATCH (r:AlertRule {id: $rule_id})
        SET r.name = $name,
            r.description = $description,
            r.alert_type = $alert_type,
            r.trigger_condition = $trigger_condition,
            r.threshold = $threshold,
            r.severity = $severity,
            r.enabled = $enabled,
            r.updated_at = $updated_at
        RETURN r
        """

        params = {
            "rule_id": rule_id,
            "name": rule_data.name,
            "description": rule_data.description,
            "alert_type": rule_data.alert_type.value,
            "trigger_condition": rule_data.trigger_condition,
            "threshold": rule_data.threshold,
            "severity": rule_data.severity.value,
            "enabled": rule_data.enabled,
            "updated_at": now.isoformat(),
        }

        result = self.conn.run_query(query, params)
        if not result:
            return None

        logger.info(f"Updated alert rule {rule_id}: {rule_data.name}")

        return self._record_to_rule_response(result[0]["r"])

    def toggle_rule(self, rule_id: str) -> AlertRuleResponse | None:
        """
        Toggle an alert rule's enabled state.

        Parameters
        ----------
        rule_id:
            UUID of the rule to toggle.

        Returns
        -------
        AlertRuleResponse if toggled, None if rule not found.
        """
        current = self.get_rule(rule_id)
        if not current:
            return None

        new_state = not current.enabled
        now = datetime.now(UTC)

        query = """
        MATCH (r:AlertRule {id: $rule_id})
        SET r.enabled = $enabled,
            r.updated_at = $updated_at
        RETURN r
        """

        params = {
            "rule_id": rule_id,
            "enabled": new_state,
            "updated_at": now.isoformat(),
        }

        result = self.conn.run_query(query, params)
        if not result:
            return None

        logger.info(
            f"Alert rule {rule_id} toggled: {'enabled' if new_state else 'disabled'}"
        )

        return self._record_to_rule_response(result[0]["r"])

    def delete_rule(self, rule_id: str) -> bool:
        """
        Delete an alert rule.

        Parameters
        ----------
        rule_id:
            UUID of the rule to delete.

        Returns
        -------
        True if deleted, False if not found.
        """
        query = """
        MATCH (r:AlertRule {id: $rule_id})
        DETACH DELETE r
        """

        result = self.conn.run_query(query, {"rule_id": rule_id})
        deleted = result[0].get("deleted", 0) if result else 0

        if deleted > 0:
            logger.info(f"Deleted alert rule {rule_id}")

        return deleted > 0

    # ── Alert Generators (Automated) ────────────────────────────────────────

    def run_all_generators(self) -> AlertGenerationReport:
        """
        Run all alert generators and return a comprehensive report.

        This is the master method that runs all checks:
        - Risk threshold checks
        - Fraud pattern checks
        - Activity spike checks
        - Merge candidate checks

        Returns
        -------
        AlertGenerationReport with results from all generators.
        """
        run_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        generators: list[AlertGeneratorResult] = []
        total_created = 0
        total_deduped = 0
        errors: list[str] = []

        logger.info(f"Starting alert generation run {run_id}")

        # Run each generator with error isolation
        generator_methods = [
            ("check_risk_thresholds", self.check_risk_thresholds),
            ("check_fraud_patterns", self.check_fraud_patterns),
            ("check_activity_spikes", self.check_activity_spikes),
            ("check_merge_candidates", self.check_merge_candidates),
        ]

        for name, method in generator_methods:
            try:
                result = method()
                generators.append(result)
                total_created += result.alerts_created
                total_deduped += result.alerts_deduplicated
                if result.errors:
                    errors.extend(result.errors)
            except Exception as e:
                logger.error(f"Alert generator '{name}' failed: {e}")
                errors.append(f"{name}: {str(e)}")
                generators.append(AlertGeneratorResult(
                    generator_name=name,
                    alerts_created=0,
                    alerts_deduplicated=0,
                    execution_time_ms=0,
                    errors=[str(e)],
                ))

        completed_at = datetime.now(UTC)

        report = AlertGenerationReport(
            run_id=run_id,
            started_at=started_at,
            completed_at=completed_at,
            total_alerts_created=total_created,
            total_alerts_deduplicated=total_deduped,
            generators=generators,
            errors=errors,
        )

        logger.info(
            f"Alert generation complete: {total_created} created, "
            f"{total_deduped} deduplicated, {len(errors)} errors"
        )

        return report

    def check_risk_thresholds(self) -> AlertGeneratorResult:
        """
        Scan for companies with risk scores crossing thresholds.

        Checks:
        - Companies with risk_score >= 0.7 (High threshold)
        - Companies that crossed risk tiers since last check

        Returns
        -------
        AlertGeneratorResult with creation stats.
        """
        start_time = time.time()
        alerts_created = 0
        alerts_deduplicated = 0
        errors: list[str] = []

        try:
            # Find companies with high risk scores that don't have recent alerts
            query = """
            MATCH (c:Company)
            WHERE c.risk_score >= 0.7
              AND NOT (
                (c)-[:HAS_ALERT]->(a:Alert {type: 'risk_spike'})
                WHERE a.created_at >= datetime() - duration({hours: $dedup_hours})
              )
            RETURN c.id as entity_id,
                   c.cf as entity_cf,
                   c.nome_normalizzato as entity_name,
                   c.risk_score as risk_score,
                   c.anomaly_flags as anomaly_flags
            ORDER BY c.risk_score DESC
            LIMIT 100
            """

            result = self.conn.run_query(query, {"dedup_hours": ALERT_DEDUP_WINDOW_HOURS})

            for row in result:
                try:
                    risk_score = row.get("risk_score", 0)
                    severity = AlertSeverity.CRITICAL if risk_score >= 0.85 else AlertSeverity.HIGH

                    alert = self.create_alert(AlertCreate(
                        type=AlertType.RISK_SPIKE,
                        severity=severity,
                        title=f"Risk Score → High: {row.get('entity_name', 'Unknown')}",
                        description=(
                            f"Company '{row.get('entity_name', 'Unknown')}' (CF: {row.get('entity_cf')}) "
                            f"has risk score {risk_score:.2f}, exceeding the 0.7 threshold. "
                            f"Anomaly flags: {', '.join(row.get('anomaly_flags', []) or ['none'])}"
                        ),
                        entity_type="Company",
                        entity_id=row.get("entity_id"),
                        entity_cf=row.get("entity_cf"),
                        triggered_by="risk_engine",
                        metadata={
                            "risk_score": risk_score,
                            "threshold": 0.7,
                            "anomaly_flags": row.get("anomaly_flags", []),
                        },
                    ))

                    if alert.id:
                        alerts_created += 1
                        # Link alert to company
                        self._link_alert_to_entity(alert.id, row.get("entity_id"), "Company")
                    else:
                        alerts_deduplicated += 1

                except Exception as e:
                    errors.append(f"Failed to create risk alert for {row.get('entity_id')}: {str(e)}")

        except Exception as e:
            errors.append(f"Risk threshold check failed: {str(e)}")

        execution_time_ms = (time.time() - start_time) * 1000

        return AlertGeneratorResult(
            generator_name="check_risk_thresholds",
            alerts_created=alerts_created,
            alerts_deduplicated=alerts_deduplicated,
            execution_time_ms=execution_time_ms,
            errors=errors,
        )

    def check_fraud_patterns(self) -> AlertGeneratorResult:
        """
        Run fraud pattern detectors and create alerts for matches.

        Each fraud pattern detector can trigger an alert based on
        the severity of the pattern found.

        Returns
        -------
        AlertGeneratorResult with creation stats.
        """
        start_time = time.time()
        alerts_created = 0
        alerts_deduplicated = 0
        errors: list[str] = []

        try:
            # Find recent fraud patterns without alerts
            query = """
            MATCH (fp:FraudPattern)
            WHERE fp.detected_at >= datetime() - duration({hours: $dedup_hours})
              AND NOT EXISTS {
                MATCH (a:Alert {type: 'fraud_pattern'})
                WHERE a.metadata.fraud_pattern_id = fp.id
              }
            RETURN fp.id as pattern_id,
                   fp.pattern_name as pattern_name,
                   fp.severity as pattern_severity,
                   fp.description as description,
                   fp.affected_entity_ids as affected_ids,
                   fp.evidence_summary as evidence,
                   fp.detected_at as detected_at
            ORDER BY fp.detected_at DESC
            LIMIT 50
            """

            result = self.conn.run_query(query, {"dedup_hours": ALERT_DEDUP_WINDOW_HOURS})

            severity_map = {
                "critical": AlertSeverity.CRITICAL,
                "high": AlertSeverity.HIGH,
                "medium": AlertSeverity.MEDIUM,
                "low": AlertSeverity.LOW,
            }

            for row in result:
                try:
                    pattern_severity = row.get("pattern_severity", "medium")
                    severity = severity_map.get(pattern_severity, AlertSeverity.MEDIUM)

                    affected_ids = row.get("affected_ids", [])
                    primary_entity_id = affected_ids[0] if affected_ids else None

                    alert = self.create_alert(AlertCreate(
                        type=AlertType.FRAUD_PATTERN,
                        severity=severity,
                        title=f"Fraud Pattern: {row.get('pattern_name', 'Unknown')}",
                        description=row.get("description", "Fraud pattern detected"),
                        entity_type="Company",
                        entity_id=primary_entity_id,
                        triggered_by="fraud_detector",
                        metadata={
                            "fraud_pattern_id": row.get("pattern_id"),
                            "pattern_name": row.get("pattern_name"),
                            "affected_entity_ids": affected_ids,
                            "evidence": row.get("evidence"),
                            "detected_at": row.get("detected_at"),
                        },
                    ))

                    if alert.id:
                        alerts_created += 1
                        if primary_entity_id:
                            self._link_alert_to_entity(alert.id, primary_entity_id, "Company")
                    else:
                        alerts_deduplicated += 1

                except Exception as e:
                    errors.append(
                        f"Failed to create fraud alert for {row.get('pattern_id')}: {str(e)}"
                    )

        except Exception as e:
            errors.append(f"Fraud pattern check failed: {str(e)}")

        execution_time_ms = (time.time() - start_time) * 1000

        return AlertGeneratorResult(
            generator_name="check_fraud_patterns",
            alerts_created=alerts_created,
            alerts_deduplicated=alerts_deduplicated,
            execution_time_ms=execution_time_ms,
            errors=errors,
        )

    def check_activity_spikes(self) -> AlertGeneratorResult:
        """
        Detect unusual activity spikes in tender volume or value.

        Checks:
        - Companies with tender volume > 3x their average
        - Companies with single-bidder ratio > 0.8

        Returns
        -------
        AlertGeneratorResult with creation stats.
        """
        start_time = time.time()
        alerts_created = 0
        alerts_deduplicated = 0
        errors: list[str] = []

        try:
            # Find companies with unusually high tender volume
            query = """
            MATCH (c:Company)-[:WINS]->(t:Tender)
            WHERE t.data_aggiudicazione IS NOT NULL
              AND t.data_aggiudicazione >= date() - duration({days: 90})
            WITH c,
                 count(t) as recent_wins,
                 sum(t.importo) as recent_value
            WHERE recent_wins > 5
            // Compare to historical average (simplified)
            OPTIONAL MATCH (c)-[:WINS]->(ht:Tender)
            WHERE ht.data_aggiudicazione >= date() - duration({days: 365})
              AND ht.data_aggiudicazione < date() - duration({days: 90})
            WITH c,
                 recent_wins,
                 recent_value,
                 count(ht) as historical_wins,
                 sum(ht.importo) as historical_value
            WHERE historical_wins > 0
              AND toFloat(recent_wins) / historical_wins > 3.0
            RETURN c.id as entity_id,
                   c.cf as entity_cf,
                   c.nome_normalizzato as entity_name,
                   recent_wins,
                   historical_wins,
                   recent_value,
                   historical_value,
                   toFloat(recent_wins) / historical_wins as volume_ratio
            ORDER BY volume_ratio DESC
            LIMIT 50
            """

            result = self.conn.run_query(query, {})

            for row in result:
                try:
                    volume_ratio = row.get("volume_ratio", 0)

                    alert = self.create_alert(AlertCreate(
                        type=AlertType.ACTIVITY_SPIKE,
                        severity=AlertSeverity.MEDIUM,
                        title=f"Tender Volume Spike: {row.get('entity_name', 'Unknown')}",
                        description=(
                            f"Company '{row.get('entity_name', 'Unknown')}' won {row.get('recent_wins')} "
                            f"tenders in the last 90 days, compared to {row.get('historical_wins')} "
                            f"in the previous period ({volume_ratio:.1f}x increase)."
                        ),
                        entity_type="Company",
                        entity_id=row.get("entity_id"),
                        entity_cf=row.get("entity_cf"),
                        triggered_by="activity_monitor",
                        metadata={
                            "recent_wins": row.get("recent_wins"),
                            "historical_wins": row.get("historical_wins"),
                            "recent_value": row.get("recent_value"),
                            "historical_value": row.get("historical_value"),
                            "volume_ratio": round(volume_ratio, 2),
                        },
                    ))

                    if alert.id:
                        alerts_created += 1
                        self._link_alert_to_entity(alert.id, row.get("entity_id"), "Company")
                    else:
                        alerts_deduplicated += 1

                except Exception as e:
                    errors.append(
                        f"Failed to create activity spike alert for {row.get('entity_id')}: {str(e)}"
                    )

        except Exception as e:
            errors.append(f"Activity spike check failed: {str(e)}")

        execution_time_ms = (time.time() - start_time) * 1000

        return AlertGeneratorResult(
            generator_name="check_activity_spikes",
            alerts_created=alerts_created,
            alerts_deduplicated=alerts_deduplicated,
            execution_time_ms=execution_time_ms,
            errors=errors,
        )

    def check_merge_candidates(self) -> AlertGeneratorResult:
        """
        Alert on potential duplicate entities found for review.

        Checks for companies with high similarity scores that
        haven't been merged yet.

        Returns
        -------
        AlertGeneratorResult with creation stats.
        """
        start_time = time.time()
        alerts_created = 0
        alerts_deduplicated = 0
        errors: list[str] = []

        try:
            # Find companies with similar names that haven't been merged
            # This is a simplified check - in production, use the merge system
            query = """
            MATCH (c1:Company), (c2:Company)
            WHERE c1.id < c2.id
              AND c1.cf <> c2.cf
              AND c1.nome_normalizzato <> c2.nome_normalizzato
              AND (
                // Same province with very similar names
                (c1.provincia = c2.provincia
                 AND toLower(c1.nome_normalizzato) CONTAINS toLower(split(c2.nome_normalizzato, ' ')[0])
                 AND toLower(c2.nome_normalizzato) CONTAINS toLower(split(c1.nome_normalizzato, ' ')[0]))
                OR
                // Same ISTAT code with phonetic similarity (simplified)
                (c1.cod_istat = c2.cod_istat
                 AND size(c1.nome_normalizzato) > 3
                 AND size(c2.nome_normalizzato) > 3
                 AND toLower(left(c1.nome_normalizzato, 4)) = toLower(left(c2.nome_normalizzato, 4)))
              )
              AND NOT EXISTS {
                MATCH (a:Alert {type: 'merge_candidate'})
                WHERE (a.entity_id = c1.id OR a.entity_id = c2.id)
                  AND a.created_at >= datetime() - duration({hours: $dedup_hours})
              }
            RETURN c1.id as entity_id_1,
                   c1.cf as cf_1,
                   c1.nome_normalizzato as name_1,
                   c2.id as entity_id_2,
                   c2.cf as cf_2,
                   c2.nome_normalizzato as name_2,
                   c1.provincia as provincia
            LIMIT 50
            """

            result = self.conn.run_query(query, {"dedup_hours": ALERT_DEDUP_WINDOW_HOURS})

            for row in result:
                try:
                    alert = self.create_alert(AlertCreate(
                        type=AlertType.MERGE_CANDIDATE,
                        severity=AlertSeverity.LOW,
                        title=f"Duplicate Company Found: {row.get('name_1', 'Unknown')}",
                        description=(
                            f"Potential duplicate companies found: "
                            f"'{row.get('name_1')}' (CF: {row.get('cf_1')}) and "
                            f"'{row.get('name_2')}' (CF: {row.get('cf_2')}). "
                            f"Both located in {row.get('provincia', 'unknown')} province."
                        ),
                        entity_type="Company",
                        entity_id=row.get("entity_id_1"),
                        entity_cf=row.get("cf_1"),
                        triggered_by="merge_detector",
                        metadata={
                            "duplicate_entity_id": row.get("entity_id_2"),
                            "duplicate_cf": row.get("cf_2"),
                            "duplicate_name": row.get("name_2"),
                            "match_reason": "name_similarity",
                            "provincia": row.get("provincia"),
                        },
                    ))

                    if alert.id:
                        alerts_created += 1
                        self._link_alert_to_entity(alert.id, row.get("entity_id_1"), "Company")
                    else:
                        alerts_deduplicated += 1

                except Exception as e:
                    errors.append(
                        f"Failed to create merge alert for {row.get('entity_id_1')}: {str(e)}"
                    )

        except Exception as e:
            errors.append(f"Merge candidate check failed: {str(e)}")

        execution_time_ms = (time.time() - start_time) * 1000

        return AlertGeneratorResult(
            generator_name="check_merge_candidates",
            alerts_created=alerts_created,
            alerts_deduplicated=alerts_deduplicated,
            execution_time_ms=execution_time_ms,
            errors=errors,
        )

    # ── Internal Methods ────────────────────────────────────────────────────

    def _calculate_alert_hash(self, alert_data: AlertCreate) -> str:
        """
        Calculate a hash for alert deduplication.

        The hash is based on:
        - Alert type
        - Entity ID (if present)
        - Entity CF (if present)
        - Rule ID (if present)
        - Key metadata fields

        Parameters
        ----------
        alert_data:
            AlertCreate schema.

        Returns
        -------
        SHA-256 hash string.
        """
        hash_components = {
            "type": alert_data.type.value,
            "entity_id": alert_data.entity_id,
            "entity_cf": alert_data.entity_cf,
            "rule_id": alert_data.rule_id,
            # Include key metadata fields for dedup
            "metadata_keys": sorted(alert_data.metadata.keys()),
        }

        hash_string = json.dumps(hash_components, sort_keys=True, default=str)
        return hashlib.sha256(hash_string.encode()).hexdigest()

    def _is_duplicate_alert(self, alert_hash: str) -> bool:
        """
        Check if an identical alert was created within the dedup window.

        Parameters
        ----------
        alert_hash:
            SHA-256 hash of the alert.

        Returns
        -------
        True if duplicate found, False otherwise.
        """
        cutoff = (datetime.now(UTC) - timedelta(hours=ALERT_DEDUP_WINDOW_HOURS)).isoformat()

        query = """
        MATCH (a:Alert {alert_hash: $alert_hash})
        WHERE a.created_at >= $cutoff
        RETURN count(a) as count
        """

        params = {"alert_hash": alert_hash, "cutoff": cutoff}
        result = self.conn.run_query(query, params)

        if result and result[0].get("count", 0) > 0:
            return True

        return False

    def _validate_status_transition(
        self, current_status: AlertStatus, new_status: AlertStatus
    ) -> None:
        """
        Validate that a status transition is allowed.

        Allowed transitions:
        - pending → acknowledged, resolved, dismissed
        - acknowledged → resolved, dismissed

        Parameters
        ----------
        current_status:
            Current alert status.
        new_status:
            Target alert status.

        Raises
        ------
        ValueError if transition is not allowed.
        """
        allowed_transitions = {
            AlertStatus.PENDING: {
                AlertStatus.ACKNOWLEDGED,
                AlertStatus.RESOLVED,
                AlertStatus.DISMISSED,
            },
            AlertStatus.ACKNOWLEDGED: {
                AlertStatus.RESOLVED,
                AlertStatus.DISMISSED,
            },
            AlertStatus.RESOLVED: set(),  # Terminal state
            AlertStatus.DISMISSED: set(),  # Terminal state
        }

        if new_status not in allowed_transitions.get(current_status, set()):
            raise ValueError(
                f"Invalid status transition: {current_status.value} → {new_status.value}. "
                f"Allowed transitions: {allowed_transitions.get(current_status, set())}"
            )

    def _link_alert_to_entity(
        self, alert_id: str, entity_id: str, entity_type: str
    ) -> None:
        """
        Create a HAS_ALERT relationship between an entity and an alert.

        Parameters
        ----------
        alert_id:
            UUID of the alert.
        entity_id:
            UUID of the entity.
        entity_type:
            Type of entity (Company, Tender, etc.).
        """
        query = f"""
        MATCH (e:{entity_type} {{id: $entity_id}})
        MATCH (a:Alert {{id: $alert_id}})
        CREATE (e)-[:HAS_ALERT]->(a)
        """

        try:
            self.conn.run_query(query, {"entity_id": entity_id, "alert_id": alert_id})
        except Exception as e:
            logger.warning(
                f"Failed to link alert {alert_id} to {entity_type}:{entity_id}: {e}"
            )

    def _send_notification(self, alert_id: str, alert_data: AlertCreate) -> None:
        """
        Hook for future notification delivery (email, webhook, etc.).

        Also creates an audit comment on the entity if applicable.

        Parameters
        ----------
        alert_id:
            UUID of the created alert.
        alert_data:
            AlertCreate schema used to create the alert.
        """
        # Dispatch through NotificationDispatcher
        try:
            from paladino.app.notification_dispatcher import NotificationDispatcher
            from paladino.models import Alert, AlertStatus

            alert = Alert(
                id=alert_id,
                type=alert_data.type,
                severity=alert_data.severity,
                status=AlertStatus.PENDING,
                title=alert_data.title,
                description=alert_data.description,
                entity_type=alert_data.entity_type,
                entity_id=alert_data.entity_id,
                entity_cf=alert_data.entity_cf,
                rule_id=alert_data.rule_id,
                triggered_by=alert_data.triggered_by,
                metadata=alert_data.metadata or {},
                alert_hash=alert_data.alert_hash,
                acknowledged_at=None,
                resolved_at=None,
                dismissed_at=None,
                created_at=None,
            )

            dispatcher = NotificationDispatcher()
            results = dispatcher.dispatch(alert)
            dispatched_channels = [ch for ch, ok in results.items() if ok]
            if dispatched_channels:
                logger.info(
                    f"Alert {alert_id[:8]}... dispatched via: {', '.join(dispatched_channels)}"
                )
        except Exception as e:
            logger.warning(f"Notification dispatch failed for alert {alert_id}: {e}")

        # Integration with Comment System:
        # Auto-create a comment on the entity for audit trail
        if alert_data.entity_id and alert_data.entity_type:
            self._create_alert_comment(alert_id, alert_data)

    def _create_alert_comment(self, alert_id: str, alert_data: AlertCreate) -> None:
        """
        Create an audit comment on the entity when an alert is triggered.

        This links the alert to the entity's investigation thread,
        providing context for analysts reviewing the entity.

        Parameters
        ----------
        alert_id:
            UUID of the created alert.
        alert_data:
            AlertCreate schema used to create the alert.
        """
        try:
            from paladino.app.comment_service import CommentService
            from paladino.models import CommentCreate

            comment_service = CommentService(self.conn)

            comment_content = (
                f"🚨 Alert triggered: [{alert_data.severity.value.upper()}] {alert_data.title}\n"
                f"{alert_data.description}"
            )

            comment_data = CommentCreate(
                entity_id=alert_data.entity_id,
                entity_type=alert_data.entity_type,
                content=comment_content,
                tags=["alert", alert_data.type.value, alert_data.severity.value],
                author="system",
                source="system",
                confidence=1.0,
            )

            comment_service.create_comment(comment_data)

            logger.debug(
                f"Created audit comment for alert {alert_id} on "
                f"{alert_data.entity_type}:{alert_data.entity_id}"
            )

        except Exception as e:
            # Don't fail alert creation if comment creation fails
            logger.warning(
                f"Failed to create audit comment for alert {alert_id}: {e}"
            )

    def _record_to_alert(self, record: dict[str, Any]) -> Alert:
        """
        Convert a Neo4j record to an Alert.

        Parameters
        ----------
        record:
            Neo4j node properties dict.

        Returns
        -------
        Alert with parsed fields.
        """
        # Handle provenance if present
        provenance = None
        if "provenance" in record and record["provenance"]:
            prov_data = record["provenance"]
            if isinstance(prov_data, dict):
                try:
                    provenance = ProvenanceMetadata(**prov_data)
                except Exception:
                    pass

        # Parse datetime fields
        def parse_datetime(value: Any) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return datetime.now(UTC)
            return datetime.now(UTC)

        created_at = parse_datetime(record.get("created_at"))

        return Alert(
            id=record.get("id", ""),
            type=AlertType(record.get("type", "risk_spike")),
            severity=AlertSeverity(record.get("severity", "medium")),
            status=AlertStatus(record.get("status", "pending")),
            title=record.get("title", ""),
            description=record.get("description", ""),
            entity_type=record.get("entity_type"),
            entity_id=record.get("entity_id"),
            entity_cf=record.get("entity_cf"),
            rule_id=record.get("rule_id"),
            triggered_by=record.get("triggered_by", "system"),
            metadata=record.get("metadata") or {},
            alert_hash=record.get("alert_hash"),
            acknowledged_at=parse_datetime(record.get("acknowledged_at")),
            resolved_at=parse_datetime(record.get("resolved_at")),
            dismissed_at=parse_datetime(record.get("dismissed_at")),
            created_at=created_at,
            provenance=provenance,
        )

    def _record_to_rule_response(self, record: dict[str, Any]) -> AlertRuleResponse:
        """
        Convert a Neo4j record to an AlertRuleResponse.

        Parameters
        ----------
        record:
            Neo4j node properties dict.

        Returns
        -------
        AlertRuleResponse with parsed fields.
        """
        def parse_datetime(value: Any) -> datetime | None:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return datetime.now(UTC)
            return datetime.now(UTC)

        return AlertRuleResponse(
            id=record.get("id", ""),
            name=record.get("name", ""),
            description=record.get("description", ""),
            alert_type=AlertType(record.get("alert_type", "risk_spike")),
            trigger_condition=record.get("trigger_condition", ""),
            threshold=record.get("threshold"),
            severity=AlertSeverity(record.get("severity", "medium")),
            enabled=record.get("enabled", True),
            created_at=parse_datetime(record.get("created_at")) or datetime.now(UTC),
            updated_at=parse_datetime(record.get("updated_at")),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────

def get_alert_service() -> AlertService:
    """Get an AlertService instance using the default Neo4j connection."""
    from paladino.db import Neo4jConnection
    conn = Neo4jConnection()
    return AlertService(conn)


def initialize_default_rules(service: AlertService | None = None) -> list[AlertRuleResponse]:
    """
    Initialize default alert rules if they don't exist.

    This should be called on first run or during database setup.

    Parameters
    ----------
    service:
        AlertService instance (creates one if not provided).

    Returns
    -------
    List of created AlertRuleResponse objects.
    """
    if service is None:
        service = get_alert_service()

    # Check if rules already exist
    existing_rules = service.list_rules()
    existing_names = {r.name for r in existing_rules}

    created_rules: list[AlertRuleResponse] = []

    for rule_def in DEFAULT_ALERT_RULES:
        if rule_def["name"] not in existing_names:
            rule_data = AlertRuleCreate(
                name=rule_def["name"],
                description=rule_def["description"],
                alert_type=rule_def["alert_type"],
                trigger_condition=rule_def["trigger_condition"],
                threshold=rule_def["threshold"],
                severity=rule_def["severity"],
                enabled=rule_def["enabled"],
            )
            created_rule = service.create_rule(rule_data)
            created_rules.append(created_rule)
            logger.info(f"Created default alert rule: {rule_def['name']}")

    if not created_rules:
        logger.info("Default alert rules already exist, skipping initialization")

    return created_rules
