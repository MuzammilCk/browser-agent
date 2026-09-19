"""Phase 3 exit criterion — synthetic multi-step form via typed tool calls.

"A synthetic agent can complete a multi-step form through typed tool calls."

The driver is a deterministic agent (NO LLM — Phase 4): it observes via
``observe_page``, decides which tool to call next from the observation,
invokes every action through ``ToolRegistry.execute`` with typed
ToolCalls, and follows the fresh post-action observations. All policy
and verification stay inside the existing BrowserExecutor path.

Invariants proven here:
- Every decision is a typed ToolCall carrying a typed BrowserAction.
- Every mutating action is schema-validated, ref-validated, executed via
  the executor (policy + verification intact), and followed by a fresh
  observation.
- The runtime-visible task state (WorkflowState records) is updated from
  ToolResults, not by tools themselves.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.agent.runtime.runtime import AgentRuntime
from app.agent.tools import (
    ToolCall,
    ToolContext,
    ToolRegistry,
    build_registry,
)
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.models.actions import BrowserAction
from app.models.workflow_state import ActionRecord, WorkflowState, WorkflowStatus

SYNTHETIC_PAGES_DIR = Path(__file__).parent / "pages"
BASE = SYNTHETIC_PAGES_DIR.as_uri()


# ---------------------------------------------------------------------------
# Deterministic tool-calling agent (Phase 4 will replace the decision rules
# with an LLM emitting AgentDecision objects — nothing else changes).
# ---------------------------------------------------------------------------


class MultiStepFormDriver:
    """Drives the multistep.html wizard through typed tool calls.

    Decision rules are deterministic (field names + page shape). Every
    action still goes: ToolCall → schema validation → registry → executor
    (policy → Playwright → verify) → ToolResult → fresh observation.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        ctx: ToolContext,
        workflow: WorkflowState,
        profile: dict[str, str],
    ) -> None:
        self.registry = registry
        self.ctx = ctx
        self.workflow = workflow
        self.profile = profile
        self.tool_calls: list[ToolCall] = []
        self.results: list = []

    async def _execute(self, call: ToolCall):
        self.tool_calls.append(call)
        result = await self.registry.execute(call, self.ctx)
        self.results.append(result)
        # Record in workflow state (runtime's job; tools never do this)
        self.workflow.record_action(ActionRecord(
            action_type=result.tool_name,
            target_ref=(call.action.target_ref if call.action else None),
            success=result.success,
            message=result.message,
            observation_id=result.observation_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        ))
        return result

    def _find(self, html_name: str):
        for el in self.ctx.page_state.elements:
            if el.html_name == html_name and el.visible:
                return el
        return None

    def _find_button(self, *keywords: str):
        for el in self.ctx.page_state.elements:
            if el.role == "button" and el.visible and el.accessible_name:
                if all(k in el.accessible_name.lower() for k in keywords):
                    return el
        return None

    async def observe(self):
        return await self._execute(ToolCall(tool_name="observe_page"))

    async def run(self) -> bool:
        """Drive all three wizard steps; True when the review page is
        reached with every required field filled."""
        # ---- Step 1: personal info ----
        await self.observe()
        await self._fill("name", self.profile["name"])
        await self._fill("dob", self.profile["dob"])
        await self._select("gender", self.profile["gender"])
        await self._click_button("next")

        # ---- Step 2: contact ----
        await self.observe()
        await self._fill("email", self.profile["email"])
        await self._fill("phone", self.profile["phone"])
        await self._click_button("next")

        # ---- Step 3: review ----
        await self.observe()
        submit = self._find_button("submit")
        return (
            submit is not None
            and all(r.success for r in self.results)
            and self.workflow.successful_actions >= 8
        )

    async def _fill(self, html_name: str, value: str) -> None:
        el = self._find(html_name)
        assert el is not None, f"field {html_name} not visible on current step"
        call = ToolCall(
            tool_name="fill_field",
            arguments={},
            action=BrowserAction(
                action="fill",
                target_ref=el.ref,
                literal_value=value,
                observation_id=self.ctx.observation.observation_id,
            ),
            reason=f"fill {html_name}",
        )
        result = await self._execute(call)
        assert result.success, f"fill {html_name} failed: {result.message}"

    async def _select(self, html_name: str, option: str) -> None:
        el = self._find(html_name)
        assert el is not None, f"select {html_name} not visible"
        call = ToolCall(
            tool_name="select_option",
            arguments={"option_note": f"choose {option}"},
            action=BrowserAction(
                action="select",
                target_ref=el.ref,
                option=option,
                observation_id=self.ctx.observation.observation_id,
            ),
        )
        result = await self._execute(call)
        assert result.success, f"select {html_name} failed: {result.message}"

    async def _click_button(self, *keywords: str) -> None:
        el = self._find_button(*keywords)
        assert el is not None, f"button {keywords} not visible"
        call = ToolCall(
            tool_name="click",
            arguments={},
            action=BrowserAction(
                action="click",
                target_ref=el.ref,
                observation_id=self.ctx.observation.observation_id,
            ),
        )
        result = await self._execute(call)
        assert result.success, f"click {keywords} failed: {result.message}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True)


