"""Agent WorldState module — Phase 6.

Provides durable semantic WorldState independent from ephemeral DOM references.
"""

from __future__ import annotations

from app.agent.world.models import (
    AgentWorldState,
    AuthenticationWorldState,
    DocumentWorldState,
    EpistemicStatus,
    Provenance,
    SemanticField,
    TabWorldState,
)
from app.agent.world.reducer import (
    is_target_ref_valid,
    record_tool_result,
    record_verified_action,
    reduce_observation,
)
from app.agent.world.semantic_id import compute_semantic_id

__all__ = [
    "AgentWorldState",
    "AuthenticationWorldState",
    "DocumentWorldState",
    "EpistemicStatus",
    "Provenance",
    "SemanticField",
    "TabWorldState",
    "compute_semantic_id",
    "is_target_ref_valid",
    "record_tool_result",
    "record_verified_action",
    "reduce_observation",
]
