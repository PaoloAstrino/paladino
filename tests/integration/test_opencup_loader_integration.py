"""
Integration tests for OpenCUP loader.

NOTE: These tests require a running Neo4j instance.
"""

import pytest
import polars as pl

from paladino.etl.opencup_loader import OpencupNeo4jLoader


@pytest.mark.skip(reason="Requires running Neo4j instance")
def test_load_projects_creates_nodes(clean_neo4j):
    """Test that loading projects creates nodes."""
    loader = OpencupNeo4jLoader(clean_neo4j)

    project_df = pl.DataFrame(
        [
            {
                "id": "p1",
                "cup": "J12345678901234",
                "titolo": "Test Project",
                "descrizione": "Test description",
                "importo_previsto": 2000000.0,
                "importo_finanziato": 1800000.0,
                "data_inizio": "2024-01-01",
                "data_fine": "2026-12-31",
                "stato": "In corso",
                "regione": "Lazio",
                "provincia": "RM",
                "settore": "ICT",
                "fondi_comunitari": ["PNRR"],
                "source": "TEST",
                "dataset_version": "test-v1",
                "retrieval_date": "2024-01-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loaded = loader.load_projects(project_df)

    assert loaded == 1

    # Verify node exists
    with clean_neo4j.session() as session:
        result = session.run("MATCH (p:Project {cup: 'J12345678901234'}) RETURN p")
        node = result.single()

        assert node is not None
        assert node["p"]["titolo"] == "Test Project"


@pytest.mark.skip(reason="Requires running Neo4j instance")
def test_load_funding_sources(clean_neo4j):
    """Test loading funding sources."""
    loader = OpencupNeo4jLoader(clean_neo4j)

    funding_df = pl.DataFrame(
        [
            {"id": "f1", "nome": "PNRR", "tipo": "EU", "source": "TEST"},
            {"id": "f2", "nome": "FSE", "tipo": "EU", "source": "TEST"},
        ]
    )

    loaded = loader.load_funding_sources(funding_df)

    assert loaded == 2

    # Verify nodes exist
    with clean_neo4j.session() as session:
        result = session.run(
            "MATCH (f:FundingSource) WHERE f.source = 'TEST' RETURN count(f) as count"
        )
        count = result.single()["count"]

        assert count == 2


@pytest.mark.skip(reason="Requires running Neo4j instance")
def test_load_part_of_project_relationships(clean_neo4j):
    """Test loading PART_OF_PROJECT relationships."""
    loader = OpencupNeo4jLoader(clean_neo4j)

    # Create tender and project first
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (t:Tender {cig: 'TEST_CIG', source: 'TEST'})
            CREATE (p:Project {cup: 'TEST_CUP', source: 'TEST'})
        """)

    # Load relationship
    matches_df = pl.DataFrame(
        [
            {
                "tender_cig": "TEST_CIG",
                "project_cup": "TEST_CUP",
                "confidence": 0.95,
                "matching_method": "temporal",
                "match_date": "2024-01-01T00:00:00",
            }
        ]
    )

    loaded = loader.load_part_of_project(matches_df)

    assert loaded == 1

    # Verify relationship
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (t:Tender {cig: 'TEST_CIG'})-[r:PART_OF_PROJECT]->(p:Project {cup: 'TEST_CUP'})
            RETURN r.confidence as conf, r.matching_method as method
        """)
        rel = result.single()

        assert rel is not None
        assert rel["conf"] == 0.95
        assert rel["method"] == "temporal"


@pytest.mark.skip(reason="Requires running Neo4j instance")
def test_project_versioning(clean_neo4j):
    """Test that updating a project creates a Version node."""
    loader = OpencupNeo4jLoader(clean_neo4j)

    # Load initial project
    project_v1 = pl.DataFrame(
        [
            {
                "id": "p1",
                "cup": "J_VERSION_TEST",
                "titolo": "Test Project",
                "importo_finanziato": 1000000.0,
                "stato": "In corso",
                "source": "TEST",
                "dataset_version": "v1",
                "retrieval_date": "2024-01-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loader.load_projects(project_v1)

    # Load updated project
    project_v2 = pl.DataFrame(
        [
            {
                "id": "p1",
                "cup": "J_VERSION_TEST",
                "titolo": "Test Project",
                "importo_finanziato": 1200000.0,  # Updated amount
                "stato": "Completato",  # Updated status
                "source": "TEST",
                "dataset_version": "v2",
                "retrieval_date": "2024-06-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loader.load_projects(project_v2)

    # Verify versioning
    with clean_neo4j.session() as session:
        # Current state
        result = session.run("""
            MATCH (p:Project {cup: 'J_VERSION_TEST'})
            RETURN p.importo_finanziato as current_amount, p.stato as current_status
        """)
        current = result.single()
        assert current["current_amount"] == 1200000.0
        assert current["current_status"] == "Completato"

        # Historical state
        result = session.run("""
            MATCH (p:Project {cup: 'J_VERSION_TEST'})-[:HAS_VERSION]->(v:Version)
            RETURN v.importo_finanziato as old_amount, v.stato as old_status
        """)
        old = result.single()
        assert old["old_amount"] == 1000000.0
        assert old["old_status"] == "In corso"
