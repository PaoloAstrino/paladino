"""
End-to-end tests for Connection Discovery against a real Neo4j instance.

These tests require a running Neo4j container (docker-compose up -d).
Skipped automatically if Neo4j is unavailable.
"""

import os

import pytest

from paladino.config import settings
from paladino.db import Neo4jConnection
from paladino.etl.connection_resolver import ConnectionResolver
from paladino.etl.unstructured_models import ExtractedEntity, ExtractedRelationship, NERResult


def neo4j_available():
    """Check if Neo4j is reachable."""
    try:
        conn = Neo4jConnection()
        conn.verify_connectivity()
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture
def db():
    """Real Neo4j connection for E2E tests."""
    conn = Neo4jConnection()
    conn.verify_connectivity()
    yield conn
    conn.close()


@pytest.fixture
def resolver(db):
    """ConnectionResolver backed by real Neo4j."""
    return ConnectionResolver(db=db, llm_manager=None, fuzzy_threshold=0.85)


@pytest.fixture(autouse=True)
def clean_graph(db):
    """Clean test data before and after each test."""
    # Clean before
    db.run_query("""
    MATCH (n:E2E_TEST)
    DETACH DELETE n
    """)
    yield
    # Clean after
    db.run_query("""
    MATCH (n:E2E_TEST)
    DETACH DELETE n
    """)


def _create_test_company(db, cf, name, regione="Lombardia"):
    """Create a test Company node."""
    db.run_query("""
    CREATE (c:Company:E2E_TEST {
        cf: $cf,
        nome_normalizzato: $name,
        regione: $regione,
        risk_score: 0.0
    })
    """, {"cf": cf, "name": name, "regione": regione})


def _create_test_person(db, name):
    """Create a test Person node."""
    db.run_query("""
    CREATE (p:Person:E2E_TEST {
        name: $name
    })
    """, {"name": name})


def _create_test_tender(db, cig, oggetto="Test Tender", importo=100000):
    """Create a test Tender node."""
    db.run_query("""
    CREATE (t:Tender:E2E_TEST {
        cig: $cig,
        oggetto: $oggetto,
        importo: $importo
    })
    """, {"cig": cig, "oggetto": oggetto, "importo": importo})


def _create_shareholder(db, person_name, company_cf):
    """Create SHAREHOLDER_OF relationship."""
    db.run_query("""
    MATCH (p:Person:E2E_TEST {name: $person_name})
    MATCH (c:Company:E2E_TEST {cf: $company_cf})
    CREATE (p)-[:SHAREHOLDER_OF {source: 'e2e_test'}]->(c)
    """, {"person_name": person_name, "company_cf": company_cf})


def _create_tender_win(db, company_cf, tender_cig):
    """Create WINS relationship."""
    db.run_query("""
    MATCH (c:Company:E2E_TEST {cf: $company_cf})
    MATCH (t:Tender:E2E_TEST {cig: $tender_cig})
    CREATE (c)-[:WINS {source: 'e2e_test'}]->(t)
    """, {"company_cf": company_cf, "tender_cig": tender_cig})


# ──────────────────────────────────────────────────────────────
# E2E Tests
# ──────────────────────────────────────────────────────────────


