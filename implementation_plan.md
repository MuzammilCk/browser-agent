# IMPLEMENTATION PLAN — Agent Runtime Transformation

## Status

Phase 0 — Control-plane preparation  
Phase 1 — Browser foundation (COMPLETE)  
Phase 2 — AgentSession/AgentRuntime (COMPLETE)  
Phase 3 — Tool Registry (COMPLETE)  
Phase 4 — OpenRouter agent loop (COMPLETE)  
Phase 5 — Goal / Plan / Subgoal (COMPLETE)  
Phase 6 — WorldState (COMPLETE)  
Phase 7 — Reflection/Recovery (COMPLETE)  
Phase 8 — Durable Human Interrupts (COMPLETE)  
Phase 9 — Memory + Compaction (COMPLETE)Phase 10 — Restricted Specialist Agents (COMPLETE)   
Phase 11 — Security Hardening (COMPLETE)   
Phase 12 — Evaluation Platform (COMPLETE)   
Phase 13 — Enterprise Runtime (COMPLETE)   
Phase 14 — Live Portal Validation (COMPLETE)   
Overall: IN PROGRESS (Phases 0–14 complete; Phase 15 next)     
Evidence policy: every checkbox requires current evidence.

---

# Phase 0 — Control plane

Deliver:

- [x] AGENTS.md
- [x] context.md
- [x] implementation_plan.md
- [x] docs/ARCHITECTURE_TARGET.md
- [x] docs/AGENT_PROTOCOL.md
- [x] docs/BUILD_STATUS.md
- [x] docs/DECISIONS.md
- [x] docs/SECURITY_MODEL.md
- [x] docs/EVAL_PLAN.md

Exit criteria:

- [x] legacy docs point to canonical files
- [x] no stale test-count claims are presented as current evidence (BUILD_STATUS.md has current baseline)
- [x] source-of-truth precedence is explicit (in AGENTS.md)

---

# Phase 1 — Stabilize browser foundation

Goal: freeze reliable Playwright primitives before agent refactoring.

Retain:

- BrowserManager
- PageObserver
- ARIA/DOM perception
- frames
- locator
- executor
- verification
- tab tracker
- bounded vision fallback
- trusted-domain registry

Tasks:

- [x] run current test suite → 506 passed, 0 failed
- [x] record exact current baseline → docs/BUILD_STATUS.md
- [x] synthetic coverage: text/select/radio/checkbox/file/iframe/dynamic/validation → 31 synthetic tests + 14 verification tests
- [x] stale-reference tests → TestStaleRefRejection (2 tests)
- [x] multi-tab tests → TestTargetBlankClick + TestObservationReportsTabs + TestManagerTabTracking + TestRunnerTabSwitchTrace (11 tests)
- [x] no swallowed browser errors → TestBrowserErrorVisibility (3 new tests)

New files for Phase 1 coverage:
- tests/synthetic_forms/pages/file_upload.html
- tests/synthetic_forms/pages/iframe.html
- tests/integration/test_browser_errors.py

Exit:

~~~text
observe → act → verify → re-observe
works without an LLM.
~~~

Evidence: all 506 tests passed at Phase 1 completion (superseded at Phase 2 HEAD
by the 554-test baseline: 464 unit + 59 integration + 31 synthetic, 0 failures).

---

# Phase 2 — AgentSession and AgentRuntime

Goal: establish the persistent agent runtime.

Create:

- AgentSession
- AgentRuntime
- AgentEvent
- AgentCheckpoint
- AgentDecision
- AgentRunState

State includes:

- run id
- goal
- plan
- current subgoal
- WorldState
- memory handles
- browser/session handle
- pending interrupt
- lifecycle
- iteration
- cost/usage counters
- timestamps
- parent/child agent metadata

Runtime states:

~~~text
INITIALIZING
OBSERVING
REASONING
ACTING
VERIFYING
REFLECTING
WAITING_FOR_USER
READY_FOR_REVIEW
READY_FOR_CONFIRMATION
COMPLETED
FAILED
ABORTED
~~~

Tasks:

