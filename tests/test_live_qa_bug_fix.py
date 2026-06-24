"""Live QA Bug Fix Patch — 2026-06-04.

Three live-test bugs surfaced after the Booking Date Parse + Lead
Field Separation Patch:

  BUG 1 — Event Interest column leaks adult data into PARENT
          Sheets row. Previous patch closed the leak on the
          challenge column but the event_interest column still
          carried „ზრდასრულთა საღამოები" for PARENT leads.

  BUG 2 — ADULT transition still stops. gpt-5.4-mini produces
          short ack responses ending in „დაგეხმარებით." that the
          previous bare-intro detector missed.

  BUG 3 — Two issues bundled:
          (A) „კარგად შეამოწმე თავისუფალია?" triggered
              `book_consultation` instead of a re-check via
              `check_consultation_slot`.
          (B) `calendar_service.book_slot` can return True without
              an event_id (Google Calendar HTTP 200 empty body).
              The agent said „ჩაგინიშნეთ" without an actual
              event. Backend must reject this silent failure.

PART 1 — BUG 1 — Sheets PARENT row scrub:
  * PARENT row event_interest cell is blank when lead carries
    „ზრდასრულთა..." / „კულტურული საღამო" etc.
  * PARENT row event_interest cell preserves a camp-related
    value.
  * ADULT row event_interest cell preserves adult vocabulary
    (unchanged behaviour).
  * UNCLEAR row passes through unchanged.
  * Lead in-memory `lead.event_interest` NOT mutated.

PART 2 — BUG 2 — Adult intro followup broader detection:
  * Bare „გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით." →
    next question appended.
  * Any short response ending with „დაგეხმარებით." → next question
    appended.
  * Response with „?" → not modified.
  * Response > 120 chars → not modified.
  * gpt-5.4-mini period-separator variant catches.

PART 3 — BUG 3A — Verification phrases reject book:
  * „კარგად შეამოწმე თავისუფალია?" → `book_consultation` returns
    `reason=verification_requested`.
  * „ნამდვილად თავისუფალია?" → same.
  * „დარწმუნებული ხარ?" → same.
  * No verification phrase + valid args → booking proceeds.

PART 4 — BUG 3B — Backend booking success/failure:
  * `book_slot` returns False → tool result success=False
    reason=calendar_error.
  * `book_slot` raises → tool result success=False.
  * `book_slot` returns True but no event_id → tool result
    success=False, reason=calendar_booking_failed.
  * `book_slot` returns True with event_id → tool result
    success=True.
  * Failed booking → Sentry capture called with area=booking +
    masked sender.
  * Failed booking → lead.calendly_booked rolled back to False.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.llm.adult_llm_engine import (
    _ends_with_dagexmarebit,
    _ensure_adult_intro_followup,
)
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    _user_requested_verification,
)
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import sheets_service


TBILISI = ZoneInfo("Asia/Tbilisi")
FIXED_NOW = datetime(2026, 6, 4, 9, 0, 0, tzinfo=TBILISI)


def _future_slot_iso() -> str:
    """A dynamically-computed future weekday slot at 11:00 (Tbilisi).

    Test-robustness fix (2026-06-15): `_book_consultation`'s past-date guard
    uses the REAL wall clock (`datetime.now(...)`, NOT the patched
    `now_tbilisi`), so a hard-coded slot date silently expires and turns
    these booking regressions into wall-clock date-bombs. Computing the slot
    relative to the real clock keeps them deterministic on any run date.
    """
    dt = datetime.now(TBILISI) + timedelta(days=3)
    while dt.weekday() >= 5:  # skip Sat/Sun
        dt += timedelta(days=1)
    return dt.replace(hour=11, minute=0, second=0, microsecond=0).isoformat()


FUTURE_SLOT_ISO = _future_slot_iso()


# =========================================================================
# PART 1 — BUG 1 — Sheets PARENT event_interest column scrub
# =========================================================================


def test_parent_row_scrubs_adult_event_interest_from_cell():
    lead = Lead(
        sender_id="s1",
        platform="instagram",
        segment="PARENT",
        name="ნანა",
        phone="555111222",
        child_age="12",
        challenge="ახალი მეგობრები და საინტერესო ზაფხული",
        event_interest="ზრდასრულთა საღამოები",
    )
    row = sheets_service._lead_to_row(lead, lead_id=1)
    # Event Interest is column index 10 (0-based) per HEADERS layout.
    event_interest_cell = row[10]
    assert event_interest_cell == ""
    # Lead object NOT mutated — historical interest still readable.
    assert lead.event_interest == "ზრდასრულთა საღამოები"


def test_parent_row_preserves_legitimate_event_interest():
    """A PARENT lead whose event_interest happens to be empty or
    contain camp-flavoured text passes through unchanged."""
    lead = Lead(
        sender_id="s2",
        platform="instagram",
        segment="PARENT",
        name="ნანა",
        phone="555111222",
        child_age="12",
        event_interest="",  # empty — typical PARENT
    )
    row = sheets_service._lead_to_row(lead, lead_id=2)
    assert row[10] == ""

    lead2 = Lead(
        sender_id="s3",
        platform="instagram",
        segment="PARENT",
        event_interest="ფონეტიკის სავარჯიშოები",  # camp-flavoured
    )
    row2 = sheets_service._lead_to_row(lead2, lead_id=3)
    assert row2[10] == "ფონეტიკის სავარჯიშოები"


def test_adult_row_event_interest_unchanged():
    """Critical regression — ADULT row keeps adult vocabulary."""
    lead = Lead(
        sender_id="s4",
        platform="instagram",
        segment="ADULT",
        name="თამარი",
        phone="595999733",
        event_interest="ზრდასრულთა საღამოები",
    )
    row = sheets_service._lead_to_row(lead, lead_id=4)
    assert row[10] == "ზრდასრულთა საღამოები"


def test_unclear_row_event_interest_unchanged():
    """Non-PARENT segment passes through unchanged — defence
    against accidental scrub on routing edge cases."""
    lead = Lead(
        sender_id="s5",
        platform="instagram",
        segment="UNCLEAR",
        event_interest="ზრდასრულთა საღამოები",
    )
    row = sheets_service._lead_to_row(lead, lead_id=5)
    assert row[10] == "ზრდასრულთა საღამოები"


def test_scrub_helper_direct():
    parent_lead = Lead(
        sender_id="s6", platform="instagram", segment="PARENT",
        event_interest="ზრდასრულთა საღამოები",
    )
    assert sheets_service._scrub_event_interest_for_segment(parent_lead) == ""

    adult_lead = Lead(
        sender_id="s7", platform="instagram", segment="ADULT",
        event_interest="ზრდასრულთა საღამოები",
    )
    assert (
        sheets_service._scrub_event_interest_for_segment(adult_lead)
        == "ზრდასრულთა საღამოები"
    )


# =========================================================================
# PART 2 — BUG 2 — Adult intro followup detection
# =========================================================================


def _adult_lead() -> Lead:
    return Lead(sender_id="s_adult", platform="instagram", segment="ADULT")


def test_bare_intro_with_period_separator_gets_followup():
    """gpt-5.4-mini sometimes uses a period after „გასაგებია" —
    the previous heuristic only had the comma form."""
    lead = _adult_lead()
    out = _ensure_adult_intro_followup(
        "გასაგებია. ზრდასრულთა ღონისძიებებზე დაგეხმარებით.", lead,
    )
    assert "?" in out
    assert out.startswith("გასაგებია")


def test_bare_intro_with_emdash_separator_gets_followup():
    lead = _adult_lead()
    out = _ensure_adult_intro_followup(
        "გასაგებია — ზრდასრულთა ღონისძიებებზე დაგეხმარებით.", lead,
    )
    assert "?" in out


def test_any_short_response_ending_dagexmarebit_gets_followup():
    """The catch-all: short response + ends with „დაგეხმარებით." →
    always appends. This is the LIVE-bug pattern."""
    lead = _adult_lead()
    out = _ensure_adult_intro_followup(
        "ზრდასრულთა ღონისძიებებზე დაგეხმარებით.", lead,
    )
    assert "?" in out
    assert out.startswith("ზრდასრულთა")


def test_kulturul_saghamo_ending_dagexmarebit_gets_followup():
    lead = _adult_lead()
    out = _ensure_adult_intro_followup(
        "კულტურულ საღამოებზე დაგეხმარებით.", lead,
    )
    assert "?" in out


def test_response_with_question_mark_unchanged():
    """Defence — when LLM already asked something, don't pile on."""
    lead = _adult_lead()
    text = (
        "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
        "რამდენი წლის ბრძანდებით?"
    )
    out = _ensure_adult_intro_followup(text, lead)
    assert out == text


