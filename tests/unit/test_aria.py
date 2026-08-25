"""Tests for ARIA snapshot kwarg construction (audit C3 regression guard).

The B1 fix introspected the signature correctly but passed mode=True (a
bool) where Playwright's driver requires "ai"|"default". These tests pin
the kwarg VALUES, not just which keys are present.
"""

from __future__ import annotations

from app.browser import aria


class TestSnapshotKwargs:
    def test_mode_value_is_ai_string_not_bool(self):
        kwargs = aria._build_snapshot_kwargs(mode=True)
        if "mode" in kwargs:
            assert kwargs["mode"] == "ai"

    def test_refs_value_is_boolean_true(self):
        kwargs = aria._build_snapshot_kwargs(mode=True, refs=True)
        if "refs" in kwargs:
            assert kwargs["refs"] is True

    def test_unsupported_kwargs_omitted(self):
        kwargs = aria._build_snapshot_kwargs(mode=False, refs=False)
        assert "mode" not in kwargs
        assert "refs" not in kwargs

    def test_supported_kwargs_match_driver_signature(self):
        # Every emitted kwarg must exist in the installed driver's signature
        from playwright.async_api import Locator
        import inspect
        sig_params = set(inspect.signature(Locator.aria_snapshot).parameters) - {"self"}
        for k in aria._build_snapshot_kwargs(mode=True, refs=True):
            assert k in sig_params

    def test_kwarg_values_table_covers_emitted_keys(self):
        for k in ("mode", "refs"):
            assert k in aria._KWARG_VALUES
