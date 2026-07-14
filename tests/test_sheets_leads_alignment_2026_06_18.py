"""P0 data-integrity — Leads sheet row alignment (2026-06-18).

Bug: during a NORMAL consultation booking the Google Sheets "Leads" row
was written under the WRONG / shifted columns. Root cause: `save_lead`
appended via `worksheet.append_row(row, value_input_option="USER_ENTERED")`,
which gspread sends to the Sheets `values.append` API with an UNBOUNDED
sheet range (`'Leads'`). The API then relies on "logical table"
auto-detection to choose both the target row AND the start column; on a
live sheet whose data region was not cleanly anchored at column A, the new
row landed under the detected table's first column (to the right of A),
shifting every value under the wrong header.

Fix: write the Leads row to an EXPLICIT, A-anchored full-row range
(`A{n}:Q{n}`) via `worksheet.update(...)`, the same deterministic pattern
already used for the header row and the events tab — immune to
table-detection heuristics. The row builder (`_lead_to_row`) was already
correct (17 values in header order, ID first); only the WRITE mechanism
was non-deterministic.

These tests use a fully in-memory FakeWorksheet — no real Google Sheets,
Calendar, Meta, email, or Redis.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.agent.tools.parent_tools import TOOL_BOOK_CONSULTATION
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import calendar_service, notification_service, sheets_service


TBILISI = ZoneInfo("Asia/Tbilisi")
SAT = (2030, 6, 8)   # Saturday
WED = (2030, 6, 5)   # Wednesday (weekday)


def _iso(ymd: tuple[int, int, int], hour: int) -> str:
    return datetime(ymd[0], ymd[1], ymd[2], hour, 0, tzinfo=TBILISI).isoformat()


class FakeWorksheet:
    """Records every write so tests can assert range + values. Mimics just
    enough gspread surface for the Leads code paths."""

    def __init__(self, rows: list[list] | None = None):
        self._rows = [list(r) for r in (rows or [])]
        self.updates: list[tuple] = []       # (range_name, values, kwargs)
        self.appended: list[tuple] = []      # (row, kwargs)
        self.cell_updates: list[tuple] = []  # (row, col, value)

    def get_all_values(self):
        return [list(r) for r in self._rows]

    def row_values(self, idx):
        return list(self._rows[idx - 1]) if 1 <= idx <= len(self._rows) else []

    def col_values(self, col_idx):
        return [
            (r[col_idx - 1] if col_idx - 1 < len(r) else "")
            for r in self._rows
        ]

    def update(self, *args, **kwargs):
        range_name = kwargs.get("range_name")
        values = kwargs.get("values")
        if range_name is None and values is None and args:
            # legacy positional (range_name, values) or new (values, range_name)
            a0 = args[0]
            a1 = args[1] if len(args) > 1 else None
            if isinstance(a0, str):
                range_name, values = a0, a1
            else:
                values, range_name = a0, a1
        self.updates.append((range_name, values, kwargs))
        return {}

    def append_row(self, row, **kwargs):
        self.appended.append((row, kwargs))
        self._rows.append(list(row))
        return {}

    def update_cell(self, row, col, value):
        self.cell_updates.append((row, col, value))
        while len(self._rows) < row:
            self._rows.append([])
        r = self._rows[row - 1]
        while len(r) < col:
            r.append("")
        r[col - 1] = value
        return {}


def _header_only_sheet() -> FakeWorksheet:
    return FakeWorksheet(rows=[list(sheets_service.HEADERS)])


# =========================================================================
# Test 1 — row builder matches header order exactly (ID first, no shift).
# =========================================================================


def test_lead_to_row_matches_header_order():
    lead = Lead(
        sender_id="pb-15a", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="595999733", child_age="14",
        calendly_booked=True, status="Booked",
    )
    values = sheets_service._lead_to_row(lead, 17)

    assert len(values) == len(sheets_service.HEADERS) == 17
    # Positional alignment — no leading blank, no one-column shift.
    assert values[0] == 17               # A: ID
    assert values[1] == "pb-15a"         # B: Sender ID
    assert values[2] == "instagram"      # C: Platform
    assert values[3] == "PARENT"         # D: Segment
    assert values[4] == "ნიკოლოზი"        # E: Name
    assert values[5] == "595999733"      # F: Phone
    assert values[6] == "14"             # G: Child Age
    assert values[0] != "pb-15a", "ID column must hold the numeric id, not sender_id"

    row = dict(zip(sheets_service.HEADERS, values))
    assert row["ID"] == 17
    assert row["Sender ID"] == "pb-15a"
    assert row["Status"] == "Booked"            # N
    assert row["Consultation Booked"] == "TRUE"  # L


# =========================================================================
# Test 2 — append writes to an explicit A-anchored full-row range.
# =========================================================================


def test_save_lead_writes_a_anchored_full_row_range(monkeypatch):
    fake = _header_only_sheet()
    monkeypatch.setattr(sheets_service, "_worksheet", lambda: fake)

    lead = Lead(
        sender_id="pb-15a", platform="instagram", segment="PARENT",
        name="ნიკოლოზი", phone="595999733", child_age="14",
        calendly_booked=True, status="Booked",
    )
    assert sheets_service.save_lead(lead) is True

    # The fix writes via an explicit, A-anchored range — never the
    # heuristic unbounded append_row.
    assert not fake.appended, "must not use the unbounded append_row path"
    assert fake.updates, "expected an explicit-range update write"
    range_name, values, _kw = fake.updates[-1]
    assert range_name == "A2:Q2", f"row must be A-anchored, got {range_name!r}"

    written = values[0]
    assert len(written) == 17
    row = dict(zip(sheets_service.HEADERS, written))
    assert row["ID"] == 1                       # _next_id over header-only sheet
    assert row["Sender ID"] == "pb-15a"
    assert row["Platform"] == "instagram"
    assert row["Segment"] == "PARENT"
    assert row["Name"] == "ნიკოლოზი"
    assert row["Phone"] == "595999733"
    assert row["Child Age"] == "14"
    assert row["Consultation Booked"] == "TRUE"
    assert row["Status"] == "Booked"


def test_save_lead_appends_after_existing_rows(monkeypatch):
    """Next row index is computed from existing data, not hardcoded."""
    rows = [list(sheets_service.HEADERS)]
    rows.append([1, "old-1", "instagram", "PARENT"] + [""] * 13)
    rows.append([2, "old-2", "facebook", "PARENT"] + [""] * 13)
    fake = FakeWorksheet(rows=rows)
    monkeypatch.setattr(sheets_service, "_worksheet", lambda: fake)

    lead = Lead(sender_id="pb-new", platform="instagram", segment="PARENT",
                name="ანა", phone="595111222", child_age="12")
    assert sheets_service.save_lead(lead) is True
    range_name, _values, _kw = fake.updates[-1]
    assert range_name == "A4:Q4"  # header + 2 data rows → next is row 4


# =========================================================================
# Test 3 + 4 — Saturday and weekday bookings use the same aligned path.
# =========================================================================


def _mock_booking_externals(monkeypatch, fake_ws):
    monkeypatch.setattr(sheets_service, "_worksheet", lambda: fake_ws)
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda *a, **k: True)

    def _book(**kwargs):
        lead = kwargs.get("lead")
        if lead is not None:
            lead.calendar_event_id = "evt_align_test"
        return True

    monkeypatch.setattr(calendar_service, "book_slot", _book)
    monkeypatch.setattr(parent_flow, "_generate_summary", lambda conv: "ტესტ-რეზიუმე")
    monkeypatch.setattr(
        notification_service, "send_manager_notification", lambda *a, **k: None,
    )


def _book_through_executor(monkeypatch, sender_id: str, datetime_iso: str):
    parent_tool_executor.reset_state()
    conv = Conversation(sender_id=sender_id, platform="instagram")
    conv.history.append({"role": "user", "content": "ჩამიწერეთ კონსულტაციაზე"})
    lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = lead
    executor = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id=sender_id, platform="instagram",
    )
    return executor.execute(TOOL_BOOK_CONSULTATION, {
        "name": "ნიკოლოზი",
        "phone": "595999733",
        "datetime_iso": datetime_iso,
        "child_age": "14",
        "user_confirmed_datetime": True,
    })


def _assert_aligned_booking_write(fake: FakeWorksheet):
    assert not fake.appended, "booking must not use the unbounded append_row path"
    assert fake.updates, "booking must write the lead row"
    range_name, values, _kw = fake.updates[-1]
    assert range_name == "A2:Q2"
    row = dict(zip(sheets_service.HEADERS, values[0]))
    assert row["Sender ID"]  # column B holds the sender id, not the ID
    assert row["Consultation Booked"] == "TRUE"
    assert row["Status"] == "Booked"
    assert row["Name"] == "ნიკოლოზი"
    assert row["Phone"] == "595999733"
    assert row["Child Age"] == "14"
    return range_name


def test_saturday_booking_writes_aligned_row(monkeypatch, camp_registration_open):
    fake = _header_only_sheet()
    _mock_booking_externals(monkeypatch, fake)
    result = _book_through_executor(monkeypatch, "sat-align", _iso(SAT, 12))
    assert result["success"] is True
    _assert_aligned_booking_write(fake)


def test_weekday_booking_writes_aligned_row(monkeypatch, camp_registration_open):
    fake = _header_only_sheet()
    _mock_booking_externals(monkeypatch, fake)
    result = _book_through_executor(monkeypatch, "wed-align", _iso(WED, 12))
    assert result["success"] is True
    _assert_aligned_booking_write(fake)


def test_saturday_and_weekday_use_identical_write_range(monkeypatch, camp_registration_open):
    fake_sat = _header_only_sheet()
    _mock_booking_externals(monkeypatch, fake_sat)
    assert _book_through_executor(monkeypatch, "sat-x", _iso(SAT, 12))["success"]
    sat_range = fake_sat.updates[-1][0]

    fake_wed = _header_only_sheet()
    _mock_booking_externals(monkeypatch, fake_wed)
    assert _book_through_executor(monkeypatch, "wed-x", _iso(WED, 12))["success"]
    wed_range = fake_wed.updates[-1][0]

    assert sat_range == wed_range == "A2:Q2", (
        "Saturday must use the exact same aligned Sheets range as weekday"
    )


# =========================================================================
# Test 5 — update/upsert targets the correct row and correct A-based columns.
# =========================================================================


def test_update_lead_targets_correct_row_and_columns(monkeypatch):
    rows = [list(sheets_service.HEADERS)]
    rows.append([1, "other-sender", "instagram", "PARENT"] + [""] * 13)
    rows.append([2, "pb-15a", "instagram", "PARENT"] + [""] * 13)  # row 3
    fake = FakeWorksheet(rows=rows)
    monkeypatch.setattr(sheets_service, "_worksheet", lambda: fake)

    assert sheets_service.update_lead(
        "pb-15a", {"status": "Rescheduled", "name": "ნინო"},
    ) is True

    # Column indices are A-based and stable; no shift.
    assert sheets_service.COLUMN_INDEX["Status"] == 14   # N
    assert sheets_service.COLUMN_INDEX["Name"] == 5      # E
    assert (3, 14, "Rescheduled") in fake.cell_updates
    assert (3, 5, "ნინო") in fake.cell_updates
    # Must not have touched the wrong (other-sender) row 2.
    assert all(r != 2 for (r, _c, _v) in fake.cell_updates)


# =========================================================================
# Test 6 — under-age manager handoff dispatches but NEVER writes Sheets.
# =========================================================================


def test_underage_manager_handoff_does_not_write_sheets(monkeypatch):
    parent_tool_executor.reset_state()
    notified: list = []
    monkeypatch.setattr(
        notification_service, "notify_manager_handoff",
        lambda lead, reason: (notified.append((lead, reason)), True)[1],
    )
    # Any Sheets write on this path is a regression.
    for fn in ("save_lead", "create_lead", "append_lead", "update_lead"):
        monkeypatch.setattr(
            sheets_service, fn,
            lambda *a, **k: pytest.fail(f"under-age handoff must not call sheets_service.{fn}"),
        )

    conv = Conversation(sender_id="underage-1", platform="instagram")
    # Name already known on the lead so the handoff has both name + phone
    # once the phone arrives in the message → it dispatches (rather than
    # asking for the missing field).
    lead = Lead(sender_id="underage-1", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", child_age="8")
    conv.lead = lead

    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მენეჯერთან დამაკავშირეთ 595999733",
    )

    assert out is not None, "under-age handoff should produce a response"
    assert notified, "manager handoff notification must be dispatched"
    # The whole point: this path must never write the Leads sheet (the
    # monkeypatched sheets_service.* would pytest.fail if it did).
