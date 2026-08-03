"""The Leads sheet must never lose a column because a flag is off.

`_ensure_headers` runs on every read and every write. It used to call
`worksheet.resize(cols=len(headers))`, and `_active_leads_headers()` is
flag-dependent: 18 columns with `USE_PER_PRODUCT_BOOKING` on („Program" in R),
17 with it off. `resize` deletes every cell beyond the new width in EVERY row,
so one call made while the flag was off wiped the Program value of every lead
in the sheet — reported by the operator on 2026-08-03 as the programs column
disappearing and an earlier lead's program vanishing when a later lead was
written with a different one.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.services import sheets_service as ss


class FakeWorksheet:
    def __init__(self, headers, col_count):
        self._headers = list(headers)
        self.col_count = col_count
        self.resized_to = None
        self.header_writes = []

    def row_values(self, _row):
        return list(self._headers)

    def resize(self, cols=None, rows=None):
        self.resized_to = cols
        self.col_count = cols
        # Mirror the real destruction so a shrink cannot pass unnoticed.
        self._headers = self._headers[:cols]

    def update(self, range_name, values, **_kw):
        self.header_writes.append((range_name, values))


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setattr(
        ss, "settings",
        dataclasses.replace(ss.settings, USE_PER_PRODUCT_BOOKING=False))


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(
        ss, "settings",
        dataclasses.replace(ss.settings, USE_PER_PRODUCT_BOOKING=True))


def test_flag_off_never_shrinks_a_wider_sheet(flag_off):
    """The regression: 18-column sheet + flag off must NOT drop column R."""
    ws = FakeWorksheet(ss.HEADERS + ["Program"], col_count=18)
    ss._ensure_headers(ws)
    assert ws.resized_to is None, "resize() shrank the sheet and deleted Program"
    assert ws.col_count == 18


def test_flag_on_still_grows_a_narrow_sheet(flag_on):
    ws = FakeWorksheet(ss.HEADERS, col_count=17)
    ss._ensure_headers(ws)
    assert ws.resized_to == 18
    assert ws.header_writes and ws.header_writes[0][0] == "A1:R1"


def test_matching_headers_touch_nothing(flag_on):
    ws = FakeWorksheet(ss.HEADERS + ["Program"], col_count=18)
    ss._ensure_headers(ws)
    assert ws.resized_to is None
    assert ws.header_writes == []


def test_header_row_is_still_rewritten_when_it_differs(flag_off):
    """A genuine rename must still land — only the shrink is gone."""
    stale = ["ID"] + ss.HEADERS[1:]
    stale[3] = "ძველი სათაური"
    ws = FakeWorksheet(stale, col_count=17)
    ss._ensure_headers(ws)
    assert ws.header_writes, "the header row was not corrected"
    assert ws.header_writes[0][1] == [ss.HEADERS]
