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

### Failure Injection Tests

| Scenario | Detection |
|----------|-----------|
| Field disappears after fill | ✅ FAILURE |
| Field becomes disabled | ✅ FAILURE |
| Validation error appears | ✅ FAILURE |
| Normal fill (no side effects) | ✅ SUCCESS |
| No-op click | ✅ UNCERTAIN (stops) |
| Click adds new elements | ✅ SUCCESS |
| Click changes title | ✅ SUCCESS |
| Select causes dependent field | ✅ SUCCESS |
| Select with invalid option | ✅ FAILURE |
| Stale observation_id rejected | ✅ FAILURE |

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

### Acceptance Criteria

```
The verifier detects failed actions rather than blindly reporting success. ✅
Failure injection tests prove detection works. ✅
UNCERTAIN stops progression. ✅
Post-observation returned to caller. ✅
Stale refs rejected. ✅
```

**Tests:** 128 passed in 102.28s

---

## Phase 4 — User Vault + Document Registry ✅

### Deliverables

- `UserVault` model (29 fields: identity, contact, address, education, employment, government_ids, financial)
- `DocumentRef` model + `DocumentRegistry`
- `ValueResolver` maps `USER.x` → actual value locally
- `DocumentResolver` maps `DOCUMENT.x` → file path locally
- Sensitive field classification per SAFETY.md
- `VaultManager` for JSON persistence (load/save)
- Sample vault with realistic Indian government form data
- Executor integration: `value_ref` resolved before Playwright execution

### Sensitive Field Classification

| Level | Fields |
|-------|--------|
| 🔴 SENSITIVE | aadhaar_number, pan_number, voter_id, date_of_birth, mobile, annual_income, account_number |
| 🟡 INTERNAL | email, address, employer, bank_name, ifsc_code |
| 🟢 PUBLIC | full_name, state, district, gender, category, education, occupation |

### Acceptance Criteria

```
The executor resolves USER.full_name, USER.date_of_birth,
DOCUMENT.income_certificate locally without exposing raw values. ✅
```

**Tests:** 34 passed in 0.41s (Phase 4), 128 total

---

## Phase 5 — OpenRouter LLM Gateway ✅

### Goal

OpenRouter API client with structured output, retries, and cost tracking.

### Deliverables

- [x] `LLMGateway` protocol/interface
- [x] `OpenRouterGateway` implementation
- [x] Structured JSON schema output
- [x] Timeout/retry policy (bounded, 3 retries with exponential backoff)
- [x] Model configuration via env vars (`OPENROUTER_MODEL`)
- [x] Request/response logging with redaction
- [x] Usage/cost metadata recording (`LLMUsage`)
- [x] Error hierarchy (Timeout, RateLimit, Server, BadRequest, MalformedResponse)
- [x] Multimodal support (images via base64)
- [x] Async context manager
- [x] 22 tests (protocol, schemas, retry, gateway, integration)

### Acceptance Criteria

```
LLMGateway protocol defined and satisfied. ✅
OpenRouterGateway retries on timeout/429/5xx. ✅
Structured JSON schema output works. ✅
Fail-closed on all errors. ✅
```

**Tests:** 22 passed in 5.19s, 150 total

---

## Phase 6 — Semantic Field Mapper ✅

### Goal

Map website form fields to user-data references using deterministic matching + LLM reasoning.

### Deliverables

- [x] `FieldBinding` model with confidence scoring (HIGH/MEDIUM/LOW/NONE)
- [x] `MappingResult` with strategy counts, unmapped/ambiguous field tracking
- [x] `FieldMapper` with deterministic keyword/semantic matching
- [x] LLM-based ambiguous resolution via OpenRouter structured output
- [x] 30+ deterministic rules covering identity, contact, address, education, financial, documents
- [x] Exclude-keyword logic to prevent false matches (e.g., "Father Name" → not USER.full_name)
- [x] Minimum keyword length filter to prevent false positives (e.g., "name" → not random text)
- [x] Evidence trail for every mapping (labels, roles, sections, LLM reasoning)
- [x] Similar label discrimination tested: Applicant/Father/Mother/Spouse Name
- [x] Synthetic government form with 20+ fields and dependent dropdown
- [x] 41 tests (deterministic matching, confidence, evidence, LLM mocked, discrimination)

### Deterministic Rules

| Category | Bindings |
|----------|----------|
| Identity | USER.full_name, USER.date_of_birth, USER.gender, USER.age |
| Contact | USER.mobile, USER.email |
| Address | USER.address, USER.permanent_address, USER.state, USER.district, USER.pincode, USER.village |
| Government IDs | USER.aadhaar_number, USER.pan_number, USER.voter_id |
| Education | USER.education |
| Employment | USER.occupation, USER.annual_income |
| Category | USER.category |
| Family | USER.father_name, USER.mother_name, USER.spouse_name |
| Financial | USER.bank_account, USER.ifsc_code |
| Documents | DOCUMENT.aadhaar, DOCUMENT.income_certificate, DOCUMENT.photo, DOCUMENT.signature |

### Similar Label Discrimination

| Label | Correct Mapping |
|-------|----------------|
| Applicant Name | USER.full_name |
| Father's Name | USER.father_name |
| Mother's Name | USER.mother_name |
| Spouse Name | USER.spouse_name |
| Parent/Guardian Name | Not USER.full_name (exclude) |

### Acceptance Criteria

```
Deterministic matching correctly distinguishes semantically similar labels. ✅
LLM resolves ambiguous cases when gateway available. ✅
Confidence levels prevent incorrect auto-fill. ✅
Evidence trail supports audit. ✅
```

**Tests:** 41 passed in 0.44s (Phase 6), 191 total

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
