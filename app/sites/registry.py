"""Trusted government domain registry.

Per audit #36:
- TrustedDomainRegistry for verifying government portals
- Before navigation: check domain against registry
- Unverified sites require explicit confirmation
- Do NOT add site-specific scripts — generic browser agent only
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DomainEntry(BaseModel):
    """A trusted government domain entry."""

    domain: str = Field(description="Domain name (e.g., 'pmkisan.gov.in')")
    official_name: str = Field(default="", description="Official name of the service")
    government_level: str = Field(
        default="central",
        description="central | state | local"
    )
    verified: bool = Field(default=True, description="Whether domain is verified")
    allowed: bool = Field(default=True, description="Whether automation is allowed")
    special_constraints: list[str] = Field(
        default_factory=list,
        description="Special rules for this domain"
    )
    notes: str = Field(default="", description="Additional notes")


# ============================================================
# Default trusted government domains
# ============================================================

_DEFAULT_DOMAINS: list[dict[str, Any]] = [
    # Central Government
    {"domain": "pmkisan.gov.in", "official_name": "PM-KISAN",
     "government_level": "central"},
    {"domain": "uidai.gov.in", "official_name": "UIDAI (Aadhaar)",
     "government_level": "central"},
    {"domain": "incometax.gov.in", "official_name": "Income Tax Department",
     "government_level": "central"},
    {"domain": "india.gov.in", "official_name": "National Portal of India",
     "government_level": "central"},
    {"domain": "digitalindia.gov.in", "official_name": "Digital India",
     "government_level": "central"},
    {"domain": "scholarships.gov.in", "official_name": "National Scholarship Portal",
     "government_level": "central"},
    {"domain": "epfindia.gov.in", "official_name": "EPFO",
     "government_level": "central"},
    {"domain": "nps.nsdl.com", "official_name": "National Pension System",
     "government_level": "central"},
    {"domain": "insight.gov.in", "official_name": "INSIGHT Government",
     "government_level": "central"},
    {"domain": "registration.gov.in", "official_name": "Foreigners Registration",
     "government_level": "central"},
    {"domain": "parivahan.gov.in", "official_name": "Parivahan (Transport)",
     "government_level": "central"},
    {"domain": "passportindia.gov.in", "official_name": "Passport Seva",
     "government_level": "central"},
    {"domain": "ccebc.gov.in", "official_name": "Central Council for CBSE",
     "government_level": "central"},
    {"domain": "udiseplus.gov.in", "official_name": "UDISE+ Education",
     "government_level": "central"},
    {"domain": "gst.gov.in", "official_name": "GST Portal",
     "government_level": "central"},
    {"domain": "mca.gov.in", "official_name": "Ministry of Corporate Affairs",
     "government_level": "central"},
    {"domain": "epfo.gov.in", "official_name": "Employees' Provident Fund",
     "government_level": "central"},

    # State Government — Kerala
    {"domain": "kerala.gov.in", "official_name": "Government of Kerala",
     "government_level": "state"},
    {"domain": "kstfieldset.kerala.gov.in", "official_name": "Kerala SET",
     "government_level": "state"},

    # State Government — Karnataka
    {"domain": "karnataka.gov.in", "official_name": "Government of Karnataka",
     "government_level": "state"},

    # State Government — Tamil Nadu
    {"domain": "tn.gov.in", "official_name": "Government of Tamil Nadu",
     "government_level": "state"},

    # State Government — Maharashtra
    {"domain": "maharashtra.gov.in", "official_name": "Government of Maharashtra",
     "government_level": "state"},

    # State Government — Delhi
    {"domain": "delhi.gov.in", "official_name": "Government of NCT of Delhi",
     "government_level": "state"},
]


class TrustedDomainRegistry:
    """Registry of trusted government domains.

    Per audit #36: check domain before navigation.
    Unverified sites require explicit user confirmation.
    """

    def __init__(self) -> None:
        self._domains: dict[str, DomainEntry] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load default trusted government domains."""
        for entry_data in _DEFAULT_DOMAINS:
            try:
                domain_val = entry_data.get("domain", "")
                if not isinstance(domain_val, str) or not domain_val:
                    continue
                entry = DomainEntry(**entry_data)
                self._domains[entry.domain] = entry
            except Exception:
                continue

    def is_trusted(self, url: str) -> bool:
        """Check if a URL's domain is in the trusted registry."""
        domain = self._extract_domain(url)
        if not domain:
            return False
        entry = self._domains.get(domain)
        return entry is not None and entry.allowed and entry.verified

    def is_known(self, url: str) -> bool:
        """Check if a URL's domain is known (even if not trusted)."""
        domain = self._extract_domain(url)
        if not domain:
            return False
        return domain in self._domains

    def get_entry(self, url: str) -> DomainEntry | None:
        """Get the domain entry for a URL."""
        domain = self._extract_domain(url)
        if not domain:
            return None
        return self._domains.get(domain)

    def get_constraints(self, url: str) -> list[str]:
        """Get special constraints for a domain."""
        entry = self.get_entry(url)
        if entry:
            return entry.special_constraints
        return []

    def register(self, entry: DomainEntry) -> None:
        """Register a new trusted domain."""
        self._domains[entry.domain] = entry

    def _extract_domain(self, url: str) -> str | None:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return None

    def list_domains(self) -> list[str]:
        """List all registered domains."""
        return sorted(self._domains.keys())

    def __len__(self) -> int:
        return len(self._domains)

    def __contains__(self, domain: str) -> bool:
        return domain in self._domains