- [x] Pydantic models (app/agent/runtime/*.py; 48 lifecycle tests)
- [x] serializable state (lossless JSON round-trip incl. cross-runtime restore)
- [x] event append/replay (frozen AgentEvent, monotonic sequence, ordered replay)
- [x] deterministic state transitions (explicit table; illegal transitions raise)
- [x] AgentRunner compatibility facade (RuntimeBackedAgentRunner, same run/resume contract)
- [x] lifecycle tests (tests/unit/test_agent_runtime.py: 48 passed)

Exit:

A paused run can be serialized and restored without losing logical task state.

Evidence (verified at current HEAD, 2026-09-19): READY_FOR_CONFIRMATION run
exports to JSON (`AgentRuntime.export_run_json`) and restores into a FRESH
`AgentRuntime` (`restore_checkpoint_from_json`) with goal, subgoal, iteration,
workflow state, pending interrupt, and full event log intact:

- `TestCheckpoints::test_restored_run_preserves_logical_task_state` — asserts
  goal, subgoal, iteration=4, lifecycle=READY_FOR_CONFIRMATION,
  world_state.status, world_state.total_actions, actions_taken[0].binding,
  and pending_interrupt.kind survive the round-trip. PASSED.
- `TestCheckpoints::test_restored_run_replays_full_event_log` — restored event
  log = captured log + 1 `RUN_RESTORED`, sequence continuity 1..N+1. PASSED.
- `TestCheckpoints::test_json_round_trip_lossless` — JSON round-trip equality.
  PASSED.

Phase 2 tests: 48 passed (tests/unit/test_agent_runtime.py). Full regression:
554 passed, 0 failed (464 unit + 59 integration + 31 synthetic).
Note: HANDOFF decision type is deliberately reserved for Phase 10; memory
handles are placeholders by design; SQLite checkpoint store is Phase 8.

---

# Phase 3 — Tool Registry

Goal: make typed tools the model-facing interface.

Tool metadata:

- name
- description
- input schema
- output schema
- read-only
- destructive
- user interaction required
- interrupt behavior
- policy class
- concurrency semantics

Initial tools are defined in context.md.

Tasks:

- [x] Tool protocol/base (app/agent/tools/base.py: Tool ABC, ToolMetadata,
      ToolCall, ToolResult, ToolContext; validate→execute→normalize template)
- [x] registry (ToolRegistry: catalog + fail-closed execution gate —
      TOOL_NOT_FOUND / TOOL_SCHEMA_INVALID / INVALID_TOOL_CALL /
      MISSING_CONTEXT; duplicate registration raises)
- [x] adapt existing executor operations (14 browser tools delegating to
      BrowserExecutor.execute — policy + verification reused, not duplicated;
      navigate via BrowserManager trusted-domain gate)
- [x] strict schemas (pydantic input schemas per tool; output schema
      validated at the Tool base — malformed tool output fails closed)
- [x] permission metadata (read_only, destructive, requires_user_interaction,
      interrupt_behavior, policy_class, concurrency, accepts_browser_action)
- [x] tool-result normalization (stable ToolResult: error_code taxonomy incl.
      POLICY_DENIED / CONFIRMATION_REQUIRED / USER_ACTION_REQUIRED /
      VERIFICATION_FAILED; policy_allowed + verification_status promoted to
      first-class fields; fresh post_observation carried to the next decision)
- [x] tool permission tests (tests/unit/test_tool_registry.py: 31 tests)

Exit:

A synthetic agent can complete a multi-step form through typed tool calls.

Evidence (verified at current HEAD, 2026-09-19): deterministic driver (NO LLM)
completes the multistep.html wizard in real Chromium using only typed
ToolCalls through ToolRegistry.execute — observe_page ×3, fill_field ×4,
select_option ×1, click ×2, all schema-validated, executed via the existing
BrowserExecutor (policy + verification intact), each followed by fresh
post-action observations, ending on the review/submit step (10/10 results
successful; WorkflowState updated only from ToolResults).
tests/synthetic_forms/test_tool_agent.py::
TestMultiStepFormViaTypedToolCalls::test_completes_all_three_steps — PASSED.
AgentDecision widened backward-compatibly (tool_name + arguments); all 48
Phase 2 runtime tests pass unchanged. Full regression: 589 passed, 0 failed
(495 unit + 59 integration + 35 synthetic).
Note: metadata is descriptive; PolicyEngine stays authoritative. Agent-services
tools (reflect/replan/verify_goal) are Phases 5/7; handoff_browser and
specialist tools are Phase 10.

---

# Phase 4 — OpenRouter agent loop

Goal: the LLM becomes the decision-making controller inside the runtime.

Target:

~~~text
LLM
 ↓
AgentDecision
 ↓
ToolCall
 ↓
ToolRegistry
 ↓
Policy
 ↓
Executor
 ↓
ToolResult
 ↓
LLM
~~~

Tasks:

- [x] AgentReasoner (app/agent/reasoning/reasoner.py — model-agnostic,
      holds only frozen tool-name sets, no registry/executor/page handle)
- [x] structured OpenRouter tool calling (app/agent/reasoning/
      openrouter_model.py — OpenRouterDecisionModel over the EXISTING
      LLMGateway/OpenRouterGateway; strict json_schema response_format
      derived from ReasonerDecisionSchema via build_decision_json_schema;
      unit-tested offline with a stub gateway — no live key required or
      used; live-key smoke test outstanding)
- [x] minimal context assembler (app/agent/reasoning/context.py —
      bounded: 60 elements / 5 recent results / 1500 visible-text chars;
      key-based ToolResult payload whitelist so value-bearing keys such
      as resolved_value never reach the prompt; semantic reference NAMES
      only, never values; no policy internals)
- [x] strict decision validation (app/agent/reasoning/parser.py — strict
      schema extra=forbid → decision-type allow-list (HANDOFF reserved
      Phase 10) → registered-tool check → typed BrowserAction →
      AgentDecision; runtime stamps CURRENT observation_id, overriding
      any model-supplied stale id)
- [x] bounded model retries (ReasonerConfig.max_attempts default 3,
      hard cap 5; rejection reason fed back on repair attempts)
- [x] visible model failures (ReasoningOutcome.phase=MODEL_FAILURE with
      machine-readable code DECISION_PARSE_FAILED / DECISION_SCHEMA_INVALID /
      DECISION_VALIDATION_FAILED and a `model_failure:` reason prefix)
- [x] explicit fallback state, never silent fallback (retries exhausted →
      ReasoningOutcome.model_failure with decision=None; no deterministic
      decision is ever fabricated — proven by
      TestExplicitModelFailure::test_never_falls_back_to_a_deterministic_decision)
- [x] mock-model tests (tests/unit/test_agent_reasoner.py: 28 tests on
      the deterministic MockDecisionModel — no API key; plus 3 Chromium
      loop tests in tests/synthetic_forms/test_reasoning_loop.py)
- [x] replay tests (tests/unit/test_reasoning_replay.py: 6 tests —
      identical prompts/decisions/results/executor calls across
      independent episodes, including a tool-failure episode)

Exit:

The model chooses among multiple tools over multiple iterations while deterministic runtime rules remain authoritative.

Evidence (verified at current HEAD, 2026-09-19):
tests/synthetic_forms/test_reasoning_loop.py::
TestMockModelCompletesWizard::test_model_chooses_multiple_tools_over_multiple_iterations —
the scripted decision model drives multistep.html in real Chromium
through context assembly → AgentReasoner → schema-validated
AgentDecision → ToolRegistry → BrowserExecutor → ToolResult → next
context, choosing 4 different tools over 10 iterations (observe_page ×3,
fill_field ×4, select_option ×1, click ×2), 10/10 successful, ending on
the review/submit step. Policy + verification ran inside the existing
executor path on every mutation; the reasoner holds no browser handle.
Failure path: a bogus-ref fill failed closed (STALE_OR_INVALID_TARGET),
the failure surfaced to the model in the next context's
recent_tool_results, recovery was model-chosen. Phase 4 tests: 44 unit
(28 reasoner + 6 replay + 10 OpenRouter adapter, offline) + 4 synthetic
(real Chromium). Full regression: 637 passed, 0 failed (539 unit + 59
integration + 39 synthetic).
Note: the decision interface is structured JSON-schema output validated
against the registry catalog (not OpenRouter's native function-calling
API) so the prompt contract and the validation contract are the same
pydantic model; AgentRuntime auto-derivation of ToolContext remains a
later wiring task — Phase 4 runs the loop against the existing
facade/driver path without redesigning Phases 1–3.

---

# Phase 5 — Goal / Plan / Subgoal

Goal: provide strategic context without creating brittle scripts.

Models:

- AgentGoal
- AgentPlan
- Subgoal
- SuccessCriterion
- PlanRevision

Tasks:

- [x] goal parser (app/agent/strategy/goal_parser.py — deterministic
      keyword/shape classification; ambiguity becomes explicit
      unresolved questions; reference NAMES only; no LLM)
- [x] initial plan creation (app/agent/strategy/plan_builder.py —
      portal-agnostic step templates, strict dependency chain,
      structurally validated at build)
- [x] subgoal lifecycle (7-state table-validated state machine with
      machine-readable SubgoalStatusReason; illegal transitions raise —
      app/agent/strategy/manager.py)
- [x] dependencies (depends_on chains enforced by activate_next;
      failed/invalidated deps BLOCK downstream; unknown deps and cycles
      rejected by validate_structure)
- [x] plan invalidation (INVALIDATED status with causal evidence;
      deterministic invalidation check demonstrated in the acceptance
      test — expected fields absent from the fresh observation)
- [x] plan revision (AgentPlanManager.revise replaces ONE subgoal —
      id/order/dependents preserved, prior shape snapshotted into
      PlanRevision, COMPLETED subgoals refused; recover_blocked re-opens
      BLOCKED steps after revision)
- [x] final-submission boundary in plan (boundary subgoal is
      explicit; FinalSubmissionGate blocks activation/completion/
      revision/any transition; next_actionable and activate_next skip
      it; at_final_boundary parks the run at the human gate)
- [x] dynamic-form tests (tests/synthetic_forms/test_strategy_loop.py
      + new page tests/synthetic_forms/pages/dynamic_step_change.html)

Exit:

A local page change can invalidate one subgoal without destroying the overall goal.

Evidence (verified at current HEAD, 2026-09-19):
tests/synthetic_forms/test_strategy_loop.py::
TestDynamicFormInvalidation::test_page_change_invalidates_one_subgoal_goal_survives —
real Chromium + mock decision model + the REAL strategy/reasoning/registry
stack: "Fill primary details" completes; the Continue click swaps the
contact layout (dynamic_step_change.html); the deterministic
invalidation check finds the active subgoal's expected fields gone and
invalidates it (causal evidence preserved); the model proposes a REPLAN;
the manager applies the revision (plan version 1→2, prior shape
snapshotted into PlanRevision, id/order/dependents preserved); completed
subgoals remain COMPLETED; the goal stays active; the agent continues
from the REVISED subgoal and fills the new phone/address fields; the run
ends parked at the final-submission boundary (at_final_boundary — a
human decision, never planner-actionable). Phase 5 tests: 42 unit + 1
synthetic. Regression: Phase 2 (48), Phase 3 (35), Phase 4 (48) all
green; full suite 680 passed, 0 failed (581 unit + 59 integration + 40
synthetic).
Note: criteria are evaluated against a thin Snapshot of
WorkflowState+PageObservation; the WorldState redesign that owns those
sources is Phase 6. AgentRunState.plan wiring (typed plan into the
Phase 2 runtime + events) is deliberate later wiring, not Phase 5 scope.

---

# Phase 6 — WorldState

Goal: separate semantic workflow state from DOM refs.

Track:

- portal
- page
- tabs
- semantic fields
- mappings
- verified values
- validation
- authentication
- documents
- completed subgoals
- unresolved questions
- evidence

Tasks:

- [x] AgentWorldState (app/agent/world/models.py — durable semantic workflow
      state, tracks portal, page, tabs, semantic fields, field mappings,
      verified values, validation errors, auth challenge, documents, completed
      subgoals, unresolved questions, monotonic version, immutable provenance log)
- [x] observation reducer (app/agent/world/reducer.py — reduce_observation,
      record_verified_action, record_tool_result; epistemic hierarchy
      VERIFIED > OBSERVED > INFERRED > STALE; verified facts survive DOM rerenders)
- [x] semantic IDs (app/agent/world/semantic_id.py — compute_semantic_id stable
      slugs from HTML name, accessible name, label, section context, and type)
- [x] stale-ref invalidation (app/agent/world/reducer.py — is_target_ref_valid;
      ephemeral DOM refs invalidated when observation changes or elements disappear;
      actions targeting stale refs fail closed)
- [x] dynamic form continuity (tests/synthetic_forms/test_world_state_loop.py::
      TestDynamicFormContinuity — state selection verified, dependent district field
      appears, state verified fact preserved, district introduced with status OBSERVED)
- [x] multi-tab continuity (tests/synthetic_forms/test_world_state_loop.py::
      TestMultiTabContinuity — tabs tracked in TabWorldState, active tab changes
      preserve inactive tab state, actions on stale tab refs rejected, switching back
      restores semantic continuity)

Exit:

DOM rerenders do not erase verified semantic progress.

Evidence (verified at current HEAD, 2026-09-19):
tests/synthetic_forms/test_world_state_loop.py (2 passed in 62.03s, real Chromium):
1. TestDynamicFormContinuity::test_dynamic_district_dropdown_appearance_preserves_state:
   State selection verified on dropdowns.html (field:state = "kerala", status=VERIFIED);
   page re-renders with dependent district dropdown; reducer updates WorldState:
   state verified value remains intact, district added with status OBSERVED, old DOM
   refs invalidated, new refs actionable; district selected and verified
   (field:district = "ernakulam", status=VERIFIED); block field appears with all
   prior progress intact.
2. TestMultiTabContinuity::test_tab_switching_preserves_verified_progress:
   Tab A verified progress (field:fullname = "Priya Sharma"); Tab B opens; both
   tabs tracked in WorldState; active tab switches to Tab B; Tab A state preserved;
   actions on stale Tab A refs while on Tab B rejected; Tab B field filled and
   verified; switching back to Tab A restores semantic continuity with all verified
   facts intact.
Phase 6 unit tests: 14 passed in tests/unit/test_agent_world_state.py.
Full regression suite: 696 passed, 0 failed (595 unit + 59 integration + 42 synthetic).

---

# Phase 7 — Verification + reflection + recovery

Goal: recover intelligently rather than repeat blindly.

Failure taxonomy:

- TARGET_NOT_FOUND
- AMBIGUOUS_FIELD
- INVALID_OPTION
- VALIDATION_FAILURE
- STALE_REFERENCE
- PAGE_CHANGED
- NAVIGATION_FAILURE
- AUTHENTICATION_REQUIRED
- PROMPT_INJECTION
- TOOL_FAILURE
- MODEL_FAILURE
- TIMEOUT
- POLICY_DENIED

Tasks:

- [x] ReflectionResult (app/agent/recovery/models.py — ReflectionResult, RecoveryDecision,
      FailureEvidence, FailureClassification, RecoveryBudget, RecoveryAttemptRecord,
      canonical 13-type FailureType enum, RecoveryStrategy enum)
- [x] bounded reflection (app/agent/recovery/reflector.py — RecoveryReflector; evaluates
      failure evidence and recommends next strategy; cannot execute browser tools directly;
      enforces per-type, per-subgoal, and total run budgets; fails closed on injection and policy denial)
- [x] stale-target recovery (app/agent/recovery/manager.py — RecoveryManager; on STALE_REFERENCE,
      triggers re-observation, re-resolves durable semantic_id in AgentWorldState, and derives
      fresh typed ToolCall targeting updated observation ref; fails safely if ambiguous)
- [x] validation recovery (app/agent/recovery/reflector.py + classifier.py — detects VALIDATION_FAILURE
      from tool result or page state; recommends REVISE_INPUT_AND_RETRY with modified arguments within budget)
- [x] navigation recovery (app/agent/recovery/reflector.py + classifier.py — classifies NAVIGATION_FAILURE,
      authorizes bounded retry, and terminates with TERMINAL_FAILURE if unrecoverable)
- [x] model-failure recovery (app/agent/recovery/reflector.py + classifier.py — explicit MODEL_FAILURE
      classification from ReasoningOutcome; bounded retry without fabricating fallback decisions)
- [x] repeated-action integration (app/agent/recovery/classifier.py — classifies StallDetector stall
      verdicts into TOOL_FAILURE / STALE_REFERENCE, stopping repeated loops and forcing replanning)
- [x] recovery tests (tests/unit/test_agent_recovery.py: 15 unit tests covering all required recovery
      behaviors, fail-closed boundaries, and budget enforcement; tests/synthetic_forms/test_recovery_loop.py:
      full loop acceptance in real Chromium with dynamic layout mutation)

Exit:

The agent changes strategy after meaningful failures and stops when no safe strategy remains.

Evidence (verified at current HEAD, 2026-09-19):
tests/synthetic_forms/test_recovery_loop.py::
TestRecoveryLoop::test_stale_target_recovery_preserves_verified_progress —
real Chromium + dynamic synthetic form (tests/synthetic_forms/pages/dynamic_recovery.html):
Personal details (fullname = "Asha Kumar") filled and verified in AgentWorldState;
page dynamically mutates into stage 2 layout, invalidating previous PIN code ref `e2`;
subsequent fill on stale ref produces STALE_REFERENCE;
FailureClassifier classifies the failure; RecoveryReflector confirms recovery budget and recommends
RETRY_WITH_FRESH_TARGET; runtime re-observes; AgentWorldState reduces fresh observation and binds
field:pincode to fresh ref `e5`; RecoveryManager derives fresh typed tool call targeting `e5`;
BrowserExecutor executes it through ToolRegistry and PolicyEngine; verification succeeds;
verified semantic progress remains 100% intact; complete RecoveryAttemptRecord is recorded in audit log.
Phase 7 tests: 15 unit + 1 synthetic.
Full regression suite: 712 passed, 0 failed (610 unit + 59 integration + 43 synthetic).

---

# Phase 8 — Durable human interrupts

Goal: OTP/CAPTCHA/auth/clarification/confirmation become persistent resumable states backed by PostgreSQL.

Tasks:

- [x] CheckpointStore abstraction protocol (app/agent/persistence/store.py)
- [x] PostgresCheckpointStore using asyncpg (app/agent/persistence/postgres_store.py)
- [x] PostgreSQL relational schema with migrations/DDL (app/agent/persistence/schema.sql)
- [x] Durable HumanInterrupt lifecycle model & table-driven transitions (app/agent/interrupts/*)
- [x] Machine-checked ApprovalBinding with version and semantic binding
- [x] ResumeCoordinator with 11-step resume protocol (app/agent/runtime/resume.py)
- [x] Checkpoint schema versioning (format_version 2)
- [x] Live browser re-observation & WorldState reconciliation on resume
- [x] Stale DOM reference invalidation and target re-resolution
- [x] Deterministic stale approval rejection upon state drift
- [x] Deterministic expiration for interrupts and approvals
- [x] PostgreSQL atomic resume locking with fencing tokens and lease recovery
- [x] Secret-redacted audit events table (hitl_audit_events)
- [x] Restart/resume integration tests on live PostgreSQL (tests/integration/test_postgres_checkpoint_store.py)
- [x] Full crash-recovery acceptance test on real Chromium + PostgreSQL (tests/synthetic_forms/test_durable_hitl_crash_recovery.py)

Exit:

Kill and restart the process during an OTP/CAPTCHA pause and safely resume the same run.
Evidence: Proven by tests/synthetic_forms/test_durable_hitl_crash_recovery.py.
Synthetic workflow paused at OTP_REQUIRED -> checkpoint & interrupt persisted to PostgreSQL ->
Process 1 terminated -> Process 2 loads checkpoint -> browser re-observed -> WorldState reconciled ->
verified facts preserved -> stale ref rejected -> stale approval rejected -> human completes OTP in browser ->
fresh approval validated -> resume lock acquired -> interrupt transitioned to RESUMED ->
agent resumes from same subgoal with fresh DOM ref -> acknowledgment receipt reached ->
resume lock released -> full audit trail recorded in PostgreSQL.
Phase 8 tests: 10 unit interrupts + 11 unit resume + 4 integration postgres + 1 synthetic crash-recovery.
Full regression suite: 738 passed, 0 failed (631 unit + 63 integration + 44 synthetic).

---

# Phase 9 — Memory + compaction

Layers:

- working
- episodic
- semantic
- experience

Tasks:

- [x] memory schema (app/agent/memory/schema.sql, schema.py, models.py: semantic_memories, memory_provenance, episodes, experiences, compaction_records)
- [x] working-memory builder (app/agent/memory/models.py: WorkingMemory with bounded tool results, failures, and dialogue history)
- [x] event-backed episodic memory (app/agent/memory/models.py, store.py, postgres_store.py: EpisodicMemory with trajectory milestones and key events)
- [x] semantic profile/portal memory (app/agent/memory/models.py: SemanticMemoryItem with validity intervals, is_current, and supersession tracking)
- [x] experience extraction (app/agent/memory/models.py: ExperienceMemory with contextual trigger conditions, recovery strategies, and cautious confidence scaling)
- [x] threshold-based compaction (app/agent/memory/compactor.py: WorkingMemoryCompactor preserving goal, subgoal, verified WorldState facts, unresolved questions, interrupts, and approvals)
- [x] isolated summarization (app/agent/memory/summarizer.py: IsolatedSummarizer sandboxed with zero browser or tool privileges and fail-safe preservation)
- [x] provenance (MemoryProvenance with source, author_type, run_id, observation_id, tool_name, state_version, timestamp, and details)
- [x] memory poisoning tests (tests/unit/test_agent_memory.py: prompt-injection defense, sensitive data rejection, unverified inference rejection)

Exit:

Long workflows can compact context while preserving goal, verified facts, unresolved issues and next actions.
Evidence: Proven by tests/synthetic_forms/test_memory_compaction_loop.py::TestMemoryCompactionLoopAcceptance::test_multi_turn_memory_and_compaction_lifecycle (real Chromium + live PostgreSQL):
Turn 1: Citizen provides stable preference -> verified semantic memory stored in PostgreSQL with provenance.
Turn 2: Workflow executes in real Chromium -> applicant details verified -> meaningful episodic milestone recorded in PostgreSQL.
Turn 3: Layout re-renders -> stale reference error triggers recovery -> fresh target filled and verified -> recovery pattern persisted as experience memory in PostgreSQL.
Turn 4: New workflow starts -> deterministic retriever queries PostgreSQL -> bounded semantic, episodic, and experience memories injected into reasoner context.
Turn 5: Working memory exceeds threshold -> loss-aware compaction executes -> current goal, subgoal, verified WorldState facts, and unresolved questions are 100% preserved -> compaction record persisted in PostgreSQL.
Turn 6: Malicious webpage attempts memory injection -> MemoryWritePolicy rejects privilege escalation and unverified status masquerade -> false memory blocked from persistence.
Phase 9 tests: 24 unit memory + 2 integration postgres memory + 1 synthetic multi-turn acceptance loop. All 27 pass cleanly. Full regression suite: 765 passed, 0 failures.

---

# Phase 10 — Restricted specialist agents

Initial specialists:

- PortalResearchAgent — read-only
- FormSemanticsAgent — read-only
- DocumentAgent — vault-scoped
- RecoveryAgent — analysis/scoped
- VerificationAgent — read-only

- [x] isolated context (app/agent/specialists/models.py, context_builder.py: allowlisted projections, forbidden parameter defense against handles, secrets, raw bytes)
- [x] agent-as-tool interface (app/agent/specialists/adapter.py: SpecialistToolAdapter, accepts_browser_action=False, read_only=True, normalization clears mutation/verification)
- [x] timeout/cancellation (app/agent/specialists/base.py: asyncio timeout boundary, child task cancellation and await)
- [x] cleanup (app/agent/specialists/base.py: cleanup hooks, no orphan tasks)
- [x] transcript/audit (app/agent/specialists/base.py, models.py: SpecialistAuditLog, SpecialistAuditRecord with secret redaction and hashed payloads)
- [x] specialist permission tests (tests/unit/test_specialist_agents.py: 24 comprehensive invariant and security boundary tests)

Exit:

Specialists improve decisions without independently mutating the browser.
Evidence: Proven by tests/synthetic_forms/test_specialist_agent_loop.py (real Chromium):
Scenario 1: FormSemanticsAgent advises on simple.html fields -> primary AgentReasoner decides typed fill_field action -> executed through ToolRegistry -> PolicyEngine -> BrowserExecutor -> live Chromium DOM verified -> WorldState updated. Specialist never directly mutates DOM.
Scenario 2: RecoveryAgent analyzes failure evidence projection -> recommends RETRY_WITH_FRESH_TARGET -> specialist output strictly advisory.
Scenario 3: Prompt injection escalation attempt in specialist output fail-closed blocked before any policy bypass or execution.
Phase 10 tests: 24 unit specialist + 3 synthetic Chromium acceptance scenarios. Full regression suite: 792 passed, 0 failures.

---

# Phase 11 — Security hardening

Threats:

- prompt injection
- malicious documents
- malicious redirects
- stale approvals
- reference injection
- memory poisoning
- credential leakage
- runaway loops

Tasks:

- [x] trusted/untrusted context boundaries (TrustDomain, SensitivityLevel, RuntimeProvenance, envelope wrappers)
- [x] injection fixtures (tests/prompt_injection/pages/adversarial_injection.html)
- [x] malicious document fixtures (defense-in-depth XML escaping and untrusted metadata envelope wrap_document_data)
- [x] redirect tests (PolicyIntegrityGuard validate_navigation_destination + real Chromium redirect blocking acceptance test)
- [x] reference validation (fail-closed strict schema extra="forbid" on all tools and BrowserAction)
- [x] approval binding to action + target + state version (ApprovalIntegrityGuard with SHA-256 arguments_hash, origin_url, policy_decision, and approved_by validation)
- [x] per-tool permissions (ToolRegistry extra-parameter rejection and PolicyIntegrityGuard injection-attribute stripping)
- [x] rate/iteration/cost limits (RuntimeBudgetTracker with monotonic wall-clock, actions, tokens, specialist calls, error budgets and checkpoint persistence)
- [x] secret redaction tests (structural classification, vault token redaction, regex scrubbing defense-in-depth)
- [x] fail-closed tests (25 unit tests + 3 real Chromium acceptance scenarios)

Exit:

Malicious page content cannot upgrade its permissions or bypass policy.

Evidence: Proven by 28 targeted security tests:
- tests/prompt_injection/test_security_hardening.py (25 passed in 0.50s): Trust vs Sensitivity separation, immutable runtime provenance, structural secret protection, USER_VERIFIED / STATE_VERIFIED epistemic invariants, fail-closed schema gates (extra="forbid"), prompt envelope escaping, SHA-256 approval binding validation, and monotonic budget enforcement with checkpoint persistence.
- tests/prompt_injection/test_injection_acceptance.py (3 passed in 15.01s, real Chromium):
  1. Adversarial page with hidden prompt injection claiming "action pre-approved" and spoofed DOM attributes fails closed; PolicyEngine enforces REQUIRE_CONFIRMATION; spoofed approval rejected.
  2. Malicious page attempting external redirect to evil-attacker.com blocked fail-closed with UNAUTHORIZED_REDIRECT.
  3. Action parameter tampering, state version drift, or target change invalidates approved bindings via SHA-256 mismatch.
Full regression suite: 820 passed, 0 failures.

---

# Phase 12 — Evaluation platform

Three layers:

1. synthetic
2. frozen real-portal observations
3. live shadow/controlled execution

Track:

- field mapping accuracy
- tool success rate
- verification accuracy
- subgoal success
- recovery success
- workflow completion
- human intervention
- unsafe action rate
- prompt injection success
- iterations
- latency
- LLM cost

Tasks:

- [x] scenario runner (`ScenarioRunner` orchestrating real `AgentRuntime`, `AgentReasoner`, `ToolRegistry`, `PolicyEngine`, `BrowserExecutor`, `AgentWorldState`, and isolated test contexts)
- [x] replay engine (`ReplayEngine` with step-by-step causal divergence detection, `ReplayDiff`, and `ReplayDiffSeverity`)
- [x] metrics (`MetricsCalculator` measuring task completion, efficiency, recovery, safety invariants, and reliability without relying on model self-reports)
- [x] regression thresholds (`RegressionGate` enforcing statistical thresholds, absolute invariant gates, and structured regression reports)
- [x] failure injection (`FailureInjector` with deterministic fault types, trigger conditions, and auditable trace markers)
- [x] trace export (`TraceRecorder` producing causally-linked, schema-validated JSON and JSONL with `SensitivityLevel.RESTRICTED_SECRET` redaction)
- [x] golden scenario suite (14 cataloged scenarios across all canonical categories in `app/agent/evaluation/scenarios.py`)

Exit:

Every meaningful runtime change produces comparable evaluation data.

Evidence: Proven by 30 targeted evaluation tests:
- `tests/evaluation/test_evaluation_acceptance.py` (2 passed in real Chromium):
  1. Golden Scenario 1 runs against real Chromium and produces complete verified `EvaluationResult` with DOM field validation and metrics.
  2. Golden Scenario 9 (Prompt Injection Defense) contains malicious page in real Chromium, verifies `PolicyEngine` enforcement of `REQUIRE_CONFIRMATION` and `hitl_interrupt`.
- `tests/evaluation/test_evaluation_security.py` (3 passed): Evaluator cannot bypass `PolicyEngine`, cannot forge HITL approvals, blocks unauthorized redirects fail-closed.
- `tests/evaluation/test_failure_injection.py` (3 passed): Failure injection disabled by default, triggers deterministically on iteration and tool, state isolated.
- `tests/evaluation/test_metrics.py` (2 passed): Multi-dimensional metrics calculation from trace events; metrics never trust model self-reported claims.
- `tests/evaluation/test_regression_gates.py` (3 passed): Gate passes compliant metrics, fails degraded metrics with structured explanations, marks missing metrics inconclusive.
- `tests/evaluation/test_replay_engine.py` (4 passed): Matches identical traces, detects tool divergence, policy divergence, and trace truncation.
- `tests/evaluation/test_scenario_runner.py` (3 passed): Drives real runtime stack, maintains run isolation, handles injected budget faults.
- `tests/evaluation/test_scenarios.py` (3 passed): Validates all 14 golden scenarios, rejects malformed configs, JSON roundtrip.
- `tests/evaluation/test_trace_recorder.py` (4 passed): Causal parent/child tracking, schema validation, full event types, JSON/JSONL export.
- `tests/evaluation/test_trace_redaction.py` (3 passed): Structural and content secret scrubbing; exports contain zero raw secrets.
Full regression suite: 850 passed, 0 failures.

---

# Phase 13 — Enterprise runtime

Target:

~~~text
API Gateway
 ↓
Workflow Service
 ↓
Postgres
 ↓
Queue
 ↓
Isolated Agent Worker
 ↓
Browser Worker
 ↓
Government Site
~~~

Requirements:

- durable runs
- event log
- distributed locks
- browser isolation
- cancellation
- resource limits
- observability
- audit
- secret management
- retention/deletion
- health checks

Do not implement before Phases 2–12 prove the local runtime.

### Phase 13 implementation (COMPLETE, 2026-09-20)

Implemented as a single deployable process with five logical components behind
explicit boundaries (`app/enterprise/*`, additive — no Phase 1–12 subsystem modified):

- [x] Service/domain models (models.py: Workflow, WorkflowRun referencing — never
      duplicating — AgentRunState; 12-state RunStatus lifecycle with explicit
      fail-closed RUN_TRANSITIONS table; WorkerLease with monotonic fencing tokens;
      ExecutionQueueItem with references-only payloads; IdempotencyRecord; AuditEvent)
- [x] Workflow persistence/state machine (store protocol + in-memory twin +
      PostgreSQL implementation on the SAME database as the Phase 8 checkpoint store;
      workflow_service.py owns all lifecycle transitions, validated against the table)
- [x] Worker lease/fencing (atomic claim = queue claim + lease acquisition in ONE
      transaction; per-run monotonic fencing tokens; ALL worker-side durable writes
      go through save_run_with_fencing validated by the store — stale workers fail closed)
- [x] Durable queue/dispatch (PostgreSQL SKIP LOCKED queue with visibility timeout,
      bounded attempts, dead-letter state, idempotent enqueue — no Kafka/RabbitMQ/Redis;
      decision recorded in docs/DECISIONS.md D025)
- [x] Execution Worker wrapper around existing AgentRuntime (worker.py + engine.py:
      claim → lease+fencing → verify → load checkpoint → run/resume the REAL stack
      AgentRuntime → ToolRegistry → PolicyEngine → BrowserExecutor → verification →
      WorldState → Phase 8 checkpoint → release; NO alternative execution path)
- [x] Crash/recovery semantics (lease reaper flips to RECOVERY_REQUIRED and requeues;
      service.recover_run requeues only with no active lease + remaining dispatch
      budget; Worker B resumes from the latest Phase 8 checkpoint with budget/world
      state preserved; the last browser mutation is never blindly replayed)
- [x] API Gateway (POST/GET /workflows, POST /workflows/{id}/runs, GET /runs/{id},
      cancel/resume/events; worker claim/heartbeat/complete/fail/pause; strict
      extra=forbid request schemas; strict response schemas — no handles/secrets/
      checkpoints/policy internals; gateway never executes Playwright, never touches
      browser state, never resolves raw vault secrets)
- [x] Authentication/authorization (IdentityProvider resolves bearer tokens to
      server-side identities; worker ids server-assigned; roles USER/WORKER/ADMIN
      only, each with concrete runtime meaning; every service method fails closed on
      tenant mismatch or wrong role; client bodies cannot carry tenant/user/role fields)
- [x] Vault abstraction + integration boundary (vault_service.py: reference shape
      validation USER.*/DOCUMENT.*; per-tenant/user scoping; execution authority =
      ACTIVE lease + CURRENT fencing token + executable run state; ResolvedSecret
      delivered only in-process; audit metadata without values)
