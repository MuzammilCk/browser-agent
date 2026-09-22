"""Base verification types and shared helpers.

Extracted from verification.py per software-architecture skill.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.page_state import ElementState, PageState

logger = logging.getLogger(__name__)


class VerificationStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNCERTAIN = "uncertain"


@dataclass
class VerificationResult:
    """Result of a post-action verification."""

    status: VerificationStatus
    action_type: str
    target_ref: str | None = None
    expected: str | None = None
    actual: str | None = None
    message: str = ""
    page_changed: bool = False
    validation_errors: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def describe_value_mismatch(
    expected: str, actual: str | None, subject: str = "Filled value",
) -> str:
    """Shape-only description of a fill-value mismatch — never echoes values.

    Secret-safety (Phase 15 H1): the expected value may be a vault-resolved
    credential and the live value is page-controlled, so neither may be
    formatted into a message that reaches the model, traces, or audit records
    (AGENTS.md rule 6, docs/SECURITY_MODEL.md). Only lengths are reported.
    """
    expected_len = len(expected.strip())
    if actual is None:
        actual_desc = "unreadable"
    else:
        actual_desc = f"{len(actual.strip())} chars"
    return (
        f"{subject} did not stick: expected value "
        f"({expected_len} chars) != live value ({actual_desc}); "
        "values withheld for secret safety"
    )


def find_element(ref: str, state: PageState) -> ElementState | None:
    """Find element by ref in PageState."""
    for el in state.elements:
        if el.ref == ref:
            return el
    return None


def make_success(
    action_type: str, ref: str | None = None, message: str = "",
    page_changed: bool = False, details: dict | None = None,
) -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.SUCCESS, action_type=action_type,
        target_ref=ref, message=message, page_changed=page_changed,
        details=details or {},
    )


def make_failure(
    action_type: str, ref: str | None = None, message: str = "",
    expected: str | None = None, actual: str | None = None,
    validation_errors: list[str] | None = None,
) -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.FAILURE, action_type=action_type,
        target_ref=ref, expected=expected, actual=actual,
        message=message, validation_errors=validation_errors or [],
    )


def make_uncertain(
    action_type: str, ref: str | None = None, message: str = "",
) -> VerificationResult:
    return VerificationResult(
        status=VerificationStatus.UNCERTAIN, action_type=action_type,
        target_ref=ref, message=message,
    )
