"""Live QA Session 8 Patch (2026-06-07) — Booking confirmation
shortening + Sheets reschedule row consistency.

Covers:

  Bug 1 — Strip awkward post-booking CTA filler:
          „თუ კიდევ რაიმე გაგიჩნდებათ, …",
          „თუ კიდევ რაიმე დაგაინტერესებთ, …",
          „თუ დამატებითი კითხვა გაქვთ, …".
          Auto-append of the help CTA after the new-booking-CTA
          stripper is removed.
  Bug 2 — Reschedule path: old Sheets row is updated to
          ``Status="Rescheduled"`` (oldest sender_id row whose
          Status is ``"Booked"``). New Sheets row stays ``Booked``.
          Sheets-write failure is logged + Sentry-captured but
          never rolls back the Calendar success.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.agent.llm import parent_llm_engine
from app.agent.llm.parent_llm_engine import sanitise_response_wording
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, sheets_service
from app.services.session_key_service import conversation_cache_key


TBILISI = ZoneInfo("Asia/Tbilisi")


@pytest.fixture
def camp_registration_open(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_registration_status", lambda: "open",
    )


# =========================================================================
# Bug 1 — booking-confirmation sanitizer
# =========================================================================


def _booked_conv(
    booked_dt_iso: str = "2026-12-10T11:00:00+04:00",
    state: str = "DONE",
) -> Conversation:
    lead = Lead(
        sender_id="s_session8", platform="messenger", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
        calendly_booked=True,
        booked_datetime_iso=booked_dt_iso,
        calendar_event_id="evt_old",
        status="Booked",
    )
    conv = Conversation(
        sender_id="s_session8", platform="messenger", segment="PARENT",
        state=state,
    )
    conv.lead = lead
    return conv


def test_sanitizer_collapses_doubled_tu_mixed_verbs():
    """Live observation: „თუ კიდევ რაიმე დაგაინტერესებთ, თუ კიდევ
    რაიმე გაგიჩნდებათ, მომწერეთ და დაგეხმარებით." → collapse to a
    single „თუ …" clause."""
    raw = (
        "მადლობა თქვენ. თუ კიდევ რაიმე დაგაინტერესებთ, თუ კიდევ "
        "რაიმე გაგიჩნდებათ, მომწერეთ და დაგეხმარებით."
    )
    out = sanitise_response_wording(raw)
    # The doubled clause is collapsed.
    assert out.count("თუ კიდევ რაიმე") == 1


def test_sanitizer_collapses_doubled_tu_same_verb():
    raw = (
        "კარგი. თუ რამე გაგიჩნდებათ, თუ კიდევ რაიმე გაგიჩნდებათ, "
        "შემეხმიანეთ."
    )
    out = sanitise_response_wording(raw)
    # Both clauses collapsed into one.
    assert out.count("გაგიჩნდებათ") == 1


def test_stripper_drops_tu_kidev_raime_gagichndebat_when_booked():
    conv = _booked_conv()
    raw = (
        "თქვენი ჯავშანი 10 ივნისს, 11:00 საათზე.\n\n"
        "თუ კიდევ რაიმე გაგიჩნდებათ, მომწერეთ და დაგეხმარებით."
    )
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert "თუ კიდევ რაიმე გაგიჩნდებათ" not in out
    assert "მომწერეთ და დაგეხმარებით" not in out
    assert "10 ივნისს" in out


def test_stripper_drops_tu_kidev_raime_dagainteresebt_when_booked():
    conv = _booked_conv()
    raw = (
        "თქვენი ჯავშანი 10 ივნისს, 11:00 საათზე.\n\n"
        "თუ კიდევ რაიმე დაგაინტერესებთ, მომწერეთ და დაგეხმარებით."
    )
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert "თუ კიდევ რაიმე დაგაინტერესებთ" not in out
    assert "მომწერეთ და დაგეხმარებით" not in out


def test_stripper_drops_help_cta_when_booked():
    conv = _booked_conv()
    raw = (
        "კონსულტაცია ჩანიშნულია.\n\n"
        "თუ დამატებითი კითხვა გაქვთ, მომწერეთ და დაგეხმარებით."
    )
    out = parent_flow._strip_consultation_cta_if_booked(conv, raw)
    assert "თუ დამატებითი კითხვა გაქვთ" not in out
    assert "კონსულტაცია ჩანიშნულია" in out


def test_trim_booking_success_drops_tu_kidev_raime(monkeypatch):
    from app.agent.tools.parent_tool_executor import (
        book_consultation_success_for_conversation,
    )
    conv = Conversation(
        sender_id="s_trim_8", platform="messenger", segment="PARENT",
    )
    cache_key = conversation_cache_key(conv)
    book_consultation_success_for_conversation[cache_key] = True
    raw = (
        "10 ივნისს, 11:00 საათზე კონსულტაცია ჩაგინიშნეთ. "
        "თუ კიდევ რაიმე გაგიჩნდებათ, მომწერეთ და დაგეხმარებით."
    )
    out = parent_flow._trim_booking_success_response(conv, raw)
    assert "თუ კიდევ რაიმე" not in out
    assert "კონსულტაცია ჩაგინიშნეთ" in out
    book_consultation_success_for_conversation.pop(cache_key, None)