- [x] Audit persistence (append-only audit_events — INSERT is the only write path;
      payloads redacted via the existing Phase 11/12 redact_trace_value BEFORE
      persistence; parent_event_id causality validated in-tenant, dangling/foreign
      rejected fail-closed)
- [x] Idempotency/cancellation/retry (durable Idempotency-Key handling for workflow
      creation, run creation, cancel, resume; key reuse with a different body → 422;
      queued runs cancel immediately, running runs stop at safe boundaries; terminal
      runs never resume; service/worker/agent recovery budgets remain distinct layers)
- [x] Tenant isolation enforcement (tenant-scoped lookups at the store level —
      cross-tenant access returns not-found without distinction; queue claim is
      tenant-restricted when the worker is; audit reads are tenant-scoped)
- [x] Enterprise security hardening (forged worker identity rejected; queue payload
      cannot override tenant/worker authority; model/untrusted input cannot touch
      leases or workflow ownership; stale fencing tokens rejected at the store)
- [x] Integration tests (148 enterprise tests across 16 files:
      test_api_gateway, test_workflow_service, test_worker_leases, test_execution_worker,
      test_queue, test_vault_service, test_audit_persistence, test_tenant_isolation,
      test_idempotency, test_crash_recovery, test_hitl_resume, test_enterprise_security,
      test_cancellation, test_postgres_enterprise_store, test_enterprise_acceptance,
      test_acceptance_isolation_vault)
