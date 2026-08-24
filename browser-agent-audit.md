# Browser Agent — Form-Filling & Browser Automation Audit

**Repo:** github.com/MuzammilCk/browser-agent
**Commit audited:** `b5bf64d` — "feat: comprehensive Indian government portal registry + redesigned frontend" (latest on `main` as of Aug 24, 2026)
**Method:** Full clone, dependency install, live Playwright/Chromium execution, full test suite run, line-by-line reading of every module in `app/agent/`, `app/browser/`, `app/vault/`, `app/policy/`, `app/models/actions.py`, `app/sites/`, `app/api/`, `app/frontend/`. Findings below are traced to exact files/lines and, where relevant, reproduced live — this is not a docs-only review.
**Scope:** Form-filling pipeline (field mapping → vault resolution → policy gating) and browser automation (perception → locate → execute → verify). API/frontend and LLM layers are covered only where they intersect these two.

---

## 1. Test baseline

```
327 passed, 1 failed in 67.4s   (328 tests total)
```

The one failure is real and is Finding B1 below — not a flaky test. Everything else genuinely passes against a live headless Chromium instance I installed in the sandbox (not mocked).

---

## 2. Executive summary

The core engine is well-architected and mostly does what its own docs claim: one atomic browser action per loop iteration, deterministic-first field mapping with LLM fallback only for ambiguity, PII kept out of LLM prompts via reference indirection (`USER.full_name` instead of raw values), and a policy engine that classifies every action by risk before it runs. Since my last look at this repo, the team shipped a large refactor (verifiers split into one-file-per-action-type, a dedicated `planner.py`, a regex-based prompt-injection sanitizer) that measurably improved code organization and closed some gaps.

But four things below are load-bearing enough to call out before this touches a real government site with real Aadhaar/PAN data:

1. **The confirmation checkpoint for sensitive/high-risk actions still doesn't stop execution.** It sets a status flag and proceeds anyway — in both places that check it.
2. **Verification of filled data silently skips the exact case that matters most** — fields filled via the vault (`value_ref`), which is the sensitive-data path, aren't checked against the live DOM at all; only the low-stakes `literal_value` path is.
3. **The vault (Aadhaar, PAN, bank account, IFSC) is stored as plaintext JSON on disk.** Nothing in the system sends this to an LLM, but nothing protects it at rest either.
4. **The default LLM is now an anonymous, free, ~1-week "stealth preview" model** with a contested data-retention policy, per public reporting — a meaningfully different trust profile for a tool whose entire premise is careful PII handling.

None of these are exotic to find — #1 and #2 are visible from reading two adjacent functions; #3 and #4 are one grep and one search away. They're not called out anywhere in the project's own `SAFETY.md` or `MILESTONES.md`, which is the main reason to write them down now.

---

## PART A — Browser Automation Layer

### A1. Perception (`app/browser/dom.py`, `observer.py`, `aria.py`)

**Architecture:** `PageObserver.observe(page)` runs a hand-written JS accessibility-tree walk (`dom.py`, `page.evaluate()`) to build the structured `ElementState` list that everything downstream (mapping, policy, execution, verification) actually acts on. This is solid and version-independent — it doesn't lean on any particular Playwright API surface.

**Finding B1 — `aria_snapshot()` always fails silently (confirmed, still present).**
`app/browser/aria.py` calls:
```python
snapshot = await body.aria_snapshot(mode="ai", refs=True)   # extract_aria_snapshot_with_refs
```
The installed Playwright (1.56.0, satisfies the `>=1.50.0,<2.0.0` pin in `pyproject.toml`) only accepts `timeout`:
```
TypeError: Locator.aria_snapshot() got an unexpected keyword argument 'mode'
```
Both the primary call and its `TypeError` fallback (which still passes `mode="ai"`) fail, get caught by a broad `except Exception`, and `PageObservation.aria_snapshot` is silently `""` on every single page load. I reproduced this directly outside pytest too — real accessibility tree in, empty string out.

**Practical impact — smaller than it looks, but not zero:**
- `ElementState` extraction (the thing that actually drives the agent) doesn't touch this field, confirmed by grep — so mapping, policy, execution, and locator resolution are unaffected.
- It **is** read in `app/browser/vision.py:86` as one completeness signal (`thin_aria_snapshot` fires whenever `len(aria_snapshot) < 50`) — which, since it's always `""`, now fires on *every* page, nudging the vision-fallback trigger logic slightly more often than intended. It's one signal among several, not a sole trigger, so this degrades rather than breaks that subsystem.
- It's also the one field the LLM prompt in `planner.py` does *not* include (only the structured `elements_info`/`bindings_info` JSON is sent) — so this bug currently costs "thin_aria_snapshot" noise and nothing else, not reasoning quality.

