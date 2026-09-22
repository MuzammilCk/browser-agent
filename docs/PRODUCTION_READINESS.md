# PRODUCTION READINESS — Release Gate (Phase 15)

Assessed: 2026-09-22, at Phase 15 completion HEAD.

Evidence basis: the audited Phase 15 test run
(`python -m pytest tests -q` → **1186 passed, 12 skipped, 0 failures**,
2026-09-22) plus the per-directory runs recorded in docs/BUILD_STATUS.md,
the gated live-site run (10/10 shadow tests, 2026-09-21), and the gated
real-LLM evidence recorded under Phase 14 (D028). Historical claims were not
accepted without a current-HEAD re-run (D012).

## Gate-by-gate assessment

| # | Gate | Status | Evidence |
|---|------|--------|----------|
| 1 | Functional reliability | PASS | 1186 green tests incl. real-Chromium synthetic suites (83), multi-step/loop/recovery acceptance runs; deterministic replay (Phase 4/12) |
| 2 | Security | PASS | H1 verifier secret-safety; H7 3-layer password masking; injection corpus 28/28; policy/registry/executor fail-closed chain unchanged; Z6 model guard; no secret reaches model context/traces/audit in any tested path |
| 3 | Persistence | PASS | Transactional checkpoint writes; format-version gate; H6 audit redaction aligned with Phase 11 patterns; live-PostgreSQL store tests green |
| 4 | Worker recovery | PASS | Lease/fencing semantics unchanged and tested; H4 cross-process resume now works against async-only stores; crash-recovery + engine-hardening suites green |
| 5 | HITL integrity | PASS | Approval binding validation (run/interrupt/action/target/version/observation/expiry) unchanged; H3 makes ASK_USER a durable pause; replay/drift/expiry suites green |
| 6 | Tenant isolation | PASS | Server-side identity, tenant-scoped stores, strict schemas (`extra=forbid`); isolation/vault/API suites green |
| 7 | Browser recovery | PASS (with noted residual) | Generic fail-safe path converts crash-class failures to EXECUTION_FAILED + recovery_required; dedicated frame-disappearance test deferred (documented residual) |
| 8 | Memory isolation | PASS | Write policy, poisoning defense, promotion gate, cross-run isolation suites green; end-to-end injection-persistence scenario deferred (non-exploitable authority chain) |
| 9 | Observability | PASS | TraceRecorder redaction before persistence; causal correlation ids; H3 closes the non-tool-decision trace gap; no secrets in traces (H1/H6/H7 verified by tests) |
| 10 | API reliability | PASS | Strict schemas; deterministic error codes; H5 removes the 500 path and legitimizes out-of-process worker heartbeats; idempotency/cancellation suites green |
| 11 | Evaluation coverage | PASS | 14 golden scenarios + fault injection + live acceptance; infra-crash faults covered at unit/enterprise level (rationale in docs/PHASE15_PLAN.md) |
| 12 | Deployment readiness | PASS (dev posture) | H8 readiness validation + /ready; secure defaults documented; blockers fire under production_mode. Posture is single-node/localhost-class — NOT a hardened multi-host deployment |
| 13 | Live-site safety | PASS | Shadow ≠ controlled execution ≠ unrestricted automation boundary intact (D026–D028); zero live mutations performed in Phase 15 |
| 14 | Real-LLM validation | PARTIAL | Real OpenRouter path proven live end-to-end earlier on 2026-09-21 (schema-valid fill → full path → verification); gated test failed on free-tier quota 429 later the same day — honest environment-class failure, fail-closed path proven live. Continuous live-LLM soak NOT established |

## What this classification means

- **READY FOR CONTROLLED PILOT** — the architecture and its safeguards are
  implemented and test-proven; the system may operate against real portals
  only within the Phase 14 live-safety boundary (observation-only shadow, or
  controlled execution under its signed-review gates) with real human
  oversight, durable HITL, and per-run audit.
- It is NOT production ready: no sustained real-LLM soak, no load testing,
  single-node deployment posture, and the documented residuals below.

## Residual risks (accepted, documented)

1. Frame-disappearance adversarial test missing (generic fail-safe covered).
2. Cancellation granularity is the iteration boundary, not per-Playwright-call.
3. Memory prompt-injection persistence lacks a dedicated end-to-end scenario.
4. Heartbeat API lightly load-tested (redundant with in-process renewal).
5. Free-tier OpenRouter quotas churn; operators must pin provider/model and
   manage quotas (D028.7). No model identity is hard-coded.
6. NO CI is configured in this repository — all evidence is local, dated,
   reproducible execution, not continuous integration.

## Production blockers (to reach PRODUCTION READY)

1. Continuous integration running the full suite on every change.
2. Named-provider LLM contract (non-free-tier) with soak evidence over real
   workflow runs.
3. Hardened deployment posture: secrets management, TLS termination,
   multi-node Postgres, backup/restore drills.
4. Load/soak testing of the enterprise queue + worker pool.
5. A controlled pilot report against a real portal class with a real user,
   including at least one full HITL round-trip and audit review.

## Classification

**READY FOR CONTROLLED PILOT**

Chosen for the evidence above — not optimized upward: gates 12 (deployment
posture) and 14 (real-LLM soak) are the limiting factors, and none of the
documented residuals is a safety defect.
