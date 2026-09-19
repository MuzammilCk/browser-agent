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

### Layer C — Live Shadow Mode
Agent observes, maps, and proposes tool calls against live portals without mutating remote state.

### Layer D — Controlled Live Execution
Permits bounded low/medium-risk mutations with human authorization. Strictly zero bypass of payment, final legal submission, CAPTCHA, or OTP.

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
- Phase 12 verified test baseline: **850 tests passing**, 0 failures.
- Target CI threshold: Zero safety violations (`safety_pass == 1.0`), zero unauthorized mutations (`blocked_unauthorized == 0`), deterministic success criteria satisfied on all golden scenarios.
