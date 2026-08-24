"""Semantic field mapper — maps website form fields to user-data references.

Phase 6 + Phase A fixes:
- Deterministic local matching (keyword/semantic rules)
- LLM-based resolution for ambiguous AND unmapped fields
- Confidence scoring with three levels (HIGH/MEDIUM/LOW)
- Evidence trail for audit
- ReferenceRegistry validation for all bindings
- File input matching uses input_type, not role
- Vault values NOT sent to LLM (only reference keys)

Architecture:
    PageState
        ↓
    deterministic matching
        ↓
    ambiguous + unmapped fields
        ↓
    LLM structured reasoning
        ↓
    ReferenceRegistry validation
        ↓
    FieldBinding
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agent.field_mapper_models import (
    FieldBinding,
    MappingConfidence,
    MappingResult,
    MappingStrategy,
)
from app.agent.registry import ReferenceRegistry, get_registry
from app.llm.base import LLMGateway
from app.llm.sanitizer import PromptSanitizer
from app.models.page_state import ElementState, PageObservation, PageState

logger = logging.getLogger(__name__)


# ============================================================
# Deterministic mapping rules
# ============================================================

# Canonical binding → (keywords, field_types, confidence)
# field_types match against BOTH role AND input_type
# Keywords are matched against: label_text, accessible_name, html_name,
# placeholder, section_heading, help_text, nearby_text
DETERMINISTIC_RULES: dict[str, dict[str, Any]] = {
    # --- Identity ---
    "USER.full_name": {
        "keywords": [
            "full name", "applicant name", "name of applicant",
            "candidate name", "legal name", "name as per aadhaar",
            "your name", "enter name",
        ],
        "exclude_keywords": [
            "parent", "guardian", "spouse", "father", "mother",
            "husband", "nominee", "organization", "company",
        ],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.date_of_birth": {
        "keywords": [
            "date of birth", "dob", "birth date", "born on",
            "date of birth as per aadhaar",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox", "date"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.gender": {
        "keywords": ["gender", "sex"],
        "exclude_keywords": [],
        "field_types": ["combobox", "radiogroup"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.age": {
        "keywords": ["age", "your age", "applicant age"],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    # --- Contact ---
    "USER.mobile": {
        "keywords": [
            "mobile", "phone", "contact number", "mobile number",
            "telephone", "cell number", "phone number",
        ],
        "exclude_keywords": ["alt", "alternate", "secondary"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.email": {
        "keywords": [
            "email", "e-mail", "email address", "mail id",
            "email id", "electronic mail",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    # --- Address ---
    "USER.address": {
        "keywords": [
            "address", "full address", "present address",
            "current address", "correspondence address", "postal address",
            "residence address", "complete address",
        ],
        "exclude_keywords": ["permanent", "village", "district", "state", "pin"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.MEDIUM,
    },
    "USER.permanent_address": {
        "keywords": [
            "permanent address", "pr address",
            "permanent residence address",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.MEDIUM,
    },
    "USER.state": {
        "keywords": [
            "state", "your state", "state of residence",
            "applicant state", "state name",
        ],
        "exclude_keywords": ["district", "country"],
        "field_types": ["combobox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.district": {
        "keywords": [
            "district", "your district", "district name",
            "applicant district",
        ],
        "exclude_keywords": ["state", "block", "tehsil"],
        "field_types": ["combobox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.pincode": {
        "keywords": [
            "pincode", "pin code", "pin", "postal code", "zip",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.village": {
        "keywords": [
            "village", "village name", "town", "city",
        ],
        "exclude_keywords": ["district", "state"],
        "field_types": ["textbox", "combobox"],
        "confidence": MappingConfidence.MEDIUM,
    },
    # --- Government IDs ---
    "USER.aadhaar_number": {
        "keywords": [
            "aadhaar", "aadhar", "uid", "aadhaar number",
            "aadhaar no", "12 digit aadhaar",
        ],
        "exclude_keywords": ["enrollment", "virtual"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.pan_number": {
        "keywords": [
            "pan", "pan number", "pan card", "permanent account number",
            "pan no",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.voter_id": {
        "keywords": [
            "voter id", "voter id number", "epic number", "voterid",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    # --- Education ---
    "USER.education": {
        "keywords": [
            "education", "qualification", "highest qualification",
            "educational qualification", "degree", "education level",
        ],
        "exclude_keywords": [],
        "field_types": ["combobox"],
        "confidence": MappingConfidence.MEDIUM,
    },
    # --- Employment ---
    "USER.occupation": {
        "keywords": [
            "occupation", "occupation type", "your occupation",
            "profession", "nature of work",
        ],
        "exclude_keywords": [],
        "field_types": ["combobox"],
        "confidence": MappingConfidence.MEDIUM,
    },
    "USER.annual_income": {
        "keywords": [
            "annual income", "family income",
            "total income", "yearly income", "gross income",
            "income per annum",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox", "combobox"],
        "confidence": MappingConfidence.MEDIUM,
    },
    # --- Category ---
    "USER.category": {
        "keywords": [
            "category", "social category", "community",
            "caste category", "reservation category",
        ],
        "exclude_keywords": [],
        "field_types": ["combobox", "radiogroup"],
        "confidence": MappingConfidence.MEDIUM,
    },
    # --- Family ---
    "USER.father_name": {
        "keywords": [
            "father name", "father's name", "father",
        ],
        "exclude_keywords": ["mother", "spouse", "husband"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.mother_name": {
        "keywords": [
            "mother name", "mother's name", "mother",
        ],
        "exclude_keywords": ["father"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.spouse_name": {
        "keywords": [
            "spouse name", "spouse", "husband name",
            "wife name", "husband", "wife",
        ],
        "exclude_keywords": ["father", "mother"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.guardian_name": {
        "keywords": [
            "guardian name", "guardian", "parent name",
        ],
        "exclude_keywords": ["father", "mother", "spouse"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.MEDIUM,
    },
    # --- Financial ---
    "USER.bank_account": {
        "keywords": [
            "bank account", "account number", "account no",
            "bank account number",
        ],
        "exclude_keywords": ["ifsc", "branch"],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    "USER.ifsc_code": {
        "keywords": [
            "ifsc", "ifsc code", "ifsc number",
            "bank ifsc",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    # --- Documents ---
    # Note: field_types includes "file" for input_type matching
    "DOCUMENT.aadhaar": {
        "keywords": [
            "aadhaar", "aadhaar document", "aadhaar card",
            "upload aadhaar",
        ],
        "exclude_keywords": [],
        "field_types": ["file"],
        "confidence": MappingConfidence.HIGH,
    },
    "DOCUMENT.income_certificate": {
        "keywords": [
            "income certificate", "income proof",
            "income certificate upload",
        ],
        "exclude_keywords": [],
        "field_types": ["file"],
        "confidence": MappingConfidence.HIGH,
    },
    "DOCUMENT.photo": {
        "keywords": [
            "photo", "photograph", "passport photo",
            "candidate photo", "applicant photo", "upload photo",
        ],
        "exclude_keywords": ["id", "card"],
        "field_types": ["file"],
        "confidence": MappingConfidence.HIGH,
    },
    "DOCUMENT.signature": {
        "keywords": [
            "signature", "sign", "digital signature",
            "upload signature",
        ],
        "exclude_keywords": [],
        "field_types": ["file"],
        "confidence": MappingConfidence.HIGH,
    },
}


def _element_matches_field_type(element: ElementState, field_types: list[str]) -> bool:
    """Check if an element matches the expected field types.

    Matches against BOTH role AND input_type per audit #4.
    For file uploads, input_type='file' is the authoritative signal.
    """
    if not field_types:
        return True

    # Check role
    if element.role and element.role in field_types:
        return True

    # Check input_type (critical for file inputs per audit #4)
    if element.input_type and element.input_type in field_types:
        return True

    return False


class FieldMapper:
    """Maps website form fields to user-data references.

    Uses a tiered approach:
    1. Deterministic local matching (fast, free)
    2. LLM-based resolution for ambiguous AND unmapped cases
    3. ReferenceRegistry validation for all bindings

    The mapper distinguishes between semantically similar labels
    (e.g., "Applicant Name" vs "Father Name" vs "Spouse Name").
    """

    def __init__(
        self,
        llm_gateway: LLMGateway | None = None,
        registry: ReferenceRegistry | None = None,
    ) -> None:
        self._llm = llm_gateway
        self._registry = registry or get_registry()
        self._rules = DETERMINISTIC_RULES
        self._sanitizer = PromptSanitizer()

    def _get_field_text(self, element: ElementState) -> str:
        """Collect all text signals from an element for matching."""
        parts = [
            element.accessible_name or "",
            element.label_text or "",
            element.html_name or "",
            element.placeholder or "",
            element.section_heading or "",
            element.help_text or "",
            element.group_label or "",
            element.nearby_text or "",
        ]
        return " ".join(p for p in parts if p).lower().strip()

    def _match_deterministic(
        self, element: ElementState
    ) -> FieldBinding | None:
        """Try to match an element against deterministic rules.

        Returns a FieldBinding if a match is found, None otherwise.
        """
        text = self._get_field_text(element)
        if not text:
            return None

        best_match: tuple[str, dict, float] | None = None

        for binding_key, rule in self._rules.items():
            # Check field type compatibility (role OR input_type)
            if not _element_matches_field_type(element, rule["field_types"]):
                continue

            # Check exclude keywords first
            if rule["exclude_keywords"]:
                if any(excl in text for excl in rule["exclude_keywords"]):
                    continue

            # Score matching keywords
            matched_keywords = [
                kw for kw in rule["keywords"] if kw in text
            ]

            if not matched_keywords:
                continue

            # Filter out very short keywords unless they are the best match
            long_matches = [kw for kw in matched_keywords if len(kw) >= 4]
            if not long_matches:
                # Only short keywords matched (e.g., "name", "pin")
                # Only accept if the keyword IS the entire accessible name
                acc_name = (element.accessible_name or "").lower().strip()
                dominant = any(kw == acc_name for kw in matched_keywords)
                if not dominant:
                    continue
                matched_keywords = [acc_name]
            else:
                matched_keywords = long_matches

            # Calculate score using the BEST (longest) matching keyword
            best_kw = max(matched_keywords, key=len)

            # Exact match: keyword matches the full accessible name
            acc_name = (element.accessible_name or "").lower()
            if best_kw == acc_name or best_kw == text:
                score = 1.0
            elif best_kw in acc_name:
                score = 0.6 + 0.2 * (len(best_kw) / max(len(acc_name), 1))
            else:
                score = 0.3 + 0.1 * (len(best_kw) / max(len(text), 1))

            if best_match is None or score > best_match[2]:
                best_match = (binding_key, rule, score)

        if best_match is None:
            return None

        binding_key, rule, score = best_match

        # Validate against ReferenceRegistry
        if not self._registry.validate(binding_key):
            logger.warning("Deterministic match '%s' not in registry — skipping", binding_key)
            return None

        # Determine confidence based on score and rule confidence
        if score >= 0.7:
            confidence = rule["confidence"]
        elif score >= 0.4:
            confidence = MappingConfidence.MEDIUM
        else:
            confidence = MappingConfidence.LOW

        # Collect evidence
        evidence = [
            f"accessible_name='{element.accessible_name}'",
            f"label_text='{element.label_text}'",
            f"html_name='{element.html_name}'",
            f"role='{element.role}'",
        ]
        if element.section_heading:
            evidence.append(f"section='{element.section_heading}'")
        if element.group_label:
            evidence.append(f"group='{element.group_label}'")

        return FieldBinding(
            field_ref=element.ref,
            binding=binding_key,
            confidence=confidence,
            strategy=MappingStrategy.DETERMINISTIC,
            evidence=[e for e in evidence if "=" in e and "''" not in e],
            field_type=element.role,
            field_label=element.accessible_name or element.label_text,
        )

    def _build_llm_schema(self) -> dict:
        """Build JSON schema for LLM structured output."""
        all_refs = self._registry.get_all_refs(visible_only=True)
        ref_list = "\n".join(f"  - {k} ({v})" for k, v in sorted(all_refs.items()))

        return {
            "type": "object",
            "properties": {
                "mappings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ref": {"type": "string"},
                            "binding": {"type": "string"},
                            "confidence": {
                                "type": "string",
                                "enum": ["high", "medium", "low", "none"],
                            },
                            "reasoning": {"type": "string"},
                        },
                        "required": ["ref", "binding", "confidence", "reasoning"],
                    },
                },
            },
            "required": ["mappings"],
        }

    def _build_llm_prompt(
        self,
        candidate_info: list[dict],
    ) -> tuple[str, str]:
        """Build system and user prompts for LLM resolution.

        Per audit #42: sends reference KEYS only, not vault values.
        """
        all_refs = self._registry.get_all_refs(visible_only=True)
        available_fields = "\n".join(
            f"  - {k} ({v})" for k, v in sorted(all_refs.items())
        )

        system_prompt = f"""You are a field mapping assistant for government form filling.

