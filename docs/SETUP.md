# Setup & Prerequisites

**Last updated:** 2026-09-18

---

## Pre-Implementation Checklist

Before writing any code, verify:

- [ ] Python 3.12+ installed
- [ ] pip / poetry / uv available
- [ ] Playwright can be installed (`pip install playwright`)
- [ ] Chromium can be installed (`playwright install chromium`)
- [ ] `.env` file created from `.env.example`
- [ ] OpenRouter API key available (for Phase 5+)
- [ ] Git repository initialized
- [ ] Tests can be run (`pytest`)

---

## Environment Variables

```env
# OpenRouter API
OPENROUTER_API_KEY=sk-...          # Never commit this
OPENROUTER_MODEL=...               # Configurable reasoning model
OPENROUTER_VISION_MODEL=...        # Configurable vision model
OPENROUTER_TIMEOUT_SECONDS=60

# Optional
OPENROUTER_FALLBACK_MODEL=...      # Fallback model when primary fails
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
LOG_LEVEL=INFO

# API auth — set a token to require `Authorization: Bearer <token>` on /api/*.
# Empty disables auth (localhost dev only). Required before any remote exposure.
API_TOKEN=

# Vault encryption at rest — passphrase for Fernet encryption of
# data/vault/user_vault.json. Strongly recommended before real data.
# Empty = plaintext (dev/test only).
VAULT_ENCRYPTION_KEY=

# Upload confinement — comma-separated dirs upload files must live under.
# Empty disables confinement.
DOCUMENT_ALLOWED_DIRS=

# Browser
# NOTE: BROWSER_MODE="user" forces a headed window and OVERRIDES HEADLESS —
# a HEADLESS=true setting is a no-op when user mode is on. Use BROWSER_MODE="test"
# for the headless behavior controlled by HEADLESS below.
HEADLESS=true
BROWSER_MODE=test
IGNORE_HTTPS_ERRORS=true

# Vision fallback (audit Z7 / P0-16) — screenshot-based perception when
# semantic DOM/ARIA extraction is insufficient.
VISION_FALLBACK_ENABLED=true

# Model guardrail (audit Z6) — refuse runs that would send real vault
# data through the anonymous default model. Set true only with informed consent.
ALLOW_ANONYMOUS_MODEL_WITH_VAULT=false
```

**Key security settings:**
- `VAULT_ENCRYPTION_KEY`: When set, vault PII at rest is encrypted with Fernet (scrypt key derivation). Without it, vault is plaintext JSON.
- `OPENROUTER_MODEL`: Must be pinned to a named provider for real PII (e.g. `anthropic/claude-sonnet-4-20250514`). Anonymous/free-tier models (`:free` suffix or `stealth/ox-alpha`) are refused when vault is populated, unless `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true`.
- `API_TOKEN`: Bearer token required on `/api/*` endpoints. Empty = no auth (localhost only).
- `BROWSER_MODE`: `"test"` (headless, automated) or `"user"` (headed, interactive). On Windows with `--reload`, use `"test"` to avoid SelectorEventLoop subprocess issues.

---

## Python Dependencies

### Core (always required)