def test_long_response_unchanged():
    """A long LLM answer is treated as a real reply, not a stub."""
    lead = _adult_lead()
    long = (
        "ჩვენი კულტურული საღამოები 13 წლის ასაკიდან არის ღია "
        "ფართო თემატური ღონისძიებების ფორმატით — ლიტერატურა, "
        "მუსიკა, დისკუსიები — და თითოეული საღამო ცალკე ბილეთით "
        "ფასდება სხვადასხვა ჟანრის მიხედვით. დაგეხმარებით."
    )
    assert len(long) > 120
    out = _ensure_adult_intro_followup(long, lead)
    assert out == long


def test_empty_response_unchanged():
    assert _ensure_adult_intro_followup("", _adult_lead()) == ""


def test_ends_with_dagexmarebit_helper():
    assert _ends_with_dagexmarebit("ღონისძიებებზე დაგეხმარებით.") is True
    assert _ends_with_dagexmarebit("ღონისძიებებზე დაგეხმარებით") is True
    assert _ends_with_dagexmarebit("რამდენი წლის ბრძანდებით?") is False
    assert _ends_with_dagexmarebit("") is False


# =========================================================================
# PART 3 — BUG 3A — Verification phrase routing
# =========================================================================


def test_user_requested_verification_helper():
    assert _user_requested_verification("კარგად შეამოწმე თავისუფალია?") is True
    assert _user_requested_verification("ნამდვილად თავისუფალია?") is True
    assert _user_requested_verification("დარწმუნებული ხარ?") is True
    assert _user_requested_verification("ზუსტი ინფორმაციაა?") is True
    assert _user_requested_verification("გადაამოწმე, თუ შეგიძლია") is True
    assert _user_requested_verification("კი, ვადასტურებ") is False
    assert _user_requested_verification("") is False


