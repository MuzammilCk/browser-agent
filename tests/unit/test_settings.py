"""Unit tests for application settings."""

from app.config.settings import Settings


def test_default_settings() -> None:
    """Settings load with defaults (ignoring .env file)."""
    settings = Settings(_env_file=None)
    assert settings.openrouter_model == "anthropic/claude-sonnet-4-20250514"
    assert settings.openrouter_timeout_seconds == 60
    assert settings.headless is True
    assert settings.log_level == "INFO"


def test_settings_model_config() -> None:
    """Settings accepts extra fields gracefully."""
    settings = Settings(OPENROUTER_API_KEY="test-key-12345")
    assert settings.openrouter_api_key == "test-key-12345"


def test_settings_timeout_bounds() -> None:
    """Timeout is bounded."""
    settings = Settings(openrouter_timeout_seconds=30)
    assert settings.openrouter_timeout_seconds == 30
