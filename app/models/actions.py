"""Browser action models — typed actions the LLM can emit.

Updated per audit #16: Action-specific validation enforced via Pydantic validators.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BrowserAction(BaseModel):
    """A single browser action to execute.

    Each action type has specific required fields enforced by validators.
    """

    action: Literal[
        "open",
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
        "finish_review",
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
        description="Literal value to use (only for non-sensitive fields)",
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

    @model_validator(mode="after")
    def validate_action_fields(self) -> BrowserAction:
        """Enforce action-specific required field combinations."""
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

        if act == "select":
            if not self.target_ref:
                raise ValueError("select requires target_ref")
            if not self.option:
                raise ValueError("select requires option")

        if act == "upload":
            if not self.target_ref:
                raise ValueError("upload requires target_ref")
            if not self.document_ref and not self.literal_value:
                raise ValueError("upload requires either document_ref or literal_value (file path)")

        if act == "open":
            if not self.literal_value:
                raise ValueError("open requires literal_value (URL)")

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