def _book_executor(user_message: str, *, monkeypatch) -> ParentToolExecutor:
    import app.flows.parent_flow as parent_flow
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(
        parent_tool_executor, "now_tbilisi", lambda: FIXED_NOW,
    )
    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )

    conv = Conversation(sender_id="s_book", platform="instagram")
    lead = Lead(
        sender_id="s_book",
        platform="instagram",
        segment="PARENT",
        name="ნანა",
        phone="555111222",
        child_age="12",
    )
    return ParentToolExecutor(
        conversation=conv,
        lead=lead,
        sender_id="s_book",
        platform="instagram",
        user_message=user_message,
    )


def _book_args() -> dict:
    return {
        "name": "ნანა",
        "phone": "555111222",
        "child_age": "12",
        "datetime_iso": FUTURE_SLOT_ISO,
        "user_confirmed_datetime": True,
    }


def test_verification_phrase_blocks_book_consultation(monkeypatch):
    exe = _book_executor("კარგად შეამოწმე თავისუფალია?", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is False
    assert result["reason"] == "verification_requested"
    assert result.get("next_action") == "check_consultation_slot"
    assert exe.lead.calendly_booked is False


def test_namdvilad_tavisuplaia_blocks_book(monkeypatch):
    exe = _book_executor("ნამდვილად თავისუფალია?", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is False
    assert result["reason"] == "verification_requested"


def test_darcmunebuli_xar_blocks_book(monkeypatch):
    exe = _book_executor("დარწმუნებული ხარ?", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is False
    assert result["reason"] == "verification_requested"


def test_no_verification_phrase_book_proceeds(monkeypatch):
    """Regression — a normal confirmation reaches the booking layer."""
    import app.flows.parent_flow as parent_flow

    def fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_test_123"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    exe = _book_executor("კი, ვადასტურებ", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is True
    assert "booked_date" in result


# =========================================================================
# PART 4 — BUG 3B — Backend booking success/failure enforcement
# =========================================================================


def test_book_slot_returns_false_yields_failure(monkeypatch):
    import app.flows.parent_flow as parent_flow

    monkeypatch.setattr(
        parent_flow, "_book_selected_slot", lambda c, l, s: False,
    )
    exe = _book_executor("კი, ვადასტურებ", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is False
    assert result["reason"] == "calendar_error"
    assert result.get("error") == "calendar_booking_failed"
    assert result.get("manager_handoff_required") is True


def test_book_slot_raises_yields_failure_and_sentry(monkeypatch):
    import app.flows.parent_flow as parent_flow

    captured: list[tuple] = []
    monkeypatch.setattr(
        parent_tool_executor.sentry_service,
        "capture_exception",
        lambda exc, context=None: captured.append((exc, context)),
    )

    def boom(c, l, s):
        raise RuntimeError("boom from book_slot")

    monkeypatch.setattr(parent_flow, "_book_selected_slot", boom)
    exe = _book_executor("კი, ვადასტურებ", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is False
    assert result["reason"] == "calendar_error"
    assert result.get("error") == "calendar_booking_failed"
    # Sentry captured the original exception + safe context.
    assert len(captured) == 1
    exc, ctx = captured[0]
    assert isinstance(exc, RuntimeError)
    assert ctx is not None
    assert ctx["area"] == "booking"
    assert ctx["slot"] == FUTURE_SLOT_ISO
    assert "***" in ctx["sender"]  # masked
    assert "ნანა" not in str(ctx.get("sender", ""))


def test_book_slot_true_but_no_event_id_yields_failure(monkeypatch):
    """The silent-Calendar-failure mode the live bug exposed: Google
    API returns HTTP 200 but the body has no `id`, so book_slot
    returns True (current behaviour) without populating
    `lead.calendar_event_id`. The executor must NOT report success."""
    import app.flows.parent_flow as parent_flow

    captured: list[tuple] = []
    monkeypatch.setattr(
        parent_tool_executor.sentry_service,
        "capture_exception",
        lambda exc, context=None: captured.append((exc, context)),
    )

    def silent_fail(c, l, s):
        l.calendly_booked = True  # half-written success state
        l.booked_datetime_iso = s["datetime_iso"]
        l.status = "Booked"
        l.calendar_event_id = ""  # no event_id — silent failure
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", silent_fail)
    exe = _book_executor("კი, ვადასტურებ", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is False
    assert result["reason"] == "calendar_booking_failed"
    assert result.get("error") == "calendar_booking_failed"
    assert result.get("manager_handoff_required") is True
    # Lead state rolled back so the fake-booking guard later in the
    # pipeline never sees stale `calendly_booked=True`.
    assert exe.lead.calendly_booked is False
    assert exe.lead.booked_datetime_iso == ""
    assert exe.lead.calendar_event_id == ""
    assert exe.lead.status != "Booked"
    # Sentry captured with the synthetic RuntimeError.
    assert len(captured) == 1
    exc, ctx = captured[0]
    assert ctx["area"] == "booking"
    assert ctx["reason"] == "calendar_booking_failed"


def test_book_slot_success_path_returns_success(monkeypatch):
    """Regression — the happy path still confirms."""
    import app.flows.parent_flow as parent_flow

    def good_book(c, l, s):
        l.calendly_booked = True
        l.calendar_event_id = "evt_real_456"
        l.booked_datetime_iso = s["datetime_iso"]
        l.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", good_book)
    exe = _book_executor("კი, ვადასტურებ", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is True
    assert result["booked_datetime_iso"] == FUTURE_SLOT_ISO
    # The per-turn success flag is set so the engine's sanitiser
    # accepts a „ჩაგინიშნეთ" reply.
    assert parent_tool_executor.book_consultation_success_for_conversation.get(
        "s_book"
    ) is True


def test_failed_booking_clears_per_turn_success_flag(monkeypatch):
    """Defence in depth — even if a previous turn briefly set
    success=True, a failure on this call drops it back to False so
    the final fake-booking guard cannot leak a stale confirmation."""
    import app.flows.parent_flow as parent_flow

    parent_tool_executor.book_consultation_success_for_conversation["s_book"] = True
    monkeypatch.setattr(
        parent_flow, "_book_selected_slot", lambda c, l, s: False,
    )
    exe = _book_executor("კი, ვადასტურებ", monkeypatch=monkeypatch)
    result = exe._book_consultation(_book_args())
    assert result["success"] is False
    assert parent_tool_executor.book_consultation_success_for_conversation.get(
        "s_book"
    ) is False