- [x] Real Chromium enterprise acceptance (test_enterprise_acceptance.py:
      API → workflow → durable run → queue → worker → AgentRuntime → real Chromium →
      ToolRegistry → PolicyEngine → BrowserExecutor → verification → WorldState →
      checkpoint/audit → completion; Worker A crash → lease expiry → Worker B claim →
      higher fencing token → checkpoint resume → safe completion; stale Worker A
      resurrected write rejected fail-closed)
- [x] Phase 12 evaluation compatibility (test_enterprise_acceptance.py::
      TestPhase12Compatibility — ScenarioRunner still drives the real AgentRuntime;
      the enterprise engine mirrors the same loop conventions; no bypass path)
- [x] Control-plane reconciliation (docs/DECISIONS.md D025; docs/BUILD_STATUS.md
      Phase 13 evidence; this plan section)
- [x] Full regression (998 passed, 0 failures: 679 unit + 65 integration +
      48 synthetic + 28 prompt_injection + 30 evaluation + 148 enterprise)

Deviations from the original Phase 13 sketch (documented, intentional):
- Queue is PostgreSQL-backed (SKIP LOCKED) rather than a separate message broker —
  smallest production-appropriate dispatch abstraction (AGENTS.md rule 18/19).
- Default deployment is one process with the in-memory store; PostgresEnterpriseStore
  is the production swap-in via set_enterprise_state — enterprise boundaries are
  logical, not microservice-proliferation.
