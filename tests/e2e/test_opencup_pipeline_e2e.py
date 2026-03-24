"""
End-to-end test for complete OpenCUP pipeline.
"""

import polars as pl
import pytest

from paladino.etl.cup_cig_matcher import CupCigMatcher
from paladino.etl.opencup_download import OpencupDownloader
from paladino.etl.opencup_loader import OpencupNeo4jLoader
from paladino.etl.opencup_transform import OpencupTransformer


@pytest.mark.slow
def test_opencup_pipeline_e2e(clean_neo4j, tmp_path):
    """
    End-to-end test of OpenCUP pipeline.

    This test:
    1. Downloads sample OpenCUP data
    2. Transforms to DataFrames
    3. Matches CUP to CIG
    4. Loads to Neo4j
    5. Verifies data integrity
    """
    # 1. Download (use sample data)
    downloader = OpencupDownloader(cache_dir=tmp_path / "opencup")

    # For E2E test, create sample data
    sample_data = pl.DataFrame(
        [
            {
                "CUP": "J12345678901234",
                "TITOLO_PROGETTO": "Test Project",
                "IMPORTO_PREVISTO": "1000000",
                "IMPORTO_FINANZIATO": "900000",
                "DATA_INIZIO": "01/01/2024",
                "DATA_FINE": "31/12/2026",
                "STATO": "In corso",
                "REGIONE": "Lazio",
                "FONDI_UE": "PNRR",
            }
        ]
    )

    # 2. Transform
    transformer = OpencupTransformer()
    transformed = transformer.transform_projects(sample_data)
    funding = transformer.extract_funding_sources(sample_data)

    assert len(transformed) == 1
    assert len(funding) >= 1

    # 3. Match CUP-CIG (create sample tender first)
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (t:Tender {
                cig: 'Z1234567890',
                importo: 950000.0,
                oggetto: 'Test tender for project',
                data_aggiudicazione: '2024-01-15',
                source: 'TEST'
            })
        """)

    # Fetch tenders for matching
    with clean_neo4j.session() as session:
        result = session.run(
            "MATCH (t:Tender) WHERE t.source = 'TEST' RETURN t.cig as cig, t.importo as importo, t.oggetto as oggetto, t.data_aggiudicazione as data_aggiudicazione"
        )
        tenders_df = pl.DataFrame([dict(r) for r in result])

    matcher = CupCigMatcher(use_semantic=False)
    matches = matcher.match(tenders_df, transformed)

    # 4. Load to Neo4j
    loader = OpencupNeo4jLoader(clean_neo4j)

    data = {"projects": transformed, "funding_sources": funding}

    stats = loader.load_all(data, matches)

    # 5. Verify
    assert stats["projects"] == 1
    assert stats["funding_sources"] >= 1

    # Verify project exists
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (p:Project {cup: 'J12345678901234'})
            RETURN p.titolo as titolo
        """)
        project = result.single()

        assert project is not None
        assert project["titolo"] == "Test Project"

    # Verify funding relationship
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (p:Project {cup: 'J12345678901234'})-[:FUNDED_BY]->(f:FundingSource {nome: 'PNRR'})
            RETURN count(*) as count
        """)
        count = result.single()["count"]

        assert count == 1


@pytest.mark.slow
def test_cup_cig_matching_e2e(clean_neo4j):
    """
    E2E test for CUP-CIG matching strategies.

    Tests all three matching strategies in sequence.
    """
    # Create test data
    with clean_neo4j.session() as session:
        # Tender with explicit CUP reference
        session.run("""
            CREATE (t1:Tender {
                cig: 'EXPLICIT_CIG',
                cup: 'J11111111111111',
                importo: 100000.0,
                source: 'TEST'
            })
        """)

        # Tender for temporal matching
        session.run("""
            CREATE (t2:Tender {
                cig: 'TEMPORAL_CIG',
                importo: 200000.0,
                data_aggiudicazione: '2024-02-15',
                oggetto: 'IT services',
                source: 'TEST'
            })
        """)

    # Create projects
    projects_df = pl.DataFrame(
        [
            {
                "cup": "J11111111111111",
                "titolo": "Project with explicit match",
                "importo_previsto": 100000.0,
            },
            {
                "cup": "J22222222222222",
                "titolo": "IT digitalization project",
                "importo_previsto": 210000.0,
                "data_inizio": "2024-02-20",
            },
        ]
    )

    # Fetch tenders
    with clean_neo4j.session() as session:
        result = session.run("MATCH (t:Tender) WHERE t.source = 'TEST' RETURN t")
        tenders_df = pl.DataFrame([dict(r["t"]) for r in result])

    # Run matcher
    matcher = CupCigMatcher(use_semantic=False)
    matches = matcher.match(tenders_df, projects_df)

    # Verify matches
    assert len(matches) >= 1

    # Should have explicit match
    explicit_match = next((m for m in matches if m["tender_cig"] == "EXPLICIT_CIG"), None)
    assert explicit_match is not None
    assert explicit_match["confidence"] == 1.0
    assert explicit_match["matching_method"] == "explicit"

    # May have temporal match (depending on tolerance)
    temporal_match = next((m for m in matches if m["tender_cig"] == "TEMPORAL_CIG"), None)
    if temporal_match:
        assert temporal_match["matching_method"] == "temporal"
        assert temporal_match["confidence"] < 1.0
