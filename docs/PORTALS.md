# 🌐 Portals — Validation Matrix & Test Status

**Last updated:** 2024-08-24

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

### Suggested First Test Set

| # | Portal | Domain | Classes | Status | Notes |
|---|--------|--------|---------|--------|-------|
| 1 | ServicePlus | serviceonline.gov.in | A, B | UNVERIFIED | Generic service workflow |
| 2 | Udyam | udyamregistration.gov.in | A, C | UNVERIFIED | Registration + OTP boundary |
| 3 | GST | gst.gov.in | B, C | UNVERIFIED | Multi-stage + OTP |
| 4 | Bihar RTPS | serviceonline.bihar.gov.in | A, D | UNVERIFIED | Documents + acknowledgement |
| 5 | Passport Seva | passportindia.gov.in | B, F, G | UNVERIFIED | Service + appointment + payment |
| 6 | Vahan | vahan.parivahan.gov.in | B, E | UNVERIFIED | Dynamic service workflow |
| 7 | CPGRAMS | pgportal.gov.in | A, C | UNVERIFIED | Grievance + authentication |
| 8 | NCH | consumerhelpline.gov.in | A, C | UNVERIFIED | Complaint workflow |
| 9 | UPSC/SSC | upsc.gov.in / ssc.nic.in | A, B | UNVERIFIED | Structured application |
| 10 | PM-KISAN | pmkisan.gov.in | A | UNVERIFIED | Citizen/service flow |

---

## Portal Test Status Legend

| Status | Meaning |
|--------|---------|
| `UNVERIFIED` | Domain known but no regression test exists |
| `TESTING` | Actively being tested |
| `VERIFIED` | Reproducible regression test passes |
| `BROKEN` | Previously verified, now failing |
| `UNSUPPORTED` | Checked and confirmed not automatable or out of scope |

---

## Domain Registry Structure

```json
{
  "domain": "example.gov.in",
  "organization": "Example Government Service",
  "official": true,
  "verified": false,
  "allowed": true,
  "authentication_modes": ["password", "otp", "captcha"],
  "has_payment": false,
  "final_submission_requires_confirmation": true,
  "special_rules": [],
  "status": "UNVERIFIED"
}
```

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

## Portal Test Results

*No tests run yet. This section will be populated as portals are tested.*

### Example Entry

```markdown
### ServicePlus (serviceonline.gov.in)

- Date tested: 2024-09-15
- Class: A, B
- Result: VERIFIED
- Test file: tests/portal_regression/test_serviceplus.py
- Fields mapped: 12/12 (100%)
- Actions executed: 8/8 (100%)
- Safety blocks: 1 (OTP — correct user takeover)
- Notes: Dependent dropdown for State→District worked correctly
```
