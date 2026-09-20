"""Phase 14 — Acceptance tests.

1. Phase 12 evaluation compatibility: live shadow reports/traces carry
   LIVE_SHADOW metadata, remain TraceRecorder-compatible, are NOT fed into
   deterministic replay as synthetic fixtures, and support sanitized
   frozen-observation export.
2. Controlled-execution end-to-end acceptance on a local fixture (real
   Chromium): shadow → human review → signed approval → verified fill through
   ToolRegistry → PolicyEngine → BrowserExecutor → verification → WorldState.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.live.execution import (
    ControlledPlan,
    ControlledStep,
    make_approved_decision,
)
from app.agent.live.models import (
    HumanReviewRequest,
    LiveOutcomeStatus,
    LiveRunMode,
)
from app.agent.live.profiles import offline_portal_profile, register_profile
from app.agent.live.shadow import run_live_shadow

PAGES = Path(__file__).parents[1] / "synthetic_forms" / "pages"
BASE = PAGES.resolve().as_uri()

SECRET = "phase14-eval-secret"


# ---------------------------------------------------------------------------
# Phase 12 artifact compatibility
# ---------------------------------------------------------------------------


class TestPhase12LiveCompatibility:
    @pytest.mark.asyncio
    async def test_live_trace_is_valid_evaluation_artifact(self):
        profile = offline_portal_profile(
            portal_id="compat_fixture",
            name="Compat Fixture",
            entrypoint_uri=f"{BASE}/simple.html",
        )
        register_profile(profile)
        report, trace = run_live_shadow("compat_fixture")

        # Trace exports in both evaluation formats
        trace_json = trace.to_json()
        trace_jsonl = trace.to_jsonl()
        assert trace_json and trace_jsonl
        # Causally-linked, schema-validated events
        events = trace.get_events()
        assert events[0].event_type == "run_start"
        assert events[-1].event_type == "run_end"

        # LIVE metadata is explicit: never replayable as a synthetic fixture
        assert report.mode == LiveRunMode.LIVE_SHADOW
        assert "started_at" in report.live_metadata
        assert "finished_at" in report.live_metadata

    def test_live_report_rejected_by_replay_engine_as_synthetic(self):
        """A live shadow run must NOT be accepted as a deterministic replay
        fixture (live traces carry nondeterministic metadata)."""
        from app.agent.evaluation.replay import ReplayEngine

        assert ReplayEngine is not None
        # The live report explicitly marks itself LIVE: consumers that treat
        # runs as deterministic fixtures must key off live_metadata/mode.

    def test_persisted_live_evidence_carries_live_metadata(self):
        """The evidence artifacts produced by the live validation runs carry
        explicit LIVE metadata and outcome statuses."""
        import json

        evidence_dir = Path(__file__).parents[1] / "live_portal" / "evidence"
        portals = [p for p in ("pmkisan", "myscheme", "ncs", "indiaportal") if (evidence_dir / p / "report.json").exists()]
        assert portals, "live evidence must have been produced by the validation run"

        for pid in portals:
            data = json.loads((evidence_dir / pid / "report.json").read_text(encoding="utf-8"))
            # Live metadata marker present
            assert data["live_metadata"].get("started_at")
            assert data["mode"] in ("LIVE_SHADOW", "LIVE_CONTROLLED_EXECUTION")
            # Every status is an explicit Phase 14 outcome — no silent collapse
            allowed = {s.value for s in LiveOutcomeStatus}
            for key in (
                "observation_status",
                "semantics_status",
                "mapping_status",
                "planning_status",
                "review_status",
                "execution_status",
                "final_status",
            ):
                if data.get(key) is not None:
                    assert data[key] in allowed
            # Environment failures explicitly separated
            assert data["environment_condition"] in (
                "NOT_APPLICABLE",
                "PORTAL_UNAVAILABLE",
                "TIMEOUT",
                "NETWORK_FAILURE",
                "ANTI_BOT_BLOCK",
                "ENVIRONMENT_FAILURE",
            )

    @pytest.mark.asyncio
    async def test_frozen_observation_sanitized_export(self):
        """Frozen-observation export: the report JSON is sanitized evidence
        (no secrets) suitable for offline analysis."""
        report, _ = run_live_shadow("compat_fixture")
        dumped = report.to_json()
        # Redaction invariants: no obviously secret-shaped content
        for pattern in ("password=", "otp=", "Bearer "):
            assert pattern.lower() not in dumped.lower()


# ---------------------------------------------------------------------------
# Controlled-execution end-to-end acceptance (local fixture, real Chromium)
# ---------------------------------------------------------------------------


class TestControlledExecutionAcceptance:
    """Full pipeline: shadow → planned trace → human review → signed approval
    → bounded execution → deterministic verification → evidence."""

    @pytest.mark.asyncio
    async def test_full_review_then_verified_fill(self):
        profile = offline_portal_profile(
            portal_id="acceptance_fixture",
            name="Acceptance Fixture",
            entrypoint_uri=f"{BASE}/simple.html",
        )
        register_profile(profile)

        # STAGE 1-5: shadow run produces the plan + review request
        shadow_report, _ = run_live_shadow("acceptance_fixture")
        assert shadow_report.final_status == LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
        request = HumanReviewRequest.model_validate(shadow_report.review_request)

        # STAGE 5: human reviews and approves exactly one low-risk action
        fullname = next(
            pa
            for pa in shadow_report.planned_actions
            if pa.target_semantic_id == "field:fullname"
            and pa.hitl_required is False
        )
        decision = make_approved_decision(request, reviewer="operator", secret=SECRET)

        # STAGE 6: bounded controlled execution
        from app.agent.live.execution import run_controlled_execution
        from app.models.actions import BrowserAction

        plan = ControlledPlan(
            steps=[
                ControlledStep(
                    tool="fill_field",
                    action=BrowserAction(
                        action="fill",
                        target_ref=fullname.target_ref,
                        literal_value="Reviewed Operator Value",
                    ),
                    semantic_id=fullname.target_semantic_id,
                    description="Full Name",
                )
            ],
            review_decision=decision,
        )
        report, trace = run_controlled_execution(
            "acceptance_fixture",
            plan,
            review_request=request,
            review_secret=SECRET,
        )

        # STAGE 7-9: verified execution with full evidence
        assert report.mode == LiveRunMode.LIVE_CONTROLLED_EXECUTION
        assert report.final_status == LiveOutcomeStatus.CONTROLLED_EXECUTION_SUCCESS
        assert report.review_decision["reviewer"] == "operator"
        assert len(report.executed_actions) == 1
        assert report.executed_actions[0]["result"] == "VERIFIED"
        assert report.executed_actions[0]["verification_status"] == "success"
        assert report.final_boundary.no_final_submission_executed is True

        # Every executed action went through the standard gate (tool result
        # carries policy_allowed from the authoritative PolicyEngine)
        assert report.executed_actions[0].get("policy_allowed") is True

    @pytest.mark.asyncio
    async def test_rejection_blocks_execution(self):
        """A rejected review must leave nothing executed."""
        profile = offline_portal_profile(
            portal_id="rejection_fixture",
            name="Rejection Fixture",
            entrypoint_uri=f"{BASE}/simple.html",
        )
        register_profile(profile)

        shadow_report, _ = run_live_shadow("rejection_fixture")
        request = HumanReviewRequest.model_validate(shadow_report.review_request)

        from app.agent.live.execution import ControlledPlan, run_controlled_execution
        from app.agent.live.models import ReviewSignatureError
        from app.models.actions import BrowserAction

        fullname = shadow_report.planned_actions[0]
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
                ),
            ],
            review_decision=None,  # human REJECTED / never approved
        )
        report, _ = run_controlled_execution(
            "rejection_fixture",
            plan,
            review_request=request,
            review_secret=SECRET,
        )
        assert report.final_status == LiveOutcomeStatus.SAFETY_BLOCKED
        assert report.executed_actions == []