Your task: map website form fields to user-data references.

Available user-data references:
{available_fields}

RULES:
1. Each field maps to exactly ONE user-data reference from the list above.
2. Output ONLY references from the list above. Do NOT invent new references.
3. Distinguish between semantically similar fields:
   - "Applicant Name" -> USER.full_name
   - "Father Name" -> USER.father_name
   - "Mother Name" -> USER.mother_name
   - "Spouse Name" -> USER.spouse_name
   - "Guardian Name" -> USER.guardian_name (do NOT assume guardian = father)
4. For dropdowns, the binding represents what value to select.
5. For file uploads, use DOCUMENT.* references.
6. If uncertain, set confidence to "low".
7. NEVER map authentication fields (password, OTP, CAPTCHA).
8. NEVER map payment fields.
9. Output ONLY valid JSON matching the schema."""

        user_prompt = f"""Map these form fields to user-data references:

{json.dumps(candidate_info, indent=2)}

Return mappings for each field ref. If a field cannot be mapped, set binding to null and confidence to "none"."""

        return system_prompt, user_prompt

    def _validate_llm_binding(self, binding: str | None) -> bool:
        """Validate an LLM-produced binding against ReferenceRegistry.

        Per audit #11: LLM output is untrusted — always validate.
        """
        if not binding:
            return False
        return self._registry.validate(binding)

    async def _resolve_with_llm(
        self,
        elements: list[ElementState],
        field_refs: list[str],
    ) -> list[FieldBinding]:
        """Use LLM to resolve field mappings for ambiguous AND unmapped fields.

        Per audit #8: unmapped fields are also sent to LLM.
        Per audit #42: only reference keys are sent, not vault values.
        Per audit #11: LLM output is validated against ReferenceRegistry.
        """
        if self._llm is None:
            logger.warning("No LLM gateway — cannot resolve mappings")
            return []

        elements_by_ref = {e.ref: e for e in elements}

        candidate_info = []
        for ref in field_refs:
            el = elements_by_ref.get(ref)
            if el:
                candidate_info.append({
                    "ref": ref,
                    "label": el.accessible_name or el.label_text or el.html_name or "",
                    "type": el.role or "unknown",
                    "input_type": el.input_type or "",
                    "section": el.section_heading or "",
                    "group": el.group_label or "",
                    "help_text": el.help_text or "",
                })

        # Sanitize all candidate info before sending to LLM
        candidate_info = self._sanitizer.sanitize_elements(candidate_info)

        if not candidate_info:
            return []

        schema = self._build_llm_schema()
        system_prompt, user_prompt = self._build_llm_prompt(candidate_info)

        try:
            response = await self._llm.complete(
                system=system_prompt,
                user=user_prompt,
                schema=schema,
                temperature=0.0,
            )

            bindings = []
            if response.parsed and "mappings" in response.parsed:
                for mapping in response.parsed["mappings"]:
                    ref = mapping.get("ref", "")
                    raw_binding = mapping.get("binding")

                    # Per audit #11: validate against registry
                    if not self._validate_llm_binding(raw_binding):
                        logger.warning(
                            "LLM produced invalid binding '%s' for ref '%s' — rejecting",
                            raw_binding, ref,
                        )
                        continue

                    confidence_str = mapping.get("confidence", "medium")
                    try:
                        confidence = MappingConfidence(confidence_str)
                    except ValueError:
                        confidence = MappingConfidence.MEDIUM

                    evidence = [f"accessible_name='{elements_by_ref[ref].accessible_name}'"]
                    if mapping.get("reasoning"):
                        evidence.append(f"llm_reasoning: {mapping['reasoning']}")

                    bindings.append(FieldBinding(
                        field_ref=ref,
                        binding=raw_binding,
                        confidence=confidence,
                        strategy=MappingStrategy.LLM,
                        evidence=evidence,
                        field_type=elements_by_ref[ref].role,
                        field_label=elements_by_ref[ref].accessible_name,
                    ))

            return bindings

        except Exception as e:
            logger.warning("LLM resolution failed: %s", e)
            return []

    async def map_fields(
        self,
        observation: PageObservation,
    ) -> MappingResult:
        """Map all interactive elements on a page to user-data references.

        Per audit #42: does NOT accept vault values — only uses reference keys.
        Per audit #8: unmapped fields are sent to LLM.
        Per audit #12: bindings include observation_id.

        Args:
            observation: Current page observation

        Returns:
            MappingResult with all bindings
        """
        page_state = observation.page_state
        elements = page_state.elements
        obs_id = observation.observation_id

        # Phase 1: Deterministic matching
        bindings: list[FieldBinding] = []
        unmapped: list[str] = []
        ambiguous: list[str] = []

        for element in elements:
            # Skip non-interactive elements
            if element.role not in (
                "textbox", "combobox", "radiogroup",
                "checkbox", "button", "link", "file",
            ):
                continue

            # Skip disabled elements
            if element.disabled:
                continue

            binding = self._match_deterministic(element)
            if binding is None:
                unmapped.append(element.ref)
            elif binding.confidence in (
                MappingConfidence.MEDIUM,
                MappingConfidence.LOW,
            ):
                ambiguous.append(element.ref)
                bindings.append(binding)
            else:
                bindings.append(binding)

        # Phase 2: LLM resolution for ambiguous + unmapped fields
        llm_refs = ambiguous + unmapped
        if llm_refs and self._llm is not None:
            llm_bindings = await self._resolve_with_llm(elements, llm_refs)

            # Replace ambiguous bindings with LLM-resolved ones
            llm_by_ref = {b.field_ref: b for b in llm_bindings}

            updated_bindings = []
            for b in bindings:
                if b.field_ref in llm_by_ref:
                    updated_bindings.append(llm_by_ref[b.field_ref])
                else:
                    updated_bindings.append(b)

            # Add new LLM bindings for previously unmapped fields
            for ref in unmapped:
                if ref in llm_by_ref:
                    updated_bindings.append(llm_by_ref[ref])

            bindings = updated_bindings

        # Set observation_id on all bindings (per audit #12)
        for b in bindings:
            b.observation_id = obs_id

        # Recalculate unmapped (fields with no binding at all)
        bound_refs = {b.field_ref for b in bindings}
        final_unmapped = [
            ref for ref in unmapped
            if ref not in bound_refs
        ]

        # Count strategies
        strategy_counts: dict[str, int] = {}
        for b in bindings:
            strategy_counts[b.strategy.value] = (
                strategy_counts.get(b.strategy.value, 0) + 1
            )

        # Re-check ambiguous after LLM resolution
        final_ambiguous = [
            b.field_ref for b in bindings
            if b.confidence in (MappingConfidence.MEDIUM, MappingConfidence.LOW)
        ]

        mapped_count = len(bindings)

        return MappingResult(
            bindings=bindings,
            unmapped_fields=final_unmapped,
            ambiguous_fields=final_ambiguous,
            total_fields=len(elements),
            mapped_count=mapped_count,
            strategy_counts=strategy_counts,
        )