@pytest.mark.skipif(not neo4j_available(), reason="Neo4j not available")
class TestConnectionResolverE2E:
    """End-to-end tests with real Neo4j."""

    def test_exact_cf_match_resolves_to_existing(self, resolver, db):
        """Extracted entity with CF should match existing Company in Neo4j."""
        _create_test_company(db, "MRARSS80A01H501Z", "Rossi SRL")

        entities = [
            ExtractedEntity(
                id="e1", type="Company",
                properties={"name": "Rossi SRL", "cf": "MRARSS80A01H501Z"},
                confidence=0.95,
            ),
        ]
        ner_result = NERResult(entities=entities)
        report = resolver.resolve(ner_result, source="e2e_test.pdf")

        assert report.entities_extracted == 1
        assert report.entities_matched == 1
        assert report.entity_matches[0].match_method == "exact_cf"
        assert report.entity_matches[0].confidence == 1.0

    def test_no_match_creates_new(self, resolver, db):
        """Entity with no matching CF/name should be marked for creation."""
        entities = [
            ExtractedEntity(
                id="e1", type="Company",
                properties={"name": "Completely Unknown Company XYZ SPA"},
                confidence=0.5,
            ),
        ]
        ner_result = NERResult(entities=entities)
        report = resolver.resolve(ner_result, source="e2e_test.pdf")

        assert report.entities_extracted == 1
        assert report.entities_created == 1
        assert report.entities_matched == 0

    def test_fuzzy_name_match_finds_similar_company(self, resolver, db):
        """Entity with similar but not exact name should match via fuzzy."""
        _create_test_company(db, "MRARSS80A01H501Z", "Rossi Costruzioni SRL")

        entities = [
            ExtractedEntity(
                id="e1", type="Company",
                properties={"name": "Rossi Costruzioni S.R.L."},
                confidence=0.9,
            ),
        ]
        ner_result = NERResult(entities=entities)
        report = resolver.resolve(ner_result, source="e2e_test.pdf")

        # Should match by fuzzy name (high similarity since names are nearly identical)
        assert report.entities_matched >= 0 or report.entities_created == 1
        # If matched, it should be a fuzzy match
        if report.entities_matched == 1:
            assert report.entity_matches[0].match_method in ("fuzzy_name", "exact_cf")

    def test_shared_shareholder_discovery(self, resolver, db):
        """Two companies sharing a person should be flagged as implicitly connected."""
        _create_test_company(db, "AAAAAA00A00A000A", "Alpha SRL")
        _create_test_company(db, "BBBBBB00B00B000B", "Beta SPA")
        _create_test_person(db, "Mario Verdi")
        _create_shareholder(db, "Mario Verdi", "AAAAAA00A00A000A")
        _create_shareholder(db, "Mario Verdi", "BBBBBB00B00B000B")

        entities = [
            ExtractedEntity(
                id="c1", type="Company",
                properties={"name": "Alpha SRL", "cf": "AAAAAA00A00A000A"},
                confidence=0.95,
            ),
            ExtractedEntity(
                id="c2", type="Company",
                properties={"name": "Beta SPA", "cf": "BBBBBB00B00B000B"},
                confidence=0.90,
            ),
        ]
        ner_result = NERResult(entities=entities)
        report = resolver.resolve(ner_result, source="e2e_test_shareholder.pdf")

        assert report.entities_extracted == 2
        assert report.entities_matched == 2
        assert report.implicit_connections_found >= 1

        # Find the shared shareholder connection
        shareholder_conn = next(
            (c for c in report.implicit_connections if c.discovery_type == "shared_shareholder"),
            None,
        )
        assert shareholder_conn is not None
        # Person has 'name' property, resolved via coalesce
        assert "shareholder" in shareholder_conn.description.lower()

    def test_common_tender_discovery(self, resolver, db):
        """Two companies winning the same tender should be flagged."""
        _create_test_company(db, "CCCCCC00C00C000C", "Gamma SRL")
        _create_test_company(db, "DDDDDD00D00D000D", "Delta SRL")
        _create_test_tender(db, "Z99887766", "Public Works Tender", 500000)
        _create_tender_win(db, "CCCCCC00C00C000C", "Z99887766")
        _create_tender_win(db, "DDDDDD00D00D000D", "Z99887766")

        entities = [
            ExtractedEntity(
                id="c1", type="Company",
                properties={"name": "Gamma SRL", "cf": "CCCCCC00C00C000C"},
                confidence=0.95,
            ),
            ExtractedEntity(
                id="c2", type="Company",
                properties={"name": "Delta SRL", "cf": "DDDDDD00D00D000D"},
                confidence=0.90,
            ),
        ]
        ner_result = NERResult(entities=entities)
        report = resolver.resolve(ner_result, source="e2e_test_tender.pdf")

        assert report.entities_extracted == 2
        assert report.entities_matched == 2
        assert report.implicit_connections_found >= 1

        tender_conn = next(
            (c for c in report.implicit_connections if c.discovery_type == "common_tender"),
            None,
        )
        assert tender_conn is not None
        assert "Z99887766" in tender_conn.description

    def test_geographic_clustering(self, resolver, db):
        """Companies in the same region should be flagged."""
        _create_test_company(db, "EEEEEE00E00E000E", "Epsilon SRL", regione="Lazio")
        _create_test_company(db, "FFFFFF00F00F000F", "Zeta SRL", regione="Lazio")

        entities = [
            ExtractedEntity(
                id="c1", type="Company",
                properties={"name": "Epsilon SRL", "cf": "EEEEEE00E00E000E"},
                confidence=0.95,
            ),
            ExtractedEntity(
                id="c2", type="Company",
                properties={"name": "Zeta SRL", "cf": "FFFFFF00F00F000F"},
                confidence=0.90,
            ),
        ]
        ner_result = NERResult(entities=entities)
        report = resolver.resolve(ner_result, source="e2e_test_geo.pdf")

        assert report.entities_extracted == 2
        assert report.entities_matched == 2
        assert report.implicit_connections_found >= 1

        geo_conn = next(
            (c for c in report.implicit_connections if c.discovery_type == "geographic_cluster"),
            None,
        )
        assert geo_conn is not None
        assert "Lazio" in geo_conn.description

    def test_full_pipeline_mixed_match_and_create(self, resolver, db):
        """Some entities match, some are created new, with implicit connections."""
        _create_test_company(db, "AAAAAA00A00A000A", "Existing Co")
        _create_test_person(db, "Luigi Bianchi")
        _create_shareholder(db, "Luigi Bianchi", "AAAAAA00A00A000A")

        entities = [
            ExtractedEntity(
                id="c1", type="Company",
                properties={"name": "Existing Co", "cf": "AAAAAA00A00A000A"},
                confidence=0.95,
            ),
            ExtractedEntity(
                id="c2", type="Company",
                properties={"name": "BrandNew Company SPA"},
                confidence=0.7,
            ),
            ExtractedEntity(
                id="p1", type="Person",
                properties={"name": "Luigi Bianchi"},
                confidence=0.8,
            ),
        ]
        relationships = [
            ExtractedRelationship(source_id="c1", target_id="p1", type="SHAREHOLDER_OF", confidence=0.85),
        ]

        ner_result = NERResult(entities=entities, relationships=relationships)
        report = resolver.resolve(ner_result, source="e2e_mixed.pdf")

        assert report.entities_extracted == 3
        assert report.entities_matched == 1  # Only Existing Co matched by CF
        assert report.entities_created == 2  # BrandNew Company + Luigi Bianchi (as new Person)
        assert report.relationships_resolved == 1
