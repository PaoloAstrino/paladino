"""
Confidence Propagation Engine.
Implements the 'Weakest Link' trust model across the knowledge graph.
"""

from loguru import logger
from paladino.db import Neo4jConnection

class ConfidencePropagator:
    """
    Updates derived_confidence scores by propagating trust across relationships.
    Uses a multi-pass approach to reach a stable trust state.
    """
    
    def __init__(self, conn: Neo4jConnection):
        self.conn = conn

    def initialize_derived_scores(self):
        """Reset derived_confidence to the baseline source confidence."""
        logger.info("Initializing derived confidence scores from source provenance...")
        query = """
        MATCH (n)
        WHERE n:Company OR n:Tender OR n:Project OR n:Person
        SET n.derived_confidence = coalesce(n.confidence, 1.0)
        """
        self.conn.run_query(query)
        logger.success("Derived confidence scores initialized.")

    def run_propagation_sweep(self, max_passes: int = 3):
        """
        Execute multiple passes of trust propagation.
        Formula: Node.derived = min(Node.derived, min(Neighbor.derived * Rel.confidence))
        """
        logger.info(f"Starting confidence propagation sweep ({max_passes} passes)...")
        
        # Propagation Query
        # We look for the minimum incoming trust from any neighbor
        # Note: We use a simplified 'Weakest Link' logic here
        query = """
        MATCH (n)<-[r]-(m)
        WHERE (n:Company OR n:Tender OR n:Project OR n:Person)
          AND (m:Company OR m:Tender OR m:Project OR m:Person)
          AND r.confidence IS NOT NULL
        WITH n, min(m.derived_confidence * r.confidence) as incoming_trust
        WHERE n.derived_confidence > incoming_trust
        SET n.derived_confidence = incoming_trust
        RETURN count(n) as updates
        """
        
        for i in range(1, max_passes + 1):
            logger.info(f"  Pass {i}/{max_passes}...")
            result = self.conn.run_query(query)
            updates = result[0]["updates"] if result else 0
            logger.debug(f"    Updated {updates} nodes.")
            
            if updates == 0:
                logger.info("  Convergence reached. Stopping early.")
                break
                
        logger.success("Confidence propagation sweep completed.")

    def get_confidence_stats(self) -> dict:
        """Return distribution of confidence scores."""
        query = """
        MATCH (n)
        WHERE n.derived_confidence IS NOT NULL
        RETURN 
            count(n) as total,
            avg(n.derived_confidence) as average,
            min(n.derived_confidence) as minimum,
            sum(case when n.derived_confidence >= 0.95 then 1 else 0 end) as high_trust,
            sum(case when n.derived_confidence < 0.75 then 1 else 0 end) as low_trust
        """
        res = self.conn.run_query(query)
        return dict(res[0]) if res else {}

if __name__ == "__main__":
    from paladino.db import Neo4jConnection
    conn = Neo4jConnection()
    propagator = ConfidencePropagator(conn)
    propagator.initialize_derived_scores()
    propagator.run_propagation_sweep()
    stats = propagator.get_confidence_stats()
    print(f"Confidence Stats: {stats}")
    conn.close()
