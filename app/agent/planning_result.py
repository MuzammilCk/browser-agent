"""Typed planning result — P0-13 contract.

``BrowserAction | None`` overloaded ``None`` to mean at least five things:
"genuinely done", "LLM errored", "LLM said stop", "LLM returned garbage",
and "no LLM was ever configured". These variants make each meaning
explicit so the runner can report honest workflow status instead of
collapsing every stall into READY_FOR_SUBMISSION.

Variants:
    ActionPlanned    — a concrete action to evaluate and execute.
    PlanLLMError     — the LLM call failed or returned a non-conforming /
                       unparseable response despite a schema being sent.
    NoValidAction    — the planner ran fine but found nothing to do.
    TaskComplete     — the planner believes the task is finished; only
                       honored on a success page by the runner.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.actions import BrowserAction


@dataclass(frozen=True)
class ActionPlanned:
    """Planner produced a concrete action."""

    action: BrowserAction


@dataclass(frozen=True)
class PlanLLMError:
    """LLM transport failure OR non-conforming/unparseable response.

    Never collapses into "no action" — surfaced verbatim in workflow state
    as WAITING_FOR_USER with the reason attached.
    """

    message: str


@dataclass(frozen=True)
class NoValidAction:
    """Planner ran fine but found nothing to do on this page.

    ``reason`` is the planner's own explanation (e.g. an LLM stop reason)
    for surfacing in checkpoints and workflow state.
    """

    reason: str


@dataclass(frozen=True)
class TaskComplete:
    """Planner believes the task is genuinely finished.

    The runner honors this only when the page is classified as a success
    page; elsewhere it is treated like NoValidAction.
    """

    reason: str


PlanOutcome = ActionPlanned | PlanLLMError | NoValidAction | TaskComplete
