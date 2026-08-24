"""LLM Gateway protocol — abstract interface for LLM providers.

Per architecture doc: the rest of the system depends only on this protocol.
Only OpenRouterGateway knows how to construct OpenRouter requests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.llm.schemas import LLMResponse


@runtime_checkable
class LLMGateway(Protocol):
    """Protocol for LLM gateway implementations.

    The gateway receives structured requests and returns typed responses.
    Implementation details (OpenRouter, API keys, retries) are hidden.
    """

    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: dict | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        images: list[bytes] | None = None,
    ) -> LLMResponse:
        """Send a completion request and return a structured response.

        Args:
            system: System prompt (trusted instructions).
            user: User message (may contain PageObservation, task, etc.).
            schema: Optional JSON schema for structured output.
            temperature: Generation temperature (0 = deterministic).
            max_tokens: Maximum tokens to generate.
            images: Optional list of image bytes for multimodal requests.

        Returns:
            LLMResponse with content, usage, and metadata.

        Raises:
            LLMTimeoutError: Request timed out.
            LLMBadRequestError: Invalid request (4xx).
            LLMServerError: Server error (5xx).
            LLMRateLimitError: Rate limited (429).
            LLMMalformedResponseError: Response doesn't match schema.
        """
        ...

    async def close(self) -> None:
        """Clean up resources."""
        ...
