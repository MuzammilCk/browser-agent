# Phase 15 — Production Hardening Plan

Derived from `docs/PHASE15_AUDIT.md`. Each item is a small, test-backed
hardening change — no architectural rewrite, no change to working Phase 1–14
behavior beyond the documented defect fixes.

## Guiding constraints (from the mission)

- LLM proposes → AgentReasoner → AgentDecision → AgentRuntime → ToolRegistry
  → PolicyEngine → BrowserExecutor → verification → WorldState → checkpoint.
  Unchanged by every item below.
- Fail closed by default; every new failure path is explicit and machine-readable.
- Every change ships with a regression test written against the defect first.

## Work items

### H1 — Verifier messages never echo field values (HIGH)
- **Defect:** fill/select verifiers formatted expected and live values
  (potentially vault-resolved credentials) into `VerificationResult.message`,
  which flows into `ToolResult.message` → model context and traces.
- **Fix:** shape-only reporting (`describe_value_mismatch` in
  `app/browser/verifiers/base.py`): lengths + equality, never values. Used by
  `verifiers/fill.py` and `verifiers/select.py`.
- **Tests:** `tests/unit/test_verifier_secret_safety.py` (7).

### H2 — Bounded wall-clock timeout on model calls (HIGH)
- **Defect:** `ReasonerConfig` bounded attempts but not time; a hung
  OpenRouter call blocked the run indefinitely (past worker lease, no
  checkpoint).
- **Fix:** `asyncio.wait_for` around each `decide()` in `AgentReasoner`;
  `decision_timeout_seconds` config (default 60); timeout consumes one
  attempt; final timeout → standard explicit `MODEL_FAILURE`. Fail closed.
- **Tests:** `tests/unit/test_reasoner_timeout.py` (6).

### H3 — Enterprise engine loop hardening (MEDIUM)
- **Defects:** (a) model ASK_USER decisions silently burned iterations —
  no durable interrupt; (b) REPLAN not counted against `max_replans`;
  (c) tool-call budget unenforced at the engine boundary; (d) budget
  tracker mutations not persisted into `run_state` at each mutation, so
  checkpoints carried stale counters.
- **Fix (app/enterprise/engine.py):** ASK_USER → `WAITING_FOR_USER` +
  `raise_human_interrupt(USER_CLARIFICATION_REQUIRED)` + `PAUSED_HITL`
  (same durable path as REQUIRE_CONFIRMATION); REPLAN →
  `tracker.record_replan()` with budget-exhausted failure; tool calls →
  `tracker.record_tool_call(...)` before execution; `save_budget_tracker`
  after every mutation. Non-tool decisions now traced with their reason.
- **Tests:** `tests/enterprise/test_engine_hardening.py` (5) + coverage
  inside the budget/cross-process tests.

### H4 — Cross-process checkpoint resume (MEDIUM)
- **Defect:** engine resume called the runtime's sync `restore_checkpoint`;
  for `PostgresCheckpointStore` the sync surface is a process-local cache,
  so a fresh worker process could not restore a PostgreSQL-only checkpoint.
- **Fix:** when the store exposes `load_checkpoint` (async protocol), the
  engine loads through it and seeds via `restore_checkpoint_from_json`;
  sync path retained as fallback; unknown checkpoints still fail closed.
- **Tests:** `test_resume_from_async_only_store` (forked-store simulation),
  `test_unknown_checkpoint_still_fails_closed`.

### H5 — Worker API heartbeat/token robustness (MEDIUM)
- **Defects:** heartbeat resolved the fencing token from a process-local
  cache that nothing populated → legitimate out-of-process workers always
  got 400; missing cache entry raised KeyError → 500.
- **Fix (app/enterprise/api/worker_api.py):** `/claim` caches the token for
  the (run, worker) pair; heartbeat accepts `fencing_token` in the request
  body (validated against the lease by `renew_lease`) with cache fallback;
  missing token → 400; wrong/stale token → 409; shared
  `_parse_fencing_token` gives all report endpoints deterministic 400s on
  non-integer tokens instead of 500s.
- **Tests:** `tests/enterprise/test_worker_api_hardening.py` (10).

### H6 — Audit-event redaction defense in depth (LOW)
- **Defect:** durable stores filtered audit payloads with a narrow
  substring list (password/secret/otp/pin/credential) and dropped keys
  silently; token/cookie/api_key/authorization/session keys leaked through.
- **Fix:** `app/agent/persistence/redaction.py` — key patterns aligned with
  the Phase 11 trace recorder, recursive filtering, explicit
  `[REDACTED:restricted_secret]` marker (auditable, not silent). Wired into
  both `InMemoryCheckpointStore` and `PostgresCheckpointStore`.
- **Tests:** `tests/unit/test_audit_redaction.py` (27, incl. Postgres SQL
  interception without a live DB). Existing integration test updated to the
  stronger marker contract.

### H7 — Password-field values masked (LOW)
- **Defect:** password-typed field values flowed unmasked from DOM
  extraction into `ElementState.value` → model context previews → world
  state → stall fingerprints → checkpoints.
- **Fix (3 layers):** DOM extraction JS returns '' for password inputs
  (main page + frames); `PageObserver._element_from_raw` masks any
  password-typed value in Python; reasoning context masks again at prompt
  build (defense in depth against hostile pages / old checkpoints).
- **Tests:** `tests/unit/test_password_masking.py` (8, incl. real-Chromium
  extraction through the new `tests/synthetic_forms/pages/login.html`
  fixture).

### H8 — Startup readiness validation + /ready endpoint (LOW)
- **Defect:** no startup validation; auth-disabled and plaintext-vault
  configurations booted silently; no readiness signal distinct from /health.
- **Fix:** `Settings.production_mode` + `validate_production_readiness()`
  returning (blockers, warnings) — blockers fire only under explicit
  production_mode (zero behavior change for local dev); `/ready` reports
  component states and 503s when blockers exist; `refresh_app_settings()`
  re-reads the singleton. Messages name settings, never values.
- **Tests:** `tests/unit/test_startup_readiness.py` (10).

## Evaluation expansion (mission item 12)

Fault injection for infrastructure crashes is exercised at the
unit/enterprise level (test_crash_recovery, test_engine_hardening) rather
than as new ScenarioRunner wrappers: the ScenarioRunner drives the
model/policy/verification axes, while crash-class faults belong to the
worker/store layer where they are already integration-tested. Rationale
recorded here to avoid duplicating harness code without evidence.

## Deferred (documented, not silently dropped)

- Dedicated frame-disappearance adversarial test (generic fail-safe path
  exists; low probability, no blocker).
- End-to-end memory prompt-injection persistence scenario (authority chain
  makes it non-exploitable today).
- Heartbeat API load testing (redundant with in-process renewal today).

## Verification gate

`python -m pytest tests -q` must pass with the exact result recorded in
docs/BUILD_STATUS.md before any release classification is written.
