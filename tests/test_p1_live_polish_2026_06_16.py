"""P1 Live Polish (2026-06-15/16) regression tests.

BUG 1 — manager handoff collects name + phone TOGETHER (consultation-booking
        style), asks ONLY the missing field, never claims the name was sent
        when unknown, and dispatches (message-only) ONLY when BOTH are present.

BUG 2 — a named PAST / unknown event resolves on the FIRST try even after
        camp / under-age context, BEFORE any self/child target question.

Wording — no „მოგიწოდებთ"; multi-sentence handoff/event answers keep paragraph
        breaks.

All offline / mocked — no real notifications, OpenAI, Calendar, Sheets, Redis.
The autouse `_block_real_smtp` net (conftest) is an extra safety belt.
"""
from __future__ import annotations

import pytest

from app.agent.tools import parent_tool_executor
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, calendar_service, notification_service, sheets_service

_OFFER = "ბანაკში მონაწილეობა შესაძლებელია 9–17 წლის. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."


@pytest.fixture(autouse=True)
def _reset_exec_state():
    parent_tool_executor.reset_state()
    yield
    parent_tool_executor.reset_state()


def _ua_conv(sender_id, *, name="", phone="", child_age="8", last=_OFFER):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead.child_age = child_age
    if name:
        conv.lead.name = name
    if phone:
        conv.lead.phone = phone
    conv.history.append({"role": "assistant", "content": last})
    return conv


def _spy_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda lead, reason: calls.append((lead.name, lead.phone, reason)) or True,
    )
    return calls


# ===========================================================================
# BUG 1 — name+phone collection style
# ===========================================================================


