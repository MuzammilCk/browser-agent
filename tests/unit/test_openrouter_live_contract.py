"""Phase 4 regression: adapter + REAL gateway, mocked HTTP (no live API).

The offline stub-gateway tests (test_openrouter_decision_model.py) can
miss contract bugs between the adapter and the real gateway because the
stub accepts whatever the adapter sends. The Phase 4 live smoke test
exposed exactly such a bug: the adapter passed the pre-built
``{name, strict, schema}`` envelope to the gateway, which wraps ``schema=``
into ``response_format.json_schema`` itself — a double wrap the API
rejects with 400 before auth even matters.

These tests wire ``OpenRouterDecisionModel`` to the REAL
``OpenRouterGateway`` with only the HTTP client mocked, proving the
exact wire payload the adapter+gateway pair produces and how non-JSON
model content flows into ``InvalidModelOutput``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.reasoning import InvalidModelOutput, OpenRouterDecisionModel
from app.agent.reasoning.protocol import build_decision_json_schema
from app.config.settings import Settings
from app.llm.openrouter import OpenRouterGateway

VALID_DECISION = {
    "decision_type": "tool_call",
    "tool_name": "observe_page",
    "arguments": {},
    "action": None,
    "reason": "",
    "question": "",
    "plan": [],
    "confidence": None,
}


def _live_shaped_response(content: str):
    """Mock ONLY the HTTP layer of the real gateway (status/json/text).
    MagicMock response (the gateway reads .json()/.text synchronously);
    the client itself stays AsyncMock (the gateway awaits .post)."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "id": "test-req-123",
        "model": "test-model",
        "choices": [
            {
                "message": {"content": content, "role": "assistant"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    resp.text = json.dumps(resp.json.return_value)
    return resp


@pytest.fixture
def gateway() -> OpenRouterGateway:
    gateway = OpenRouterGateway(Settings(openrouter_api_key="test-key"))
    client = AsyncMock()
    client.is_closed = False
    gateway._client = client
    return gateway


class TestAdapterWithRealGateway:
    async def test_wire_payload_has_single_wrapped_strict_schema(self, gateway):
        """The decision schema reaches the wire EXACTLY once-wrapped:
        response_format.json_schema.schema is the inner JSON schema derived
        from ReasonerDecisionSchema — not a nested envelope-in-envelope."""
        adapter = OpenRouterDecisionModel(gateway)
        gateway._client.post.return_value = _live_shaped_response(
            json.dumps(VALID_DECISION)
        )

        decision = await adapter.decide(system="s", context="c")

        assert decision["decision_type"] == "tool_call"
        # Inspect the exact HTTP payload the real gateway built.
        call = gateway._client.post.call_args
        payload = call.kwargs.get("json") or call[1].get("json")
        response_format = payload["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "agent_decision"
        assert response_format["json_schema"]["strict"] is True
        inner = response_format["json_schema"]["schema"]
        assert inner["type"] == "object"
        assert "decision_type" in inner["properties"]
        # No double wrap: the inner schema is not itself an envelope.
        assert "name" not in inner
        assert "strict" not in inner
        assert "schema" not in inner
        # Matches the schema derivation contract.
        assert inner == build_decision_json_schema()["schema"]

    async def test_non_json_content_raises_invalid_model_output(self, gateway):
        """Real gateway + real adapter: unparseable model content arrives as
        parsed=None and must surface as InvalidModelOutput (the reasoner's
        bounded-retry → MODEL_FAILURE trigger)."""
        adapter = OpenRouterDecisionModel(gateway)
        gateway._client.post.return_value = _live_shaped_response(
            "I cannot comply as JSON."
        )

        with pytest.raises(InvalidModelOutput):
            await adapter.decide(system="s", context="c")

    async def test_valid_json_object_is_returned_unchanged(self, gateway):
        adapter = OpenRouterDecisionModel(gateway)
        gateway._client.post.return_value = _live_shaped_response(
            json.dumps(VALID_DECISION)
        )
        decision = await adapter.decide(system="s", context="c")
        assert decision == VALID_DECISION


class TestConfigurableMaxTokens:
    """Phase 14 live-validation regression: reasoning-style models spend
    hidden reasoning tokens from the SAME budget before emitting the visible
    JSON decision. The hardcoded 4096 default truncated the decision
    (finish_reason=length) and the reasoner failed closed with
    DECISION_PARSE_FAILED. The budget is now the configurable
    ``openrouter_max_tokens`` setting; the adapter passes no explicit budget,
    so the gateway default must flow through to the wire payload."""

    async def test_adapter_uses_gateway_configured_budget(self, gateway):
        from app.config.settings import Settings

        settings = Settings(
            openrouter_api_key="test-key",
            openrouter_max_tokens=16384,
        )
        from app.llm.openrouter import OpenRouterGateway as _GW

        real_gw = _GW(settings)
        real_gw._client = gateway._client  # mocked HTTP layer
        adapter = OpenRouterDecisionModel(real_gw)
        gateway._client.post.return_value = _live_shaped_response(
            json.dumps(VALID_DECISION)
        )
        await adapter.decide(system="s", context="c")
        call = gateway._client.post.call_args
        payload = call.kwargs.get("json") or call[1].get("json")
        assert payload["max_tokens"] == 16384

    async def test_default_budget_is_4096(self, gateway):
        from app.config.settings import Settings

        # NOTE: Settings reads .env, so the environment's configured budget
        # could differ from the code default; this test must be hermetic.
        settings = Settings(
            openrouter_api_key="test-key",
            openrouter_max_tokens=Settings.model_fields[
                "openrouter_max_tokens"
            ].default,
        )
        assert settings.openrouter_max_tokens == 4096
        # Explicit caller-supplied max_tokens still wins (back-compat).
        gateway._client.post.return_value = _live_shaped_response(
            json.dumps(VALID_DECISION)
        )
        await gateway.complete(
            system="s", user="c", schema=None, max_tokens=777,
        )
        call = gateway._client.post.call_args
        payload = call.kwargs.get("json") or call[1].get("json")
        assert payload["max_tokens"] == 777
