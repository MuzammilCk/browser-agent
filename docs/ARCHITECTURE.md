<<<<<<< HEAD
# Architecture — Decisions & Component Map

**Last updated:** 2026-09-18

> **Rule:** Before implementation, read `docs/context.md` and `docs/architecture.md` (this file).
> After implementation, update this file with any deviations from the planned architecture.
=======
# Legacy Architecture Document — Redirect

This historical architecture document is retained for provenance only.

**Canonical target architecture:** [ARCHITECTURE_TARGET.md](ARCHITECTURE_TARGET.md)
>>>>>>> 927bc65113ef1c51cafe118f42e581a7b982540a

**Canonical context:** [../context.md](../context.md)

**Canonical implementation plan:** [../implementation_plan.md](../implementation_plan.md)

<<<<<<< HEAD
```
┌─────────────────────────────────────────────────────────┐
│                     LOCAL WEB UI                         │
│              FastAPI + HTMX frontend                    │
│   URL + task + activity logs + confirmation UI          │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                  WORKFLOW MANAGER                        │
│           State machine + orchestration                  │
│   AgentRunner: observe → map → plan → policy → execute   │
└──────┬──────────────┬────────────────┬──────────────────┘
       │              │                │
       ▼              ▼                ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│ User Vault │ │ Documents  │ │  Policy    │
│ (encrypted │ │ (encrypted │ │  Engine    │
│   at rest) │ │   at rest) │ │  R0-R4     │
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
│         R0 (auto) → R1 (auto) → R2 → R3 → R4            │
│         Low → Sensitive→ Confirm → Pause → User         │
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
=======
**Agent contract:** [../AGENTS.md](../AGENTS.md)
>>>>>>> 927bc65113ef1c51cafe118f42e581a7b982540a

The old diagram describes the earlier workflow-oriented system. The target architecture now requires a persistent hierarchical agent runtime with goals/subgoals, typed tools, WorldState, memory, reflection, durable interrupts, deterministic policy and verification.

<<<<<<< HEAD
## Module Responsibility Map

| Module | Responsibility | Key Types |
|--------|---------------|-----------|
| `app/config/` | Settings, env vars, model config | `Settings` |
| `app/browser/manager.py` | Playwright lifecycle + TabTracker | `BrowserManager` |
| `app/browser/observer.py` | Page observation + auth detection | `PageObserver` |
| `app/browser/aria.py` | ARIA snapshot extraction | — |
| `app/browser/dom.py` | DOM metadata extraction (JS) | — |
| `app/browser/locator.py` | Frame-aware element resolution | `LocatorResolver` |
| `app/browser/executor.py` | Browser action execution + policy | `BrowserExecutor` |
| `app/browser/verification.py` | Post-action verification | `VerificationResult` |
| `app/browser/verifiers/` | Per-action verifiers (7 modules) | — |
| `app/browser/vision.py` | Completeness assessment for vision fallback | `CompletenessAssessment` |
| `app/browser/tabs.py` | Multi-tab state tracking | `TabSwitch`, `TabTracker` |
| `app/models/` | Pydantic data models | `PageState`, `ElementState`, `BrowserAction`, `WorkflowState` |
| `app/agent/runner.py` | Full agent loop orchestrator | `AgentRunner` |
| `app/agent/planner.py` | LLM + deterministic planning | `plan_with_llm`, `plan_deterministic` |
| `app/agent/planning_result.py` | Typed planning outcomes | `ActionPlanned`, `NoValidAction`, `PlanLLMError`, `TaskComplete` |
| `app/agent/field_mapper.py` | Semantic field binding | `FieldMapper` |
| `app/agent/registry.py` | **Canonical reference registry** — single source of truth for all USER.* and DOCUMENT.* refs | `ReferenceRegistry`, `ReferenceDefinition` |
| `app/agent/stall_detector.py` | Repeated-action stall detection | `ActionSignature`, `StallVerdict` |
| `app/agent/vision_fallback.py` | Vision fallback trigger + request | `should_attempt_vision`, `request_vision_action` |
| `app/llm/base.py` | LLMGateway protocol | `LLMGateway` |
| `app/llm/openrouter.py` | OpenRouter API implementation | `OpenRouterGateway` |
| `app/llm/schemas.py` | LLM response/error models | `LLMResponse`, `LLMUsage` |
| `app/llm/retry.py` | Bounded retry with exponential backoff | `RetryPolicy` |
| `app/llm/sanitizer.py` | Prompt sanitization for element names | `PromptSanitizer` |
| `app/policy/engine.py` | Risk classification + action gate | `PolicyEngine`, `RiskLevel`, `PolicyDecision` |
| `app/policy/document_policy.py` | Upload file type/size/path validation | `DocumentPolicy` |
| `app/vault/resolver.py` | Value/document reference resolution | `UserVault`, `DocumentRef`, `DocumentRegistry`, `ValueResolver`, `DocumentResolver` |
| `app/vault/sensitivity.py` | Sensitivity classification (from registry) | `SensitivityLevel` |
| `app/vault/manager.py` | Vault persistence (encrypted at rest) | `VaultManager` |
| `app/sites/registry.py` | Trusted government domain registry (15+ domains) | `TrustedDomainRegistry`, `DomainEntry`, `SiteTask` |
| `app/api/routes.py` | FastAPI routes (sites + automation) | — |
| `app/api/vault_routes.py` | Vault CRUD API (names only, never values) | — |
| `app/storage/` | Storage initialization (stub — SQLite planned) | — |

---

## Architecture Decisions Log

> Record significant deviations from the planned architecture here.

| Date | Decision | Rationale | Document |
|------|----------|-----------|----------|
| 2024-08-24 | Vault encrypted at rest via Fernet + scrypt KDF | Audit B6: protect sensitive PII on disk | |
| 2024-08-24 | Multi-tab state made explicit in PageState | Phase 8: clicks opening target=_blank tabs were invisible to the agent | |
| 2024-08-24 | Stall detection for repeated actions | Phase 9: labeled stall instead of generic max-iteration exit | |
| 2024-08-24 | ReferenceRegistry as single source of truth | Audit #37: eliminated dual hardcoded reference lists | |
| 2024-08-24 | Free-tier model guard (Z6) | Prevent real PII through anonymous/contested models | |
| 2024-08-24 | Vision fallback as one-shot rescue | Audit Z7/P0-16: only at confirmed stalls, max 1 per workflow | |
| 2024-08-24 | PromptSanitizer for element names | Audit #20: strip prompt-injection payloads from page text before LLM context | |
| 2026-09-18 | `open` removed from LLM action set | Navigation is workflow-controlled, not model-controlled | |
| 2026-09-18 | Vault encrypted at rest via Fernet + scrypt KDF | Audit B6: protect sensitive PII on disk | |

---

## Key Design Constraints

1. **Single action per cycle** — default implementation takes one atomic action, then re-observes.
2. **Fail closed** — unknown actions, invalid schemas, low confidence → stop.
3. **LLM is reasoning, not execution** — Playwright executes, policy validates.
4. **No secrets in prompts** — sensitive values resolved locally, not sent to OpenRouter.
5. **Page content is untrusted** — never let page text override system policy. PromptSanitizer strips dangerous content.
6. **Configurable model** — no hardcoded model names in business logic.
7. **Observation-scoped refs** — element refs are ephemeral, tied to an observation_id; stale refs are rejected.
8. **Multi-tab aware** — TabTracker records every tab; agent always knows which tab is active.
9. **Stall detection** — repeated identical actions on an unchanged page halt with a labeled reason.
10. **Vault encryption** — vault data encrypted at rest with Fernet when passphrase provided.

---

## Current Implementation Status

**Completed Phases:** Phase 0 — Phase 6, Phase A — Phase E

**Phases completed (audit hardening):**
- Phase A — Contract Hardening (50 issues: #1, #4, #5, #6, #7, #8, #10, #11, #12, #15, #37, #42)
- Phase B — Safety Engine (issues: #19, #21, #22, #23, #24, #36)
- Phase C — Workflow Orchestration (#25, #26, #28, #49, #50)
- Phase D — E2E Synthetic Tests + Contract Tests (#43, #44)
- Phase E — Remaining Audit Fixes (#3, #30, #35, #38, #41, #47)

**Test count:** 294+ passing

**Pending:**
- Phase 7 — Agent Control Loop (LLM planning — implemented but requires OpenRouter API key for full testing)
- Phase 8 — Risk and approval gate (partially implemented; full UI confirmation flow in place)
- Phase 9 — Vision fallback (trigger implemented; multimodal request path exists)
- Phase 10 — Prompt injection testing (sanitizer in place; tests need hostile pages)

**Next action:** Phase 7 full E2E with live OpenRouter (requires API key).
=======
Do not use this document to define new architecture.
>>>>>>> 927bc65113ef1c51cafe118f42e581a7b982540a
