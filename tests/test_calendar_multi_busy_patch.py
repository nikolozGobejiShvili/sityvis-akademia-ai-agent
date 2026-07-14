"""Calendar Multi-Busy Check + Reschedule Wording Patch — 2026-06-04.

Live bug: manager had a busy event on a side-calendar; the agent's
FreeBusy check (single-calendar) didn't see it, so the first
availability reply was a false "free", later contradicted by the
correct check. Also the reschedule opening „კონსულტაციის გადატანას
დავეხმარები" is unnatural.

This patch:
  * Adds `BOOKING_CALENDAR_ID` + `BUSY_CALENDAR_IDS` env vars with
    safe fallbacks to the existing `GOOGLE_CALENDAR_ID`.
  * Updates `_free_busy_intervals` to query EVERY busy calendar and
    raise `_BusyCalendarQueryError` if ANY calendar's response fails —
    callers convert this to fail-CLOSED.
  * Keeps booking writes scoped to `BOOKING_CALENDAR_ID`.
  * Adds sanitiser entries fixing the awkward „გადატანას" forms.

Tests (spec PART 6):

PART 1/5 — config & fallbacks:
  * BOOKING_CALENDAR_ID falls back to GOOGLE_CALENDAR_ID.
  * BUSY_CALENDAR_IDS falls back to [BOOKING_CALENDAR_ID].
  * Comma-separated BUSY_CALENDAR_IDS parsed + deduped.
  * Booking calendar always present at front of busy list.

PART 2 — multi-calendar FreeBusy:
  * Busy event on booking calendar blocks slot.
  * Busy event on side calendar blocks slot.
  * Busy 10:30–19:00 blocks 14:00.
  * 19:00 stays free if busy ends at 19:00.
  * Partial overlap blocks slot.
  * If one busy calendar response carries `errors`, fail CLOSED.
  * FreeBusy HTTP exception → fail CLOSED.
  * Booking still writes only to BOOKING_CALENDAR_ID.

PART 4 — reschedule wording sanitiser:
  * „გადატანას დავეხმარები" rewritten.
  * „გადატანას დაგეხმარებით" rewritten.
  * „შეცვლას დაგეხმარებით" rewritten.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.agent.services.timestamps import now_tbilisi


TBILISI = ZoneInfo("Asia/Tbilisi")


def _make_settings(*, booking="", busy="", legacy="primary@example.com"):
    """Return a Settings copy with the requested calendar config."""
    from app.config import settings
    return dataclasses.replace(
        settings,
        GOOGLE_CALENDAR_ID=legacy,
        BOOKING_CALENDAR_ID=booking,
        BUSY_CALENDAR_IDS=busy,
    )


# =========================================================================
# PART 1/5 — settings fallbacks
# =========================================================================


def test_booking_calendar_id_falls_back_to_google_calendar_id():
    s = _make_settings(booking="", legacy="primary@example.com")
    assert s.booking_calendar_id() == "primary@example.com"


def test_booking_calendar_id_uses_explicit_value_when_set():
    s = _make_settings(booking="bookings@example.com", legacy="primary@example.com")
    assert s.booking_calendar_id() == "bookings@example.com"


def test_busy_calendar_ids_empty_falls_back_to_booking_calendar():
    s = _make_settings(booking="bookings@example.com", busy="")
    assert s.busy_calendar_ids() == ["bookings@example.com"]


def test_busy_calendar_ids_includes_booking_calendar_at_front():
    s = _make_settings(
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    assert s.busy_calendar_ids() == [
        "bookings@example.com",
        "manager@example.com",
    ]


def test_busy_calendar_ids_dedupes_booking_calendar_in_list():
    s = _make_settings(
        booking="bookings@example.com",
        busy="manager@example.com,bookings@example.com,manager@example.com",
    )
    assert s.busy_calendar_ids() == [
        "bookings@example.com",
        "manager@example.com",
    ]


def test_busy_calendar_ids_strips_whitespace_and_empty_entries():
    s = _make_settings(
        booking="bookings@example.com",
        busy=" manager@example.com , , side@example.com ",
    )
    assert s.busy_calendar_ids() == [
        "bookings@example.com",
        "manager@example.com",
        "side@example.com",
    ]


def test_busy_calendar_ids_with_only_legacy_calendar_set():
    """Single-calendar legacy deploy: BOOKING + BUSY both empty,
    only GOOGLE_CALENDAR_ID is set. busy_calendar_ids() must return
    that single id."""
    s = _make_settings(booking="", busy="", legacy="legacy@example.com")
    assert s.busy_calendar_ids() == ["legacy@example.com"]


# =========================================================================
# PART 2 — multi-calendar FreeBusy query
# =========================================================================


def _fake_freebusy_response(per_calendar_busy: dict[str, list[tuple[str, str]]]):
    """Build a Google-shaped FreeBusy response.

    `per_calendar_busy` maps calendar id → [(start_iso, end_iso), ...].
    Calendars not present in the dict are returned with an empty
    `busy` list (Google's normal "no busy" shape).
    """
    return {
        "calendars": {
            cid: {"busy": [{"start": s, "end": e} for s, e in intervals]}
            for cid, intervals in per_calendar_busy.items()
        },
    }


def _stub_calendar_service(monkeypatch, response):
    """Stub `_calendar_service().freebusy().query(...).execute()` so the
    test controls the payload `_free_busy_intervals` sees."""
    from app.services import calendar_service

    query = MagicMock()
    query.execute.return_value = response
    freebusy = MagicMock()
    freebusy.query.return_value = query
    service = MagicMock()
    service.freebusy.return_value = freebusy

    monkeypatch.setattr(calendar_service, "_calendar_service", lambda: service)
    return service


def _pin_settings(monkeypatch, *, booking, busy):
    from app.services import calendar_service
    swapped = _make_settings(booking=booking, busy=busy)
    monkeypatch.setattr(calendar_service, "settings", swapped)


def test_freebusy_queries_all_busy_calendar_ids(monkeypatch):
    """The FreeBusy body must enumerate every busy calendar id —
    booking calendar first, then any additional configured ones."""
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com,side@example.com",
    )
    service = _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        "bookings@example.com": [],
        "manager@example.com": [],
        "side@example.com": [],
    }))

    start = datetime(2026, 6, 4, 9, 0, tzinfo=TBILISI)
    end = datetime(2026, 6, 4, 22, 0, tzinfo=TBILISI)
    calendar_service._free_busy_intervals(start, end)

    sent_body = service.freebusy.return_value.query.call_args.kwargs["body"]
    sent_ids = [item["id"] for item in sent_body["items"]]
    assert sent_ids == [
        "bookings@example.com",
        "manager@example.com",
        "side@example.com",
    ]


def test_freebusy_returns_union_across_calendars(monkeypatch):
    """Busy intervals from EVERY calendar must be returned as a single
    flat list."""
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    payload = _fake_freebusy_response({
        "bookings@example.com": [
            ("2026-06-04T11:00:00+04:00", "2026-06-04T12:00:00+04:00"),
        ],
        "manager@example.com": [
            ("2026-06-04T14:00:00+04:00", "2026-06-04T15:00:00+04:00"),
        ],
    })
    _stub_calendar_service(monkeypatch, payload)

    start = datetime(2026, 6, 4, 9, 0, tzinfo=TBILISI)
    end = datetime(2026, 6, 4, 22, 0, tzinfo=TBILISI)
    result = calendar_service._free_busy_intervals(start, end)

    iso_pairs = sorted((s.isoformat(), e.isoformat()) for s, e in result)
    assert iso_pairs == [
        ("2026-06-04T11:00:00+04:00", "2026-06-04T12:00:00+04:00"),
        ("2026-06-04T14:00:00+04:00", "2026-06-04T15:00:00+04:00"),
    ]


def test_busy_on_booking_calendar_blocks_14_00_via_check_slot_available(monkeypatch):
    from app.services import calendar_service

    _pin_settings(monkeypatch, booking="bookings@example.com", busy="")
    _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        "bookings@example.com": [
            ("2026-06-04T14:00:00+04:00", "2026-06-04T15:00:00+04:00"),
        ],
    }))

    # 2026-06-04 is a Thursday (weekday).
    slot = datetime(2026, 6, 4, 14, 0, tzinfo=TBILISI)
    assert calendar_service.check_slot_available(slot) is False


def test_busy_on_side_calendar_blocks_14_00(monkeypatch):
    """The bug: live manager had busy on a separate calendar; the agent
    must consult it and refuse the 14:00 slot."""
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        "bookings@example.com": [],  # booking calendar clear
        "manager@example.com": [
            ("2026-06-04T10:30:00+04:00", "2026-06-04T19:00:00+04:00"),
        ],
    }))

    slot = datetime(2026, 6, 4, 14, 0, tzinfo=TBILISI)
    assert calendar_service.check_slot_available(slot) is False


def test_busy_10_30_to_19_00_blocks_11_through_18(monkeypatch):
    """Busy 10:30–19:00 blocks every 1-hour slot from 10:00 through
    18:00; 19:00 and 20:00 remain free.

    Date is derived from `now_tbilisi() + 14 days` so the test does
    NOT race the wall clock — using a hardcoded today's date here
    risks the 2-hour `SLOT_BUFFER` tripping when the real Tbilisi
    time crosses 17:00 on that exact day.

    Test Stability Patch (2026-06-06): when today is Saturday or
    Sunday, +14 days also lands on a weekend, and Calendar correctly
    rejects weekend slots regardless of FreeBusy state. Advance day-
    by-day past any weekend so the target is always a future weekday.
    """
    from app.services import calendar_service

    target_date = (now_tbilisi() + timedelta(days=14)).date()
    while target_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
        target_date = target_date + timedelta(days=1)
    date_str = target_date.isoformat()

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        "bookings@example.com": [],
        "manager@example.com": [
            (f"{date_str}T10:30:00+04:00", f"{date_str}T19:00:00+04:00"),
        ],
    }))

    blocked_hours = [10, 11, 12, 13, 14, 15, 16, 17, 18]
    for hour in blocked_hours:
        slot = datetime(
            target_date.year, target_date.month, target_date.day,
            hour, 0, tzinfo=TBILISI,
        )
        assert calendar_service.check_slot_available(slot) is False, (
            f"slot {hour:02d}:00 should be blocked (busy 10:30–19:00)"
        )

    # 19:00 starts exactly when busy ends → strict-inequality overlap
    # leaves 19:00 free.
    slot_19 = datetime(
        target_date.year, target_date.month, target_date.day,
        19, 0, tzinfo=TBILISI,
    )
    assert calendar_service.check_slot_available(slot_19) is True
    slot_20 = datetime(
        target_date.year, target_date.month, target_date.day,
        20, 0, tzinfo=TBILISI,
    )
    assert calendar_service.check_slot_available(slot_20) is True


def test_partial_overlap_blocks_slot(monkeypatch):
    from app.services import calendar_service

    _pin_settings(monkeypatch, booking="bookings@example.com", busy="")
    _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        # Busy 14:30–15:30. Slot 14:00 (14:00–15:00) overlaps at 14:30.
        "bookings@example.com": [
            ("2026-06-04T14:30:00+04:00", "2026-06-04T15:30:00+04:00"),
        ],
    }))

    slot_14 = datetime(2026, 6, 4, 14, 0, tzinfo=TBILISI)
    slot_15 = datetime(2026, 6, 4, 15, 0, tzinfo=TBILISI)
    assert calendar_service.check_slot_available(slot_14) is False
    assert calendar_service.check_slot_available(slot_15) is False


def test_freebusy_response_with_errors_block_fails_closed(monkeypatch):
    """A per-calendar `errors` payload (e.g. permission denied) must
    surface as fail-CLOSED at `check_slot_available`."""
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    bad_payload = {
        "calendars": {
            "bookings@example.com": {"busy": []},
            "manager@example.com": {
                "errors": [{"domain": "global", "reason": "notFound"}],
            },
        },
    }
    _stub_calendar_service(monkeypatch, bad_payload)

    slot = datetime(2026, 6, 4, 14, 0, tzinfo=TBILISI)
    assert calendar_service.check_slot_available(slot) is False


def test_freebusy_query_http_exception_fails_closed(monkeypatch):
    """Network / 5xx during FreeBusy query → `_BusyCalendarQueryError`
    inside `_free_busy_intervals`; `check_slot_available` returns
    False."""
    from app.services import calendar_service

    _pin_settings(monkeypatch, booking="bookings@example.com", busy="")
    query = MagicMock()
    query.execute.side_effect = RuntimeError("freebusy unreachable")
    freebusy = MagicMock()
    freebusy.query.return_value = query
    service = MagicMock()
    service.freebusy.return_value = freebusy
    monkeypatch.setattr(calendar_service, "_calendar_service", lambda: service)

    slot = datetime(2026, 6, 4, 14, 0, tzinfo=TBILISI)
    assert calendar_service.check_slot_available(slot) is False


def test_freebusy_response_missing_calendar_entry_fails_closed(monkeypatch):
    """If Google's response omits an entry for one of the requested
    calendars, we cannot prove the slot is free → fail-CLOSED."""
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    incomplete = {
        "calendars": {
            "bookings@example.com": {"busy": []},
            # manager@example.com entry missing — shape mismatch.
        },
    }
    _stub_calendar_service(monkeypatch, incomplete)

    slot = datetime(2026, 6, 4, 14, 0, tzinfo=TBILISI)
    assert calendar_service.check_slot_available(slot) is False


def test_get_free_slots_for_day_uses_multi_busy_calendars(monkeypatch):
    """`_get_free_slots_for_day` filters by every busy calendar — a busy
    block on a side calendar must prune the slot list."""
    from app.services import calendar_service as cs

    fixed_now = datetime(2026, 6, 3, 9, 0, tzinfo=TBILISI)

    class _FakeDT(cs.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FakeDT)
    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        "bookings@example.com": [],
        "manager@example.com": [
            ("2026-06-04T10:30:00+04:00", "2026-06-04T19:00:00+04:00"),
        ],
    }))

    slots = cs._get_free_slots_for_day(date(2026, 6, 4), 60)
    times = {s["time"] for s in slots}
    # 10:00 through 18:00 all blocked; 19:00 / 20:00 remain.
    assert times == {"19:00", "20:00"}


def test_get_free_slots_for_day_empty_when_freebusy_fails(monkeypatch):
    """`_free_busy_intervals` raises → `_get_free_slots_for_day` catches
    and returns []. Production paths offer the user nothing rather
    than a guessed slot list."""
    from app.services import calendar_service as cs

    fixed_now = datetime(2026, 6, 3, 9, 0, tzinfo=TBILISI)

    class _FakeDT(cs.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(cs, "datetime", _FakeDT)
    _pin_settings(monkeypatch, booking="bookings@example.com", busy="")

    query = MagicMock()
    query.execute.side_effect = RuntimeError("freebusy down")
    freebusy = MagicMock()
    freebusy.query.return_value = query
    service = MagicMock()
    service.freebusy.return_value = freebusy
    monkeypatch.setattr(cs, "_calendar_service", lambda: service)

    slots = cs._get_free_slots_for_day(date(2026, 6, 4), 60)
    assert slots == []


# =========================================================================
# PART 2 — booking still writes only to BOOKING_CALENDAR_ID
# =========================================================================


def test_book_slot_inserts_event_into_booking_calendar_only(monkeypatch):
    """Even when BUSY_CALENDAR_IDS lists multiple calendars,
    `events().insert` is called exactly once and targets
    `BOOKING_CALENDAR_ID` only."""
    from app.models.lead import Lead
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com,side@example.com",
    )

    captured = {"calendar_ids": []}

    class _FakeEvents:
        def insert(self, *, calendarId, body):
            captured["calendar_ids"].append(calendarId)
            return MagicMock(execute=lambda: {"id": "evt_only_booking"})

    class _FakeService:
        def events(self):
            return _FakeEvents()

    monkeypatch.setattr(calendar_service, "_calendar_service", lambda: _FakeService())

    lead = Lead(
        sender_id="s_w", platform="instagram", segment="PARENT",
        name="ნიკა", phone="599999733", child_age="12",
    )
    ok = calendar_service.book_slot("2026-06-04T19:00:00+04:00", lead)
    assert ok is True
    # Booking calendar appears exactly once.
    assert captured["calendar_ids"] == ["bookings@example.com"]
    assert "manager@example.com" not in captured["calendar_ids"]
    assert "side@example.com" not in captured["calendar_ids"]


def test_cancel_calendar_event_targets_booking_calendar(monkeypatch):
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    captured = {"calendar_id": None}

    class _FakeEvents:
        def delete(self, *, calendarId, eventId):
            captured["calendar_id"] = calendarId
            return MagicMock(execute=lambda: None)

    class _FakeService:
        def events(self):
            return _FakeEvents()

    monkeypatch.setattr(calendar_service, "_calendar_service", lambda: _FakeService())
    assert calendar_service.cancel_calendar_event("evt_x") is True
    assert captured["calendar_id"] == "bookings@example.com"


def test_legacy_single_calendar_deploy_uses_google_calendar_id(monkeypatch):
    """Operator with no `BOOKING_CALENDAR_ID` / `BUSY_CALENDAR_IDS`
    set keeps the pre-patch behaviour: single calendar query against
    `GOOGLE_CALENDAR_ID`."""
    from app.services import calendar_service

    _pin_settings(monkeypatch, booking="", busy="")
    service = _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        "primary@example.com": [],
    }))

    start = datetime(2026, 6, 4, 9, 0, tzinfo=TBILISI)
    end = datetime(2026, 6, 4, 22, 0, tzinfo=TBILISI)
    calendar_service._free_busy_intervals(start, end)

    sent_body = service.freebusy.return_value.query.call_args.kwargs["body"]
    sent_ids = [item["id"] for item in sent_body["items"]]
    assert sent_ids == ["primary@example.com"]


# =========================================================================
# PART 4 — reschedule wording sanitiser
# =========================================================================


def test_sanitiser_rewrites_konsultaciis_gadatans_davekhmare():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    bad = "კონსულტაციის გადატანას დავეხმარები. რომელი თარიღი გსურთ?"
    out = sanitise_response_wording(bad)
    assert "გადატანას დავეხმარები" not in out
    assert "გადატანაში დაგეხმარებით" in out


def test_sanitiser_rewrites_gadatans_dagekhmarebit():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    bad = "ჯავშნის გადატანას დაგეხმარებით."
    out = sanitise_response_wording(bad)
    assert "გადატანას დაგეხმარებით" not in out
    assert "გადატანაში დაგეხმარებით" in out


def test_sanitiser_rewrites_shecvla_dagekhmarebit():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    bad = "კონსულტაციის შეცვლას დაგეხმარებით."
    out = sanitise_response_wording(bad)
    assert "შეცვლას დაგეხმარებით" not in out
    assert "შეცვლაში დაგეხმარებით" in out


def test_sanitiser_preserves_correct_reschedule_wording():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    text = "კონსულტაციის გადატანაში დაგეხმარებით. რომელი დრო გსურთ?"
    assert sanitise_response_wording(text) == text


def test_sanitiser_idempotent_for_reschedule_rewrite():
    from app.agent.llm.parent_llm_engine import sanitise_response_wording
    bad = "კონსულტაციის გადატანას დავეხმარები."
    once = sanitise_response_wording(bad)
    twice = sanitise_response_wording(once)
    assert once == twice


# =========================================================================
# Prompt evidence — PART 3 / PART 4
# =========================================================================


def test_prompt_documents_reschedule_wording():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "კონსულტაციის გადატანაში დაგეხმარებით" in text
    # The banned form is also called out.
    assert "გადატანას დავეხმარები" in text


def test_prompt_forbids_thavisuplaia_without_check():
    from app.agent.llm.prompt_loader import load_prompt, reset_cache
    reset_cache()
    text = load_prompt("system_parent_v2")
    # The rule that the LLM must call check_consultation_slot BEFORE
    # claiming "თავისუფალია" / "დამიდასტურეთ".
    assert "სავალდებულოა" in text
    assert "check_consultation_slot" in text


# =========================================================================
# PART 3 — reschedule path uses same multi-busy check
# =========================================================================


def test_reschedule_executor_blocks_when_calendar_busy(monkeypatch, camp_registration_open):
    """The executor's reschedule path calls `check_slot_available`,
    which now uses the multi-busy backend. A busy event on a side
    calendar must surface as `slot_unavailable`."""
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    from app.services import calendar_service

    _pin_settings(
        monkeypatch,
        booking="bookings@example.com",
        busy="bookings@example.com,manager@example.com",
    )
    _stub_calendar_service(monkeypatch, _fake_freebusy_response({
        "bookings@example.com": [],
        "manager@example.com": [
            ("2030-06-04T14:00:00+04:00", "2030-06-04T15:00:00+04:00"),
        ],
    }))

    conv = Conversation(sender_id="s_r", platform="instagram", segment="PARENT")
    lead = Lead(
        sender_id="s_r", platform="instagram", segment="PARENT",
        name="ნიკა", phone="599999733", child_age="12",
        calendly_booked=True,
        booked_datetime_iso="2030-06-04T10:00:00+04:00",
        calendar_event_id="evt_old",
    )
    conv.lead = lead
    executor = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="s_r", platform="instagram",
    )
    result = executor.execute("manage_consultation_booking", {
        "action": "reschedule",
        "new_datetime_iso": "2030-06-04T14:00:00+04:00",
    })
    assert result["success"] is False
    assert result["reason"] == "slot_unavailable"
