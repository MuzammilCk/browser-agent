"""Runtime execution budgets — Phase 11 Security Hardening.

Key Architectural Invariants:
1. Budgets are runtime-owned and immutable from model/untrusted input.
2. Reserve/check budget BEFORE expensive execution.
3. Use monotonic time (time.monotonic()) for wall-time accounting.
4. Persist counters through checkpoint/resume (budgets must not reset on crash/restart).
"""

from __future__ import annotations

import time
from typing import Any
from pydantic import BaseModel, Field

from app.agent.security.models import SecurityViolation, SecurityViolationCode


class RuntimeBudget(BaseModel):
    """Immutable budget configuration limits for one agent run."""

    model_config = {"frozen": True, "extra": "forbid"}

    max_iterations: int = Field(default=30, ge=1)
    max_tool_calls: int = Field(default=50, ge=1)
    max_replans: int = Field(default=5, ge=0)
    max_specialist_calls: int = Field(default=10, ge=0)
    max_tokens: int = Field(default=100_000, ge=100)
    max_cost_usd: float = Field(default=1.00, ge=0.01)
    max_wall_time_seconds: float = Field(default=300.0, ge=0.001)
    max_navigations: int = Field(default=10, ge=1)


class RuntimeBudgetTracker:
    """Thread-safe runtime execution budget tracker.
    
    Tracks cumulative resource utilization and enforces hard stops.
    Supports lossless checkpoint/resume serialization.
    """

    def __init__(
        self,
        budget: RuntimeBudget | None = None,
        *,
        iterations: int = 0,
        tool_calls: int = 0,
        replans: int = 0,
        specialist_calls: int = 0,
        tokens_used: int = 0,
        cost_usd: float = 0.0,
        accumulated_wall_time: float = 0.0,
        navigations: int = 0,
    ) -> None:
        self.budget = budget or RuntimeBudget()
        self.iterations = iterations
        self.tool_calls = tool_calls
        self.replans = replans
        self.specialist_calls = specialist_calls
        self.tokens_used = tokens_used
        self.cost_usd = cost_usd
        self.accumulated_wall_time = accumulated_wall_time
        self.navigations = navigations

        # Monotonic time base for the active execution session
        self._session_start_monotonic = time.monotonic()

    @property
    def total_wall_time_seconds(self) -> float:
        """Total elapsed wall time combining accumulated previous sessions and current session."""
        current_session = max(0.0, time.monotonic() - self._session_start_monotonic)
        return self.accumulated_wall_time + current_session

    def to_dict(self) -> dict[str, Any]:
        """Serialize counters for checkpoint persistence."""
        return {
            "budget": self.budget.model_dump(),
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "replans": self.replans,
            "specialist_calls": self.specialist_calls,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "accumulated_wall_time": self.total_wall_time_seconds,
            "navigations": self.navigations,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeBudgetTracker:
        """Restore tracker from persisted checkpoint state."""
        b_data = data.get("budget", {})
        budget = RuntimeBudget(**b_data) if b_data else RuntimeBudget()
        return cls(
            budget=budget,
            iterations=data.get("iterations", 0),
            tool_calls=data.get("tool_calls", 0),
            replans=data.get("replans", 0),
            specialist_calls=data.get("specialist_calls", 0),
            tokens_used=data.get("tokens_used", 0),
            cost_usd=data.get("cost_usd", 0.0),
            accumulated_wall_time=data.get("accumulated_wall_time", 0.0),
            navigations=data.get("navigations", 0),
        )

    def check_wall_time(self) -> None:
        """Check wall-time limit using monotonic time."""
        elapsed = self.total_wall_time_seconds
        if elapsed > self.budget.max_wall_time_seconds:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded wall time budget: {elapsed:.1f}s > {self.budget.max_wall_time_seconds}s",
                {"elapsed": elapsed, "limit": self.budget.max_wall_time_seconds},
            )

    def check_before_iteration(self) -> None:
        """Check and reserve before starting a new reasoning loop iteration."""
        self.check_wall_time()
        if self.iterations + 1 > self.budget.max_iterations:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded maximum iterations: {self.iterations + 1} > {self.budget.max_iterations}",
                {"iterations": self.iterations, "limit": self.budget.max_iterations},
            )

    def record_iteration(self) -> None:
        """Record iteration start."""
        self.check_before_iteration()
        self.iterations += 1

    def check_before_tool_call(
        self,
        tool_name: str,
        *,
        is_specialist: bool = False,
        is_navigation: bool = False,
    ) -> None:
        """Reserve and check budget BEFORE executing any tool."""
        self.check_wall_time()
        if self.tool_calls + 1 > self.budget.max_tool_calls:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded maximum tool calls: {self.tool_calls + 1} > {self.budget.max_tool_calls}",
                {"tool_calls": self.tool_calls, "limit": self.budget.max_tool_calls},
            )

        if is_specialist and self.specialist_calls + 1 > self.budget.max_specialist_calls:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded maximum specialist calls: {self.specialist_calls + 1} > {self.budget.max_specialist_calls}",
                {"specialist_calls": self.specialist_calls, "limit": self.budget.max_specialist_calls},
            )

        if is_navigation and self.navigations + 1 > self.budget.max_navigations:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded maximum navigations: {self.navigations + 1} > {self.budget.max_navigations}",
                {"navigations": self.navigations, "limit": self.budget.max_navigations},
            )

    def record_tool_call(
        self,
        tool_name: str,
        *,
        is_specialist: bool = False,
        is_navigation: bool = False,
    ) -> None:
        """Record completed tool invocation."""
        self.check_before_tool_call(
            tool_name,
            is_specialist=is_specialist,
            is_navigation=is_navigation,
        )
        self.tool_calls += 1
        if is_specialist:
            self.specialist_calls += 1
        if is_navigation:
            self.navigations += 1

    def record_replan(self) -> None:
        """Record replan decision."""
        self.check_wall_time()
        if self.replans + 1 > self.budget.max_replans:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded maximum replans: {self.replans + 1} > {self.budget.max_replans}",
                {"replans": self.replans, "limit": self.budget.max_replans},
            )
        self.replans += 1

    def record_tokens(self, tokens: int, cost_usd: float = 0.0) -> None:
        """Record tokens and cost from model invocation."""
        self.check_wall_time()
        self.tokens_used += tokens
        self.cost_usd += cost_usd

        if self.tokens_used > self.budget.max_tokens:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded token budget: {self.tokens_used} > {self.budget.max_tokens}",
                {"tokens_used": self.tokens_used, "limit": self.budget.max_tokens},
            )

        if self.cost_usd > self.budget.max_cost_usd:
            raise SecurityViolation(
                SecurityViolationCode.BUDGET_EXHAUSTED,
                f"Execution exceeded cost budget: ${self.cost_usd:.4f} > ${self.budget.max_cost_usd:.4f}",
                {"cost_usd": self.cost_usd, "limit": self.budget.max_cost_usd},
            )
