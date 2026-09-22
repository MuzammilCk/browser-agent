# Phase 15 — Production Hardening & Readiness Audit

Audited: 2026-09-22, against the Phase 14 verified baseline
(`python -m pytest tests -q` → 1093 passed, 12 skipped).

Scope: all 15 subsystems listed in the Phase 15 mission. For each: current
implementation, current tests, failure modes, production risks, recommended
hardening, and whether the risk is already mitigated. Confirmed defects are
numbered H1–H8 and tracked into `docs/PHASE15_PLAN.md`.

Legend for risk status: **MITIGATED** (evidence found), **PARTIAL** (mitigated
for the common path, gap identified), **OPEN** (no mitigation found).

---

## 1. Agent runtime reliability

**Implementation.** `AgentRuntime` (app/agent/runtime/runtime.py) owns
lifecycle transitions, decision recording, checkpoints, interrupts.
`AgentReasoner` (app/agent/reasoning/reasoner.py) gives bounded retries
(`max_attempts ≤ 5`) with rejection-repair feedback and explicit
`MODEL_FAILURE` outcomes — no silent fallback. `RuntimeBudgetTracker`
(app/agent/security/budget.py) enforces iterations/tool calls/wall time/tokens
with monotonic clocks, serializable via `budget_state`. The stall detector
(app/agent/stall_detector.py) halts repeated identical no-progress actions.

**Tests.** Unit tests for reasoner retries/failures, budget persistence
(budget_state survives checkpoint round-trip), stall detection, lifecycle
transitions; synthetic-form loop tests; enterprise acceptance runs.

**Failure modes / findings.**

- **H2 (confirmed defect, OPEN):** the reasoner has NO wall-clock bound around
  `self._model.decide(...)`. `ReasonerConfig` bounds *attempts*, not *time*.
  A hung OpenRouter call blocks the loop indefinitely (the reasoner is also
  used directly by the enterprise engine, where lease renewal is the only
  indirect time bound). Transport exceptions are retried, so a hang-and-raise
  cycle repeats up to `max_attempts`. Production risk: worker lease expiry,
  frozen run, no checkpoint. Hardening: wrap each `decide()` call in
  `asyncio.wait_for` with a configurable per-decision timeout; timeout counts
  as an attempt (existing bounded-retry machinery absorbs it); on final
  timeout the outcome is the standard `MODEL_FAILURE`/`DECISION_TIMEOUT`
  path — fail closed.
- **PARTIAL — enterprise loop non-TOOL_CALL decisions:** `WorkerRunEngine._loop`
  (app/enterprise/engine.py) treats REPLAN/REFLECT/ASK_USER identically
  (`continue` without recording). Non-`tool_call` decisions therefore consume
  an iteration and re-prompt without any durable record. Not a safety issue
  (nothing executes), but it is observability debt; H3 adds trace records.
- **MITIGATED — malformed decisions:** strict parse + schema validation +
  bounded repair retries + explicit failure codes; tested extensively.
- **MITIGATED — repeated-action stalls:** stall detector with page
  fingerprint; `max_iterations` backstop; both tested.
- **MITIGATED — cancellation:** engine checks `cancel_check` and
  `lease_guard.ensure_valid()` at every iteration boundary (safe boundary
  rule). Browser-mutation granularity is not finer — accepted, documented.
- **MITIGATED — checkpoint boundaries:** checkpoint on every engine exit path
  (COMPLETED/PAUSED/FAILED/CANCELLED/LEASE_LOST); budget state persisted in
  `run_state.budget_state` at checkpoint time.

**Hardening:** H2 (+ trace records for non-tool decisions in H3).

## 2. Browser lifecycle

**Implementation.** `BrowserManager` (app/browser/manager.py) owns
launch/context/page lifecycle; `BrowserExecutor` wraps raw Playwright
mutation + verification + re-observation; tab reconciliation
(`_sync_tabs`) promotes new tabs as the observation source; every mutating
action is verified (per-action verifiers) and followed by a fresh
observation.

**Tests.** Synthetic-form failure pages (failure_click/fill/select),
multistep, dropdowns, verification tests, world-state loop tests, and
Phase 12 fault injection (stale reference, unauthorized redirect).

