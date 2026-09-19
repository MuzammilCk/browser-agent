"""User-interaction tools — Phase 3 (context.md "User" tool family).

These tools surface human checkpoints: user input, authentication,
confirmation. They perform NO browser mutation and NO policy logic —
they normalize the request into a ToolResult whose payload the runtime
turns into a durable interrupt (runtime.raise_interrupt, Phase 2 path).

Phase 3 note: handoff_browser is deliberately absent — specialists are
Phase 10 and handoff decisions are not accepted by AgentDecision yet.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.base import (
    Concurrency,
    InterruptBehavior,
    PolicyClass,
    RequestUserOutput,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolResult,
)
from app.agent.tools.browser_tools import _BrowserTool  # shared error helper


class _RequestInput(BaseModel):
    reason: str = Field(
        min_length=1, description="Why the user must act right now",
    )
    question: str = Field(
        default="", description="Specific question for the user (input requests)",
    )


class RequestUserInputTool(_BrowserTool):
    metadata = ToolMetadata(
        name="request_user_input",
        description=(
            "Ask the user a question or for information the agent cannot "
            "decide alone (ambiguous field, missing value). The run pauses "
            "until the user answers; the answer arrives as a runtime event."
        ),
        family="user",
        input_schema=_RequestInput,
        output_schema=RequestUserOutput,
        read_only=True,
        requires_user_interaction=True,
        interrupt_behavior=InterruptBehavior.PAUSES_RUN,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.SHARED,
    )

    async def run(self, args: _RequestInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        output = RequestUserOutput(
            interrupt_kind="user_input",
            question=args.question or args.reason,
            description=args.reason,
        )
        return self.success(
            call, output, f"User input requested: {args.question or args.reason}", ctx=ctx,
        )


class RequestAuthenticationTool(_BrowserTool):
    metadata = ToolMetadata(
        name="request_authentication",
        description=(
            "Hand control to the user for an authentication step (login, "
            "OTP, CAPTCHA, password/PIN). The agent never fills or bypasses "
            "these — this is a hard human boundary."
        ),
        family="user",
        input_schema=_RequestInput,
        output_schema=RequestUserOutput,
        read_only=True,
        requires_user_interaction=True,
        interrupt_behavior=InterruptBehavior.PAUSES_RUN,
        policy_class=PolicyClass.AUTHENTICATION,
        concurrency=Concurrency.SHARED,
    )

    async def run(self, args: _RequestInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        output = RequestUserOutput(
            interrupt_kind="authentication",
            question=args.question or args.reason,
            description=args.reason,
        )
        return self.success(
            call, output, f"Authentication requested: {args.reason}", ctx=ctx,
        )


class RequestConfirmationTool(_BrowserTool):
    metadata = ToolMetadata(
        name="request_confirmation",
        description=(
            "Ask the user to confirm a specific pending action (sensitive "
            "fill, upload, payment-related click, final submission). The "
            "run pauses; execution continues only after explicit approval."
        ),
        family="user",
        input_schema=_RequestInput,
        output_schema=RequestUserOutput,
        read_only=True,
        destructive=False,
        requires_user_interaction=True,
        interrupt_behavior=InterruptBehavior.PAUSES_RUN,
        policy_class=PolicyClass.HIGH_RISK,
        concurrency=Concurrency.SHARED,
    )

    async def run(self, args: _RequestInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        output = RequestUserOutput(
            interrupt_kind="confirmation",
            question=args.question or args.reason,
            description=args.reason,
        )
        return self.success(
            call, output, f"Confirmation requested: {args.reason}", ctx=ctx,
        )


USER_TOOL_CLASSES = [
    RequestUserInputTool,
    RequestAuthenticationTool,
    RequestConfirmationTool,
]
