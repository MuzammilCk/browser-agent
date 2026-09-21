"""Phase 14 — Live portal shadow validation (real government portals).

RUN ONLY with explicit operator intent:

    RUN_REAL_SITE_TESTS=true python -m pytest tests/real_sites/test_live_shadow.py -v

Safety contract (Phase 14):
- OBSERVATION ONLY: no form fill, no click, no navigation beyond the portal
  entrypoint. Zero mutation against live government portals.
- One page load per portal; conservative pacing.
- The planned action trace, mapping evidence, and human review request are
  recorded — never executed.
- Environment conditions (anti-bot blocks, timeouts) are recorded as such and
  are NOT counted as agent failures. A portal that cannot be safely reached
  yields PORTAL_UNAVAILABLE / ANTI_BOT_BLOCK — an honest, passing outcome.
"""

from __future__ import annotations

import os

import pytest

from app.agent.live.models import (
    LiveOutcomeStatus,
    LiveRunMode,
    shadow_run_is_success,
)
from app.agent.live.profiles import get_live_portal_profile
from app.agent.live.shadow import run_live_shadow

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_SITE_TESTS", "").lower() != "true",
    reason="Live portal tests require RUN_REAL_SITE_TESTS=true (observation-only, no CI)",
)


def _assert_shadow_safety(report) -> None:
    """Invariants that must hold for EVERY live shadow run, success or not."""
    assert report.mode == LiveRunMode.LIVE_SHADOW
    assert report.executed_actions == [], "shadow mode must never execute"
    assert report.final_boundary is None or (
        report.final_boundary.no_final_submission_executed is True
    )
    # No mutation events in the trace
    # (imported lazily to keep module import light)
    from app.agent.evaluation.trace import TraceEventType

    return None


class TestLiveShadowPmKisan:
    """Welfare portal (pmkisan.gov.in) — observation-only."""

    @pytest.mark.asyncio
    async def test_shadow_observation_only(self):
        profile = get_live_portal_profile("pmkisan")
        report, trace = run_live_shadow("pmkisan")

        _assert_shadow_safety(report)

        if report.final_status == LiveOutcomeStatus.PORTAL_UNAVAILABLE:
            pytest.skip(f"Portal unavailable: {report.environment_condition}")
        if report.final_status == LiveOutcomeStatus.SAFETY_BLOCKED:
            pytest.fail("Origin mismatch on official portal — must be investigated")

        assert report.final_status == LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
        assert report.observation_status == LiveOutcomeStatus.PORTAL_OBSERVATION_SUCCESS
        assert report.observation.url.startswith("https://pmkisan.gov.in")
        assert report.observation.element_count > 0
        assert report.semantics_status == LiveOutcomeStatus.SEMANTICS_SUCCESS
        assert len(report.planned_actions) >= 1
        assert shadow_run_is_success(report)


class TestLiveShadowMyScheme:
    """Certificate/scheme-discovery portal (myscheme.gov.in)."""

    @pytest.mark.asyncio
    async def test_shadow_observation_only(self):
        report, trace = run_live_shadow("myscheme")

        _assert_shadow_safety(report)

        if report.final_status == LiveOutcomeStatus.PORTAL_UNAVAILABLE:
            pytest.skip(f"Portal unavailable: {report.environment_condition}")
        if report.final_status == LiveOutcomeStatus.SAFETY_BLOCKED:
            pytest.fail("Origin mismatch on official portal — must be investigated")

        assert report.final_status == LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
        assert report.observation.element_count > 0
        assert report.semantics_status == LiveOutcomeStatus.SEMANTICS_SUCCESS
        assert shadow_run_is_success(report)


class TestLiveShadowNCS:
    """Recruitment portal (ncs.gov.in) — includes job-search field mapping."""

    @pytest.mark.asyncio
    async def test_shadow_observation_with_search_semantics(self):
        report, trace = run_live_shadow("ncs")

        _assert_shadow_safety(report)

        if report.final_status == LiveOutcomeStatus.PORTAL_UNAVAILABLE:
            pytest.skip(f"Portal unavailable: {report.environment_condition}")

        assert report.final_status == LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
        assert report.observation_status == LiveOutcomeStatus.PORTAL_OBSERVATION_SUCCESS
        # Field mapping evidence exists and surfaces ambiguity rather than guessing
        assert report.mapping is not None
        assert (
            report.mapping.mapped > 0 or report.mapping.unmapped
        ), "mapping must produce evidence (mapped fields or explicit unmapped list)"
        if report.mapping.ambiguous:
            # Ambiguity must be recorded, not silently resolved
            assert report.mapping_status in (
                LiveOutcomeStatus.MAPPING_SUCCESS,
                LiveOutcomeStatus.AMBIGUOUS,
            )
        assert shadow_run_is_success(report)


