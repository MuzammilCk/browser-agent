# BUILD STATUS

Last reconciled: 2026-09-18
Current phase: Phase 1 — Stabilize browser foundation (COMPLETE)
Overall: IN PROGRESS (Phase 0 + Phase 1 complete)
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

Current reproducible test baseline: **505 tests passing** (431 unit + 44 synthetic + 30 browser-error/integration tests). 0 tests failing. 2 tests were previously failing due to `.env` misconfiguration (ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true was defeating the model guardrail) — fixed by setting it to false.

## Phase 1 evidence

### Test count
```
pytest tests/unit/ tests/integration/ tests/synthetic_forms/ tests/real_sites/ -q
→ 505 passed in 188.5s
```

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
| 6 | iframe | `test_observer.py::TestIframeObservation` + `test_executor.py::TestIframeInteraction` | ✅ Yes (NEW) | Sufficient — observe + iframe content interaction + DOM verification |
| 7 | dynamic form | `test_observer.py::TestDropdownForm::test_dependent_dropdown_appears` + `test_executor.py::TestSelectAction::test_select_dependent_dropdown` | ✅ Yes | Sufficient |
| 8 | validation | `test_observer.py::TestValidationForm::test_observes_validation_errors` + `test_verification.py::TestFillFailureDetection::test_detects_validation_appeared` | ✅ Yes | Sufficient |
| 9 | stale references | `test_executor.py::TestStaleRefRejection::test_stale_observation_rejected` | ✅ Yes | Sufficient |
| 10 | multi-tab | `test_multi_tab.py` (11 tests across 4 classes) | ✅ Yes | Sufficient |
| 11 | no swallowed browser errors | `test_browser_errors.py` (3 NEW tests) | ✅ Yes (NEW) | Sufficient |

### New files added for Phase 1 coverage
- `tests/synthetic_forms/pages/file_upload.html` — page with file inputs
- `tests/synthetic_forms/pages/iframe.html` — page with iframe (uses `srcdoc` for content)
- `tests/integration/fixtures/test_photo.jpg` — real JPEG fixture for upload tests (created with PIL)
- `tests/integration/test_browser_errors.py` — browser error visibility tests (3 tests)

### Current Phase 1 status
| Item | Status | Evidence |
|------|--------|----------|
| Run current test suite | ✅ Done | 505 passed, 0 failed |
| Record exact current baseline | ✅ Done | See above |
| Synthetic coverage: text/select/radio/checkbox/file/iframe/dynamic/validation | ✅ Done (31 tests) | tests/synthetic_forms/ |
| Execution coverage: fill/click/select/check/radio/upload/iframe/dynamic | ✅ Done (32 tests) | tests/integration/test_executor.py::TestFillAction, TestClickAction, TestSelectAction, TestCheckUncheckAction, TestUploadAction, TestIframeInteraction |
| Stale-reference tests | ✅ Done | tests/integration/test_executor.py::TestStaleRefRejection |
| Multi-tab tests | ✅ Done | tests/integration/test_multi_tab.py |
| No swallowed browser errors | ✅ Done | tests/integration/test_browser_errors.py |

## Phase tracker

| Phase | Status |
|---|---|
| 0 Control plane | COMPLETE |
| 1 Browser foundation | COMPLETE |
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
- [x] current regression suite green (505 tests, 0 failures)
- [ ] persistent AgentSession (Phase 2)
- [x] policy on every mutation (PolicyEngine wired into BrowserExecutor)
- [x] verification on every mutation (8 per-action verifiers)
- [ ] durable human interrupts (Phase 8)
- [ ] prompt-injection suite (stub exists: tests/prompt_injection/)
- [ ] evaluation metrics (Phase 12)
- [x] live observation-only validation (tests/real_sites/test_pmkisan_observe.py)
- [ ] isolated worker runtime (Phase 13)
