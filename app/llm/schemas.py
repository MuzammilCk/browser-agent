"""LLM request/response schemas and error types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMUsage:
    """Token usage and cost metadata from an LLM response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = None


@dataclass
class LLMResponse:
    """Structured response from an LLM gateway."""

    content: str = ""
    parsed: dict[str, Any] | None = None
    usage: LLMUsage = field(default_factory=LLMUsage)
    model: str = ""
    finish_reason: str = ""
    request_id: str = ""
    latency_ms: float = 0.0


class LLMError(Exception):
    """Base class for LLM errors."""


class LLMTimeoutError(LLMError):
    """Request timed out."""


class LLMBadRequestError(LLMError):
    """Invalid request (4xx)."""


class LLMServerError(LLMError):
    """Server error (5xx)."""


class LLMRateLimitError(LLMError):
    """Rate limited (429)."""


class LLMMalformedResponseError(LLMError):
    """Response doesn't match expected schema."""
