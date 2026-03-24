"""
Integration tests for ANAC loader with temporal versioning.
"""

import polars as pl

from paladino.etl.anac_loader import AnacNeo4jLoader


def test_load_tender_creates_node(clean_neo4j):
    """Test that loading a tender creates a node."""
    loader = AnacNeo4jLoader(clean_neo4j)

    tender_df = pl.DataFrame(
        [
            {
                "id": "t1",
                "cig": "TEST123",
                "ocid": "ocds-test",
                "oggetto": "Test tender",
                "importo": 100000.0,
                "procedura": "open",
                "source": "TEST",
                "dataset_version": "test-v1",
                "retrieval_date": "2024-01-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loaded = loader.load_tenders(tender_df)

    assert loaded == 1

    # Verify node exists
    with clean_neo4j.session() as session:
        result = session.run("MATCH (t:Tender {cig: 'TEST123'}) RETURN t")
        node = result.single()

        assert node is not None
        assert node["t"]["oggetto"] == "Test tender"


def test_versioning_creates_version_node(clean_neo4j):
    """Test that updating a tender creates a Version node."""
    loader = AnacNeo4jLoader(clean_neo4j)

    # Load initial tender
    tender_v1 = pl.DataFrame(
        [
            {
                "id": "t1",
                "cig": "TEST123",
                "ocid": "ocds-test",
                "oggetto": "Test tender",
                "importo": 100000.0,
                "procedura": "open",
                "source": "TEST",
                "dataset_version": "test-v1",
                "retrieval_date": "2024-01-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loader.load_tenders(tender_v1)

    # Load updated tender (same CIG, different price)
    tender_v2 = pl.DataFrame(
        [
            {
                "id": "t1",
                "cig": "TEST123",
                "ocid": "ocds-test",
                "oggetto": "Test tender",
                "importo": 120000.0,  # Updated price
                "procedura": "open",
                "source": "TEST",
                "dataset_version": "test-v2",
                "retrieval_date": "2024-02-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    loader.load_tenders(tender_v2)

    # Verify Version node was created
    with clean_neo4j.session() as session:
        # Check main tender has new price
        result = session.run("""
            MATCH (t:Tender {cig: 'TEST123'})
            RETURN t.importo as current_price
        """)
        assert result.single()["current_price"] == 120000.0

        # Check Version node has old price
        result = session.run("""
            MATCH (t:Tender {cig: 'TEST123'})-[:HAS_VERSION]->(v:Version)
            RETURN v.importo as old_price, v.archived_at as archived
        """)
        version = result.single()

        assert version is not None
        assert version["old_price"] == 100000.0
        assert version["archived"] is not None


def test_load_companies_and_wins(clean_neo4j):
    """Test loading companies and WINS relationships."""
    loader = AnacNeo4jLoader(clean_neo4j)

    # Load tender
    tender_df = pl.DataFrame(
        [
            {
                "id": "t1",
                "cig": "TEST123",
                "ocid": "ocds-test",
                "oggetto": "Test tender",
                "importo": 100000.0,
                "procedura": "open",
                "source": "TEST",
                "dataset_version": "test-v1",
                "retrieval_date": "2024-01-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    # Load company
    company_df = pl.DataFrame(
        [
            {
                "id": "c1",
                "cf": "12345678901",
                "piva": "12345678901",
                "nome_normalizzato": "TEST COMPANY",
                "nome_originale": "Test Company S.r.l.",
                "source": "TEST",
                "dataset_version": "test-v1",
                "retrieval_date": "2024-01-01T00:00:00",
                "confidence": 1.0,
            }
        ]
    )

    # Load WINS relationship
    wins_df = pl.DataFrame(
        [
            {
                "company_cf": "12345678901",
                "tender_cig": "TEST123",
                "importo": 95000.0,
                "data": "2024-01-15",
                "source": "TEST",
                "confidence": 1.0,
            }
        ]
    )

    loader.load_tenders(tender_df)
    loader.load_companies(company_df)
    loader.load_wins(wins_df)

    # Verify relationship
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (c:Company {cf: '12345678901'})-[w:WINS]->(t:Tender {cig: 'TEST123'})
            RETURN w.importo as amount
        """)

        rel = result.single()
        assert rel is not None
        assert rel["amount"] == 95000.0
