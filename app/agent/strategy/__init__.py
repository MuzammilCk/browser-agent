"""Phase 5 strategic planning — Goal / Plan / Subgoal.

Strategic state ABOVE the action loop (implementation_plan.md Phase 5):

    AgentGoal (what the user wants + testable success criteria)
      ↓
    AgentPlan (versioned ordered subgoals + dependencies + revisions)
      ↓
    Subgoal (explicit lifecycle, evidence-based completion)
      ↓
    AgentReasoner (Phase 4 — decides the NEXT ACTION, unchanged)
      ↓
    ToolRegistry → executor (Phases 1–3, unchanged)

Separation of concerns (user instruction, Phase 5):
- Goal/Plan/Subgoal are STRATEGIC STATE — serializable data, no execution.
- AgentReasoner stays the tactical decision-maker (chooses next action).
- Browser observation remains the source of truth.
- PolicyEngine remains the authoritative safety boundary.
- The final-submission boundary is EXPLICIT in the plan: the boundary
  subgoal cannot be activated, auto-completed, or revised by the
  manager (FinalSubmissionGate), and the reasoner's runtime constraints
  (Phase 4) still gate the action itself — planning never authorizes
  submission.
- WorldState redesign is Phase 6; Snapshot is a thin projection only.
"""

from app.agent.strategy.criteria import (
    CriterionOutcome,
    Snapshot,
    criteria_verdict,
    evaluate_criteria,
)
from app.agent.strategy.goal_parser import ParsedGoal, parse_goal
from app.agent.strategy.manager import (
    RevisionResult,
    SUBGOAL_TRANSITIONS,
    TransitionOutcome,
    AgentPlanManager,
)
from app.agent.strategy.models import (
    AgentGoal,
    AgentPlan,
    FinalSubmissionGate,
    IllegalSubgoalTransition,
    PlanInvalid,
    PlanRevision,
    Subgoal,
    SubgoalNotFound,
    SubgoalStatus,
    SubgoalStatusReason,
    SuccessCriterion,
)
from app.agent.strategy.plan_builder import build_initial_plan

__all__ = [
    "SUBGOAL_TRANSITIONS",
    "AgentGoal",
    "AgentPlan",
    "AgentPlanManager",
    "CriterionOutcome",
    "FinalSubmissionGate",
    "IllegalSubgoalTransition",
    "ParsedGoal",
    "PlanInvalid",
    "PlanRevision",
    "RevisionResult",
    "Snapshot",
    "Subgoal",
    "SubgoalNotFound",
    "SubgoalStatus",
    "SubgoalStatusReason",
    "SuccessCriterion",
    "TransitionOutcome",
    "build_initial_plan",
    "criteria_verdict",
    "evaluate_criteria",
    "parse_goal",
]
