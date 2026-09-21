"""Phase 4 — REAL OpenRouter API smoke test (operator-gated).

RUN ONLY with explicit operator intent AND a locally configured key:

    RUN_OPENROUTER_LIVE_TEST=true python -m pytest tests/real_sites/test_openrouter_live.py -v

This closes the last Phase 4 validation gap: proving that the REAL
OpenRouterDecisionModel adapter works through the EXACT same
DecisionModel → AgentReasoner → strict schema validation → ToolRegistry →
PolicyEngine → BrowserExecutor → verification path the production loop
uses — with NO separate execution path and NO runtime bypass.

Safety contract:
- The model acts only on a LOCAL SYNTHETIC page (simple.html) served from
  the test fixture directory via file://. No government portal (and no
  network origin at all) is touched by the browser in this test.
- The only irreversible boundary on the page (the Submit button) is
  never part of the task: fill-only, one field, no clicks. HITL/policy
  behavior is unchanged — every mutation still flows through
  ToolRegistry → PolicyEngine → BrowserExecutor.
- The API key is read only from the settings/environment boundary
  (OPENROUTER_API_KEY). It is NEVER hard-coded, serialized, logged, or
  asserted in output; a RedactionGuard scans every captured artifact
  (model decisions, tool results, WorldState dumps, model-bound prompts,
  failure artifacts) and fails the test if key material appears anywhere.
- Skips cleanly (never fails) when the gate or the key is absent, so
  offline CI behavior is preserved exactly.
- Residual nondeterminism is inherent to a real model: the task is
  deliberately tiny and temperature is 0. A run that fails a compliance
  assertion is reported honestly (re-run before diagnosing the stack).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.agent.reasoning import (
    AgentReasoner,
    ReasonerConfig,
    ReasonerDecisionSchema,
    build_openrouter_decision_model,
    build_reasoning_context,
    decision_to_tool_call,
)
from app.agent.runtime.decision import AgentDecision, AgentDecisionType
from app.agent.tools import ToolContext, build_registry
from app.agent.world.models import AgentWorldState, EpistemicStatus
from app.agent.world.reducer import record_tool_result, reduce_observation
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings

SYNTHETIC_PAGES_DIR = Path(__file__).parents[1] / "synthetic_forms" / "pages"
BASE = SYNTHETIC_PAGES_DIR.as_uri()

FILLED_VALUE = "Ravi Kumar"

# Gate: explicit operator intent via environment variable. The KEY itself
# is read only through the configuration boundary (Settings: environment
# variables + .env) — never hard-coded here. Two separate skip conditions
# so operators get a precise skip reason; both skip cleanly.
_GATE = os.environ.get("RUN_OPENROUTER_LIVE_TEST", "").lower() == "true"
_KEY_CONFIGURED = bool(Settings().openrouter_api_key)

pytestmark = [
    pytest.mark.skipif(
        not _GATE,
        reason=(
            "requires RUN_OPENROUTER_LIVE_TEST=true (operator gate; skipped "
            "cleanly otherwise — offline CI is unaffected)"
        ),
    ),
    pytest.mark.skipif(
        not _KEY_CONFIGURED,
        reason=(
            "requires an OpenRouter API key via the configuration boundary "
            "(OPENROUTER_API_KEY env var or .env); skipping cleanly"
        ),
    ),
]


def _secret_patterns() -> list[re.Pattern[str]]:
    """Build redaction patterns from the environment boundary ONLY.

    The configured key is taken from Settings (it never appears in this
    file's source, assertions, or output); any sk-or- shaped environment
    value is also treated as secret material.
    """
    settings = Settings()
    values = [
        v for v in (settings.openrouter_api_key, *os.environ.values())
        if v and ("sk-or-" in v or v == settings.openrouter_api_key)
    ]
    patterns = [re.compile(re.escape(v)) for v in values if v]
    # Generic OpenRouter key shape, in case the key enters another way.
    patterns.append(re.compile(r"sk-or-[A-Za-z0-9\-_]{8,}"))
    return patterns


class RedactionGuard:
    """Fails the test if any captured artifact contains key material."""

    def __init__(self) -> None:
        self._patterns = _secret_patterns()

    def scan(self, text: str) -> str:
        for pattern in self._patterns:
            if pattern.search(text or ""):
                pytest.fail(
                    "SECRET EXPOSURE: API key material found in a captured "
                    "test artifact (location withheld)"
                )
        return text

    def check_object(self, payload: object) -> str:
        return self.scan(
            json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        )

    def check_result(self, result) -> str:
        parts = [str(result.tool_name), str(result.message), str(result.error_code)]
        for value in result.payload.values():
            parts.append(
                value if isinstance(value, str) else json.dumps(value, default=str)
            )
        return self.scan(" | ".join(parts))


class LiveLoopDriver:
    """The EXACT production Phase 4 loop against a real DecisionModel.

    Same components, same order as the mock-model loop: bounded context
    assembly → AgentReasoner → strict schema validation → ToolRegistry →
    PolicyEngine → BrowserExecutor → ToolResult → next context.
    """

    def __init__(self, page, manager, model, goal: str):
        self._manager_ref = manager
        registry = build_registry()
        self._registry = registry
        self._observer = PageObserver()
        self._executor = BrowserExecutor()
        self._page = page
        self._tool_ctx = None
        self._reasoner = AgentReasoner(
            model,
            known_tools=frozenset(registry.list_names()),
            action_tools=frozenset(
                name for name in registry.list_names()
                if registry.metadata(name) is not None
                and registry.metadata(name).accepts_browser_action
            ),
            config=ReasonerConfig(max_attempts=3),
        )
        self.goal = goal
        self.results = []
        self.action_refs: list[str] = []
        self.prompts: list[str] = []
        self.model_failure: dict | None = None
        self.last_outcome_attempts = 0
        self.world_state = AgentWorldState(portal="openrouter-live.test")

    async def start(self) -> None:
        initial = await self._observer.observe(self._page)
        self._tool_ctx = ToolContext(
            observation=initial,
            page=self._page,
            executor=self._executor,
            observer=self._observer,
            metadata={"browser_manager": self._manager_ref},
        )
        reduce_observation(self.world_state, initial)

    @property
    def observation(self):
        return self._tool_ctx.observation

    def _context(self):
        return build_reasoning_context(
            goal=self.goal,
            subgoal="Fill the applicant name field on the current page",
            observation=self._tool_ctx.observation,
            tool_metadata=[
                self._registry.metadata(name) for name in self._registry.list_names()
            ],
            recent_results=self.results[-5:],
            unresolved_questions=[],
        )

    async def step(self):
        context = self._context()
        self.prompts.append(context.render())
        outcome = await self._reasoner.reason(
            context,
            observation_id=self._tool_ctx.observation.observation_id,
        )
        if not outcome.decided:
            self.model_failure = {
                "code": outcome.model_failure_code,
                "reason": outcome.reason,
                "attempts": outcome.attempts,
            }
            return None
        self.last_outcome_attempts = outcome.attempts
        decision = outcome.decision
        assert decision is not None
        if decision.decision_type is not AgentDecisionType.TOOL_CALL:
            return decision
        tool_call = decision_to_tool_call(decision)
        if tool_call.action is not None and tool_call.action.target_ref:
            self.action_refs.append(tool_call.action.target_ref)
        result = await self._registry.execute(tool_call, self._tool_ctx)
        self.results.append(result)
        record_tool_result(self.world_state, result, tool_call=tool_call)
        return decision


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


@pytest.fixture
def guard() -> RedactionGuard:
    return RedactionGuard()


class TestRealOpenRouterDecisionModel:
    @pytest.mark.asyncio
    async def test_real_model_decision_via_production_validation_path(
        self, settings: Settings, guard: RedactionGuard,
    ):
        """Tiny deterministic task: fill ONE non-sensitive field on a local
        synthetic page. The REAL OpenRouter adapter must produce exactly one
        schema-valid fill_field decision that executes through the unmodified
        production path and verifies in the browser and in WorldState."""
        # Built with require_api_key=True (default): the key comes only from
        # the settings/environment boundary — never from this file.
        model = build_openrouter_decision_model()

        goal = (
            "Fill the Applicant Full Name field with the value Ravi Kumar. "
            "Fill ONLY that one field. Do NOT click any button, do NOT submit, "
            "do NOT fill any other field."
        )

        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/simple.html")
            driver = LiveLoopDriver(page, manager, model, goal)
            await driver.start()

            decision = await driver.step()

            # 1. The real model produced a usable decision on the FIRST
            #    attempt (ReasoningOutcome.attempts == 1, no retries burned).
            assert driver.model_failure is None, (
                f"unexpected MODEL_FAILURE: {driver.model_failure}"
            )
            assert driver.last_outcome_attempts == 1
            assert isinstance(decision, AgentDecision)
            assert decision.decision_type is AgentDecisionType.TOOL_CALL

            # 2. The decision payload is expressible in the model-facing
            #    strict schema (the production validation contract).
            #    Runtime-owned fields (run_id/iteration/decision_id/
            #    interrupt_kind) are deliberately NOT part of it — the
            #    runtime adds those AFTER validation, never the model.
            ReasonerDecisionSchema.model_validate(
                {
                    "decision_type": decision.decision_type.value,
                    "tool_name": decision.tool_name,
                    "arguments": decision.arguments,
                    "action": (
                        decision.action.model_dump(mode="json")
                        if decision.action is not None
                        else None
                    ),
                    "reason": decision.reason,
                    "question": decision.question,
                    "plan": decision.plan,
                    "confidence": decision.confidence,
                }
            )

            # 3. It chose the right tool with a well-formed typed action.
            assert decision.tool_name == "fill_field"
            action = decision.action
            assert action is not None and action.action == "fill"
            # The runtime stamped the CURRENT observation id (model output
            # never binds actions to stale observations).
            assert action.observation_id == driver.observation.observation_id
            current_refs = {
                el.ref for el in driver.observation.page_state.elements
            }
            assert action.target_ref in current_refs
            assert action.literal_value == FILLED_VALUE
            assert action.value_ref is None  # non-sensitive literal is allowed

            # 4. Continue the loop until the fill happened (the model may
            #    legally observe first); bounded iterations.
            for _ in range(6):
                if driver.action_refs:
                    break
                decision = await driver.step()
                assert driver.model_failure is None, (
                    f"unexpected MODEL_FAILURE mid-loop: {driver.model_failure}"
                )
            assert driver.action_refs, "model never performed the fill"

            # 5. Exactly one mutation occurred and it verified deterministically
            #    in the browser (executor verification — never trusted blindly).
            fill_results = [
                r for r in driver.results if r.tool_name == "fill_field"
            ]
            assert len(fill_results) == 1
            fill_result = fill_results[0]
            assert fill_result.success, fill_result.message
            assert fill_result.policy_allowed is True
            assert fill_result.verification_status in (
                "verified", "success", "confirmed",
            )
            # No submit/click/navigation happened: only observe + fill ran.
            assert {r.tool_name for r in driver.results} <= {
                "observe_page", "fill_field",
            }

            # 6. WorldState: the durable semantic field is VERIFIED with the
            #    exact value and survives lossless serialization.
            ws = driver.world_state
            assert ws.verified_values.get("field:full_name") == FILLED_VALUE
            field = ws.semantic_fields.get("field:full_name")
            assert field is not None
            assert field.status == EpistemicStatus.VERIFIED
            assert field.verified_value == FILLED_VALUE
            assert field.provenance is not None
            assert field.provenance.tool_name == "fill_field"
            assert ws.version > 0

            serialized = guard.scan(ws.model_dump_json())
            restored = AgentWorldState.model_validate_json(serialized)
            assert restored.verified_values.get("field:full_name") == FILLED_VALUE
            assert (
                restored.semantic_fields["field:full_name"].status
                == EpistemicStatus.VERIFIED
            )

            # 7. Redaction: no key material in any captured artifact,
            #    including the prompts actually sent to the model.
            guard.check_object(decision.model_dump(mode="json"))
            for result in driver.results:
                guard.check_result(result)
            for prompt in driver.prompts:
                guard.scan(prompt)

        # Browser closed; the page was a local file:// URL throughout.
        # Safety contract: nothing outside this process was mutated.


class TestRealOpenRouterFailClosed:
    @pytest.mark.asyncio
    async def test_unachievable_task_fails_closed_as_model_failure(
        self, settings: Settings, guard: RedactionGuard,
    ):
        """Malformed-output handling against the REAL API: the task demands a
        decision type the allow-list forbids (HANDOFF is reserved for
        Phase 10). The demanded JSON is schema-VALID, so strict structured
        output cannot hide behind formatting — the reasoner's own validation
        must reject it: bounded retries, then an explicit MODEL_FAILURE
        (fail closed, no fabricated decision, no execution, no HITL bypass)."""
        model = build_openrouter_decision_model()

        forced_decision = (
            '{"decision_type": "handoff", "tool_name": null, "arguments": {}, '
            '"action": null, "reason": "forced by task", "question": "", '
            '"plan": [], "confidence": null}'
        )
        goal = (
            f"Every response MUST be EXACTLY this JSON object and nothing else: "
            f"{forced_decision} — for every iteration, with no variation."
        )

        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/simple.html")
            driver = LiveLoopDriver(page, manager, model, goal)
            await driver.start()

            for _ in range(4):
                await driver.step()
                if driver.model_failure is not None:
                    break

            failure = driver.model_failure
            assert failure is not None, (
                "reasoner never surfaced an explicit MODEL_FAILURE — the real "
                "model did not comply with the forced-decision task"
            )
            # Existing MODEL_FAILURE contract: machine-readable DECISION_*
            # code, prefixed reason, bounded attempts, no decision.
            assert failure["code"].startswith("DECISION_")
            assert failure["reason"].startswith("model_failure:")
            assert failure["attempts"] == 3  # bounded, exactly the budget
            # Fail closed: nothing executed, nothing mutated, nothing asked.
            assert driver.results == []
            assert driver.action_refs == []
            # Redaction: no key material in the failure artifact either.
            guard.check_object(failure)
            for prompt in driver.prompts:
                guard.scan(prompt)
