"""Mixed camp+adult intent in one message — USE_MIXED_INTENT_CAMP_ADULT (Step 4, 2026-07-23).

„ბავშვისთვის ბანაკი მინდა და ჩემთვის რამე ღონისძიება" collapsed to the camp intro,
dropping the adult half (eval R8). With the flag ON, a camp-intro turn that ALSO
carries an adult-event marker AND a self/other reference gets a deterministic
adult-events pointer appended, so both halves are addressed. „What events are IN
the camp?" (adult marker, no self ref) never matches. OFF ⇒ byte-identical.
"""
import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

_R8 = "ბავშვისთვის ბანაკი მინდა და ჩემთვის რამე ღონისძიება — ორივე გაქვთ?"
_CAMP_EVENTS = "ბანაკში რა ღონისძიებებია?"
_PURE_CAMP = "ბავშვს ბანაკი მინდა"


def _set_flag(monkeypatch, value):
    swapped = dataclasses.replace(config_module.settings, USE_MIXED_INTENT_CAMP_ADULT=value)
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _conv():
    c = Conversation(sender_id="x", platform="instagram", segment="PARENT")
    c.state = "START"
    c.lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    return c


# --- detector ---

@pytest.mark.parametrize("msg,expected", [
    (_R8, True),
    ("მე ღონისძიება მინდა, ბავშვს ბანაკი", True),
    (_CAMP_EVENTS, False),   # adult marker but NO self reference → not mixing
    (_PURE_CAMP, False),     # no adult marker
])
def test_detector(msg, expected):
    assert parent_flow._is_mixed_camp_adult_request(msg) is expected


# --- handler ---

def test_flag_off_mixed_gets_camp_intro_only(monkeypatch):
    _set_flag(monkeypatch, False)
    assert parent_flow._maybe_handle_camp_intro(_conv(), _R8) == parent_flow._CAMP_INTRO_TEXT


def test_flag_on_mixed_appends_adult_pointer(monkeypatch):
    _set_flag(monkeypatch, True)
    out = parent_flow._maybe_handle_camp_intro(_conv(), _R8)
    assert out == parent_flow._CAMP_INTRO_TEXT + "\n\n" + parent_flow._CAMP_OFF_ADULT_POINTER
    assert "წლის" in out                                                # R8 require_all
    assert any(t in out for t in ("ღონისძიება", "ზრდასრულ", "კულტურულ"))  # R8 require_any


def test_flag_on_pure_camp_unchanged(monkeypatch):
    _set_flag(monkeypatch, True)
    assert parent_flow._maybe_handle_camp_intro(_conv(), _PURE_CAMP) == parent_flow._CAMP_INTRO_TEXT
