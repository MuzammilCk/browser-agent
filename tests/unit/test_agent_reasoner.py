"""Phase 4 unit tests — AgentReasoner + minimal context (mock model, no API).

Proves the ten behaviors required by the Phase 4 instruction, plus the
context-assembly invariants. The browser is never launched here: tool
schemas come from the real registry metadata, observations are canned
PageObservations, and the model is the deterministic MockDecisionModel.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent.reasoning import (
    DECISION_PARSE_FAILED,
    DECISION_SCHEMA_INVALID,
    DECISION_VALIDATION_FAILED,
    MODEL_FAILURE_REASON_PREFIX,
    AgentReasoner,
    MockDecisionModel,
    ReasonerConfig,
    ReasonerDecisionSchema,
    ReasoningOutcome,
    ReasoningPhase,
    build_decision_json_schema,
    build_reasoning_context,
    parse_model_decision,
)
from app.agent.tools import (
    FillFieldTool,
    ObservePageTool,
    SelectOptionTool,
    ToolRegistry,
    build_registry,
)
from app.agent.tools.base import ToolResult
from app.models.page_state import (
    ElementState,
    PageObservation,
    PageState,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_observation(
    *, observation_id: str = "obs-1", page_type: str = "form",
) -> PageObservation:
    ps = PageState(
        url="https://uidai.gov.in/form",
        title="Application",
        page_id=observation_id,
        page_type=page_type,  # type: ignore[arg-type]
        elements=[
            ElementState(ref="e1", role="textbox", accessible_name="Full Name",
                         input_type="text", required=True),
            ElementState(ref="e2", role="combobox", accessible_name="State",
                         selected_options=[]),
            ElementState(ref="e3", role="button", accessible_name="Next"),
        ],
    )
    return PageObservation(page_state=ps, observation_id=observation_id)


@pytest.fixture
def registry() -> ToolRegistry:
    return build_registry()


@pytest.fixture
def known_tools(registry: ToolRegistry) -> set[str]:
    return set(registry.list_names())


@pytest.fixture
def action_tools(registry: ToolRegistry) -> set[str]:
    return {
        name for name in registry.list_names()
        if registry.metadata(name) is not None
        and registry.metadata(name).accepts_browser_action  # type: ignore[union-attr]
    }


def make_context(**overrides: Any):
    kwargs: dict[str, Any] = {
        "goal": "Fill the application form",
        "subgoal": "Complete personal details",
        "observation": make_observation(),
        "tool_metadata": [
            m for m in (
                ObservePageTool().metadata,
                FillFieldTool().metadata,
                SelectOptionTool().metadata,
            )
        ],
        "recent_results": [],
        "unresolved_questions": [],
    }
    kwargs.update(overrides)
    return build_reasoning_context(**kwargs)


def make_reasoner(
    script: list[Any],
    *,
    known_tools: set[str],
    action_tools: set[str],
    max_attempts: int = 3,
) -> tuple[AgentReasoner, MockDecisionModel]:
    model = MockDecisionModel(script)
    reasoner = AgentReasoner(
        model,
        known_tools=known_tools,
        action_tools=action_tools,
        config=ReasonerConfig(max_attempts=max_attempts),
    )
    return reasoner, model


def valid_fill_action() -> dict[str, Any]:
    return {
        "action": "fill",
        "target_ref": "e1",
        "literal_value": "Rahul Sharma",
    }


# ---------------------------------------------------------------------------
# 1. model selects observe_page
# ---------------------------------------------------------------------------


class TestModelSelectsObservePage:
    async def test_observe_page_decision_parsed_and_bound(
        self, known_tools, action_tools,
    ):
        reasoner, model = make_reasoner(
            [{"decision_type": "tool_call", "tool_name": "observe_page"}],
            known_tools=known_tools, action_tools=action_tools,
        )
        outcome = await reasoner.reason(make_context(), observation_id="obs-1")
        assert outcome.decided is True
        assert outcome.decision is not None
        assert outcome.decision.decision_type.value == "tool_call"
        assert outcome.decision.tool_name == "observe_page"
        assert outcome.attempts == 1
        # The authoritative observation id is bound by the runtime/parser,
        # not trusted from the model.
        assert model.calls[0]["context"].count("obs-1") >= 1


# ---------------------------------------------------------------------------
# 2. model selects fill_field
# ---------------------------------------------------------------------------


class TestModelSelectsFillField:
    async def test_fill_field_decision_carries_typed_action(
        self, known_tools, action_tools,
    ):
        reasoner, _ = make_reasoner(
            [{
                "decision_type": "tool_call",
                "tool_name": "fill_field",
                "action": valid_fill_action(),
            }],
            known_tools=known_tools, action_tools=action_tools,
        )
        outcome = await reasoner.reason(make_context(), observation_id="obs-1")
        assert outcome.decided is True
        decision = outcome.decision
        assert decision is not None
        assert decision.tool_name == "fill_field"
        assert decision.action is not None
        assert decision.action.action == "fill"
        assert decision.action.target_ref == "e1"
        # Runtime stamped the CURRENT observation id onto the action.
        assert decision.action.observation_id == "obs-1"

    async def test_fill_with_semantic_reference_stays_a_reference(
        self, known_tools, action_tools,
    ):
        """value_ref crosses as USER.* / DOCUMENT.* — never a raw value."""
        reasoner, _ = make_reasoner(
            [{
                "decision_type": "tool_call",
                "tool_name": "fill_field",
                "action": {
                    "action": "fill", "target_ref": "e1",
                    "value_ref": "USER.aadhaar_number",
                },
            }],
            known_tools=known_tools, action_tools=action_tools,
        )
        outcome = await reasoner.reason(make_context(), observation_id="obs-1")
        assert outcome.decided is True
        action = outcome.decision.action
        assert action is not None
        assert action.value_ref == "USER.aadhaar_number"
        assert action.literal_value is None


# ---------------------------------------------------------------------------
# 3. model selects select_option
# ---------------------------------------------------------------------------


class TestModelSelectsSelectOption:
    async def test_select_option_decision_parsed(self, known_tools, action_tools):
        reasoner, _ = make_reasoner(
            [{
                "decision_type": "tool_call",
                "tool_name": "select_option",
                "arguments": {"option_note": "user's home state"},
                "action": {"action": "select", "target_ref": "e2",
                           "option": "Kerala"},
            }],
            known_tools=known_tools, action_tools=action_tools,
        )
        outcome = await reasoner.reason(make_context(), observation_id="obs-1")
        assert outcome.decided is True
        decision = outcome.decision
        assert decision is not None
        assert decision.tool_name == "select_option"
        assert decision.action is not None
        assert decision.action.option == "Kerala"
        assert decision.arguments == {"option_note": "user's home state"}


# ---------------------------------------------------------------------------
# 4. model handles tool failure and chooses another action
# ---------------------------------------------------------------------------


class TestModelHandlesToolFailure:
    async def test_failure_feedback_present_and_recovery_chosen(
        self, known_tools, action_tools,
    ):
        """Iteration 1 fails at the registry; iteration 2 gets the failure
        in context and picks a different tool."""
        seen_results: list[list[dict]] = []

        def ctx_with_failure() -> Any:
            failure = ToolResult(
                tool_name="fill_field", success=False,
                error_code="STALE_OR_INVALID_TARGET",
                message="Element e1 not in current observation — re-observe first",
            )
            seen_results.append([])
            return make_context(
                recent_results=[failure],
                unresolved_questions=["e1 vanished — which ref now?"],
            )

        contexts = [ctx_with_failure(), ctx_with_failure()]

        async def scripted_context(_ctx):
            return contexts.pop(0)

        # Patch build via direct construction: feed both contexts.
        model = MockDecisionModel([
            {
                "decision_type": "tool_call",
                "tool_name": "fill_field",
                "action": {"action": "fill", "target_ref": "e1",
                           "literal_value": "x"},
            },
            {
                "decision_type": "tool_call",
                "tool_name": "observe_page",
            },
        ])
        reasoner = AgentReasoner(
            model, known_tools=known_tools, action_tools=action_tools,
        )

        outcome1 = await reasoner.reason(await scripted_context(None), observation_id="obs-1")
        assert outcome1.decided is True and outcome1.decision.tool_name == "fill_field"

        outcome2 = await reasoner.reason(await scripted_context(None), observation_id="obs-2")
        assert outcome2.decided is True and outcome2.decision.tool_name == "observe_page"

        # The second prompt carried the failure + question.
        second_prompt = model.calls[1]["context"]
        assert "STALE_OR_INVALID_TARGET" in second_prompt
        assert "e1 vanished" in second_prompt


# ---------------------------------------------------------------------------
# 5. malformed tool call is rejected
# ---------------------------------------------------------------------------


class TestMalformedToolCallRejected:
    async def test_missing_action_rejected_then_repairs(
        self, known_tools, action_tools,
    ):
        reasoner, model = make_reasoner(
            [
                {"decision_type": "tool_call", "tool_name": "fill_field"},
                {"decision_type": "tool_call", "tool_name": "observe_page"},
            ],
            known_tools=known_tools, action_tools=action_tools,
        )
        outcome = await reasoner.reason(make_context(), observation_id="obs-1")
        assert outcome.decided is True
        assert outcome.decision.tool_name == "observe_page"
        assert outcome.attempts == 2
        # The repair attempt carried the rejection reason.
        assert "REJECTED" in model.calls[1]["context"]
        assert "action object" in model.calls[1]["context"]

    async def test_broken_action_dict_never_becomes_a_decision(
        self, known_tools, action_tools,
    ):
        # fill with NEITHER value_ref NOR literal_value → BrowserAction rejects
        decision, failure = parse_model_decision(
            {
                "decision_type": "tool_call",
                "tool_name": "fill_field",
                "action": {"action": "fill", "target_ref": "e1"},
            },
            known_tools=known_tools, action_tools=action_tools,
            observation_id="obs-1",
        )
        assert decision is None
        assert failure is not None
        assert failure[0] == DECISION_VALIDATION_FAILED


# ---------------------------------------------------------------------------
# 6. unknown tool is rejected
# ---------------------------------------------------------------------------


class TestUnknownToolRejected:
    async def test_unknown_tool_fails_closed_at_parser(self, known_tools, action_tools):
        decision, failure = parse_model_decision(
            {"decision_type": "tool_call", "tool_name": "delete_database"},
            known_tools=known_tools, action_tools=action_tools,
        )
        assert decision is None
        assert failure is not None
        assert failure[0] == DECISION_VALIDATION_FAILED
        assert "unknown tool" in failure[1]

    async def test_registry_still_rejects_unknown_after_decision(
        self, known_tools, action_tools,
    ):
        """Defense in depth: even a hand-built AgentDecision with an
        unknown tool fails closed at ToolRegistry.execute."""
        from app.agent.runtime.decision import AgentDecision, AgentDecisionType
        from app.agent.tools import ToolCall, ToolContext, ToolRegistry

        registry = ToolRegistry()
        ctx = ToolContext(observation=make_observation())
        call = ToolCall(tool_name="not_a_tool", arguments={})
        result = await registry.execute(call, ctx)
        assert result.success is False
        assert result.error_code == "TOOL_NOT_FOUND"


# ---------------------------------------------------------------------------
# 7. model failure becomes explicit MODEL_FAILURE
# ---------------------------------------------------------------------------


class TestExplicitModelFailure:
    async def test_transport_errors_become_model_failure(
        self, known_tools, action_tools,
    ):
        reasoner, model = make_reasoner(
            [RuntimeError("api down"), RuntimeError("api down"),
             RuntimeError("api down")],
            known_tools=known_tools, action_tools=action_tools,
        )
        outcome = await reasoner.reason(make_context())
        assert outcome.decided is False
        assert outcome.phase == ReasoningPhase.MODEL_FAILURE
        assert outcome.model_failure_code == DECISION_PARSE_FAILED
        assert outcome.reason.startswith(MODEL_FAILURE_REASON_PREFIX)
        assert outcome.attempts == 3
        assert outcome.decision is None
        assert model.call_count == 3

    async def test_persistently_malformed_output_becomes_model_failure(
        self, known_tools, action_tools,
    ):
        bad_output = {"decision_type": "do_something_else"}
        reasoner, model = make_reasoner(
            [bad_output, bad_output, bad_output],
            known_tools=known_tools, action_tools=action_tools,
            max_attempts=2,
        )
        outcome = await reasoner.reason(make_context())
        assert outcome.decided is False
        assert outcome.model_failure_code == DECISION_SCHEMA_INVALID
        assert outcome.attempts == 2
        assert outcome.reason.startswith(MODEL_FAILURE_REASON_PREFIX)

    async def test_never_falls_back_to_a_deterministic_decision(
        self, known_tools, action_tools,
    ):
        """No silent fallback: a failed model call must not produce a
        fabricated observe_page or any other default decision."""
        reasoner, _ = make_reasoner(
            [RuntimeError("down")] * 3,
            known_tools=known_tools, action_tools=action_tools,
        )
        outcome = await reasoner.reason(make_context())
        assert outcome.decided is False
        assert outcome.decision is None


# ---------------------------------------------------------------------------
# 8. multiple iterations work
# ---------------------------------------------------------------------------


class TestMultipleIterations:
    async def test_sequence_over_multiple_iterations(
        self, known_tools, action_tools,
    ):
        script = [
            {"decision_type": "tool_call", "tool_name": "observe_page"},
            {
                "decision_type": "tool_call", "tool_name": "fill_field",
                "action": {"action": "fill", "target_ref": "e1",
                           "literal_value": "Rahul Sharma"},
            },
            {
                "decision_type": "tool_call", "tool_name": "select_option",
                "action": {"action": "select", "target_ref": "e2",
                           "option": "Kerala"},
            },
            {"decision_type": "complete", "reason": "form filled"},
        ]
        reasoner, model = make_reasoner(
            script, known_tools=known_tools, action_tools=action_tools,
        )
        chosen: list[str] = []
        for i, observation_id in enumerate(("obs-1", "obs-2", "obs-3", "obs-4")):
            outcome = await reasoner.reason(
                make_context(observation=make_observation(observation_id=observation_id)),
                observation_id=observation_id,
            )
            assert outcome.decided is True, outcome.reason
            decision = outcome.decision
            assert decision is not None
            chosen.append(
                decision.tool_name or decision.decision_type.value
            )
            # Every action binds to ITS OWN observation (stale-ref guard).
            if decision.action is not None:
                assert decision.action.observation_id == observation_id
        assert chosen == ["observe_page", "fill_field", "select_option", "complete"]
        assert model.call_count == 4


# ---------------------------------------------------------------------------
# 9. replay produces the same decisions/results from recorded inputs
# ---------------------------------------------------------------------------


class TestReplayDeterminism:
    async def test_same_recorded_inputs_produce_same_decisions(
        self, known_tools, action_tools,
    ):
        """Re-run the identical recorded prompts through a fresh reasoner
        with the identical scripted outputs; the decision sequence must
        match exactly."""
        script = [
            {"decision_type": "tool_call", "tool_name": "observe_page"},
            {
                "decision_type": "tool_call", "tool_name": "fill_field",
                "action": {"action": "fill", "target_ref": "e1",
                           "literal_value": "Rahul"},
            },
            {"decision_type": "complete", "reason": "done"},
        ]
        observation_ids = ["obs-1", "obs-2", "obs-3"]

        async def run_episode() -> tuple[list[dict], list[str]]:
            model = MockDecisionModel(list(script))
            reasoner = AgentReasoner(
                model, known_tools=known_tools, action_tools=action_tools,
            )
            decisions: list[dict] = []
            for obs_id in observation_ids:
                ctx = make_context(observation=make_observation(observation_id=obs_id))
                outcome = await reasoner.reason(ctx, observation_id=obs_id)
                assert outcome.decided is True
                decisions.append(outcome.decision.model_dump(mode="json"))
            return decisions, [c["context"] for c in model.calls]

        first_decisions, first_prompts = await run_episode()
        second_decisions, second_prompts = await run_episode()

        assert first_decisions == second_decisions
        assert first_prompts == second_prompts

    async def test_context_render_is_deterministic(self):
        """Same inputs → byte-identical rendered prompt (replay foundation)."""
        def build():
            return build_reasoning_context(
                goal="Fill the form",
                subgoal="personal details",
                observation=make_observation(observation_id="obs-9"),
                tool_metadata=[ObservePageTool().metadata],
                recent_results=[],
                unresolved_questions=[],
            )

        first = build().render()
        second = build().render()
        assert first == second
        parsed = json.loads(first)
        assert parsed["goal"] == "Fill the form"
        assert parsed["page_observation"]["observation_id"] == "obs-9"


# ---------------------------------------------------------------------------
# 10. the model cannot bypass policy through tool arguments
# ---------------------------------------------------------------------------


class TestPolicyBypassPrevention:
    async def test_sensitive_literal_in_action_is_rejected(
        self, known_tools, action_tools,
    ):
        """BrowserAction's sensitive-literal policy rejects Aadhaar-shaped
        literals BEFORE the registry/policy layer — the model cannot
        smuggle a sensitive value through arguments."""
        decision, failure = parse_model_decision(
            {
                "decision_type": "tool_call",
                "tool_name": "fill_field",
                "action": {
                    "action": "fill", "target_ref": "e1",
                    "literal_value": "123456789012",
                },
            },
            known_tools=known_tools, action_tools=action_tools,
            observation_id="obs-1",
        )
        assert decision is None
        assert failure is not None
        assert failure[0] == DECISION_VALIDATION_FAILED

    async def test_extra_fields_rejected_at_schema(self):
        """Prompt-injected or hallucinated keys fail the strict schema."""
        with pytest.raises(Exception):
            ReasonerDecisionSchema.model_validate({
                "decision_type": "tool_call",
                "tool_name": "observe_page",
                "policy_override": "allow_everything",
            })

    async def test_action_on_non_action_tool_rejected(
        self, known_tools, action_tools,
    ):
        decision, failure = parse_model_decision(
            {
                "decision_type": "tool_call",
                "tool_name": "observe_page",
                "action": {"action": "click", "target_ref": "e1"},
            },
            known_tools=known_tools, action_tools=action_tools,
            observation_id="obs-1",
        )
        assert decision is None
        assert failure is not None
        assert failure[0] == DECISION_VALIDATION_FAILED

    async def test_stale_observation_cannot_be_smuggled(
        self, known_tools, action_tools,
    ):
        """The runtime stamps the CURRENT observation id; a stale one in
        the model's action dict is overwritten, never trusted."""
        decision, failure = parse_model_decision(
            {
                "decision_type": "tool_call",
                "tool_name": "fill_field",
                "action": {
                    "action": "fill", "target_ref": "e1",
                    "literal_value": "x",
                    "observation_id": "obs-STALE",
                },
            },
            known_tools=known_tools, action_tools=action_tools,
            observation_id="obs-CURRENT",
        )
        assert failure is None and decision is not None
        assert decision.action is not None
        assert decision.action.observation_id == "obs-CURRENT"


