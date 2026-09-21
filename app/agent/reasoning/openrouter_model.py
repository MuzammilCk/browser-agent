"""OpenRouter decision-model adapter — Phase 4.

Implements the narrow DecisionModel protocol over the EXISTING
LLMGateway (app/llm/openrouter.py). This module is the ONLY place the
Phase 4 loop touches OpenRouter specifics:

- structured output: the inner decision JSON schema from
  build_decision_json_schema()["schema"] is passed to the gateway, which
  itself wraps it as response_format: {type: json_schema, json_schema:
  {name, strict, schema}} on the request. (The gateway owns the
  response_format envelope; the adapter passes only the inner JSON
  schema — passing the pre-built envelope would double-wrap it and the
  API would reject the request with 400.)
- schema violation handling: strict-JSON providers still can return
  schema-violating content; LLMMalformedResponseError and unparseable
  JSON both surface as InvalidModelOutput — which the AgentReasoner
  treats like any other rejected attempt (bounded retries → explicit
  MODEL_FAILURE);
- the reasoner stays model-agnostic: no OpenRouter import above this
  adapter;
- no API key is required for core tests (mock model covers the loop);
  without a key the adapter refuses to build (fail closed) rather than
  silently degrading to deterministic behavior.
"""

from __future__ import annotations

import json
import logging

from app.agent.reasoning.protocol import build_decision_json_schema
from app.config.settings import get_settings
from app.llm.base import LLMGateway
from app.llm.schemas import LLMMalformedResponseError

logger = logging.getLogger(__name__)


class InvalidModelOutput(Exception):
    """The model answered but its output was unusable (unparseable or
    schema-violating). Treated by the reasoner as a rejected attempt."""


class OpenRouterDecisionModel:
    """DecisionModel adapter over the existing OpenRouterGateway."""

    def __init__(self, gateway: LLMGateway) -> None:
        self._gateway = gateway
        # The gateway builds the response_format envelope itself; pass the
        # INNER JSON schema only (protocol.py builds it from the same
        # pydantic model the parser validates with, so prompt and
        # validation contracts cannot drift).
        self._schema = build_decision_json_schema()["schema"]

    async def decide(self, *, system: str, context: str) -> dict:
        response = await self._gateway.complete(
            system=system,
            user=context,
            schema=self._schema,
            temperature=0.0,
        )
        parsed = response.parsed
        if parsed is None:
            # Content failed JSON parsing at the gateway.
            raise InvalidModelOutput(
                "model returned non-JSON content "
                f"(finish_reason={response.finish_reason!r})"
            )
        if not isinstance(parsed, dict):
            raise InvalidModelOutput(
                f"model returned JSON {type(parsed).__name__}, expected object"
            )
        return parsed


def build_openrouter_decision_model(
    gateway: LLMGateway | None = None,
    *,
    require_api_key: bool = True,
) -> OpenRouterDecisionModel:
    """Build the real adapter from settings.

    Fails closed when no API key is configured: an agent that cannot
    call a model must not silently become a deterministic one. Callers
    pass require_api_key=False only when they bring their own gateway
    (e.g. tests with a stub gateway).
    """
    if gateway is None:
        settings = get_settings()
        if require_api_key and not settings.openrouter_api_key:
            raise RuntimeError(
                "No OpenRouter API key configured — refusing to build the "
                "decision model (fail closed; set OPENROUTER_API_KEY)"
            )
        from app.llm.openrouter import OpenRouterGateway

        gateway = OpenRouterGateway(settings)
    return OpenRouterDecisionModel(gateway)
