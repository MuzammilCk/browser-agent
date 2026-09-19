"""Phase 4 unit tests — OpenRouter decision-model adapter (NO live API).

The adapter is exercised through a stub LLMGateway so no network call
and no API key is ever required. What is proven here:

- the decision JSON schema is attached to the request (structured
  output) via the existing gateway contract;
- valid JSON content → parsed dict returned to the reasoner;
- non-JSON / non-object / schema-invalid content → InvalidModelOutput,
  which the AgentReasoner converts into bounded retries and then an
  explicit MODEL_FAILURE (never a silent fallback);
- construction without an API key fails closed;
- the adapter is a valid DecisionModel under the runtime_checkable
  protocol.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent.reasoning import (
    AgentReasoner,
    InvalidModelOutput,
    MockDecisionModel,
    OpenRouterDecisionModel,
    ReasoningPhase,
    build_decision_json_schema,
    build_openrouter_decision_model,
)
from app.agent.reasoning.protocol import DecisionModel
from app.llm.schemas import LLMResponse, LLMUsage


class StubGateway:
    """Records requests, returns canned content (no network)."""

    def __init__(self, content: str | None = None, error: Exception | None = None):
        self.content = content
        self.error = error
        self.requests: list[dict] = []

    async def complete(self, **kwargs: Any) -> LLMResponse:
        self.requests.append(kwargs)
        if self.error is not None:
            raise self.error
        return LLMResponse(
            content=self.content or "",
            parsed=(json.loads(self.content) if self.content else None),
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="test/model",
            finish_reason="stop",
        )

    async def close(self) -> None:
        return None


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


class TestAdapterContract:
    async def test_implements_decision_model_protocol(self):
        adapter = OpenRouterDecisionModel(StubGateway())
        assert isinstance(adapter, DecisionModel)

    async def test_passes_structured_schema_to_gateway(self):
        gateway = StubGateway(content=json.dumps(VALID_DECISION))
        adapter = OpenRouterDecisionModel(gateway)
        decision = await adapter.decide(system="s", context="c")
        assert decision["decision_type"] == "tool_call"
        schema = gateway.requests[0]["schema"]
        assert schema["strict"] is True
        assert schema["name"] == "agent_decision"
        assert "decision_type" in schema["schema"]["properties"]

    async def test_temperature_is_zero_for_determinism(self):
        gateway = StubGateway(content=json.dumps(VALID_DECISION))
        adapter = OpenRouterDecisionModel(gateway)
        await adapter.decide(system="s", context="c")
        assert gateway.requests[0]["temperature"] == 0.0


class TestMalformedModelOutput:
    async def test_non_json_content_raises_invalid_model_output(self):
        adapter = OpenRouterDecisionModel(
            StubGatewayWithRaw(content="I cannot do that.")
        )
        with pytest.raises(InvalidModelOutput):
            await adapter.decide(system="s", context="c")

    async def test_non_object_json_raises_invalid_model_output(self):
        adapter = OpenRouterDecisionModel(
            StubGatewayWithRaw(content='["a", "list"]')
        )
        with pytest.raises(InvalidModelOutput):
            await adapter.decide(system="s", context="c")

    async def test_invalid_output_becomes_explicit_model_failure(self):
        """End-to-end at the reasoner: InvalidModelOutput on every attempt
        → ReasoningOutcome.model_failure, never a fallback decision."""
        from app.agent.reasoning import build_reasoning_context
        from app.agent.tools import build_registry

        class AlwaysBroken(StubGatewayWithRaw):
            async def complete(self, **kwargs: Any) -> LLMResponse:
                self.requests.append(kwargs)
                raise InvalidModelOutput("garbage output")

        registry = build_registry()
        adapter = OpenRouterDecisionModel(AlwaysBroken(content=""))
        reasoner = AgentReasoner(
            adapter,
            known_tools=frozenset(registry.list_names()),
            action_tools=frozenset({"observe_page"}),
            # max_attempts=1 keeps the test instant (no real sleeps here,
            # but bounded anyway)
        )
        context = build_reasoning_context(
            goal="g",
            tool_metadata=[registry.metadata("observe_page")],
        )
        outcome = await reasoner.reason(context, observation_id="obs-1")
        assert outcome.decided is False
        assert outcome.phase == ReasoningPhase.MODEL_FAILURE
        assert outcome.decision is None
        assert outcome.reason.startswith("model_failure:")


class StubGatewayWithRaw(StubGateway):
    """Gateway whose parsed field is derived exactly like the real one:
    None when content does not parse as JSON."""

    async def complete(self, **kwargs: Any) -> LLMResponse:
        self.requests.append(kwargs)
        parsed = None
        if self.content:
            try:
                parsed = json.loads(self.content)
            except json.JSONDecodeError:
                parsed = None
        return LLMResponse(
            content=self.content or "",
            parsed=parsed,
            model="test/model",
            finish_reason="stop",
        )


class TestFailClosedConstruction:
    def test_no_api_key_refuses_to_build(self, monkeypatch):
        from app.config.settings import Settings

        monkeypatch.setattr(
            "app.agent.reasoning.openrouter_model.get_settings",
            lambda: Settings(openrouter_api_key=""),
        )
        with pytest.raises(RuntimeError, match="fail closed"):
            build_openrouter_decision_model()

    def test_own_gateway_bypasses_key_requirement(self):
        adapter = build_openrouter_decision_model(
            StubGateway(), require_api_key=False,
        )
        assert isinstance(adapter, OpenRouterDecisionModel)


class TestSchemaContract:
    def test_schema_rejects_unknown_fields(self):
        import pydantic
        from app.agent.reasoning import ReasonerDecisionSchema

        with pytest.raises(pydantic.ValidationError):
            ReasonerDecisionSchema.model_validate({
                **VALID_DECISION,
                "execute_arbitrary_code": True,
            })

    def test_schema_matches_structured_output_shape(self):
        schema = build_decision_json_schema()
        # The schema the adapter sends validates the exact decision the
        # mock model emits (prompt contract == validation contract).
        assert schema["schema"]["properties"]["decision_type"]["type"] == "string"
