# BUILD STATUS

Last reconciled: 2026-09-18
Current phase: Phase 1 — Stabilize browser foundation
Overall: IN PROGRESS (Phase 0 complete, Phase 1 baseline established)
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

Current reproducible test baseline: **494 tests passing** (416 unit + 27 synthetic + 51 integration/real_sites). 2 tests previously failing due to `.env` misconfiguration (ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true was defeating the model guardrail) — now fixed.

## Phase 1 evidence

### Test count
```
pytest tests/unit/ tests/integration/ tests/synthetic_forms/ tests/real_sites/ -q
→ 494 passed in 128.92s
```

### Failing tests
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
Validated via `tests/synthetic_forms/` (27 tests, all passing):
- Text inputs observed and filled
- Select dropdowns observed and selected
- Checkbox/radio observation
- Validation error detection and extraction
- Multi-step form navigation
- Post-action verification (fill, click, select)
- Re-observation after every action (`post_observation` in `ActionResult`)
- Stale reference rejection
- UNCERTAIN verification stops progression

### Current Phase 1 status
| Item | Status | Evidence |
|------|--------|----------|
| Run current test suite | ✅ Done | 494 passed, 0 failed |
| Record exact current baseline | ✅ Done | See above |
| Synthetic coverage: text/select/radio/checkbox/file/iframe/dynamic/validation | ✅ Done (27 tests) | tests/synthetic_forms/ |
| Stale-reference tests | ✅ Done | tests/unit/test_* |
| Multi-tab tests | ✅ Done | tests/integration/test_multi_tab.py |
| No swallowed browser errors | ✅ Partial | No error-suppression found in observer/executor |

## Phase tracker

| Phase | Status |
|---|---|
| 0 Control plane | COMPLETE |
| 1 Browser foundation | IN PROGRESS |
| 2 AgentRuntime | NOT STARTED |
| 3 Tool Registry | NOT STARTED |
| 4 OpenRouter agent loop | NOT STARTED |
| 5 Goal/Subgoal | NOT STARTED |
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

- [ ] current regression suite green
- [ ] persistent AgentSession
- [ ] real tool-calling loop
- [ ] restart/resume
- [ ] policy on every mutation
- [ ] verification on every mutation
- [ ] durable human interrupts
- [ ] prompt-injection suite
- [ ] evaluation metrics
- [ ] live observation-only validation
- [ ] isolated worker runtime
