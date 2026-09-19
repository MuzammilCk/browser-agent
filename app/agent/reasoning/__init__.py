"""Phase 4 reasoning loop — the LLM decision-making controller.

Boundary (docs/ARCHITECTURE_TARGET.md "Reasoner"):

    AgentRuntime
      ↓ minimal context assembler (context.py)
      ↓ DecisionModel protocol (protocol.py)
      ↓ structured decision JSON (ReasonerDecisionSchema)
      ↓ AgentReasoner parse + validate + bounded retries (reasoner.py)
      ↓ AgentDecision
      ↓ ToolRegistry → PolicyEngine → executor (Phases 1–3, unchanged)

Invariants encoded across this package:
- The model NEVER receives execution power, Playwright handles, paths,
  or raw secrets — only structured context and tool schemas.
- The model's output is DATA. It is schema-validated into an
  AgentDecision; ToolRegistry + PolicyEngine remain the only path to
  execution and stay authoritative over authorization.
- Malformed output is never silently retried into a guess: after bounded
  retries the reasoner returns an explicit MODEL_FAILURE ReasoningOutcome
  (AGENT_PROTOCOL.md "No silent fallback").
- Sensitive data crosses this boundary as semantic references
  (USER.full_name, DOCUMENT.aadhaar) — never raw values.
- The OpenRouter adapter (openrouter_model.py) is the only OpenRouter
  touchpoint; the reasoner itself is model-agnostic and tests run on the
  deterministic MockDecisionModel (no API key required).
"""

from app.agent.reasoning.context import (
    MAX_ELEMENTS,
    MAX_RECENT_RESULTS,
    MAX_VISIBLE_TEXT_CHARS,
    ReasoningContext,
    RUNTIME_CONSTRAINTS,
    build_reasoning_context,
)
from app.agent.reasoning.mock_model import MockDecisionModel
from app.agent.reasoning.openrouter_model import (
    InvalidModelOutput,
    OpenRouterDecisionModel,
    build_openrouter_decision_model,
)
from app.agent.reasoning.parser import parse_model_decision
from app.agent.reasoning.protocol import (
    DECISION_PARSE_FAILED,
    DECISION_SCHEMA_INVALID,
    DECISION_VALIDATION_FAILED,
    MODEL_FAILURE,
    MODEL_FAILURE_REASON_PREFIX,
    ALLOWED_DECISION_TYPES,
    DecisionModel,
    ReasonerDecisionSchema,
    ReasoningOutcome,
    ReasoningPhase,
    build_decision_json_schema,
    decision_to_tool_call,
)
from app.agent.reasoning.reasoner import AgentReasoner, ReasonerConfig

__all__ = [
    "ALLOWED_DECISION_TYPES",
    "AgentReasoner",
    "DECISION_PARSE_FAILED",
    "DECISION_SCHEMA_INVALID",
    "DECISION_VALIDATION_FAILED",
    "DecisionModel",
    "InvalidModelOutput",
    "MAX_ELEMENTS",
    "MAX_RECENT_RESULTS",
    "MAX_VISIBLE_TEXT_CHARS",
    "MODEL_FAILURE",
    "MODEL_FAILURE_REASON_PREFIX",
    "MockDecisionModel",
    "OpenRouterDecisionModel",
    "RUNTIME_CONSTRAINTS",
    "ReasonerConfig",
    "ReasonerDecisionSchema",
    "ReasoningContext",
    "ReasoningOutcome",
    "ReasoningPhase",
    "build_decision_json_schema",
    "build_openrouter_decision_model",
    "build_reasoning_context",
    "decision_to_tool_call",
    "parse_model_decision",
]
