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

## D016 — Phase 4 reasoner boundary: model proposes JSON, runtime owns everything else

Phase 4 (2026-09-19):

1. The model's ONLY capability is the `DecisionModel` protocol (system
   prompt + bounded context in, parsed JSON out). The AgentReasoner holds
   only frozen tool-name sets — never the ToolRegistry, executor, page,
   or run state — so the reasoner cannot execute anything by construction.
2. Model output is untrusted data: ReasonerDecisionSchema (strict,
   extra=forbid) → decision-type allow-list → registered-tool check →
   typed BrowserAction → AgentDecision, then ToolRegistry re-validates
   everything again (defense in depth; D015 gates are unchanged).
3. Structured OUTPUT schema (response_format json_schema, strict) was
   chosen over OpenRouter native function-calling: the prompt contract
   and validation contract are the same pydantic model
   (build_decision_json_schema), decisions stay one-per-iteration, and
   the existing ToolRegistry remains the only decision→tool path.
4. Model failures are EXPLICIT: bounded retries (default 3, cap 5) with
   the rejection reason fed back on repair attempts; exhaustion returns
   ReasoningOutcome.model_failure (code DECISION_PARSE_FAILED /
   DECISION_SCHEMA_INVALID / DECISION_VALIDATION_FAILED, reason prefixed
   `model_failure:`, decision=None). No deterministic decision is ever
   fabricated (AGENT_PROTOCOL.md: no silent fallback).
5. The parser stamps the CURRENT authoritative observation_id onto every
   browser action; a stale id in the model's dict is overwritten, never
   trusted. Refs must still exist in that observation (registry +
   executor verify) — the model cannot smuggle browser state.
6. Context assembly is minimal and key-whitelisted: recent ToolResult
   payloads pass through a fixed safe-key list (value-bearing keys like
   `resolved_value` can never reach the prompt), element/visible-text/
   result caps are enforced, and only semantic reference NAMES (with
   sensitivity labels) are exposed — never values, paths, or policy
   internals.
7. The OpenRouter adapter is the only OpenRouter touchpoint and fails
   closed at build time without an API key; the loop itself is proven by
   the deterministic MockDecisionModel (no key required for tests).

Status: ACCEPTED — implemented in `app/agent/reasoning/*`, covered by
`tests/unit/test_agent_reasoner.py` (28),
`tests/unit/test_reasoning_replay.py` (6),
`tests/unit/test_openrouter_decision_model.py` (10), and
`tests/synthetic_forms/test_reasoning_loop.py` (4, real Chromium).

## D017 — Strategic planning is deterministic state; the reasoner stays tactical

Phase 5 (2026-09-19):

1. Goal/Plan/Subgoal are STRATEGIC STATE (serializable pydantic models,
   no execution capability). The Phase 4 AgentReasoner remains the only
   LLM component and stays TACTICAL: it decides the next action; the
   deterministic AgentPlanManager owns subgoal lifecycle and revisions.
   The initial plan is built deterministically (portal-agnostic
   templates), NOT by the model — no portal scripts (rule 17).
2. Success is EVIDENCE, not confidence: SuccessCriterion is a typed
   predicate (10 kinds) evaluated deterministically against a Snapshot
   of WorkflowState + PageObservation. Unknown criterion kinds fail
   CLOSED as uncertain; the verdict is three-valued (satisfied /
   deterministic-failure / uncertain). `complete` refuses to complete a
   subgoal whose required criteria are unsatisfied — there is no
   planner-side bypass.
3. Subgoal lifecycle is a table-validated state machine (mirrors D014):
   7 states, machine-readable status reasons, illegal transitions raise.
4. Revision is SURGICAL: revise() replaces ONE subgoal, preserving its
   id, order and dependents; the prior shape is snapshotted into an
   immutable PlanRevision (reason, affected ids, previous/new version,
   timestamp, triggering event, previous shapes). COMPLETED subgoals are
   refused revision — completed work is stable (COMPLETED has no
   outgoing transitions).
5. The final-submission boundary is a FIRST-CLASS plan element:
   `final_submission=True` subgoal is hard-gated — FinalSubmissionGate
   blocks activation/completion/revision/any transition (the gate sits
   inside _transition, so no code path bypasses it); next_actionable and
   activate_next skip it; at_final_boundary signals the human handover.
   Planning REPRESENTS the boundary; PolicyEngine + runtime constraints
   still gate the actual action.
6. REPLAN decisions from the model are PROPOSALS: the manager applies
   them deterministically (structure validated, completed work
   protected). The model cannot create/destroy plan structure directly.
