# Zero-Action Automation Stall — Root Cause Audit

**Repo audited:** `MuzammilCk/browser-agent`, `origin/main @ fd1eb5e` ("feat: audit hardening, agent planner fixes, and automation UI improvements", Aug 25 2026, 18:56 IST)
**Symptom under investigation:** browser opens and navigates, but no automation action is ever visibly executed.
**Scope:** backend agent/orchestration logic only, per request (UI/UX explicitly excluded).
**No code was modified.** Two throwaway repro scripts were written and run *outside* the repo tree, importing the repo's real, unmodified modules, purely to turn "I read this and think X happens" into "I ran this and X happened." They are not part of the deliverable and touch nothing in your tree.

---

## TL;DR — Playwright, LLM, or agent execution?

**Agent execution/orchestration — not Playwright, and not "the LLM lacks intelligence."**

Every root cause below is the scaffolding *around* the model failing in one of two ways:
1. **Starving it of information** it needed to act (truncated element list, an empty data vault with no fill values, no fallback when accessibility-tree perception comes up empty), or
2. **Misinterpreting its silence or a benign signal as something else** (a help-page mention of "CAPTCHA" is read as a live challenge; a deliberate/benign "nothing to do here yet" is read as "form complete"; a malformed JSON response is read identically to "no action needed").

Playwright itself — the executor, the locator-resolution strategy, the verifiers — is in good shape; nothing in this audit implicates it. Your instinct that "perception" is the weak point is directionally right, but the fix is not a smarter model — it's fixing what the model is shown and how its output (including its *absence* of output) is interpreted.

---

## 1. Method

- Pulled `origin/main` fresh (`71d2043` → `fd1eb5e`; the latter landed today and already fixes several real bugs — see §3).
- Installed deps, ran the full suite: **374 passed, 0 failed** (`pytest tests/ -q --ignore=tests/real_sites`).
- Read `observer.py`, `planner.py`, `runner.py`, `executor.py`, `openrouter.py`, `routes.py`, `settings.py`, `vault/*.py` end-to-end, not just the diff.
- Cross-checked every claim below against your own `browser-agent-audit.md` and its "Remediation log" so I don't re-report what you already found and fixed — I verified the remediation claims directly in code rather than taking the log at its word (see Z3, where the log's claim is technically true but incomplete).
- Where a claim was falsifiable without live OpenRouter/government-site access (not available from this sandbox), I built a minimal fixture, imported your actual classes, and ran it. Two findings below have real stdout attached.

---

## 2. Ranked findings

### Z1 — [HIGH · confirmed by repro · still open] Ordinary page text can trip a false auth/OTP halt on the very first observation

`observer.py::_detect_auth_challenge` scans the accessible name/label/placeholder of **every element on the page** (not just form fields) for keyword substrings:

```python
if any(kw in name_lower + label_lower + placeholder_lower
       for kw in ["otp", "one-time", "verification code", "enter code", "captcha"]):
    has_otp_field = True
    ...
```

Note `"captcha"` is in the **OTP** keyword list, and this branch runs before the dedicated CAPTCHA-text branch. Any element — including a plain `<a>` link, not a form field — whose accessible name merely *mentions* the word is enough.

**Repro (real code, real classes, no mocking of the function under test):**
```
elements = [Home, About Us, Apply Online, Track Application Status,
            "Help: How to complete the CAPTCHA during registration",
            Search button]

>>> PageObserver()._detect_auth_challenge(elements, [], [])
detected       = True
challenge_type = otp
confidence     = 0.9
reason         = OTP element detected: otp_field: Help: How to complete
                  the CAPTCHA during registration
```
A footer/FAQ link that merely explains the CAPTCHA process to users — extremely common on Indian government portals — is enough to make the observer report a live OTP challenge with 90% confidence, on a page that has neither OTP nor CAPTCHA. `_check_auth` in `runner.py` halts unconditionally on this (`return True` → loop breaks), on **iteration 1**, before the actual task is ever attempted.

