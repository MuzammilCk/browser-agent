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
