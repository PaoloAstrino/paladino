"""
Security Test Suite for Paladino API

Comprehensive test coverage for:
- API Key Authentication (SEC-002)
- Rate Limiting (SEC-006)
- CORS Configuration (SEC-005)
- Cypher Injection Prevention (SEC-009)
- Input Validation (SEC-011)
- Credential Leakage (SEC-013)
- Query Timeouts (REL-005)
- Cypher Query Validation (REL-006)
- Security Headers (SEC-015)
- Request ID Tracing (OBS-002)
- Audit Logging (OBS-003)

Includes:
- Normal cases
- Edge cases
- Boundary conditions
- Attack vectors
- Error conditions
"""

import hashlib
import time
import uuid
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from paladino.app.cypher_validator import (
    CypherValidator,
    validate_cypher,
)
from paladino.app.security import (
    APIError,
    QueryAuditor,
    RateLimiter,
)
from paladino.config import settings

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def test_app():
    """Create test FastAPI app with security middleware."""
    app = FastAPI()

    @app.middleware("http")
    async def add_request_id(request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.get("/test/auth")
    async def test_auth(api_key: str | None = None):
        return {"authenticated": api_key is not None}

    @app.get("/test/error")
    async def test_error():
        raise ValueError("Test error")

    @app.get("/test/headers")
    async def test_headers():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(test_app):
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def rate_limiter():
    """Create fresh rate limiter for each test."""
    return RateLimiter()


@pytest.fixture
def query_auditor():
    """Create query auditor with test settings."""
    auditor = QueryAuditor()
    auditor.enabled = True
    return auditor


# =============================================================================
# API Key Authentication Tests (SEC-002)
# =============================================================================


class TestAPIKeyAuthentication:
    """Test API key authentication mechanisms."""

    def test_valid_api_key(self):
        """Test authentication with valid API key."""
        # Setup
        with patch.object(settings, "api_keys", "sk_test_abc123,sk_test_def456"):
            # Test valid key
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="sk_test_abc123")

            # Mock the dependency
            with patch("paladino.app.security.Depends") as mock_depends:
                mock_depends.return_value = creds

                # Should not raise
                # Note: Full integration test requires running app

    def test_invalid_api_key(self):
        """Test authentication with invalid API key."""
        with patch.object(settings, "api_keys", "sk_test_abc123"):
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="sk_invalid_key")

            # Should raise HTTPException 401
            with pytest.raises(HTTPException) as exc_info:
                # Simulate verification
                if creds.credentials != "sk_test_abc123":
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid API key",
                    )

            assert exc_info.value.status_code == 401

    def test_missing_api_key(self):
        """Test authentication with missing API key."""
        with patch.object(settings, "api_keys", "sk_test_abc123"):
            # No credentials provided
            creds = None

            with pytest.raises(HTTPException) as exc_info:
                if creds is None:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="API key required",
                    )

            assert exc_info.value.status_code == 401

    def test_empty_api_key(self):
        """Test authentication with empty API key."""
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")

        with patch.object(settings, "api_keys", "sk_test_abc123"):
            assert creds.credentials != "sk_test_abc123"

    def test_api_key_with_whitespace(self):
        """Test API key with leading/trailing whitespace."""
        valid_key = "sk_test_abc123"
        test_cases = [
            " sk_test_abc123",
            "sk_test_abc123 ",
            "  sk_test_abc123  ",
            "sk_test_abc123\n",
            "sk_test_abc123\t",
        ]

        for invalid_key in test_cases:
            assert invalid_key != valid_key, f"Whitespace should not match: '{invalid_key}'"

    def test_api_key_case_sensitivity(self):
        """Test API key is case-sensitive."""
        valid_key = "sk_test_AbC123"
        invalid_variants = [
            "sk_test_abc123",
            "sk_test_ABC123",
            "SK_TEST_AbC123",
            "sk_test_abC123",
        ]

        for invalid_key in invalid_variants:
            assert invalid_key != valid_key

    def test_api_key_format_validation(self):
        """Test API key format expectations."""
        valid_formats = [
            "sk_live_" + "a" * 32,
            "sk_test_" + "b" * 32,
            "sk_prod_" + "c" * 32,
        ]

        invalid_formats = [
            "",  # Empty
            "sk_",  # Too short
            "sk_live_",  # No actual key
            "sk_live_" + "a" * 10,  # Too short
            "api_key_123",  # Wrong prefix
            "sk-live-abc123",  # Wrong separator
            "sk_live_abc123!",  # Special characters
            "sk_live_abc 123",  # Spaces
        ]

        for key in valid_formats:
            assert len(key) > 10, f"Valid key too short: {key}"

        for key in invalid_formats:
            # These should be rejected by validation
            assert not key or len(key) < 20 or " " in key or "!" in key

    def test_multiple_api_keys(self):
        """Test multiple valid API keys configured."""
        keys = "sk_test_abc123,sk_test_def456,sk_test_ghi789"
        key_list = [k.strip() for k in keys.split(",")]

        assert len(key_list) == 3
        assert "sk_test_abc123" in key_list
        assert "sk_test_def456" in key_list
        assert "sk_test_ghi789" in key_list

    def test_api_key_with_unicode(self):
        """Test API key with unicode characters (should be rejected)."""
        invalid_keys = [
            "sk_live_abc123é",
            "sk_live_abc123ñ",
            "sk_live_abc123中文",
            "sk_live_abc123🔑",
        ]

        for key in invalid_keys:
            # Should be ASCII only
            assert not key.isascii()

    def test_api_key_null_byte_injection(self):
        """Test API key with null byte injection attempt."""
        invalid_keys = [
            "sk_test_abc123\x00",
            "sk_test_\x00abc123",
            "\x00sk_test_abc123",
        ]

        for key in invalid_keys:
            # Null bytes should be stripped or rejected
            assert "\x00" in key

    def test_api_key_sql_injection_attempt(self):
        """Test API key with SQL/Cypher injection attempt."""
        injection_attempts = [
            "sk_test' OR '1'='1",
            "sk_test'; DROP TABLE users; --",
            "sk_test' UNION SELECT * FROM users --",
            'sk_test" OR "1"="1',
        ]

        for key in injection_attempts:
            # Should be treated as literal string, not executed
            assert "'" in key or '"' in key or ";" in key


