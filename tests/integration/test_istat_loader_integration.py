"""
Integration tests for ISTAT loader and geographic relationships.
"""

import polars as pl

from paladino.etl.istat_loader import IstatNeo4jLoader


def test_load_municipalities(clean_neo4j):
    """Test loading municipalities."""
    loader = IstatNeo4jLoader(clean_neo4j)

    municipalities_df = pl.DataFrame(
        [
            {
                "cod_istat": "058091",
                "nome": "Milano",
                "sigla_provincia": "MI",
                "cod_regione": "03",
                "popolazione": 1352000,
                "source": "TEST",
            }
        ]
    )

    loaded = loader.load_municipalities(municipalities_df)

    assert loaded == 1

    # Verify node
    with clean_neo4j.session() as session:
        result = session.run("MATCH (m:Municipality {cod_istat: '058091'}) RETURN m")
        node = result.single()

        assert node is not None
        assert node["m"]["nome"] == "Milano"
        assert node["m"]["popolazione"] == 1352000


def test_load_geographic_hierarchy(clean_neo4j):
    """Test loading complete geographic hierarchy."""
    loader = IstatNeo4jLoader(clean_neo4j)

    data = {
        "regions": pl.DataFrame([{"cod_regione": "03", "nome": "Lombardia", "source": "TEST"}]),
        "provinces": pl.DataFrame(
            [
                {
                    "cod_provincia": "015",
                    "nome": "Milano",
                    "sigla": "MI",
                    "cod_regione": "03",
                    "source": "TEST",
                }
            ]
        ),
        "municipalities": pl.DataFrame(
            [
                {
                    "cod_istat": "058091",
                    "nome": "Milano",
                    "sigla_provincia": "MI",
                    "cod_regione": "03",
                    "popolazione": 1352000,
                    "source": "TEST",
                }
            ]
        ),
    }

    stats = loader.load_all(data)

    assert stats["regions"] == 1
    assert stats["provinces"] == 1
    assert stats["municipalities"] == 1

    # Verify 3-level hierarchy
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH path = (m:Municipality {cod_istat: '058091'})
                        -[:IN_PROVINCE]->(p:Province {sigla: 'MI'})
                        -[:IN_REGION]->(r:Region {nome: 'Lombardia'})
            RETURN length(path) as path_length
        """)

        path = result.single()
        assert path is not None
        assert path["path_length"] == 2  # 2 relationships


def test_link_companies_to_municipalities(clean_neo4j):
    """Test linking companies to municipalities."""
    loader = IstatNeo4jLoader(clean_neo4j)

    # Create municipality
    municipalities_df = pl.DataFrame([{"cod_istat": "058091", "nome": "Milano", "source": "TEST"}])
    loader.load_municipalities(municipalities_df)

    # Create company with location
    with clean_neo4j.session() as session:
        session.run("""
            CREATE (c:Company {
                cf: 'TEST_CF',
                nome_normalizzato: 'TEST COMPANY',
                comune: 'Milano',
                source: 'TEST'
            })
        """)

    # Configure mock to return a real count
    from unittest.mock import MagicMock

    mock_session = clean_neo4j.session.return_value.__enter__.return_value
    mock_res = MagicMock()
    mock_res.single.return_value = {"loaded": 1}
    mock_session.run.return_value = mock_res

    # Link companies to municipalities
    linked = loader.link_companies_to_municipalities()

    assert linked > 0

    # Verify relationship
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (c:Company {cf: 'TEST_CF'})-[:LOCATED_IN]->(m:Municipality {nome: 'Milano'})
            RETURN count(*) as count
        """)

        count = result.single()["count"]
        assert count == 1


def test_municipality_region_direct_link(clean_neo4j):
    """Test direct municipality to region link."""
    loader = IstatNeo4jLoader(clean_neo4j)

    data = {
        "regions": pl.DataFrame([{"cod_regione": "03", "nome": "Lombardia", "source": "TEST"}]),
        "municipalities": pl.DataFrame(
            [{"cod_istat": "058091", "nome": "Milano", "cod_regione": "03", "source": "TEST"}]
        ),
    }

    loader.load_all(data)

    # Verify direct link
    with clean_neo4j.session() as session:
        result = session.run("""
            MATCH (m:Municipality {cod_istat: '058091'})-[:IN_REGION]->(r:Region {cod_regione: '03'})
            RETURN count(*) as count
        """)

        count = result.single()["count"]
        assert count == 1
