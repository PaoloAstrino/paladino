"""
PNRR data loader - Bulk load to Neo4j.
"""

import polars as pl
from loguru import logger
from neo4j import Driver
from tqdm import tqdm


class PnnrNeo4jLoader:
    """Load PNRR data into Neo4j graph database."""

    def __init__(self, driver: Driver, batch_size: int = 2000):
        """
        Initialize loader.
        """
        self.driver = driver
        self.batch_size = batch_size

    def load_companies(self, df: pl.DataFrame) -> int:
        """
        Load or update company nodes from PNRR data.
        """
        if df.is_empty():
            return 0

        logger.info(f"Loading {len(df)} PNRR-related companies...")
        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading PNRR companies"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows as row
                    MERGE (c:Company {cf: row.cf})
                    ON CREATE SET 
                        c.id = row.id,
                        c.nome_normalizzato = row.nome_normalizzato,
                        c.nome_originale = row.nome_originale,
                        c.source = row.source,
                        c.dataset_version = row.dataset_version,
                        c.retrieval_date = datetime(row.retrieval_date),
                        c.confidence = row.confidence,
                        c.ateco = row.ateco,
                        c.forma_giuridica = row.forma_giuridica
                    ON MATCH SET
                        c.source = apoc.coll.toSet(c.source + row.source),
                        c.ateco = coalesce(c.ateco, row.ateco),
                        c.forma_giuridica = coalesce(c.forma_giuridica, row.forma_giuridica)
                    RETURN count(c) as loaded
                """,
                    rows=rows,
                )

                total_loaded += result.single()["loaded"]

        return total_loaded

    def load_involvement(self, df: pl.DataFrame) -> int:
        """
        Load INVOLVED_IN_PNRR relationships.
        """
        if df.is_empty():
            return 0

        logger.info(f"Loading {len(df)} PNRR involvement links...")
        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading involvement"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows as row
                    MATCH (c:Company {cf: row.company_cf})
                    MERGE (p:Project {cup: row.project_cup})
                    MERGE (c)-[rel:INVOLVED_IN_PNRR]->(p)
                    SET rel.role = row.role,
                        rel.submisura_code = row.submisura_code,
                        rel.submisura_desc = row.submisura_desc,
                        rel.source = row.source,
                        rel.date = datetime(row.date),
                        rel.confidence = row.confidence
                    RETURN count(rel) as loaded
                """,
                    rows=rows,
                )

                total_loaded += result.single()["loaded"]

        return total_loaded

    def load_sub_contracts(self, df: pl.DataFrame) -> int:
        """
        Load SUB_CONTRACTOR_ON relationships  (subcontractor → Tender/Project).
        """
        if df.is_empty():
            return 0

        logger.info(f"Loading {len(df)} PNRR sub-contractor links...")
        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading sub-contracts"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows as row
                    MATCH (c:Company {cf: row.sub_cf})
                    
                    // Link to Tender
                    OPTIONAL MATCH (t:Tender {cig: row.tender_cig})
                    FOREACH (ignoreMe IN CASE WHEN t IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (c)-[rel:SUB_CONTRACTOR_ON]->(t)
                        SET rel.role = row.role,
                            rel.source = row.source,
                            rel.date = datetime(row.date)
                    )
                    
                    // Link to Project
                    OPTIONAL MATCH (p:Project {cup: row.project_cup})
                    FOREACH (ignoreMe IN CASE WHEN p IS NOT NULL THEN [1] ELSE [] END |
                        MERGE (c)-[rel:SUB_CONTRACTOR_ON]->(p)
                        SET rel.role = row.role,
                            rel.source = row.source,
                            rel.date = datetime(row.date)
                    )
                    RETURN count(c) as processed
                """,
                    rows=rows,
                )

                total_loaded += result.single()["processed"]

        return total_loaded

    def load_subcontracts_to(self, df: pl.DataFrame) -> int:
        """
        Load SUBCONTRACTS_TO relationships  (winner Company → subcontractor Company).

        Uses the CIG to find the *winner* of a tender and links it directly to
        the subcontractor, forming the supply-chain Company→Company graph that
        powers carousel-fraud detection and supply-chain traversal queries.

        Rows that have no matching winner in the graph (CIG not yet loaded) are
        silently skipped — they will be picked up on the next ETL run once ANAC
        data is available.
        """
        if df.is_empty():
            return 0

        logger.info(f"Loading {len(df)} SUBCONTRACTS_TO edges (winner→sub)...")
        total_loaded = 0
        skipped = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading SUBCONTRACTS_TO"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows AS row

                    // Find the winner of the tender by CIG
                    OPTIONAL MATCH (winner:Company)-[:WINS]->(t:Tender {cig: row.tender_cig})

                    // Find (or create) the subcontractor node
                    MATCH (sub:Company {cf: row.sub_cf})

                    // Only create the edge when we know the winner
                    FOREACH (w IN CASE WHEN winner IS NOT NULL THEN [winner] ELSE [] END |
                        MERGE (w)-[r:SUBCONTRACTS_TO {cig: row.tender_cig}]->(sub)
                        SET r.cup              = row.project_cup,
                            r.ruolo            = row.role,
                            r.ateco            = row.ateco,
                            r.data_estrazione  = row.data_estrazione,
                            r.source           = row.source
                    )

                    RETURN
                        count(CASE WHEN winner IS NOT NULL THEN 1 END) AS linked,
                        count(CASE WHEN winner IS NULL     THEN 1 END) AS skipped
                """,
                    rows=rows,
                )

                rec = result.single()
                total_loaded += rec["linked"]
                skipped += rec["skipped"]

        if skipped > 0:
            logger.warning(
                f"{skipped} SUBCONTRACTS_TO rows skipped — CIG not found in graph.\n"
                "  → Run the ANAC ETL first, then re-run the PNRR Supply Chain ETL."
            )

        return total_loaded
