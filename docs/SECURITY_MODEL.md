# SECURITY MODEL

## Boundary

~~~text
LLM proposal
 ↓
typed schema
 ↓
reference validation
 ↓
policy
 ↓
human approval if needed
 ↓
deterministic executor
~~~

The model cannot bypass these steps.

## Threat model

Assume:

- pages may contain prompt injection;
- redirects may be malicious;
- documents may contain malicious text;
- models may hallucinate;
- browser state changes between decisions;
- stale approvals may be replayed;
- user data contains sensitive PII;
- tools and model outputs may be malformed.

## Prompt injection

Portal content is untrusted.

It cannot:

- change system policy;
- alter permissions;
- redefine the user's task;
- request secrets;
- approve its own high-risk action;
- disable safety checks.

Test visible, hidden, label-based, redirect, document and tool-result injection.

## Sensitive data

High-value data includes Aadhaar, PAN, bank details, passwords, OTPs, health information, legal information and uploaded identity documents.

Rules:

- no secrets in source;
- no raw secrets in ordinary logs;
- local reference resolution;
- exact target verification for sensitive writes;
- approvals bind to action + target + state version.

## Authentication

CAPTCHA, OTP, password/PIN, MFA and biometric steps are human checkpoints. No bypass.

## Legal / financial

Require explicit user confirmation for payment, final submission, legal declaration, certification and consent with legal effect.

## Domain security

Trusted-domain checks are required before navigation. Unexpected redirects must be revalidated.

## Tool security

Every tool declares input/output schema, read-only/destructive state, required permission and interrupt behavior.

No arbitrary code execution tool.

## Memory security

Store provenance. Distinguish user facts from model hypotheses. Do not allow model summaries to silently overwrite authoritative user facts.

## Browser security

- isolated browser contexts;
- no cross-user session reuse;
- constrained upload/download directories;
- document validation;
- tab tracking;
- cleanup on finish/abort;
- redacted telemetry.

## Fail closed

Stop on:

- unknown tool;
- invalid schema;
- untrusted domain;
- ambiguous sensitive binding;
- stale approval;
- contradictory state;
- repeated verification failure;
- unresolved authentication challenge;
- suspicious injection.

## Security release gates

- [x] injection fixtures pass
- [x] secret redaction passes
- [x] stale approval tests pass
- [x] redirect tests pass
- [x] reference-injection tests pass
- [x] high-risk gate tests pass
- [x] auth challenges remain human-controlled
- [x] no arbitrary code tool
- [x] audit traces do not leak secrets
- [x] service-boundary trust tests pass (Phase 13 enterprise suite)

## Service-boundary trust (Phase 13 enterprise runtime)

Trust does not upgrade across service boundaries. Each enterprise component
keeps exactly the authority it needs and nothing more:

~~~text
API Gateway      — authenticate, authorize, validate envelopes, idempotency.
                   NO Playwright, NO browser mutation, NO vault secrets,
                   NO PolicyEngine/HITL bypass, NO AgentWorldState writes.
Workflow Service — durable lifecycle + transitions (table-validated).
                   NO browser access, NO approval fabrication.
Execution Worker — the ONLY component holding live browser handles.
                   Executes THROUGH the existing AgentRuntime → ToolRegistry
                   → PolicyEngine → BrowserExecutor path (no alternative path).
Vault boundary   — resolves references locally in-process at the worker;
                   raw values never cross any boundary.
~~~

Boundary rules enforced by tests:

- identity is server-side only: bearer tokens resolve to identities; request
  schemas are extra=forbid so clients cannot carry tenant/user/role/worker fields;
- single-owner execution: one durable lease per run with monotonic fencing
  tokens; stale workers have their durable writes REJECTED BY THE STORE (worker
  honesty is never assumed); lease loss stops browser mutation immediately;
- queue payloads carry references only — never secrets, browser handles, or
  checkpoint bytes; payloads cannot override tenant or worker authority;
- tenant isolation is enforced at the store layer (scoped lookups), not by UUID
  obscurity; cross-tenant access returns not-found without distinction;
- raw secrets never enter model context, queue payloads, audit payloads, or
  application logs; vault resolution requires an ACTIVE lease + CURRENT fencing
  token (possessing a secret grants no authority — approvals remain bound);
- audit is append-only (INSERT is the only write path), redacted before
  persistence, and causally linked (dangling/foreign parent events rejected);
- untrusted input (page content, model output, client bodies) cannot modify
  leases, workflow ownership, roles, or policy decisions.

Evidence: tests/enterprise/ (148 tests, including live PostgreSQL store tests
and real-Chromium acceptance scenarios).
