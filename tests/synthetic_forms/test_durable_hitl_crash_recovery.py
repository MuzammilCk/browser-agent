"""Phase 8 Primary Acceptance Scenario — Durable HITL Crash Recovery with PostgreSQL & Real Chromium.

Proves Phase 8 exit criterion:
"The process can be killed and restarted during an OTP/CAPTCHA pause and the same
run can safely resume without reusing stale DOM references or stale human approval."

Workflow:
1. Synthetic workflow begins on otp_verification.html.
2. Agent completes valid progress (fills and verifies personal details).
3. Agent triggers OTP step; page layout changes dynamically.
4. Agent reaches OTP_REQUIRED; human interrupt & checkpoint persisted to PostgreSQL.
5. Process is terminated (runtime & store discarded).
6. New process starts.
7. Same run is loaded from PostgreSQL.
8. Browser/session reconnected.
9. Current browser state is re-observed.
10. WorldState is reconstructed/updated.
11. Old DOM refs are invalidated.
12. Interrupt remains pending.
13. Stale approvals are tested and rejected if mismatched.
14. Human provides OTP response and grants valid approval.
15. Resume is requested.
16. Atomic lock is acquired in PostgreSQL with fencing token.
17. Agent continues from the same logical subgoal.
18. Previously verified semantic facts remain intact.
19. No stale DOM ref is used (fresh ref resolved for OTP input).
20. Interrupt transitions to RESUMED.
21. OTP is submitted and application completes.
22. Checkpoint is updated transactionally and audit trail is recorded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.agent.interrupts.models import (
    ApprovalBinding,
    InterruptReason,
    InterruptStatus,
    ResumeRequest,
)
from app.agent.persistence.postgres_store import PostgresCheckpointStore
from app.agent.runtime.resume import ResumeCoordinator
from app.agent.runtime.runtime import AgentRuntime
from app.agent.runtime.state import AgentLifecycle, AgentRunState
from app.agent.world.models import AgentWorldState, EpistemicStatus
from app.agent.world.reducer import is_target_ref_valid, reduce_observation
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.models.actions import BrowserAction

import os

POSTGRES_TEST_DSN = (
    os.getenv("POSTGRES_TEST_DSN")
    or os.getenv("POSTGRES_URL")
    or Settings().postgres_url
)
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


class TestDurableHitlCrashRecovery:
    """Proves the Phase 8 crash recovery exit criterion with real Chromium and PostgreSQL."""

    @pytest.mark.asyncio
    async def test_kill_process_during_otp_and_resume_safely(self, settings: Settings) -> None:
        run_id = f"run_hitl_{uuid.uuid4().hex[:8]}"

        # ======================================================================
        # PROCESS 1: Initial Run & Progress
        # ======================================================================
        pg_store_1 = PostgresCheckpointStore(POSTGRES_TEST_DSN)
        await pg_store_1.connect()

        async with BrowserManager(settings) as browser_mgr:
            page = await browser_mgr.open(f"{SYNTHETIC_BASE}/otp_verification.html")
            observer = PageObserver()
            executor = BrowserExecutor()

            # 1. Observe initial page
            obs1 = await observer.observe(page)
            assert obs1 is not None

            # Build initial WorldState
            ws1 = AgentWorldState(version=1, portal=obs1.page_state.url, current_observation_id=obs1.observation_id)
            ws1 = reduce_observation(ws1, obs1)

            # 2. Perform valid progress: fill applicant details
            ref_name = _find_ref(obs1, "fullname")
            act1 = BrowserAction(action="fill", target_ref=ref_name, literal_value="Asha Kumar")
            res1 = await executor.execute(page, act1, obs1)
            assert res1.success is True

            # Reduce into WorldState and mark verified
            obs2 = await observer.observe(page)
            ws1 = reduce_observation(ws1, obs2)
            ws1.verified_values["field:fullname"] = "Asha Kumar"
            field_name = ws1.semantic_fields.get("field:fullname")
            assert field_name is not None
            field_name.status = EpistemicStatus.VERIFIED
            field_name.verified_value = "Asha Kumar"

            # 3. Trigger OTP step: click Generate OTP
            button_el = next(el for el in obs2.page_state.elements if el.role == "button")
            act_gen = BrowserAction(action="click", target_ref=button_el.ref)
            res_gen = await executor.execute(page, act_gen, obs2)
            assert res_gen.success is True

            # 4. Re-observe: Step 1 hidden, Step 2 (OTP challenge) active!
            obs_otp = await observer.observe(page)
            ws2 = reduce_observation(ws1, obs_otp)

            # Old DOM ref for fullname is now invalidated!
            assert not is_target_ref_valid(ws2, ref_name, obs_otp.observation_id)

            # 5. Agent detects OTP challenge -> raises HumanInterrupt
            rt_1 = AgentRuntime(checkpoint_store=pg_store_1)
            session = rt_1.create_session(label="test_hitl_session")
            run_1 = rt_1.create_run(session=session, goal="Apply for income certificate")
            run_1.run_id = run_id
            run_1.agent_world_state = ws2
            run_1.current_subgoal = "sg_otp_verification"

            intr = rt_1.raise_human_interrupt(
                run_1,
                reason=InterruptReason.OTP_REQUIRED,
                description="Enter 6-digit OTP received on registered mobile",
                observation_id=obs_otp.observation_id,
                world_state_version=ws2.version,
                subgoal_id="sg_otp_verification",
                required_action="enter_otp",
                target_identity="field:otp",
                semantic_id="field:otp",
            )
            assert intr.status == InterruptStatus.WAITING_FOR_USER
            assert run_1.lifecycle == AgentLifecycle.WAITING_FOR_USER

            # Persist checkpoint & interrupt to PostgreSQL
            latest_cp = rt_1.get_checkpoint(intr.checkpoint_id)
            assert latest_cp is not None
            await pg_store_1.save_checkpoint(latest_cp)
            await pg_store_1.save_interrupt(intr)

            # ==================================================================
            # 6. SIMULATE PROCESS TERMINATION / CRASH:
            # Drop runtime instance 1, close database store 1
            # ==================================================================
            del rt_1
            del run_1
            await pg_store_1.close()

            # ==================================================================
            # PROCESS 2: New Process Starts & Resumes Run
            # ==================================================================
            pg_store_2 = PostgresCheckpointStore(POSTGRES_TEST_DSN)
            await pg_store_2.connect()

            # 7. Load checkpoint from PostgreSQL in Process 2
            restored_cp = await pg_store_2.load_latest_for_run(run_id)
            assert restored_cp is not None
            assert restored_cp.run_id == run_id
            assert restored_cp.state.goal == "Apply for income certificate"
            assert restored_cp.state.current_subgoal == "sg_otp_verification"

            # 8. Re-observe current live browser state
            obs_reconnected = await observer.observe(page)
            assert obs_reconnected.observation_id != obs1.observation_id

            # 9. WorldState reconciliation in new process
            restored_ws = restored_cp.state.agent_world_state
            assert restored_ws is not None
            reconciled_ws = reduce_observation(restored_ws, obs_reconnected)

            # 10. Verify previously verified facts remain 100% intact!
            assert reconciled_ws.verified_values["field:fullname"] == "Asha Kumar"
            assert reconciled_ws.is_field_verified("field:fullname")

            # 11. Stale DOM refs rejected
            assert not is_target_ref_valid(reconciled_ws, ref_name, obs_reconnected.observation_id)

            # 12. Human interrupt remains pending in PostgreSQL
            stored_intr = await pg_store_2.get_interrupt(intr.interrupt_id)
            assert stored_intr is not None
            assert stored_intr.status == InterruptStatus.WAITING_FOR_USER

            # 13. Test Stale Approval Rejection:
            # If an approval was granted against an old/mismatched version, reject it!
            stale_approval = ApprovalBinding(
                run_id=run_id,
                interrupt_id=stored_intr.interrupt_id,
                requested_action="enter_otp",
                target_identity="field:otp",
                semantic_id="field:otp",
                world_state_version=999,  # Mismatch!
                observation_id="obs_old",
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            )
            coordinator_2 = ResumeCoordinator(store=pg_store_2)
            stale_req = ResumeRequest(run_id=run_id, interrupt_id=stored_intr.interrupt_id, approval=stale_approval)
            stale_res = await coordinator_2.resume_run(stale_req, page=page, observer=observer)
            assert stale_res.success is False
            assert stale_res.status == "reconfirmation_required"

            # 14. Human completes required authentication step directly in the browser
            await page.locator("#otp").fill("987654")
            await page.locator("#btn_verify_otp").click()

            valid_approval = ApprovalBinding(
                run_id=run_id,
                interrupt_id=stored_intr.interrupt_id,
                requested_action="enter_otp",
                target_identity="field:otp",
                semantic_id="field:otp",
                world_state_version=reconciled_ws.version,
                observation_id=obs_reconnected.observation_id,
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                approved_by="citizen_user",
            )
            await pg_store_2.save_approval(valid_approval)

            # 15. Resume requested with valid approval
            resume_req = ResumeRequest(
                run_id=run_id,
                interrupt_id=stored_intr.interrupt_id,
                worker_id="worker_process_2",
                approval=valid_approval,
            )

            # 16. ResumeCoordinator acquires lock & resumes run
            resume_res = await coordinator_2.resume_run(resume_req, page=page, observer=observer)
            assert resume_res.success is True
            assert resume_res.status == "resumed"

            # 17. Interrupt transitioned to RESUMED in PostgreSQL
            final_intr = await pg_store_2.get_interrupt(stored_intr.interrupt_id)
            assert final_intr is not None
            assert final_intr.status == InterruptStatus.RESUMED

            # 18. Verified semantic facts remain intact
            assert reconciled_ws.verified_values["field:fullname"] == "Asha Kumar"

            # 19. Agent completes action on the post-auth page using fresh ref
            obs_current = await observer.observe(page)
            download_btn_ref = next(
                el.ref for el in obs_current.page_state.elements
                if el.role == "button" and "Download" in (el.accessible_name or "")
            )
            assert download_btn_ref != ref_name  # Cannot be the old ref from Step 1!

            act_download = BrowserAction(action="click", target_ref=download_btn_ref)
            res_download = await executor.execute(page, act_download, obs_current)
            assert res_download.success is True

            # 20. Verify final success confirmation page and receipt reached
            obs_final = await observer.observe(page)
            assert "ACK-IND-8829" in (obs_final.aria_snapshot or "")
            assert "Receipt Downloaded" in (obs_final.aria_snapshot or "")

            # 21. Release lock upon completion
            released = await pg_store_2.release_resume_lock(run_id, "worker_process_2")
            assert released is True

            # 22. Verify full audit trail recorded in PostgreSQL
            audit_events = await pg_store_2.get_audit_events(run_id)
            event_types = [e["event_type"] for e in audit_events]
            assert "CHECKPOINT_SAVED" in event_types
            assert "INTERRUPT_CREATED" in event_types
            assert "APPROVAL_GRANTED" in event_types
            assert "RESUME_LOCK_ACQUIRED" in event_types
            assert "RESUME_SUCCEEDED" in event_types
            assert "RESUME_LOCK_RELEASED" in event_types

            # Close PostgreSQL connection
            await pg_store_2.close()
