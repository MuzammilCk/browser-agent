"""Application settings loaded from environment variables."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Anonymous free-tier model shipped as fallback default (audit Z6):
# contested data retention — must never silently process real PII.
ANONYMOUS_DEFAULT_MODEL = "stealth/ox-alpha"

# OpenRouter marks anonymous/free-tier models with a ":free" suffix.
FREE_TIER_SUFFIX = ":free"


def is_free_tier_model(model: str | None) -> bool:
    """True when a model string denotes an anonymous/free-tier offering."""
    if not model:
        return False
    return model == ANONYMOUS_DEFAULT_MODEL or model.endswith(FREE_TIER_SUFFIX)


class Settings(BaseSettings):
    """Application configuration. Reads from .env and environment variables."""

    # OpenRouter
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    openrouter_model: str = Field(
        default=ANONYMOUS_DEFAULT_MODEL,
        description=(
            "Primary reasoning model. Note: 'stealth/ox-alpha' is an anonymous "
            "free-tier model with contested data retention. For production use "
            "with real PII, pin to a named provider (e.g. 'anthropic/claude-sonnet-4-20250514', "
            "'openai/gpt-4o', 'google/gemini-2.0-flash-001'). "
            "See https://openrouter.ai/models for options."
        ),
    )
    openrouter_vision_model: str = Field(
        default="stealth/ox-alpha",
        description=(
            "Vision model for screenshot-based fallback. Same privacy note as openrouter_model."
        ),
    )
    openrouter_fallback_model: str = Field(
        default="",
        description="Fallback model when primary fails",
    )
    openrouter_timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        description="Timeout for OpenRouter API calls",
    )
    allow_anonymous_model_with_vault: bool = Field(
        default=False,
        description=(
            "Explicit override: permit running the anonymous default model "
            "while a populated vault (real personal data) is present. "
            "Leave false to refuse such runs at start."
        ),
    )

    # Vault encryption (audit B6)
    vault_encryption_key: str = Field(
        default="",
        description="Passphrase for Fernet vault encryption at rest. "
        "If empty, vault is stored as plaintext (dev/test only).",
    )

    # Application
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/app.db",
        description="Database connection URL",
    )
    log_level: str = Field(default="INFO", description="Logging level")
    api_token: str = Field(
        default="",
        description=(
            "Bearer token required on /api/* endpoints. Empty disables auth "
            "(localhost dev only). Set before any non-localhost exposure."
        ),
    )

    # Browser
    headless: bool = Field(default=True, description="Run browser in headless mode")
    browser_mode: str = Field(
        default="test",
        description="Browser mode: 'test' (headless, automated) or 'user' (visible, interactive)",
    )
    ignore_https_errors: bool = Field(
        default=True,
        description="Ignore TLS certificate errors (some gov portals have chain issues). "
        "Disable for stricter MITM protection.",
    )
    vision_fallback_enabled: bool = Field(
        default=True,
        description="Enable screenshot-based vision fallback when semantic perception is insufficient",
    )

    # Uploads
    document_allowed_dirs: list[Path] = Field(
        default_factory=list,
        description=(
            "Directories upload files must live under. Empty disables "
            "confinement (documents may come from anywhere the user registered)."
        ),
    )

    # Paths
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    docs_dir: Path = Field(default=PROJECT_ROOT / "docs")

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("openrouter_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if v and v.startswith("sk-") and len(v) > 10:
            return v
        if not v:
            return v
        return v

    def setup_logging(self) -> None:
        """Configure application logging."""
        numeric_level = getattr(logging, self.log_level.upper(), logging.INFO)
        logging.basicConfig(
            level=numeric_level,
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        # Quiet noisy libraries
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings singleton."""
    return Settings()
