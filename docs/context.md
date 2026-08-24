# CONTEXT.md — Government Form-Filling Browser Agent

**Purpose:** This file is the primary context/instruction document for the coding agent implementing the project.

**Project status:** Architecture defined; implementation is now starting.

**Scope:** Browser agent only. Do NOT implement the Companion AI / full-duplex voice layer in this project unless explicitly requested later.

**Primary LLM gateway:** OpenRouter API.

**Primary browser automation:** Playwright + Chromium.

**Primary page perception:** Playwright accessibility/ARIA snapshot + targeted DOM metadata.

**Visual fallback:** Screenshot + a vision-capable model through OpenRouter, only when semantic browser perception is insufficient.

---

# 1. WHAT WE ARE BUILDING

We are building a **government form-filling browser agent**.

The user gives the agent an official government-service URL and a task such as:

> "Fill this application using my saved information."

The agent opens the **real government website** in a Playwright-controlled Chromium browser. It does NOT recreate the government form inside our application.

The agent repeatedly:

```text
Observe current webpage
        ↓
Normalize browser state
        ↓
Understand fields / controls / page state
        ↓
Map known user data to fields
        ↓
Choose one safe browser action
        ↓
Policy / risk check
        ↓
Execute with Playwright
        ↓
Verify result
        ↓
Observe again
        ↓
Continue / ask user / stop
```

The system must work against the **live website**, not against copied/simulated government forms.

---

# 2. IMPORTANT: WHAT THIS IS NOT

Do NOT build the project as:

- a collection of hardcoded scripts for individual government websites;
- a form-recreation website;
- a screenshot-only browser agent;
- OCR-first automation;
- an LLM that receives arbitrary HTML and writes JavaScript selectors;
- an autonomous CAPTCHA solver;
- an OTP/MFA bypass system;
- an autonomous payment system;
- an autonomous legal-declaration/final-submission system;
- a system that guesses missing sensitive information;
- a system that stores government credentials casually in logs or prompts.

The intended system is a **semantic, state-aware, human-safe browser agent**.

---

# 3. KEY ARCHITECTURE DECISION

The project uses a local application/backend as the control plane and Playwright as the browser execution engine.

Initial MVP:

```text
Local Web UI
     ↓
Backend / Workflow Manager
     ↓
OpenRouter LLM
     ↓
Policy / Guardrail Layer
     ↓
Playwright
     ↓
Playwright-controlled Chromium
     ↓
REAL government website
```

Do NOT start with a Chrome extension.

A browser extension may be added later as a polished user interface/bridge, but the first implementation must use a Playwright-controlled browser because it minimizes architecture complexity and lets us validate the core agent loop first.

The user's web app is NOT a clone of the government website. It is only a control panel.

Example MVP UI:

```text
Government Browser Agent

Official Website URL:
[ https://....gov.in ]

Task:
[ Fill this application using my saved information ]

[ Start Browser ]

Agent Activity:
✓ Browser started
✓ Page observed
✓ Form detected
✓ Fields mapped
✓ Field filled
⚠ OTP required — user action needed
```

---

# 4. TECHNOLOGY STACK

## Required

- Python 3.12+
- Playwright for Python
- Chromium via Playwright
- asyncio
- Pydantic
- httpx
- OpenRouter API
- SQLite initially
- Minimal local web UI (FastAPI + simple frontend is acceptable)

## LLM

All LLM calls must go through **OpenRouter**.

Do not integrate the OpenAI API directly unless explicitly requested later.

OpenRouter should be treated as the model gateway so the underlying model can be changed via configuration.

Recommended environment variables:

```env
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=...
OPENROUTER_VISION_MODEL=...
OPENROUTER_TIMEOUT_SECONDS=60
```

Never hardcode the API key.

Do not hardcode one model name throughout the source code.

---

# 5. HIGH-LEVEL ARCHITECTURE

