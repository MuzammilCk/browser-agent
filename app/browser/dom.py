"""DOM metadata extraction — targeted extraction of interactive elements."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)

# JavaScript that extracts interactive element metadata from the page
EXTRACT_ELEMENTS_JS = """
() => {
    const INTERACTIVE_ROLES = [
        'textbox', 'combobox', 'listbox', 'checkbox', 'radio',
        'button', 'link', 'switch', 'slider', 'spinbutton',
        'searchbox', 'menuitem', 'tab', 'treeitem', 'option'
    ];

    const results = [];
    const seen = new Set();

    // Helper to generate a ref for an element
    function getRef(el, idx) {
        const tag = el.tagName.toLowerCase();
        const type = el.type || '';
        const role = el.getAttribute('role') || '';
        return 'e' + idx;
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

        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute('role') || getImplicitRole(el);
        const label = findLabel(el);
        const name = el.getAttribute('aria-label') ||
                     el.getAttribute('name') ||
                     label || '';
        const placeholder = el.getAttribute('placeholder') || '';
        const autocomplete = el.getAttribute('autocomplete') || '';
        const description = el.getAttribute('aria-description') ||
                           el.getAttribute('title') || '';

        const state = {
            ref: ref,
            role: role || null,
            name: name || null,
            label: label || null,
            value: getInputValue(el),
            input_type: el.type || null,
            required: el.required || el.getAttribute('aria-required') === 'true',
            disabled: el.disabled || el.getAttribute('aria-disabled') === 'true',
            checked: getChecked(el),
            selected_options: getSelectedOptions(el),
            placeholder: placeholder || null,
            autocomplete: autocomplete || null,
            description: description || null,
            visible: isVisible(el),
            frame_id: null,
            tag_name: tag,
            has_options: el.options ? el.options.length : 0
        };

        results.push(state);
    }

    return results;

    function getImplicitRole(el) {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || '').toLowerCase();
        const map = {
            'input': {
                'text': 'textbox', 'email': 'textbox', 'password': 'textbox',
                'tel': 'textbox', 'url': 'textbox', 'number': 'spinbutton',
                'search': 'searchbox', 'checkbox': 'checkbox', 'radio': 'radio',
                'submit': 'button', 'button': 'button', 'file': 'button'
            },
            'textarea': 'textbox',
            'select': 'combobox',
            'button': 'button',
            'a': el.href ? 'link' : null,
            'h1': null, 'h2': null, 'h3': null, 'h4': null, 'h5': null, 'h6': null,
        };
        return (map[tag] && typeof map[tag] === 'object') ? map[tag][type] : (map[tag] || null);
    }

    function findLabel(el) {
        // Check for associated <label>
        if (el.id) {
            const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (label) return label.textContent.trim();
        }
        // Check parent label
        const parentLabel = el.closest('label');
        if (parentLabel) return parentLabel.textContent.trim();
        // Check aria-labelledby
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
}
"""

EXTRACT_VALIDATIONS_JS = """
() => {
    const results = [];
    const inputs = document.querySelectorAll('input, textarea, select');

    for (const el of inputs) {
        // Check aria-invalid
        if (el.getAttribute('aria-invalid') === 'true') {
            // Look for associated error message
            const errorId = el.getAttribute('aria-errormessage');
            let message = '';
            if (errorId) {
                const errEl = document.getElementById(errorId);
                if (errEl) message = errEl.textContent.trim();
            }
            // Also look for nearby error text
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

    // Check for visible alerts
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
    """Extract all interactive elements with their metadata."""
    try:
        elements = await page.evaluate(EXTRACT_ELEMENTS_JS)
        logger.debug("Extracted %d interactive elements", len(elements))
        return elements
    except Exception:
        logger.warning("Failed to extract interactive elements", exc_info=True)
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
