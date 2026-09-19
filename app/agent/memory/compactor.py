"""Working-memory compaction — Phase 9.

Implements loss-aware, bounded working-memory compaction:
When working memory exceeds configured thresholds:
1. Identifies low-value historical context (old tool calls, past turns).
2. Preserves inviolable safety and task state:
   - current goal
   - current subgoal
   - verified WorldState facts
   - unresolved questions
   - active human interrupt state
   - pending approval bindings
   - key recent recovery/failure state
3. Summarizes eligible history.
4. Generates an EpisodicMemory milestone.
5. Replaces old working context with a compact representation.

Compaction must NOT mutate AgentWorldState or change browser observation.
"""

from __future__ import annotations

from app.agent.memory.models import (
    AuthorType,
    CompactionRecord,
    EpisodeOutcome,
    EpisodicMemory,
    MemoryProvenance,
    WorkingMemory,
    new_id,
    utc_now_iso,
)


class WorkingMemoryCompactor:
    """Loss-aware compactor for short-lived working memory."""

    def __init__(
        self,
        total_items_threshold: int = 15,
        preserve_recent_results: int = 2,
        preserve_recent_failures: int = 2,
        preserve_recent_turns: int = 2,
    ) -> None:
        self._threshold = total_items_threshold
        self._preserve_results = preserve_recent_results
        self._preserve_failures = preserve_recent_failures
        self._preserve_turns = preserve_recent_turns

    def should_compact(self, wm: WorkingMemory) -> bool:
        """Check if working memory has exceeded the configured item limit."""
        return wm.total_items_count() >= self._threshold

    def compact(
        self,
        wm: WorkingMemory,
        run_id: str,
        portal: str = "",
    ) -> tuple[WorkingMemory, EpisodicMemory | None, CompactionRecord]:
        """Perform loss-aware compaction on working memory."""
        pre_count = wm.total_items_count()

        # Inviolable facts to preserve
        preserved_goal = wm.goal
        preserved_subgoal = wm.subgoal
        preserved_verified_facts = dict(wm.verified_facts)
        preserved_unresolved = list(wm.unresolved_questions)
        preserved_interrupt = dict(wm.active_interrupt) if wm.active_interrupt else None
        preserved_approval = dict(wm.active_approval) if wm.active_approval else None

        # Identify items to compact vs retain
        compacted_results = wm.recent_tool_results[:-self._preserve_results] if len(wm.recent_tool_results) > self._preserve_results else []
        retained_results = wm.recent_tool_results[-self._preserve_results:]

        compacted_failures = wm.recent_failures[:-self._preserve_failures] if len(wm.recent_failures) > self._preserve_failures else []
        retained_failures = wm.recent_failures[-self._preserve_failures:]

        compacted_turns = wm.conversation_context[:-self._preserve_turns] if len(wm.conversation_context) > self._preserve_turns else []
        retained_turns = wm.conversation_context[-self._preserve_turns:]

        # Formulate concise summary of compacted history
        summary_parts = []
        if compacted_results:
            tools_used = [r.get("tool", "unknown") for r in compacted_results]
            success_count = sum(1 for r in compacted_results if r.get("success", False))
            summary_parts.append(
                f"Executed {len(compacted_results)} prior actions ({success_count} succeeded, tools: {', '.join(set(tools_used))})"
            )

        if compacted_failures:
            summary_parts.append(f"Encountered {len(compacted_failures)} past issues/recoveries")

        if compacted_turns:
            summary_parts.append(f"Processed {len(compacted_turns)} prior conversation turns")

        if not summary_parts:
            summary_parts.append("Prior execution steps compacted")

        incremental_summary = "; ".join(summary_parts)
        if wm.compacted_summary:
            total_compacted_summary = f"{wm.compacted_summary} | {incremental_summary}"
        else:
            total_compacted_summary = incremental_summary

        # Create updated bounded WorkingMemory
        new_wm = WorkingMemory(
            goal=preserved_goal,
            subgoal=preserved_subgoal,
            verified_facts=preserved_verified_facts,
            semantic_fields=list(wm.semantic_fields),
            recent_tool_results=retained_results,
            recent_failures=retained_failures,
            unresolved_questions=preserved_unresolved,
            active_interrupt=preserved_interrupt,
            active_approval=preserved_approval,
            conversation_context=retained_turns,
            compacted_summary=total_compacted_summary,
            is_compacted=True,
            max_tool_results=wm.max_tool_results,
            max_failures=wm.max_failures,
            max_conversation_turns=wm.max_conversation_turns,
        )

        # Create an episodic memory milestone if meaningful actions were compacted
        episode: EpisodicMemory | None = None
        if compacted_results or compacted_failures:
            episode = EpisodicMemory(
                episode_id=new_id("ep"),
                run_id=run_id,
                portal=portal,
                goal=preserved_goal,
                subgoal=preserved_subgoal,
                summary=f"Milestone: {incremental_summary}",
                key_events=[
                    {"type": "compacted_results", "count": len(compacted_results)},
                    {"type": "compacted_failures", "count": len(compacted_failures)},
                ],
                outcome=EpisodeOutcome.PAUSED if preserved_interrupt else EpisodeOutcome.SUCCESS,
                provenance=MemoryProvenance(
                    source="working_memory_compaction",
                    author_type=AuthorType.RUNTIME_VERIFIED,
                    run_id=run_id,
                    details={"pre_count": pre_count, "post_count": new_wm.total_items_count()},
                ),
            )

        record = CompactionRecord(
            compaction_id=new_id("cmp"),
            run_id=run_id,
            created_at=utc_now_iso(),
            pre_items_count=pre_count,
            post_items_count=new_wm.total_items_count(),
            preserved_keys=[
                "goal", "subgoal", "verified_facts", "unresolved_questions",
                "active_interrupt", "active_approval",
            ],
            compacted_summary=incremental_summary,
            metadata={
                "compacted_results_count": len(compacted_results),
                "compacted_failures_count": len(compacted_failures),
                "compacted_turns_count": len(compacted_turns),
            },
        )

        return new_wm, episode, record
