"""Semantic field mapper — maps website form fields to user-data references.

Phase 6 deliverables:
- Deterministic local matching (keyword/semantic rules)
- LLM-based ambiguous resolution via OpenRouter
- Confidence scoring with three levels (HIGH/MEDIUM/LOW)
- Evidence trail for audit
- Distinction between semantically similar labels

Architecture:
    PageState
        ↓
    deterministic matching
        ↓
    ambiguous candidates?
        ├── NO → return FieldBinding
        └── YES → LLM structured reasoning → FieldBinding
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
from app.llm.base import LLMGateway
from app.models.page_state import ElementState, PageObservation, PageState

logger = logging.getLogger(__name__)


# ============================================================
# Deterministic mapping rules
# ============================================================

# Canonical binding → (keywords, field_types, confidence)
# Keywords are matched against: label_text, accessible_name, html_name,
# placeholder, section_heading, help_text, nearby_text
DETERMINISTIC_RULES: dict[str, dict[str, Any]] = {
    # --- Identity ---
    "USER.full_name": {
        "keywords": [
            "full name", "applicant name", "name of applicant",
            "candidate name", "legal name", "name as per aadhaar",
            "your name", "enter name", "name",
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
            "annual income", "income", "family income",
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
            "parent name", "guardian name",
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
            "bank ifsc", "ifsc code",
        ],
        "exclude_keywords": [],
        "field_types": ["textbox"],
        "confidence": MappingConfidence.HIGH,
    },
    # --- Documents ---
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


class FieldMapper:
    """Maps website form fields to user-data references.

    Uses a tiered approach:
    1. Deterministic local matching (fast, free)
    2. LLM-based resolution for ambiguous cases (slower, costs tokens)

    The mapper distinguishes between semantically similar labels
    (e.g., "Applicant Name" vs "Father Name" vs "Spouse Name").
    """

    def __init__(self, llm_gateway: LLMGateway | None = None) -> None:
        self._llm = llm_gateway
        self._rules = DETERMINISTIC_RULES

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
            # Check if field type matches (if rule specifies types)
            if rule["field_types"]:
                if element.role and element.role not in rule["field_types"]:
                    continue

            # Check exclude keywords first
            if rule["exclude_keywords"]:
                if any(excl in text for excl in rule["exclude_keywords"]):
                    continue

            # Score matching keywords
            # Require longest matching keyword to be at least 4 chars
            # to avoid false positives like "name" matching "Random Widget Name"
            matched_keywords = []
            for kw in rule["keywords"]:
                if kw in text:
                    matched_keywords.append(kw)

            if not matched_keywords:
                continue

            # Filter out very short keywords unless they are the best match
            long_matches = [kw for kw in matched_keywords if len(kw) >= 4]
            if not long_matches:
                # Only short keywords matched (e.g., "name", "pin")
                # Only accept if the keyword IS the entire accessible name
                # e.g., accessible_name="Name" and keyword="name"
                acc_name = (element.accessible_name or "").lower().strip()
                dominant = any(kw == acc_name for kw in matched_keywords)
                if not dominant:
                    continue
                matched_keywords = [acc_name]  # Use the full accessible name
            else:
                matched_keywords = long_matches

            # Calculate score using the BEST (longest) matching keyword
            # Longer keywords = more specific = higher confidence
            best_kw = max(matched_keywords, key=len)

            # Exact match: keyword matches the full accessible name
            acc_name = (element.accessible_name or "").lower()
            if best_kw == acc_name or best_kw == text:
                score = 1.0  # Perfect match
            elif best_kw in acc_name:
                # Keyword is a substring of the accessible name
                # e.g., "full name" in "full name of applicant"
                score = 0.6 + 0.2 * (len(best_kw) / max(len(acc_name), 1))
            else:
                # Keyword matches in combined text but not in name alone
                score = 0.3 + 0.1 * (len(best_kw) / max(len(text), 1))

            if best_match is None or score > best_match[2]:
                best_match = (binding_key, rule, score)

        if best_match is None:
            return None

        binding_key, rule, score = best_match

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

    async def _resolve_ambiguous(
        self,
        elements: list[ElementState],
        candidates: list[FieldBinding],
        vault_fields: dict[str, str],
    ) -> list[FieldBinding]:
        """Use LLM to resolve ambiguous field mappings.

        Only called when deterministic matching produces MEDIUM/LOW confidence.
        """
        if self._llm is None:
            logger.warning("No LLM gateway — cannot resolve ambiguous mappings")
            return candidates

        # Build prompt for LLM
        elements_by_ref = {e.ref: e for e in elements}

        candidate_info = []
        for c in candidates:
            el = elements_by_ref.get(c.field_ref)
            if el:
                candidate_info.append({
                    "ref": c.field_ref,
                    "label": el.accessible_name or el.label_text or el.html_name or "",
                    "type": el.role or "unknown",
                    "current_binding": c.binding,
                    "current_confidence": c.confidence.value,
                    "section": el.section_heading or "",
                    "group": el.group_label or "",
                })

        schema = {
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

        available_fields = "\n".join(
            f"- {k}" for k in sorted(vault_fields.keys())
        )

        system_prompt = f"""You are a field mapping assistant for government form filling.

