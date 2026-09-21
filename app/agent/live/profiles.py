"""Phase 14 portal profiles for the selected live validation set.

Selection criteria (Phase 14 plan): accessibility, public availability,
low-risk workflow availability, stable navigation, deterministic/safe form
behavior, no real-world side effects, useful architectural coverage.

These profiles are trusted METADATA ONLY — never executable scripts.
Safe test paths are recorded only after being exercised on the live portal.
"""

from __future__ import annotations

from app.agent.live.models import PortalClass, PortalProfile


def offline_portal_profile(*, portal_id: str, name: str, entrypoint_uri: str) -> PortalProfile:
    """Create a TEST-ONLY profile bound to a local file:// fixture page."""
    from app.agent.live.models import PortalProfile as _PP

    return _PP.offline_test_profile(
        portal_id=portal_id,
        name=name,
        entrypoint_uri=entrypoint_uri,
    )

PMKISAN_PORTAL = PortalProfile(
    portal_id="pmkisan",
    name="PM-KISAN (pmkisan.gov.in)",
    official_origin="https://pmkisan.gov.in",
    portal_class=PortalClass.WELFARE,
    entrypoint="https://pmkisan.gov.in",
    trusted_domains=["pmkisan.gov.in"],
    observed_workflow=(
        "Landing page with navigation links (Farmers Corner sections), "
        "eKYC/login links behind authentication boundaries, beneficiary "
        "status/search links. Public pages are observation-safe."
    ),
    authentication_requirements=(
        "Beneficiary eKYC requires Aadhaar + CAPTCHA + OTP — human boundary. "
        "Never bypassed; observation stops at the boundary."
    ),
    document_requirements="None on public pages",
    known_constraints=[
        "Dynamic JS-driven navigation on landing page",
        "Auth boundary on eKYC/login — HITL required beyond that point",
    ],
    safe_test_path="Observation of landing page only; no form submission",
    last_verified_at="2026-09-20",
)

MYScheme_PORTAL = PortalProfile(
    portal_id="myscheme",
    name="MyScheme (myscheme.gov.in)",
    official_origin="https://www.myscheme.gov.in",
    portal_class=PortalClass.CERTIFICATE,
    entrypoint="https://www.myscheme.gov.in",
    trusted_domains=["myscheme.gov.in"],
    observed_workflow=(
        "Scheme discovery portal: search box, filters, link-driven navigation. "
        "No citizen-data mutation on public pages."
    ),
    authentication_requirements="None on public discovery pages",
    document_requirements="None on public discovery pages",
    known_constraints=["Search is JS-driven; results load asynchronously"],
    safe_test_path="Observation of landing page + public search semantics; no submission",
    last_verified_at="2026-09-20",
)

NCS_PORTAL = PortalProfile(
    portal_id="ncs",
    name="National Career Service (ncs.gov.in)",
    official_origin="https://ncs.gov.in",
    portal_class=PortalClass.RECRUITMENT,
    entrypoint="https://ncs.gov.in",
    trusted_domains=["ncs.gov.in"],
    observed_workflow=(
        "Career services portal: job search controls, navigation links, "
        "public information pages. Job seeker features sit behind login/HITL."
    ),
    authentication_requirements=(
        "Job seeker/employer features require registration + login — human boundary"
    ),
    document_requirements="None on public pages",
    known_constraints=["JS-driven navigation; generic element names on landing page"],
    safe_test_path="Observation of landing page + public search semantics; no submission",
    last_verified_at="2026-09-20",
)

INDIA_PORTAL = PortalProfile(
    portal_id="indiaportal",
    name="National Services Portal (services.india.gov.in)",
    official_origin="https://services.india.gov.in",
    portal_class=PortalClass.GRIEVANCE,
    entrypoint="https://services.india.gov.in",
    trusted_domains=["services.india.gov.in", "india.gov.in"],
    observed_workflow=(
        "National services directory: public search box, service categories, "
        "how-to navigation. Pure discovery; no citizen-data mutation."
    ),
    authentication_requirements="None on public pages",
    document_requirements="None on public pages",
    known_constraints=[
        "www.india.gov.in (sibling gateway) serves an Akamai anti-bot block "
        "to automated browsers — recorded as ANTI_BOT_BLOCK, not attempted twice",
    ],
    safe_test_path="Observation + public search semantics within the official origin",
    last_verified_at="2026-09-20",
)

APPRENTICESHIP_PORTAL = PortalProfile(
    portal_id="apprenticeship",
    name="National Apprenticeship Training Scheme (apprenticeshipindia.gov.in)",
    official_origin="https://www.apprenticeshipindia.gov.in",
    portal_class=PortalClass.TRAINING,
    entrypoint="https://www.apprenticeshipindia.gov.in",
    trusted_domains=["apprenticeshipindia.gov.in"],
    observed_workflow=(
        "Apprenticeship training portal: opportunity search by district/trade, "
        "establishment and TNI directories. Candidate registration and "
        "applications sit behind login — human boundary."
    ),
    authentication_requirements=(
        "Candidate/establishment features require registration + login — human boundary"
    ),
    document_requirements="None on public pages",
    known_constraints=["JS-driven navigation on landing page"],
    safe_test_path="Observation of landing page + public search semantics; no submission",
    last_verified_at="2026-09-21",
)

