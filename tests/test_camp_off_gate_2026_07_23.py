"""Camp-off gate — USE_CAMP_OFF_GATE (2026-07-23).

Live bug (operator test, dynamic product „დისნეილენდი"): a follow-up „ფასი რა
არის?" leaked the CAMP price block (2150 ₾) and later a typo'd product name fell
into camp registration/Sunday-School — because the deterministic camp INFO
interceptors fire on generic markers ("ფასი") regardless of camp status. The camp
is ENDED, so those rote camp answers should never appear.

With USE_CAMP_OFF_GATE ON, when the camp is NOT active AND the message has no
explicit camp word (ბანაკ/საზაფხულო/ლაგერ), `_handle_core` skips the camp INFO
interceptors (`camp_off`), so the generic question is reasoned by the LLM engine
over the active program's data. Explicit camp questions still get the clean camp
status message; booking/contact/safety interceptors are never gated. OFF ⇒
`_camp_off_suppresses_info` is always False ⇒ camp chain byte-identical.
"""
import dataclasses

import pytest

from app.config import Settings
from app.flows import parent_flow
from app.services import admin_config_service


def _set(monkeypatch, *, flag, status):
    swapped = dataclasses.replace(parent_flow.settings, USE_CAMP_OFF_GATE=flag)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(admin_config_service, "get_camp_status", lambda: status)


# --- flag default ---

def test_flag_defaults_false():
    assert Settings().USE_CAMP_OFF_GATE is False


def test_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_CAMP_OFF_GATE", "true")
    assert Settings.from_env().USE_CAMP_OFF_GATE is True


# --- gate logic ---

@pytest.mark.parametrize("flag,status,msg,expected", [
    # flag OFF → never suppress (byte-identical arm), even camp ended
    (False, "ended", "ფასი რა არის?", False),
    (False, "active", "ფასი რა არის?", False),
    # camp ACTIVE → never suppress (regression guarantee)
    (True, "active", "ფასი რა არის?", False),
    # camp OFF + generic marker (no camp word) → SUPPRESS → defer to engine
    (True, "ended", "ფასი რა არის?", True),
    (True, "hidden", "სად ტარდება და როდის?", True),
    (True, "inactive", "და ეს რა თანხა დამიჯდება თვეში?", True),
    # camp OFF + EXPLICIT camp word → NOT suppressed (clean „camp ended" message)
    (True, "ended", "ბანაკის ფასი რა არის?", False),
    (True, "ended", "საზაფხულო პროგრამა მაინტერესებს", False),
    (True, "ended", "ლაგერი გაქვთ?", False),
])
def test_suppresses_info(monkeypatch, flag, status, msg, expected):
    _set(monkeypatch, flag=flag, status=status)
    assert parent_flow._camp_off_suppresses_info(msg) is expected


def test_fail_open_on_error(monkeypatch):
    """Any error resolving camp status → False (never suppress camp on a fault)."""
    swapped = dataclasses.replace(parent_flow.settings, USE_CAMP_OFF_GATE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)

    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr(admin_config_service, "get_camp_status", _boom)
    assert parent_flow._camp_off_suppresses_info("ფასი რა არის?") is False


def test_empty_message_when_off_gate(monkeypatch):
    _set(monkeypatch, flag=True, status="ended")
    # empty message, camp ended → suppressed (no camp word) — harmless (engine path)
    assert parent_flow._camp_off_suppresses_info("") is True