- Retention/deletion and health-check endpoints were NOT built in Phase 13 (they are
  Phase 15 enterprise-definition-of-done items per the plan); /health already exists
  from the pre-Phase-13 app.

---

# Phase 14 — Live portal validation (COMPLETE; expanded 2026-09-21)

Progression implemented as a shadow-first live layer (`app/agent/live/*`, additive —
no Phase 1–13 subsystem modified except additive registry entries):

~~~text
OBSERVE ONLY (LIVE_SHADOW)
 ↓
semantic extraction
 ↓
field mapping (deterministic FieldMapper, no LLM)
 ↓
planned action trace (PolicyEngine risk probes)
 ↓
human review request (recorded, signed-bound)
 ↓
safe execution (LIVE_CONTROLLED_EXECUTION — separate, signed-review-gated)
 ↓
human checkpoints (unchanged Phase 8/11 HITL)
 ↓
final confirmation (unchanged boundary; never autonomous)
~~~

Portal classes tested (complete coverage, 2026-09-21): welfare (PM-KISAN),
certificate/scheme discovery (MyScheme), recruitment (NCS), grievance/gateway
(services.india.gov.in — ANTI_BOT_BLOCK recorded), training
(apprenticeshipindia.gov.in), education (udiseplus.gov.in), transport
(parivahan.gov.in), identity_document (digilocker.gov.in), appointments
(passportindia.gov.in).