7. Snapshot is deliberately a thin projection of the sources Phase 6's
   AgentWorldState will own — the criterion contract will not change
   when WorldState lands. AgentRunState.plan wiring (typed plan into the
   Phase 2 runtime) is deliberate later wiring.

Status: ACCEPTED — implemented in `app/agent/strategy/*`, covered by
`tests/unit/test_agent_strategy.py` (42) and
`tests/synthetic_forms/test_strategy_loop.py` (1, real Chromium).

## D018 — Semantic WorldState is durable reality; DOM refs are ephemeral handles

Phase 6 (2026-09-19):

1. Ephemeral vs Durable Separation: DOM element references (`ref: 'e12'`)
   belong strictly to a single PageObservation and are never treated as
   durable truth. WorldState stores durable `SemanticField` instances
   indexed by stable semantic IDs (`field:state`, `field:district`, etc.)
   derived from HTML name, accessible name, label, section context, and
   user bindings.
2. Epistemic Hierarchy: `VERIFIED > OBSERVED > INFERRED > STALE`.
   A lower-trust observation or model statement can NEVER silently
   overwrite or erase a verified fact. Verified values survive DOM
   re-renders and blankings.
3. Stale-Reference Invalidation: When observation changes, prior
   ephemeral DOM refs are invalidated (`current_ref = None` or updated
   to the fresh observation's ref). Actions attempting to target stale
   refs or refs with wrong observation IDs fail closed (`is_target_ref_valid`).
4. Multi-Tab Continuity: Browser tabs are explicitly tracked with distinct
   `TabWorldState`. When the active tab changes, inactive tab state is
   preserved. Actions targeting inactive tab refs are rejected.
   Switching back restores semantic continuity.
5. Deterministic Provenance: Every WorldState mutation increments `version`
   monotonically and records an immutable `Provenance` audit record with
   source, observation ID, timestamp, and state version.
6. Zero Secrets & Zero DOM Tree Duplication: No raw passwords, OTPs, full
   identity numbers, or document bytes are stored in WorldState; only
   semantic reference identifiers. WorldState does not store live Playwright
   objects or duplicate raw PageState DOM trees.

Status: ACCEPTED — implemented in `app/agent/world/*`, covered by
`tests/unit/test_agent_world_state.py` (14) and
`tests/synthetic_forms/test_world_state_loop.py` (2, real Chromium).

## D019 — Bounded reflection, failure taxonomy, and recovery loop

Phase 7 (2026-09-19):

1. Non-Mutating Reflection: Reflection (`RecoveryReflector`) evaluates failures
   and recommends recovery strategies (`ReflectionResult`, `RecoveryDecision`).
   Critically, reflection NEVER executes browser actions directly and NEVER
   bypasses `ToolRegistry` or `PolicyEngine`. Browser mutations remain the
   exclusive responsibility of the authorized execution pipeline.
2. Canonical 13-Type Failure Taxonomy: All execution failures, reasoning anomalies,
   and execution stalls are classified by `FailureClassifier` into canonical
   `FailureType`s (`TARGET_NOT_FOUND`, `AMBIGUOUS_FIELD`, `INVALID_OPTION`,
   `VALIDATION_FAILURE`, `STALE_REFERENCE`, `PAGE_CHANGED`, `NAVIGATION_FAILURE`,
   `AUTHENTICATION_REQUIRED`, `PROMPT_INJECTION`, `TOOL_FAILURE`, `MODEL_FAILURE`,
   `TIMEOUT`, `POLICY_DENIED`).
3. Fail-Closed Security & Policy Boundaries: Security violations and policy denials
   are non-recoverable via automated tool retry:
   - `PROMPT_INJECTION` fails closed immediately (`fail_closed = True`, no retry).
     Page instructions cannot alter tool permissions or policy.
   - `POLICY_DENIED` surfaces denial directly to the runtime (`can_retry = False`);
     no automated retry is permitted.
   - `AUTHENTICATION_REQUIRED` halts automated execution (`user_action_required = True`),
     demanding human handover without bypassing authentication.
4. Ambiguity Beats Guessing: When encountering `AMBIGUOUS_FIELD` or `TARGET_NOT_FOUND`
   without a clear semantic match, the reflector refuses to guess and signals
   `request_clarification` or terminates the action.
5. Strictly Bounded Recovery: Recovery is bounded on three levels (`RecoveryBudget`):
   per-failure-type budget (default 2), per-subgoal budget (default 3), and total
   run budget (default 10). When a budget is exhausted, recovery terminates with
   `RecoveryStrategy.TERMINAL_FAILURE`.
6. Stale Target & Semantic Healing: On `STALE_REFERENCE` or `PAGE_CHANGED`,
   the runtime triggers re-observation. The `RecoveryManager` attempts to re-resolve
   the durable `semantic_id` in `AgentWorldState` to obtain a fresh observation ref.
   If target identity remains unambiguous, a fresh typed `ToolCall` is synthesized;
   if ambiguous or missing, it halts safely.
7. Verifiable Audit Trail: Every recovery attempt records an immutable
   `RecoveryAttemptRecord` tracking failure type, triggering evidence, strategy,
   attempt count, resulting tool result, and WorldState delta. Verified facts
   in `AgentWorldState` are never overwritten by failed or unverified recovery outcomes.

Status: ACCEPTED — implemented in `app/agent/recovery/*`, covered by
`tests/unit/test_agent_recovery.py` (15) and
`tests/synthetic_forms/test_recovery_loop.py` (1, real Chromium).

## D020 — Durable human interrupts, PostgreSQL persistence, and stale approval invalidation

Phase 8 (2026-09-19):

1. PostgreSQL Persistence over SQLite: Production checkpoints, human interrupts,
   approval bindings, and concurrency locks are persisted to PostgreSQL using `asyncpg`.
   PostgreSQL provides atomic upserts (`ON CONFLICT ... DO UPDATE ... RETURNING`),
   transactional multi-row consistency, native timestamp intervals, and distributed worker
   safety. Zero SQL is embedded within `AgentRuntime`, `AgentReasoner`, or `RecoveryReflector`.
2. Abstract Store Interface: Runtime interacts strictly via the `CheckpointStore`
   protocol (`app/agent/persistence/store.py`). `PostgresCheckpointStore` provides the
   production/integration backing; `InMemoryCheckpointStore` powers isolated unit suites.
3. Deterministic Interrupt Lifecycle: Human interrupts (`HumanInterrupt`) model
   human-required pauses (`OTP_REQUIRED`, `CAPTCHA_REQUIRED`, `AUTHENTICATION_REQUIRED`,
   `USER_CLARIFICATION_REQUIRED`, `USER_CONFIRMATION_REQUIRED`, `FINAL_REVIEW_REQUIRED`).
   Lifecycle transitions are strictly table-driven (`PENDING`, `WAITING_FOR_USER`,
   `APPROVED`, `EXPIRED`, `INVALIDATED`, `RESUMING`, `RESUMED`, `REJECTED`, `CANCELLED`).
   Illegal transitions fail closed and raise `InvalidInterruptTransition`.
4. Machine-Checked Approval Bindings (Never Permanent Booleans): Approvals are
   epistemic objects (`ApprovalBinding`) bound to `run_id`, `interrupt_id`, `requested_action`,
   `target_identity`, `semantic_id`, `world_state_version`, `observation_id`, and
   `expires_at`. Approval is invalidated if `world_state_version` drifts, the target identity
   changes, semantic reference is unresolvable, expiration passes, or requested action differs.
5. Re-observation & Semantic Reconciliation on Resume: Resume never blind-continues
   from historical checkpoint state. The `ResumeCoordinator` executes an 11-step protocol:
   load checkpoint -> validate schema version -> check interrupt status -> acquire PostgreSQL
   resume lock -> restore logical run state -> re-observe live browser state -> reduce into
   `AgentWorldState` (invalidating old DOM refs) -> compare state & validate approval binding ->
   transition interrupt to `RESUMED` -> resume from the logical subgoal.
6. Atomic PostgreSQL Resume Locking with Fencing Tokens: Mutex locking over `resume_locks`
   ensures only one active worker executes a run. Atomic upsert with lease duration and
   incrementing `fencing_token` prevents race conditions, handles crashed worker lease
   recovery, and rejects concurrent resume attempts deterministically. Failed resume
   attempts immediately release the lock.
7. Zero Secret Leakage: Passwords, OTPs, CAPTCHA answers, document bytes, and authentication
   secrets are strictly prohibited from checkpoints and audit event payloads. Audit events
   are recorded to `hitl_audit_events` with scrubbed metadata.

Status: ACCEPTED — implemented in `app/agent/interrupts/*`, `app/agent/persistence/*`,
`app/agent/runtime/resume.py`, covered by 26 targeted tests (10 unit interrupts,
11 unit resume protocol, 4 integration postgres, 1 synthetic Chromium+Postgres crash-recovery).


