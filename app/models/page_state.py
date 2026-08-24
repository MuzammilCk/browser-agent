"""PageState, PageObservation, and related models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ElementState(BaseModel):
    """A single interactive element on the page.

    Name fields are explicitly separated per audit #3:
    - accessible_name: ARIA accessible name (aria-label, aria-labelledby, etc.)
    - html_name: HTML name="" attribute
    - label_text: Text from associated <label> element
    """

    ref: str = Field(description="Ephemeral element reference (e.g. 'e12')")
    role: str | None = Field(default=None, description="ARIA / implicit role")
    accessible_name: str | None = Field(
        default=None,
        description="Accessible name (aria-label, aria-labelledby resolved)",
    )
    html_name: str | None = Field(
        default=None,
        description="HTML name attribute",
    )
    label_text: str | None = Field(
        default=None,
        description="Text from associated <label> element",
    )
    value: str | None = Field(default=None, description="Current value/state")
    input_type: str | None = Field(default=None, description="HTML input type")
    required: bool = Field(default=False, description="Whether the field is required")
    disabled: bool = Field(default=False, description="Whether the field is disabled")
    checked: bool | None = Field(default=None, description="Checkbox/radio state")
    selected_options: list[str] = Field(
        default_factory=list, description="Selected dropdown options"
    )
    placeholder: str | None = Field(default=None, description="Placeholder text")
    autocomplete: str | None = Field(default=None, description="Autocomplete attribute")
    description: str | None = Field(
        default=None, description="Accessible description / title"
    )
    visible: bool = Field(default=True, description="Whether element is visible")
    frame_id: str | None = Field(
        default=None, description="Frame ID if element is inside an iframe"
    )
    # Context fields per audit #8
    section_heading: str | None = Field(
        default=None, description="Nearest section/fieldset heading"
    )
    help_text: str | None = Field(
        default=None, description="Nearby help/instructional text"
    )
    group_label: str | None = Field(
        default=None, description="Fieldset/fieldset legend or group label"
    )
    nearby_text: str | None = Field(
        default=None, description="Adjacent text for disambiguation"
    )

    # Backward compatibility: map old 'name' to the best available
    @property
    def name(self) -> str | None:
        """Best human-readable name: accessible_name > label_text > html_name."""
        return self.accessible_name or self.label_text or self.html_name


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
    """Authentication challenge detection state.

    Uses confidence-based detection per audit #7, not just keywords.
    """

    detected: bool = False
    challenge_type: str | None = Field(
        default=None,
        description="login | password | otp | captcha | identity_verification | unknown",
    )
    reason: str | None = None
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Detection confidence 0-1"
    )

    # Backward compatibility
    @property
    def challenge_detected(self) -> bool:
        return self.detected


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
    elements: list[ElementState] = Field(
        default_factory=list, description="Interactive elements"
    )
    alerts: list[AlertState] = Field(
        default_factory=list, description="Page alerts/dialogs"
    )
    validation_errors: list[ValidationErrorState] = Field(
        default_factory=list, description="Validation errors"
    )
    frames: list[FrameState] = Field(
        default_factory=list, description="Embedded frames"
    )
    navigation: NavigationState = Field(
        default_factory=NavigationState, description="Nav state"
    )
    authentication: AuthenticationState = Field(
        default_factory=AuthenticationState, description="Auth challenge state"
    )
    visual_fallback_available: bool = Field(
        default=False, description="Whether screenshot fallback is available"
    )


class PageObservation(BaseModel):
    """Complete model-facing observation — wraps PageState + ARIA + context.

    Per audit #2: PageState is normalized browser state.
    PageObservation is the full observation the LLM receives.
    """

    page_state: PageState
    aria_snapshot: str = Field(
        default="", description="ARIA accessibility snapshot text"
    )
    frame_snapshots: list[dict] = Field(
        default_factory=list, description="Per-frame ARIA snapshots"
    )
    visible_text: str | None = Field(
        default=None, description="Extracted visible text for context"
    )
    screenshot_available: bool = Field(
        default=False, description="Whether a screenshot was captured"
    )
    observation_id: str = Field(
        default="", description="Unique observation ID"
    )
