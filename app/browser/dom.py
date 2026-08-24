"""DOM metadata extraction — targeted extraction of interactive elements.

Updated per audit findings:
- #3: Split name into accessible_name, html_name, label_text
- #8: Added surrounding context (section headings, help text, group labels)
- #15: Frame-aware element extraction
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# JavaScript that extracts interactive element metadata from the page
EXTRACT_ELEMENTS_JS = """
() => {
    const results = [];
    const seen = new Set();

    function getImplicitRole(el) {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || '').toLowerCase();
        const map = {
            'input': {
                'text': 'textbox', 'email': 'textbox', 'password': 'textbox',
                'tel': 'textbox', 'url': 'textbox', 'number': 'spinbutton',
                'search': 'searchbox', 'checkbox': 'checkbox', 'radio': 'radio',
                'submit': 'button', 'button': 'button', 'file': 'button',
                'date': 'textbox', 'hidden': null
            },
            'textarea': 'textbox',
            'select': 'combobox',
            'button': 'button',
            'a': el.href ? 'link' : null,
        };
        return (map[tag] && typeof map[tag] === 'object') ? map[tag][type] : (map[tag] || null);
    }

    function findLabel(el) {
        if (el.id) {
            const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (label) return label.textContent.trim();
        }
        const parentLabel = el.closest('label');
        if (parentLabel) return parentLabel.textContent.trim();
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const parts = labelledBy.split(' ').map(id => {
                const lab = document.getElementById(id);
                return lab ? lab.textContent.trim() : '';
            }).filter(Boolean);
            if (parts.length) return parts.join(' ');
        }
        return '';
    }

    function findAccessibleName(el) {
        // aria-label is the primary accessible name
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return ariaLabel;

        // aria-labelledby
        const labelledBy = el.getAttribute('aria-labelledby');
        if (labelledBy) {
            const parts = labelledBy.split(' ').map(id => {
                const lab = document.getElementById(id);
                return lab ? lab.textContent.trim() : '';
            }).filter(Boolean);
            if (parts.length) return parts.join(' ');
        }

        // For inputs, accessible name can come from label
        return findLabel(el) || '';
    }

    function findContext(el) {
        // Walk up to find section heading, fieldset legend, or group
        let node = el.parentElement;
        let sectionHeading = null;
        let groupLabel = null;
        let helpText = null;
        let nearbyText = null;

        for (let i = 0; i < 10 && node && node !== document.body; i++) {
            // Check for fieldset/fieldset legend
            if (node.tagName === 'FIELDSET') {
                const legend = node.querySelector('legend');
                if (legend && !groupLabel) groupLabel = legend.textContent.trim();
            }

            // Check for section heading
            if (/^H[1-6]$/.test(node.tagName) && !sectionHeading) {
                sectionHeading = node.textContent.trim();
            }

            // Check for aria-describedby (help text)
            const descId = el.getAttribute('aria-describedby');
            if (descId && !helpText) {
                const descEl = document.getElementById(descId);
                if (descEl) helpText = descEl.textContent.trim();
            }

            // Check for .help-text, .form-text, [class*=help] nearby
            if (!helpText) {
                const nextSib = el.nextElementSibling;
                if (nextSib) {
                    const cls = nextSib.className || '';
                    if (typeof cls === 'string' && (cls.includes('help') || cls.includes('hint') || cls.includes('text'))) {
                        helpText = nextSib.textContent.trim();
                    }
                }
            }

            // Nearby text: previous sibling text node or element
            if (!nearbyText) {
                const prev = el.previousElementSibling;
                if (prev && prev.textContent.trim()) {
                    nearbyText = prev.textContent.trim().substring(0, 200);
                }
            }

            node = node.parentElement;
        }

        return { sectionHeading, groupLabel, helpText, nearbyText };
    }

    function getInputValue(el) {
        const tag = el.tagName.toLowerCase();
        if (tag === 'select') {
            const sel = el.options[el.selectedIndex];
            return sel ? sel.text : '';
        }
        if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
            return el.checked ? 'checked' : 'unchecked';
        }
        return el.value || '';
    }

    function getChecked(el) {
        const tag = el.tagName.toLowerCase();
        if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
            return el.checked;
        }
        return null;
    }

    function getSelectedOptions(el) {
        if (el.tagName.toLowerCase() !== 'select') return [];
        return Array.from(el.selectedOptions || []).map(o => o.text);
    }

    function isVisible(el) {
        if (el.offsetParent === null && el.tagName !== 'BODY') return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return true;
    }

    // Find all interactive elements
    const allElements = document.querySelectorAll(
        'input, textarea, select, button, a[href], [role], [tabindex], [contenteditable="true"]'
    );

    let idx = 0;
    for (const el of allElements) {
        idx++;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;
        if (el.offsetParent === null && el.tagName !== 'BODY') continue;

        const ref = 'e' + idx;
        if (seen.has(ref)) continue;
        seen.add(ref);

        const role = el.getAttribute('role') || getImplicitRole(el);
        const label = findLabel(el);
        const accessibleName = findAccessibleName(el);
        const htmlName = el.getAttribute('name') || null;
        const context = findContext(el);

        const state = {
            ref: ref,
            role: role || null,
            accessible_name: accessibleName || null,
            html_name: htmlName,
            label_text: label || null,
            value: getInputValue(el),
            input_type: el.type || null,
            required: el.required || el.getAttribute('aria-required') === 'true',
            disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
            checked: getChecked(el),
            selected_options: getSelectedOptions(el),
            placeholder: el.getAttribute('placeholder') || null,
            autocomplete: el.getAttribute('autocomplete') || null,
            description: el.getAttribute('aria-description') ||
                         el.getAttribute('title') || null,
            visible: isVisible(el),
            frame_id: null,
            section_heading: context.sectionHeading,
            group_label: context.groupLabel,
            help_text: context.helpText,
            nearby_text: context.nearbyText
        };

        results.push(state);
    }

    return results;
}
"""

# Frame-aware element extraction — runs inside an iframe context
EXTRACT_FRAME_ELEMENTS_JS = """
(frameId) => {
    const results = [];
    const seen = new Set();

    function getImplicitRole(el) {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || '').toLowerCase();
        const map = {
            'input': {
                'text': 'textbox', 'email': 'textbox', 'password': 'textbox',
                'tel': 'textbox', 'url': 'textbox', 'number': 'spinbutton',
                'search': 'searchbox', 'checkbox': 'checkbox', 'radio': 'radio',
                'submit': 'button', 'button': 'button', 'file': 'button',
                'date': 'textbox', 'hidden': null
            },
            'textarea': 'textbox',
            'select': 'combobox',
            'button': 'button',
            'a': el.href ? 'link' : null,
        };
        return (map[tag] && typeof map[tag] === 'object') ? map[tag][type] : (map[tag] || null);
    }

    function findLabel(el) {
        if (el.id) {
            const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (label) return label.textContent.trim();
        }
        const parentLabel = el.closest('label');
        if (parentLabel) return parentLabel.textContent.trim();
        return '';
    }

    function findAccessibleName(el) {
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return ariaLabel;
        return findLabel(el) || '';
    }

    function isVisible(el) {
        if (el.offsetParent === null && el.tagName !== 'BODY') return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        return true;
    }

    function getInputValue(el) {
        const tag = el.tagName.toLowerCase();
        if (tag === 'select') {
            const sel = el.options[el.selectedIndex];
            return sel ? sel.text : '';
        }
        if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) {
            return el.checked ? 'checked' : 'unchecked';
        }
        return el.value || '';
    }

    const allElements = document.querySelectorAll(
        'input, textarea, select, button, a[href], [role], [tabindex]'
    );

    let idx = 0;
    for (const el of allElements) {
        idx++;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) continue;
        if (el.offsetParent === null && el.tagName !== 'BODY') continue;

        const ref = 'f_' + frameId + '_e' + idx;
        if (seen.has(ref)) continue;
        seen.add(ref);

        const role = el.getAttribute('role') || getImplicitRole(el);
        const label = findLabel(el);
        const accessibleName = findAccessibleName(el);

        results.push({
            ref: ref,
            role: role || null,
            accessible_name: accessibleName || null,
            html_name: el.getAttribute('name') || null,
            label_text: label || null,
            value: getInputValue(el),
            input_type: el.type || null,
            required: el.required || el.getAttribute('aria-required') === 'true',
            disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
            checked: null,
            selected_options: [],
            placeholder: el.getAttribute('placeholder') || null,
            autocomplete: null,
            description: el.getAttribute('title') || null,
            visible: isVisible(el),
            frame_id: frameId,
            section_heading: null,
            group_label: null,
            help_text: null,
            nearby_text: null
        });
    }

    return results;
}
"""

EXTRACT_VALIDATIONS_JS = """
() => {
    const results = [];
    const inputs = document.querySelectorAll('input, textarea, select');

    for (const el of inputs) {
        if (el.getAttribute('aria-invalid') === 'true') {
            const errorId = el.getAttribute('aria-errormessage');
            let message = '';
            if (errorId) {
                const errEl = document.getElementById(errorId);
                if (errEl) message = errEl.textContent.trim();
            }
            if (!message) {
                const next = el.nextElementSibling;
                if (next && (next.classList.contains('error') ||
                    next.classList.contains('invalid-feedback') ||
                    next.getAttribute('role') === 'alert')) {
                    message = next.textContent.trim();
                }
            }
            results.push({
                target_ref: null,
                element_id: el.id || null,
                element_name: el.name || null,
                message: message || 'Invalid input',
                visible: true
            });
        }
    }

    const alerts = document.querySelectorAll('[role="alert"], .alert, .error-message, .validation-error');
    for (const alert of alerts) {
        if (alert.offsetParent !== null || alert.tagName === 'BODY') {
            const text = alert.textContent.trim();
            if (text) {
                results.push({
                    target_ref: null,
                    element_id: alert.id || null,
                    element_name: null,
                    message: text,
                    visible: true
                });
            }
        }
    }

    return results;
}
"""

EXTRACT_FRAMES_JS = """
() => {
    const frames = [];
    const iframes = document.querySelectorAll('iframe');

    for (let i = 0; i < iframes.length; i++) {
        const iframe = iframes[i];
        frames.push({
            frame_id: 'f' + (i + 1),
            url: iframe.src || null,
            name: iframe.name || null,
            title: iframe.title || null
        });
    }

    return frames;
}
"""

EXTRACT_ALERTS_JS = """
() => {
    const results = [];
    const alertEls = document.querySelectorAll(
        '[role="alert"], [role="dialog"], [role="alertdialog"], .modal.show, dialog[open]'
    );

    for (const el of alertEls) {
        results.push({
            ref: 'a' + (results.length + 1),
            role: el.getAttribute('role') || 'alert',
            name: el.getAttribute('aria-label') || null,
            text: el.textContent.trim().substring(0, 500),
            visible: el.offsetParent !== null
        });
    }

    return results;
}
"""

EXTRACT_NAVIGATION_JS = """
() => {
    return {
        can_go_back: window.history.length > 1,
        can_go_forward: false,
        current_url: window.location.href,
        title: document.title || ''
    };
}
"""


async def extract_interactive_elements(page: Page) -> list[dict[str, Any]]:
    """Extract all interactive elements with their metadata from main frame."""
    try:
        elements = await page.evaluate(EXTRACT_ELEMENTS_JS)
        logger.debug("Extracted %d interactive elements from main frame", len(elements))
        return elements
    except Exception:
        logger.warning("Failed to extract interactive elements", exc_info=True)
        return []


async def extract_frame_elements(
    page: Page, frame_id: str, frame_url: str
) -> list[dict[str, Any]]:
    """Extract interactive elements from a specific frame."""
    try:
        # Find the frame by URL
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            if frame.url == frame_url or frame.name == frame_id:
                elements = await frame.evaluate(EXTRACT_FRAME_ELEMENTS_JS, frame_id)
                logger.debug(
                    "Extracted %d elements from frame %s", len(elements), frame_id
                )
                return elements
    except Exception:
        logger.debug("Could not extract elements from frame %s", frame_id)
    return []


async def extract_validations(page: Page) -> list[dict[str, Any]]:
    """Extract validation errors and alert messages."""
    try:
        validations = await page.evaluate(EXTRACT_VALIDATIONS_JS)
        logger.debug("Extracted %d validation errors", len(validations))
        return validations
    except Exception:
        logger.warning("Failed to extract validations", exc_info=True)
        return []


async def extract_frames(page: Page) -> list[dict[str, Any]]:
    """Extract iframe metadata."""
    try:
        frames = await page.evaluate(EXTRACT_FRAMES_JS)
        logger.debug("Extracted %d frames", len(frames))
        return frames
    except Exception:
        logger.warning("Failed to extract frames", exc_info=True)
        return []


async def extract_alerts(page: Page) -> list[dict[str, Any]]:
    """Extract visible alerts and dialogs."""
    try:
        alerts = await page.evaluate(EXTRACT_ALERTS_JS)
        logger.debug("Extracted %d alerts", len(alerts))
        return alerts
    except Exception:
        logger.warning("Failed to extract alerts", exc_info=True)
        return []


async def extract_navigation(page: Page) -> dict[str, Any]:
    """Extract navigation state."""
    try:
        return await page.evaluate(EXTRACT_NAVIGATION_JS)
    except Exception:
        logger.warning("Failed to extract navigation state", exc_info=True)
        return {
            "can_go_back": False,
            "can_go_forward": False,
            "current_url": page.url if page else "",
            "title": "",
        }
