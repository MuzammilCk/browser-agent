# 🌐 Portals — Validation Matrix & Test Status

**Last updated:** 2026-09-20 (Phase 14 live shadow validation)

> **Rule:** A portal is only marked "supported" after a reproducible regression test passes.
> Portals without verified tests are marked `UNVERIFIED`.

---

## Portal Interaction Classes

| Class | Description | Examples |
|-------|-------------|----------|
| **A** | Simple forms | Single-page application |
| **B** | Multi-step forms | Wizard-style application |
| **C** | OTP/authentication | Login + OTP flow |
| **D** | Document uploads | Aadhaar, income cert upload |
| **E** | Dynamic/conditional forms | Dependent dropdowns, conditional fields |
| **F** | Appointments | Slot selection |
| **G** | Payment | Fee payment gateway |
| **H** | Draft/resume | Save and continue later |
| **I** | Multiple linked forms | Sequential applications |
| **J** | Mixed workflows | Combination of above |

---

## Portal Registry

The trusted government domain registry is implemented in `app/sites/registry.py` with 60+ domains. All domains have associated service task descriptions and special constraints.

### Verified Test Set

| # | Portal | Domain | Classes | Status | Test File | Notes |
|---|--------|--------|---------|--------|-----------|-------|
| 1 | PM-KISAN | pmkisan.gov.in | A | OBSERVED | `tests/real_sites/test_pmkisan_observe.py`, `tests/real_sites/test_live_shadow.py` | Phase 1 observation + Phase 14 shadow validation (104 elements, planned trace, evidence persisted) — no data submission |
| 1b | MyScheme | myscheme.gov.in | A | OBSERVED | `tests/real_sites/test_live_shadow.py` | Phase 14 shadow validation — 72 elements, 1 frame, 3 planned search actions; evidence in `tests/live_portal/evidence/myscheme/` |
| 1c | NCS | ncs.gov.in | A | OBSERVED | `tests/real_sites/test_live_shadow.py` | Phase 14 shadow validation — job-search fields planned; city mapping LOW-confidence surfaced as ambiguous (no guess) |
| 1d | India Gateway | india.gov.in / services.india.gov.in | A | BLOCKED_BY_SAFETY / ENVIRONMENT | `tests/real_sites/test_live_shadow.py` | Akamai anti-bot block ("Access Denied") from automation; classified ANTI_BOT_BLOCK/PORTAL_UNAVAILABLE — never an agent failure; not retried |

### Registered Portals (UNVERIFIED)

