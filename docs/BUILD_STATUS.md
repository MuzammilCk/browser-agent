# BUILD STATUS

Last reconciled: 2026-09-19
Current phase: Phase 5 — Goal / Plan / Subgoal (COMPLETE — deterministic strategic layer above the Phase 4 loop; exit criterion proven on a dynamic-form scenario)
Overall: IN PROGRESS (Phases 0–5 complete)
Release status: NOT PRODUCTION READY

## Phase 0 evidence

Control plane is complete.

Created:

- AGENTS.md
- context.md
- implementation_plan.md
- docs/ARCHITECTURE_TARGET.md
- docs/AGENT_PROTOCOL.md
- docs/BUILD_STATUS.md
- docs/DECISIONS.md
- docs/SECURITY_MODEL.md
- docs/EVAL_PLAN.md
- docs/RESEARCH_BASIS.md

Legacy pointer files updated:

- implementation-plan.md
- docs/context.md
- docs/ARCHITECTURE.md

Evidence: these files were committed to current main during Phase 0.

## Evidence policy

Historical audit documents contain prior test counts and live smoke-test claims. Those are not treated as current proof until current HEAD is executed again.

Current reproducible test baseline (verified with Phase 5, 2026-09-19): **680 tests passing** (581 unit + 59 integration + 40 synthetic). 0 tests failing. The two Phase 1-time `.env` guardrail failures remain fixed, and the earlier vault-crypto temp-path failure also passes at current HEAD. Note: `tests/real_sites/` contains a manual observation script with no pytest-collectable tests, and `tests/portal_regression/`, `tests/prompt_injection/`, `tests/safety/` are empty stubs.

## Phase 1 evidence

### Test count
```
pytest tests/unit/ tests/integration/ tests/synthetic_forms/ tests/real_sites/ -q
→ 506 passed in 188.5s
```

(Phase 1-time count. Superseded at current HEAD by the 554-test baseline above;
`real_sites/` now collects 0 pytest tests.)

### Previously failing tests (now fixed)
| Test File | Failing Tests | Root Cause | Fix Applied |
|-----------|---------------|------------|-------------|
| `tests/unit/test_model_guardrails.py` | 2 (`test_refusal_happens_before_browser_launch`, `test_free_tier_env_model_also_refused`) | `.env` had `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true` which disabled the Z6 model guard. Guard is designed to refuse free-tier model + populated vault unless explicitly overridden. | Changed `.env` to `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=false` (matching `.env.example`). All 12 tests now pass. |

### Playwright launch check
```
Chromium launched OK (Playwright 1.62.0)
ARIA snapshot captured successfully
Browser lifecycle: start → open → observe → close — all OK
```

### Synthetic observe → act → verify → re-observe
Validated via `tests/synthetic_forms/` (31 tests, all passing):
- Text inputs observed and filled
- Select dropdowns observed and selected
- Checkbox/radio observation
- Validation error detection and extraction
- Multi-step form navigation
- Post-action verification (fill, click, select)
- Re-observation after every action (`post_observation` in `ActionResult`)
- Stale reference rejection
- UNCERTAIN verification stops progression
- File input observation (`TestFileUpload`)
- Iframe observation (`TestIframeObservation`)

