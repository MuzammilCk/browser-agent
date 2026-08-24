# 🧪 Testing — Strategy & Coverage Tracker

**Last updated:** 2026-08-24

> **Rule:** Run tests after each meaningful milestone. Update this file with results.
> No phase is complete until its tests pass.

---

## Test Categories

### 1. Unit Tests (`tests/unit/`)

| Target | What to test |
|--------|-------------|
| `PageState` model | Parsing, validation, required fields |
| `BrowserAction` schema | Valid/invalid actions, schema enforcement |
| `FieldBinding` model | Confidence levels, reference validation |
| `RiskLevel` classification | Correct risk assignment for action types |
| `PolicyEngine` | Allow/block/confirm decisions |
| `ValueResolver` | `USER.x` → actual value mapping |
| `DomainRegistry` | Trusted/untrusted domain lookup |
| `LocatorRanking` | Priority ordering of locator strategies |

### 2. Browser Integration Tests (`tests/integration/`)

| Target | What to test |
|--------|-------------|
| `fill` | Fill text input, verify value |
| `click` | Click button, verify page change |
| `select` | Select dropdown option, verify selection |
| `check`/`uncheck` | Toggle checkbox, verify state |
| `upload` | Upload file, verify file input |
| `scroll` | Scroll page, verify viewport change |
| `frames` | Interact with iframe content |
| `dynamic forms` | Dependent dropdown, conditional fields |
| `validation` | Post-action validation detection |

### 3. Synthetic Form Tests (`tests/synthetic_forms/`)

| Form Type | File |
|-----------|------|
| Simple text inputs | `test_simple_form.py` |
| Dropdowns + dependent dropdowns | `test_dropdowns.py` |
| Checkboxes + radio buttons | `test_checks.py` |
| File upload | `test_upload.py` |
| Multi-step wizard | `test_multistep.py` |
| Iframe content | `test_iframes.py` |
| Dynamic fields | `test_dynamic.py` |
| Validation errors | `test_validation.py` |
| Mixed form | `test_mixed_form.py` |

### 4. LLM Contract Tests (`tests/unit/`)

| Target | What to test |
|--------|-------------|
| Valid structured output | Model returns schema-valid JSON |
| Malformed output | Agent handles non-JSON gracefully |
| Ambiguous field | Agent asks user instead of guessing |
| Conflicting mapping | Agent resolves or asks |
| Refusal/stop | Agent stops when uncertain |

### 5. Safety Tests (`tests/safety/`)

| Target | What to test |
|--------|-------------|
| R0–R4 classification | Correct risk level for each action type |
| Policy enforcement | R2/R3/R4 actions blocked without approval |
| Secret leakage | No raw values in LLM context or logs |
| Fail-closed | Unknown actions stopped |
| Domain safety | Untrusted navigation blocked |

### 6. Security Tests (`tests/prompt_injection/`)

| Target | What to test |
|--------|-------------|
| Fake system instructions in page | Agent ignores them |
| Credential harvesting text | Agent does not comply |
| Hidden prompt text | Agent treats as untrusted |
| Malicious redirects | Agent handles safely |
| Data exfiltration instructions | Agent preserves policy |

### 7. Portal Regression Tests (`tests/portal_regression/`)

| Portal | File | Status |
|--------|------|--------|
| *(populated as portals are tested)* | — | — |

---

## Coverage Targets

| Category | Target |
|----------|--------|
| Unit tests | 90%+ line coverage |
| Integration tests | All browser actions covered |
| Synthetic forms | All form types in Section 2 covered |
| Safety tests | All R0–R4 paths tested |
| Security tests | At least 5 injection scenarios |

---

## Test Commands

```bash
# Run all tests
pytest

# Run specific category
pytest tests/unit/
pytest tests/integration/
pytest tests/synthetic_forms/
pytest tests/safety/
pytest tests/prompt_injection/

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test
pytest tests/unit/test_page_state.py -v
```

---

## Test Results Log

### Phase 0 — 2026-08-24

**Command:** `pytest tests/unit/ -v`
**Result:** 19 passed in 4.94s
**Notes:**
- Settings tests (3) pass
- Model tests (11) pass  
- Browser manager tests (5) pass

### Phase 1 — 2026-08-24

**Command:** `pytest tests/synthetic_forms/test_observer.py -v`
**Result:** 14 passed in 17.66s
**Notes:**
- Simple form: 5 tests (text inputs, required fields, dropdown, button, unique refs)
- Dropdown form: 2 tests (hidden elements, dependent dropdown)
- Checkboxes/radios: 2 tests (radios, checkboxes)
- Validation: 3 tests (errors detected, messages captured, invalid element)
- Multi-step: 2 tests (step 1 visible, step 2 after click)

### Phase 2 — 2026-08-24