Tasks:

- [x] Live shadow mode — `run_live_shadow`: observe → origin validation →
      semantic extraction → deterministic field mapping → planned action trace →
      human review request; ZERO mutations; reasoner never invoked (model output
      cannot flip shadow into live mutation mode)
- [x] Portal profiles (trusted metadata only) for pmkisan / myscheme / ncs /
      indiaportal with official origin, trusted domains, safe test path,
      last_verified_at; offline file:// test profiles are validator-marked
- [x] Origin validation before every run + post-action (OriginMismatchError →
      SAFETY_BLOCKED); live redirects validated against trusted_domains
- [x] Planned action trace: tool, target semantic ID, current observation ID,
      argument/reference summary, PolicyEngine risk classification, expected
      state transition, verification criterion, HITL flag per action
- [x] Human review boundary: HumanReviewRequest + HumanReviewDecision with
      SHA-256 digest + HMAC signature; transplanted/forged approvals rejected
- [x] Controlled execution — `run_controlled_execution`: separate mode,
      signed-review-gated, action allowlist (fill/select/check/uncheck only),
      per-step semantic re-binding (fresh ref + observation_id or STOP),
      executed through the EXISTING ToolRegistry → PolicyEngine →
      BrowserExecutor → verification loop; UNCERTAIN verification = failure