| Package | Purpose |
|---------|---------|
| `playwright>=1.50.0,<2.0.0` | Browser automation (pinned per audit #3) |
| `pydantic>=2.0.0` | Typed models / schema validation |
| `pydantic-settings>=2.0.0` | Environment variable loading |
| `httpx>=0.27.0` | Async HTTP client (OpenRouter API) |
| `fastapi>=0.109.0` | Web API + frontend serving |
| `uvicorn[standard]>=0.27.0` | ASGI server |
| `python-dotenv>=1.0.0` | Environment variable loading |
| `cryptography>=42.0.0` | Fernet vault encryption at rest |

### Dev (testing)

| Package | Purpose |
|---------|---------|
| `pytest>=8.0.0` | Testing |
| `pytest-asyncio>=0.23.0` | Async test support |
| `pytest-cov>=4.1.0` | Coverage |
| `aiosqlite>=0.19.0` | Async SQLite |

---

## Project Bootstrap Commands

```bash
# Create virtual environment (Python 3.12+)
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # Linux/Mac

# Install dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium

# Create .env from .env.example
cp .env.example .env
# Edit .env to set your OpenRouter API key, model, etc.

# Verify
python --version
python -c "import playwright; print('Playwright OK')"
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop(); print('Browser OK')"
```

---

## Running the Application

```bash
# Start the server (no --reload on Windows due to Playwright event loop)
python run.py
# or: uvicorn app.main:app --host 127.0.0.1 --port 8000

# Then open http://127.0.0.1:8000/ in your browser
```

On Windows, **do not use `--reload` or `--watch`** — uvicorn uses `SelectorEventLoop` for reload mode, which doesn't support subprocesses (required by Playwright). On Linux/Mac, `--reload` is safe.

---

## Verification Gates

| Gate | Command | Expected Result |
|------|---------|----------------|
| Python starts | `python --version` | 3.12+ |
| Playwright launches Chromium | See bootstrap commands above | `Browser OK` |
| Local UI reachable | `python run.py` then `curl http://127.0.0.1:8000/health` | `{"status":"ok","service":"government-browser-agent"}` |
| Tests pass | `pytest` | All green (294+ tests) |
| No secrets in code | `grep -r "sk-" app/` | No matches |

---

## Current Project Structure

```
browser-agent/
├── app/
│   ├── main.py                    # FastAPI app entry point + frontend serving
│   ├── run.py                     # Server startup script (handles Windows event loop)
│   │
│   ├── api/
│   │   ├── routes.py              # Site registry + automation endpoints
│   │   └── vault_routes.py        # Vault CRUD API (names only, never values)
│   │
│   ├── config/
│   │   └── settings.py            # Settings (pydantic-settings, env vars)
│   │
│   ├── browser/
│   │   ├── manager.py             # BrowserManager — Playwright lifecycle + tab tracking
│   │   ├── observer.py           # PageObserver — page normalization
│   │   ├── aria.py               # ARIA snapshot extraction (mode="ai" introspected)
│   │   ├── dom.py                # DOM metadata extraction (JS in browser)
│   │   ├── locator.py            # LocatorResolver — frame-aware resolution
│   │   ├── executor.py           # BrowserExecutor — action execution + policy gate
│   │   ├── verification.py        # ActionVerifier dispatch
│   │   ├── verifiers/            # Per-action verifiers (8 modules)
│   │   │   ├── base.py
│   │   │   ├── click.py
│   │   │   ├── fill.py
│   │   │   ├── check.py
│   │   │   ├── select.py
│   │   │   ├── upload.py
│   │   │   ├── scroll.py
│   │   │   └── press.py
│   │   ├── vision.py              # CompletenessAssessment for vision fallback
│   │   └── tabs.py                # TabTracker — multi-tab state (Phase 8)
│   │
│   ├── agent/
│   │   ├── runner.py              # AgentRunner — full observe→plan→execute→verify loop
│   │   ├── planner.py             # LLM + deterministic planning
│   │   ├── planning_result.py     # Typed planning outcomes
│   │   ├── field_mapper.py        # FieldMapper — semantic field binding
│   │   ├── field_mapper_models.py # FieldBinding, MappingResult, enums
│   │   ├── registry.py            # ReferenceRegistry — canonical USER.*/DOC.* refs (38)
│   │   ├── stall_detector.py      # Repeated-action stall detection (Phase 9)
│   │   └── vision_fallback.py     # Vision fallback request trigger
│   │
│   ├── llm/
│   │   ├── base.py               # LLMGateway protocol
│   │   ├── openrouter.py         # OpenRouterGateway implementation
│   │   ├── schemas.py            # LLMResponse, LLMUsage, error types
│   │   ├── retry.py              # RetryPolicy (bounded, exponential backoff)
│   │   └── sanitizer.py          # PromptSanitizer (prompt injection defense)
│   │
│   ├── policy/
│   │   ├── engine.py             # PolicyEngine — R0-R4 risk classification
│   │   └── document_policy.py    # DocumentPolicy — upload file validation
│   │
│   ├── vault/
│   │   ├── resolver.py           # UserVault, DocumentRef, DocumentRegistry, ValueResolver
│   │   ├── sensitivity.py        # SensitivityLevel (derived from registry)
│   │   └── manager.py            # VaultManager — Fernet+scrypt encrypted persistence
│   │
│   ├── sites/
│   │   └── registry.py           # TrustedDomainRegistry — 15+ government domains
│   │
│   ├── models/
│   │   ├── page_state.py         # PageState, PageObservation, ElementState, etc.
│   │   ├── actions.py            # BrowserAction (typed action set)
│   │   └── workflow_state.py     # WorkflowState, WorkflowStatus, ActionRecord
│   │
│   ├── storage/
│   │   └── __init__.py           # (stub — SQLite persistence planned)
│   │
│   └── frontend/
│       ├── index.html           # Main UI with auto-panel + status reasons
│       └── automation.html       # Full-page automation monitor
│
├── data/
│   ├── vault/
│   │   ├── user_vault.json       # Real vault (gitignored, encrypted)
│   │   ├── user_vault.example.json  # Mock data template (35 fields)
│   │   └── README.md
│   └── site_registry.json       # (deprecated — registry now in code)
│
├── tests/
│   ├── unit/              # ~20+ unit test files
│   ├── integration/       # Executor + agent loop E2E (Playwright)
│   ├── synthetic_forms/   # Observer + verification tests
│   ├── safety/            # (stub — prompt injection tests planned)
│   ├── prompt_injection/  # (stub — prompt injection tests planned)
│   ├── portal_regression/ # (stub — portal regression tests planned)
│   └── real_sites/        # PM-KISAN observation-only test
│
├── .env.example           # Environment variable template
├── .gitignore
├── pyproject.toml
├── docs/                   # All documentation
└── README.md
```
