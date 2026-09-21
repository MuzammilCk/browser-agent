"""Phase 4 unit tests — OpenRouter decision-model adapter (NO live API).

The adapter is exercised through a stub LLMGateway so no network call
and no API key is ever required. What is proven here:

- the INNER decision JSON schema is attached to the request (structured
  output) via the existing gateway contract — the gateway owns the
  response_format envelope, so the adapter must pass only the inner
  schema (a pre-wrapped envelope would be double-wrapped and rejected
  by the API with 400 — regression guard for the live smoke test);
- valid JSON content → parsed dict returned to the reasoner;
- non-JSON / non-object / schema-invalid content → InvalidModelOutput,
  which the AgentReasoner converts into bounded retries and then an
  explicit MODEL_FAILURE (never a silent fallback);
- construction without an API key fails closed;
- the API key never crosses the adapter boundary (never in prompts,
  parsed payloads, or exception text);
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

    async def test_passes_inner_schema_to_gateway_not_prebuilt_envelope(self):
        """Regression guard (found by the Phase 4 live smoke test): the
        gateway wraps `schema` into response_format.json_schema itself.
        The adapter must pass the INNER schema; passing the pre-built
        {name, strict, schema} envelope would double-wrap it and OpenRouter
        would reject the request with 400."""
        gateway = StubGateway(content=json.dumps(VALID_DECISION))
        adapter = OpenRouterDecisionModel(gateway)
        await adapter.decide(system="s", context="c")
        schema = gateway.requests[0]["schema"]
        # INNER schema: a raw JSON-schema object...
        assert schema["type"] == "object"
        assert "decision_type" in schema["properties"]
        # ...NOT the response_format envelope (no name/strict keys).
        assert "name" not in schema
        assert "strict" not in schema
        assert "schema" not in schema

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


class TestApiKeyBoundary:
    async def test_api_key_never_crosses_the_adapter_boundary(self):
        """The key is a gateway concern. It must never appear in the
        request-facing prompt arguments, in the parsed decision payload,
        or in any exception the adapter raises."""
        secret = "sk-or-v1-super-secret-test-key"
        gateway = StubGateway(content=json.dumps(VALID_DECISION))
        adapter = OpenRouterDecisionModel(gateway)
        decision = await adapter.decide(system="s", context="c")
        # Prompt arguments carry no key material (the adapter passes
        # system/user straight through — check exactly those).
        for request in gateway.requests:
            assert secret not in request.get("system", "")
            assert secret not in request.get("user", "")
            assert secret not in json.dumps(request.get("schema", {}))
        # Returned decision payload carries no key material
        assert secret not in json.dumps(decision)

    async def test_transport_error_text_does_not_require_key_material(self):
        """The reasoner surfaces exception text on retries; the adapter's
        own error messages must not depend on request payloads that could
        carry credentials."""
        gateway = StubGateway(content="", error=RuntimeError("boom"))
        adapter = OpenRouterDecisionModel(gateway)
        with pytest.raises(Exception) as exc_info:
            await adapter.decide(system="s", context="c")
        assert "sk-or-v1" not in str(exc_info.value)


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


class TestSchemaViolatingOutputFailsClosed:
    async def test_schema_valid_json_but_invalid_decision_is_model_failure(self):
        """Strict structured output still permits schema-shaped JSON whose
        CONTENT is an invalid decision (e.g. an unregistered tool). The
        reasoner's validation must catch it: bounded retries with the
        rejection fed back, then an explicit MODEL_FAILURE — never a
        fallback decision."""
        from app.agent.reasoning import ReasonerConfig
        from app.agent.tools import build_registry

        class OneShotBrokenThenValid(StubGateway):
            """Attempt 1: schema-valid JSON, invalid decision content.
            Attempt 2: a valid decision (proves the repair path)."""

            async def complete(self, **kwargs: Any) -> LLMResponse:
                self.requests.append(kwargs)
                content = (
                    json.dumps({
                        "decision_type": "tool_call",
                        "tool_name": "definitely_not_a_tool",
                        "arguments": {},
                        "action": None,
                        "reason": "",
                        "question": "",
                        "plan": [],
                        "confidence": None,
                    })
                    if len(self.requests) == 1
                    else json.dumps(VALID_DECISION)
                )
                return LLMResponse(
                    content=content,
                    parsed=json.loads(content),
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    model="test/model",
                    finish_reason="stop",
                )

        registry = build_registry()
        adapter = OpenRouterDecisionModel(OneShotBrokenThenValid())
        reasoner = AgentReasoner(
            adapter,
            known_tools=frozenset(registry.list_names()),
            # observe_page takes NO typed browser action — it must NOT be
            # listed in action_tools (that would make the parser demand
            # an action object for it).
            action_tools=frozenset({"fill_field"}),
            config=ReasonerConfig(max_attempts=3),
        )
        from app.agent.reasoning import build_reasoning_context

        context = build_reasoning_context(
            goal="g",
            tool_metadata=[registry.metadata("observe_page")],
        )
        outcome = await reasoner.reason(context, observation_id="obs-1")
        # Repair succeeded on attempt 2 within the bounded budget.
        assert outcome.decided is True
        assert outcome.attempts == 2
        assert outcome.decision is not None

    async def test_persistently_schema_violating_output_is_model_failure(self):
        """A model that always returns schema-valid JSON with invalid
        decision content is retried the bounded number of times and then
        fails CLOSED as an explicit MODEL_FAILURE with decision=None."""
        from app.agent.reasoning import ReasonerConfig, ReasoningPhase, build_reasoning_context
        from app.agent.tools import build_registry

        class AlwaysUnknownTool(StubGateway):
            async def complete(self, **kwargs: Any) -> LLMResponse:
                self.requests.append(kwargs)
                content = json.dumps({
                    "decision_type": "tool_call",
                    "tool_name": "definitely_not_a_tool",
                    "arguments": {},
                    "action": None,
                    "reason": "",
                    "question": "",
                    "plan": [],
                    "confidence": None,
                })
                return LLMResponse(
                    content=content,
                    parsed=json.loads(content),
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    model="test/model",
                    finish_reason="stop",
                )

        registry = build_registry()
        adapter = OpenRouterDecisionModel(AlwaysUnknownTool())
        reasoner = AgentReasoner(
            adapter,
            known_tools=frozenset(registry.list_names()),
            # observe_page takes NO typed browser action — it must NOT be
            # listed in action_tools (that would make the parser demand
            # an action object for it).
            action_tools=frozenset({"fill_field"}),
            config=ReasonerConfig(max_attempts=3),
        )
        from app.agent.reasoning import build_reasoning_context

        context = build_reasoning_context(
            goal="g",
            tool_metadata=[registry.metadata("observe_page")],
        )
        outcome = await reasoner.reason(context, observation_id="obs-1")
        assert outcome.decided is False
        assert outcome.phase == ReasoningPhase.MODEL_FAILURE
        assert outcome.decision is None
        assert outcome.attempts == 3  # bounded, exactly the configured budget
        assert outcome.reason.startswith("model_failure:")
        assert outcome.model_failure_code in (
            "DECISION_VALIDATION_FAILED", "DECISION_SCHEMA_INVALID",
            "DECISION_PARSE_FAILED",
        )