@pytest.fixture
def registry() -> ToolRegistry:
    return build_registry()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMultiStepFormViaTypedToolCalls:
    @pytest.mark.asyncio
    async def test_completes_all_three_steps(self, settings, registry):
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/multistep.html")
            observation = await PageObserver().observe(page)

            workflow = WorkflowState(
                workflow_id="phase3-exit",
                task_description="Complete the application wizard",
                status=WorkflowStatus.RUNNING,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            ctx = ToolContext(
                observation=observation,
                page=page,
                executor=BrowserExecutor(),
                observer=PageObserver(),
                metadata={"browser_manager": manager},
            )
            driver = MultiStepFormDriver(
                registry, ctx, workflow,
                profile={
                    "name": "Rahul Sharma",
                    "dob": "1994-06-15",
                    "gender": "Male",
                    "email": "rahul@example.com",
                    "phone": "9876543210",
                },
            )

            completed = await driver.run()

            # ---- Exit criterion: the review/submit step was reached ----
            assert completed is True
            submit = driver._find_button("submit")
            assert submit is not None

            # ---- Every mutation was a typed, validated tool call ----
            tool_names = [c.tool_name for c in driver.tool_calls]
            assert tool_names.count("observe_page") == 3
            assert tool_names.count("fill_field") == 4  # name, dob, email, phone
            assert tool_names.count("select_option") == 1  # gender
            assert tool_names.count("click") == 2  # Next, Next

            # ---- All tool results succeeded; task state recorded ----
            assert all(r.success for r in driver.results)
            assert workflow.successful_actions == 10
            assert workflow.failed_actions == 0
            # WorkflowState progressed via ToolResults, not by tools
            assert workflow.total_actions == 10

    @pytest.mark.asyncio
    async def test_every_call_is_schema_validated_and_ref_bound(self, settings, registry):
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/multistep.html")
            ctx = ToolContext(
                observation=await PageObserver().observe(page),
                page=page,
                executor=BrowserExecutor(),
                observer=PageObserver(),
                metadata={"browser_manager": manager},
            )
            MultiStepFormDriver(registry, ctx, WorkflowState(
                workflow_id="t", created_at=datetime.now(timezone.utc).isoformat(),
            ), profile={})
            # invalid ref is rejected by the tool before any browser call
            bad = ToolCall(
                tool_name="fill_field",
                arguments={},
                action=BrowserAction(
                    action="fill", target_ref="e999", literal_value="x",
                    observation_id=ctx.observation.observation_id,
                ),
            )
            result = await registry.execute(bad, ctx)
            assert result.success is False
            assert result.error_code == "STALE_OR_INVALID_TARGET"

    @pytest.mark.asyncio
    async def test_stale_observation_id_is_rejected(self, settings, registry):
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/multistep.html")
            ctx = ToolContext(
                observation=await PageObserver().observe(page),
                page=page,
                executor=BrowserExecutor(),
                observer=PageObserver(),
                metadata={"browser_manager": manager},
            )
            el = ctx.page_state.elements[0]
            stale = ToolCall(
                tool_name="fill_field",
                arguments={},
                action=BrowserAction(
                    action="fill", target_ref=el.ref, literal_value="x",
                    observation_id="obs-from-the-past",
                ),
            )
            result = await registry.execute(stale, ctx)
            assert result.error_code == "STALE_OR_INVALID_TARGET"


class TestDriverTracksRuntime:
    @pytest.mark.asyncio
    async def test_runtime_lifecycle_follows_tool_progress(self, settings, registry):
        """The AgentRuntime (Phase 2) stays authoritative: the driver only
        feeds it observations of progress; lifecycle transitions flow
        through the runtime's validated path."""
        from app.agent.runtime.state import AgentLifecycle
        from app.models.workflow_state import WorkflowStatus

        rt = AgentRuntime()
        session = rt.create_session()
        run = rt.create_run(session=session, goal="Complete the wizard")

        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{BASE}/multistep.html")
            observation = await PageObserver().observe(page)
            run.world_state.status = WorkflowStatus.RUNNING
            rt.sync_lifecycle_from_workflow(run)

            ctx = ToolContext(
                observation=observation,
                page=page,
                executor=BrowserExecutor(),
                observer=PageObserver(),
                metadata={"browser_manager": manager},
            )
            driver = MultiStepFormDriver(registry, ctx, run.world_state, profile={
                "name": "Rahul Sharma", "dob": "1994-06-15", "gender": "Male",
                "email": "rahul@example.com", "phone": "9876543210",
            })
            completed = await driver.run()

            assert completed is True
            # Run state advanced through the runtime's own bridge
            assert run.world_state.total_actions == 10
            assert run.usage.actions_executed == 0  # tools never mutate runtime state
            rt.sync_lifecycle_from_workflow(run)
            # still a working lifecycle (not stuck mid-step)
            assert run.lifecycle in (
                AgentLifecycle.REASONING, AgentLifecycle.READY_FOR_REVIEW,
                AgentLifecycle.READY_FOR_CONFIRMATION,
            )
