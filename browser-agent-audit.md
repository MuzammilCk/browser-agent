# Browser Agent — Full Audit (Form-Filling & Browser Automation)

> **REMEDIATION STATUS (Aug 25, 2026):** All findings below marked with a fix
> ID have been remediated and verified by the full test suite (**374 passed,
> 0 failed**) plus a live end-to-end confirmation-flow smoke test against real
> Chromium. See "Remediation log" at the bottom of this document.

**Repo:** github.com/MuzammilCk/browser-agent
**Commit audited:** `71d2043` — "feat: enhance task instructions, Windows event loop handling, and runner entrypoint" (latest on `main` as of Aug 25, 2026)
**Method:** Full local checkout, dependency install (Playwright 1.62.0, Python 3.14.6), full test suite run against live headless Chromium, line-by-line reading of every module under `app/` plus `run.py`, `tests/`, and the frontend. Prior audit of commit `b5bf64d` was re-verified finding-by-finding against the two commits landed since.
**Scope:** Full system — form-filling pipeline (perception → mapping → planning → policy → execution → verification), browser automation layer, vault/policy/LLM layers, API/frontend product surface, configuration, and tests.

---

## 1. Test baseline

```
3 failed, 325 passed in 177s   (328 tests total)
```

All three failures are understood and traced to specific code changes — none are flaky:

| Failing test | Root cause |
|---|---|
| `test_executor.py::TestClickAction::test_click_button` | Clicks a "Submit Application" button → now correctly classified `HIGH_RISK` → executor refuses (`REQUIRE_CONFIRMATION`). **The safety gate works; the test predates it and still asserts `success is True`.** |
| `test_executor.py::TestPressAction::test_press_tab` | B4 fix added `verify_press`; a Tab press on a static page produces no observable change → `UNCERTAIN` → executor marks `success=False`. Test not updated. |
| `test_observer.py::TestSimpleForm::test_page_observation_has_aria_snapshot` | Real regression — see Finding C3. `aria_snapshot` is empty on every page again due to a bug in the B1 fix itself. |

