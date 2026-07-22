"""Sunday-School section status gate — USE_SECTION_STATUS_GATE (Step 4, 2026-07-23).

An operator who sets sunday_school to ended/hidden/full has turned it OFF: the
agent must say it is not offered and reveal NO availability/details — uniform with
camp (`_maybe_handle_camp_status`) and adult_events (`get_active_adult_events`).
OFF ⇒ byte-identical (before this, only `coming_soon` was special-cased; ended/
hidden/full still revealed the availability text + a handoff offer).
"""
import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.services import admin_config_service


def _patch_ss(monkeypatch, status):
    monkeypatch.setattr(admin_config_service, "get_sunday_school_status", lambda: {
        "availability_text": "საკვირაო სკოლა ივლისში დაემატება.",
        "details_text": "დეტალები ზუსტდება",
        "status": status, "handoff_enabled": True, "lead_type": "sunday_school",
    })


def _set_flag(monkeypatch, value):
    swapped = dataclasses.replace(config_module.settings, USE_SECTION_STATUS_GATE=value)
    monkeypatch.setattr(parent_flow, "settings", swapped)


@pytest.mark.parametrize("status", ["ended", "hidden", "full"])
def test_flag_off_inactive_ss_still_answers(monkeypatch, status):
    _set_flag(monkeypatch, False)
    _patch_ss(monkeypatch, status)
    out = parent_flow._render_sunday_school_answer()
    # byte-identical: availability is still revealed when the flag is OFF
    assert "დაემატება" in out and "აქტიური არ არის" not in out


@pytest.mark.parametrize("status", ["ended", "hidden", "full"])
def test_flag_on_inactive_ss_says_not_offered(monkeypatch, status):
    _set_flag(monkeypatch, True)
    _patch_ss(monkeypatch, status)
    out = parent_flow._render_sunday_school_answer()
    assert out == parent_flow._SUNDAY_SCHOOL_NOT_OFFERED
    assert "დაემატება" not in out  # no availability/details leaked


def test_flag_on_coming_soon_unchanged(monkeypatch):
    _set_flag(monkeypatch, True)
    _patch_ss(monkeypatch, "coming_soon")
    out = parent_flow._render_sunday_school_answer()
    assert out == parent_flow._SUNDAY_SCHOOL_COMING_SOON
    assert "აქტიური არ არის" not in out


def test_flag_on_active_ss_unchanged(monkeypatch):
    _set_flag(monkeypatch, True)
    _patch_ss(monkeypatch, "active")
    out = parent_flow._render_sunday_school_answer()
    assert "დაემატება" in out and "აქტიური არ არის" not in out
