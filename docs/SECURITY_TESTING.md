# 🧪 Security Testing Documentation

**Date:** February 25, 2026  
**Version:** 1.0.0  
**Maintained By:** Paladino Security Team

---

## Overview

This document describes the comprehensive security test suite created for Paladino. The tests validate all security fixes implemented in the security hardening PR.

### Test Files

| File | Purpose | Tests |
|------|---------|-------|
| `tests/security/test_security_features.py` | Core security feature tests | 100+ |
| `tests/security/test_security_edge_cases.py` | Advanced edge cases | 50+ |
| `scripts/run_security_tests.py` | Test runner script | N/A |

---

## Test Categories

### 1. API Key Authentication (SEC-002)

**Location:** `test_security_features.py::TestAPIKeyAuthentication`

**Tests:**
- ✅ Valid API key authentication
- ✅ Invalid API key rejection
- ✅ Missing API key handling
- ✅ Empty API key handling
- ✅ API key with whitespace
- ✅ API key case sensitivity
- ✅ API key format validation
- ✅ Multiple API keys configuration
- ✅ API key with unicode characters
- ✅ API key null byte injection
- ✅ API key SQL/Cypher injection attempts

**Edge Cases Covered:**
- Unicode lookalike characters
- Zero-width space injection
- Null byte injection
- SQL injection syntax in API key
- JWT token confusion (Bearer scheme)

---

### 2. Rate Limiting (SEC-006)

**Location:** `test_security_features.py::TestRateLimiting`

**Tests:**
- ✅ Requests under threshold allowed
- ✅ Requests at threshold blocked
- ✅ Different IPs rate limited independently
- ✅ Rate limit window reset
- ✅ Retry-after calculation
- ✅ Zero limit edge case
- ✅ Large limit edge case
- ✅ Zero window edge case
- ✅ Concurrent request handling
- ✅ API key vs IP rate limiting
- ✅ Burst traffic handling
- ✅ Gradual traffic handling

**Edge Cases Covered:**
- Time zone manipulation attempts
- Clock skew attacks
- IPv6 address handling
- Concurrent bypass attempts
- Burst vs gradual traffic patterns

---

### 3. CORS Configuration (SEC-005)

**Location:** `test_security_features.py::TestCORSConfiguration`

**Tests:**
- ✅ Allowed origins parsing
- ✅ Wildcard rejection
- ✅ Origins with trailing slashes
- ✅ Origin case sensitivity
- ✅ Origins with paths (should be rejected)
- ✅ Empty origins list
- ✅ Origins with whitespace

**Edge Cases Covered:**
- @ sign in origin (URL parsing attack)
- Newline injection in origin
- Unicode in origins

---

### 4. Cypher Injection Prevention (SEC-009)

**Location:** 
- `test_security_features.py::TestCypherInjectionPrevention`
- `test_security_edge_cases.py::TestCypherInjectionEdgeCases`

**Tests:**
- ✅ Allowed key properties list
- ✅ Injected key property rejection
- ✅ Unicode injection attempts
- ✅ Null byte injection
- ✅ SQL injection syntax
- ✅ Cypher syntax in key property
- ✅ Dangerous query patterns blocked
- ✅ Safe query patterns allowed
- ✅ Injection via parameter manipulation
- ✅ Function call injection
- ✅ Case variation bypass attempts
- ✅ Whitespace variation bypass

**Edge Cases Covered:**
- Unicode normalization attacks
- Zero-width character injection
- Right-to-left override characters
- Homoglyph substitution (Cyrillic lookalikes)
- Combining diacritical marks
- Ligature characters
- Nested comments
- String escaping
- Multi-line injection
- URL-encoded injection

---

### 5. Cypher Query Validation (REL-006)

**Location:** `test_security_features.py::TestCypherQueryValidation`

**Tests:**
- ✅ Safe queries allowed
- ✅ Dangerous queries blocked (DELETE, DROP, etc.)
- ✅ Injection attempts blocked
- ✅ Write operations blocked in read-only mode
- ✅ Write operations allowed when enabled
- ✅ Warning patterns detected
- ✅ Queries with comments handled
- ✅ Multi-line injection attempts
- ✅ validate_and_raise helper
- ✅ Convenience validate_cypher function

