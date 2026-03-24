#!/usr/bin/env python3
"""
Run entity resolution pipeline - Deduplicate companies and enrich with statistics.
"""

import sys
from pathlib import Path

import polars as pl
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from paladino.db import get_driver
from paladino.ml.deduplicator import CompanyDeduplicator
from paladino.ml.enricher import CompanyEnricher
from paladino.ml.entity_loader import EntityResolutionLoader


def main():
    """Run the complete entity resolution pipeline."""
    logger.info("=" * 60)
    logger.info("Entity Resolution Pipeline")
    logger.info("=" * 60)

    # Connect to Neo4j
    driver = get_driver()

    try:
        driver.verify_connectivity()
        logger.success("Connected to Neo4j")

        # Step 1: Load companies from Neo4j
        logger.info("\n[1/4] Loading companies from Neo4j...")

        with driver.session() as session:
            result = session.run("""
                MATCH (c:Company)
                RETURN c.id as id,
                       c.cf as cf,
                       c.nome_normalizzato as nome_normalizzato,
                       c.nome_originale as nome_originale
            """)

            companies_data = [dict(r) for r in result]

        if not companies_data:
            logger.error("No companies found in Neo4j. Run ANAC ETL first.")
            sys.exit(1)

        companies_df = pl.DataFrame(companies_data)
        logger.success(f"Loaded {len(companies_df)} companies")

        # Step 2: Find duplicates
        logger.info("\n[2/4] Finding duplicate companies...")

        deduplicator = CompanyDeduplicator(
            name_similarity_threshold=0.85, cf_match_weight=0.5, name_match_weight=0.5
        )

        duplicates_df = deduplicator.find_duplicates(companies_df)

        if duplicates_df.is_empty():
            logger.warning("No duplicates found")
        else:
            logger.success(f"Found {len(duplicates_df)} duplicate pairs")

            # Show sample duplicates
            logger.info("Sample duplicates:")
            for row in duplicates_df.head(5).iter_rows(named=True):
                logger.info(
                    f"  {row['company_id_1']} ↔ {row['company_id_2']} "
                    f"(confidence: {row['confidence']}, method: {row['match_method']})"
                )

        # Step 3: Merge duplicates
        logger.info("\n[3/4] Merging duplicates...")

        companies_df, same_as_df = deduplicator.merge_duplicates(companies_df, duplicates_df)

        # Load SAME_AS relationships
        loader = EntityResolutionLoader(driver)

        if not same_as_df.is_empty():
            loader.load_same_as_relationships(same_as_df)

        # Step 4: Enrich companies
        logger.info("\n[4/4] Enriching companies with statistics and risk scores...")

        enricher = CompanyEnricher(driver)
        enricher.enrich_all_companies()

        logger.success("\n" + "=" * 60)
        logger.success("Entity Resolution Complete!")
        logger.success("=" * 60)
        logger.success("Results:")
        logger.success(f"  - {len(companies_df)} unique companies")
        logger.success(f"  - {len(same_as_df)} SAME_AS relationships")
        logger.success("  - All companies enriched with statistics")

        # Validation: Show high-risk companies
        logger.info("\n[Validation] High-risk companies:")

        with driver.session() as session:
            result = session.run("""
                MATCH (c:Company)
                WHERE c.risk_score > 0.5
                RETURN c.nome_normalizzato as nome,
                       c.risk_score as risk_score,
                       c.anomaly_flags as flags,
                       c.total_tenders as tenders
                ORDER BY c.risk_score DESC
                LIMIT 10
            """)

            for record in result:
                logger.info(
                    f"  {record['nome']}: risk={record['risk_score']:.2f}, "
                    f"tenders={record['tenders']}, flags={record['flags']}"
                )

    except Exception as e:
        logger.error(f"Entity resolution failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    finally:
        driver.close()


if __name__ == "__main__":
    main()
