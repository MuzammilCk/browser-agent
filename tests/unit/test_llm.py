"""Unit tests for LLM gateway — all mocked, no real API calls."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.base import LLMGateway
from app.llm.openrouter import OpenRouterGateway
from app.llm.retry import RetryPolicy
from app.llm.schemas import (
    LLMError,
    LLMBadRequestError,
    LLMMalformedResponseError,
    LLMRateLimitError,
    LLMResponse,
    LLMServerError,
    LLMTimeoutError,
    LLMUsage,
)
from app.config.settings import Settings


# ═══════════════════════════════════════════════════════════════
# LLMGateway PROTOCOL
# ═══════════════════════════════════════════════════════════════

class TestLLMGatewayProtocol:
    """Verify the LLMGateway protocol is properly defined."""

    def test_openrouter_implements_protocol(self) -> None:
        """OpenRouterGateway satisfies the LLMGateway protocol."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings)
        assert isinstance(gateway, LLMGateway)

    def test_protocol_has_complete_method(self) -> None:
        """Protocol requires complete() method."""
        assert hasattr(LLMGateway, "complete")

    def test_protocol_has_close_method(self) -> None:
        """Protocol requires close() method."""
        assert hasattr(LLMGateway, "close")


# ═══════════════════════════════════════════════════════════════
# LLMResponse SCHEMAS
# ═══════════════════════════════════════════════════════════════

class TestLLMSchemas:
    """Test LLM response schemas."""

    def test_llm_response_defaults(self) -> None:
        resp = LLMResponse()
        assert resp.content == ""
        assert resp.parsed is None
        assert resp.usage.total_tokens == 0

    def test_llm_usage(self) -> None:
        usage = LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert usage.total_tokens == 150

    def test_error_hierarchy(self) -> None:
        """All LLM errors inherit from LLMError."""
        from app.llm.schemas import LLMError
        assert issubclass(LLMTimeoutError, LLMError)
        assert issubclass(LLMBadRequestError, LLMError)
        assert issubclass(LLMServerError, LLMError)
        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMMalformedResponseError, LLMError)


# ═══════════════════════════════════════════════════════════════
# RETRY POLICY
# ═══════════════════════════════════════════════════════════════

class TestRetryPolicy:
    """Test bounded retry behavior."""

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self) -> None:
        """Retries on LLMTimeoutError."""
        policy = RetryPolicy(max_retries=2, base_delay=0.01)
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise LLMTimeoutError("timeout")
            return "success"

        result = await policy.execute(flaky_func)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self) -> None:
        """Retries on LLMRateLimitError."""
        policy = RetryPolicy(max_retries=2, base_delay=0.01)
        call_count = 0

        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise LLMRateLimitError("429")
            return "ok"

        result = await policy.execute(flaky_func)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_no_retry_on_bad_request(self) -> None:
        """Does NOT retry on LLMBadRequestError."""
        policy = RetryPolicy(max_retries=3, base_delay=0.01)

        async def bad_request():
            raise LLMBadRequestError("400 bad request")

        with pytest.raises(LLMBadRequestError):
            await policy.execute(bad_request)

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self) -> None:
        """Raises LLMError after all retries exhausted."""
        policy = RetryPolicy(max_retries=2, base_delay=0.01)

        async def always_fail():
            raise LLMTimeoutError("timeout")

        with pytest.raises(LLMError, match="All 3 attempts failed"):
            await policy.execute(always_fail)

    @pytest.mark.asyncio
    async def test_retry_on_server_error(self) -> None:
        """Retries on LLMServerError."""
        policy = RetryPolicy(max_retries=2, base_delay=0.01)
        call_count = 0

        async def server_error():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise LLMServerError("500")
            return "recovered"

        result = await policy.execute(server_error)
        assert result == "recovered"


# ═══════════════════════════════════════════════════════════════
# OPENROUTER GATEWAY (mocked HTTP)
# ═══════════════════════════════════════════════════════════════

