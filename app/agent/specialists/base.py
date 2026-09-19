"""SpecialistAgent base contract and audit logging — Phase 10.

CRITICAL INVARIANTS:
1. Specialists are ADVISORS, never authorities (Rule 1).
2. Specialists cannot mutate browser state or access BrowserExecutor (Rule 1, 3).
3. Every specialist invocation is strictly bounded by timeout and cancellation (Rule 11).
4. Specialist failures are isolated from the main runtime (Rule 11).
5. All invocations are recorded in the audit trail without secrets (Rule 11).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.specialists.models import (
    ResultKind,
    SpecialistAuditRecord,
    SpecialistContext,
    SpecialistOutcome,
    SpecialistPermission,
    SpecialistResult,
    SpecialistType,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Audit Log (Rule 11, 12)
# ==============================================================================


class SpecialistAuditLog:
    """Thread-safe append-only audit trail for specialist invocations."""

    def __init__(self) -> None:
        self._records: list[SpecialistAuditRecord] = []
        self._lock = threading.RLock()

    def record(self, record: SpecialistAuditRecord) -> None:
        """Record a completed, failed, or cancelled specialist invocation."""
        with self._lock:
            self._records.append(record)
            logger.debug(
                "Specialist audit [%s] %s outcome=%s duration=%.1fms",
                record.invocation_id,
                record.specialist_type,
                record.outcome,
                record.duration_ms,
            )

    def get_records(
        self,
        parent_run_id: str | None = None,
        specialist_type: SpecialistType | str | None = None,
    ) -> list[SpecialistAuditRecord]:
        """Retrieve audit records matching filter criteria."""
        with self._lock:
            records = list(self._records)

        if parent_run_id is not None:
            records = [r for r in records if r.parent_run_id == parent_run_id]

        if specialist_type is not None:
            stype = (
                specialist_type.value
                if isinstance(specialist_type, SpecialistType)
                else str(specialist_type)
            )
            records = [r for r in records if r.specialist_type == stype]

        return records

    def clear(self) -> None:
        """Clear all audit records (primarily for testing)."""
        with self._lock:
            self._records.clear()


# Global audit log
_GLOBAL_AUDIT_LOG: SpecialistAuditLog | None = None
_AUDIT_LOCK = threading.RLock()


def get_specialist_audit_log() -> SpecialistAuditLog:
    """Get or initialize global specialist audit log."""
    global _GLOBAL_AUDIT_LOG
    with _AUDIT_LOCK:
        if _GLOBAL_AUDIT_LOG is None:
            _GLOBAL_AUDIT_LOG = SpecialistAuditLog()
        return _GLOBAL_AUDIT_LOG


# ==============================================================================
# SpecialistAgent Base Class
# ==============================================================================


class SpecialistAgent(ABC):
    """Base contract for isolated specialist agents.

    Subclasses define:
    - specialist_type: SpecialistType
    - permission: SpecialistPermission (fixed, immutable)
    - default_timeout: float
    - input_schema: type[BaseModel]
    - output_schema: type[BaseModel]

    And implement:
    - _run(context: SpecialistContext) -> SpecialistResult
    """

    specialist_type: SpecialistType
    permission: SpecialistPermission
    default_timeout: float = 10.0
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    def __init__(self, audit_log: SpecialistAuditLog | None = None) -> None:
        self.audit_log = audit_log or get_specialist_audit_log()

    async def execute(self, context: SpecialistContext) -> SpecialistResult:
        """Execute the specialist agent within its isolated context.

        Template method:
        1. Validates permissions match between context and implementation.
        2. Validates parameters against input_schema.
        3. Enforces bounded timeout and cancellation with child cleanup.
        4. Validates output payload against output_schema.
        5. Checks for permission escalation attempts.
        6. Records sanitized audit record.
        7. Catches internal failures to keep main runtime isolated.
        """
        start_time = time.monotonic()
        started_at = utc_now_iso()
        timeout = context.timeout_seconds or self.default_timeout

        # 1. Authoritative permission check (Rule 5)
        if context.permission != self.permission:
            ended_at = utc_now_iso()
            duration_ms = (time.monotonic() - start_time) * 1000.0
            error_msg = (
                f"Permission mismatch: context specifies '{context.permission.value}' "
                f"but specialist '{self.specialist_type.value}' requires '{self.permission.value}'"
            )
            self._record_audit(
                context,
                outcome=SpecialistOutcome.VALIDATION_FAILED,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary="Permission mismatch",
                error=error_msg,
            )
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.VALIDATION_FAILED,
                error_code="PERMISSION_MISMATCH",
                error_message=error_msg,
            )

        # 2. Input validation
        try:
            self.input_schema.model_validate(context.parameters)
        except ValidationError as ve:
            ended_at = utc_now_iso()
            duration_ms = (time.monotonic() - start_time) * 1000.0
            error_msg = f"Specialist input parameters failed schema validation: {ve}"
            self._record_audit(
                context,
                outcome=SpecialistOutcome.VALIDATION_FAILED,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary="Input schema validation failed",
                error=error_msg,
            )
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.VALIDATION_FAILED,
                error_code="INPUT_SCHEMA_INVALID",
                error_message=error_msg,
            )

        # 3. Execution with bounded timeout & cancellation (Rule 11)
        child_task = asyncio.create_task(self._run(context))
        try:
            result = await asyncio.wait_for(asyncio.shield(child_task), timeout=timeout)
        except asyncio.TimeoutError:
            # Cancel child task and await termination
            child_task.cancel()
            try:
                await child_task
            except (asyncio.CancelledError, Exception):
                pass

            await self._cleanup(context)
            ended_at = utc_now_iso()
            duration_ms = (time.monotonic() - start_time) * 1000.0
            error_msg = f"Specialist '{self.specialist_type.value}' timed out after {timeout:.1f}s"
            self._record_audit(
                context,
                outcome=SpecialistOutcome.TIMEOUT,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary="Execution timed out",
                error=error_msg,
                timeout_or_cancelled=True,
            )
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.TIMEOUT,
                error_code="SPECIALIST_TIMEOUT",
                error_message=error_msg,
            )
        except asyncio.CancelledError:
            child_task.cancel()
            try:
                await child_task
            except (asyncio.CancelledError, Exception):
                pass

            await self._cleanup(context)
            ended_at = utc_now_iso()
            duration_ms = (time.monotonic() - start_time) * 1000.0
            error_msg = f"Specialist '{self.specialist_type.value}' was cancelled"
            self._record_audit(
                context,
                outcome=SpecialistOutcome.CANCELLED,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary="Execution cancelled",
                error=error_msg,
                timeout_or_cancelled=True,
            )
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.CANCELLED,
                error_code="SPECIALIST_CANCELLED",
                error_message=error_msg,
            )
        except Exception as ex:
            await self._cleanup(context)
            ended_at = utc_now_iso()
            duration_ms = (time.monotonic() - start_time) * 1000.0
            error_msg = f"Specialist execution error: {type(ex).__name__}: {ex}"
            logger.exception("Specialist %s execution failed", self.specialist_type.value)
            self._record_audit(
                context,
                outcome=SpecialistOutcome.FAILURE,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary="Execution failed",
                error=error_msg,
            )
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.FAILURE,
                error_code="SPECIALIST_EXECUTION_ERROR",
                error_message=error_msg,
            )

        # 4. Output validation against declared output_schema
        try:
            self.output_schema.model_validate(result.data)
        except ValidationError as ve:
            await self._cleanup(context)
            ended_at = utc_now_iso()
            duration_ms = (time.monotonic() - start_time) * 1000.0
            error_msg = f"Specialist output payload violated output schema: {ve}"
            self._record_audit(
                context,
                outcome=SpecialistOutcome.VALIDATION_FAILED,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary="Output schema validation failed",
                error=error_msg,
            )
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.VALIDATION_FAILED,
                error_code="OUTPUT_SCHEMA_INVALID",
                error_message=error_msg,
            )

        # 5. Security & escalation check (handled by SpecialistResult model_validator)
        try:
            # Re-validate result container to trigger security checks
            result = SpecialistResult.model_validate(result.model_dump())
        except (ValueError, ValidationError) as ve:
            await self._cleanup(context)
            ended_at = utc_now_iso()
            duration_ms = (time.monotonic() - start_time) * 1000.0
            error_msg = f"Security check failed: {ve}"
            self._record_audit(
                context,
                outcome=SpecialistOutcome.ESCALATION_BLOCKED,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                summary="Escalation attempt blocked",
                error=error_msg,
            )
            return SpecialistResult(
                result_kind=ResultKind.SPECIALIST_ANALYSIS,
                invocation_id=context.invocation_id,
                parent_run_id=context.parent_run_id,
                specialist_type=self.specialist_type,
                permission=self.permission,
                outcome=SpecialistOutcome.ESCALATION_BLOCKED,
                error_code="PERMISSION_ESCALATION_BLOCKED",
                error_message=error_msg,
            )

        # Clean up resources
        await self._cleanup(context)

        ended_at = utc_now_iso()
        duration_ms = (time.monotonic() - start_time) * 1000.0

        # 6. Audit recording
        summary = (
            f"Analyzed {len(result.evidence)} evidence items, "
            f"{len(result.ambiguities)} ambiguities"
        )
        self._record_audit(
            context,
            outcome=result.outcome,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            summary=summary,
        )

        return result

    @abstractmethod
    async def _run(self, context: SpecialistContext) -> SpecialistResult:
        """Implement the specialist's isolated analysis logic."""

    async def _cleanup(self, context: SpecialistContext) -> None:
        """Clean up any child resources. Subclasses may override."""

    def _record_audit(
        self,
        context: SpecialistContext,
        outcome: SpecialistOutcome,
        started_at: str,
        ended_at: str,
        duration_ms: float,
        summary: str,
        error: str | None = None,
        timeout_or_cancelled: bool = False,
    ) -> None:
        """Construct and persist an immutable audit record."""
        # Safe input scope summary (no secrets or raw bytes)
        scope_summary = {
            "has_observation": context.observation_projection is not None,
            "has_world_state": context.world_state_projection is not None,
            "has_failure_evidence": context.failure_evidence is not None,
            "doc_metadata_count": len(context.document_metadata),
            "memory_items_count": len(context.memory_projections),
            "param_keys": list(context.parameters.keys()),
        }

        record = SpecialistAuditRecord(
            parent_run_id=context.parent_run_id,
            invocation_id=context.invocation_id,
            specialist_type=self.specialist_type.value,
            permission=self.permission.value,
            outcome=outcome.value,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            timeout_or_cancelled=timeout_or_cancelled,
            result_summary=summary,
            error_message=error,
            input_scope_summary=scope_summary,
        )
        self.audit_log.record(record)