---

### 6. Input Validation (SEC-011)

**Location:** `test_security_features.py::TestInputValidation`

**Tests:**
- ✅ Question max length enforced
- ✅ Control characters removed
- ✅ Whitespace trimming
- ✅ Empty question rejected
- ✅ Unicode accepted
- ✅ Injection attempts treated as literal text

**Edge Cases Covered:**
- XSS attempts in questions
- Template injection attempts
- SQL injection in questions

---

### 7. Security Headers (SEC-015)

**Location:** `test_security_features.py::TestSecurityHeaders`

**Tests:**
- ✅ Security headers present in responses
- ✅ Header values correct
- ✅ Headers present on error responses

**Headers Validated:**
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `X-XSS-Protection: 1; mode=block`
- `Content-Security-Policy: default-src 'self'`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: geolocation=(), microphone=(), camera=()`

---

### 8. Request ID Tracing (OBS-002)

**Location:** `test_security_features.py::TestRequestIDTracing`

**Tests:**
- ✅ Request ID generated if not provided
- ✅ Provided request ID propagated
- ✅ Request ID format (valid UUID)
- ✅ Request ID available for logging

**Edge Cases Covered:**
- XSS in request ID header
- SQL injection in request ID
- Path traversal in request ID
- Control characters in request ID

---

### 9. Error Handling (SEC-013)

**Location:** `test_security_features.py::TestErrorHandling`

**Tests:**
- ✅ Error messages don't include credentials
- ✅ Standardized error response format
- ✅ No stack traces in error responses

**Validated:**
- No "password" in error messages
- No "secret" in error messages
- No "key" in error messages
- No "File" paths in errors
- No "Traceback" in errors

---

### 10. Query Audit Logging (OBS-003)

**Location:** `test_security_features.py::TestQueryAuditLogging`

**Tests:**
- ✅ Audit log entry created
- ✅ Request ID included
- ✅ API key anonymized (hashed)
- ✅ Cypher query hashed (not stored plain)
- ✅ Audit logging can be disabled

**Edge Cases Covered:**
- Injection attempts in logged fields
- Audit log tampering detection
- Privacy leakage prevention

---

### 11. Advanced Edge Cases

**Location:** `test_security_edge_cases.py`

**Categories:**

#### Unicode Attacks
- Unicode normalization
- Zero-width characters
- Right-to-left override
- Homoglyph substitution
- Combining characters
- Ligatures

#### CSV Import Security
- Path traversal in key property
- Null byte injection
- SQL injection syntax
- Cypher syntax injection
- Formula injection (DDE attacks)
- BOM and encoding issues
- Extremely long values (DoS)
- Duplicate headers
- Empty headers

#### LLM Prompt Injection
- System message override
- Base64-encoded injection
- ROT13 encoding
- Unicode confusion
- Context escaping
- Markdown injection

#### Batch Processing Security
- Hash collision attempts
- Race condition attempts
- Replay attacks
- Resource exhaustion

#### Time-Based Attacks
- Time zone manipulation
- Clock skew attacks
- Session fixation
- Slow query DoS

#### Cryptographic Edge Cases
- Empty input hashing
- Unicode input hashing
- Timing attacks on validation

---

## Running the Tests

### Quick Start

```bash
# Run all security tests
python scripts/run_security_tests.py

# Run specific category
python scripts/run_security_tests.py --category authentication injection

# Run with verbose output
python scripts/run_security_tests.py --verbose

# Generate report
python scripts/run_security_tests.py --report security_report.md
```

### Using Pytest

```bash
# Run all security tests
pytest tests/security/ -v

# Run specific test file
pytest tests/security/test_security_features.py -v

# Run specific test class
pytest tests/security/test_security_features.py::TestAPIKeyAuthentication -v

# Run with coverage
pytest tests/security/ --cov=paladino -v

