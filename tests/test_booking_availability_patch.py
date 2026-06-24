"""Booking Availability Patch — 2026-06-03.

New consultation booking rules:
  * Window 10:00–21:00 Asia/Tbilisi, weekdays only.
  * Slots are 1 hour (60 minutes). No half-hour slots.
  * First valid start: 10:00. Last valid start: 20:00. 21:00 is
    closing time, never a valid start.
  * Real Google Calendar busy data filters offered slots and
    blocks final-step booking confirmation.
  * Partial overlap with a busy event blocks the candidate slot.
  * Calendar API failure → return False from `check_slot_available`
    so the booking path surfaces the manager-callback fallback.

Per spec PART 5 the new tests cover:
  1. 10:00 valid
  2. 20:00 valid
  3. 21:00 invalid
  4. 09:00 invalid
  5. 20:30 invalid
  6. 18:00 valid if free
  7. 10:30 not offered
  8. Calendar event duration = 1 hour
  9. busy block 12:00–17:00 hides overlapping slots
  10. partial overlap 12:30–13:30 blocks 12:00 and 13:00
  11. final pre-booking re-check blocks newly busy slot
  12. Calendar API failure does not book blindly
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest


TBILISI = ZoneInfo("Asia/Tbilisi")


def _far_future_weekday(hour: int = 10, minute: int = 0) -> datetime:
    """Return a far-future weekday datetime in Asia/Tbilisi for
    deterministic business-hours testing."""
    # 2030-06-05 is a Wednesday.
    return datetime(2030, 6, 5, hour, minute, tzinfo=TBILISI)


# =========================================================================
# 1-7 — is_within_business_hours edge cases
# =========================================================================


def test_10_00_is_valid_first_slot():
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(10, 0))
    assert ok is True
    assert reason == ""


def test_20_00_is_valid_last_slot():
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(20, 0))
    assert ok is True, f"20:00 must be valid (20:00–21:00). Got reason={reason!r}"


def test_21_00_is_invalid_closing_time():
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(21, 0))
    assert ok is False
    # 21:00 + 1h = 22:00, past closing.
    assert reason == "outside_business_hours"


def test_09_00_is_invalid_before_opening():
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(9, 0))
    assert ok is False
    assert reason == "outside_business_hours"


def test_20_30_is_invalid_half_hour_after_last_slot():
    """20:30 has TWO problems: it's a half-hour AND its end (21:30)
    would be past closing. The half-hour rule fires first."""
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(20, 30))
    assert ok is False
    assert reason == "half_hour_not_supported"


def test_18_00_is_valid_if_free():
    """18:00 weekday is well inside the new 10:00–21:00 window."""
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(18, 0))
    assert ok is True
    assert reason == ""


def test_10_30_is_rejected_by_half_hour_rule():
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(10, 30))
    assert ok is False
    assert reason == "half_hour_not_supported"


def test_11_30_is_rejected_by_half_hour_rule():
    from app.services.calendar_service import is_within_business_hours
    ok, reason = is_within_business_hours(_far_future_weekday(11, 30))
    assert ok is False
    assert reason == "half_hour_not_supported"


def test_saturday_now_allowed():
    """Scheduling policy update (2026-06-16): Saturday is now an OPEN
    booking day. 2030-06-08 = Saturday; 12:00 is inside 10:00–21:00."""
    from app.services.calendar_service import is_within_business_hours
    slot = datetime(2030, 6, 8, 12, 0, tzinfo=TBILISI)
    ok, reason = is_within_business_hours(slot)
    assert ok is True, f"Saturday in-hours must be allowed; got reason={reason!r}"
    assert reason == ""


def test_sunday_still_rejected():
    """Sunday remains CLOSED. 2030-06-09 = Sunday."""
    from app.services.calendar_service import is_within_business_hours
    slot = datetime(2030, 6, 9, 12, 0, tzinfo=TBILISI)
    ok, reason = is_within_business_hours(slot)
    assert ok is False
    assert reason == "weekend"


# =========================================================================
# 8 — Calendar event duration is 1 hour
# =========================================================================


def test_book_slot_default_duration_is_60_minutes(monkeypatch):
    """`book_slot` constructs the Calendar event with `end = start +
    60min` by default. This guarantees consultation events occupy a
    full 1-hour block in the manager's calendar."""
    from app.models.lead import Lead
    from app.services import calendar_service

    captured: dict = {}

    class _FakeEvents:
        def insert(self, *, calendarId, body):
            captured["body"] = body
            class _Exec:
                def execute(self_inner):
                    return {"id": "evt_test_60min"}
            return _Exec()

    class _FakeService:
        def events(self):
            return _FakeEvents()

    monkeypatch.setattr(calendar_service, "_calendar_service", lambda: _FakeService())

    lead = Lead(sender_id="s_dur", platform="instagram", segment="PARENT",
                name="ნიკა", phone="599999733", child_age="14")
    ok = calendar_service.book_slot("2030-06-05T15:00:00+04:00", lead)
    assert ok is True

    start = captured["body"]["start"]["dateTime"]
    end = captured["body"]["end"]["dateTime"]
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    delta_min = int((end_dt - start_dt).total_seconds() // 60)
    assert delta_min == 60, f"expected 60-min event, got {delta_min}-min"


# =========================================================================
# 9-10 — Google Calendar busy blocks (partial overlap)
# =========================================================================


def _stub_busy(monkeypatch, *intervals: tuple[datetime, datetime]) -> None:
    """Pin `_free_busy_intervals` to a fixed list of busy ranges."""
    from app.services import calendar_service

    def _fake_freebusy(start_at, end_at):
        return list(intervals)

    monkeypatch.setattr(
        calendar_service, "_free_busy_intervals", _fake_freebusy,
    )


def _pin_now(monkeypatch, fixed_now: datetime) -> None:
    """Pin calendar_service.datetime.now() so the buffer-today rule is
    deterministic."""
    from app.services import calendar_service as cs

    class _FakeDT(cs.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FakeDT)


def test_busy_block_12_to_17_hides_all_overlapping_slots(monkeypatch):
    """Manager calendar busy 12:00–17:00 on a future weekday must
    block the 12, 13, 14, 15, 16 slots; 10/11/17/18/19/20 stay free.
    """
    from app.services import calendar_service

    fixed_now = datetime(2030, 6, 4, 9, 0, tzinfo=TBILISI)
    _pin_now(monkeypatch, fixed_now)
    target = date(2030, 6, 5)  # Wednesday
    busy_start = datetime(2030, 6, 5, 12, 0, tzinfo=TBILISI)
    busy_end = datetime(2030, 6, 5, 17, 0, tzinfo=TBILISI)
    _stub_busy(monkeypatch, (busy_start, busy_end))

    slots = calendar_service._get_free_slots_for_day(target, 60)
    times = {s["time"] for s in slots}

    # Open slots:
    for t in ("10:00", "11:00", "17:00", "18:00", "19:00", "20:00"):
        assert t in times, f"{t} must be offered (busy was 12:00–17:00). Got {sorted(times)}"
    # Blocked slots:
    for t in ("12:00", "13:00", "14:00", "15:00", "16:00"):
        assert t not in times, f"{t} must be blocked (overlaps 12:00–17:00). Got {sorted(times)}"


def test_partial_overlap_12_30_to_13_30_blocks_12_and_13(monkeypatch):
    """A 1-hour busy block at 12:30–13:30 partially overlaps the 12:00
    and 13:00 candidate slots — both must be blocked."""
    from app.services import calendar_service

    fixed_now = datetime(2030, 6, 4, 9, 0, tzinfo=TBILISI)
    _pin_now(monkeypatch, fixed_now)
    target = date(2030, 6, 5)
    busy_start = datetime(2030, 6, 5, 12, 30, tzinfo=TBILISI)
    busy_end = datetime(2030, 6, 5, 13, 30, tzinfo=TBILISI)
    _stub_busy(monkeypatch, (busy_start, busy_end))

    slots = calendar_service._get_free_slots_for_day(target, 60)
    times = {s["time"] for s in slots}

    # 12:00 ends at 13:00 which is INSIDE busy (busy starts at 12:30).
    # 13:00 starts at 13:00 which is INSIDE busy (busy ends 13:30).
    assert "12:00" not in times, f"12:00 must be blocked by partial overlap"
    assert "13:00" not in times, f"13:00 must be blocked by partial overlap"
    # 11:00 (ends at 12:00) and 14:00 (starts at 14:00) are clear.
    assert "11:00" in times
    assert "14:00" in times


def test_busy_at_exact_boundary_does_not_block_adjacent_slot(monkeypatch):
    """Busy 13:00–14:00 must NOT block 12:00 (ends exactly at 13:00)
    nor 14:00 (starts exactly when busy ends). Strict-inequality
    interval overlap is required."""
    from app.services import calendar_service

    fixed_now = datetime(2030, 6, 4, 9, 0, tzinfo=TBILISI)
    _pin_now(monkeypatch, fixed_now)
    target = date(2030, 6, 5)
    busy_start = datetime(2030, 6, 5, 13, 0, tzinfo=TBILISI)
    busy_end = datetime(2030, 6, 5, 14, 0, tzinfo=TBILISI)
    _stub_busy(monkeypatch, (busy_start, busy_end))

    slots = calendar_service._get_free_slots_for_day(target, 60)
    times = {s["time"] for s in slots}
    # 12:00 ends exactly when busy starts — should remain offered.
    assert "12:00" in times
    # 13:00 IS busy — blocked.
    assert "13:00" not in times
    # 14:00 starts exactly when busy ends — should remain offered.
    assert "14:00" in times


def test_get_free_slots_with_default_duration_only_offers_whole_hour(monkeypatch):
    """`_get_free_slots_for_day(date, 60)` must NEVER emit a half-hour
    slot like 10:30 / 11:30 / 20:30."""
    from app.services import calendar_service

    fixed_now = datetime(2030, 6, 4, 9, 0, tzinfo=TBILISI)
    _pin_now(monkeypatch, fixed_now)
    _stub_busy(monkeypatch)
    target = date(2030, 6, 5)

    slots = calendar_service._get_free_slots_for_day(target, 60)
    times = [s["time"] for s in slots]
    for t in times:
        assert t.endswith(":00"), f"slot {t!r} is not on the hour"
    # 20:30 / 21:00 must not appear regardless of clock state.
    assert "20:30" not in times
    assert "21:00" not in times
    # First and last slots align with the new window.
    assert times[0] == "10:00"
    assert times[-1] == "20:00"


def test_get_free_slots_covers_full_10_00_to_20_00_window(monkeypatch):
    """Range form must produce exactly 11 slots (10..20 inclusive)
    on a fully-free future weekday."""
    from app.services import calendar_service

    fixed_now = datetime(2030, 6, 4, 9, 0, tzinfo=TBILISI)
    _pin_now(monkeypatch, fixed_now)
    _stub_busy(monkeypatch)
    target = date(2030, 6, 5)

    slots = calendar_service._get_free_slots_for_day(target, 60)
    assert len(slots) == 11
    assert [s["time"] for s in slots] == [
        "10:00", "11:00", "12:00", "13:00", "14:00",
        "15:00", "16:00", "17:00", "18:00", "19:00", "20:00",
    ]


# =========================================================================
# 11 — Final pre-booking re-check blocks newly busy slot
# =========================================================================


def test_pre_booking_re_check_blocks_newly_busy_slot(monkeypatch):
    """`_book_selected_slot` calls `check_slot_available` BEFORE the
    Calendar `events().insert` call. If the slot has become busy
    between the offer and the booking attempt, the booking is refused
    and `book_slot` is NEVER invoked."""
    from app.flows import parent_flow
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    from app.services import calendar_service

    # Slot looked free when offered, now busy when we re-check.
    calls = {"check": 0, "book": 0}

    def _check(slot_dt, duration_minutes=60):
        calls["check"] += 1
        return False  # newly busy

    def _book(*a, **kw):
        calls["book"] += 1
        return True

    monkeypatch.setattr(calendar_service, "check_slot_available", _check)
    monkeypatch.setattr(calendar_service, "book_slot", _book)

    conv = Conversation(sender_id="s_recheck", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="s_recheck", platform="instagram", segment="PARENT",
                name="ნიკა", phone="599999733", child_age="12")
    conv.lead = lead

    slot = {
        "date": "5 ივნისი",
        "time": "15:00",
        "datetime_iso": "2030-06-05T15:00:00+04:00",
    }
    booked = parent_flow._book_selected_slot(conv, lead, slot)
    assert booked is False
    assert calls["check"] == 1
    assert calls["book"] == 0, "book_slot must NOT fire when re-check fails"


# =========================================================================
# 12 — Calendar API failure does not book blindly
# =========================================================================


def test_pre_booking_calendar_api_failure_fails_closed(monkeypatch):
    """When `check_slot_available` raises (Calendar API blip), the
    pre-check must fail CLOSED — `book_slot` is NOT called and the
    booking path returns False so the LLM can surface the manager
    callback."""
    from app.flows import parent_flow
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    from app.services import calendar_service

    book_calls = {"n": 0}

    def _check(slot_dt, duration_minutes=60):
        raise RuntimeError("Calendar API blew up")

    def _book(*a, **kw):
        book_calls["n"] += 1
        return True

    monkeypatch.setattr(calendar_service, "check_slot_available", _check)
    monkeypatch.setattr(calendar_service, "book_slot", _book)

    conv = Conversation(sender_id="s_api", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="s_api", platform="instagram", segment="PARENT",
                name="ნიკა", phone="599999733", child_age="12")
    conv.lead = lead

    slot = {
        "date": "5 ივნისი",
        "time": "15:00",
        "datetime_iso": "2030-06-05T15:00:00+04:00",
    }
    booked = parent_flow._book_selected_slot(conv, lead, slot)
    assert booked is False, "fail-CLOSED on Calendar API exception"
    assert book_calls["n"] == 0, "book_slot must NOT fire when re-check raises"


def test_check_slot_available_freebusy_api_error_fails_closed(monkeypatch):
    """`check_slot_available` itself must return False when the
    Free/Busy API raises — it is the production guard against blind
    double-booking."""
    from app.services import calendar_service

    def _boom(start_at, end_at):
        raise RuntimeError("freebusy down")

    monkeypatch.setattr(calendar_service, "_free_busy_intervals", _boom)

    # Far-future weekday at 15:00 — passes business-hour rules so the
    # function reaches the freebusy step.
    slot = _far_future_weekday(15, 0)
    assert calendar_service.check_slot_available(slot) is False


# =========================================================================
# Wording / prompt evidence
# =========================================================================


def test_prompt_documents_new_business_hours():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "10:00-დან 21:00-მდე" in text
    # First slot and last slot explicitly named.
    assert "10:00" in text and "20:00" in text


def test_prompt_documents_half_hour_rule():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "half_hour_not_supported" in text
    assert "ერთსაათიანი სლოტებით" in text


def test_business_hours_yaml_uses_new_window():
    from app.agent.services.knowledge_loader import load_knowledge
    b = load_knowledge("business_hours")["business"]
    assert b["work_hours"]["start"] == "10:00"
    assert b["work_hours"]["end"] == "21:00"
    assert b["business_hours"]["end"] == "21:00"
    assert b["slot"]["duration_minutes"] == 60


# =========================================================================
# Reason-string contract — LLM consumes these literally
# =========================================================================


@pytest.mark.parametrize("hour,minute,expected_reason", [
    (9, 0, "outside_business_hours"),
    (10, 0, ""),
    (10, 30, "half_hour_not_supported"),
    (11, 0, ""),
    (11, 30, "half_hour_not_supported"),
    (18, 0, ""),
    (19, 0, ""),
    (20, 0, ""),
    (20, 30, "half_hour_not_supported"),
    (21, 0, "outside_business_hours"),
    (22, 0, "outside_business_hours"),
])
def test_is_within_business_hours_reason_matrix(hour, minute, expected_reason):
    from app.services.calendar_service import is_within_business_hours
    slot = _far_future_weekday(hour, minute)
    ok, reason = is_within_business_hours(slot)
    if expected_reason == "":
        assert ok is True, f"{hour}:{minute:02d} expected accepted, reason={reason!r}"
        assert reason == ""
    else:
        assert ok is False
        assert reason == expected_reason