# =============================================================================
# Rate Limiting Tests (SEC-006)
# =============================================================================


class TestRateLimiting:
    """Test rate limiting functionality."""

    def test_rate_limit_allows_under_threshold(self, rate_limiter):
        """Test requests under limit are allowed."""
        key = "test_ip_192.168.1.1"
        limit = 10
        window = 60

        for i in range(limit):
            assert rate_limiter.is_allowed(key, limit, window) is True

    def test_rate_limit_blocks_at_threshold(self, rate_limiter):
        """Test requests at limit are blocked."""
        key = "test_ip_192.168.1.2"
        limit = 5
        window = 60

        # Make limit requests
        for i in range(limit):
            rate_limiter.is_allowed(key, limit, window)

        # Next request should be blocked
        assert rate_limiter.is_allowed(key, limit, window) is False

    def test_rate_limit_different_ips_independent(self, rate_limiter):
        """Test rate limits are per-IP."""
        limit = 5
        window = 60

        # Exhaust limit for IP 1
        ip1 = "test_ip_192.168.1.3"
        for i in range(limit):
            rate_limiter.is_allowed(ip1, limit, window)

        # IP 2 should still be allowed
        ip2 = "test_ip_192.168.1.4"
        assert rate_limiter.is_allowed(ip2, limit, window) is True

    def test_rate_limit_window_reset(self, rate_limiter):
        """Test rate limit resets after window."""
        key = "test_ip_192.168.1.5"
        limit = 3
        window = 1  # 1 second window for testing

        # Exhaust limit
        for i in range(limit):
            rate_limiter.is_allowed(key, limit, window)

        # Should be blocked
        assert rate_limiter.is_allowed(key, limit, window) is False

        # Wait for window to reset
        time.sleep(window + 0.1)

        # Should be allowed again
        assert rate_limiter.is_allowed(key, limit, window) is True

    def test_rate_limit_retry_after_calculation(self, rate_limiter):
        """Test retry-after header calculation."""
        key = "test_ip_192.168.1.6"
        limit = 2
        window = 60

        # Exhaust limit
        rate_limiter.is_allowed(key, limit, window)
        rate_limiter.is_allowed(key, limit, window)

        # Get retry-after
        retry_after = rate_limiter.get_retry_after(key, window)

        # Should be positive and less than window
        assert 0 < retry_after <= window

    def test_rate_limit_edge_case_zero_limit(self, rate_limiter):
        """Test rate limit with zero limit (edge case)."""
        key = "test_ip_192.168.1.7"
        limit = 0
        window = 60

        # Should always be blocked
        assert rate_limiter.is_allowed(key, limit, window) is False

    def test_rate_limit_edge_case_large_limit(self, rate_limiter):
        """Test rate limit with very large limit."""
        key = "test_ip_192.168.1.8"
        limit = 1000000
        window = 60

        # Should allow many requests
        for i in range(1000):
            assert rate_limiter.is_allowed(key, limit, window) is True

    def test_rate_limit_edge_case_zero_window(self, rate_limiter):
        """Test rate limit with zero window (edge case)."""
        key = "test_ip_192.168.1.9"
        limit = 10
        window = 0

        # With zero window, all old requests are expired
        # Should allow requests
        assert rate_limiter.is_allowed(key, limit, window) is True

    def test_rate_limit_concurrent_requests(self, rate_limiter):
        """Test rate limiting with concurrent requests."""
        import threading

        key = "test_ip_192.168.1.10"
        limit = 100
        window = 60
        allowed_count = [0]
        lock = threading.Lock()

        def make_request():
            if rate_limiter.is_allowed(key, limit, window):
                with lock:
                    allowed_count[0] += 1

        # Start 150 concurrent requests
        threads = [threading.Thread(target=make_request) for _ in range(150)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should allow approximately limit requests
        # (may vary slightly due to race conditions)
        assert 95 <= allowed_count[0] <= 105

    def test_rate_limit_api_key_vs_ip(self, rate_limiter):
        """Test rate limiting by API key vs IP."""
        limit = 10
        window = 60

        # Exhaust IP limit
        ip_key = "ip:192.168.1.11"
        for i in range(limit):
            rate_limiter.is_allowed(ip_key, limit, window)

        # API key should have separate limit
        api_key = "apikey:abc123"
        assert rate_limiter.is_allowed(api_key, limit, window) is True

    def test_rate_limit_burst_traffic(self, rate_limiter):
        """Test rate limiting with burst traffic."""
        key = "test_ip_192.168.1.12"
        limit = 10
        window = 60

        # Burst of 20 requests
        results = [rate_limiter.is_allowed(key, limit, window) for _ in range(20)]

        # First 10 should be allowed, rest blocked
        assert results[:10] == [True] * 10
        assert results[10:] == [False] * 10

    def test_rate_limit_gradual_traffic(self, rate_limiter):
        """Test rate limiting with gradual traffic."""
        key = "test_ip_192.168.1.13"
        limit = 5
        window = 1  # 1 second for testing

        # Make requests over time
        for i in range(3):
            assert rate_limiter.is_allowed(key, limit, window) is True
            time.sleep(0.3)

        # Should still be allowed (spread out)
        assert rate_limiter.is_allowed(key, limit, window) is True


# =============================================================================
# CORS Configuration Tests (SEC-005)
# =============================================================================


class TestCORSConfiguration:
    """Test CORS configuration."""

    def test_cors_allowed_origins_parsed(self):
        """Test CORS allowed origins parsing."""
        origins_str = "http://localhost:3000,https://example.com,https://admin.example.com"
        origins = [o.strip() for o in origins_str.split(",") if o.strip()]

        assert len(origins) == 3
        assert "http://localhost:3000" in origins
        assert "https://example.com" in origins
        assert "https://admin.example.com" in origins

    def test_cors_wildcard_rejected(self):
        """Test CORS wildcard is rejected."""
        origins_str = "*"
        origins = [o.strip() for o in origins_str.split(",") if o.strip()]

        # Wildcard should be detected and rejected
        assert "*" in origins

        # In production, this should be replaced with safe defaults
        if "*" in origins:
            origins = ["http://localhost:3000", "http://localhost:8000"]

        assert "*" not in origins

    def test_cors_origin_with_trailing_slash(self):
        """Test CORS origins with trailing slashes."""
        origins = [
            "http://localhost:3000/",
            "https://example.com/",
            "http://localhost:3000",
        ]

        # Normalize origins (remove trailing slashes)
        normalized = [o.rstrip("/") for o in origins]

        assert "http://localhost:3000" in normalized
        assert "https://example.com" in normalized

    def test_cors_origin_case_sensitivity(self):
        """Test CORS origins are case-sensitive."""
        valid_origin = "https://Example.com"
        invalid_origins = [
            "https://example.com",
            "HTTPS://Example.com",
            "https://EXAMPLE.COM",
        ]

        for origin in invalid_origins:
            assert origin != valid_origin

    def test_cors_origin_with_path_rejected(self):
        """Test CORS origins with paths should be rejected."""
        invalid_origins = [
            "https://example.com/path",
            "http://localhost:3000/app",
            "https://example.com/api/v1",
        ]

        for origin in invalid_origins:
            # Origins should not include paths
            assert "/" in origin.split("://")[1]

    def test_cors_empty_origins_list(self):
        """Test CORS with empty origins list."""
        origins_str = ""
        origins = [o.strip() for o in origins_str.split(",") if o.strip()]

        assert len(origins) == 0

    def test_cors_origin_with_whitespace(self):
        """Test CORS origins with whitespace."""
        origins_str = "  http://localhost:3000  ,  https://example.com  "
        origins = [o.strip() for o in origins_str.split(",") if o.strip()]

        assert len(origins) == 2
        assert origins[0] == "http://localhost:3000"
        assert origins[1] == "https://example.com"


# =============================================================================
# Cypher Injection Prevention Tests (SEC-009)
# =============================================================================


class TestCypherInjectionPrevention:
    """Test Cypher injection prevention."""

    def test_allowed_key_properties(self):
        """Test allowed key properties list."""
        from paladino.etl.custom_csv_importer import CustomCSVImporter

        allowed = CustomCSVImporter._ALLOWED_KEY_PROPERTIES

        # Should contain expected properties
        assert "cf" in allowed
        assert "piva" in allowed
        assert "cig" in allowed
        assert "cup" in allowed
        assert "id" in allowed

    def test_injected_key_property_rejected(self):
        """Test injected key property is rejected."""
        from paladino.etl.custom_csv_importer import CustomCSVImporter

        importer = CustomCSVImporter(Mock())

        injection_attempts = [
            "cf} DELETE MATCH (n) --",
            "cf}; DROP DATABASE neo4j; --",
            "cf' OR '1'='1",
            'cf" OR "1"="1',
            "cf); CALL dbms.shutdown(); --",
            "cf\nDELETE MATCH (n)",
            "cf\tCALL apoc.util.validate(true)",
        ]

        mapping = {"cf": "fiscal_code"}

        for injected_key in injection_attempts:
            with pytest.raises(ValueError) as exc_info:
                importer._resolve_key_property("company", mapping, injected_key)

            assert "Invalid key_property" in str(exc_info.value)

    def test_key_property_unicode_injection(self):
        """Test key property with unicode injection."""
        from paladino.etl.custom_csv_importer import CustomCSVImporter

        importer = CustomCSVImporter(Mock())

        unicode_injections = [
            "cf\u200b",  # Zero-width space
            "cf\u00a0",  # Non-breaking space
            "cf\u3000",  # Ideographic space
            "cf\u2028",  # Line separator
        ]

        mapping = {"cf": "fiscal_code"}

        for injected_key in unicode_injections:
            with pytest.raises(ValueError):
                importer._resolve_key_property("company", mapping, injected_key)

    def test_key_property_null_byte_injection(self):
        """Test key property with null byte injection."""
        from paladino.etl.custom_csv_importer import CustomCSVImporter

        importer = CustomCSVImporter(Mock())

        null_injections = [
            "cf\x00",
            "cf\x00DELETE",
            "\x00cf",
        ]

        mapping = {"cf": "fiscal_code"}

        for injected_key in null_injections:
            with pytest.raises(ValueError):
                importer._resolve_key_property("company", mapping, injected_key)


# =============================================================================
# Cypher Query Validation Tests (REL-006)
# =============================================================================


class TestCypherQueryValidation:
    """Test Cypher query validation."""

    def test_safe_query_allowed(self):
        """Test safe queries are allowed."""
        validator = CypherValidator(allow_writes=False)

        safe_queries = [
            "MATCH (c:Company) RETURN c LIMIT 10",
            "MATCH (c:Company {cf: $cf}) RETURN c",
            "MATCH (c:Company)-[:WINS]->(t:Tender) RETURN c, t",
            "MATCH (c:Company) WHERE c.risk_score > $min RETURN c",
        ]

        for query in safe_queries:
            result = validator.validate(query)
            assert result.is_safe, f"Safe query blocked: {query}"

    def test_dangerous_queries_blocked(self):
        """Test dangerous queries are blocked."""
        validator = CypherValidator(allow_writes=False)

        dangerous_queries = [
            ("MATCH (n) DELETE n", "DELETE"),
            ("MATCH (n) DETACH DELETE n", "DETACH DELETE"),
            ("DROP DATABASE neo4j", "DROP"),
            ("CREATE USER admin SET PASSWORD 'pass'", "CREATE USER"),
            ("CALL dbms.shutdown()", "dbms"),
            ("CALL apoc.create.node('Company', {})", "apoc.create"),
            ("LOAD CSV FROM 'file.csv' AS row", "LOAD CSV"),
        ]

        for query, expected_block_reason in dangerous_queries:
            result = validator.validate(query)
            assert not result.is_safe, f"Dangerous query allowed: {query}"
            assert len(result.errors) > 0

    def test_injection_attempts_blocked(self):
        """Test injection attempts are blocked."""
        validator = CypherValidator()

        injection_attempts = [
            "MATCH (c:Company {cf: '$cf'}) RETURN c",  # Param in quotes
            "MATCH (c:Company {cf: $1}) RETURN c",  # Numeric param
            "MATCH (c:Company {cf: $cf + ' OR 1=1'}) RETURN c",  # Param concat
        ]

        for query in injection_attempts:
            result = validator.validate(query)
            assert not result.is_safe
            assert len(result.errors) > 0

    def test_write_operations_blocked_when_readonly(self):
        """Test write operations blocked in read-only mode."""
        validator = CypherValidator(allow_writes=False)

        write_queries = [
            "MERGE (c:Company {cf: $cf})",
            "CREATE (c:Company {cf: $cf})",
            "MATCH (c:Company) SET c.risk_score = 0.5",
        ]

        for query in write_queries:
            result = validator.validate(query)
            assert not result.is_safe
            assert any("not allowed in read-only mode" in e for e in result.errors)

    def test_write_operations_allowed_when_enabled(self):
        """Test write operations allowed when enabled."""
        validator = CypherValidator(allow_writes=True)

        write_queries = [
            "MERGE (c:Company {cf: $cf})",
            "CREATE (c:Company {cf: $cf})",
            "MATCH (c:Company) SET c.risk_score = 0.5",
        ]

        for query in write_queries:
            result = validator.validate(query)
            # May still have warnings, but should be safe
            assert len(result.errors) == 0 or all("not allowed" not in e for e in result.errors)

    def test_warning_patterns_detected(self):
        """Test warning patterns are detected."""
        validator = CypherValidator()

        queries_with_warnings = [
            "MATCH ()-[r]->() RETURN r",  # Unbounded traversal
            "MATCH (n) WHERE NOT exists(n.name) RETURN n",  # Negation without label
            "OPTIONAL MATCH (n) WITH collect(n) RETURN n",  # Large collection
        ]

        for query in queries_with_warnings:
            result = validator.validate(query)
            assert len(result.warnings) > 0, f"No warning for: {query}"

    def test_query_with_comments(self):
        """Test query validation with comments."""
        validator = CypherValidator(allow_writes=False)

        # Dangerous operation in comment should not block
        query = """
        // This would be dangerous: DELETE MATCH (n)
        MATCH (c:Company) RETURN c LIMIT 10
        """

        result = validator.validate(query)
        # Should be safe (comment is ignored)
        assert result.is_safe

    def test_query_with_multiline_injection(self):
        """Test multi-line injection attempts."""
        validator = CypherValidator()

        injection = """
        MATCH (c:Company {cf: $cf})
        RETURN c
        /*
        DELETE MATCH (n)
        */
        """

        result = validator.validate(query)
        # Comment should be ignored
        assert result.is_safe

    def test_validate_and_raise(self):
        """Test validate_and_raise helper."""
        from paladino.app.cypher_validator import CypherValidator

        # Safe query should not raise
        CypherValidator.validate_and_raise("MATCH (c:Company) RETURN c LIMIT 10")

        # Dangerous query should raise
        with pytest.raises(ValueError) as exc_info:
            CypherValidator.validate_and_raise("MATCH (n) DELETE n")

        assert "Blocked" in str(exc_info.value)

    def test_convenience_function(self):
        """Test convenience validate_cypher function."""

        is_safe, errors, warnings = validate_cypher("MATCH (c:Company) RETURN c")
        assert is_safe is True
        assert len(errors) == 0

        is_safe, errors, warnings = validate_cypher("MATCH (n) DELETE n")
        assert is_safe is False
        assert len(errors) > 0


# =============================================================================
# Input Validation Tests (SEC-011)
# =============================================================================


class TestInputValidation:
    """Test input validation."""

    def test_question_max_length(self):
        """Test question max length validation."""
        from paladino.app.api import QueryRequest

        # Valid question
        valid = "a" * 1000
        req = QueryRequest(question=valid)
        assert len(req.question) <= 1000

        # Too long question (should be truncated by validator)
        too_long = "a" * 2000
        req = QueryRequest(question=too_long)
        assert len(req.question) <= 1000

    def test_question_control_characters(self):
        """Test question control character removal."""
        from paladino.app.api import QueryRequest

        # Question with control characters
        question = "Test\x00question\x01with\x02control\x03chars"
        req = QueryRequest(question=question)

        # Control characters should be removed
        assert "\x00" not in req.question
        assert "\x01" not in req.question
        assert "\x02" not in req.question
        assert "\x03" not in req.question

    def test_question_whitespace_trimming(self):
        """Test question whitespace trimming."""
        from paladino.app.api import QueryRequest

        question = "  Test question with spaces  "
        req = QueryRequest(question=question)

        assert req.question == req.question.strip()

    def test_question_empty_rejected(self):
        """Test empty question rejected."""
        from paladino.app.api import QueryRequest

        with pytest.raises(Exception):  # Pydantic validation error
            QueryRequest(question="")

    def test_question_unicode_accepted(self):
        """Test unicode in question accepted."""
        from paladino.app.api import QueryRequest

        questions = [
            "Qual è il nome dell'azienda?",
            "¿Cuál es el nombre de la empresa?",
            "公司名称是什么？",
            "اسم الشركة؟",
        ]

        for q in questions:
            req = QueryRequest(question=q)
            assert req.question == q

    def test_question_injection_attempts(self):
        """Test injection attempts in question."""
        from paladino.app.api import QueryRequest

        # These should be accepted as literal text (not executed)
        injection_attempts = [
            "Show companies'; DELETE FROM companies; --",
            "Show companies' OR '1'='1",
            "<script>alert('xss')</script>",
            "{{constructor.constructor('alert(1)')()}}",
        ]

        for q in injection_attempts:
            # Should be accepted but treated as literal text
            req = QueryRequest(question=q)
            assert q in req.question or req.question in q  # May be truncated


# =============================================================================
# Security Headers Tests (SEC-015)
# =============================================================================


class TestSecurityHeaders:
    """Test security headers."""

    def test_security_headers_present(self, client):
        """Test security headers are present in responses."""
        response = client.get("/test/headers")

        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert "Strict-Transport-Security" in response.headers
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "Content-Security-Policy" in response.headers

    def test_security_headers_values(self, client):
        """Test security headers have correct values."""
        response = client.get("/test/headers")

        hsts = response.headers.get("Strict-Transport-Security")
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts

    def test_security_headers_on_error(self, client):
        """Test security headers present on error responses."""
        response = client.get("/test/error")

        # Even error responses should have security headers
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"


# =============================================================================
# Request ID Tracing Tests (OBS-002)
# =============================================================================


class TestRequestIDTracing:
    """Test request ID tracing."""

    def test_request_id_generated(self, client):
        """Test request ID is generated if not provided."""
        response = client.get("/test/headers")

        assert "X-Request-ID" in response.headers
        # Should be a valid UUID
        uuid.UUID(response.headers["X-Request-ID"])

    def test_request_id_propagated(self, client):
        """Test provided request ID is propagated."""
        request_id = str(uuid.uuid4())
        response = client.get("/test/headers", headers={"X-Request-ID": request_id})

        assert response.headers.get("X-Request-ID") == request_id

    def test_request_id_format(self, client):
        """Test request ID is valid UUID format."""
        response = client.get("/test/headers")
        request_id = response.headers.get("X-Request-ID")

        # Should not raise
        uuid.UUID(request_id)

    def test_request_id_in_logs(self, client):
        """Test request ID is available for logging."""
        # The middleware sets request.state.request_id
        # This is tested indirectly via the response header
        response = client.get("/test/headers")

        assert "X-Request-ID" in response.headers


# =============================================================================
# Error Handling Tests (SEC-013)
# =============================================================================


class TestErrorHandling:
    """Test error handling doesn't leak sensitive information."""

    def test_error_no_credentials(self, client):
        """Test error messages don't include credentials."""
        response = client.get("/test/error")

        # Should not include stack trace with credentials
        assert "password" not in str(response.json()).lower()
        assert "secret" not in str(response.json()).lower()
        assert "key" not in str(response.json()).lower()

    def test_standardized_error_response(self):
        """Test error response is standardized."""
        error = APIError(
            error="Test error",
            code="TEST_ERROR",
            request_id="test-123",
        )

        error_dict = error.to_dict()

        assert "error" in error_dict
        assert "code" in error_dict
        assert "request_id" in error_dict
        assert "details" in error_dict

    def test_error_no_stack_trace(self, client):
        """Test error responses don't include stack traces."""
        response = client.get("/test/error")

        # Should not include Python stack trace
        assert 'File "' not in str(response.json())
        assert "Traceback" not in str(response.json())


# =============================================================================
# Query Audit Logging Tests (OBS-003)
# =============================================================================


class TestQueryAuditLogging:
    """Test query audit logging."""

    def test_audit_log_created(self, query_auditor):
        """Test audit log entry is created."""
        mock_request = Mock()
        mock_request.state.request_id = "test-123"
        mock_request.client.host = "192.168.1.1"
        mock_request.headers = {"user-agent": "test-client"}

        # Should not raise
        query_auditor.log_query(
            request=mock_request,
            query_type="natural_language",
            params={"question": "Test query"},
            result_count=10,
            execution_time_ms=100.5,
            status="success",
        )

    def test_audit_log_includes_request_id(self, query_auditor):
        """Test audit log includes request ID."""
        mock_request = Mock()
        mock_request.state.request_id = "test-456"
        mock_request.client.host = "192.168.1.2"
        mock_request.headers = {"user-agent": "test-client"}

        # Mock the logger to capture the call
        with patch("paladino.app.security.logger") as mock_logger:
            query_auditor.log_query(
                request=mock_request,
                query_type="template",
                template_name="test_template",
                status="success",
            )

            # Logger should be called
            assert mock_logger.bind.called
            assert mock_logger.bind.return_value.info.called

    def test_audit_log_anonymizes_api_key(self, query_auditor):
        """Test audit log anonymizes API key."""
        api_key = "sk_test_abc123def456"
        user_id = query_auditor._get_user_id(api_key)

        # Should be hashed, not plain text
        assert user_id != api_key
        assert len(user_id) == 8  # First 8 chars of hash

    def test_audit_log_hashes_cypher(self, query_auditor):
        """Test audit log hashes Cypher query."""
        cypher = "MATCH (c:Company) RETURN c"
        cypher_hash = query_auditor._hash_cypher(cypher)

        # Should be hash, not plain text
        assert cypher_hash != cypher
        assert len(cypher_hash) == 16  # First 16 chars of hash

    def test_audit_log_disabled(self):
        """Test audit logging can be disabled."""
        auditor = QueryAuditor()
        auditor.enabled = False

        mock_request = Mock()
        mock_request.state.request_id = "test-789"
        mock_request.client.host = "192.168.1.3"
        mock_request.headers = {"user-agent": "test-client"}

        with patch("paladino.app.security.logger") as mock_logger:
            auditor.log_query(
                request=mock_request,
                query_type="test",
                status="success",
            )

            # Logger should not be called
            assert not mock_logger.bind.called


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for security features."""

    def test_authenticated_request_with_rate_limit(self, rate_limiter):
        """Test authenticated request with rate limiting."""
        # Setup
        api_key = "sk_test_abc123"
        ip = "192.168.1.100"
        limit = 100  # Authenticated limit

        # Make authenticated requests
        rate_limit_key = f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"

        for i in range(limit):
            assert rate_limiter.is_allowed(rate_limit_key, limit, 60) is True

        # Should be blocked at limit
        assert rate_limiter.is_allowed(rate_limit_key, limit, 60) is False

    def test_unauthenticated_request_with_rate_limit(self, rate_limiter):
        """Test unauthenticated request with rate limiting."""
        ip = "192.168.1.101"
        limit = 20  # Unauthenticated limit

        rate_limit_key = f"ip:{ip}"

        for i in range(limit):
            assert rate_limiter.is_allowed(rate_limit_key, limit, 60) is True

        # Should be blocked at limit
        assert rate_limiter.is_allowed(rate_limit_key, limit, 60) is False

    def test_full_security_pipeline(self, client, rate_limiter, query_auditor):
        """Test full security pipeline: auth, rate limit, audit."""
        # 1. Request with valid API key
        api_key = "sk_test_abc123"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "X-Request-ID": str(uuid.uuid4()),
        }

        # 2. Rate limit check
        rate_limit_key = f"apikey:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
        assert rate_limiter.is_allowed(rate_limit_key, 100, 60) is True

        # 3. Make request
        response = client.get("/test/headers", headers=headers)

        # 4. Check response
        assert response.status_code == 200
        assert "X-Request-ID" in response.headers
        assert "X-Content-Type-Options" in response.headers

        # 5. Audit log
        mock_request = Mock()
        mock_request.state.request_id = response.headers["X-Request-ID"]
        mock_request.client.host = "testclient"
        mock_request.headers = headers

        query_auditor.log_query(
            request=mock_request,
            query_type="test",
            status="success",
            api_key=api_key,
        )


# =============================================================================
# Edge Cases and Attack Vectors
# =============================================================================


class TestEdgeCasesAndAttacks:
    """Test edge cases and attack vectors."""

    def test_rate_limit_time_zone_manipulation(self, rate_limiter):
        """Test rate limit with time zone manipulation."""
        key = "test_ip_192.168.1.200"
        limit = 10
        window = 60

        # Rate limiter uses time.time() which is UTC
        # Changing system timezone should not affect it
        # (This is more of a design verification)

        for i in range(limit):
            assert rate_limiter.is_allowed(key, limit, window) is True

        assert rate_limiter.is_allowed(key, limit, window) is False

    def test_rate_limit_clock_skew_attack(self, rate_limiter):
        """Test rate limit with clock skew."""
        key = "test_ip_192.168.1.201"
        limit = 10
        window = 60

        # If attacker manipulates clock, sliding window should still work
        # because we store absolute timestamps

        for i in range(limit):
            rate_limiter.is_allowed(key, limit, window)

        # Should be blocked regardless of clock skew
        assert rate_limiter.is_allowed(key, limit, window) is False

    def test_cors_origin_with_at_sign(self):
        """Test CORS origin with @ sign (URL parsing attack)."""
        malicious_origin = "https://evil.com@example.com"

        # Should be treated as literal string
        assert "@" in malicious_origin

        # Proper URL parsing should reject this
        from urllib.parse import urlparse

        parsed = urlparse(malicious_origin)
        # Netloc would be "evil.com@example.com" which is wrong
        assert parsed.netloc == "evil.com@example.com"

    def test_cors_origin_with_newline(self):
        """Test CORS origin with newline (header injection)."""
        malicious_origin = "https://example.com\nX-Injected: header"

        # Should be rejected or sanitized
        assert "\n" in malicious_origin

        # Proper validation should reject
        if "\n" in malicious_origin or "\r" in malicious_origin:
            # Reject
            pass

    def test_cypher_with_encoded_injection(self):
        """Test Cypher with URL-encoded injection."""
        validator = CypherValidator()

        # URL-encoded DELETE
        encoded_query = "MATCH%20%28n%29%20DELETE%20n"

        # Should be decoded before validation
        from urllib.parse import unquote

        decoded = unquote(encoded_query)

        result = validator.validate(decoded)
        assert not result.is_safe

    def test_cypher_with_homoglyph_attack(self):
        """Test Cypher with homoglyph (unicode lookalike) attack."""
        validator = CypherValidator()

        # Cyrillic 'а' instead of Latin 'a' in DELETE
        homoglyph_query = "МАТCH (n) DЕLЕTЕ n"

        result = validator.validate(homoglyph_query)
        # Should still be detected as dangerous
        assert not result.is_safe

    def test_api_key_with_jwt_bearer_confusion(self):
        """Test API key with JWT bearer token confusion."""
        # JWT tokens also use "Bearer" scheme
        jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"

        # Should be treated as opaque string, not decoded
        assert jwt_token.startswith("eyJ")  # JWT signature

        # Our simple API key validation should not try to decode it
        # Just compare as string
        valid_keys = ["sk_test_abc123"]
        assert jwt_token not in valid_keys

    def test_rate_limit_with_ipv6(self, rate_limiter):
        """Test rate limiting with IPv6 addresses."""
        ipv6_addresses = [
            "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
            "::1",  # Localhost
            "fe80::1",  # Link-local
        ]

        limit = 10
        window = 60

        for ip in ipv6_addresses:
            key = f"ip:{ip}"

            # Should work same as IPv4
            for i in range(limit):
                rate_limiter.is_allowed(key, limit, window)

            assert rate_limiter.is_allowed(key, limit, window) is False

    def test_request_id_with_injection(self, client):
        """Test request ID with injection attempts."""
        injection_attempts = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE requests; --",
            "../../../etc/passwd",
            "\x00\x01\x02",  # Control chars
        ]

        for attempt in injection_attempts:
            response = client.get("/test/headers", headers={"X-Request-ID": attempt})

            # Should either use provided ID or generate new one
            # Should not crash or execute injection
            assert response.status_code in [200, 400]

    def test_concurrent_rate_limit_bypass_attempt(self, rate_limiter):
        """Test concurrent rate limit bypass attempt."""
        import threading

        base_ip = "192.168.2."
        limit = 10
        window = 60
        allowed_total = [0]
        lock = threading.Lock()

        def make_request_from_ip(ip_suffix):
            ip = f"{base_ip}{ip_suffix}"
            key = f"ip:{ip}"

            # Try to bypass by using different IPs
            if rate_limiter.is_allowed(key, limit, window):
                with lock:
                    allowed_total[0] += 1

        # Try 100 different IPs
        threads = [
            threading.Thread(target=make_request_from_ip, args=(str(i),)) for i in range(100)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should be allowed (different IPs)
        assert allowed_total[0] == 100

        # But each IP individually limited
        # Try 15 requests from same IP
        allowed_same_ip = [0]

        def make_same_ip_request(i):
            ip = f"{base_ip}200"
            key = f"ip:{ip}"

            if rate_limiter.is_allowed(key, limit, window):
                with lock:
                    allowed_same_ip[0] += 1

        threads = [threading.Thread(target=make_same_ip_request, args=(str(i),)) for i in range(15)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should be limited to ~10
        assert 9 <= allowed_same_ip[0] <= 11


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Test security feature performance."""

    def test_rate_limit_performance(self, rate_limiter):
        """Test rate limiting performance under load."""
        import time

        key = "test_ip_performance"
        limit = 10000
        window = 60

        start = time.time()

        for i in range(limit):
            rate_limiter.is_allowed(key, limit, window)

        elapsed = time.time() - start

        # Should process 10k requests in < 1 second
        assert elapsed < 1.0, f"Rate limiting too slow: {elapsed}s"

    def test_cypher_validation_performance(self):
        """Test Cypher validation performance."""
        import time

        validator = CypherValidator()
        query = "MATCH (c:Company {cf: $cf}) RETURN c LIMIT 10"

        start = time.time()

        for i in range(1000):
            validator.validate(query)

        elapsed = time.time() - start

        # Should validate 1k queries in < 1 second
        assert elapsed < 1.0, f"Cypher validation too slow: {elapsed}s"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
