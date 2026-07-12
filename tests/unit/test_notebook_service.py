"""
Unit tests for Investigation Notebook Service.

Tests cover:
- Notebook CRUD operations (create, get, list, update, delete, duplicate)
- Cell operations (add, update, delete, reorder, get)
- Cell execution (Cypher, markdown, error handling, execute all)
- Templates (create from template, list, validation)
- Export (JSON, Markdown, HTML, invalid format)
- Model validation (enums, create/update models, list params)
- Security (Cypher validation rejects write operations)
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from paladino.app.notebook_service import (
    NotebookService,
    INVESTIGATION_TEMPLATES,
    _WRITE_CYPHER_KEYWORDS,
)
from paladino.models import (
    Notebook,
    NotebookCell,
    NotebookCellCreate,
    NotebookCellExecuteResponse,
    NotebookCellType,
    NotebookCellUpdate,
    NotebookChangeHistoryResponse,
    NotebookCreate,
    NotebookExecuteAllResponse,
    NotebookExportFormat,
    NotebookListParams,
    NotebookResponse,
    NotebookStatus,
    NotebookUpdate,
)
from paladino.db import Neo4jConnection


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_conn():
    """Create a mock Neo4jConnection."""
    conn = MagicMock(spec=Neo4jConnection)
    return conn


@pytest.fixture
def notebook_service(mock_conn):
    """Create a NotebookService with mocked connection."""
    return NotebookService(mock_conn)


@pytest.fixture
def sample_notebook_create():
    """Sample notebook creation data."""
    return NotebookCreate(
        title="Test Investigation",
        description="Test investigation notebook",
        linked_entity_ids=["company-uuid-123"],
        linked_alert_ids=["alert-uuid-456"],
        tags=["test", "investigation"],
        author="analyst",
    )


@pytest.fixture
def sample_notebook_record():
    """Sample Neo4j record for a notebook."""
    return {
        "n": {
            "id": "nb-uuid-123",
            "title": "Test Investigation",
            "description": "Test investigation notebook",
            "status": "draft",
            "template_name": None,
            "linked_entity_ids": ["company-uuid-123"],
            "linked_alert_ids": ["alert-uuid-456"],
            "tags": ["test", "investigation"],
            "cell_count": 0,
            "author": "analyst",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
        }
    }


@pytest.fixture
def sample_cell_record():
    """Sample Neo4j record for a cell."""
    return {
        "c": {
            "id": "cell-uuid-123",
            "notebook_id": "nb-uuid-123",
            "cell_type": "cypher_query",
            "content": "MATCH (c:Company) RETURN c LIMIT 10",
            "position": 0,
            "title": "Company List",
            "execution_result": None,
            "execution_count": 0,
            "last_executed_at": None,
            "linked_entity_id": None,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": None,
        }
    }


@pytest.fixture
def sample_cell_create():
    """Sample cell creation data."""
    return NotebookCellCreate(
        cell_type=NotebookCellType.CYPHER_QUERY,
        content="MATCH (c:Company) RETURN c LIMIT 10",
        position=0,
        title="Company List",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Notebook CRUD Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateNotebook:
    """Tests for create_notebook method."""

    def test_create_notebook_success(self, notebook_service, mock_conn, sample_notebook_create, sample_notebook_record):
        """Test successful notebook creation."""
        mock_conn.run_query.return_value = [sample_notebook_record]

        notebook = notebook_service.create_notebook(sample_notebook_create)

        assert notebook.id == "nb-uuid-123"
        assert notebook.title == "Test Investigation"
        assert notebook.status == NotebookStatus.DRAFT
        assert notebook.cell_count == 0
        assert notebook.author == "analyst"
        assert notebook.linked_entity_ids == ["company-uuid-123"]
        assert notebook.tags == ["test", "investigation"]

    def test_create_notebook_minimal(self, notebook_service, mock_conn):
        """Test creating notebook with minimal data."""
        record = {
            "n": {
                "id": "nb-uuid-min",
                "title": "Minimal",
                "description": "",
                "status": "draft",
                "template_name": None,
                "linked_entity_ids": [],
                "linked_alert_ids": [],
                "tags": [],
                "cell_count": 0,
                "author": "user",
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": None,
                "completed_at": None,
            }
        }
        mock_conn.run_query.return_value = [record]

        notebook = notebook_service.create_notebook(NotebookCreate(title="Minimal"))

        assert notebook.title == "Minimal"
        assert notebook.author == "user"
        assert notebook.description == ""


class TestGetNotebook:
    """Tests for get_notebook method."""

    def test_get_notebook_with_cells(self, notebook_service, mock_conn, sample_notebook_record, sample_cell_record):
        """Test getting notebook with its cells."""
        mock_conn.run_query.side_effect = [
            [sample_notebook_record],
            [sample_cell_record],
        ]

        notebook = notebook_service.get_notebook("nb-uuid-123")

        assert notebook is not None
        assert notebook.id == "nb-uuid-123"
        assert len(notebook.cells) == 1
        assert notebook.cells[0].cell_type == NotebookCellType.CYPHER_QUERY

    def test_get_notebook_not_found(self, notebook_service, mock_conn):
        """Test getting non-existent notebook."""
        mock_conn.run_query.return_value = []

        notebook = notebook_service.get_notebook("nonexistent")

        assert notebook is None

    def test_get_notebook_archived_excluded(self, notebook_service, mock_conn):
        """Test that archived notebooks are not returned."""
        mock_conn.run_query.return_value = []

        notebook = notebook_service.get_notebook("archived-nb")
        assert notebook is None


class TestListNotebooks:
    """Tests for list_notebooks method."""

    def test_list_notebooks_no_filters(self, notebook_service, mock_conn, sample_notebook_record):
        """Test listing notebooks without filters."""
        mock_conn.run_query.side_effect = [
            [{"total": 1}],
            [sample_notebook_record],
        ]

        params = NotebookListParams()
        notebooks, total = notebook_service.list_notebooks(params)

        assert total == 1
        assert len(notebooks) == 1
        assert notebooks[0].id == "nb-uuid-123"

    def test_list_notebooks_with_status_filter(self, notebook_service, mock_conn):
        """Test listing notebooks filtered by status."""
        mock_conn.run_query.side_effect = [
            [{"total": 0}],
            [],
        ]

        params = NotebookListParams(status=NotebookStatus.ACTIVE)
        notebooks, total = notebook_service.list_notebooks(params)

        assert total == 0
        assert notebooks == []

    def test_list_notebooks_with_tag_filter(self, notebook_service, mock_conn):
        """Test listing notebooks filtered by tag."""
        mock_conn.run_query.side_effect = [
            [{"total": 2}],
            [{"n": {"id": "nb-1"}}, {"n": {"id": "nb-2"}}],
        ]

        params = NotebookListParams(tag="fraud")
        notebooks, total = notebook_service.list_notebooks(params)

        assert total == 2
        assert len(notebooks) == 2

    def test_list_notebooks_with_entity_filter(self, notebook_service, mock_conn):
        """Test listing notebooks filtered by entity ID."""
        mock_conn.run_query.side_effect = [
            [{"total": 1}],
            [{"n": {"id": "nb-1"}}],
        ]

        params = NotebookListParams(entity_id="company-uuid-123")
        notebooks, total = notebook_service.list_notebooks(params)

        assert total == 1


class TestUpdateNotebook:
    """Tests for update_notebook method."""

    def test_update_notebook_title(self, notebook_service, mock_conn, sample_notebook_record):
        """Test updating notebook title."""
        # Create updated record with new title
        updated_record = {
            "n": {
                **sample_notebook_record["n"],
                "title": "Updated Title",
                "updated_at": datetime.now(UTC).isoformat(),
            }
        }

        # Simplified: mock get_notebook to return a valid response
        with patch.object(notebook_service, 'get_notebook') as mock_get:
            mock_get.return_value = NotebookResponse(
                id="nb-uuid-123",
                title="Test Investigation",
                description="Test",
                status=NotebookStatus.DRAFT,
                template_name=None,
                linked_entity_ids=[],
                linked_alert_ids=[],
                tags=[],
                cell_count=0,
                cells=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                completed_at=None,
                author="user",
            )

            mock_conn.run_query.return_value = [updated_record]

            update = NotebookUpdate(title="Updated Title")
            result = notebook_service.update_notebook("nb-uuid-123", update)

            assert result is not None
            assert result.title == "Updated Title"

    def test_update_notebook_not_found(self, notebook_service, mock_conn):
        """Test updating non-existent notebook."""
        with patch.object(notebook_service, 'get_notebook', return_value=None):
            update = NotebookUpdate(title="New Title")
            result = notebook_service.update_notebook("nonexistent", update)
            assert result is None

    def test_update_notebook_status_to_completed(self, notebook_service, mock_conn):
        """Test updating status to completed sets completed_at."""
        with patch.object(notebook_service, 'get_notebook') as mock_get:
            mock_get.return_value = NotebookResponse(
                id="nb-uuid-123",
                title="Test",
                description="Test",
                status=NotebookStatus.ACTIVE,
                template_name=None,
                linked_entity_ids=[],
                linked_alert_ids=[],
                tags=[],
                cell_count=0,
                cells=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                completed_at=None,
                author="user",
            )

            mock_conn.run_query.return_value = [{
                "n": {
                    "id": "nb-uuid-123",
                    "title": "Test",
                    "description": "Test",
                    "status": "completed",
                    "template_name": None,
                    "linked_entity_ids": [],
                    "linked_alert_ids": [],
                    "tags": [],
                    "cell_count": 0,
                    "author": "user",
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            }]

            update = NotebookUpdate(status=NotebookStatus.COMPLETED)
            result = notebook_service.update_notebook("nb-uuid-123", update)

            assert result is not None
            assert result.status == NotebookStatus.COMPLETED


class TestDeleteNotebook:
    """Tests for delete_notebook method (soft delete)."""

    def test_delete_notebook_success(self, notebook_service, mock_conn):
        """Test soft deleting a notebook."""
        mock_conn.run_query.return_value = [{"n": {"id": "nb-uuid-123"}}]

        result = notebook_service.delete_notebook("nb-uuid-123")

        assert result is True

    def test_delete_notebook_not_found(self, notebook_service, mock_conn):
        """Test soft deleting non-existent notebook."""
        mock_conn.run_query.return_value = []

        result = notebook_service.delete_notebook("nonexistent")

        assert result is False


class TestDuplicateNotebook:
    """Tests for duplicate_notebook method."""

    def test_duplicate_notebook_success(self, notebook_service, mock_conn):
        """Test duplicating a notebook."""
        source_notebook = NotebookResponse(
            id="nb-uuid-source",
            title="Source",
            description="Source notebook",
            status=NotebookStatus.ACTIVE,
            template_name=None,
            linked_entity_ids=["entity-1"],
            linked_alert_ids=[],
            tags=["test"],
            cell_count=1,
            cells=[
                NotebookCell(
                    id="cell-1",
                    notebook_id="nb-uuid-source",
                    cell_type=NotebookCellType.MARKDOWN,
                    content="# Test",
                    position=0,
                    title="Intro",
                    execution_result=None,
                    execution_count=0,
                    last_executed_at=None,
                    linked_entity_id=None,
                    created_at=datetime.now(UTC),
                    updated_at=None,
                )
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=None,
            author="user",
        )

        with patch.object(notebook_service, 'get_notebook') as mock_get, \
             patch.object(notebook_service, 'create_notebook') as mock_create, \
             patch.object(notebook_service, 'add_cell') as mock_add:

            mock_get.side_effect = [source_notebook, None]  # First call returns source, second returns None (will be handled)
            mock_create.return_value = NotebookResponse(
                id="nb-uuid-dup",
                title="Copy of Source",
                description="Source notebook",
                status=NotebookStatus.DRAFT,
                template_name=None,
                linked_entity_ids=["entity-1"],
                linked_alert_ids=[],
                tags=["test"],
                cell_count=0,
                cells=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                completed_at=None,
                author="user",
            )

            # First call: get source, second call: get duplicate
            mock_get.side_effect = [source_notebook, NotebookResponse(
                id="nb-uuid-dup",
                title="Copy of Source",
                description="Source notebook",
                status=NotebookStatus.DRAFT,
                template_name=None,
                linked_entity_ids=["entity-1"],
                linked_alert_ids=[],
                tags=["test"],
                cell_count=1,
                cells=[
                    NotebookCell(
                        id="cell-dup-1",
                        notebook_id="nb-uuid-dup",
                        cell_type=NotebookCellType.MARKDOWN,
                        content="# Test",
                        position=0,
                        title="Intro",
                        execution_result=None,
                        execution_count=0,
                        last_executed_at=None,
                        linked_entity_id=None,
                        created_at=datetime.now(UTC),
                        updated_at=None,
                    )
                ],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                completed_at=None,
                author="user",
            )]

            result = notebook_service.duplicate_notebook("nb-uuid-source")

            assert result is not None
            assert result.title == "Copy of Source"
            mock_create.assert_called_once()
            mock_add.assert_called_once()

    def test_duplicate_notebook_not_found(self, notebook_service, mock_conn):
        """Test duplicating non-existent notebook."""
        with patch.object(notebook_service, 'get_notebook', return_value=None):
            with pytest.raises(ValueError, match="not found"):
                notebook_service.duplicate_notebook("nonexistent")


# ─────────────────────────────────────────────────────────────────────────────
# Cell Operations Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAddCell:
    """Tests for add_cell method."""

    def test_add_cell_at_position(self, notebook_service, mock_conn, sample_cell_create, sample_cell_record):
        """Test adding cell at specific position."""
        mock_conn.run_query.side_effect = [
            [{"n": {"id": "nb-uuid-123"}}],  # notebook exists
            [sample_cell_record],  # create cell
        ]

        cell = notebook_service.add_cell("nb-uuid-123", sample_cell_create)

        assert cell.id == "cell-uuid-123"
        assert cell.position == 0
        assert cell.cell_type == NotebookCellType.CYPHER_QUERY

    def test_add_cell_auto_append(self, notebook_service, mock_conn, sample_cell_create, sample_cell_record):
        """Test adding cell at end (auto-position)."""
        cell_data = NotebookCellCreate(
            cell_type=NotebookCellType.MARKDOWN,
            content="# New Cell",
        )

        mock_conn.run_query.side_effect = [
            [{"n": {"id": "nb-uuid-123"}}],  # notebook exists
            [{"max_pos": 2}],  # max position
            [sample_cell_record],  # create cell
        ]

        cell = notebook_service.add_cell("nb-uuid-123", cell_data)

        assert cell is not None

    def test_add_cell_notebook_not_found(self, notebook_service, mock_conn, sample_cell_create):
        """Test adding cell to non-existent notebook."""
        mock_conn.run_query.return_value = []

        with pytest.raises(ValueError, match="not found"):
            notebook_service.add_cell("nonexistent", sample_cell_create)


class TestUpdateCell:
    """Tests for update_cell method."""

    def test_update_cell_content(self, notebook_service, mock_conn, sample_cell_record):
        """Test updating cell content."""
        updated_record = dict(sample_cell_record)
        updated_record["c"] = dict(sample_cell_record["c"])
        updated_record["c"]["content"] = "Updated content"
        updated_record["c"]["updated_at"] = datetime.now(UTC).isoformat()

        mock_conn.run_query.side_effect = [
            [sample_cell_record],  # get cell
            [updated_record],  # update
        ]

        update = NotebookCellUpdate(content="Updated content")
        result = notebook_service.update_cell("nb-uuid-123", "cell-uuid-123", update)

        assert result is not None

    def test_update_cell_not_found(self, notebook_service, mock_conn):
        """Test updating non-existent cell."""
        mock_conn.run_query.return_value = []

        update = NotebookCellUpdate(content="New content")
        result = notebook_service.update_cell("nb-uuid-123", "nonexistent", update)

        assert result is None


class TestDeleteCell:
    """Tests for delete_cell method."""

    def test_delete_cell_success(self, notebook_service, mock_conn, sample_cell_record):
        """Test deleting a cell."""
        mock_conn.run_query.side_effect = [
            [sample_cell_record],  # get cell
            [{"deleted": 1}],  # delete
        ]

        result = notebook_service.delete_cell("nb-uuid-123", "cell-uuid-123")

        assert result is True

    def test_delete_cell_not_found(self, notebook_service, mock_conn):
        """Test deleting non-existent cell."""
        mock_conn.run_query.return_value = []

        result = notebook_service.delete_cell("nb-uuid-123", "nonexistent")

        assert result is False


class TestReorderCells:
    """Tests for reorder_cells method."""

    def test_reorder_cells_success(self, notebook_service, mock_conn):
        """Test reordering cells."""
        positions = [
            {"cell_id": "cell-1", "position": 2},
            {"cell_id": "cell-2", "position": 0},
        ]

        mock_conn.run_query.side_effect = [
            [{"matched": 2}],  # verify cells
            [{"updated": 2}],  # update positions
        ]

        result = notebook_service.reorder_cells("nb-uuid-123", positions)

        assert result is True

    def test_reorder_cells_empty_list(self, notebook_service, mock_conn):
        """Test reordering with empty list."""
        result = notebook_service.reorder_cells("nb-uuid-123", [])

        assert result is False

    def test_reorder_cells_cell_not_in_notebook(self, notebook_service, mock_conn):
        """Test reordering when cell doesn't belong to notebook."""
        positions = [{"cell_id": "cell-1", "position": 0}]

        mock_conn.run_query.return_value = [{"matched": 0}]

        result = notebook_service.reorder_cells("nb-uuid-123", positions)

        assert result is False