**Fix is mechanical:** introspect `inspect.signature(locator.aria_snapshot)` once and only pass kwargs the installed driver actually accepts, instead of hardcoding a `mode="ai"` call and one fixed fallback. I wrote and verified this fix locally (not pushed) — happy to hand it over.

### A2. Locating elements (`app/browser/locator.py`)

Layered strategy: resolve by `ref` → verify against current `PageState` (rejects refs from a stale/different observation) → fall back through role+name, `label`, `placeholder`, CSS-ish heuristics. This general "try progressively looser strategies, but always validate against the *current* structured state first" shape is the right one for an environment where the DOM can shift between observation and action. No issues found here beyond what's noted in A4 below.

### A3. Execution (`app/browser/executor.py`)

**Finding B2 — Confirmation-required actions execute anyway. Confirmed present on the current commit, in two places, after a full runner rewrite.**

`policy/engine.py` classifies every action `ALLOW / DENY / REQUIRE_CONFIRMATION / PAUSE_FOR_USER`. Aadhaar/PAN/DOB fills → `SENSITIVE`; payment and final-submission clicks → `HIGH_RISK`; both map to `REQUIRE_CONFIRMATION`. `SAFETY.md`'s own R2/R4 rules describe this as a hard gate ("Mandatory explicit confirmation immediately before action").

In `app/agent/runner.py`, the current (post-refactor) policy check is:
```python
def _check_policy(self, workflow: WorkflowState, policy_result) -> bool:
    if policy_result.blocked:            # DENY
        ...
        return True                       # halts — correct
    if policy_result.needs_user:          # PAUSE_FOR_USER (CAPTCHA/OTP/password)
        ...
        return True                       # halts — correct
    if policy_result.needs_confirmation:  # SENSITIVE / HIGH_RISK
        workflow.status = WorkflowStatus.READY_FOR_CONFIRMATION
    return False                          # <-- does NOT halt
```
Returning `False` means `_run_iteration` proceeds straight to step 6 (EXECUTE) regardless. `DENY` and `PAUSE_FOR_USER` correctly stop the loop; `REQUIRE_CONFIRMATION` sets a status label and runs the action anyway. This is the same behavior the pre-refactor code had (previously spelled out with a `# For now, proceed — Phase C confirmation UI comes later` comment) — the November refactor reorganized the code without closing the gap.

`app/browser/executor.py` has its own, independent copy of this same check (defense-in-depth, since `BrowserExecutor.execute()` can be called directly without going through the runner):
```python
if policy_result.needs_confirmation:
    logger.warning("Policy REQUIRE_CONFIRMATION: %s — proceeding for now", ...)
    # falls through to _do_execute() anyway
```
Same bug, independently.

**I proved this isn't theoretical, not just a code-reading exercise.** `tests/integration/test_executor.py::TestClickAction::test_click_button` clicks the only button on the synthetic test form, labeled *"Submit Application."* `"submit"` is a `SUBMISSION_KEYWORDS` entry, so this click is classified `HIGH_RISK` → `REQUIRE_CONFIRMATION` by the engine's own rules — and the test passes today only because the confirmation gate is a no-op. The green test suite is currently masking the exact gap it should be catching.

**Secondary bug from the same root cause:** `workflow.status` is set to `READY_FOR_CONFIRMATION` but nothing ever sets it back. If the auto-executed action succeeds, the loop continues normally while the status field keeps reporting "ready for confirmation" — a stale, misleading status for the rest of the run.

**What a real fix needs (I built and locally verified this before switching to the audit — not yet pushed):**
- Both check sites must actually halt (`break`/`return`) instead of falling through.
- The specific pending action needs to be held somewhere (`WorkflowState.pending_action`) so a caller can present it and resume — not re-derived from scratch, since re-planning after a pause could produce a *different* action than the one the user was shown.
- A `resume(page, workflow, approved: bool)` path that re-observes before replaying (never trust a paused snapshot), and — if declined — stops cleanly rather than guessing what to do next.

### A4. Verification (`app/browser/verifiers/*`, refactored since last review)