UDISE_PORTAL = PortalProfile(
    portal_id="udiseplus",
    name="UDISE+ (udiseplus.gov.in)",
    official_origin="https://udiseplus.gov.in",
    portal_class=PortalClass.EDUCATION,
    entrypoint="https://udiseplus.gov.in",
    trusted_domains=["udiseplus.gov.in"],
    observed_workflow=(
        "School education data system: public dashboards, school locator "
        "search, report links. School data entry requires admin login — "
        "human boundary."
    ),
    authentication_requirements=(
        "School data entry requires administrator login — human boundary"
    ),
    document_requirements="None on public pages",
    known_constraints=["Report downloads may require navigation past landing page"],
    safe_test_path="Observation of landing page + public search semantics; no submission",
    last_verified_at="2026-09-21",
)

PARIVAHAN_PORTAL = PortalProfile(
    portal_id="parivahan",
    name="Parivahan Sewa (parivahan.gov.in)",
    official_origin="https://parivahan.gov.in",
    portal_class=PortalClass.TRANSPORT,
    entrypoint="https://parivahan.gov.in",
    trusted_domains=["parivahan.gov.in"],
    observed_workflow=(
        "Transport services gateway: license/vehicle service selection, "
        "state selection dropdowns, informational pages. All transactions "
        "(applications, payments) sit behind auth + payment boundaries."
    ),
    authentication_requirements=(
        "Applications require login; payments are human boundaries"
    ),
    document_requirements="License/RC services require uploaded documents — vault-scoped, human-gated",
    known_constraints=[
        "Heavy JS SPA on service pages; state selection precedes services",
    ],
    safe_test_path="Observation of landing page only; no service selection submission",
    last_verified_at="2026-09-21",
)

DIGILOCKER_PORTAL = PortalProfile(
    portal_id="digilocker",
    name="DigiLocker (digilocker.gov.in)",
    official_origin="https://www.digilocker.gov.in",
    portal_class=PortalClass.IDENTITY_DOCUMENT,
    entrypoint="https://www.digilocker.gov.in",
    trusted_domains=["digilocker.gov.in"],
    observed_workflow=(
        "Digital document repository: informational pages, document issuer "
        "directory, public search. All document access requires Aadhaar "
        "authentication — strictly human boundary."
    ),
    authentication_requirements=(
        "Document access requires Aadhaar + OTP login — human boundary, "
        "never bypassed; observation stops at the boundary"
    ),
    document_requirements=(
        "Issued documents are vault-class sensitive data — never accessed "
        "autonomously"
    ),
    known_constraints=["Auth boundary is the primary workflow surface"],
    safe_test_path="Observation of landing page only; no authentication attempt",
    last_verified_at="2026-09-21",
)

PASSPORT_PORTAL = PortalProfile(
    portal_id="passport",
    name="Passport Seva (passportindia.gov.in)",
    official_origin="https://www.passportindia.gov.in",
    portal_class=PortalClass.APPOINTMENTS,
    entrypoint="https://www.passportindia.gov.in",
    trusted_domains=["passportindia.gov.in"],
    observed_workflow=(
        "Passport services portal: information pages, PSK locator, fee "
        "calculator. Appointment booking sits behind login + payment — "
        "human boundaries."
    ),
    authentication_requirements=(
        "Application/appointment requires login; fee payment is a human boundary"
    ),
    document_requirements="Applications require document upload — vault-scoped, human-gated",
    known_constraints=["Landing page is largely informational; appointment flow is auth-gated"],
    safe_test_path="Observation of landing page only; no booking or payment attempt",
    last_verified_at="2026-09-21",
)

_PROFILES: dict[str, PortalProfile] = {
    p.portal_id: p
    for p in (
        PMKISAN_PORTAL,
        MYScheme_PORTAL,
        NCS_PORTAL,
        INDIA_PORTAL,
        APPRENTICESHIP_PORTAL,
        UDISE_PORTAL,
        PARIVAHAN_PORTAL,
        DIGILOCKER_PORTAL,
        PASSPORT_PORTAL,
    )
}


def register_profile(profile: PortalProfile) -> None:
    """Register a profile (used by offline pipeline tests for file:// fixtures).

    Live profiles come from this module's constants; this hook exists so the
    shadow/controlled pipeline can be exercised end-to-end on local fixtures
    without touching any live portal.
    """
    _PROFILES[profile.portal_id] = profile


def get_live_portal_profile(portal_id: str) -> PortalProfile:
    try:
        return _PROFILES[portal_id]
    except KeyError as e:
        raise KeyError(
            f"Unknown live portal profile: {portal_id}. "
            f"Known: {sorted(_PROFILES)}"
        ) from e
