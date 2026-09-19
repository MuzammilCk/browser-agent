"""Phase 7 recovery subsystem — verification, reflection, and recovery.

Public exports:
- FailureType (the 13-type taxonomy)
- RecoveryStrategy
- FailureEvidence
- FailureClassification
- RecoveryBudget
- RecoveryDecision
- ReflectionResult
- RecoveryAttemptRecord
- FailureClassifier
- RecoveryReflector
- RecoveryManager
"""

from app.agent.recovery.classifier import FailureClassifier
from app.agent.recovery.manager import RecoveryManager
from app.agent.recovery.models import (
    FailureClassification,
    FailureEvidence,
    FailureType,
    RecoveryAttemptRecord,
    RecoveryBudget,
    RecoveryDecision,
    RecoveryStrategy,
    ReflectionResult,
)
from app.agent.recovery.reflector import RecoveryReflector

__all__ = [
    "FailureType",
    "RecoveryStrategy",
    "FailureEvidence",
    "FailureClassification",
    "RecoveryBudget",
    "RecoveryDecision",
    "ReflectionResult",
    "RecoveryAttemptRecord",
    "FailureClassifier",
    "RecoveryReflector",
    "RecoveryManager",
]
