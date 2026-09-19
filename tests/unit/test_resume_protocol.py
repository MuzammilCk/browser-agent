"""Unit tests for Phase 8 Resume Protocol & Stale Approval Rejection.

Covers:
15. checkpoint schema version is validated
16. corrupted checkpoint fails closed
17. browser is re-observed on resume
18. stale DOM ref is rejected
19. current semantic target is re-resolved
20. stale approval is rejected after WorldState changes
21. unchanged valid approval can resume
22. expired interrupt is rejected
23. expired approval is rejected
24. invalid semantic target causes safe rejection
25. authentication cannot be bypassed
26. final confirmation remains human-controlled
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptReason,
    InterruptStatus,
    ResumeRequest,
)
from app.agent.persistence.in_memory_store import InMemoryCheckpointStore
from app.agent.runtime.checkpoint import AgentCheckpoint, IncompatibleCheckpointSchema
from app.agent.runtime.resume import ResumeCoordinator
from app.agent.runtime.runtime import AgentRuntime
from app.agent.runtime.state import AgentLifecycle
from app.agent.world.models import AgentWorldState, EpistemicStatus, SemanticField
from app.models.page_state import ElementState, PageObservation, PageState


class TestResumeProtocolPartC:
    """Part C resume safety tests."""

    @pytest.fixture
    def setup_env(self):
        store = InMemoryCheckpointStore()
        coordinator = ResumeCoordinator(store=store)
        rt = AgentRuntime(checkpoint_store=store)
        session = rt.create_session(label="test")
        run = rt.create_run(session=session, goal="Renew Driving License")
        run.lifecycle = AgentLifecycle.OBSERVING
        return store, coordinator, rt, run

    @pytest.mark.asyncio
    async def test_checkpoint_schema_version_is_validated(self, setup_env):
        """15. Checkpoint schema version is validated."""
        store, coordinator, rt, run = setup_env
        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="Confirm renewal",
        )
        cp = store.load(intr.checkpoint_id)
        assert cp is not None
        assert cp.format_version == 2
        cp.validate_schema()  # Should not raise

        # Incompatible future version
        cp_future = AgentCheckpoint.from_dict(cp.to_dict())
        cp_future.format_version = 999
        with pytest.raises(IncompatibleCheckpointSchema):
            cp_future.validate_schema()

    def test_corrupted_checkpoint_fails_closed(self):
        """16. Corrupted checkpoint fails closed."""
        with pytest.raises(ValidationError):
            AgentCheckpoint.from_json("{\"corrupted\": true, \"format_version\": 2}")

    @pytest.mark.asyncio
    async def test_browser_is_reobserved_on_resume(self, setup_env):
        """17. Browser is re-observed on resume."""
        store, coordinator, rt, run = setup_env
        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="Confirm step",
            observation_id="obs_old_1",
            required_action="click",
            target_identity="button:confirm",
        )

        mock_page = MagicMock()
        mock_observer = MagicMock()
        fresh_obs = PageObservation(
            observation_id="obs_fresh_2",
            page_state=PageState(
                url="https://transport.gov.in/renew",
                page_type="form",
                elements=[
                    ElementState(
                        ref="e1",
                        role="button",
                        accessible_name="Confirm",
                    )
                ],
            ),
        )
        mock_observer.observe = AsyncMock(return_value=fresh_obs)

        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id)
        res = await coordinator.resume_run(req, page=mock_page, observer=mock_observer)

        assert res.success is True
        mock_observer.observe.assert_awaited_once_with(mock_page)

    @pytest.mark.asyncio
    async def test_stale_dom_ref_is_rejected_and_reresolved(self, setup_env):
        """18 & 19. Stale DOM ref is rejected; current semantic target is re-resolved."""
        store, coordinator, rt, run = setup_env

        # Run had semantic field with old ref e1
        ws = AgentWorldState(version=1)
        ws.semantic_fields["field:otp"] = SemanticField(
            semantic_id="field:otp",
            label="OTP Input",
            current_ref="e1_old",
            current_observation_id="obs_old",
            status=EpistemicStatus.OBSERVED,
        )
        run.agent_world_state = ws

        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.OTP_REQUIRED,
            description="Enter OTP",
            observation_id="obs_old",
            world_state_version=1,
            required_action="fill",
            target_identity="field:otp",
            semantic_id="field:otp",
        )

        # Fresh observation has new ref e5 for OTP
        mock_page = MagicMock()
        mock_observer = MagicMock()
        fresh_obs = PageObservation(
            observation_id="obs_fresh_99",
            page_state=PageState(
                url="https://service.gov.in/otp",
                page_type="form",
                elements=[
                    ElementState(
                        ref="e5",
                        role="textbox",
                        html_name="otp",
                        accessible_name="OTP Input",
                    )
                ],
            ),
        )
        mock_observer.observe = AsyncMock(return_value=fresh_obs)

        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id)
        res = await coordinator.resume_run(req, page=mock_page, observer=mock_observer)

        assert res.success is True
        # Verify WorldState was updated and e1_old is invalidated
        loaded_cp = await store.load_latest_for_run(run.run_id)
        assert loaded_cp is not None
        updated_ws = loaded_cp.state.agent_world_state
        assert updated_ws is not None
        otp_field = updated_ws.semantic_fields.get("field:otp")
        assert otp_field is not None
        # Old ref is replaced with fresh ref e5!
        assert otp_field.current_ref == "e5"
        assert otp_field.current_observation_id == "obs_fresh_99"

    @pytest.mark.asyncio
    async def test_stale_approval_is_rejected_after_world_state_changes(self, setup_env):
        """20. Stale approval is rejected after WorldState changes."""
        store, coordinator, rt, run = setup_env
        ws = AgentWorldState(version=184)
        run.agent_world_state = ws

        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="Confirm details",
            world_state_version=184,
            required_action="confirm",
            target_identity="btn_confirm",
        )

        approval = ApprovalBinding(
            run_id=run.run_id,
            interrupt_id=intr.interrupt_id,
            requested_action="confirm",
            target_identity="btn_confirm",
            world_state_version=184,
            observation_id="obs_184",
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        )
        rt.approve_interrupt(run, approval)

        # Before resume, page state / WorldState advanced to version 191
        ws_advanced = AgentWorldState(version=191)
        run.agent_world_state = ws_advanced
        # Update checkpoint to simulate background drift
        rt.checkpoint_run(run, reason="drift")

        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id, approval=approval)
        res = await coordinator.resume_run(req)

        assert res.success is False
        assert res.status == "reconfirmation_required"
        assert "Stale approval rejected" in res.reason

    @pytest.mark.asyncio
    async def test_unchanged_valid_approval_can_resume(self, setup_env):
        """21. Unchanged valid approval can resume."""
        store, coordinator, rt, run = setup_env
        ws = AgentWorldState(version=50)
        run.agent_world_state = ws

        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="Confirm step",
            world_state_version=50,
            required_action="confirm",
            target_identity="btn_confirm",
        )

        approval = ApprovalBinding(
            run_id=run.run_id,
            interrupt_id=intr.interrupt_id,
            requested_action="confirm",
            target_identity="btn_confirm",
            world_state_version=50,
            observation_id="obs_50",
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        )
        rt.approve_interrupt(run, approval)

        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id, approval=approval)
        res = await coordinator.resume_run(req)

        assert res.success is True
        assert res.status == "resumed"

    @pytest.mark.asyncio
    async def test_expired_interrupt_is_rejected(self, setup_env):
        """22. Expired interrupt is rejected."""
        store, coordinator, rt, run = setup_env
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.OTP_REQUIRED,
            description="Enter OTP",
            expires_at=past,
        )

        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id)
        res = await coordinator.resume_run(req)

        assert res.success is False
        assert res.status == "expired"
        assert "expired" in res.reason

    @pytest.mark.asyncio
    async def test_expired_approval_is_rejected(self, setup_env):
        """23. Expired approval is rejected."""
        store, coordinator, rt, run = setup_env
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="Confirm payment",
            expires_at=future,
        )

        approval = ApprovalBinding(
            run_id=run.run_id,
            interrupt_id=intr.interrupt_id,
            requested_action="confirm",
            target_identity="btn_pay",
            world_state_version=0,
            observation_id="obs_1",
            expires_at=past,  # Expired approval!
        )

        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id, approval=approval)
        res = await coordinator.resume_run(req)

        assert res.success is False
        assert res.status == "expired"

    @pytest.mark.asyncio
    async def test_invalid_semantic_target_causes_safe_rejection(self, setup_env):
        """24. Invalid semantic target causes safe rejection."""
        store, coordinator, rt, run = setup_env
        future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="Confirm upload",
            required_action="click",
            target_identity="button:submit_doc",
            expires_at=future,
        )

        approval = ApprovalBinding(
            run_id=run.run_id,
            interrupt_id=intr.interrupt_id,
            requested_action="click",
            target_identity="button:wrong_target",  # Mismatch!
            world_state_version=0,
            observation_id="obs_1",
            expires_at=future,
        )

        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id, approval=approval)
        res = await coordinator.resume_run(req)

        assert res.success is False
        assert res.status == "reconfirmation_required"
        assert "target mismatch" in res.reason

    @pytest.mark.asyncio
    async def test_authentication_cannot_be_bypassed(self, setup_env):
        """25. Authentication cannot be bypassed (demands human handover)."""
        store, coordinator, rt, run = setup_env
        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.AUTHENTICATION_REQUIRED,
            description="DigiLocker login required",
        )
        assert intr.reason == InterruptReason.AUTHENTICATION_REQUIRED
        assert intr.status == InterruptStatus.WAITING_FOR_USER
        assert run.lifecycle == AgentLifecycle.WAITING_FOR_USER

    @pytest.mark.asyncio
    async def test_final_confirmation_remains_human_controlled(self, setup_env):
        """26. Final confirmation remains human-controlled (cannot resume without approval)."""
        store, coordinator, rt, run = setup_env
        intr = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.FINAL_REVIEW_REQUIRED,
            description="Final review of entire application",
        )

        # Resume attempt WITHOUT approval binding
        req = ResumeRequest(run_id=run.run_id, interrupt_id=intr.interrupt_id, approval=None)
        res = await coordinator.resume_run(req)

        assert res.success is False
        assert res.status == "reconfirmation_required"
        assert "Final review requires explicit user confirmation" in res.reason
