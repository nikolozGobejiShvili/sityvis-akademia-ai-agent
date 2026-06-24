"""ADULT LLM Engine — backend tool executor tests.

Covers:
  * unknown tool name → success=false reason=unknown_tool
  * get_adult_events returns active events (and respects age filter)
  * get_adult_event_details returns the configured event without
    inventing fields
  * unknown event id → success=false reason=unknown_event
  * save_adult_lead_info validates phone (reports invalid_fields)
  * save_adult_lead_info never writes Sheets / never notifies / never
    books Calendar
  * request_adult_manager_callback requires phone
  * request_adult_manager_callback returns manager_phone to the LLM
  * request_adult_manager_callback writes Sheets + notifies manager
  * request_adult_manager_callback NEVER books Calendar
  * provide_adult_reservation_link returns the configured link
  * provide_adult_reservation_link with missing link → reason=link_missing
    (and NEVER invents a URL)
  * switch_to_parent_flow flips the segment
"""

from __future__ import annotations

import textwrap

import pytest

from app.agent.tools import adult_tool_executor
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import (
    TOOL_GET_ADULT_EVENT_DETAILS,
    TOOL_GET_ADULT_EVENTS,
    TOOL_PROVIDE_ADULT_RESERVATION_LINK,
    TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
    TOOL_SAVE_ADULT_LEAD_INFO,
    TOOL_SWITCH_TO_PARENT_FLOW,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service


@pytest.fixture(autouse=True)
def reset_module_state():
    adult_tool_executor.reset_state()
    yield
    adult_tool_executor.reset_state()


@pytest.fixture
def admin_yaml_with_events(monkeypatch, tmp_path):
    yaml_text = textwrap.dedent(
        """\
        sections:
        - id: adult_events
          name: ზრდასრულთა ღონისძიებები
          type: adult_events
          status: active
          hashtags: [ღონისძიება]
          auto_dm_template_id: adult_events_comment_dm
          events:
          - id: poetry_evening
            title: პოეზიის საღამო
            status: active
            min_age: 16
            date_text: ივლისი
            location: თბილისი
            theme: პოეზია
            reservation_url: https://example.com/poetry
            seats_available: 20
          - id: silent_event
            title: ღამის ფილოსოფია
            status: active
            min_age: 18
            date_text: ''
            location: ''
            theme: ''
            reservation_url: ''
        """,
    )
    sections_path = tmp_path / "sections.yaml"
    sections_path.write_text(yaml_text, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", sections_path)
    return sections_path


@pytest.fixture
def executor():
    conversation = Conversation(sender_id="sender_adult_1", platform="instagram", segment="ADULT")
    lead = Lead(sender_id="sender_adult_1", platform="instagram", segment="ADULT")
    conversation.lead = lead
    return AdultToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id="sender_adult_1",
        platform="instagram",
    )


def test_unknown_tool_returns_safe_error(executor):
    result = executor.execute("totally_made_up_tool", {})
    assert result == {
        "success": False,
        "reason": "unknown_tool",
        "tool": "totally_made_up_tool",
    }


def test_get_adult_events_returns_active(executor, admin_yaml_with_events):
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {})
    assert result["success"] is True
    ids = {e["id"] for e in result["events"]}
    assert ids == {"poetry_evening", "silent_event"}


def test_get_adult_events_filters_by_user_age(executor, admin_yaml_with_events):
    result = executor.execute(TOOL_GET_ADULT_EVENTS, {"user_age": 16})
    ids = {e["id"] for e in result["events"]}
    assert ids == {"poetry_evening"}, (
        "User 16 should NOT see the 18+ silent_event."
    )


def test_get_adult_event_details_returns_event(executor, admin_yaml_with_events):
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "poetry_evening"},
    )
    assert result["success"] is True
    assert result["event"]["title"] == "პოეზიის საღამო"
    assert result["event"]["min_age"] == 16


def test_get_adult_event_details_never_invents_fields(executor, admin_yaml_with_events):
    """For an event with empty location/date/theme/url, the result must
    surface empty strings — never a placeholder like 'TBA' or 'soon'."""
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "silent_event"},
    )
    assert result["success"] is True
    event = result["event"]
    assert event["date_text"] == ""
    assert event["location"] == ""
    assert event["theme"] == ""
    assert event["has_reservation_url"] is False


def test_get_adult_event_details_unknown_event(executor, admin_yaml_with_events):
    result = executor.execute(
        TOOL_GET_ADULT_EVENT_DETAILS,
        {"event_id_or_title": "სრულიად-უცნობი-ღონისძიება"},
    )
    assert result["success"] is False
    assert result["reason"] == "unknown_event"


def test_save_adult_lead_info_validates_phone(executor):
    result = executor.execute(
        TOOL_SAVE_ADULT_LEAD_INFO,
        {"name": "ნინო", "phone": "totally_invalid"},
    )
    assert result["success"] is True
    assert "name" in result["saved_fields"]
    assert "phone" in result.get("invalid_fields", [])
    assert executor.lead.phone == ""


def test_save_adult_lead_info_never_writes_sheets(executor, monkeypatch):
    from app.services import sheets_service

    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: pytest.fail("save_adult_lead_info must not call create_lead"),
    )
    result = executor.execute(
        TOOL_SAVE_ADULT_LEAD_INFO,
        {"name": "ნინო", "phone": "599123456"},
    )
    assert result["success"] is True


