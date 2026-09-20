"""Phase 14 — Live shadow mode.

OBSERVE → semantic extraction → field mapping → planned action trace →
human review record. NEVER executes a mutation against a live portal.

Model-independence: the reasoner is never invoked in shadow mode, so model
output can never switch shadow mode into live mutation mode. Field mapping is
the existing deterministic FieldMapper (no LLM gateway supplied — deterministic
rules only); the planned action trace is derived deterministically from
observation + mapping + PolicyEngine risk classification.

Everything captured from the live portal is UNTRUSTED_WEB: it informs the
evidence report and nothing else. No approval can be minted from page content.
"""

from __future__ import annotations

import logging
import time
import uuid

from app.agent.evaluation.models import BaselineIdentity
from app.agent.evaluation.trace import TraceEventType, TraceRecorder
from app.agent.live.models import (
    EnvironmentCondition,
    FieldMappingEvidence,
    FinalBoundaryEvidence,
    HumanReviewRequest,
    LiveOutcomeStatus,
    LivePortalRunReport,
    LiveRunMode,
    OriginMismatchError,
    PlannedAction,
    SemanticExtractionEvidence,
    classify_environment_error,
    classify_injection_exposure,
    shadow_run_is_success,
    utc_now_iso,
)
from app.agent.live.profiles import get_live_portal_profile
from app.agent.field_mapper import FieldMapper
from app.agent.world.semantic_id import compute_semantic_id
from app.browser.manager import BrowserManager
from app.browser.observer import PageObservation, PageObserver
from app.config.settings import Settings
from app.policy.engine import PolicyDecision, PolicyEngine

logger = logging.getLogger(__name__)

# Conservative live-interaction pacing (rate-limit invariant).
_LIVE_SETTLE_SECONDS = 2.0

# Substrings in accessible/label text that mark a final-boundary control.
_FINAL_BOUNDARY_KEYWORDS = (
    "submit",
    "finalize",
    "declaration",
    "i declare",
    "i hereby",
    "pay now",
    "pay fee",
    "payment",
    "proceed to pay",
    "apply now",
    "complete application",
)

# Read-only tool planning map: element role → planned tool + argument note.
_PLANNED_TOOLS = {
    "textbox": ("fill_field", "fill", "mapped USER.* reference (pending review)"),
    "combobox": ("select_option", "select", "mapped option (pending human-confirmed choice)"),
    "checkbox": ("check_control", "check", "mapped option (pending human-confirmed choice)"),
    "radio": ("check_control", "check", "mapped reference"),
    "file": ("upload_document", "upload", "DOCUMENT.* semantic reference (vault-scoped)"),
}


# Error-page titles produced by anti-bot/CDN layers (Akamai etc.). A page
# with one of these titles is NOT the real portal — classify as environment.
_BLOCKED_PAGE_TITLES = (
    "access denied",
    "forbidden",
    "attention required",
    "access to this page has been denied",
    "just a moment",  # Cloudflare challenge
    "please wait while we verify",  # anti-bot interstitial
)


def _detect_anti_bot_block(observation: PageObservation) -> bool:
    """Detect CDN/anti-bot block pages generically from page title.

    A blocked page must be recorded as an environment condition, never as a
    successful observation of the portal (external instability is not agent
    success — Phase 14 invariant 10).
    """
    title = (observation.page_state.title or "").lower()
    return any(marker in title for marker in _BLOCKED_PAGE_TITLES)


def _evidence_from_observation(observation: PageObservation) -> SemanticExtractionEvidence:
    """Deterministic extraction evidence from a live observation."""
    state = observation.page_state
    elements = state.elements
    counts: dict[str, int] = {}
    selected_options = 0
    required_fields = 0
    for el in elements:
        counts[el.role] = counts.get(el.role, 0) + 1
        if el.selected_options:
            selected_options += len(el.selected_options)
        if el.required:
            required_fields += 1
    interactive = sum(
        n for role, n in counts.items() if role in _PLANNED_TOOLS or role in ("button", "link")
    )
    auth = state.authentication
    return SemanticExtractionEvidence(
        observation_id=observation.observation_id,
        url=state.url,
        title=state.title,
        page_type=state.page_type or "unknown",
        element_count=len(elements),
        interactive_count=interactive,
        textboxes=counts.get("textbox", 0),
        comboboxes=counts.get("combobox", 0),
        buttons=counts.get("button", 0),
        links=counts.get("link", 0),
        checkboxes=counts.get("checkbox", 0),
        radios=counts.get("radio", 0),
        alerts=len(state.alerts),
        validation_errors=len(state.validation_errors),
        frames=len(state.frames),
        auth_detected=bool(auth.detected),
        auth_challenge_type=auth.challenge_type or "",
        aria_snapshot_chars=len(observation.aria_snapshot or ""),
        selected_options_seen=selected_options,
        required_fields_seen=required_fields,
    )


