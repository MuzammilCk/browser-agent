# EVALUATION PLAN

## Purpose

Evaluate the runtime as a long-horizon system, not merely the quality of individual LLM replies.

## Architecture Layers

### Layer A — Synthetic Scenarios (Implemented — Phase 12)
Covers deterministic local HTML forms with known ground truth:
- Basic and multi-step forms
- Dependent dropdowns and dynamic DOM mutations
- Validation errors and recovery
- Multi-tab flows
- File upload and iframes
- Adversarial prompt injection and fake DOM policy bypass
- Unauthorized external redirect attempts
- Approval replay and state version drift
- Controlled failure injection (stale references, model timeouts, budget halts)

### Layer B — Frozen Real-Portal Observations
Captures safe observations without real PII across portal archetypes:
- Identity and certificates
- Welfare and direct benefit transfer
- Transport and licensing
- Grievance redressal
- Appointments and scheduling
Replays `PageState` / DOM / ARIA / screenshot fixtures offline via `ReplayEngine`.

### Layer C — Live Shadow Mode (Implemented — Phase 14)
Agent observes, maps, and proposes tool calls against live portals without mutating remote state.

Implemented in `app/agent/live/shadow.py` (`run_live_shadow`):
- Model-independent: the reasoner is never invoked; the planned action trace is
  derived deterministically (observation → deterministic FieldMapper →
  PolicyEngine risk probes). Model output alone can never switch shadow mode
  into live mutation mode.
- Origin validation before observation; generic anti-bot/CDN block detection
  classifies blocked portals as `ANTI_BOT_BLOCK`/`PORTAL_UNAVAILABLE` (an
  environment condition — never an agent failure, never a successful
  observation).
- Evidence: `LivePortalRunReport` per run + `TraceRecorder` JSON/JSONL with
  explicit LIVE metadata (`live_metadata.started_at/finished_at`, mode,
  agent commit). Live traces are NEVER fed into deterministic replay as
  synthetic fixtures.
- Statuses are explicit and non-collapsing: PORTAL_OBSERVATION_SUCCESS /
  SEMANTICS_SUCCESS / MAPPING_SUCCESS / SHADOW_VALIDATION_SUCCESS /
  HITL_REQUIRED / AMBIGUOUS / UNSUPPORTED / POLICY_BLOCKED / PORTAL_UNAVAILABLE
  / ENVIRONMENT_FAILURE / AGENT_FAILURE / SAFETY_BLOCKED.

Phase 14 live evidence (2026-09-21): full portal-class coverage — PM-KISAN,
MyScheme, NCS, apprenticeshipindia (training), UDISE+ (education), Parivahan
(transport), DigiLocker (identity_document), Passport Seva (appointments)
shadow-validated successfully; services.india.gov.in recorded ANTI_BOT_BLOCK.
Landing pages without data-entry forms record mapping UNSUPPORTED honestly
(mapped=0) — never forced to MAPPING_SUCCESS. Artifacts:
tests/live_portal/evidence/<portal>/report.json + trace.jsonl.

### Layer D — Controlled Live Execution (Implemented — Phase 14; live use deferred, D027)
Permits bounded low/medium-risk mutations with human authorization. Strictly zero bypass of payment, final legal submission, CAPTCHA, or OTP.

Implemented in `app/agent/live/execution.py` (`run_controlled_execution`):
- Requires a successful shadow run's review request PLUS a signed human review
  decision (SHA-256 digest + HMAC; transplanted or forged approvals rejected;
  expired or unparseable-expiry approvals rejected fail-closed — approvals are
  bounded authorizations).
- Deterministic action allowlist: fill/select/check/uncheck only; click/upload
  never; password/otp/captcha/mfa/pin semantic targets never; submit/payment
  text never (final boundary is human-gated).
- Every mutation flows through the EXISTING ToolRegistry → PolicyEngine →
  BrowserExecutor → verification path; per-step semantic re-binding (fresh ref
  + observation_id) or STALE_TARGET_STOPPED; UNCERTAIN verification counts as
  failure; failure classification is non-collapsing: POLICY_DENIED →
  POLICY_BLOCKED, USER_ACTION_REQUIRED/CONFIRMATION_REQUIRED → HITL_REQUIRED,
  VERIFICATION_FAILED → AGENT_FAILURE, stale target → ENVIRONMENT_FAILURE.
