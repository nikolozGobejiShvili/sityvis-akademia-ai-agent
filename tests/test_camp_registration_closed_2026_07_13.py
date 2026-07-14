from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import (
    TOOL_BOOK_CONSULTATION,
    TOOL_CHECK_CONSULTATION_SLOT,
    TOOL_GET_AVAILABLE_SLOTS,
    TOOL_GET_CAMP_INFO,
    TOOL_MANAGE_CONSULTATION_BOOKING,
)
from app.flows import parent_flow, parent_turn_router
from app.agent.intent.parent_intent_detector import INTENT_BOOKING_REQUEST
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, comment_service, followup_service


_REG_URL = "https://example.test/register"


def _sections(registration_status=None):
    camp = {
        "id": "summer_camp",
        "name": "Summer Camp",
        "type": "program",
        "status": "active",
        "hashtags": ["camp"],
        "auto_dm_template_id": "summer_camp_rich_dm",
        "registration_url": _REG_URL,
        "price_text": "2150",
        "price_gel": 2150,
        "age_min": 9,
        "age_max": 17,
        "duration_days": 7,
        "location": "Test location",
        "streams": [
            {"name": "III", "dates_text": "1-7 August", "status": "active"},
        ],
    }
    if registration_status is not None:
        camp["registration_status"] = registration_status
    return [camp]


def _set_registration_status(monkeypatch, value):
    monkeypatch.setattr(
        admin_config_service,
        "load_sections",
        lambda: _sections(value),
    )


def _conversation(sender_id="closed-user"):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    return conv


def _executor(sender_id="closed-user"):
    conv = _conversation(sender_id)
    return ParentToolExecutor(
        conversation=conv,
        lead=conv.lead,
        sender_id=sender_id,
        platform="instagram",
    )


def test_registration_status_defaults_open_but_explicit_invalid_fails_closed(monkeypatch):
    monkeypatch.setattr(admin_config_service, "load_sections", lambda: _sections(None))
    assert admin_config_service.get_camp_registration_status() == "open"
    assert admin_config_service.is_camp_registration_open() is True

    for value in ["closed", "disabled", "off", "false", "0", "bogus"]:
        _set_registration_status(monkeypatch, value)
        assert admin_config_service.get_camp_registration_status() == "closed"
        assert admin_config_service.is_camp_registration_open() is False

    for value in ["open", "active", "enabled", "true", "1"]:
        _set_registration_status(monkeypatch, value)
        assert admin_config_service.get_camp_registration_status() == "open"
        assert admin_config_service.is_camp_registration_open() is True


def test_parent_registration_answers_do_not_emit_url_when_closed(monkeypatch):
    _set_registration_status(monkeypatch, "closed")
    expected = parent_flow._camp_registration_closed_answer()

    assert parent_flow._render_camp_registration_answer() == expected
    assert parent_flow._render_camp_fast_track_registration_answer() == expected

    conv = _conversation("registration-link")
    out = parent_flow._maybe_handle_camp_registration_link(conv, "camp register")
    assert out == expected
    assert "http" not in out


def test_start_book_closed_does_not_enter_age_state(monkeypatch):
    _set_registration_status(monkeypatch, "closed")
    conv = _conversation("start-book")
    conv.state = "START"

    monkeypatch.setattr(parent_flow, "_fetch_profile_into_lead", lambda c, lead: None)
    monkeypatch.setattr(parent_flow, "maybe_handle_analyzer_interrupt", lambda c, lead, msg: None)
    monkeypatch.setattr(parent_flow, "_detect_safe_intent", lambda msg: "BOOK")

    out = parent_flow._handle_impl(conv, "not a router booking phrase")
    assert out == parent_flow._camp_registration_closed_answer()
    assert conv.state == "START"
    assert "http" not in out