def _classify_element_risk(
    policy: PolicyEngine, element, mapped_reference: str | None = None
) -> tuple[str, str]:
    """Risk classification for a planned action on this element.

    Builds a well-formed probe action (never executed) so PolicyEngine's
    deterministic risk classifier — not guesswork — assigns the risk column.
    For textboxes the probe carries the ACTUAL mapped reference so the plan's
    risk matches what PolicyEngine would decide for the real action.
    """
    role = element.role
    if role == "textbox":
        ref = mapped_reference if mapped_reference and mapped_reference.startswith(("USER.", "DOCUMENT.")) else "USER.full_name"
        probe = _probe("fill", value_ref=ref)
    elif role == "combobox":
        probe = _probe("select", option="(planning probe)")
    elif role in ("checkbox", "radio"):
        probe = _probe("check")
    elif role == "file":
        probe = _probe("upload", document_ref=mapped_reference or "DOCUMENT.proof_of_identity")
    else:
        probe = _probe("click")
    result = policy.evaluate(probe)
    return result.risk_level.value, result.decision.value


def _probe(action: str, **kwargs):
    from app.models.actions import BrowserAction

    return BrowserAction(action=action, target_ref="e0", **kwargs)


async def _map_fields_deterministically(
    observation: PageObservation,
) -> tuple[FieldMappingEvidence, list[dict]]:
    """Deterministic field mapping (existing FieldMapper, no LLM gateway).

    Returns the evidence record plus per-element rows used for planning.
    """
    mapper = FieldMapper(llm_gateway=None)
    mapping = await mapper.map_fields(observation)

    by_ref: dict[str, dict] = {}
    bindings: list[dict] = []
    for b in mapping.bindings:
        if not b.binding:
            continue
        bindings.append(
            {
                "field_ref": b.field_ref,
                "reference": b.binding,
                "confidence": b.confidence.value,
                "strategy": b.strategy.value,
            }
        )
        by_ref[b.field_ref] = {
            "reference": b.binding,
            "confidence": b.confidence.value,
        }
    evidence = FieldMappingEvidence(
        total_interactive=mapping.total_fields,
        mapped=mapping.mapped_count,
        unmapped=list(mapping.unmapped_fields),
        ambiguous=list(mapping.ambiguous_fields),
        strategy_counts=mapping.strategy_counts,
        bindings=bindings,
    )
    return evidence, [by_ref]