```text
                         ┌──────────────────────┐
                         │     Local Web UI     │
                         │  URL + task + logs   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Workflow Manager    │
                         └──────────┬───────────┘
                                    │
             ┌──────────────────────┼─────────────────────┐
             │                      │                     │
             ▼                      ▼                     ▼
       User Profile            Documents              Policy
             │                      │                     │
             └──────────────────────┼─────────────────────┘
                                    ▼
                         ┌──────────────────────┐
                         │      OpenRouter      │
                         │   LLM reasoning      │
                         └──────────┬───────────┘
                                    │
                             typed action JSON
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   Action Policy Gate │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      Playwright      │
                         │ browser controller   │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────┼────────────────┐
                    ▼               ▼                ▼
             ARIA Snapshot    DOM Metadata      Screenshot
                    │               │                │
                    └───────────────┼────────────────┘
                                    ▼
                              PageState
                                    │
                                    └──────→ OpenRouter
```

The LLM is the **reasoning component**.

Playwright is the **execution component**.

The application's policy layer is the **safety/authorization component**.

The state layer is the **memory/control component**.

---

# 6. CORE AGENT LOOP

The fundamental loop is:

```text
OBSERVE
  ↓
NORMALIZE
  ↓
REASON
  ↓
POLICY CHECK
  ↓
EXECUTE ONE ATOMIC ACTION
  ↓
VERIFY
  ↓
RE-OBSERVE
```

Never assume that an action succeeded merely because Playwright returned without an exception.

For example:

```text
fill DOB
  ↓
verify value
  ↓
check validation state
  ↓
only then continue
```

For dynamic forms:

```text
select State
  ↓
observe again
  ↓
District options changed
  ↓
map District
  ↓
select District
```

Do NOT generate a long sequence of clicks/fills based on a single initial screenshot/state snapshot.

---

# 7. PAGE PERCEPTION STRATEGY

## Primary

Use Playwright's accessibility/ARIA representation and targeted DOM metadata.

Extract useful information such as:

- role
- accessible name
- associated label
- input type
- value/state
- required status
- disabled status
- checked status
- selected option
- visible text
- placeholder
- relevant semantic attributes
- validation messages
- alerts
- buttons
- links
- dialogs
- frames/iframes

## Secondary

Use targeted DOM metadata where accessibility information is incomplete.

## Tertiary

Use screenshots and vision through OpenRouter only when the semantic representation is insufficient.

Examples:

- visually rendered controls with poor accessibility metadata;
- canvas-based UI;
- visual relationship between text and control cannot be established;
- unusual custom widgets;
- layout-dependent interpretation.

Do NOT take/send screenshots continuously by default.

Do NOT perform OCR on the entire website by default.

---

# 8. PAGESTATE CONTRACT

The browser observation layer must normalize the live page into a typed PageState object.

Conceptually:

```json
{
  "url": "https://example.gov.in/form",
  "title": "Application Form",
  "page_type": "form",
  "elements": [
    {
      "ref": "e12",
      "role": "textbox",
      "name": "Applicant Full Name",
      "label": "Applicant Full Name",
      "type": "text",
      "required": true,
      "disabled": false,
      "value": ""
    },
    {
      "ref": "e13",
      "role": "combobox",
      "name": "State",
      "required": true,
      "options": ["Kerala", "Tamil Nadu"]
    }
  ],
  "buttons": [],
  "links": [],
  "alerts": [],
  "validation_errors": [],
  "frames": []
}
```

Implement this as Pydantic models.

Do not expose arbitrary raw HTML to the LLM unless a targeted diagnostic actually requires it.

---

# 9. SEMANTIC FIELD MAPPING

The agent must map website fields to user-data references.

Examples:

```text
"Applicant Full Name"
        ↓
USER.full_name
```

```text
"Name as per Aadhaar"
        ↓
USER.aadhaar_name
```

The model should return the semantic binding, not unnecessarily receive or repeat the sensitive value.

Example:

```json
{
  "field_ref": "e12",
  "binding": "USER.full_name",
  "confidence": 0.98,
  "reason": "The field explicitly requests the applicant's full name."
}
```

The application resolves the reference locally.

Never allow the model to invent user-data references.

Unknown references must be rejected by Pydantic/policy validation.

---

# 10. USER PROFILE

Create a typed user data model with references such as:

```text
USER.full_name
USER.date_of_birth
USER.gender
USER.nationality
USER.mobile
USER.email
USER.address
USER.state
USER.district
USER.education...
USER.pan
USER.aadhaar_name
```

Do not put all personal data into every LLM request.

The LLM should primarily see references and only the minimum data necessary for reasoning.

Sensitive values should be resolved as late as possible in the local executor.

---

# 11. DOCUMENT MODEL

Documents should have semantic references:

```text
DOCUMENT.aadhaar
DOCUMENT.income_certificate
DOCUMENT.degree_certificate
DOCUMENT.passport_photo
DOCUMENT.signature
```

The LLM can request:

```json
{
  "action": "upload",
  "target_ref": "e32",
  "document_ref": "DOCUMENT.income_certificate"
}
```

The executor resolves the document reference locally.

Do not choose documents solely from filenames.

Document type must be known/confirmed in the local document registry.

---

# 12. BROWSER ACTION CONTRACT

The LLM must NOT emit arbitrary JavaScript or arbitrary Python.

Use typed actions only.

Initial action set:

```text
OPEN
CLICK
FILL
SELECT
CHECK
UNCHECK
UPLOAD
SCROLL
WAIT
GO_BACK
REQUEST_USER_ACTION
STOP
```

Example:

```json
{
  "action": "fill",
  "target_ref": "e12",
  "value_ref": "USER.full_name",
  "confidence": 0.98
}
```

Example:

```json
{
  "action": "select",
  "target_ref": "e21",
  "option": "Kerala",
  "confidence": 0.99
}
```

Example:

```json
{
  "action": "request_user_action",
  "reason": "OTP is required by the website."
}
```

Every action must be validated against:

1. Action schema
2. Current PageState
3. Target existence
4. Target type
5. Policy/risk level
6. User-data binding validity

---

# 13. LOCATOR STRATEGY

Use a deterministic locator hierarchy.

Priority:

1. accessibility role + accessible name;
2. associated label;
3. placeholder/user-facing text where appropriate;
4. semantic attributes such as autocomplete/name/aria-label;
5. scoped DOM relationships;
6. visual fallback when necessary;
7. CSS/XPath only as a last-resort implementation detail.

Do not generate long brittle selectors as the normal approach.

The locator engine should re-resolve the target from the CURRENT page state rather than keep stale element handles wherever possible.

---

# 14. IF FRAMES/IFRAMES EXIST

PageState must record frames.

The browser observer must inspect relevant same-origin/cross-frame accessible content where Playwright permits it.

The action target must identify the correct frame context.

Never assume an element belongs to the top page.

---

# 15. VALIDATION

After state-changing actions, inspect:

- field value/state;
- aria-invalid;
- visible validation messages;
- required/disabled state;
- page alerts;
- disabled/enabled next/submit buttons;
- relevant changes in PageState.

Success means the browser's new state is consistent with the intended action.

Not merely:

```text
Playwright.fill() returned successfully
```

---

# 16. RISK POLICY

Classify actions before execution.

## LOW RISK

Can normally execute automatically:

- navigate within trusted workflow;
- scroll;
- inspect;
- open menus;
- fill ordinary non-sensitive fields;
- select ordinary values;
- check/uncheck non-sensitive options.

## SENSITIVE

Require stronger validation and potentially user approval according to configurable policy:

- government ID fields;
- financial information;
- sensitive demographic/category information;
- document uploads;
- legally significant answers.

## AUTHENTICATION

Agent must stop/request user action:

- password entry;
- OTP;
- MFA;
- CAPTCHA;
- biometric authentication.

