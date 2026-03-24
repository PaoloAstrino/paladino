"""
Entity resolution loader - Load SAME_AS relationships to Neo4j.
"""

import polars as pl
from loguru import logger
from neo4j import Driver
from tqdm import tqdm


class EntityResolutionLoader:
    """Load entity resolution results to Neo4j."""

    def __init__(self, driver: Driver, batch_size: int = 1000):
        """
        Initialize loader.

        Args:
            driver: Neo4j driver instance
            batch_size: Number of records per batch
        """
        self.driver = driver
        self.batch_size = batch_size

    def load_same_as_relationships(self, same_as_df: pl.DataFrame) -> int:
        """
        Load SAME_AS relationships for duplicate companies.

        Args:
            same_as_df: DataFrame with company_id and canonical_id

        Returns:
            Number of relationships loaded
        """
        if same_as_df.is_empty():
            logger.warning("No SAME_AS relationships to load")
            return 0

        logger.info(f"Loading {len(same_as_df)} SAME_AS relationships...")

        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(same_as_df), self.batch_size), desc="Loading SAME_AS"):
                batch = same_as_df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows as row
                    MATCH (c1:Company {id: row.company_id})
                    MATCH (c2:Company {id: row.canonical_id})
                    MERGE (c1)-[r:SAME_AS]->(c2)
                    RETURN count(r) as loaded
                """,
                    rows=rows,
                )

                loaded = result.single()["loaded"]
                total_loaded += loaded

        logger.success(f"Loaded {total_loaded} SAME_AS relationships")
        return total_loaded

    def update_company_statistics(self, stats_df: pl.DataFrame) -> int:
        """
        Update company nodes with aggregated statistics.

        Args:
            stats_df: DataFrame with company statistics

        Returns:
            Number of companies updated
        """
        if stats_df.is_empty():
            logger.warning("No statistics to update")
            return 0

        logger.info(f"Updating {len(stats_df)} companies with statistics...")

        total_updated = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(stats_df), self.batch_size), desc="Updating stats"):
                batch = stats_df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows as row
                    MATCH (c:Company {cf: row.cf})
                    SET c.total_tenders = row.total_tenders,
                        c.total_importo = row.total_importo,
                        c.avg_importo = row.avg_importo,
                        c.risk_score = row.risk_score,
                        c.anomaly_flags = row.anomaly_flags
                    RETURN count(c) as updated
                """,
                    rows=rows,
                )

                updated = result.single()["updated"]
                total_updated += updated

        logger.success(f"Updated {total_updated} companies")
        return total_updated