### Phase 1 coverage audit
| # | Requirement | Test File | Test Exists? | Sufficient? |
|---|-------------|-----------|--------------|-------------|
| 1 | text | `test_observer.py::TestSimpleForm::test_observes_text_inputs` | ✅ Yes | Sufficient |
| 2 | select | `test_observer.py::TestSimpleForm::test_observes_select_dropdown` + `test_executor.py::TestSelectAction::test_select_dropdown` | ✅ Yes | Sufficient |
| 3 | radio | `test_observer.py::TestCheckboxesRadios::test_observes_radios` + `test_executor.py::TestCheckUncheckAction::test_check_radio_button` | ✅ Yes | Sufficient |
| 4 | checkbox | `test_observer.py::TestCheckboxesRadios::test_observes_checkboxes` + `test_executor.py::TestCheckUncheckAction::test_check_checkbox` | ✅ Yes | Sufficient |
| 5 | file input | `test_observer.py::TestFileUpload` + `test_executor.py::TestUploadAction` | ✅ Yes (NEW) | Sufficient — observe + upload execution + DOM verification |
| 6 | iframe | `test_observer.py::TestIframeObservation` + `test_executor.py::TestIframeInteraction` | ✅ Yes (NEW) | Sufficient — observe + executor-level iframe action via frame-aware LocatorResolver + DOM verification |
| 7 | dynamic form | `test_observer.py::TestDropdownForm::test_dependent_dropdown_appears` + `test_executor.py::TestSelectAction::test_select_dependent_dropdown` | ✅ Yes | Sufficient |
| 8 | validation | `test_observer.py::TestValidationForm::test_observes_validation_errors` + `test_verification.py::TestFillFailureDetection::test_detects_validation_appeared` | ✅ Yes | Sufficient |
| 9 | stale references | `test_executor.py::TestStaleRefRejection::test_stale_observation_rejected` | ✅ Yes | Sufficient |
| 10 | multi-tab | `test_multi_tab.py` (11 tests across 4 classes) | ✅ Yes | Sufficient |
| 11 | no swallowed browser errors | `test_browser_errors.py` (3 NEW tests) | ✅ Yes (NEW) | Sufficient |

### New files added for Phase 1 coverage
- `tests/synthetic_forms/pages/file_upload.html` — page with file inputs
- `tests/synthetic_forms/pages/iframe.html` — page with iframe (loads iframe_content.html via src)
- `tests/synthetic_forms/pages/iframe_content.html` — iframe content (separate file for URL-based frame matching)
- `tests/integration/fixtures/test_photo.jpg` — real JPEG fixture for upload tests (created with PIL)
- `tests/integration/test_browser_errors.py` — browser error visibility tests (3 tests)

### Current Phase 1 status
| Item | Status | Evidence |
|------|--------|----------|
| Run current test suite | ✅ Done | 506 passed, 0 failed |
| Record exact current baseline | ✅ Done | See above |
| Synthetic coverage: text/select/radio/checkbox/file/iframe/dynamic/validation | ✅ Done (31 tests) | tests/synthetic_forms/ |
| Execution coverage: fill/click/select/check/radio/upload/iframe/dynamic | ✅ Done (32 tests) | tests/integration/test_executor.py::TestFillAction, TestClickAction, TestSelectAction, TestCheckUncheckAction, TestUploadAction, TestIframeInteraction |
| Stale-reference tests | ✅ Done | tests/integration/test_executor.py::TestStaleRefRejection |
| Multi-tab tests | ✅ Done | tests/integration/test_multi_tab.py |
| No swallowed browser errors | ✅ Done | tests/integration/test_browser_errors.py |

## Phase 2 evidence

Implemented (all additive, no existing file modified):

- `app/agent/runtime/state.py` — `AgentLifecycle` (12 required states), explicit
  `LIFECYCLE_TRANSITIONS` table, `AgentRunState` (run id, goal, plan, current
  subgoal, WorldState handle, memory handles, browser handle, pending interrupt,
  lifecycle, iteration, usage counters, timestamps, parent/child agent metadata)
- `app/agent/runtime/events.py` — frozen `AgentEvent`, append-only `AgentEventLog`
  with monotonic sequence + ordered replay
- `app/agent/runtime/decision.py` — `AgentDecision` / `AgentDecisionType`
  (TOOL_CALL/REPLAN/REFLECT/ASK_USER/COMPLETE; HANDOFF reserved for Phase 10),
  schema-validated, embeds `BrowserAction` (no LLM loop — Phase 4)
- `app/agent/runtime/checkpoint.py` — `AgentCheckpoint` (state + full event log,
  format-versioned), `CheckpointStore` protocol, `InMemoryCheckpointStore`
  (SQLite deferred to Phase 8 by plan)
- `app/agent/runtime/session.py` — `AgentSession` (serializable run registry +
  active-run pointer)
- `app/agent/runtime/runtime.py` — deterministic `AgentRuntime`: validated
  transitions (illegal = raised, never coerced), `transition_toward` BFS for
  multi-hop workflow-status changes, durable interrupts (raise/resolve +
  auto-checkpoint), decision recording, usage counters, checkpoint
  create/restore incl. cross-runtime JSON restore