def test_booking_confirmation_first_booking_is_concise(camp_registration_open):
    """End-to-end against the deterministic pending-commit path: the
    booking-success response must contain date/time + ჩაგინიშნეთ +
    მენეჯერი დაგიკავშირდებათ — and NOTHING else."""
    import app.services.calendar_service as calendar_service
    import app.services.sheets_service as sheets_mod

    conv = Conversation(
        sender_id="s_conf", platform="messenger", segment="PARENT",
    )
    lead = Lead(
        sender_id="s_conf", platform="messenger", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
    )
    conv.lead = lead
    conv.pending_booking = {
        "requested_datetime_iso": "2026-12-15T11:00:00+04:00",
        "requested_date_text": "15 დეკემბერი",
        "requested_time_text": "11:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": [],
    }

    def fake_book(c, l, slot):
        l.calendly_booked = True
        l.calendar_event_id = "evt_new"
        l.booked_datetime_iso = slot["datetime_iso"]
        l.status = "Booked"
        return True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(parent_flow, "TBILISI_TZ", TBILISI)
        mp.setattr(calendar_service, "check_slot_available", lambda dt: True)
        mp.setattr(parent_flow, "_book_selected_slot", fake_book)
        mp.setattr(sheets_mod, "update_lead", lambda sender_id, payload: True)
        response = parent_flow._maybe_commit_pending_booking_engine(conv, "კი")

    assert response is not None
    # The Georgian uses „კონსულტაცია <date>, <time> საათზე ჩაგინიშნეთ"
    # so the two key tokens („კონსულტაცია" + „ჩაგინიშნეთ") are
    # asserted independently.
    assert "კონსულტაცია" in response
    assert "ჩაგინიშნეთ" in response
    assert "მენეჯერი დაგიკავშირდებათ" in response
    assert "თუ კიდევ რაიმე" not in response
    assert "თუ დამატებითი კითხვა" not in response
    assert "მომწერეთ და დაგეხმარებით" not in response
    assert "საჯაროდ არ გამოქვეყნდება" not in response


def test_booking_confirmation_reschedule_includes_old_cancel_line(camp_registration_open):
    """Reschedule confirmation must say „ძველი კონსულტაცია გაუქმებულია."
    and stay concise."""
    import app.services.calendar_service as calendar_service
    import app.services.sheets_service as sheets_mod

    conv = Conversation(
        sender_id="s_rs", platform="messenger", segment="PARENT",
        state="DONE",
    )
    lead = Lead(
        sender_id="s_rs", platform="messenger", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
        calendly_booked=True,
        booked_datetime_iso="2026-12-10T11:00:00+04:00",
        calendar_event_id="evt_old_rs", status="Booked",
    )
    conv.lead = lead
    conv.pending_booking = {
        "requested_datetime_iso": "2026-12-10T19:00:00+04:00",
        "requested_date_text": "10 დეკემბერი",
        "requested_time_text": "19:00",
        "user_confirmed_datetime": True,
        "source": "reschedule",
        "old_event_id": "evt_old_rs",
        "old_booked_datetime_iso": "2026-12-10T11:00:00+04:00",
        "missing_fields": [],
    }

    def fake_book(c, l, slot):
        l.calendly_booked = True
        l.calendar_event_id = "evt_new_rs"
        l.booked_datetime_iso = slot["datetime_iso"]
        l.status = "Booked"
        return True

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(parent_flow, "TBILISI_TZ", TBILISI)
        mp.setattr(calendar_service, "check_slot_available", lambda dt: True)
        mp.setattr(calendar_service, "cancel_calendar_event", lambda eid: True)
        mp.setattr(parent_flow, "_book_selected_slot", fake_book)
        mp.setattr(
            sheets_mod, "mark_old_booking_rescheduled",
            lambda sender_id, **kw: (True, "ok"),
        )
        mp.setattr(sheets_mod, "update_lead", lambda sender_id, p: True)
        response = parent_flow._maybe_commit_pending_booking_engine(conv, "კი")

    assert response is not None
    assert "ჩაგინიშნეთ" in response
    assert "ძველი კონსულტაცია გაუქმებულია" in response
    assert "მენეჯერი დაგიკავშირდებათ" in response
    # No filler trailing CTA.
    assert "თუ კიდევ რაიმე" not in response
    assert "თუ დამატებითი კითხვა" not in response


