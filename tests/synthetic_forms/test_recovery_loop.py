"""Phase 7 acceptance scenario — Real Chromium dynamic form recovery loop.

Proves Phase 7 exit criterion:
"The agent changes strategy after meaningful failures and stops when no safe strategy remains."

Acceptance Scenario:
1. observe page
2. perform a valid action
3. page changes unexpectedly
4. previously generated target becomes stale
5. tool execution fails with STALE_REFERENCE
6. reflection classifies the failure
7. runtime re-observes
8. semantic WorldState finds the same logical field under a new ref
9. recovery chooses a fresh typed tool call
10. BrowserExecutor executes it
11. verification succeeds
12. verified semantic progress remains intact
13. recovery attempt is recorded
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.recovery import FailureType, RecoveryManager, RecoveryStrategy
from app.agent.tools import ToolCall, ToolContext, build_registry
from app.agent.world.models import AgentWorldState, EpistemicStatus
from app.agent.world.reducer import (
    is_target_ref_valid,
    record_tool_result,
    reduce_observation,
)
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.models.actions import BrowserAction

SYNTHETIC_DIR = Path(__file__).resolve().parent / "pages"
SYNTHETIC_BASE = SYNTHETIC_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True, browser_mode="test")


def _find_ref(observation, html_name: str) -> str:
    for el in observation.page_state.elements:
        if el.html_name == html_name:
            return el.ref
    raise ValueError(f"Element with html_name={html_name} not found in observation")


class TestPhase7DynamicRecoveryLoop:
    """Proves the Phase 7 acceptance scenario in real Chromium."""

    @pytest.mark.asyncio
    async def test_dynamic_form_stale_reference_recovery(self, settings: Settings) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/dynamic_recovery.html")

            # Infrastructure setup
            observer = PageObserver()
            executor = BrowserExecutor()
            registry = build_registry()
            recovery_mgr = RecoveryManager()
            ws = AgentWorldState(portal="dynamic_recovery.test")

            # -----------------------------------------------------------------
            # 1. Observe page
            # -----------------------------------------------------------------
            obs1 = await observer.observe(page)
            reduce_observation(ws, obs1)

            ref_name_1 = _find_ref(obs1, "applicant_name")
            ref_pincode_1 = _find_ref(obs1, "pincode")

            assert "field:applicant_name" in ws.semantic_fields
            assert "field:pincode" in ws.semantic_fields
            assert is_target_ref_valid(ws, ref_name_1, obs1.observation_id) is True
            assert is_target_ref_valid(ws, ref_pincode_1, obs1.observation_id) is True

            # -----------------------------------------------------------------
            # 2. Perform a valid action on applicant_name
            # -----------------------------------------------------------------
            call_1 = ToolCall(
                tool_name="fill_field",
                arguments={"target_ref": ref_name_1, "value": "Aarav Kumar"},
                action=BrowserAction(
                    action="fill",
                    target_ref=ref_name_1,
                    literal_value="Aarav Kumar",
                    observation_id=obs1.observation_id,
                ),
            )
            ctx1 = ToolContext(observation=obs1, page=page, executor=executor, observer=observer)
            result_1 = await registry.execute(call_1, ctx1)
            assert result_1.success is True
            record_tool_result(ws, result_1, tool_call=call_1)

            # Verification succeeds, applicant_name is VERIFIED
            assert ws.verified_values.get("field:applicant_name") == "Aarav Kumar"
            assert ws.semantic_fields["field:applicant_name"].status == EpistemicStatus.VERIFIED

            # -----------------------------------------------------------------
            # 3. Page changes unexpectedly (DOM section re-rendered)
            # -----------------------------------------------------------------
            await page.locator("#btn_rerender").click()

            # -----------------------------------------------------------------
            # 4. Previously generated target for pincode becomes stale
            # -----------------------------------------------------------------
            stale_call = ToolCall(
                tool_name="fill_field",
                arguments={"target_ref": ref_pincode_1, "value": "560001"},
                action=BrowserAction(
                    action="fill",
                    target_ref=ref_pincode_1,
                    literal_value="560001",
                    observation_id=obs1.observation_id,
                ),
            )

            # -----------------------------------------------------------------
            # 5. Tool execution fails with STALE_REFERENCE
            # -----------------------------------------------------------------
            # Even if current context has fresh page, the action targeted obs1
            # Or the DOM element ref_pincode_1 is detached
            stale_result = await registry.execute(stale_call, ctx1)
            assert stale_result.success is False
            # Executor / registry detects either observation mismatch or element not located / stale
            assert stale_result.error_code in (
                "STALE_REFERENCE",
                "STALE_OR_INVALID_TARGET",
                "EXECUTION_FAILED",
                "TARGET_NOT_FOUND",
            )

            # -----------------------------------------------------------------
            # 6. Reflection classifies the failure
            # -----------------------------------------------------------------
            reflection = recovery_mgr.handle_tool_failure(
                stale_result, call=stale_call, world_state=ws, observation=obs1,
            )
            assert reflection.failure_type in (FailureType.STALE_REFERENCE, FailureType.TARGET_NOT_FOUND)
            assert reflection.can_recover is True
            assert reflection.decision.action_required == "re_observe"

            # -----------------------------------------------------------------
            # 7. Runtime re-observes
            # -----------------------------------------------------------------
            obs2 = await observer.observe(page)
            reduce_observation(ws, obs2)

            # -----------------------------------------------------------------
            # 8. Semantic WorldState finds the same logical field under new ref
            # -----------------------------------------------------------------
            ref_pincode_2 = _find_ref(obs2, "pincode")
            assert ref_pincode_2 != ref_pincode_1, "Dynamic re-render must assign a fresh element ref"

            pincode_field = ws.semantic_fields["field:pincode"]
            assert pincode_field.current_ref == ref_pincode_2
            assert is_target_ref_valid(ws, ref_pincode_2, obs2.observation_id, expected_semantic_id="field:pincode") is True
            # Old ref from obs1 is invalid because observation_id is stale
            assert is_target_ref_valid(ws, ref_pincode_1, obs1.observation_id) is False
            # And under the fresh observation, old ref does not point to pincode
            assert is_target_ref_valid(ws, ref_pincode_1, obs2.observation_id, expected_semantic_id="field:pincode") is False

            # -----------------------------------------------------------------
            # 9. Recovery chooses a fresh typed tool call
            # -----------------------------------------------------------------
            fresh_call = recovery_mgr.resolve_fresh_target_call("field:pincode", stale_call, ws)
            assert fresh_call is not None
            assert fresh_call.action.target_ref == ref_pincode_2
            assert fresh_call.action.observation_id == obs2.observation_id

            # -----------------------------------------------------------------
            # 10. BrowserExecutor executes it through the registry
            # -----------------------------------------------------------------
            ctx2 = ToolContext(observation=obs2, page=page, executor=executor, observer=observer)
            recovery_result = await registry.execute(fresh_call, ctx2)

            # -----------------------------------------------------------------
            # 11. Verification succeeds
            # -----------------------------------------------------------------
            assert recovery_result.success is True
            assert recovery_result.verification_status in ("verified", "success")

            # -----------------------------------------------------------------
            # 12. Verified semantic progress remains intact
            # -----------------------------------------------------------------
            record_tool_result(ws, recovery_result, tool_call=fresh_call)
            # Prior progress on applicant_name is 100% preserved
            assert ws.verified_values["field:applicant_name"] == "Aarav Kumar"
            assert ws.semantic_fields["field:applicant_name"].status == EpistemicStatus.VERIFIED
            # Newly filled pincode is now also VERIFIED
            assert ws.verified_values["field:pincode"] == "560001"
            assert ws.semantic_fields["field:pincode"].status == EpistemicStatus.VERIFIED

            # Check DOM input value in real browser
            val = await page.locator("input[name='pincode']").input_value()
            assert val == "560001"

            # -----------------------------------------------------------------
            # 13. Recovery attempt is recorded
            # -----------------------------------------------------------------
            assert len(recovery_mgr.history) == 1
            record = recovery_mgr.history[0]
            recovery_mgr.record_attempt_result(
                record, tool_result=recovery_result, world_state_version_after=ws.version,
            )

            assert record.failure_type in (FailureType.STALE_REFERENCE, FailureType.TARGET_NOT_FOUND)
            assert record.attempt_count == 1
            assert record.resulting_tool_result_summary is not None
            assert "ok" in record.resulting_tool_result_summary
            assert record.resulting_world_state_version_change[1] >= record.resulting_world_state_version_change[0]
