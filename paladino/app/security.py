"""
Security middleware and authentication for Paladino API.

This module provides:
- API key authentication (SEC-002)
- Rate limiting (SEC-006)
- Request ID tracing (OBS-002)
- Security headers (SEC-015)
- Audit logging (OBS-003)
"""

import hashlib
import time
import uuid
from collections.abc import Callable
from datetime import datetime
from functools import wraps

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from paladino.config import settings

# =============================================================================
# API Key Authentication (SEC-002)
# =============================================================================

security = HTTPBearer(auto_error=False)


async def verify_api_key(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> str | None:
    """
    Validate API key against configured keys.

    Returns:
        API key if valid, None if authentication not provided (for optional auth endpoints)

    Raises:
        HTTPException: 401 if invalid API key provided
    """
    print(f"\nDEBUG: verify_api_key called. creds={creds}, api_keys={getattr(settings, 'api_keys', None)}\n")
    # Get valid API keys from settings
    valid_keys = (
        settings.api_keys.split(",") if hasattr(settings, "api_keys") and settings.api_keys else []
    )

    # If no keys configured and no creds provided, allow (for development)
    if not valid_keys and creds is None:
        logger.warning("No API keys configured - authentication disabled")
        return "development"

    # If no creds provided but keys exist, reject
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate the provided key
    if creds.credentials not in valid_keys:
        logger.warning(f"Invalid API key attempt from {creds.credentials[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Key is valid - return it for audit logging
    return creds.credentials


def require_auth(func: Callable) -> Callable:
    """Decorator to require authentication on an endpoint."""

    @wraps(func)
    async def wrapper(*args, api_key: str = Depends(verify_api_key), **kwargs):
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        return await func(*args, api_key=api_key, **kwargs)

    return wrapper


# =============================================================================
# Rate Limiting (SEC-006)
# =============================================================================


class RateLimiter:
    """
    In-memory rate limiter with sliding window.

    For production, replace with Redis-based implementation.
    """

    def __init__(self):
        self._requests: dict[str, list[float]] = {}
        self._cleanup_interval = 300  # 5 minutes

    def is_allowed(self, key: str, limit: int, window: int = 60) -> bool:
        """
        Check if request is allowed under rate limit.

        Args:
            key: Unique identifier (e.g., IP address or API key)
            limit: Maximum requests per window
            window: Time window in seconds (default: 60)

        Returns:
            True if allowed, False if rate limited
        """
        now = time.time()
        cutoff = now - window

        # Clean up old entries
        if key in self._requests:
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]
        else:
            self._requests[key] = []

        # Check if under limit
        if len(self._requests[key]) < limit:
            self._requests[key].append(now)
            return True

        return False

    def get_retry_after(self, key: str, window: int = 60) -> int:
        """Get seconds until rate limit resets."""
        if key not in self._requests:
            return 0

        oldest = min(self._requests[key])
        retry_after = int(oldest + window - time.time())
        return max(0, retry_after)


# Global rate limiter instance
_rate_limiter = RateLimiter()


def get_rate_limit_key(request: Request, api_key: str | None = None) -> str:
    """Generate rate limit key from request."""
    # Prefer API key if available
    if api_key:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        return f"apikey:{key_hash}"

    # Fall back to IP address
    client_ip = request.client.host if request.client else "unknown"
    return f"ip:{client_ip}"


async def rate_limit_middleware(request: Request, call_next: Callable) -> Response:
    """
    Apply rate limiting to all requests.

    Limits:
    - Authenticated: 100 requests/minute
    - Unauthenticated: 20 requests/minute
    """
    # Skip rate limiting for health checks
    if request.url.path in ["/health", "/ready", "/live"]:
        return await call_next(request)

    # Get API key if present
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    is_authenticated = bool(
        api_key
        and api_key
        in (
            settings.api_keys.split(",")
            if hasattr(settings, "api_keys") and settings.api_keys
            else []
        )
    )

    # Get rate limit based on authentication status
    limit = 100 if is_authenticated else 20
    rate_limit_key = get_rate_limit_key(request, api_key if is_authenticated else None)

    # Check rate limit
    if not _rate_limiter.is_allowed(rate_limit_key, limit):
        retry_after = _rate_limiter.get_retry_after(rate_limit_key)
        logger.warning(f"Rate limit exceeded for {rate_limit_key}")

        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "error": "Rate limit exceeded",
                "detail": f"Maximum {limit} requests per minute allowed",
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)


