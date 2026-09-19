# ARCHITECTURE DECISIONS

## D001 — Stateful hierarchical browser agent

Build a stateful hierarchical browser agent rather than a single-shot planner or generic swarm.

Status: ACCEPTED

## D002 — One primary browser controller

One primary agent owns browser mutation. Specialists are agent-as-tools.

Status: ACCEPTED

## D003 — LLM proposes; deterministic runtime authorizes

The LLM cannot own the security or execution boundary.

Status: ACCEPTED

## D004 — Typed tool registry

The model-facing interface is a typed Tool Registry with schemas and permission metadata.

Status: ACCEPTED

## D005 — Semantic state survives DOM changes

WorldState is durable; DOM refs are ephemeral.

Status: ACCEPTED

## D006 — Durable human interrupts

OTP/CAPTCHA/auth/legal/payment/final confirmation are persistent workflow checkpoints.

Status: ACCEPTED

## D007 — Local secret resolution

Sensitive values are resolved locally at execution time.

Status: ACCEPTED

## D008 — Verification is mandatory

Successful Playwright invocation is not equivalent to successful workflow transition.

Status: ACCEPTED

## D009 — Structured memory before vector search

Start with structured memory and add vector retrieval only if evaluation proves value.

Status: ACCEPTED

## D010 — Generic automation before portal scripts

Prefer generic semantics plus small adapters for true exceptions.

Status: ACCEPTED

## D011 — No authentication or payment bypass

CAPTCHA, OTP, password/PIN, biometric, payment and final irreversible actions remain human-controlled as specified by policy.

Status: ACCEPTED

## D012 — Current HEAD evidence only

Historical audit claims must be reverified against the current repository before being used as completion evidence.

Status: ACCEPTED

## D013 — Model guardrail override is opt-in via environment variable

The Z6 model guard (`_vault_model_guard` in `app/api/routes.py`) refuses free-tier/anonymous OpenRouter models when the vault is populated, unless `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true`. This override defaults to `false` to ensure fail-closed behavior. The `.env` must match `.env.example` defaults for tests to pass.

Status: ACCEPTED — implemented fix in `.env` (set `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=false`)

## D014 — Lifecycle transitions are table-validated; external jumps walk a deterministic path

Phase 2 runtime (Phase 2 work, 2026-09-19):

1. Every lifecycle change is validated against an explicit `LIFECYCLE_TRANSITIONS`
   table (`app/agent/runtime/state.py`); an illegal single-step transition raises
   `InvalidLifecycleTransition` — never coerced (fail closed).
2. The existing `AgentRunner` mutates `WorkflowStatus` and can skip several
   runtime states at once (e.g. RUNNING → READY_FOR_CONFIRMATION on a sensitive
   fill). Rather than loosening the table, `AgentRuntime.transition_toward` walks
   the shortest path through legal intermediate states using a BFS whose neighbor
   order is the enum definition order — deterministic and event-per-hop auditable.
3. `WAITING_FOR_AUTH` / `WAITING_FOR_CAPTCHA` collapse into the runtime's single
   `WAITING_FOR_USER` state; the distinguishing cause lives in `PendingInterrupt.kind`
   and the workflow state.
4. Checkpoints capture the `CHECKPOINT_CREATED` event BEFORE snapshotting, so a
   restored run's event log contains the record of its own checkpoint.
5. Deferred deliberately (with the phase that owns them): `AgentDecision.HANDOFF`
   (Phase 10 specialists), typed plan models — plan stays `list[dict]` (Phase 5),
   SQLite checkpoint store (Phase 8 durable interrupts), memory contents behind
   `MemoryHandles` (Phase 9). The WorldState handle is the existing `WorkflowState`;
   the full `AgentWorldState` expansion is Phase 6.

Status: ACCEPTED — implemented in `app/agent/runtime/runtime.py`, covered by
`tests/unit/test_agent_runtime.py` (48 tests).

## D015 — Tool metadata is descriptive; PolicyEngine stays authoritative (Phase 3)

Phase 3 Tool Registry (2026-09-19):

1. Tool metadata (`read_only`, `policy_class`, etc.) is DESCRIPTIVE — it feeds
   the Phase 4 model catalog and defense-in-depth checks. It never authorizes
   or bypasses anything: the authoritative risk classification still happens
   in `PolicyEngine.evaluate()` against the concrete BrowserAction + live page
   state. A tool cannot downgrade its own policy by declaring a lower class.
2. The registry is the ONLY decision→tool path and fails closed at every step
   (unknown tool, schema-invalid arguments, stray/missing BrowserAction,
   missing fresh observation). Schema validation happens at both boundaries
   (Tool base AND registry) — defense in depth, not redundancy.
3. Tools are ADAPTERS, not replacements: every mutation delegates to
   `BrowserExecutor.execute()` (stale-ref → policy → document policy →
   Playwright → re-observe → verify), so the Phase 1-verified safety loop is
   reused verbatim and cannot be bypassed by construction. Zero policy or
   verification logic is duplicated in the tools layer.
4. Only executor-backed tools accept a typed BrowserAction
   (`accepts_browser_action`); read-only browser tools (observe/inspect)
   take none. A stray action on any other tool is rejected — it would smuggle
   an unvetted execution path past the tool's own schema.
5. Tools receive only a `ToolContext` (observation, page, executor, observer,
   resolvers). There is no path from a tool to `AgentRunState`: tools cannot
   mutate run state, lifecycle, events, or checkpoints — the runtime observes
   ToolResults and updates state itself.
6. Mutating tools return the executor's fresh `post_observation` and the tool
   context advances to it, so the next decision always targets current
   browser state (browser = source of truth). A REFRESHED failure (goal
   failed but page changed) still updates the observation — pretending the
   page didn't change would poison the next decision.
7. `ToolResult` promotes policy + verification facts (`policy_allowed`,
   `verification_status`, error-code taxonomy) to first-class fields so the
   Phase 4 reasoner can see WHY a call failed without parsing free text.
8. Vault tools return resolution HANDLES, never raw sensitive values; the
   executor re-resolves locally at execution time (sensitive-data path).

Status: ACCEPTED — implemented in `app/agent/tools/*`, covered by
`tests/unit/test_tool_registry.py` (31 tests) and
`tests/synthetic_forms/test_tool_agent.py` (4 tests, real Chromium).
