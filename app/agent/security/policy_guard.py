"""Policy & Origin Security Guard — Phase 11 Security Hardening.

Key Architectural Invariants:
1. Structural secret handling first:
   - Elements with input_type == 'password' or sensitive field roles are RESTRICTED_SECRET.
2. Webpage DOM attributes are non-authoritative:
   - Injected labels, data-* attributes (e.g. data-risk="low", data-preapproved="true"),
     or page text claims cannot downgrade risk or bypass policy.
3. Domain security & redirect checks:
   - Navigations and redirects to untrusted external domains are blocked fail-closed.
4. Schema strictness:
   - Tool arguments reject forbidden / unknown parameters fail-closed.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from typing import Any

from app.agent.security.models import (
    SecurityViolation,
    SecurityViolationCode,
    SensitivityLevel,
    TrustDomain,
)
from app.models.actions import BrowserAction
from app.models.page_state import ElementState, PageState

logger = logging.getLogger(__name__)

# Canonical trusted domains for Indian government portals
DEFAULT_ALLOWED_DOMAINS = frozenset({
    "gov.in",
    "nic.in",
    "pmkisan.gov.in",
    "uidai.gov.in",
    "incometax.gov.in",
    "epfindia.gov.in",
    "parivahan.gov.in",
    "passportindia.gov.in",
    "localhost",
    "127.0.0.1",
})


def is_trusted_domain(url: str, allowed_domains: set[str] | frozenset[str] | None = None) -> bool:
    """Check if URL host matches or is a subdomain of an allowed trusted domain."""
    if not url:
        return False
    if url.startswith("file://"):
        return True  # Local file URLs (synthetic testing)

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False

    allowed = allowed_domains or DEFAULT_ALLOWED_DOMAINS
    for domain in allowed:
        if host == domain or host.endswith(f".{domain}"):
            return True
    return False


def validate_navigation_destination(
    target_url: str,
    allowed_domains: set[str] | frozenset[str] | None = None,
) -> None:
    """Verify that a proposed navigation or redirect target is a trusted domain.
    
    Raises SecurityViolation(UNAUTHORIZED_REDIRECT) if untrusted.
    """
    if not is_trusted_domain(target_url, allowed_domains):
        raise SecurityViolation(
            SecurityViolationCode.UNAUTHORIZED_REDIRECT,
            f"Navigation target '{target_url}' is not a trusted government domain.",
            {"target_url": target_url},
        )


class PolicyIntegrityGuard:
    """Ensures deterministic policy evaluation cannot be influenced by adversarial web claims."""

    @staticmethod
    def sanitize_action_for_policy(action: BrowserAction) -> None:
        """Verify action does not attempt to smuggle forbidden bypass arguments."""
        # Check action dictionary representation for injected bypass flags
        d = action.model_dump()
        forbidden_keys = {
            "pre_approved", "bypass_policy", "skip_confirmation",
            "admin_override", "force_execute", "elevated_privilege",
        }
        found_forbidden = [k for k in forbidden_keys if d.get(k) is not None]
        if found_forbidden:
            raise SecurityViolation(
                SecurityViolationCode.FORBIDDEN_PARAMETER_INJECTION,
                f"Action contains forbidden bypass parameter(s): {found_forbidden}",
                {"forbidden_keys": found_forbidden},
            )

    @staticmethod
    def classify_element_sensitivity(element: ElementState) -> SensitivityLevel:
        """Structural / field-based classification first.
        
        Passwords, OTPs, PINs, and auth challenge elements are RESTRICTED_SECRET.
        """
        input_type = (element.input_type or "").lower()
        role = (element.role or "").lower()
        html_name = (element.html_name or "").lower()
        name = (element.accessible_name or element.name or "").lower()

        # Structural check 1: password input type
        if input_type == "password":
            return SensitivityLevel.RESTRICTED_SECRET

        # Structural check 2: explicit OTP / PIN in html_name or id
        if any(token in html_name for token in ("otp", "pin", "password", "passwd", "secret")):
            return SensitivityLevel.RESTRICTED_SECRET

        # Content-based check (defense-in-depth only)
        if any(token in name for token in ("one time password", "verification code")):
            return SensitivityLevel.RESTRICTED_SECRET

        return SensitivityLevel.PUBLIC
