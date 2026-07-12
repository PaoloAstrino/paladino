// ============================================================================
// PALADINO - Alert Dashboard Queries
// ============================================================================
// Cypher queries for the Alert/Notification dashboard.
// These queries power the alert statistics, trending, and entity analysis views.
// ============================================================================

// ============================================================================
// DASHBOARD OVERVIEW QUERIES
// ============================================================================

// Pending alerts by severity (for priority queue)
MATCH (a:Alert {status: 'pending'})
RETURN a.severity AS severity, count(*) AS count
ORDER BY
  CASE a.severity
    WHEN 'critical' THEN 1
    WHEN 'high' THEN 2
    WHEN 'medium' THEN 3
    WHEN 'low' THEN 4
    WHEN 'info' THEN 5
  END

// Alerts this week by type (for trend analysis)
MATCH (a:Alert)
WHERE a.created_at >= datetime() - duration({days: 7})
RETURN a.type AS type, count(*) AS count
ORDER BY count DESC

// Alert status distribution (for pie chart)
MATCH (a:Alert)
RETURN a.status AS status, count(*) AS count
ORDER BY count DESC

// ============================================================================
// ENTITY-CENTRIC QUERIES
// ============================================================================

// Top alerted entities (for hotspot analysis)
MATCH (a:Alert)
WHERE a.entity_id IS NOT NULL
RETURN a.entity_id AS entity_id,
       a.entity_type AS entity_type,
       a.entity_cf AS entity_cf,
       count(*) AS alert_count,
       collect(DISTINCT a.type) AS alert_types,
       max(a.severity) AS max_severity
ORDER BY alert_count DESC
LIMIT 20

// Entity alert timeline (for specific entity view)
MATCH (a:Alert {entity_id: $entity_id})
RETURN a.id AS alert_id,
       a.type AS type,
       a.severity AS severity,
       a.status AS status,
       a.title AS title,
       a.created_at AS created_at
ORDER BY a.created_at DESC
LIMIT 50

// Entities with critical alerts requiring immediate attention
MATCH (a:Alert {status: 'pending', severity: 'critical'})
WHERE a.entity_id IS NOT NULL
RETURN a.entity_id AS entity_id,
       a.entity_type AS entity_type,
       a.entity_cf AS entity_cf,
       a.title AS alert_title,
       a.created_at AS created_at
ORDER BY a.created_at DESC

// ============================================================================
// TIME-BASED QUERIES
// ============================================================================

// Alerts in last 24 hours (for real-time dashboard)
MATCH (a:Alert)
WHERE a.created_at >= datetime() - duration({hours: 24})
RETURN a.type AS type,
       a.severity AS severity,
       a.status AS status,
       count(*) AS count
ORDER BY
  CASE a.severity
    WHEN 'critical' THEN 1
    WHEN 'high' THEN 2
    WHEN 'medium' THEN 3
    WHEN 'low' THEN 4
    WHEN 'info' THEN 5
  END,
  count DESC

// Daily alert volume (for trend chart - last 30 days)
MATCH (a:Alert)
WHERE a.created_at >= datetime() - duration({days: 30})
RETURN date(a.created_at) AS alert_date,
       count(*) AS total_alerts,
       sum(CASE WHEN a.severity = 'critical' THEN 1 ELSE 0 END) AS critical_count,
       sum(CASE WHEN a.severity = 'high' THEN 1 ELSE 0 END) AS high_count,
       sum(CASE WHEN a.severity = 'medium' THEN 1 ELSE 0 END) AS medium_count
ORDER BY alert_date ASC

// Average time to acknowledge alerts
MATCH (a:Alert)
WHERE a.acknowledged_at IS NOT NULL
  AND a.created_at IS NOT NULL
RETURN a.type AS type,
       avg(duration.between(a.created_at, a.acknowledged_at).hours) AS avg_hours_to_ack,
       count(*) AS acknowledged_count
ORDER BY avg_hours_to_ack DESC

// Average time to resolve alerts
MATCH (a:Alert)
WHERE a.resolved_at IS NOT NULL
  AND a.created_at IS NOT NULL
RETURN a.type AS type,
       avg(duration.between(a.created_at, a.resolved_at).hours) AS avg_hours_to_resolve,
       count(*) AS resolved_count
ORDER BY avg_hours_to_resolve DESC

// ============================================================================
// FRAUD PATTERN QUERIES
// ============================================================================

// Fraud pattern alerts by pattern name
MATCH (a:Alert {type: 'fraud_pattern'})
RETURN a.metadata.pattern_name AS pattern_name,
       count(*) AS occurrence_count,
       count(CASE WHEN a.status = 'pending' THEN 1 END) AS pending_count,
       count(CASE WHEN a.status = 'resolved' THEN 1 END) AS resolved_count
ORDER BY occurrence_count DESC

