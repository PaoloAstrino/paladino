#!/usr/bin/env python3
"""
Run OpenCUP ETL pipeline - Download, transform, match, and load OpenCUP data.
"""

import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver
from paladino.etl.opencup_download import OpencupDownloader
from paladino.etl.opencup_transform import OpencupTransformer
from paladino.etl.opencup_loader import OpencupNeo4jLoader
from paladino.etl.cup_cig_matcher import CupCigMatcher
import polars as pl


def main():
    """Run the complete OpenCUP ETL pipeline."""
    logger.info("=" * 60)
    logger.info("OpenCUP ETL Pipeline + CUP-CIG Matching")
    logger.info("=" * 60)
    
    # Step 1: Detect cached files
    logger.info("\n[1/5] Detecting OpenCUP CSV files...")
    downloader = OpencupDownloader()
    files = downloader.get_cached_files()
    
    if not files:
        logger.error(f"No OpenCUP project files found in {downloader.cache_dir}. Exiting.")
        sys.exit(1)
    
    logger.success(f"Found {len(files)} files to process")
    
    # Step 2 & 4: Transform and Load (Iterative to save memory)
    logger.info("\n[2/4/5] Processing files iteratively...")
    transformer = OpencupTransformer()
    driver = get_driver()
    loader = OpencupNeo4jLoader(driver)
    
    total_stats = {"projects": 0, "funding_sources": 0, "part_of_project": 0, "funded_by": 0}
    
    for i, file in enumerate(files, 1):
        logger.info(f"--- Processing File {i}/{len(files)}: {file.name} ---")
        
        try:
            # Load single file
            df_raw = downloader.load_csv_to_dataframe(file)
            if df_raw.is_empty():
                continue
                
            # Transform
            data = transformer.transform(df_raw)
            
            # Load to Neo4j
            # Note: For now, we omit the matcher (Step 3) during the bulk load 
            # as it requires all tenders in memory. We can run it as a post-process.
            stats = loader.load_all(data, pl.DataFrame())
            
            # Accumulate stats
            for k in total_stats:
                total_stats[k] += stats.get(k, 0)
                
            # Free memory
            del df_raw
            del data
            
        except Exception as e:
            logger.error(f"Failed to process {file.name}: {e}")
            continue
    
    logger.success(f"Total Loaded from Projects:")
    logger.success(f"  - {total_stats['projects']} projects")
    logger.success(f"  - {total_stats['funding_sources']} funding sources")
    
    # Step 4.1: Localization Ingestion
    logger.info("\n[4.1/5] Processing Localization data...")
    loc_file = downloader.cache_dir / "OpenCup_Localizzazione.csv"
    if loc_file.exists():
        try:
            df_loc = downloader.load_csv_to_dataframe(loc_file)
            if not df_loc.is_empty():
                loc_data = transformer.extract_localization(df_loc)
                loaded_loc = loader.load_localization(loc_data)
                logger.success(f"Loaded {loaded_loc} localization relationships")
                total_stats["localization"] = loaded_loc
            del df_loc
        except Exception as e:
            logger.error(f"Failed to process localization: {e}")
    else:
        logger.warning("OpenCup_Localizzazione.csv not found")

    # Step 4.2: Subjects Ingestion
    logger.info("\n[4.2/5] Processing Subjects data...")
    sub_file = downloader.cache_dir / "OpenCup_Soggetti.csv"
    if sub_file.exists():
        try:
            df_sub = downloader.load_csv_to_dataframe(sub_file)
            if not df_sub.is_empty():
                sub_data = transformer.extract_subjects(df_sub)
                loaded_sub = loader.load_subjects(sub_data)
                logger.success(f"Loaded {loaded_sub} actors")
                total_stats["subjects"] = loaded_sub
            del df_sub
        except Exception as e:
            logger.error(f"Failed to process subjects: {e}")
    else:
        logger.warning("OpenCup_Soggetti.csv not found")

    driver.close()
    
    # Step 5: Validation
    logger.info("\n[5/5] Validating graph structure...")
    
    try:
        driver = get_driver()
        
        with driver.session() as session:
            # Count nodes
            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] as label, count(n) as count
                ORDER BY count DESC
            """)
            
            logger.info("Node counts:")
            for record in result:
                logger.info(f"  {record['label']}: {record['count']}")
            
            # Count relationships
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) as type, count(r) as count
                ORDER BY count DESC
            """)
            
            logger.info("Relationship counts:")
            for record in result:
                logger.info(f"  {record['type']}: {record['count']}")
        
        driver.close()
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")


if __name__ == "__main__":
    main()