Do not bypass or solve these through prohibited automation.

## IRREVERSIBLE / HIGH-RISK

Require explicit user confirmation:

- payment;
- final submission;
- legal declaration;
- consent with legal effect;
- irreversible account/service changes.

The agent may prepare the page but must stop before final irreversible action.

---

# 17. CAPTCHA / OTP RULE

Never implement CAPTCHA bypass.

Never implement OTP interception/extraction/bypass.

Correct behavior:

```text
Agent detects OTP
       ↓
state = WAITING_FOR_USER
       ↓
UI tells user what is required
       ↓
User completes the step in browser
       ↓
Agent observes new page state
       ↓
Continue
```

Same pattern for CAPTCHA and other authentication challenges.

---

# 18. OFFICIAL DOMAIN SAFETY

The system should maintain a trusted government-domain registry.

Do not blindly navigate to arbitrary domains based only on an LLM interpretation of a search result.

For a known supported portal, store metadata such as:

```json
{
  "domain": "example.gov.in",
  "official": true,
  "supported": true,
  "authentication": ["password", "otp", "captcha"],
  "has_payment": true,
  "final_submission_requires_confirmation": true
}
```

The registry is configuration, not a hardcoded full workflow.

A site adapter may contain exceptional rules when genuinely necessary, but should not reproduce the entire website workflow as a script.

---

# 19. OPENROUTER RESPONSIBILITIES

Use OpenRouter for tasks that benefit from model reasoning:

- classify current page;
- understand user task;
- map semantic field meaning to user-data references;
- interpret ambiguous labels;
- choose next safe action;
- resolve dynamic form semantics;
- determine whether clarification is required;
- interpret visual fallback observations.

Do NOT ask the LLM to perform deterministic tasks that normal code can do:

- locating an element when a deterministic locator already exists;
- validating JSON schema;
- checking whether a ref exists;
- checking permissions;
- resolving a local user-data reference;
- executing the browser command;
- persisting workflow state.

---

# 20. OPENROUTER CALL DESIGN

Use structured output / JSON schema for agent decisions.

At minimum, define schemas for:

```text
PageInterpretation
FieldBinding
AgentAction
ClarificationRequest
CompletionDecision
```

The backend must reject malformed/unknown actions before execution.

Use low temperature/deterministic generation settings where supported/appropriate.

Do not depend on model-specific undocumented behavior.

The model is configurable through environment variables.

---

# 21. LLM CONTEXT SENT TO OPENROUTER

Each request should contain only the minimum relevant state.

Conceptual structure:

```text
SYSTEM
  Agent rules / safety policy

TASK
  User task

USER DATA SCHEMA
  Allowed semantic references only

WORKFLOW STATE
  Current workflow step/status

PAGE STATE
  Current normalized browser state

PREVIOUS ACTION + VERIFICATION
  What just happened

REQUEST
  Decide the next safe action
```

Do not send the entire user profile or all documents on every request.

Do not send raw passwords or OTPs.

Do not persist sensitive prompts to ordinary logs.

---

# 22. AGENT DECISION PROCESS

For every cycle:

1. Inspect current PageState.
2. Determine page type/state.
3. Determine whether the workflow is blocked by authentication or another protected boundary.
4. Identify unfilled/relevant fields.
5. Map available data.
6. Check confidence/ambiguity.
7. Select one action.
8. Run policy validation.
9. Execute.
10. Verify.
11. Record event.
12. Re-observe.

If ambiguity is material, ask the user rather than guess.

---

# 23. WORKFLOW STATE

Maintain a typed state machine.

Possible states:

```text
INIT
BROWSER_STARTING
NAVIGATING
OBSERVING
UNDERSTANDING
FILLING
VALIDATING
WAITING_FOR_USER
WAITING_FOR_AUTHENTICATION
REVIEW_REQUIRED
READY_FOR_SUBMISSION
SUBMITTED
FAILED
COMPLETED
STOPPED
```