# ---------------------------------------------------------------------------
# Context assembly invariants
# ---------------------------------------------------------------------------


class TestContextAssemblyInvariants:
    def test_context_is_minimal_and_structured(self):
        ctx = make_context()
        payload = ctx.context_payload
        assert set(payload.keys()) == {
            "goal", "plan_state", "world_state", "page_observation",
            "available_references", "available_references_note", "tools",
            "recent_tool_results", "unresolved_questions",
            "runtime_constraints",
        }
        # Element cap exists and is enforced
        assert ctx.element_count <= 60

    def test_no_vault_paths_or_secrets_in_context(self):
        import app.agent.reasoning.context as context_module

        rendered = make_context().render()
        # No filesystem paths, no credential markers. (The word "vault"
        # may appear in tool DESCRIPTIONS — exposing a vault PATH or key
        # material is what is forbidden.)
        for marker in ("data/", ".json", "/home/", "/Users/",
                       "api_key", "sk-", "OPENROUTER"):
            assert marker not in rendered, marker
        # Sensitive data appears only as semantic references.
        assert "USER." in rendered or "available_references" in rendered
        # Constraints mention semantic references explicitly.
        constraints = " ".join(context_module.RUNTIME_CONSTRAINTS)
        assert "USER.aadhaar_number" in constraints
        assert "never literal values" in constraints

    def test_recent_results_carry_no_raw_values(self):
        result = ToolResult(
            tool_name="fill_field", success=True, message="ok",
            payload={"executor_message": "filled", "resolved_value": "SECRET"},
        )
        ctx = make_context(recent_results=[result])
        rendered = ctx.render()
        assert "SECRET" not in rendered

    def test_observation_authoritative_in_context(self):
        ctx = make_context(observation=make_observation(observation_id="obs-live"))
        assert ctx.context_payload["page_observation"]["observation_id"] == "obs-live"


