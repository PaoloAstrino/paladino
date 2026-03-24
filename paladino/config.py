from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_NEO4J_SCHEMES = (
    "bolt://",
    "bolt+s://",
    "bolt+ssc://",
    "neo4j://",
    "neo4j+s://",
    "neo4j+ssc://",
)


class Settings(BaseSettings):
    """Global application settings."""

    # Neo4j Settings
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = Field(..., env="NEO4J_USER", description="Neo4j username (required)")
    neo4j_password: str = Field(..., env="NEO4J_PASSWORD", description="Neo4j password (required)")
    neo4j_database: str = "neo4j"

    # Ollama Settings (Local LLM)
    ollama_base_url: str = "http://localhost:11434"

    # LLM Settings (Universal)
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_model: str = "llama3.2"

    # External API Keys (convenience aliases)
    openai_api_key: str | None = None
    groq_api_key: str | None = None
    anthropic_api_key: str | None = None

    embedding_dimensions: int = 768

    # ETL Settings
    min_tender_amount: float = 40000.0
    dataset_version: str = "2026-02"
    batch_size: int = 5000

    # Paths
    base_dir: Path = Path(__file__).parent.parent
    schema_dir: Path = base_dir / "schema"
    data_dir: Path = base_dir / "data"

    # SECURITY FIX (SEC-002, SEC-005): API authentication and CORS
    api_keys: str | None = Field(
        default=None,
        description="Comma-separated list of valid API keys",
    )
    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:8000",
        description="Comma-separated list of allowed CORS origins",
    )

    # Rate limiting
    api_rate_limit: str = "100/minute"
    api_rate_limit_unauthenticated: str = "20/minute"

    # Audit logging
    enable_audit_logging: bool = True
    audit_retention_days: int = 90
    audit_log_dir: Path = base_dir / "audit_logs"

    # API configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4

    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        env_prefix="PALADINO_",
        extra="ignore",
    )

    # ── validators ────────────────────────────────────────────────────────────

    @field_validator("neo4j_uri")
    @classmethod
    def validate_neo4j_uri(cls, v: str) -> str:
        """Ensure the URI uses a recognised Neo4j driver scheme."""
        if not any(v.startswith(scheme) for scheme in _VALID_NEO4J_SCHEMES):
            valid = ", ".join(_VALID_NEO4J_SCHEMES)
            raise ValueError(
                f"NEO4J_URI has an invalid scheme: {v!r}. Must start with one of: {valid}"
            )
        return v

    def validate_startup(self) -> None:
        """Run once at application startup to surface configuration problems early.

        Raises:
            paladino.errors.ConfigurationError: if critical values are missing or wrong.
        """
        from paladino.errors import config_missing_error

        missing: list[str] = []

        # Pydantic already enforces required fields, but password/user could be
        # empty strings injected via .env — catch that here.
        if not self.neo4j_user.strip():
            missing.append("NEO4J_USER")
        if not self.neo4j_password.strip():
            missing.append("NEO4J_PASSWORD")

        # data_dir must exist and be readable
        if not self.data_dir.exists():
            missing.append(f"data_dir ({self.data_dir}) — directory not found")

        if missing:
            raise config_missing_error(missing)


# Singleton instance
settings = Settings()
