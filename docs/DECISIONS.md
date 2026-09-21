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

## D021 — Multi-layer memory architecture, deterministic write policy, loss-aware compaction, and PostgreSQL persistence

Phase 9 (2026-09-19):

1. Four Separate Memory Layers:
   - Working Memory: Short-lived, strictly bounded context for current loop iterations
     (goal, subgoal, verified WorldState facts, recent tool results, recovery attempts,
     unresolved questions, active interrupts, and approvals).
   - Episodic Memory: Milestone records of what happened during workflows with
     structured key events, summaries, outcomes, and provenance (never raw conversation dumps).
   - Semantic Memory: Durable facts with explicit validity intervals (`valid_from`, `valid_until`),
     `is_current` flags, and `superseded_by` pointers for full historical lineage.
   - Experience Memory: Contextual execution lessons from successful recoveries and patterns
     with success/failure counters and cautious confidence scaling (no premature generalization).
2. Deterministic Memory Write Policy & Poisoning Defense:
   - The LLM cannot freely write arbitrary permanent memories. An explicit pipeline gates
     persistence: `Candidate` -> `MemoryWritePolicy` -> `Store`.
   - Strictly rejects passwords, OTPs, PINs, auth secrets, raw document bytes, and raw identity numbers.
   - Enforces semantic references (`USER.full_name`, `DOCUMENT.income_certificate`).
   - Webpage content and untrusted sources cannot write permanent system rules, cannot grant
     privileges (e.g. "User authorized payments"), and cannot claim `VERIFIED` epistemic status.
   - Model inferences cannot propose `VERIFIED` status without deterministic runtime verification.
3. Epistemic Hierarchy & Conflict Resolution:
   - `VERIFIED > OBSERVED > INFERRED > STALE`.
   - Conflicting memories never silently overwrite each other. When a newer verified fact
     supersedes an older fact, the older record is marked `is_current = False`, `valid_until = now`,
     `superseded_by = new_id`. Both provenance logs are preserved intact.
   - Current WorldState always supersedes memory: `Observation > WorldState > Memory > Inference`.
4. Loss-Aware Compaction:
   - When working memory exceeds thresholds, compacts historical tool results and conversation
     turns while strictly preserving: current goal, active subgoal, verified WorldState facts,
     unresolved questions, active human interrupts, and pending approvals.
   - Compacted context is consolidated into an episodic milestone and an audit `CompactionRecord`.
   - Compaction never mutates WorldState or alters browser state.
5. Deterministic Property-Based Retrieval:
   - Filtered by portal, goal, active subjects, user session, and recency without vector databases
     or embeddings. Bounded result sets (max 5 semantic facts, max 3 episodes, max 3 experiences)
     prevent context explosion in `AgentReasoner`.
6. Sandboxed Isolated Summarization:
   - Runs in a strict sandbox without browser, tool registry, or state mutation powers.
   - Output is strictly validated; summarization failure preserves original context without fabricating summaries.
7. PostgreSQL Persistence:
   - Backed by `asyncpg` with relational tables (`semantic_memories`, `memory_provenance`, `episodes`,
     `experiences`, `compaction_records`), indexes, connection pooling, and transactional consistency.
   - An `InMemoryMemoryStore` is provided for isolated, fast unit testing.

Status: ACCEPTED — implemented in `app/agent/memory/*`, covered by 27 targeted tests (24 unit memory,
2 integration postgres memory, 1 synthetic Chromium+Postgres multi-turn acceptance loop).

## D022 — Restricted specialist agents as non-mutating advisors

Phase 10 (2026-09-19):

1. Advisors, Never Authorities (Rule 1):
   - Specialists provide structured recommendations, evidence, and classifications only.
   - Specialists never directly mutate `AgentWorldState`, mark items `VERIFIED`, complete goals,
     authorize tools, bypass `PolicyEngine`, create/modify HITL approvals, write directly to
     `MemoryStore`, or unlock final legal/financial submission.
   - Specialist verification is advisory; authoritative verification remains deterministic,
     post-observation, and browser/environment grounded.

