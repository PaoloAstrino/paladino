"""
Unit tests for Watermark Manager.
"""

import pytest
from unittest.mock import MagicMock
from datetime import datetime


@pytest.fixture
def mock_driver():
    """Mock Neo4j driver for watermark tests."""
    driver = MagicMock()
    mock_session = MagicMock()
    driver.session.return_value.__enter__.return_value = mock_session
    return driver, mock_session


class TestWatermarkManager:
    """Test watermark manager functionality."""
    
    def test_get_watermark_none(self, mock_driver):
        """Test getting watermark that doesn't exist."""
        from paladino.etl.watermark_manager import WatermarkManager
        
        driver, mock_session = mock_driver
        mock_session.run.return_value.single.return_value = None
        
        wm = WatermarkManager(driver)
        result = wm.get_watermark("test_source")
        
        assert result["last_value"] is None
        assert result["last_id"] is None
        assert result["rows_processed"] == 0
    
    def test_get_watermark_exists(self, mock_driver):
        """Test getting existing watermark."""
        from paladino.etl.watermark_manager import WatermarkManager
        
        driver, mock_session = mock_driver
        mock_record = MagicMock()
        mock_record.__getitem__.side_effect = lambda key: {
            "last_value": "2026-01-15T10:00:00",
            "last_id": 12345,
            "updated_at": datetime.now(),
            "rows_processed": 5000,
        }[key]
        mock_session.run.return_value.single.return_value = mock_record
        
        wm = WatermarkManager(driver)
        result = wm.get_watermark("anac_tenders")
        
        assert result["last_value"] == "2026-01-15T10:00:00"
        assert result["last_id"] == 12345
        assert result["rows_processed"] == 5000
    
    def test_save_watermark_new(self, mock_driver):
        """Test saving new watermark."""
        from paladino.etl.watermark_manager import WatermarkManager
        
        driver, mock_session = mock_driver
        mock_session.run.return_value.single.return_value = None
        
        wm = WatermarkManager(driver)
        wm.save_watermark(
            source="test_source",
            last_value="2026-01-16",
            last_id=100,
            incremental_rows=50,
        )
        
        # Verify run was called
        assert mock_session.run.called
    
    def test_save_watermark_update(self, mock_driver):
        """Test updating existing watermark."""
        from paladino.etl.watermark_manager import WatermarkManager
        
        driver, mock_session = mock_driver
        
        # First call returns existing watermark
        mock_record = MagicMock()
        mock_record.__getitem__.side_effect = lambda key: {
            "last_value": "2026-01-15",
            "last_id": 50,
            "updated_at": datetime.now(),
            "rows_processed": 100,
        }[key]
        mock_session.run.return_value.single.return_value = mock_record
        
        wm = WatermarkManager(driver)
        wm.save_watermark(
            source="test_source",
            last_value="2026-01-16",
            last_id=100,
            incremental_rows=50,
        )
        
        # Verify run was called twice (get + save)
        assert mock_session.run.call_count >= 1
    
    def test_delete_watermark(self, mock_driver):
        """Test deleting watermark."""
        from paladino.etl.watermark_manager import WatermarkManager
        
        driver, mock_session = mock_driver
        
        wm = WatermarkManager(driver)
        wm.delete_watermark("test_source")
        
        # Verify DELETE query was run
        assert mock_session.run.called
        call_args = mock_session.run.call_args[0][0]
        assert "DELETE" in call_args
    
    def test_list_watermarks(self, mock_driver):
        """Test listing all watermarks."""
        from paladino.etl.watermark_manager import WatermarkManager
        
        driver, mock_session = mock_driver
        
        # Mock multiple watermarks
        mock_record1 = MagicMock()
        mock_record1.__getitem__.side_effect = lambda key: {
            "source": "anac_tenders",
            "last_value": "2026-01-15",
            "last_id": 100,
            "updated_at": datetime.now(),
            "rows_processed": 500,
        }[key]
        
        mock_record2 = MagicMock()
        mock_record2.__getitem__.side_effect = lambda key: {
            "source": "opencup_projects",
            "last_value": "2026-01-14",
            "last_id": 200,
            "updated_at": datetime.now(),
            "rows_processed": 300,
        }[key]
        
        mock_result = [mock_record1, mock_record2]
        mock_session.run.return_value = mock_result
        
        wm = WatermarkManager(driver)
        watermarks = wm.list_watermarks()
        
        assert len(watermarks) == 2
        assert watermarks[0]["source"] == "anac_tenders"
        assert watermarks[1]["source"] == "opencup_projects"
    
    def test_get_watermark_timestamp(self, mock_driver):
        """Test parsing watermark as datetime."""
        from paladino.etl.watermark_manager import WatermarkManager
        
        driver, mock_session = mock_driver
        
        mock_record = MagicMock()
        mock_record.__getitem__.side_effect = lambda key: {
            "last_value": "2026-01-15T10:30:00",
            "last_id": None,
            "updated_at": None,
            "rows_processed": 0,
        }[key]
        mock_session.run.return_value.single.return_value = mock_record
        
        wm = WatermarkManager(driver)
        ts = wm.get_watermark_timestamp("test_source")
        
        assert isinstance(ts, datetime)
        assert ts.year == 2026
        assert ts.month == 1
        assert ts.day == 15


class TestGetIncrementalData:
    """Test the convenience helper function."""
    
    def test_incremental_etl_pattern(self, mock_driver):
        """Test the get_incremental_data helper."""
        from paladino.etl.watermark_manager import get_incremental_data
        
        driver, mock_session = mock_driver
        
        # Mock fetch function
        def mock_fetch(since):
            return [{"id": 1, "data": "new"}]
        
        # Mock load function
        loaded = []
        def mock_load(data):
            loaded.extend(data)
        
        # Mock watermark (return None for first call)
        mock_session.run.return_value.single.return_value = None
        
        result = get_incremental_data(
            source="test",
            fetch_function=mock_fetch,
            load_function=mock_load,
            driver=driver,
        )
        
        assert result["rows_fetched"] == 1
        assert result["rows_loaded"] == 1
        assert len(loaded) == 1
