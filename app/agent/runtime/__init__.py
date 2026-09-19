"""Persistent agent runtime — Phase 2.

Public surface (implementation_plan.md Phase 2):

- AgentRunState / AgentLifecycle — durable run state + transition table
- AgentEvent / AgentEventLog — immutable append-only events with replay
- AgentDecision / AgentDecisionType — schema-validated decision contract
- AgentCheckpoint / CheckpointStore — run serialization/restoration
- AgentSession — persistent session envelope
- AgentRuntime — deterministic lifecycle orchestration
- RuntimeBackedAgentRunner — AgentRunner compatibility facade

Phase 2 implements these deterministically: no LLM loop (Phase 4), no
tool registry (Phase 3), no memory (Phase 9), no specialists (Phase 10).
"""

from app.agent.runtime.checkpoint import (
    CHECKPOINT_FORMAT_VERSION,
    AgentCheckpoint,
    CheckpointStore,
    InMemoryCheckpointStore,
)
from app.agent.runtime.decision import AgentDecision, AgentDecisionType
from app.agent.runtime.events import AgentEvent, AgentEventLog, AgentEventType
from app.agent.runtime.facade import RuntimeBackedAgentRunner
from app.agent.runtime.runtime import (
    AgentRuntime,
    InvalidLifecycleTransition,
    lifecycle_for_workflow_status,
)
from app.agent.runtime.session import AgentSession
from app.agent.runtime.state import (
    TERMINAL_LIFECYCLE_STATES,
    AgentIdentity,
    AgentLifecycle,
    AgentRunState,
    BrowserHandle,
    LIFECYCLE_TRANSITIONS,
    MemoryHandles,
    PendingInterrupt,
    UsageCounters,
    can_transition,
)

__all__ = [
    "CHECKPOINT_FORMAT_VERSION",
    "TERMINAL_LIFECYCLE_STATES",
    "AgentCheckpoint",
    "AgentDecision",
    "AgentDecisionType",
    "AgentEvent",
    "AgentEventLog",
    "AgentEventType",
    "AgentIdentity",
    "AgentLifecycle",
    "AgentRunState",
    "AgentRuntime",
    "AgentSession",
    "BrowserHandle",
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "InvalidLifecycleTransition",
    "LIFECYCLE_TRANSITIONS",
    "MemoryHandles",
    "PendingInterrupt",
    "RuntimeBackedAgentRunner",
    "UsageCounters",
    "can_transition",
    "lifecycle_for_workflow_status",
]
