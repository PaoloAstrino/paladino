"""
Verification script for Tier 3 Confidence Propagation.
"""

import sys
from pathlib import Path
import uuid

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from paladino.db import Neo4jConnection
from paladino.analytics.confidence_engine import ConfidencePropagator

def test_propagation():
    conn = Neo4jConnection()
    try:
        conn.verify_connectivity()
        logger.info("Connected to Neo4j. Setting up test scenario...")
        
        # 1. Setup Test Data
        # Company A (Official) -> Confidence 1.0
        # Company B (Fuzzy)    -> Confidence 0.6
        # Link (SAME_AS)       -> Confidence 0.9
        
        test_id_a = f"test_a_{uuid.uuid4().hex[:8]}"
        test_id_b = f"test_b_{uuid.uuid4().hex[:8]}"
        
        setup_query = """
        CREATE (a:Company {id: $id_a, nome_normalizzato: 'TEST OFFICIAL', confidence: 1.0, derived_confidence: 1.0})
        CREATE (b:Company {id: $id_b, nome_normalizzato: 'TEST FUZZY', confidence: 0.6, derived_confidence: 0.6})
        CREATE (a)-[r:RELATED_TO {confidence: 0.8}]->(b)
        CREATE (b)-[r2:RELATED_TO {confidence: 0.8}]->(a)
        """
        conn.run_query(setup_query, {"id_a": test_id_a, "id_b": test_id_b})
        logger.info("Test nodes created.")

        # 2. Run Propagator
        propagator = ConfidencePropagator(conn)
        # Note: initialize_derived_scores resets everything to n.confidence
        propagator.initialize_derived_scores()
        
        logger.info("Running propagation sweep...")
        propagator.run_propagation_sweep(max_passes=5)

        # 3. Verify Results
        verify_query = """
        MATCH (c:Company)
        WHERE c.id IN [$id_a, $id_b]
        RETURN c.id as id, c.nome_normalizzato as name, c.confidence as original, c.derived_confidence as derived
        """
        results = conn.run_query(verify_query, {"id_a": test_id_a, "id_b": test_id_b})
        
        logger.info("--- Results ---")
        for res in results:
            logger.info(f"Entity: {res['name']}")
            logger.info(f"  Original Confidence: {res['original']}")
            logger.info(f"  Derived Confidence:  {res['derived']:.4f}")
            
            # Logic check: 
            # A's derived should be min(1.0, B.derived * 0.8) = min(1.0, 0.6 * 0.8) = 0.48
            # B's derived should be min(0.6, A.derived * 0.8) = min(0.6, 1.0 * 0.8) = 0.6 (stayed same because original 0.6 < 0.8)
            # Actually, with multi-pass:
            # Pass 1: B sees A (1.0 * 0.8 = 0.8). B stays 0.6.
            # Pass 1: A sees B (0.6 * 0.8 = 0.48). A becomes 0.48.
            # Pass 2: B sees A (0.48 * 0.8 = 0.384). B becomes 0.384.
            # Pass 3: A sees B (0.384 * 0.8 = 0.3072). A becomes 0.3072.
            # This is the "Confidence Decay" effect of cycles.
            
        # 4. Cleanup
        cleanup_query = "MATCH (c:Company) WHERE c.id IN [$id_a, $id_b] DETACH DELETE c"
        conn.run_query(cleanup_query, {"id_a": test_id_a, "id_b": test_id_b})
        logger.info("Test data cleaned up.")

    except Exception as e:
        logger.error(f"Test failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    test_propagation()
