"""Vault/document tools — Phase 3 (context.md "Vault/document" family).

These tools answer "can this semantic reference be resolved?" — they
NEVER return raw sensitive values. Sensitive references resolve to a
resolution handle; the executor re-resolves locally at execution time
(docs/SECURITY_MODEL.md sensitive-data path). Document listing returns
metadata only, never contents.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.tools.base import (
    Concurrency,
    InspectDocumentsOutput,
    PolicyClass,
    ResolveReferenceOutput,
    ToolCall,
    ToolContext,
    ToolMetadata,
    ToolResult,
)
from app.agent.tools.browser_tools import _BrowserTool
from app.agent.registry import ReferenceRegistry, get_registry

# Sensitivity levels that must never be echoed to the model
_MASKED = ("sensitive", "secret")


class _ResolveUserInput(BaseModel):
    ref: str = Field(description="Semantic user reference (e.g. 'USER.full_name')")


class _ResolveDocumentInput(BaseModel):
    ref: str = Field(description="Semantic document reference (e.g. 'DOCUMENT.aadhaar')")


class _EmptyInput(BaseModel):
    pass


def _mask_sensitivity(sensitivity) -> str:
    """Public name for public/internal levels; masked label otherwise."""
    name = getattr(sensitivity, "value", str(sensitivity))
    return "masked" if name in _MASKED else name


class ResolveUserReferenceTool(_BrowserTool):
    metadata = ToolMetadata(
        name="resolve_user_reference",
        description=(
            "Check whether a USER.* semantic reference can be resolved from "
            "the local vault. Returns resolvability and sensitivity — never "
            "the raw value (sensitive values stay local)."
        ),
        family="vault",
        input_schema=_ResolveUserInput,
        output_schema=ResolveReferenceOutput,
        read_only=True,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.SHARED,
    )

    def __init__(
        self,
        *,
        value_resolver=None,
        document_resolver=None,
        reference_registry: ReferenceRegistry | None = None,
    ) -> None:
        self._value_resolver = value_resolver
        self._registry = reference_registry or get_registry()

    async def run(self, args: _ResolveUserInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        ref = args.ref
        if not ref.startswith("USER."):
            return self.error(call, "INVALID_REFERENCE", "USER references start with 'USER.'", ctx=ctx)
        definition = self._registry.get(ref)
        if definition is None:
            return self.error(call, "UNKNOWN_REFERENCE", f"Unknown reference: {ref}", ctx=ctx)
        resolver = self._value_resolver or (ctx.value_resolver if ctx else None)
        resolvable = bool(resolver and resolver.resolve(ref) is not None)
        output = ResolveReferenceOutput(
            ref=ref,
            resolvable=resolvable,
            sensitivity=_mask_sensitivity(definition.sensitivity),
            display_name=definition.display_name,
            resolution_hint=(
                "resolved locally at execution time"
                if resolvable else "not present in local vault"
            ),
        )
        return self.success(call, output, f"{ref}: {'resolvable' if resolvable else 'unresolvable'}", ctx=ctx)


class ResolveDocumentReferenceTool(_BrowserTool):
    metadata = ToolMetadata(
        name="resolve_document_reference",
        description=(
            "Check whether a DOCUMENT.* reference resolves to a locally "
            "registered document file. Returns existence and type metadata "
            "— never the file contents or path."
        ),
        family="vault",
        input_schema=_ResolveDocumentInput,
        output_schema=ResolveReferenceOutput,
        read_only=True,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.SHARED,
    )

    def __init__(
        self,
        *,
        value_resolver=None,
        document_resolver=None,
        reference_registry: ReferenceRegistry | None = None,
    ) -> None:
        self._document_resolver = document_resolver
        self._registry = reference_registry or get_registry()

    async def run(self, args: _ResolveDocumentInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        ref = args.ref
        if not ref.startswith("DOCUMENT."):
            return self.error(call, "INVALID_REFERENCE", "DOCUMENT references start with 'DOCUMENT.'", ctx=ctx)
        definition = self._registry.get(ref)
        if definition is None:
            return self.error(call, "UNKNOWN_REFERENCE", f"Unknown reference: {ref}", ctx=ctx)
        resolver = self._document_resolver or (ctx.document_resolver if ctx else None)
        doc = resolver.resolve(ref) if resolver else None
        resolvable = doc is not None
        output = ResolveReferenceOutput(
            ref=ref,
            resolvable=resolvable,
            sensitivity=_mask_sensitivity(definition.sensitivity),
            display_name=definition.display_name,
            resolution_hint="document registered locally" if resolvable else "document not registered",
        )
        return self.success(call, output, f"{ref}: {'resolvable' if resolvable else 'unresolvable'}", ctx=ctx)


class InspectAvailableDocumentsTool(_BrowserTool):
    metadata = ToolMetadata(
        name="inspect_available_documents",
        description=(
            "List locally registered documents (type, display name, "
            "sensitivity) — metadata only, never file contents or paths."
        ),
        family="vault",
        input_schema=_EmptyInput,
        output_schema=InspectDocumentsOutput,
        read_only=True,
        policy_class=PolicyClass.READ_ONLY,
        concurrency=Concurrency.SHARED,
    )

    def __init__(
        self,
        *,
        value_resolver=None,
        document_resolver=None,
        reference_registry: ReferenceRegistry | None = None,
    ) -> None:
        self._document_resolver = document_resolver
        self._registry = reference_registry or get_registry()

    async def run(self, args: _EmptyInput, call: ToolCall, ctx: ToolContext) -> ToolResult:
        resolver = self._document_resolver or (ctx.document_resolver if ctx else None)
        documents: list[dict[str, str]] = []
        if resolver is not None:
            for ref_key in self._registry.get_doc_refs():
                doc = resolver.resolve(ref_key)
                definition = self._registry.get(ref_key)
                if doc is None or definition is None:
                    continue
                documents.append({
                    "ref": ref_key,
                    "display_name": definition.display_name,
                    "type": doc.type,
                    "sensitivity": _mask_sensitivity(definition.sensitivity),
                    "registered": "true",
                })
        output = InspectDocumentsOutput(documents=documents)
        return self.success(call, output, f"{len(documents)} document(s) available", ctx=ctx)


VAULT_TOOL_CLASSES = [
    ResolveUserReferenceTool,
    ResolveDocumentReferenceTool,
    InspectAvailableDocumentsTool,
]
