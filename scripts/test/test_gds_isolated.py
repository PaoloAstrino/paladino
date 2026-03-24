import sys
from pathlib import Path

from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver


def test_isolated():
    driver = get_driver()
    with driver.session() as session:
        session.run("CALL gds.graph.drop('test_isolated', false)")
        try:
            logger.info("Projecting isolated Company-Tender graph...")
            res = session.run("""
                CALL gds.graph.project(
                    'test_isolated',
                    ['Company', 'Tender'],
                    {
                        WINS: {type: 'WINS', orientation: 'UNDIRECTED'}
                    }
                )
            """)
            logger.success(f"Isolated Projection Success: {res.single()}")
        except Exception as e:
            logger.error(f"Isolated Projection Error: {e}")
    driver.close()


if __name__ == "__main__":
    test_isolated()
