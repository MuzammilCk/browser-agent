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
    openrouter_max_tokens: int = Field(
        default=4096,
        ge=256,
        le=200000,
        description=(
            "Per-request completion token budget. Reasoning-style models spend "
            "hidden reasoning tokens from this budget before emitting the "
            "visible JSON decision — a too-small budget truncates the decision "
            "(finish_reason=length) and the agent fails closed with "
            "DECISION_PARSE_FAILED. Raise for reasoning models."
        ),
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
    postgres_url: str = Field(
        default="postgresql://postgres@localhost:5432/browser_agent",
        description="PostgreSQL connection URL for Phase 8 durable checkpoints and interrupts",
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

    # Phase 13 — Enterprise runtime
    enterprise_worker_token: str = Field(
        default="",
        description=(
            "Bearer token required for enterprise worker endpoints "
            "(/enterprise/worker/*). Empty disables worker registration "
            "(fail closed for out-of-process workers)."
        ),
    )
    enterprise_user_token: str = Field(
        default="",
        description=(
            "Bearer token for enterprise client APIs. Empty requires "
            "per-identity registration via IdentityProvider before use."
        ),
    )
    enterprise_lease_seconds: float = Field(
        default=30.0, ge=1.0,
        description="Execution lease TTL for enterprise workers",
    )
    enterprise_max_dispatch_attempts: int = Field(
        default=3, ge=1,
        description="Bounded service-level dispatch retries before dead-letter",
    )

    # Paths
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    docs_dir: Path = Field(default=PROJECT_ROOT / "docs")

    # Phase 15 H8 — deployment posture
    production_mode: bool = Field(
        default=False,
        description=(
            "Deployment marker. When true, validate_production_readiness() "
            "treats unsafe configuration as BLOCKING; /ready reports 503. "
            "Local development leaves it false (warnings only)."
        ),
    )

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

    def validate_production_readiness(
        self,
    ) -> tuple[list[str], list[str]]:
        """Assess deployment readiness — Phase 15 H8.

        Returns (blockers, warnings). Blockers are conditions that make a
        production deployment unsafe (they fail the /ready endpoint when
        production_mode is set); warnings surface silently-unsafe dev
        defaults without changing local behavior.

        Messages name settings, never values (secret safety).
        """
        from app.config.settings import is_free_tier_model  # local import

        blockers: list[str] = []
        warnings: list[str] = []

        if not self.api_token:
            warnings.append(
                "api_token is empty: /api/* endpoints are UNAUTHENTICATED "
                "(localhost dev only)"
            )
            if self.production_mode:
                blockers.append(
                    "api_token is empty: authentication must be enabled "
                    "before production exposure"
                )

        if not self.vault_encryption_key:
            warnings.append(
                "vault_encryption_key is empty: vault is stored as "
                "plaintext (dev/test only)"
            )
            if self.production_mode:
                blockers.append(
                    "vault_encryption_key is empty: vault must be "
                    "encrypted at rest in production"
                )

        if not self.enterprise_worker_token:
            if self.production_mode:
                blockers.append(
                    "enterprise_worker_token is empty: out-of-process "
                    "worker registration is disabled (fail closed)"
                )

        if self.production_mode and self.allow_anonymous_model_with_vault:
            blockers.append(
                "allow_anonymous_model_with_vault is true in production: "
                "contested data retention (audit Z6) forbids the anonymous "
                "model for real PII"
            )
        elif (
            self.production_mode
            and is_free_tier_model(self.openrouter_model)
            and self.vault_encryption_key
        ):
            blockers.append(
                "openrouter_model is an anonymous free-tier model while "
                "vault encryption is configured: pin a named provider "
                "before processing real PII"
            )
        elif is_free_tier_model(self.openrouter_model):
            warnings.append(
                "openrouter_model is an anonymous free-tier model with "
                "contested data retention — do not use with real PII"
            )

        if not self.document_allowed_dirs:
            warnings.append(
                "document_allowed_dirs is empty: upload confinement is "
                "disabled"
            )

        return blockers, warnings

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
