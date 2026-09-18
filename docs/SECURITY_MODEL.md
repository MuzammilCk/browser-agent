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

- [ ] injection fixtures pass
- [ ] secret redaction passes
- [ ] stale approval tests pass
- [ ] redirect tests pass
- [ ] reference-injection tests pass
- [ ] high-risk gate tests pass
- [ ] auth challenges remain human-controlled
- [ ] no arbitrary code tool
- [ ] audit traces do not leak secrets
