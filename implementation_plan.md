# IMPLEMENTATION PLAN — Agent Runtime Transformation

## Status

Phase 0 — Control-plane preparation  
Overall: NOT COMPLETE  
Evidence policy: every checkbox requires current evidence.

---

# Phase 0 — Control plane

Deliver:

- [ ] AGENTS.md
- [ ] context.md
- [ ] implementation_plan.md
- [ ] docs/ARCHITECTURE_TARGET.md
- [ ] docs/AGENT_PROTOCOL.md
- [ ] docs/BUILD_STATUS.md
- [ ] docs/DECISIONS.md
- [ ] docs/SECURITY_MODEL.md
- [ ] docs/EVAL_PLAN.md

Exit criteria:

- [ ] legacy docs point to canonical files
- [ ] no stale test-count claims are presented as current evidence
- [ ] source-of-truth precedence is explicit

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

- [ ] run current test suite
- [ ] record exact current baseline
- [ ] synthetic coverage: text/select/radio/checkbox/file/iframe/dynamic/validation
- [ ] stale-reference tests
- [ ] multi-tab tests
- [ ] no swallowed browser errors

Exit:

~~~text
observe → act → verify → re-observe
works without an LLM.
~~~

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

- [ ] Pydantic models
- [ ] serializable state
- [ ] event append/replay
- [ ] deterministic state transitions
- [ ] AgentRunner compatibility facade
- [ ] lifecycle tests

Exit:

A paused run can be serialized and restored without losing logical task state.

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

- [ ] Tool protocol/base
- [ ] registry
- [ ] adapt existing executor operations
- [ ] strict schemas
- [ ] permission metadata
- [ ] tool-result normalization
- [ ] tool permission tests

Exit:

A synthetic agent can complete a multi-step form through typed tool calls.

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
