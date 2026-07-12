"""
Migration script to initialize temporal fields for existing nodes.
Sets valid_from to retrievalDate (if available) or current UTC time.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from paladino.db import Neo4jConnection

def migrate():
    """Run migration queries for all core node types."""
    conn = Neo4jConnection()
    
    try:
        conn.verify_connectivity()
        logger.info("Connected to Neo4j. Starting temporal migration...")
        
        queries = [
            # Company
            """
            MATCH (c:Company)
            WHERE c.valid_from IS NULL
            SET c.valid_from = coalesce(c.retrievalDate, datetime())
            RETURN count(c) as count
            """,
            # Tender
            """
            MATCH (t:Tender)
            WHERE t.valid_from IS NULL
            SET t.valid_from = coalesce(t.retrievalDate, datetime())
            RETURN count(t) as count
            """,
            # Project
            """
            MATCH (p:Project)
            WHERE p.valid_from IS NULL
            SET p.valid_from = coalesce(p.retrievalDate, datetime())
            RETURN count(p) as count
            """,
            # Person
            """
            MATCH (p:Person)
            WHERE p.valid_from IS NULL
            SET p.valid_from = coalesce(p.retrievalDate, datetime())
            RETURN count(p) as count
            """,
             # Relationship migration (WINS)
            """
            MATCH ()-[r:WINS]->()
            WHERE r.valid_from IS NULL
            SET r.valid_from = coalesce(r.data, datetime())
            RETURN count(r) as count
            """
        ]
        
        labels = ["Company", "Tender", "Project", "Person", "WINS Relationship"]
        
        for label, query in zip(labels, queries):
            logger.info(f"Migrating {label} nodes/edges...")
            result = conn.run_query(query)
            count = result[0]["count"] if result else 0
            logger.success(f"  ✓ {label}: {count} records updated")
            
        logger.success("Temporal migration completed successfully.")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
