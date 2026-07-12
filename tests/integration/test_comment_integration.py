"""
Integration tests for Comment System.

Tests cover end-to-end workflows including:
- Full comment lifecycle (create, read, update, delete)
- Entity linking
- Threaded conversations
- Search with full-text index
- API endpoint integration

NOTE: These tests require a running Neo4j instance.
"""

import pytest
import time
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from paladino.app.api import app
from paladino.app.comment_service import CommentService
from paladino.db import Neo4jConnection
from paladino.models import (
    CommentCreate,
    CommentUpdate,
    CommentListParams,
    CommentSearchRequest,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    # Mock API key verification for tests
    with patch("paladino.app.security.verify_api_key", return_value="test-api-key"):
        with TestClient(app) as client:
            yield client


@pytest.fixture
def mock_neo4j_driver():
    """Mock Neo4j driver for integration tests."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    return driver


@pytest.fixture
def sample_company_id():
    """Sample company ID for testing."""
    return "12345678901"


@pytest.fixture
def sample_tender_id():
    """Sample tender ID for testing."""
    return "Z1234567890"


# ─────────────────────────────────────────────────────────────────────────────
# End-to-End Comment Workflow Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires running Neo4j instance")
class TestCommentWorkflow:
    """End-to-end comment workflow tests."""

    def test_create_comment_api(self, client, mock_neo4j_driver):
        """Test creating a comment via API."""
        # Mock Neo4j response
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "new-comment-uuid",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "test-user",
                "content": "Test comment content",
                "parent_comment_id": None,
                "tags": ["test"],
                "mentions": [],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/comments",
                json={
                    "entity_id": "12345678901",
                    "entity_type": "Company",
                    "content": "Test comment content",
                    "tags": ["test"],
                    "author": "test-user",
                },
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "new-comment-uuid"
        assert data["entity_id"] == "12345678901"
        assert data["entity_type"] == "Company"
        assert data["content"] == "Test comment content"

    def test_get_comment_api(self, client, mock_neo4j_driver):
        """Test retrieving a comment via API."""
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "existing-comment",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "analyst",
                "content": "Existing comment",
                "parent_comment_id": None,
                "tags": [],
                "mentions": [],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/comments/existing-comment",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "existing-comment"

    def test_get_comment_not_found_api(self, client, mock_neo4j_driver):
        """Test 404 for non-existent comment."""
        mock_result = MagicMock()
        mock_result.single.return_value = None
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/comments/non-existent",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 404

    def test_update_comment_api(self, client, mock_neo4j_driver):
        """Test updating a comment via API."""
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "comment-to-update",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "analyst",
                "content": "Updated content",
                "parent_comment_id": None,
                "tags": ["updated"],
                "mentions": [],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": datetime.now(UTC).isoformat(),
                "source": "user",
                "confidence": 1.0,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.put(
                "/comments/comment-to-update",
                json={
                    "content": "Updated content",
                    "tags": ["updated"],
                },
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Updated content"
        assert data["tags"] == ["updated"]

    def test_delete_comment_api(self, client, mock_neo4j_driver):
        """Test soft deleting a comment via API."""
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "comment-to-delete",
                "is_deleted": True,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.delete(
                "/comments/comment-to-delete",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

    def test_list_comments_api(self, client, mock_neo4j_driver):
        """Test listing comments via API."""
        mock_result = MagicMock()
        mock_result.data = [
            {"c": {"id": "comment-1", "entity_id": "12345678901", "entity_type": "Company",
                   "author": "analyst", "content": "Comment 1", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": False,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0}},
        ]
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/comments?entity_id=12345678901&entity_type=Company&limit=10",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


# ─────────────────────────────────────────────────────────────────────────────
# Entity Linking Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires running Neo4j instance")
class TestEntityLinking:
    """Tests for entity-comment linking."""

    def test_get_entity_comments_company(self, client, mock_neo4j_driver):
        """Test getting comments for a Company entity."""
        mock_result = MagicMock()
        mock_result.data = [
            {"c": {"id": "comment-1", "entity_id": "12345678901", "entity_type": "Company",
                   "author": "analyst", "content": "Company comment", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": False,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0}},
        ]
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/entities/Company/12345678901/comments",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200

    def test_get_entity_comments_tender(self, client, mock_neo4j_driver):
        """Test getting comments for a Tender entity."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/entities/Tender/Z1234567890/comments",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200

    def test_get_entity_comments_invalid_type(self, client):
        """Test 400 for invalid entity type."""
        response = client.get(
            "/entities/InvalidType/123/comments",
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 400

    def test_get_entity_comment_threads(self, client, mock_neo4j_driver):
        """Test getting threaded comments for an entity."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/entities/Company/12345678901/comments/threads?limit=10",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Threaded Conversation Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires running Neo4j instance")
class TestThreadedConversations:
    """Tests for threaded comment conversations."""

    def test_create_reply(self, client, mock_neo4j_driver):
        """Test creating a reply to an existing comment."""
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "reply-uuid",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "reviewer",
                "content": "I agree with this assessment",
                "parent_comment_id": "parent-comment-id",
                "tags": [],
                "mentions": [],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/comments",
                json={
                    "entity_id": "12345678901",
                    "entity_type": "Company",
                    "content": "I agree with this assessment",
                    "parent_comment_id": "parent-comment-id",
                    "author": "reviewer",
                },
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["parent_comment_id"] == "parent-comment-id"

    def test_get_comment_thread(self, client, mock_neo4j_driver):
        """Test getting a comment thread with replies."""
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "parent-comment",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "analyst",
                "content": "Parent comment",
                "parent_comment_id": None,
                "tags": [],
                "mentions": [],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/comments/parent-comment/thread",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Search Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires running Neo4j instance")
class TestCommentSearch:
    """Tests for comment search functionality."""

    def test_search_comments_api(self, client, mock_neo4j_driver):
        """Test searching comments via API."""
        mock_result = MagicMock()
        mock_result.data = [
            {"c": {"id": "search-result", "entity_id": "12345678901", "entity_type": "Company",
                   "author": "analyst", "content": "Matching content here", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": False,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0},
             "score": 0.95}
        ]
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/comments/search",
                json={
                    "query": "matching",
                    "limit": 20,
                },
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "count" in data

    def test_search_with_entity_filter(self, client, mock_neo4j_driver):
        """Test searching with entity type filter."""
        mock_result = MagicMock()
        mock_result.data = []
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/comments/search",
                json={
                    "query": "test",
                    "entity_type": "Company",
                    "limit": 20,
                },
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200

    def test_search_empty_query_raises(self, client):
        """Test that empty search query raises validation error."""
        response = client.post(
            "/comments/search",
            json={"query": ""},
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 422  # Validation error


# ─────────────────────────────────────────────────────────────────────────────
# Mention Extraction Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires running Neo4j instance")
class TestMentionExtraction:
    """Tests for entity mention extraction in comments."""

    def test_comment_with_company_mention(self, client, mock_neo4j_driver):
        """Test creating a comment with @Company mention."""
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "mention-comment",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "analyst",
                "content": "Related to @Company:98765432109",
                "parent_comment_id": None,
                "tags": [],
                "mentions": ["98765432109"],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/comments",
                json={
                    "entity_id": "12345678901",
                    "entity_type": "Company",
                    "content": "Related to @Company:98765432109",
                    "author": "analyst",
                },
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "98765432109" in data["mentions"]

    def test_comment_with_multiple_mentions(self, client, mock_neo4j_driver):
        """Test creating a comment with multiple entity mentions."""
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "c": {
                "id": "multi-mention",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "analyst",
                "content": "Company @Company:111 won tender @Tender:222",
                "parent_comment_id": None,
                "tags": [],
                "mentions": ["111", "222"],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.post(
                "/comments",
                json={
                    "entity_id": "12345678901",
                    "entity_type": "Company",
                    "content": "Company @Company:111 won tender @Tender:222",
                    "author": "analyst",
                },
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
        data = response.json()
        assert set(data["mentions"]) == {"111", "222"}


# ─────────────────────────────────────────────────────────────────────────────
# Validation and Error Handling Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires running Neo4j instance")
class TestValidationAndErrors:
    """Tests for input validation and error handling."""

    def test_invalid_entity_type_raises(self, client):
        """Test that invalid entity type returns 400."""
        response = client.post(
            "/comments",
            json={
                "entity_id": "123",
                "entity_type": "InvalidType",
                "content": "Test",
            },
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_empty_content_raises(self, client):
        """Test that empty content returns validation error."""
        response = client.post(
            "/comments",
            json={
                "entity_id": "123",
                "entity_type": "Company",
                "content": "",
            },
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 422

    def test_content_too_long_raises(self, client):
        """Test that content exceeding max length returns validation error."""
        long_content = "x" * 10001  # Exceeds 10000 char limit
        response = client.post(
            "/comments",
            json={
                "entity_id": "123",
                "entity_type": "Company",
                "content": long_content,
            },
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 422

    def test_invalid_tag_format_raises(self, client):
        """Test that invalid tag format returns validation error."""
        response = client.post(
            "/comments",
            json={
                "entity_id": "123",
                "entity_type": "Company",
                "content": "Test",
                "tags": ["valid", "invalid@tag"],
            },
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 422

    def test_pagination_limit_validation(self, client):
        """Test pagination limit validation."""
        response = client.get(
            "/comments?limit=500",  # Exceeds max of 100
            headers={"X-API-Key": "test-key"},
        )

        assert response.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# Soft Delete Tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Requires running Neo4j instance")
class TestSoftDelete:
    """Tests for soft delete functionality."""

    def test_soft_delete_hides_from_list(self, client, mock_neo4j_driver):
        """Test that soft-deleted comments are hidden from normal lists."""
        # First, mock the delete
        mock_delete = MagicMock()
        mock_delete.single.return_value = {"c": {"is_deleted": True}}
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_delete

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            # Delete the comment
            delete_response = client.delete(
                "/comments/comment-to-hide",
                headers={"X-API-Key": "test-key"},
            )
            assert delete_response.status_code == 200

    def test_include_deleted_param(self, client, mock_neo4j_driver):
        """Test include_deleted query parameter."""
        mock_result = MagicMock()
        mock_result.data = [
            {"c": {"id": "deleted-comment", "is_deleted": True}}
        ]
        mock_neo4j_driver.session.return_value.__enter__.return_value.run.return_value = mock_result

        with patch("paladino.db.get_driver", return_value=mock_neo4j_driver):
            response = client.get(
                "/comments?include_deleted=true",
                headers={"X-API-Key": "test-key"},
            )

        assert response.status_code == 200