Good structural change: one file per action type (`fill.py`, `click.py`, `select.py`, `check.py`, `scroll.py`, `upload.py`) behind a small dispatch table in `verification.py`, each under 100 lines. `click.py`'s change-detection (URL/title/page_type/element-count/alerts/validation-errors/element-state/content-diff, in that order, `UNCERTAIN` if nothing matches) is a sensible, well-thought-out cascade.

**Finding B3 — `verify_fill()` doesn't check the value for the sensitive-data path (new finding, not previously documented anywhere in the repo).**

```python
# app/browser/verifiers/fill.py
expected_value = action.literal_value or ""
if expected_value:
    live_value = await _read_live_value(page, ref, target)
    if live_value is not None and live_value.strip() != expected_value.strip():
        return make_failure(...)
```

The system's own design (stated directly in `planner.py`'s LLM system prompt: *"Use value_ref... for sensitive fields. Use literal_value only for non-sensitive PUBLIC fields"*) means the highest-stakes fills — name, DOB, Aadhaar, PAN, bank details, all resolved through the vault via `value_ref` — arrive here with `action.literal_value == None`. `expected_value` is then `""`, the `if expected_value:` guard is false, and the live-DOM-value check is **skipped entirely** for exactly the fills that most need it. I traced this all the way through: `executor.py::_execute_fill()` resolves `value_ref` to a real string via `VaultResolver` and fills the field with it, but that resolved value is a local variable — it's never attached back to the `ActionResult` or threaded into the `verify()` call, which receives the original, unmodified `action` object.

What still runs for a `value_ref` fill: element-still-present, not-disabled, no new validation errors, no new alerts. That's a reasonable proxy but not the same guarantee as "the Aadhaar field now contains the Aadhaar number" — e.g. a masked/formatted input that silently truncated or reformatted the value would sail through as `SUCCESS`.

**Fix shape:** thread the resolved value back (e.g. `ActionResult.resolved_value`, set in `_execute_fill`, consumed by `verify_fill` in place of `action.literal_value`) so both fill paths get the same live-value check. The resolved value shouldn't go in logs or `ActionRecord.message` — just passed through this one call.

**Finding B4 — Two action types skip verification by default, and one of them looks like the wrong default.**
`_VERIFIERS` in `verification.py` covers `fill/click/select/check/uncheck/upload/scroll_to`. Not covered → auto-`SUCCESS`, "no verification needed": `press`, `wait`, `go_back`, `request_user_action`, `finish_review`, `stop`. `wait`/`stop`/`request_user_action`/`finish_review` are genuinely non-mutating control actions, so skipping them is fine. `press` and `go_back` are questionable: pressing Enter inside a form field can submit it, and `go_back` changes the URL and can discard unsaved form state — both are exactly the kind of state change the verification layer exists to catch, and today both get a free pass.

### A5. Browser session & trust boundary (`app/browser/manager.py`, `app/sites/registry.py`)

**Finding B5 — the (now very large) trusted-domain registry isn't wired to anything that enforces it.**

`app/sites/registry.py` grew by **1,323 lines** in the latest commit into a genuinely comprehensive `TrustedDomainRegistry` — dozens of vetted `.gov.in` domains across central/state/district levels, each with per-task metadata (`requires_auth`, `requires_payment`, difficulty). Good, serious work. But:

```python
$ grep -rn "TrustedDomainRegistry" app/ --include="*.py"
app/api/routes.py: ...          # read-only /api/sites, /api/search, /api/site/{domain}
app/sites/registry.py: ...      # the class itself
```

That's the complete list. It's used exactly once, to power the new frontend's site directory/search — never in `policy/engine.py`, never in `browser/executor.py`, never in `agent/runner.py`. Most directly: `BrowserManager.open(url)` navigates to whatever URL it's given —
```python
async def open(self, url: str) -> Page:
    await self.page.goto(url, wait_until="domcontentloaded")
```
— with no check against the registry at all. Nothing currently stops the agent from being pointed at, and starting to fill forms on, a domain that isn't in the (extensive) vetted list. The registry is a real asset sitting one function call away from being an actual access-control gate and currently isn't one.

---

## PART B — Form-Filling Pipeline

### B1. Reference registry & field mapping (`app/agent/registry.py`, `field_mapper.py`)

This is the strongest part of the codebase. `ReferenceRegistry` is a genuine single source of truth for every valid `USER.*`/`DOCUMENT.*` reference — the field mapper and the LLM planner both validate bindings against it, so a hallucinated reference like `USER.social_security_number` (not a real field) gets rejected rather than silently mishandled. `FieldMapper.map_fields()` runs cheap deterministic keyword/pattern matching first (label text, `name`/`id` attributes, `aria-label`, input type/pattern) and only escalates genuinely ambiguous or unmatched fields to the LLM, with the LLM's binding re-validated against the registry before it's trusted. This tiered design is the correct shape for cost, latency, and — more importantly — for keeping the LLM out of the loop on fields that don't need judgment calls.