**Failure modes / findings.**

- **PARTIAL — crash-class failures:** no dedicated adversarial test that
  kills the page/browser mid-loop (close target, crash context). The
  executor's broad `except Exception` converts crashes into
  `EXECUTION_FAILED` + `recovery_required`, which the engine checkpoints —
  the fail-safe path exists but lacks an explicit test. Hardening: add a
  synthetic-forms test that closes the page mid-loop and asserts a
  deterministic FAILED outcome with checkpoint (see plan §6).
- **MITIGATED — navigation failure/timeout:** executor converts exceptions to
  `EXECUTION_FAILED`; navigation goes through PolicyEngine +
  `validate_navigation_destination` (origin checks).
- **MITIGATED — stale references:** observation_id binding on every mutating
  action; registry + tool-level `_validate` reject stale refs (fail closed);
  post-observation refresh after each mutation.
- **MITIGATED — popups/new tabs:** `_sync_tabs` + tab reconciliation; Phase 8
  audit covered it.
- **OPEN (accepted for now):** frame disappearance mid-action is handled
  generically by the exception path (UNCERTAIN/failed verification) but not
  proven by a dedicated test. Recorded as residual risk, not a blocker.

## 3. PostgreSQL / persistence reliability

**Implementation.** `PostgresCheckpointStore` (app/agent/persistence/
postgres_store.py): transactional checkpoint writes (state + events +
audit row in one transaction), schema-version validation on load
(fail closed on `format_version` mismatch), resume-lock with fencing tokens
(`acquire_resume_lock` recovers expired leases with an incremented token),
audit event recording with key-based secret filtering.

**Tests.** Gated real-PostgreSQL tests (`test_postgres_*.py`) covering
checkpoint round-trip, interrupt/approval persistence, resume-lock
contention, crash recovery; in-memory double covers the logic hermetically.

**Failure modes / findings.**

- **PARTIAL (H6):** `record_audit_event` filters payload keys by substring
  match on a small list (`password|secret|otp|pin|credential`). Values are
  trusted to be non-secret. This is defense-in-depth only (trace recorder
  already redacts content), but the filter is narrower than the Phase 11
  `_SENSITIVE_KEY_PATTERNS` set — e.g. `api_key`, `token`, `authorization`,
  `cookie` are not filtered here. Hardening: align the key filter with the
  Phase 11 patterns (H6).
- **MITIGATED — partial writes:** single INSERT … transaction per checkpoint;
  the CHECKPOINT_SAVED audit row rides in the same transaction.
- **MITIGATED — concurrent resume:** fencing tokens + lease expiry recovery
  + `RUN_RESTORED` event; tested for contention.
- **MITIGATED — restart compatibility:** `format_version` gate with explicit
  `IncompatibleCheckpointSchema`; cross-process restore path exists
  (`restore_checkpoint_from_json`) and is tested at unit level. Gap: the
  *enterprise engine* resume path (H4, below) did not use the async store —
  fixed under H4.

## 4. Worker robustness

**Implementation.** `ExecutionWorker` (app/enterprise/worker.py):
claim → lease+fencing → fenced RUNNING write → engine execute with
`LeaseGuard` + cancellation flag → finalize per outcome with fenced writes;
renewal failure fails closed; stale-worker writes rejected by fencing;
cancellation flag refreshed from the store and polled at safe boundaries.

**Tests.** test_execution_worker, test_worker_leases, test_crash_recovery,
test_cancellation, test_queue — including duplicate claim, lease expiry,
fencing rejection, cancel race, stale lease.

**Failure modes / findings.**

- **MITIGATED — no double execution:** fencing token invalidates the older
  worker's writes; engine checks `lease_guard.ensure_valid()` before each
  iteration; browser is worker-owned, so a stale worker cannot even reach
  the same page. Tested.
- **MITIGATED — worker crash mid-run:** lease expires; recovery marker;
  resume path re-enqueues. Tested (test_crash_recovery).
