"""Prompt injection sanitizer — protects LLM from malicious page content.

Per audit #10 and security requirements:
- Sanitize all page content before sending to LLM
- Detect and neutralize prompt injection patterns
- Never send raw HTML/JS to LLM
- Strip instruction overrides from visible text

Architecture:
    PageObservation
        ↓
    Sanitizer.sanitize()
        ↓
    Clean text for LLM
        ↓
    LLM (reasoning only on safe content)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ─── Injection patterns to detect and neutralize ─────────────────

INJECTION_PATTERNS = [
    # Direct instruction overrides
    r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|rules?|prompts?|guidelines?)",
    r"(?:you\s+are\s+now|act\s+as|pretend\s+(?:to\s+be|you\s+are)|roleplay\s+as)",
    r"(?:system\s*:|<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\])",
    r"(?:new\s+instructions?|override\s+instructions?|updated\s+rules?)",

    # Escape/hack attempts
    r"(?:\\n|\\r|\\t){3,}",  # Excessive escape sequences
    r"(?:&#x?[0-9a-f]+;){3,}",  # HTML entity stuffing
    r"(?:\u200b|\u200c|\u200d|\ufeff){3,}",  # Zero-width characters

    # Prompt boundaries
    r"(?:```\s*(?:system|assistant|user)\s*:)",
    r"(?:---\s*(?:END|BEGIN)\s*(?:SYSTEM|ASSISTANT|USER)\s*---)",

    # Data exfiltration attempts
    r"(?:send|post|exfiltrate|leak|transmit)\s+(?:all\s+)?(?:data|info|secrets?|keys?|tokens?|passwords?)",
    r"(?:to\s+(?:https?://|ftp://|ws://))",

    # Role confusion
    r"(?:forget\s+you\s+are\s+(?:an?\s+)?(?:AI|assistant|bot|agent))",
    r"(?:you\s+(?:are|must|should)\s+(?:now\s+)?(?:obey|follow|listen\s+to)\s+me)",

    # Encoding attacks
    r"(?:base64|rot13|hex)\s*(?:decode|encode|decryption)",
]

# Compile patterns for performance
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

# Characters that might be used for Unicode attacks
SUSPICIOUS_UNICODE = re.compile(r"[\u200b-\u200f\u2028-\u202f\u2060-\u2064\ufeff]")


@dataclass
class SanitizationResult:
    """Result of content sanitization."""

    clean_text: str
    injections_detected: list[str] = field(default_factory=list)
    content_stripped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_safe: bool = True


class PromptSanitizer:
    """Sanitizes page content before sending to LLM.

    Detects and neutralizes prompt injection attempts in:
    - Visible text on the page
    - Element labels and names
    - ARIA snapshots
    - Alerts and validation messages
    """

    def sanitize_text(self, text: str, source: str = "unknown") -> SanitizationResult:
        """Sanitize a piece of text for LLM consumption.

        Args:
            text: Raw text from page
            source: Where the text came from (for logging)

        Returns:
            SanitizationResult with clean text and detection info
        """
        if not text:
            return SanitizationResult(clean_text="")

        result = SanitizationResult(clean_text=text)
        original = text

        # Check for injection patterns
        for pattern in _COMPILED_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                result.injections_detected.extend(matches)
                result.is_safe = False
                # Neutralize by replacing with [SANITIZED]
                text = pattern.sub("[SANITIZED]", text)

        # Strip zero-width characters
        if SUSPICIOUS_UNICODE.search(text):
            text = SUSPICIOUS_UNICODE.sub("", text)
            result.content_stripped.append("suspicious_unicode")
            result.is_safe = False

        # Strip excessive whitespace (common in injection attempts)
        text = re.sub(r"\s{5,}", "    ", text)

        # Truncate extremely long content (injection attempts often use long payloads)
        if len(text) > 2000:
            text = text[:2000] + "...[truncated]"
            result.warnings.append(f"Content truncated from {len(original)} chars")
            result.is_safe = False

        result.clean_text = text.strip()

        if result.injections_detected:
            logger.warning(
                "Injection detected in %s: %d patterns matched",
                source, len(result.injections_detected),
            )

        return result

    def sanitize_elements(
        self, elements: list[dict],
    ) -> list[dict]:
        """Sanitize element info before sending to LLM.

        Processes labels, names, and descriptions.
        """
        clean_elements = []
        for el in elements:
            clean_el = dict(el)
            for field_name in ("name", "label", "section", "group", "help_text"):
                if field_name in clean_el and clean_el[field_name]:
                    result = self.sanitize_text(
                        clean_el[field_name],
                        source=f"element.{field_name}",
                    )
                    clean_el[field_name] = result.clean_text
                    if not result.is_safe:
                        logger.warning(
                            "Sanitized element field %s: %s",
                            field_name, result.injections_detected,
                        )
            clean_elements.append(clean_el)
        return clean_elements

    def sanitize_snapshot(self, snapshot: str) -> str:
        """Sanitize an ARIA snapshot for LLM consumption."""
        result = self.sanitize_text(snapshot, source="aria_snapshot")
        return result.clean_text

    def sanitize_alerts(self, alerts: list[str]) -> list[str]:
        """Sanitize alert messages."""
        clean = []
        for alert in alerts:
            result = self.sanitize_text(alert, source="alert")
            clean.append(result.clean_text)
        return clean

    def is_content_safe(self, text: str) -> bool:
        """Quick check if content is safe (no injections detected)."""
        result = self.sanitize_text(text)
        return result.is_safe
