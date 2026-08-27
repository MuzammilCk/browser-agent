"""Explicit multi-tab state for the browser layer — audit Phase 8.

**Why this module exists.** `BrowserManager` opened exactly one `Page` at
`start()` and threaded that single object through the entire workflow.
Nothing registered `context.on("page", ...)`, and nothing ever re-checked
`context.pages`. So a click on a `target="_blank"` link (or a
`window.open()`) — extremely common where a legacy portal links out to a
separate sub-application — navigated a tab **nobody was looking at**:

- the tracked page never moved, so the next observation looked unchanged;
- `wait_for_load_state` on the tracked page resolved trivially;
- the click was still reported as `success=True`;
- the planner, reasoning correctly on what it could see, clicked the same
  link again — one duplicate tab per retry.

That is a perception gap, not a reasoning failure. The fix is to make
"which tab is active" and "how many tabs are open" explicit, observable
state instead of an implicit property of whichever object was passed
around, and to write every switch into the workflow trace.

Design notes:
- Detection is event-first (`context.on("page")` in `BrowserManager`) with
  a short bounded wait in the action path, because `context.pages` is
  populated asynchronously and is still length 1 in the instant after
  `locator.click()` returns (verified against the real driver).
- Every helper degrades to "keep the page we have" when tab information is
  unavailable (non-Playwright/mock pages), so this never invents state.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.models.page_state import TabState, TabsState

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)

# How long to wait for a brand-new tab to register after an action. Polling
# exits as soon as a tab appears, so the full budget is only ever spent by
# an action that changed nothing at all — exactly the case that used to
# burn a recovery attempt and re-click.
NEW_TAB_GRACE_MS = 1000
_POLL_INTERVAL_MS = 25

# How long to let a freshly opened tab settle before it is observed.
NEW_TAB_LOAD_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class TabSwitch:
    """An explicit, recorded change of the active tab.

    Named state instead of a silent reroute: this is what gets written into
    the workflow checkpoint/trace log so the switch is visible to whoever
    debugs the run next.
    """

    from_url: str
    to_url: str
    total_tabs: int
    closed_tabs: int = 0
    reason: str = "new_tab_opened"

    def describe(self) -> str:
        detail = (
            f"opened a new tab: {self.to_url} — switching context to it"
            if self.reason == "new_tab_opened"
            else f"active tab {self.reason} — switching context to {self.to_url}"
        )
        tail = f" ({self.total_tabs} tab(s) open"
        if self.closed_tabs:
            tail += f", closed {self.closed_tabs} orphaned tab(s)"
        tail += f"; previous tab was {self.from_url or 'unknown'})"
        return f"Tab switch: {detail}{tail}"


@dataclass(frozen=True)
class TabSyncResult:
    """Which page later observations/actions must use, and why."""

    active_page: Any
    switch: TabSwitch | None = None


# ── Low-level, mock-safe accessors ─────────────────────────


def context_of(page: Any) -> Any:
    """The BrowserContext owning ``page``, or None when unavailable."""
    return getattr(page, "context", None)


def is_closed(page: Any) -> bool:
    try:
        return bool(page.is_closed())
    except Exception:
        return False


def safe_url(page: Any) -> str:
    try:
        url = page.url
    except Exception:
        return ""
    return url if isinstance(url, str) else ""


def live_pages(context: Any) -> list[Any]:
    """Open pages in ``context``.

    Returns ``[]`` when the object cannot report pages (mock/None), which
    every caller treats as "tab state unknown — change nothing".
    """
    if context is None:
        return []
    try:
        pages = list(context.pages)
    except Exception:
        return []
    return [p for p in pages if not is_closed(p)]


def pages_for(page: Any) -> list[Any]:
    """Open sibling pages of ``page`` (including itself)."""
    return live_pages(context_of(page))


def build_tabs_state(page: Any) -> TabsState:
    """Snapshot the context's tabs for a PageObservation.

    Falls back to a single-tab state when the context cannot be inspected,
    never to invented tabs.
    """
    pages = pages_for(page)
    if not pages:
        return TabsState(total=1, active_index=0, tabs=[])

    active_index = 0
    for idx, candidate in enumerate(pages):
        if candidate is page:
            active_index = idx
            break

    return TabsState(
        total=len(pages),
        active_index=active_index,
        tabs=[
            TabState(index=idx, url=safe_url(p), active=idx == active_index)
            for idx, p in enumerate(pages)
        ],
    )


# ── Waiting and switching ──────────────────────────────────


async def wait_for_new_pages(
    context: Any,
    pages_before: list[Any],
    *,
    timeout_ms: int = NEW_TAB_GRACE_MS,
) -> list[Any]:
    """Poll for pages that were not open before, bounded by ``timeout_ms``.

    Playwright registers a new page asynchronously, so the list is still
    unchanged in the instant an action returns. Exits as soon as anything
    new appears.
    """
    if context is None:
        return []
    known = {id(p) for p in pages_before}
    deadline_polls = max(1, int(timeout_ms / _POLL_INTERVAL_MS))
    for _ in range(deadline_polls):
        fresh = [p for p in live_pages(context) if id(p) not in known]
        if fresh:
            return fresh
        await asyncio.sleep(_POLL_INTERVAL_MS / 1000)
    return []


async def settle_page(page: Any, *, timeout_ms: int = NEW_TAB_LOAD_TIMEOUT_MS) -> None:
    """Let a freshly adopted tab reach domcontentloaded before observation."""
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except Exception as e:  # not fatal: the observer handles partial pages
        logger.debug("New tab did not reach domcontentloaded in time: %s", e)


async def close_pages(pages: list[Any]) -> int:
    """Close pages, tolerating already-closed/detached ones. Returns count."""
    closed = 0
    for page in pages:
        if is_closed(page):
            continue
        try:
            await page.close()
            closed += 1
        except Exception as e:
            logger.debug("Could not close orphaned tab: %s", e)
    return closed


async def sync_active_page(
    page: Any,
    pages_before: list[Any],
    *,
    close_orphans: bool = True,
    wait_for_tabs: bool = True,
) -> TabSyncResult:
    """Resolve the active page after an action that may have opened a tab.

    Policy (Phase 8):
    - a click that opens tabs → the NEWEST tab becomes active;
    - the orphaned previous tab is closed when ``close_orphans`` is set,
      and extra duplicate tabs opened by the same action are always
      closed, so one click can never leave a pile behind;
    - if the tracked page was closed by the site, fall forward onto the
      newest live tab instead of failing later on a dead handle;
    - otherwise nothing changes and no switch is reported.
    """
    context = context_of(page)
    if context is None:
        return TabSyncResult(active_page=page)

    # No inspectable tab list (non-Playwright/mocked page): tab state is
    # unknowable, so change nothing and do not spend the grace period.
    if not live_pages(context):
        return TabSyncResult(active_page=page)

    new_pages = (
        await wait_for_new_pages(context, pages_before)
        if wait_for_tabs
        else [p for p in live_pages(context) if id(p) not in {id(x) for x in pages_before}]
    )

    if not new_pages:
        return _fall_forward_if_dead(page, context)

    newest = new_pages[-1]
    await settle_page(newest)

    from_url = safe_url(page)
    orphans = [p for p in new_pages if p is not newest]
    if close_orphans:
        orphans.append(page)
    closed = await close_pages([p for p in orphans if p is not newest])

    total = len(live_pages(context))
    switch = TabSwitch(
        from_url=from_url,
        to_url=safe_url(newest),
        total_tabs=total,
        closed_tabs=closed,
        reason="new_tab_opened",
    )
    logger.info("%s", switch.describe())
    return TabSyncResult(active_page=newest, switch=switch)


def _fall_forward_if_dead(page: Any, context: Any) -> TabSyncResult:
    """Adopt the newest live tab when the tracked page is gone."""
    if not is_closed(page):
        return TabSyncResult(active_page=page)
    survivors = live_pages(context)
    if not survivors:
        return TabSyncResult(active_page=page)
    newest = survivors[-1]
    switch = TabSwitch(
        from_url="",
        to_url=safe_url(newest),
        total_tabs=len(survivors),
        reason="closed_by_site",
    )
    logger.warning("%s", switch.describe())
    return TabSyncResult(active_page=newest, switch=switch)


def resolve_active_page(page: Any) -> TabSyncResult:
    """Iteration-start check: is the page we are about to observe still real?

    Synchronous because it only inspects already-known context state.
    Deliberately conservative — it only adopts another tab when the tracked
    page is dead. Tabs that appear without an action of ours are reported
    to the model through ``PageState.tabs`` instead of being seized
    silently: the model decides whether they matter.
    """
    context = context_of(page)
    if context is None:
        return TabSyncResult(active_page=page)
    return _fall_forward_if_dead(page, context)


def switch_from_result(current_page: Any, result: Any) -> TabSyncResult:
    """Narrow an ``ActionResult`` to the page later iterations must use.

    Typed narrowing on purpose: anything that is not a real ``TabSwitch``
    (including a mocked result) leaves the tracked page untouched.
    """
    switch = getattr(result, "tab_switch", None)
    if not isinstance(switch, TabSwitch):
        return TabSyncResult(active_page=current_page)
    candidate = getattr(result, "active_page", None)
    if candidate is None:
        return TabSyncResult(active_page=current_page, switch=switch)
    return TabSyncResult(active_page=candidate, switch=switch)


class TabTracker:
    """Tracks every tab in a context from the moment it opens.

    Registered by ``BrowserManager.start()`` via ``context.on("page", ...)``
    so a new tab is known immediately instead of being discovered by
    accident. "Newest tab wins" is the same rule the action path uses, so
    the manager and the executor never disagree about what is active.
    """

    def __init__(self, context: BrowserContext, initial_page: Page | None = None) -> None:
        self._context = context
        self._active: Any = initial_page
        self._history: list[TabSwitch] = []
        context.on("page", self._on_page)

    @property
    def active_page(self) -> Any:
        """The tab to observe/act on, healed if the previous one died."""
        if self._active is not None and not is_closed(self._active):
            return self._active
        survivors = live_pages(self._context)
        if survivors:
            self._active = survivors[-1]
        return self._active

    @property
    def history(self) -> list[TabSwitch]:
        return list(self._history)

    def snapshot(self) -> TabsState:
        return build_tabs_state(self.active_page)

    def adopt(self, page: Any, *, reason: str = "explicit_switch") -> TabSwitch | None:
        """Make ``page`` active, recording the switch when it changes."""
        if page is None or page is self._active:
            return None
        previous = self._active
        self._active = page
        switch = TabSwitch(
            from_url=safe_url(previous) if previous is not None else "",
            to_url=safe_url(page),
            total_tabs=len(live_pages(self._context)),
            reason=reason,
        )
        self._history.append(switch)
        return switch

    def _on_page(self, page: Any) -> None:
        """`context.on("page")` handler — a tab opened, adopt it."""
        try:
            page.on("close", lambda _p=page: self._on_close(_p))
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Could not attach close handler to new tab: %s", e)
        switch = self.adopt(page, reason="new_tab_opened")
        if switch is not None:
            logger.info("%s", switch.describe())

    def _on_close(self, page: Any) -> None:
        if page is not self._active:
            return
        survivors = [p for p in live_pages(self._context) if p is not page]
        if survivors:
            self.adopt(survivors[-1], reason="closed_by_site")