def test_router_registration_and_booking_are_closed(monkeypatch):
    _set_registration_status(monkeypatch, "closed")
    conv = _conversation("router-booking")
    lead = conv.lead

    out = parent_turn_router._build_premium_registration_answer()
    assert out == parent_flow._camp_registration_closed_answer()
    assert "http" not in out

    conv.pending_booking = {"requested_datetime_iso": "2030-08-01T12:00:00"}
    out = parent_turn_router._response_for_intent(
        INTENT_BOOKING_REQUEST,
        conv,
        lead,
        "book consultation",
    )
    assert out == parent_flow._camp_registration_closed_answer()
    assert conv.pending_booking is None


def test_pending_booking_continuation_is_dropped_when_registration_closed(monkeypatch):
    _set_registration_status(monkeypatch, "closed")
    conv = _conversation("pending-booking")
    conv.pending_booking = {
        "requested_datetime_iso": "2030-08-01T12:00:00",
        "missing_fields": ["phone"],
    }

    out = parent_turn_router.maybe_handle_pending_booking_continuation(
        conv,
        conv.lead,
        "555123456",
    )
    assert out == parent_flow._camp_registration_closed_answer()
    assert conv.pending_booking is None


def test_parent_tool_registration_and_calendar_paths_are_closed(monkeypatch):
    _set_registration_status(monkeypatch, "closed")
    executor = _executor("tool-closed")

    registration = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "registration"})
    assert registration == {
        "success": False,
        "reason": "camp_registration_closed",
        "topic": "registration",
    }
    assert "registration_url" not in registration

    all_info = executor.execute(TOOL_GET_CAMP_INFO, {"topic": "all"})
    assert all_info == {
        "success": False,
        "reason": "camp_public_info_limited",
        "topic": "all",
        "message": parent_flow._camp_registration_closed_answer(),
    }
    assert "registration_url" not in all_info

    slots = executor.execute(TOOL_GET_AVAILABLE_SLOTS, {})
    assert slots["success"] is False
    assert slots["reason"] == "camp_registration_closed"
    assert slots["slots"] == []

    check = executor.execute(
        TOOL_CHECK_CONSULTATION_SLOT,
        {"datetime_iso": "2030-08-01T12:00:00"},
    )
    assert check["success"] is False
    assert check["reason"] == "camp_registration_closed"
    assert check["available"] is False

    booked = executor.execute(
        TOOL_BOOK_CONSULTATION,
        {
            "name": "Nino",
            "phone": "555123456",
            "datetime_iso": "2030-08-01T12:00:00",
            "child_age": "12",
            "user_confirmed_datetime": True,
        },
    )
    assert booked == {"success": False, "reason": "camp_registration_closed"}

    reschedule = executor.execute(
        TOOL_MANAGE_CONSULTATION_BOOKING,
        {"action": "reschedule", "new_datetime_iso": "2030-08-02T12:00:00"},
    )
    assert reschedule == {
        "success": False,
        "reason": "camp_registration_closed",
        "action": "reschedule",
    }


def test_comment_dm_strips_registration_url_when_closed(monkeypatch):
    _set_registration_status(monkeypatch, "closed")
    monkeypatch.setattr(
        admin_config_service,
        "get_section",
        lambda section_id: _sections("closed")[0] if section_id == "summer_camp" else None,
    )
    monkeypatch.setattr(
        admin_config_service,
        "build_section_dm",
        lambda section: "Camp info\nრეგისტრაციის ბმული: https://example.test/register\nTail",
    )

    out = comment_service._build_parent_rich_dm()
    assert "Camp info" in out
    assert "Tail" in out
    assert "http" not in out
    assert "რეგისტრაციის ბმული" not in out


def test_followup_is_skipped_when_registration_closed(monkeypatch):
    _set_registration_status(monkeypatch, "closed")
    conv = _conversation("followup-closed")
    conv.last_bot_message_at = (datetime.utcnow() - timedelta(hours=25)).isoformat()

    def _send_should_not_run(**kwargs):
        raise AssertionError("follow-up send should be gated")

    monkeypatch.setattr(
        followup_service,
        "messenger_service",
        SimpleNamespace(send_message=_send_should_not_run),
    )

    result = followup_service._maybe_send_followup_for_conversation(
        conv,
        datetime.utcnow(),
    )
    assert result == "skipped"
    assert conv.followup_stage == ""