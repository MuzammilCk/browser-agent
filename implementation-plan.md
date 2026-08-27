# Implementation Plan — From Zero-Action Stall to Production-Ready

**Companion to:** `audit-zero-action-stall.md` (Z1–Z7)
**Reconciled against:** your own `context_fix_plan.md` already in the repo (P0-1…P0-42+)
**Repo state this plan targets:** `origin/main @ fd1eb5e`
**Regression floor the executing agent must never drop below:** 374 passed (`pytest tests/ -q --ignore=tests/real_sites`)

---

## 0. Read this before handing anything to your coding agent

Your repo already contains `context_fix_plan.md` — a genuinely good implementation contract, with a Section 1 "anti-hallucination / anti-breakage protocol" (read → inspect current code → reproduce/write test → confirm → smallest fix → targeted tests → full suite → next issue) and ten non-negotiable rules. **Keep enforcing that protocol.** This document does not replace it — it tells the agent *what* to build; that protocol still governs *how*.

While reconciling my new findings against that document, I found something important: **four items in your own plan were never actually finished**, and three of them are directly responsible for the stall you reported. I checked each one directly in the current code rather than trusting the plan's checkboxes (there are none — the doc has no done/not-done markers, so this had to be verified by reading `observer.py`, `planner.py`, and `routes.py` against what each item demands):

| Your plan's item | Demands | Verified status in `fd1eb5e` |
|---|---|---|
| P0-13 — LLM failure must be typed, never collapsed to "no action" | A `PlannerStatus` enum (`SUCCESS/LLM_ERROR/NO_VALID_ACTION/USER_REQUIRED/COMPLETE`) | **Not built.** Today's fix added one narrow string check (`error_state == "recoverable"`) instead — a patch, not the contract this item asked for. |
| P0-16 — vision is a fallback, not the default | A `DOM_COMPLETE/DOM_PARTIAL/VISUAL_REQUIRED` threshold wired into the loop | **Not built.** `vision.py` exists in isolation; zero call sites in `app/agent/*.py` or `app/api/routes.py`. |
| P0-18 — authentication detection must mean "active challenge" | Multi-signal detection, not presence-of-a-keyword | **Not built.** `observer.py::_detect_auth_challenge` still does plain substring matching against every element's accessible name — confirmed by direct repro in the audit file. |
| P0-37 — report whether LLM mode is actually active | Expose `planning_mode`, `llm_enabled`, `model` in workflow state; never silently fall back | **Not built at all.** `grep` for `planning_mode`/`llm_enabled` across the whole codebase returns nothing. See **Z8** below — this is likely the single most complete explanation for what you saw. |

Everything below is organized to *finish* those four properly (as one coherent abstraction each, not more narrow patches), plus close the items from my own audit that your plan doesn't yet cover at all (vault population, element-cap ranking, model pinning).

---

## 1. New finding — Z8: the system may be silently running with no LLM at all

Found while checking P0-37 against the live code. `routes.py`, where the automation run is actually kicked off:

```python
llm = None
if settings.openrouter_api_key:
    try:
        llm = OpenRouterGateway(settings)
    except Exception as e:
        logger.warning("Could not create LLM gateway: %s", e)
```

