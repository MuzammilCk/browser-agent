# 🛡️ Safety — Rules, Risk Classes & Enforcement

**Last updated:** 2024-08-24

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

### Policy Engine (Phase 8)

- [ ] Risk classification runs before every Playwright action
- [ ] R0/R1 actions auto-approve
- [ ] R2 actions check configured consent policy
- [ ] R3 actions set state to `WAITING_FOR_USER`
- [ ] R4 actions require explicit user confirmation
- [ ] Unknown/invalid actions → FAIL CLOSED (stop, preserve state, report)
- [ ] Policy engine is deterministic code, not LLM-dependent

### Prompt Injection Defense (Phase 10)

- [ ] Page text is treated as **untrusted data**
- [ ] System policy is never overridden by page content
- [ ] LLM receives explicit TRUSTED/UNTRUSTED classification
- [ ] Hidden DOM text, page instructions, embedded links are untrusted

### Data Protection

- [ ] Sensitive values resolved locally, not in LLM context
- [ ] `USER.full_name` sent to LLM, not `"Rahul Sharma"`
- [ ] Documents referenced semantically, not by filename
- [ ] Passwords/OTPs excluded from logs by default
- [ ] Full Aadhaar/PAN excluded from logs by default
- [ ] OpenRouter API key never in source code

### Domain Safety

- [ ] Trusted government domain registry exists
- [ ] Navigation to untrusted domains is blocked or warned
- [ ] Domain spoofing detected
- [ ] Unexpected redirects handled safely

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

**Recovery:** Stop → preserve state → explain reason → request user intervention.

---

## Verification: Post-Action Safety

After every state-changing action:

1. Re-observe the page
2. Verify the action had the intended effect
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
timestamp: 2024-08-24T10:30:00Z
```

This creates an audit trail without storing raw secrets.
