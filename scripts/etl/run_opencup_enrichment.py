import sys
from pathlib import Path

from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


from paladino.db import get_driver
from paladino.etl.opencup_download import OpencupDownloader
from paladino.etl.opencup_loader import OpencupNeo4jLoader
from paladino.etl.opencup_transform import OpencupTransformer


def main():
    logger.info("Starting OpenCUP Enrichment ETL (Localization & Subjects)")

    downloader = OpencupDownloader()
    transformer = OpencupTransformer()
    driver = get_driver()
    loader = OpencupNeo4jLoader(driver)

    # 1. Localization
    logger.info("\n[1/2] Processing Localization data...")
    loc_file = downloader.cache_dir / "OpenCup_Localizzazione.csv"
    if loc_file.exists():
        try:
            df_loc = downloader.load_csv_to_dataframe(loc_file)
            if not df_loc.is_empty():
                loc_data = transformer.extract_localization(df_loc)
                # Filter out projects - we only want CUPs that exist in Neo4j?
                # Actually Neo4j MATCH will handle it, but for speed we just load.
                loaded_loc = loader.load_localization(loc_data)
                logger.success(f"Loaded {loaded_loc} localization relationships")
            del df_loc
        except Exception as e:
            logger.error(f"Failed to process localization: {e}")

    # 2. Subjects
    logger.info("\n[2/2] Processing Subjects data...")
    sub_file = downloader.cache_dir / "OpenCup_Soggetti.csv"
    if sub_file.exists():
        try:
            df_sub = downloader.load_csv_to_dataframe(sub_file)
            if not df_sub.is_empty():
                sub_data = transformer.extract_subjects(df_sub)
                loaded_sub = loader.load_subjects(sub_data)
                logger.success(f"Loaded {loaded_sub} actors")
            del df_sub
        except Exception as e:
            logger.error(f"Failed to process subjects: {e}")

    driver.close()
    logger.success("Enrichment Complete!")


if __name__ == "__main__":
    main()