| # | Portal | Domain | Classes | Status | Notes |
|---|--------|--------|---------|--------|-------|
| 2 | Aadhaar | uidai.gov.in | C, D | UNVERIFIED | Authentication + document upload |
| 3 | Meri Pehchaan | meripehchaan.gov.in | C, H | UNVERIFIED | Authentication + draft/resume |
| 4 | Passport Seva | passportindia.gov.in | B, F, G | UNVERIFIED | Multi-step + appointment + payment |
| 5 | Vahan/Parivahan | parivahan.gov.in, vahan.parivahan.gov.in | B, E | UNVERIFIED | Dynamic service workflow |
| 6 | Income Tax | incometax.gov.in | A, B, C | UNVERIFIED | Multi-step + authentication |
| 7 | GST | gst.gov.in | B, C, G | UNVERIFIED | Multi-stage + OTP + payment |
| 8 | EPFO | epfindia.gov.in | A, C | UNVERIFIED | Authentication workflow |
| 9 | NPS | nps.nsdl.com | B, C, G | UNVERIFIED | Registration + authentication + payment |
| 10 | Scholarships | scholarships.gov.in | A, B | UNVERIFIED | Multi-step application |
| 11 | UDISE+ | udiseplus.gov.in | A | UNVERIFIED | Simple form |
| 12 | DigiLocker | digilocker.gov.in | A, C | UNVERIFIED | Authentication |
| 13 | PMFBY | pmfby.gov.in | A, B | UNVERIFIED | Application form |
| 14 | Soil Health | soilhealth.dac.gov.in | A | UNVERIFIED | Simple form |
| 15 | ABHA | abha.abdm.gov.in | A, C | UNVERIFIED | Authentication |
| 16 | NHA | nha.gov.in | A | UNVERIFIED | Simple form |
| 17 | NCDC | ncdc.gov.in | A | UNVERIFIED | Simple form |
| 18 | NCS | ncs.gov.in | A | UNVERIFIED | Simple form |
| 19 | eShram | eshram.gov.in | A, C | UNVERIFIED | Registration + authentication |
| 20 | Udyam | udyamregistration.gov.in | A, C | UNVERIFIED | Registration + OTP |
| 21 | MCA | mca.gov.in | B, C | UNVERIFIED | Multi-step + authentication |
| 22 | Startup India | startupindia.gov.in | A, B | UNVERIFIED | Multi-step form |
| 23 | India.gov.in | india.gov.in | A | UNVERIFIED | Portal |
| 24 | Digital India | digitalindia.gov.in | A | UNVERIFIED | Portal |
| 25 | UMANG | umang.gov.in | A | UNVERIFIED | Portal |
| 26 | MyScheme | myscheme.gov.in | A, B | UNVERIFIED | Multi-step form |
| 27 | India Post | indiapost.gov.in | A, B, F | UNVERIFIED | Appointment booking |
| 28 | CPGRAMS | pgportal.gov.in | A, C | UNVERIFIED | Grievance + authentication |
| 29 | RTI Online | rtionline.gov.in | A, B | UNVERIFIED | Multi-step form |
| 30 | eCourts | ecourts.gov.in | A, C | UNVERIFIED | Authentication |
| 31 | CIC | cic.gov.in | A | UNVERIFIED | Simple form |
| 32 | IndiaGovt | indiagovt.gov.in | A | UNVERIFIED | Portal |
| 33 | PMAY-MIS | pmaymis.gov.in | A, B | UNVERIFIED | Multi-step form |
| 34 | JaYabharat | jayabharat.gov.in | A | UNVERIFIED | Simple form |
| 35 | NREGA | nrega.nic.in | A | UNVERIFIED | Simple form |
| 36 | PM Ujjwala | lpg.ujjwal.gov.in | A | UNVERIFIED | Simple form |
| 37 | NGDRS | ngdrs.gov.in | A, B, D | UNVERIFIED | Multi-step + document upload |
| 38 | DILRMP | dilrmp.gov.in | A | UNVERIFIED | Simple form |
| 39 | Registration | registration.gov.in | A, C | UNVERIFIED | Authentication |
| 40 | AP Gov | ap.gov.in | A | UNVERIFIED | Portal |
| 41 | AP MeeSeva | ap.meeseva.telangana.gov.in | A, B | UNVERIFIED | Multi-step |
| 42 | Bihar Portal | state.bihar.gov.in | A, B | UNVERIFIED | Multi-step |
| 43 | Bihar RTPS | serviceonline.bihar.gov.in | A, D | UNVERIFIED | Document upload |
| 44 | Delhi Gov | delhi.gov.in | A | UNVERIFIED | Portal |
| 45 | Gujarat Gov | gujarat.gov.in | A | UNVERIFIED | Portal |
| 46 | Goa Gov | goa.gov.in | A | UNVERIFIED | Portal |
| 47 | Haryana Gov | haryana.gov.in | A | UNVERIFIED | Portal |
| 48 | Jharkhand Gov | jharkhand.gov.in | A | UNVERIFIED | Portal |
| 49 | Karnataka Gov | karnataka.gov.in | A | UNVERIFIED | Portal |
| 50 | Kerala Gov | kerala.gov.in | A | UNVERIFIED | Portal |
| 51 | MP Gov | mp.gov.in | A | UNVERIFIED | Portal |
| 52 | Maharashtra Gov | maharashtra.gov.in | A | UNVERIFIED | Portal |
| 53 | Odisha Gov | odisha.gov.in | A | UNVERIFIED | Portal |
| 54 | Punjab Gov | punjab.gov.in | A | UNVERIFIED | Portal |
| 55 | Rajasthan Gov | rajasthan.gov.in | A | UNVERIFIED | Portal |
| 56 | Tamil Nadu Gov | tn.gov.in | A | UNVERIFIED | Portal |
| 57 | Telangana Gov | telangana.gov.in | A | UNVERIFIED | Portal |
| 58 | UP Gov | up.gov.in | A | UNVERIFIED | Portal |
| 59 | West Bengal Gov | wb.gov.in | A | UNVERIFIED | Portal |

---

## Portal Test Status Legend

| Status | Meaning |
|--------|---------|
| `OBSERVED` | Real site observation test passes (ARIA/DOM extraction verified, no data submission) |
| `UNVERIFIED` | Domain registered but no regression test exists |
| `TESTING` | Actively being tested |
| `VERIFIED` | Reproducible regression test passes |
| `BROKEN` | Previously verified, now failing |
| `UNSUPPORTED` | Checked and confirmed not automatable or out of scope |

