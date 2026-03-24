"""
Paladino - Centralized error types and user-friendly error builders.

All user-facing error messages live here so they are consistent across API,
CLI, ETL pipelines and the REPL.
"""

from __future__ import annotations

# ──────────────────────────────────────────────────────────────────────────────
# Custom exception hierarchy
# ──────────────────────────────────────────────────────────────────────────────

class PaladinoError(Exception):
    """Base class for all Paladino errors."""
    def __init__(self, message: str, hint: str = ""):
        self.message = message
        self.hint = hint
        super().__init__(message)

    def to_dict(self) -> dict:
        d = {"error": self.message}
        if self.hint:
            d["hint"] = self.hint
        return d


class DatabaseError(PaladinoError):
    """Raised when Neo4j is unreachable or authentication fails."""


class DatabaseAuthError(DatabaseError):
    """Wrong credentials for Neo4j."""


class DatabaseTimeoutError(DatabaseError):
    """Query or connection timed out."""


class LLMError(PaladinoError):
    """Raised when the LLM backend is unavailable or returns bad output."""


class LLMConnectionError(LLMError):
    """Ollama or external LLM API not reachable."""


class LLMRateLimitError(LLMError):
    """LLM API returned 429 Too Many Requests."""


class LLMBadResponseError(LLMError):
    """LLM returned a response that cannot be parsed."""


class ValidationError(PaladinoError):
    """Input validation failure."""


class FileSizeError(ValidationError):
    """Uploaded or referenced file exceeds the allowed size."""


class BadFileError(ValidationError):
    """Unsupported file type or corrupted content."""


class ConfigurationError(PaladinoError):
    """Missing or invalid configuration (env vars, .env, paths)."""


class DownloadError(PaladinoError):
    """External data source download failed."""


class RateLimitedError(DownloadError):
    """Remote server rate-limited the request (HTTP 429)."""


# ──────────────────────────────────────────────────────────────────────────────
# User-friendly message builders
# ──────────────────────────────────────────────────────────────────────────────

def neo4j_offline_error(original: Exception | None = None) -> DatabaseError:
    """Build a user-friendly 'Neo4j not running' error."""
    return DatabaseError(
        message="🔴 Neo4j Database is not running!",
        hint=(
            "Start Neo4j then try again:\n"
            "  • Docker:  docker-compose -f infra/docker-compose.yml up -d\n"
            "  • Desktop: Open Neo4j Desktop and start the DBMS"
        ),
    )


def neo4j_auth_error(original: Exception | None = None) -> DatabaseAuthError:
    """Build a user-friendly 'bad credentials' error."""
    return DatabaseAuthError(
        message="🔐 Neo4j authentication failed!",
        hint=(
            "Check your credentials in .env:\n"
            "  NEO4J_USER=<username>\n"
            "  NEO4J_PASSWORD=<password>\n"
            "Default credentials for a fresh installation are neo4j / neo4j."
        ),
    )


def neo4j_timeout_error(query: str = "", original: Exception | None = None) -> DatabaseTimeoutError:
    """Build a user-friendly query timeout error."""
    msg = "⏱️  Neo4j query timed out."
    if query:
        msg += f" Query: {query[:120]}..."
    return DatabaseTimeoutError(
        message=msg,
        hint=(
            "The database may be under heavy load or the query is too broad.\n"
            "Try adding LIMIT clause or narrowing filters."
        ),
    )


def llm_offline_error(url: str = "", original: Exception | None = None) -> LLMConnectionError:
    """Build a user-friendly 'LLM not running' error."""
    hint = (
        "Start Ollama then try again:\n"
        "  ollama serve\n"
        "  ollama pull llama3.2\n"
        "\nAlternatively set LLM_API_KEY + LLM_API_BASE in .env for a cloud provider."
    )
    if url:
        hint = f"Cannot reach: {url}\n\n" + hint
    return LLMConnectionError(message="🤖 LLM service is not running!", hint=hint)


def llm_rate_limit_error(retry_after: int = 0) -> LLMRateLimitError:
    """Build a rate limit error."""
    hint = "Wait before retrying."
    if retry_after:
        hint = f"Retry after {retry_after} seconds."
    return LLMRateLimitError(
        message="🚦 LLM API rate limit reached (HTTP 429).",
        hint=hint,
    )


def llm_bad_response_error(raw: str = "") -> LLMBadResponseError:
    """Build a bad LLM response error."""
    snippet = raw[:200] if raw else "<empty>"
    return LLMBadResponseError(
        message="⚠️  LLM returned an unparseable response.",
        hint=f"Raw response snippet:\n{snippet}",
    )


def config_missing_error(missing: list[str]) -> ConfigurationError:
    """Build a startup configuration error for missing env vars."""
    fields = "\n".join(f"  {k}" for k in missing)
    return ConfigurationError(
        message=f"⚙️  Missing required configuration: {', '.join(missing)}",
        hint=(
            f"Add the following to your .env file:\n{fields}\n\n"
            "Copy .env.example to .env and fill in the values."
        ),
    )


def file_too_large_error(size_mb: float, limit_mb: float) -> FileSizeError:
    """Build a file size error."""
    return FileSizeError(
        message=f"📦 File too large: {size_mb:.1f} MB (limit: {limit_mb:.0f} MB).",
        hint="Split the file into smaller parts or use the streaming ingestion endpoint.",
    )


def download_rate_limit_error(url: str, retry_after: int = 0) -> RateLimitedError:
    """Build an external download rate-limit error."""
    hint = f"The server at {url} has rate-limited your requests."
    if retry_after:
        hint += f" Retry after {retry_after} s."
    return RateLimitedError(message="🚦 Download rate-limited (HTTP 429).", hint=hint)
