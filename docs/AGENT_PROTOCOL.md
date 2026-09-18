# AGENT DEVELOPMENT PROTOCOL

## Before code changes

Read:

~~~text
AGENTS.md
context.md
implementation_plan.md
docs/ARCHITECTURE_TARGET.md
docs/SECURITY_MODEL.md
docs/BUILD_STATUS.md
docs/DECISIONS.md
~~~

Then inspect the exact code and tests.

## Evidence loop

~~~text
READ
 ↓
UNDERSTAND
 ↓
REPRODUCE
 ↓
WRITE / UPDATE TEST
 ↓
IMPLEMENT
 ↓
TARGETED TEST
 ↓
INTEGRATION TEST
 ↓
FULL RELEVANT TEST
 ↓
UPDATE BUILD STATUS
~~~

## Rules

- Search before creating new abstractions.
- Reuse existing browser, policy, vault and verification components.
- Make the smallest architecture-consistent change.
- Never silently switch from agent mode to deterministic mode.
- Never silently bypass policy.
- Never treat a successful Playwright call as proof of success.
- Never persist important resumable state only in process memory.
- Never dump the entire transcript/page into every LLM call.
- Never allow memory summaries to overwrite authoritative user facts without provenance.

## Failure capture

Record safe metadata:

~~~text
workflow_id
iteration
observation_id
page_url
page_type
current_subgoal
tool
target_ref
semantic_ref
policy_decision
execution_error
verification_result
state_version
~~~

Never record raw OTPs, passwords, full identity numbers or document contents.

## No silent fallback

Any fallback must appear in workflow state and trace.

Examples:

- primary model → fallback model
- LLM → deterministic
- semantic locator → visual fallback
- retry → strategy change

## Handoff

End work with:

~~~text
CURRENT PHASE:
COMPLETED:
IN PROGRESS:
BLOCKED:
TESTS:
FILES CHANGED:
DECISIONS:
NEXT EXACT TASK:
~~~