# =============================================================================
# Request ID Tracing (OBS-002)
# =============================================================================


async def request_id_middleware(request: Request, call_next: Callable) -> Response:
    """
    Add request ID to all requests and responses.

    Propagates X-Request-ID header for distributed tracing.
    """
    # Get or generate request ID
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    # Add to request state for logging
    request.state.request_id = request_id

    # Log request start
    logger.info(f"START {request.method} {request.url.path} [request_id={request_id}]")

    # Process request
    response = await call_next(request)

    # Add request ID to response headers
    response.headers["X-Request-ID"] = request_id

    # Log request end
    logger.info(f"END {request.method} {request.url.path} [request_id={request_id}]")

    return response


# =============================================================================
# Security Headers (SEC-015)
# =============================================================================


async def security_headers_middleware(request: Request, call_next: Callable) -> Response:
    """
    Add security headers to all responses.

    Headers:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Strict-Transport-Security: max-age=31536000
    - X-XSS-Protection: 1; mode=block
    - Content-Security-Policy: default-src 'self'
    """
    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

    return response


# =============================================================================
# Audit Logging (OBS-003)
# =============================================================================


class QueryAuditor:
    """Audit all queries for compliance and debugging."""

    def __init__(self):
        self.enabled = hasattr(settings, "enable_audit_logging") and settings.enable_audit_logging
        self.retention_days = getattr(settings, "audit_retention_days", 90)

    def log_query(
        self,
        request: Request | None,
        query_type: str,
        template_name: str | None = None,
        cypher: str | None = None,
        params: dict | None = None,
        result_count: int = 0,
        execution_time_ms: float = 0,
        status: str = "success",
        error: str | None = None,
        api_key: str | None = None,
    ):
        """Log query for audit trail."""
        if not self.enabled:
            return

        audit_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "request_id": getattr(request.state, "request_id", "unknown") if request else "unknown",
            "user_id": self._get_user_id(api_key),
            "query_type": query_type,
            "template_name": template_name,
            "cypher_hash": self._hash_cypher(cypher) if cypher else None,
            "params_hash": self._hash_params(params) if params else None,
            "result_count": result_count,
            "execution_time_ms": execution_time_ms,
            "status": status,
            "error": error,
            "ip_address": request.client.host if request and request.client else "unknown",
            "user_agent": request.headers.get("user-agent", "unknown") if request else "unknown",
        }

        # Log to structured audit log
        logger.bind(audit=True).info(f"QUERY_AUDIT: {audit_entry}")

    def _get_user_id(self, api_key: str | None) -> str | None:
        """Get user ID from API key (anonymized)."""
        if not api_key:
            return None
        # Return first 8 chars of key hash for identification
        return hashlib.sha256(api_key.encode()).hexdigest()[:8]

    def _hash_cypher(self, cypher: str) -> str:
        """Hash Cypher query for audit without storing full query."""
        return hashlib.sha256(cypher.encode()).hexdigest()[:16]

    def _hash_params(self, params: dict) -> str:
        """Hash query parameters for audit."""
        params_str = str(sorted(params.items()))
        return hashlib.sha256(params_str.encode()).hexdigest()[:16]


# Global auditor instance
query_auditor = QueryAuditor()


# =============================================================================
# Error Response Standardization
# =============================================================================


class APIError:
    """Standardized API error response."""

    def __init__(
        self,
        error: str,
        code: str,
        request_id: str,
        details: dict | None = None,
    ):
        self.error = error
        self.code = code
        self.request_id = request_id
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "error": self.error,
            "code": self.code,
            "request_id": self.request_id,
            "details": self.details,
        }


async def standardized_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Convert exceptions to standardized error responses."""
    request_id = getattr(request.state, "request_id", "unknown")

    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=APIError(
                error=exc.detail,
                code=f"HTTP_{exc.status_code}",
                request_id=request_id,
            ).to_dict(),
            headers=getattr(exc, "headers", None),
        )

    # Unexpected errors
    logger.exception(f"Unexpected error [request_id={request_id}]: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=APIError(
            error="Internal server error",
            code="INTERNAL_ERROR",
            request_id=request_id,
        ).to_dict(),
    )
