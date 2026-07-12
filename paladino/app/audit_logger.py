"""
Centralized Audit Logger for Paladino API.

This module provides comprehensive audit logging for compliance and debugging:
- Logs all API requests with user, endpoint, duration, status
- Supports file-based logging with rotation
- Optional Neo4j storage for queryable audit trail
- GDPR-compliant (anonymizes sensitive data)

Usage:
    from paladino.app.audit_logger import audit_logger
    
    audit_logger.log_request(
        user_id="user123",
        endpoint="/query",
        method="POST",
        status=200,
        duration_ms=150.5,
        ip_address="192.168.1.1",
    )
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from paladino.config import settings


class AuditLogger:
    """Centralized audit logger with file and database storage."""
    
    def __init__(self):
        self.enabled = getattr(settings, 'enable_audit_logging', True)
        self.retention_days = getattr(settings, 'audit_retention_days', 90)
        self.log_to_file = getattr(settings, 'audit_log_to_file', True)
        self.log_to_db = getattr(settings, 'audit_log_to_db', False)
        
        # Setup file handler with rotation
        if self.log_to_file:
            self.log_dir = Path(settings.audit_log_dir) if hasattr(settings, 'audit_log_dir') else Path('logs/audit')
            self.log_dir.mkdir(parents=True, exist_ok=True)
            
            # Configure structured JSON logging
            self.file_logger = logging.getLogger('paladino.audit')
            self.file_logger.setLevel(logging.INFO)
            
            # File handler with rotation
            from logging.handlers import RotatingFileHandler
            handler = RotatingFileHandler(
                self.log_dir / 'audit.log',
                maxBytes=10*1024*1024,  # 10 MB
                backupCount=10,
                encoding='utf-8'
            )
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.file_logger.addHandler(handler)
        else:
            self.file_logger = None
    
    def log_request(
        self,
        endpoint: str,
        method: str,
        status: int,
        duration_ms: float,
        user_id: str | None = None,
        api_key_hash: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        params: dict | None = None,
        error: str | None = None,
    ):
        """
        Log an API request for audit trail.
        
        Args:
            endpoint: API endpoint path
            method: HTTP method
            status: HTTP status code
            duration_ms: Request duration in milliseconds
            user_id: Anonymized user identifier
            api_key_hash: Hash of API key (first 8 chars)
            ip_address: Client IP address
            user_agent: Client user agent
            request_id: Request tracing ID
            params: Request parameters (sanitized)
            error: Error message if failed
        """
        if not self.enabled:
            return
        
        audit_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': 'api_request',
            'endpoint': endpoint,
            'method': method,
            'status': status,
            'duration_ms': round(duration_ms, 2),
            'user_id': self._anonymize(user_id) if user_id else None,
            'api_key_hash': api_key_hash,
            'ip_address': self._mask_ip(ip_address) if ip_address else None,
            'user_agent': user_agent,
            'request_id': request_id,
            'params_hash': self._hash_params(params) if params else None,
            'error': error,
        }
        
        # Log to file
        if self.file_logger:
            self.file_logger.info(json.dumps(audit_entry, ensure_ascii=False))
        
        # Log to database (optional)
        if self.log_to_db:
            self._log_to_neo4j(audit_entry)
        
        # Also log to structured audit log via loguru
        logger.bind(audit=True).info(f"AUDIT: {json.dumps(audit_entry)}")
    
    def log_query(
        self,
        query_type: str,
        cypher_hash: str | None = None,
        result_count: int = 0,
        template_name: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
        duration_ms: float = 0,
    ):
        """
        Log a database query for audit trail.
        
        Args:
            query_type: Type of query (natural_language, template, export, search)
            cypher_hash: Hash of Cypher query (for audit without storing full query)
            result_count: Number of results returned
            template_name: Name of template if template query
            user_id: Anonymized user identifier
            request_id: Request tracing ID
            duration_ms: Query execution time
        """
        if not self.enabled:
            return
        
        audit_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': 'database_query',
            'query_type': query_type,
            'cypher_hash': cypher_hash,
            'result_count': result_count,
            'template_name': template_name,
            'user_id': self._anonymize(user_id) if user_id else None,
            'request_id': request_id,
            'duration_ms': round(duration_ms, 2),
        }
        
        # Log to file
        if self.file_logger:
            self.file_logger.info(json.dumps(audit_entry, ensure_ascii=False))
        
        # Log to structured audit log
        logger.bind(audit=True).info(f"AUDIT_QUERY: {json.dumps(audit_entry)}")
    
    def log_data_access(
        self,
        entity_type: str,
        entity_id: str,
        access_type: str,
        user_id: str | None = None,
        request_id: str | None = None,
    ):
        """
        Log access to sensitive data (GDPR compliance).
        
        Args:
            entity_type: Type of entity accessed (Company, Person, etc.)
            entity_id: Entity identifier
            access_type: Type of access (read, update, delete)
            user_id: Anonymized user identifier
            request_id: Request tracing ID
        """
        if not self.enabled:
            return
        
        audit_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': 'data_access',
            'entity_type': entity_type,
            'entity_id': self._anonymize(entity_id),
            'access_type': access_type,
            'user_id': self._anonymize(user_id) if user_id else None,
            'request_id': request_id,
        }
        
        # Log to file
        if self.file_logger:
            self.file_logger.info(json.dumps(audit_entry, ensure_ascii=False))
        
        # Log to structured audit log
        logger.bind(audit=True).info(f"AUDIT_ACCESS: {json.dumps(audit_entry)}")
    
    def _anonymize(self, value: str) -> str:
        """Anonymize sensitive data for GDPR compliance."""
        if not value:
            return value
        # Return first 4 chars + *** for identification without full exposure
        return str(value)[:4] + '***' if len(str(value)) > 4 else '***'
    
    def _mask_ip(self, ip: str) -> str:
        """Mask IP address for privacy (keep only first two octets)."""
        if not ip:
            return ip
        parts = ip.split('.')
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.***.***"
        return '***'
    
    def _hash_params(self, params: dict) -> str:
        """Hash parameters for audit without storing full values."""
        import hashlib
        params_str = str(sorted(params.items()))
        return hashlib.sha256(params_str.encode()).hexdigest()[:16]
    
    def _log_to_neo4j(self, audit_entry: dict):
        """Store audit entry in Neo4j for querying."""
        try:
            from paladino.db import get_driver
            
            driver = get_driver()
            with driver.session() as session:
                session.run("""
                    CREATE (a:AuditLog {
                        timestamp: datetime($timestamp),
                        event_type: $event_type,
                        endpoint: $endpoint,
                        status: $status,
                        duration_ms: $duration_ms,
                        user_id_hash: $user_id,
                        ip_hash: $ip_address,
                        request_id: $request_id
                    })
                """, **audit_entry)
        except Exception as e:
            logger.warning(f"Failed to log audit to Neo4j: {e}")
    
    def get_audit_logs(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        event_type: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Retrieve audit logs for compliance review.
        
        Args:
            start_date: Filter logs after this date
            end_date: Filter logs before this date
            event_type: Filter by event type (api_request, database_query, data_access)
            user_id: Filter by user ID hash
            limit: Maximum results to return
            
        Returns:
            List of audit log entries
        """
        # For now, return empty - would query Neo4j or parse log files
        # This is a placeholder for future implementation
        return []


# Global audit logger instance
audit_logger = AuditLogger()