- **PARTIAL — resume-with-checkpoint cross-process (H4):** the engine's
  resume path called the *sync* `AgentRuntime.restore_checkpoint()` with a
  `checkpoint_id`, but the runtime's constructor wires its internal store as
  `InMemoryCheckpointStore()` when given the async `CheckpointStore` protocol
  object — the sync `load()` on that object does not hit PostgreSQL. A fresh
  worker process resuming a run whose checkpoint lives only in PostgreSQL
  would fail with "checkpoint not found" (fail closed, no corruption — but
  recovery is broken). Confirmed by reading `AgentRuntime.__init__` +
  `restore_checkpoint`. Hardening H4: in `WorkerRunEngine.execute`, when
  `checkpoint_id` is set and the store exposes `load_checkpoint`, load the
  checkpoint asynchronously and seed the runtime via
  `restore_checkpoint_from_json(cp.to_json())`. Regression test proves a
  resumed run in a *new* runtime instance recovers budget/world state from
  the async store.
- **MITIGATED — poisoned execution:** malformed decisions fail closed
  (bounded retries → MODEL_FAILURE); policy denies out-of-bound actions.

## 5. Enterprise isolation

**Implementation.** Server-side identity only (`IdentityProvider` from bearer
token; worker_id never client-supplied); strict pydantic request schemas with
`extra=forbid` (tenant/user/role/worker fields cannot be smuggled);
tenant-scoped store methods; idempotency keys server-owned; audit events
tenant-scoped; vault service tenant/user-scoped.

**Tests.** test_tenant_isolation, test_api_gateway (unauthorized/cross-tenant
paths), test_acceptance_isolation_vault, test_idempotency,
test_vault_service, test_enterprise_security.

**Failure modes / findings.**

- **MITIGATED — tenant isolation:** every store read/write is tenant-keyed;
  cross-tenant access attempts tested to fail (404/403 semantics).
- **MITIGATED — workflow ownership/authorization:** role checks
  (`require_role`) + ownership checks in WorkflowService; strict request
  schemas prevent authority smuggling.
- **MITIGATED — idempotency:** durable `put_idempotency_if_absent` /
  `update_idempotency_response`; duplicate-create tests pass.
- **MITIGATED — audit visibility:** audit list endpoints are tenant-scoped.
- **MITIGATED — vault isolation:** vault service is tenant/user-scoped;
  acceptance tests prove cross-tenant vault reads fail.

## 6. Security hardening (adversarial)

**Implementation.** Content security envelope (`wrap_web_content` marks page
text as untrusted), injection test corpus (28 tests), PolicyIntegrityGuard,
navigation destination validation, ApprovalIntegrityGuard (approval binding
validation: run/interrupt/action/semantic target/world-version/observation/
expiry), stall detection, strict tool schemas, `extra=forbid` everywhere.

**Tests.** tests/prompt_injection (28), security guard unit tests, approval
drift/replay tests (Phase 8/13), policy bypass tests.

**Failure modes / findings.**

- **MITIGATED — prompt injection / hostile DOM:** enveloped untrusted text,
  strict action schema, deterministic policy; page text can propose but never
  authorize. 28 adversarial tests.
- **MITIGATED — approval replay/drift:** ApprovalBinding validated against
  current world-state version + observation id + expiry; replay and drift
  tests pass (Phase 13 + Phase 8 suites).
- **MITIGATED — malicious redirect:** `validate_navigation_destination`
  + PolicyEngine deny; tested.
- **MITIGATED — tool-schema abuse:** double schema validation (tool + registry),
  `extra=forbid`, unknown-tool rejection.