def test_save_adult_lead_info_never_notifies(executor, monkeypatch):
    from app.services import notification_service

    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda *args, **kw: pytest.fail("save_adult_lead_info must not notify"),
    )
    executor.execute(
        TOOL_SAVE_ADULT_LEAD_INFO,
        {"name": "ნინო", "phone": "599123456"},
    )


def test_request_adult_manager_callback_requires_phone(executor, monkeypatch):
    from app.services import notification_service, sheets_service

    notify_calls = []
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda *args, **kw: notify_calls.append(args),
    )
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: None)

    result = executor.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"name": "ნინო"},
    )

    assert result == {"success": False, "reason": "missing_phone"}
    assert notify_calls == [], "manager must NOT be notified without phone"


def test_request_adult_manager_callback_returns_manager_phone(
    executor, monkeypatch, admin_yaml_with_events,
):
    from app.services import notification_service, sheets_service

    monkeypatch.setattr(notification_service, "send_manager_notification", lambda *a, **k: True)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        admin_config_service, "get_manager_phone", lambda: "558 67 47 33",
    )

    result = executor.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"name": "ნინო", "phone": "599 12 34 56", "event_interest": "პოეზიის საღამო"},
    )

    assert result["success"] is True
    assert result["manager_notified"] is True
    assert result["manager_phone"] == "558 67 47 33"
    assert executor.lead.phone == "599123456"
    assert executor.lead.reservation_status == "ManagerHandoff"


def test_request_adult_manager_callback_writes_sheets_and_notifies(
    executor, monkeypatch, admin_yaml_with_events,
):
    from app.services import notification_service, sheets_service

    sheets_calls: list = []
    notify_calls: list = []
    monkeypatch.setattr(
        sheets_service, "create_lead", lambda lead: sheets_calls.append(lead),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notify_calls.append((lead, summary)),
    )
    monkeypatch.setattr(
        admin_config_service, "get_manager_phone", lambda: "558 67 47 33",
    )

    result = executor.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"name": "ნინო", "phone": "599123456"},
    )

    assert result["success"] is True
    assert len(sheets_calls) == 1, "must save lead to Sheets"
    assert len(notify_calls) == 1, "must notify manager"
    assert sheets_calls[0].segment == "ADULT"


def test_request_adult_manager_callback_idempotent(
    executor, monkeypatch, admin_yaml_with_events,
):
    from app.services import notification_service, sheets_service

    notify_count = {"n": 0}
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda *a, **k: notify_count.__setitem__("n", notify_count["n"] + 1),
    )
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")

    r1 = executor.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"phone": "599123456"},
    )
    r2 = executor.execute(
        TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {"phone": "599123456"},
    )

    assert r1["manager_notified"] is True
    assert r2.get("manager_notified") is False
    assert r2.get("reason") == "already_notified"
    assert notify_count["n"] == 1, "manager must NOT be notified twice"


def test_adult_flow_never_books_calendar(executor, monkeypatch, admin_yaml_with_events):
    """The adult executor must NEVER call calendar_service.book_slot or
    create_event regardless of which tool the LLM invokes.
    """
    from app.services import calendar_service, notification_service, sheets_service

    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(notification_service, "send_manager_notification", lambda *a, **k: True)
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")

    def _no_calendar(*args, **kwargs):
        pytest.fail("Adult flow must never touch Calendar.")

    monkeypatch.setattr(calendar_service, "book_slot", _no_calendar)
    monkeypatch.setattr(calendar_service, "create_event", _no_calendar)
    monkeypatch.setattr(calendar_service, "check_slot_available", _no_calendar)

    # Exercise every adult tool that could plausibly touch Calendar by mistake.
    executor.execute(TOOL_GET_ADULT_EVENTS, {})
    executor.execute(TOOL_GET_ADULT_EVENT_DETAILS, {"event_id_or_title": "poetry_evening"})
    executor.execute(TOOL_SAVE_ADULT_LEAD_INFO, {"name": "ნინო", "phone": "599123456"})
    executor.execute(TOOL_REQUEST_ADULT_MANAGER_CALLBACK, {"phone": "599123456"})
    executor.execute(TOOL_PROVIDE_ADULT_RESERVATION_LINK, {"event_id": "poetry_evening"})


def test_provide_adult_reservation_link_returns_configured(executor, admin_yaml_with_events):
    result = executor.execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK,
        {"event_id": "poetry_evening"},
    )
    assert result["success"] is True
    assert result["reservation_url"] == "https://example.com/poetry"
    assert executor.lead.preferred_event == "poetry_evening"
    assert executor.lead.reservation_status == "LinkSent"


def test_provide_adult_reservation_link_missing_url(executor, admin_yaml_with_events):
    result = executor.execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK,
        {"event_id": "silent_event"},
    )
    assert result["success"] is False
    assert result["reason"] == "link_missing"
    # Must NOT have invented a URL.
    assert "reservation_url" not in result


def test_provide_adult_reservation_link_unknown_event(executor, admin_yaml_with_events):
    result = executor.execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK,
        {"event_id": "does_not_exist"},
    )
    assert result["success"] is False
    assert result["reason"] == "unknown_event"


def test_switch_to_parent_flow_sets_segment_parent(executor):
    result = executor.execute(
        TOOL_SWITCH_TO_PARENT_FLOW,
        {"reason": "user mentioned camp"},
    )
    assert result["success"] is True
    assert result["segment"] == "PARENT"
    assert executor.conversation.segment == "PARENT"
    assert executor.conversation.state == "START"
