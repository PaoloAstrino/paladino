"""
Unit tests for Data Lineage endpoint.
"""

import pytest
from unittest.mock import MagicMock


class TestLineageEndpoint:
    """Test data lineage endpoint."""
    
    def test_lineage_entity_not_found(self):
        """Test lineage for non-existent entity."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.run.return_value.single.return_value = None
        
        from paladino.db import get_driver
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("paladino.app.api.get_driver", lambda: mock_driver)
            client = TestClient(app)
            
            response = client.get("/lineage/nonexistent123")
            
            assert response.status_code == 404
    
    def test_lineage_basic(self):
        """Test basic lineage query."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        from datetime import datetime
        
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        
        # Mock entity record
        mock_entity = MagicMock()
        mock_entity.__getitem__.side_effect = lambda key: {
            "e": {"id": "123", "cf": "12345678901", "provenance": {
                "source": ["ANAC", "OpenCUP"],
                "confidence": 0.95,
                "dataset_version": "2026-01",
                "retrieval_date": datetime.now(),
            }},
            "entity_types": ["Company"],
        }[key]
        
        # Mock lineage record
        mock_lineage = MagicMock()
        mock_lineage.__getitem__.side_effect = lambda key: {
            "paths": [],
            "direct_sources": [],
        }[key]
        
        mock_session.run.return_value.single.side_effect = [mock_entity, mock_lineage]
        
        from paladino.db import get_driver
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("paladino.app.api.get_driver", lambda: mock_driver)
            client = TestClient(app)
            
            response = client.get("/lineage/12345678901")
            
            assert response.status_code == 200
            data = response.json()
            assert data["entity_id"] == "12345678901"
            assert data["entity_type"] == "Company"
            assert "ANAC" in data["sources"]
            assert data["confidence"] == 0.95
    
    def test_lineage_with_paths(self):
        """Test lineage with transformation paths."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        from datetime import datetime
        
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        
        # Mock entity record
        mock_entity = MagicMock()
        mock_entity.__getitem__.side_effect = lambda key: {
            "e": {"id": "123", "provenance": {}},
            "entity_types": ["Tender"],
        }[key]
        
        # Mock lineage with paths
        mock_lineage = MagicMock()
        mock_lineage.__getitem__.side_effect = lambda key: {
            "paths": [
                [
                    {"id": "ds1", "labels": ["DataSource"], "name": "ANAC"},
                    {"id": "t1", "labels": ["Transformation"], "name": "ETL"},
                ]
            ],
            "direct_sources": ["ANAC"],
        }[key]
        
        mock_session.run.return_value.single.side_effect = [mock_entity, mock_lineage]
        
        from paladino.db import get_driver
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("paladino.app.api.get_driver", lambda: mock_driver)
            client = TestClient(app)
            
            response = client.get("/lineage/123")
            
            assert response.status_code == 200
            data = response.json()
            assert data["path_count"] >= 0
            assert "ANAC" in data["sources"]
