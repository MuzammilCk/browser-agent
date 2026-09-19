# IMPLEMENTATION PLAN — Agent Runtime Transformation

## Status

Phase 0 — Control-plane preparation  
Phase 1 — Browser foundation (COMPLETE)  
Overall: IN PROGRESS  
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

- [ ] AgentReasoner
- [ ] structured OpenRouter tool calling
- [ ] minimal context assembler
- [ ] strict decision validation
- [ ] bounded model retries
- [ ] visible model failures
- [ ] explicit fallback state, never silent fallback
- [ ] mock-model tests
- [ ] replay tests

Exit:

The model chooses among multiple tools over multiple iterations while deterministic runtime rules remain authoritative.

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

- [ ] goal parser
- [ ] initial plan creation
- [ ] subgoal lifecycle
- [ ] dependencies
- [ ] plan invalidation
- [ ] plan revision
- [ ] final-submission boundary in plan
- [ ] dynamic-form tests

Exit:

A local page change can invalidate one subgoal without destroying the overall goal.

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

- [ ] AgentWorldState
- [ ] observation reducer
- [ ] semantic IDs
- [ ] stale-ref invalidation
- [ ] dynamic form continuity
- [ ] multi-tab continuity

Exit:

DOM rerenders do not erase verified semantic progress.

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

- [ ] ReflectionResult
- [ ] bounded reflection
- [ ] stale-target recovery
- [ ] validation recovery
- [ ] navigation recovery
- [ ] model-failure recovery
- [ ] repeated-action integration
- [ ] recovery tests

Exit:

The agent changes strategy after meaningful failures and stops when no safe strategy remains.

---

# Phase 8 — Durable human interrupts

Goal: OTP/CAPTCHA/auth/clarification/confirmation become persistent resumable states.

Tasks:

- [ ] SQLite checkpoint store
- [ ] durable approval state
- [ ] resume endpoint
- [ ] checkpoint versioning
- [ ] re-observation on resume
- [ ] target revalidation
- [ ] stale approval rejection
- [ ] expiration
- [ ] session locks
- [ ] restart/resume tests

Exit:

Kill and restart the process during an OTP/CAPTCHA pause and safely resume the same run.

---

# Phase 9 — Memory + compaction

Layers:

- working
- episodic
- semantic
- experience

Tasks:

- [ ] memory schema
- [ ] working-memory builder
- [ ] event-backed episodic memory
- [ ] semantic profile/portal memory
- [ ] experience extraction
- [ ] threshold-based compaction
- [ ] isolated summarization
- [ ] provenance
- [ ] memory poisoning tests

Exit:

Long workflows can compact context while preserving goal, verified facts, unresolved issues and next actions.

---

# Phase 10 — Restricted specialist agents

Initial specialists:

- PortalResearchAgent — read-only
- FormSemanticsAgent — read-only
- DocumentAgent — vault-scoped
- RecoveryAgent — analysis/scoped
- VerificationAgent — read-only

Tasks:

- [ ] isolated context
- [ ] agent-as-tool interface
- [ ] timeout/cancellation
- [ ] cleanup
- [ ] transcript/audit
- [ ] specialist permission tests

Exit:

Specialists improve decisions without independently mutating the browser.

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

- [ ] trusted/untrusted context boundaries
- [ ] injection fixtures
- [ ] malicious document fixtures
- [ ] redirect tests
- [ ] reference validation
- [ ] approval binding to action + target + state version
- [ ] per-tool permissions
- [ ] rate/iteration/cost limits
- [ ] secret redaction tests
- [ ] fail-closed tests

Exit:

Malicious page content cannot upgrade its permissions or bypass policy.

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

- [ ] scenario runner
- [ ] replay engine
- [ ] metrics
- [ ] regression thresholds
- [ ] failure injection
- [ ] trace export

Exit:

Every meaningful runtime change produces comparable evaluation data.

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

---

# Phase 14 — Live portal validation

Progression:

~~~text
OBSERVE ONLY
 ↓
semantic extraction
 ↓
field mapping
 ↓
planned action trace
 ↓
human review
 ↓
safe execution
 ↓
human checkpoints
 ↓
final confirmation
~~~

Suggested portal classes:

- training
- welfare
- identity/document
- transport
- education
- recruitment
- grievance
- certificate
- appointments

No autonomous payment or final submission.

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