def _build_planned_actions(
    observation: PageObservation,
    policy: PolicyEngine,
    ref_to_mapping: dict,
) -> tuple[list[PlannedAction], list[str], list[str], FinalBoundaryEvidence]:
    """Derive the planned action trace deterministically.

    Returns (planned_actions, ambiguous_refs, submit_controls, boundary_evidence).
    Buttons/links are NOT planned as executions — they are recorded as
    navigation proposals requiring explicit review; only data-entry actions on
    non-sensitive, non-boundary targets enter the plan.
    """
    planned: list[PlannedAction] = []
    ambiguous_refs: list[str] = []
    submit_controls: list[str] = []
    order = 0

    state = observation.page_state
    for el in state.elements:
        role = el.role
        if role not in _PLANNED_TOOLS:
            if role in ("button", "link"):
                text = (el.accessible_name or el.label_text or el.html_name or "").lower()
                if any(kw in text for kw in _FINAL_BOUNDARY_KEYWORDS):
                    submit_controls.append(f"{el.ref}: {(el.accessible_name or el.label_text or '').strip()}")
            continue
        if el.disabled or not el.visible:
            continue

        semantic_id = compute_semantic_id(el)
        mapping_info = ref_to_mapping.get(el.ref)
        reference = mapping_info["reference"] if mapping_info else None
        confidence = mapping_info["confidence"] if mapping_info else "UNMAPPED"

        text = (el.accessible_name or el.label_text or el.html_name or "").lower()
        is_boundary = any(kw in text or kw in semantic_id for kw in _FINAL_BOUNDARY_KEYWORDS)
        sensitive_sid = semantic_id.lower().startswith(
            ("field:password", "field:otp", "field:captcha", "field:pin")
        )
        role_lower = role

        tool, _action_type, args_note = _PLANNED_TOOLS[role_lower]
        risk, decision = _classify_element_risk(policy, el, reference)

        hitl_required = bool(
            is_boundary
            or sensitive_sid
            or confidence == "LOW"
            or decision in ("require_confirmation", "pause_for_user", "deny")
            or (reference or "").lower().startswith(("password", "otp", "pin", "aadhaar"))
        )
        if mapping_info is None or confidence in ("MEDIUM", "LOW"):
            ambiguous_refs.append(el.ref)
            policy_decision = "AMBIGUOUS — human clarification required (no guess)"
        elif is_boundary or sensitive_sid:
            policy_decision = "HITL_REQUIRED — human boundary, never autonomous"
        else:
            policy_decision = f"PLANNED ({decision}) — human review before execution"

        if is_boundary or sensitive_sid:
            expected = "NO AUTONOMOUS EXECUTION — stops at human boundary"
            criterion = "human completes the boundary step; agent re-observes after"
        else:
            expected = f"{semantic_id} holds mapped value after execution (deterministic verifier)"
            criterion = f"post-action observation shows {semantic_id} verified in AgentWorldState"

        planned.append(
            PlannedAction(
                order=order,
                tool=tool,
                target_semantic_id=semantic_id,
                target_ref=el.ref or "",
                observation_id=observation.observation_id,
                risk=risk if not (is_boundary or sensitive_sid) else "HIGH_RISK",
                policy_decision=policy_decision,
                arguments_summary=(
                    f"value_ref={reference or '(unmapped — clarification required)'}; {args_note}"
                ),
                expected_state_transition=expected,
                verification_criterion=criterion,
                hitl_required=hitl_required,
            )
        )
        order += 1

    boundary = FinalBoundaryEvidence(
        submit_controls_detected=submit_controls,
        submit_controls_classified_high_risk=bool(submit_controls),
        controlled_run_blocked_at_boundary=False,
        no_final_submission_executed=True,
    )
    return planned, ambiguous_refs, submit_controls, boundary


def _build_review_request(
    run_id: str,
    profile,
    planned: list[PlannedAction],
    mapping_evidence: FieldMappingEvidence,
    boundary: FinalBoundaryEvidence,
) -> HumanReviewRequest:
    references = sorted(
        {
            a.arguments_summary.split(";", 1)[0].replace("value_ref=", "").strip()
            for a in planned
            if "value_ref=" in a.arguments_summary
            and "unmapped" not in a.arguments_summary
        }
    )
    risk_summary = (
        f"{sum(1 for a in planned if a.hitl_required)} of {len(planned)} planned actions "
        f"require HITL; {len(boundary.submit_controls_detected)} final-boundary controls "
        f"detected and human-gated"
    )
    return HumanReviewRequest(
        request_id=f"review_{run_id}",
        run_id=run_id,
        portal_id=profile.portal_id,
        portal_origin=profile.official_origin,
        intended_actions=planned,
        mapped_references=references,
        risk_summary=risk_summary,
        expected_effect=(
            "Human review before ANY mutation. Shadow mode executed nothing; "
            "controlled execution would proceed action-by-action under PolicyEngine."
        ),
        verification_criteria=[a.verification_criterion for a in planned],
    )


