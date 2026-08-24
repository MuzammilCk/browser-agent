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
