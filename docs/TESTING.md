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

### Full Suite — 2026-08-24 (post-audit fixes)

**Command:** `pytest tests/ -v`
**Result:** 77 passed in 75.83s

**New tests added:**
- `tests/unit/test_resolvers.py` — 15 tests for ValueResolver + DocumentResolver + DocumentRegistry
- `tests/integration/test_executor.py` — Added action validation tests, scroll_to test, fill_no_value validation test
- `tests/unit/test_models.py` — Added split name tests, context fields, PageObservation, action validation tests
- `tests/synthetic_forms/test_observer.py` — Added ARIA snapshot test, split name fields test, context fields test

### Phase 3 — Verification Engine — 2026-08-24

**Command:** `pytest tests/synthetic_forms/test_verification.py -v`
**Result:** 13 passed in 46.35s

**Failure injection tests:**
- Fill: field disappears → detected ✅
- Fill: field becomes disabled → detected ✅
- Fill: validation error appears → detected ✅
- Fill: normal fill → verified success ✅
- Click: no-op button → UNCERTAIN ✅
- Click: new elements added → SUCCESS ✅
- Click: title changed → SUCCESS ✅
- Click: element toggled → SUCCESS/UNCERTAIN ✅
- Select: dependent field appears → SUCCESS ✅
- Select: invalid option → FAILURE ✅
- Select: triggers new text field → SUCCESS ✅
- Re-observation after fill → verified ✅
- Re-observation after select → verified ✅

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
| Iframe | Content in iframe | *(Phase 1+)* |
| Dynamic | Fields that appear/change | *(Phase 1+)* |