**Command:** `pytest tests/integration/test_executor.py -v`
**Result:** 14 passed in 16.04s
**Notes:**
- Fill: 2 tests (text input, email)
- Click: 2 tests (button, multi-step navigation)
- Select: 2 tests (single dropdown, dependent dropdown)
- Check/uncheck: 2 tests (checkbox, radio button)
- Scroll, go_back, press, open: 4 tests
- Error handling: 2 tests (no value, nonexistent ref)

### Phase 3 + 3.5 — Verification Engine + Hardening — 2026-08-24

**Command:** `pytest tests/ -v`
**Result:** 128 passed in 102.28s

**Failure injection tests (Phase 3):**
- Fill: field disappears → detected ✅
- Fill: field becomes disabled → detected ✅
- Fill: validation error appears → detected ✅
- Fill: normal fill → verified success ✅
- Click: no-op button → UNCERTAIN (stops progression) ✅
- Click: new elements added → SUCCESS ✅
- Click: title changed → SUCCESS ✅
- Select: dependent field appears → SUCCESS ✅
- Select: invalid option → FAILURE ✅
- Re-observation after fill → post_observation returned ✅
- Re-observation after select → post_observation returned ✅

**Hardening tests (Phase 3.5):**
- Stale observation_id rejected ✅
- Correct observation_id accepted ✅
- ActionResult has post_observation ✅
- ActionResult has recovery_required, user_action_required ✅
- Upload requires document_ref (no raw paths) ✅
- Sensitive Aadhaar pattern rejected ✅
- Sensitive PAN pattern rejected ✅
- open action removed from schema ✅
- UNCERTAIN causes recovery_required=True ✅

### Phase 4 — User Vault — 2026-08-24

**Command:** `pytest tests/unit/test_vault.py -v`
**Result:** 34 passed in 0.41s

**Test coverage:**
- UserVault model (5 tests)
- Sensitivity classification (7 tests)
- ValueResolver (6 tests)
- DocumentResolver (4 tests)
- DocumentRegistry (3 tests)
- VaultManager (6 tests)
- Integration (3 tests)

### Phase 5 — OpenRouter LLM Gateway — 2026-08-24

**Command:** `pytest tests/unit/test_llm.py -v`
**Result:** 22 passed in 5.19s

**Test coverage:**
- LLMGateway protocol (3 tests): implements protocol, has complete, has close
- LLM schemas (3 tests): response defaults, usage, error hierarchy
- Retry policy (5 tests): timeout retry, rate limit retry, bad request no-retry, exhaustion, server error retry
- OpenRouter gateway (10 tests): success, schema, timeout, rate limit, server error, bad request, malformed, non-JSON, close, context manager
- Gateway+retry integration (1 test): retry then success

---

## Synthetic Test Pages

These are hosted locally during testing (served by FastAPI or Playwright file://):

| Page | Purpose | File |
|------|---------|------|
| Simple form | Basic text inputs + labels | `tests/synthetic_forms/pages/simple.html` |
| Dropdown form | Select + dependent select | `tests/synthetic_forms/pages/dropdowns.html` |
| Checkbox/radio | Toggle controls | `tests/synthetic_forms/pages/checks.html` |
| File upload | Upload input | `tests/synthetic_forms/pages/upload.html` |
| Multi-step | Wizard with Next/Back | `tests/synthetic_forms/pages/multistep.html` |
| Validation | Invalid states + error messages | `tests/synthetic_forms/pages/validation.html` |
| Failure (fill) | Disappearing field, disabled, validation | `tests/synthetic_forms/pages/failure_fill.html` |
| Failure (click) | No-op, alert, toggle, add elements | `tests/synthetic_forms/pages/failure_click.html` |
| Failure (select) | Dependent dropdowns, invalid option | `tests/synthetic_forms/pages/failure_select.html` |
| Field mapping | 20+ fields, similar labels, dependent dropdown | `tests/synthetic_forms/pages/field_mapping.html` |

### Phase 6 — Semantic Field Mapper — 2026-08-24

**Command:** `pytest tests/unit/test_field_mapper.py -v`
**Result:** 41 passed in 0.44s

**Test coverage:**
- Deterministic matching (19 tests): full_name, father, mother, spouse, parent, dob, gender, mobile, email, state, district, aadhaar, pan, income, category, qualification, village, pincode, address
- Document mapping (4 tests): aadhaar upload, income cert, photo, signature
- Confidence scoring (4 tests): high exact, medium partial, no match returns None, disabled skipped
- Evidence collection (3 tests): includes label, role, section
- Full pipeline (2 tests): deterministic only, correct binding structure
- LLM resolution (3 tests): called for ambiguous, graceful failure, no LLM skips
- Similar label discrimination (4 tests): all name variants distinct, address vs permanent, income vs bank, photo vs aadhaar
- Strategy counts (1 test): populated correctly

**Full suite:** 191 passed in 86.53s

