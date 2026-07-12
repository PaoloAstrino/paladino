"""
Comment/Annotation Service for Paladino.

Provides CRUD operations for comments attached to any entity in the knowledge graph.
Supports threaded conversations, entity mentions, tagging, and full-text search.

Usage
──────────────────────────────────────────────────────────────────────────────
    from paladino.app.comment_service import CommentService
    from paladino.db import Neo4jConnection

    conn = Neo4jConnection()
    service = CommentService(conn)

    # Create a comment
    comment = service.create_comment(CommentCreate(
        entity_id="12345678901",
        entity_type="Company",
        content="This company has suspicious activity patterns",
        tags=["risk", "review-needed"],
        author="analyst"
    ))

    # List comments for an entity
    comments = service.list_comments(entity_id="12345678901", entity_type="Company")

    # Search comments
    results = service.search_comments("suspicious activity")
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, UTC
from typing import Any

from loguru import logger

from paladino.db import Neo4jConnection
from paladino.models import (
    CommentCreate,
    CommentUpdate,
    CommentResponse,
    CommentListParams,
    CommentSearchRequest,
    CommentThreadResponse,
    ProvenanceMetadata,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Regex pattern for entity mentions: @EntityType:EntityId
# Examples: @Company:12345678901, @Tender:Z1234567890
MENTION_PATTERN = re.compile(r"@(\w+):([\w]+)")

# Valid entity types that can be mentioned
VALID_MENTION_TYPES = {"Company", "Tender", "Project", "Person", "Asset", "Buyer", "FraudPattern"}


def _extract_mentions(content: str) -> list[str]:
    """Extract entity IDs from @Type:Id patterns in text."""
    if not content:
        return []
    mentions = []
    for match in MENTION_PATTERN.finditer(content):
        entity_type = match.group(1)
        entity_id = match.group(2)
        if entity_type in VALID_MENTION_TYPES:
            mentions.append(entity_id)
    return list(set(mentions))


# Maximum depth for thread traversal (prevent infinite loops)
MAX_THREAD_DEPTH = 50


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class CommentService:
    """
    Service layer for comment/annotation operations.

    Handles all CRUD operations, search, and thread management for comments
    attached to entities in the knowledge graph.
    """

    def __init__(self, conn: Neo4jConnection) -> None:
        self.conn = conn

    # ── Public API ───────────────────────────────────────────────────────────

    def create_comment(self, comment_data: CommentCreate) -> CommentResponse:
        """
        Create a new comment attached to an entity.

        Parameters
        ----------
        comment_data:
            CommentCreate schema with entity info, content, and metadata.

        Returns
        -------
        CommentResponse with the created comment details.

        Raises
        ------
        ValueError if entity_type is invalid or content is empty.
        """
        comment_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # Extract mentions from content
        mentions = self._extract_mentions(comment_data.content)

        # Build provenance metadata
        provenance = ProvenanceMetadata(
            source=[comment_data.source],
            dataset_version="1.0",
            retrieval_date=now,
            confidence=comment_data.confidence,
        )

        query = """
        CREATE (c:Comment {
            id: $id,
            entity_id: $entity_id,
            entity_type: $entity_type,
            author: $author,
            content: $content,
            parent_comment_id: $parent_comment_id,
            tags: $tags,
            mentions: $mentions,
            is_deleted: false,
            created_at: $created_at,
            edited_at: null,
            source: $source,
            confidence: $confidence,
            provenance: $provenance
        })
        RETURN c
        """

        params = {
            "id": comment_id,
            "entity_id": comment_data.entity_id,
            "entity_type": comment_data.entity_type,
            "author": comment_data.author or "user",
            "content": comment_data.content,
            "parent_comment_id": comment_data.parent_comment_id,
            "tags": comment_data.tags,
            "mentions": mentions,
            "created_at": now.isoformat(),
            "source": comment_data.source,
            "confidence": comment_data.confidence,
            "provenance": provenance.model_dump(),
        }

        result = self.conn.run_query(query, params)
        if not result:
            raise RuntimeError("Failed to create comment")

        logger.info(f"Created comment {comment_id} on {comment_data.entity_type}:{comment_data.entity_id}")

        return self._record_to_response(result[0]["c"])

    def get_comment(self, comment_id: str) -> CommentResponse | None:
        """
        Get a single comment by ID.

        Parameters
        ----------
        comment_id:
            UUID of the comment.

        Returns
        -------
        CommentResponse if found, None otherwise.
        """
        query = """
        MATCH (c:Comment {id: $comment_id})
        RETURN c
        """

        result = self.conn.run_query(query, {"comment_id": comment_id})
        if not result:
            return None

        return self._record_to_response(result[0]["c"])

    def list_comments(self, params: CommentListParams) -> tuple[list[CommentResponse], int]:
        """
        List comments with filtering and pagination.

        Parameters
        ----------
        params:
            CommentListParams with filters, pagination, and sorting.

        Returns
        -------
        Tuple of (list of CommentResponse, total count).
        """
        # Build dynamic query based on filters
        where_clauses = []
        query_params: dict[str, Any] = {}

        if params.entity_id:
            where_clauses.append("c.entity_id = $entity_id")
            query_params["entity_id"] = params.entity_id

        if params.entity_type:
            where_clauses.append("c.entity_type = $entity_type")
            query_params["entity_type"] = params.entity_type

        if params.author:
            where_clauses.append("c.author = $author")
            query_params["author"] = params.author

        if params.tag:
            where_clauses.append("$tag IN c.tags")
            query_params["tag"] = params.tag

        if not params.include_deleted:
            where_clauses.append("c.is_deleted = false")
            query_params["is_deleted"] = False

        if params.parent_comment_id:
            where_clauses.append("c.parent_comment_id = $parent_comment_id")
            query_params["parent_comment_id"] = params.parent_comment_id

        where_clause = " AND ".join(where_clauses) if where_clauses else "true"

        # Count query
        count_query = f"""
        MATCH (c:Comment)
        WHERE {where_clause}
        RETURN count(c) as total
        """

        count_result = self.conn.run_query(count_query, query_params)
        total = count_result[0]["total"] if count_result else 0

        if total == 0:
            return [], 0

        # Data query with pagination and sorting
        sort_direction = "ASC" if params.sort_order == "asc" else "DESC"
        data_query = f"""
        MATCH (c:Comment)
        WHERE {where_clause}
        RETURN c
        ORDER BY c.{params.sort_by} {sort_direction}
        SKIP $offset
        LIMIT $limit
        """

        query_params["offset"] = params.offset
        query_params["limit"] = params.limit

        result = self.conn.run_query(data_query, query_params)
        comments = [self._record_to_response(record["c"]) for record in result]

        # Enrich with reply counts
        comments = self._enrich_with_reply_counts(comments)

        return comments, total

    def update_comment(self, comment_id: str, update_data: CommentUpdate) -> CommentResponse | None:
        """
        Update a comment's content or tags.

        Parameters
        ----------
        comment_id:
            UUID of the comment to update.
        update_data:
            CommentUpdate with fields to update.

        Returns
        -------
        CommentResponse if updated, None if comment not found.

        Raises
        ------
        ValueError if no fields to update.
        """
        if not any([update_data.content, update_data.tags, update_data.is_deleted is not None]):
            raise ValueError("No fields to update")

        # Get current comment
        current = self.get_comment(comment_id)
        if not current:
            return None

        now = datetime.now(UTC)
        set_clauses = []
        params: dict[str, Any] = {"comment_id": comment_id}

        if update_data.content is not None:
            set_clauses.append("c.content = $content")
            params["content"] = update_data.content
            set_clauses.append("c.edited_at = $edited_at")
            params["edited_at"] = now.isoformat()
            # Re-extract mentions if content changed
            mentions = self._extract_mentions(update_data.content)
            set_clauses.append("c.mentions = $mentions")
            params["mentions"] = mentions

        if update_data.tags is not None:
            set_clauses.append("c.tags = $tags")
            params["tags"] = update_data.tags

        if update_data.is_deleted is not None:
            set_clauses.append("c.is_deleted = $is_deleted")
            params["is_deleted"] = update_data.is_deleted

        set_clause = ", ".join(set_clauses)

        query = f"""
        MATCH (c:Comment {{id: $comment_id}})
        SET {set_clause}
        RETURN c
        """

        result = self.conn.run_query(query, params)
        if not result:
            return None

        logger.info(f"Updated comment {comment_id}")

        return self._record_to_response(result[0]["c"])

    def delete_comment(self, comment_id: str) -> bool:
        """
        Soft delete a comment (sets is_deleted flag).

        Parameters
        ----------
        comment_id:
            UUID of the comment to delete.

        Returns
        -------
        True if deleted, False if not found.
        """
        update_data = CommentUpdate(is_deleted=True)
        result = self.update_comment(comment_id, update_data)
        return result is not None

    def hard_delete_comment(self, comment_id: str) -> bool:
        """
        Permanently delete a comment from the database.

        WARNING: This is irreversible. Use soft delete (delete_comment) for normal operations.

        Parameters
        ----------
        comment_id:
            UUID of the comment to permanently delete.

        Returns
        -------
        True if deleted, False if not found.
        """
        query = """
        MATCH (c:Comment {id: $comment_id})
        DETACH DELETE c
        """

        result = self.conn.run_query(query, {"comment_id": comment_id})
        deleted = result[0].get("deleted", 0) if result else 0

        if deleted > 0:
            logger.info(f"Hard deleted comment {comment_id}")

        return deleted > 0

    def search_comments(self, search_params: CommentSearchRequest) -> tuple[list[CommentResponse], int]:
        """
        Full-text search across comments.

        Uses Neo4j full-text index on content field.

        Parameters
        ----------
        search_params:
            CommentSearchRequest with query and filters.

        Returns
        -------
        Tuple of (list of CommentResponse, total count).
        """
        # First, try full-text search if index exists
        ft_query = """
        CALL db.index.fulltext.queryNodes('idx_comment_content', $query)
        YIELD node AS c, score
        WHERE c.is_deleted = false OR $include_deleted = true
        RETURN c, score
        ORDER BY score DESC
        LIMIT $limit
        """

        params = {
            "query": search_params.query,
            "include_deleted": search_params.include_deleted,
            "limit": search_params.limit,
        }

        try:
            result = self.conn.run_query(ft_query, params)
            if result:
                comments = [self._record_to_response(record["c"]) for record in result]
                return comments, len(comments)
        except Exception as e:
            # Fall back to basic text search if full-text index doesn't exist
            logger.warning(f"Full-text search failed, falling back to basic search: {e}")

        # Fallback: basic CONTAINS search
        where_clauses = ["c.content CONTAINS $query"]
        query_params: dict[str, Any] = {"query": search_params.query}

        if search_params.entity_type:
            where_clauses.append("c.entity_type = $entity_type")
            query_params["entity_type"] = search_params.entity_type

        if search_params.entity_id:
            where_clauses.append("c.entity_id = $entity_id")
            query_params["entity_id"] = search_params.entity_id

        if search_params.author:
            where_clauses.append("c.author = $author")
            query_params["author"] = search_params.author

        if search_params.tag:
            where_clauses.append("$tag IN c.tags")
            query_params["tag"] = search_params.tag

        if not search_params.include_deleted:
            where_clauses.append("c.is_deleted = false")

        where_clause = " AND ".join(where_clauses)

        count_query = f"""
        MATCH (c:Comment)
        WHERE {where_clause}
        RETURN count(c) as total
        """

        count_result = self.conn.run_query(count_query, query_params)
        total = count_result[0]["total"] if count_result else 0

        if total == 0:
            return [], 0

        data_query = f"""
        MATCH (c:Comment)
        WHERE {where_clause}
        RETURN c
        ORDER BY c.created_at DESC
        LIMIT $limit
        """

        query_params["limit"] = search_params.limit
        result = self.conn.run_query(data_query, query_params)
        comments = [self._record_to_response(record["c"]) for record in result]

        return comments, total

    def get_comment_threads(self, entity_id: str, entity_type: str, limit: int = 50) -> list[CommentThreadResponse]:
        """
        Get threaded conversations for an entity.

        Returns top-level comments with their replies nested.

        Parameters
        ----------
        entity_id:
            ID of the entity.
        entity_type:
            Type of the entity.
        limit:
            Maximum number of top-level comments to return.

        Returns
        -------
        List of CommentThreadResponse with nested replies.
        """
        # Get top-level comments (no parent)
        top_level_query = """
        MATCH (c:Comment {entity_id: $entity_id, entity_type: $entity_type, parent_comment_id: null})
        WHERE c.is_deleted = false
        RETURN c
        ORDER BY c.created_at DESC
        LIMIT $limit
        """

        result = self.conn.run_query(top_level_query, {"entity_id": entity_id, "entity_type": entity_type, "limit": limit})
        top_level = [self._record_to_response(record["c"]) for record in result]

        threads = []
        for comment in top_level:
            # Get replies for each top-level comment
            replies, _ = self.list_comments(CommentListParams(
                parent_comment_id=comment.id,
                include_deleted=False,
                limit=MAX_THREAD_DEPTH,
                sort_by="created_at",
                sort_order="asc",
            ))

            threads.append(CommentThreadResponse(
                comment=comment,
                replies=replies,
                total_replies=len(replies),
            ))

        return threads

    def get_reply_count(self, comment_id: str) -> int:
        """
        Get the number of direct replies to a comment.

        Parameters
        ----------
        comment_id:
            UUID of the parent comment.

        Returns
        -------
        Count of direct replies.
        """
        query = """
        MATCH (c:Comment {id: $comment_id})<-[:REPLY_TO*]-(reply:Comment)
        WHERE reply.is_deleted = false
        RETURN count(reply) as count
        """

        result = self.conn.run_query(query, {"comment_id": comment_id})
        return result[0]["count"] if result else 0

    # ── Internal Helpers ─────────────────────────────────────────────────────

    def _extract_mentions(self, content: str) -> list[str]:
        """Extract entity mentions from comment content. Wrapper for module-level function."""
        return _extract_mentions(content)

    def _record_to_response(self, record: dict[str, Any]) -> CommentResponse:
        """
        Convert a Neo4j record to a CommentResponse.

        Parameters
        ----------
        record:
            Neo4j node properties dict.

        Returns
        -------
        CommentResponse with parsed fields.
        """
        # Handle provenance if present
        provenance = None
        if "provenance" in record and record["provenance"]:
            prov_data = record["provenance"]
            if isinstance(prov_data, dict):
                try:
                    provenance = ProvenanceMetadata(**prov_data)
                except Exception:
                    pass

        # Parse datetime fields
        created_at = record.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(UTC)
        elif not created_at:
            created_at = datetime.now(UTC)

        edited_at = record.get("edited_at")
        if edited_at and isinstance(edited_at, str):
            try:
                edited_at = datetime.fromisoformat(edited_at.replace("Z", "+00:00"))
            except ValueError:
                edited_at = None

        return CommentResponse(
            id=record.get("id", ""),
            entity_id=record.get("entity_id", ""),
            entity_type=record.get("entity_type", ""),
            author=record.get("author", "user"),
            content=record.get("content", ""),
            parent_comment_id=record.get("parent_comment_id"),
            tags=record.get("tags", []) or [],
            mentions=record.get("mentions", []) or [],
            is_deleted=record.get("is_deleted", False),
            created_at=created_at,
            edited_at=edited_at,
            source=record.get("source", "user"),
            confidence=record.get("confidence", 1.0),
            provenance=provenance,
        )

    def _enrich_with_reply_counts(self, comments: list[CommentResponse]) -> list[CommentResponse]:
        """
        Enrich comments with reply count information.

        Parameters
        ----------
        comments:
            List of CommentResponse to enrich.

        Returns
        -------
        List of CommentResponse with reply_count and has_replies set.
        """
        if not comments:
            return comments

        comment_ids = [c.id for c in comments if c.parent_comment_id is None]
        if not comment_ids:
            return comments

        # Batch count query
        count_query = """
        UNWIND $comment_ids AS parent_id
        MATCH (c:Comment {parent_comment_id: parent_id})
        WHERE c.is_deleted = false
        RETURN parent_id, count(c) as reply_count
        """

        result = self.conn.run_query(count_query, {"comment_ids": comment_ids})
        reply_counts = {record["parent_id"]: record["reply_count"] for record in result}

        # Enrich each comment
        for comment in comments:
            if comment.id in reply_counts:
                comment.reply_count = reply_counts[comment.id]
                comment.has_replies = reply_counts[comment.id] > 0

        return comments


# ─────────────────────────────────────────────────────────────────────────────
# Convenience Functions
# ─────────────────────────────────────────────────────────────────────────────

def get_comment_service() -> CommentService:
    """Get a CommentService instance using the default Neo4j connection."""
    from paladino.db import Neo4jConnection
    conn = Neo4jConnection()
    return CommentService(conn)
