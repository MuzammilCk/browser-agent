# EVALUATION PLAN

## Purpose

Evaluate the runtime as a long-horizon system, not merely the quality of individual LLM replies.

## Layer A — Synthetic

Cover:

- text/select/radio/checkbox
- dependent dropdowns
- dynamic fields
- validation errors
- iframe
- multi-tab
- upload
- duplicate labels
- multilingual/abbreviated labels
- stale refs
- navigation changes
- prompt injection
- malicious redirects
- auth checkpoints
- legal declaration gates

## Layer B — Frozen real-portal observations

Capture safe observations without real PII.

Use portal classes:

- identity/document
- welfare
- transport
- education
- recruitment
- training
- grievance
- certificate
- appointment

Replay PageState/DOM/accessibility/screenshot fixtures offline.

## Layer C — Live shadow mode

The agent may observe, map and propose tool calls, but not mutate the real site.

## Layer D — Controlled live execution

Permit only bounded low/medium-risk actions first.

No payment, final legal submission, CAPTCHA bypass or OTP interception.

## Metrics

~~~text
field_mapping_accuracy
tool_success_rate
verification_accuracy
subgoal_success_rate
recovery_success_rate
workflow_completion_rate
human_intervention_rate
unsafe_action_rate
prompt_injection_success_rate
iterations
latency
LLM_cost
~~~

## Trace contract

Each iteration should expose safe metadata:

~~~text
workflow_id
iteration
observation_id
page_url
page_type
goal
current_subgoal
field_count
mapped_count
unmapped_count
agent status
selected tool
target reference
semantic reference
policy decision
execution status
verification status
new observation id
state version
~~~

Never expose actual sensitive values.

## Failure injection

Simulate:

- stale refs
- dropdown changes
- navigation
- disappearing targets
- model timeout
- malformed model output
- tool timeout
- verification mismatch
- worker restart
- duplicate resume
- stale approval
- prompt injection
- malicious document metadata

Expected behavior is safe recovery or safe halt.

## Release policy

Do not choose arbitrary model or accuracy thresholds before the benchmark baseline exists. Establish a baseline first, then record thresholds in DECISIONS.md.
