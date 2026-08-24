"""Vision fallback — decides when to use screenshot-based perception.

Per audit #30:
- DOM/ARIA observation assessed for completeness
- If insufficient → capture screenshot → send multimodal LLM
- Vision is FALLBACK, not first-choice perception

Architecture:
    PageObservation
        ↓
    CompletenessAssessment
        ↓
    if sufficient → use DOM/ARIA only
    if insufficient → screenshot → vision LLM → integrate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.models.page_state import PageObservation, PageState

logger = logging.getLogger(__name__)


@dataclass
class CompletenessAssessment:
    """Assessment of whether DOM/ARIA observation is sufficient."""

    is_sufficient: bool
    confidence: float  # 0.0 to 1.0
    missing_signals: list[str]
    reason: str


def assess_completeness(observation: PageObservation) -> CompletenessAssessment:
    """Assess whether the current observation is sufficient for reasoning.

    Returns a CompletenessAssessment indicating whether vision fallback is needed.

    Per audit #30: vision should be FALLBACK, not first-choice.
    """
    page_state = observation.page_state
    missing = []
    confidence = 1.0

    # Check 1: Are there interactive elements?
    if not page_state.elements:
        missing.append("no_interactive_elements")
        confidence -= 0.3

    # Check 2: Do elements have accessible names?
    named_elements = [
        e for e in page_state.elements
        if e.accessible_name or e.label_text
    ]
    if page_state.elements:
        name_ratio = len(named_elements) / len(page_state.elements)
        if name_ratio < 0.3:
            missing.append("low_name_coverage")
            confidence -= 0.2

    # Check 3: Is the page type classified?
    if page_state.page_type == "unknown":
        missing.append("unknown_page_type")
        confidence -= 0.1

    # Check 4: Are there frames that might contain important content?
    if page_state.frames:
        # Frames detected but we may not have extracted their content
        frame_elements = [
            e for e in page_state.elements if e.frame_id
        ]
        if not frame_elements and page_state.frames:
            missing.append("frames_not_extracted")
            confidence -= 0.2

    # Check 5: Is there visual-only content that DOM can't capture?
    # (e.g., CAPTCHA images, visual layouts, charts)
    if page_state.page_type in ("captcha", "otp"):
        missing.append("visual_challenge_detected")
        confidence -= 0.4

    # Check 6: ARIA snapshot quality
    if observation.aria_snapshot and len(observation.aria_snapshot) < 50:
        missing.append("thin_aria_snapshot")
        confidence -= 0.1

    # Check 7: Page has very few elements but is not a simple page
    if len(page_state.elements) < 3 and page_state.page_type not in (
        "success", "error", "landing"
    ):
        missing.append("sparse_elements")
        confidence -= 0.15

    # Clamp confidence
    confidence = max(0.0, min(1.0, confidence))

    # Decision: sufficient if confidence >= 0.5
    is_sufficient = confidence >= 0.5

    reason = "Observation sufficient" if is_sufficient else (
        f"Observation insufficient (confidence: {confidence:.0%}): "
        f"{', '.join(missing)}"
    )

    return CompletenessAssessment(
        is_sufficient=is_sufficient,
        confidence=confidence,
        missing_signals=missing,
        reason=reason,
    )


async def capture_screenshot_for_fallback(page) -> bytes | None:
    """Capture a screenshot for vision fallback.

    Returns PNG bytes or None if capture fails.
    """
    try:
        screenshot = await page.screenshot(type="png", full_page=False)
        logger.info("Captured screenshot for vision fallback (%d bytes)", len(screenshot))
        return screenshot
    except Exception as e:
        logger.warning("Failed to capture screenshot: %s", e)
        return None