# Run slow tests (edge cases)
pytest tests/security/test_security_edge_cases.py -v -m "not slow"
```

### Test Categories

| Category Flag | Tests |
|---------------|-------|
| `authentication` | API key auth (SEC-002) |
| `rate_limiting` | Rate limiting (SEC-006) |
| `cors` | CORS configuration (SEC-005) |
| `injection` | Cypher injection (SEC-009, REL-006) |
| `validation` | Input validation (SEC-011) |
| `headers` | Security headers (SEC-015) |
| `audit` | Audit logging (OBS-003) |
| `tracing` | Request ID tracing (OBS-002) |
| `errors` | Error handling (SEC-013) |
| `edge_cases` | All edge cases |

---

## Test Coverage

### Security Controls Tested

| Control | Tests | Status |
|---------|-------|--------|
| API Authentication | 11 | ✅ Complete |
| Rate Limiting | 12 | ✅ Complete |
| CORS | 7 | ✅ Complete |
| Cypher Injection | 15+ | ✅ Complete |
| Input Validation | 6 | ✅ Complete |
| Security Headers | 3 | ✅ Complete |
| Request Tracing | 4 | ✅ Complete |
| Error Handling | 3 | ✅ Complete |
| Audit Logging | 5 | ✅ Complete |
| Edge Cases | 50+ | ✅ Complete |

**Total:** 100+ security tests

---

## Known Limitations

### Not Tested (Requires Manual/Integration Testing)

1. **Full API Integration**
   - End-to-end authentication flow
   - Rate limiting with real HTTP traffic
   - CORS with actual browser requests

2. **Performance Under Load**
   - Rate limiting with 10k+ concurrent requests
   - Query validation latency
   - Audit logging throughput

3. **External Dependencies**
   - Neo4j connection security
   - LLM API security
   - Docker container isolation

### Recommended Additional Tests

1. **Penetration Testing**
   - OWASP ZAP scan
   - Burp Suite testing
   - Manual security review

2. **Fuzzing**
   - API input fuzzing
   - Cypher query fuzzing
   - File upload fuzzing

3. **Compliance Testing**
   - GDPR compliance audit
   - Data retention verification
   - Right to erasure testing

---

## Interpreting Results

### Test Status Icons

| Icon | Status | Meaning |
|------|--------|---------|
| ✅ | PASS | Test passed successfully |
| ❌ | FAIL | Test failed - security issue |
| ⚠️ | SKIP | Test skipped (config issue) |
| 🔴 | ERROR | Test error (infrastructure issue) |

### Security Score

The security score is calculated as:

```
Score = (Passed Tests / Total Tests) × 100
```

**Score Interpretation:**
- 100%: All tests passing (production ready)
- 90-99%: Minor issues (beta ready)
- 80-89%: Some issues (development)
- <80%: Major issues (not ready)

---

## Troubleshooting

### Common Issues

#### "API keys not configured"
```bash
# Set API keys in environment
export PALADINO_API_KEYS="sk_test_abc123"
```

#### "Import failed"
```bash
# Ensure you're in project root
cd /path/to/paladino

# Install dependencies
pip install -e ".[dev]"
```

#### "Test timed out"
```bash
# Increase timeout for slow tests
pytest tests/security/test_security_edge_cases.py --timeout=120
```

---

## Contributing

### Adding New Tests

1. Create test in appropriate file:
   - Core features: `test_security_features.py`
   - Edge cases: `test_security_edge_cases.py`

2. Follow naming convention:
   ```python
   def test_<feature>_<scenario>(self):
       """Test description."""
       # Arrange
       # Act
       # Assert
   ```

3. Add to test runner if new category:
   ```python
   def test_new_category(self):
       # Test implementation
   ```

### Test Requirements

- ✅ Must be deterministic (no random failures)
- ✅ Must be independent (no shared state)
- ✅ Must be fast (<1 second per test)
- ✅ Must have clear assertions
- ✅ Must include edge cases

---

## References

- OWASP API Security: https://owasp.org/www-project-api-security/
- pytest documentation: https://docs.pytest.org/
- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/

---

**Last Updated:** February 25, 2026  
**Next Review:** After each major security update