# =========================================================================
# Bug 2 — Sheets `mark_old_booking_rescheduled` helper
# =========================================================================


class _FakeWorksheet:
    """Minimal sheet stand-in: pretends to have N rows + a header.

    Stores columns as parallel lists; supports the methods the helper
    calls (``col_values``, ``update_cell``).
    """

    def __init__(self, sender_col: list[str], status_col: list[str]) -> None:
        self.sender_col = list(sender_col)
        self.status_col = list(status_col)
        self.updates: list[tuple[int, int, str]] = []

    def col_values(self, column_index: int) -> list[str]:
        # Use the sheets_service.HEADERS mapping for "Sender ID" / "Status".
        if column_index == sheets_service.COLUMN_INDEX["Sender ID"]:
            return list(self.sender_col)
        if column_index == sheets_service.COLUMN_INDEX["Status"]:
            return list(self.status_col)
        return []

    def update_cell(self, row_index: int, column_index: int, value: str) -> None:
        self.updates.append((row_index, column_index, str(value)))
        # Reflect the change in the in-memory column so re-reads see it.
        if column_index == sheets_service.COLUMN_INDEX["Status"]:
            self.status_col[row_index - 1] = str(value)


@pytest.fixture
def fake_worksheet(monkeypatch):
    """Provide a fresh _FakeWorksheet per test and patch _worksheet()."""
    ws_box: dict[str, _FakeWorksheet] = {}

    def _make(sender_col, status_col):
        ws = _FakeWorksheet(sender_col, status_col)
        ws_box["ws"] = ws
        monkeypatch.setattr(sheets_service, "_worksheet", lambda: ws)
        return ws

    return _make


def test_mark_old_booking_rescheduled_updates_oldest_booked_row(
    fake_worksheet,
):
    # Header row + 3 rows: discovery row (row 2), old booking (row 3),
    # new booking (row 4). The helper must target row 3.
    ws = fake_worksheet(
        sender_col=["Sender ID", "X", "X", "X"],
        status_col=["Status", "New", "Booked", "Booked"],
    )
    ok, detail = sheets_service.mark_old_booking_rescheduled("X")
    assert ok is True
    assert detail == "ok"
    assert ws.status_col == ["Status", "New", "Rescheduled", "Booked"]


def test_mark_old_booking_rescheduled_only_one_booked_row(fake_worksheet):
    """When only one Booked row exists (e.g. new create_lead failed)
    the helper still updates it — the OLD calendar event is cancelled
    so the row must NOT remain ``Booked``."""
    ws = fake_worksheet(
        sender_col=["Sender ID", "X", "X"],
        status_col=["Status", "New", "Booked"],
    )
    ok, detail = sheets_service.mark_old_booking_rescheduled("X")
    assert ok is True
    assert detail == "ok"
    assert ws.status_col == ["Status", "New", "Rescheduled"]


def test_mark_old_booking_rescheduled_skips_unrelated_sender(fake_worksheet):
    ws = fake_worksheet(
        sender_col=["Sender ID", "Y", "Y", "X"],
        status_col=["Status", "Booked", "Booked", "Booked"],
    )
    ok, detail = sheets_service.mark_old_booking_rescheduled("X")
    assert ok is True
    # Only row 4 (sender X, Booked) is updated.
    assert ws.status_col == ["Status", "Booked", "Booked", "Rescheduled"]


def test_mark_old_booking_rescheduled_returns_false_when_no_booked_row(
    fake_worksheet,
):
    ws = fake_worksheet(
        sender_col=["Sender ID", "X", "X"],
        status_col=["Status", "New", "Qualified"],
    )
    ok, detail = sheets_service.mark_old_booking_rescheduled("X")
    assert ok is False
    assert detail == "no_booked_row"
    # Nothing written.
    assert ws.updates == []


def test_mark_old_booking_rescheduled_handles_worksheet_failure(
    fake_worksheet, monkeypatch,
):
    fake_worksheet(
        sender_col=["Sender ID", "X"],
        status_col=["Status", "Booked"],
    )
    monkeypatch.setattr(
        sheets_service, "_worksheet",
        MagicMock(side_effect=RuntimeError("network down")),
    )
    ok, detail = sheets_service.mark_old_booking_rescheduled("X")
    assert ok is False
    assert detail == "worksheet_unavailable"


def test_mark_old_booking_rescheduled_log_masks_sender(
    fake_worksheet, caplog,
):
    fake_worksheet(
        sender_col=["Sender ID", "1234567890XYZ", "1234567890XYZ"],
        status_col=["Status", "New", "Booked"],
    )
    import logging
    with caplog.at_level(logging.INFO, logger="app.services.sheets_service"):
        sheets_service.mark_old_booking_rescheduled("1234567890XYZ")
    full = "\n".join(rec.message for rec in caplog.records)
    # Raw sender id MUST NOT leak.
    assert "1234567890XYZ" not in full
    # Masked form is present.
    assert "123456***" in full


