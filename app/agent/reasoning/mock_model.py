"""Deterministic mock decision model — Phase 4 test infrastructure.

A scripted stand-in for the LLM. It implements the SAME DecisionModel
protocol the OpenRouter adapter implements, so tests can prove the whole
reasoner → parser → AgentDecision boundary without any API key. Scripts
are exact: each entry is either a raw decision dict (returned verbatim)
or an Exception instance (raised), consumed one per `decide` call.

The reasoner's retry loop sends the SAME context each attempt (plus the
rejection reason on repairs), so a script that returns invalid output on
attempt 1 and a valid decision on attempt 2 deterministically proves the
repair path without flaky matching.
"""

from __future__ import annotations

from typing import Any

from app.agent.reasoning.protocol import DecisionModel


class MockDecisionModel:
    """Scripted DecisionModel: one script entry per model call."""

    def __init__(self, script: list[Any]) -> None:
        """``script`` entries are raw decision dicts or Exception instances."""
        self.script = list(script)
        self.calls: list[dict[str, str]] = []

    async def decide(self, *, system: str, context: str) -> dict[str, Any]:
        self.calls.append({"system": system, "context": context})
        if not self.script:
            raise AssertionError(
                "MockDecisionModel: script exhausted — more decide() calls "
                "than scripted entries"
            )
        entry = self.script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        if callable(entry):
            # Scripted function: (system, context) → decision dict. Lets a
            # mock "read" the observation and compute refs deterministically.
            result = entry(system=system, context=context)
            if hasattr(result, "__await__"):
                result = await result
            return result
        if not isinstance(entry, dict):
            raise AssertionError(
                f"MockDecisionModel: script entry must be dict, callable or "
                f"Exception, got {type(entry).__name__}"
            )
        return entry

    @property
    def call_count(self) -> int:
        return len(self.calls)
