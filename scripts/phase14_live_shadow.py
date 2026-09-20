"""Phase 14 — Live shadow validation runner.

Runs observation-only (LIVE_SHADOW) validation against the selected real
government portals and writes structured evidence artifacts:

    tests/live_portal/evidence/<portal_id>/report.json
    tests/live_portal/evidence/<portal_id>/trace.jsonl

SAFETY:
- Observation only: no form fill, no click, no navigation beyond the
  entrypoint. Zero mutation against live portals.
- Conservative pacing: single page load per portal, one run each.
- Environment failures are recorded as such — never as agent failures.

Usage:
    python scripts/phase14_live_shadow.py [--portals pmkisan,myscheme,indiaportal]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.agent.live.shadow import run_live_shadow
from app.agent.live.profiles import get_live_portal_profile

EVIDENCE_DIR = Path(__file__).parents[1] / "tests" / "live_portal" / "evidence"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portals",
        default="pmkisan,myscheme,indiaportal",
        help="Comma-separated portal ids",
    )
    args = parser.parse_args()
    portal_ids = [p.strip() for p in args.portals.split(",") if p.strip()]

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    summary: dict[str, dict] = {}

    for portal_id in portal_ids:
        profile = get_live_portal_profile(portal_id)
        print(f"\n{'=' * 60}")
        print(f"LIVE SHADOW — {profile.name} ({profile.official_origin})")
        print(f"{'=' * 60}")

        try:
            report, trace = run_live_shadow(portal_id)
        except Exception as exc:  # never crash the batch on one portal
            print(f"  ENVIRONMENT/SAFETY ERROR: {type(exc).__name__}: {exc}")
            summary[portal_id] = {"status": "RUNNER_ERROR", "detail": str(exc)[:200]}
            exit_code = 2
            continue

        out_dir = EVIDENCE_DIR / portal_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(report.to_json(), encoding="utf-8")
        (out_dir / "trace.jsonl").write_text(trace.to_jsonl(), encoding="utf-8")

        print(f"  final_status        : {report.final_status.value}")
        print(f"  observation         : {report.observation_status.value if report.observation_status else '-'}")
        if report.observation:
            print(f"    url               : {report.observation.url}")
            print(f"    elements          : {report.observation.element_count}")
            print(f"    auth detected     : {report.observation.auth_detected}")
        print(f"  semantics           : {report.semantics_status.value if report.semantics_status else '-'}")
        print(f"  mapping             : {report.mapping_status.value if report.mapping_status else '-'}", end="")
        if report.mapping:
            print(f" (mapped {report.mapping.mapped}/{report.mapping.total_interactive}, ambiguous {len(report.mapping.ambiguous)})")
        else:
            print()
        print(f"  planning            : {report.planning_status.value if report.planning_status else '-'}", end="")
        print(f" ({len(report.planned_actions)} planned actions)")
        print(f"  boundary gated      : {len(report.final_boundary.submit_controls_detected) if report.final_boundary else 0} submit controls")
        print(f"  review status       : {report.review_status.value if report.review_status else '-'}")
        print(f"  injection exposure  : {report.injection_exposure}")
        print(f"  security events     : {report.security_events}")
        print(f"  environment         : {report.environment_condition.value}")
        print(f"  duration            : {report.duration_seconds}s")
        print(f"  evidence            : {out_dir / 'report.json'}")

        summary[portal_id] = {
            "status": report.final_status.value,
            "environment": report.environment_condition.value,
            "planned_actions": len(report.planned_actions),
            "mapped": report.mapping.mapped if report.mapping else 0,
        }
        if not report.live_metadata.get("success"):
            exit_code = 1

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    print(json.dumps(summary, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