**Since my last review:** `field_mapper.py` now also sends candidate field info through `PromptSanitizer.sanitize_elements()` before it reaches the LLM disambiguation prompt — consistent with the same sanitizer `planner.py` uses. Good, and correctly applied at both LLM call sites, not just one.

### B2. Sensitivity classification (`app/vault/sensitivity.py`)

Classifies every `USER.*`/`DOCUMENT.*` field into `PUBLIC / PII / SENSITIVE / CRITICAL` tiers (e.g. name/city → `PUBLIC`; Aadhaar/PAN/bank account → `SENSITIVE`/`CRITICAL`), and this tiering is what `policy/engine.py` keys off of to decide `REQUIRE_CONFIRMATION`. Straightforward, does what it says, no issues found.

### B3. Vault storage — data at rest (`app/vault/manager.py`, `resolver.py`)

The in-flight protection is real: raw values never appear in LLM prompts, only `USER.field_name`-style references do, and `VaultResolver` resolves them locally inside the executor.

**Finding B6 — but the vault itself is plaintext JSON on disk (new finding).**
```python
# app/vault/manager.py
def save_vault(self, vault: UserVault | None = None) -> None:
    vault_path = self.vault_dir / "user_vault.json"
    vault_path.write_text(vault.model_dump_json(indent=2), encoding="utf-8")
```
`data/vault/user_vault.json` holds full name, DOB, Aadhaar number, PAN number, bank account number, IFSC code — unencrypted, in a directory with no special permissions set (`vault_dir.mkdir(parents=True, exist_ok=True)`, no `chmod`). The careful work keeping this data away from the LLM doesn't extend to protecting the file itself — anything with filesystem access (another process, a backup job, a misconfigured sync tool) reads it in the clear. Worth deciding deliberately (OS keychain, `Fernet`/age-style encryption with a passphrase, or at minimum restrictive file permissions + an explicit README warning) rather than by omission, especially before any real Aadhaar data goes anywhere near it.

Minor, related: `VaultManager.create_sample_vault()` seeds a complete, realistic-looking Indian identity (name, Aadhaar-shaped number, PAN-shaped number, bank details) for dev/testing convenience. Fine as a fixture; worth a one-line comment making clear it's synthetic, since it's easy to mistake for real data six months from now.

### B4. Document upload policy (`app/policy/document_policy.py`)

Checks extension against an allow-list per document type, file size against per-type limits, and a resolved-path containment check before allowing an upload to proceed to the executor.

**Finding B7 — the module documents MIME validation as a feature; it isn't actually enforced (new finding).**
The docstring says *"MIME type validation"* and `ALLOWED_MIMES` is fully populated per document type (`{"aadhaar": ["application/pdf", "image/jpeg", "image/png"], ...}`) — but `validate_upload()` never reads `self.allowed_mimes` anywhere in its body. Only the file **extension** is checked, which is trivially spoofable (rename `payload.exe` to `payload.pdf` and the extension check passes). This is dead configuration, not a logic bug — the dict is right there, just never consulted. A real fix needs actual content sniffing (magic bytes via `python-magic` or `filetype`, not just `Content-Type`/extension) since extension and reported MIME are both attacker-controlled.

Lower-severity, same file: the path-containment check (`str(resolved).startswith(str(path.parent.resolve()))`) has the classic string-prefix pitfall — a sibling directory like `uploads_evil/` would satisfy `startswith("uploads")` — but since `file_path` here comes from `DocumentRef` resolution (not directly from web/LLM-controlled input), the practical exploitability is low. Flagging for completeness, not urgency.

### B5. Action schema validation (`app/models/actions.py`)

`BrowserAction` uses Pydantic field validators to enforce, at construction time, things like "upload requires `document_ref`", "select requires `option`", and — notably — a regex rejecting Aadhaar/PAN-shaped strings from ever being placed in `literal_value` (forcing that data through `value_ref` instead). This is a good belt-and-suspenders check: even if an LLM or a bug tried to put a raw PAN number in a "public" field, construction fails before it reaches the executor. No issues found here.

---

## 3. Cross-cutting: what changed at the product layer, and one config choice worth a second look

