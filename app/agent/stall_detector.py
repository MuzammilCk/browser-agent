"""Repeated-identical-action stall detector — audit Phase 9.

`max_iterations` used to be the only backstop against a loop that keeps
doing the same thing. But "ran out of iterations" and "the last 3 actions
produced no change" are diagnostically different, and they read completely
differently in a log: the first sends a human hunting, the second names the
problem. This module makes "the agent is repeating itself" a first-class,
named signal instead of a silent multi-minute stall.

What counts as "the same thing" is a small tuple, per the audit:

    (page_type, url, action.target_ref, action.action_type)

plus a lightweight fingerprint of the observable page, so a repeat only
counts when the page state is *otherwise unchanged*. Anything that actually
moved — a new element, a changed value, a new alert, a new tab — resets the
counter, because that is progress even if the next action looks the same.

This is a backstop for whatever edge case produces the pattern, not only
for the tab duplication bug of Phase 8.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.models.actions import BrowserAction
from app.models.page_state import PageObservation

# Identical, no-progress repeats tolerated before halting. The halt fires
# when the same tuple comes up again after this many executions — i.e.
# "the last 3 actions produced no change, refuse to do it a 4th time".
REPEATED_ACTION_LIMIT = 3

# Distinct, greppable label. Not a generic max-iteration failure.
STALL_REASON_REPEATED_ACTION = "repeated_action_no_progress"


def page_fingerprint(observation: PageObservation) -> str:
    """Short hash of the page's observable state.

    Deliberately cheap and structural: refs, roles, names, values, checked
    and disabled state of every element, plus alert/validation counts and
    the number of open tabs. Screenshots and free text are excluded — this
    answers "did anything we can act on change?", nothing more.
    """
    page_state = observation.page_state
    parts: list[str] = [
        page_state.url,
        page_state.page_type,
        f"tabs={page_state.tabs.total}",
        f"alerts={len(page_state.alerts)}",
        f"validations={len(page_state.validation_errors)}",
    ]
    for el in page_state.elements:
        parts.append(
            "|".join([
                el.ref or "",
                el.role or "",
                el.accessible_name or el.label_text or "",
                el.value or "",
                str(el.checked),
                str(el.disabled),
                str(el.visible),
                ",".join(el.selected_options),
            ])
        )
    for err in page_state.validation_errors:
        parts.append(f"err:{err.target_ref}:{err.message}")
    digest = hashlib.sha256("\n".join(parts).encode("utf-8", "replace")).hexdigest()
    return digest[:16]


@dataclass(frozen=True)
class ActionSignature:
    """The identity of "this action, on this page, in this state"."""

    page_type: str
    url: str
    target_ref: str
    action_type: str
    fingerprint: str

    @property
    def key(self) -> str:
        return "|".join([
            self.action_type, self.target_ref, self.page_type,
            self.url, self.fingerprint,
        ])

    def describe(self) -> str:
        target = self.target_ref or "(no target)"
        return (
            f"{self.action_type} on {target} at {self.url} "
            f"(page_type={self.page_type})"
        )


def build_signature(
    observation: PageObservation, action: BrowserAction,
) -> ActionSignature:
    """Signature of an action about to be executed against an observation."""
    return ActionSignature(
        page_type=observation.page_state.page_type,
        url=observation.page_state.url,
        target_ref=action.target_ref or "",
        action_type=action.action,
        fingerprint=page_fingerprint(observation),
    )


@dataclass(frozen=True)
class StallVerdict:
    """Outcome of the repeat check for one planned action."""

    key: str
    repeat_count: int
    halt: bool
    reason: str = ""

    @property
    def stall_reason(self) -> str | None:
        return STALL_REASON_REPEATED_ACTION if self.halt else None


def evaluate_repeat(
    signature: ActionSignature,
    previous_key: str,
    previous_count: int,
    *,
    limit: int = REPEATED_ACTION_LIMIT,
) -> StallVerdict:
    """Count consecutive identical (page-state, action) tuples.

    Pure function of the previous signature and its count so the runner
    keeps the state in WorkflowState and this stays trivially testable.
    """
    key = signature.key
    count = previous_count + 1 if key == previous_key else 1

    if count > limit:
        return StallVerdict(
            key=key,
            repeat_count=count,
            halt=True,
            reason=(
                f"The last {limit} actions produced no change: "
                f"{signature.describe()} was already executed {limit} times "
                f"and the page state is unchanged. Halting instead of "
                f"repeating it — manual attention needed."
            ),
        )

    return StallVerdict(key=key, repeat_count=count, halt=False)
