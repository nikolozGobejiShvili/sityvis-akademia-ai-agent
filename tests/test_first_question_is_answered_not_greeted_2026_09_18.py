"""Live regression, client Page 2026-09-18 08:20 / 08:25 — a parent's FIRST
message is a question and the agent answers it with the greeting.

Measured through the real `conversation_service.process_message` with only the
model stubbed, on the live panel shape (camp ended, Sunday School the one active
programme):

  08:20:51  „ვატერლოოს ბრძოლა როდის მოხდა?"        → „გამარჯობა. რით შემიძლია
                                                       დაგეხმაროთ?"
  08:26:05  „სალამი" + „6 წლის ბავშვს ვერ დავარეგისტრირებ?"
                                                    → „გამარჯობა 💙 რით შემიძლია
                                                       დაგეხმაროთ?"

The routing fix shipped earlier the same morning (`_sole_active_program_segment`)
did its half: the turn now reaches the programme flow instead of stopping at the
„which programme?" menu. `_maybe_static_welcome` then fires on the first turn
REGARDLESS of content — it yields only for an explicit camp / price / adult-event
intent — so the parent's question was still answered with the greeting.

The greeting is the right answer to a greeting. It is the wrong answer to a
question: the parent has to repeat themselves, and a real one (registering a
6-year-old) reads as if nobody listened.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.services import admin_config_service

SCHOOL_ONLY = [
    {"id": "sunday_school", "name": "საკვირაო სკოლა",
     "type": "sunday_school", "status": "active"},
]

# The two live first messages.
OFF_TOPIC_QUESTION = "ვატერლოოს ბრძოლა როდის მოხდა?"
REGISTRATION_QUESTION = "სალამი 6 წლის ბავშვს ვერ დავარეგისტრირებ?"
# Two more from 04:12 / 05:13 the same morning — same defect, no question mark on
# the second one.
LOCATION_QUESTION = (
    "გამარჯობა, სად ხართ ტერიტორიულად და რა განრიგი გაქვთ 8წლიან ჯგუფებისთვის?"
)
ONLINE_QUESTION = "8 წლის ბიჭისთვის ლიტერატურული კუთხით თუ გაქვთ ონლაინ კურსები"

# A greeting is still a greeting.
PURE_GREETINGS = ("გამარჯობა", "სალამი", "გამარჯობა!", "hi")
# A bare topic word is not a question — the menu/camp contract for it is shipped
# behaviour and must not move.
BARE_TOPIC = "ბანაკი"


@pytest.fixture
def live_panel(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: list(SCHOOL_ONLY))
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_DYNAMIC_PROGRAMS=True, USE_DYNAMIC_WELCOME=True,
        ),
    )


def _fresh() -> Conversation:
    """A conversation as it is on the parent's very first message."""
    return Conversation(sender_id="first-turn", platform="messenger")


@pytest.mark.parametrize("message", [
    OFF_TOPIC_QUESTION, REGISTRATION_QUESTION, LOCATION_QUESTION, ONLINE_QUESTION,
])
def test_a_first_turn_question_is_not_answered_with_the_greeting(live_panel, message):
    assert parent_flow._maybe_static_welcome(_fresh(), message) is None, (
        "the parent asked a question — the greeting makes them repeat it"
    )


@pytest.mark.parametrize("message", PURE_GREETINGS)
def test_a_bare_greeting_still_gets_the_greeting(live_panel, message):
    assert parent_flow._maybe_static_welcome(_fresh(), message), (
        "a greeting is the right answer to a greeting"
    )


def test_a_bare_topic_word_keeps_its_shipped_behaviour(live_panel):
    assert parent_flow._maybe_static_welcome(_fresh(), BARE_TOPIC), (
        "a bare topic word is not a question; its menu contract is shipped behaviour"
    )


def test_a_closed_camp_does_not_rule_on_another_programmes_age_band(
    live_panel, monkeypatch,
):
    """Exposed by the fix above: once the question reaches the flow, the under-age
    handler answered „ბანაკი განკუთვნილია 9–17 წლის ბავშვებისთვის" — the CAMP's
    band, while the camp is ended and Sunday School (whose own brackets start at
    7) is what is on sale. An 8-year-old is INSIDE Sunday School's 7-8 bracket."""
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_DYNAMIC_PROGRAMS=True, USE_DYNAMIC_WELCOME=True,
            USE_PROGRAM_ISOLATION=True,
        ),
    )
    conv = _fresh()
    conv.segment = "PARENT"
    for message in ("6 წლის ბავშვს ვერ დავარეგისტრირებ?",
                    "8 წლის ბიჭისთვის ლიტერატურული კუთხით თუ გაქვთ ონლაინ კურსები"):
        answer = parent_flow._maybe_handle_out_of_range_age(conv, message)
        assert answer is None, (
            "the closed camp answered for the programme on sale: " + str(answer)
        )


def test_the_greeting_still_owns_the_turn_when_the_bot_has_not_replied_only(live_panel):
    """The welcome is a FIRST-turn rule: once the bot has replied it never fires,
    question or not — unchanged."""
    conv = _fresh()
    conv.history = [
        {"role": "user", "content": "გამარჯობა"},
        {"role": "assistant", "content": "გამარჯობა. რით შემიძლია დაგეხმაროთ?"},
    ]
    assert parent_flow._maybe_static_welcome(conv, OFF_TOPIC_QUESTION) is None
