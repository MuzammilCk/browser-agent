"""Policy engine — runtime safety gate for all browser actions.

Per audit issues #21, #22, #23, #24:
- Every action must pass through PolicyEngine before Playwright
- Risk levels: LOW, SENSITIVE, AUTHENTICATION, HIGH_RISK
- Policy decisions: ALLOW, DENY, REQUIRE_CONFIRMATION, PAUSE_FOR_USER
- CAPTCHA/OTP/password → PAUSE_FOR_USER
- Payment/final submission → REQUIRE_CONFIRMATION

Architecture:
    BrowserAction
        ↓
    schema validation
        ↓
    risk classification
        ↓
    PolicyEngine
        ↓
    ALLOW / DENY / REQUIRE_CONFIRMATION / PAUSE_FOR_USER
        ↓
    BrowserExecutor
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING

from app.agent.registry import ReferenceRegistry, ReferenceSensitivity, get_registry
from app.models.actions import BrowserAction
from app.models.page_state import AuthenticationState, PageState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk classification for browser actions.

    Per audit #22:
    LOW — safe automatic actions
    SENSITIVE — identity/financial fields, document upload
    AUTHENTICATION — password, OTP, CAPTCHA
    HIGH_RISK — payment, legal declaration, final submission
    """

    LOW = "low"
    SENSITIVE = "sensitive"
    AUTHENTICATION = "authentication"
    HIGH_RISK = "high_risk"