def test_b1_stored_name_asks_only_phone(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-1", name="ნინო")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "კი")
    assert out is not None
    assert "ნომერ" in out                     # asks for phone
    assert "სახელი და" not in out             # does NOT ask for the name again
    assert calls == []                        # nothing dispatched yet


def test_b1_stored_name_plus_phone_dispatches_once(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-2", name="ნინო")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "595999733")
    assert len(calls) == 1
    name, phone, reason = calls[0]
    assert name == "ნინო" and phone == "595999733"
    assert "8" in reason and "ასაკ" in reason     # under-age reason
    assert "გადავეცი" in out


def test_b1_no_name_asks_name_and_phone_together(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-3")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "კი")
    assert out is not None
    assert "სახელი" in out and "ნომერ" in out     # BOTH asked in one message
    assert calls == []


def test_b1_name_then_phone_in_one_message(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-4")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert len(calls) == 1
    assert calls[0][0] == "ნიკოლოზი" and calls[0][1] == "595999733"
    assert "გადავეცი" in out


def test_b1_phone_then_name_reversed(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-5")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "595999733 ნიკოლოზი")
    assert len(calls) == 1
    assert calls[0][0] == "ნიკოლოზი" and calls[0][1] == "595999733"


def test_b1_phone_only_no_name_asks_name_no_dispatch(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-6")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "595999733")
    assert calls == [], "must NOT dispatch with an unknown name"
    assert "სახელი" in out                     # asks for the name
    assert "გადავეცი" not in out               # no false success claim


def test_b1_name_only_no_phone_asks_phone_no_dispatch(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-7")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი")
    assert calls == []
    assert "ნომერ" in out                      # asks for the phone
    assert "გადავეცი" not in out


def test_b1_success_message_never_claims_name_when_unknown(monkeypatch):
    """The success wording must not assert „სახელი" — it is generic
    („ინფორმაცია მენეჯერს გადავეცი")."""
    _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-8")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert "სახელი" not in out                 # generic success, no name claim
    assert "ინფორმაცია მენეჯერს გადავეცი" in out


def test_b1_dispatch_failure_no_false_success(monkeypatch):
    monkeypatch.setattr(notification_service, "notify_manager_handoff", lambda l, r: False)
    monkeypatch.setattr(parent_flow, "_manager_contact_for_fallback", lambda: "558 67 47 33")
    conv = _ua_conv("b1-9")
    out = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert "ვერ გადავეცი" in out
    assert "558 67 47 33" in out
    assert "დაგიკავშირდებათ" not in out and "ჩავიწერე" not in out


def test_b1_no_sheets_or_calendar_write(monkeypatch):
    _spy_dispatch(monkeypatch)
    sheets_hits, cal_hits = [], []
    for fn in ("create_lead", "save_lead", "update_lead"):
        monkeypatch.setattr(sheets_service, fn,
                            lambda *a, _f=fn, **k: sheets_hits.append(_f) or True, raising=False)
    for fn in ("book_slot", "create_event"):
        monkeypatch.setattr(calendar_service, fn,
                            lambda *a, _f=fn, **k: cal_hits.append(_f) or True, raising=False)
    conv = _ua_conv("b1-10")
    parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი 595999733")
    assert sheets_hits == [] and cal_hits == []


def test_b1_multiturn_phone_then_name_dispatches_once(monkeypatch):
    calls = _spy_dispatch(monkeypatch)
    conv = _ua_conv("b1-11")
    out1 = parent_flow._maybe_handle_underage_manager_handoff(conv, "595999733")
    assert calls == [] and "სახელი" in out1      # got phone → ask name
    out2 = parent_flow._maybe_handle_underage_manager_handoff(conv, "ნიკოლოზი")
    assert len(calls) == 1                        # now both present → dispatch once
    assert calls[0][0] == "ნიკოლოზი" and calls[0][1] == "595999733"
    assert "გადავეცი" in out2


# ===========================================================================
# BUG 2 — named past/unknown event resolves before target/age (camp context)
# ===========================================================================


def _camp_conv(sender_id, *, last=None):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    if last:
        conv.history.append({"role": "assistant", "content": last})
    return conv


@pytest.fixture
def _seed_past_gia(monkeypatch):
    """Seed a SYNTHETIC past „გია მურღულია" event so the past-event-resolution
    LOGIC is tested independently of the volatile live `sections.yaml` (the
    real event was removed by operator data cleanup, 2026-06-23). Mirrors the
    established synthetic-fixture pattern (date-bomb cleanup)."""
    from app.services import admin_config_service as a
    gia = {
        "title": "შეხვედრა გია მურღულიასთან", "status": "active",
        "date_text": "14 ივნისი 20:00", "price_text": "29",
    }
    fromula = {"title": "fromula 1", "status": "active", "date_text": "28 აგვისტო"}
    monkeypatch.setattr(a, "get_active_adult_events", lambda *ar, **k: [fromula])
    monkeypatch.setattr(a, "find_active_events_by_reference", lambda m: [])
    monkeypatch.setattr(
        a, "find_events_by_reference",
        lambda m, include_past=False: [gia] if "მურღულია" in (m or "") else [],
    )
    monkeypatch.setattr(a, "is_adult_event_past", lambda e: True)
    monkeypatch.setattr(
        a, "_event_query_tokens",
        lambda m: ["მურღულია"] if "მურღულია" in (m or "") else [],
    )
    return gia


def test_b2_named_past_event_after_context_first_try(_seed_past_gia):
    conv = _camp_conv("b2-1", last="თქვენი სახელი და ნომერი მენეჯერს გადავცე.")
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "ასევე მაინტერესებს გია მურღულიას ღონისძიება როდის არის?",
    )
    assert out is not None
    assert "უკვე გაიმართა" in out
    assert "მურღულია" in out
    assert "თქვენთვის თუ" not in out and "რამდენი წლის" not in out
    assert "2150" not in out


def test_b2_named_past_event_fresh_first_try(_seed_past_gia):
    conv = _camp_conv("b2-2")
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "გია მურღულიას ღონისძიება მაინტერესებს",
    )
    assert out is not None
    assert "უკვე გაიმართა" in out
    assert "მურღულია" in out
    assert "თქვენთვის თუ" not in out


def test_b2_unknown_named_event_no_invention():
    conv = _camp_conv("b2-3")
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "გალაქტიონის საღამო მაინტერესებს",
    )
    assert out == admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY
    assert "2150" not in out

def test_b2_generic_event_mention_defers_to_engine():
    conv = _camp_conv("b2-4")
    # generic — no specific name → interceptor defers, engine asks/lists/switches
    assert parent_flow._maybe_handle_event_inquiry(conv, "ღონისძიება მაინტერესებს") is None


def test_b2_event_price_after_camp_never_returns_camp_price():
    conv = _camp_conv("b2-5")
    out = parent_flow._maybe_handle_event_inquiry(conv, "ღონისძიების ფასი რა არის")
    assert out is not None
    assert "2150" not in out


# ===========================================================================
# Wording / formatting guard
# ===========================================================================


def test_wording_no_mogiwodebt_in_handoff_messages():
    for msg in (
        parent_flow._UNDERAGE_HANDOFF_SUCCESS,
        parent_flow._HANDOFF_ASK_NAME_AND_PHONE,
        parent_flow._HANDOFF_ASK_PHONE_ONLY,
        parent_flow._HANDOFF_GOT_PHONE_ASK_NAME,
        parent_flow._HANDOFF_GOT_NAME_ASK_PHONE,
        parent_flow._UNDERAGE_HANDOFF_FAIL_NO_CONTACT,
    ):
        assert "მოგიწოდებთ" not in msg


def test_wording_handoff_success_has_paragraph_break():
    assert "\n\n" in parent_flow._UNDERAGE_HANDOFF_SUCCESS


def test_wording_past_event_answer_uses_canonical_no_active_copy():
    conv = _camp_conv("w-1")
    out = parent_flow._maybe_handle_event_inquiry(
        conv, "გია მურღულიას ღონისძიება მაინტერესებს",
    )
    assert out == admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY
