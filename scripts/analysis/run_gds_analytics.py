import sys
from pathlib import Path

from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver


def run_analytics():
    logger.info("Starting GDS Analytics Pipeline...")
    driver = get_driver()

    with driver.session() as session:
        # 1. Drop existing projection if any
        session.run("CALL gds.graph.drop('paladino_graph', false)")

        # 2. Project the graph using Cypher (Selective Projection)
        logger.info("Projecting active subgraph (Tenders, Companies, and LINKED Projects)...")
        session.run("""
            CALL gds.graph.project.cypher(
              'paladino_graph',
              'MATCH (n) WHERE n:Tender OR n:Company OR (n:Project AND EXISTS((n)<-[:PART_OF_PROJECT]-())) 
               RETURN id(n) AS id, labels(n) AS labels',
              'MATCH (s)-[r:WINS|PART_OF_PROJECT]->(t) 
               RETURN id(s) AS source, id(t) AS target, type(r) AS type'
            )
        """)

        # 3. Run PageRank (Centrality)
        logger.info("Running PageRank to identify influential actors...")
        session.run("""
            CALL gds.pageRank.write('paladino_graph', {
              writeProperty: 'centrality_score'
            })
        """)

        # 4. Run Louvain (Community Detection)
        logger.info("Running Louvain to detect bidding communities...")
        session.run("""
            CALL gds.louvain.write('paladino_graph', {
              writeProperty: 'community_id'
            })
        """)

        logger.success(
            "GDS Analytics Complete! Nodes enriched with 'centrality_score' and 'community_id'"
        )

    driver.close()


if __name__ == "__main__":
    run_analytics()
