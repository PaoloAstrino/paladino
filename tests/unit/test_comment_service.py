"""
Unit tests for Comment Service.

Tests cover:
- Comment creation and validation
- Listing and pagination
- Search functionality
- Thread replies
- Soft delete
- Mention extraction
"""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, patch

from paladino.app.comment_service import CommentService, _extract_mentions
from paladino.models import (
    CommentCreate,
    CommentUpdate,
    CommentListParams,
    CommentSearchRequest,
    ProvenanceMetadata,
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
def comment_service(mock_conn):
    """Create a CommentService with mocked connection."""
    return CommentService(mock_conn)


@pytest.fixture
def sample_comment_data():
    """Sample comment creation data."""
    return CommentCreate(
        entity_id="12345678901",
        entity_type="Company",
        content="This company shows suspicious activity patterns",
        tags=["risk", "review-needed"],
        author="analyst",
    )


@pytest.fixture
def sample_comment_record():
    """Sample Neo4j record for a comment."""
    return {
        "c": {
            "id": "test-uuid-123",
            "entity_id": "12345678901",
            "entity_type": "Company",
            "author": "analyst",
            "content": "This company shows suspicious activity patterns",
            "parent_comment_id": None,
            "tags": ["risk", "review-needed"],
            "mentions": [],
            "is_deleted": False,
            "created_at": datetime.now(UTC).isoformat(),
            "edited_at": None,
            "source": "user",
            "confidence": 1.0,
            "provenance": {
                "source": ["user"],
                "dataset_version": "1.0",
                "retrieval_date": datetime.now(UTC).isoformat(),
                "confidence": 1.0,
            }
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Mention Extraction Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMentionExtraction:
    """Tests for _extract_mentions helper function."""

    def test_extract_single_mention(self):
        """Test extracting a single entity mention."""
        content = "Check @Company:12345678901 for suspicious activity"
        mentions = _extract_mentions(content)
        assert mentions == ["12345678901"]

    def test_extract_multiple_mentions(self):
        """Test extracting multiple entity mentions."""
        content = "Company @Company:12345678901 won tender @Tender:Z1234567890"
        mentions = _extract_mentions(content)
        assert set(mentions) == {"12345678901", "Z1234567890"}

    def test_extract_deduplicates_mentions(self):
        """Test that duplicate mentions are deduplicated."""
        content = "@Company:12345678901 and again @Company:12345678901"
        mentions = _extract_mentions(content)
        assert mentions == ["12345678901"]

    def test_extract_no_mentions(self):
        """Test content without mentions returns empty list."""
        content = "No mentions here"
        mentions = _extract_mentions(content)
        assert mentions == []

    def test_extract_invalid_entity_type_ignored(self):
        """Test that invalid entity types are ignored."""
        content = "@Invalid:123456 @Company:12345678901"
        mentions = _extract_mentions(content)
        assert mentions == ["12345678901"]

    def test_extract_valid_entity_types(self):
        """Test all valid entity types are recognized."""
        content = """
            @Company:111 @Tender:222 @Project:333 @Person:444
            @Asset:555 @Buyer:666 @FraudPattern:777
        """
        mentions = _extract_mentions(content)
        assert set(mentions) == {"111", "222", "333", "444", "555", "666", "777"}

    def test_extract_empty_content(self):
        """Test empty content returns empty list."""
        mentions = _extract_mentions("")
        assert mentions == []

    def test_extract_none_content(self):
        """Test None content returns empty list."""
        mentions = _extract_mentions(None)
        assert mentions == []


# ─────────────────────────────────────────────────────────────────────────────
# Comment Creation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCreateComment:
    """Tests for create_comment method."""

    def test_create_comment_success(self, comment_service, mock_conn, sample_comment_data):
        """Test successful comment creation."""
        mock_result = [{
            "c": {
                "id": "new-uuid",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "analyst",
                "content": "This company shows suspicious activity patterns",
                "parent_comment_id": None,
                "tags": ["risk", "review-needed"],
                "mentions": [],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }]
        mock_conn.run_query.return_value = mock_result

        result = comment_service.create_comment(sample_comment_data)

        assert result.id == "new-uuid"
        assert result.entity_id == "12345678901"
        assert result.entity_type == "Company"
        assert result.author == "analyst"
        assert result.content == "This company shows suspicious activity patterns"
        assert result.tags == ["risk", "review-needed"]
        assert result.is_deleted is False

    def test_create_comment_with_mentions(self, comment_service, mock_conn):
        """Test comment creation with entity mentions."""
        data = CommentCreate(
            entity_id="12345678901",
            entity_type="Company",
            content="Related to @Tender:Z1234567890 and @Person:ABCDEF1234567890",
            author="analyst",
        )
        mock_result = [{
            "c": {
                "id": "mention-uuid",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "analyst",
                "content": data.content,
                "parent_comment_id": None,
                "tags": [],
                "mentions": ["Z1234567890", "ABCDEF1234567890"],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }]
        mock_conn.run_query.return_value = mock_result

        result = comment_service.create_comment(data)

        assert set(result.mentions) == {"Z1234567890", "ABCDEF1234567890"}

    def test_create_comment_with_parent(self, comment_service, mock_conn):
        """Test creating a reply to an existing comment."""
        data = CommentCreate(
            entity_id="12345678901",
            entity_type="Company",
            content="I agree with this assessment",
            parent_comment_id="parent-uuid",
            author="reviewer",
        )
        mock_result = [{
            "c": {
                "id": "reply-uuid",
                "entity_id": "12345678901",
                "entity_type": "Company",
                "author": "reviewer",
                "content": "I agree with this assessment",
                "parent_comment_id": "parent-uuid",
                "tags": [],
                "mentions": [],
                "is_deleted": False,
                "created_at": datetime.now(UTC).isoformat(),
                "edited_at": None,
                "source": "user",
                "confidence": 1.0,
            }
        }]
        mock_conn.run_query.return_value = mock_result

        result = comment_service.create_comment(data)

        assert result.parent_comment_id == "parent-uuid"

    def test_create_comment_empty_content_raises(self, mock_conn):
        """Test that empty content raises validation error."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            CommentCreate(
                entity_id="12345678901",
                entity_type="Company",
                content="",
                author="analyst",
            )

    def test_create_comment_invalid_entity_type_raises(self, mock_conn):
        """Test that invalid entity type raises validation error."""
        with pytest.raises(ValueError, match="entity_type must be one of"):
            CommentCreate(
                entity_id="12345678901",
                entity_type="InvalidType",
                content="Test comment",
                author="analyst",
            )

    def test_create_comment_invalid_tags_raises(self, mock_conn):
        """Test that invalid tags raise validation error."""
        with pytest.raises(ValueError, match="contains invalid characters"):
            CommentCreate(
                entity_id="12345678901",
                entity_type="Company",
                content="Test comment",
                tags=["valid-tag", "invalid@tag"],
            )


# ─────────────────────────────────────────────────────────────────────────────
# Get Comment Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestGetComment:
    """Tests for get_comment method."""

    def test_get_comment_success(self, comment_service, mock_conn, sample_comment_record):
        """Test successful comment retrieval."""
        mock_conn.run_query.return_value = [sample_comment_record]

        result = comment_service.get_comment("test-uuid-123")

        assert result is not None
        assert result.id == "test-uuid-123"
        assert result.entity_type == "Company"

    def test_get_comment_not_found(self, comment_service, mock_conn):
        """Test comment not found returns None."""
        mock_conn.run_query.return_value = []

        result = comment_service.get_comment("non-existent-uuid")

        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# List Comments Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestListComments:
    """Tests for list_comments method."""

    def test_list_comments_basic(self, comment_service, mock_conn):
        """Test basic comment listing."""
        mock_count = [{"total": 5}]
        mock_data = [
            {"c": {"id": f"comment-{i}", "entity_id": "12345678901", "entity_type": "Company",
                   "author": "analyst", "content": f"Comment {i}", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": False,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0}}
            for i in range(5)
        ]
        # Mock reply counts query (returns empty for top-level comments)
        mock_reply_counts = [
            {"parent_id": f"comment-{i}", "reply_count": 0}
            for i in range(5)
        ]
        mock_conn.run_query.side_effect = [mock_count, mock_data, mock_reply_counts]

        params = CommentListParams(entity_id="12345678901", entity_type="Company")
        comments, total = comment_service.list_comments(params)

        assert total == 5
        assert len(comments) == 5
        assert comments[0].id == "comment-0"

    def test_list_comments_with_filters(self, comment_service, mock_conn):
        """Test listing with filters."""
        mock_conn.run_query.return_value = [{"total": 0}]

        params = CommentListParams(
            entity_id="12345678901",
            entity_type="Company",
            author="analyst",
            tag="risk",
        )
        comments, total = comment_service.list_comments(params)

        assert total == 0
        # Verify query was called (filters applied)
        assert mock_conn.run_query.called

    def test_list_comments_pagination(self, comment_service, mock_conn):
        """Test pagination parameters."""
        mock_count = [{"total": 50}]
        mock_data = [
            {"c": {"id": f"comment-{i}", "entity_id": "12345678901", "entity_type": "Company",
                   "author": "analyst", "content": f"Comment {i}", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": False,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0}}
            for i in range(10)
        ]
        # Mock reply counts query
        mock_reply_counts = []
        mock_conn.run_query.side_effect = [mock_count, mock_data, mock_reply_counts]

        params = CommentListParams(
            entity_id="12345678901",
            entity_type="Company",
            limit=10,
            offset=20,
        )
        comment_service.list_comments(params)

        # Verify the data query (second call) had pagination params
        # run_query is called 3 times: count, data, reply_counts
        data_call_args = mock_conn.run_query.call_args_list[1]
        assert data_call_args[0][1]["limit"] == 10
        assert data_call_args[0][1]["offset"] == 20

    def test_list_comments_empty_result(self, comment_service, mock_conn):
        """Test empty result set."""
        mock_conn.run_query.return_value = [{"total": 0}]

        params = CommentListParams(entity_id="non-existent")
        comments, total = comment_service.list_comments(params)

        assert total == 0
        assert comments == []

    def test_list_comments_invalid_entity_type_raises(self, mock_conn):
        """Test invalid entity type raises validation error."""
        with pytest.raises(ValueError):
            CommentListParams(entity_type="InvalidType")

    def test_list_comments_invalid_sort_raises(self, mock_conn):
        """Test invalid sort field raises validation error."""
        with pytest.raises(ValueError):
            CommentListParams(sort_by="invalid_field")

    def test_list_comments_invalid_order_raises(self, mock_conn):
        """Test invalid sort order raises validation error."""
        with pytest.raises(ValueError):
            CommentListParams(sort_order="invalid")


# ─────────────────────────────────────────────────────────────────────────────
# Update Comment Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateComment:
    """Tests for update_comment method."""

    def test_update_content(self, comment_service, mock_conn):
        """Test updating comment content."""
        # First call: get_comment (returns old content)
        # Second call: update (returns NEW content after update)
        mock_conn.run_query.side_effect = [
            # get_comment call
            [{"c": {"id": "test-uuid", "entity_id": "123", "entity_type": "Company",
                    "author": "analyst", "content": "Old content", "parent_comment_id": None,
                    "tags": [], "mentions": [], "is_deleted": False,
                    "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                    "source": "user", "confidence": 1.0}}],
            # update call (returns updated record)
            [{"c": {"id": "test-uuid", "entity_id": "123", "entity_type": "Company",
                    "author": "analyst", "content": "New content", "parent_comment_id": None,
                    "tags": [], "mentions": [], "is_deleted": False,
                    "created_at": datetime.now(UTC).isoformat(),
                    "edited_at": datetime.now(UTC).isoformat(),
                    "source": "user", "confidence": 1.0}}],
        ]

        update_data = CommentUpdate(content="New content")
        result = comment_service.update_comment("test-uuid", update_data)

        assert result is not None
        assert result.content == "New content"

    def test_update_tags(self, comment_service, mock_conn):
        """Test updating comment tags."""
        mock_conn.run_query.side_effect = [
            # get_comment call
            [{"c": {"id": "test-uuid", "entity_id": "123", "entity_type": "Company",
                    "author": "analyst", "content": "Content", "parent_comment_id": None,
                    "tags": ["old"], "mentions": [], "is_deleted": False,
                    "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                    "source": "user", "confidence": 1.0}}],
            # update call (returns updated tags)
            [{"c": {"id": "test-uuid", "entity_id": "123", "entity_type": "Company",
                    "author": "analyst", "content": "Content", "parent_comment_id": None,
                    "tags": ["new", "updated"], "mentions": [], "is_deleted": False,
                    "created_at": datetime.now(UTC).isoformat(),
                    "edited_at": datetime.now(UTC).isoformat(),
                    "source": "user", "confidence": 1.0}}],
        ]

        update_data = CommentUpdate(tags=["new", "updated"])
        result = comment_service.update_comment("test-uuid", update_data)

        assert result.tags == ["new", "updated"]

    def test_update_soft_delete(self, comment_service, mock_conn):
        """Test soft deleting a comment."""
        mock_conn.run_query.return_value = [
            {"c": {"id": "test-uuid", "entity_id": "123", "entity_type": "Company",
                   "author": "analyst", "content": "Content", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": True,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0}}
        ]

        update_data = CommentUpdate(is_deleted=True)
        result = comment_service.update_comment("test-uuid", update_data)

        assert result.is_deleted is True

    def test_update_not_found(self, comment_service, mock_conn):
        """Test updating non-existent comment returns None."""
        mock_conn.run_query.return_value = []

        update_data = CommentUpdate(content="New content")
        result = comment_service.update_comment("non-existent", update_data)

        assert result is None

    def test_update_no_fields_raises(self, comment_service, mock_conn):
        """Test updating with no fields raises error."""
        update_data = CommentUpdate()

        with pytest.raises(ValueError, match="No fields to update"):
            comment_service.update_comment("test-uuid", update_data)


# ─────────────────────────────────────────────────────────────────────────────
# Delete Comment Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDeleteComment:
    """Tests for delete_comment method."""

    def test_delete_comment_success(self, comment_service, mock_conn):
        """Test successful soft delete."""
        # Mock successful update
        mock_conn.run_query.return_value = [
            {"c": {"id": "test-uuid", "entity_id": "123", "entity_type": "Company",
                   "author": "analyst", "content": "Content", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": True,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0}}
        ]

        result = comment_service.delete_comment("test-uuid")

        assert result is True

    def test_delete_comment_not_found(self, comment_service, mock_conn):
        """Test deleting non-existent comment returns False."""
        mock_conn.run_query.return_value = []

        result = comment_service.delete_comment("non-existent")

        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Search Comments Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchComments:
    """Tests for search_comments method."""

    def test_search_basic(self, comment_service, mock_conn):
        """Test basic search."""
        mock_result = [
            {"c": {"id": "result-1", "entity_id": "123", "entity_type": "Company",
                   "author": "analyst", "content": "Matching content", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": False,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0},
             "score": 0.95}
        ]
        mock_conn.run_query.return_value = mock_result

        params = CommentSearchRequest(query="matching")
        comments, total = comment_service.search_comments(params)

        assert len(comments) == 1
        assert total == 1

    def test_search_with_filters(self, comment_service, mock_conn):
        """Test search with entity type filter."""
        mock_conn.run_query.return_value = []

        params = CommentSearchRequest(
            query="test",
            entity_type="Company",
            author="analyst",
        )
        comments, total = comment_service.search_comments(params)

        assert total == 0

    def test_search_empty_result(self, comment_service, mock_conn):
        """Test search with no results."""
        mock_conn.run_query.return_value = []

        params = CommentSearchRequest(query="nonexistent")
        comments, total = comment_service.search_comments(params)

        assert total == 0
        assert comments == []


# ─────────────────────────────────────────────────────────────────────────────
# Thread Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCommentThreads:
    """Tests for threaded comment functionality."""

    def test_get_comment_threads(self, comment_service, mock_conn):
        """Test getting threaded conversations."""
        # Mock top-level comments
        mock_top = [
            {"c": {"id": "top-1", "entity_id": "123", "entity_type": "Company",
                   "author": "analyst", "content": "Top level", "parent_comment_id": None,
                   "tags": [], "mentions": [], "is_deleted": False,
                   "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                   "source": "user", "confidence": 1.0}}
        ]
        # Mock replies
        mock_replies = (
            [{"total": 2}],
            [
                {"c": {"id": "reply-1", "entity_id": "123", "entity_type": "Company",
                       "author": "reviewer", "content": "Reply 1", "parent_comment_id": "top-1",
                       "tags": [], "mentions": [], "is_deleted": False,
                       "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                       "source": "user", "confidence": 1.0}},
                {"c": {"id": "reply-2", "entity_id": "123", "entity_type": "Company",
                       "author": "reviewer", "content": "Reply 2", "parent_comment_id": "top-1",
                       "tags": [], "mentions": [], "is_deleted": False,
                       "created_at": datetime.now(UTC).isoformat(), "edited_at": None,
                       "source": "user", "confidence": 1.0}},
            ]
        )
        mock_conn.run_query.side_effect = [mock_top] + list(mock_replies)

        threads = comment_service.get_comment_threads("123", "Company")

        assert len(threads) == 1
        assert threads[0].comment.id == "top-1"
        assert threads[0].total_replies == 2

    def test_get_reply_count(self, comment_service, mock_conn):
        """Test getting reply count."""
        mock_conn.run_query.return_value = [{"count": 5}]

        count = comment_service.get_reply_count("parent-uuid")

        assert count == 5


# ─────────────────────────────────────────────────────────────────────────────
# Model Validation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestModelValidation:
    """Tests for Pydantic model validation."""

    def test_comment_create_valid(self):
        """Test valid CommentCreate."""
        data = CommentCreate(
            entity_id="12345678901",
            entity_type="Company",
            content="Valid comment",
            tags=["tag-1", "tag_2"],
            author="user",
        )
        assert data.entity_type == "Company"
        assert data.tags == ["tag-1", "tag_2"]

    def test_comment_create_auto_author(self):
        """Test author defaults to None."""
        data = CommentCreate(
            entity_id="12345678901",
            entity_type="Company",
            content="Valid comment",
        )
        assert data.author is None

    def test_comment_update_partial(self):
        """Test CommentUpdate allows partial updates."""
        data = CommentUpdate(content="Only content")
        assert data.content == "Only content"
        assert data.tags is None
        assert data.is_deleted is None

    def test_comment_list_params_defaults(self):
        """Test CommentListParams default values."""
        params = CommentListParams()
        assert params.limit == 20
        assert params.offset == 0
        assert params.sort_by == "created_at"
        assert params.sort_order == "desc"
        assert params.include_deleted is False

    def test_comment_search_request_valid(self):
        """Test valid CommentSearchRequest."""
        data = CommentSearchRequest(
            query="search term",
            entity_type="Tender",
            limit=10,
        )
        assert data.query == "search term"
        assert data.entity_type == "Tender"
        assert data.limit == 10
