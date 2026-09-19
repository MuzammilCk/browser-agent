"""Authoritative registry for specialist agents — Phase 10.

Rule 5: SPECIALIST REGISTRY IS AUTHORITATIVE
- The model may select a registered specialist by type.
- The model cannot choose or alter its permission class.
- Permissions are fixed by the registered implementation.
- Do not dynamically construct arbitrary specialist capabilities.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from app.agent.specialists.models import SpecialistPermission, SpecialistType

if TYPE_CHECKING:
    from app.agent.specialists.base import SpecialistAgent

logger = logging.getLogger(__name__)


class SpecialistRegistry:
    """Authoritative catalog of registered specialist agents.

    Enforces that:
    1. Specialists are pre-registered with immutable permissions.
    2. Dynamic creation of unvetted specialist capabilities is prohibited.
    3. Duplicate registrations fail closed.
    """

    def __init__(self) -> None:
        self._specialists: dict[SpecialistType, SpecialistAgent] = {}
        self._lock = threading.RLock()

    def register(self, specialist: SpecialistAgent) -> None:
        """Register a specialist agent. Re-registration or collision raises ValueError."""
        with self._lock:
            stype = specialist.specialist_type
            if stype in self._specialists:
                raise ValueError(f"Specialist '{stype.value}' is already registered")
            self._specialists[stype] = specialist
            logger.debug(
                "Registered specialist: %s with permission: %s",
                stype.value,
                specialist.permission.value,
            )

    def get(self, specialist_type: SpecialistType | str) -> SpecialistAgent | None:
        """Retrieve a specialist by type."""
        with self._lock:
            if isinstance(specialist_type, str):
                try:
                    specialist_type = SpecialistType(specialist_type)
                except ValueError:
                    return None
            return self._specialists.get(specialist_type)

    def get_permission(self, specialist_type: SpecialistType | str) -> SpecialistPermission | None:
        """Get the authoritative fixed permission class for a specialist type."""
        spec = self.get(specialist_type)
        return spec.permission if spec else None

    def list_specialists(self) -> list[SpecialistType]:
        """List registered specialist types."""
        with self._lock:
            return sorted(self._specialists.keys(), key=lambda s: s.value)

    def is_registered(self, specialist_type: SpecialistType | str) -> bool:
        """Check if specialist type is registered."""
        return self.get(specialist_type) is not None


# Global singleton registry
_GLOBAL_REGISTRY: SpecialistRegistry | None = None
_REGISTRY_LOCK = threading.RLock()


def get_specialist_registry() -> SpecialistRegistry:
    """Get or initialize the global specialist registry."""
    global _GLOBAL_REGISTRY
    with _REGISTRY_LOCK:
        if _GLOBAL_REGISTRY is None:
            _GLOBAL_REGISTRY = SpecialistRegistry()
        return _GLOBAL_REGISTRY
