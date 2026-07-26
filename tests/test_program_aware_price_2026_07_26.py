"""Program-aware camp gate (2026-07-26 live test #3): „[program] ფასი რა არის?" went to camp.

A price/topic question that NAMES a non-camp program („დისნეილენდის ფასი", „ფორმულა 1-ის
ფასი") was answered with „ბანაკი დასრულდა" — `_msg_has_camp_intent` → `_is_camp_price_intent`
treats ANY „ფასი" as a CAMP price, ignoring the program named. Fix: `_maybe_handle_camp_status`
now DEFERS (routes to the engine → correct program price) when the message names an active
NON-camp program, gated by USE_PROGRAM_ISOLATION. A hard camp keyword („ბანაკის ფასი") still
gets the camp status. OFF ⇒ byte-identical.
"""
import dataclasses
from unittest.mock import patch

from app import config
from app.flows import parent_flow as pf
from app.models.conversation import Conversation
from app.models.lead import Lead

_SECTIONS = [
    {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "ended", "type": "camp"},
    {"id": "disneyland_tour", "name": "დისნეილენდი", "status": "active", "type": "other"},
    {"id": "formula_1", "name": "ფორმულა 1", "status": "active", "type": "other"},
]


def _conv():
    c = Conversation(sender_id="s", platform="facebook")
    c.lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    return c


def _status(monkeypatch, isolation):
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_PROGRAM_ISOLATION=isolation))
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: list(_SECTIONS))
    monkeypatch.setattr("app.services.admin_config_service.get_camp_status", lambda: "ended")
    return lambda msg: pf._maybe_handle_camp_status(_conv(), msg)


# --- predicate ---

def test_predicate_names_other_program(monkeypatch):
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: list(_SECTIONS))
    assert pf._msg_names_other_program("დისნეილენდის ფასი რა არის?")
    assert pf._msg_names_other_program("ფორმულა 1-ის ფასი რა არის?")
    assert not pf._msg_names_other_program("ბანაკის ფასი რა არის?")   # camp is excluded
    assert not pf._msg_names_other_program("ფასი რა არის?")           # no program named


# --- the gate: non-camp program price routes to engine ---

def test_disneyland_price_defers_to_engine(monkeypatch):
    ask = _status(monkeypatch, isolation=True)
    assert ask("დისნეილენდის ფასი რა არის?") is None       # → engine (Disneyland price)
    assert ask("ფორმულა 1-ის ფასი რა არის?") is None


def test_camp_price_still_camp(monkeypatch):
    ask = _status(monkeypatch, isolation=True)
    assert "დასრულებულია" in (ask("ბანაკის ფასი რა არის?") or "")   # hard camp keyword wins


def test_genuine_camp_question_still_camp(monkeypatch):
    ask = _status(monkeypatch, isolation=True)
    assert "დასრულებულია" in (ask("ბანაკი დამთავრდა?") or "")


def test_off_is_byte_identical(monkeypatch):
    ask = _status(monkeypatch, isolation=False)
    # OLD behaviour: a non-camp program price still hit the camp gate
    assert "დასრულებულია" in (ask("დისნეილენდის ფასი რა არის?") or "")
