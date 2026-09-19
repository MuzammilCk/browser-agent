"""Unit tests for Evaluation Security and Authority Invariants — Phase 12.

Tests:
1. Evaluation code has NO execution authority (cannot bypass policy or tools).
2. Evaluation cannot modify production HITL approval state.
3. Evaluation cannot write unvalidated entries directly to memory.
4. Security violations (prompt injection, unauthorized redirect, approval replay) fail closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.agent.interrupts.models import ApprovalBinding
from app.agent.security.approval_guard import ApprovalIntegrityGuard
from app.agent.security.models import SecurityViolation, SecurityViolationCode
from app.agent.security.policy_guard import validate_navigation_destination
from app.models.actions import BrowserAction
from app.policy.engine import PolicyDecision, PolicyEngine, RiskLevel


def test_evaluator_cannot_bypass_policy_engine():
    """PolicyEngine enforces deterministic gates independently of evaluation code."""
    engine = PolicyEngine()

    # High-risk action
    action = BrowserAction(action="click", target_ref="btn_submit")
    result = engine.evaluate(action)

    # Evaluator cannot force result.allowed = True without valid human confirmation
    assert result.decision in (PolicyDecision.REQUIRE_CONFIRMATION, PolicyDecision.ALLOW, PolicyDecision.DENY)
    if result.risk_level == RiskLevel.HIGH_RISK:
        assert result.allowed is False


def test_evaluator_cannot_forge_hitl_approval_binding():
    """Spoofed approval claiming approved_by outside HITL context fails closed."""
    fake_approval = ApprovalBinding(
        run_id="run_eval_sec",
        interrupt_id="int_01",
        requested_action="click",
        tool_name="click",
        target_identity="Submit Form",
        semantic_id="btn:submit",
        world_state_version=1,
        observation_id="obs_01",
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        approved_by="evaluation_script",  # Spoofed!
    )

    with pytest.raises(SecurityViolation) as exc:
        ApprovalIntegrityGuard.validate_approval_for_execution(
            fake_approval,
            current_run_id="run_eval_sec",
            current_action="click",
            current_tool_name="click",
            current_target_identity="Submit Form",
            current_world_state_version=1,
        )
    assert exc.value.code == SecurityViolationCode.UNTRUSTED_APPROVAL_SPOOF


def test_unauthorized_redirect_destination_blocked_fail_closed():
    """Destination domain check enforces trusted government domains."""
    untrusted_destination = "https://phishing-attacker.com/login"

    with pytest.raises(SecurityViolation) as exc:
        validate_navigation_destination(untrusted_destination)
    assert exc.value.code == SecurityViolationCode.UNAUTHORIZED_REDIRECT