- [x] Environment-vs-agent separation: generic anti-bot/CDN block detection
      (title markers) → ANTI_BOT_BLOCK / PORTAL_UNAVAILABLE, never AGENT_FAILURE;
      playwright timeout/network classification
- [x] Phase 12 compatibility: TraceRecorder traces (JSON/JSONL) + evidence
      reports with explicit LIVE metadata; never replayed as synthetic fixtures
- [x] Live validation executed: pmkisan SHADOW_SUCCESS (104 elements, 29K aria
      chars), myscheme SHADOW_SUCCESS (72 elements, 1 frame), ncs SHADOW_SUCCESS
      (124 elements, 3 planned search actions, 1 LOW-confidence mapping surfaced
      as ambiguous), indiaportal PORTAL_UNAVAILABLE/ANTI_BOT_BLOCK (honest)
- [x] Live-validation expansion (2026-09-21): full portal-class coverage —
      apprenticeship (training) SHADOW_SUCCESS (251 elements, 6 submit controls
      detected + gated, mapping honestly UNSUPPORTED), udiseplus (education)
      SHADOW_SUCCESS (29 elements, 1 planned action), parivahan (transport)
      SHADOW_SUCCESS (118 elements, 1 planned action), digilocker
      (identity_document) SHADOW_SUCCESS (82 elements, auth-boundary profile,
      no authentication attempted), passport (appointments) SHADOW_SUCCESS
      (163 elements, booking/payment boundaries documented); site registry
      gained the missing apprenticeshipindia.gov.in domain
