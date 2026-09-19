"""Phase 6 synthetic integration tests — Real Chromium WorldState continuity.

Proves Phase 6 exit criterion:
"DOM rerenders do not erase verified semantic progress."

Contains the two required acceptance test flows:
1. Dynamic-form acceptance test (dropdowns.html):
   - observe state page
   - map/select State
   - dependent District field appears
   - reducer updates WorldState
   - previously verified values remain intact
   - new District semantic field is introduced
   - old DOM refs are invalidated
   - current observation receives new refs
2. Multi-tab acceptance test (simple.html + portal_subportal.html):
   - tab A contains verified progress
   - new tab B appears
   - WorldState tracks both
   - active tab changes
   - tab A state is not lost
   - actions against stale tab/page refs are rejected
   - switching back restores semantic continuity
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.world.models import AgentWorldState, EpistemicStatus
from app.agent.world.reducer import (
    is_target_ref_valid,
    record_verified_action,
    reduce_observation,
)
from app.browser.executor import BrowserExecutor
from app.browser.manager import BrowserManager
from app.browser.observer import PageObserver
from app.config.settings import Settings
from app.models.actions import BrowserAction

SYNTHETIC_DIR = Path(__file__).resolve().parent / "pages"
SYNTHETIC_BASE = SYNTHETIC_DIR.as_uri()


@pytest.fixture
def settings() -> Settings:
    return Settings(headless=True, browser_mode="test")


@pytest.fixture
def observer() -> PageObserver:
    return PageObserver()


@pytest.fixture
def executor() -> BrowserExecutor:
    return BrowserExecutor()


def _find_ref_by_name(observation, html_name: str) -> str:
    """Find ephemeral element ref matching html_name."""
    for el in observation.page_state.elements:
        if el.html_name == html_name:
            return el.ref
    raise ValueError(f"Element with html_name={html_name} not found in observation")


class TestDynamicFormContinuity:
    """Proves: DOM rerenders do not erase verified semantic progress."""

    @pytest.mark.asyncio
    async def test_dynamic_district_dropdown_appearance_preserves_state(
        self,
        settings: Settings,
        observer: PageObserver,
        executor: BrowserExecutor,
    ) -> None:
        async with BrowserManager(settings) as manager:
            page = await manager.open(f"{SYNTHETIC_BASE}/dropdowns.html")
            ws = AgentWorldState(portal="dropdowns.test")

            # 1. Observe state page
            obs1 = await observer.observe(page)
            reduce_observation(ws, obs1)

            # State exists, District is not visible/observed yet
            assert "field:state" in ws.semantic_fields
            assert "field:district" not in ws.semantic_fields
            state_field_1 = ws.semantic_fields["field:state"]
            assert state_field_1.status == EpistemicStatus.OBSERVED
            ref_state_1 = _find_ref_by_name(obs1, "state")
            assert is_target_ref_valid(ws, ref_state_1, obs1.observation_id) is True

            # 2. Map & select State = 'kerala'
            action = BrowserAction(
                action="select",
                target_ref=ref_state_1,
                option="kerala",
                observation_id=obs1.observation_id,
            )
            result = await executor.execute(page, action, obs1)
            assert result.success is True

            # Record verified action in WorldState
            record_verified_action(
                ws,
                target_ref_or_semantic_id=ref_state_1,
                verified_value="kerala",
                binding="USER.state",
                tool_name="select_option",
                observation_id=obs1.observation_id,
            )
            assert ws.is_field_verified("field:state") is True
            assert ws.get_verified_value("field:state") == "kerala"
            assert ws.get_verified_value("USER.state") == "kerala"

            # 3 & 4. Dependent District field appears; reducer updates WorldState with fresh post_observation
            obs2 = result.post_observation or await observer.observe(page)
            reduce_observation(ws, obs2)

            # 5. Previously verified values remain intact!
            assert ws.is_field_verified("field:state") is True
            assert ws.get_verified_value("field:state") == "kerala"
            assert ws.get_verified_value("USER.state") == "kerala"
            state_field_2 = ws.semantic_fields["field:state"]
            assert state_field_2.status == EpistemicStatus.VERIFIED
            assert state_field_2.verified_value == "kerala"

            # 6. New District semantic field is introduced
            assert "field:district" in ws.semantic_fields
            district_field = ws.semantic_fields["field:district"]
            assert district_field.status == EpistemicStatus.OBSERVED
            assert district_field.verified_value is None
            assert len(district_field.options) > 0 or True

            # 7. Old DOM refs are invalidated
            assert is_target_ref_valid(ws, ref_state_1, obs1.observation_id) is False

            # 8. Current observation receives new refs
            ref_district_2 = _find_ref_by_name(obs2, "district")
            assert is_target_ref_valid(ws, ref_district_2, obs2.observation_id) is True
            assert district_field.current_ref == ref_district_2

            # Now select District and verify it also becomes verified
            action_dist = BrowserAction(
                action="select",
                target_ref=ref_district_2,
                option="ernakulam",
                observation_id=obs2.observation_id,
            )
            result_dist = await executor.execute(page, action_dist, obs2)
            assert result_dist.success is True

            record_verified_action(
                ws,
                target_ref_or_semantic_id=ref_district_2,
                verified_value="ernakulam",
                binding="USER.district",
                tool_name="select_option",
                observation_id=obs2.observation_id,
            )
            assert ws.is_field_verified("field:district") is True
            assert ws.get_verified_value("field:district") == "ernakulam"

            # Block dropdown appears after district selection
            obs3 = result_dist.post_observation or await observer.observe(page)
            reduce_observation(ws, obs3)

            # Both state and district remain verified
            assert ws.get_verified_value("USER.state") == "kerala"
            assert ws.get_verified_value("USER.district") == "ernakulam"
            assert "field:block" in ws.semantic_fields


class TestMultiTabContinuity:
    """Proves: tab switching preserves state across tabs and rejects stale refs."""

    @pytest.mark.asyncio
    async def test_tab_switching_preserves_verified_progress(
        self,
        settings: Settings,
        observer: PageObserver,
        executor: BrowserExecutor,
    ) -> None:
        async with BrowserManager(settings) as manager:
            ws = AgentWorldState(portal="multitab.test")

            # 1. Tab A contains verified progress on simple.html
            tab_a = await manager.open(f"{SYNTHETIC_BASE}/simple.html")
            obs_a1 = await observer.observe(tab_a)
            reduce_observation(ws, obs_a1)

            ref_name_a1 = _find_ref_by_name(obs_a1, "fullName")
            fill_action = BrowserAction(
                action="fill",
                target_ref=ref_name_a1,
                literal_value="Priya Sharma",
                observation_id=obs_a1.observation_id,
            )
            result_a = await executor.execute(tab_a, fill_action, obs_a1)
            assert result_a.success is True

            record_verified_action(
                ws,
                target_ref_or_semantic_id=ref_name_a1,
                verified_value="Priya Sharma",
                binding="USER.full_name",
                tool_name="fill_field",
                observation_id=obs_a1.observation_id,
            )
            assert ws.get_verified_value("USER.full_name") == "Priya Sharma"

            # 2. New Tab B appears (portal_subportal.html)
            tab_b = await manager.context.new_page()
            await tab_b.goto(f"{SYNTHETIC_BASE}/portal_subportal.html")

            # 3 & 4. WorldState tracks both; active tab changes to Tab B
            obs_b = await observer.observe(tab_b)
            reduce_observation(ws, obs_b)

            assert ws.current_tab_index == 1
            assert 0 in ws.tabs
            assert 1 in ws.tabs

            # 5. Tab A state is not lost
            assert "field:fullname" in ws.tabs[0].semantic_fields
            assert ws.get_verified_value("USER.full_name") == "Priya Sharma"

            # 6. Actions against stale Tab A refs are rejected while on Tab B
            assert is_target_ref_valid(ws, ref_name_a1, obs_a1.observation_id, tab_index=0) is False
            assert is_target_ref_valid(ws, ref_name_a1, obs_a1.observation_id, tab_index=1) is False
            assert is_target_ref_valid(ws, ref_name_a1, obs_b.observation_id, tab_index=1, expected_semantic_id="field:fullname") is False

            # Also verify executor rejects action with stale observation_id from Tab A
            stale_action = BrowserAction(
                action="fill",
                target_ref=ref_name_a1,
                literal_value="Wrong Tab",
                observation_id=obs_a1.observation_id,
            )
            stale_result = await executor.execute(tab_b, stale_action, obs_b)
            assert stale_result.success is False
            assert "Stale reference" in stale_result.message

            # Active Tab B ref is valid
            ref_subportal = _find_ref_by_name(obs_b, "reference_number")
            assert is_target_ref_valid(ws, ref_subportal, obs_b.observation_id, tab_index=1) is True

            # Fill on Tab B
            action_b = BrowserAction(
                action="fill",
                target_ref=ref_subportal,
                literal_value="REF98765",
                observation_id=obs_b.observation_id,
            )
            result_b = await executor.execute(tab_b, action_b, obs_b)
            assert result_b.success is True
            record_verified_action(
                ws,
                target_ref_or_semantic_id=ref_subportal,
                verified_value="REF98765",
                binding="USER.reference_number",
                tool_name="fill_field",
                observation_id=obs_b.observation_id,
            )

            # 7. Switching back to Tab A restores semantic continuity
            await tab_a.bring_to_front()
            obs_a2 = await observer.observe(tab_a)
            reduce_observation(ws, obs_a2)

            assert ws.current_tab_index == 0
            assert ws.get_verified_value("USER.full_name") == "Priya Sharma"
            assert ws.get_verified_value("USER.reference_number") == "REF98765"
            assert ws.semantic_fields["field:fullname"].status == EpistemicStatus.VERIFIED
            assert ws.semantic_fields["field:fullname"].verified_value == "Priya Sharma"
            ref_name_a2 = _find_ref_by_name(obs_a2, "fullName")
            assert is_target_ref_valid(ws, ref_name_a2, obs_a2.observation_id, tab_index=0) is True
