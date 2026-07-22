"""Section status gate — ``USE_SECTION_STATUS_GATE`` (2026-07-22).

When ON, :func:`admin_config_service.get_active_adult_events` honors the
``adult_events`` SECTION-level ``status``: an operator who sets the section to
``ended`` / ``hidden`` in the admin panel fully turns the program off (no events
offered, listed, or resolved). OFF ⇒ byte-identical — the section status is
ignored and only the per-event ``active`` flag + the date filter apply.

This closes the live "disabled program still used" gap: today
``get_active_adult_events`` checks only per-event ``active``, so an ``ended``
adult_events section keeps surfacing every future active event.
"""
import dataclasses

import pytest

from app import config
from app.services import admin_config_service as acs


def _events(*statuses):
    """Raw events with EMPTY ``date_text`` so the date filter never hides them —
    isolating the section-status behavior under test."""
    return [
        {"id": f"ev{i}", "title": f"საღამო {i}", "status": st,
         "min_age": 13, "date_text": ""}
        for i, st in enumerate(statuses, start=1)
    ]


def _patch_section(monkeypatch, status, events):
    section = {
        "id": "adult_events", "type": "adult_events",
        "name": "ღონისძიებები", "events": events,
    }
    if status is not None:
        section["status"] = status
    monkeypatch.setattr(
        acs, "get_section",
        lambda sid: section if sid == "adult_events" else {},
    )


def _set_gate(monkeypatch, on):
    swapped = dataclasses.replace(config.settings, USE_SECTION_STATUS_GATE=on)
    monkeypatch.setattr(config, "settings", swapped)


# --- is_section_active helper -------------------------------------------------

@pytest.mark.parametrize("status,expected", [
    ("active", True), ("Active", True), (" active ", True),
    (None, True), ("", True),          # missing/empty → active (never disable by accident)
    ("ended", False), ("hidden", False),
    ("coming_soon", False), ("full", False),
])
def test_is_section_active(monkeypatch, status, expected):
    _patch_section(monkeypatch, status, _events("active"))
    assert acs.is_section_active("adult_events") is expected


# --- gate OFF = byte-identical (current behavior) -----------------------------

def test_flag_off_ended_section_still_returns_events(monkeypatch):
    _set_gate(monkeypatch, False)
    _patch_section(monkeypatch, "ended", _events("active"))
    # Flag OFF: the ended section is ignored — the event still surfaces, exactly
    # as before this change. This proves byte-identical behavior when disabled.
    assert len(acs.get_active_adult_events()) == 1


# --- gate ON = section status respected ---------------------------------------

@pytest.mark.parametrize("status", ["ended", "hidden", "coming_soon", "full"])
def test_flag_on_inactive_section_returns_empty(monkeypatch, status):
    _set_gate(monkeypatch, True)
    _patch_section(monkeypatch, status, _events("active", "active"))
    assert acs.get_active_adult_events() == []


def test_flag_on_ended_section_empty_including_past(monkeypatch):
    # The comment specific-event resolver uses include_past=True; it too must be
    # fully off for an ended program (no "this event has ended" ticket path).
    _set_gate(monkeypatch, True)
    _patch_section(monkeypatch, "ended", _events("active"))
    assert acs.get_active_adult_events(include_past=True) == []


def test_flag_on_active_section_unchanged(monkeypatch):
    _set_gate(monkeypatch, True)
    _patch_section(monkeypatch, "active", _events("active"))
    assert len(acs.get_active_adult_events()) == 1


def test_flag_on_missing_status_treated_active(monkeypatch):
    _set_gate(monkeypatch, True)
    _patch_section(monkeypatch, None, _events("active"))
    assert len(acs.get_active_adult_events()) == 1


def test_flag_on_still_applies_per_event_active_filter(monkeypatch):
    # Active section, but one event is per-event inactive → still dropped.
    _set_gate(monkeypatch, True)
    _patch_section(monkeypatch, "active", _events("active", "hidden"))
    out = acs.get_active_adult_events()
    assert [e["id"] for e in out] == ["ev1"]