def _mock_openrouter_response(
    content: str = '{"action": "click", "target_ref": "e1"}',
    model: str = "test-model",
    tokens: int = 100,
    status_code: int = 200,
) -> MagicMock:
    """Create a mock OpenRouter API response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {
        "id": "test-req-123",
        "model": model,
        "choices": [
            {
                "message": {"content": content, "role": "assistant"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": tokens // 2,
            "completion_tokens": tokens // 2,
            "total_tokens": tokens,
        },
    }
    resp.text = json.dumps(resp.json.return_value)
    return resp


class TestOpenRouterGateway:
    """Test OpenRouter gateway with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_successful_completion(self) -> None:
        """Successful API call returns parsed response."""
        settings = Settings(openrouter_api_key="test-key", openrouter_model="test-model")
        gateway = OpenRouterGateway(settings)

        mock_resp = _mock_openrouter_response()
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        gateway._client = mock_client

        result = await gateway.complete(
            system="You are a test assistant.",
            user="Hello",
        )

        assert result.content == '{"action": "click", "target_ref": "e1"}'
        assert result.parsed == {"action": "click", "target_ref": "e1"}
        assert result.usage.total_tokens == 100
        assert result.model == "test-model"
        assert result.request_id == "test-req-123"

    @pytest.mark.asyncio
    async def test_structured_output_with_schema(self) -> None:
        """Schema is included in payload when provided."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings)

        mock_resp = _mock_openrouter_response()
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        gateway._client = mock_client

        schema = {
            "type": "object",
            "properties": {"action": {"type": "string"}},
        }
        await gateway.complete(
            system="test",
            user="test",
            schema=schema,
        )

        # Verify schema was in the request
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "response_format" in payload
        assert payload["response_format"]["json_schema"]["schema"] == schema

    @pytest.mark.asyncio
    async def test_timeout_raises_error(self) -> None:
        """Timeout raises LLMError (wrapped by retry)."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings, retry_policy=RetryPolicy(max_retries=0))

        mock_client = AsyncMock()
        import httpx
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        mock_client.is_closed = False
        gateway._client = mock_client

        with pytest.raises(LLMError):
            await gateway.complete(system="test", user="test")

    @pytest.mark.asyncio
    async def test_rate_limit_raises_error(self) -> None:
        """429 raises LLMError (wrapped by retry)."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings, retry_policy=RetryPolicy(max_retries=0))

        mock_resp = _mock_openrouter_response(status_code=429)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        gateway._client = mock_client

        with pytest.raises(LLMError):
            await gateway.complete(system="test", user="test")

    @pytest.mark.asyncio
    async def test_server_error_raises_error(self) -> None:
        """5xx raises LLMError (wrapped by retry)."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings, retry_policy=RetryPolicy(max_retries=0))

        mock_resp = _mock_openrouter_response(status_code=500)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        gateway._client = mock_client

        with pytest.raises(LLMError):
            await gateway.complete(system="test", user="test")

    @pytest.mark.asyncio
    async def test_bad_request_raises_error(self) -> None:
        """4xx (not 429) raises LLMBadRequestError."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings, retry_policy=RetryPolicy(max_retries=0))

        mock_resp = _mock_openrouter_response(status_code=400)
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        gateway._client = mock_client

        with pytest.raises(LLMBadRequestError):
            await gateway.complete(system="test", user="test")

    @pytest.mark.asyncio
    async def test_malformed_response_raises_error(self) -> None:
        """Missing choices in response raises LLMMalformedResponseError."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings, retry_policy=RetryPolicy(max_retries=0))

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"no_choices_here": True}
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        gateway._client = mock_client

        with pytest.raises(LLMMalformedResponseError):
            await gateway.complete(system="test", user="test")

    @pytest.mark.asyncio
    async def test_non_json_content_returns_raw(self) -> None:
        """Non-JSON content returns raw string, parsed=None."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings)

        mock_resp = _mock_openrouter_response(content="Just plain text, not JSON")
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.is_closed = False
        gateway._client = mock_client

        result = await gateway.complete(system="test", user="test")
        assert result.content == "Just plain text, not JSON"
        assert result.parsed is None

    @pytest.mark.asyncio
    async def test_close_cleans_up(self) -> None:
        """close() cleans up the HTTP client."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(settings)

        mock_client = AsyncMock()
        mock_client.is_closed = False
        gateway._client = mock_client

        await gateway.close()
        mock_client.aclose.assert_called_once()
        assert gateway._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Gateway works as async context manager."""
        settings = Settings(openrouter_api_key="test-key")
        async with OpenRouterGateway(settings) as gateway:
            assert gateway is not None


# ═══════════════════════════════════════════════════════════════
# INTEGRATION: GATEWAY + RETRY
# ═══════════════════════════════════════════════════════════════

class TestGatewayRetryIntegration:
    """Test gateway with retry policy integrated."""

    @pytest.mark.asyncio
    async def test_retry_then_success(self) -> None:
        """Gateway retries on timeout then succeeds."""
        settings = Settings(openrouter_api_key="test-key")
        gateway = OpenRouterGateway(
            settings, retry_policy=RetryPolicy(max_retries=2, base_delay=0.01)
        )

        call_count = 0
        original_do_request = gateway._do_request

        async def flaky_request(payload):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise LLMTimeoutError("timeout")
            return _mock_openrouter_response().json()

        gateway._do_request = flaky_request

        result = await gateway.complete(system="test", user="test")
        assert result.content != ""
        assert call_count == 3