State transitions must be explicit.

No hidden workflow transitions based solely on model text.

---

# 24. EVENT LOG / TRACE

Record safe operational events:

```text
browser_started
page_loaded
page_observed
field_mapped
action_requested
policy_approved
action_executed
action_verified
validation_detected
user_action_requested
workflow_paused
workflow_resumed
workflow_completed
workflow_failed
```

Do not log:

- passwords;
- OTPs;
- authentication secrets;
- full government IDs unless strictly required for secure debugging and properly protected;
- full uploaded document contents.

Store redacted references instead.

---

# 25. PROJECT STRUCTURE

Recommended initial structure:

```text
government-browser-agent/
│
├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── routes.py
│   │   └── schemas.py
│   │
│   ├── agent/
│   │   ├── agent.py
│   │   ├── prompts.py
│   │   ├── planner.py
│   │   ├── field_mapper.py
│   │   └── decision.py
│   │
│   ├── browser/
│   │   ├── controller.py
│   │   ├── observer.py
│   │   ├── page_state.py
│   │   ├── locator.py
│   │   ├── executor.py
│   │   ├── verifier.py
│   │   └── screenshot.py
│   │
│   ├── llm/
│   │   ├── openrouter.py
│   │   ├── schemas.py
│   │   └── retry.py
│   │
│   ├── policy/
│   │   ├── engine.py
│   │   ├── risk.py
│   │   └── rules.py
│   │
│   ├── state/
│   │   ├── workflow.py
│   │   ├── user_profile.py
│   │   ├── documents.py
│   │   └── events.py
│   │
│   ├── security/
│   │   ├── secrets.py
│   │   └── domains.py
│   │
│   └── sites/
│       ├── registry.json
│       └── adapters/
│
├── frontend/
│   ├── index.html
│   └── ...
│
├── tests/
│   ├── unit/
│   ├── browser/
│   ├── agent/
│   ├── safety/
│   └── portal_regression/
│
├── .env.example
├── pyproject.toml
├── README.md
└── context.md
```

The coding agent may adjust the exact structure when there is a strong implementation reason, but responsibilities must remain separated.

---

# 26. IMPLEMENTATION ORDER

Do NOT attempt to build the entire project at once.

## Milestone 0 — Repository bootstrap

Create:

- Python environment;
- Playwright;
- Chromium installation;
- Pydantic;
- httpx;
- FastAPI/minimal UI;
- environment configuration;
- tests.

Success condition:

```text
python starts
Playwright launches Chromium
local UI is reachable
```

---

## Milestone 1 — Browser Controller

Implement deterministic Playwright wrappers:

```text
launch
open
observe
click
fill
select
check
uncheck
upload
scroll
wait
go_back
screenshot
close
```

No LLM yet.

Success condition:

A test page can be opened and manipulated reliably through typed Python functions.

---

## Milestone 2 — Page Observer

Implement:

```text
ARIA/accessibility snapshot
+
targeted DOM metadata
+
validation/alert extraction
+
frame awareness
```

Normalize to PageState.

Success condition:

Given multiple synthetic HTML forms, the observer returns accurate structured PageState.

---

## Milestone 3 — Locator Engine

Implement deterministic target resolution from PageState refs.

Priority:

```text
role/name
→ label
→ placeholder/semantic metadata
→ scoped DOM
→ visual fallback
```

Success condition:

The same logical field can be located despite common DOM/class changes.

---

## Milestone 4 — OpenRouter Client

Implement:

- API client;
- authentication;
- timeout;
- retries with bounds;
- structured output parsing;
- model configuration;
- request/response logging with redaction.

Success condition:

A test PageState can be sent to OpenRouter and a valid Pydantic decision returned.

---

## Milestone 5 — Semantic Field Mapper

Implement field-binding reasoning.

Input:

```text
PageState + allowed USER.* references
```

Output:

```text
FieldBinding[]
```

Reject unknown references.

Success condition:

Synthetic forms with renamed labels can still map correctly where semantics are clear.

---

## Milestone 6 — Policy Engine

Implement action risk classification and approval gates.

Success condition:

Unsafe actions cannot reach Playwright even if the model requests them.

---

## Milestone 7 — Agent Loop

Implement:

```text
observe
→ OpenRouter
→ policy
→ Playwright
→ verify
→ observe
```

Success condition:

Agent can fill a synthetic multi-step form without hardcoded selectors.

---

## Milestone 8 — Human Checkpoints

Implement UI for:

- CAPTCHA;
- OTP;
- password/authentication;
- sensitive confirmation;
- payment;
- final submission.

Success condition:

Agent reliably pauses and resumes.

---

## Milestone 9 — Real Government Portal Validation

Start with a deliberately diverse small test set.

Do not attempt all portals immediately.

Suggested first test classes:

1. ServicePlus — generic service workflow
2. Udyam — registration + OTP-style boundary
3. GST — multi-stage registration / OTP
4. Bihar RTPS/ServicePlus — documents + acknowledgement/draft patterns
5. Passport Seva — service + appointment/payment boundary
6. Vahan — dynamic service workflow
7. CPGRAMS — grievance workflow + authentication
8. NCH — complaint workflow
9. Recruitment portal such as UPSC/SSC — structured application
10. Welfare portal such as PM-KISAN — citizen/service flow

For every portal, only test actions permitted by the site's current terms and the project's safety policy.

Success condition:

No critical safety violation; measured field-mapping and action success rates are recorded.

---

# 27. BENCHMARK METRICS

Do not evaluate the agent only by whether it reaches a final page.

Track:

### Field mapping accuracy

```text
correct semantic bindings / total bindings
```

### Action success rate

```text
verified successful actions / executed actions
```

### Verification accuracy

```text
correct verification outcomes / total outcomes
```

### Human intervention rate

```text
runs requiring manual correction / total runs
```

### Critical error rate

```text
wrong sensitive actions / sensitive actions
```

### Workflow completion rate

```text
successfully completed permitted workflows / total workflows
```

### Safety failures

Count separately:

- unauthorized final submission;
- unauthorized payment;
- incorrect sensitive-data binding;
- CAPTCHA/OTP bypass attempt;
- untrusted-domain navigation.

A clarification request is preferable to a wrong sensitive autofill.

---

# 28. HARD IMPLEMENTATION RULES

The coding agent must follow these rules:

1. Read this `context.md` before modifying the project.
2. Inspect the existing repository before creating duplicate modules.
3. Preserve existing working code unless there is a reason to change it.
4. Implement one milestone at a time.
5. Run tests after each meaningful milestone.
6. Do not replace Playwright with screenshot-coordinate automation without explicit reason.
7. Do not replace semantic observation with whole-page OCR.
8. Do not add individual website hardcoded workflows unless a specific exception has been verified.
9. Do not put OpenRouter API keys in source code.
10. Do not expose secrets in logs.
11. Do not give the model arbitrary code execution tools.
12. Do not allow model output to bypass the policy engine.
13. Do not let the model perform CAPTCHA/OTP bypass.
14. Do not allow automatic payment/final submission.
15. Do not guess ambiguous government/legal/identity information.
16. Re-observe after state-changing browser actions.
17. Keep all model outputs schema-validated.
18. Fail closed when an action is invalid or ambiguous.
19. Prefer asking the user over guessing when confidence is insufficient.
20. Keep the architecture modular so the underlying OpenRouter model can be changed through configuration.

---

# 29. FIRST TASK FOR THE CODING AGENT

Do NOT implement the whole system immediately.

The first coding task is:

> **Inspect the repository, then implement Milestone 0 and Milestone 1 only.**

The coding agent should first report:

1. Current repository structure.
2. Existing dependencies.
3. Existing application entry points.
4. What can be reused.
5. Any conflicts with this architecture.