This is a different bug from your own C6 finding. C6 is about `sites/registry.py` task *instructions* coaching the model to solve CAPTCHAs — a static-text problem, already sanitized today. Z1 is live DOM scanning on every single observation, completely independent of what the task instructions say. Sanitizing instructions does nothing for this path.

Not touched by today's commit (`observer.py` doesn't appear in the `fd1eb5e` diff).

---

### Z2 — [HIGH · confirmed by repro · still open] `_handle_no_action` never looks at `page_type` — a stalled planner on a menu page is reported as "done"

```python
def _handle_no_action(self, workflow, mapping) -> None:
    if workflow.error_state == "recoverable" and workflow.error_message:
        workflow.status = WorkflowStatus.WAITING_FOR_USER
        ...
        return
    if not mapping.unmapped_fields and not mapping.ambiguous_fields:
        workflow.status = WorkflowStatus.READY_FOR_SUBMISSION   # <-- here
        ...
```

`observer.py::_classify_page_type` already has a `"navigation"` category for link/button-only pages with no form fields — the classifier correctly recognises a portal landing/menu page as distinct from a form. But `_handle_no_action` never consults `workflow.current_page_type`. Its only signal is "are there zero unmapped/ambiguous form fields" — which is trivially true on any page that has no fields at all, i.e. every portal homepage, before a single link has been clicked.

**Repro:**
```
workflow.current_page_type = "navigation"
mapping = MappingResult()   # zero unmapped, zero ambiguous — nothing to map

>>> AgentRunner(llm=None)._handle_no_action(workflow, mapping)
workflow.status            = WorkflowStatus.READY_FOR_SUBMISSION
workflow.submission_state  = ready
workflow.actions_taken     = []
```
The workflow ends by claiming to be **ready to submit** having done **nothing at all**. This is worse than "looks stuck" — it's false positive completion, which is a serious failure mode for something you want enterprise-ready: a downstream consumer (a human reviewer, or eventually an auto-submit step) has no signal that anything is wrong.

