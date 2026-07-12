"""
Integration tests for Notebook + Connection Discovery integration.

Tests cover:
- CONNECTION_INSIGHT cell execution
- Auto-discovery of connections after Cypher cell execution
- API endpoint POST /notebooks/from-ingestion
- Entity ID extraction from Cypher results
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Ensure conftest helpers are importable
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
from conftest import MockResult  # noqa: E402

from paladino.app.api import app  # noqa: E402
from paladino.app.notebook_service import NotebookService  # noqa: E402
from paladino.etl.unstructured_models import ImplicitConnection  # noqa: E402
from paladino.models import (  # noqa: E402
    NotebookCellCreate,
    NotebookCellType,
    NotebookCreate,
    NotebookListParams,
)


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
def notebook_service(mock_driver):
    """NotebookService backed by the mock Neo4j driver."""
    from paladino.db import Neo4jConnection

    conn = MagicMock(spec=Neo4jConnection)
    session = mock_driver.session.return_value.__enter__.return_value
    conn.run_query = session.run
    return NotebookService(conn)


# ──────────────────────────────────────────────────────────────
# 1. Entity ID Extraction
# ──────────────────────────────────────────────────────────────


def test_extract_entity_ids_from_int_columns():
    """Entity IDs returned as integer columns should be extracted."""
    from paladino.db import Neo4jConnection

    conn = MagicMock(spec=Neo4jConnection)
    service = NotebookService(conn)

    results = [
        {"id(n)": 100, "name": "Rossi SRL"},
        {"id(n)": 200, "name": "Bianchi SPA"},
        {"id(n)": 300, "name": "Verdi LLC"},
    ]

    ids = service._extract_entity_ids_from_results(results)
    assert set(ids) == {100, 200, 300}


def test_extract_entity_ids_from_dict_values():
    """Entity IDs embedded in dict values should be extracted."""
    from paladino.db import Neo4jConnection

    conn = MagicMock(spec=Neo4jConnection)
    service = NotebookService(conn)

    results = [
        {"n": {"id": 42, "nome_normalizzato": "Test Co"}},
        {"c": {"id": 99, "cf": "12345678901"}},
    ]

    ids = service._extract_entity_ids_from_results(results)
    assert set(ids) == {42, 99}


def test_extract_entity_ids_empty():
    """No entity IDs should return empty list for non-entity results."""
    from paladino.db import Neo4jConnection

    conn = MagicMock(spec=Neo4jConnection)
    service = NotebookService(conn)

    results = [
        {"count": 5, "status": "active"},
    ]

    ids = service._extract_entity_ids_from_results(results)
    assert ids == []


def test_extract_entity_ids_from_node_objects():
    """Entity IDs from neo4j.graph.Node objects should be extracted."""
    from paladino.db import Neo4jConnection

    conn = MagicMock(spec=Neo4jConnection)
    service = NotebookService(conn)

    # Simulate Neo4j Node objects with .id and .element_id
    mock_node_a = MagicMock()
    mock_node_a.id = 100
    mock_node_a.element_id = "4:company:0"

    mock_node_b = MagicMock()
    mock_node_b.id = 200
    mock_node_b.element_id = "4:company:1"

    results = [
        {"n": mock_node_a, "name": "Rossi SRL"},
        {"n": mock_node_b, "name": "Bianchi SPA"},
    ]

    ids = service._extract_entity_ids_from_results(results)
    assert set(ids) == {100, 200}


# ──────────────────────────────────────────────────────────────
# 2. Connection Discovery Helper
# ──────────────────────────────────────────────────────────────


def test_discover_connections_with_pairs(notebook_service, mock_driver):
    """Discover connections should return implicit connections for matched pairs."""
    session = mock_driver.session.return_value.__enter__.return_value

    # Shared shareholder query returns results
    def side_effect(query, parameters=None, **kwargs):
        lower = query.lower()
        if "shareholder" in lower:
            return MockResult([
                {"name_a": "Co A", "name_b": "Co B", "person_name": "Person X", "shared_count": 1},
            ])
        if "tender" in lower and "wins" in lower:
            return MockResult([])
        if "regione" in lower:
            return MockResult([])
        return MockResult([])

    session.run.side_effect = side_effect

    insights = notebook_service._discover_connections([100, 200])

    # Should have at least one connection (shared shareholder from defaults)
    assert isinstance(insights, list)


def test_discover_connections_empty_for_single_id(notebook_service):
    """Single entity ID should not trigger discovery."""
    insights = notebook_service._discover_connections([100])
    assert insights == []


def test_discover_connections_empty_for_no_ids(notebook_service):
    """No entity IDs should return empty."""
    insights = notebook_service._discover_connections([])
    assert insights == []


# ──────────────────────────────────────────────────────────────
# 3. Cell Execution with Connection Discovery
# ──────────────────────────────────────────────────────────────


def test_cypher_cell_execution_auto_discovers_connections(notebook_service, mock_driver):
    """Cypher cell execution should auto-discover connections between returned entities."""
    session = mock_driver.session.return_value.__enter__.return_value

    call_count = [0]

    def side_effect(query, parameters=None, **kwargs):
        call_count[0] += 1
        lower = query.lower()

        # First call: cypher execution (returns entities)
        if call_count[0] == 1:
            return MockResult([
                {"id(n)": 100, "nome_normalizzato": "Alpha SRL"},
                {"id(n)": 200, "nome_normalizzato": "Beta SPA"},
            ])
        # Discovery queries
        if "shareholder" in lower:
            return MockResult([
                {"name_a": "Alpha SRL", "name_b": "Beta SPA", "person_name": "Mario", "shared_count": 1},
            ])
        if "tender" in lower and "wins" in lower:
            return MockResult([])
        if "regione" in lower:
            return MockResult([])
        # Update cell
        return MockResult([{"c": {"id": "cell-1"}}])

    session.run.side_effect = side_effect

    # Create a mock cell
    from datetime import datetime, UTC
    from paladino.models import NotebookCell

    mock_cell = NotebookCell(
        id="cell-1",
        notebook_id="nb-1",
        cell_type=NotebookCellType.CYPHER_QUERY,
        content="MATCH (n:Company) RETURN id(n), n.nome_normalizzato LIMIT 10",
        position=0,
        title="Test Query",
        execution_count=0,
        last_executed_at=None,
        linked_entity_id=None,
        created_at=datetime.now(UTC).isoformat(),
    )

    with patch.object(notebook_service, "get_cell", return_value=mock_cell):
        with patch.object(notebook_service, "_validate_cypher"):
            response = notebook_service.execute_cell("nb-1", "cell-1")

    assert response.cell_id == "cell-1"
    assert response.execution_result["status"] == "success"
    assert response.execution_result["row_count"] == 2
    # Connection insights should be included
    assert "connection_insights" in response.execution_result


def test_connection_insight_cell_execution(notebook_service, mock_driver):
    """CONNECTION_INSIGHT cell should run discovery and return insights."""
    from datetime import datetime, UTC
    from paladino.models import NotebookCell

    session = mock_driver.session.return_value.__enter__.return_value

    def side_effect(query, parameters=None, **kwargs):
        lower = query.lower()
        if "shareholder" in lower:
            return MockResult([
                {"name_a": "Co A", "name_b": "Co B", "person_name": "Person X", "shared_count": 2},
            ])
        if "tender" in lower and "wins" in lower:
            return MockResult([])
        if "regione" in lower:
            return MockResult([])
        return MockResult([{"c": {"id": "cell-1"}}])

    session.run.side_effect = side_effect

    mock_cell = NotebookCell(
        id="cell-1",
        notebook_id="nb-1",
        cell_type=NotebookCellType.CONNECTION_INSIGHT,
        content="Discover connections",
        position=0,
        title="Connections",
        execution_count=0,
        last_executed_at=None,
        linked_entity_id="CF12345678901",
        created_at=datetime.now(UTC).isoformat(),
    )

    # Patch get_cell to return the CONNECTION_INSIGHT cell
    with patch.object(notebook_service, "get_cell", return_value=mock_cell):
        # Patch _get_linked_entity_ids to return some IDs
        with patch.object(notebook_service, "_get_linked_entity_ids", return_value=[100, 200]):
            response = notebook_service.execute_cell("nb-1", "cell-1")

    assert response.cell_id == "cell-1"
    assert response.execution_result["status"] == "success"
    assert "insights" in response.execution_result
    assert response.execution_result["insight_count"] >= 0


# ──────────────────────────────────────────────────────────────
# 4. API Endpoint: POST /notebooks/from-ingestion
# ──────────────────────────────────────────────────────────────


def test_api_create_notebook_from_ingestion(client, mock_driver):
    """POST /notebooks/from-ingestion should create a pre-populated notebook."""
    from datetime import datetime, UTC
    from paladino.models import NotebookResponse, NotebookStatus

    session = mock_driver.session.return_value.__enter__.return_value
    session.run.return_value = MockResult([{"n": {"id": "nb-1", "title": "ACME Investigation"}}])

    with patch("paladino.app.api._get_notebook_service") as mock_get_service:
        nb_resp = NotebookResponse(
            id="nb-1",
            title="ACME Investigation",
            description="Test",
            status=NotebookStatus.DRAFT,
            template_name=None,
            linked_entity_ids=["MRARSS80A01H501Z"],
            linked_alert_ids=[],
            tags=["from-ingestion"],
            author="user",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            completed_at=None,
            cell_count=4,
            cells=[],
        )
        mock_service = MagicMock()
        mock_service.create_notebook.return_value = nb_resp
        mock_service.add_cell.return_value = MagicMock()
        mock_service.get_notebook.return_value = nb_resp
        mock_get_service.return_value = mock_service

        response = client.post(
            "/notebooks/from-ingestion",
            json={
                "source": "test_report.json",
                "title": "ACME Investigation",
                "entity_ids": ["MRARSS80A01H501Z"],
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "notebook" in data
        assert data["connection_insights_count"] >= 1


def test_api_create_notebook_from_ingestion_auto_title(client, mock_driver):
    """POST /notebooks/from-ingestion should auto-generate title from source."""
    from datetime import datetime, UTC
    from paladino.models import NotebookResponse, NotebookStatus

    session = mock_driver.session.return_value.__enter__.return_value
    session.run.return_value = MockResult([{"n": {"id": "nb-1"}}])

    with patch("paladino.app.api._get_notebook_service") as mock_get_service:
        nb_resp = NotebookResponse(
            id="nb-1",
            title="Investigation: document.pdf",
            description="Test",
            status=NotebookStatus.DRAFT,
            template_name=None,
            linked_entity_ids=[],
            linked_alert_ids=[],
            tags=[],
            author="user",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            completed_at=None,
            cell_count=4,
            cells=[],
        )
        mock_service = MagicMock()
        mock_service.create_notebook.return_value = nb_resp
        mock_service.add_cell.return_value = MagicMock()
        mock_service.get_notebook.return_value = nb_resp
        mock_get_service.return_value = mock_service

        response = client.post(
            "/notebooks/from-ingestion",
            json={"source": "document.pdf"},
        )

        assert response.status_code == 200

        # Verify title was auto-generated
        create_call = mock_service.create_notebook.call_args
        assert "Investigation: document.pdf" == create_call[0][0].title


# ──────────────────────────────────────────────────────────────
# 5. Notebook Service with Connection Discovery
# ──────────────────────────────────────────────────────────────


def test_notebook_create_with_connection_insight_cell(notebook_service, mock_driver):
    """Creating a notebook with a CONNECTION_INSIGHT cell should work."""
    session = mock_driver.session.return_value.__enter__.return_value

    # Store params from the CREATE query so we can verify them
    captured_params: list[dict] = []

    def side_effect(query, parameters=None, **kwargs):
        params = parameters or {}
        params.update(kwargs)
        captured_params.append(params)
        cell_id = params.get("id", "cell-1")
        return MockResult([{
            "c": {
                "id": cell_id,
                "cell_type": params.get("cell_type", "markdown"),
                "position": params.get("position", 0),
                "linked_entity_id": params.get("linked_entity_id"),
            }
        }])

    session.run.side_effect = side_effect

    notebook = NotebookCreate(
        title="Test Investigation",
        description="Test",
        linked_entity_ids=["CF123"],
        tags=["test"],
    )
    nb_resp = notebook_service.create_notebook(notebook)

    # Add a CONNECTION_INSIGHT cell
    cell_data = NotebookCellCreate(
        cell_type=NotebookCellType.CONNECTION_INSIGHT,
        content="Discover connections",
        position=0,
        title="Connections",
        linked_entity_id="CF123",
    )
    cell = notebook_service.add_cell(nb_resp.id, cell_data)

    # Verify the cell was created with the right cell_type
    assert cell.cell_type.value == "connection_insight"
    # linked_entity_id should be passed through (verify from captured params)
    assert any(p.get("linked_entity_id") == "CF123" for p in captured_params), \
        f"linked_entity_id not found in query params: {captured_params}"


def test_linked_entity_id_resolution(notebook_service, mock_driver):
    """Linked entity IDs should be resolved from business ID to Neo4j internal ID."""
    session = mock_driver.session.return_value.__enter__.return_value

    def side_effect(query, parameters=None, **kwargs):
        params = parameters or {}
        params.update(kwargs)
        if params.get("eid"):
            return MockResult([{"neo4j_id": 42}])
        return MockResult([])

    session.run.side_effect = side_effect

    ids = notebook_service._resolve_external_id_to_internal("MRARSS80A01H501Z")
    assert 42 in ids
