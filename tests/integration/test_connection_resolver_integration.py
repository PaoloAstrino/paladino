"""
Integration tests for the Connection Resolver.

Tests cover:
- End-to-end entity matching against a mock Neo4j graph
- Relationship creation between resolved entities
- Implicit connection discovery (shared shareholders, common tenders)
- API endpoint POST /ingest/unstructured
- ConnectionReport model validation
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure conftest helpers are importable
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from conftest import MockResult, MockRecord  # noqa: E402

from paladino.app.api import app  # noqa: E402
from paladino.etl.connection_resolver import ConnectionResolver  # noqa: E402
from paladino.etl.unstructured_models import (  # noqa: E402
    ConnectionReport,
    DiscoveredPath,
    EntityMatch,
    ExtractedEntity,
    ExtractedRelationship,
    ImplicitConnection,
    NERResult,
)
from paladino.llm_manager import LLMManager  # noqa: E402


# ──────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """FastAPI test client with mocked API key."""
    with patch("paladino.app.security.verify_api_key", return_value="test-api-key"):
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMManager)
    llm.chat.return_value = "YES"
    return llm


@pytest.fixture
def resolver(mock_driver, mock_llm):
    """ConnectionResolver backed by the mock Neo4j driver from conftest."""
    from paladino.db import Neo4jConnection

    conn = MagicMock(spec=Neo4jConnection)
    session = mock_driver.session.return_value.__enter__.return_value
    conn.run_query = session.run
    return ConnectionResolver(db=conn, llm_manager=mock_llm, fuzzy_threshold=0.85)


# ──────────────────────────────────────────────────────────────
# 1. End-to-End Entity Resolution
# ──────────────────────────────────────────────────────────────


def _mock_cf_match(session, cf, neo4j_id, name):
    """Configure session.run to return a CF match."""
    def side_effect(query, parameters=None, **kwargs):
        params = parameters or {}
        params.update(kwargs)
        value = params.get("value", "")
        if value == cf:
            return MockResult([
                {"neo4j_id": neo4j_id, "properties": {"cf": cf, "nome_normalizzato": name}},
            ])
        return MockResult([])
    session.run.side_effect = side_effect


def test_resolve_entities_with_exact_cf_match(resolver, mock_driver):
    """Extracted entity with CF should match existing Company node."""
    session = mock_driver.session.return_value.__enter__.return_value
    _mock_cf_match(session, "MRARSS80A01H501Z", 42, "Rossi SRL")

    entities = [
        ExtractedEntity(
            id="ent_1",
            type="Company",
            properties={"name": "Rossi SRL", "cf": "MRARSS80A01H501Z"},
            confidence=0.95,
        ),
    ]
    ner_result = NERResult(entities=entities)
    report = resolver.resolve(ner_result, source="test_doc.pdf")

    assert report.entities_extracted == 1
    assert report.entities_matched == 1
    assert report.entity_matches[0].match_method == "exact_cf"
    assert report.entity_matches[0].confidence == 1.0


def test_resolve_entities_creates_new_when_no_match(resolver, mock_driver):
    """Extracted entity with no match should be marked for creation."""
    session = mock_driver.session.return_value.__enter__.return_value
    session.run.return_value = MockResult([])

    entities = [
        ExtractedEntity(
            id="ent_1",
            type="Company",
            properties={"name": "BrandNew Company SPA"},
            confidence=0.8,
        ),
    ]
    ner_result = NERResult(entities=entities)
    report = resolver.resolve(ner_result, source="test_doc.pdf")

    assert report.entities_extracted == 1
    assert report.entities_created == 1
    assert report.entities_matched == 0


def test_resolve_multiple_entities_mixed(resolver, mock_driver):
    """Some entities match, others are created new."""
    session = mock_driver.session.return_value.__enter__.return_value

    def side_effect(query, parameters=None, **kwargs):
        params = parameters or {}
        params.update(kwargs)
        value = params.get("value", "")

        if value == "MATCHED123":
            return MockResult([
                {"neo4j_id": 100, "properties": {"cf": "MATCHED123", "nome_normalizzato": "Known Co"}},
            ])
        return MockResult([])

    session.run.side_effect = side_effect

    entities = [
        ExtractedEntity(id="e1", type="Company", properties={"cf": "MATCHED123", "name": "Known Co"}, confidence=0.9),
        ExtractedEntity(id="e2", type="Person", properties={"name": "New Person"}, confidence=0.7),
    ]
    ner_result = NERResult(entities=entities)
    report = resolver.resolve(ner_result, source="mixed.pdf")

    assert report.entities_extracted == 2
    assert report.entities_matched == 1
    assert report.entities_created == 1


# ──────────────────────────────────────────────────────────────
# 2. Relationship Resolution
# ──────────────────────────────────────────────────────────────


def test_resolve_relationship_creates_edge(resolver, mock_driver):
    """Resolved relationship should create a Neo4j edge."""
    session = mock_driver.session.return_value.__enter__.return_value
    session.run.return_value = MockResult([{"count": 1}])

    # Pre-populate id_map (normally done by entity matching)
    resolver._id_map = {"company_1": "100", "tender_1": "200"}

    relationships = [
        ExtractedRelationship(source_id="company_1", target_id="tender_1", type="WINS", confidence=0.9),
    ]
    created = resolver._resolve_relationships(relationships, source="test.pdf")
    assert created == 1

    # Verify MERGE query was executed
    calls = session.run.call_args_list
    assert any("WINS" in str(call) for call in calls), "WINS relationship should be created"


def test_resolve_relationship_skips_missing_mapping(resolver):
    """Relationship with unmapped source/target should be skipped."""
    resolver._id_map = {"tender_1": "200"}  # company_1 not mapped

    relationships = [
        ExtractedRelationship(source_id="company_1", target_id="tender_1", type="WINS", confidence=0.9),
    ]
    created = resolver._resolve_relationships(relationships, source="test.pdf")
    assert created == 0


# ──────────────────────────────────────────────────────────────
# 3. Implicit Connection Discovery
# ──────────────────────────────────────────────────────────────


def test_discover_shared_shareholders(resolver, mock_driver):
    """Two matched companies should be flagged if they share a shareholder."""
    session = mock_driver.session.return_value.__enter__.return_value
    session.run.return_value = MockResult([
        {"name_a": "Rossi SRL", "name_b": "Bianchi SPA", "person_name": "Mario Verdi", "shared_count": 2},
    ])

    resolver._matches = [
        EntityMatch(
            extracted_entity_id="e1", extracted_entity_type="Company",
            matched_neo4j_id="100", matched_neo4j_label="Company",
            match_method="exact_cf", confidence=1.0,
        ),
        EntityMatch(
            extracted_entity_id="e2", extracted_entity_type="Company",
            matched_neo4j_id="200", matched_neo4j_label="Company",
            match_method="exact_cf", confidence=1.0,
        ),
    ]

    implicit = resolver._discover_implicit_connections("test.pdf")

    shareholder_conns = [c for c in implicit if c.discovery_type == "shared_shareholder"]
    assert len(shareholder_conns) >= 1
    assert "shareholder" in shareholder_conns[0].description.lower()


def test_discover_common_tender_winners(resolver, mock_driver):
    """Two companies that won the same tender should be flagged."""
    session = mock_driver.session.return_value.__enter__.return_value
    session.run.return_value = MockResult([
        {"name_a": "Rossi SRL", "name_b": "Bianchi SPA", "tender_cig": "Z99887766", "shared_tenders": 1},
    ])

    resolver._matches = [
        EntityMatch(
            extracted_entity_id="e1", extracted_entity_type="Company",
            matched_neo4j_id="100", matched_neo4j_label="Company",
            match_method="exact_cf", confidence=1.0,
        ),
        EntityMatch(
            extracted_entity_id="e2", extracted_entity_type="Company",
            matched_neo4j_id="200", matched_neo4j_label="Company",
            match_method="exact_cf", confidence=1.0,
        ),
    ]

    implicit = resolver._discover_implicit_connections("test.pdf")
    tender_conns = [c for c in implicit if c.discovery_type == "common_tender"]
    assert len(tender_conns) >= 1


def test_no_implicit_connections_with_single_company(resolver):
    """Single matched company → no implicit connections possible."""
    resolver._matches = [
        EntityMatch(
            extracted_entity_id="e1", extracted_entity_type="Company",
            matched_neo4j_id="100", matched_neo4j_label="Company",
            match_method="exact_cf", confidence=1.0,
        ),
    ]

    implicit = resolver._discover_implicit_connections("test.pdf")
    assert implicit == []


# ──────────────────────────────────────────────────────────────
# 4. API Endpoint Integration
# ──────────────────────────────────────────────────────────────


def _mock_connection_report():
    """Return a realistic ConnectionReport for API test mocking."""
    return ConnectionReport(
        source="test.txt",
        entities_extracted=2,
        entities_matched=1,
        entities_created=1,
        relationships_created=1,
        implicit_connections_found=0,
        entity_matches=[],
        discovered_paths=[],
        implicit_connections=[],
        warnings=[],
    )


def test_api_ingest_unstructured_with_connections(client, mock_driver, mock_llm):
    """POST /ingest/unstructured with resolve_connections=True."""
    mock_driver.session.return_value.__enter__.return_value.run.return_value = MockResult([])

    with (
        patch("paladino.etl.universal_ingestor.UniversalIngestor") as MockIngestor,
        patch("paladino.etl.ner_pipeline.UnstructuredNERPipeline") as MockNER,
        patch("paladino.llm_manager.LLMManager", return_value=mock_llm),
    ):
        mock_ingestor = MagicMock()
        mock_ingestor.route.return_value = MagicMock(
            route="unstructured", handler="text_extractor"
        )
        mock_ingestor.ingest.return_value = MagicMock(
            source="test.txt", source_type="text", content="Test content mentioning Rossi SRL"
        )
        mock_ingestor.ingest_with_connections.return_value = _mock_connection_report()
        MockIngestor.return_value = mock_ingestor

        mock_ner = MagicMock()
        mock_ner.extract.return_value = NERResult(
            entities=[
                ExtractedEntity(id="e1", type="Company", properties={"name": "Rossi SRL"}, confidence=0.9),
            ]
        )
        mock_ner.llm = mock_llm
        MockNER.return_value = mock_ner

        response = client.post(
            "/ingest/unstructured",
            json={
                "source": "test.txt",
                "resolve_connections": True,
                "max_chars": 12000,
                "chunk_overlap": 400,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entities_extracted"] == 2
        assert data["entities_matched"] == 1
        assert data["entities_created"] == 1
        assert "processing_time_seconds" in data


def test_api_ingest_unstructured_extract_only(client, mock_driver, mock_llm):
    """POST /ingest/unstructured with resolve_connections=False."""
    mock_driver.session.return_value.__enter__.return_value.run.return_value = MockResult([])

    with (
        patch("paladino.etl.universal_ingestor.UniversalIngestor") as MockIngestor,
        patch("paladino.etl.ner_pipeline.UnstructuredNERPipeline") as MockNER,
        patch("paladino.llm_manager.LLMManager", return_value=mock_llm),
    ):
        mock_ingestor = MagicMock()
        mock_ingestor.route.return_value = MagicMock(route="unstructured", handler="text_extractor")
        mock_ingestor.ingest.return_value = MagicMock(
            source="test.txt", source_type="text", content="Test content"
        )
        MockIngestor.return_value = mock_ingestor

        mock_ner = MagicMock()
        mock_ner.extract.return_value = NERResult(
            entities=[ExtractedEntity(id="e1", type="Company", properties={"name": "Test Co"}, confidence=0.8)]
        )
        mock_ner.llm = mock_llm
        MockNER.return_value = mock_ner

        response = client.post(
            "/ingest/unstructured",
            json={
                "source": "test.txt",
                "resolve_connections": False,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["entities_extracted"] == 1
        assert data["entities_matched"] == 0
        assert data["entities_created"] == 0


def test_api_ingest_unstructured_file_not_found(client, mock_driver):
    """POST /ingest/unstructured with non-existent file returns 404."""
    from paladino.etl.universal_ingestor import UniversalIngestor

    with patch.object(UniversalIngestor, "route", side_effect=FileNotFoundError("Source does not exist: no_such_file.pdf")):
        response = client.post(
            "/ingest/unstructured",
            json={"source": "no_such_file.pdf", "resolve_connections": True},
        )

        assert response.status_code == 404


def test_api_ingest_unstructured_structured_source(client, mock_driver):
    """POST /ingest/unstructured with known structured source returns 400."""
    from paladino.etl.universal_ingestor import UniversalIngestor

    with patch.object(UniversalIngestor, "route") as mock_route:
        mock_route.return_value = MagicMock(
            route="structured",
            handler="existing_anac_etl",
            next_command="scripts/run_anac_etl.py",
        )

        response = client.post(
            "/ingest/unstructured",
            json={"source": "data/anac/tenders.json", "resolve_connections": True},
        )

        assert response.status_code == 400
        assert "structured dataset" in response.json()["detail"].lower()


# ──────────────────────────────────────────────────────────────
# 5. ConnectionReport Model Validation
# ──────────────────────────────────────────────────────────────


def test_connection_report_serialization():
    """ConnectionReport should serialize to JSON for API responses."""
    report = ConnectionReport(
        source="test.pdf",
        entities_extracted=10,
        entities_matched=6,
        entities_created=4,
        relationships_created=8,
        implicit_connections_found=2,
        entity_matches=[
            EntityMatch(
                extracted_entity_id="e1",
                extracted_entity_type="Company",
                matched_neo4j_id="42",
                matched_neo4j_label="Company",
                match_method="exact_cf",
                confidence=1.0,
                matched_properties={"cf": "12345678901", "nome_normalizzato": "Test Co"},
            ),
        ],
        discovered_paths=[
            DiscoveredPath(
                from_entity="Test Co",
                to_entity="Other Co",
                path_length=2,
                via=["Tender X"],
                description="Connected via WINS, WINS",
            ),
        ],
        implicit_connections=[
            ImplicitConnection(
                entity_a="Test Co",
                entity_b="Other Co",
                discovery_type="shared_shareholder",
                confidence=0.65,
                description="Both share shareholder Mario Rossi",
            ),
        ],
        warnings=["Low confidence extraction on 2 entities"],
    )

    json_str = json.dumps(report.model_dump())
    data = json.loads(json_str)

    assert data["entities_extracted"] == 10
    assert data["entities_matched"] == 6
    assert len(data["entity_matches"]) == 1
    assert data["entity_matches"][0]["match_method"] == "exact_cf"
    assert len(data["discovered_paths"]) == 1
    assert len(data["implicit_connections"]) == 1
    assert len(data["warnings"]) == 1


# ──────────────────────────────────────────────────────────────
# 6. Full Pipeline Integration (mocked end-to-end)
# ──────────────────────────────────────────────────────────────


def test_full_pipeline_extract_and_resolve(resolver, mock_driver):
    """Full pipeline: extract entities, resolve, create relationships, discover implicit."""
    session = mock_driver.session.return_value.__enter__.return_value

    def side_effect(query, parameters=None, **kwargs):
        params = parameters or {}
        params.update(kwargs)
        value = params.get("value", "")
        lower = query.lower()

        # CF matches
        if value == "AAAAAA00A00A000A":
            return MockResult([
                {"neo4j_id": 100, "properties": {"cf": "AAAAAA00A00A000A", "nome_normalizzato": "Alpha SRL"}},
            ])
        if value == "BBBBBB00B00B000B":
            return MockResult([
                {"neo4j_id": 200, "properties": {"cf": "BBBBBB00B00B000B", "nome_normalizzato": "Beta SPA"}},
            ])
        # Shared shareholder discovery
        if "shareholder" in lower:
            return MockResult([
                {"name_a": "Alpha SRL", "name_b": "Beta SPA", "person_name": "Luigi Bianchi", "shared_count": 1},
            ])
        # Common tender
        if "tender" in lower and "wins" in lower:
            return MockResult([])
        # Geographic
        if "regione" in lower:
            return MockResult([])
        # Default
        return MockResult([])

    session.run.side_effect = side_effect

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
        ExtractedEntity(
            id="p1", type="Person",
            properties={"name": "Luigi Bianchi"},
            confidence=0.80,
        ),
    ]
    relationships = [
        ExtractedRelationship(source_id="c1", target_id="c2", type="PARTNERS_WITH", confidence=0.7),
        ExtractedRelationship(source_id="p1", target_id="c1", type="SHAREHOLDER_OF", confidence=0.85),
    ]

    ner_result = NERResult(entities=entities, relationships=relationships)
    report = resolver.resolve(ner_result, source="full_pipeline_test.pdf")

    # Assertions
    assert report.entities_extracted == 3
    assert report.entities_matched == 2  # Both companies matched by CF
    assert report.entities_created == 1  # Person created new
    assert report.relationships_resolved == 2
    assert report.implicit_connections_found >= 1  # Shared shareholder

    # Verify the shareholder connection
    shareholder = next(
        (c for c in report.implicit_connections if c.discovery_type == "shared_shareholder"),
        None,
    )
    assert shareholder is not None
    assert "Luigi Bianchi" in shareholder.description
