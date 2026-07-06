"""Consultation booking day/time reply must NOT fall into adult events (live bug 2026-06-27).

Transcript:
  Agent: „მადლობა, სალომე. რომელი დღე და დრო გირჩევნიათ კონსულტაციისთვის?"
  User : „ორშაბათს, საღამოს საათებში"
  Bad  : „ამ ეტაპზე აქტიური ღონისძიება სიაში არ მაქვს. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."

Root cause: `_maybe_handle_event_inquiry` (adult-event interceptor, runs pre-engine)
treated the reply as a named-event query because „საღამოს" (evening daypart)
contains „საღამო" (the adult-event word) and the tokens passed the genuine-name
gate. With 0 active events it returned the no-events fallback.

Fix (deterministic, GENERAL day/time-in-booking-context detection — NOT a
phrase handler, planner/slim OFF, engine ON):
  * `_maybe_handle_event_inquiry` steps aside when the conversation is in
    consultation booking context AND the message looks like a date/time/daypart
    reply;
  * a new `_maybe_handle_booking_datetime_reply` keeps such replies in the
    booking flow — a broad daypart with no exact time asks for the exact hour
    (daypart-aware); an exact time defers to the existing booking commit/engine.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service, messenger_service

_MANAGER_NUMBER = "558 67 47 33"
_ADULT_FALLBACK = "აქტიური ღონისძიება"   # the bug-phrase fragment
_ENGINE_MARK = "[ENGINE]"


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture(autouse=True)
def _mock_calendar(monkeypatch):
    """BUG 6 (2026-07-06) — the daypart handler now offers REAL calendar free
    slots. Mock the calendar so tests are deterministic (hourly slots 10:00–20:00
    on any day; not Sunday; a fixed Tuesday `now`)."""
    from datetime import datetime
    from app.services import calendar_service

    def _slots(day):
        return [{"date": str(day), "time": f"{h:02d}:00"} for h in range(10, 21)]

    monkeypatch.setattr(calendar_service, "get_free_slots", _slots)
    monkeypatch.setattr(calendar_service, "is_closed_booking_day", lambda now: False)
    monkeypatch.setattr(
        calendar_service, "now_tbilisi",
        lambda: datetime(2026, 7, 7, 9, 0, tzinfo=calendar_service.TIMEZONE),
    )
    yield


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # The engine is reached only for an exact-time booking turn (test 3); make
    # sure no real OpenAI call happens and the reply is recognisable.
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: f"{_ENGINE_MARK} კონსულტაციას მოვაგვარებთ — დაგიდასტურებთ დროს.",
    )
    return swapped


def _booking_conv(sid="bk", name="სალომე", phone="558914814", child_age="14"):
    """Turn-N conversation where the bot just asked the consultation date/time."""
    c = Conversation(sender_id=sid, platform="instagram", segment="PARENT")
    c.state = "OFFER_BOOKING"
    c.history.append({
        "role": "assistant",
        "content": f"მადლობა, {name}. რომელი დღე და დრო გირჩევნიათ კონსულტაციისთვის?",
    })
    c.lead = Lead(
        sender_id=sid, platform="instagram", segment="PARENT",
        name=name, phone=phone, child_age=child_age,
    )
    return c


def _asks_for_time(text: str) -> bool:
    # BUG 6 (2026-07-06) — the handler now OFFERS real free slots and asks
    # „რომელი დრო გირჩევნიათ?" (in addition to the legacy „რომელი საათი" form).
    low = (text or "").lower()
    return (
        ("რომელი საათი" in low)
        or ("რომელ საათზე" in low)
        or ("რომელი დრო" in low)
    )


def _no_adult_fallback(text: str) -> bool:
    return _ADULT_FALLBACK not in (text or "")


# =====================================================================
# Required test 1 — mixed day + evening daypart (the exact bug)
# =====================================================================
def test_1_evening_daypart_stays_in_booking(engine_on):
    conv = _booking_conv()
    out = parent_flow.handle(conv, "ორშაბათს, საღამოს საათებში")
    assert _no_adult_fallback(out)                 # NOT „აქტიური ღონისძიება"
    assert "ღონისძიება" not in out                 # not routed to adult events
    assert _asks_for_time(out)                     # asks for the exact time
    assert ("18:00" in out) or ("19:00" in out)    # evening slot examples


# =====================================================================
# Required test 2 — weekday only
# =====================================================================
def test_2_weekday_only_asks_time(engine_on):
    conv = _booking_conv()
    out = parent_flow.handle(conv, "ორშაბათს")
    assert _no_adult_fallback(out)
    assert "ღონისძიება" not in out
    assert _asks_for_time(out)


# =====================================================================
# Required test 3 — exact relative time → continues booking (engine)
# =====================================================================
def test_3_exact_time_continues_booking(engine_on):
    conv = _booking_conv()
    out = parent_flow.handle(conv, "ხვალ 6-ზე")
    assert _no_adult_fallback(out)
    assert "ღონისძიება" not in out
    assert _ENGINE_MARK in out                     # reached the booking engine, not adult fallback


# =====================================================================
# Required test 4 — bare daypart
# =====================================================================
def test_4_bare_daypart_asks_day_time(engine_on):
    conv = _booking_conv()
    out = parent_flow.handle(conv, "საღამოს")
    assert _no_adult_fallback(out)
    assert _asks_for_time(out)


# =====================================================================
# Required test 5 — adult event query still works (not hijacked)
# =====================================================================
def test_5_adult_query_still_works(engine_on):
    q = "ზრდასრულთა ღონისძიებები რა გაქვთ?"
    # An explicit adult-event query is never a booking date/time reply …
    assert parent_flow._looks_like_booking_datetime_reply(q) is False
    # … and is never captured by the booking-datetime handler, even mid-booking.
    assert parent_flow._maybe_handle_booking_datetime_reply(_booking_conv(), q) is None
    # End-to-end (fresh, non-booking): routes to the existing adult/event path,
    # never the booking time-ask.
    fresh = Conversation(sender_id="ad", platform="instagram", segment="PARENT")
    fresh.lead = Lead(sender_id="ad", platform="instagram", segment="PARENT")
    out = parent_flow.handle(fresh, q)
    assert not _asks_for_time(out)


# =====================================================================
# Required test 6 — camp registration link still works
# =====================================================================
def test_6_camp_registration_still_works(engine_on):
    conv = _booking_conv()                          # even mid-booking
    out = parent_flow.handle(conv, "ბანაკის რეგისტრაციის ლინკი მომწერე")
    assert out == parent_flow._render_camp_registration_answer()
    assert not _asks_for_time(out)


# =====================================================================
# Required test 7 — manager phone priority still works
# =====================================================================
def test_7_manager_phone_priority_still_works(engine_on):
    conv = _booking_conv()
    out = parent_flow.handle(conv, "კონსულტაცია არ მინდა, მენეჯერის ნომერი მომწერეთ")
    assert _MANAGER_NUMBER in out
    assert not _asks_for_time(out)


# =====================================================================
# Guard / unit coverage
# =====================================================================
def test_event_inquiry_suppressed_for_booking_datetime_reply():
    # Direct: without the guard this returned the adult no-events fallback.
    conv = _booking_conv()
    assert parent_flow._maybe_handle_event_inquiry(conv, "ორშაბათს, საღამოს საათებში") is None


def test_out_of_context_daypart_does_not_fire():
    # No booking context → the booking-datetime handler must not fire.
    fresh = Conversation(sender_id="oc", platform="instagram", segment="PARENT")
    fresh.lead = Lead(sender_id="oc", platform="instagram", segment="PARENT")
    assert parent_flow._in_consultation_booking_context(fresh) is False
    assert parent_flow._maybe_handle_booking_datetime_reply(
        fresh, "ორშაბათს, საღამოს საათებში",
    ) is None


def test_pending_booking_counts_as_booking_context():
    c = Conversation(sender_id="pb", platform="instagram", segment="PARENT")
    c.lead = Lead(sender_id="pb", platform="instagram", segment="PARENT",
                  name="ნიკოლოზი", phone="595999733", child_age="14")
    c.pending_booking = {"requested_datetime_iso": "2026-07-06T12:00:00"}
    assert parent_flow._in_consultation_booking_context(c) is True
    out = parent_flow._maybe_handle_booking_datetime_reply(c, "ორშაბათს")
    assert out is not None and _asks_for_time(out)


def test_exact_time_defers_to_booking_flow():
    # An exact-time reply is not consumed by the daypart handler (defers → None).
    conv = _booking_conv()
    assert parent_flow._maybe_handle_booking_datetime_reply(conv, "სამშაბათს 19:00") is None
    assert parent_flow._maybe_handle_booking_datetime_reply(conv, "ხვალ 6-ზე") is None


def test_afternoon_daypart_examples():
    conv = _booking_conv()
    out = parent_flow._maybe_handle_booking_datetime_reply(conv, "დღის მეორე ნახევარში")
    assert out is not None and _asks_for_time(out)
    assert ("14:00" in out) or ("15:00" in out) or ("16:00" in out)
