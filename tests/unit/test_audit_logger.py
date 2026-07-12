"""
Unit tests for Audit Logger.
"""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestAuditLogger:
    """Test audit logging functionality."""
    
    def test_audit_logger_initialization(self):
        """Test audit logger initializes correctly."""
        from paladino.app.audit_logger import AuditLogger
        
        logger = AuditLogger()
        assert logger.enabled is True
        assert logger.retention_days == 90
    
    def test_log_request(self, tmp_path):
        """Test request logging creates proper audit entry."""
        from paladino.app.audit_logger import AuditLogger
        
        # Create temp directory for logs
        log_dir = tmp_path / "audit_logs"
        
        with patch("paladino.app.audit_logger.settings") as mock_settings:
            mock_settings.enable_audit_logging = True
            mock_settings.audit_retention_days = 90
            mock_settings.audit_log_to_file = True
            mock_settings.audit_log_to_db = False
            mock_settings.audit_log_dir = log_dir
            
            logger = AuditLogger()
            
            # Log a request
            logger.log_request(
                endpoint="/query",
                method="POST",
                status=200,
                duration_ms=150.5,
                user_id="user123",
                ip_address="192.168.1.100",
                request_id="test-request-123",
            )
            
            # Verify log file was created
            log_file = log_dir / "audit.log"
            assert log_file.exists()
            
            # Verify log content
            content = log_file.read_text()
            assert "api_request" in content
            assert "/query" in content
            assert "user123" not in content  # Should be anonymized
            assert "192.168.***.***" in content  # IP should be masked
    
    def test_anonymize(self):
        """Test data anonymization."""
        from paladino.app.audit_logger import AuditLogger
        
        logger = AuditLogger()
        
        # Test anonymization
        assert logger._anonymize("user123") == "user***"
        assert logger._anonymize("ab") == "***"
        assert logger._anonymize("1234567890") == "1234***"
    
    def test_mask_ip(self):
        """Test IP address masking."""
        from paladino.app.audit_logger import AuditLogger
        
        logger = AuditLogger()
        
        assert logger._mask_ip("192.168.1.100") == "192.168.***.***"
        assert logger._mask_ip("10.0.0.1") == "10.0.***.***"
        assert logger._mask_ip(None) is None
    
    def test_hash_params(self):
        """Test parameter hashing."""
        from paladino.app.audit_logger import AuditLogger
        
        logger = AuditLogger()
        
        params = {"query": "test", "limit": 10}
        hash1 = logger._hash_params(params)
        hash2 = logger._hash_params(params)
        
        # Same params should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 16  # 16 char hex hash
    
    def test_log_query(self, tmp_path):
        """Test query logging."""
        from paladino.app.audit_logger import AuditLogger
        
        log_dir = tmp_path / "audit_logs"
        
        with patch("paladino.app.audit_logger.settings") as mock_settings:
            mock_settings.enable_audit_logging = True
            mock_settings.audit_retention_days = 90
            mock_settings.audit_log_to_file = True
            mock_settings.audit_log_to_db = False
            mock_settings.audit_log_dir = log_dir
            
            logger = AuditLogger()
            
            logger.log_query(
                query_type="natural_language",
                cypher_hash="abc123",
                result_count=10,
                user_id="user456",
                request_id="query-123",
                duration_ms=50.0,
            )
            
            # Verify log file
            log_file = log_dir / "audit.log"
            content = log_file.read_text()
            assert "database_query" in content
            assert "natural_language" in content
            assert "abc123" in content
    
    def test_log_data_access(self, tmp_path):
        """Test sensitive data access logging."""
        from paladino.app.audit_logger import AuditLogger
        
        log_dir = tmp_path / "audit_logs"
        
        with patch("paladino.app.audit_logger.settings") as mock_settings:
            mock_settings.enable_audit_logging = True
            mock_settings.audit_retention_days = 90
            mock_settings.audit_log_to_file = True
            mock_settings.audit_log_to_db = False
            mock_settings.audit_log_dir = log_dir
            
            logger = AuditLogger()
            
            logger.log_data_access(
                entity_type="Company",
                entity_id="12345678901",
                access_type="read",
                user_id="user789",
                request_id="access-123",
            )
            
            # Verify log file
            log_file = log_dir / "audit.log"
            content = log_file.read_text()
            assert "data_access" in content
            assert "Company" in content
            # Entity ID should be anonymized
            assert "1234***" in content
    
    def test_audit_disabled(self):
        """Test that logging is skipped when disabled."""
        from paladino.app.audit_logger import AuditLogger
        
        with patch("paladino.app.audit_logger.settings") as mock_settings:
            mock_settings.enable_audit_logging = False
            
            logger = AuditLogger()
            assert logger.enabled is False
            
            # Should not raise, just do nothing
            logger.log_request(
                endpoint="/test",
                method="GET",
                status=200,
                duration_ms=10,
            )
    
    def test_get_audit_logs_empty(self):
        """Test retrieving audit logs (empty result for now)."""
        from paladino.app.audit_logger import AuditLogger
        
        logger = AuditLogger()
        logs = logger.get_audit_logs(limit=100)
        assert logs == []  # Placeholder returns empty


class TestAuditLoggerIntegration:
    """Integration tests for audit logger."""
    
    def test_json_log_format(self, tmp_path):
        """Test that logs are valid JSON."""
        from paladino.app.audit_logger import AuditLogger
        
        log_dir = tmp_path / "audit_logs"
        
        with patch("paladino.app.audit_logger.settings") as mock_settings:
            mock_settings.enable_audit_logging = True
            mock_settings.audit_retention_days = 90
            mock_settings.audit_log_to_file = True
            mock_settings.audit_log_to_db = False
            mock_settings.audit_log_dir = log_dir
            
            logger = AuditLogger()
            
            logger.log_request(
                endpoint="/test",
                method="GET",
                status=200,
                duration_ms=10.5,
                user_id="test_user",
            )
            
            # Parse log file as JSON lines
            log_file = log_dir / "audit.log"
            for line in log_file.read_text().strip().split('\n'):
                if line:
                    entry = json.loads(line)
                    assert "timestamp" in entry
                    assert "event_type" in entry
                    assert "endpoint" in entry


# Fix method names to match the class
@pytest.fixture
def audit_logger_for_test(tmp_path):
    """Create audit logger with temp log directory."""
    from paladino.app.audit_logger import AuditLogger
    
    log_dir = tmp_path / "audit_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    with patch("paladino.app.audit_logger.settings") as mock_settings:
        mock_settings.enable_audit_logging = True
        mock_settings.audit_retention_days = 90
        mock_settings.audit_log_to_file = True
        mock_settings.audit_log_to_db = False
        mock_settings.audit_log_dir = log_dir
        
        logger = AuditLogger()
        yield logger, log_dir