**API/frontend (`app/api/routes.py`, `app/frontend/index.html`, both new).** The new frontend is a legitimately well-built directory/search UI over the site registry (categories, per-state filtering, full-text search, site detail modals) — a real, working piece of software. But the button that matters, "Start Automation," is:
```javascript
function startAutomation(domain) {
    closeModal();
    alert(`Automation for ${domain} - coming soon!`);
}
```
`AgentRunner`, `BrowserExecutor`, and `BrowserManager` are not imported anywhere in `app/main.py` or `app/api/routes.py`. The engine audited above is real and mostly sound; it still isn't reachable from the UI. Worth naming plainly since a lot of the latest work (1,323 lines of registry data, 1,008-line frontend) went into the discovery layer around the hard problem rather than into closing the last mile to it.

**Default LLM (`app/config/settings.py`).** Both `openrouter_model` and `openrouter_vision_model` now default to `stealth/ox-alpha`:
```python
openrouter_model: str = Field(default="stealth/ox-alpha", ...)
openrouter_vision_model: str = Field(default="stealth/ox-alpha", ...)
```
Checking what this actually is: it's a free, anonymous "stealth" model that appeared on OpenRouter around August 20, 2026, with its developer undisclosed and, per multiple outlets covering the release, an unresolved public question about whether/how prompts are retained by the anonymous operator — one report specifically frames this as a live, contested issue rather than a settled one. Separately, "stealth" listings on OpenRouter are explicitly temporary preview arrangements (this one's free window is reported as roughly one week from its Aug 20 launch), so this default is also likely to stop resolving or silently swap providers within days regardless of the privacy question. For a tool whose central design goal is careful handling of government-ID data, defaulting to an anonymous provider with an open data-retention question is worth an explicit, documented decision rather than an unstated one — even though, per the sanitizer/reference-indirection design above, raw Aadhaar/PAN values shouldn't reach the LLM either way. This is a config default worth deliberately pinning to a named, accountable provider before this goes anywhere near real user data, not a code bug.

---

## 4. Findings summary

| ID | Area | Finding | Status | Severity |
|----|------|---------|--------|----------|
| B1 | Browser automation | `aria_snapshot(mode="ai")` throws on installed Playwright; snapshot always empty | Confirmed, reproduced live | Low (contained blast radius) |
| B2 | Browser automation | `REQUIRE_CONFIRMATION` actions execute without pausing, in both runner.py and executor.py | Confirmed on latest commit, post-refactor | **High** — safety-critical |
| B3 | Browser automation | `verify_fill()` skips live-value check for `value_ref` (vault/sensitive) fills | New finding | **High** — data-integrity |
| B4 | Browser automation | `press` and `go_back` skip verification by default | New finding | Medium |
| B5 | Browser automation | `TrustedDomainRegistry` (1,300+ lines) not enforced anywhere in the execution path | Confirmed, exact chokepoint identified | Medium–High |
| B6 | Form filling | Vault (Aadhaar/PAN/bank data) stored as plaintext JSON at rest | New finding | Medium–High |
| B7 | Form filling | `DocumentPolicy` MIME validation is configured but never enforced; extension-only check is spoofable | New finding | Medium |
| — | Product | "Start Automation" is a stub `alert()`; engine not reachable from any UI/API | Confirmed | Blocks real usage |
| — | Config | Default LLM is an anonymous, temporary "stealth" model with a contested retention policy | Confirmed via current reporting | Worth a deliberate decision |

## 5. Suggested order of attack

1. **B2** (confirmation gate) — this is the one place where "the code doesn't match the safety doc" translates directly into an unattended sensitive/financial action.
2. **B3** (fill verification) — cheap, mechanical fix (thread the resolved value through), closes a real correctness gap on the sensitive-data path specifically.
3. **B5** (trusted-domain enforcement) — the data already exists; this is wiring one check into `BrowserManager.open()` or the policy engine, not new research.
4. **B6** (vault at rest) — a deliberate encryption-at-rest decision before this handles real Aadhaar/PAN data.
5. B1, B4, B7, and the LLM default are all real but lower-urgency — good next-PR-sized items.
6. The API/frontend gap isn't a bug so much as a scoping decision: the engine is close to demo-able once #1–3 are addressed; wiring `AgentRunner` behind a couple of endpoints (start / poll status / confirm-pending-action) is the remaining path to an actual working demo.

---

*I have working, tested fixes ready for B1, B2 (including the resume-after-confirmation flow), and B3 from earlier in this session — not yet applied to this checkout. Say the word and I'll apply and verify them against this exact commit.*
