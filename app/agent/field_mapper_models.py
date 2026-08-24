"""Field binding model — maps website fields to user-data references.

Phase 6 deliverables:
- FieldBinding with confidence scoring
- Mapping strategy tracking (deterministic vs LLM)
- Evidence trail for audit
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MappingConfidence(str, Enum):
    """Confidence level for field mapping."""

    HIGH = "high"        # Safe under action policy — auto-fill
    MEDIUM = "medium"    # Ask for confirmation for sensitive fields
    LOW = "low"          # Do not fill — ask user
    NONE = "none"        # No mapping found


class MappingStrategy(str, Enum):
    """How the mapping was determined."""

    DETERMINISTIC = "deterministic"    # Local keyword/semantic rules
    LLM = "llm"                        # OpenRouter structured reasoning
    MANUAL = "manual"                  # User-provided mapping
    FALLBACK = "fallback"              # Best guess when nothing else works


class FieldBinding(BaseModel):
    """A mapping between a website form field and a user-data reference.

    Example:
        field_ref = "e12"
        binding = "USER.full_name"
        confidence = MappingConfidence.HIGH
        strategy = MappingStrategy.DETERMINISTIC
    """

    field_ref: str = Field(
        description="Ephemeral element ref from current PageObservation"
    )
    binding: str | None = Field(
        default=None,
        description="Semantic reference like USER.full_name or DOCUMENT.aadhaar",
    )
    confidence: MappingConfidence = Field(
        default=MappingConfidence.NONE,
        description="Confidence in this mapping",
    )
    strategy: MappingStrategy = Field(
        default=MappingStrategy.DETERMINISTIC,
        description="How this mapping was determined",
    )
    value_override: str | None = Field(
        default=None,
        description="Literal value override (only for non-sensitive PUBLIC fields)",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Evidence supporting this mapping (labels, context, etc.)",
    )
    conflict_with: list[str] = Field(
        default_factory=list,
        description="Other field_refs that could potentially match the same binding",
    )
    requires_confirmation: bool = Field(
        default=False,
        description="True if user should confirm before filling",
    )
    field_type: str | None = Field(
        default=None,
        description="Detected field type (textbox, combobox, etc.)",
    )
    field_label: str | None = Field(
        default=None,
        description="The actual label/name of the field on the page",
    )


class MappingResult(BaseModel):
    """Result of mapping all fields on a page."""

    bindings: list[FieldBinding] = Field(
        default_factory=list,
        description="All field bindings found",
    )
    unmapped_fields: list[str] = Field(
        default_factory=list,
        description="Field refs that could not be mapped to any binding",
    )
    ambiguous_fields: list[str] = Field(
        default_factory=list,
        description="Field refs with MEDIUM or LOW confidence",
    )
    total_fields: int = Field(
        default=0,
        description="Total interactive fields observed",
    )
    mapped_count: int = Field(
        default=0,
        description="Number of fields successfully mapped",
    )
    strategy_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of bindings per strategy used",
    )
