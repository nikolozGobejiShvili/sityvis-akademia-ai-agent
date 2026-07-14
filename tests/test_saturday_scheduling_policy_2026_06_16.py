"""Scheduling Policy Update — Saturday bookings (2026-06-16).

Client/operator decision: consultations should be bookable on SATURDAY.
Sunday stays closed; weekdays and all working-hours / timezone / FreeBusy
behaviour are unchanged.

Before this change the code blocked the WHOLE weekend (Saturday AND
Sunday) via ``weekday() >= 5`` in three calendar-service sites and two
tool-executor pre-checks. The fix centralises the policy in
``calendar_service.is_closed_booking_day`` (only Sunday is closed).

These regression tests pin the new contract:

  1. Saturday booking allowed (validation + slot generation + the
     executor booking flow reaches and accepts the mocked Calendar call).
  2. Sunday booking blocked (rejected; no Calendar query, no Calendar
     booking call, no Sheets write).
  3. Weekday behaviour unchanged.
  4. Working hours unchanged (Saturday inside hours allowed, outside
     rejected, half-hour rejected).
  5. Timezone unchanged (the booking day is evaluated in Asia/Tbilisi,
     NOT UTC; naive datetimes are treated as Tbilisi).
  6. FreeBusy still respected on Saturday (a busy Saturday slot is not
     offered and cannot be booked).

Every external service (Google Calendar, Google Sheets, Meta, OpenAI,
Redis) is fully mocked — no network, no real writes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_BOOK_CONSULTATION
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import calendar_service, notification_service, sheets_service


TBILISI = ZoneInfo("Asia/Tbilisi")
UTC = timezone.utc

# Far-future anchor dates (2030) so the today-only 2h buffer never applies
# and "now" never races the wall clock.
SAT = (2030, 6, 8)   # Saturday
SUN = (2030, 6, 9)   # Sunday
WED = (2030, 6, 5)   # Wednesday (representative weekday)


def _dt(ymd: tuple[int, int, int], hour: int, minute: int = 0, *, tz=TBILISI) -> datetime:
    return datetime(ymd[0], ymd[1], ymd[2], hour, minute, tzinfo=tz)


# =========================================================================
# Sanity: the anchor dates really are the weekdays we claim.
# =========================================================================


def test_anchor_dates_are_correct_weekdays():
    assert date(*SAT).weekday() == 5  # Saturday
    assert date(*SUN).weekday() == 6  # Sunday
    assert date(*WED).weekday() == 2  # Wednesday


# =========================================================================
# is_closed_booking_day — the centralised policy helper.
# =========================================================================


@pytest.mark.parametrize(
    "ymd, weekday_name, expected_closed",
    [
        ((2030, 6, 3), "Monday", False),
        ((2030, 6, 4), "Tuesday", False),
        ((2030, 6, 5), "Wednesday", False),
        ((2030, 6, 6), "Thursday", False),
        ((2030, 6, 7), "Friday", False),
        ((2030, 6, 8), "Saturday", False),  # now OPEN
        ((2030, 6, 9), "Sunday", True),     # still CLOSED
    ],
)
def test_is_closed_booking_day_only_sunday(ymd, weekday_name, expected_closed):
    assert calendar_service.is_closed_booking_day(date(*ymd)) is expected_closed, (
        f"{weekday_name} closed-day policy regressed"
    )


# =========================================================================
# 1 + 3 — validation layer (is_within_business_hours).
# =========================================================================


def test_saturday_inside_hours_accepted():
    """A valid Saturday consultation time inside working hours is
    accepted by validation."""
    ok, reason = calendar_service.is_within_business_hours(_dt(SAT, 12, 0))
    assert ok is True, f"Saturday 12:00 must be allowed; reason={reason!r}"
    assert reason == ""


def test_sunday_inside_hours_rejected_weekend():
    """Sunday is still rejected with the stable 'weekend' reason."""
    ok, reason = calendar_service.is_within_business_hours(_dt(SUN, 12, 0))
    assert ok is False
    assert reason == "weekend"


def test_weekday_inside_hours_still_accepted():
    ok, reason = calendar_service.is_within_business_hours(_dt(WED, 12, 0))
    assert ok is True, f"weekday 12:00 must be allowed; reason={reason!r}"
    assert reason == ""


# =========================================================================
# 4 — working hours unchanged (verified on a Saturday).
# =========================================================================


def test_saturday_first_slot_10_00_allowed():
    ok, reason = calendar_service.is_within_business_hours(_dt(SAT, 10, 0))
    assert ok is True and reason == ""


def test_saturday_last_slot_20_00_allowed():
    ok, reason = calendar_service.is_within_business_hours(_dt(SAT, 20, 0))
    assert ok is True, f"Saturday 20:00 (20:00–21:00) must be allowed; reason={reason!r}"


def test_saturday_before_opening_09_00_rejected():
    ok, reason = calendar_service.is_within_business_hours(_dt(SAT, 9, 0))
    assert ok is False
    assert reason == "outside_business_hours"


def test_saturday_after_last_slot_21_00_rejected():
    """21:00 + 1h = 22:00 is past closing — rejected, exactly as on a
    weekday."""
    ok, reason = calendar_service.is_within_business_hours(_dt(SAT, 21, 0))
    assert ok is False
    assert reason == "outside_business_hours"


def test_saturday_half_hour_rejected():
    ok, reason = calendar_service.is_within_business_hours(_dt(SAT, 12, 30))
    assert ok is False
    assert reason == "half_hour_not_supported"


# =========================================================================
# 5 — timezone unchanged (Asia/Tbilisi, not UTC).
# =========================================================================


def test_booking_day_evaluated_in_tbilisi_not_utc_sunday():
    """An instant that is Saturday 22:00 in UTC but Sunday 02:00 in
    Asia/Tbilisi must be treated as a (closed) Sunday.

    If the weekday were (wrongly) judged in UTC it would be Saturday —
    now an OPEN day — so the 'weekend' reason proves Tbilisi-day
    evaluation."""
    instant = datetime(2030, 6, 8, 22, 0, tzinfo=UTC)
    assert instant.astimezone(TBILISI).weekday() == 6  # Sunday in Tbilisi
    ok, reason = calendar_service.is_within_business_hours(instant)
    assert ok is False
    assert reason == "weekend"


def test_booking_day_evaluated_in_tbilisi_not_utc_saturday():
    """The converse: an instant that is Friday 22:00 in UTC but Saturday
    02:00 in Asia/Tbilisi is treated as Saturday — NOT a weekend. (02:00
    is outside hours, so the reason is the hours rejection, never
    'weekend'.)"""
    instant = datetime(2030, 6, 7, 22, 0, tzinfo=UTC)
    assert instant.astimezone(TBILISI).weekday() == 5  # Saturday in Tbilisi
    ok, reason = calendar_service.is_within_business_hours(instant)
    assert ok is False
    assert reason == "outside_business_hours"
    assert reason != "weekend"


def test_naive_datetime_treated_as_tbilisi():
    """Naive datetimes are assumed Asia/Tbilisi: a naive Saturday in
    hours is allowed; a naive Sunday is a weekend."""
    ok_sat, reason_sat = calendar_service.is_within_business_hours(
        datetime(2030, 6, 8, 12, 0),
    )
    assert ok_sat is True and reason_sat == ""

    ok_sun, reason_sun = calendar_service.is_within_business_hours(
        datetime(2030, 6, 9, 12, 0),
    )
    assert ok_sun is False and reason_sun == "weekend"


def test_same_instant_two_zones_agree_on_saturday():
    same_in_utc = _dt(SAT, 12, 0).astimezone(UTC)
    assert calendar_service.is_within_business_hours(_dt(SAT, 12, 0)) == (True, "")
    assert calendar_service.is_within_business_hours(same_in_utc) == (True, "")


# =========================================================================
# 1 + 6 — slot generation (_get_free_slots_for_day) + FreeBusy respected.
# =========================================================================


def test_saturday_generates_full_slot_window_when_free(monkeypatch):
    """A fully-free Saturday yields the same 11 slots (10:00–20:00) a
    weekday would. Proves the mocked Calendar (FreeBusy) call is reached
    and honoured on Saturday."""
    calls: list[tuple] = []

    def _free(start, end):
        calls.append((start, end))
        return []

    monkeypatch.setattr(calendar_service, "_free_busy_intervals", _free)

    slots = calendar_service._get_free_slots_for_day(date(*SAT), 60)
    assert len(slots) == 11
    assert len(calls) == 1, "FreeBusy must be queried for a Saturday"
    times = [s["time"] for s in slots]
    assert times[0] == "10:00" and times[-1] == "20:00"


def test_sunday_generates_no_slots_and_never_queries_calendar(monkeypatch):
    """Sunday short-circuits BEFORE any FreeBusy query — no Calendar
    call at all."""
    def _must_not_run(start, end):
        pytest.fail("FreeBusy must not be queried on a closed Sunday")

    monkeypatch.setattr(calendar_service, "_free_busy_intervals", _must_not_run)

    slots = calendar_service._get_free_slots_for_day(date(*SUN), 60)
    assert slots == []


def test_weekday_generates_full_slot_window_when_free(monkeypatch):
    monkeypatch.setattr(calendar_service, "_free_busy_intervals", lambda s, e: [])
    slots = calendar_service._get_free_slots_for_day(date(*WED), 60)
    assert len(slots) == 11


def test_saturday_busy_slot_not_offered(monkeypatch):
    """FreeBusy still filters Saturday slots: a 12:00–13:00 busy block
    removes the 12:00 slot while neighbours stay free."""
    busy = [(_dt(SAT, 12, 0), _dt(SAT, 13, 0))]
    monkeypatch.setattr(calendar_service, "_free_busy_intervals", lambda s, e: busy)

    slots = calendar_service._get_free_slots_for_day(date(*SAT), 60)
    times = [s["time"] for s in slots]
    assert "12:00" not in times, "busy Saturday slot must be filtered out"
    assert "11:00" in times and "13:00" in times
    assert len(slots) == 10


def test_saturday_busy_slot_check_returns_false(monkeypatch):
    """The agent must not book a busy Saturday slot."""
    busy = [(_dt(SAT, 12, 0), _dt(SAT, 13, 0))]
    monkeypatch.setattr(calendar_service, "_free_busy_intervals", lambda s, e: busy)
    assert calendar_service.check_slot_available(_dt(SAT, 12, 0)) is False


def test_saturday_free_slot_check_returns_true(monkeypatch):
    monkeypatch.setattr(calendar_service, "_free_busy_intervals", lambda s, e: [])
    assert calendar_service.check_slot_available(_dt(SAT, 12, 0)) is True


# =========================================================================
# 1 + 2 + 3 — end-to-end executor booking flow (book_consultation).
# =========================================================================


def _make_executor(sender_id: str):
    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.history.append({"role": "user", "content": "ჩამიწერეთ კონსულტაციაზე"})
    lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = lead
    executor = ParentToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id=sender_id,
        platform="instagram",
    )
    return executor, conv, lead


def _book_slot_ok(**kwargs):
    """Mirror the real book_slot success contract: stamp an event_id and
    return True (the executor treats an empty event_id as failure)."""
    lead = kwargs.get("lead")
    if lead is not None:
        lead.calendar_event_id = "evt_test_saturday"
    return True


def _mock_calendar_success(monkeypatch):
    """Stub every external boundary the booking success path touches so
    nothing real is written. Returns recorders for assertions."""
    check_calls: list = []
    book_calls: list = []
    sheets_calls: list = []
    notify_calls: list = []

    def _check(slot_dt, *a, **k):
        check_calls.append(slot_dt)
        return True

    def _book(**kwargs):
        book_calls.append(kwargs)
        return _book_slot_ok(**kwargs)

    monkeypatch.setattr(calendar_service, "check_slot_available", _check)
    monkeypatch.setattr(calendar_service, "book_slot", _book)
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: (sheets_calls.append(lead), True)[1],
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda *a, **k: notify_calls.append((a, k)),
    )
    monkeypatch.setattr(parent_flow, "_generate_summary", lambda conv: "ტესტ-რეზიუმე")
    return check_calls, book_calls, sheets_calls, notify_calls


def test_executor_books_saturday_slot(monkeypatch, camp_registration_open):
    """A valid Saturday consultation booking proceeds: validation passes,
    the (mocked) Calendar call is made, and the booking succeeds."""
    check_calls, book_calls, sheets_calls, _ = _mock_calendar_success(monkeypatch)
    executor, conv, lead = _make_executor("sat_booker")

    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599123456",
        "datetime_iso": _dt(SAT, 12, 0).isoformat(),
        "child_age": "14",
        "user_confirmed_datetime": True,
    })

    assert result["success"] is True, f"Saturday booking should succeed: {result!r}"
    assert lead.calendly_booked is True
    assert book_calls, "Calendar book_slot must be called for a Saturday slot"
    assert check_calls, "Calendar availability check must run for a Saturday slot"
    assert sheets_calls, "Sheets row should be written on a successful booking"


def test_executor_rejects_sunday_slot_no_calendar_no_sheets(monkeypatch, camp_registration_open):
    """A Sunday booking is rejected at the business-day gate — before any
    Calendar query, Calendar booking, or Sheets write."""
    monkeypatch.setattr(
        calendar_service, "check_slot_available",
        lambda *a, **k: pytest.fail("check_slot_available must not run on Sunday"),
    )
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **k: pytest.fail("book_slot must not run on Sunday"),
    )
    monkeypatch.setattr(
        sheets_service, "create_lead",
        lambda lead: pytest.fail("Sheets must not be written for a blocked Sunday"),
    )
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda *a, **k: pytest.fail("no manager notification on a blocked Sunday"),
    )
    executor, conv, lead = _make_executor("sun_booker")

    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599123456",
        "datetime_iso": _dt(SUN, 12, 0).isoformat(),
        "child_age": "14",
        "user_confirmed_datetime": True,
    })

    assert result["success"] is False
    assert result["reason"] == "outside_business_hours"
    assert lead.calendly_booked is False


def test_executor_books_weekday_slot_unchanged(monkeypatch, camp_registration_open):
    """Weekday booking still works exactly as before."""
    _, book_calls, _, _ = _mock_calendar_success(monkeypatch)
    executor, conv, lead = _make_executor("wed_booker")

    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599123456",
        "datetime_iso": _dt(WED, 12, 0).isoformat(),
        "child_age": "14",
        "user_confirmed_datetime": True,
    })

    assert result["success"] is True
    assert lead.calendly_booked is True
    assert book_calls


def test_executor_books_saturday_busy_slot_is_unavailable(monkeypatch, camp_registration_open):
    """FreeBusy is respected end-to-end: a busy Saturday slot is refused
    (slot_unavailable) and never written to Calendar."""
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda *a, **k: False)
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **k: pytest.fail("book_slot must not run for a busy slot"),
    )
    # Keep the alternatives lookup from hitting a real calendar.
    monkeypatch.setattr(parent_flow, "_load_available_slots", lambda sid: [])
    executor, conv, lead = _make_executor("sat_busy_booker")

    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599123456",
        "datetime_iso": _dt(SAT, 12, 0).isoformat(),
        "child_age": "14",
        "user_confirmed_datetime": True,
    })

    assert result["success"] is False
    assert result["reason"] == "slot_unavailable"
    assert lead.calendly_booked is False


# =========================================================================
# Wording cleanup (P2) — the closed-day messaging must name only Sunday
# now that Saturday is open. These assert wording only; no scheduling
# logic is exercised here beyond the unchanged 'weekend' reason string.
# =========================================================================


def test_weekend_rejection_text_names_sunday_not_saturday():
    """The deterministic 'weekend' rejection text must clearly say Sunday
    is closed and must NOT say „შაბათ-კვირას" (Saturday-Sunday) any more."""
    out = parent_flow._format_repaired_slot_response({
        "available": False,
        "reason": "weekend",
        "datetime_iso": _dt(SUN, 12, 0).isoformat(),
    })
    assert "კვირას" in out, f"Sunday must be named: {out!r}"
    assert "არ ინიშნება" in out, f"must state it's closed: {out!r}"
    assert "შაბათ" not in out, f"Saturday must no longer be mentioned: {out!r}"
    assert "შაბათ-კვირას" not in out


def test_saturday_outside_hours_hint_says_mon_sat_not_mon_fri(monkeypatch, camp_registration_open):
    """A Saturday slot OUTSIDE working hours is rejected as
    outside_business_hours (proving Saturday is a booking day that
    reaches the hours check), and the business-hours hint now reads
    'Mon-Sat', never 'Mon-Fri'."""
    # No Calendar should be hit — the hours pre-check returns first.
    monkeypatch.setattr(
        calendar_service, "check_slot_available",
        lambda *a, **k: pytest.fail("hours pre-check should return before Calendar"),
    )
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **k: pytest.fail("book_slot must not run for an out-of-hours slot"),
    )
    executor, conv, lead = _make_executor("sat_out_of_hours")

    result = executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "599123456",
        "datetime_iso": _dt(SAT, 9, 0).isoformat(),  # 09:00, before opening
        "child_age": "14",
        "user_confirmed_datetime": True,
    })

    assert result["success"] is False
    assert result["reason"] == "outside_business_hours"
    hint = result.get("business_hours", "")
    assert "Mon-Sat" in hint, f"hint must read Mon-Sat: {hint!r}"
    assert "Mon-Fri" not in hint