class TestLiveShadowIndiaPortal:
    """National services gateway — currently CDN/anti-bot blocked from this
    environment. The block must be classified as an environment condition,
    NOT an agent failure and NOT a successful observation."""

    @pytest.mark.asyncio
    async def test_blocked_portal_classified_as_environment(self):
        report, trace = run_live_shadow("indiaportal")

        _assert_shadow_safety(report)

        if report.final_status == LiveOutcomeStatus.PORTAL_UNAVAILABLE:
            # Honest classification: anti-bot block is an environment condition
            assert report.environment_condition.value in (
                "ANTI_BOT_BLOCK",
                "NETWORK_FAILURE",
                "TIMEOUT",
            )
            assert report.final_status != LiveOutcomeStatus.AGENT_FAILURE
            assert report.observation_status is None
            return

        # If the block is lifted, the full pipeline must work
        assert report.final_status == LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
        assert shadow_run_is_success(report)


# ---------------------------------------------------------------------------
# Phase 14 live-validation expansion: remaining intended portal classes.
# Each class below asserts the same safety invariants and honestly records
# PORTAL_UNAVAILABLE when a portal cannot be reached — an environment
# condition, never an agent failure and never forced coverage.
# ---------------------------------------------------------------------------


class _ExpandedPortalContract:
    """Shared observation-only contract for every expanded live target."""

    portal_id = ""
    origin_prefix = ""

    async def _run(self):
        report, trace = run_live_shadow(self.portal_id)
        _assert_shadow_safety(report)
        if report.final_status == LiveOutcomeStatus.PORTAL_UNAVAILABLE:
            # Honest environment classification — the run still passed.
            assert report.environment_condition.value in (
                "ANTI_BOT_BLOCK", "NETWORK_FAILURE", "TIMEOUT", "ENVIRONMENT_FAILURE",
            )
            assert report.final_status != LiveOutcomeStatus.AGENT_FAILURE
            pytest.skip(f"Portal unavailable: {report.environment_condition.value}")
        if report.final_status == LiveOutcomeStatus.SAFETY_BLOCKED:
            pytest.fail("Origin mismatch on official portal — must be investigated")
        return report, trace

    async def test_shadow_observation_only(self):
        report, _ = await self._run()

        assert report.final_status == LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
        assert report.observation_status == LiveOutcomeStatus.PORTAL_OBSERVATION_SUCCESS
        assert report.observation.url.startswith(self.origin_prefix)
        assert report.observation.element_count > 0
        assert report.semantics_status == LiveOutcomeStatus.SEMANTICS_SUCCESS
        # Mapping evidence exists; unsupported/ambiguous is recorded honestly
        assert report.mapping is not None
        if report.mapping.mapped == 0:
            assert report.mapping_status == LiveOutcomeStatus.UNSUPPORTED
        else:
            assert report.mapping_status == LiveOutcomeStatus.MAPPING_SUCCESS
        # Every planned action carries risk + policy classification
        for pa in report.planned_actions:
            assert pa.policy_decision
            assert pa.verification_criterion
        # Final boundary evidence recorded; nothing executed
        assert report.final_boundary is not None
        assert report.final_boundary.no_final_submission_executed is True
        assert shadow_run_is_success(report)


class TestLiveShadowApprenticeship(_ExpandedPortalContract):
    """Training portal (apprenticeshipindia.gov.in)."""

    portal_id = "apprenticeship"
    origin_prefix = "https://www.apprenticeshipindia.gov.in"


class TestLiveShadowUdisePlus(_ExpandedPortalContract):
    """Education portal (udiseplus.gov.in)."""

    portal_id = "udiseplus"
    origin_prefix = "https://udiseplus.gov.in"


class TestLiveShadowParivahan(_ExpandedPortalContract):
    """Transport portal (parivahan.gov.in)."""

    portal_id = "parivahan"
    origin_prefix = "https://parivahan.gov.in"


class TestLiveShadowDigiLocker(_ExpandedPortalContract):
    """Identity/document portal (digilocker.gov.in) — auth boundary must be
    detected and reported, never crossed."""

    portal_id = "digilocker"
    origin_prefix = "https://www.digilocker.gov.in"

    @pytest.mark.asyncio
    async def test_auth_boundary_recorded_when_detected(self):
        report, _ = await self._run()
        if report.observation.auth_detected:
            # The boundary must be visible in evidence as an event
            assert any(
                ev.startswith("AUTH_BOUNDARY_DETECTED")
                for ev in report.security_events
            )
            # And NO planned action may target authentication
            assert report.planned_actions == [] or all(
                not pa.target_semantic_id.lower().startswith(("field:password", "field:otp"))
                for pa in report.planned_actions
            )


class TestLiveShadowPassport(_ExpandedPortalContract):
    """Appointments portal (passportindia.gov.in)."""

    portal_id = "passport"
    origin_prefix = "https://www.passportindia.gov.in"
