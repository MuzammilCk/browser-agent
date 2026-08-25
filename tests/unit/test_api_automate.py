"""API-layer tests for the confirmation/abort endpoints (audit C1/C5)."""

from __future__ import annotations

import asyncio

from app.api import routes
from app.api.routes import ConfirmRequest


class TestConfirmEndpoint:
    def test_confirm_delivers_approval_and_event(self):
        wf = {
            "workflow_id": "t1",
            "status": "ready_for_confirmation",
            "approved": None,
            "confirm_event": asyncio.Event(),
        }
        routes._workflows["t1"] = wf
        try:
            result = asyncio.run(routes.confirm_automation(
                "t1", ConfirmRequest(approved=True),
            ))
            assert result == {"workflow_id": "t1", "approved": True}
            assert wf["approved"] is True
            assert wf["confirm_event"].is_set()
        finally:
            routes._workflows.pop("t1", None)

    def test_decline_delivers_rejection(self):
        wf = {
            "workflow_id": "t2",
            "status": "ready_for_confirmation",
            "approved": None,
            "confirm_event": asyncio.Event(),
        }
        routes._workflows["t2"] = wf
        try:
            result = asyncio.run(routes.confirm_automation(
                "t2", ConfirmRequest(approved=False),
            ))
            assert result["approved"] is False
            assert wf["approved"] is False
            assert wf["confirm_event"].is_set()
        finally:
            routes._workflows.pop("t2", None)

    def test_confirm_unknown_workflow_errors(self):
        result = asyncio.run(routes.confirm_automation(
            "missing", ConfirmRequest(approved=True),
        ))
        assert "error" in result

    def test_confirm_without_active_wait_errors(self):
        routes._workflows["t3"] = {"workflow_id": "t3", "status": "running"}
        try:
            result = asyncio.run(routes.confirm_automation(
                "t3", ConfirmRequest(approved=True),
            ))
            assert "error" in result
        finally:
            routes._workflows.pop("t3", None)


class TestAbortEndpoint:
    def test_abort_finished_workflow_reports_finished(self):
        routes._workflows["t4"] = {"workflow_id": "t4", "status": "completed"}
        try:
            result = asyncio.run(routes.abort_automation("t4"))
            assert "already finished" in result["message"]
        finally:
            routes._workflows.pop("t4", None)

    def test_abort_unknown_workflow_errors(self):
        result = asyncio.run(routes.abort_automation("missing"))
        assert "error" in result


class TestStartAutomationValidation:
    def test_unknown_domain_rejected_without_launch(self):
        from app.api.routes import AutomateRequest
        before = set(routes._workflows.keys())
        result = asyncio.run(routes.start_automation(
            AutomateRequest(domain="not-a-real-domain.example", task="x"),
        ))
        assert "error" in result
        assert set(routes._workflows.keys()) == before

    def test_missing_domain_rejected(self):
        from app.api.routes import AutomateRequest
        result = asyncio.run(routes.start_automation(AutomateRequest(domain="")))
        assert "error" in result