- No live controlled execution has been performed (Phase 14 portals are
  observation-class; D027). The machinery is proven on offline fixtures with
  real Chromium (tests/evaluation/test_live_portal_acceptance.py,
  tests/synthetic_forms/test_live_controlled_offline.py, and the full
  WS3 matrix: tests/synthetic_forms/test_live_controlled_matrix.py —
  select/check execution, semantic re-binding over stale refs, sensitive
  value_ref → HITL_REQUIRED, approval expiry, world-state drift stop,
  Playwright timeout → ENVIRONMENT_FAILURE, and the prohibited-actions
  denial matrix).

---

## Evaluation Platform Components (`app/agent/evaluation/`)

1. **Scenario Runner (`ScenarioRunner`)**
   - Drives the real `AgentRuntime`, `AgentReasoner`, `ToolRegistry`, `PolicyEngine`, `BrowserExecutor`, and `AgentWorldState`.
   - Runs in isolated ephemeral session and checkpoint storage.
   - Evaluator owns zero execution authority: cannot bypass policy or synthesize verification.

2. **Causal Trace Recorder (`TraceRecorder`)**
   - Append-only thread-safe log of typed events (`TraceEventType`).
   - Strict causal lineage (`parent_event_id`, `correlation_id`, `iteration`).
   - Pre-export redaction of all sensitive keys and patterns (`SensitivityLevel.RESTRICTED_SECRET`).
   - Schema-validated export in JSON and JSONL.

3. **Multi-Dimensional Metrics (`MetricsCalculator`)**
   - **Task**: `task_success`, `goal_completed`, `subgoal_completion_rate`, `verification_success_rate`, `unmet_criteria_count`.
   - **Efficiency**: `iterations_count`, `tool_calls_count`, `browser_actions_count`, `total_tokens`, `cost_usd`, `duration_seconds`.
   - **Recovery**: `failures_encountered`, `recoveries_succeeded`, `recovery_success_rate`, `stale_ref_recoveries`.
   - **Safety**: `safety_pass`, `policy_denials`, `blocked_unauthorized_actions`, `hitl_bypasses_blocked`, `injections_contained`, `unauthorized_redirects_blocked`.
   - **Reliability**: `exceptions_count`, `browser_failures_count`, `model_failures_count`, `unhandled_errors_count`.
   - Invariant: Derived strictly from DOM state and verified world facts, never from model claims.

4. **Deterministic Replay Engine (`ReplayEngine`)**
   - Step-by-step trace comparison (`ReplayResult`, `ReplayDiff`).
   - Categorizes divergence severity (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
   - Localizes first diverging event and causal explanation.

5. **Failure Injector (`FailureInjector`)**
   - Injects controlled faults (`STALE_REFERENCE`, `BUDGET_EXHAUSTION`, `UNAUTHORIZED_REDIRECT`, `MODEL_FAILURE`).
   - Evaluates explicit scenario triggers (`iteration`, `tool_name`, `target_ref`).
   - Emits `FAULT_INJECTED` trace events for auditable reproduction.

6. **Regression Gates (`RegressionGate`)**
   - Compares candidate run metrics against baseline thresholds.
   - Enforces absolute safety invariants (`safety_pass == True`, zero unauthorized actions).
   - Generates structured pass/fail reports with metric explanations.

7. **Golden Scenario Catalog (`get_golden_scenarios()`)**
   - 14 cataloged scenarios across all canonical categories in `app/agent/evaluation/scenarios.py`.

---

## Release Policy & Baseline Evidence

Do not choose arbitrary model or accuracy thresholds before the benchmark baseline exists.
- Phase 14 expansion verified test baseline: **1092 tests passing**, 0 failures
  (733 unit + 65 integration + 80 synthetic + 28 prompt_injection + 36 evaluation
  + 148 enterprise) + 10 gated live observation tests + 2 gated real-LLM tests.
- Target CI threshold: Zero safety violations (`safety_pass == 1.0`), zero
  unauthorized mutations (`blocked_unauthorized == 0`), deterministic success
  criteria satisfied on all golden scenarios.
- Live-validation evidence artifacts (report.json + trace.jsonl per portal) are
  kept under tests/live_portal/evidence/ and validated for LIVE metadata,
  explicit outcome statuses, and redaction by
  tests/evaluation/test_live_portal_acceptance.py.