If `OPENROUTER_API_KEY` is empty, unset, or the gateway constructor throws for any reason — **this is completely silent.** No entry in `wf` (the workflow status dict the API/frontend/your coding agent would poll), nothing beyond a server-console `logger.warning` that fires only in the "constructor threw" branch (the "key is just empty" branch doesn't even log). `runner.run(..., llm=None)` proceeds normally.

With `llm=None`, `AgentRunner._plan` falls back to `plan_deterministic`, whose actual, complete capability (I read the full function) is:
- Fill high-confidence `textbox`/`combobox`/`checkbox` bindings whose vault value resolves to something non-empty (ties directly to **Z3** — empty vault → every one of these is skipped too),
- then look for a `role == "button"` whose accessible name contains one of exactly four English substrings: `"submit"`, `"next"`, `"apply"`, `"save"`,
- otherwise return nothing.

It has **no handling for `role == "link"` at all.** Real portal navigation is built almost entirely out of `<a>` tags. Put together: on a landing page with only links, with an empty or misconfigured API key, with no data in the vault yet — the deterministic fallback produces exactly zero actions, silently, and there is currently no field anywhere in the workflow state that would tell you *this is why*. This reframes your own hypothesis usefully: it's not that the LLM reasoned poorly — it may never have been invoked in the first place, and you'd have no way to know that from the outside.

This is why Phase 1 below is ordered first: every other fix is unverifiable until you can see, from the workflow status itself, whether the LLM was actually in the loop.

---

## 2. Governing design principle for every phase below

Two rules, both already implicit in your own plan's non-negotiable list (#5, #6), applied consistently instead of piecemeal:

1. **Loud failure beats silent success.** A stalled workflow must never look identical to a completed one. An unreachable model must never look identical to "nothing to do."
2. **Fix the abstraction once, not the symptom three times.** Z2, Z5, and Z8 are three symptoms of the same underlying gap: `plan()` returns `BrowserAction | None`, and `None` is currently overloaded to mean "genuinely done," "LLM errored," "LLM said stop," "LLM returned garbage," and "no LLM was ever configured." Phase 1 replaces the overload with one typed result, which is what P0-13 already asked for — it just specifies the parts P0-13 left implicit (page-type-aware dispatch, and LLM-engagement visibility).

---

## Phase 1 — Typed planning result + honest workflow status
**Closes:** Z2, Z5, Z8. **Completes:** P0-13, P0-37 from your own plan.

### Scope
Replace the bare `BrowserAction | None` return type shared by `plan_with_llm` and `plan_deterministic` with a small typed result carrying one of:

```text
PlanOutcome
├── ACTION(action: BrowserAction)
├── LLM_ERROR(message: str)          # exception OR non-conforming/unparseable response
├── NO_VALID_ACTION(reason: str)     # planner ran fine, found nothing to do
└── TASK_COMPLETE(reason: str)       # planner believes the task is genuinely finished
```

Dispatch rules for the runner, replacing `_handle_no_action`'s current "count unmapped fields" proxy:
- `LLM_ERROR` → `WAITING_FOR_USER`, error surfaced verbatim in workflow state (this is what closes Z5 — a malformed JSON response becomes this variant instead of silently becoming `parsed=None`).
- `NO_VALID_ACTION` where `page_type in ("navigation", "unknown", "otp", "captcha")` → `WAITING_FOR_USER` with an explicit "stalled, not complete" reason — **never** `READY_FOR_SUBMISSION`. This is the actual fix for Z2; page_type becomes a real input to the transition instead of being ignored.
- `NO_VALID_ACTION` where `page_type in ("form", "review")` and mapping has no unmapped/ambiguous fields → this is the one legitimate path to `READY_FOR_SUBMISSION` (a form that was already correct, or just finished).
- `TASK_COMPLETE` → `COMPLETED` (only reachable if `page_type == "success"`, per the existing check already in `runner.py` — keep that guard).

Separately, and this is what closes Z8: the moment `llm` is constructed (or fails to be), write an explicit, structured field into workflow state — not a log line:

```text
workflow.planning_mode  = "llm" | "deterministic_fallback"
workflow.llm_model      = resolved model string, or null
workflow.llm_disabled_reason = null | "no_api_key" | "gateway_init_failed: <msg>"
```
This must be present from the very first status the API/poller sees, not only on failure — so "is the LLM even running" is answerable at a glance for every workflow, not just broken ones.

### Acceptance criteria
- New tests: `page_type="navigation"` + `NO_VALID_ACTION` → asserts status is `WAITING_FOR_USER`, never `READY_FOR_SUBMISSION`, and `workflow.actions_taken == []` is consistent with a stalled (not completed) message.
- New test: a deliberately malformed/non-JSON OpenRouter response (mock) with `schema` set → planner returns `LLM_ERROR`, not a silent empty result.
- New test: `OPENROUTER_API_KEY=""` → workflow status shows `planning_mode == "deterministic_fallback"` and a non-null `llm_disabled_reason` from the very first poll.
- Existing 374 tests still pass. Existing legitimate `page_type="form"` completions must not regress.
- Add the missing fixture class your own test suite is short: at least one test constructing `page_type="navigation"` (currently zero exist — every fixture defaults to `"form"`).

---

## Phase 2 — A real way to get user data into the vault
**Closes:** Z3.

### Scope
Today's fix genuinely wires `VaultManager` into `routes.py` (verified directly — not just trusting the remediation log). What's still missing is any way to *populate* it:
- No `/api/vault` route of any kind exists.
- `data/vault/` doesn't exist on a fresh clone and nothing creates it.

Minimum viable, in order of effort:
1. Commit a `data/vault/user_vault.example.json` template mirroring the full `UserVault` schema (all ~35 fields, blank/placeholder values), plus a README section: "copy to `user_vault.json`, fill in your real details, before running your first task."
2. Add a small `POST /api/vault` (and `GET /api/vault` returning field *names* present, never values) so the frontend — or your coding agent's own smoke tests — can populate it programmatically instead of hand-editing JSON.
3. Promote the existing `logger.warning("vault is empty")` line into a structured `workflow.vault_loaded: bool` + `workflow.vault_warning: str | null` field in workflow state, next to `planning_mode` from Phase 1, so an empty vault is visible from the same place an LLM outage is visible.

### Acceptance criteria
- A synthetic-form test run with a populated vault fixture shows real fills for every high-confidence binding.
- A synthetic-form test run with an empty vault shows `vault_loaded: false` in workflow state within the first iteration — not after burning through the retry budget.
- `data/vault/` stays out of git (already correctly gitignored — don't change that).

---

## Phase 3 — Authentication detection means an active challenge, not a keyword
**Closes:** Z1. **Completes:** P0-18 from your own plan.

### Scope
`_detect_auth_challenge` currently scans every element's accessible name/label/placeholder for bare substrings, and `"captcha"` is (incorrectly) in the *OTP* keyword list — confirmed by direct repro in the audit file, where a plain help-link mentioning CAPTCHA registered as a 90%-confidence OTP challenge.

Required changes:
1. Remove `"captcha"` from the OTP branch's keyword list — it's a category confusion, not an OTP signal.
2. Require signal co-occurrence, not a bare substring anywhere on the page: a real OTP challenge should require an actual input-type element (short numeric `textbox`/`spinbutton`, `maxlength` around 4–6, or an explicit `role` tied to OTP entry) — not a `link` or `button`. A real CAPTCHA challenge should require an actual image/iframe/canvas widget structurally present, not a text mention.
3. Per P0-18: separate "a password field exists on this page" from "an authentication challenge is actively blocking progress right now" — a login link in a nav bar is not a challenge.

### Acceptance criteria
- The exact repro fixture from the audit (four nav links + one "Help: how to complete the CAPTCHA" link, no real challenge) must return `detected=False`.
- All existing true-positive fixtures (real password field, real OTP input, real CAPTCHA widget) must still detect correctly — do not weaken true positives while removing the false one.
- Add this fixture as a permanent regression test; it did not exist before.

---

## Phase 4 — Relevance-ranked element selection, not a flat cutoff
**Closes:** Z4 (today's fix, extended).

### Scope
`_MAX_ELEMENTS_FOR_LLM = 120` is an improvement over the old hard-20 cutoff you diagnosed yourself, but it's still arbitrary DOM-order truncation. Replace the flat slice with a ranked selection:
- Score each element by token overlap between its accessible name/label and the task description's keywords.
- Always retain elements already part of an in-progress binding (fields the mapper has already committed to), regardless of rank, so a multi-step fill doesn't lose track of a field it's midway through.
- Truncate by score, not DOM position, once over the cap. Keep a cap (memory/token budget is real) but make it a relevance filter, not a coin flip based on markup order.

### Acceptance criteria
- New test: a synthetic page with 200 elements where the actual task-relevant link sits at DOM position #150 but has strong keyword overlap with the task text — must still appear in the elements sent to the LLM after ranking + truncation.
- Existing element-cap tests (the ones added for the 20→120 fix today) still pass.

---

## Phase 5 — Model configuration guardrails
**Closes:** Z6.

### Scope
`openrouter_model` defaults to `"stealth/ox-alpha"` — an anonymous, free-tier model, clearly flagged as such in its own field description, but silently operative if `.env` doesn't override it.
1. At workflow start, resolve and log the actual model string being used — not just at the HTTP-call level, at the point a human or your coding agent would look first.
2. If `workflow.vault_loaded` (Phase 2) is `true` — i.e., real personal data is about to flow through this model — and the resolved model is still the anonymous default, refuse the run or require an explicit override flag, rather than silently proceeding. Free/anonymous models with contested retention policies and real Aadhaar/PAN/DOB data should never be the quiet default combination.
3. Treat the fuller "Capability Registry" / tiered Model Router from the original architecture plan as a separate, later initiative — this phase is the minimum guardrail, not that full system.

### Acceptance criteria
- New test: `vault_loaded=True` + unmodified default model → run is refused or clearly flagged, not silently executed.
- New test: an explicitly-set named model + populated vault → runs normally.

---

## Phase 6 — Wire the existing vision fallback into the loop
**Closes:** Z7. **Completes:** P0-16 from your own plan.

### Scope
`capture_screenshot_for_fallback` and `assess_completeness` already exist in `app/browser/vision.py` and are fully unreferenced elsewhere — confirmed independently, and it matches what your own audit already flagged (`browser-agent-audit.md`, the C10 remediation note). This phase is purely the wiring, not new capability:
- After Phase 1 makes "we are stalled, not done" an honest, distinguishable state (`NO_VALID_ACTION` on a page that should have actionable content), attempt one vision-fallback pass — screenshot → vision model → grounded coordinates → a single Playwright action — **before** surfacing to the user, per the `DOM_COMPLETE / DOM_PARTIAL / VISUAL_REQUIRED` decision threshold your own plan already specifies in P0-16.
- Gate this behind `settings.vision_fallback_enabled` (the flag already exists and is currently a no-op — this phase is what makes it do something).
- Do not call vision on every iteration — only on a confirmed `NO_VALID_ACTION`/`VISUAL_REQUIRED` state, exactly as P0-16 already specifies.

### Acceptance criteria
- A fixture where ARIA-based mapping/planning finds nothing usable triggers exactly one vision-fallback attempt, visible in the workflow's checkpoint/trace log, before the workflow moves to `WAITING_FOR_USER`.
- `vision_fallback_enabled=False` skips this path entirely and behaves exactly as before this phase.

---

## Phase 7 — Production-readiness checklist (beyond this audit)

Lighter-weight than Phases 1–6 — some of these are backlog items, not bugs, and a few are explicitly *not* code tasks. Listed so nothing gets lost, not as a strict spec.

**Code-addressable:**
- **Cost/rate cap.** `LLMUsage.cost_usd` is already captured per-call in `openrouter.py` but never aggregated or enforced anywhere. Sum it per workflow; hard-stop past a configurable threshold. This is the concrete fix for the "cost runaway from uncapped model calls" risk already on your own register.
- **Prompt-injection regression suite.** A `PromptSanitizer` already exists (`tests/prompt_injection` passes today) — add adversarial fixtures specifically shaped like scraped government-page content (hidden elements, off-screen text instructing the model to fill sensitive fields with attacker-chosen values) as a permanent regression set, not just the current test cases.
- **Observability / trace export.** Every action already produces a rich `ActionRecord` + `WorkflowState`. A simple endpoint or script that dumps a workflow's full step-by-step trace (page_type, plan outcome, policy decision, verification result at each step) turns "why did it stop" from a log-grepping exercise into a single artifact — directly useful for whichever agent is debugging this next.
- **Config/secrets checklist at startup.** Fail fast (not silently) if `API_TOKEN` is unset while the server is bound to a non-localhost interface; confirm `VAULT_ENCRYPTION_KEY` is set before any vault write; confirm `.env` is still gitignored (it is — don't regress this).

**Not a coding-agent task — needs a human/legal owner:**
- The DPDP Act (2023) / Aadhaar-specific compliance review. A coding agent can implement the technical *building blocks* a legal review will likely require anyway (purpose-limitation logging for vault access, a data-deletion/right-to-erasure path for `data/vault/*`, an access log of what was read/filled and when) — but whether the system *as a whole* is compliant is a judgment call for you or counsel, not something to mark "done" in a PR.
- Pilot rollout / real-user consent flow design — product and legal, not implementation.

---

## Appendix — mapping table

| Finding | Your own plan's item | Phase | Status before this plan |
|---|---|---|---|
| Z1 — false auth/OTP positive from page text | P0-18 | 3 | Spec'd in your plan, never implemented |
| Z2 — `_handle_no_action` ignores page_type | P0-13 (partially) | 1 | Not spec'd this precisely; folded into Phase 1's typed result |
| Z3 — no way to populate the vault | *(not in your plan)* | 2 | New |
| Z4 — flat element-cap truncation | P0-14/15 (adjacent, not identical) | 4 | Partially fixed today (20→120); ranking not spec'd anywhere |
| Z5 — silent malformed-JSON parse | P0-13 | 1 | Spec'd in your plan, never implemented |
| Z6 — anonymous default model, no guardrail | *(not in your plan)* | 5 | New |
| Z7 — vision fallback unwired | P0-16 | 6 | Spec'd in your plan, never implemented |
| Z8 — silent deterministic-only fallback | P0-37 | 1 | Spec'd in your plan, never implemented at all |

---

## Handing this to your coding agent

1. Give it three files together: `context_fix_plan.md` (already in the repo — keep its Section 1 protocol as the enforced process), `audit-zero-action-stall.md`, and this plan.
2. Tell it explicitly: work phase by phase, in the order above — Phase 1 first, always. Nothing after Phase 1 is fully verifiable until "is the LLM even running" is visible in workflow state.
3. After every phase: run the full suite, confirm the count is ≥ 374 plus whatever new tests that phase added, and only then move on. This is your own non-negotiable rule #10 ("never claim a phase works because a module exists; prove the runtime path with tests") — keep holding it to that.
4. Ask it to append its own remediation-log entries to `browser-agent-audit.md` in the same style already used there (`Zn <short name> | what changed | files touched`), so the audit trail stays continuous instead of forking into a separate document.