The suite is green-masking nothing anymore — if anything it is now *under*-asserting in the other direction: there are **no tests at all** for `AgentRunner.resume()`, `pending_action`, or the confirmation-halt path (grep confirms zero matches outside `test_policy.py`'s engine-level checks).

---

## 2. Executive summary

Since the last audit (`b5bf64d`), every one of the seven prior findings has had a fix attempted, and most are genuinely fixed: REQUIRE_CONFIRMATION now halts in both the runner and the executor (`B2`), fill verification checks vault-resolved values (`B3`), `press`/`go_back` have verifiers (`B4`), `BrowserManager.open()` enforces the trusted-domain registry (`B5`), the vault supports Fernet encryption at rest (`B6`), document uploads get magic-byte validation (`B7`), and the engine is finally reachable from the UI through real `/api/automate` endpoints.

But the fixes were applied at the component level without re-checking the cross-component contracts this project's own remediation spec says are the whole game. The result:

1. **The confirmation gate halts correctly but can never be resumed.** `resume(approved=True)` sends the exact same sensitive action back through the executor's own policy gate, which refuses it again. And no API endpoint or UI code calls `resume()` at all. Net effect: any workflow containing one sensitive field (DOB, mobile, Aadhaar…) runs until that field and stops forever. The flagship fix is inert end-to-end.
2. **The vault is not wired into the runtime.** The API's automation flow constructs `AgentRunner` → `BrowserExecutor()` with an *empty* `UserVault`. Every `value_ref` fill resolves to `None` and fails. Separately, `VaultManager` reads `os.environ.get("VAULT_ENCRYPTION_KEY")` while the new `Settings.vault_encryption_key` field (loaded from `.env`) is never passed to it — setting the key in `.env` silently does nothing.
3. **A real regression: ARIA snapshots are empty again.** The B1 fix introspects Playwright's signature correctly but then passes `mode=True` (a boolean) where the driver requires `"ai"|"default"`. Every snapshot fails server-side and returns `""`.
4. **The test suite was not updated for the new safety semantics** — 3 failures, all caused by correct new behavior or the C3 regression, and the most important new behavior (confirmation pause/resume) has zero coverage.

Also notable: the site registry's task instructions — which flow verbatim into the agent's LLM prompt — explicitly instruct the agent to *"Solve the CAPTCHA by typing the characters shown"* and *"Enter the OTP"*, directly contradicting the PolicyEngine's hard rule that CAPTCHA/OTP are user checkpoints.

---

## PART A — Verification of prior findings (b5bf64d audit)

### B1 — `aria_snapshot()` kwargs — fix attempted, **regressed (now Finding C3)**
`app/browser/aria.py` now introspects `inspect.signature(Locator.aria_snapshot)` once and builds kwargs from what the driver accepts. The mechanism is right; the value is wrong. `_build_snapshot_kwargs(mode=True)` emits `{"mode": True}` — the boolean `True`, not `"ai"` — so on Playwright 1.62 the driver rejects it (`mode: expected one of (ai|default)`), the broad `except Exception` swallows it, and `PageObservation.aria_snapshot` is `""` on every page. Blast radius unchanged from before: element extraction doesn't use it; `vision.py:86` (`thin_aria_snapshot`) fires on every page; one test fails.

### B2 — Confirmation actions executed anyway — **fixed at both gates, but resume path broken (Finding C1)**
- `runner.py::_check_policy` now stores `workflow.pending_action` + `pending_observation_id`, sets `READY_FOR_CONFIRMATION`, adds a checkpoint, and **halts** (returns True). Correct.
- `executor.py::execute` independently returns without executing on `needs_confirmation`. Correct defense-in-depth for direct calls.
- **But:** the stored pending action is a sensitive/high-risk action by definition. `runner.resume(approved=True)` reconstructs it and calls `_executor.execute(...)` — which evaluates policy again, gets `REQUIRE_CONFIRMATION` again, and returns `success=False, recovery_required=True`. There is no bypass flag, no `confirmed=True` parameter, nothing. An approved action can never execute. `resume()` also ignores its own fresh `policy_result` entirely (a DENY after state change would still attempt execution — moot today only because the executor blocks first).
- Additionally, nothing in `app/api/routes.py` or `app/frontend/index.html` ever calls `resume()`. The workflow ends at `READY_FOR_CONFIRMATION` and the HTTP polling loop just displays it. The status is terminal in practice.

### B3 — Fill verification skipped for vault fills — **fixed**
`ActionResult.resolved_value` is set in `_execute_fill` and threaded into `verify_fill`, which now checks `resolved_value or action.literal_value` against the live DOM readback. Residual gaps (minor): `_read_live_value` resolves locators against the main page only — fills inside iframes aren't value-checked; a `None` live read still passes silently.

### B4 — `press`/`go_back` unverified — **fixed**, with a behavioral cost (Finding C7)
Both have verifiers now. Side effect: benign key presses (Tab) legitimately produce no DOM change → `UNCERTAIN` → executor converts to `success=False, recovery_required=True` → runner burns recovery attempts and can FAIL the workflow over a harmless Tab. One test failure is the visible symptom.

### B5 — TrustedDomainRegistry not enforced — **fixed at navigation entry only**
`BrowserManager.open()` raises `DomainAccessError` for domains absent from the registry or marked `allowed=False` (with lazy loading and a fail-open sentinel if registry construction throws). Caveats: enforcement covers only explicit `open()` calls — clicks/forms inside the page can still navigate anywhere (inherent to a browser agent, worth documenting); `file://` and non-http schemes skip the check entirely; registry load failure fails open with a warning.

### B6 — Plaintext vault — **implemented, not wired (Finding C2) + weak KDF (Finding C9)**
`VaultManager` encrypts with Fernet when a key is present, auto-detects encrypted files on load, and logs plaintext fallbacks. Two problems: (a) nothing in the runtime constructs `VaultManager` at all — the API flow uses an empty in-memory vault, so encryption protects a file nobody reads; (b) the key comes from raw `os.environ`, not from `Settings.vault_encryption_key`, so `.env` configuration is dead. Also `_derive_fernet_key` is a single unsalted SHA-256 — fine against casual reading, weak against a real attacker with the file; scrypt/PBKDF2/argon2 would be appropriate.

### B7 — Document MIME validation unenforced — **fixed**, path check is vacuous (Finding C8)
Magic-byte sniffing now gates uploads per document type. But the "path safety" check compares `path.resolve()` against `path.parent.resolve()` with `is_relative_to` — always true, can never fire. It validates nothing; the original intent (confine uploads to an allowed root like `data/documents/`) is not implemented.

### Previously noted product gap — **closed**
`POST /api/automate` looks up the domain in the registry, launches `BrowserManager` + `AgentRunner` in a background task, and exposes poll/screenshot/abort endpoints. The frontend drives them with live status, action log, and screenshots. The engine is now reachable end-to-end — subject to Findings C1/C2 below, which make real form-filling impossible through this path.

---

## PART B — New findings

### C1 (High — safety/product-critical): The confirmation flow is a dead end
Three compounding defects:
1. `resume(approved=True)` cannot execute the approved action (double-gating, detailed above). Fix shape: pass an explicit `skip_confirmation=True`/`confirmed_action=True` to `executor.execute()` from `resume()` only, and honor a fresh `policy_result.blocked` (state may have changed during the pause).
2. No API/UI surface calls `resume()`; there is no approve/decline endpoint. The frontend shows `ready_for_confirmation` as a terminal badge.
3. `resume()` executes exactly one action and returns — despite a comment claiming "Continue the normal loop from here". There is no re-entry into the observe→plan→execute loop preserving the same `WorkflowState` (`run()` always creates a fresh one).

Until this is fixed, the system's central safety feature converts every realistic government form (all require DOB/mobile/Aadhaar) into a guaranteed stall at the first sensitive field.

### C2 (High): Vault is disconnected from the runtime
- `routes.py::_run_automation` builds `AgentRunner(llm=llm)` → `BrowserExecutor(policy_engine=...)` → `ValueResolver(UserVault())` — **empty**. Every planned `fill` with a `value_ref` returns "No value provided (value_ref unresolved)". Deterministic planner only ever emits `value_ref` fills, so through the API the agent cannot fill anything, ever.
- `VaultManager` reads `os.environ["VAULT_ENCRYPTION_KEY"]`; `Settings.vault_encryption_key` (from `.env`) is never consumed by app code. Same class of disconnect.
- Fix shape: construct `VaultManager(settings.data_dir / "vault")` in the API layer (or runner), call `set_vault(manager.vault)` / `set_document_registry(manager.registry)` on the executor, and route the encryption key through Settings.

### C3 (Medium–High): ARIA snapshot regression — `mode=True`
As described in Part A/B1. One-line-class fix: map hints to proper values (`mode="ai"` when the param exists), e.g. `kwargs = {"mode": "ai"} if "mode" in _supported_snapshot_kwargs else {}`. Add a unit test asserting the built kwargs values, not just keys.

### C4 (Medium): Deterministic planner's select logic is wrong
`plan_deterministic` handles comboboxes with:
```python
if el.ref == binding.field_ref and el.selected_options:
    return BrowserAction(action="select", ..., option=el.selected_options[0], ...)
```
It acts only when something is *already selected* and then re-selects the current value — a no-op that will fail click-style verification ("content changed") and can loop/retry. It never consults the binding (`USER.state` etc.) or the vault. Checkboxes similarly always emit `check` regardless of desired state. Correct shape: resolve `binding.binding` via `ValueResolver` and select that option text (or report unmappable). Today this path mostly matters for LLM-less runs, but the LLM prompt also gives the planner no resolved values to select with — `select_option(label=...)` requires exact label match against page text, which vault values like "Male" vs "MALE" will frequently miss.

### C5 (Medium): Abort is a no-op; background-task hygiene
`POST /api/automate/{id}/abort` sets `wf["status"] = "aborted"` and returns. Nothing cancels the running task: `_run_automation` keeps driving the browser and later overwrites the status with `workflow_state.status.value`, resurrecting the aborted workflow. Related issues in the same endpoint family:
- `asyncio.create_task(_run_automation(...))` result is not referenced — schedulable tasks can be garbage-collected mid-flight (CPython docs warning); keep a strong ref / task registry.
- Screenshots accumulate as hex strings in `_workflows` forever (unbounded memory); no eviction, no cap.
- Polling returns `actions` list unbounded; fine for now, same growth story.

### C6 (Medium): Registry task instructions contradict the safety policy
`sites/registry.py` task `instructions` fields (e.g., UIDAI "Download Aadhaar": *"Solve the CAPTCHA by typing the characters shown… Enter the 6-digit OTP…"*) become `task_description` → the LLM planner's system prompt. The PolicyEngine will still PAUSE_FOR_USER at those pages (good — runtime gate wins), but the prompt actively coaches the model toward behavior the architecture forbids, wasting iterations and inviting creative circumvention attempts. Fix: strip/annotate CAPTCHA/OTP/payment steps from instructions programmatically, or mark them "user handles this step".

### C7 (Low–Medium): UNCERTAIN press semantics burn the recovery budget
Any `press` that produces no visible change (Tab, arrow keys, Escape closing nothing) is `UNCERTAIN` → `recovery_required=True` → up to 3 wasted retry cycles → workflow FAILED. Consider treating control-key presses with no change as SUCCESS-with-note, or exempting non-Enter keys from the strict rule.

### C8 (Low): Vacuous path-containment check in `DocumentPolicy`
`resolved.is_relative_to(path.parent.resolve())` is tautologically true. Implement the intended check: resolve and compare against a configured allowed root (e.g. `settings.docs_dir`), passed in as a parameter.

### C9 (Low): Weak KDF for vault encryption
Single unsalted SHA-256 passphrase → Fernet key. Use `cryptography.hazmat.primitives.kdf.scrypt`/PBKDF2 with a stored random salt. Low urgency while the vault is unwired (C2), high relevance once real data lands.

### C10 (Low): Dead configuration & unreachable features
Inventory of things that exist but do nothing (each verified by grep):
- `Settings.openrouter_vision_model` — gateway always uses `openrouter_model`, even for `images=` requests.
- `Settings.openrouter_fallback_model` — `RetryPolicy` retries the same model; no fallback switch anywhere.
- `vision.py::assess_completeness` / `capture_screenshot_for_fallback` — never called from runner/planner; vision fallback (audit issue #30) remains trigger-without-integration. Only `tests/unit/test_vision.py` touches it.
- `ReferenceRegistry.llm_visible` (never set False → `visible_only=True` filters nothing) and `confirmation_policy` (always "none", never consulted).
- `WorkflowStatus.COMPLETED` and `WAITING_FOR_CAPTCHA` are never set by any code path; `submission_state` is never updated. The frontend polls for `completed` and will never see it — successful runs terminate as `READY_FOR_SUBMISSION`.
- `finish_review` is a valid `BrowserAction` literal but has no executor handler ("Unknown action type") and is absent from the LLM schema.
- `browser_mode`/`headless`: `browser_mode="user"` forces headed regardless of `headless` — intentional per docstring, but `.env.example` documents neither variable.
- `=42.0.0` — a tracked junk file at repo root (artifact of an unquoted `pip install ... >=42.0.0`).

### C11 (Low): Tests lag the new semantics
- Update `test_click_button` to assert the gate (expect `success=False`, message contains `REQUIRE_CONFIRMATION`, or assert via a pre-approved executor flag once C1 lands).
- Update `test_press_tab` for C7 semantics.
- Add runner-level tests: sensitive fill halts with `pending_action` stored; `resume(approved=True)` actually executes (post-C1-fix); `resume(False)` → ABORTED; stale `pending_observation_id` rejected.
- Add an aria.py unit test asserting kwarg *values* (`mode == "ai"`), which would have caught C3.

### C12 (Informational / hardening notes)
- `ignore_https_errors=True` on the browser context — acceptable for gov-site TLS oddities, but worth a setting with default False and per-domain opt-in.
- `/api/*` endpoints have no authentication whatsoever; anyone who can reach port 8000 can launch browser automations. Fine for localhost dev; must be addressed before any remote exposure. `start_automation(body: dict)` also skips Pydantic validation.
- Frontend renders registry-derived strings via `innerHTML` with minimal escaping (`escapedTask` escapes single quotes only). Source data is code-controlled today, so exploitability is nil, but the pattern breaks the moment registry data becomes user-editable.
- `_handle_no_action` maps "planner produced nothing" to `READY_FOR_SUBMISSION` when there are no unmapped fields — an LLM outage or a `stop` on a half-filled multi-page form reports "ready for submission". Should be a distinct status (e.g. WAITING_FOR_USER with reason).
- `WorkflowState.record_action` adds `target_ref` to `completed_bindings` for any successful action including clicks/scrolls — field-completion bookkeeping can be polluted.
- Prompt truncation `elements_info[:20]` in the LLM planner silently hides fields beyond the 20th — common on real government forms.
- `verify_upload`'s final JS fallback picks the Nth `input[type=file]` by parsing the global element index out of the ref — can attribute another input's file to this upload (violates the file's own docstring / audit issue #16). Frame-hosted uploads are unverifiable (JS runs in main frame only).
- `sensitivity.py::FIELD_SENSITIVITY` duplicates sensitivity data already in `ReferenceRegistry` (currently consistent, but two sources of truth is exactly what the remediation spec's Issue #37 said to eliminate).
- `routes.py::list_states` reaches into `reg._domains` (private attr).
- `executor.py` reads `document_resolver._doc_fields` (private attr across classes).
- `main.py` serves `index.html` with no caching headers issue — fine; but reading from disk per request is intentional ("fresh"), documented inline.

---

## 3. What's working well

Worth stating plainly, because the skeleton is genuinely good:

- **Policy engine**: clean risk taxonomy, auth-context short-circuit, deny-by-default posture for unknown risky patterns; correctly wired at both runner and executor layers.
- **Reference indirection for PII**: raw Aadhaar/PAN never enter prompts; `value_ref` resolution happens locally in the executor; `BrowserAction` validators reject PAN/Aadhaar-shaped literals at construction time.
- **Field mapping**: tiered deterministic→LLM→user design with registry validation of every binding (including LLM output) is the right architecture and is implemented faithfully.
- **Verification layer**: per-action verifier modules, sensible cascades (click's URL/title/count/alerts/validation/state/content diff), UNCERTAIN treated as stop-not-proceed.
- **Observation staleness contract**: `observation_id` on actions/bindings + executor rejection of stale refs works as designed.
- **LLM gateway**: bounded retries with jitter, structured output, redacted logging, typed error hierarchy, fail-closed.
- **Trusted-domain gate at `open()`** is a real access-control boundary now, and the API only starts workflows for registered domains.

## 4. Architecture as-built (one paragraph)

`FastAPI (main.py/routes.py)` owns discovery + workflow launch; `AgentRunner (runner.py)` owns the loop: `PageObserver.observe()` (dom.py JS extraction + aria.py + frames) → `FieldMapper.map_fields()` (deterministic rules → optional LLM disambiguation, registry-validated) → `plan_with_llm/plan_deterministic` → `PolicyEngine.evaluate()` → `BrowserExecutor.execute()` (locator.py frame-aware resolution → Playwright → re-observe → `ActionVerifier` dispatch) → `WorkflowState` accumulation. `VaultResolver`/`DocumentResolver` resolve refs locally; `VaultManager` persists (optionally encrypted); `OpenRouterGateway` is the only outbound LLM transport. The two broken joints are exactly at the human boundaries: confirm/resume (C1) and vault loading (C2).

## 5. Findings summary

| ID | Severity | Area | Finding |
|----|----------|------|---------|
| C1 | **High** | Agent/workflow + API | Confirmation halt works but `resume()` is double-gated (approved actions can't execute), no API/UI resumes, and resume doesn't re-enter the loop |
| C2 | **High** | Vault/API wiring | Runtime uses an empty `UserVault` — all `value_ref` fills fail via API; `VAULT_ENCRYPTION_KEY` in `.env` never reaches `VaultManager` |
| C3 | Medium–High | Perception | ARIA snapshot passes `mode=True` (bool) — driver rejects, snapshots empty again; 1 test failing |
| C4 | Medium | Planning | Deterministic select re-picks the already-selected option; checkbox always checks; select ignores bindings/vault |
| C5 | Medium | API | `abort` doesn't cancel the running task and its status gets overwritten; unreferenced `create_task`; unbounded screenshot memory |
| C6 | Medium | Data/prompts | Registry task instructions coach the agent to solve CAPTCHAs/enter OTPs, contradicting the policy engine |
| C7 | Low–Med | Verification | Benign presses (Tab) → UNCERTAIN → recovery burn → possible workflow FAILURE; 1 test failing |
| C8 | Low | Document policy | Path-containment check is a tautology; intended allowed-root confinement not implemented |
| C9 | Low | Vault crypto | Unsalted single-pass SHA-256 KDF for Fernet key |
| C10 | Low | Config/dead code | Vision fallback unintegrated; vision/fallback models unused; `COMPLETED`/`WAITING_FOR_CAPTCHA`/`submission_state` never set; `llm_visible`/`confirmation_policy` dead; junk `=42.0.0` file |
| C11 | Low | Tests | Suite not updated for gate/press semantics; zero coverage of resume/pending-action path; no kwarg-value test for aria |
| C12 | Info | Hardening | No API auth; `ignore_https_errors`; innerHTML rendering; READY_FOR_SUBMISSION mislabel on LLM failure; upload index-fallback mis-targeting; duplicated sensitivity tables; private-attr reach-throughs |

Prior findings: **B2, B3, B4, B5, B6(impl), B7 fixed**; **B1 regressed (C3)**; **B6 wiring missing (C2)**.

## 6. Suggested order of attack

1. **C1** — make the confirmation loop real: confirmed-execution bypass in `executor.execute()`, an approve/decline endpoint calling `runner.resume()`, and loop re-entry preserving `WorkflowState`. Without it, the product stalls on every realistic form.
2. **C2** — wire `VaultManager` into the API/runner path and route the encryption key through `Settings`. This is what turns "engine works" into "agent can fill forms".
3. **C3** — one-line aria fix + kwarg-value test (clears a test failure immediately).
4. **C5 + C11** — abort cancellation/task refs/memory caps, and bring the three failing tests in line with intended semantics while adding resume-path coverage.
5. **C4, C6, C7** — planner select correctness, instruction/policy alignment, press semantics.
6. **C8–C10, C12** — quality/hardening backlog, in whatever order convenience dictates; none block a demo, several block production.

---

## Remediation log (Aug 25, 2026 — post-audit implementation)

All fixes verified by: full test suite **374 passed / 0 failed** (was 3 failed / 325 passed),
plus a live semi-E2E smoke run (real Chromium, synthetic form): public fills auto-execute →
sensitive fill halts with `pending_action` → `resume(approved=True)` re-validates target and
executes → select completes → submit click gates again → `resume(approved=False)` aborts cleanly.

| Finding | Fix | Files |
|---|---|---|
| C1 confirmation dead end | `user_confirmed` bypass in executor; `resume()` re-observes, verifies target identity via stored signature, re-targets to fresh observation, honors fresh DENY/PAUSE, then **re-enters the shared loop**; `POST /api/automate/{id}/confirm` endpoint + frontend Approve/Decline UI; automation loop waits at checkpoints | `executor.py`, `runner.py`, `routes.py`, `workflow_state.py`, `index.html` |
| C2 vault disconnected | `AgentRunner(vault=…, document_registry=…)` wired from a `VaultManager` loaded in the API flow; empty-vault warning surfaced per workflow | `runner.py`, `executor.py`, `routes.py` |
| C3 aria `mode=True` | kwargs now carry proper values (`mode="ai"`, `refs=True`) filtered by driver signature; kwarg-value regression tests | `aria.py`, `tests/unit/test_aria.py` |
| C4 planner select/checkbox | deterministic planner resolves bindings through the vault; skips already-satisfied fields; skips unresolvable bindings; robust option matching (label → value attr → case/whitespace-insensitive) | `planner.py`, `executor.py`, `runner.py` |
| C5 abort no-op / memory | real task cancellation with strong task refs; screenshot history capped; bounded workflow store with eviction | `routes.py` |
| C6 CAPTCHA/OTP coaching | sentence-level instruction sanitizer drops manual-step steps and appends an explicit user-handles note | `sites/registry.py`, `routes.py` |
| C7 press semantics | control keys (Tab/arrows/Escape/…) without change → SUCCESS; Enter stays strict | `verifiers/press.py` |
| C8 vacuous path check | opt-in `allowed_roots` confinement enforced against configured roots | `document_policy.py`, `settings.py`, `executor.py` |
| C9 weak KDF | salted scrypt KDF with versioned on-disk format (`VLT1`+salt+token); legacy unsalted files still readable and upgraded on save; key routed through Settings | `vault/manager.py`, `settings.py` |
| C10 dead config/statuses | vision model used for image requests; fallback model implemented as second-chance switch; `COMPLETED` + `WAITING_FOR_CAPTCHA` set; `submission_state` transitions; `finish_review` removed; junk `=42.0.0` deleted | `openrouter.py`, `runner.py`, `actions.py` |
| C11 tests lagging | stale tests updated to gate semantics; new coverage: resume flow (approve/decline/no-pending/DENY-wins/vanished-target), planner determinism, aria kwargs, instruction sanitizer, vault crypto formats, doc-policy roots, API confirm/abort endpoints | `tests/unit/*`, `tests/integration/*` |
| C12 hardening | typed request bodies; optional bearer-token auth on `/api/*`; LLM-failure no longer mislabeled READY_FOR_SUBMISSION; upload index-guess fallback removed; public accessors replace private reach-throughs; sensitivity derived from ReferenceRegistry (single source of truth); frontend `escapeHtml`; `.env.example` documents all new vars | multiple |

**Bonus fix found during live verification:** qualified labels ("Applicant Full Name") scored
MEDIUM due to keyword-length dilution — token-coverage scoring now keeps them HIGH
(`field_mapper.py`), unblocking the most common real-world label pattern.

---

## Remediation log (Aug 26, 2026 — Z1–Z8 from audit-zero-action-stall.md, per implementation-plan.md)

Executed phase-by-phase under `context_fix_plan.md` Section 1 protocol (read → inspect →
reproduce/write test → confirm → smallest fix → targeted tests → full suite). Baseline before
work: **374 passed / 0 failed**. After all phases: **441 passed / 0 failed** (+67 new tests,
one new permanent regression fixture class per finding). Skills discovered and validated via
`find-skills` per milestone per protocol §2; no external skill outranked repo code + official docs.

| Finding | Fix | Files |
|---|---|---|
| Z2 + Z5 + Z8 (Phase 1 — typed planning result, honest status; completes P0-13/P0-37) | New `PlanOutcome` variants (`ActionPlanned`/`PlanLLMError`/`NoValidAction`/`TaskComplete`) replace the overloaded `BrowserAction \| None`; `_handle_plan_outcome` dispatches by page_type — navigation/unknown stalls are WAITING_FOR_USER ("stalled"), never READY_FOR_SUBMISSION; unparseable structured LLM responses become surfaced errors instead of silent None; `planning_mode`/`llm_model`/`llm_disabled_reason` on WorkflowState + poll payload from the first iteration | `app/agent/planning_result.py` (new), `planner.py`, `runner.py`, `models/workflow_state.py`, `api/routes.py`, `llm/openrouter.py`, `tests/unit/test_plan_outcome.py` |
| Z3 (Phase 2 — a way to put your data in) | `POST/GET /api/vault` (partial updates, unknown fields rejected via extra=forbid, responses carry field NAMES only); committed `user_vault.example.json` template + README; `data/vault/*` now gitignored (**plan assumed it already was — it was not**); empty vault surfaced as structured `vault_loaded`/`vault_warning` workflow fields, not just a log line | `app/api/vault_routes.py` (new), `main.py`, `.gitignore`, `data/vault/user_vault.example.json` + `README.md` (new), `models/workflow_state.py`, `runner.py`, `api/routes.py`, `tests/unit/test_vault_api.py` |
| Z1 (Phase 3 — auth detection = active challenge; completes P0-18) | `"captcha"` removed from OTP keyword list; OTP detection requires an editable, enabled input-role element; CAPTCHA requires an entry box/img widget, an active dialog instructing one, or reCAPTCHA iframe metadata (frames now passed to detector); the exact audit repro (help link mentioning CAPTCHA → 90% "OTP") is a permanent regression test; true positives preserved | `app/browser/observer.py`, `tests/unit/test_auth_detection.py` |
| Z4 (Phase 4 — relevance-ranked element selection) | Flat `[:120]` DOM-order slice replaced by task-keyword-overlap ranking with in-progress binding targets always protected; cap retained; prompt order stays DOM-stable; truncation note now says "top N by task relevance" | `app/agent/planner.py`, `tests/unit/test_element_ranking.py` |
| Z6 (Phase 5 — model guardrails) | Free-tier detection = shipped anonymous default OR any OpenRouter `:free` model; populated-vault + free-tier runs refused BEFORE browser launch unless `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true`; resolved model logged at start and visible in poll. **Operator note: this repo's real `.env` pins `dots-studio/dots-3-note-preview:free` — with a populated vault such runs will refuse until `OPENROUTER_MODEL` is pinned to a named provider or the override is set deliberately** | `app/config/settings.py`, `api/routes.py`, `.env.example`, `tests/unit/test_model_guardrails.py` |
| Z7 (Phase 6 — vision fallback wired; completes P0-16) | One vision pass per workflow at a confirmed NO_VALID_ACTION stall: screenshot → multimodal model → named target grounded against observed refs (exact > containment; never guessed into actions, P0-41); clicks only; attempts + outcome recorded in checkpoints/trace; gated by `vision_fallback_enabled`; disabled path byte-identical to Phase 1 behavior | `app/agent/vision_fallback.py` (new), `runner.py`, `models/workflow_state.py` (`vision_fallback_attempts`), `api/routes.py`, `tests/unit/test_vision_fallback_wiring.py` |

Not done here (deliberately, per plan): Phase 7 production backlog items (cost caps, injection
fixture expansion, trace export endpoint, startup config checks) remain open; Capability
Registry / tiered Model Router remains a separate future initiative.

Test-count trail per phase: 374 → 393 → 403 → 415 → 422 → 434 → 441 (all `--ignore=tests/real_sites`).

---

## Remediation log (Phase 8 + Phase 9 — multi-tab awareness & repeated-action stall detector)

New audit (tab duplication + "what a reference build would do differently") identified a code-level gap that defeats any model: nothing in the stack knew a second browser tab existed, so a `target="_blank"` click landed in a tab nobody observed and every retry duplicated it. Implemented per `implementation-plan.md` Phases 8–9, under the repo's Section 1 protocol.

Baseline before this round: **441 passed / 0 failed**. After: **494 passed / 0 failed** (+53 new:
`tests/unit/test_tabs.py`, `tests/unit/test_stall_detector.py`, `tests/integration/test_multi_tab.py`
plus `tests/synthetic_forms/pages/portal_landing.html` + `portal_subportal.html`).

| Finding | Fix | Files |
|---|---|---|
| Phase 8 — tab duplication (a click into `target="_blank"`/`window.open` was invisible) | `BrowserManager.start()` registers `context.on("page", ...)` via a new `TabTracker` so every tab is known from the moment it opens (newest tab wins); after click-type actions the executor reconciles tab state in `_sync_tabs` and adopts the newest tab as the active page for all later observation/action; the switch is explicit on `ActionResult.tab_switch`/`active_page` and written into the workflow trace via `record_tab_switch` + a checkpoint (`opened a new tab: <url> — switching context to it`); the orphaned old tab is closed so one click never leaves a pile; `PageObserver` populates `PageState.tabs` so a second tab is reported to the planner, not guessed at | `app/browser/tabs.py` (new), `app/browser/manager.py`, `app/browser/executor.py`, `app/models/page_state.py`, `app/agent/runner.py`, `tests/integration/test_multi_tab.py`, `tests/synthetic_forms/pages/portal_landing.html`, `tests/synthetic_forms/pages/portal_subportal.html`, `tests/unit/test_tabs.py` |
| Phase 9 — repeated-identical-action stall | New `stall_detector` builds `ActionSignature = (action_type, target_ref, page_type, url)` + structural `page_fingerprint`; `evaluate_repeat` halts after 3 identical no-progress repeats with greppable reason `repeated_action_no_progress`; `runner._check_repeated_action` sets `WAITING_FOR_USER` + a named checkpoint — a labeled stall, not a generic max-iteration failure; any real page change resets the counter | `app/agent/stall_detector.py` (new), `app/agent/runner.py`, `app/models/workflow_state.py`, `tests/unit/test_stall_detector.py` |
| Smaller item — document `browser_mode` overrides `HEADLESS` | One-line note added to `.env.example` next to `HEADLESS` (and a note on pinning a named, established `OPENROUTER_MODEL` rather than a `:free` model before the vault has real data) | `.env.example` |
| Smaller item — pin `OPENROUTER_MODEL` | `.env.example` already pins `anthropic/claude-sonnet-4-20250514` (a named provider); comment added clarifying the guardrail interaction. (The gitignored runtime `.env` is the operator's responsibility — the example no longer ships the anonymous default.) | `.env.example` |

Not done here (out of scope of this branch): the §5 "evals from real frozen snapshots" recommendation — every fixture is still synthetic. A library of real, captured, replayed-offline portal snapshots (UIDAI, PM-KISAN, a scholarship portal) would have caught this class of bug earlier and remains the highest-leverage follow-up.