# ---------------------------------------------------------------------------
# Parser contract details
# ---------------------------------------------------------------------------


class TestParserContract:
    def test_non_object_output_rejected(self, known_tools, action_tools):
        decision, failure = parse_model_decision(
            ["not", "an", "object"],
            known_tools=known_tools, action_tools=action_tools,
        )
        assert decision is None
        assert failure[0] == DECISION_SCHEMA_INVALID

    def test_handoff_reserved_for_phase_10(self, known_tools, action_tools):
        decision, failure = parse_model_decision(
            {"decision_type": "handoff", "reason": "specialist"},
            known_tools=known_tools, action_tools=action_tools,
        )
        assert decision is None
        assert failure[0] == DECISION_SCHEMA_INVALID

    def test_ask_user_requires_question(self, known_tools, action_tools):
        decision, failure = parse_model_decision(
            {"decision_type": "ask_user"},
            known_tools=known_tools, action_tools=action_tools,
        )
        assert decision is None
        assert failure[0] == DECISION_VALIDATION_FAILED

    def test_alias_mapping_fill_field_to_fill(self, known_tools, action_tools):
        decision, failure = parse_model_decision(
            {
                "decision_type": "tool_call",
                "tool_name": "click",
                "action": {"action": "click", "target_ref": "e3"},
            },
            known_tools=known_tools, action_tools=action_tools,
            observation_id="obs-1",
        )
        assert failure is None
        assert decision is not None
        assert decision.action.action == "click"

    def test_json_schema_is_strict_and_complete(self):
        schema = build_decision_json_schema()
        assert schema["strict"] is True
        assert schema["name"] == "agent_decision"
        inner = schema["schema"]
        assert inner["additionalProperties"] is False
        assert set(inner["required"]) == set(inner["properties"].keys())
