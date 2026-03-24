"""
Graph Upgrade Script - Upgrades the Neo4j graph without re-ingesting data.
Performs:
1. Schema initialization (new constraints/indexes)
2. CUP-CIG relationship enrichment
3. Entity Deduplication (ER Judge)
"""

from loguru import logger
import polars as pl
from paladino.db import Neo4jConnection
from paladino.schema_manager import SchemaManager
from paladino.etl.cup_cig_matcher import CupCigMatcher
from paladino.etl.deduplicator import EntityDeduplicator
from paladino.llm_manager import LLMManager

def upgrade_graph():
    logger.info("Starting Graph Upgrade Pipeline...")
    
    # Initialize DB connection
    conn = Neo4jConnection()
    if not conn.verify_connectivity():
        logger.error("Could not connect to Neo4j. Ensure the container is running.")
        return
    
    driver = conn.connect()
    
    # 1. Update Schema
    logger.info("Step 1: Initializing/Updating Schema...")
    schema_mgr = SchemaManager(driver)
    schema_mgr.initialize_schema()
    
    # 2. Enrich CUP-CIG Relationships
    logger.info("Step 2: Enriching CUP-CIG relationships...")
    matcher = CupCigMatcher(threshold=0.7)
    
    # Fetch all Tenders and Projects
    tenders = conn.run_query("MATCH (t:Tender) RETURN properties(t) as props")
    projects = conn.run_query("MATCH (p:Project) RETURN properties(p) as props")
    
    tender_list = [t['props'] for t in tenders]
    project_list = [p['props'] for p in projects]
    
    if not tender_list or not project_list:
        logger.warning("No Tenders or Projects found. Skipping matching.")
    else:
        logger.info(f"Analyzing {len(tender_list)} tenders against {len(project_list)} projects...")
        all_matches = []
        for tender in tender_list:
            matches = matcher.match(tender, project_list)
            all_matches.extend(matches)
        
        if all_matches:
            logger.info(f"Found {len(all_matches)} new potential links. Loading into Neo4j...")
            query = """
            UNWIND $batch as row
            MATCH (t:Tender {cig: row.tender_cig})
            MATCH (p:Project {cup: row.project_cup})
            MERGE (t)-[r:PART_OF_PROJECT]->(p)
            SET r.confidence = row.confidence,
                r.matching_method = row.matching_method,
                r.match_date = datetime(row.match_date)
            """
            conn.execute_batch(query, all_matches)
            logger.success(f"Enriched graph with {len(all_matches)} relationships.")
        else:
            logger.info("No new relationships identified.")

    # 3. Run ER Judge (Deduplication)
    logger.info("Step 3: Running ER Judge (Entity Deduplication)...")
    llm_mgr = LLMManager()
    deduplicator = EntityDeduplicator(conn, llm_mgr)
    
    # Deduplicate Companies
    deduplicator.run_deduplication_pipeline("Company")
    
    # Deduplicate People (if any exist)
    deduplicator.run_deduplication_pipeline("Person")
    
    logger.success("Graph Upgrade Pipeline completed successfully!")

if __name__ == "__main__":
    upgrade_graph()
