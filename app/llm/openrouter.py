"""OpenRouter LLM gateway implementation.

Phase 5 deliverables:
- OpenRouter authentication via API key
- Configurable model via env vars
- Structured JSON schema output
- Timeout/retry policy (bounded)
- Request/response logging with redaction
- Usage/cost metadata recording
- Fail-closed on errors
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.config.settings import Settings, get_settings
from app.llm.base import LLMGateway
from app.llm.retry import RetryPolicy
from app.llm.schemas import (
    LLMBadRequestError,
    LLMError,
    LLMMalformedResponseError,
    LLMRateLimitError,
    LLMResponse,
    LLMServerError,
    LLMTimeoutError,
    LLMUsage,
)

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


def _redact(text: str, max_len: int = 200) -> str:
    """Redact sensitive content for logging."""
    if len(text) > max_len:
        return text[:max_len] + "...[redacted]"
    return text


class OpenRouterGateway(LLMGateway):
    """OpenRouter API gateway with structured output support.

    Uses httpx async client with bounded retries.
    Model is configurable via OPENROUTER_MODEL env var.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._retry = retry_policy or RetryPolicy(max_retries=3)
        self._client: httpx.AsyncClient | None = None

    @property
    def model_name(self) -> str:
        """Resolved primary model string (P0-37 planning-mode visibility)."""
        return self._settings.openrouter_model

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/government-browser-agent",
            "X-Title": "Government Browser Agent",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self._settings.openrouter_timeout_seconds,
                    connect=10.0,
                ),
            )
        return self._client

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
        """Send a completion request to OpenRouter.

        Uses structured JSON output when schema is provided.
        Retries on timeout, 429, and 5xx errors.
        """
        model = self._settings.openrouter_model
        # Vision requests go to the configured vision model when set (audit C10)
        if images and self._settings.openrouter_vision_model:
            model = self._settings.openrouter_vision_model

        # Build messages
        messages = [{"role": "system", "content": system}]

        # Handle multimodal content
        if images:
            content: list[dict[str, Any]] = [{"type": "text", "text": user}]
            for img_bytes in images:
                import base64
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user})

        # Build payload
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Add structured output schema if provided
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "agent_decision",
                    "strict": True,
                    "schema": schema,
                },
            }

        # Execute with retries; on total failure, try the fallback model
        # once when configured (audit C10 — openrouter_fallback_model).
        start_time = time.monotonic()
        try:
            response = await self._retry.execute(self._do_request, payload)
        except LLMError:
            fallback = self._settings.openrouter_fallback_model
            if not fallback or fallback == model:
                raise
            logger.warning(
                "Primary model '%s' failed after retries — trying fallback '%s'",
                model, fallback,
            )
            payload["model"] = fallback
            response = await self._retry.execute(self._do_request, payload)
        latency_ms = (time.monotonic() - start_time) * 1000

        # Parse response
        return self._parse_response(response, model, latency_ms)

    async def _do_request(self, payload: dict) -> dict:
        """Execute a single HTTP request to OpenRouter."""
        client = await self._get_client()

        logger.debug(
            "OpenRouter request: model=%s, messages=%d",
            payload.get("model"),
            len(payload.get("messages", [])),
        )

        try:
            resp = await client.post(
                OPENROUTER_API_URL,
                headers=self._headers,
                json=payload,
            )
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"OpenRouter request timed out: {e}") from e
        except httpx.HTTPError as e:
            raise LLMServerError(f"OpenRouter HTTP error: {e}") from e

        # Handle status codes
        if resp.status_code == 429:
            raise LLMRateLimitError(f"OpenRouter rate limited: {resp.status_code}")
        elif resp.status_code >= 500:
            raise LLMServerError(f"OpenRouter server error: {resp.status_code}")
        elif resp.status_code >= 400:
            raise LLMBadRequestError(
                f"OpenRouter bad request: {resp.status_code} — {resp.text[:500]}"
            )

        try:
            return resp.json()
        except Exception as e:
            raise LLMServerError(f"Failed to parse OpenRouter response: {e}") from e

    def _parse_response(
        self, data: dict, model: str, latency_ms: float
    ) -> LLMResponse:
        """Parse OpenRouter response into LLMResponse."""
        try:
            choice = data["choices"][0]
            message = choice.get("message", {})
            content = message.get("content", "")
            finish_reason = choice.get("finish_reason", "")

            # Parse usage
            usage_data = data.get("usage", {})
            usage = LLMUsage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
                cost_usd=usage_data.get("cost"),
            )

            # Try to parse JSON content
            parsed = None
            if content:
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    # Content is not JSON — that's okay for non-schema requests
                    pass

            request_id = data.get("id", "")

            logger.info(
                "OpenRouter response: model=%s, tokens=%d, latency=%.0fms, finish=%s",
                model,
                usage.total_tokens,
                latency_ms,
                finish_reason,
            )

            return LLMResponse(
                content=content,
                parsed=parsed,
                usage=usage,
                model=data.get("model", model),
                finish_reason=finish_reason,
                request_id=request_id,
                latency_ms=latency_ms,
            )

        except (KeyError, IndexError) as e:
            raise LLMMalformedResponseError(
                f"Unexpected OpenRouter response structure: {e}"
            ) from e

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> OpenRouterGateway:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
