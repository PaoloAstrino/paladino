#!/usr/bin/env python3
"""
Run ANAC ETL pipeline - Download, transform, validate, and load ANAC data.
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver
from paladino.etl.anac_download import AnacOcdsDownloader
from paladino.etl.anac_transform import AnacOcdsTransformer
from paladino.etl.anac_quality import AnacQualityValidator
from paladino.etl.anac_loader import AnacNeo4jLoader


def main():
    """Run the complete ANAC ETL pipeline."""
    logger.info("=" * 60)
    logger.info("ANAC ETL Pipeline")
    logger.info("=" * 60)
    
    # Configuration
    months_to_fetch = 3  # Fetch last 3 months for testing
    data_dir = Path("data/anac")
    
    # Step 1: Download / Local file detection
    logger.info("\n[1/4] Detecting ANAC OCDS data...")
    downloader = AnacOcdsDownloader(cache_dir=data_dir / "raw")
    
    # Try to fetch recent months but don't crash if it fails (restricted portal)
    try:
        downloader.fetch_recent(months=months_to_fetch)
    except Exception as e:
        logger.warning(f"Automated download failed (likely portal restrictions): {e}")
    
    # Get all JSON files in the raw directory (downloaded or manually placed)
    files = downloader.get_cached_files()
    
    if not files:
        logger.error(f"No ANAC files found in {downloader.cache_dir}. Exiting.")
        sys.exit(1)
    
    logger.success(f"Found {len(files)} files to process")
    
    # Step 2: Transform
    logger.info("\n[2/4] Transforming OCDS to graph schema...")
    transformer = AnacOcdsTransformer()
    
    all_data = {
        "tenders": [],
        "companies": [],
        "buyers": [],
        "wins": [],
    }
    
    for file in files:
        try:
            data = transformer.transform_file(file)
            
            for key in all_data.keys():
                if not data[key].is_empty():
                    all_data[key].append(data[key])
        
        except Exception as e:
            logger.error(f"Failed to transform {file.name}: {e}")
            continue
    
    # Concatenate all DataFrames
    import polars as pl
    for key in all_data.keys():
        if all_data[key]:
            all_data[key] = pl.concat(all_data[key])
        else:
            all_data[key] = pl.DataFrame()
    
    logger.success("Transformation complete")
    logger.info(f"  Tenders: {len(all_data['tenders'])}")
    logger.info(f"  Companies: {len(all_data['companies'])}")
    logger.info(f"  Buyers: {len(all_data['buyers'])}")
    logger.info(f"  WINS: {len(all_data['wins'])}")
    
    # Step 3: Quality validation
    logger.info("\n[3/4] Validating data quality...")
    validator = AnacQualityValidator()
    
    reports = {}
    for context, df in all_data.items():
        if not df.is_empty():
            reports[context] = validator.validate(df, context)
    
    # Check if any critical issues
    critical_failures = [
        ctx for ctx, report in reports.items()
        if not report["pass"]
    ]
    
    if critical_failures:
        logger.error(f"Critical quality issues in: {critical_failures}")
        logger.warning("Proceeding anyway for testing purposes...")
    
    # Step 4: Load to Neo4j
    logger.info("\n[4/4] Loading to Neo4j...")
    
    try:
        driver = get_driver()
        driver.verify_connectivity()
        logger.success("Connected to Neo4j")
        
        loader = AnacNeo4jLoader(driver)
        stats = loader.load_all(all_data)
        
        logger.success("\n" + "=" * 60)
        logger.success("ETL Pipeline Complete!")
        logger.success("=" * 60)
        logger.success(f"Loaded:")
        logger.success(f"  - {stats['tenders']} tenders")
        logger.success(f"  - {stats['companies']} companies")
        logger.success(f"  - {stats['buyers']} buyers")
        logger.success(f"  - {stats['wins']} WINS relationships")
        
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        sys.exit(1)
    
    finally:
        driver.close()


if __name__ == "__main__":
    main()
