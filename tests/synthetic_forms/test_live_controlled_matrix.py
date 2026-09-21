"""Phase 14 live validation — controlled-execution matrix (offline, real Chromium).

Extends test_live_controlled_offline.py with the full WS2/WS3 contract:

Execution surface:
- select_option and check_control execution with verification (not just fill).

Policy behavior:
- CONFIRMATION_REQUIRED (sensitive value_ref) → HITL_REQUIRED, never silent.
- Semantic re-binding targets the CURRENT ref (stale refs in the plan are
  refreshed, not trusted).

Approval lifecycle:
- Expired approval → SAFETY_BLOCKED even with a valid signature.
- World-state drift between plan and page → STALE_TARGET_STOPPED recorded
  as an environment/state condition, never an agent failure.

Environment vs agent:
- Playwright timeout during a controlled run → ENVIRONMENT_FAILURE, never
  AGENT_FAILURE.

Prohibited actions (deterministic, model-independent):
- click / upload / password / otp / captcha / mfa / pin / payment /
  final-legal-submission remain blocked even with a signed approval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agent.live.execution import (
    ControlledPlan,
    ControlledStep,
    make_approved_decision,
)
from app.agent.live.models import (
    ControlledActionDeniedError,
    HumanReviewRequest,
    LiveOutcomeStatus,
    LiveRunMode,
    ReviewSignatureError,
    validate_controlled_action,
)
from app.agent.live.profiles import offline_portal_profile, register_profile
from app.agent.live.shadow import run_live_shadow
from app.models.actions import BrowserAction

PAGES = Path(__file__).parent / "pages"
BASE = PAGES.resolve().as_uri()

SECRET = "phase14-matrix-secret"


@pytest.fixture()
def offline_matrix_profile():
    profile = offline_portal_profile(
        portal_id="offline_matrix",
        name="Offline Controlled Matrix Fixture",
        entrypoint_uri=f"{BASE}/simple.html",
    )
    register_profile(profile)
    return profile


def _review_request_for(report) -> HumanReviewRequest:
    return HumanReviewRequest.model_validate(report.review_request)


def _decision(request, *, expires_at: str = ""):
    return make_approved_decision(request, reviewer="operator", secret=SECRET, expires_at=expires_at)


def _run(portal_id: str, plan: ControlledPlan, request):
    from app.agent.live.execution import run_controlled_execution

    return run_controlled_execution(
        portal_id, plan, review_request=request, review_secret=SECRET,
    )


# ---------------------------------------------------------------------------
# Wider execution surface: select + check (not just fill)
# ---------------------------------------------------------------------------


class TestSelectAndCheckExecution:
    @pytest.mark.asyncio
    async def test_select_option_executes_and_verifies(self, offline_matrix_profile):
        shadow_report, _ = run_live_shadow("offline_matrix")
        request = _review_request_for(shadow_report)

        state = next(
            pa for pa in shadow_report.planned_actions
            if pa.target_semantic_id == "field:state"
        )
        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="select_option",
                    action=BrowserAction(
                        action="select",
                        target_ref=state.target_ref,
                        option="Kerala",
                    ),
                    semantic_id=state.target_semantic_id,
                    description="State",
                )
            ],
            review_decision=_decision(request),
        )
        report, _ = _run("offline_matrix", plan, request)

        assert report.mode == LiveRunMode.LIVE_CONTROLLED_EXECUTION
        assert report.final_status == LiveOutcomeStatus.CONTROLLED_EXECUTION_SUCCESS
        step = report.executed_actions[0]
        assert step["result"] == "VERIFIED"
        assert step["verification_status"] == "success"
        assert step["policy_allowed"] is True

    @pytest.mark.asyncio
    async def test_check_control_executes_and_verifies(self, offline_matrix_profile):
        shadow_report, _ = run_live_shadow("offline_matrix")
        request = _review_request_for(shadow_report)

        # simple.html has no checkbox — the checks.html fixture does. Use a
        # dedicated fixture profile bound to checks.html.
        checks = offline_portal_profile(
            portal_id="offline_matrix_checks",
            name="Offline Controlled Checks Fixture",
            entrypoint_uri=f"{BASE}/checks.html",
        )
        register_profile(checks)
        shadow_checks, _ = run_live_shadow("offline_matrix_checks")
        request2 = _review_request_for(shadow_checks)

        terms = next(
            pa for pa in shadow_checks.planned_actions
            if pa.target_semantic_id == "field:terms"
        )
        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="check_control",
                    action=BrowserAction(
                        action="check",
                        target_ref=terms.target_ref,
                    ),
                    semantic_id=terms.target_semantic_id,
                    description="Terms agreement",
                )
            ],
            review_decision=_decision(request2),
        )
        report, _ = _run("offline_matrix_checks", plan, request2)

        assert report.final_status == LiveOutcomeStatus.CONTROLLED_EXECUTION_SUCCESS
        step = report.executed_actions[0]
        assert step["result"] == "VERIFIED"
        assert step["verification_status"] == "success"


# ---------------------------------------------------------------------------
# Policy behavior: sensitive targets require human confirmation
# ---------------------------------------------------------------------------


class TestPolicyBehaviorInControlledMode:
    @pytest.mark.asyncio
    async def test_sensitive_value_ref_yields_hitl_not_silent_success(
        self, offline_matrix_profile,
    ):
        """A fill carrying a SENSITIVE value_ref gets REQUIRE_CONFIRMATION from
        PolicyEngine. Controlled execution must record that as a HITL boundary
        (CONFIRMATION_REQUIRED), never as success and never as agent failure."""
        shadow_report, _ = run_live_shadow("offline_matrix")
        request = _review_request_for(shadow_report)

        phone = next(
            pa for pa in shadow_report.planned_actions
            if pa.target_semantic_id == "field:phone"
        )
        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="fill_field",
                    action=BrowserAction(
                        action="fill",
                        target_ref=phone.target_ref,
                        value_ref="USER.mobile",
                    ),
                    semantic_id=phone.target_semantic_id,
                    description="Mobile number (sensitive reference)",
                )
            ],
            review_decision=_decision(request),
        )
        report, _ = _run("offline_matrix", plan, request)

        assert report.final_status == LiveOutcomeStatus.HITL_REQUIRED
        step = report.executed_actions[0]
        assert step["result"] == "CONFIRMATION_REQUIRED"
        # Nothing was verified as executed
        assert all(a["result"] != "VERIFIED" for a in report.executed_actions)
        # Final boundary evidence still recorded
        assert report.final_boundary.no_final_submission_executed is True

    @pytest.mark.asyncio
    async def test_stale_ref_in_plan_is_rebound_not_trusted(
        self, offline_matrix_profile,
    ):
        """The reviewed plan carries the ref observed at planning time. When
        the CURRENT page shows a different ref for the same semantic target,
        semantic re-binding targets the fresh ref (durable semantics, ephemeral
        refs) and the action still verifies."""
        shadow_report, _ = run_live_shadow("offline_matrix")
        request = _review_request_for(shadow_report)

        fullname = next(
            pa for pa in shadow_report.planned_actions
            if pa.target_semantic_id == "field:fullname"
        )
        # Deliberately poison the ref: point at a WRONG/STALE ref ('e0').
        # Re-binding must resolve field:fullname to the CURRENT ref.
        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="fill_field",
                    action=BrowserAction(
                        action="fill",
                        target_ref="e0",
                        literal_value="Rebound Value",
                    ),
                    semantic_id=fullname.target_semantic_id,
                    description="Full Name (stale planning ref)",
                )
            ],
            review_decision=_decision(request),
        )
        report, _ = _run("offline_matrix", plan, request)

        assert report.final_status == LiveOutcomeStatus.CONTROLLED_EXECUTION_SUCCESS
        step = report.executed_actions[0]
        assert step["result"] == "VERIFIED"


# ---------------------------------------------------------------------------
# Approval lifecycle: expiry and world-state drift
# ---------------------------------------------------------------------------


class TestApprovalLifecycle:
    @pytest.mark.asyncio
    async def test_expired_approval_is_safety_blocked(self, offline_matrix_profile):
        """A signed approval with an expiry in the past is rejected even
        though the signature itself is valid — approvals are bounded
        authorizations, not permanent ones."""
        shadow_report, _ = run_live_shadow("offline_matrix")
        request = _review_request_for(shadow_report)

        expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        decision = _decision(request, expires_at=expired)

        fullname = next(
            pa for pa in shadow_report.planned_actions
            if pa.target_semantic_id == "field:fullname"
        )
        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="fill_field",
                    action=BrowserAction(
                        action="fill",
                        target_ref=fullname.target_ref,
                        literal_value="should never execute",
                    ),
                    semantic_id=fullname.target_semantic_id,
                    description="Full Name",
                )
            ],
            review_decision=decision,
        )
        report, _ = _run("offline_matrix", plan, request)

        assert report.final_status == LiveOutcomeStatus.SAFETY_BLOCKED
        assert report.executed_actions == []
        assert any(
            ev.startswith("REVIEW_BINDING_REJECTED")
            for ev in report.security_events
        )

    @pytest.mark.asyncio
    async def test_future_expiry_is_accepted(self, offline_matrix_profile):
        shadow_report, _ = run_live_shadow("offline_matrix")
        request = _review_request_for(shadow_report)

        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        decision = _decision(request, expires_at=future)

        fullname = next(
            pa for pa in shadow_report.planned_actions
            if pa.target_semantic_id == "field:fullname"
        )
        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="fill_field",
                    action=BrowserAction(
                        action="fill",
                        target_ref=fullname.target_ref,
                        literal_value="Fresh Approval Value",
                    ),
                    semantic_id=fullname.target_semantic_id,
                    description="Full Name",
                )
            ],
            review_decision=decision,
        )
        report, _ = _run("offline_matrix", plan, request)
        assert report.final_status == LiveOutcomeStatus.CONTROLLED_EXECUTION_SUCCESS

    @pytest.mark.asyncio
    async def test_world_state_drift_stops_without_guessing(self):
        """The reviewed semantic target disappears from the page after
        approval: the run STOPS (STALE_TARGET_STOPPED) instead of guessing a
        substitute target. The stop is an environment/state condition."""
        # dynamic_recovery.html re-renders and REMOVES nothing by itself —
        # but its pincode field changes ref on re-render. For a deterministic
        # disappearance we point the plan at a semantic ID absent from the
        # fixture page entirely (drifted world).
        profile = offline_portal_profile(
            portal_id="offline_matrix_drift",
            name="Offline Controlled Drift Fixture",
            entrypoint_uri=f"{BASE}/simple.html",
        )
        register_profile(profile)
        shadow_report, _ = run_live_shadow("offline_matrix_drift")
        request = _review_request_for(shadow_report)

        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="fill_field",
                    action=BrowserAction(
                        action="fill",
                        target_ref="e1",
                        literal_value="drifted",
                    ),
                    semantic_id="field:drifted_away_target",
                    description="Field that no longer exists",
                )
            ],
            review_decision=_decision(request),
        )
        report, _ = _run("offline_matrix_drift", plan, request)

        assert report.final_status == LiveOutcomeStatus.ENVIRONMENT_FAILURE
        assert report.environment_condition.value == "ENVIRONMENT_FAILURE"
        step = report.executed_actions[0]
        assert step["result"] == "STALE_TARGET_STOPPED"
        assert "drift" in step["detail"]
        # The un-reviewed substitute was NEVER executed
        assert all(a["result"] != "VERIFIED" for a in report.executed_actions)


# ---------------------------------------------------------------------------
# Environment failure is not an agent failure
# ---------------------------------------------------------------------------


class TestEnvironmentVsAgentInControlledMode:
    @pytest.mark.asyncio
    async def test_timeout_during_controlled_run_is_environment_failure(self):
        """A Playwright timeout inside a controlled run is classified as an
        environment condition — never collapsed into AGENT_FAILURE."""
        from unittest.mock import patch

        from app.agent.live.execution import run_controlled_execution_async

        profile = offline_portal_profile(
            portal_id="offline_matrix_timeout",
            name="Offline Controlled Timeout Fixture",
            entrypoint_uri=f"{BASE}/simple.html",
        )
        register_profile(profile)
        shadow_report, _ = run_live_shadow("offline_matrix_timeout")
        request = _review_request_for(shadow_report)

        fullname = next(
            pa for pa in shadow_report.planned_actions
            if pa.target_semantic_id == "field:fullname"
        )
        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="fill_field",
                    action=BrowserAction(
                        action="fill",
                        target_ref=fullname.target_ref,
                        literal_value="timeout probe",
                    ),
                    semantic_id=fullname.target_semantic_id,
                    description="Full Name",
                )
            ],
            review_decision=_decision(request),
        )

        from playwright.async_api import TimeoutError as PWTimeout

        # Patch the page-level observation the controlled loop uses to
        # re-bind targets: the timeout fires mid-run (after gates passed).
        async def _timeout_observe(self, page):
            raise PWTimeout("Timeout 20000ms exceeded")

        with patch(
            "app.agent.live.execution.PageObserver.observe",
            new=_timeout_observe,
        ):
            report, _ = await run_controlled_execution_async(
                "offline_matrix_timeout",
                plan,
                review_request=request,
                review_secret=SECRET,
            )

        assert report.final_status == LiveOutcomeStatus.ENVIRONMENT_FAILURE
        assert report.environment_condition.value == "TIMEOUT"
        assert report.final_status != LiveOutcomeStatus.AGENT_FAILURE


# ---------------------------------------------------------------------------
# Prohibited actions remain prohibited — even with a signed approval
# ---------------------------------------------------------------------------


class TestProhibitedActionsMatrix:
    """Deterministic, model-independent denial of every prohibited class."""

    def test_click_denied(self):
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("click", "click", "e7", "Continue")

    def test_upload_denied(self):
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action(
                "upload_document", "upload", "field:proof", "Upload document"
            )

    def test_password_target_denied(self):
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("fill_field", "fill", "field:password", "Password")

    def test_otp_target_denied(self):
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("fill_field", "fill", "field:otp", "Enter OTP")

    def test_captcha_target_denied(self):
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("fill_field", "fill", "field:captcha", "CAPTCHA")

    def test_mfa_keyword_denied(self):
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("fill_field", "fill", "field:mfa_code", "MFA code")

    def test_pin_target_denied(self):
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("fill_field", "fill", "field:pin", "PIN")

    def test_payment_text_denied(self):
        for text in ("Pay Now", "Proceed to Pay", "Payment"):
            with pytest.raises(ControlledActionDeniedError):
                validate_controlled_action("check_control", "check", "e9", text)

    def test_final_legal_submission_denied(self):
        for text in ("Submit Application", "I declare that the above is true",
                     "Final Submit", "Complete Application"):
            with pytest.raises(ControlledActionDeniedError):
                validate_controlled_action("fill_field", "fill", "e9", text)

    def test_uncheck_is_allowed_for_non_boundary_targets(self):
        # The allowlist includes uncheck — verify it is not over-blocked.
        validate_controlled_action("uncheck_control", "uncheck", "e3", "Newsletter option")

    def test_denial_is_independent_of_model_output(self):
        """Even if a (hypothetical compromised) model marked a submit click as
        low-risk fill, the deterministic gate re-checks the ACTUAL tool +
        action type. There is no path for model text to authorize these."""
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("click", "click", "btn_submit", "")
        with pytest.raises(ControlledActionDeniedError):
            validate_controlled_action("upload_document", "upload", "e2", "")


class TestApprovalExpiryAtUnitLevel:
    def test_expired_decision_rejected_at_gate(self):
        from app.agent.live.execution import _verify_review_decision

        profile_report = None

        class _FakeRequest:
            pass

        # Build a real request via the shadow models (no browser needed).
        from tests.unit.test_live_validation import _review_request, _approved_decision  # noqa: F401

        req = _review_request()
        expired = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        d = make_approved_decision(req, reviewer="op", secret="s", expires_at=expired)
        with pytest.raises(ReviewSignatureError, match="expired"):
            _verify_review_decision(d, req, "s")