Your task: map website form fields to user-data references.

Available user-data references:
{available_fields}

RULES:
1. Each field maps to exactly ONE user-data reference.
2. Distinguish between semantically similar fields:
   - "Applicant Name" -> USER.full_name
   - "Father Name" -> USER.father_name
   - "Mother Name" -> USER.mother_name
   - "Spouse Name" -> USER.spouse_name
   - "Guardian Name" -> USER.father_name (if father is guardian)
3. For dropdowns, the binding represents what value to select.
4. For file uploads, use DOCUMENT.* references.
5. If uncertain, set confidence to "low".
6. NEVER map authentication fields (password, OTP, CAPTCHA).
7. NEVER map payment fields.
8. Output ONLY valid JSON matching the schema."""

        user_prompt = f"""Map these form fields to user-data references:

{json.dumps(candidate_info, indent=2)}

Return mappings for each field ref. If a field cannot be mapped, set binding to null and confidence to "none"."""

        try:
            response = await self._llm.complete(
                system=system_prompt,
                user=user_prompt,
                schema=schema,
                temperature=0.0,
            )

            if response.parsed and "mappings" in response.parsed:
                llm_mappings = response.parsed["mappings"]

                # Merge LLM results into candidates
                updated = []
                for c in candidates:
                    llm_match = next(
                        (m for m in llm_mappings if m.get("ref") == c.field_ref),
                        None,
                    )
                    if llm_match and llm_match.get("binding"):
                        c.binding = llm_match["binding"]
                        c.confidence = MappingConfidence(
                            llm_match.get("confidence", "medium")
                        )
                        c.strategy = MappingStrategy.LLM
                        if llm_match.get("reasoning"):
                            c.evidence.append(
                                f"llm_reasoning: {llm_match['reasoning']}"
                            )
                    updated.append(c)
                return updated

        except Exception as e:
            logger.warning("LLM resolution failed: %s", e)

        return candidates

    async def map_fields(
        self,
        observation: PageObservation,
        vault_fields: dict[str, str] | None = None,
    ) -> MappingResult:
        """Map all interactive elements on a page to user-data references.

        Args:
            observation: Current page observation
            vault_fields: Available vault fields (e.g., {"USER.full_name": "John Doe"})

        Returns:
            MappingResult with all bindings
        """
        page_state = observation.page_state
        elements = page_state.elements

        if vault_fields is None:
            vault_fields = {}

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

        # Phase 2: LLM resolution for ambiguous fields
        if ambiguous and self._llm is not None:
            ambiguous_bindings = [b for b in bindings if b.field_ref in ambiguous]
            resolved = await self._resolve_ambiguous(
                elements, ambiguous_bindings, vault_fields
            )
            # Replace ambiguous bindings with resolved ones
            non_ambiguous = [b for b in bindings if b.field_ref not in ambiguous]
            bindings = non_ambiguous + resolved

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
            unmapped_fields=unmapped,
            ambiguous_fields=final_ambiguous,
            total_fields=len(elements),
            mapped_count=mapped_count,
            strategy_counts=strategy_counts,
        )
