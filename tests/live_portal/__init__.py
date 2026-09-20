"""Phase 14 — Live portal validation tests.

Categories:
- tests/unit/test_live_validation.py — unit tests for the live layer
- tests/synthetic_forms/test_live_shadow_offline.py — full shadow pipeline over local fixtures (real Chromium, no network)
- tests/synthetic_forms/test_live_controlled_offline.py — controlled-execution gates over local fixtures (real Chromium, no network)
- tests/real_sites/ — live portals (observation-only), skipped unless RUN_REAL_SITE_TESTS=true
"""
