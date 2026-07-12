"""
Unit tests for Entity Merge/Deduplication API endpoints.

NOTE: Since the API uses lazy imports (imports inside functions),
we must patch 'paladino.etl.deduplicator.EntityDeduplicator', NOT 'paladino.app.api.EntityDeduplicator'.
"""

import pytest
from unittest.mock import MagicMock, patch
from paladino.app.security import _rate_limiter


class TestMergeEndpoints:
    """Test merge/deduplication API endpoints."""

    def setup_method(self):
        """Reset rate limiter before each test to avoid 429 errors."""
        _rate_limiter._requests.clear()

    def test_find_duplicates_success(self):
        """Test /companies/duplicates endpoint with valid request."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app

        # Mock deduplicator
        mock_dedup = MagicMock()
        mock_dedup.find_candidates_for_entity.return_value = [
            {
                "entity_id": "2",
                "cf": "12345678901",
                "piva": None,
                "nome_normalizzato": "ACME SRL",
                "similarity_score": 0.95,
                "match_reason": "fuzzy_name_match",
                "properties": {"regione": "Lombardia"},
            }
        ]

        # Patch the actual import location (lazy imports inside functions)
        with patch("paladino.etl.deduplicator.EntityDeduplicator") as mock_cls:
            mock_cls.return_value = mock_dedup

            client = TestClient(app)
            response = client.post(
                "/companies/duplicates",
                json={"entity_id": "12345678901", "limit": 10, "min_similarity": 0.75},
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["similarity_score"] == 0.95
            assert data[0]["match_reason"] == "fuzzy_name_match"
    
    def test_find_duplicates_empty(self):
        """Test /companies/duplicates with no duplicates found."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app

        mock_dedup = MagicMock()
        mock_dedup.find_candidates_for_entity.return_value = []

        # Patch the actual import location (lazy imports inside functions)
        with patch("paladino.etl.deduplicator.EntityDeduplicator") as mock_cls:
            mock_cls.return_value = mock_dedup

            client = TestClient(app)
            response = client.post(
                "/companies/duplicates",
                json={"entity_id": "nonexistent", "limit": 10},
            )

            assert response.status_code == 200
            data = response.json()
            assert data == []

    def test_merge_dry_run(self):
        """Test /companies/merge with dry_run=True."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app

        mock_dedup = MagicMock()
        mock_dedup.merge_with_rollback.return_value = {
            "status": "dry_run",
            "target_id": "1",
            "source_ids": ["2", "3"],
            "properties_to_merge": {},
            "relationships_to_update": 5,
            "rollback_id": None,
        }

        # Patch the actual import location (lazy imports inside functions)
        with patch("paladino.etl.deduplicator.EntityDeduplicator") as mock_cls:
            mock_cls.return_value = mock_dedup

            client = TestClient(app)
            response = client.post(
                "/companies/merge",
                json={
                    "source_ids": ["2", "3"],
                    "target_id": "1",
                    "dry_run": True,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "dry_run"
            assert data["rollback_id"] is None

    def test_merge_execute(self):
        """Test /companies/merge with dry_run=False."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app

        mock_dedup = MagicMock()
        mock_dedup.merge_with_rollback.return_value = {
            "status": "success",
            "merged_count": 2,
            "target_id": "1",
            "source_ids": ["2", "3"],
            "relationships_to_update": 5,
            "rollback_id": "merge_2026-04-01_abc123",
        }

        # Patch the actual import location (lazy imports inside functions)
        with patch("paladino.etl.deduplicator.EntityDeduplicator") as mock_cls:
            mock_cls.return_value = mock_dedup

            client = TestClient(app)
            response = client.post(
                "/companies/merge",
                json={
                    "source_ids": ["2", "3"],
                    "target_id": "1",
                    "dry_run": False,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["merged_count"] == 2
            assert data["rollback_id"] == "merge_2026-04-01_abc123"

    def test_rollback_merge(self):
        """Test /companies/merge/rollback endpoint."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app

        mock_dedup = MagicMock()
        mock_dedup.rollback_merge.return_value = {"sources_restored": 2}

        # Patch the actual import location (lazy imports inside functions)
        with patch("paladino.etl.deduplicator.EntityDeduplicator") as mock_cls:
            mock_cls.return_value = mock_dedup

            client = TestClient(app)
            response = client.post(
                "/companies/merge/rollback?rollback_id=merge_2026-04-01_abc123",
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert data["sources_restored"] == 2

    def test_merge_history(self):
        """Test /companies/merge/history endpoint."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app

        mock_dedup = MagicMock()
        mock_dedup.get_merge_history.return_value = [
            {
                "rollback_id": "merge_2026-04-01_abc123",
                "created_at": "2026-04-01T10:00:00",
                "target_id": "1",
                "source_ids": ["2", "3"],
                "status": "COMPLETED",
                "merged_count": 2,
            }
        ]

        # Patch the actual import location (lazy imports inside functions)
        with patch("paladino.etl.deduplicator.EntityDeduplicator") as mock_cls:
            mock_cls.return_value = mock_dedup

            client = TestClient(app)
            response = client.get("/companies/merge/history?limit=10")

            assert response.status_code == 200
            data = response.json()
            assert "merges" in data
            assert data["count"] == 1
            assert len(data["merges"]) == 1


class TestMergeModels:
    """Test Pydantic models for merge functionality."""
    
    def test_merge_candidate_model(self):
        """Test MergeCandidate model validation."""
        from paladino.models import MergeCandidate
        
        candidate = MergeCandidate(
            entity_id="123",
            cf="12345678901",
            piva=None,
            nome_normalizzato="ACME SRL",
            similarity_score=0.95,
            match_reason="fuzzy_name_match",
            properties={"regione": "Lombardia"},
        )
        
        assert candidate.entity_id == "123"
        assert candidate.cf == "12345678901"
        assert candidate.piva is None
        assert candidate.similarity_score == 0.95
    
    def test_merge_review_request_validation(self):
        """Test MergeReviewRequest validation."""
        from paladino.models import MergeReviewRequest
        
        # Valid request
        request = MergeReviewRequest(
            entity_id="123",
            limit=20,
            min_similarity=0.75,
        )
        assert request.limit == 20
        assert request.min_similarity == 0.75
        
        # Limit too high
        with pytest.raises(Exception):
            MergeReviewRequest(entity_id="123", limit=200)
        
        # Invalid similarity
        with pytest.raises(Exception):
            MergeReviewRequest(entity_id="123", min_similarity=1.5)
    
    def test_merge_execute_request(self):
        """Test MergeExecuteRequest model."""
        from paladino.models import MergeExecuteRequest
        
        request = MergeExecuteRequest(
            source_ids=["2", "3"],
            target_id="1",
            dry_run=True,
        )
        
        assert request.source_ids == ["2", "3"]
        assert request.target_id == "1"
        assert request.dry_run is True
        
        # Empty source_ids should fail
        with pytest.raises(Exception):
            MergeExecuteRequest(source_ids=[], target_id="1")
    
    def test_merge_response_model(self):
        """Test MergeResponse model."""
        from paladino.models import MergeResponse
        
        response = MergeResponse(
            status="success",
            merged_count=2,
            target_id="1",
            source_ids=["2", "3"],
            properties_merged={},
            relationships_updated=5,
            rollback_id="merge_2026-04-01_abc123",
        )
        
        assert response.status == "success"
        assert response.merged_count == 2
        assert response.rollback_id == "merge_2026-04-01_abc123"
