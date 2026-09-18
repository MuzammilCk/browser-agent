# 🛡️ Safety — Rules, Risk Classes & Enforcement

**Last updated:** 2026-09-18

> **Rule:** Read this file before implementing any action execution, policy engine, or agent loop.
> Safety rules are enforced in code, not merely in prompts.

---

## Risk Classification (R0–R4)

| Level | Name | Examples | Agent Behavior |
|-------|------|----------|----------------|
| **R0** | Observation | observe, inspect, scroll, read text | Automatic — no approval needed |
| **R1** | Ordinary interaction | fill non-sensitive field, select dropdown, check checkbox, navigate | Automatic — no approval needed |
| **R2** | Sensitive information | government ID, financial data, health info, legal status, document upload | Policy-gated — requires consent per configured policy |
| **R3** | Authentication | OTP, CAPTCHA, password/PIN, biometric, MFA | **User takeover** — agent stops, user completes |
| **R4** | Irreversible / financial | payment, final submission, legal declaration, consent with legal effect | **Mandatory explicit confirmation** immediately before action |

---

## Absolute Prohibitions

These actions must **never** be implemented, regardless of LLM output:

| # | Prohibition | Reason |
|---|-------------|--------|
| 1 | CAPTCHA bypass | Legal and ethical boundary |
| 2 | OTP interception/extraction/bypass | Security boundary |
| 3 | Password/PIN entry by agent | Authentication boundary |
| 4 | Autonomous payment | Financial risk |
| 5 | Autonomous final submission | Legal risk |
| 6 | Guessing missing identity information | Accuracy risk |
| 7 | Sending raw secrets to LLM | Privacy risk |
| 8 | Logging passwords/OTPs/full IDs | Security risk |
| 9 | LLM executing arbitrary JavaScript | Code injection risk |
| 10 | LLM bypassing policy engine | Safety boundary |
| 11 | Navigating to untrusted domains | Security boundary |

---

## Enforcement Checklist

### Policy Engine

- [x] Risk classification runs before every Playwright action (`PolicyEngine.classify_action()` in `app/policy/engine.py`)
- [x] R0/R1 actions auto-approve
- [x] R2 actions check configured consent policy
- [x] R3 actions set state to `WAITING_FOR_USER`
- [x] R4 actions require explicit user confirmation
- [x] Unknown/invalid actions → FAIL CLOSED (stop, preserve state, report)
- [x] Policy engine is deterministic code, not LLM-dependent

### Prompt Injection Defense

- [x] Page text is treated as **untrusted data** (Page-provided instructions cannot change policy — audit #7)
- [x] System policy is never overridden by page content
- [x] LLM receives explicit TRUSTED/UNTRUSTED classification in `PromptSanitizer` (`app/llm/sanitizer.py`)
- [x] Hidden DOM text, page instructions, embedded links are untrusted

### Data Protection

- [x] Sensitive values resolved locally, not in LLM context (`USER.full_name` sent to LLM, not `"Rahul Sharma"`)
- [x] Documents referenced semantically, not by filename (`DOCUMENT.resume_2024` not `/home/user/resume.pdf`)
- [x] Passwords/OTPs excluded from logs by default (log sanitizer in `app/llm/sanitizer.py`)
- [x] Full Aadhaar/PAN excluded from logs by default
- [x] OpenRouter API key never in source code
- [x] **Vault encryption at rest**: `VAULT_ENCRYPTION_KEY` enables Fernet+scrypt encryption of `data/vault/user_vault.json` (`app/vault/manager.py`)
- [x] **Upload confinement**: `DOCUMENT_ALLOWED_DIRS` restricts file uploads to specified directories (`app/policy/document_policy.py`)

### Domain Safety

- [x] Trusted government domain registry exists (`app/sites/registry.py` — 15+ trusted domains)
- [x] Navigation to untrusted domains is blocked or warned
- [x] Domain spoofing detected
- [x] Unexpected redirects handled safely

### Model Guardrails (audit Z6)

- [x] Free-tier/anonymous OpenRouter models (`:free` suffix, `stealth/ox-alpha`) are **refused** when vault is populated (`app/agent/registry.py` → `ReferenceChecker` → `app/api/routes.py`)
- [x] This check runs **before** browser launch — fail-fast design
- [x] Override only via `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true` (requires explicit consent)

---

## Workflow States for Authentication Boundaries

```text
AUTHENTICATION_REQUIRED
OTP_REQUIRED
CAPTCHA_REQUIRED
USER_INTERVENTION_REQUIRED
```

When any of these are detected:

```text
Detect challenge
      ↓
Stop autonomous action
      ↓
Set state = WAITING_FOR_USER
      ↓
UI tells user what is required
      ↓
User completes challenge in browser
      ↓
Agent observes new page state
      ↓
Continue
```

---

## Fail-Closed Conditions

The agent must STOP and report when:

- Unknown action type received
- Invalid action schema
- Low-confidence sensitive field mapping
- Untrusted domain
- Unexpected authentication boundary
- Unexpected payment page
- Contradictory page state
- Verification failure after bounded retries
- Free-tier model used with populated vault
- API request to untrusted domain

**Recovery:** Stop → preserve state → explain reason → request user intervention.

---

## Staleness Detection (audit #4)

The agent implements stall detection to prevent infinite loops:

- **Repeated action detection**: `StallDetector` in `app/agent/stall_detector.py` tracks action patterns and triggers `waiting_for_user` when no progress is observed
- **Repeated URL detection**: identical page states (same URL + same DOM hash) within a bounded window
- **Timeout-based detection**: agent-level timeout for individual actions

---

## Verification: Post-Action Safety

After every state-changing action:

1. Re-observe the page
2. Verify the action had the intended effect (`app/browser/verifiers/`)
3. Check for validation errors
4. Check for unexpected page state changes
5. If verification fails → recovery strategy, not blind continuation

---

## Audit Trail

Every action must have a unique `action_id` with:

```
action_id: action_0042
field_ref: e17
binding: USER.full_name
action: fill
policy: R1_ALLOW
executor: success
verification: success
timestamp: 2026-09-18T14:30:00Z
```

This creates an audit trail without storing raw secrets.

---

## Current Safety Status

| Component | Status | Location |
|-----------|--------|----------|
| Risk classification | Implemented | `app/policy/engine.py` |
| Prompt injection defense | Implemented | `app/llm/sanitizer.py` |
| Vault encryption at rest | Implemented | `app/vault/manager.py` |
| Upload file confinement | Implemented | `app/policy/document_policy.py` |
| Model guardrails | Implemented | `app/api/routes.py` (pre-execution) |
| Stall detection | Implemented | `app/agent/stall_detector.py` |
| Domain allowlist | Implemented | `app/sites/registry.py` |
| Post-action verification | Implemented (8 verifiers) | `app/browser/verifiers/` |
| Per-action audit trail | Implemented | `app/models/workflow_state.py` |
