"""Self over-age → adult redirect — USE_SELF_OVERAGE_ADULT_REDIRECT (Step 4, 2026-07-23).

An adult (>17) asking about CAMP for THEMSELVES („ჩემთვის მინდა ბანაკი, 25 წლის
ვარ") used to get the child-focused camp intro (camp is 9–17 — a mismatch). With
the flag ON, `_maybe_handle_camp_intro` returns the camp age band + an adult-events
pointer instead (eval R7); no booking. OFF ⇒ byte-identical. A third-person child
age („შვილი 25 წლისაა") is never matched.
"""
import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

_R7 = "ჩემთვის მინდა ბანაკი, 25 წლის ვარ"
_CHILD = "შვილს ბანაკი მინდა"


def _set_flag(monkeypatch, value):
    swapped = dataclasses.replace(
        config_module.settings, USE_SELF_OVERAGE_ADULT_REDIRECT=value)
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _conv():
    c = Conversation(sender_id="x", platform="instagram", segment="PARENT")
    c.state = "START"
    c.lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    return c


# --- detector unit ---

@pytest.mark.parametrize("msg,expected", [
    ("ჩემთვის მინდა ბანაკი, 25 წლის ვარ", True),
    ("მე 30 წლის ვარ, ბანაკი მინდა", True),
    ("ჩემი თავის, 40 წლის ვარ", True),
    ("შვილს ბანაკი მინდა, 25 წლისაა", False),   # third-person child age
    ("ჩემთვის ბანაკი", False),                   # self but no age
    ("ჩემთვის, 15 წლის ვარ", False),             # self but age <= 17
    ("ბანაკი მაინტერესებს", False),              # neither
])
def test_detector(msg, expected):
    assert parent_flow._is_self_overage_camp_request(msg) is expected


# --- handler: flag OFF byte-identical ---

def test_flag_off_self_overage_gets_camp_intro(monkeypatch):
    _set_flag(monkeypatch, False)
    assert parent_flow._maybe_handle_camp_intro(_conv(), _R7) == parent_flow._CAMP_INTRO_TEXT


# --- handler: flag ON ---

def test_flag_on_self_overage_redirects_to_adult(monkeypatch):
    _set_flag(monkeypatch, True)
    out = parent_flow._maybe_handle_camp_intro(_conv(), _R7)
    assert out == parent_flow._CAMP_OVERAGE_ADULT_REDIRECT
    assert "ზრდასრულ" in out                                       # R7 require_any
    assert "ჩაგინიშნეთ" not in out and "დაჯავშნ" not in out        # R7 forbid: no booking


def test_flag_on_child_request_still_gets_camp_intro(monkeypatch):
    _set_flag(monkeypatch, True)
    assert parent_flow._maybe_handle_camp_intro(_conv(), _CHILD) == parent_flow._CAMP_INTRO_TEXT