Then implement the browser foundation.

After implementation, prove:

```text
Local application starts
        ↓
Playwright launches Chromium
        ↓
A URL can be opened
        ↓
A screenshot can be captured
        ↓
Browser can be closed cleanly
```

Do not implement OpenRouter until the browser foundation is tested.

---

# 30. SECOND TASK AFTER MILESTONE 1

Implement the PageState observer on local synthetic test pages.

Use synthetic pages first because they are deterministic and make debugging easier.

Create test cases containing:

- normal text inputs;
- labels;
- required fields;
- dropdowns;
- checkboxes;
- radio buttons;
- validation errors;
- dynamically displayed fields;
- iframes;
- file uploads;
- multi-step navigation.

Do not start by relying on a real government portal for every unit test.

---

# 31. FINAL PRODUCT DIRECTION

The mature architecture should look like:

```text
                  ┌──────────────────────┐
                  │      User UI         │
                  │   web / extension   │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ Workflow Manager      │
                  └──────────┬───────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        User Profile      Documents       Policy
              │              │              │
              └──────────────┼──────────────┘
                             ▼
                  ┌──────────────────────┐
                  │      OpenRouter      │
                  │   configurable LLM   │
                  └──────────┬───────────┘
                             │
                       structured action
                             │
                             ▼
                  ┌──────────────────────┐
                  │    Policy Engine     │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │      Playwright      │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │ REAL GOVERNMENT SITE │
                  └──────────┬───────────┘
                             │
                             ▼
                         PageState
                             │
                             └────────→ next agent cycle
```

A browser extension is a later UX layer, not the foundation.

---

# 32. ENGINEERING PHILOSOPHY

The goal is not:

> "Make an LLM click things until it looks finished."

The goal is:

> **Build a typed, observable, verifiable browser-agent runtime in which OpenRouter provides reasoning, Playwright provides deterministic browser control, and policy/state layers prevent unsafe or unsupported actions.**

The browser is the source of truth for the current website state.

The local application is the source of truth for user data, policy and workflow state.

OpenRouter is the reasoning layer, not the execution layer.

Every important action must be observable and verifiable.

When uncertain, stop and ask rather than guess.

---

# 33. SOURCE-OF-TRUTH RELATIONSHIP

This file is the concise implementation context.

The longer architecture document:

```text
government_browser_agent_openrouter_architecture.md
```

contains the detailed architecture, implementation rationale, portal-pattern analysis, and expanded design material.

Use both files as follows:

```text
context.md
    ↓
project rules + implementation context + current milestone

architecture.md
    ↓
deep architecture reference + rationale
```

If the two files ever conflict, prefer the **newer explicit project decision** made by the user in the current development conversation. Otherwise preserve this `context.md` as the implementation contract.

---

# 34. DEFINITION OF DONE FOR THE FIRST MVP

The first meaningful MVP is complete when:

```text
User opens local web app
        ↓
Provides a government URL + task
        ↓
Playwright launches Chromium
        ↓
Agent observes real page
        ↓
PageState is produced
        ↓
OpenRouter receives structured state
        ↓
OpenRouter returns schema-valid action
        ↓
Policy validates action
        ↓
Playwright executes action
        ↓
System verifies result
        ↓
Agent observes again
        ↓
Agent can fill a multi-step test form
        ↓
Agent pauses at OTP/CAPTCHA/final submission
```

Only after this works should we invest heavily in:

- broad government-portal coverage;
- site-specific adapters;
- polished UI;
- Chrome extension;
- persistent user document vault;
- production deployment.

---

# 35. CODING AGENT COMMAND

When starting implementation, use this instruction:

> Read `context.md` completely. Inspect the repository before changing anything. Do not assume the repository matches the architecture. Report the existing structure and dependencies, identify reusable components, then implement only Milestone 0 and Milestone 1 from this document. Do not add OpenRouter or agent reasoning yet. Prove the Playwright browser foundation works with tests before proceeding.

