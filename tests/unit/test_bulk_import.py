"""
Unit tests for Bulk Import API endpoint.
"""

import pytest
from io import BytesIO


class TestBulkImport:
    """Test bulk import endpoint."""
    
    def test_bulk_import_missing_file(self):
        """Test bulk import without file returns error."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        client = TestClient(app)
        
        # Missing file should fail
        response = client.post(
            "/ingest/bulk",
            data={"target": "company"},
        )
        # FastAPI will return 422 for missing required file
        assert response.status_code == 422
    
    def test_bulk_import_invalid_target(self, tmp_path):
        """Test bulk import with invalid target type."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        # Create test CSV
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("cf,name\n12345678901,Test SRL\n")
        
        client = TestClient(app)
        
        with open(csv_file, 'rb') as f:
            response = client.post(
                "/ingest/bulk",
                files={"file": ("test.csv", f, "text/csv")},
                data={"target": "invalid", "dry_run": "true"},
            )
        
        assert response.status_code == 400
        assert "Invalid target" in response.json()["detail"]
    
    def test_bulk_import_missing_columns(self, tmp_path):
        """Test bulk import with missing required columns."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        # Create test CSV with missing columns
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("vat_id,company_name\n12345678901,Test SRL\n")
        
        client = TestClient(app)
        
        with open(csv_file, 'rb') as f:
            response = client.post(
                "/ingest/bulk",
                files={"file": ("test.csv", f, "text/csv")},
                data={"target": "company", "dry_run": "true"},
            )
        
        assert response.status_code == 400
        assert "Missing required columns" in response.json()["detail"]
    
    def test_bulk_import_valid_csv(self, tmp_path):
        """Test bulk import with valid CSV file."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        # Create valid test CSV
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("cf,name\n12345678901,TEST SRL\n12345678902,ENEL SPA\n")
        
        client = TestClient(app)
        
        with open(csv_file, 'rb') as f:
            response = client.post(
                "/ingest/bulk",
                files={"file": ("test.csv", f, "text/csv")},
                data={"target": "company", "dry_run": "true"},
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["rows_processed"] == 2
        assert data["rows_valid"] == 2
        assert data["dry_run"] is True
        assert "preview" in data
    
    def test_bulk_import_invalid_cf(self, tmp_path):
        """Test bulk import with invalid CF format."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        # Create CSV with invalid CF
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("cf,name\n123,Test SRL\n")  # CF too short
        
        client = TestClient(app)
        
        with open(csv_file, 'rb') as f:
            response = client.post(
                "/ingest/bulk",
                files={"file": ("test.csv", f, "text/csv")},
                data={"target": "company", "dry_run": "true"},
            )
        
        assert response.status_code == 200
        data = response.json()
        assert data["rows_invalid"] == 1
        assert "Invalid CF" in str(data["errors"])
    
    def test_bulk_import_unsupported_file(self, tmp_path):
        """Test bulk import with unsupported file type."""
        from fastapi.testclient import TestClient
        from paladino.app.api import app
        
        # Create unsupported file
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("some text")
        
        client = TestClient(app)
        
        with open(txt_file, 'rb') as f:
            response = client.post(
                "/ingest/bulk",
                files={"file": ("test.txt", f, "text/plain")},
                data={"target": "company", "dry_run": "true"},
            )
        
        assert response.status_code == 400
        assert "Unsupported file type" in response.json()["detail"]
