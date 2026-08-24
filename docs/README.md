# 📚 Government Browser Agent — Documentation Index

**Last updated:** 2026-08-24

---

## Reading Order Before Every Implementation Step

Before writing any code, the coding agent **must** read these files in order:

| # | Document | Purpose |
|---|----------|---------|
| 1 | [context.md](./context.md) | **Implementation contract** — rules, milestones, constraints |
| 2 | [architecture.md](./government_browser_agent_openrouter_architecture.md) | Deep architecture reference + rationale |
| 3 | [MILESTONES.md](./MILESTONES.md) | Current milestone status — know what's done, what's next |
| 4 | [SAFETY.md](./SAFETY.md) | Safety rules and risk classes — never violate these |
| 5 | [BUILD_LOG.md](./BUILD_LOG.md) | What was built and verified — avoid rework |

After each implementation step, update:

| Document | What to update |
|----------|---------------|
| [MILESTONES.md](./MILESTONES.md) | Mark milestone phase as complete, add verification evidence |
| [BUILD_LOG.md](./BUILD_LOG.md) | Log what was built, files created, tests run, results |
| [TESTING.md](./TESTING.md) | Update test coverage and results |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Note any deviations from planned architecture |

---

## Document Map

### Source of Truth

| Document | Role |
|----------|------|
| [context.md](./context.md) | Primary implementation context and project rules |
| [architecture.md](./government_browser_agent_openrouter_architecture.md) | Detailed architecture, rationale, and expanded design |

**Conflict resolution:** If `context.md` and `architecture.md` conflict, prefer the newer explicit user decision in the current conversation. Otherwise, `context.md` is the implementation contract.

### Control Documents

| Document | Role |
|----------|------|
| [README.md](./README.md) | This file — master index |
| [SETUP.md](./SETUP.md) | Environment setup and prerequisites |
| [MILESTONES.md](./MILESTONES.md) | Phase-by-phase milestone tracker |
| [BUILD_LOG.md](./BUILD_LOG.md) | Chronological implementation log |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Architecture decisions and component map |
| [SAFETY.md](./SAFETY.md) | Safety rules, risk classes, enforcement checklist |
| [PORTALS.md](./PORTALS.md) | Portal validation matrix and test status |
| [TESTING.md](./TESTING.md) | Test strategy and coverage tracker |

---

## Quick Status

| Phase | Status |
|-------|--------|
| Phase 0 — Repository bootstrap | ✅ Complete |
| Phase 1 — Playwright perception engine | ✅ Complete |
| Phase 2 — Deterministic browser executor | ✅ Complete |
| Phase 3 — Verification engine | ⬜ Not started |
| Phase 4 — User vault + document registry | ⬜ Not started |
| Phase 5 — OpenRouter LLM gateway | ⬜ Not started |
| Phase 6 — Semantic field mapper | ⬜ Not started |
| Phase 7 — Agent control loop | ⬜ Not started |
| Phase 8 — Risk and approval gate | ⬜ Not started |
| Phase 9 — Vision fallback | ⬜ Not started |
| Phase 10 — Prompt injection testing | ⬜ Not started |

---

## Rules

1. **Read before coding.** Every implementation session starts by reading the docs above.
2. **Log after coding.** Every implementation session ends by updating BUILD_LOG.md.
3. **Verify before moving on.** Every milestone must have passing tests before the next begins.
4. **One phase at a time.** Do not skip ahead.
5. **Fail closed.** When uncertain, stop and ask.
