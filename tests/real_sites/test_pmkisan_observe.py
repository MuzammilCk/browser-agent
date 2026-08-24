"""Real site observation test — observe PM-KISAN (pmkisan.gov.in).

This script:
1. Opens the PM-KISAN website
2. Observes the page using our PageObserver
3. Prints what the agent sees (elements, labels, roles, validation)
4. Takes a screenshot

This is OBSERVATION ONLY — no actions are taken on the real site.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"


async def observe_site(url: str) -> None:
    """Open a URL, observe it, and print the results."""
    settings = Settings(headless=True)
    observer = PageObserver()

    SCREENSHOT_DIR.mkdir(exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  OBSERVING: {url}")
    print(f"{'='*60}\n")

    async with BrowserManager(settings) as manager:
        # Navigate
        print("🌐 Opening page...")
        page = await manager.open(url)

        # Wait for page to settle
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)  # Extra settle time for JS

        # Take screenshot
        screenshot_path = SCREENSHOT_DIR / "pmkisan_home.png"
        await manager.screenshot(path=screenshot_path, full_page=True)
        print(f"📸 Screenshot saved: {screenshot_path}")

        # Observe
        print("\n🔍 Observing page...\n")
        observation = await observer.observe(page)
        state = observation.page_state

        # Print results
        print(f"📋 URL: {state.url}")
        print(f"📋 Title: {state.title}")
        print(f"📋 Page type: {state.page_type}")
        print(f"📋 Page ID: {state.page_id}")
        print(f"📋 Elements found: {len(state.elements)}")
        print(f"📋 Alerts: {len(state.alerts)}")
        print(f"📋 Validation errors: {len(state.validation_errors)}")
        print(f"📋 Frames: {len(state.frames)}")
        print(f"📋 Auth detected: {state.authentication.detected}")

        if state.authentication.detected:
            print(f"   → Type: {state.authentication.challenge_type}")
            print(f"   → Reason: {state.authentication.reason}")
            print(f"   → Confidence: {state.authentication.confidence}")

        print(f"\n{'─'*60}")
        print("  INTERACTIVE ELEMENTS")
        print(f"{'─'*60}\n")

        for el in state.elements:
            vis = "👁" if el.visible else "🚫"
            req = " *REQUIRED*" if el.required else ""
            dis = " [DISABLED]" if el.disabled else ""

            name = el.accessible_name or el.label_text or el.html_name or "(unnamed)"
            print(f"  {vis} {el.ref} | {el.role or 'none':12s} | {name}{req}{dis}")

            if el.value:
                print(f"     value: {el.value}")
            if el.placeholder:
                print(f"     placeholder: {el.placeholder}")
            if el.selected_options:
                print(f"     selected: {el.selected_options}")
            if el.section_heading:
                print(f"     section: {el.section_heading}")
            if el.group_label:
                print(f"     group: {el.group_label}")
            if el.help_text:
                print(f"     help: {el.help_text}")

        if state.validation_errors:
            print(f"\n{'─'*60}")
            print("  VALIDATION ERRORS")
            print(f"{'─'*60}\n")
            for ve in state.validation_errors:
                print(f"  ⚠️  {ve.message} (target: {ve.target_ref})")

        if state.alerts:
            print(f"\n{'─'*60}")
            print("  ALERTS")
            print(f"{'─'*60}\n")
            for a in state.alerts:
                print(f"  🔔 [{a.role}] {a.text}")

        if state.frames:
            print(f"\n{'─'*60}")
            print("  FRAMES")
            print(f"{'─'*60}\n")
            for f in state.frames:
                print(f"  📦 {f.frame_id}: {f.url or f.name or '(no url)'}")

        # Print ARIA snapshot (first 500 chars)
        if observation.aria_snapshot:
            print(f"\n{'─'*60}")
            print("  ARIA SNAPSHOT (first 500 chars)")
            print(f"{'─'*60}\n")
            print(observation.aria_snapshot[:500])
            if len(observation.aria_snapshot) > 500:
                print(f"\n  ... ({len(observation.aria_snapshot)} total chars)")

        # Summary
        text_fields = [e for e in state.elements if e.role in ("textbox",) and e.visible]
        dropdowns = [e for e in state.elements if e.role == "combobox" and e.visible]
        buttons = [e for e in state.elements if e.role == "button" and e.visible]
        checkboxes = [e for e in state.elements if e.role == "checkbox" and e.visible]
        radios = [e for e in state.elements if e.role == "radio" and e.visible]
        links = [e for e in state.elements if e.role == "link" and e.visible]

        print(f"\n{'─'*60}")
        print("  SUMMARY")
        print(f"{'─'*60}\n")
        print(f"  📝 Text fields: {len(text_fields)}")
        print(f"  📋 Dropdowns: {len(dropdowns)}")
        print(f"  🔘 Buttons: {len(buttons)}")
        print(f"  ☑️  Checkboxes: {len(checkboxes)}")
        print(f"  🔘 Radio buttons: {len(radios)}")
        print(f"  🔗 Links: {len(links)}")

        # Save full observation as JSON
        json_path = SCREENSHOT_DIR / "pmkisan_observation.json"
        json_path.write_text(
            observation.model_dump_json(indent=2),
            encoding="utf-8",
        )
        print(f"\n  💾 Full observation saved: {json_path}")

        print(f"\n{'='*60}")
        print(f"  OBSERVATION COMPLETE")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(observe_site("https://pmkisan.gov.in"))
