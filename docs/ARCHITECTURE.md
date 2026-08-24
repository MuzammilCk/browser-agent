# 🏗️ Architecture — Decisions & Component Map

**Last updated:** 2024-08-24

> **Rule:** Before implementation, read `docs/context.md` and `docs/architecture.md`.
> After implementation, update this file with any deviations from the planned architecture.

---

## Component Map

```
┌─────────────────────────────────────────────────────────┐
│                     LOCAL WEB UI                         │
│              FastAPI + minimal frontend                  │
│              URL + task + activity logs                  │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  WORKFLOW MANAGER                        │
│           State machine + orchestration                  │
└──────┬──────────────┬────────────────┬──────────────────┘
       │              │                │
       ▼              ▼                ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│ User Vault │ │ Documents  │ │  Policy    │
│ (Pydantic) │ │ (Pydantic) │ │  Engine    │
└──────┬─────┘ └──────┬─────┘ └──────┬─────┘
       │              │              │
       └──────────────┼──────────────┘
                      ▼
┌─────────────────────────────────────────────────────────┐
│                 OPENROUTER LLM                          │
│         Reasoning + Field Mapping + Planning            │
│         (Configurable model via env vars)               │
└──────────────────────────┬──────────────────────────────┘
                           │
                    typed action JSON
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              ACTION POLICY GATE                         │
│         R0 (auto) → R4 (confirm)                        │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  PLAYWRIGHT                              │
│         Browser + Page + Frames + Locators              │
└──────┬──────────────┬────────────────┬──────────────────┘
       │              │                │
       ▼              ▼                ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│   ARIA     │ │    DOM     │ │ Screenshot │
│  Snapshot  │ │  Metadata  │ │ (fallback) │
└──────┬─────┘ └──────┬─────┘ └──────┬─────┘
       │              │              │
       └──────────────┼──────────────┘
                      ▼
              ┌──────────────┐
              │  PageState   │
              │  (Pydantic)  │
              └──────┬───────┘
                     │
                     └──────────► next agent cycle
```

---

## Module Responsibility Map

| Module | Responsibility | Key Types |
|--------|---------------|-----------|
| `app/config/` | Settings, env vars, model config | `Settings` |
| `app/browser/manager.py` | Playwright lifecycle | `BrowserManager` |
| `app/browser/observer.py` | Page observation | `PageObserver` |
| `app/browser/aria.py` | ARIA snapshot extraction | — |
| `app/browser/dom.py` | DOM metadata extraction | — |
| `app/browser/locator.py` | Element resolution | — |
| `app/browser/executor.py` | Browser action execution | — |
| `app/browser/verification.py` | Post-action verification | `VerificationResult` |
| `app/browser/screenshots.py` | Screenshot capture | — |
| `app/browser/frames.py` | Frame handling | — |
| `app/models/` | Pydantic data models | `PageState`, `ElementState`, `BrowserAction` |
| `app/agent/planner.py` | LLM-based decision making | `BrowserDecision` |
| `app/agent/field_mapper.py` | Semantic field binding | `FieldBinding` |
| `app/agent/workflow.py` | Workflow state machine | `WorkflowState` |
| `app/agent/recovery.py` | Error recovery | — |
| `app/llm/` | OpenRouter gateway | `LLMGateway`, `OpenRouterGateway` |
| `app/policy/` | Risk classification + gates | `PolicyEngine`, `RiskLevel` |
| `app/vault/` | User data + documents | `UserVault`, `DocumentRef` |
| `app/sites/` | Domain registry + adapters | `SiteRegistry` |
| `app/storage/` | Database persistence | `Repository` |
| `app/api/` | FastAPI routes | — |

---

## Architecture Decisions Log

> Record significant deviations from the planned architecture here.

| Date | Decision | Rationale | Document |
|------|----------|-----------|----------|
| — | *No decisions yet* | — | — |

---

## Key Design Constraints

1. **Single action per cycle** — default implementation takes one atomic action, then re-observes.
2. **Fail closed** — unknown actions, invalid schemas, low confidence → stop.
3. **LLM is reasoning, not execution** — Playwright executes, policy validates.
4. **No secrets in prompts** — sensitive values resolved locally, not sent to OpenRouter.
5. **Page content is untrusted** — never let page text override system policy.
6. **Configurable model** — no hardcoded model names in business logic.

---

## Current Implementation Phase

**Active phase:** Phase 7 — Agent Control Loop

**Completed:** Phases 0-6 (191 tests passing)

**Next action:** Implement the closed-loop agent: observe → plan → policy → execute → verify → observe.
