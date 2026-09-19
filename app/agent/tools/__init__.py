"""Typed tool registry — Phase 3 (implementation_plan.md).

Public surface:
- Tool / ToolMetadata / ToolCall / ToolResult / ToolContext — the contract
- ToolRegistry — model-facing catalog + fail-closed validation gate
- Browser tool adapters over the existing BrowserExecutor/Observer/Manager
- User-interaction tools (request_user_input / authentication / confirmation)
- Vault/document reference tools (resolve + inspect, masked sensitive data)
"""

from app.agent.tools.base import (
    Concurrency,
    ElementSummary,
    GoBackOutput,
    InspectDocumentsOutput,
    InspectFieldOutput,
    InspectOptionsOutput,
    InterruptBehavior,
    NavigateOutput,
    ObservePageOutput,
    PolicyClass,
    RequestUserOutput,
    ResolveReferenceOutput,
    Tool,
    ToolCall,
    ToolContext,
    ToolHandler,
    ToolMetadata,
    ToolResult,
)
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.browser_tools import (
    BROWSER_TOOL_CLASSES,
    CheckControlTool,
    ClickTool,
    FillFieldTool,
    GoBackTool,
    InspectFieldTool,
    InspectOptionsTool,
    NavigateTool,
    ObservePageTool,
    PressKeyTool,
    ScrollTool,
    SelectOptionTool,
    UncheckControlTool,
    UploadDocumentTool,
    WaitForStateTool,
)
from app.agent.tools.user_tools import (
    USER_TOOL_CLASSES,
    RequestAuthenticationTool,
    RequestConfirmationTool,
    RequestUserInputTool,
)
from app.agent.tools.vault_tools import (
    VAULT_TOOL_CLASSES,
    InspectAvailableDocumentsTool,
    ResolveDocumentReferenceTool,
    ResolveUserReferenceTool,
)

__all__ = [
    "BROWSER_TOOL_CLASSES",
    "CheckControlTool",
    "ClickTool",
    "Concurrency",
    "ElementSummary",
    "FillFieldTool",
    "GoBackOutput",
    "GoBackTool",
    "InspectAvailableDocumentsTool",
    "InspectDocumentsOutput",
    "InspectFieldOutput",
    "InspectFieldTool",
    "InspectOptionsOutput",
    "InspectOptionsTool",
    "InterruptBehavior",
    "NavigateOutput",
    "NavigateTool",
    "ObservePageOutput",
    "ObservePageTool",
    "PolicyClass",
    "PressKeyTool",
    "RequestAuthenticationTool",
    "RequestConfirmationTool",
    "RequestUserInputTool",
    "RequestUserOutput",
    "ResolveDocumentReferenceTool",
    "ResolveReferenceOutput",
    "ResolveUserReferenceTool",
    "ScrollTool",
    "SelectOptionTool",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolHandler",
    "ToolMetadata",
    "ToolRegistry",
    "ToolResult",
    "UncheckControlTool",
    "UploadDocumentTool",
    "USER_TOOL_CLASSES",
    "VAULT_TOOL_CLASSES",
    "WaitForStateTool",
    "build_registry",
]


def build_registry(
    *,
    value_resolver=None,
    document_resolver=None,
    reference_registry=None,
) -> ToolRegistry:
    """Build a registry with all Phase 3 tools registered."""
    registry = ToolRegistry()
    for cls in BROWSER_TOOL_CLASSES:
        registry.register(cls())
    for cls in USER_TOOL_CLASSES:
        registry.register(cls())
    for cls in VAULT_TOOL_CLASSES:
        registry.register(
            cls(
                value_resolver=value_resolver,
                document_resolver=document_resolver,
                reference_registry=reference_registry,
            )
        )
    return registry
