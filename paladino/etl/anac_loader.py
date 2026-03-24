"""
ANAC data loader - Bulk load to Neo4j.
"""

import polars as pl
from loguru import logger
from neo4j import Driver
from tqdm import tqdm


class AnacNeo4jLoader:
    """Load ANAC data into Neo4j graph database."""

    def __init__(self, driver: Driver, batch_size: int = 1000):
        """
        Initialize loader.

        Args:
            driver: Neo4j driver instance
            batch_size: Number of records per batch
        """
        self.driver = driver
        self.batch_size = batch_size

    def load_tenders(self, df: pl.DataFrame) -> int:
        """
        Load tender nodes.

        Args:
            df: DataFrame with tender data

        Returns:
            Number of tenders loaded
        """
        if df.is_empty():
            logger.warning("No tenders to load")
            return 0

        logger.info(f"Loading {len(df)} tenders...")

        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading tenders"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows as row
                    
                    // 1. Find existing tender
                    OPTIONAL MATCH (t:Tender {cig: row.cig})
                    
                    // 2. If exists, create a Version node with CURRENT properties before update
                    FOREACH (ignoreMe IN CASE WHEN t IS NOT NULL THEN [1] ELSE [] END |
                        CREATE (v:Version)
                        SET v = properties(t),
                            v.id = row.id + "_" + toString(timestamp()),
                            v.entityId = t.id,
                            v.archived_at = datetime()
                        CREATE (t)-[:HAS_VERSION]->(v)
                    )
                    
                    // 3. Update or Create (MERGE) the main node
                    MERGE (t_new:Tender {cig: row.cig})
                    SET t_new.id = row.id,
                        t_new.ocid = row.ocid,
                        t_new.oggetto = row.oggetto,
                        t_new.descrizione_estesa = row.descrizione_estesa,
                        t_new.importo = row.importo,
                        t_new.procedura = row.procedura,
                        t_new.data_apertura = CASE
                            WHEN row.data_apertura IS NOT NULL
                            THEN date(substring(row.data_apertura, 0, 10))
                            ELSE null END,
                        t_new.data_aggiudicazione = CASE
                            WHEN row.data_aggiudicazione IS NOT NULL
                            THEN date(substring(row.data_aggiudicazione, 0, 10))
                            ELSE null END,
                        t_new.source = row.source,
                        t_new.dataset_version = row.dataset_version,
                        t_new.retrieval_date = datetime(row.retrieval_date),
                        t_new.confidence = row.confidence,
                        t_new.cup = row.cup,
                        t_new.last_updated = datetime()
                    RETURN count(t_new) as loaded
                """,
                    rows=rows,
                )

                loaded = result.single()["loaded"]
                total_loaded += loaded

        logger.success(f"Loaded {total_loaded} tenders")
        return total_loaded

    def load_companies(self, df: pl.DataFrame) -> int:
        """
        Load company nodes.

        Args:
            df: DataFrame with company data

        Returns:
            Number of companies loaded
        """
        if df.is_empty():
            logger.warning("No companies to load")
            return 0

        # Ensure PIVA is unique across companies (Neo4j constraint)
        # If multiple CFs have the same PIVA, we keep the first one.
        # Null values are allowed to be multiple (Neo4j unique constraints exclude null).
        if not df.is_empty() and "piva" in df.columns:
            has_piva = df.filter(pl.col("piva").is_not_null())
            no_piva = df.filter(pl.col("piva").is_null())

            unique_piva = has_piva.unique(subset=["piva"], keep="first")
            df = pl.concat([unique_piva, no_piva])

            logger.info(
                f"Filtered to {len(df)} companies (ensured unique PIVA for non-null values)"
            )

        logger.info(f"Loading {len(df)} companies...")

        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading companies"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                try:
                    result = session.run(
                        """
                        UNWIND $rows as row
                        MERGE (c:Company {cf: row.cf})
                        SET c.id = row.id,
                            c.piva = row.piva,
                            c.nome_normalizzato = row.nome_normalizzato,
                            c.nome_originale = row.nome_originale,
                            c.source = row.source,
                            c.dataset_version = row.dataset_version,
                            c.retrieval_date = datetime(row.retrieval_date),
                            c.confidence = row.confidence
                        RETURN count(c) as loaded
                    """,
                        rows=rows,
                    )

                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load company batch: {e}")
                    # Log first row for context
                    if rows:
                        logger.error(f"Sample row: {rows[0]}")
                    raise

        logger.success(f"Loaded {total_loaded} companies")
        return total_loaded

    def load_buyers(self, df: pl.DataFrame) -> int:
        """
        Load buyer nodes.

        Args:
            df: DataFrame with buyer data

        Returns:
            Number of buyers loaded
        """
        if df.is_empty():
            logger.warning("No buyers to load")
            return 0

        logger.info(f"Loading {len(df)} buyers...")

        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading buyers"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                result = session.run(
                    """
                    UNWIND $rows as row
                    MERGE (b:Buyer {cf: row.cf})
                    SET b.id = row.id,
                        b.nome = row.nome,
                        b.tipo = row.tipo,
                        b.source = row.source
                    RETURN count(b) as loaded
                """,
                    rows=rows,
                )

                loaded = result.single()["loaded"]
                total_loaded += loaded

        logger.success(f"Loaded {total_loaded} buyers")
        return total_loaded

    def load_wins(self, df: pl.DataFrame) -> int:
        """
        Load WINS relationships.

        Args:
            df: DataFrame with WINS relationship data

        Returns:
            Number of relationships loaded
        """
        if df.is_empty():
            logger.warning("No WINS relationships to load")
            return 0

        logger.info(f"Loading {len(df)} WINS relationships...")

        total_loaded = 0

        with self.driver.session() as session:
            for i in tqdm(range(0, len(df), self.batch_size), desc="Loading WINS"):
                batch = df[i : i + self.batch_size]
                rows = batch.to_dicts()

                try:
                    result = session.run(
                        """
                        UNWIND $rows as row
                        MATCH (c:Company {cf: row.company_cf})
                        MATCH (t:Tender {cig: row.tender_cig})
                        MERGE (c)-[w:WINS]->(t)
                        SET w.data = CASE
                                WHEN row.data IS NOT NULL
                                THEN date(substring(row.data, 0, 10))
                                ELSE null END,
                            w.importo = row.importo,
                            w.source = row.source,
                            w.confidence = row.confidence
                        RETURN count(w) as loaded
                    """,
                        rows=rows,
                    )

                    loaded = result.single()["loaded"]
                    total_loaded += loaded
                except Exception as e:
                    logger.error(f"Failed to load WINS batch: {e}")
                    if rows:
                        logger.error(f"Sample row: {rows[0]}")
                    raise

        logger.success(f"Loaded {total_loaded} WINS relationships")
        return total_loaded

    def load_all(self, data: dict) -> dict:
        """
        Load all ANAC data (tenders, companies, buyers, wins).

        Args:
            data: Dictionary with DataFrames

        Returns:
            Statistics dictionary
        """
        stats = {
            "tenders": self.load_tenders(data.get("tenders", pl.DataFrame())),
            "companies": self.load_companies(data.get("companies", pl.DataFrame())),
            "buyers": self.load_buyers(data.get("buyers", pl.DataFrame())),
            "wins": self.load_wins(data.get("wins", pl.DataFrame())),
        }

        logger.success(f"Load complete: {stats}")
        return stats