def run_live_shadow(
    portal_id: str,
    *,
    settings: Settings | None = None,
    baseline_identity: BaselineIdentity | None = None,
    take_screenshot: bool = False,
) -> tuple[LivePortalRunReport, TraceRecorder]:
    """Run observation-only live validation for one portal.

    Synchronous wrapper around the async implementation (safe to call from
    tests and scripts; creates its own event loop if none is running).
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run_live_shadow_async(portal_id, settings=settings, baseline_identity=baseline_identity, take_screenshot=take_screenshot))
    # Already inside a loop (e.g. pytest-asyncio): run in a worker thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run,
            _run_live_shadow_async(portal_id, settings=settings, baseline_identity=baseline_identity, take_screenshot=take_screenshot),
        ).result()


async def _run_live_shadow_async(
    portal_id: str,
    *,
    settings: Settings | None,
    baseline_identity: BaselineIdentity | None,
    take_screenshot: bool,
) -> tuple[LivePortalRunReport, TraceRecorder]:
    profile = get_live_portal_profile(portal_id)
    settings = settings or Settings(headless=True)
    identity = baseline_identity or BaselineIdentity(model_identity="no-llm-shadow")
    run_id = f"live_shadow_{uuid.uuid4().hex[:12]}"
    start = time.monotonic()
    policy = PolicyEngine()
    observer = PageObserver()
    security_events: list[str] = []

    recorder = TraceRecorder(run_id=run_id, scenario_id=f"live_shadow_{portal_id}")
    recorder.record(
        TraceEventType.RUN_START,
        subsystem="live_validation",
        component="run_live_shadow",
        input_summary={
            "portal_id": portal_id,
            "mode": LiveRunMode.LIVE_SHADOW.value,
            "official_origin": profile.official_origin,
            "entrypoint": profile.entrypoint,
            "agent_commit": identity.commit_sha,
        },
    )

    report = LivePortalRunReport(
        run_id=run_id,
        mode=LiveRunMode.LIVE_SHADOW,
        portal_id=portal_id,
        portal_class=profile.portal_class,
        official_origin=profile.official_origin,
        agent_commit=identity.commit_sha,
        model_identity=identity.model_identity,
        configuration="headless, deterministic mapper (no LLM), observation-only",
        final_status=LiveOutcomeStatus.AGENT_FAILURE,
        live_metadata={"started_at": utc_now_iso(), "entrypoint": profile.entrypoint},
    )

    try:
        async with BrowserManager(settings) as manager:
            page = await manager.open(profile.entrypoint)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                logger.info("networkidle wait timed out for %s — continuing (live pages)", portal_id)
            observation = await observer.observe(page)

            # ---- STAGE 0: origin validation (before anything else) ----
            if not profile.origin_matches(observation.page_state.url):
                recorder.record(
                    TraceEventType.SECURITY_VIOLATION,
                    subsystem="live_validation",
                    component="run_live_shadow",
                    output_summary={
                        "violation": "ORIGIN_MISMATCH",
                        "observed_url": observation.page_state.url,
                        "official_origin": profile.official_origin,
                    },
                )
                raise OriginMismatchError(
                    f"Live page URL {observation.page_state.url!r} is not on the "
                    f"official origin {profile.official_origin!r}"
                )

            # ---- Anti-bot / CDN block detection (generic) ----
            if _detect_anti_bot_block(observation):
                security_events.append(
                    f"ANTI_BOT_BLOCK_DETECTED:{observation.page_state.title[:50]}"
                )
                report.environment_condition = EnvironmentCondition.ANTI_BOT_BLOCK
                report.final_status = LiveOutcomeStatus.PORTAL_UNAVAILABLE
                recorder.record(
                    TraceEventType.SECURITY_VIOLATION,
                    subsystem="live_validation",
                    component="run_live_shadow",
                    output_summary={
                        "violation": "ANTI_BOT_BLOCK",
                        "page_title": observation.page_state.title,
                        "note": "environment condition — not an agent failure",
                    },
                )
                report.observation = _evidence_from_observation(observation)
                report.observation_status = None
                return report, recorder

            report.observation_status = LiveOutcomeStatus.PORTAL_OBSERVATION_SUCCESS
            report.observation = _evidence_from_observation(observation)
            recorder.record(
                TraceEventType.OBSERVATION,
                subsystem="live_validation",
                component="run_live_shadow",
                input_summary={"observation_id": observation.observation_id},
                output_summary=report.observation.model_dump(),
            )

            # ---- Injection exposure (untrusted content scan) ----
            visible = " ".join(
                (el.accessible_name or el.label_text or el.placeholder or "")
                for el in observation.page_state.elements
            )
            alerts = " ".join(a.text for a in observation.page_state.alerts)
            exposure = classify_injection_exposure(visible, alerts)
            report.injection_exposure = exposure
            if exposure != "none":
                security_events.append(f"PROMPT_INJECTION_PATTERN:{exposure}")
                recorder.record(
                    TraceEventType.SECURITY_VIOLATION,
                    subsystem="live_validation",
                    component="run_live_shadow",
                    output_summary={"violation": "PROMPT_INJECTION_PATTERN", "pattern": exposure},
                )

            # ---- STAGE 2: semantic extraction evidence ----
            if report.observation.element_count == 0:
                report.semantics_status = LiveOutcomeStatus.UNSUPPORTED
            else:
                report.semantics_status = LiveOutcomeStatus.SEMANTICS_SUCCESS

            # ---- STAGE 3: field mapping (deterministic) ----
            if report.semantics_status == LiveOutcomeStatus.SEMANTICS_SUCCESS:
                mapping_evidence, refs = await _map_fields_deterministically(observation)
                ref_to_mapping = refs[0] if refs else {}
                report.mapping = mapping_evidence
                report.mapping_status = (
                    LiveOutcomeStatus.MAPPING_SUCCESS if mapping_evidence.mapped > 0
                    else LiveOutcomeStatus.UNSUPPORTED
                )
                recorder.record(
                    TraceEventType.WORLD_STATE_UPDATE,
                    subsystem="live_validation",
                    component="run_live_shadow",
                    output_summary={"stage": "field_mapping", "mapped": mapping_evidence.mapped},
                )
            else:
                mapping_evidence = FieldMappingEvidence(
                    total_interactive=0, mapped=0, unmapped=[], ambiguous=[]
                )
                ref_to_mapping = {}
                report.mapping_status = LiveOutcomeStatus.UNSUPPORTED

            # ---- STAGE 4: planned action trace (deterministic) ----
            planned, ambiguous_refs, submit_controls, boundary = _build_planned_actions(
                observation, policy, ref_to_mapping
            )
            boundary.controlled_run_blocked_at_boundary = bool(submit_controls)
            report.planned_actions = planned
            report.final_boundary = boundary
            report.planning_status = LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
            recorder.record(
                TraceEventType.TOOL_PROPOSAL,
                subsystem="live_validation",
                component="run_live_shadow",
                output_summary={
                    "stage": "planned_action_trace",
                    "planned": len(planned),
                    "ambiguous": len(ambiguous_refs),
                    "submit_controls_gated": len(submit_controls),
                },
            )

            # ---- STAGE 5: human review request (record only) ----
            review_request = _build_review_request(run_id, profile, planned, mapping_evidence, boundary)
            report.review_request = review_request.model_dump(mode="json")
            report.review_status = (
                LiveOutcomeStatus.HITL_REQUIRED if planned else LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS
            )
            recorder.record(
                TraceEventType.HITL_INTERRUPT,
                subsystem="live_validation",
                component="run_live_shadow",
                output_summary={
                    "stage": "human_review",
                    "request_id": review_request.request_id,
                    "note": "shadow mode — recorded for review; nothing executed",
                },
            )

            # ---- Optional screenshot (sanitized evidence) ----
            if take_screenshot:
                from pathlib import Path

                shots = Path(__file__).parents[3] / "tests" / "live_portal" / "evidence"
                shots.mkdir(parents=True, exist_ok=True)
                shot_path = shots / f"{portal_id}_shadow.png"
                try:
                    await manager.screenshot(path=shot_path, full_page=False)
                    report.frozen_observation_path = str(shot_path)
                except Exception as e:  # screenshot is best-effort evidence
                    logger.info("screenshot failed for %s: %s", portal_id, e)

            # ---- Auth boundary reporting ----
            if report.observation.auth_detected:
                security_events.append(
                    f"AUTH_BOUNDARY_DETECTED:{report.observation.auth_challenge_type}"
                )

            report.final_status = LiveOutcomeStatus.SHADOW_VALIDATION_SUCCESS

    except OriginMismatchError:
        # Safety block — NOT an environment condition and NOT an agent failure.
        report.final_status = LiveOutcomeStatus.SAFETY_BLOCKED
        report.security_events = security_events + ["ORIGIN_MISMATCH"]
    except Exception as exc:
        condition = classify_environment_error(exc)
        report.environment_condition = condition
        if condition == EnvironmentCondition.TIMEOUT:
            report.final_status = LiveOutcomeStatus.ENVIRONMENT_FAILURE
        elif condition == EnvironmentCondition.NETWORK_FAILURE:
            report.final_status = LiveOutcomeStatus.PORTAL_UNAVAILABLE
        elif condition == EnvironmentCondition.ENVIRONMENT_FAILURE:
            report.final_status = LiveOutcomeStatus.ENVIRONMENT_FAILURE
        else:
            report.final_status = LiveOutcomeStatus.AGENT_FAILURE
        logger.warning("live shadow run for %s ended: %s: %s", portal_id, type(exc).__name__, exc)
    finally:
        report.security_events = report.security_events or security_events
        report.duration_seconds = round(time.monotonic() - start, 3)
        report.live_metadata["finished_at"] = utc_now_iso()
        report.live_metadata["success"] = shadow_run_is_success(report)
        recorder.record(
            TraceEventType.RUN_END,
            subsystem="live_validation",
            component="run_live_shadow",
            output_summary={
                "final_status": report.final_status.value,
                "environment_condition": report.environment_condition.value,
                "duration_seconds": report.duration_seconds,
                "executed_actions": 0,
            },
        )

    return report, recorder
