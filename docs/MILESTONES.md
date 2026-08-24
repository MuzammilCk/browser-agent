# 🎯 Milestones — Implementation Tracker

**Last updated:** 2026-08-24

> **Rule:** Read `docs/context.md` and `docs/architecture.md` before starting any milestone.
> Update this file after completing each milestone with verification evidence.

---

## Phase 0 — Repository Bootstrap ✅

- Project structure, pyproject.toml, .env.example, .gitignore
- FastAPI app with health endpoint and minimal UI
- Playwright browser manager (launch, open, screenshot, close)
- Settings with pydantic-settings, logging setup
- **Tests:** 19 passed in 4.94s

---

## Phase 1 — Playwright Perception Engine ✅

- ARIA snapshot extraction (`app/browser/aria.py`)
- Targeted DOM metadata extraction (`app/browser/dom.py`)
- `PageObserver` produces typed `PageState` + `PageObservation`
- Split name fields: `accessible_name`, `html_name`, `label_text`
- Context fields: `section_heading`, `help_text`, `group_label`
- Frame-aware element extraction
- Auth detection with confidence scoring
- **Synthetic pages:** simple, dropdowns, checks, validation, multistep
- **Tests:** 14 passed in 17.66s

---

## Phase 2 — Deterministic Browser Executor ✅

- Typed browser actions: click, fill, select, check/uncheck, scroll, scroll_to, press, wait, go_back, upload
- Locator engine with priority hierarchy (role→label→placeholder→semantic→text)
- Pydantic validators enforce required fields per action type
- `open` removed from LLM action set (navigation is workflow-controlled)
- Upload requires `document_ref` only (no raw filesystem paths)
- **Tests:** 47 passed in 38.62s

---

## Phase 2+ — Audit Fixes ✅

- Created `PageObservation` model (wraps PageState + ARIA + context)
- Removed broken `snapshot_ref` locator strategy
- Implemented `ValueResolver` (`USER.full_name` → actual value locally)
- Implemented `DocumentResolver` (`DOCUMENT.aadhaar` → file path locally)
- Wired `ActionVerifier` into executor core loop
- Added `scroll_to(target_ref)` semantic scrolling
- Sensitive field classification (`PUBLIC/INTERNAL/SENSITIVE/SECRET`)
- **Tests:** 77 passed in 75.83s

---

## Phase 3 — Verification Engine ✅

### Deliverables

- Post-fill verification: live DOM value check, validation errors, disabled state, alerts
- Post-click verification: page change, dialog, new elements, title, element state, content comparison
- Post-select verification: option match, dependent field detection
- Post-check/uncheck verification: checkbox state match
- Post-upload verification: **targets exact element** (not all file inputs)
- Post-scroll_to verification: **viewport bounding rect check**
- Re-observation after every action (executor produces `post_observation`)
- UNCERTAIN verification **stops progression** (`recovery_required=True`)
- Observation-scoped refs with **stale reference rejection**
- Sensitive field policy blocks Aadhaar/PAN patterns in `literal_value`

### ActionResult Contract (Phase 3.5)

```
ActionResult
├── action: BrowserAction
├── success: bool
├── message: str
├── verification: VerificationResult
├── post_observation: PageObservation   ← next iteration uses this
├── recovery_required: bool             ← True for FAILURE/UNCERTAIN
└── user_action_required: bool          ← True for request_user_action
```

**Tests:** 128 passed in 102.28s

---

## Phase 4 — User Vault + Document Registry ✅

### Deliverables

- `UserVault` model (35+ fields: identity, contact, address, education, employment, government_ids, financial, family)
- `DocumentRef` model + `DocumentRegistry`
- `ValueResolver` maps `USER.x` → actual value locally
- `DocumentResolver` maps `DOCUMENT.x` → file path locally
- Sensitive field classification per SAFETY.md
- `VaultManager` for JSON persistence (load/save)
- Sample vault with realistic Indian government form data

**Tests:** 34 passed in 0.41s (Phase 4), 128 total

---

## Phase 5 — OpenRouter LLM Gateway ✅

### Deliverables

- `LLMGateway` protocol/interface
- `OpenRouterGateway` implementation
- Structured JSON schema output
- Timeout/retry policy (bounded, 3 retries with exponential backoff)
- Model configuration via env vars (`OPENROUTER_MODEL`)
- Request/response logging with redaction
- Usage/cost metadata recording (`LLMUsage`)
- Error hierarchy (Timeout, RateLimit, Server, BadRequest, MalformedResponse)
- Multimodal support (images via base64)
- Async context manager
- 22 tests (protocol, schemas, retry, gateway, integration)

**Tests:** 22 passed in 5.19s, 150 total

---

## Phase 6 — Semantic Field Mapper ✅

### Deliverables

