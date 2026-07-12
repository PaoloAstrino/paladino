"""
Run PNRR ETL pipeline.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

import polars as pl
from loguru import logger
from neo4j import GraphDatabase

from paladino.config import settings
from paladino.etl.pnnr_loader import PnnrNeo4jLoader
from paladino.etl.pnnr_transform import PnnrTransformer


def main():
    logger.info("Starting PNRR ETL pipeline")

    # 1. Setup Neo4j connection
    driver = GraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )

    transformer = PnnrTransformer()
    loader = PnnrNeo4jLoader(driver)

    # 2. Process PNRR Soggetti (Large file)
    soggetti_path = settings.data_dir / "pnnr" / "PNRR_Soggetti.csv"
    if soggetti_path.exists():
        logger.info(f"Processing {soggetti_path} in streaming batches...")
        
        # Using read_csv_batched for memory efficiency
        reader = pl.read_csv_batched(soggetti_path, separator=";", ignore_errors=True, batch_size=100_000)
        
        batches = reader.next_batches(1)
        while batches:
            df_batch = batches[0]
            logger.info(f"Transforming batch of {len(df_batch)} rows...")
            data_soggetti = transformer.transform_soggetti(df_batch)

            loader.load_companies(data_soggetti["companies"])
            loader.load_involvement(data_soggetti["involvement"])
            
            batches = reader.next_batches(1)
    else:
        logger.warning(f"File not found: {soggetti_path}")

    # 3. Process PNRR Subappaltatori
    sub_path = settings.data_dir / "pnnr" / "PNRR_Subappaltatori_Gare.csv"
    if sub_path.exists():
        logger.info(f"Processing {sub_path} in streaming batches...")
        reader = pl.read_csv_batched(sub_path, separator=";", ignore_errors=True, batch_size=50_000)
        
        batches = reader.next_batches(1)
        while batches:
            df_batch = batches[0]
            data_sub = transformer.transform_subappaltatori(df_batch)

            loader.load_companies(data_sub["companies"])
            loader.load_sub_contracts(data_sub["sub_contracts"])
            loader.load_subcontracts_to(data_sub["sub_contracts"])
            
            batches = reader.next_batches(1)
    else:
        logger.warning(f"File not found: {sub_path}")

    driver.close()
    logger.success("PNRR ETL pipeline finished")


if __name__ == "__main__":
    main()