// Fraud patterns affecting multiple entities (collusion indicators)
MATCH (a:Alert {type: 'fraud_pattern'})
WHERE size(a.metadata.affected_entity_ids) > 1
RETURN a.metadata.pattern_name AS pattern_name,
       a.metadata.affected_entity_ids AS affected_entities,
       a.severity AS severity,
       a.created_at AS created_at
ORDER BY size(a.metadata.affected_entity_ids) DESC
LIMIT 20

// ============================================================================
// RISK SPIKE QUERIES
// ============================================================================

// Risk spike alerts with score details
MATCH (a:Alert {type: 'risk_spike'})
RETURN a.entity_cf AS entity_cf,
       a.metadata.risk_score AS risk_score,
       a.metadata.threshold AS threshold,
       a.severity AS severity,
       a.status AS status,
       a.created_at AS created_at
ORDER BY a.metadata.risk_score DESC
LIMIT 50

// Companies with multiple risk spike alerts (chronic risk)
MATCH (a:Alert {type: 'risk_spike'})
WHERE a.entity_cf IS NOT NULL
RETURN a.entity_cf AS entity_cf,
       a.entity_id AS entity_id,
       count(*) AS spike_count,
       max(a.metadata.risk_score) AS max_risk_score,
       avg(a.metadata.risk_score) AS avg_risk_score
ORDER BY spike_count DESC
LIMIT 20

// ============================================================================
// ACTIVITY SPIKE QUERIES
// ============================================================================

// Activity spike alerts with volume ratios
MATCH (a:Alert {type: 'activity_spike'})
RETURN a.entity_cf AS entity_cf,
       a.metadata.volume_ratio AS volume_ratio,
       a.metadata.recent_wins AS recent_wins,
       a.metadata.historical_wins AS historical_wins,
       a.created_at AS created_at
ORDER BY a.metadata.volume_ratio DESC
LIMIT 20

// ============================================================================
// MERGE CANDIDATE QUERIES
// ============================================================================

// Merge candidate alerts with duplicate details
MATCH (a:Alert {type: 'merge_candidate'})
RETURN a.entity_cf AS primary_cf,
       a.metadata.duplicate_cf AS duplicate_cf,
       a.metadata.duplicate_name AS duplicate_name,
       a.metadata.match_reason AS match_reason,
       a.status AS status,
       a.created_at AS created_at
ORDER BY a.created_at DESC
LIMIT 50

// ============================================================================
// RULE EFFECTIVENESS QUERIES
// ============================================================================

// Alert rule effectiveness (alerts generated per rule)
MATCH (r:AlertRule)<-[:TRIGGERED_BY_RULE]-(a:Alert)
RETURN r.name AS rule_name,
       r.enabled AS enabled,
       count(a) AS alerts_generated,
       count(CASE WHEN a.status = 'pending' THEN a END) AS pending_alerts,
       count(CASE WHEN a.status = 'resolved' THEN a END) AS resolved_alerts
ORDER BY alerts_generated DESC

// Rules that never triggered (candidates for removal)
MATCH (r:AlertRule)
WHERE NOT EXISTS {
  MATCH (a:Alert) WHERE a.rule_id = r.id
}
RETURN r.name AS rule_name,
       r.alert_type AS alert_type,
       r.enabled AS enabled,
       r.created_at AS created_at
ORDER BY r.created_at ASC

// ============================================================================
// AUDIT & COMPLIANCE QUERIES
// ============================================================================

// All alerts for a specific entity (audit trail)
MATCH (a:Alert {entity_id: $entity_id})
RETURN a.id AS alert_id,
       a.type AS type,
       a.severity AS severity,
       a.status AS status,
       a.title AS title,
       a.description AS description,
       a.triggered_by AS triggered_by,
       a.created_at AS created_at,
       a.acknowledged_at AS acknowledged_at,
       a.resolved_at AS resolved_at,
       a.dismissed_at AS dismissed_at
ORDER BY a.created_at DESC

// Alert status change audit trail
MATCH (a:Alert)
WHERE a.acknowledged_at IS NOT NULL
   OR a.resolved_at IS NOT NULL
   OR a.dismissed_at IS NOT NULL
RETURN a.id AS alert_id,
       a.title AS title,
       a.status AS current_status,
       a.created_at AS created_at,
       a.acknowledged_at AS acknowledged_at,
       a.resolved_at AS resolved_at,
       a.dismissed_at AS dismissed_at
ORDER BY a.created_at DESC
LIMIT 100

// Dismissed alerts (for review - potential false positives)
MATCH (a:Alert {status: 'dismissed'})
RETURN a.type AS type,
       a.severity AS severity,
       a.title AS title,
       a.dismissed_at AS dismissed_at,
       a.metadata AS metadata
ORDER BY a.dismissed_at DESC
LIMIT 50

// ============================================================================
// PERFORMANCE NOTES
// ============================================================================
// - All queries leverage indexes on status, type, severity, created_at
// - Composite indexes (status + created_at) optimize dashboard queries
// - Entity-specific queries use idx_alert_entity_created composite index
// - For large datasets, consider adding date partitioning
// - Use EXPLAIN/PROFILE to verify index usage in production
