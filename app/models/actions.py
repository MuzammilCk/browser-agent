"""Browser action models — typed actions the LLM can emit.

Phase 3.5 hardening:
- #6: Removed open from LLM action set (navigation is workflow-controlled)
- #7+#9: Upload requires document_ref only (no raw filesystem paths)
- #8: Sensitive field policy for literal_value
- #3: Added observation_id for stale ref prevention
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.vault.sensitivity import is_sensitive


class BrowserAction(BaseModel):
    """A single browser action to execute.

    Each action type has specific required fields enforced by validators.
    The LLM may only emit actions from this set — open is NOT included
    because navigation is controlled by the workflow/session layer.
    """

    action: Literal[
        "click",
        "fill",
        "select",
        "check",
        "uncheck",
        "upload",
        "scroll",
        "scroll_to",
        "press",
        "wait",
        "go_back",
        "request_user_action",
        "stop",
    ]
    target_ref: str | None = Field(
        default=None,
        description="Element ref from PageState (e.g. 'e12')",
    )
    value_ref: str | None = Field(
        default=None,
        description="Semantic value reference (e.g. 'USER.full_name')",
    )
    literal_value: str | None = Field(
        default=None,
        description="Literal value (only for non-sensitive fields)",
    )
    option: str | None = Field(
        default=None,
        description="Option text for select actions",
    )
    document_ref: str | None = Field(
        default=None,
        description="Document reference (e.g. 'DOCUMENT.aadhaar')",
    )
    direction: str | None = Field(
        default=None,
        description="Scroll direction: 'up', 'down', 'left', 'right'",
    )
    key: str | None = Field(
        default=None,
        description="Key to press (e.g. 'Enter', 'Tab', 'Escape')",
    )
    reason: str | None = Field(
        default=None,
        description="Reason for the action or for requesting user action",
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence in this action being correct",
    )
    observation_id: str | None = Field(
        default=None,
        description="Observation ID this action targets (for stale ref prevention)",
    )

    @model_validator(mode="after")
    def validate_action_fields(self) -> BrowserAction:
        """Enforce action-specific required field combinations + sensitive policy."""
        act = self.action

        if act in ("click", "check", "uncheck", "scroll_to"):
            if not self.target_ref:
                raise ValueError(f"{act} requires target_ref")

        if act == "fill":
            if not self.target_ref:
                raise ValueError("fill requires target_ref")
            if not self.value_ref and not self.literal_value:
                raise ValueError("fill requires either value_ref or literal_value")
            if self.value_ref and self.literal_value:
                raise ValueError("fill cannot have both value_ref and literal_value")
            # Sensitive field policy (#8): reject literal_value for sensitive fields
            if self.literal_value and self.target_ref:
                # Heuristic: if the value looks like sensitive data, reject it
                # The actual field classification happens at resolver level,
                # but we block obviously sensitive patterns here
                import re
                # Aadhaar pattern: 12 digits with optional dashes/spaces
                if re.match(r"^[\d\s\-]{12,14}$", self.literal_value):
                    raise ValueError(
                        "Sensitive numeric value detected in literal_value. "
                        "Use value_ref (e.g., USER.aadhaar_number) instead."
                    )
                # PAN pattern: 5 letters + 4 digits + 1 letter
                if re.match(r"^[A-Z]{5}\d{4}[A-Z]$", self.literal_value):
                    raise ValueError(
                        "PAN number detected in literal_value. "
                        "Use value_ref (e.g., USER.pan_number) instead."
                    )

        if act == "select":
            if not self.target_ref:
                raise ValueError("select requires target_ref")
            if not self.option:
                raise ValueError("select requires option")

        if act == "upload":
            if not self.target_ref:
                raise ValueError("upload requires target_ref")
            if not self.document_ref:
                raise ValueError(
                    "upload requires document_ref (e.g., 'DOCUMENT.aadhaar'). "
                    "Raw filesystem paths are not allowed."
                )

        if act == "press":
            if not self.key:
                raise ValueError("press requires key")

        if act == "request_user_action":
            if not self.reason:
                raise ValueError("request_user_action requires reason")

        if act == "scroll":
            if self.direction and self.direction not in ("up", "down", "left", "right"):
                raise ValueError(f"scroll direction must be up/down/left/right, got: {self.direction}")

        return self