---

## Domain Registry Structure

The domain registry is defined in code (`app/sites/registry.py`), not as a JSON file. Each entry uses the `DomainEntry` model:

```python
class DomainEntry(BaseModel):
    """A trusted government domain entry with full metadata."""
    domain: str
    organization: str
    official: bool = True
    verified: bool = True
    allowed: bool = True
    state: str | None = None
    categories: list[str]
    authentication_modes: list[str]
    has_payment: bool = False
    final_submission_requires_confirmation: bool = True
    status: str = "UNVERIFIED"
    special_rules: list[str] = []
    tasks: list[SiteTask]
```

### Key API methods:

- `registry.is_trusted(url)` — Check if URL's domain is in trusted registry
- `registry.is_known(url)` — Check if domain is known (even if not trusted)
- `registry.get_entry(url)` — Get full `DomainEntry` for a URL
- `registry.get_constraints(url)` — Get special rules/constraints for a domain
- `registry.list_states()` — List all state names in registry
- `registry.register(entry)` — Register a new trusted domain

---

## Portal Test Results

### PM-KISAN (pmkisan.gov.in)

- Date tested: 2026-09-18 (Phase 1 observation); 2026-09-20 (Phase 14 shadow)
- Class: A (welfare)
- Result: OBSERVED (Phase 14: SHADOW_VALIDATION_SUCCESS)
- Test files: `tests/real_sites/test_pmkisan_observe.py`, `tests/real_sites/test_live_shadow.py`
- Phase 14 evidence: 104 elements observed, 29,366-char ARIA snapshot, language combobox planned with policy risk classification, human review request recorded; evidence in `tests/live_portal/evidence/pmkisan/`
- Actions executed: 0 (observation only)
- Safety blocks: None (observation mode)
- Notes: Skipped by default (operator gate `RUN_REAL_SITE_TESTS=true`); no CI is configured for this repository.

### MyScheme (myscheme.gov.in) — Phase 14

- Date tested: 2026-09-20
- Class: A (certificate/scheme discovery)
- Result: SHADOW_VALIDATION_SUCCESS
- Test file: `tests/real_sites/test_live_shadow.py`
- Evidence: 72 elements, 1 frame detected, 3 planned actions on search controls; `tests/live_portal/evidence/myscheme/`
- Actions executed: 0

### NCS (ncs.gov.in) — Phase 14

- Date tested: 2026-09-20
- Class: A (recruitment)
- Result: SHADOW_VALIDATION_SUCCESS
- Test file: `tests/real_sites/test_live_shadow.py`
- Evidence: 124 elements; job-search fields planned (skills/city); "Enter City" mapped to USER.village at LOW confidence and surfaced as AMBIGUOUS (never guessed); `tests/live_portal/evidence/ncs/`
- Actions executed: 0

### india.gov.in / services.india.gov.in — Phase 14

- Date tested: 2026-09-20
- Class: A (grievance/gateway)
- Result: BLOCKED_BY_SAFETY / ENVIRONMENT (ANTI_BOT_BLOCK)
- Test file: `tests/real_sites/test_live_shadow.py::TestLiveShadowIndiaPortal`
- Evidence: Akamai "Access Denied" page served to the automated browser; detected generically by title and classified `EnvironmentCondition.ANTI_BOT_BLOCK` → `PORTAL_UNAVAILABLE`. NOT an agent failure; observation stage not credited; not retried (rate-limit invariant). `tests/live_portal/evidence/indiaportal/`
- Notes: services.india.gov.in was added to the site registry during Phase 14; its live redirect to the blocked www.india.gov.in/services validated the redirect trusted-domain check.

---

## Site Adapter Policy

Adapters are used **only** when a portal has behavior the generic engine cannot express.

An adapter may contain:
- Official domains list
- Known authentication modes
- Known challenge states
- Portal-specific warnings
- Document restrictions

An adapter must **not** contain:
- Hardcoded click/fill sequences
- Full workflow reproduction

---

## Real Sites Testing

Real site tests (in `tests/real_sites/`) are **observation-only** by design. They:
1. Load the real government portal
2. Observe the page (ARIA snapshot + DOM metadata)
3. Save screenshots and observation results
4. **Never** fill forms, click submit, or interact with data

These tests are **skipped by default** and require `RUN_REAL_SITE_TESTS=true` to run, keeping live observation opt-in during development. (No CI system is configured for this repository; the gate exists for operator safety, not CI.)
