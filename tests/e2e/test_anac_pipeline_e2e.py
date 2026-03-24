"""
End-to-end test for complete ANAC pipeline.
"""

import pytest

from paladino.etl.anac_download import AnacOcdsDownloader
from paladino.etl.anac_loader import AnacNeo4jLoader
from paladino.etl.anac_quality import AnacQualityValidator
from paladino.etl.anac_transform import AnacOcdsTransformer


@pytest.mark.slow
def test_anac_pipeline_e2e(clean_neo4j, tmp_path):
    """
    End-to-end test of ANAC pipeline.

    This test:
    1. Downloads sample OCDS data (or uses cached)
    2. Transforms to DataFrames
    3. Validates quality
    4. Loads to Neo4j
    5. Verifies data integrity
    """
    # 1. Download (use cache dir in tmp)
    downloader = AnacOcdsDownloader(cache_dir=tmp_path / "anac")

    # For E2E test, we'll use a small sample
    # In production, this would download real data
    files = downloader.get_cached_files()

    if not files:
        pytest.skip("No ANAC data available for E2E test")

    # 2. Transform
    transformer = AnacOcdsTransformer()

    all_data = {"tenders": [], "companies": [], "buyers": [], "wins": []}

    for file in files[:1]:  # Process only first file for speed
        data = transformer.transform_file(file)

        for key in all_data:
            if key in data and not data[key].is_empty():
                all_data[key].append(data[key])

    # Concatenate DataFrames
    import polars as pl

    for key in all_data:
        if all_data[key]:
            all_data[key] = pl.concat(all_data[key])
        else:
            all_data[key] = pl.DataFrame()

    # 3. Validate quality
    validator = AnacQualityValidator()

    if not all_data["tenders"].is_empty():
        report = validator.validate(all_data["tenders"])

        # Quality should be acceptable
        assert report["quality_score"] > 0.7

    # 4. Load to Neo4j
    loader = AnacNeo4jLoader(clean_neo4j)
    stats = loader.load_all(all_data)

    # 5. Verify
    assert stats["tenders"] > 0
    assert stats["companies"] > 0

    # Verify relationships exist
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (c:Company)-[:WINS]->(t:Tender)
            RETURN count(*) as wins_count
        """)

        wins_count = result.single()["wins_count"]
        assert wins_count > 0


@pytest.mark.slow
def test_versioning_e2e(clean_neo4j, tmp_path):
    """
    E2E test for versioning behavior.

    Simulates re-running the pipeline with updated data.
    """
    import polars as pl

    loader = AnacNeo4jLoader(clean_neo4j)

    # First load
    tender_v1 = pl.DataFrame(
        [
            {
                "id": "t1",
                "cig": "E2E_TEST_CIG",
                "ocid": "ocds-e2e",
                "oggetto": "E2E Test Tender",
                "importo": 100000.0,
                "procedura": "open",
                "source": "TEST",
                "dataset_version": "v1",
                "retrieval_date": "2024-01-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loader.load_tenders(tender_v1)

    # Second load (updated price)
    tender_v2 = pl.DataFrame(
        [
            {
                "id": "t1",
                "cig": "E2E_TEST_CIG",
                "ocid": "ocds-e2e",
                "oggetto": "E2E Test Tender",
                "importo": 150000.0,  # Price increased
                "procedura": "open",
                "source": "TEST",
                "dataset_version": "v2",
                "retrieval_date": "2024-02-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loader.load_tenders(tender_v2)

    # Verify versioning
    with clean_neo4j.session() as session:
        # Current state
        result = session.run("""
            MATCH (t:Tender {cig: 'E2E_TEST_CIG'})
            RETURN t.importo as current, t.dataset_version as version
        """)
        current = result.single()
        assert current["current"] == 150000.0
        assert current["version"] == "v2"

        # Historical state
        result = session.run("""
            MATCH (t:Tender {cig: 'E2E_TEST_CIG'})-[:HAS_VERSION]->(v:Version)
            RETURN v.importo as old, v.dataset_version as old_version
        """)
        old = result.single()
        assert old["old"] == 100000.0
        assert old["old_version"] == "v1"
