# 🔧 Setup & Prerequisites

**Last updated:** 2024-08-24

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
# Required from Phase 0
OPENROUTER_API_KEY=sk-...          # Never commit this
OPENROUTER_MODEL=...               # Configurable reasoning model
OPENROUTER_VISION_MODEL=...        # Configurable vision model
OPENROUTER_TIMEOUT_SECONDS=60

# Optional
OPENROUTER_FALLBACK_MODEL=...      # Fallback model
DATABASE_URL=sqlite:///./data/app.db
LOG_LEVEL=INFO
```

---

## Python Dependencies

### Phase 0 (Foundation)

| Package | Purpose |
|---------|---------|
| `playwright` | Browser automation |
| `pydantic` | Typed models / schema validation |
| `httpx` | Async HTTP client (OpenRouter) |
| `fastapi` | Local web UI |
| `uvicorn` | ASGI server |
| `python-dotenv` | Environment variable loading |
| `pytest` | Testing |
| `pytest-asyncio` | Async test support |

### Later Phases (as needed)

| Package | Purpose | Phase |
|---------|---------|-------|
| `aiosqlite` | Async SQLite | Phase 4+ |
| `jinja2` | HTML templates | Phase 0+ (FastAPI UI) |

---

## Project Bootstrap Commands

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install playwright pydantic httpx fastapi uvicorn python-dotenv pytest pytest-asyncio

# Install Playwright browsers
playwright install chromium

# Verify
python -c "import playwright; print('Playwright OK')"
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); b.close(); p.stop(); print('Browser OK')"
```

---

## Verification Gates

| Gate | Command | Expected Result |
|------|---------|----------------|
| Python starts | `python --version` | 3.12+ |
| Playwright launches Chromium | See bootstrap commands above | `Browser OK` |
| Local UI reachable | `uvicorn app.main:app --reload` | Server starts on :8000 |
| Tests pass | `pytest` | All green |
| No secrets in code | `grep -r "sk-" app/` | No matches |

---

## File Structure After Setup

```
government-browser-agent/
├── .env                    # Secrets (gitignored)
├── .env.example            # Template
├── .gitignore
├── pyproject.toml          # Project config
├── docs/                   # All documentation
│   ├── README.md
│   ├── context.md
│   ├── government_browser_agent_openrouter_architecture.md
│   ├── SETUP.md
│   ├── MILESTONES.md
│   ├── BUILD_LOG.md
│   ├── ARCHITECTURE.md
│   ├── SAFETY.md
│   ├── PORTALS.md
│   └── TESTING.md
├── app/                    # Application code
│   └── main.py
├── tests/                  # Test suite
│   └── ...
└── data/                   # Runtime data (gitignored)
    └── .gitkeep
```
