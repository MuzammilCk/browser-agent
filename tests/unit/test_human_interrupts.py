"""Tests for Durable Human Interrupts (HITL) — Phase 8 Part A.

Covers:
1. OTP pause creates a durable interrupt
2. CAPTCHA pause creates a durable interrupt
3. clarification pause creates a durable interrupt
4. confirmation pause creates a durable interrupt
5. final review pause remains human-controlled
6. illegal interrupt transitions are rejected
7. interrupt serialization/deserialization is lossless
8. approval binding validation and expiration
9. approval invalidation on WorldState version drift
10. approval invalidation on target or action mismatch
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent.interrupts.lifecycle import (
    INTERRUPT_TRANSITIONS,
    InvalidInterruptTransition,
    can_transition,
    is_expired,
    validate_approval,
    validate_transition,
)
from app.agent.interrupts.models import (
    ApprovalBinding,
    HumanInterrupt,
    InterruptReason,
    InterruptStatus,
    utc_now_iso,
)
from app.agent.runtime.runtime import AgentRuntime
from app.agent.runtime.state import AgentLifecycle, AgentRunState


class TestHumanInterruptsPartA:
    """Part A requirements 1–7."""

    def _make_runtime_and_run(self) -> tuple[AgentRuntime, AgentRunState]:
        rt = AgentRuntime()
        session = rt.create_session(label="test_session")
        run = rt.create_run(session=session, goal="Apply for farmer subsidy")
        run.lifecycle = AgentLifecycle.OBSERVING
        return rt, run

    def test_otp_pause_creates_durable_interrupt(self):
        """1. OTP pause creates a durable interrupt."""
        rt, run = self._make_runtime_and_run()
        interrupt = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.OTP_REQUIRED,
            description="6-digit OTP sent to registered Aadhaar mobile",
            observation_id="obs_otp_101",
            world_state_version=5,
            subgoal_id="sg_auth",
            required_action="enter_otp",
            target_identity="field:aadhaar_otp",
            semantic_id="field:aadhaar_otp",
        )

        assert interrupt.reason == InterruptReason.OTP_REQUIRED
        assert interrupt.status == InterruptStatus.WAITING_FOR_USER
        assert run.lifecycle == AgentLifecycle.WAITING_FOR_USER
        assert run.human_interrupt is not None
        assert run.human_interrupt.interrupt_id == interrupt.interrupt_id
        assert interrupt.checkpoint_id is not None
        # Verify checkpoint contains the interrupt
        cp = rt.get_checkpoint(interrupt.checkpoint_id)
        assert cp.human_interrupt is not None
        assert cp.human_interrupt.reason == InterruptReason.OTP_REQUIRED

    def test_captcha_pause_creates_durable_interrupt(self):
        """2. CAPTCHA pause creates a durable interrupt."""
        rt, run = self._make_runtime_and_run()
        interrupt = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.CAPTCHA_REQUIRED,
            description="Visual CAPTCHA challenge detected",
            observation_id="obs_captcha_102",
            target_identity="field:captcha_input",
            semantic_id="field:captcha",
        )

        assert interrupt.reason == InterruptReason.CAPTCHA_REQUIRED
        assert interrupt.status == InterruptStatus.WAITING_FOR_USER
        assert run.lifecycle == AgentLifecycle.WAITING_FOR_USER
        assert run.human_interrupt.target_identity == "field:captcha_input"

    def test_clarification_pause_creates_durable_interrupt(self):
        """3. Clarification pause creates a durable interrupt."""
        rt, run = self._make_runtime_and_run()
        interrupt = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CLARIFICATION_REQUIRED,
            description="Ambiguous land category: select irrigated or dryland",
            observation_id="obs_land_103",
            metadata={"options": ["irrigated", "dryland"]},
        )

        assert interrupt.reason == InterruptReason.USER_CLARIFICATION_REQUIRED
        assert interrupt.status == InterruptStatus.WAITING_FOR_USER
        assert interrupt.metadata["options"] == ["irrigated", "dryland"]

    def test_confirmation_pause_creates_durable_interrupt(self):
        """4. Confirmation pause creates a durable interrupt."""
        rt, run = self._make_runtime_and_run()
        interrupt = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.USER_CONFIRMATION_REQUIRED,
            description="Confirm submission of personal details",
            observation_id="obs_confirm_104",
            required_action="confirm_step",
            target_identity="button:continue",
        )

        assert interrupt.reason == InterruptReason.USER_CONFIRMATION_REQUIRED
        assert interrupt.status == InterruptStatus.WAITING_FOR_USER
        assert interrupt.required_action == "confirm_step"

    def test_final_review_pause_remains_human_controlled(self):
        """5. Final review pause remains human-controlled."""
        rt, run = self._make_runtime_and_run()
        interrupt = rt.raise_human_interrupt(
            run,
            reason=InterruptReason.FINAL_REVIEW_REQUIRED,
            description="Legal declaration and final application submission boundary",
            observation_id="obs_final_105",
            required_action="confirm_final_review",
            target_identity="button:final_submit",
        )

        assert interrupt.reason == InterruptReason.FINAL_REVIEW_REQUIRED
        # Approval is None initially
        assert interrupt.approval_binding is None
        assert run.approval_binding is None

        # Human attaches approval
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=10)
        approval = ApprovalBinding(
            run_id=run.run_id,
            interrupt_id=interrupt.interrupt_id,
            requested_action="confirm_final_review",
            target_identity="button:final_submit",
            semantic_id=None,
            world_state_version=10,
            observation_id="obs_final_105",
            expires_at=exp.isoformat(),
            approved_by="citizen_user",
        )
        approved_intr = rt.approve_interrupt(run, approval)
        assert approved_intr.status == InterruptStatus.APPROVED
        assert approved_intr.approval_binding is not None
        assert approved_intr.approval_binding.approved_by == "citizen_user"

    def test_illegal_interrupt_transitions_are_rejected(self):
        """6. Illegal interrupt transitions are rejected (fail closed)."""
        # PENDING cannot jump directly to RESUMED
        assert not can_transition(InterruptStatus.PENDING, InterruptStatus.RESUMED)
        with pytest.raises(InvalidInterruptTransition):
            validate_transition(InterruptStatus.PENDING, InterruptStatus.RESUMED)

        # APPROVED cannot jump to WAITING_FOR_USER directly
        assert not can_transition(InterruptStatus.APPROVED, InterruptStatus.WAITING_FOR_USER)
        with pytest.raises(InvalidInterruptTransition):
            validate_transition(InterruptStatus.APPROVED, InterruptStatus.WAITING_FOR_USER)

        # Terminal states have no outgoing transitions
        for term in (InterruptStatus.RESUMED, InterruptStatus.REJECTED, InterruptStatus.EXPIRED, InterruptStatus.CANCELLED):
            assert len(INTERRUPT_TRANSITIONS[term]) == 0
            with pytest.raises(InvalidInterruptTransition):
                validate_transition(term, InterruptStatus.APPROVED)

    def test_interrupt_serialization_roundtrip_lossless(self):
        """7. Interrupt serialization/deserialization is lossless."""
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=30)
        intr = HumanInterrupt(
            run_id="run_test_42",
            reason=InterruptReason.OTP_REQUIRED,
            status=InterruptStatus.APPROVED,
            description="Enter verification code",
            observation_id="obs_999",
            world_state_version=12,
            subgoal_id="sg_verify",
            required_action="submit_otp",
            target_identity="field:otp",
            semantic_id="field:otp",
            created_at=now.isoformat(),
            expires_at=exp.isoformat(),
            metadata={"attempt": 1, "service": "uidai"},
            approval_binding=ApprovalBinding(
                run_id="run_test_42",
                interrupt_id="int_xyz",
                requested_action="submit_otp",
                target_identity="field:otp",
                semantic_id="field:otp",
                world_state_version=12,
                observation_id="obs_999",
                expires_at=exp.isoformat(),
                approved_by="user",
            ),
        )

        raw_json = intr.model_dump_json()
        loaded = HumanInterrupt.model_validate_json(raw_json)

        assert loaded.interrupt_id == intr.interrupt_id
        assert loaded.run_id == intr.run_id
        assert loaded.reason == intr.reason
        assert loaded.status == intr.status
        assert loaded.world_state_version == 12
        assert loaded.metadata == {"attempt": 1, "service": "uidai"}
        assert loaded.approval_binding is not None
        assert loaded.approval_binding.requested_action == "submit_otp"


class TestApprovalBindingValidation:
    """Approval binding invalidation semantics."""

    def test_approval_expires_deterministically(self):
        now = datetime.now(timezone.utc)
        past = now - timedelta(seconds=10)
        future = now + timedelta(minutes=10)

        appr_expired = ApprovalBinding(
            run_id="run_1",
            interrupt_id="int_1",
            requested_action="click",
            target_identity="btn_submit",
            world_state_version=1,
            observation_id="obs_1",
            expires_at=past.isoformat(),
        )
        assert appr_expired.is_expired(now)
        valid, reason = appr_expired.is_valid_for(
            current_world_state_version=1,
            current_action="click",
            current_target_identity="btn_submit",
            now=now,
        )
        assert not valid
        assert "expired" in reason

        appr_valid = ApprovalBinding(
            run_id="run_1",
            interrupt_id="int_1",
            requested_action="click",
            target_identity="btn_submit",
            world_state_version=1,
            observation_id="obs_1",
            expires_at=future.isoformat(),
        )
        assert not appr_valid.is_expired(now)
        valid, reason = appr_valid.is_valid_for(
            current_world_state_version=1,
            current_action="click",
            current_target_identity="btn_submit",
            now=now,
        )
        assert valid
        assert reason == "valid"

    def test_approval_invalidates_on_world_state_drift(self):
        now = datetime.now(timezone.utc)
        future = now + timedelta(minutes=10)

        approval = ApprovalBinding(
            run_id="run_1",
            interrupt_id="int_1",
            requested_action="confirm_final_review",
            target_identity="button:final_submit",
            world_state_version=184,
            observation_id="obs_184",
            expires_at=future.isoformat(),
        )

        # Page state advanced to version 191
        valid, reason = validate_approval(
            approval,
            current_world_state_version=191,
            current_action="confirm_final_review",
            current_target_identity="button:final_submit",
            now=now,
        )
        assert not valid
        assert "world_state_version mismatch" in reason

    def test_approval_invalidates_on_target_or_action_mismatch(self):
        now = datetime.now(timezone.utc)
        future = now + timedelta(minutes=10)

        approval = ApprovalBinding(
            run_id="run_1",
            interrupt_id="int_1",
            requested_action="fill",
            target_identity="field:otp",
            semantic_id="field:otp",
            world_state_version=10,
            observation_id="obs_10",
            expires_at=future.isoformat(),
        )

        # Action changed to 'click'
        valid_act, reason_act = validate_approval(
            approval,
            current_world_state_version=10,
            current_action="click",
            current_target_identity="field:otp",
            current_semantic_id="field:otp",
            now=now,
        )
        assert not valid_act
        assert "action mismatch" in reason_act

        # Target changed
        valid_tgt, reason_tgt = validate_approval(
            approval,
            current_world_state_version=10,
            current_action="fill",
            current_target_identity="field:phone",
            current_semantic_id="field:phone",
            now=now,
        )
        assert not valid_tgt
        assert "target mismatch" in reason_tgt
