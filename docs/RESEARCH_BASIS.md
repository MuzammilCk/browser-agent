# RESEARCH BASIS — Agent Runtime Architecture

## Purpose

This file records why the project uses a stateful hierarchical browser-agent architecture.

It is supporting evidence, not a replacement for AGENTS.md, context.md, or implementation_plan.md.

## Key conclusions

### 1. Workflow code is not the same as an agent

Modern agent guidance distinguishes predefined workflows from agents that dynamically select actions/tool usage based on environmental feedback.

Implication for this project:

- AgentRuntime must own a persistent decision loop.
- The LLM must select from typed tools.
- The runtime must preserve state across many iterations.

Source:
https://www.anthropic.com/engineering/building-effective-agents

### 2. ReAct is useful but insufficient alone

ReAct combines reasoning and environmental interaction.

Implication:

Use ReAct-style local execution inside a larger hierarchical runtime rather than building a pure next-action loop.

Source:
https://arxiv.org/abs/2210.03629

### 3. Explicit planning helps long-horizon tasks

Plan-and-Solve style approaches show the value of decomposing larger goals before solving individual steps.

Implication:

Use Goal → Plan → Subgoal, but allow the plan to be invalidated and revised after browser state changes.

Source:
https://arxiv.org/abs/2305.04091

### 4. Reflection/recovery should modify future behavior

Reflexion-style agents use feedback from failed attempts to change later decisions.

Implication:

A browser failure should create structured evidence and a strategy change, not simply another identical retry.

Source:
https://arxiv.org/abs/2303.11366

### 5. Human-in-the-loop requires durable runtime state

Modern agent runtimes treat approvals and interrupts as part of resumable state rather than a UI-only pause.

Implication:

OTP, CAPTCHA, authentication, confirmation and final-submit boundaries require durable checkpoints and resume semantics.

Sources:
https://openai.github.io/openai-agents-python/human_in_the_loop/
https://www.langchain.com/blog/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt

### 6. Tool calling is the correct LLM/application boundary

OpenRouter provides structured tool calling and interleaved model/tool execution.

Implication:

Move from LLM → BrowserAction to LLM → typed ToolCall → deterministic tool executor → ToolResult → LLM.

Source:
https://openrouter.ai/docs/guides/features/tool-calling

### 7. Structured model output is important

Strict structured outputs reduce malformed model decisions reaching deterministic execution code.

Implication:

All AgentDecision and tool inputs are schema validated before execution.

Source:
https://openrouter.ai/docs/guides/features/structured-outputs

### 8. Production agents need tracing and durable state

Current agent SDK architecture treats model calls, tools, guardrails and handoffs as traceable runtime events, and supports resumable run state.

Implication:

AgentEvent, state versioning, trace metadata and checkpoint persistence are first-class architecture concepts.

Sources:
https://openai.github.io/openai-agents-python/tracing/
https://openai.github.io/openai-agents-python/human_in_the_loop/

### 9. Agent security is different from ordinary web automation

OWASP's agentic-security guidance emphasizes risks including goal hijacking, excessive permissions/autonomy, tool misuse and privilege abuse.

Implication:

The model must not own policy, permissions, secret resolution, arbitrary execution or final irreversible actions.

Source:
https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/

### 10. Browser agents degrade on long, realistic tasks

Browser-agent research shows that multi-step web tasks are materially harder than single-page form filling, and real-world instability/attacks make them harder still.

Implication:

Evaluation must measure long-horizon workflow behavior, recovery, safety, and live-web robustness rather than a one-off successful form fill.

Sources:
https://arxiv.org/abs/2307.13854
https://arxiv.org/abs/2510.03285

## Reference codebase lessons

The supplied reference implementation was inspected for architecture patterns.

Useful patterns:

- persistent QueryEngine session state;
- explicit Task lifecycle;
- rich Tool metadata and input/output contracts;
- isolated subagent contexts;
- periodic session-memory extraction and compaction.

Do not copy unrelated code. Reproduce the architectural ideas inside this Python/Playwright system.

## Resulting project choice

Chosen architecture:

Stateful Hierarchical Browser Agent

Composition:

- primary persistent agent;
- ReAct-style execution loop;
- Goal/Plan/Subgoal;
- WorldState;
- typed Tool Registry;
- deterministic PolicyEngine;
- Playwright executor;
- verifier;
- reflection/recovery;
- structured memory;
- durable HITL interrupts;
- restricted specialist agents as tools.

This is the canonical architectural rationale for the implementation plan.
