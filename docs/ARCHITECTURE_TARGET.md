# TARGET ARCHITECTURE — Stateful Hierarchical Browser Agent

~~~text
                           USER
                            │
                            ▼
                    Task API / UI
                            │
                            ▼
                    Workflow Service
                            │
                            ▼
                    ┌─────────────────┐
                    │  AgentRuntime   │
                    │                 │
                    │ Goal / Plan     │
                    │ WorldState      │
                    │ Memory          │
                    │ Checkpoints     │
                    │ Tools           │
                    │ Lifecycle       │
                    └────────┬────────┘
                             │
                  ┌──────────┼──────────┐
                  ▼          ▼          ▼
               Reasoner   Policy     Memory
              OpenRouter  Engine      Service
                  │
                  ▼
             AgentDecision
                  │
                  ▼
             Tool Registry
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
      Browser    Vault      Human
       Tools     Tools      Tools
        │
        ▼
    Playwright
        │
        ▼
REAL GOVERNMENT WEBSITE
        │
        ▼
 PageObservation
        │
        ▼
 WorldState update
        │
        ▼
 Verification
        │
     ┌──┴──┐
     ▼     ▼
   success failure
     │      │
  continue Reflection
            │
            ▼
           Plan
           revision
~~~

## Responsibility boundaries

### AgentRuntime

Owns lifecycle, state, goal, plan, interrupts, persistence, memory coordination and events.

It does not call Playwright directly.

### Reasoner

Chooses tools, revises plans, asks users, reflects.

It cannot authorize itself or bypass policy.

### PolicyEngine

Owns permissions, risk, reference validation, trusted domains and human gates.

### ToolExecutor

Translates typed tool calls into deterministic application operations.

### BrowserExecutor

Owns Playwright.

### Verifier

Determines whether a requested state transition actually happened.

### WorldState

Stores semantic workflow state. DOM refs are temporary.

## Runtime loop

~~~text
observe
→ update WorldState
→ handle interrupt if present
→ validate/revise plan
→ construct minimal reasoning context
→ reason
→ validate decision
→ policy
→ execute
→ verify
→ emit event
→ update state
→ memory/compaction
→ continue or replan
~~~

## One browser controller

Exactly one primary agent owns browser mutation.

Specialists are scoped:

~~~text
Primary CitizenAgent
 ├── PortalResearchAgent
 ├── FormSemanticsAgent
 ├── DocumentAgent
 ├── RecoveryAgent
 └── VerificationAgent
~~~

Specialists cannot silently inherit the primary agent's privileges.

## Sensitive-data path

~~~text
Local vault
  ↓
semantic reference
  ↓
executor
  ↓
browser
~~~

The LLM sees references, not raw secrets.

## Completion proof

~~~text
required safe state
AND
required evidence
AND
validation clear
AND
authentication satisfied
AND
review state reached
AND
no unresolved ambiguity
→ READY_FOR_CONFIRMATION
~~~

Final irreversible actions remain human-gated.

## Enterprise deployment

~~~text
API
 ↓
Workflow Service
 ↓
Postgres
 ↓
Queue
 ↓
Agent Worker
 ↓
Browser Worker
 ↓
Government Site
~~~

The single-process version remains the development runtime until durability and evaluation justify the service split.
