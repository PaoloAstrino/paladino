
import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver

def run_matcher():
    logger.info("Starting CUP-CIG Matching & Linkage...")
    driver = get_driver()
    
    with driver.session() as session:
        # 1. Exact CUP Match
        logger.info("Linking exact CUP matches...")
        result = session.run("""
            MATCH (t:Tender)
            WHERE t.cup IS NOT NULL
            MATCH (p:Project {cup: t.cup})
            MERGE (t)-[r:PART_OF_PROJECT]->(p)
            ON CREATE SET r.matching_method = 'exact_cup_match',
                          r.confidence = 1.0,
                          r.created_at = datetime()
            RETURN count(r) as links
        """)
        exact_links = result.single()["links"]
        logger.success(f"Matched {exact_links} exact CUP links")
        
        # 2. Semantic/Heuristic Matching (Optional - placeholder for now)
        # We could add more complex logic here later.
        
    driver.close()
    logger.success("Linkage Phase 1 Complete!")

if __name__ == "__main__":
    run_matcher()