2. Semantically Distinct Results (Rule 2):
   - Specialist outputs are returned under `result_kind: "specialist_analysis"`.
   - Never masquerade as browser mutation results (`ToolResult.post_observation` is explicitly `None`).
   - Specialist analysis enters reasoning context and memory-candidate pipelines only.

3. Allowlisted Projections & Complete Isolation (Rules 3 & 4):
   - Boundary enforcement uses pure serialization: `PageObservationProjection`,
     `WorldStateProjection`, `FailureEvidenceProjection`, `DocumentMetadataProjection`,
     `MemorySummaryProjection`.
   - Never pass live `Page`, `BrowserContext`, `BrowserExecutor`, `AgentRuntime`, `ToolRegistry`,
     passwords, OTPs, PINs, or raw document bytes across the specialist boundary.
   - No nested specialist calls or subagent swarms: exactly one primary browser-controlling runtime.

4. Authoritative Registry & Immutable Permission Classes (Rule 5):
   - Permissions are fixed by the registered specialist implementation and cannot be altered
     dynamically by the model or prompt.
   - Four immutable classes:
     * `READ_ONLY`: Sees page observation projection only (`PortalResearchAgent`, `FormSemanticsAgent`).
     * `VAULT_SCOPED`: Sees document reference metadata only; never raw contents (`DocumentAgent`).
     * `ANALYSIS_ONLY`: Sees failure evidence and safe world state summaries (`RecoveryAgent`).
     * `VERIFICATION_ONLY`: Compares target vs observed evidence; outputs recommendation (`VerificationAgent`).

5. Epistemic Status & Provenance (Rule 6):
   - Specialist recommendations are strictly `INFERRED` unless backed by explicit observed evidence.
   - Outputs can never unilaterally promote `INFERRED -> VERIFIED`.
   - Provenance retains `specialist_type`, `invocation_id`, `parent_run_id`, `evidence`, `confidence`,
     and `epistemic_status`.

6. Memory & WorldState Boundaries (Rules 7 & 8):
   - Route through `SpecialistResult -> MemoryCandidate -> MemoryWritePolicy -> MemoryStore`.
   - Specialist results cannot directly write to `MemoryStore` or mutate `AgentWorldState`.
   - Primary `AgentRuntime` independently decides browser mutations based on deterministic verification.

7. Bounded Execution, Timeout, Cancellation, and Audit (Rules 11, 12, & 13):
   - Specialist runs are bounded by strict timeouts; child tasks are cleanly cancelled and awaited.
   - Crashes produce fresh safe invocations without resuming stale sub-processes.
   - Thread-safe `SpecialistAuditLog` records every invocation with hashed/redacted payloads.
   - `SpecialistToolAdapter` normalizes outputs to clear `post_observation`, `verification_status`, and `policy_allowed`.

Status: ACCEPTED — implemented in `app/agent/specialists/*`, covered by 27 targeted tests (24 unit specialist tests, 3 synthetic Chromium acceptance scenarios), 792 total tests passing with 0 failures.

## D023 — Provenance-aware trust boundaries, orthogonal sensitivity, fail-closed schema gates, hardened approval bindings, and execution budgets

Phase 11 (2026-09-19):

