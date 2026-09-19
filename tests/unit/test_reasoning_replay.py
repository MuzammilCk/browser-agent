"""Phase 4 replay tests — recorded inputs reproduce identical decisions/results.

Replay contract (user instruction, Phase 4): "replay produces the same
decisions/results from recorded inputs". These tests run the full Phase 4
loop — context assembly → AgentReasoner → AgentDecision → ToolRegistry →
ToolResult → next context — twice against the same recorded model script
and the same deterministic environment, then assert equality of the
recorded artifacts:

- identical rendered prompts (context determinism),
- identical decision sequence,
- identical ToolResult summaries (excluding opaque observation ids and
  timestamps, which are freshly generated per episode by design).

A mock executor stubs the browser boundary; the ToolRegistry, tool
adapters, normalization and error-code taxonomy are the REAL Phase 3
code, so replay equality covers the actual decision→result pipeline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agent.reasoning import (
    AgentReasoner,
    MockDecisionModel,
    ReasonerConfig,
    build_reasoning_context,
)
from app.agent.tools import (
    ToolCall,
    ToolContext,
    ToolRegistry,
    build_registry,
)
from app.agent.tools.base import ToolResult
from app.browser.executor import ActionResult
from app.browser.verifiers.base import VerificationResult, VerificationStatus
from app.models.actions import BrowserAction
from app.models.page_state import (
    ElementState,
    PageObservation,
    PageState,
)

# ---------------------------------------------------------------------------
# Deterministic environment (same for both replay episodes)
# ---------------------------------------------------------------------------


def build_observation(
    *, observation_id: str, page_type: str = "form",
) -> PageObservation:
    ps = PageState(
        url="https://uidai.gov.in/form",
        title="Application",
        page_id=observation_id,
        page_type=page_type,  # type: ignore[arg-type]
        elements=[
            ElementState(ref="e1", role="textbox", accessible_name="Full Name",
                         input_type="text", required=True),
            ElementState(ref="e2", role="combobox", accessible_name="State"),
            ElementState(ref="e3", role="button", accessible_name="Next"),
        ],
    )
    return PageObservation(page_state=ps, observation_id=observation_id)


@dataclass
class RecordingExecutor:
    """Deterministic executor stub: success for the canned observation."""
    observation_id: str = "obs-1"
    calls: list = field(default_factory=list)

    async def execute(self, page, action, observation, *, user_confirmed=False):
        self.calls.append((action.action, action.target_ref))
        return ActionResult(
            action=action,
            success=True,
            message=f"{action.action} ok",
            verification=VerificationResult(
                status=VerificationStatus.SUCCESS, action_type=action.action,
            ),
            post_observation=build_observation(observation_id=self.observation_id),
        )


def make_ctx(executor: RecordingExecutor, observation: PageObservation) -> ToolContext:
    return ToolContext(
        observation=observation,
        page=object(),
        executor=executor,  # type: ignore[arg-type]
        observer=None,
    )


def result_fingerprint(result: ToolResult) -> dict[str, Any]:
    """Comparable ToolResult projection (drops fresh ids/timestamps)."""
    return {
        "tool_name": result.tool_name,
        "success": result.success,
        "error_code": result.error_code,
        "message": result.message,
        "policy_allowed": result.policy_allowed,
        "verification_status": result.verification_status,
        "payload": result.payload,
    }


@dataclass
class Episode:
    """One recorded run of the full loop."""
    prompts: list[str]
    decisions: list[dict]
    results: list[dict]
    executor_calls: list


async def run_episode(script: list[dict], observation_ids: list[str]) -> Episode:
    """Execute the full loop once with the given recorded model script.

    Identical inputs → identical outputs: the context assembler is
    deterministic (sorted-key JSON), the model script is scripted, the
    registry is deterministic, and the executor stub is deterministic.
    """
    registry: ToolRegistry = build_registry()
    known_tools = frozenset(registry.list_names())
    action_tools = frozenset(
        name for name in registry.list_names()
        if registry.metadata(name).accepts_browser_action  # type: ignore[union-attr]
    )
    executor = RecordingExecutor()
    model = MockDecisionModel(list(script))
    reasoner = AgentReasoner(
        model, known_tools=known_tools, action_tools=action_tools,
        config=ReasonerConfig(max_attempts=3),
    )

    observation = build_observation(observation_id=observation_ids[0])
    ctx = make_ctx(executor, observation)
    prompts: list[str] = []
    decisions: list[dict] = []
    results: list[dict] = []
    raw_results: list[ToolResult] = []

    for observation_id in observation_ids:
        context = build_reasoning_context(
            goal="Fill the application form",
            subgoal="personal details",
            observation=ctx.observation,
            tool_metadata=[
                registry.metadata(name)  # type: ignore[misc]
                for name in registry.list_names()
            ],
            recent_results=raw_results[-5:],
            unresolved_questions=[],
        )
        prompts.append(context.render())

        outcome = await reasoner.reason(context, observation_id=observation_id)
        assert outcome.decided is True, outcome.reason
        decision = outcome.decision
        assert decision is not None

        # Execute through the REAL registry (Phase 3 gate).
        call = ToolCall(
            tool_name=decision.tool_name or "",
            arguments=dict(decision.arguments or {}),
            action=decision.action,
            reason=decision.reason,
        )
        result = await registry.execute(call, ctx)
        results.append(result_fingerprint(result))
        raw_results.append(result)

        # Mutating tools advanced the context observation (post_observation)
        # — exactly what the runtime does between iterations.
        if result.post_observation is not None:
            ctx.observation = result.post_observation

        decisions.append(decision.model_dump(mode="json"))

    return Episode(
        prompts=prompts, decisions=decisions,
        results=results, executor_calls=executor.calls,
    )


SCRIPT: list[dict] = [
    {"decision_type": "tool_call", "tool_name": "observe_page"},
    {
        "decision_type": "tool_call", "tool_name": "fill_field",
        "action": {"action": "fill", "target_ref": "e1",
                   "literal_value": "Rahul Sharma"},
    },
    {
        "decision_type": "tool_call", "tool_name": "select_option",
        "action": {"action": "select", "target_ref": "e2", "option": "Kerala"},
    },
    {"decision_type": "tool_call", "tool_name": "click",
     "action": {"action": "click", "target_ref": "e3"}},
]
OBS_IDS = ["obs-1", "obs-2", "obs-3", "obs-4"]


# ---------------------------------------------------------------------------
# Replay equality
# ---------------------------------------------------------------------------


class TestReplayProducesIdenticalOutcomes:
    async def test_full_loop_replay_matches(self):
        first = await run_episode(SCRIPT, OBS_IDS)
        second = await run_episode(SCRIPT, OBS_IDS)

        assert first.decisions == second.decisions
        assert first.results == second.results
        assert first.executor_calls == second.executor_calls

    async def test_prompts_are_identical_across_replays(self):
        first = await run_episode(SCRIPT, OBS_IDS)
        second = await run_episode(SCRIPT, OBS_IDS)
        assert first.prompts == second.prompts
        # And they parse as JSON with the expected minimal structure.
        for prompt in first.prompts:
            payload = json.loads(prompt)
            assert "goal" in payload and "page_observation" in payload

    async def test_three_replays_still_match(self):
        baseline = await run_episode(SCRIPT, OBS_IDS)
        for _ in range(2):
            again = await run_episode(SCRIPT, OBS_IDS)
            assert again.decisions == baseline.decisions
            assert again.results == baseline.results


class TestReplayRecordsFailureEpisodes:
    async def test_failure_episode_replays_identically(self):
        """A recorded episode containing a tool failure (stale target)
        must replay to the same failure + same recovery decisions."""
        failure_script: list[dict] = [
            {"decision_type": "tool_call", "tool_name": "observe_page"},
            # fill against e1 while context holds obs-2 → stale-ref failure
            {
                "decision_type": "tool_call", "tool_name": "fill_field",
                "action": {"action": "fill", "target_ref": "e1",
                           "literal_value": "x"},
            },
            # recovery: observe again
            {"decision_type": "tool_call", "tool_name": "observe_page"},
        ]
        first = await run_episode(failure_script, ["obs-1", "obs-2", "obs-3"])
        second = await run_episode(failure_script, ["obs-1", "obs-2", "obs-3"])

        assert first.results == second.results
        stale = first.results[1]
        assert stale["success"] is False
        assert stale["error_code"] == "STALE_OR_INVALID_TARGET"
        # Recovery decision identical across replays
        assert first.decisions[2] == second.decisions[2]
        assert first.decisions[2]["tool_name"] == "observe_page"


class TestReplayIntegrity:
    async def test_different_script_produces_different_recording(self):
        """Sanity: replay equality is meaningful — a changed script
        changes the recording."""
        altered = [dict(step) for step in SCRIPT]
        altered[1] = {
            "decision_type": "tool_call", "tool_name": "fill_field",
            "action": {"action": "fill", "target_ref": "e1",
                       "literal_value": "Different Name"},
        }
        baseline = await run_episode(SCRIPT, OBS_IDS)
        changed = await run_episode(altered, OBS_IDS)
        assert baseline.decisions != changed.decisions

    async def test_decisions_are_json_serializable_records(self):
        episode = await run_episode(SCRIPT, OBS_IDS)
        for record in episode.decisions:
            # Round-trips through JSON: the replay log is durable.
            assert json.loads(json.dumps(record)) == record
