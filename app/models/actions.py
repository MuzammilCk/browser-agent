"""Browser action models — typed actions the LLM can emit."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BrowserAction(BaseModel):
    """A single browser action to execute."""

    action: Literal[
        "open",
        "click",
        "fill",
        "select",
        "check",
        "uncheck",
        "upload",
        "scroll",
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
