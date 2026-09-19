"""Specialist agents package — Phase 10 (Restricted Specialist Agents / Subagents).

Exports models, registry, base classes, implementations, tool adapters, and memory bridge.
"""

from __future__ import annotations

from app.agent.specialists.adapter import (
    CallSpecialistInput,
    CallSpecialistTool,
    SpecialistToolAdapter,
    SpecialistToolOutputPayload,
    register_specialists_in_tool_registry,
)
from app.agent.specialists.base import (
    SpecialistAgent,
    SpecialistAuditLog,
    get_specialist_audit_log,
)
from app.agent.specialists.context_builder import build_specialist_context
from app.agent.specialists.implementations import (
    DocumentAgent,
    DocumentSpecialistInput,
    FormSemanticsAgent,
    FormSemanticsInput,
    PortalResearchAgent,
    PortalResearchInput,
    RecoveryAgent,
    RecoverySpecialistInput,
    VerificationAgent,
    VerificationSpecialistInput,
)
from app.agent.specialists.memory_bridge import (
    create_memory_candidate_from_specialist,
    write_specialist_memory,
)
from app.agent.specialists.models import (
    DocumentMetadataProjection,
    DocumentSpecialistOutput,
    ElementSummaryProjection,
    FailureEvidenceProjection,
    FieldSemanticInfo,
    FormSemanticsOutput,
    MatchedDocumentInfo,
    MemorySummaryProjection,
    PageObservationProjection,
    PortalResearchOutput,
    RecoverySpecialistOutput,
    ResultKind,
    SpecialistAuditRecord,
    SpecialistContext,
    SpecialistOutcome,
    SpecialistPermission,
    SpecialistResult,
    SpecialistType,
    VerificationSpecialistOutput,
    WorldStateProjection,
)
from app.agent.specialists.registry import (
    SpecialistRegistry,
    get_specialist_registry,
)

__all__ = [
    # Models
    "SpecialistPermission",
    "SpecialistType",
    "ResultKind",
    "SpecialistOutcome",
    "ElementSummaryProjection",
    "PageObservationProjection",
    "WorldStateProjection",
    "FailureEvidenceProjection",
    "DocumentMetadataProjection",
    "MemorySummaryProjection",
    "SpecialistContext",
    "PortalResearchOutput",
    "FieldSemanticInfo",
    "FormSemanticsOutput",
    "MatchedDocumentInfo",
    "DocumentSpecialistOutput",
    "RecoverySpecialistOutput",
    "VerificationSpecialistOutput",
    "SpecialistResult",
    "SpecialistAuditRecord",
    # Registry
    "SpecialistRegistry",
    "get_specialist_registry",
    # Base
    "SpecialistAgent",
    "SpecialistAuditLog",
    "get_specialist_audit_log",
    # Context builder
    "build_specialist_context",
    # Implementations
    "PortalResearchAgent",
    "PortalResearchInput",
    "FormSemanticsAgent",
    "FormSemanticsInput",
    "DocumentAgent",
    "DocumentSpecialistInput",
    "RecoveryAgent",
    "RecoverySpecialistInput",
    "VerificationAgent",
    "VerificationSpecialistInput",
    # Adapter
    "SpecialistToolAdapter",
    "SpecialistToolOutputPayload",
    "CallSpecialistInput",
    "CallSpecialistTool",
    "register_specialists_in_tool_registry",
    # Memory bridge
    "create_memory_candidate_from_specialist",
    "write_specialist_memory",
]