- `app/agent/runtime/facade.py` — `RuntimeBackedAgentRunner(AgentRunner)`: same
  `run`/`resume` contract, tracks session/run/events, derives lifecycle from
  `WorkflowStatus`, checkpoints every pause and every terminal state

Serialization format: pydantic v2 `model_dump_json()` (lossless round-trip).
Checkpoints are self-contained JSON: `{format_version, checkpoint_id, run_id,
created_at, reason, state, events[]}`.

### Phase 2 test counts (verified at current HEAD, 2026-09-19)

```
pytest tests/unit/test_agent_runtime.py -q
→ 48 passed in 0.78s

pytest "tests/unit/test_agent_runtime.py::TestCheckpoints::test_restored_run_preserves_logical_task_state" \
  "tests/unit/test_agent_runtime.py::TestCheckpoints::test_restored_run_replays_full_event_log" \
  "tests/unit/test_agent_runtime.py::TestCheckpoints::test_json_round_trip_lossless" -v
→ 3 passed

pytest tests/unit/ -q
→ 464 passed in 17.78s

pytest tests/integration/ -q
→ 59 passed

pytest tests/synthetic_forms/ -q
→ 31 passed

pytest tests/unit/ tests/integration/ tests/synthetic_forms/ -q
→ 554 passed in 189.62s
```

An earlier work-in-progress note recorded 463 passed + 1 failed in `tests/unit/`
(vault-crypto temp-path assertion). At current HEAD that test passes: 464/464
unit tests are green. No test was masked or weakened.

### Phase 2 exit criterion

A paused run can be serialized and restored without losing logical task state:
verified by `test_restored_run_preserves_logical_task_state` and
`test_restored_run_replays_full_event_log` — a run paused at
READY_FOR_CONFIRMATION (interrupt + workflow state + iteration + subgoal +
action history intact) exports to JSON, restores into a FRESH `AgentRuntime`,
and replays the full event log with sequence continuity (+1 `RUN_RESTORED`).

### Phase 2 status

