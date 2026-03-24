
import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver

def test():
    driver = get_driver()
    with driver.session() as session:
        try:
            logger.info("Testing GDS projection...")
            # Using a very simple projection
            res = session.run("CALL gds.graph.project('test_simple', 'Company', '*')")
            logger.info(f"Result: {res.single()}")
        except Exception as e:
            logger.error(f"GDS Error: {e}")
    driver.close()

if __name__ == "__main__":
    test()