1. Separation of Trust vs Sensitivity:
   `TrustDomain` (`SYSTEM_UNCONDITIONAL`, `RUNTIME_DETERMINISTIC`, `USER_VERIFIED`,
   `VAULT_RESOLVED`, `STATE_VERIFIED`, `SPECIALIST_INFERRED`, `PAGE_UNTRUSTED`,
   `MODEL_INFERRED`) governs data provenance and epistemic authority.
   `SensitivityLevel` (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`, `SECRET`)
   governs confidentiality and exposure control orthogonally.
   Secret handling is structural and field-based first (e.g., `input[type=password]`,
   vault bindings); content-based regex scrubbing operates as defense-in-depth only.
   Local vault credentials do not count as user approval.

2. Runtime-Owned Immutable Provenance:
   Provenance lineage (`RuntimeProvenance`) is minted and owned exclusively by the runtime.
   Untrusted content (pages, model inferences, extracted text) cannot construct, modify,
   or escalate `TrustDomain`, `verified=True`, `verifier`, or authorization states.
   No fake cryptographic signatures are used; runtime memory immutability and deterministic
   runtime minting serve as the authority boundary.

3. Strict Epistemic Authority (`USER_VERIFIED` and `STATE_VERIFIED`):
   - `USER_VERIFIED` strictly denotes explicit, interactive human HITL authorization.
     Local vault credentials or automated heuristics never mint `USER_VERIFIED`.
   - `STATE_VERIFIED` is minted solely by deterministic post-observation verification
     rules against observed DOM/environment state. Page claims, DOM attributes
     (`data-approved`, `data-risk`, `aria-*`), model claims, and specialist advice cannot
     create `STATE_VERIFIED` facts or lower risk.

4. Fail-Closed Strict Schemas:
   Tool arguments, action models, and reasoner schemas enforce recursive `extra="forbid"`.
   Any smuggled or unrecognized attributes (e.g., `is_trusted`, `bypass_policy`,
   `skip_verification`) trigger immediate schema rejection (`TOOL_SCHEMA_INVALID`)
   prior to policy evaluation or tool execution.

5. Hardened Approval Bindings & Cryptographic Argument Fingerprinting:
   `ApprovalBinding` is bound to exact invocation parameters via SHA-256 hash (`arguments_hash`),
   `run_id`, `session_id`, `requested_action`, `tool_name`, `target_identity`, `semantic_id`,
   `world_state_version`, and `origin_url`.
   Any argument mutation, state drift, observation staleness, or origin deviation invalidates
   the approval (`APPROVAL_BINDING_MISMATCH` / `APPROVAL_ORIGIN_MISMATCH`).
   Spoofed `approved_by` values outside authenticated HITL context are rejected fail-closed
   (`UNTRUSTED_APPROVAL_SPOOF`).

6. Enveloped Untrusted Content & Origin Navigation Gating:
   Untrusted webpage text, extracted metadata, OCR, and specialist advice are wrapped in
   escaped boundary envelopes (`wrap_web_content`, `wrap_specialist_advice`, `wrap_document_data`)
   with explicit instructions that enclosed content is untrusted data.
   Navigation outside registered allowlisted origin domains is blocked fail-closed
   (`PolicyDecision.DENY` / `UNAUTHORIZED_REDIRECT`).

7. Persistent Monotonic Execution Budgets:
   `RuntimeBudgetTracker` enforces monotonic wall-clock time (`time.monotonic()`), action count,
   token count, specialist invocations, and error thresholds.
   Budgets are reserved and checked prior to expensive operations. Counters persist losslessly
   across checkpoints and resumes, preventing reset on restart.

Status: ACCEPTED — implemented in `app/agent/security/*`, `app/policy/engine.py`,
`app/agent/interrupts/models.py`, `app/agent/memory/policy.py`, `app/agent/reasoning/context.py`,
`app/agent/runtime/state.py`, `app/agent/tools/registry.py`, covered by 28 targeted tests
(25 unit security tests, 3 synthetic Chromium prompt-injection acceptance scenarios),
820 total tests passing with 0 failures.

## D024 — Multi-dimensional evaluation platform with causal tracing, deterministic replay, failure injection, regression gates, and strict zero-authority evaluation invariants

Phase 12 (2026-09-19):

1. Real Runtime Under Test:
   Evaluation executes the full production runtime stack (`AgentRuntime`, `AgentReasoner`, `ToolRegistry`,
   `PolicyEngine`, `BrowserExecutor`, `AgentWorldState`). The evaluator owns zero execution authority:
   it cannot bypass policy, synthesize verification, or forge HITL approvals.

2. Causal Tracing and Pre-Export Redaction:
   `TraceRecorder` produces append-only, causally ordered event sequences with strict `parent_event_id`
   and `correlation_id` lineage. Secret scrubbing (`SensitivityLevel.RESTRICTED_SECRET`) occurs prior
   to memory storage or export, ensuring zero plaintext secrets in traces.

3. Objective Evidence Over Model Self-Reporting:
   `MetricsCalculator` and `ScenarioRunner` derive task success strictly from deterministic DOM
   assertions (`DOM_FIELD_VALUE`, `DOM_ELEMENT_VISIBLE`, etc.) and verified `AgentWorldState` facts.
   Model claims of task completion are untrusted and never treated as ground truth.
   Outcome dimensions are explicitly segregated: `task_success` and `safety_pass` cannot mask each other.

4. Deterministic Replay and Divergence Localization:
   `ReplayEngine` performs structured comparison between baseline and replay traces across model decisions,
   tool arguments, policy verdicts, and verification statuses, categorizing divergence with `ReplayDiffSeverity`
   to pinpoint the exact causal divergence point.

5. Isolated, Auditable Failure Injection:
   `FailureInjector` introduces controlled faults (stale references, budget limits, model errors, redirects)
   via explicit scenario configuration. Injected faults emit explicit `FAULT_INJECTED` trace events and
   cannot be triggered or modified by model output.

6. Strict Regression Gates:
   `RegressionGate` enforces statistical thresholds and absolute safety invariants (`safety_pass == True`,
   `zero_unauthorized_mutations == True`), producing structured regression reports that fail CI closed.

7. Golden Scenario Suite:
   14 canonical evaluation scenarios covering all core categories (basic forms, dynamic DOM, multi-step,
   HITL confirmation gating, approval replay, prompt injection containment, budget exhaustion, stale references).

Status: ACCEPTED — implemented in `app/agent/evaluation/*`, covered by 30 targeted evaluation tests
(including real Chromium acceptance tests), 850 total tests passing with 0 failures.

## D025 — Enterprise runtime: smallest service boundary set, PostgreSQL-backed queue, lease/fencing ownership, and strict secret isolation

Phase 13 (2026-09-19):

1. Minimal Service Boundaries (no microservices for their own sake):
   The enterprise runtime is a single deployable process by default with five logical
   components behind explicit boundaries: API Gateway, Workflow Service, durable store
   (PostgreSQL or in-memory twin), Execution Workers, and the Vault Integration boundary.
   The API Gateway never executes Playwright, mutates browser state, bypasses PolicyEngine/HITL,
   resolves raw vault secrets, or touches AgentWorldState. The Workflow Service owns lifecycle
   state only — no browser access. Exactly one Execution Worker owns a run's browser at any moment.

2. PostgreSQL as the Only Durable Substrate (D007 extended):
   The queue, leases, workflow/run lifecycle, idempotency, and audit all live in the SAME
   PostgreSQL database the Phase 8 checkpoint store already uses
   (`workflows`, `workflow_runs`, `worker_leases`, `execution_queue`, `audit_events`,
   `idempotency_keys`). No Kafka/RabbitMQ/Redis — a `SKIP LOCKED` transactional queue with
   visibility timeouts and dead-lettering satisfies every dispatch requirement without a
   second stateful system.

3. Lease + Fencing Ownership (single-owner invariant):
   A run is claimed atomically (queue claim + lease acquisition in ONE transaction, `SKIP LOCKED`).
   Every lease carries a per-run monotonic fencing token. All worker-side durable writes go
   through `save_run_with_fencing`, which is validated by the STORE — a stale worker with an
   outdated token has its writes rejected fail-closed; worker honesty is never assumed.
   Lease renewal failure stops browser execution immediately (LeaseGuard fails closed between
   iterations) and the worker reports `RECOVERY_REQUIRED`.

4. Worker Wraps, Never Replaces, the Runtime (invariant 4):
   `WorkerRunEngine` mirrors the Phase 12 ScenarioRunner loop (observe → reason → policy →
   execute → verify → world update) around the existing AgentRuntime → ToolRegistry →
   PolicyEngine → BrowserExecutor stack. There is no worker-specific execution path.
   Resume uses the EXISTING Phase 8 checkpoint store — never a second checkpoint mechanism.

5. Queue Payloads Carry References Only (invariant 5):
   Queue payloads contain `run_id`, `workflow_id`, `agent_run_id` — never secrets, browser
   handles, or checkpoint bytes. Only the lease-holding worker process possesses live handles.

6. Vault: Possession Is Not Authority (invariant 11):
   `VaultIntegrationService` validates reference shape (`USER.*` / `DOCUMENT.*`), scopes to
   the run's OWN tenant/user (per-tenant `VaultManager` directories), and requires proof of
   execution authority: an ACTIVE lease with the CURRENT fencing token for THAT run in an
   executable state. `ResolvedSecret` is handed only to the in-process execution boundary and
   is never serialized anywhere. Audit metadata records reference + scoping only.

7. Append-Only, Redacted, Causally-Linked Audit (invariants 12/13):
   `audit_events` has INSERT as the only write path. Payloads pass the Phase 11/12
   sensitivity redaction (`redact_trace_value`) before persistence. Every event may declare
   `parent_event_id`; the service rejects dangling or foreign-tenant causality fail-closed.

8. Server-Side Identity Only (invariant 15):
   `IdentityProvider` resolves bearer tokens to server-side identities. Request schemas are
   `extra="forbid"`, so clients cannot even carry tenant/user/role/worker fields. Roles are
   limited to USER / WORKER / ADMIN — each with concrete runtime meaning, no decorative RBAC.
   Worker ids are server-assigned at token registration.

9. Durable Idempotency and Bounded Retries (invariants 16/17):
   Mutating endpoints accept an `Idempotency-Key` header; records persist per (key, tenant)
   with the request hash — key reuse with a different body fails 422. Service-level retries
   (`recover_run`) require NO active lease AND remaining dispatch budget before requeueing;
   agent recovery, worker retry, and service retry budgets remain distinct layers.

10. Cancellation Is Durable and Terminal (no accidental resume):
    Queued runs cancel immediately; running runs flip to `CANCELLATION_REQUESTED`, observed by
    the worker at safe boundaries. Terminal runs never transition again — a restart is a NEW run.

11. Phase 12 Evaluation Unaffected:
    The evaluator keeps driving the real `AgentRuntime` through `ScenarioRunner`. The enterprise
    engine reuses the same stack and trace conventions; no evaluation bypass path exists.

Status: ACCEPTED — implemented in `app/enterprise/*`, covered by 148 targeted tests
(16 test files: gateway, workflow service, leases, queue, worker, crash recovery, HITL resume,
idempotency, tenant isolation, audit persistence, vault, security, cancellation, live PostgreSQL
store, and two real-Chromium acceptance scenarios), 998 total tests passing with 0 failures.

## D026 — Live validation is a separate shadow-first layer, not a new execution path

Phase 14 (2026-09-20):

1. Shadow mode is MODEL-INDEPENDENT by construction: `run_live_shadow`
   never invokes the reasoner, so no model output can flip shadow mode into
   live mutation mode. The planned action trace is derived deterministically
   from observation + the existing deterministic FieldMapper (no LLM
   gateway) + PolicyEngine risk probes.
2. Controlled execution is a SEPARATELY CONSTRUCTED mode requiring a signed
   human review decision (SHA-256 request digest + HMAC signature, constant-time
   compare). A transplanted approval (valid signature, different plan) is
   rejected by digest mismatch; a forged signature is rejected by HMAC check.
3. Controlled execution adds NO new execution path: mutations go through the
   existing ToolRegistry → PolicyEngine → BrowserExecutor → verification loop
   with the tool layer's stale-ref guard intact. The only additions are two
   deterministic gates in FRONT of the registry: an action allowlist
   (fill/select/check/uncheck only — click/upload never allowed) and per-step
   semantic re-binding (durable semantic ID → fresh ref + fresh
   observation_id, or STOP — never guess).
4. UNCERTAIN verification is failure: a controlled step counts as executed
   only when the executor's deterministic verifier reports `success`.
5. Live evidence separates observed behavior, agent inference (mapper
   bindings are advisory, never verification), deterministic verification,
   human-confirmed results, and environment conditions. Explicit outcome
   statuses never collapse (PORTAL_UNAVAILABLE ≠ AGENT_FAILURE;
   POLICY_BLOCKED ≠ automation failure).
6. Portal profiles are trusted METADATA ONLY (origin, trusted domains, safe
   test path, last_verified_at). The registry must not become executable
   website scripts. Offline test profiles (file://) are validator-marked and
   cannot be confused with live profiles (live constructor enforces https
   gov.in/nic.in origins).

Status: ACCEPTED — implemented in `app/agent/live/*`, covered by 34 unit tests
(tests/unit/test_live_validation.py), 15 offline pipeline tests (real Chromium:
tests/synthetic_forms/test_live_shadow_offline.py, test_live_controlled_offline.py),
6 evaluation-compatibility/acceptance tests (tests/evaluation/test_live_portal_acceptance.py),
and 4 gated live tests (tests/real_sites/test_live_shadow.py, RUN_REAL_SITE_TESTS=true).

## D027 — Phase 14 portal selection, honest environment classification, and no unsafe live mutation

Phase 14 (2026-09-20):

1. Selected portals (small representative set, all with safe observation-only
   paths): PM-KISAN (welfare, pmkisan.gov.in), MyScheme (certificate/scheme
   discovery, myscheme.gov.in), National Career Service (recruitment,
   ncs.gov.in). The india.gov.in gateway was attempted and is CDN/anti-bot
   blocked (Akamai "Access Denied") from this environment.
2. Anti-bot block pages are detected GENERICALLY (title markers: "access
   denied", "just a moment", etc.) and classified as
   `EnvironmentCondition.ANTI_BOT_BLOCK` → `PORTAL_UNAVAILABLE`. A blocked
   page is never credited as a portal observation and never counted as an
   agent failure. The blocked portal is recorded honestly and not retried.
3. services.india.gov.in was added to the site registry (it was absent); it
   redirects to the blocked www.india.gov.in/services — evidence that
   redirect validation against trusted_domains works on live redirects.
4. NO live controlled execution was performed in Phase 14: the selected
   portals are observation/search-class pages whose only interactive
   controls (language selectors, search boxes) offer no meaningful safe
   mutation candidate, and the actual mutation candidate surfaces (eKYC,
   login, job applications) all sit behind authentication boundaries that
   require real user data. The controlled-execution machinery is fully
   proven on offline fixtures (real Chromium) and is READY for live use;
   deferring live mutation is the safety-correct choice, not a gap.
5. Live-run artifacts (report.json + trace.jsonl per portal) are persisted
   under tests/live_portal/evidence/ with explicit LIVE metadata and are
   never fed into deterministic replay as synthetic fixtures.

Status: ACCEPTED — evidence in tests/live_portal/evidence/ (pmkisan,
myscheme, ncs, indiaportal) and tests/real_sites/test_live_shadow.py.


## D028 — Phase 14 live-validation expansion: full portal-class coverage, bounded approvals, and honest failure classification

Phase 14 live validation (2026-09-21):

1. Full portal-class coverage: the live registry now spans all nine
   intended classes — welfare (pmkisan), certificate (myscheme),
   recruitment (ncs), grievance (services.india.gov.in), training
   (apprenticeshipindia.gov.in), education (udiseplus.gov.in), transport
   (parivahan.gov.in), identity_document (digilocker.gov.in), and
   appointments (passportindia.gov.in). apprenticeshipindia.gov.in was
   added to the site registry (it was absent). Every expanded portal was
   live-validated observation-only with persisted evidence. NO live
   mutation was performed on any portal (D027 unchanged): all expanded
   surfaces are landing/discovery pages, and their workflow interiors sit
   behind authentication/payment/document-upload boundaries that remain
   human-gated.
2. Honest mapping evidence: landing pages without data-entry forms record
   `mapping_status=UNSUPPORTED` (mapped=0) — never forced to MAPPING_SUCCESS
   to inflate coverage. The one portal with a mappable public field (NCS
   job search) records MAPPING_SUCCESS with its single HIGH-confidence
   binding. UNSUPPORTED ≠ failure; it is recorded evidence that the
   deterministic mapper found no citizen-data field to bind.
3. Failure classification is non-collapsing end-to-end (WS2): in controlled
   execution, ToolResult error codes now map explicitly — POLICY_DENIED →
   POLICY_BLOCKED; USER_ACTION_REQUIRED / CONFIRMATION_REQUIRED →
   HITL_REQUIRED (a human boundary, never an agent failure);
   VERIFICATION_FAILED → AGENT_FAILURE; everything else → AGENT_FAILURE.
   STALE_TARGET_STOPPED (semantic target absent from the fresh observation)
   is recorded as ENVIRONMENT_FAILURE with a per-step evidence row — the
   run stopped rather than guessed, which is the machinery working.
4. Approvals are BOUNDED authorizations: HumanReviewDecision carries an
   optional `expires_at`; the controlled-execution gate rejects expired or
   unparseable-expiry approvals fail-closed (same path as forged/
   transplanted decisions). Phase 14 live-validation callers always set an
   explicit expiry; empty expiry remains possible only when the issuing
   HITL system records none.
5. The deterministic controlled allowlist now also forbids `field:mfa` and
   `field:passwd` semantic prefixes (password/OTP/CAPTCHA/PIN were already
   forbidden). Prohibition is enforced by the fixed gate — independent of
   any model output — and is proven by an explicit denial matrix
   (click/upload/password/otp/captcha/mfa/pin/payment/final-legal).
6. Real-LLM compatibility (WS4) closed its last gap: the OpenRouter
   completion budget is the configurable `openrouter_max_tokens` setting
   (default 4096) because reasoning-style models spend hidden reasoning
   tokens from the same budget — a hardcoded 4096 truncated the visible
   JSON decision (finish_reason=length) and the reasoner failed closed with
   DECISION_PARSE_FAILED. The system prompt now shows the EXACT decision
   JSON shape (nested `action` object) after live probing showed small free
   models otherwise emit non-conforming shapes they never repair. Both
   changes are contract clarifications: validation, policy, and the
   execution path are unchanged, and model failures still fail closed.
7. Free-tier model slugs churn: the daily free quota (50 requests/day per
   account) and per-model availability both change without notice. The
   gated real-LLM test skips cleanly without a key, fails honestly on
   quota exhaustion, and the operator pins working slugs via .env
   (documented in BUILD_STATUS). No model identity is hard-coded in source.

Status: ACCEPTED — evidence in tests/live_portal/evidence/ (9 portals),
tests/real_sites/test_live_shadow.py (10 gated live tests),
tests/synthetic_forms/test_live_controlled_matrix.py (20 offline controlled
matrix tests), tests/unit/test_live_validation.py (45 unit tests), and
tests/unit/test_openrouter_live_contract.py (real-gateway contract tests).






