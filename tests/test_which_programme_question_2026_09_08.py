"""Two camps meant the first handler won, whatever the parent meant.

„ბანაკი" identified one programme for as long as the panel held one camp. With
„საზაფხულო ბანაკი" and „პარიზის ბანაკი" both switched on it identifies neither,
and measured on 2026-09-08 the turn went to whichever handler the code reached
first — the summer camp every time, including for its price:

    in='ბანაკი მაინტერესებს'  → „სიტყვის აკადემიის ბანაკი არის 7-დღიანი…"
    in='ბანაკის ფასი რა არის?' → „ბანაკის ფასი არის 2150 ლარი"

Guessing between them is the one thing that must not happen, so the agent asks
which — above every camp handler, so an unresolved turn cannot be answered from
a candidate by accident.

Nothing here is about camps. Two programmes sharing „სკოლა" behave identically,
and the names come from the panel at reply time: switch one off and it leaves
the question; leave one and the question is not asked at all.
"""
import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow as pf
from app.models.conversation import Conversation

_CAMP = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
         "status": "active", "hashtags": ["ბანაკი"],
         "description_short": "საზაფხულო ბანაკი — 7 დღე."}
_PARIS = {"id": "disneyland", "name": "პარიზის ბანაკი", "type": "kids_program",
          "status": "active", "description_short": "პარიზის ბანაკი — 10 დღე."}
_WINTER = {"id": "winter_camp", "name": "ზამთრის ბანაკი", "type": "kids_program",
           "status": "active", "description_short": "ზამთრის ბანაკი — 5 დღე."}
_SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
           "status": "active", "description_short": "საკვირაო სკოლა — 3 თვე."}


@pytest.fixture
def panel(monkeypatch):
    def _install(sections, template=None):
        monkeypatch.setattr(
            "app.services.admin_config_service.get_active_sections",
            lambda: [dict(s) for s in sections])
        monkeypatch.setattr(
            "app.services.admin_config_service.render_template",
            lambda tid, ctx: (template or "").format(**ctx) if template else "")
        swapped = dataclasses.replace(config_module.settings,
                                      USE_CAMP_OFF_GATE=True)
        monkeypatch.setattr(pf, "settings", swapped)
    return _install


def _ask(msg, history=()):
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.history = list(history)
    return pf._maybe_ask_which_programme(conv, msg)


# ── it asks, naming what the operator switched on ──────────────────────────

def test_two_camps_are_both_named(panel):
    panel([_CAMP, _SCHOOL, _PARIS])
    assert _ask("ბანაკი მაინტერესებს") == (
        "რომელი გაინტერესებთ: საზაფხულო ბანაკი თუ პარიზის ბანაკი?")


def test_three_camps_are_all_named(panel):
    panel([_CAMP, _SCHOOL, _PARIS, _WINTER])
    assert _ask("ბანაკი მაინტერესებს") == (
        "რომელი გაინტერესებთ: საზაფხულო ბანაკი, პარიზის ბანაკი, ზამთრის ბანაკი?")


def test_switching_one_off_removes_it_from_the_question(panel):
    """Panel-driven: no code change, and the count decides the wording."""
    panel([_CAMP, _SCHOOL, _PARIS, dict(_WINTER, status="ended")])
    assert "ზამთრის" not in _ask("ბანაკი მაინტერესებს")


def test_one_camp_is_never_asked_about(panel):
    """The whole point of the count — a single answer is not a choice."""
    panel([dict(_CAMP, status="ended"), _SCHOOL, _PARIS])
    assert _ask("ბანაკი მაინტერესებს") is None


def test_naming_one_of_them_is_not_a_question(panel):
    panel([_CAMP, _SCHOOL, _PARIS])
    assert _ask("პარიზის ბანაკი მაინტერესებს") is None


def test_it_is_not_about_camps(panel):
    """Two programmes sharing „სკოლა" get the same treatment."""
    other = {"id": "art_school", "name": "ხელოვნების სკოლა",
             "type": "kids_program", "status": "active",
             "description_short": "ხელოვნების სკოლა."}
    panel([_SCHOOL, other])
    assert _ask("სკოლა მაინტერესებს") == (
        "რომელი გაინტერესებთ: საკვირაო სკოლა თუ ხელოვნების სკოლა?")


def test_a_message_naming_nothing_is_left_alone(panel):
    panel([_CAMP, _SCHOOL, _PARIS])
    assert _ask("გამარჯობა") is None


# ── it asks once ───────────────────────────────────────────────────────────

def test_the_same_question_is_not_repeated(panel):
    """Re-sending it would mean the reply named none of them either, and
    asking again is a loop. The engine holds that conversation instead."""
    panel([_CAMP, _SCHOOL, _PARIS])
    asked = _ask("ბანაკი მაინტერესებს")
    assert _ask("ბანაკი მაინტერესებს",
                history=[{"role": "assistant", "content": asked}]) is None


# ── the operator owns the wording ──────────────────────────────────────────

def test_the_operator_can_write_the_question(panel):
    panel([_CAMP, _SCHOOL, _PARIS],
          template="რომელ ბანაკზეა საუბარი — {listed}?")
    assert _ask("ბანაკი მაინტერესებს") == (
        "რომელ ბანაკზეა საუბარი — საზაფხულო ბანაკი თუ პარიზის ბანაკი?")


def test_the_names_are_never_hardcoded(panel):
    """Rename in the panel, and the question renames with it."""
    panel([dict(_CAMP, name="ზაფხულის ბანაკი 2027"), _SCHOOL, _PARIS])
    assert "ზაფხულის ბანაკი 2027" in _ask("ბანაკი მაინტერესებს")


# ── through the flow, where it has to beat the camp handlers ───────────────

def _handle(msg, sections, monkeypatch):
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [dict(s) for s in sections])
    monkeypatch.setattr("app.services.admin_config_service.load_sections",
                        lambda: [dict(s) for s in sections])
    monkeypatch.setattr("app.services.admin_config_service.get_camp_status",
                        lambda: next((s["status"] for s in sections
                                      if s["id"] == "summer_camp"), "ended"))
    monkeypatch.setattr("app.services.messenger_service.get_user_profile",
                        lambda sid, plat: {})
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config_module.settings, USE_CAMP_OFF_GATE=True))
    conv = Conversation(sender_id="f", platform="messenger", segment="PARENT")
    return pf.handle(conv, msg)


def test_the_question_beats_the_camp_price_handler(monkeypatch):
    """„ბანაკის ფასი" returned the summer camp's approved 2150 whatever the
    parent meant. With two camps on, neither price is ours to give."""
    out = _handle("ბანაკის ფასი რა არის?", [_CAMP, _SCHOOL, _PARIS], monkeypatch)
    assert "2150" not in out
    assert "საზაფხულო ბანაკი" in out and "პარიზის ბანაკი" in out


def test_the_question_beats_the_camp_intro(monkeypatch):
    out = _handle("ბანაკი მაინტერესებს", [_CAMP, _SCHOOL, _PARIS], monkeypatch)
    assert "7-დღიანი" not in out
    assert "რომელი გაინტერესებთ" in out
