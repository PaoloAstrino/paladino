"""
Unit tests for Entity Search API endpoint.

Tests the /search endpoint with fuzzy matching capabilities.
"""

import pytest
from unittest.mock import MagicMock, patch


def _create_mock_driver():
    """Helper to create mock Neo4j driver."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session
    
    sample_companies = [
        {"id": "1", "name": "TELECOM ITALIA SPA", "cf": "00488410010", "address": "Roma", "risk_score": 0.5, "community_id": 1},
        {"id": "2", "name": "ENEL SPA", "cf": "00934061003", "address": "Roma", "risk_score": 0.3, "community_id": 1},
        {"id": "3", "name": "GENERALI ASSICURAZIONI SPA", "cf": "00008230323", "address": "Trieste", "risk_score": 0.4, "community_id": 2},
        {"id": "4", "name": "INTESA SANPAOLO SPA", "cf": "00513440016", "address": "Torino", "risk_score": 0.6, "community_id": 1},
        {"id": "5", "name": "UNICREDIT SPA", "cf": "00348170101", "address": "Milano", "risk_score": 0.55, "community_id": 1},
    ]
    
    mock_result = MagicMock()
    mock_result.__iter__.return_value = sample_companies
    mock_session.run.return_value = mock_result
    
    return mock_driver


class TestEntitySearch:
    """Test entity search endpoint."""
    
    def test_search_company_exact_match(self):
        """Test search with exact company name match."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        mock_driver = _create_mock_driver()
        
        with patch("paladino.app.api.get_driver", return_value=mock_driver):
            client = TestClient(app)
            response = client.post(
                "/search",
                json={
                    "query": "TELECOM",
                    "target": "company",
                    "limit": 10,
                    "min_similarity": 0.5
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert "results" in data
            assert "count" in data
            assert "search_time_ms" in data
            assert data["query"] == "TELECOM"
            assert data["target"] == "company"
    
    def test_search_company_fuzzy_match(self):
        """Test search with typo/fuzzy match."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        mock_driver = _create_mock_driver()
        
        with patch("paladino.app.api.get_driver", return_value=mock_driver):
            client = TestClient(app)
            response = client.post(
                "/search",
                json={
                    "query": "Telefonica",  # Similar to TELECOM
                    "target": "company",
                    "limit": 10,
                    "min_similarity": 0.4
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert data["count"] >= 0  # May or may not find matches depending on similarity
    
    def test_search_with_high_similarity_threshold(self):
        """Test search with high similarity threshold."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        mock_driver = _create_mock_driver()
        
        with patch("paladino.app.api.get_driver", return_value=mock_driver):
            client = TestClient(app)
            response = client.post(
                "/search",
                json={
                    "query": "ENEL",
                    "target": "company",
                    "limit": 10,
                    "min_similarity": 0.9  # Very high threshold
                }
            )
            assert response.status_code == 200
            data = response.json()
            # Results should have high similarity scores
            for result in data["results"]:
                assert result["similarity_score"] >= 0.9
    
    def test_search_invalid_target(self):
        """Test search with invalid target type."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        client = TestClient(app)
        response = client.post(
            "/search",
            json={
                "query": "test",
                "target": "invalid",
                "limit": 10
            }
        )
        assert response.status_code == 422  # Validation error
    
    def test_search_empty_query(self):
        """Test search with empty query."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        client = TestClient(app)
        response = client.post(
            "/search",
            json={
                "query": "",
                "target": "company",
                "limit": 10
            }
        )
        assert response.status_code == 422  # Validation error
    
    def test_search_limit_validation(self):
        """Test search with invalid limit."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        client = TestClient(app)
        response = client.post(
            "/search",
            json={
                "query": "test",
                "target": "company",
                "limit": 1000  # Above max
            }
        )
        assert response.status_code == 422  # Validation error
    
    def test_search_min_similarity_validation(self):
        """Test search with invalid min_similarity."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        client = TestClient(app)
        response = client.post(
            "/search",
            json={
                "query": "test",
                "target": "company",
                "min_similarity": 1.5  # Above max
            }
        )
        assert response.status_code == 422  # Validation error
    
    def test_search_results_sorted_by_similarity(self):
        """Test that results are sorted by similarity score descending."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        mock_driver = _create_mock_driver()
        
        with patch("paladino.app.api.get_driver", return_value=mock_driver):
            client = TestClient(app)
            response = client.post(
                "/search",
                json={
                    "query": "SPA",
                    "target": "company",
                    "limit": 10,
                    "min_similarity": 0.3
                }
            )
            assert response.status_code == 200
            data = response.json()
            
            if len(data["results"]) > 1:
                scores = [r["similarity_score"] for r in data["results"]]
                assert scores == sorted(scores, reverse=True)
    
    def test_search_returns_similarity_scores(self):
        """Test that each result includes similarity score."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        mock_driver = _create_mock_driver()
        
        with patch("paladino.app.api.get_driver", return_value=mock_driver):
            client = TestClient(app)
            response = client.post(
                "/search",
                json={
                    "query": "TEST",
                    "target": "company",
                    "limit": 10,
                    "min_similarity": 0.3
                }
            )
            assert response.status_code == 200
            data = response.json()
            
            for result in data["results"]:
                assert "similarity_score" in result
                assert 0.0 <= result["similarity_score"] <= 1.0


class TestEntitySearchIntegration:
    """Integration tests for entity search (requires rapidfuzz)."""
    
    def test_rapidfuzz_fuzzy_matching(self):
        """Test rapidfuzz fuzzy matching logic directly."""
        from rapidfuzz import fuzz
        
        # Test exact match
        assert fuzz.ratio("TELECOM", "TELECOM") == 100
        
        # Test partial match
        assert fuzz.partial_ratio("TELECOM", "TELECOM ITALIA") > 50
        
        # Test typo tolerance
        score = fuzz.WRatio("Telefonica", "TELECOM")
        assert score > 0
        
        # Test token-based matching
        assert fuzz.token_sort_ratio("SPA ENEL", "ENEL SPA") > 80
    
    def test_search_response_model(self):
        """Test search response model validation."""
        from paladino.app.api import EntitySearchResponse
        
        response = EntitySearchResponse(
            query="test",
            target="company",
            results=[
                {"id": "1", "name": "Test SPA", "similarity_score": 0.95}
            ],
            count=1,
            search_time_ms=15.5
        )
        
        assert response.query == "test"
        assert response.target == "company"
        assert response.count == 1
        assert len(response.results) == 1
