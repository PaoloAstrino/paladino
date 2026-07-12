"""
Temporal Oracle - Proactive Network Drift Detection.
Scans for significant changes between snapshots and persists them as alerts.
"""

import uuid
from datetime import datetime
from loguru import logger
from paladino.db import Neo4jConnection

class TemporalOracle:
    """
    Analyzes systemic changes between the current and previous snapshots.
    Identifies risk spikes and community migrations.
    """
    
    def __init__(self, conn: Neo4jConnection):
        self.conn = conn

    def find_snapshot_boundaries(self) -> tuple[datetime | None, datetime | None]:
        """Identify the current and previous snapshot dates based on valid_from."""
        query = """
        MATCH (n:Company)
        RETURN DISTINCT n.valid_from as snapshot_date
        ORDER BY n.valid_from DESC
        LIMIT 2
        """
        results = self.conn.run_query(query)
        if not results:
            return None, None
            
        current = results[0]["snapshot_date"]
        previous = results[1]["snapshot_date"] if len(results) > 1 else None
        
        return previous, current

    def detect_risk_spikes(self, date_a: datetime, date_b: datetime, threshold: float = 0.3):
        """Find companies whose risk_score increased by > threshold."""
        query = """
        MATCH (ca:Company {valid_from: $date_a})
        MATCH (cb:Company {id: ca.id, valid_from: $date_b})
        WITH ca, cb, (cb.risk_score - ca.risk_score) as delta
        WHERE delta >= $threshold
        RETURN ca.id as entity_id, ca.risk_score as old_val, cb.risk_score as new_val, delta
        """
        return self.conn.run_query(query, {"date_a": date_a, "date_b": date_b, "threshold": threshold})

    def detect_community_migration(self, date_a: datetime, date_b: datetime):
        """Find companies that moved to a different community."""
        query = """
        MATCH (ca:Company {valid_from: $date_a})
        MATCH (cb:Company {id: ca.id, valid_from: $date_b})
        WHERE ca.community_id <> cb.community_id
        RETURN ca.id as entity_id, ca.community_id as old_val, cb.community_id as new_val
        """
        return self.conn.run_query(query, {"date_a": date_a, "date_b": date_b})

    def persist_alerts(self, alerts: list[dict], alert_type: str, date_a: datetime, date_b: datetime):
        """Create TemporalAlert nodes and link them to entities."""
        logger.info(f"Persisting {len(alerts)} temporal alerts of type '{alert_type}'...")
        
        # Batch create alerts
        query = """
        UNWIND $batch as alert
        MATCH (e {id: alert.entity_id})
        WHERE e.valid_from = $date_b
        CREATE (a:TemporalAlert {
            id: alert.alert_id,
            alert_type: $alert_type,
            entity_id: alert.entity_id,
            old_value: alert.old_val,
            new_value: alert.new_val,
            delta: alert.delta,
            date_a: $date_a,
            date_b: $date_b,
            severity: alert.severity,
            valid_from: datetime()
        })
        CREATE (e)-[:HAS_TEMPORAL_ALERT]->(a)
        """
        
        batch = []
        for a in alerts:
            severity = "critical" if a.get("delta", 0) > 0.5 else "high"
            batch.append({
                "alert_id": str(uuid.uuid4()),
                "entity_id": a["entity_id"],
                "old_val": a["old_val"],
                "new_val": a["new_val"],
                "delta": a.get("delta"),
                "severity": severity
            })
            
        if batch:
            self.conn.run_query(query, {
                "batch": batch, 
                "alert_type": alert_type,
                "date_a": date_a,
                "date_b": date_b
            })

    def run_full_scan(self):
        """Perform all detections and persist results."""
        date_a, date_b = self.find_snapshot_boundaries()
        if not date_a or not date_b:
            logger.warning("Not enough snapshots found for temporal analysis.")
            return
            
        logger.info(f"Running Temporal Oracle scan: {date_a.isoformat()} -> {date_b.isoformat()}")
        
        # 1. Risk Spikes
        spikes = self.detect_risk_spikes(date_a, date_b)
        self.persist_alerts(spikes, "risk_spike", date_a, date_b)
        
        # 2. Community Migration
        migrations = self.detect_community_migration(date_a, date_b)
        self.persist_alerts(migrations, "community_migration", date_a, date_b)
        
        logger.success(f"Temporal Oracle scan complete. {len(spikes) + len(migrations)} alerts created.")

if __name__ == "__main__":
    from paladino.db import Neo4jConnection
    conn = Neo4jConnection()
    oracle = TemporalOracle(conn)
    oracle.run_full_scan()
    conn.close()
