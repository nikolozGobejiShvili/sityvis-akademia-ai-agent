"""Vague camp question → answer, not menu — USE_VAGUE_CAMP_INTENT (Step 4, 2026-07-23).

A vague colloquial camp question („ეგ თქვენი ბანაკი რა ხდება საერთოდ?") has a camp
keyword + a WH word but no interest marker, so `_has_explicit_georgian_camp_intent`
was False → `_maybe_static_welcome` showed the two-option menu instead of answering
(eval U9). With the flag ON, a camp keyword + a WH word counts as camp intent (the
static welcome yields) and `_maybe_handle_camp_intro` answers it. A BARE „ბანაკი"
still shows the menu; price/topic questions still defer. OFF ⇒ byte-identical.
"""
import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

_U9 = "ეგ თქვენი ბანაკი რა ხდება საერთოდ? რო ბავშვებმა ზაფხული კარგად გაატარონ?"
_BARE = "ბანაკი"
_PRICE = "ბანაკი რა ღირს?"


def _set_flag(monkeypatch, value):
    swapped = dataclasses.replace(config_module.settings, USE_VAGUE_CAMP_INTENT=value)
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _conv():
    c = Conversation(sender_id="x", platform="instagram", segment="PARENT")
    c.state = "START"
    c.lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    return c


# --- explicit-camp-intent gate (drives whether the static welcome yields) ---

def test_flag_off_vague_camp_not_explicit(monkeypatch):
    _set_flag(monkeypatch, False)
    assert parent_flow._has_explicit_georgian_camp_intent(_U9) is False  # byte-identical


def test_flag_on_vague_camp_is_explicit(monkeypatch):
    _set_flag(monkeypatch, True)
    assert parent_flow._has_explicit_georgian_camp_intent(_U9) is True


def test_flag_on_bare_camp_word_still_shows_menu(monkeypatch):
    _set_flag(monkeypatch, True)
    # bare „ბანაკი" (no WH word) must still be NON-explicit → branded menu
    assert parent_flow._has_explicit_georgian_camp_intent(_BARE) is False


# --- camp intro handler ---

def test_flag_off_vague_camp_intro_defers(monkeypatch):
    _set_flag(monkeypatch, False)
    assert parent_flow._maybe_handle_camp_intro(_conv(), _U9) is None  # byte-identical


def test_flag_on_vague_camp_gets_intro(monkeypatch):
    _set_flag(monkeypatch, True)
    out = parent_flow._maybe_handle_camp_intro(_conv(), _U9)
    assert out == parent_flow._CAMP_INTRO_TEXT
    assert any(t in out for t in ("რამდენი წლის", "7-დღიან", "ცოცხალ", "ურთიერთობა"))  # U9 require_any
    assert "ბანაკი თუ ღონისძიება" not in out  # U9 forbid: not the menu


def test_flag_on_price_question_still_defers(monkeypatch):
    _set_flag(monkeypatch, True)
    # „ბანაკი რა ღირს?" has a WH word but is a price question → its own handler, not the intro
    assert parent_flow._maybe_handle_camp_intro(_conv(), _PRICE) is None
