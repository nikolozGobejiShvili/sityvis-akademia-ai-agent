"""ADULT LLM Engine — manager notification + CRM tests.

Covers:
  * Adult email has ADULT labels — never "ბავშვის ასაკი"
  * Adult email never contains "ღრმა ფესვი"
  * Adult lead saved with segment="ADULT"
  * Manager notification failure does not crash the executor
  * Adult flow does NOT trigger Calendar booking
  * Notification body uses adult summary, not parent summary
"""

from __future__ import annotations

import pytest

from app.agent.tools import adult_tool_executor
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import TOOL_REQUEST_ADULT_MANAGER_CALLBACK
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, notification_service


@pytest.fixture(autouse=True)
def reset_executor_state():
    adult_tool_executor.reset_state()
    yield
    adult_tool_executor.reset_state()


@pytest.fixture
def executor_with_lead():
    conv = Conversation(sender_id="adult_mgr_1", platform="instagram", segment="ADULT")
    lead = Lead(
        sender_id="adult_mgr_1",
        platform="instagram",
        segment="ADULT",
        name="ნინო",
        phone="599123456",
        event_interest="პოეზიის საღამო",
    )
    conv.lead = lead
    return AdultToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="adult_mgr_1",
        platform="instagram",
    )


def test_adult_email_uses_adult_labels(executor_with_lead):
    """The notification email body builder must use the ADULT branch
    (event interest + ticket label), not the PARENT branch (child age +
    deeper concern)."""
    body = notification_service._manager_email_body(executor_with_lead.lead)
    # ADULT-only label.
    assert "ღონისძიება" in body or "ბილეთი" in body
    # PARENT-only labels MUST NOT appear for an ADULT lead.
    assert "ბავშვის ასაკი" not in body
    assert "ღრმა ფესვი" not in body
    assert "მშობლის დამატებითი დაკვირვება" not in body


def test_adult_lead_segment_persisted(executor_with_lead, monkeypatch):
    from app.services import notification_service, sheets_service

    captured: list = []
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: captured.append(lead),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")

    executor_with_lead.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"phone": "599123456"},
    )

    assert len(captured) == 1
    assert captured[0].segment == "ADULT"


def test_notification_failure_does_not_crash(executor_with_lead, monkeypatch):
    """If send_manager_notification raises, executor must NOT propagate
    the exception — it must still return success=true (the Sheets row
    is the durable record)."""
    from app.services import notification_service, sheets_service

    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)

    def _boom(*args, **kwargs):
        raise RuntimeError("SMTP server down")

    monkeypatch.setattr(notification_service, "send_manager_notification", _boom)
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")

    result = executor_with_lead.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"phone": "599123456"},
    )

    assert result["success"] is True


def test_adult_flow_never_books_calendar_in_manager_path(executor_with_lead, monkeypatch):
    from app.services import calendar_service, notification_service, sheets_service

    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(notification_service, "send_manager_notification", lambda *a, **k: True)
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda *a, **k: pytest.fail("Adult flow must not book Calendar"),
    )
    monkeypatch.setattr(
        calendar_service, "create_event",
        lambda *a, **k: pytest.fail("Adult flow must not create Calendar event"),
    )

    result = executor_with_lead.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"phone": "599123456"},
    )

    assert result["success"] is True
    # Lead must NOT be marked calendly_booked — adult flow has no Calendar.
    assert executor_with_lead.lead.calendly_booked is False


def test_adult_summary_used_not_parent_summary(executor_with_lead):
    """Adult-segment lead must get the adult summary line, not the
    parent one. Accepts any case form of 'ღონისძიება' (nominative,
    instrumental 'ღონისძიებით', etc.)."""
    summary = notification_service._email_summary_for(executor_with_lead.lead)
    assert "ღონისძიე" in summary or "ბილეთი" in summary
    # Must NOT mention camp ("ბანაკი") for an ADULT lead.
    assert "ბანაკ" not in summary