- `FieldBinding` model with confidence scoring (HIGH/MEDIUM/LOW/NONE)
- `MappingResult` with strategy counts, unmapped/ambiguous field tracking
- `FieldMapper` with deterministic keyword/semantic matching (30+ rules)
- LLM-based ambiguous resolution via OpenRouter structured output
- Similar label discrimination tested
- Synthetic government form with 20+ fields
- 41 tests

**Tests:** 41 passed in 0.44s (Phase 6), 191 total

---

## Phase A — Contract Hardening ✅

### Goal

Fix cross-component contracts and integration gaps identified in the 50-issue audit.

### Deliverables

- [x] **ReferenceRegistry** (`app/agent/registry.py`) — single source of truth for all 35+ USER.* and DOCUMENT.* references
- [x] **ValueResolver** updated — uses ReferenceRegistry, includes all missing fields (father_name, mother_name, spouse_name, guardian_name, permanent_address, age, village, bank_account)
- [x] **DocumentResolver** updated — uses ReferenceRegistry, unified document names (DOCUMENT.photo everywhere)
- [x] **FieldMapper** updated — matches file inputs via `input_type` not `role` (audit #4)
- [x] **Unmapped fields → LLM** — completely unmapped fields now sent to LLM second stage (audit #8)
- [x] **LLM output validated** — every LLM-produced binding checked against ReferenceRegistry (audit #11)
- [x] **FieldBinding.observation_id** — bindings are observation-scoped (audit #12)
- [x] **Frame-aware locator** — resolves against correct Playwright Frame based on element.frame_id (audit #15)
- [x] **FALLBACK strategy removed** — replaced with UNMAPPED (audit #10)
- [x] **map_fields() no longer accepts vault values** — only reference keys sent to LLM (audit #42)
- [x] **Guardian Name** maps to USER.guardian_name, not USER.father_name (audit #7)

### Files Changed

| File | Change |
|------|--------|
| `app/agent/registry.py` | **NEW** — ReferenceRegistry with 38 references |
| `app/agent/field_mapper.py` | Updated to use registry, unmapped→LLM, LLM validation |
| `app/agent/field_mapper_models.py` | Added observation_id, removed FALLBACK |
| `app/vault/resolver.py` | Updated ValueResolver/DocumentResolver to use registry |
| `app/vault/sensitivity.py` | Added sensitivity for new fields |
| `app/browser/locator.py` | Frame-aware resolution |
| `tests/unit/test_registry.py` | **NEW** — 17 registry tests |
| `tests/unit/test_field_mapper.py` | Updated for new API, added Phase A tests |

### Audit Issues Addressed

| # | Issue | Fix |
|---|-------|-----|
| 1 | Element ref system not unified | ReferenceRegistry as single source |
| 4 | File input role/type mismatch | Match on input_type, not role |
| 5 | FieldMapper refs don't match Vault | All refs derived from registry |
| 6 | Document ref names inconsistent | Unified to DOCUMENT.photo |
| 7 | Guardian name unsafe guessing | Maps to USER.guardian_name |
| 8 | Unmapped fields don't reach LLM | Now sent to LLM second stage |
| 10 | FALLBACK strategy dangerous | Removed, replaced with UNMAPPED |
| 11 | LLM refs not validated | Validated against registry |
| 12 | FieldBinding needs observation_id | Added observation_id field |
| 15 | Frame-aware locator incomplete | Resolves against correct Frame |
| 37 | Contracts not from one source | ReferenceRegistry is source of truth |
| 42 | Mapper prompt receives values | Only reference keys sent |

### Acceptance Criteria

```
ReferenceRegistry exists and is used by all consumers. ✅
FieldMapper bindings validated against registry. ✅
LLM output validated against registry. ✅
File inputs match via input_type. ✅
Unmapped fields sent to LLM. ✅
Bindings are observation-scoped. ✅
Frame-aware locator resolves correctly. ✅
```

**Tests:** 52 new (Phase A), 202 total passed in 84.76s

---

## Phase B — Safety Engine

**Status:** ⬜ Not started

### Goal

PolicyEngine with R0-R4 risk levels, user checkpoints, trusted domain registry.

---

## Phase C — Workflow Orchestration

**Status:** ⬜ Not started

### Goal

WorkflowState, AgentRunner/WorkflowManager, full observe→plan→execute→verify loop.

---

## Phase D — Perception / Mapping Hardening

**Status:** ⬜ Not started

### Goal

Fix remaining perception and mapping issues, e2e synthetic test.

---

## Phase 7 — Agent Control Loop

**Status:** ⬜ Not started

### Goal

The closed-loop: observe → plan → policy → execute → verify → observe.

---

## Phase 8 — Risk and Approval Gate

**Status:** ⬜ Not started

### Goal

R0-R4 policy enforcement in code, not just prompts.

---

## Phase 9 — Vision Fallback

**Status:** ⬜ Not started

### Goal

Screenshot + vision model for when semantic perception is insufficient.

---

## Phase 10 — Prompt Injection Testing

**Status:** ⬜ Not started

### Goal

Verify the agent treats page content as untrusted data.
