"""Quick test — observe a real government site (observation only, no filling)."""

import asyncio
from playwright.async_api import async_playwright
from app.browser.observer import PageObserver


async def test_observation():
    """Observe a real site and print the results."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        # Try a simple government form page
        url = "https://pmkisan.gov.in/helpline.htm"
        print(f"\n--- Observing: {url} ---\n")

        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        observer = PageObserver()
        observation = await observer.observe(page)
        state = observation.page_state

        print(f"Page URL:    {state.url}")
        print(f"Page Title:  {state.title}")
        print(f"Page Type:   {state.page_type}")
        print(f"Elements:    {len(state.elements)}")
        print(f"Frames:      {len(state.frames)}")
        print(f"Alerts:      {len(state.alerts)}")
        print(f"Auth:        detected={state.authentication.detected}")

        print(f"\n{'='*60}")
        print("INTERACTIVE ELEMENTS:")
        print(f"{'='*60}")
        for el in state.elements[:30]:
            if el.role in ("textbox", "combobox", "button", "link", "checkbox", "radio"):
                name = el.accessible_name or el.label_text or el.html_name or "(no name)"
                req = " [required]" if el.required else ""
                dis = " [disabled]" if el.disabled else ""
                print(f"  {el.ref:6s} | {el.role:12s} | {name}{req}{dis}")

        if len(state.elements) > 30:
            print(f"  ... and {len(state.elements) - 30} more elements")

        print(f"\n{'='*60}")
        print("VALIDATION ERRORS:")
        print(f"{'='*60}")
        for v in state.validation_errors:
            print(f"  {v.target_ref}: {v.message}")

        print(f"\n{'='*60}")
        print(f"OBSERVATION ID: {observation.observation_id}")
        print(f"ARIA SNAPSHOT:  {len(observation.aria_snapshot)} chars")
        print(f"{'='*60}")

        await browser.close()
        print("\nDone! Observation works correctly.")


if __name__ == "__main__":
    asyncio.run(test_observation())
