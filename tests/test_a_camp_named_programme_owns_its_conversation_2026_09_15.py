"""A second camp in the panel still got the summer camp's answers (2026-09-14).

Measured offline with „Paris camp" active and the summer camp ended, driven
through `conversation_service.process_message`:

    „Paris camp — interested"   → Paris overview                 (right)
    „what is the price?"        → „summer camp already took place…"  (wrong)
    „7 years old"               → the summer camp's 9–17 age text    (wrong)

Both wrong answers came from the same place. `_conversation_names_other_program`
walks the parent's turns newest-first and stopped at the first CAMP WORD before
asking whether that turn identified a programme. „Paris camp" contains the camp
word, so the walk ended there and every camp handler took the turn as the
summer camp's. A bare „camp" turn was worse still: the name matcher refuses a
shared word on its own, so reordering the two checks alone does not see Paris.

The routing already knew better. `_program_id_for_turn` — the question the
camp-status gate itself asks a few lines later — reads „camp" as Paris when
Paris is the only camp that answers to it. The walk now asks that same
question. Nothing is added: a camp word with no single owner still ends the
walk exactly as before, so the summer camp alone, and two active camps that
still need „which one?", are unchanged.

Georgian strings are built from code points so no letter can drift.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service as acs


def _ka(text: str) -> str:
    """Every letter must be ASCII or Georgian — a stray letter from another
    script would silently break programme-name matching."""
    for ch in text:
        assert ord(ch) < 128 or 0x10D0 <= ord(ch) <= 0x10FF, repr(text)
    return text


CAMP_WORD = _ka("ბანაკი")                      # ბანაკი
PARIS_NAME = _ka("პარიზის " + CAMP_WORD)   # პარიზის ბანაკი
PARIS_TAG = _ka("პარიზი")                       # პარიზი
SUMMER_CAMP_NAME = _ka(
    "საზაფხულო " + CAMP_WORD)  # საზაფხულო ბანაკი
SCHOOL_NAME = _ka(
    "საკვირაო "
    "სკოლა")                                        # საკვირაო სკოლა
INTERESTED = _ka(
    " მაინტერესებს")  # მაინტერესებს
PRICE_Q = _ka(
    "ფასი რა არის?")      # ფასი რა არის?
SEVEN_YEARS = _ka("7 წლის არის")     # 7 წლის არის


def _summer_camp(status: str) -> dict:
    return {"id": "summer_camp", "type": "camp", "status": status,
            "name": SUMMER_CAMP_NAME, "hashtags": [CAMP_WORD],
            "age_min": 9, "age_max": 17,
            "registration_status": "open" if status == "active" else "closed"}


def _paris(status: str = "active") -> dict:
    return {"id": "disneyland", "type": "kids_program", "status": status,
            "name": PARIS_NAME, "hashtags": [PARIS_TAG],
            "age_min": 10, "age_max": 14, "registration_status": "open"}


_SCHOOL = {"id": "sunday_school", "type": "kids_program", "status": "active",
           "name": SCHOOL_NAME, "age_min": 7, "age_max": 17,
           "registration_status": "open"}


@pytest.fixture
def panel(monkeypatch):
    def _install(sections, camp_status="ended"):
        sections = list(sections)
        monkeypatch.setattr(acs, "load_sections",
                            lambda: [dict(s) for s in sections])
        monkeypatch.setattr(acs, "get_active_sections",
                            lambda: [dict(s) for s in sections
                                     if s.get("status") == "active"])
        monkeypatch.setattr(acs, "get_section",
                            lambda pid: next((dict(s) for s in sections
                                              if s["id"] == pid), None))
        monkeypatch.setattr(acs, "get_camp_status", lambda: camp_status)
        monkeypatch.setattr(acs, "get_camp_age_bounds", lambda: (9, 17))
        monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
        monkeypatch.setattr(parent_flow, "settings", dataclasses.replace(
            config_module.settings, USE_DYNAMIC_PROGRAMS=True))
    return _install


def _conv(*user_turns: str) -> Conversation:
    conv = Conversation(sender_id="paris", platform="messenger", segment="PARENT")
    conv.lead = Lead(sender_id="paris", platform="messenger", segment="PARENT")
    history = []
    for text in user_turns:
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": "ok"})
    conv.history = history
    return conv


# ── the Paris conversation belongs to Paris ────────────────────────────────

@pytest.mark.parametrize("opening", [PARIS_NAME + INTERESTED, CAMP_WORD + INTERESTED],
                         ids=["named", "bare-camp-word"])
def test_the_conversation_is_recognised_as_paris(panel, opening):
    panel([_summer_camp("ended"), _SCHOOL, _paris()])
    assert parent_flow._conversation_names_other_program(_conv(opening)) is True


@pytest.mark.parametrize("opening", [PARIS_NAME + INTERESTED, CAMP_WORD + INTERESTED],
                         ids=["named", "bare-camp-word"])
def test_a_price_question_is_not_answered_as_the_summer_camp(panel, opening):
    """Live-shaped turn 2: „what is the price?" got „summer camp already took place"."""
    panel([_summer_camp("ended"), _SCHOOL, _paris()])
    assert parent_flow._maybe_handle_camp_status(_conv(opening), PRICE_Q) is None


def test_a_young_age_is_not_answered_with_the_summer_camps_band(panel):
    """Live-shaped turn 5: after a later bare-camp-word turn, „7 years old" got
    „the camp is for 9–17"."""
    panel([_summer_camp("ended"), _SCHOOL, _paris()])
    conv = _conv(PARIS_NAME + INTERESTED, CAMP_WORD + INTERESTED)
    assert parent_flow._maybe_handle_out_of_range_age(conv, SEVEN_YEARS) is None


# ── what must not move ─────────────────────────────────────────────────────

def test_sunday_school_is_still_its_own_conversation(panel):
    panel([_summer_camp("ended"), _SCHOOL, _paris()])
    conv = _conv(SCHOOL_NAME + INTERESTED)
    assert parent_flow._conversation_names_other_program(conv) is True
    assert parent_flow._maybe_handle_camp_status(conv, PRICE_Q) is None


def test_the_summer_camp_alone_still_answers_its_own_conversation(panel):
    """No other camp in the panel: „camp" is the summer camp, as before."""
    panel([_summer_camp("ended"), _SCHOOL, _paris("inactive")])
    conv = _conv(CAMP_WORD + INTERESTED)
    assert parent_flow._conversation_names_other_program(conv) is False
    assert parent_flow._maybe_handle_camp_status(conv, PRICE_Q) is not None


def test_two_active_camps_still_leave_a_bare_camp_word_unowned(panel):
    """Two camps answer to „camp": no single owner, so the walk ends on the
    camp word exactly as before and the parent is still asked which one."""
    panel([_summer_camp("active"), _SCHOOL, _paris()], camp_status="active")
    assert parent_flow._conversation_names_other_program(
        _conv(CAMP_WORD + INTERESTED)) is False


def test_the_summer_camp_named_in_full_is_the_summer_camps(panel):
    panel([_summer_camp("active"), _SCHOOL, _paris()], camp_status="active")
    assert parent_flow._conversation_names_other_program(
        _conv(SUMMER_CAMP_NAME)) is False
