# 🎯 Milestones — Implementation Tracker

**Last updated:** 2026-08-24

> **Rule:** Read `docs/context.md` and `docs/architecture.md` before starting any milestone.
> Update this file after completing each milestone with verification evidence.

---

## Phase 0 — Repository Bootstrap

**Status:** ✅ Complete

### Goal

A Python project that starts, launches Playwright Chromium, and serves a minimal local UI.

### Deliverables

- [x] Python project structure created
- [x] `pyproject.toml` with all Phase 0 dependencies
- [x] `.env.example` with required variables
- [x] `.gitignore` (secrets, venv, data, __pycache__)
- [x] `app/main.py` — FastAPI entry point with health endpoint
- [x] Playwright browser manager — launch, open URL, screenshot, close
- [x] Basic config system (reads `.env`)
- [x] Basic logging setup
- [x] First test: `pytest` passes

### Acceptance Criteria

```
python starts ✅
Playwright launches Chromium ✅
A URL can be opened ✅
A screenshot can be captured ✅
Browser closes cleanly ✅
Local UI reachable at localhost:8000 ✅
```

### Verification Evidence

- Date completed: 2026-08-24
- Files created: pyproject.toml, .env.example, .gitignore, app/main.py, app/config/settings.py, app/models/*.py, app/browser/manager.py, tests/unit/*.py
- Test output: 19 passed in 4.94s
- Notes: All tests pass. Playwright Chromium launches and closes cleanly. FastAPI app serves HTML UI and health endpoint.

---

## Phase 1 — Playwright Perception Engine

**Status:** ✅ Complete

### Goal

Normalize any web page into a typed `PageState` object using ARIA snapshots + DOM metadata.

### Deliverables

- [x] ARIA snapshot extraction
- [x] Interactive DOM metadata extraction
- [x] Validation/error extraction
- [x] Frame discovery
- [x] Screenshot capture (as fallback — via BrowserManager)
- [x] `PageState` Pydantic model
- [x] `ElementState`, `AlertState`, `ValidationErrorState`, `FrameState` models
- [x] Synthetic test pages (text inputs, dropdowns, checkboxes, radios, validation, multi-step)
- [x] Tests: observer returns accurate PageState for all synthetic forms

### Acceptance Criteria

```
Given synthetic HTML forms,
the observer returns accurate structured PageState
with correct element refs, roles, labels, required/disabled states.
✅ All 14 tests pass.
```

### Verification Evidence

- Date completed: 2026-08-24
- Files created: app/browser/aria.py, app/browser/dom.py, app/browser/observer.py
- Synthetic test pages: simple.html, dropdowns.html, checks.html, validation.html, multistep.html
- Test results: 14 passed in 17.66s
- Notes: DOM extraction uses targeted JavaScript. ARIA snapshot available as fallback. Dependent dropdown test confirms re-observation pattern works.

---

## Phase 2 — Deterministic Browser Executor

**Status:** ✅ Complete

### Goal

Typed Python functions that execute browser actions without any LLM involvement.

### Deliverables

- [x] `open(url)` — navigate to URL
- [x] `click(ref)` — click element
- [x] `fill(ref, value)` — fill text input
- [x] `select(ref, option)` — select dropdown option
- [x] `check(ref)` / `uncheck(ref)` — toggle checkboxes
- [x] `upload(ref, file_path)` — file upload
- [x] `scroll(direction)` — page scroll
- [x] `wait(condition)` — wait for state
- [x] `go_back()` — navigate back
- [x] `press(key)` — keyboard press
- [x] Locator engine with priority hierarchy (role→label→placeholder→semantic→text)
- [x] Post-action verification engine (fill, click, select, check/uncheck)
- [x] Integration tests for every action type

### Acceptance Criteria

```
Every browser tool has integration tests. ✅
A test page can be manipulated reliably through typed Python functions. ✅
```

### Verification Evidence

- Date completed: 2026-08-24
- Files created: app/browser/executor.py, app/browser/locator.py, app/browser/verification.py, tests/integration/test_executor.py
- Test results: 47 passed in 38.62s (full suite)
- Notes: Locator uses role+name exact matching to avoid strict mode violations. Dependent dropdown re-observation works correctly.

### Audit Fixes (Phases 0-2 hardening) — 2026-08-24

**Audit issues addressed:** 1-16

| # | Issue | Fix |
|---|-------|-----|
| 1+2+5 | ARIA snapshot unused, refs inconsistent, broken snapshot_ref | Created PageObservation model, removed broken `[ref='e12']` strategy |
| 3 | name vs accessible_name mixed | Split into accessible_name, html_name, label_text with .name property fallback |
| 6 | Page classification too heuristic | Multi-signal classification with form/review/payment detection |
| 7 | Auth detection too keyword-based | Confidence-scored detection using field types + structure + alerts |
| 8 | Page context too thin | Added section_heading, help_text, group_label, nearby_text to ElementState |
| 9 | fill ignores value_ref | Implemented ValueResolver (USER.full_name → actual value locally) |
| 10 | upload ignores document_ref | Implemented DocumentResolver (DOCUMENT.aadhaar → file path locally) |
| 11+12 | Verification not wired | ActionVerifier now called after every state-changing action |
| 14 | Scroll too low-level | Added scroll_to(target_ref) semantic scrolling |
| 15 | Frames not connected | Frame-aware element extraction + frame_id on elements |
| 16 | Action model needs validation | Pydantic validators enforce required fields per action type |

**Tests:** 77 passed in 75.83s

---

## Phase 3 — Verification Engine

**Status:** ✅ Complete

### Goal

After every state-changing action, verify the result matches expectations.

### Deliverables

- [x] Post-fill verification (live DOM value check, validation state, disabled state, alerts)
- [x] Post-click verification (page change, dialog, new elements, title change, element state)
- [x] Post-select verification (selected option match, dependent field changes)
- [x] Post-check/uncheck verification (checkbox state match)
- [x] Post-upload verification (live DOM file input check)
- [x] Failure injection tests (field disappears, disabled, validation, no-op click, new elements, dependent dropdowns)
- [x] Re-observation after every action (executor re-observes + verifies)
- [x] Verification result model with status, message, expected/actual, validation_errors

### Acceptance Criteria

```
The verifier detects failed actions rather than blindly reporting success. ✅
Failure injection tests prove detection works. ✅
```

### Verification Evidence

- Date completed: 2026-08-24
- Files created: app/browser/verification.py (enhanced), tests/synthetic_forms/test_verification.py, 3 failure injection pages
- Test results: 90 passed in 89.48s (full suite), 13 Phase 3 tests
- Notes: Verifier uses live Playwright DOM queries for ground-truth value checks, not just PageState comparison

---

## Phase 4 — User Vault + Document Registry

**Status:** ✅ Complete

### Goal

Typed user data model with semantic references. Local resolution without exposing raw values to LLM.

### Deliverables

- [x] `UserVault` model (identity, contact, address, education, employment, government_ids, financial)
- [x] `DocumentRef` model
- [x] `DocumentRegistry` — register and resolve documents
- [x] Semantic reference resolver (`USER.full_name` → actual value)
- [x] Document resolver (`DOCUMENT.aadhaar` → file path)
- [x] Sensitive field classification (PUBLIC/INTERNAL/SENSITIVE/SECRET)
- [x] Vault manager (load/save from JSON)
- [x] Sample vault with Indian government form data
- [x] 34 tests covering vault, resolvers, classification, persistence, integration

### Acceptance Criteria

```
The executor can resolve USER.full_name, USER.date_of_birth,
DOCUMENT.income_certificate locally without exposing raw values to the planner. ✅
```

### Verification Evidence

- Date completed: 2026-08-24
- Files created: app/vault/sensitivity.py, app/vault/manager.py, tests/unit/test_vault.py
- Test results: 34 passed in 0.41s (Phase 4), 124 passed total
- Notes: Full end-to-end: create sample vault → resolve all fields → verify values

---

## Phase 5 — OpenRouter LLM Gateway

**Status:** ⬜ Not started

### Goal

OpenRouter API client with structured output, retries, and cost tracking.

### Deliverables

- [ ] `LLMGateway` protocol/interface
- [ ] `OpenRouterGateway` implementation
- [ ] Structured JSON schema output
- [ ] Timeout/retry policy (bounded)
- [ ] Model configuration via env vars
- [ ] Request/response logging with redaction
- [ ] Usage/cost metadata recording
- [ ] Tests: valid output, timeout, 429, 5xx, malformed output, fail-closed

### Acceptance Criteria

```
A test PageState can be sent to OpenRouter and a valid Pydantic decision returned.
API failures are handled with fail-closed behavior.
```

### Verification Evidence

*Fill in after implementation:*

- Date completed:
- Files created:
- Test results:
- Notes:

---

## Phase 6 — Semantic Field Mapper

**Status:** ⬜ Not started

### Goal

Map website form fields to user-data references using LLM reasoning.

### Deliverables

- [ ] Local deterministic matching (first pass)
- [ ] LLM-based ambiguous resolution (second pass)
- [ ] `FieldBinding` model with confidence
- [ ] Three confidence levels: HIGH, MEDIUM, LOW
- [ ] Benchmark with intentionally different labels
- [ ] Tests: correct differentiation of "Applicant Name" vs "Parent Name" vs "Name as per Aadhaar"

### Acceptance Criteria

```
Synthetic forms with renamed labels still map correctly
where semantics are clear. Ambiguous cases ask the user.
```

### Verification Evidence

*Fill in after implementation:*

- Date completed:
- Files created:
- Test results:
- Notes:

---

## Phase 7 — Agent Control Loop

**Status:** ⬜ Not started

### Goal

The closed-loop: observe → plan → policy → execute → verify → observe.

### Deliverables

- [ ] Main agent loop implementation
- [ ] Workflow state machine
- [ ] Integration with all previous components
- [ ] Synthetic multi-step form test
- [ ] Tests: simple form, multi-page, dependent dropdown, conditional field, validation error, upload, user intervention

### Acceptance Criteria

```
Agent can fill a synthetic multi-step form without hardcoded selectors.
Agent pauses at OTP/CAPTCHA/final submission boundaries.
```

### Verification Evidence

*Fill in after implementation:*

- Date completed:
- Files created:
- Test results:
- Notes:

---

## Phase 8 — Risk and Approval Gate

**Status:** ⬜ Not started

### Goal

R0-R4 policy enforcement in code, not just prompts.

### Deliverables

- [ ] Risk classification engine
- [ ] R0: observation — auto approve
- [ ] R1: ordinary field — auto approve
- [ ] R2: sensitive — policy consent required
- [ ] R3: authentication — user takeover
- [ ] R4: irreversible — explicit confirmation required
- [ ] Tests proving enforcement

### Acceptance Criteria

```
Ordinary fill → automatic
ID field → policy-gated
OTP → user takeover
CAPTCHA → user takeover
payment → confirmation
final submission → confirmation
```

### Verification Evidence

*Fill in after implementation:*

- Date completed:
- Files created:
- Test results:
- Notes:

---

## Phase 9 — Vision Fallback

**Status:** ⬜ Not started

### Goal

Screenshot + vision model for when semantic perception is insufficient.

### Deliverables

- [ ] Screenshot capture on demand
- [ ] OpenRouter multimodal request
- [ ] Structured visual finding output
- [ ] DOM re-verification of visual findings
- [ ] Policy gate on vision-derived actions
- [ ] Tests on pages with intentionally insufficient semantic data

### Acceptance Criteria

```
System recognizes visual uncertainty → uses screenshot → identifies candidate
→ verifies against DOM → executes only after confirmation.
```

### Verification Evidence

*Fill in after implementation:*

- Date completed:
- Files created:
- Test results:
- Notes:

---

## Phase 10 — Prompt Injection & Security Testing

**Status:** ⬜ Not started

### Goal

Verify the agent treats page content as untrusted data.

### Deliverables

- [ ] Hostile synthetic pages (fake instructions, credential harvesting, malicious redirects)
- [ ] Hidden prompt injection text tests
- [ ] Tests proving policy preservation under attack
- [ ] Security test suite

### Acceptance Criteria

```
Agent treats page content as untrusted information.
Application policy is never overridden by page text.
```

### Verification Evidence

*Fill in after implementation:*

- Date completed:
- Files created:
- Test results:
- Notes:
