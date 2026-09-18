"""Live regression, client Page 2026-09-18 04:12-06:35 — the closed camp claimed
other programmes' questions, and a parent's first real question was answered with
the greeting menu.

Five parents wrote that morning; none got an answer.

  04:24:20  „მაინტერესებს კვირას პარაგრაფში თუ გაქვთ დარჩენილი ადგილი
             16 წლის მოზარდისთვის"
            → „საზაფხულო ბანაკი უკვე გაიმართა და რეგისტრაცია დასრულებულია…"
  04:24:44  „და ასევე 3 თვის გადასახადის გადახდა ერთად ხდება თუ ყოველთვიურად"
            → the same camp-ended text
  04:12:46  „გამარჯობა, სად ხართ ტერიტორიულად და რა განრიგი გაქვთ 8წლიან
             ჯგუფებისთვის?"          → „გამარჯობა 💙 რით შემიძლია დაგეხმაროთ?"
  05:13:56  „8 წლის ბიჭისთვის ლიტერატურული კუთხით თუ გაქვთ ონლაინ კურსები"
            → the same greeting
  06:30:48  „მაინტერესებს დეტალები რა ასაკიდან მიიღება მისამართი და რამდენია
             გადასახადი"             → the same greeting

Two causes, both measured on these exact strings:

A. The camp is OFF and Sunday School is the only active programme, yet the camp's
   GENERIC detectors still claim the turn — `resolve_operational` on „16 წლის"
   and `_is_camp_price_intent` on „გადასახად". The existing deferral only fires
   when the message or the conversation NAMES another programme, which a parent's
   first substantive message never does.

B. `_classify_segment` knows only camp/adult keywords, so a question about the
   one active programme classifies UNCLEAR and gets the disambiguation greeting —
   a menu that, with a single active programme, has nothing to disambiguate.

Both fixes are panel-driven and remove reach from a deterministic branch rather
than adding a new one: a closed camp answers only when it is named, and a sole
active programme owns a substantive turn.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.services import admin_config_service, conversation_service


def _enable_dynamic_programs(monkeypatch) -> None:
    """ON in production (boot log), pinned OFF by the suite — enable it here."""
    monkeypatch.setattr(
        conversation_service, "settings",
        dataclasses.replace(config_module.settings, USE_DYNAMIC_PROGRAMS=True),
    )


def _enable_program_isolation(monkeypatch) -> None:
    """`USE_PROGRAM_ISOLATION` is the existing switch for „a non-camp answer never
    borrows camp"; the new deferral hangs off the same one, so OFF stays exactly
    as it was."""
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(config_module.settings, USE_PROGRAM_ISOLATION=True),
    )

SCHOOL_ONLY = [
    {"id": "sunday_school", "name": "საკვირაო სკოლა",
     "type": "sunday_school", "status": "active"},
]
SCHOOL_AND_EVENTS = SCHOOL_ONLY + [
    {"id": "adult_events", "name": "ზრდასრულთა ღონისძიებები",
     "type": "adult_events", "status": "active"},
]

AGE_QUESTION = (
    "მაინტერესებს კვირას პარაგრაფში თუ გაქვთ დარჩენილი ადგილი "
    "16 წლის მოზარდისთვის"
)
PAYMENT_QUESTION = "და ასევე 3 თვის გადასახადის გადახდა ერთად ხდება თუ ყოველთვიურად"
LOCATION_QUESTION = (
    "გამარჯობა, სად ხართ ტერიტორიულად და რა განრიგი გაქვთ 8წლიან ჯგუფებისთვის?"
)
CAMP_NAMED = "ბანაკი მაინტერესებს"


@pytest.fixture
def camp_off_school_live(monkeypatch):
    """The live client panel of 2026-09-18: camp ended, Sunday School active.

    `USE_DYNAMIC_PROGRAMS` is ON in production (boot log) and pinned OFF by the
    test suite, so the panel-driven routing is enabled explicitly here."""
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: list(SCHOOL_ONLY))
    _enable_dynamic_programs(monkeypatch)
    _enable_program_isolation(monkeypatch)


def _conversation() -> Conversation:
    return Conversation(sender_id="t-2026-09-18", platform="messenger")


# ── A. a closed camp answers only when it is named ──────────────────────────

def test_closed_camp_does_not_claim_an_age_question(camp_off_school_live):
    conv = _conversation()
    assert parent_flow._maybe_handle_camp_status(conv, AGE_QUESTION) is None


def test_closed_camp_does_not_claim_a_payment_question(camp_off_school_live):
    conv = _conversation()
    assert parent_flow._maybe_handle_camp_status(conv, PAYMENT_QUESTION) is None


def test_closed_camp_still_answers_when_the_camp_is_named(camp_off_school_live):
    conv = _conversation()
    answer = parent_flow._maybe_handle_camp_status(conv, CAMP_NAMED)
    assert answer, "an explicit camp question must still get the honest status"


def test_camp_info_interceptors_are_suppressed_for_a_generic_turn(
    camp_off_school_live,
):
    """The status gate standing down must not hand the turn to the camp INFO
    interceptors instead — they answer with camp facts (9–17, camp's manager)."""
    conv = _conversation()
    assert parent_flow._camp_off_suppresses_info(PAYMENT_QUESTION, conv) is True
    assert parent_flow._camp_off_suppresses_info(AGE_QUESTION, conv) is True
    # An explicit camp question is never suppressed.
    assert parent_flow._camp_off_suppresses_info(CAMP_NAMED, conv) is False


def test_camp_still_owns_a_generic_turn_when_it_is_the_only_programme(monkeypatch):
    """Nothing else is active ⇒ the camp status is the honest answer, unchanged."""
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [])
    conv = _conversation()
    assert parent_flow._maybe_handle_camp_status(conv, PAYMENT_QUESTION) is not None


# ── B. the sole active programme owns a substantive turn ────────────────────

def test_sole_active_programme_is_the_route_for_a_question(camp_off_school_live):
    assert conversation_service._sole_active_program_segment() == "PARENT"


def test_two_active_programmes_still_ask_which_one(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda *a, **k: list(SCHOOL_AND_EVENTS))
    _enable_dynamic_programs(monkeypatch)
    assert conversation_service._sole_active_program_segment() is None


def test_a_first_question_reaches_the_programme_flow(camp_off_school_live, monkeypatch):
    """End-to-end: the live 04:12 question must reach the PARENT flow instead of
    being answered with the greeting menu."""
    seen: dict[str, str] = {}

    def _spy(conversation, message):
        seen["message"] = message
        return "PROGRAMME ANSWER"

    monkeypatch.setattr(parent_flow, "handle", _spy)
    reply = conversation_service.process_message(
        "t-2026-09-18-b", LOCATION_QUESTION, "messenger",
    )
    assert seen.get("message") == LOCATION_QUESTION, (
        "the parent's first question never reached the programme flow"
    )
    assert reply == "PROGRAMME ANSWER"


def test_a_bare_greeting_still_gets_the_greeting(camp_off_school_live, monkeypatch):
    """The greeting is right for a bare greeting — only a question overrides it."""
    monkeypatch.setattr(
        parent_flow, "handle", lambda *a, **k: "PROGRAMME ANSWER")
    reply = conversation_service.process_message(
        "t-2026-09-18-c", "გამარჯობა", "messenger",
    )
    assert reply != "PROGRAMME ANSWER"
