"""Phase 4 — relevance-ranked element selection for the LLM prompt (Z4).

The flat ``elements[:120]`` slice truncates by DOM position, so on dense
portals the task-relevant link can sit at position #150 and never reach
the model. Ranking must select by task-keyword overlap, always retain
in-progress binding targets regardless of rank, and keep the memory cap.
"""

from __future__ import annotations

from app.agent.planner import (
    _MAX_ELEMENTS_FOR_LLM, _select_elements_for_llm, _task_keywords,
)


def _el(ref: str, name: str) -> dict:
    return {
        "ref": ref, "role": "link", "name": name,
        "value": "", "required": False, "disabled": False,
    }


def _filler(start: int, count: int) -> list[dict]:
    return [_el(f"e{i}", f"Menu item {i}") for i in range(start, start + count)]


class TestTaskKeywords:
    def test_common_words_and_stopwords_dropped(self):
        kws = _task_keywords("Download the Aadhaar card from the portal")
        assert "aadhaar" in kws and "download" in kws
        assert "the" not in kws and "from" not in kws

    def test_empty_task_yields_no_keywords(self):
        assert _task_keywords("") == set()


class TestRankedSelection:
    def test_relevant_element_beyond_cap_is_retained(self):
        """Acceptance criterion: task-relevant link at DOM #150 survives."""
        elements = _filler(0, 150)
        target = _el("e150", "Download Aadhaar")
        elements.append(target)                      # position #150
        elements.extend(_filler(151, 60))            # 211 total > 120

        selected, truncated = _select_elements_for_llm(
            elements, _task_keywords("Download Aadhaar card"), protected_refs=set(),
        )

        assert truncated is True
        assert len(selected) == _MAX_ELEMENTS_FOR_LLM
        assert any(el["ref"] == "e150" for el in selected), (
            "task-relevant element beyond the flat cutoff was dropped"
        )

    def test_under_cap_returns_all_in_dom_order(self):
        elements = _filler(0, 50)
        selected, truncated = _select_elements_for_llm(
            elements, _task_keywords("Download Aadhaar"), protected_refs=set(),
        )
        assert truncated is False
        assert [el["ref"] for el in selected] == [f"e{i}" for i in range(50)]

    def test_bound_field_protected_regardless_of_rank(self):
        """An in-progress binding target must never be truncated away."""
        elements = _filler(0, 200)
        bound = _el("e185", "Some Form Field")       # no keyword overlap
        elements.append(bound)

        selected, truncated = _select_elements_for_llm(
            elements, _task_keywords("Download Aadhaar"),
            protected_refs={"e185"},
        )

        assert truncated is True
        assert any(el["ref"] == "e185" for el in selected)

    def test_higher_overlap_wins_over_lower(self):
        """With cap pressure, ranked selection retains both scored
        elements and drops a zero-scorer — a flat DOM slice would keep
        the weak one and lose the strong one entirely."""
        elements = _filler(0, 119)
        weak = _el("w1", "Aadhaar")                          # 1 overlapping token
        strong = _el("s1", "Download Aadhaar Card Online")   # 3 tokens
        elements.insert(50, weak)
        elements.append(strong)
        assert len(elements) == 121

        selected, truncated = _select_elements_for_llm(
            elements, _task_keywords("Download Aadhaar Card Online"),
            protected_refs=set(),
        )

        assert truncated is True
        assert len(selected) == _MAX_ELEMENTS_FOR_LLM
        refs = [el["ref"] for el in selected]
        # Both survive; exactly one zero-overlap element was cut instead.
        assert "s1" in refs and "w1" in refs
        dropped = set(refs) ^ {el["ref"] for el in elements}
        assert len(dropped) == 1
        dropped_ref = next(iter(dropped))
        assert dropped_ref not in ("s1", "w1")

    def test_cap_still_enforced_with_no_keyword_overlap(self):
        elements = _filler(0, 300)
        selected, truncated = _select_elements_for_llm(
            elements, _task_keywords("zzzqqq"), protected_refs=set(),
        )
        assert truncated is True
        assert len(selected) == _MAX_ELEMENTS_FOR_LLM
        # No signal to rank by → deterministic DOM-order prefix
        assert selected[0]["ref"] == "e0"
