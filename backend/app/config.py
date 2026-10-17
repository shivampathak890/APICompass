import logging
import os
from typing import List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("apicompass.config")


class Settings(BaseSettings):
    """APICompass application configuration.

    All external credentials remain optional in offline mock mode.
    """
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    # Core Environment Settings
    APP_ENV: str = Field(default="development", description="Runtime environment")
    APP_NAME: str = Field(default="apicompass-api", description="Service identifier")
    APP_VERSION: str = Field(default="0.1.0", description="Application semantic version")

    # Mock Mode
    MOCK_MODE: bool = Field(
        default=True,
        description="Explicit mock mode flag (true = local mock data, false = live external calls)"
    )

    # Server Bind Settings
    API_HOST: str = Field(default="127.0.0.1", description="Backend host address")
    API_PORT: int = Field(default=8000, description="Backend port number")

    # CORS Policy
    FRONTEND_ORIGIN: str = Field(
        default="http://localhost:5173",
        description="Explicit allowed frontend origin (no wildcards)"
    )

    # Rate Limiting & Resource Abuse Controls
    RATE_LIMIT_ENABLED: bool = Field(
        default=True,
        description="Whether to enforce rate limiting on incoming API requests"
    )
    RATE_LIMIT_PER_MINUTE: int = Field(
        default=120,
        description="Maximum requests permitted per minute per client IP"
    )
    MAX_REQUEST_BODY_BYTES: int = Field(
        default=2_097_152,  # 2 MB
        description="Maximum allowed request payload size in bytes"
    )

    # Documentation Host Allowlist
    APPROVED_DOC_HOSTS: List[str] | str = Field(
        default_factory=lambda: ["stripe.com", "docs.stripe.com", "github.com"],
        description="Allowed HTTPS domains for documentation retrieval"
    )

    # Optional External Service Credentials
    TINYFISH_API_KEY: str | None = Field(
        default=None,
        description="Optional TinyFish API key for live doc searches"
    )
    TINYFISH_SEARCH_BASE_URL: str = Field(
        default="https://api.search.tinyfish.ai",
        description="TinyFish Search API base URL"
    )
    TINYFISH_FETCH_BASE_URL: str = Field(
        default="https://api.fetch.tinyfish.ai",
        description="TinyFish Fetch API base URL"
    )
    DOC_RETRIEVAL_TIMEOUT_SECONDS: float = Field(
        default=60.0,
        description="Maximum timeout in seconds for documentation retrieval requests"
    )
    DOC_RETRIEVAL_MAX_RETRIES: int = Field(
        default=2,
        description="Maximum retry attempts for transient documentation retrieval failures"
    )
    DOC_RETRIEVAL_BASE_BACKOFF_SECONDS: float = Field(
        default=0.05,
        description="Base backoff delay in seconds for transient documentation retrieval retries"
    )
    DOC_CIRCUIT_BREAKER_FAILURES: int = Field(
        default=3,
        description="Consecutive transient failure threshold before opening circuit breaker"
    )
    DOC_CIRCUIT_BREAKER_RECOVERY_SECONDS: float = Field(
        default=30.0,
        description="Recovery timeout in seconds before attempting half-open probe"
    )
    DOC_MAX_RESULTS_LIMIT: int = Field(
        default=10,
        description="Maximum number of results allowed per retrieval request"
    )
    LLM_PROVIDER: str = Field(
        default="disabled",
        description="LLM reasoning provider: 'disabled', 'mock', or 'openai'"
    )
    LLM_API_KEY: str | None = Field(
        default=None,
        description="Optional LLM API key for assisted candidate reasoning"
    )
    LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        description="LLM model identifier"
    )
    LLM_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        description="Maximum timeout in seconds for LLM reasoning requests"
    )
    LLM_MAX_CHARS: int = Field(
        default=8000,
        description="Maximum character length of untrusted code sent to model"
    )

    # SQLite Audit Database Settings
    APICOMPASS_DB_PATH: str = Field(
        default="data/apicompass.db",
        description="Path to SQLite audit database (relative to repository root or absolute)"
    )
    DB_BUSY_TIMEOUT_MS: int = Field(
        default=5000,
        description="SQLite busy timeout in milliseconds"
    )
    SOURCE_RETENTION_ENABLED: bool = Field(
        default=False,
        description="Whether to retain raw submitted source code in the audit database. Default False for privacy."
    )

    @field_validator("SOURCE_RETENTION_ENABLED", mode="before")
    @classmethod
    def validate_source_retention(cls, value: object) -> bool:
        """Strictly validate source retention configuration.

        Defaults to False. Never silently enables on ambiguous or invalid input.
        """
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in ("true", "1", "yes", "on"):
                return True
            if clean in ("false", "0", "no", "off", ""):
                return False
        return False

    @field_validator("APPROVED_DOC_HOSTS", mode="before")
    @classmethod
    def parse_doc_hosts(cls, value: object) -> List[str]:
        if isinstance(value, str):
            return [h.strip() for h in value.split(",") if h.strip()]
        if isinstance(value, list):
            return [str(h).strip() for h in value if str(h).strip()]
        return ["stripe.com", "docs.stripe.com", "github.com"]

    @field_validator("FRONTEND_ORIGIN")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        trimmed = value.strip().rstrip("/")
        if trimmed == "*":
            raise ValueError("Wildcard '*' is prohibited as FRONTEND_ORIGIN for security.")
        return trimmed

    @field_validator("TINYFISH_API_KEY", mode="before")
    @classmethod
    def clean_tinyfish_key(cls, value: object) -> str | None:
        """Strip whitespace and normalize empty string credentials to None."""
        if value is None:
            return None
        if isinstance(value, str):
            clean = value.strip()
            return clean if clean else None
        return None


# Identify accidentally empty environment variable overrides
if os.environ.get("TINYFISH_API_KEY") is not None and not os.environ.get("TINYFISH_API_KEY", "").strip():
    logger.warning(
        "TINYFISH_API_KEY is present in OS environment variables but empty/whitespace. "
        "Ignoring empty environment variable override to prevent misdiagnosing credentials."
    )

# Singleton settings instance
settings = Settings()
