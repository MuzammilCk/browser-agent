"""Isolated memory summarizer — Phase 9.

Performs LLM-assisted or rule-assisted memory extraction and summarization
in a strictly isolated context.

Invariants:
- The summarizer receives ONLY explicitly selected material.
- It holds NO browser handles, NO tool execution power, NO policy handles, and cannot mutate WorldState.
- Model output is strictly validated against schemas before becoming memory candidates.
- If summarization fails:
  - Preserves original context intact.
  - Emits explicit error.
  - Never fabricates a summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, Field


class SummarizationResult(BaseModel):
    """Validated structured output of an isolated summarization run."""

    success: bool
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    error_message: str = ""


class IsolatedSummarizer:
    """Sandboxed summarizer with zero browser, policy, or execution privileges."""

    def __init__(
        self,
        llm_fn: Callable[[str], str] | None = None,
    ) -> None:
        """Initialize with an optional isolated LLM callable.

        The callable must accept a prompt string and return a JSON string.
        It has NO access to tools, browsers, or runtime state.
        """
        self._llm_fn = llm_fn

    def summarize(
        self,
        items: list[dict[str, Any]],
        context_label: str = "workflow_events",
    ) -> SummarizationResult:
        """Summarize selected items in isolation.

        Fails safely if inputs are invalid or the model call fails.
        """
        if not items:
            return SummarizationResult(
                success=True,
                summary="No prior items to summarize.",
                key_points=[],
            )

        # 1. Deterministic formatting of input items
        serialized_items = json.dumps(items, indent=2)

        # 2. If no LLM callable is configured, use deterministic structured condensation
        if self._llm_fn is None:
            actions = [item.get("tool") or item.get("type", "event") for item in items]
            summary_str = f"Consolidated {len(items)} {context_label}: {', '.join(set(actions))}"
            key_points = [f"{k}: {v}" for item in items[:5] for k, v in item.items() if k in ("tool", "error_code", "status")]
            return SummarizationResult(
                success=True,
                summary=summary_str,
                key_points=key_points[:5],
            )

        # 3. LLM-assisted summarization in sandbox
        prompt = (
            f"You are an isolated memory summarizer. Summarize the following {context_label} "
            f"into concise factual points without fabricating details:\n{serialized_items}\n"
            f"Respond with JSON: {{\"summary\": \"...\", \"key_points\": [\"...\"]}}"
        )

        try:
            raw_output = self._llm_fn(prompt)
            data = json.loads(raw_output)
            if not isinstance(data, dict) or "summary" not in data:
                return SummarizationResult(
                    success=False,
                    error_message="Summarizer output was not a valid summary object.",
                )
            return SummarizationResult(
                success=True,
                summary=str(data.get("summary", "")),
                key_points=[str(p) for p in data.get("key_points", []) if isinstance(p, str)],
            )
        except Exception as e:
            # Preservation guarantee: never fabricate on error, preserve original context
            return SummarizationResult(
                success=False,
                error_message=f"Summarization failed: {type(e).__name__}: {e}",
            )
