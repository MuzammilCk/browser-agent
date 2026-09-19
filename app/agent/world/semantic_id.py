"""Semantic ID computation for interactive elements — Phase 6.

A semantic ID is a durable, human-meaningful identifier that identifies a form field
or interactive control across DOM re-renders, pagination, and ephemeral ref churn.

Examples:
- <select name="state">: "field:state"
- <select name="district">: "field:district"
- <input type="text" id="app_name">: "field:app_name"
- <label>Mobile Number</label><input>: "field:mobile_number"
- Inside fieldset "Permanent Address": "field:permanent_address.state"
"""

from __future__ import annotations

import re
from typing import Any

from app.models.page_state import ElementState


def _slugify(text: str) -> str:
    """Normalize text into a lowercase underscore-separated slug."""
    text = text.strip().lower()
    # Replace non-alphanumeric chars with underscore
    text = re.sub(r"[^a-z0-9]+", "_", text)
    # Strip leading/trailing underscores
    return text.strip("_")


def compute_semantic_id(
    element: ElementState,
    disambiguation_index: int = 0,
) -> str:
    """Compute a durable, stable semantic ID for an ElementState.

    Precedence for base key:
    1. html_name (cleanest form attribute: name="district" -> "district")
    2. accessible_name or label_text (e.g. "Select State" -> "select_state")
    3. placeholder (e.g. "Enter your full name" -> "enter_your_full_name")
    4. fallback: role + input_type + ref
    """
    base_name: str = ""

    if element.html_name and element.html_name.strip():
        base_name = _slugify(element.html_name)
    elif element.label_text and element.label_text.strip():
        base_name = _slugify(element.label_text)
    elif element.accessible_name and element.accessible_name.strip():
        base_name = _slugify(element.accessible_name)
    elif element.placeholder and element.placeholder.strip():
        base_name = _slugify(element.placeholder)

    if not base_name:
        role_part = _slugify(element.role or element.input_type or "control")
        base_name = f"{role_part}_{element.ref}"

    # Section / group prefix for disambiguation across fieldsets
    prefix = ""
    section = element.section_heading or element.group_label
    if section and section.strip():
        section_slug = _slugify(section)
        # Only prefix if section adds meaningful distinction and isn't identical
        if section_slug and section_slug not in base_name:
            prefix = f"{section_slug}."

    semantic_key = f"field:{prefix}{base_name}"

    if disambiguation_index > 0:
        semantic_key = f"{semantic_key}_{disambiguation_index}"

    return semantic_key
