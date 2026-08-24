"""PageState and related models — normalized page representation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ElementState(BaseModel):
    """A single interactive element on the page."""

    ref: str = Field(description="Ephemeral element reference (e.g. 'e12')")
    role: str | None = Field(default=None, description="ARIA role")
    name: str | None = Field(default=None, description="Accessible name")
    label: str | None = Field(default=None, description="Associated label text")
    value: str | None = Field(default=None, description="Current value/state")
    input_type: str | None = Field(default=None, description="HTML input type")
    required: bool = Field(default=False, description="Whether the field is required")
    disabled: bool = Field(default=False, description="Whether the field is disabled")
    checked: bool | None = Field(default=None, description="Checkbox/radio state")
    selected_options: list[str] = Field(default_factory=list, description="Selected dropdown options")
    placeholder: str | None = Field(default=None, description="Placeholder text")
    autocomplete: str | None = Field(default=None, description="Autocomplete attribute")
    description: str | None = Field(default=None, description="Accessible description")
    visible: bool = Field(default=True, description="Whether element is visible")
    frame_id: str | None = Field(default=None, description="Frame ID if in an iframe")


class AlertState(BaseModel):
    """An alert or dialog on the page."""

    ref: str
    role: str | None = None
    name: str | None = None
    text: str | None = None
    visible: bool = True


class ValidationErrorState(BaseModel):
    """A validation error detected on the page."""

    target_ref: str | None = None
    message: str | None = None
    visible: bool = True


class FrameState(BaseModel):
    """An iframe or frame detected on the page."""

    frame_id: str
    url: str | None = None
    name: str | None = None
    title: str | None = None


class NavigationState(BaseModel):
    """Navigation-related state."""

    can_go_back: bool = False
    can_go_forward: bool = False
    current_url: str = ""
    title: str = ""


class AuthenticationState(BaseModel):
    """Authentication challenge detection state."""

    challenge_detected: bool = False
    challenge_type: str | None = None
    challenge_reason: str | None = None


class PageState(BaseModel):
    """Complete normalized representation of a browser page."""

    url: str = Field(default="", description="Current page URL")
    title: str = Field(default="", description="Page title")
    page_id: str = Field(default="", description="Unique page observation ID")
    page_type: Literal[
        "unknown",
        "landing",
        "navigation",
        "form",
        "review",
        "payment",
        "authentication",
        "captcha",
        "otp",
        "error",
        "success",
        "appointment",
    ] = Field(default="unknown", description="Page type classification")
    elements: list[ElementState] = Field(default_factory=list, description="Interactive elements")
    alerts: list[AlertState] = Field(default_factory=list, description="Page alerts/dialogs")
    validation_errors: list[ValidationErrorState] = Field(
        default_factory=list, description="Validation errors"
    )
    frames: list[FrameState] = Field(default_factory=list, description="Embedded frames")
    navigation: NavigationState = Field(default_factory=NavigationState, description="Nav state")
    authentication: AuthenticationState = Field(
        default_factory=AuthenticationState, description="Auth challenge state"
    )
    visual_fallback_available: bool = Field(
        default=False,
        description="Whether screenshot fallback is available",
    )
