"""Adult-events section-level fallback gating (2026-07-07).

Live bug: after the operator DELETED the „fromula 1" adult event so
`adult_events.events: []`, `get_adult_events()` still synthesised a section-level
fallback event (`adult_events_default`) from the section's Maroon-5 fields — so a
deleted event could reappear (and would surface if its section-level date were
future). It was harmless only because the Maroon-5 stream date is now past.

Fix: the section-level fallback fires ONLY when the `events` key is COMPLETELY
ABSENT (legacy old-form config). An explicit `events: []` means the operator
intentionally has no adult events → never fabricate one. Admin-created events
saved into `events[]` still surface normally.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services import admin_config_service as acs

_TZ = timezone(timedelta(hours=4))
_NOW = datetime(2026, 7, 7, 12, 0, tzinfo=_TZ)

# Section carrying legacy section-level (Maroon-5) event-like fields.
_SECTION_BASE = {
    "id": "adult_events", "type": "adult_events", "status": "active",
    "name": "ზრდასრულთა ღონისძიებები",
    "description_short": "maroon 5  კონცერტი", "price_text": "200", "price_gel": 200,
    "location": "ბორის პაიჭაძის სტადიონი",
    "streams": [{"name": "23 ივნისი", "dates_text": "19:00", "status": "active"}],
}


def _use_section(monkeypatch, section):
    monkeypatch.setattr(
        acs, "get_section",
        lambda sid: section if sid == "adult_events" else None,
    )


def _fromula(status="active", date_text="28 აგვისტო 2030"):
    return {"id": "fromula_1", "title": "fromula 1", "status": status,
            "date_text": date_text, "location": "monaco", "price_text": "5000",
            "price_gel": 4999, "min_age": 13}


# ── events: [] → NO fallback, NO adult_events_default ─────────────────────────
def test_events_empty_returns_empty_no_fallback(monkeypatch):
    _use_section(monkeypatch, {**_SECTION_BASE, "events": []})
    raw = acs.get_adult_events()
    assert raw == []
    assert not any(e.get("id") == "adult_events_default" for e in raw)
    assert acs.get_active_adult_events(now=_NOW) == []


def test_events_empty_with_future_section_date_still_empty(monkeypatch):
    _use_section(monkeypatch, {
        **_SECTION_BASE, "events": [],
        "streams": [{"name": "30 დეკემბერი 2030", "dates_text": "19:00", "status": "active"}],
    })
    assert acs.get_adult_events() == []
    assert acs.get_active_adult_events(now=_NOW) == []


# ── events key ABSENT → legacy fallback may still fire ───────────────────────
def test_events_key_absent_keeps_legacy_fallback(monkeypatch):
    section = {k: v for k, v in _SECTION_BASE.items()}  # no "events" key
    _use_section(monkeypatch, section)
    raw = acs.get_adult_events()
    assert any(e.get("id") == "adult_events_default" for e in raw)


# ── deleted / inactive fromula never appears ─────────────────────────────────
def test_deleted_fromula_not_listed_after_events_empty(monkeypatch):
    _use_section(monkeypatch, {**_SECTION_BASE, "events": []})
    raw = acs.get_adult_events()
    assert not any("fromula" in str(e.get("id", "")).lower() for e in raw)
    assert not any("fromula" in str(e.get("title", "")).lower() for e in raw)


def test_inactive_fromula_not_active(monkeypatch):
    _use_section(monkeypatch, {**_SECTION_BASE, "events": [_fromula(status="inactive")]})
    assert acs.get_active_adult_events(now=_NOW) == []


def test_no_active_events_does_not_fabricate_maroon_or_fromula(monkeypatch):
    _use_section(monkeypatch, {**_SECTION_BASE, "events": []})
    active = acs.get_active_adult_events(now=_NOW)
    assert active == []
    blob = " ".join(str(e) for e in acs.get_adult_events()).lower()
    assert "maroon" not in blob and "fromula" not in blob and "5000" not in blob


# ── fromula only appears when explicitly active + future in events[] ─────────
def test_fromula_appears_only_when_active_future_in_events(monkeypatch):
    _use_section(monkeypatch, {**_SECTION_BASE, "events": [_fromula(date_text="28 აგვისტო 2030")]})
    assert any(e.get("id") == "fromula_1" for e in acs.get_active_adult_events(now=_NOW))
    _use_section(monkeypatch, {**_SECTION_BASE, "events": []})
    assert acs.get_active_adult_events(now=_NOW) == []


# ── future Admin-created event surfaces; events:[] does not disable ──────────
def test_admin_created_future_event_is_listed(monkeypatch):
    ev = {"id": "concert_x", "title": "concert x", "status": "active",
          "date_text": "30 დეკემბერი 2030", "min_age": 13}
    _use_section(monkeypatch, {**_SECTION_BASE, "events": [ev]})
    active = acs.get_active_adult_events(now=_NOW)
    assert [e.get("id") for e in active] == ["concert_x"]


def test_events_empty_does_not_permanently_disable(monkeypatch):
    # events: [] → none; then the operator adds an event → it shows (same section).
    _use_section(monkeypatch, {**_SECTION_BASE, "events": []})
    assert acs.get_active_adult_events(now=_NOW) == []
    ev = {"id": "new_ev", "title": "ახალი ღონისძიება", "status": "active",
          "date_text": "1 ივნისი 2031", "min_age": 13}
    _use_section(monkeypatch, {**_SECTION_BASE, "events": [ev]})
    assert any(e.get("id") == "new_ev" for e in acs.get_active_adult_events(now=_NOW))


# ── delete removes from events[] (persistence path is file-based) ────────────
def test_delete_adult_event_removes_from_list(monkeypatch):
    store = {"events": [_fromula(), {"id": "keep", "title": "keep", "status": "active",
                                     "date_text": "1 ივნისი 2031", "min_age": 13}]}
    monkeypatch.setattr(acs, "_load_adult_events_raw", lambda: list(store["events"]))
    monkeypatch.setattr(acs, "_save_adult_events_list", lambda evs: store.update(events=evs) or [])
    assert acs.delete_adult_event("fromula_1") is True
    assert not any(e.get("id") == "fromula_1" for e in store["events"])
