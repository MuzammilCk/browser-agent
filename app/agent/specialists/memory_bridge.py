"""Memory bridge for Phase 10 specialist agents.

Rule 7: MEMORY BOUNDARY
- SpecialistResult -> MemoryCandidate -> MemoryWritePolicy -> MemoryStore
- Never: Specialist -> MemoryStore
- Never trust specialist claims of VERIFIED state.
- Memory writes must retain specialist provenance.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.memory.models import (
    AuthorType,
    EpistemicStatus,
    MemoryCandidate,
    MemoryProvenance,
    MemoryType,
)
from app.agent.memory.policy import MemoryWritePolicy, PolicyVerdict
from app.agent.memory.store import MemoryStore
from app.agent.specialists.models import SpecialistResult

logger = logging.getLogger(__name__)


def create_memory_candidate_from_specialist(
    specialist_result: SpecialistResult,
    *,
    subject: str,
    predicate: str,
    value: Any,
    memory_type: MemoryType = MemoryType.SEMANTIC,
    portal: str = "",
    user_session_id: str = "",
    state_version: int = 0,
) -> MemoryCandidate:
    """Transform a SpecialistResult into a gated MemoryCandidate.

    CRITICAL INVARIANTS:
    - AuthorType is ALWAYS AuthorType.MODEL_INFERRED (never RUNTIME_VERIFIED or USER_EXPLICIT).
    - Proposed epistemic status is ALWAYS EpistemicStatus.INFERRED (never VERIFIED).
    - Specialist claims of VERIFIED status are explicitly downgraded/rejected.
    - Provenance retains specialist type, invocation ID, confidence, and evidence.
    """
    provenance = MemoryProvenance(
        source=f"specialist:{specialist_result.specialist_type.value}",
        author_type=AuthorType.MODEL_INFERRED,
        run_id=specialist_result.parent_run_id,
        observation_id="",
        tool_name=f"call_{specialist_result.specialist_type.value}",
        state_version=state_version,
        details={
            "invocation_id": specialist_result.invocation_id,
            "specialist_type": specialist_result.specialist_type.value,
            "permission": specialist_result.permission.value,
            "confidence": specialist_result.confidence,
            "evidence": specialist_result.evidence[:5],
        },
    )

    candidate = MemoryCandidate(
        memory_type=memory_type,
        portal=portal,
        subject=subject,
        predicate=predicate,
        value=value,
        user_session_id=user_session_id,
        author_type=AuthorType.MODEL_INFERRED,
        source=f"specialist:{specialist_result.specialist_type.value}",
        # INVIOLABLE: A specialist can never propose VERIFIED status (Rule 6, 7)
        proposed_status=EpistemicStatus.INFERRED,
        confidence=min(specialist_result.confidence, 0.85),  # Cautious confidence cap
        run_id=specialist_result.parent_run_id,
        details={
            "invocation_id": specialist_result.invocation_id,
            "specialist_type": specialist_result.specialist_type.value,
            "permission": specialist_result.permission.value,
            "confidence": specialist_result.confidence,
            "evidence": specialist_result.evidence[:5],
        },
    )

    return candidate


async def write_specialist_memory(
    specialist_result: SpecialistResult,
    *,
    subject: str,
    predicate: str,
    value: Any,
    memory_store: MemoryStore,
    write_policy: MemoryWritePolicy | None = None,
    portal: str = "",
    user_session_id: str = "",
    state_version: int = 0,
) -> tuple[bool, str]:
    """Route specialist memory candidate through MemoryWritePolicy before storing.

    Enforces the pipeline:
    SpecialistResult -> MemoryCandidate -> MemoryWritePolicy -> MemoryStore

    Returns (persisted: bool, reason: str).
    """
    policy = write_policy or MemoryWritePolicy()
    candidate = create_memory_candidate_from_specialist(
        specialist_result,
        subject=subject,
        predicate=predicate,
        value=value,
        portal=portal,
        user_session_id=user_session_id,
        state_version=state_version,
    )

    # 1. Authoritative policy evaluation
    decision = policy.evaluate(candidate)
    if not decision.allowed:
        logger.warning(
            "MemoryWritePolicy rejected specialist candidate [%s]: %s (%s)",
            candidate.subject,
            decision.reason,
            decision.rejection_code,
        )
        return False, f"Policy rejected: {decision.reason} ({decision.rejection_code})"

    # 2. Write to store with verified Inferred status
    try:
        from app.agent.memory.models import SemanticMemoryItem

        prov = MemoryProvenance(
            source=candidate.source,
            author_type=candidate.author_type,
            run_id=candidate.run_id,
            observation_id=candidate.observation_id,
            tool_name=f"call_{specialist_result.specialist_type.value}",
            state_version=state_version,
            details=candidate.details,
        )
        item = SemanticMemoryItem(
            subject=candidate.subject,
            predicate=candidate.predicate,
            value=candidate.value,
            portal=candidate.portal,
            user_session_id=candidate.user_session_id,
            confidence=candidate.confidence,
            epistemic_status=EpistemicStatus.INFERRED,
            provenance=prov,
        )
        await memory_store.create_semantic_memory(item)
        return True, "Stored successfully as INFERRED semantic memory"
    except Exception as e:
        logger.exception("Failed to persist specialist memory candidate: %s", e)
        return False, f"Storage error: {e}"
