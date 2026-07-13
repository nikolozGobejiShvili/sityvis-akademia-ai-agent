"""General registration-link intent routing (2026-06-19).

When the user asks for a registration / sign-up link or form, the agent must
return the CONFIGURED Admin link for the clear target and never invent one:

  * camp keyword        → PARENT → engine `get_camp_info("registration")`
                          → camp Admin `registration_url`;
  * adult-event context → ADULT  → `provide_adult_reservation_link`
                          → event `reservation_url`;
  * sticky PARENT/ADULT segment (conversation context target) → that flow;
  * FRESH ambiguous (no camp/adult target) → a registration-specific
    clarification ("ბანაკის თუ კონკრეტული ღონისძიების?") — NEVER a guessed
    link;
  * missing configured URL → safe manager/contact fallback (no invented link).

All offline / mocked — no real OpenAI, Meta, WhatsApp, Calendar, Sheets,
Redis, or network.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import adult_llm_engine
from app.agent.tools.adult_tool_executor import AdultToolExecutor
from app.agent.tools.adult_tools import TOOL_PROVIDE_ADULT_RESERVATION_LINK
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_GET_CAMP_INFO
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service


_MENU = "გვითხარით, რა გაინტერესებთ"
_CLARIFY = "რომელი მიმართულების რეგისტრაციის ლინკი"
_CAMP_URL = "https://tinyurl.com/36jcae8z"
_EVENT_URL = "https://wordacademy.ge/tickets"


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()

@pytest.fixture
def camp_registration_open(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_registration_status", lambda: "open",
    )


@pytest.fixture
def stub_flows(monkeypatch):
    """Stub the downstream flows so routing is observable without engines."""
    monkeypatch.setattr(
        conversation_service.parent_flow, "handle",
        lambda conv, msg: "PARENT_FLOW_REPLY",
    )
    monkeypatch.setattr(
        conversation_service.adult_flow, "handle",
        lambda conv, msg: "ADULT_FLOW_REPLY",
    )


# =========================================================================
# Helper — registration/link intent detection.
# =========================================================================


@pytest.mark.parametrize("msg", [
    "სარეგისტრაციო ლინკი მომწერე",
    "რეგისტრაციის ფორმა სად არის",
    "ლინკი მომწერე",
    "ბმული გამომიგზავნე",
    "როგორ დავრეგისტრირდე",
    "ჩაწერა მინდა",
    "registration link please",
    "how do i sign up",
])
def test_is_registration_link_request_true(msg):
    assert conversation_service._is_registration_link_request(msg) is True


@pytest.mark.parametrize("msg", [
    "გამარჯობა",
    "ფასი?",
    "ბანაკი",
    "",
])
def test_is_registration_link_request_false(msg):
    assert conversation_service._is_registration_link_request(msg) is False


# =========================================================================
# Fresh AMBIGUOUS registration request → clarification, never a guessed link.
# =========================================================================


@pytest.mark.parametrize("msg", [
    "სარეგისტრაციო ლინკი მომწერე",
    "ლინკი მომწერე",
    "რეგისტრაციის ფორმა სად არის",
    "როგორ დავრეგისტრირდე?",
])
def test_fresh_ambiguous_registration_asks_clarification(stub_flows, msg):
    out = conversation_service.process_message("amb", msg, "instagram")
    assert _CLARIFY in out, f"expected registration clarification for {msg!r}"
    assert _MENU not in out                # not the generic menu
    assert "http" not in out               # no guessed link
    assert "PARENT_FLOW_REPLY" not in out  # did not route into a flow
    assert "ADULT_FLOW_REPLY" not in out


def test_bare_greeting_still_shows_generic_menu(stub_flows):
    out = conversation_service.process_message("greet", "გამარჯობა", "instagram")
    assert _MENU in out
    assert _CLARIFY not in out


def test_price_question_still_generic_menu(stub_flows):
    out = conversation_service.process_message("price", "ფასი?", "instagram")
    assert _MENU in out
    assert _CLARIFY not in out


# =========================================================================
# Clear CAMP target → PARENT flow (configured camp URL handled there).
# =========================================================================


@pytest.mark.parametrize("msg", [
    "ბანაკის სარეგისტრაციო ლინკი მომწერე",
    "ბანაკზე ფორმა სად არის?",
    "ბავშვი მინდა ჩავწერო ბანაკში",
])
def test_camp_registration_routes_to_parent_flow(stub_flows, msg):
    out = conversation_service.process_message("camp", msg, "instagram")
    assert out == "PARENT_FLOW_REPLY"
    assert _CLARIFY not in out
    assert _MENU not in out
    assert conversation_service.conversations["camp"].segment == "PARENT"


# =========================================================================
# Conversation CONTEXT target — sticky segment resolves bare "ლინკი მომწერე".
# =========================================================================


def test_context_camp_then_bare_link_stays_parent(stub_flows):
    sid = "ctx-camp"
    conversation_service.process_message(sid, "ბანაკი მაინტერესებს", "instagram")
    assert conversation_service.conversations[sid].segment == "PARENT"
    out = conversation_service.process_message(sid, "ლინკი მომწერე", "instagram")
    assert out == "PARENT_FLOW_REPLY"   # camp context resolves the link
    assert _CLARIFY not in out


def test_context_event_then_bare_link_stays_adult(stub_flows):
    sid = "ctx-event"
    conversation_service.process_message(sid, "ღონისძიება მაინტერესებს", "instagram")
    assert conversation_service.conversations[sid].segment == "ADULT"
    out = conversation_service.process_message(sid, "ლინკი მომწერე", "instagram")
    assert out == "ADULT_FLOW_REPLY"     # event context resolves the link
    assert _CLARIFY not in out


# =========================================================================
# CAMP Registration URL source + safe missing fallback (executor tool).
# =========================================================================


def _parent_executor(sid="reg-camp"):
    conv = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    lead = Lead(sender_id=sid, platform="instagram", segment="PARENT")
    conv.lead = lead
    return ParentToolExecutor(conversation=conv, lead=lead, sender_id=sid, platform="instagram")


def test_camp_registration_url_uses_admin_config(monkeypatch, camp_registration_open):
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts",
        lambda: {"name": "ბანაკი", "registration_url": _CAMP_URL, "phone": "558674733"},
    )
    result = _parent_executor().execute(TOOL_GET_CAMP_INFO, {"topic": "registration"})
    assert result["success"] is True
    assert result["registration_url"] == _CAMP_URL


def test_camp_registration_url_missing_safe_fallback(monkeypatch, camp_registration_open):
    monkeypatch.setattr(
        admin_config_service, "get_camp_facts",
        lambda: {"name": "ბანაკი", "registration_url": "", "phone": "558674733"},
    )
    result = _parent_executor().execute(TOOL_GET_CAMP_INFO, {"topic": "registration"})
    assert result["success"] is False
    assert result["reason"] == "registration_url_missing"
    assert result.get("phone") == "558674733"   # manager/contact fallback
    assert "registration_url" not in result      # no invented link


# =========================================================================
# ADULT EVENT Registration URL source + safe missing fallback (executor tool).
# =========================================================================


def _adult_executor(sid="reg-event"):
    conv = Conversation(sender_id=sid, platform="instagram", segment="ADULT")
    lead = Lead(sender_id=sid, platform="instagram", segment="ADULT")
    conv.lead = lead
    return AdultToolExecutor(conversation=conv, lead=lead, sender_id=sid, platform="instagram")


def test_event_registration_url_uses_configured_value(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "find_adult_event",
        lambda ref: {"id": "evt1", "title": "პოეზიის საღამო", "reservation_url": _EVENT_URL},
    )
    result = _adult_executor().execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK, {"event_id": "evt1"},
    )
    assert result["success"] is True
    assert result["reservation_url"] == _EVENT_URL


def test_event_registration_url_missing_safe_fallback(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "find_adult_event",
        lambda ref: {"id": "evt1", "title": "პოეზიის საღამო", "reservation_url": ""},
    )
    result = _adult_executor().execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK, {"event_id": "evt1"},
    )
    assert result["success"] is False
    assert result["reason"] == "link_missing"
    assert "reservation_url" not in result   # no invented link


def test_event_registration_unknown_event_no_link(monkeypatch):
    monkeypatch.setattr(admin_config_service, "find_adult_event", lambda ref: None)
    result = _adult_executor().execute(
        TOOL_PROVIDE_ADULT_RESERVATION_LINK, {"event_id": "ghost"},
    )
    assert result["success"] is False
    assert result["reason"] == "unknown_event"
    assert "reservation_url" not in result


# =========================================================================
# PAST event → no stale registration link (rendered past message).
# =========================================================================


def test_past_event_renderer_omits_reservation_link():
    past_event = {
        "title": "გია მურღულიასთან შეხვედრა",
        "date_text": "14 ივნისი 20:00",
        "reservation_url": "https://wordacademy.ge/stale-link",
    }
    out = adult_llm_engine._render_past_named_event(past_event)
    assert "უკვე გაიმართა" in out                       # "already took place"
    assert "https://wordacademy.ge/stale-link" not in out  # no stale link
    assert "http" not in out


# =========================================================================
# Regression guards.
# =========================================================================


def test_bare_camp_keyword_routes_parent(stub_flows):
    out = conversation_service.process_message("bare-camp", "ბანაკი", "instagram")
    assert out == "PARENT_FLOW_REPLY"
    assert conversation_service.conversations["bare-camp"].segment == "PARENT"


def test_adult_keyword_routes_adult(stub_flows):
    out = conversation_service.process_message("bare-adult", "ღონისძიება მაინტერესებს", "instagram")
    assert out == "ADULT_FLOW_REPLY"
    assert conversation_service.conversations["bare-adult"].segment == "ADULT"


def test_sheets_and_scheduling_unchanged():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.services import calendar_service, sheets_service
    tz = ZoneInfo("Asia/Tbilisi")
    assert len(sheets_service.HEADERS) == 17
    ok_sat, _ = calendar_service.is_within_business_hours(datetime(2030, 6, 8, 12, 0, tzinfo=tz))
    ok_sun, r_sun = calendar_service.is_within_business_hours(datetime(2030, 6, 9, 12, 0, tzinfo=tz))
    assert ok_sat is True
    assert ok_sun is False and r_sun == "weekend"