- **H1 (confirmed leak, OPEN):** fill-verifier failure messages embed the
  expected and live values verbatim — `f"Live value '{live_value}' != expected
  '{expected_value}'"` (app/browser/verifiers/fill.py) — and
  `_from_action_result` promotes `result.message` into `ToolResult.message`
  AND `payload["executor_message"]`. The context assembler whitelists payload
  *keys* but `message` itself is always included (`result.message[:300]`).
  Net effect: a vault-resolved password/Aadhaar/PAN value can be echoed into
  the model prompt and traces when a fill mismatches. This violates
  AGENTS.md rule 6 / docs/SECURITY_MODEL.md ("no secret exposure to the
  LLM"). Hardening H1: never format values into verifier messages; report
  shape (lengths, equality booleans) instead of content.
- **H7 (defense-in-depth, OPEN):** page field values flow unmasked into
  `ElementState.value` → model-facing element previews
  (`_element_lines` caps at 40 chars but does not mask) and into world-state
  reduction. The `input_type=password` marker exists on the element but is
  not used to mask. Vault values never enter the observation for fills, but
  a pre-filled password field rendered by the page itself (or a hostile page
  echoing a value) would leak into the prompt. Hardening H7: mask values of
  password-type fields at observation serialization + context assembly.

## 7. HITL integrity

**Implementation.** `HumanInterrupt` + `ApprovalBinding` (durable models,
no secrets), raise/resolve through `AgentRuntime`, expiry + world-state
version + observation binding, checkpoint contains interrupt + approval.
Enterprise path: REQUIRE_CONFIRMATION → `raise_human_interrupt` →
`PAUSED_HITL` → lease release → resume re-enqueues.

**Tests.** Phase 8 interrupt/approval suites; Phase 13 HITL resume, replay,
drift, expiry, wrong-run/wrong-interrupt rejections; concurrent resume via
resume-lock.

**Failure modes / findings.**

- **MITIGATED — replay/drift/expiry/cancellation:** binding validation
  covers run_id, interrupt_id, action, semantic target, world version,
  observation id, expiry. Tests for every listed attack pass.
- **H3a (confirmed gap, OPEN):** the enterprise engine never surfaces model
  `ASK_USER` decisions as interrupts. `WorkerRunEngine._loop` treats
  ASK_USER/REPLAN/REFLECT as "not TOOL_CALL → continue". A model that
  correctly decides to ask the human (OTP/CAPTCHA/clarification) burns
  iterations in a silent loop instead of pausing durably. The runtime
  already has the machinery (`record_decision` raises an interrupt on
  ASK_USER); the engine just doesn't route through it. Hardening H3a: on
  ASK_USER, transition to WAITING_FOR_USER, `raise_human_interrupt`
  (USER_CLARIFICATION_REQUIRED), trace HITL_INTERRUPT, return PAUSED_HITL.
- **PARTIAL — worker crash after approval before action:** approval binding
  survives in the checkpoint; resume revalidates the binding against current
  world state (drift-sensitive). Covered by Phase 8 tests at the runtime
  level; enterprise-level flow relies on the same validation path.

## 8. Memory hardening

**Implementation.** Working memory (Phase 9) with sensitivity-aware writes,
promotion gates, compaction; episodic log bounded by run; memory is
advisory — reasoning context treats it as hints, observation stays
authoritative.

**Tests.** test suites for sensitive rejection, unauthorized writes,
promotion, compaction, cross-run isolation.

**Failure modes / findings.**

- **MITIGATED — sensitive rejection/unauthorized writes/cross-run leakage:**
  tested; sensitivity levels gate persistence.
- **PARTIAL — prompt-injection persistence:** untrusted page content is not
  written to durable memory by construction (writes come from tool results
  with sensitivity metadata), and adversarial tests cover injection texts.
  No dedicated test persists a hostile sentence into memory and asserts it
  cannot alter a later decision — recorded as residual coverage debt, not a
  defect (the authority chain cannot be altered by memory content).

## 9. Security / secret boundaries

**Implementation.** Vault values resolve only at execution time
(resolution handles, never raw values, cross the model boundary);
`_TOOL_PAYLOAD_SAFE_KEYS` key whitelist for prompt payloads; trace recorder
redacts content + sensitive key patterns before persistence; postgres audit
filter (narrow — H6); ToolResult contract forbids raw secrets.

**Findings.**

- **H1 (OPEN, highest severity of this audit):** verifier failure messages
  leak resolved values into `ToolResult.message` → model context and traces
  (details under §6). **Mitigation: H1.**
- **H6 (PARTIAL):** postgres `record_audit_event` key filter narrower than
  Phase 11 patterns. **Mitigation: H6.**
- **MITIGATED — model prompts:** context assembler is key-whitelisted and
  value-capped; semantic references only for sensitive data.
- **MITIGATED — checkpoints:** logical state only; no Playwright objects, no
  raw credentials (models enforce).
- **MITIGATED — logs:** executor logs verification status, not values;
  live-value read failures log refs only.

## 10. Observability

**Implementation.** TraceRecorder (causal parent/child, correlation ids,
secret redaction before persistence), run/workflow/tenant/checkpoint ids on
enterprise records, policy/verification/HITL events recorded in the engine
loop, redacted trace export (JSON/JSONL schema-validated).

**Tests.** trace unit tests, redaction tests, evaluation traces asserted in
scenario tests.

**Findings.**

- **PARTIAL:** engine loop records OBSERVATION/MODEL_DECISION/POLICY/
  BROWSER_RESULT/HITL but not REPLAN/REFLECT decisions (H3 adds them) and
  not tool-call budget exhaustion explicitly (it appears only in the failure
  message). Accepted with H3's trace additions.
- **MITIGATED — no secrets in traces:** redaction occurs before persistence;
  H1 closes the one content leak found.

## 11. API robustness

**Implementation.** Strict schemas (`extra=forbid`, length caps) on all
gateway request models; deterministic error codes (401/403/404/409/503);
idempotency on create; worker API fencing-validated; cancellation and resume
state-machine checked server-side.

**Tests.** test_api_gateway (malformed input, unauthorized, invalid ids,
dup requests), test_idempotency, test_cancellation.

**Findings.**

- **H5 (confirmed defect, OPEN):** `POST /enterprise/worker/claims/
  {run_id}/heartbeat` resolves the fencing token from a *process-local*
  cache populated only by `cache_worker_token` (which nothing in the
  codebase calls — the real worker renews in-process, bypassing the API).
  Two defects: (a) a legitimate out-of-process worker that obtained a lease
  via `/claim` (which returns the token in its response body, but does not
  cache it server-side) always gets 400 "invalid fencing token"; (b) a
  missing cache entry raises `KeyError` inside `.get()` which is NOT caught
  (`except (ValueError, TypeError)`) → 500 instead of a clean 404/409.
  Hardening H5: accept the fencing token in the heartbeat request body
  (worker-supplied, server validates against the lease), keep the cache as
  fallback, and map missing/invalid tokens to explicit 4xx codes.
- **MITIGATED — invalid state transitions:** RunTransitionError → 409;
  tested.
- **MITIGATED — concurrent requests:** idempotency + fencing; tested.
- **MITIGATED — large inputs:** length caps on all string fields.

## 12. Evaluation expansion

**Implementation.** ScenarioRunner (Phase 12) drives the real stack with
fault injection (model failure, stale reference, budget exhaustion,
unauthorized redirect), causal traces, criteria/safety evaluation; 36
evaluation tests.

**Findings.**

- **PARTIAL:** existing scenarios cover the model/policy/verification axes;
  fault injection for *infrastructure* crashes (browser kill, store
  interruption, worker kill) is exercised at the unit/enterprise level but
  has no scenario wrappers. Phase 15 plan §6 adds: browser-crash scenario
  (synthetic page closed mid-loop) and store-interruption scenario (async
  checkpoint store raising mid-run must fail closed with a checkpoint from
  the previous good state). Both go through the real policy/runtime
  architecture; no new bypass path.

## 13. Configuration / deployment readiness

**Implementation.** `Settings` (pydantic-settings): OpenRouter key/model/
timeout/token budget, vault encryption key, API tokens (empty = localhost
dev), enterprise tokens (empty = worker registration fails closed),
browser mode, headless, upload confinement dirs. `/health` endpoint exists.

**Findings.**

- **H8 (OPEN):** no startup validation and no readiness endpoint:
  - `api_token` empty disables auth on /api/* with only a description
    warning — a production deployment can boot silently unauthenticated.
  - `enterprise_worker_token` empty disables out-of-process worker
    registration (fail closed) — good — but nothing surfaces this at boot.
  - Vault plaintext mode (`vault_encryption_key` empty) is allowed silently.
  - No `/ready` distinguishes "process up" from "runtime usable".
  Hardening H8: add `Settings.validate_production_readiness()` returning a
  list of blocking conditions (auth disabled + non-test browser mode or
  explicit production flag), plus a `/ready` endpoint that reports auth
  state, vault encryption state, and enterprise runtime initialization —
  failing readiness when a blocking condition holds. Default behavior is
  unchanged for local dev (readiness reports warnings, server still boots;
  only an explicit production marker flips blocking semantics) — no
  behavior change for existing tests.
- **MITIGATED — secure defaults:** anonymous free-tier model gate for vault
  runs (audit Z6), worker tokens fail closed, upload confinement.

## 14. Real LLM path

**Implementation.** OpenRouterDecisionModel implements `DecisionModel`
(system/context → raw string); AgentReasoner parses/validates/repairs;
AgentRuntime routes. No Playwright access exists anywhere in app/llm/
(verified by import graph: openrouter.py imports only httpx + settings).

**Tests.** test_openrouter_decision_model (unit, mocked transport);
2 gated live-LLM tests behind RUN_OPENROUTER_LIVE_TEST=true (documented
pass on 2026-09-21 run).

**Findings.** **MITIGATED.** The chain OpenRouter → DecisionModel →
AgentReasoner → validated AgentDecision → AgentRuntime → ToolRegistry →
PolicyEngine → BrowserExecutor is enforced structurally; H2 adds the missing
time bound on the model call itself. No change to the real-LLM path.

## 15. Live-site safety boundary

**Implementation.** Phase 14 distinction preserved: LIVE SHADOW (read-only
real-site observation behind RUN_REAL_SITE_TESTS=true) ≠ LIVE CONTROLLED
EXECUTION (synthetic/dedicated test endpoints only) ≠ unrestricted live
automation (not implemented, by design).

**Tests.** 10 shadow tests re-verified green on the Phase 14 baseline.

**Findings.** **MITIGATED.** No changes to live-site scope in Phase 15; no
real government mutation performed for evidence.

---

## Confirmed defect / hardening register

| ID | Subsystem | Severity | Summary | Fix |
|----|-----------|----------|---------|-----|
| H1 | 6, 9 | HIGH | Fill-verifier failure messages echo expected/live field values (potentially vault-resolved secrets) into ToolResult.message → model context + traces | Mask values in verifier messages; report shape only |
| H2 | 1, 14 | HIGH | No wall-clock bound on model call inside AgentReasoner; hung LLM blocks loop past lease | asyncio.wait_for per decide() call; timeout = bounded attempt; DECISION_TIMEOUT failure |
| H3 | 1, 7, 10 | MEDIUM | Enterprise loop: ASK_USER never raises an interrupt (silent iteration burn); REPLAN/REFLECT unrecorded; tool-call budget not enforced in engine; budget tracker mutations not persisted to run state each iteration | Handle ASK_USER → durable PAUSED_HITL; trace non-tool decisions; tracker.record_tool_call; save_budget_tracker after mutation |
| H4 | 3, 4 | MEDIUM | Engine resume uses sync restore against an async-only store — cross-process resume of a PostgreSQL-only checkpoint fails | Async load + restore_checkpoint_from_json seeding when store exposes load_checkpoint |
| H5 | 11 | MEDIUM | Heartbeat requires server-local token cache that is never populated → legit out-of-process workers always 400; missing cache entry raises 500 | Accept fencing_token in body, validate against lease; explicit 4xx mapping |
| H6 | 3, 9 | LOW | Postgres audit-event key filter narrower than Phase 11 sensitive-key patterns | Align filters |
| H7 | 6, 9 | LOW | Password-type field values unmasked in observation → element previews | Mask at element serialization + context assembly |
| H8 | 13 | LOW | No startup production-readiness validation; no /ready endpoint | validate_production_readiness() + /ready |

## Residual risks (accepted, documented)

1. Frame disappearance lacks a dedicated adversarial test (handled by the
   generic fail-safe path).
2. Cancellation granularity is the iteration boundary, not per-Playwright-call.
3. Memory prompt-injection persistence has no dedicated end-to-end scenario
   (authority chain makes it non-exploitable today).
4. Heartbeat API is redundant with in-process renewal; kept for external
   workers but only lightly load-tested.

None of the above is a release blocker under the classification in
docs/PRODUCTION_READINESS.md.