class TestGetCell:
    """Tests for get_cell method."""

    def test_get_cell_success(self, notebook_service, mock_conn, sample_cell_record):
        """Test getting a cell."""
        mock_conn.run_query.return_value = [sample_cell_record]

        cell = notebook_service.get_cell("nb-uuid-123", "cell-uuid-123")

        assert cell is not None
        assert cell.id == "cell-uuid-123"
        assert cell.notebook_id == "nb-uuid-123"

    def test_get_cell_not_found(self, notebook_service, mock_conn):
        """Test getting non-existent cell."""
        mock_conn.run_query.return_value = []

        cell = notebook_service.get_cell("nb-uuid-123", "nonexistent")

        assert cell is None


# ─────────────────────────────────────────────────────────────────────────────
# Cell Execution Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteCell:
    """Tests for execute_cell method."""

    def test_execute_cypher_cell_success(self, notebook_service, mock_conn, sample_cell_record):
        """Test executing a Cypher query cell."""
        cell_record = dict(sample_cell_record)
        cell_record["c"] = dict(sample_cell_record["c"])
        cell_record["c"]["cell_type"] = "cypher_query"

        mock_conn.run_query.side_effect = [
            [cell_record],  # get cell
            [{"name": "ACME SRL", "cf": "12345678901"}],  # execute cypher
            [cell_record],  # update execution result
        ]

        result = notebook_service.execute_cell("nb-uuid-123", "cell-uuid-123")

        assert result.error is None
        assert result.execution_count == 1
        assert result.execution_result is not None

    def test_execute_markdown_cell_success(self, notebook_service, mock_conn, sample_cell_record):
        """Test executing a markdown cell."""
        cell_record = dict(sample_cell_record)
        cell_record["c"] = dict(sample_cell_record["c"])
        cell_record["c"]["cell_type"] = "markdown"
        cell_record["c"]["content"] = "# Hello **World**"

        mock_conn.run_query.side_effect = [
            [cell_record],  # get cell
            [cell_record],  # update execution result
        ]

        result = notebook_service.execute_cell("nb-uuid-123", "cell-uuid-123")

        assert result.error is None
        assert result.execution_count == 1

    def test_execute_cell_not_found(self, notebook_service, mock_conn):
        """Test executing non-existent cell."""
        mock_conn.run_query.return_value = []

        result = notebook_service.execute_cell("nb-uuid-123", "nonexistent")

        assert result.error == "Cell not found"

    def test_execute_cell_cypher_validation_error(self, notebook_service, mock_conn, sample_cell_record):
        """Test executing cell with invalid Cypher (write operation)."""
        cell_record = dict(sample_cell_record)
        cell_record["c"] = dict(sample_cell_record["c"])
        cell_record["c"]["cell_type"] = "cypher_query"
        cell_record["c"]["content"] = "CREATE (n:Test) RETURN n"

        mock_conn.run_query.side_effect = [
            [cell_record],  # get cell
            [cell_record],  # update with error
        ]

        result = notebook_service.execute_cell("nb-uuid-123", "cell-uuid-123")

        assert result.error is not None
        assert "Security" in result.error or "write operation" in result.error.lower()

    def test_execute_all_cells(self, notebook_service, mock_conn):
        """Test executing all cells in a notebook."""
        notebook = NotebookResponse(
            id="nb-uuid-123",
            title="Test",
            description="Test",
            status=NotebookStatus.DRAFT,
            template_name=None,
            linked_entity_ids=[],
            linked_alert_ids=[],
            tags=[],
            cell_count=2,
            cells=[
                NotebookCell(
                    id="cell-1",
                    notebook_id="nb-uuid-123",
                    cell_type=NotebookCellType.MARKDOWN,
                    content="# Test",
                    position=0,
                    title=None,
                    execution_result=None,
                    execution_count=0,
                    last_executed_at=None,
                    linked_entity_id=None,
                    created_at=datetime.now(UTC),
                    updated_at=None,
                ),
                NotebookCell(
                    id="cell-2",
                    notebook_id="nb-uuid-123",
                    cell_type=NotebookCellType.CYPHER_QUERY,
                    content="MATCH (c:Company) RETURN c LIMIT 5",
                    position=1,
                    title=None,
                    execution_result=None,
                    execution_count=0,
                    last_executed_at=None,
                    linked_entity_id=None,
                    created_at=datetime.now(UTC),
                    updated_at=None,
                ),
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=None,
            author="user",
        )

        with patch.object(notebook_service, 'get_notebook', return_value=notebook):
            with patch.object(notebook_service, 'execute_cell') as mock_exec:
                mock_exec.side_effect = [
                    NotebookCellExecuteResponse(
                        cell_id="cell-1",
                        cell_type=NotebookCellType.MARKDOWN,
                        execution_count=1,
                        execution_result={"status": "success"},
                        last_executed_at=datetime.now(UTC),
                    ),
                    NotebookCellExecuteResponse(
                        cell_id="cell-2",
                        cell_type=NotebookCellType.CYPHER_QUERY,
                        execution_count=1,
                        execution_result={"status": "success", "row_count": 5},
                        last_executed_at=datetime.now(UTC),
                    ),
                ]

                result = notebook_service.execute_all_cells("nb-uuid-123")

                assert result.total_cells == 2
                assert result.executed_count == 2
                assert result.failed_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Template Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplates:
    """Tests for template operations."""

    def test_list_templates(self, notebook_service, mock_conn):
        """Test listing templates."""
        templates = notebook_service.list_templates()

        assert len(templates) == 5
        assert templates[0]["name"] == "Company Due Diligence"
        assert templates[4]["name"] == "Blank Investigation"

    def test_create_from_template_success(self, notebook_service, mock_conn):
        """Test creating notebook from template."""
        notebook_record = {
            "n": {
                "id": "nb-from-template",
                "title": "Company Due Diligence",
                "description": "Standard template",
                "status": "draft",
                "template_name": "Company Due Diligence",
                "linked_entity_ids": [],
                "linked_alert_ids": [],
                "tags": [],
                "cell_count": 0,
                "author": "user",
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
                "completed_at": None,
            }
        }

        with patch.object(notebook_service, 'create_notebook') as mock_create, \
             patch.object(notebook_service, 'add_cell') as mock_add, \
             patch.object(notebook_service, 'get_notebook') as mock_get:

            mock_create.return_value = NotebookResponse(
                id="nb-from-template",
                title="Company Due Diligence",
                description="Standard template",
                status=NotebookStatus.DRAFT,
                template_name="Company Due Diligence",
                linked_entity_ids=[],
                linked_alert_ids=[],
                tags=[],
                cell_count=0,
                cells=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                completed_at=None,
                author="user",
            )
            mock_add.return_value = NotebookCell(
                id="cell-tpl-1",
                notebook_id="nb-from-template",
                cell_type=NotebookCellType.MARKDOWN,
                content="## Company Overview",
                position=0,
                title="Introduction",
                execution_result=None,
                execution_count=0,
                last_executed_at=None,
                linked_entity_id=None,
                created_at=datetime.now(UTC),
                updated_at=None,
            )
            mock_get.return_value = NotebookResponse(
                id="nb-from-template",
                title="Company Due Diligence",
                description="Standard template",
                status=NotebookStatus.DRAFT,
                template_name="Company Due Diligence",
                linked_entity_ids=[],
                linked_alert_ids=[],
                tags=[],
                cell_count=5,
                cells=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                completed_at=None,
                author="user",
            )

            result = notebook_service.create_notebook_from_template("Company Due Diligence", "user")

            assert result is not None
            assert result.template_name == "Company Due Diligence"
            mock_create.assert_called_once()
            assert mock_add.call_count == 5  # Template has 5 cells

    def test_create_from_template_not_found(self, notebook_service, mock_conn):
        """Test creating from non-existent template."""
        with pytest.raises(ValueError, match="not found"):
            notebook_service.create_notebook_from_template("NonExistent Template")

    def test_template_cell_count(self, notebook_service, mock_conn):
        """Test that templates have expected cell counts."""
        templates = notebook_service.list_templates()

        # Company Due Diligence: 5 cells
        assert templates[0]["cell_count"] == 5
        # Fraud Pattern Analysis: 5 cells
        assert templates[1]["cell_count"] == 5
        # Risk Assessment: 5 cells
        assert templates[2]["cell_count"] == 5
        # Supply Chain Analysis: 5 cells
        assert templates[3]["cell_count"] == 5
        # Blank Investigation: 1 cell
        assert templates[4]["cell_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Export Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestExport:
    """Tests for export operations."""

    def test_export_json(self, notebook_service, mock_conn):
        """Test exporting to JSON."""
        notebook = NotebookResponse(
            id="nb-uuid-123",
            title="Test Export",
            description="Test description",
            status=NotebookStatus.DRAFT,
            template_name=None,
            linked_entity_ids=["entity-1"],
            linked_alert_ids=[],
            tags=["test"],
            cell_count=1,
            cells=[
                NotebookCell(
                    id="cell-1",
                    notebook_id="nb-uuid-123",
                    cell_type=NotebookCellType.MARKDOWN,
                    content="# Test",
                    position=0,
                    title=None,
                    execution_result=None,
                    execution_count=0,
                    last_executed_at=None,
                    linked_entity_id=None,
                    created_at=datetime.now(UTC),
                    updated_at=None,
                )
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=None,
            author="user",
        )

        with patch.object(notebook_service, 'get_notebook', return_value=notebook):
            result = notebook_service.export_notebook("nb-uuid-123", "json")

            import json
            data = json.loads(result)
            assert data["title"] == "Test Export"
            assert len(data["cells"]) == 1

    def test_export_markdown(self, notebook_service, mock_conn):
        """Test exporting to Markdown."""
        notebook = NotebookResponse(
            id="nb-uuid-123",
            title="Test Export",
            description="Test description",
            status=NotebookStatus.DRAFT,
            template_name=None,
            linked_entity_ids=[],
            linked_alert_ids=[],
            tags=[],
            cell_count=1,
            cells=[
                NotebookCell(
                    id="cell-1",
                    notebook_id="nb-uuid-123",
                    cell_type=NotebookCellType.CYPHER_QUERY,
                    content="MATCH (c:Company) RETURN c",
                    position=0,
                    title="Query",
                    execution_result=None,
                    execution_count=0,
                    last_executed_at=None,
                    linked_entity_id=None,
                    created_at=datetime.now(UTC),
                    updated_at=None,
                )
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=None,
            author="user",
        )

        with patch.object(notebook_service, 'get_notebook', return_value=notebook):
            result = notebook_service.export_notebook("nb-uuid-123", "markdown")

            assert "# Test Export" in result
            assert "```cypher" in result
            assert "MATCH (c:Company) RETURN c" in result

    def test_export_html(self, notebook_service, mock_conn):
        """Test exporting to HTML."""
        notebook = NotebookResponse(
            id="nb-uuid-123",
            title="Test Export",
            description="Test description",
            status=NotebookStatus.DRAFT,
            template_name=None,
            linked_entity_ids=[],
            linked_alert_ids=[],
            tags=[],
            cell_count=1,
            cells=[
                NotebookCell(
                    id="cell-1",
                    notebook_id="nb-uuid-123",
                    cell_type=NotebookCellType.MARKDOWN,
                    content="# Hello",
                    position=0,
                    title=None,
                    execution_result=None,
                    execution_count=0,
                    last_executed_at=None,
                    linked_entity_id=None,
                    created_at=datetime.now(UTC),
                    updated_at=None,
                )
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            completed_at=None,
            author="user",
        )

        with patch.object(notebook_service, 'get_notebook', return_value=notebook):
            result = notebook_service.export_notebook("nb-uuid-123", "html")

            assert "<!DOCTYPE html>" in result
            assert "<title>Test Export</title>" in result

    def test_export_invalid_format_raises(self, notebook_service, mock_conn):
        """Test exporting with invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported export format"):
            notebook_service.export_notebook("nb-uuid-123", "pdf")

        with pytest.raises(ValueError, match="Unsupported export format"):
            notebook_service.export_notebook("nb-uuid-123", "xml")


# ─────────────────────────────────────────────────────────────────────────────
# Model Validation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNotebookCreateValidation:
    """Tests for NotebookCreate model validation."""

    def test_minimal_valid(self):
        """Test minimal valid NotebookCreate."""
        data = NotebookCreate(title="Test")
        assert data.title == "Test"
        assert data.description == ""
        assert data.author == "user"
        assert data.linked_entity_ids == []
        assert data.tags == []

    def test_full_valid(self):
        """Test NotebookCreate with all fields."""
        data = NotebookCreate(
            title="Full Test",
            description="Full description",
            template_name="Company Due Diligence",
            linked_entity_ids=["entity-1"],
            linked_alert_ids=["alert-1"],
            tags=["test", "fraud"],
            author="analyst",
        )
        assert data.title == "Full Test"
        assert data.template_name == "Company Due Diligence"
        assert data.author == "analyst"

    def test_title_empty_raises(self):
        """Test empty title raises validation error."""
        with pytest.raises(ValueError):
            NotebookCreate(title="")

    def test_title_max_length(self):
        """Test title at max length is valid."""
        data = NotebookCreate(title="A" * 200)
        assert len(data.title) == 200

    def test_title_over_max_length_raises(self):
        """Test title exceeding max length raises validation error."""
        with pytest.raises(ValueError):
            NotebookCreate(title="A" * 201)


class TestNotebookCellCreateValidation:
    """Tests for NotebookCellCreate model validation."""

    def test_minimal_valid(self):
        """Test minimal valid NotebookCellCreate."""
        data = NotebookCellCreate(cell_type=NotebookCellType.MARKDOWN)
        assert data.cell_type == NotebookCellType.MARKDOWN
        assert data.content == ""
        assert data.position is None

    def test_full_valid(self):
        """Test NotebookCellCreate with all fields."""
        data = NotebookCellCreate(
            cell_type=NotebookCellType.CYPHER_QUERY,
            content="MATCH (c:Company) RETURN c",
            position=5,
            title="Company Query",
            linked_entity_id="entity-1",
        )
        assert data.cell_type == NotebookCellType.CYPHER_QUERY
        assert data.position == 5
        assert data.linked_entity_id == "entity-1"

    def test_position_negative_raises(self):
        """Test negative position raises validation error."""
        with pytest.raises(ValueError):
            NotebookCellCreate(cell_type=NotebookCellType.MARKDOWN, position=-1)


class TestNotebookListParamsValidation:
    """Tests for NotebookListParams model validation."""

    def test_defaults(self):
        """Test default values."""
        params = NotebookListParams()
        assert params.limit == 50
        assert params.offset == 0
        assert params.sort_by == "updated_at"
        assert params.sort_order == "desc"

    def test_sort_by_valid_fields(self):
        """Test all valid sort_by fields."""
        valid_fields = ["updated_at", "created_at", "title", "status"]
        for field in valid_fields:
            params = NotebookListParams(sort_by=field)
            assert params.sort_by == field

    def test_sort_by_invalid_raises(self):
        """Test invalid sort_by raises ValueError."""
        with pytest.raises(ValueError, match="sort_by must be one of"):
            NotebookListParams(sort_by="invalid_field")

    def test_sort_order_valid(self):
        """Test valid sort_order values."""
        assert NotebookListParams(sort_order="asc").sort_order == "asc"
        assert NotebookListParams(sort_order="desc").sort_order == "desc"

    def test_sort_order_invalid_raises(self):
        """Test invalid sort_order raises ValueError."""
        with pytest.raises(ValueError, match="sort_order must be one of"):
            NotebookListParams(sort_order="ascending")

    def test_limit_min_raises(self):
        """Test limit below minimum raises ValueError."""
        with pytest.raises(ValueError):
            NotebookListParams(limit=0)

    def test_limit_max_raises(self):
        """Test limit above maximum raises ValueError."""
        with pytest.raises(ValueError):
            NotebookListParams(limit=201)


class TestNotebookCellTypeEnum:
    """Tests for NotebookCellType enum."""

    def test_all_values(self):
        """Test all NotebookCellType enum values."""
        assert NotebookCellType.MARKDOWN.value == "markdown"
        assert NotebookCellType.CYPHER_QUERY.value == "cypher_query"
        assert NotebookCellType.RESULTS_TABLE.value == "results_table"
        assert NotebookCellType.VISUALIZATION.value == "visualization"
        assert NotebookCellType.CODE.value == "code"

    def test_count(self):
        """Test expected number of cell types."""
        assert len(NotebookCellType) == 6  # markdown, cypher_query, results_table, visualization, code, connection_insight

    def test_from_string(self):
        """Test constructing NotebookCellType from string."""
        assert NotebookCellType("markdown") == NotebookCellType.MARKDOWN
        assert NotebookCellType("cypher_query") == NotebookCellType.CYPHER_QUERY

    def test_invalid_value_raises(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            NotebookCellType("invalid_type")


class TestNotebookStatusEnum:
    """Tests for NotebookStatus enum."""

    def test_all_values(self):
        """Test all NotebookStatus enum values."""
        assert NotebookStatus.DRAFT.value == "draft"
        assert NotebookStatus.ACTIVE.value == "active"
        assert NotebookStatus.COMPLETED.value == "completed"
        assert NotebookStatus.ARCHIVED.value == "archived"

    def test_count(self):
        """Test expected number of status values."""
        assert len(NotebookStatus) == 4

    def test_from_string(self):
        """Test constructing NotebookStatus from string."""
        assert NotebookStatus("draft") == NotebookStatus.DRAFT

    def test_invalid_value_raises(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            NotebookStatus("deleted")


class TestNotebookExportFormatEnum:
    """Tests for NotebookExportFormat enum."""

    def test_all_values(self):
        """Test all NotebookExportFormat enum values."""
        assert NotebookExportFormat.JSON.value == "json"
        assert NotebookExportFormat.MARKDOWN.value == "markdown"
        assert NotebookExportFormat.HTML.value == "html"

    def test_count(self):
        """Test expected number of export formats."""
        assert len(NotebookExportFormat) == 3

    def test_from_string(self):
        """Test constructing NotebookExportFormat from string."""
        assert NotebookExportFormat("json") == NotebookExportFormat.JSON

    def test_invalid_value_raises(self):
        """Test invalid string raises ValueError."""
        with pytest.raises(ValueError):
            NotebookExportFormat("pdf")


# ─────────────────────────────────────────────────────────────────────────────
# Security Tests (Cypher Validation)
# ─────────────────────────────────────────────────────────────────────────────

class TestCypherValidation:
    """Tests for Cypher query validation security."""

    def test_rejects_create(self, notebook_service):
        """Test validation rejects CREATE."""
        with pytest.raises(ValueError, match="write operation"):
            notebook_service._validate_cypher("CREATE (n:Test) RETURN n")

    def test_rejects_delete(self, notebook_service):
        """Test validation rejects DELETE."""
        with pytest.raises(ValueError, match="write operation"):
            notebook_service._validate_cypher("MATCH (n:Test) DELETE n")

    def test_rejects_merge(self, notebook_service):
        """Test validation rejects MERGE."""
        with pytest.raises(ValueError, match="write operation"):
            notebook_service._validate_cypher("MERGE (n:Test {id: 1}) RETURN n")

    def test_allows_match(self, notebook_service):
        """Test validation allows MATCH."""
        # Should not raise
        notebook_service._validate_cypher("MATCH (c:Company) RETURN c")

    def test_allows_return(self, notebook_service):
        """Test validation allows RETURN."""
        # Should not raise
        notebook_service._validate_cypher("MATCH (c:Company) RETURN c.name, c.cf")

    def test_rejects_set(self, notebook_service):
        """Test validation rejects SET."""
        with pytest.raises(ValueError, match="write operation"):
            notebook_service._validate_cypher("MATCH (c:Company) SET c.risk_score = 0.5")

    def test_rejects_remove(self, notebook_service):
        """Test validation rejects REMOVE."""
        with pytest.raises(ValueError, match="write operation"):
            notebook_service._validate_cypher("MATCH (c:Company) REMOVE c.anomaly_flags")

    def test_rejects_drop(self, notebook_service):
        """Test validation rejects DROP."""
        with pytest.raises(ValueError, match="write operation"):
            notebook_service._validate_cypher("DROP INDEX company_name_idx")

    def test_empty_query_raises(self, notebook_service):
        """Test empty query raises ValueError."""
        with pytest.raises(ValueError, match="Empty Cypher query"):
            notebook_service._validate_cypher("")

        with pytest.raises(ValueError, match="Empty Cypher query"):
            notebook_service._validate_cypher("   ")

    def test_complex_read_only_allowed(self, notebook_service):
        """Test complex read-only query is allowed."""
        query = """
        MATCH (c:Company)-[:WINS]->(t:Tender)
        WITH c, count(t) AS total_wins, sum(t.importo) AS total_value
        WHERE total_wins > 5
        RETURN c.nome_normalizzato AS name, total_wins, total_value
        ORDER BY total_value DESC
        LIMIT 20
        """
        # Should not raise
        notebook_service._validate_cypher(query)

    def test_write_in_string_ignored(self, notebook_service):
        """Test that write keywords inside strings are ignored."""
        query = 'MATCH (c:Company) RETURN "CREATE" AS test'
        # Should not raise since CREATE is inside a string
        notebook_service._validate_cypher(query)


# ─────────────────────────────────────────────────────────────────────────────
# Markdown Rendering Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkdownRendering:
    """Tests for markdown to HTML rendering."""

    def test_render_headings(self, notebook_service):
        """Test rendering headings."""
        md = "# Heading 1\n## Heading 2\n### Heading 3"
        html = notebook_service._render_markdown(md)

        assert "<h1>Heading 1</h1>" in html
        assert "<h2>Heading 2</h2>" in html
        assert "<h3>Heading 3</h3>" in html

    def test_render_bold_italic(self, notebook_service):
        """Test rendering bold and italic."""
        md = "**bold text** and *italic text*"
        html = notebook_service._render_markdown(md)

        assert "<strong>bold text</strong>" in html
        assert "<em>italic text</em>" in html

    def test_render_unordered_list(self, notebook_service):
        """Test rendering unordered lists."""
        md = "- Item 1\n- Item 2\n- Item 3"
        html = notebook_service._render_markdown(md)

        assert "<ul>" in html
        assert "<li>Item 1</li>" in html
        assert "<li>Item 2</li>" in html
        assert "</ul>" in html

    def test_render_code_block(self, notebook_service):
        """Test rendering code blocks."""
        md = "```\ncode block\n```"
        html = notebook_service._render_markdown(md)

        assert "<pre><code>" in html
        assert "code block" in html
        assert "</code></pre>" in html

    def test_render_links(self, notebook_service):
        """Test rendering links."""
        md = "[Link Text](https://example.com)"
        html = notebook_service._render_markdown(md)

        assert '<a href="https://example.com">Link Text</a>' in html

    def test_render_empty(self, notebook_service):
        """Test rendering empty content."""
        html = notebook_service._render_markdown("")
        assert html == ""


# ─────────────────────────────────────────────────────────────────────────────
# Template Data Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateData:
    """Tests for pre-built template data."""

    def test_five_templates_exist(self):
        """Test that exactly 5 templates exist."""
        assert len(INVESTIGATION_TEMPLATES) == 5

    def test_template_names(self):
        """Test expected template names."""
        names = [t["name"] for t in INVESTIGATION_TEMPLATES]
        assert "Company Due Diligence" in names
        assert "Fraud Pattern Analysis" in names
        assert "Risk Assessment" in names
        assert "Supply Chain Analysis" in names
        assert "Blank Investigation" in names

    def test_template_cells_have_required_fields(self):
        """Test that all template cells have required fields."""
        for template in INVESTIGATION_TEMPLATES:
            for cell in template["cells"]:
                assert "cell_type" in cell
                assert "content" in cell
                assert "position" in cell
                assert cell["cell_type"] in ["markdown", "cypher_query", "results_table", "visualization", "code"]

    def test_company_due_diligence_template(self):
        """Test Company Due Diligence template structure."""
        template = INVESTIGATION_TEMPLATES[0]
        assert template["name"] == "Company Due Diligence"
        assert len(template["cells"]) == 5

        # First cell should be markdown intro
        assert template["cells"][0]["cell_type"] == "markdown"
        # Should have cypher query cells
        cypher_cells = [c for c in template["cells"] if c["cell_type"] == "cypher_query"]
        assert len(cypher_cells) == 3

    def test_blank_investigation_template(self):
        """Test Blank Investigation template is minimal."""
        template = INVESTIGATION_TEMPLATES[4]
        assert template["name"] == "Blank Investigation"
        assert len(template["cells"]) == 1
        assert template["cells"][0]["cell_type"] == "markdown"