# =========================================================================
# Bug 2 — reschedule executor wires through to mark_old_booking_rescheduled
# =========================================================================


def _reschedule_lead_conv() -> tuple[Conversation, Lead]:
    lead = Lead(
        sender_id="s_rs_e2e", platform="messenger", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
        calendly_booked=True,
        booked_datetime_iso="2026-12-10T11:00:00+04:00",
        calendar_event_id="evt_old_e2e",
        status="Booked",
    )
    conv = Conversation(
        sender_id="s_rs_e2e", platform="messenger", segment="PARENT",
        state="DONE", lead=lead,
    )
    return conv, lead


def test_reschedule_calls_mark_old_booking_rescheduled(monkeypatch, camp_registration_open):
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)

    def fake_book(c, l, slot):
        l.calendly_booked = True
        l.calendar_event_id = "evt_new_e2e"
        l.booked_datetime_iso = slot["datetime_iso"]
        l.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(calendar_service, "cancel_calendar_event", lambda eid: True)

    mark_mock = MagicMock(return_value=(True, "ok"))
    monkeypatch.setattr(sheets_service, "mark_old_booking_rescheduled", mark_mock)
    legacy_update = MagicMock(return_value=True)
    monkeypatch.setattr(sheets_service, "update_lead", legacy_update)

    conv, lead = _reschedule_lead_conv()
    exe = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id="s_rs_e2e", platform="messenger",
        user_message="კი მაწყობს",
    )
    result = exe._book_consultation({
        "name": "ლუკა",
        "phone": "595999733",
        "child_age": "11",
        "datetime_iso": "2026-12-10T19:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is True
    assert result["action"] == "reschedule"
    # New helper called.
    mark_mock.assert_called_once_with("s_rs_e2e", new_status="Rescheduled")
    # Legacy update_lead NOT called for the "Rescheduled" status — we
    # use the targeted helper instead.
    for call in legacy_update.call_args_list:
        args, kwargs = call
        if args and isinstance(args[1], dict):
            assert args[1].get("status") != "Rescheduled"


def test_reschedule_logs_warning_when_sheets_helper_fails(
    monkeypatch, caplog, camp_registration_open,
):
    import app.services.calendar_service as calendar_service
    import logging

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)

    def fake_book(c, l, slot):
        l.calendly_booked = True
        l.calendar_event_id = "evt_new_fail"
        l.booked_datetime_iso = slot["datetime_iso"]
        l.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(calendar_service, "cancel_calendar_event", lambda eid: True)
    monkeypatch.setattr(
        sheets_service, "mark_old_booking_rescheduled",
        lambda sender_id, **kw: (False, "write_failed"),
    )

    conv, lead = _reschedule_lead_conv()
    exe = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id="s_rs_fail", platform="messenger",
    )
    with caplog.at_level(
        logging.WARNING, logger="app.agent.tools.parent_tool_executor",
    ):
        result = exe._book_consultation({
            "name": "ლუკა",
            "phone": "595999733",
            "child_age": "11",
            "datetime_iso": "2026-12-10T19:00:00+04:00",
            "user_confirmed_datetime": True,
        })
    # Calendar success is preserved even though Sheets write failed.
    assert result["success"] is True
    assert result["action"] == "reschedule"
    # Warning log emitted, masked sender.
    full = "\n".join(rec.message for rec in caplog.records)
    assert "old booking reschedule status update failed" in full
    # Raw sender id NOT in log.
    assert "s_rs_fail" not in full


def test_reschedule_calendar_success_not_rolled_back_on_sheets_failure(
    monkeypatch, camp_registration_open,
):
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)

    cancelled: list[str] = []

    def fake_book(c, l, slot):
        l.calendly_booked = True
        l.calendar_event_id = "evt_new_keep"
        l.booked_datetime_iso = slot["datetime_iso"]
        l.status = "Booked"
        return True

    def fake_cancel(event_id):
        cancelled.append(event_id)
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(calendar_service, "cancel_calendar_event", fake_cancel)
    monkeypatch.setattr(
        sheets_service, "mark_old_booking_rescheduled",
        lambda sender_id, **kw: (False, "write_failed"),
    )

    conv, lead = _reschedule_lead_conv()
    exe = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id="s_rs_no_rollback", platform="messenger",
    )
    result = exe._book_consultation({
        "name": "ლუკა",
        "phone": "595999733",
        "child_age": "11",
        "datetime_iso": "2026-12-10T19:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is True
    assert lead.calendar_event_id == "evt_new_keep"
    assert lead.booked_datetime_iso == "2026-12-10T19:00:00+04:00"
    # Old Calendar event was cancelled (the patch's promise).
    assert cancelled == ["evt_old_e2e"]
