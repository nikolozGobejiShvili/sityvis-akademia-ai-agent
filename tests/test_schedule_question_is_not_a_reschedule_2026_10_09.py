"""A programme's schedule question is not a consultation reschedule (2026-10-09).

Live 2026-10-06 19:48 a Sunday-School parent asked „შაბათ კვირის გარდა სხვა
დღეს არ არის?" — whether the classes run on another day — and got „ვერ ვპოულობ
თქვენს აქტიურ კონსულტაციას. გთხოვთ, მომწერეთ თქვენი სახელი და საკონტაქტო
ნომერი, რომ მენეჯერმა გადატანაში დაგეხმაროთ." in 230 ms: the reschedule entry
read „სხვა დღეს" as „move my consultation to another day", and the model never
saw the turn. „სხვა დღეს" / „სხვა დროზე" left its word list; a reschedule still
says so with its own verb.
"""
from __future__ import annotations

import pytest

from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _no_network,
    world,
)

_ASKED = parent_flow._RESCHEDULE_NO_BOOKING_ASK
_SCHEDULE_QUESTIONS = (
    "შაბათ კვირის გარდა სხვა დღეს არ არის?",
    "სხვა დღეს ხომ არ გაქვთ ჯგუფი?",
    "სხვა დროზე თუ არის შეხვედრები?",
)


def _conv(booked: bool) -> Conversation:
    conv = Conversation(sender_id="r6-unit", platform="messenger")
    conv.segment = "PARENT"
    conv.lead = Lead(sender_id="r6-unit", platform="messenger", segment="PARENT")
    if booked:
        conv.lead.calendly_booked = True
        conv.lead.booked_datetime_iso = "2030-01-15T12:00:00+04:00"
    return conv


@pytest.mark.parametrize("booked", [False, True])
@pytest.mark.parametrize("message", _SCHEDULE_QUESTIONS)
def test_a_schedule_question_is_not_taken_for_a_reschedule(booked, message):
    assert parent_flow._maybe_handle_reschedule_intent_engine(_conv(booked), message) is None


@pytest.mark.parametrize("message", ["კონსულტაციის გადატანა მინდა", "გადავიტანოთ"])
def test_a_reschedule_said_with_its_own_verb_is_still_one(message):
    assert parent_flow._maybe_handle_reschedule_intent_engine(_conv(False), message) == _ASKED
    assert parent_flow._maybe_handle_reschedule_intent_engine(_conv(True), message) == (
        parent_flow._RESCHEDULE_ASK_NEW_TIME)


def test_the_sunday_school_parents_question_reaches_the_model(world):
    """The live conversation: Sunday School the one programme on sale, the
    parent asking about the class days. The model answers it."""
    world.panel("SS")
    world.say("საკვირაო სკოლა მაინტერესებს")
    reply = world.say("შაბათ კვირის გარდა სხვა დღეს არ არის?")
    assert reply == "გასაგებია.", reply   # the scripted model, not a canned reply
    assert "კონსულტაცი" not in reply