| Item | Status | Evidence |
|------|--------|----------|
| Pydantic models | ✅ Done | app/agent/runtime/*.py, 48 tests |
| Serializable state | ✅ Done | test_serialization_round_trip, test_json_round_trip_lossless |
| Event append/replay | ✅ Done | TestEvents (4 tests, immutability + sequence + replay) |
| Deterministic state transitions | ✅ Done | TestLifecycleTransitions (illegal raised, BFS multi-hop) |
| AgentRunner compatibility facade | ✅ Done | RuntimeBackedAgentRunner, TestFacade (is-a + run/resume tracking) |
| Lifecycle tests | ✅ Done | 48 tests in tests/unit/test_agent_runtime.py |

## Phase 3 evidence

Implemented (typed model-facing Tool Registry; NO LLM loop, NO new framework,
NO Playwright code outside the existing executor):

- `app/agent/tools/base.py` — `ToolMetadata` (name/description/family, strict
  input+output schemas, read_only, destructive, requires_user_interaction,
  interrupt_behavior, policy_class, concurrency, accepts_browser_action),
  `ToolCall` (tool_name + arguments + typed BrowserAction), `ToolResult`
  (success/error_code/message/payload/observation_id/post_observation/
  policy_allowed/verification_status), `ToolContext` (the ONLY handle a tool
  gets: observation, page, executor, observer, resolvers — no path to
  AgentRunState), `Tool` ABC with validate→execute→normalize template,
  strict pydantic output models per tool family.
- `app/agent/tools/registry.py` — `ToolRegistry`: model-facing catalog + the
  ONE fail-closed execution gate (unknown tool → TOOL_NOT_FOUND; browser tool
  without typed action → TOOL_SCHEMA_INVALID; stray action on non-action tool
  → INVALID_TOOL_CALL; missing observation → MISSING_CONTEXT; schema-invalid
  arguments → TOOL_SCHEMA_INVALID; duplicate registration raises).
- `app/agent/tools/browser_tools.py` — 14 adapters over the EXISTING
  foundation (observe_page, inspect_field, inspect_options, navigate,
  wait_for_state, click, fill_field, select_option, check_control,
  uncheck_control, upload_document, scroll, press_key, go_back). All
  mutations delegate to BrowserExecutor.execute (PolicyEngine + document
  policy + verification intact, not duplicated); navigate reuses
  BrowserManager's trusted-domain gate; read tools reuse PageObserver.
- `app/agent/tools/user_tools.py` — request_user_input /
  request_authentication / request_confirmation (pauses-run metadata;
  handoff_browser deliberately absent until Phase 10).
- `app/agent/tools/vault_tools.py` — resolve_user_reference,
  resolve_document_reference, inspect_available_documents (sensitive
  refs return a resolution HANDLE; raw values/paths never appear in
  results).
- `app/agent/runtime/decision.py` — AgentDecision widened backward-
  compatibly: TOOL_CALL may carry tool_name + arguments (48 Phase 2
  runtime tests still pass unchanged).

### Phase 3 test counts (verified at current HEAD, 2026-09-19)

```
pytest tests/unit/test_tool_registry.py -q
→ 31 passed in 0.49s

pytest tests/synthetic_forms/test_tool_agent.py -q
→ 4 passed in 9.35s (real Chromium)

pytest tests/unit/ tests/integration/ tests/synthetic_forms/ -q
→ 589 passed in 148.50s
```

### Phase 3 exit criterion

"A synthetic agent can complete a multi-step form through typed tool calls":
verified by `tests/synthetic_forms/test_tool_agent.py::
TestMultiStepFormViaTypedToolCalls::test_completes_all_three_steps` — a
deterministic driver (NO LLM, Phase 4) drives the multistep.html wizard
directly against Chromium: every action is a typed ToolCall (observe_page ×3,
fill_field ×4, select_option ×1, click ×2) validated by the registry, executed
by the existing BrowserExecutor (policy + verification intact), followed by
fresh post-action observations, ending on the review/submit step with
10/10 successful results and WorkflowState updated only from ToolResults.

### Phase 3 status

| Item | Status | Evidence |
|------|--------|----------|
| Tool protocol/base | ✅ Done | app/agent/tools/base.py, TestToolProtocol |
| Tool metadata model | ✅ Done | ToolMetadata (all 8 context.md fields + accepts_browser_action) |
| ToolRegistry | ✅ Done | registry.py, TestRegistryGates (fail-closed) |
| Strict input/output schemas | ✅ Done | pydantic per tool; output schema enforced |
| Permission metadata | ✅ Done | read_only/destructive/requires_user_interaction/interrupt/policy_class/concurrency, TestMetadataPermissionModel |
| Tool-result normalization | ✅ Done | ToolResult stable shape incl. policy_allowed + verification_status |
| Existing capabilities adapted | ✅ Done | BrowserExecutor/PageObserver/BrowserManager reused, zero duplicated policy/verification |
| Permission/registry tests | ✅ Done | 31 unit tests |
| Multi-step exit criterion | ✅ Done | 4 synthetic tests incl. runtime-lifecycle integration |

Deliberately deferred: agent-services family (reflect/replan/verify_goal —
Phases 5/7), handoff_browser + specialist tools (Phase 10), ToolContext
auto-derivation inside AgentRuntime (natural Phase 4 loop wiring).

## Phase 4 evidence

Implemented (additive; NO Phase 1–3 file modified — the reasoner is a new
caller of the existing registry/executor path):

- `app/agent/reasoning/protocol.py` — `DecisionModel` protocol (prompt in,
  parsed JSON out; the ONLY model capability), `ReasonerDecisionSchema`
  (strict, extra=forbid), `build_decision_json_schema()` (OpenRouter
  structured-output schema derived from the same pydantic model — prompt
  and validation contracts cannot drift), `ReasoningOutcome`
  (decided | explicit MODEL_FAILURE), DECISION_* failure codes,
  `decision_to_tool_call`.
- `app/agent/reasoning/context.py` — minimal bounded context assembler
  (goal, current subgoal, plan state, verified WorldState summary,
  authoritative page observation, tool schemas, semantic reference NAMES,
  recent ToolResults, unresolved questions, runtime constraints; caps:
  60 elements / 5 recent results / 1500 chars visible text; the ToolResult
  payload filter is KEY-based — value-bearing keys such as
  `resolved_value` can never reach the prompt).
- `app/agent/reasoning/parser.py` — strict decision parsing: schema →
  decision-type allow-list (HANDOFF reserved, Phase 10) → registered-tool
  check → typed BrowserAction (pydantic validators incl. sensitive-literal
  policy) → AgentDecision. The runtime stamps the CURRENT observation_id
  onto every browser action; a stale id in the model's dict is
  overwritten, never trusted.
- `app/agent/reasoning/reasoner.py` — `AgentReasoner`: bounded retries
  (default 3, hard cap 5) with rejection feedback on repair attempts;
  explicit MODEL_FAILURE on exhaustion; holds only frozen tool-name sets —
  no registry/executor/page/runtime handle, so it cannot execute anything
  by construction.
- `app/agent/reasoning/mock_model.py` — deterministic scripted model
  (dicts / callables / exceptions per call; no API key).
- `app/agent/reasoning/openrouter_model.py` — `OpenRouterDecisionModel`
  over the EXISTING `LLMGateway` (strict json_schema response_format,
  temperature 0); non-JSON/non-object output raises `InvalidModelOutput`
  → reasoner retries → explicit MODEL_FAILURE; building without an API
  key raises (fail closed — never silently degrades to deterministic).

### Phase 4 test counts (verified at current HEAD, 2026-09-19)

~~~
pytest tests/unit/test_agent_reasoner.py -q
→ 28 passed in 0.63s

pytest tests/unit/test_reasoning_replay.py -q
→ 6 passed in 1.80s

pytest tests/unit/test_openrouter_decision_model.py -q
→ 10 passed in 0.51s (offline — stub gateway, no live key)

pytest tests/synthetic_forms/test_reasoning_loop.py -q
→ 4 passed in 6.44s (real Chromium)

pytest tests/unit/ tests/integration/ tests/synthetic_forms/ -q
→ 637 passed in 191.92s (539 unit + 59 integration + 39 synthetic)
~~~

### Phase 4 exit criterion

"The model chooses among multiple tools over multiple iterations while
deterministic runtime rules remain authoritative": verified by
`tests/synthetic_forms/test_reasoning_loop.py::
TestMockModelCompletesWizard::test_model_chooses_multiple_tools_over_multiple_iterations`
— the scripted decision model drives the multistep.html wizard in real
Chromium through the full loop (context assembly → AgentReasoner →
schema-validated AgentDecision → ToolRegistry → BrowserExecutor →
ToolResult → next context), choosing 4 DIFFERENT tools over 10 iterations
(observe_page ×3, fill_field ×4, select_option ×1, click ×2), 10/10
results successful, ending on the review/submit step. Policy +
verification ran inside the existing executor path on every mutation;
the reasoner never touched the browser. Deterministic rules stayed
authoritative in the failure path too: a bogus-ref fill failed closed
with STALE_OR_INVALID_TARGET, the failure was surfaced to the model in
the next context (recent_tool_results), and recovery was model-chosen.

The ten required mock-model behaviors (user instruction, Phase 4), all
proven in `tests/unit/test_agent_reasoner.py` + the synthetic suite:

1. model selects observe_page — TestModelSelectsObservePage
2. model selects fill_field (literal + value_ref semantic reference) —
   TestModelSelectsFillField
3. model selects select_option — TestModelSelectsSelectOption
4. model handles tool failure and chooses another action —
   TestModelHandlesToolFailure + synthetic recovery test
5. malformed tool call rejected (missing action, broken action dict) —
   TestMalformedToolCallRejected
6. unknown tool rejected at the parser AND still at the registry —
   TestUnknownToolRejected
7. transport errors + persistently malformed output → explicit
   MODEL_FAILURE (code + `model_failure:` reason prefix, attempts
   bounded, decision None, no fabricated fallback) —
   TestExplicitModelFailure
8. multiple iterations work (observe → fill → select → complete with
   per-iteration observation binding) — TestMultipleIterations
9. replay produces the same decisions/results/prompts from recorded
   inputs across independent episodes (incl. a failure episode) —
   tests/unit/test_reasoning_replay.py
10. model cannot bypass policy through tool arguments (sensitive-literal
   rejection, extra-field rejection at the strict schema, action on a
   read-only tool rejected, observation-id override) —
   TestPolicyBypassPrevention

Note: `OpenRouterDecisionModel` is unit-tested OFFLINE (stub gateway); a
live OpenRouter smoke test requires a real API key and remains
outstanding — it is not required for the Phase 4 exit criterion.

## Phase 5 evidence

Implemented (additive, `app/agent/strategy/*`; NO Phase 1–4 file modified
except two compatibility guards in the Phase 5 manager itself — the
Phase 4 reasoner, Phase 3 registry, Phase 2 runtime are untouched):

- `app/agent/strategy/models.py` — `AgentGoal` (raw + normalized
  description + typed success criteria), `AgentPlan` (versioned,
  ordered subgoals, validate_structure: duplicate ids/orders, unknown
  deps, dependency cycles, boundary placement), `Subgoal`
  (explicit 7-state lifecycle + machine-readable status reasons),
  `SuccessCriterion` (10 typed predicate kinds — explicit and testable,
  never natural-language confidence), `PlanRevision` (revision id,
  number, reason, affected subgoal ids, previous/new version, timestamp,
  triggering event, previous subgoal shapes), `FinalSubmissionGate` /
  `IllegalSubgoalTransition` / `PlanInvalid` / `SubgoalNotFound`.
- `app/agent/strategy/criteria.py` — `Snapshot` (thin projection of
  WorkflowState + PageObservation; Phase 6 will replace the sources,
  not the contract) + deterministic `evaluate_criteria` (unknown kinds
  fail CLOSED as uncertain) + three-valued `criteria_verdict`
  (satisfied / deterministic-failure / uncertain — never confidence).
- `app/agent/strategy/goal_parser.py` — deterministic goal parser
  (keyword/shape classification; ambiguity becomes explicit unresolved
  questions; multi-step + review-boundary detection; reference NAMES
  only, never values; no LLM).
- `app/agent/strategy/plan_builder.py` — deterministic initial plan
  builder (portal-agnostic step templates; strict dependency chain;
  explicit final-submission boundary subgoal).
- `app/agent/strategy/manager.py` — `AgentPlanManager`: table-validated
  subgoal transitions (illegal → raise, never coerced), evidence-based
  completion (`complete` refuses unsatisfied criteria; no bypass),
  `activate_next`/`next_actionable` NEVER target the boundary subgoal
  (`at_final_boundary` parks the run at the human gate), `recover_blocked`
  after revisions, `revise` replaces ONE subgoal (id/order/dependents
  preserved; COMPLETED refused; prior shape snapshotted into the
  PlanRevision; original invalidation evidence preserved).
- New page: `tests/synthetic_forms/pages/dynamic_step_change.html`
  (Stage 1 contact layout replaced by Stage 2 phone/address layout).

### Phase 5 test counts (verified at current HEAD, 2026-09-19)

~~~
pytest tests/unit/test_agent_strategy.py -q
→ 42 passed in 0.31s

pytest tests/synthetic_forms/test_strategy_loop.py -q
→ 1 passed in 4.79s (real Chromium)

pytest tests/unit/test_agent_runtime.py -q            (Phase 2)
→ 48 passed

pytest tests/unit/test_tool_registry.py tests/synthetic_forms/test_tool_agent.py -q   (Phase 3)
→ 35 passed

pytest tests/unit/test_agent_reasoner.py tests/unit/test_reasoning_replay.py \
  tests/unit/test_openrouter_decision_model.py tests/synthetic_forms/test_reasoning_loop.py -q   (Phase 4)
→ 48 passed

pytest tests/unit/ tests/integration/ tests/synthetic_forms/ -q
→ 680 passed in 177.25s (581 unit + 59 integration + 40 synthetic)
~~~

### Phase 5 exit criterion

"A local page change can invalidate one subgoal without destroying the
overall goal": verified by `tests/synthetic_forms/test_strategy_loop.py::
TestDynamicFormInvalidation::test_page_change_invalidates_one_subgoal_goal_survives`
— real Chromium + mock decision model + REAL strategy/reasoning/registry
stack: the plan (5 subgoals) completes "Fill primary details", the
Continue click swaps the contact layout, the deterministic invalidation
check finds the active subgoal's expected fields gone and invalidates it
(evidence preserved on the subgoal), the model proposes a REPLAN, the
manager applies the revision (version 1→2, prior shape snapshotted,
id/order/dependents preserved), previously completed subgoals remain
COMPLETED, the goal stays active, and the agent continues from the
REVISED subgoal — filling the new phone/address fields — ending parked
at the final-submission boundary (`at_final_boundary`, boundary still
PENDING: a human decision).

Ten required proofs (tests/unit/test_agent_strategy.py):

1. goal → structured AgentGoal — TestGoalParsing
2. initial multi-step plan — TestInitialPlan
3. dependencies respected — TestDependencies
4. deterministic transitions — TestDeterministicTransitions
5. completed subgoals remain completed — TestCompletedWorkIsStable
6. local invalidation preserves goal — TestLocalInvalidation
7. revision preserves unaffected subgoals — TestRevision
8. final-submission boundary explicit — TestFinalSubmissionBoundary
9. invalid plans rejected — TestInvalidPlansRejected
10. serialization round-trip — TestSerialization

## Phase tracker

| Phase | Status |
|---|---|
| 0 Control plane | COMPLETE |
| 1 Browser foundation | COMPLETE |
| 2 AgentRuntime | COMPLETE (deterministic core; LLM loop is Phase 4) |
| 3 Tool Registry | COMPLETE (typed registry + adapters; LLM loop is Phase 4) |
| 4 OpenRouter agent loop | COMPLETE (mock-model loop proven; real OpenRouterDecisionModel behind the same DecisionModel contract; live-key smoke test outstanding) |
| 5 Goal/Subgoal | COMPLETE (deterministic strategic layer; exit criterion proven on dynamic-form scenario) |
| 6 WorldState | NOT STARTED |
| 7 Reflection/Recovery | NOT STARTED |
| 8 Durable HITL | NOT STARTED |
| 9 Memory | NOT STARTED |
| 10 Specialist agents | NOT STARTED |
| 11 Security hardening | PARTIAL |
| 12 Evaluation | PARTIAL |
| 13 Enterprise runtime | NOT STARTED |
| 14 Live portal validation | NOT STARTED |
| 15 Production readiness | NOT STARTED |

## Production gates

## Existing foundation

Known from repository inspection:

- Playwright browser layer exists.
- Page observation exists.
- Semantic field mapping exists.
- Typed browser actions exist.
- Policy engine exists.
- Vault/document reference components exist.
- Verification exists.
- Tab awareness exists.
- Repeated-action stall detection exists.
- Synthetic/unit/integration/safety tests exist.

These are capabilities, not current release certification.

## Phase 1 immediate work

The next coding agent must first establish the current baseline and stabilize the browser foundation before changing the agent architecture.

Required first evidence:

~~~text
environment/dependencies
→ test count
→ failing tests
→ Playwright launch check
→ synthetic observe/act/verify/re-observe
~~~

Then update this file with exact commands and results.

## Main architectural gap

Transform:

~~~text
LLM planner inside AgentRunner
~~~

into:

~~~text
persistent AgentRuntime
+ tool registry
+ goal/subgoal state
+ WorldState
+ reasoning loop
+ verification
+ reflection
+ memory
+ durable checkpoints
~~~

## Production gates

Phase 1 completion:
- [x] current regression suite green (554 tests, 0 failures)
- [x] persistent AgentSession (Phase 2 — serializable session/run/checkpoint; SQLite store is Phase 8)
- [x] policy on every mutation (PolicyEngine wired into BrowserExecutor)
- [x] verification on every mutation (8 per-action verifiers)
- [ ] durable human interrupts (Phase 8)
- [ ] prompt-injection suite (stub exists: tests/prompt_injection/)
- [ ] evaluation metrics (Phase 12)
- [x] live observation-only validation (tests/real_sites/test_pmkisan_observe.py)
- [ ] isolated worker runtime (Phase 13)
