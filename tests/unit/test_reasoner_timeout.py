"""Phase 15 H2 regression tests — bounded wall-clock timeout on model calls.

Before H2, ReasonerConfig bounded *attempts* but not *time*: a hung
OpenRouter call blocked the loop indefinitely (past worker leases, with no
checkpoint). The reasoner must treat a hung call as a failed attempt and,
after the attempt budget, produce the standard explicit MODEL_FAILURE.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.reasoning import (
    DECISION_PARSE_FAILED,
    MODEL_FAILURE_REASON_PREFIX,
    AgentReasoner,
    MockDecisionModel,
    ReasonerConfig,
    ReasoningPhase,
    build_reasoning_context,
)
from app.agent.tools import build_registry
from app.models.page_state import PageObservation, PageState


def make_observation(observation_id: str = "obs-1") -> PageObservation:
    ps = PageState(
        url="https://uidai.gov.in/form",
        title="Application",
        page_id=observation_id,
        page_type="form",
        elements=[],
    )
    return PageObservation(page_state=ps, observation_id=observation_id)


def make_context() -> Any:
    return build_reasoning_context(
        goal="Fill the application form",
        subgoal="personal details",
        observation=make_observation(),
        tool_metadata=[],
        recent_results=[],
        unresolved_questions=[],
    )


class HangingModel:
    """A DecisionModel whose decide() never returns."""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, *, system: str, context: str) -> dict[str, Any]:
        self.calls += 1
        await asyncio.sleep(3600)


class SlowThenOkModel:
    """First call hangs, subsequent calls answer (would deadlock pre-H2)."""

    def __init__(self) -> None:
        self.calls = 0

    async def decide(self, *, system: str, context: str) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            await asyncio.sleep(3600)
        return {"decision_type": "tool_call", "tool_name": "observe_page"}


@pytest.fixture
def known_tools() -> set[str]:
    return set(build_registry().list_names())


@pytest.fixture
def action_tools() -> set[str]:
    registry = build_registry()
    return {
        name for name in registry.list_names()
        if registry.metadata(name) is not None
        and registry.metadata(name).accepts_browser_action
    }


class TestDecisionTimeout:
    async def test_hung_model_call_is_bounded(
        self, known_tools, action_tools,
    ):
        """A hanging model call must return within the configured timeout,
        not block forever."""
        model = HangingModel()
        reasoner = AgentReasoner(
            model, known_tools=known_tools, action_tools=action_tools,
            config=ReasonerConfig(max_attempts=2, decision_timeout_seconds=0.05),
        )
        outcome = await reasoner.reason(make_context())
        assert outcome.decided is False
        assert outcome.phase == ReasoningPhase.MODEL_FAILURE
        assert outcome.model_failure_code == DECISION_PARSE_FAILED
        assert "timed out" in outcome.reason
        assert outcome.reason.startswith(MODEL_FAILURE_REASON_PREFIX)
        assert model.calls == 2

    async def test_timeout_consumes_attempt_then_repairs(
        self, known_tools, action_tools,
    ):
        """A single hung call consumes exactly one attempt; the next
        attempt can still succeed — bounded, not fatal on first timeout."""
        model = SlowThenOkModel()
        reasoner = AgentReasoner(
            model, known_tools=known_tools, action_tools=action_tools,
            config=ReasonerConfig(max_attempts=3, decision_timeout_seconds=0.05),
        )
        outcome = await reasoner.reason(make_context())
        assert outcome.decided is True
        assert outcome.decision is not None
        assert outcome.decision.tool_name == "observe_page"
        assert outcome.attempts == 2
        assert model.calls == 2

    async def test_timeout_failure_carries_bounded_attempt_count(
        self, known_tools, action_tools,
    ):
        model = HangingModel()
        reasoner = AgentReasoner(
            model, known_tools=known_tools, action_tools=action_tools,
            config=ReasonerConfig(max_attempts=3, decision_timeout_seconds=0.05),
        )
        outcome = await reasoner.reason(make_context())
        assert outcome.attempts == 3
        assert model.calls == 3

    async def test_reasoner_never_blocks_longer_than_budget(
        self, known_tools, action_tools,
    ):
        """Wall-clock guarantee: max_attempts x timeout + slack."""
        model = HangingModel()
        reasoner = AgentReasoner(
            model, known_tools=known_tools, action_tools=action_tools,
            config=ReasonerConfig(max_attempts=2, decision_timeout_seconds=0.05),
        )
        loop = asyncio.get_running_loop()
        start = loop.time()
        await reasoner.reason(make_context())
        elapsed = loop.time() - start
        # 2 attempts x 0.05s = 0.1s; generous slack for scheduling.
        assert elapsed < 2.0

    def test_config_rejects_nonpositive_timeout(self):
        with pytest.raises(Exception):
            ReasonerConfig(max_attempts=2, decision_timeout_seconds=0)

    def test_default_timeout_is_configured(self):
        config = ReasonerConfig()
        assert config.decision_timeout_seconds == 60.0