Today's prompt change (rule 9: "do NOT stop merely because the target is not in the visible list") reduces how *often* the model outputs a bare "stop" here, but it doesn't close the gap structurally — any remaining "stop" (semantic mismatch between task wording and the portal's actual link text, model caution, an off day) still gets mislabeled as completion rather than surfaced as "stuck, please look." Confirmed via `grep`: **no test in the suite constructs `page_type="navigation"`** — every existing fixture defaults to `page_type="form"`, so this exact scenario, the one nearly every real task starts in, has zero coverage.

---

### Z3 — [HIGH · most likely everyday explanation · partially misdescribed in your own remediation log] There is currently no way to put your own data into the system

Your own audit's C2 said the vault was disconnected from the runtime. Today's fix genuinely wires it — I verified this directly rather than trusting the log:

```python
# routes.py, _run_automation
vault_manager = VaultManager(settings.data_dir / "vault", encryption_key=...)
wf["vault_loaded"] = any(bool(v) for v in vault_data.values())
if not wf["vault_loaded"]:
    logger.warning("Automation %s: vault is empty — value_ref fills will fail. "
                    "Populate data/vault/user_vault.json first.", workflow_id)
runner = AgentRunner(..., vault=vault_manager.vault, ...)
```
That part of the C2 remediation-log entry is accurate: the vault *is* now wired to the executor. What it doesn't mention: on a fresh clone (I checked — this is not present in the repo and not created by any setup step), **`data/vault/` does not exist, and nothing in the codebase creates or populates it.** I searched for a route, a CLI command, anything:
```
grep -rn "def.*vault\|/api/vault" app/api/routes.py app/vault/*.py
→ no /api/vault route of any kind
```
`UserVault` (35+ typed fields — `full_name`, `date_of_birth`, `mobile`, `address`, …) has no onboarding path at all right now. So on essentially any first real run:
- **Deterministic planner:** every field's `_resolve(binding.binding)` returns `None` → `continue`s past every single field → returns no action → falls straight into Z2.
- **LLM planner:** may still emit a `fill` action (it only sees the reference name, e.g. `USER.full_name`, not whether it actually resolves) → the *executor* resolves it at execution time, finds nothing, and returns a clear `"No value provided (value_ref unresolved or literal_value missing)"` failure — but this is treated as `recovery_required`, so it burns through the retry budget before finally landing on a legible `FAILED` state rather than surfacing immediately.

This is arguably the single most mundane explanation for your report, and it would present almost identically to Z1/Z2 — browser opens, nothing visibly happens — because a deterministic-mode run with an empty vault produces literally zero actions before you even get to see whether perception or planning was the problem.

---

### Z4 — [MEDIUM · self-diagnosed and largely fixed today · residual risk] Element list to the LLM was hard-capped at 20, now 120

Your own commit message: *"raise LLM element context cap 20 → 120 (target links were invisible on large portal pages, causing 0-action stops)"*. That's a first-party confirmation this exact class of bug has already bitten you in testing. The fix is real but still a flat ceiling with no prioritization, retrieval, or paging:
```python
_MAX_ELEMENTS_FOR_LLM = 120
visible_elements = elements_info[:_MAX_ELEMENTS_FOR_LLM]
```
Dense portals (GST, EPFO, income-tax e-filing, anything with a mega-menu and a language switcher) can plausibly exceed 120 interactive elements on a single landing page. The user-facing prompt does now say `"; list truncated to first 120"` when this happens, which at least makes the truncation legible in the trace — an improvement, not a full fix.

---

### Z5 — [MEDIUM · confirmed, still open] A non-conforming LLM response is indistinguishable from "nothing to do"

```python
# openrouter.py::_parse_response
parsed = None
if content:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        pass   # "that's okay for non-schema requests"
```
The comment is accurate for free-text requests but this same code path serves the **schema-constrained** planning call too. `response_format: {"type": "json_schema", "strict": true}` is sent correctly (verified — this part of the gateway is solid), but not every model routed through OpenRouter honors `strict` mode, particularly free/anonymous ones (see Z6). When a model ignores it and returns non-JSON or wrapped JSON (```` ```json ... ``` ````, trailing prose, truncated output), `parsed` becomes `None` with **no exception raised anywhere** — so `plan_with_llm`'s exception handler (which today correctly sets `workflow.error_state = "recoverable"`) never fires. This silently degrades to the exact same `_handle_no_action` path as Z2, with no error attached, so even the query "did the LLM fail, or did it succeed and rule the task complete?" becomes unanswerable from the workflow state.

---

### Z6 — [MEDIUM · context, not a bug per se] Default model is still an anonymous free-tier "stealth" model; no model-tier router exists

```python
openrouter_model: str = Field(
    default="stealth/ox-alpha",
    description="... anonymous free-tier model with contested data retention ...",
)
```
This is clearly flagged in the field description as unsuitable for production/PII, which is good practice — but it's still the operative default if `OPENROUTER_MODEL` isn't explicitly set in your real `.env` (the `.env.example` template shows a named Claude model, but a template isn't your actual `.env`). Worth a 30-second check of your own `.env` before looking anywhere else, because everything upstream (perception reasoning, field mapping, planning) currently rides on **one single configured model string** — I confirmed by grep that the "Capability Registry" / task-tiered "Model Router" concept from the original architecture plan doesn't exist in code yet (`OpenRouterGateway` is a flat single-model-plus-one-fallback client). An anonymous free model is also the one most likely to ignore `strict` JSON mode, which is exactly what feeds Z5.

---

### Z7 — [MEDIUM · already in your own audit as C10, independently reconfirmed, still open] Visual grounding fallback exists but is never invoked

`app/browser/vision.py` has `assess_completeness` and `capture_screenshot_for_fallback`. I grepped the entire agent loop and API for any call site:
```
grep -rn "vision\|capture_screenshot\|assess_completeness" app/agent/*.py app/api/routes.py
→ no matches
```
Zero. This matches your own audit's C10 note almost verbatim ("vision fallback ... trigger-without-integration") — today's remediation only fixed *which* model gets used *if* an image request is ever made (`openrouter_vision_model` routing), it did not add the call site that would actually invoke it. So right now there is exactly one perception path (the ARIA/accessibility tree), and no fallback when it comes up empty on a poorly-marked-up page — which is common on older Indian government sites. This is the one finding closest to your original hypothesis, but the honest framing is "the fallback perception path is unwired," not "the model is unintelligent."

---

## 3. What's *not* broken (so effort doesn't get redirected wrongly)

- **Playwright / executor / verifiers.** Locator resolution, fill/select/check verification against live DOM, press/go-back verifiers — all solid, all tested, nothing here implicated in the stall.
- **Today's C1 (confirmation dead-end) and C2 (vault wiring) fixes are real.** I read the actual diff, not just the commit message: `resume()` now re-validates the target's identity, re-evaluates policy, re-enters the shared loop, and the vault is genuinely constructed from disk and passed through — a plausible last-minute end-to-end regression was checked and isn't there.
- **C9 (weak KDF) fix is real**: salted scrypt, versioned format, legacy-file upgrade path.
- **Test discipline is unusually good for this stage**: 374 passing, and the team (you) is clearly running your own adversarial audits rather than assuming green tests mean done — which is exactly how Z2's coverage gap became visible to me (by noticing what *wasn't* tested, not what failed).

---

## 4. Five-minute diagnostic — figure out which of these you actually hit

No code changes needed for this part, just look:

1. **Grep your own server console output** from the run that stalled, for these exact literal strings:
   - `"Auth detected:"` → Z1 (false auth/OTP/CAPTCHA halt)
   - `"vault is empty"` → Z3 (no data to fill with)
   - `"Planner stopped:"` → deliberate LLM stop — check the reason text, then cross-reference Z2
   - `"LLM planning failed:"` → a real exception (network/auth/rate-limit to OpenRouter) — different from Z5
2. **Check `data/vault/user_vault.json`** — does it exist, and is it non-empty? (It won't exist on a fresh clone — see Z3.)
3. **Check the workflow status at the moment it stopped** — was it `ready_for_submission` with an empty `actions_taken` (Z2), `waiting_for_auth` / `waiting_for_captcha` on the very first page (Z1), or `failed` with a "no value provided" message (Z3 surfacing correctly, just late)?
4. **Check your actual `.env`** for `OPENROUTER_MODEL` — confirm it's not silently falling back to `stealth/ox-alpha` (Z6).

---

## 5. Suggested order of attack (priority only — no code here per your instruction)

1. **Z3** — nothing else matters until there's real data to fill forms with; this blocks every other finding from even being observable.
2. **Z1** — a single mislabeled help link shouldn't be able to freeze the entire run; highest blast-radius-to-effort ratio.
3. **Z2** — make page_type part of the completion signal; this is what turns silent stalls into loud, correct ones.
4. **Z6** — pin the model explicitly and confirm it in a log line at startup, so "which model actually ran" is never a mystery during debugging.
5. **Z5** — treat an unparseable structured-output response as an error, not as silence.
6. **Z4** — replace the flat 120-cap with something that prioritizes by task-keyword relevance instead of raw DOM order, or paginate.
7. **Z7** — wire the existing vision utilities into the loop as the fallback they were built to be, once 1–3 are solid enough that you can tell the difference between "vision would have helped" and "the loop just wasn't given the chance."

---

## 6. On your hypothesis

You said: *"even if everything is wired, it still doesn't know what to do... the system must be lacking in intelligence perceptiveness."*

Based on everything above: not quite. Every confirmed finding is the system either withholding information the model needed (Z3, Z4, Z7) or mis-reading a signal that had nothing to do with reasoning quality — a help link's wording (Z1), the absence of an action (Z2), a formatting slip (Z5). None of these are "the model couldn't figure out what to do" in the reasoning sense; they're "the model was never shown the real situation, or its answer got relabeled by the code around it." Z6 is the one place actual model capability is a live variable — worth pinning down and confirming, but it's a secondary factor, not the headline cause.
