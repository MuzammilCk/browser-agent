# ARCHITECTURE DECISIONS

## D001 — Stateful hierarchical browser agent

Build a stateful hierarchical browser agent rather than a single-shot planner or generic swarm.

Status: ACCEPTED

## D002 — One primary browser controller

One primary agent owns browser mutation. Specialists are agent-as-tools.

Status: ACCEPTED

## D003 — LLM proposes; deterministic runtime authorizes

The LLM cannot own the security or execution boundary.

Status: ACCEPTED

## D004 — Typed tool registry

The model-facing interface is a typed Tool Registry with schemas and permission metadata.

Status: ACCEPTED

## D005 — Semantic state survives DOM changes

WorldState is durable; DOM refs are ephemeral.

Status: ACCEPTED

## D006 — Durable human interrupts

OTP/CAPTCHA/auth/legal/payment/final confirmation are persistent workflow checkpoints.

Status: ACCEPTED

## D007 — Local secret resolution

Sensitive values are resolved locally at execution time.

Status: ACCEPTED

## D008 — Verification is mandatory

Successful Playwright invocation is not equivalent to successful workflow transition.

Status: ACCEPTED

## D009 — Structured memory before vector search

Start with structured memory and add vector retrieval only if evaluation proves value.

Status: ACCEPTED

## D010 — Generic automation before portal scripts

Prefer generic semantics plus small adapters for true exceptions.

Status: ACCEPTED

## D011 — No authentication or payment bypass

CAPTCHA, OTP, password/PIN, biometric, payment and final irreversible actions remain human-controlled as specified by policy.

Status: ACCEPTED

## D012 — Current HEAD evidence only

Historical audit claims must be reverified against the current repository before being used as completion evidence.

Status: ACCEPTED

## D013 — Model guardrail override is opt-in via environment variable

The Z6 model guard (`_vault_model_guard` in `app/api/routes.py`) refuses free-tier/anonymous OpenRouter models when the vault is populated, unless `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=true`. This override defaults to `false` to ensure fail-closed behavior. The `.env` must match `.env.example` defaults for tests to pass.

Status: ACCEPTED — implemented fix in `.env` (set `ALLOW_ANONYMOUS_MODEL_WITH_VAULT=false`)
