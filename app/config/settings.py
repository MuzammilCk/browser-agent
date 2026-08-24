"""Application settings loaded from environment variables."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application configuration. Reads from .env and environment variables."""

    # OpenRouter
    openrouter_api_key: str = Field(default="", description="OpenRouter API key")
    openrouter_model: str = Field(
        default="anthropic/claude-sonnet-4-20250514",
        description="Primary reasoning model",
    )
    openrouter_vision_model: str = Field(
        default="anthropic/claude-sonnet-4-20250514",
        description="Vision-capable model for screenshot fallback",
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

    # Application
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/app.db",
        description="Database connection URL",
    )
    log_level: str = Field(default="INFO", description="Logging level")

    # Browser
    headless: bool = Field(default=True, description="Run browser in headless mode")

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
