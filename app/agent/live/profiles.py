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

_PROFILES: dict[str, PortalProfile] = {
    p.portal_id: p for p in (PMKISAN_PORTAL, MYScheme_PORTAL, NCS_PORTAL, INDIA_PORTAL)
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