class PolicyDecision(str, Enum):
    """Outcome of a policy evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_CONFIRMATION = "require_confirmation"
    PAUSE_FOR_USER = "pause_for_user"


class PolicyResult:
    """Result of a policy evaluation for a single action."""

    def __init__(
        self,
        decision: PolicyDecision,
        risk_level: RiskLevel,
        reason: str = "",
        details: dict | None = None,
    ) -> None:
        self.decision = decision
        self.risk_level = risk_level
        self.reason = reason
        self.details = details or {}

    @property
    def allowed(self) -> bool:
        return self.decision == PolicyDecision.ALLOW

    @property
    def blocked(self) -> bool:
        return self.decision == PolicyDecision.DENY

    @property
    def needs_confirmation(self) -> bool:
        return self.decision == PolicyDecision.REQUIRE_CONFIRMATION

    @property
    def needs_user(self) -> bool:
        return self.decision == PolicyDecision.PAUSE_FOR_USER

    def __repr__(self) -> str:
        return (
            f"PolicyResult(decision={self.decision.value}, "
            f"risk={self.risk_level.value}, reason='{self.reason}')"
        )


# ============================================================
# Authentication keywords — per audit #23
# ============================================================

AUTH_KEYWORDS = {
    "password", "passwd", "pwd", "pin", "secret",
    "otp", "one time password", "verification code", "verify code",
    "captcha", "recaptcha", "human verification", "prove you are",
}

PAYMENT_KEYWORDS = {
    "payment", "pay now", "pay fee", "transaction", "razorpay",
    "paytm", "upi", "net banking", "credit card", "debit card",
    "bank transfer", "demand draft", "challan",
}

SUBMISSION_KEYWORDS = {
    "submit", "final submit", "confirm submission", "apply now",
    "complete application", "finalize", "declaration",
    "i declare", "i hereby declare", "terms and conditions",
}


def _classify_action_risk(
    action: BrowserAction,
    page_state: PageState | None = None,
    registry: ReferenceRegistry | None = None,
) -> RiskLevel:
    """Classify the risk level of a browser action.

    Per audit #22 risk levels.
    """
    reg = registry or get_registry()

    # HIGH_RISK actions — per audit #24
    if action.action in ("stop",):
        return RiskLevel.LOW

    if action.action == "request_user_action":
        # Already requesting user — this is safe
        return RiskLevel.LOW

    # Check action-specific risk

    # UPLOAD — always SENSITIVE (document handling)
    if action.action == "upload":
        if action.document_ref and reg.is_sensitive(action.document_ref):
            return RiskLevel.SENSITIVE
        return RiskLevel.SENSITIVE

    # FILL — check if the target is a sensitive field
    if action.action == "fill":
        if action.value_ref:
            if reg.is_sensitive(action.value_ref):
                return RiskLevel.SENSITIVE
        # Check page state for authentication context
        if page_state and page_state.authentication.detected:
            auth_type = page_state.authentication.challenge_type or ""
            if auth_type in ("otp", "captcha", "password", "login"):
                return RiskLevel.AUTHENTICATION

    # CLICK — check for payment/submission keywords
    if action.action == "click" and page_state:
        target = action.target_ref
        if target:
            for el in page_state.elements:
                if el.ref == target:
                    name = (el.accessible_name or "").lower()
                    # Check payment keywords
                    if any(kw in name for kw in PAYMENT_KEYWORDS):
                        return RiskLevel.HIGH_RISK
                    # Check submission keywords
                    if any(kw in name for kw in SUBMISSION_KEYWORDS):
                        return RiskLevel.HIGH_RISK

    # SELECT — generally LOW unless in auth context
    if action.action == "select":
        if page_state and page_state.authentication.detected:
            return RiskLevel.AUTHENTICATION
        return RiskLevel.LOW

    # CHECK/UNCHECK — generally LOW
    if action.action in ("check", "uncheck"):
        return RiskLevel.LOW

    # SCROLL, PRESS, GO_BACK, WAIT — LOW
    if action.action in ("scroll", "scroll_to", "press", "go_back", "wait"):
        return RiskLevel.LOW

    # Default to SENSITIVE for unknown combinations
    return RiskLevel.LOW


def _check_authentication_context(
    page_state: PageState,
) -> PolicyResult | None:
    """Check if the page is in an authentication challenge state.

    Per audit #23: CAPTCHA/OTP/password must be user checkpoints.
    """
    auth = page_state.authentication
    if not auth.detected:
        return None

    auth_type = auth.challenge_type or "unknown"

    if auth_type in ("captcha",):
        return PolicyResult(
            decision=PolicyDecision.PAUSE_FOR_USER,
            risk_level=RiskLevel.AUTHENTICATION,
            reason=f"CAPTCHA detected (confidence: {auth.confidence:.0%}). "
                   "User must complete CAPTCHA manually.",
        )

    if auth_type in ("otp",):
        return PolicyResult(
            decision=PolicyDecision.PAUSE_FOR_USER,
            risk_level=RiskLevel.AUTHENTICATION,
            reason=f"OTP challenge detected (confidence: {auth.confidence:.0%}). "
                   "User must enter OTP manually.",
        )

    if auth_type in ("password", "login"):
        return PolicyResult(
            decision=PolicyDecision.PAUSE_FOR_USER,
            risk_level=RiskLevel.AUTHENTICATION,
            reason=f"Authentication required (type: {auth_type}). "
                   "User must handle login manually.",
        )

    return None


class PolicyEngine:
    """Runtime safety gate for all browser actions.

    Every action must pass through this engine before reaching Playwright.
    """

    def __init__(self, registry: ReferenceRegistry | None = None) -> None:
        self._registry = registry or get_registry()

    def evaluate(
        self,
        action: BrowserAction,
        page_state: PageState | None = None,
    ) -> PolicyResult:
        """Evaluate a browser action against safety policy.

        Returns PolicyResult with decision and reason.
        """
        # Step 1: Check authentication context (per audit #23)
        if page_state:
            auth_result = _check_authentication_context(page_state)
            if auth_result:
                return auth_result

        # Step 2: Classify risk level (per audit #22)
        risk_level = _classify_action_risk(action, page_state, self._registry)

        # Step 3: Apply risk-based policy
        if risk_level == RiskLevel.HIGH_RISK:
            return PolicyResult(
                decision=PolicyDecision.REQUIRE_CONFIRMATION,
                risk_level=risk_level,
                reason=f"High-risk action: {action.action}. "
                       "User confirmation required.",
            )

        if risk_level == RiskLevel.AUTHENTICATION:
            return PolicyResult(
                decision=PolicyDecision.PAUSE_FOR_USER,
                risk_level=risk_level,
                reason=f"Authentication action: {action.action}. "
                       "User must handle this manually.",
            )

        if risk_level == RiskLevel.SENSITIVE:
            return PolicyResult(
                decision=PolicyDecision.REQUIRE_CONFIRMATION,
                risk_level=risk_level,
                reason=f"Sensitive action: {action.action}. "
                       "User confirmation recommended.",
            )

        # LOW risk — allow
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            risk_level=risk_level,
            reason=f"Low-risk action: {action.action}",
        )
