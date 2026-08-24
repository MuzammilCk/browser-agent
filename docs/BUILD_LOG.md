# 📋 Build Log — Implementation Chronicle

**Last updated:** 2026-08-24

---

### [Phase 0] Repository Bootstrap — 2026-08-24

**What was done:**
- Created Python project structure with pyproject.toml
- Set up .env.example, .gitignore, README.md
- Created FastAPI app with health endpoint and minimal UI
- Created Playwright browser manager (launch, open, screenshot, close)
- Created Pydantic models: BrowserAction, PageState, ElementState, etc.
- Created Settings system with pydantic-settings
- Created test infrastructure with 19 passing tests

**Tests:** 19 passed in 4.94s

---

### [Phase 1] Playwright Perception Engine — 2026-08-24

**What was done:**
- Implemented ARIA snapshot extraction (app/browser/aria.py)
- Implemented targeted DOM metadata extraction (app/browser/dom.py)
- Implemented PageObserver that produces PageObservation (PageState + ARIA + context)
- Split name fields: accessible_name, html_name, label_text
- Added context fields: section_heading, help_text, group_label, nearby_text
- Frame-aware element extraction
- Multi-signal auth detection with confidence scoring
- Created 5 synthetic test pages
- Wrote 14 integration tests

**Tests:** 14 passed in 17.66s

---

### [Phase 2] Deterministic Browser Executor — 2026-08-24

**What was done:**
- Implemented browser action executor (fill, click, select, check/uncheck, scroll, scroll_to, press, wait, go_back, upload)
- Implemented locator engine with priority hierarchy
- Implemented verification engine
- Pydantic validators enforce required fields per action type
- Removed 'open' from LLM action set
- Upload requires document_ref only
- Sensitive field policy blocks Aadhaar/PAN patterns

**Tests:** 47 passed in 38.62s

---

### [Phase 2+] Audit Fixes — 2026-08-24

**What was done:**
- Created PageObservation model wrapping PageState + ARIA snapshot + frame snapshots
- Removed broken snapshot_ref locator strategy
- Implemented ValueResolver (USER.full_name → actual value locally)
- Implemented DocumentResolver (DOCUMENT.aadhaar → file path locally)
- Wired ActionVerifier into executor core loop
- Added scroll_to(target_ref) semantic scrolling
- Added frame-aware element extraction

**Tests:** 77 passed in 75.83s

---

### [Phase 3 + 3.5] Verification Engine + Hardening — 2026-08-24

**What was done:**
- Enhanced ActionVerifier with live Playwright DOM queries for ground-truth verification
- Live value reading for fill verification
- Enhanced click verification (disabled state, content comparison)
- Enhanced select verification (dependent field detection)
- Upload verification targets exact element (not all file inputs)
- scroll_to verifies viewport via bounding rect
- Created 3 failure injection synthetic pages (fill, click, select)
- Wrote failure injection tests proving detection works

**Hardening (Phase 3.5):**
- UNCERTAIN verification now stops progression (recovery_required=True)
- ActionResult includes post_observation, recovery_required, user_action_required
- Observation-scoped refs with stale reference rejection
- Sensitive field policy blocks Aadhaar/PAN patterns in literal_value

**Tests:** 128 passed in 102.28s

---

### [Phase 4] User Vault + Document Registry — 2026-08-24

**What was done:**
- Created sensitivity classification module (PUBLIC/INTERNAL/SENSITIVE/SECRET)
- Created vault manager for JSON persistence (load/save)
- Created sample vault with realistic Indian government form data
- Wrote 34 comprehensive tests (vault, resolvers, classification, manager, integration)

**Tests:** 34 passed in 0.41s (Phase 4), 128 total

### [Phase 5] OpenRouter LLM Gateway — 2026-08-24

**What was done:**
- Created LLMGateway protocol (app/llm/base.py)
- Created OpenRouterGateway implementation (app/llm/openrouter.py)
- Created LLM request/response schemas and error hierarchy (app/llm/schemas.py)
- Created bounded retry policy with exponential backoff (app/llm/retry.py)
- Wrote 22 tests (protocol, schemas, retry, gateway, integration)

**Files created:**
- `app/llm/base.py` — LLMGateway protocol
- `app/llm/openrouter.py` — OpenRouter API gateway
- `app/llm/schemas.py` — LLMResponse, LLMUsage, error types
- `app/llm/retry.py` — RetryPolicy with bounded retries
- `tests/unit/test_llm.py` — 22 tests

**Tests run:**
- `python -m pytest tests/ -v` — 150 passed in 92.81s

**Verification:**
- LLMGateway protocol satisfied ✅
- Successful completion with parsed JSON ✅
- Structured output with schema ✅
- Timeout → LLMError ✅
- Rate limit (429) → LLMError ✅
- Server error (5xx) → LLMError ✅
- Bad request (400) → LLMError (no retry) ✅
- Malformed response → LLMMalformedResponseError ✅
- Retry exhaustion → LLMError ✅
- Retry then success → recovered ✅
- Non-JSON content → raw string ✅
- Close cleans up ✅
- Context manager works ✅
