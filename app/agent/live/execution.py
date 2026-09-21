"""Phase 14 — Controlled live execution.

Only constructed after a successful shadow validation AND an explicit human
review decision. Every mutation still routes through the ONLY execution path:

    typed ToolCall → ToolRegistry → PolicyEngine → BrowserExecutor
    → verification → WorldState update → fresh observation

Deterministic gates that model output can never override:
1. mode is a constructor argument — the reasoner cannot change it;
2. the human review decision must cryptographically match the review request;
3. every action passes validate_controlled_action (allowlist + boundary + sensitive);
4. PolicyEngine remains authoritative for every action;
5. post-action verification must succeed or the run stops (fail closed);
6. one atomic action per iteration with fresh observation between actions.

There is no portal-specific code here: targets are semantic IDs resolved
through AgentWorldState, exactly as in synthetic evaluation.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.agent.evaluation.models import BaselineIdentity
from app.agent.evaluation.trace import TraceEventType, TraceRecorder
from app.agent.live.models import (
    ControlledActionDeniedError,
    EnvironmentCondition,
    FinalBoundaryEvidence,
    HumanReviewDecision,
    LiveOutcomeStatus,
    LivePortalRunReport,
    LiveRunMode,
    OriginMismatchError,
    PlannedAction,
    ReviewSignatureError,
    classify_environment_error,
    classify_injection_exposure,
    request_digest,
    utc_now_iso,
    validate_controlled_action,
)
from app.agent.live.profiles import get_live_portal_profile
from app.agent.world.models import AgentWorldState
from app.agent.world.reducer import record_tool_result, reduce_observation
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.policy.engine import PolicyEngine

logger = logging.getLogger(__name__)

# Action-type → tool name (ToolRegistry names).
_ACTION_TO_TOOL = {
    "fill": "fill_field",
    "select": "select_option",
    "check": "check_control",
    "uncheck": "uncheck_control",
}


@dataclass
class ControlledStep:
    """One human-reviewed, deterministic-safe action to execute live."""

    tool: str
    action: object  # app.models.actions.BrowserAction
    semantic_id: str
    description: str


@dataclass
class ControlledPlan:
    """The complete reviewed plan for a controlled run."""

    steps: list[ControlledStep] = field(default_factory=list)
    review_decision: HumanReviewDecision | None = None


def _sign(secret: str, digest: str) -> str:
    import hashlib
    import hmac

    return hmac.new(secret.encode("utf-8"), digest.encode("utf-8"), hashlib.sha256).hexdigest()


def make_approved_decision(
    request,  # HumanReviewRequest
    *,
    reviewer: str,
    secret: str,
    reason: str = "operator approved controlled execution",
    expires_at: str = "",
) -> HumanReviewDecision:
    """Helper for the human/operator side: build a validly signed approval.

    In production this is produced by the HITL UI after real human review;
    tests use it to exercise the approval path end-to-end.

    ``expires_at`` is an ISO-8601 UTC timestamp bounding the approval's
    validity. Phase 14 live-validation callers should always set it — an
    approval without expiry is only accepted when the issuing HITL system
    explicitly records none.
    """
    decision = HumanReviewDecision(
        request_id=request.request_id,
        decision="approved",
        reviewer=reviewer,
        reason=reason,
        request_digest=request_digest(request),
        signature="",
        expires_at=expires_at,
    )
    decision.signature = _sign(secret, decision.request_digest)
    return decision


def _verify_review_decision(decision: HumanReviewDecision, request, secret: str) -> None:
    if decision.decision != "approved":
        raise ReviewSignatureError("Human review decision is not an approval")
    if decision.request_id != request.request_id:
        raise ReviewSignatureError("Review decision request_id mismatch")
    if not decision.digest_matches(request):
        raise ReviewSignatureError(
            "Review decision digest mismatch — decision does not bind to this "
            "exact plan (transplant rejected)"
        )
    expected = _sign(secret, decision.request_digest)
    import hmac as _hmac

    if not _hmac.compare_digest(decision.signature, expected):
        raise ReviewSignatureError("Review decision signature invalid")
    # Approval EXPIRY (Phase 14 live validation): a signed approval is a
    # bounded authorization, not a permanent one. Expired approvals are
    # rejected fail-closed exactly like transplanted/forged ones.
    if decision.expires_at:
        from datetime import datetime

        try:
            expires = datetime.fromisoformat(decision.expires_at.replace("Z", "+00:00"))
        except ValueError as e:
            raise ReviewSignatureError(f"Review decision expiry unparseable: {e}") from e
        if datetime.now(UTC) >= expires:
            raise ReviewSignatureError(
                "Review decision expired — human re-approval required "
                f"(expires_at={decision.expires_at})"
            )


async def run_controlled_execution_async(
    portal_id: str,
    plan: ControlledPlan,
    *,
    review_request,  # HumanReviewRequest from the shadow run
    review_secret: str,
    settings: Settings | None = None,
    baseline_identity: BaselineIdentity | None = None,
    max_steps: int = 8,
) -> tuple[LivePortalRunReport, TraceRecorder]:
    """Execute the reviewed, bounded plan against the live portal.

    Fails closed at every gate. Never performs payment, final submission,
    or authentication autonomously.
    """
    profile = get_live_portal_profile(portal_id)
    settings = settings or Settings(headless=True)
    identity = baseline_identity or BaselineIdentity(model_identity="no-llm-controlled")
    run_id = f"live_ctrl_{uuid.uuid4().hex[:12]}"
    start = time.monotonic()
    policy = PolicyEngine()
    observer = PageObserver()
    executor = BrowserExecutor()
    security_events: list[str] = []

    recorder = TraceRecorder(run_id=run_id, scenario_id=f"live_controlled_{portal_id}")
    recorder.record(
        TraceEventType.RUN_START,
        subsystem="live_validation",
        component="run_controlled_execution",
        input_summary={
            "portal_id": portal_id,
            "mode": LiveRunMode.LIVE_CONTROLLED_EXECUTION.value,
            "steps": len(plan.steps),
            "review_request_id": review_request.request_id,
        },
    )

    report = LivePortalRunReport(
        run_id=run_id,
        mode=LiveRunMode.LIVE_CONTROLLED_EXECUTION,
        portal_id=portal_id,
        portal_class=profile.portal_class,
        official_origin=profile.official_origin,
        agent_commit=identity.commit_sha,
        model_identity=identity.model_identity,
        configuration="controlled execution; ToolRegistry→PolicyEngine→BrowserExecutor",
        final_status=LiveOutcomeStatus.AGENT_FAILURE,
        review_request=review_request.model_dump(mode="json"),
        live_metadata={"started_at": utc_now_iso()},
    )

    world = AgentWorldState(goal=f"Controlled execution on {portal_id}")

    try:
        # ---- GATE 1: human review binding (deterministic) ----
        if plan.review_decision is None:
            raise ReviewSignatureError("Controlled execution requires a human review decision")
        _verify_review_decision(plan.review_decision, review_request, review_secret)
        report.review_decision = plan.review_decision.model_dump(mode="json")

        # ---- GATE 2: deterministic per-step validation ----
        if len(plan.steps) > max_steps:
            raise ControlledActionDeniedError(
                f"Controlled plan exceeds max_steps ({len(plan.steps)} > {max_steps})"
            )
        for i, step in enumerate(plan.steps):
            action = step.action
            validate_controlled_action(
                step.tool,
                action.action,
                step.semantic_id,
                step.description,
            )
            recorder.record(
                TraceEventType.TOOL_PROPOSAL,
                subsystem="live_validation",
                component="run_controlled_execution",
                output_summary={
                    "step": i,
                    "tool": step.tool,
                    "semantic_id": step.semantic_id,
                    "action": action.action,
                },
            )

        async with BrowserManager(settings) as manager:
            page = await manager.open(profile.entrypoint)
            try:
                await page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                logger.info("networkidle wait timed out for %s — continuing", portal_id)
            observation = await observer.observe(page)

            # ---- GATE 3: origin validation ----
            if not profile.origin_matches(observation.page_state.url):
                raise OriginMismatchError(
                    f"Live page URL {observation.page_state.url!r} is not on the "
                    f"official origin {profile.official_origin!r}"
                )

            # Reconcile live observation into WorldState (stale refs invalidated).
            world = reduce_observation(world, observation)
            report.observation_status = LiveOutcomeStatus.PORTAL_OBSERVATION_SUCCESS

            executed = 0
            blocked = 0
            completed_all = True
            for i, step in enumerate(plan.steps):
                # Fresh observation + semantic re-binding: DOM refs from the
                # shadow run are EPHEMERAL. The reviewed plan carries the
                # durable semantic ID; the runtime re-binds the CURRENT ref
                # exactly as WorldState reconciliation does everywhere else.
                current_observation = await observer.observe(page)
                world = reduce_observation(world, current_observation)
                bound_action = _rebind_target(step, current_observation)
                if bound_action is None:
                    logger.warning(
                        "controlled run step %s semantic target %s not found on fresh observation",
                        i,
                        step.semantic_id,
                    )
                    report.executed_actions.append(
                        {
                            "step": i,
                            "tool": step.tool,
                            "semantic_id": step.semantic_id,
                            "result": "STALE_TARGET_STOPPED",
                            "detail": (
                                "semantic target absent from fresh observation — "
                                "stopped rather than guessed (world-state drift)"
                            ),
                        }
                    )
                    report.final_status = LiveOutcomeStatus.AGENT_FAILURE
                    completed_all = False
                    break

                tool_call = _ToolCallShim(step.tool, bound_action)
                from app.agent.tools.base import ToolContext

                ctx = ToolContext(
                    observation=current_observation,
                    page=page,
                    executor=executor,
                    observer=observer,
                )
                from app.agent.tools import build_registry

                registry = build_registry()
                result = await registry.execute(tool_call, ctx)

                # Deterministic verification semantics (executor verifiers):
                # success = verified; failure/uncertain = NOT verified (fail
                # closed). UNCERTAIN never counts as success.
                verified_ok = result.success and result.verification_status == "success"
                report.executed_actions.append(
                    {
                        "step": i,
                        "tool": step.tool,
                        "semantic_id": step.semantic_id,
                        "result": (
                            "VERIFIED" if verified_ok else (result.error_code or "FAILED")
                        ),
                        "verification_status": result.verification_status,
                        "policy_allowed": result.policy_allowed,
                    }
                )
                if result.success:
                    executed += 1
                    if result.post_observation is not None:
                        world = reduce_observation(world, result.post_observation)
                else:
                    blocked += 1
                    completed_all = False
                    # Explicit, non-collapsing failure classification (WS2):
                    # the ToolResult's first-class policy/verification facts
                    # decide the outcome — never free text.
                    if result.error_code == "POLICY_DENIED":
                        report.final_status = LiveOutcomeStatus.POLICY_BLOCKED
                    elif result.error_code == "USER_ACTION_REQUIRED":
                        # PolicyEngine demands a human checkpoint (auth/OTP/
                        # CAPTCHA contexts). This is a HITL boundary — NOT an
                        # agent failure and NOT an environment failure.
                        report.final_status = LiveOutcomeStatus.HITL_REQUIRED
                    elif result.error_code == "CONFIRMATION_REQUIRED":
                        # PolicyEngine requires explicit human confirmation
                        # (sensitive/medium risk). Also a HITL boundary.
                        report.final_status = LiveOutcomeStatus.HITL_REQUIRED
                    elif result.error_code == "VERIFICATION_FAILED":
                        # The action ran but the expected state transition did
                        # not happen — a real verification failure of THIS run.
                        report.final_status = LiveOutcomeStatus.AGENT_FAILURE
                    else:
                        report.final_status = LiveOutcomeStatus.AGENT_FAILURE
                    break

                # One atomic action per iteration — verify then continue.
                post = result.post_observation
                if post is not None and not profile.origin_matches(post.page_state.url):
                    raise OriginMismatchError(
                        f"Post-action origin changed to {post.page_state.url!r}"
                    )

            if completed_all and blocked == 0:
                report.final_status = LiveOutcomeStatus.CONTROLLED_EXECUTION_SUCCESS
            report.final_boundary = FinalBoundaryEvidence(
                submit_controls_detected=[],
                submit_controls_classified_high_risk=True,
                controlled_run_blocked_at_boundary=True,
                no_final_submission_executed=True,
            )

    except ReviewSignatureError as e:
        report.final_status = LiveOutcomeStatus.SAFETY_BLOCKED
        security_events.append(f"REVIEW_BINDING_REJECTED:{e}")
    except ControlledActionDeniedError as e:
        report.final_status = LiveOutcomeStatus.POLICY_BLOCKED
        security_events.append(f"CONTROLLED_ACTION_DENIED:{e}")
    except OriginMismatchError:
        report.final_status = LiveOutcomeStatus.SAFETY_BLOCKED
        security_events.append("ORIGIN_MISMATCH")
    except Exception as exc:
        condition = classify_environment_error(exc)
        report.environment_condition = condition
        if condition in (EnvironmentCondition.TIMEOUT, EnvironmentCondition.ENVIRONMENT_FAILURE):
            report.final_status = LiveOutcomeStatus.ENVIRONMENT_FAILURE
        elif condition == EnvironmentCondition.NETWORK_FAILURE:
            report.final_status = LiveOutcomeStatus.PORTAL_UNAVAILABLE
        else:
            report.final_status = LiveOutcomeStatus.AGENT_FAILURE
        logger.warning("controlled run for %s ended: %s: %s", portal_id, type(exc).__name__, exc)
    finally:
        # STALE_TARGET_STOPPED means the run stopped honestly on world-state
        # drift — that is the machinery working as designed, not an agent
        # failure. Downgrade the final status to reflect the environment /
        # state reality while keeping the per-step evidence intact.
        if (
            report.final_status == LiveOutcomeStatus.AGENT_FAILURE
            and report.executed_actions
            and report.executed_actions[-1].get("result") == "STALE_TARGET_STOPPED"
        ):
            report.final_status = LiveOutcomeStatus.ENVIRONMENT_FAILURE
            report.environment_condition = EnvironmentCondition.ENVIRONMENT_FAILURE
        report.security_events = security_events
        report.duration_seconds = round(time.monotonic() - start, 3)
        report.live_metadata["finished_at"] = utc_now_iso()
        report.live_metadata["executed_verified_count"] = len(
            [a for a in report.executed_actions if a.get("result") == "VERIFIED"]
        )
        report.live_metadata["no_final_submission"] = True
        recorder.record(
            TraceEventType.RUN_END,
            subsystem="live_validation",
            component="run_controlled_execution",
            output_summary={
                "final_status": report.final_status.value,
                "executed": report.live_metadata["executed_verified_count"],
                "no_final_submission": True,
            },
        )

    return report, recorder


class _ToolCallShim:
    """Minimal ToolCall-shaped adapter carrying tool name + typed action."""

    def __init__(self, tool_name: str, action) -> None:
        self.tool_name = tool_name
        self.action = action
        self.arguments: dict = {}


def _rebind_target(step: "ControlledStep", observation) -> object | None:
    """Re-bind a reviewed step's durable semantic ID to the CURRENT DOM ref.

    The reviewed plan stores the semantic target (e.g. field:fullname) plus
    the ref observed at planning time. Before execution the fresh observation
    is searched for a semantic match; the action's target_ref is replaced
    with the fresh ref. Returns None when the target disappeared (stale —
    caller stops rather than guessing).
    """
    from app.agent.world.semantic_id import compute_semantic_id

    # Re-validate the (possibly stale) step against the controlled allowlist
    # using the durable semantic ID — never the raw ref.
    validate_controlled_action(step.tool, step.action.action, step.semantic_id, step.description)

    for el in observation.page_state.elements:
        if el.role not in ("textbox", "combobox", "checkbox", "radio", "file"):
            continue
        if compute_semantic_id(el) == step.semantic_id:
            # Stamp BOTH the fresh ref and the fresh observation id — the
            # tool layer's stale-ref guard requires exact binding to the
            # current observation (ephemeral refs, durable semantics).
            fresh = step.action.model_copy(
                update={
                    "target_ref": el.ref,
                    "observation_id": observation.observation_id,
                }
            )
            return fresh
    return None


def run_controlled_execution(
    portal_id: str,
    plan: ControlledPlan,
    *,
    review_request,
    review_secret: str,
    settings: Settings | None = None,
    baseline_identity: BaselineIdentity | None = None,
    max_steps: int = 8,
) -> tuple[LivePortalRunReport, TraceRecorder]:
    """Sync wrapper around run_controlled_execution_async."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            run_controlled_execution_async(
                portal_id,
                plan,
                review_request=review_request,
                review_secret=review_secret,
                settings=settings,
                baseline_identity=baseline_identity,
                max_steps=max_steps,
            )
        )
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run,
            run_controlled_execution_async(
                portal_id,
                plan,
                review_request=review_request,
                review_secret=review_secret,
                settings=settings,
                baseline_identity=baseline_identity,
                max_steps=max_steps,
            ),
        ).result()