- [x] Non-collapsing failure classification end-to-end (WS2): controlled
      execution maps ToolResult codes explicitly — POLICY_DENIED →
      POLICY_BLOCKED; USER_ACTION_REQUIRED/CONFIRMATION_REQUIRED →
      HITL_REQUIRED (human boundary); VERIFICATION_FAILED → AGENT_FAILURE;
      STALE_TARGET_STOPPED → ENVIRONMENT_FAILURE with per-step evidence.
      Mapping UNSUPPORTED never becomes MAPPING_SUCCESS (evidence-only
      landing pages record mapped=0 honestly)
- [x] Bounded approvals (WS3): HumanReviewDecision.expires_at; expired or
      unparseable expiry rejected fail-closed by the controlled gate
- [x] Controlled-execution matrix proven offline (WS3, real Chromium):
      select/check execution with verification, semantic re-binding over
      stale planning refs, sensitive value_ref → CONFIRMATION_REQUIRED →
      HITL_REQUIRED, approval expiry, world-state drift →
      STALE_TARGET_STOPPED, Playwright timeout → ENVIRONMENT_FAILURE, and
      the prohibited-actions denial matrix (click/upload/password/otp/
      captcha/mfa/pin/payment/final-legal) — all deterministic, model-
      independent (test_live_controlled_matrix.py, 20 tests)
- [x] Real-LLM compatibility gap closed (WS4): OpenRouter completion budget
      configurable via OPENROUTER_MAX_TOKENS (reasoning models truncate at
      the hardcoded 4096 → DECISION_PARSE_FAILED); system prompt shows the
      EXACT decision JSON shape after live probing showed small free models
      emit non-conforming shapes they never repair; adapter/gateway wire
      contract regression-tested with the real gateway + mocked HTTP
      (test_openrouter_live_contract.py); gated real-model test
      (tests/real_sites/test_openrouter_live.py) proves REAL OpenRouter →
      AgentReasoner → strict AgentDecision → ToolRegistry → PolicyEngine →
      BrowserExecutor → verification on a local file:// fixture — the model
      never touches Playwright directly; operator-gated (RUN_OPENROUTER_LIVE_TEST=true)
- [x] Evidence persisted: tests/live_portal/evidence/<portal>/report.json +
      trace.jsonl (redacted, LIVE-metadata-tagged) for all 9 portals
- [x] NO live controlled execution performed — selected portals are
      observation-class; real mutation candidates sit behind auth boundaries
      (HITL + real user data). Controlled machinery proven on offline fixtures.
      Decision: D027.

Phase 14 tests: 45 unit (test_live_validation.py) + 41 offline pipeline
(test_live_shadow_offline.py: 9, test_live_controlled_offline.py: 6,
test_live_controlled_matrix.py: 20... see BUILD_STATUS for exact split) +
36 evaluation acceptance/compat + 10 gated live (tests/real_sites/test_live_shadow.py)
+ 2 gated real-LLM (tests/real_sites/test_openrouter_live.py).
Full regression: 1092 passed, 0 failures (733 unit + 65 integration +
80 synthetic + 28 prompt_injection + 36 evaluation + 148 enterprise).
Real-LLM chain: VALIDATED LIVE end-to-end on the success path (real model →
schema-valid decision → full production path → deterministic verification)
and on the fail-closed MODEL_FAILURE path; the final full-suite re-run hit
the free-tier daily quota (429) on the success-path test — an honest,
environment-class failure recorded as such (see BUILD_STATUS).

---

# Phase 15 — Enterprise definition of done

Agent:

- [ ] persistent session
- [ ] goal/subgoal planning
- [ ] tool calling
- [ ] WorldState
- [ ] verification
- [ ] reflection
- [ ] memory
- [ ] durable checkpoints
- [ ] scoped specialists

Browser:

- [ ] semantic perception
- [ ] frame handling
- [ ] tab handling
- [ ] dynamic forms
- [ ] robust locator
- [ ] verification
- [ ] bounded vision fallback

Safety:

- [ ] policy outside LLM
- [ ] injection defense
- [ ] domain trust
- [ ] sensitive-data isolation
- [ ] auth checkpoints
- [ ] payment gate
- [ ] legal declaration gate
- [ ] final confirmation
- [ ] fail closed

Reliability:

- [ ] durable state
- [ ] deterministic event log
- [ ] replay
- [ ] bounded retries
- [ ] cancellation
- [ ] crash recovery
- [ ] regression benchmark

Operations:

- [ ] durable database
- [ ] worker isolation
- [ ] tracing
- [ ] metrics
- [ ] audit
- [ ] secret management
- [ ] retention
