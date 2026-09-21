# Testing Guide

**Last updated:** 2026-09-21 (test-count audit; reconciled against actual pytest output)

---

## Authoritative Test Counts (audited 2026-09-21)

Exact commands and results (Python 3.14, Windows, local Chromium):

```
python -m pytest tests -q
→ 1093 passed, 12 skipped in 302.20s

python -m pytest tests/unit -q             → 733 passed
python -m pytest tests/integration -q      → 65 passed
python -m pytest tests/synthetic_forms -q  → 83 passed
python -m pytest tests/prompt_injection -q → 28 passed
python -m pytest tests/evaluation -q       → 36 passed
python -m pytest tests/enterprise -q       → 148 passed

Sum: 733 + 65 + 83 + 28 + 36 + 148 = 1093 (matches the full run; no double counting)
```

The 12 skips are the gated tests in `tests/real_sites/` (see below). Each
file is counted exactly once, in its own directory, even where its theme
belongs to another category (e.g. `tests/unit/test_prompt_injection.py`
counts as unit; the `test_live_*` files count as synthetic_forms).

> Historical note: this page previously documented "~457 tests" and
> "2 known failures" in `test_model_guardrails.py`. Both are stale
> Phase-1-era figures — the guardrail tests pass at current HEAD and the
> current totals are above. No CI is configured for this repository; all
> counts are local, dated executions.

---

## Test Suite Overview

```
tests/
├── unit/                      # Pure logic tests (733 collected)
│   ├── ... (50+ files, incl. test_live_validation.py, test_openrouter_*.py)
│
├── integration/               # Agent loop + executor with Playwright (65 tests)
│
├── synthetic_forms/           # Observer/verification/live-pipeline fixtures (83 tests)
│   ├── test_observer.py
│   ├── test_verification.py
│   ├── test_live_shadow_offline.py        (9)
│   ├── test_live_controlled_offline.py    (6)
│   └── test_live_controlled_matrix.py     (20)
│
├── prompt_injection/          # Dedicated injection suite (28 tests)
├── evaluation/                # Metrics/trace/acceptance incl. live artifacts (36 tests)
├── enterprise/                # Gateway/worker/queue/vault/audit (148 tests)
│
├── real_sites/                # GATED: 12 tests total, ALL skipped without env gates
│   ├── test_live_shadow.py        # 10 observation-only live tests (RUN_REAL_SITE_TESTS=true)
│   ├── test_openrouter_live.py    # 2 real-LLM tests (RUN_OPENROUTER_LIVE_TEST=true)
│   └── test_pmkisan_observe.py    # manual observation script (not pytest-collectable)
│
├── live_portal/               # Evidence artifacts only (report.json/trace.jsonl) — 0 tests
├── safety/                    # (stub — only __init__.py)
└── portal_regression/         # (stub — only __init__.py)
```

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

None at current HEAD (audited 2026-09-21: `python -m pytest tests -q` →
1093 passed, 12 gated skips, 0 failures).

### Resolved: `test_model_guardrails.py` — 2 failures (Phase-1 era)

| Test | Historical Failure Reason | Resolution |
|------|---------------------------|------------|
| `test_refusal_happens_before_browser_launch` | `.env` had `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true`, disabling the Z6 model guard | Fixed by resetting the flag to `false`; passes at current HEAD |
| `test_free_tier_env_model_also_refused` | Same root cause | Same fix; passes at current HEAD |

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

### Real Site Tests (`tests/real_sites/`) — GATED
Observation-only tests against real government portals. **All 12 are skipped
by default** (verified: `python -m pytest tests/real_sites -q` → 12 skipped):
- `test_live_shadow.py` — 10 tests; requires `RUN_REAL_SITE_TESTS=true`;
  a portal that cannot be reached yields PORTAL_UNAVAILABLE (an environment
  condition, recorded honestly — the test still passes or skips, never
  fabricates)
- `test_openrouter_live.py` — 2 tests; requires `RUN_OPENROUTER_LIVE_TEST=true`
  and a configured OpenRouter API key; skips cleanly when either is absent
- `test_pmkisan_observe.py` — manual Phase-1 observation script (not
  pytest-collectable)

### Stub Directories
- `tests/safety/` — placeholder (only `__init__.py`)
- `tests/portal_regression/` — placeholder (only `__init__.py`)

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
