#!/usr/bin/env python3
"""
Run ISTAT ETL pipeline - Download, transform, and load Italian geographic data.
"""

import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver
from paladino.etl.istat_download import IstatDownloader
from paladino.etl.istat_transform import IstatTransformer
from paladino.etl.istat_loader import IstatNeo4jLoader


def main():
    """Run the complete ISTAT ETL pipeline."""
    logger.info("=" * 60)
    logger.info("ISTAT ETL Pipeline")
    logger.info("=" * 60)
    
    # Step 1: Download
    logger.info("\n[1/4] Downloading ISTAT geographic data...")
    downloader = IstatDownloader()
    
    raw_data = downloader.fetch_all()
    
    if not raw_data:
        logger.error("No ISTAT data downloaded. Exiting.")
        sys.exit(1)
    
    logger.success("Download complete")
    for key, df in raw_data.items():
        logger.info(f"  {key}: {len(df)} records")
    
    # Step 2: Transform
    logger.info("\n[2/4] Transforming ISTAT data...")
    transformer = IstatTransformer()
    
    transformed_data = {}
    
    if "municipalities" in raw_data and not raw_data["municipalities"].is_empty():
        transformed_data["municipalities"] = transformer.transform_municipalities(
            raw_data["municipalities"]
        )
    
    if "provinces" in raw_data and not raw_data["provinces"].is_empty():
        transformed_data["provinces"] = transformer.transform_provinces(
            raw_data["provinces"]
        )
    
    if "regions" in raw_data and not raw_data["regions"].is_empty():
        transformed_data["regions"] = transformer.transform_regions(
            raw_data["regions"]
        )
    
    logger.success("Transformation complete")
    for key, df in transformed_data.items():
        logger.info(f"  {key}: {len(df)} records")
    
    # Step 3: Load to Neo4j
    logger.info("\n[3/4] Loading to Neo4j...")
    
    driver = get_driver()
    
    try:
        driver.verify_connectivity()
        logger.success("Connected to Neo4j")
        
        loader = IstatNeo4jLoader(driver)
        stats = loader.load_all(transformed_data)
        
        logger.success("\n" + "=" * 60)
        logger.success("ETL Pipeline Complete!")
        logger.success("=" * 60)
        logger.success(f"Loaded:")
        logger.success(f"  - {stats['municipalities']} municipalities")
        logger.success(f"  - {stats['provinces']} provinces")
        logger.success(f"  - {stats['regions']} regions")
        logger.success(f"  - {stats.get('municipality_province', 0)} municipality→province links")
        logger.success(f"  - {stats.get('municipality_region', 0)} municipality→region links")
        logger.success(f"  - {stats.get('province_region', 0)} province→region links")
        logger.success(f"  - {stats.get('company_locations', 0)} company→municipality links")
        
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        driver.close()
    
    # Step 4: Validation
    logger.info("\n[4/4] Validating geographic graph...")
    
    try:
        driver = get_driver()
        
        with driver.session() as session:
            # Count geographic nodes
            result = session.run("""
                MATCH (n)
                WHERE n:Municipality OR n:Province OR n:Region
                RETURN labels(n)[0] as label, count(n) as count
                ORDER BY count DESC
            """)
            
            logger.info("Geographic node counts:")
            for record in result:
                logger.info(f"  {record['label']}: {record['count']}")
            
            # Sample query: Companies by region
            result = session.run("""
                MATCH (c:Company)-[:LOCATED_IN]->(m:Municipality)-[:IN_REGION]->(r:Region)
                RETURN r.nome as regione, count(c) as companies
                ORDER BY companies DESC
                LIMIT 10
            """)
            
            logger.info("\nTop 10 regions by company count:")
            for record in result:
                logger.info(f"  {record['regione']}: {record['companies']} companies")
        
        driver.close()
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")


if __name__ == "__main__":
    main()
