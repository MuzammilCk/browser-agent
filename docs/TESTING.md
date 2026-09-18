# Testing Guide

**Last updated:** 2026-09-18

---

## Test Suite Overview

```
tests/
├── unit/                      # Pure logic tests (~416 tests)
│   ├── test_aria.py
│   ├── test_vault.py
│   ├── test_vault_crypto_and_docpolicy.py
│   ├── test_vault_api.py
│   ├── test_settings.py
│   ├── test_policy.py
│   ├── test_document_policy.py
│   ├── test_planner_deterministic.py
│   ├── test_model_guardrails.py     ← 2 known failures (see below)
│   ├── test_prompt_injection.py
│   ├── test_llm.py
│   ├── test_resolvers.py
│   ├── test_registry.py
│   ├── test_stall_detector.py
│   ├── test_tabs.py
│   ├── test_field_mapper.py
│   ├── test_confirmation_flow.py
│   ├── test_element_ranking.py
│   ├── test_browser_manager.py
│   ├── test_auth_detection.py
│   ├── test_runner.py
│   ├── test_live_fixes.py
│   ├── test_task_instructions.py
│   ├── test_plan_outcome.py
│   ├── test_vision.py
│   ├── test_vision_fallback_wiring.py
│   ├── test_api_automate.py
│
├── integration/               # Agent loop + executor with Playwright (~27 tests)
│   ├── test_executor.py
│   ├── test_e2e_loop.py
│   ├── test_multi_tab.py
│
├── synthetic_forms/           # Observer + verification tests (~14 tests)
│   ├── test_observer.py
│   ├── test_verification.py
│
├── real_sites/                # Observation-only tests
│   ├── test_pmkisan_observe.py    # PM-KISAN login page (no data submission)
│
├── safety/                    # (stub — prompt injection tests planned)
├── prompt_injection/          # (stub — dedicated tests planned)
└── portal_regression/         # (stub — portal regression tests planned)
```

**Total: ~457 tests** across unit, integration, synthetic_forms, and real_sites.
**safety/, prompt_injection/, portal_regression/** are stubs with only `__init__.py` — test scaffolding exists but actual test files are not yet written.

---

## Running Tests

### All tests (excluding integration/real_sites which require Playwright):

```bash
python -m pytest tests/unit/ tests/integration/ tests/synthetic_forms/ tests/real_sites/ -q
```

### Unit tests only (fastest):

```bash
cd D:\projects\browser-agent
.venv\Scripts\activate
python -m pytest tests/unit/ -q
```

### Integration tests (require Playwright + Chromium):

```bash
python -m pytest tests/integration/ -q
```

### Synthetic form tests:

```bash
python -m pytest tests/synthetic_forms/ -q
```

### Real sites (observation-only, requires internet):

```bash
python -m pytest tests/real_sites/ -q
```

### Single test file:

```bash
python -m pytest tests/unit/test_policy.py -v
```

### Single test:

```bash
python -m pytest tests/unit/test_model_guardrails.py::TestFreeTierRefusal::test_free_tier_model_refused -v
```

### With coverage:

```bash
python -m pytest tests/unit/ --cov=app --cov-report=term-missing -q
```

---

## Known Failures

### `test_model_guardrails.py` — 2 failures

| Test | Failure Reason |
|------|---------------|
| `test_refusal_happens_before_browser_launch` | `.env` has an expired/invalid OpenRouter API key. The test expects a refusal before browser launch, but since the model returns 401, the flow falls into `waiting_for_user` state instead of `failed`. This is **expected behavior with a real API key** — the test should pass in CI with a mock or valid key. |
| `test_free_tier_env_model_also_refused` | Same root cause — API key 401 cascades into different error path. |

**Not a code defect** — these tests require a valid OpenRouter API key (or mocking in CI).

---

## Test Categories Explained

### Unit Tests (`tests/unit/`)
Pure logic tests that don't launch a browser. Covers:
- Vault encryption/decryption (Fernet + scrypt)
- Policy engine risk classification (R0-R4)
- Document policy (file validation, confinement)
- Model guardrails (free-tier refusal, anonymous model checks)
- Prompt injection sanitization
- Registry (USER.* / DOCUMENT.* references)
- Stall detection (repeated-action detection)
- Tab tracker logic
- Field mapper (semantic field binding)
- LLM gateway (retry, error mapping)
- Authentication detection from ARIA snapshots
- Planning outcome types

### Integration Tests (`tests/integration/`)
End-to-end agent loop tests using Playwright:
- `test_executor.py` — BrowserExecutor action execution + verification
- `test_e2e_loop.py` — Full observe→map→plan→policy→execute→verify loop
- `test_multi_tab.py` — Multi-tab state tracking

### Synthetic Form Tests (`tests/synthetic_forms/`)
Tests using synthetic HTML forms (no real government portals):
- `test_observer.py` — ARIA snapshot + DOM extraction
- `test_verification.py` — Per-action verification (click, fill, check, select, scroll, press)

### Real Site Tests (`tests/real_sites/`)
Observation-only tests against real government portals:
- `test_pmkisan_observe.py` — PM-KISAN login page observation (no form submission)

### Stub Directories
- `tests/safety/` — Placeholder for security hardening tests
- `tests/prompt_injection/` — Placeholder for dedicated prompt injection tests (some tests exist in `tests/unit/test_prompt_injection.py`)
- `tests/portal_regression/` — Placeholder for cross-portal consistency tests

---

## Verification Commands

| Check | Command |
|-------|---------|
| Unit tests pass | `pytest tests/unit/ -q` |
| Integration tests pass | `pytest tests/integration/ -q` |
| Synthetic forms pass | `pytest tests/synthetic_forms/ -q` |
| Real sites observe OK | `pytest tests/real_sites/ -q` |
| No secrets in code | `grep -r "sk-" app/` — must return nothing |
| Vault encryption works | `pytest tests/unit/test_vault_crypto_and_docpolicy.py -q` |
| Policy engine works | `pytest tests/unit/test_policy.py -q` |
