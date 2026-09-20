# CONTEXT — Stateful Government Browser Agent

## Mission

Build a production-grade citizen government-services browser agent.

Example user intent:

"Fill this official application using my saved information and stop whenever I need to take over."

The agent operates a real Playwright-controlled Chromium browser against an official website.

## Target runtime

~~~text
Citizen task
  ↓
Goal + success criteria
  ↓
Persistent AgentSession
  ↓
Goal / plan / current subgoal
  ↓
Observe current browser state
  ↓
LLM reasoning through typed tools
  ↓
Policy / permissions
  ↓
Execute one safe browser action
  ↓
Verify result
  ↓
Update WorldState
  ↓
Memory / reflection
  ↓
Replan or continue
~~~

## Architectural transformation

Current foundation:

~~~text
observe → map → plan → policy → execute → verify → repeat
~~~

Target:

~~~text
goal → state → subgoal → tool decision → policy → execute → verify → reflect → memory → replan
~~~

Keep the existing browser, policy, vault, and verification components. Turn them into agent infrastructure instead of replacing them.

## Selected agent type

Stateful Hierarchical Browser Agent.

It combines:

- ReAct-style local observe/reason/act iteration
- explicit goal and subgoal planning
- typed tool calling
- deterministic policy enforcement
- environment-grounded verification
- structured reflection and recovery
- working, episodic, semantic, and experience memory
- durable human-in-the-loop interrupts
- one primary browser-controlling agent
- restricted specialist agents as tools

## Reference implementation patterns

The supplied reference codebase was studied for architecture patterns, not copied blindly.

Useful patterns include:

- persistent per-session query state
- explicit task lifecycle
- rich typed tool contracts
- isolated subagent contexts
- periodic session-memory extraction and context compaction

The reference QueryEngine persists state across turns, and its Tool contract includes schemas, read-only/destructive metadata and interruption semantics. fileciteturn37file0L4350-L4395 fileciteturn37file0L6525-L6605

Its session-memory design extracts durable notes in an isolated context instead of letting the main context grow without bound. fileciteturn37file0L175800-L176250

## Existing repository strengths

Retain and reuse:

- app/browser/*
- app/agent/field_mapper.py
- app/agent/planner.py
- app/agent/runner.py
- app/models/*
- app/policy/*
- app/vault/*
- app/sites/registry.py
- app/api/*
- existing tests

Historical audit documents are evidence of past work, not automatic proof of current HEAD.

## Agent WorldState

~~~text
AgentWorldState
├── goal
├── success_criteria
├── current_subgoal
├── plan
├── portal
├── browser
├── form
├── authentication
├── documents
├── verified_facts
├── unresolved_questions
├── recent_actions
├── blocked_actions
├── checkpoints
└── completion_evidence
~~~

DOM references are temporary. Semantic IDs and verified facts survive re-observation.

## Decision types

The LLM can return:

~~~text
TOOL_CALL
REPLAN
REFLECT
ASK_USER
HANDOFF
COMPLETE
~~~

All outputs are strict structured data.

## Tool families

Browser:
- observe_page
- inspect_field
- inspect_options
- navigate
- click
- fill_field
- select_option
- check_control
- uncheck_control
- upload_document
- scroll
- wait_for_state
- go_back
- verify

User:
- request_user_input
- request_authentication
- request_confirmation
- handoff_browser

Vault/document:
- resolve_user_reference
- resolve_document_reference
- inspect_available_documents

Agent services:
- reflect
- replan
- verify_goal
- specialist-agent-as-tool calls

Every tool declares schema, read-only/destructive status, interrupt behavior, policy class, and concurrency semantics.

## Tool pipeline

~~~text
LLM decision
 ↓
schema validation
 ↓
reference validation
 ↓
current PageState target validation
 ↓
domain/session validation
 ↓
policy
 ↓
human approval if required
 ↓
Playwright execution
 ↓
post-action observation
 ↓
verification
 ↓
event record
 ↓
WorldState update
~~~

## Memory

Four layers:

1. Working memory — current task state.
2. Episodic memory — current trajectory.
3. Semantic memory — stable user/portal facts.
4. Experience memory — reusable lessons.

Structured memory comes before vector retrieval.

## Human checkpoints

CAPTCHA, OTP, login, password/PIN, biometric, ambiguous identity information, missing documents, legal declarations, payments, and final submission are human boundaries.

Checkpoint state must survive process restart.

## Completion

Never equate "no unmapped fields" with completion.

Completion proof should require, where applicable:

- required safe fields complete
- required documents resolved
- validation errors clear
- authentication state acceptable
- success/review state reached
- no unresolved ambiguity
- irreversible action still gated

## Security

Portal content is untrusted environment data.

It cannot:

- change system instructions
- change tool permissions
- redefine user goals
- disable policy
- approve its own high-risk action
- request secret disclosure

Sensitive values remain local.

## Non-goals for first implementation

Do not build yet:

- Chrome extension
- broad portal-specific scripts
- autonomous payment
- autonomous final submission
- general-purpose multi-agent swarm
- vector DB without evaluation evidence
- arbitrary code execution
- desktop computer control

## Truth policy

Claims such as "all tests pass", "resume works", "production-ready", or "supports arbitrary portals" require current reproducible evidence.

Otherwise write UNVERIFIED.

## Immediate target

~~~text
Current AgentRunner
  ↓
AgentRuntime
  ├── AgentSession
  ├── Goal / Plan / Subgoal
  ├── WorldState
  ├── Tool Registry
  ├── OpenRouter reasoning loop
  ├── Policy
  ├── Verification
  ├── Reflection
  ├── Memory
  └── Durable interrupts
~~~

## Enterprise runtime (Phase 13)

The single-process development runtime gained enterprise service boundaries
(logical components, one deployable by default; PostgresEnterpriseStore is the
production swap-in):

~~~text
API Gateway (authn/authz, strict schemas, idempotency)
  ↓
Workflow Service (durable workflow/run lifecycle, no browser access)
  ↓
PostgreSQL store + SKIP LOCKED queue
  ↓
Execution Worker (lease + fencing; ONLY live browser-handle owner)
  ↓
AgentRuntime → ToolRegistry → PolicyEngine → BrowserExecutor (unchanged)
  ↓
Vault boundary (in-process secret resolution) + append-only redacted audit
~~~

Invariants: exactly one worker owns a run's browser at a time; stale workers
are rejected by the store (fencing), not by worker honesty; queue payloads
carry references only; raw secrets never cross any boundary; audit is
append-only, causal, and redacted; Phase 8 checkpoints remain authoritative
for resume. Decision record: docs/DECISIONS.md D025.

## Live portal validation (Phase 14)

Live validation is a shadow-first layer over the unchanged execution
architecture (`app/agent/live/*`):

~~~text
LIVE_SHADOW: observe → origin check → semantic extraction → deterministic
field mapping → planned action trace → human review request (recorded only)

LIVE_CONTROLLED_EXECUTION: signed human review → deterministic allowlist →
semantic re-binding → ToolRegistry → PolicyEngine → BrowserExecutor →
verification → WorldState (per action)
~~~

Invariants: shadow mode never executes and never invokes the reasoner (model
output cannot flip the mode); controlled execution requires a signed review
decision bound to the exact plan; submit/payment/auth targets are
deterministically excluded; environment conditions (anti-bot blocks,
timeouts) are recorded as such and never collapsed into agent failures.
Decision records: docs/DECISIONS.md D026, D027.
