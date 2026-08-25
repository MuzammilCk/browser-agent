"""Sensitive field classification.

Audit C12: FIELD_SENSITIVITY used to be a second, hardcoded copy of the
sensitivity data already in ``ReferenceRegistry`` — exactly the
dual-source-of-truth drift the remediation spec (issue #37) warned about.
All classification now derives lazily from the registry.

Per SAFETY.md and context.md:
- R2 (sensitive) fields require stronger validation
- Government IDs, financial data, health info are sensitive
- The LLM should NOT receive raw sensitive values
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache


class SensitivityLevel(str, Enum):
    """Field sensitivity classification."""

    PUBLIC = "public"        # Safe to send to LLM (e.g., state, gender)
    INTERNAL = "internal"    # Used internally only (e.g., internal IDs)
    SENSITIVE = "sensitive"  # Government IDs, financial (e.g., Aadhaar, PAN)
    SECRET = "secret"        # Never expose (e.g., passwords, OTP)


@lru_cache(maxsize=1)
def _field_sensitivity() -> dict[str, SensitivityLevel]:
    """Build {vault_attribute: SensitivityLevel} from ReferenceRegistry."""
    from app.agent.registry import get_registry

    reg = get_registry()
    mapping: dict[str, SensitivityLevel] = {}
    strictness = [
        SensitivityLevel.PUBLIC,
        SensitivityLevel.INTERNAL,
        SensitivityLevel.SENSITIVE,
        SensitivityLevel.SECRET,
    ]
    for key in reg.list_keys():
        attr = reg.get_vault_attribute(key)
        if not attr:
            continue
        level = SensitivityLevel(reg.get_sensitivity(key).value)
        # A vault attribute may back several reference keys (e.g.
        # USER.account_number and USER.bank_account); the strictest wins.
        existing = mapping.get(attr)
        if existing is None or strictness.index(level) > strictness.index(existing):
            mapping[attr] = level
    return mapping


def get_field_sensitivity(field_name: str) -> SensitivityLevel:
    """Get the sensitivity level of a vault attribute (default INTERNAL)."""
    return _field_sensitivity().get(field_name, SensitivityLevel.INTERNAL)


def is_sensitive(field_name: str) -> bool:
    """Check if a field is sensitive or secret."""
    level = get_field_sensitivity(field_name)
    return level in (SensitivityLevel.SENSITIVE, SensitivityLevel.SECRET)


def get_safe_fields() -> list[str]:
    """Get fields safe to send to LLM (public only)."""
    return [
        k for k, v in _field_sensitivity().items()
        if v == SensitivityLevel.PUBLIC
    ]


def get_sensitive_fields() -> list[str]:
    """Get all sensitive/secret fields."""
    return [
        k for k, v in _field_sensitivity().items()
        if v in (SensitivityLevel.SENSITIVE, SensitivityLevel.SECRET)
    ]


# Backwards-compatible mapping view, derived from ReferenceRegistry.
# Kept as a name because existing callers/tests import it; the data is
# no longer maintained here — update ReferenceRegistry instead.
FIELD_SENSITIVITY: dict[str, SensitivityLevel] = _field_sensitivity()
