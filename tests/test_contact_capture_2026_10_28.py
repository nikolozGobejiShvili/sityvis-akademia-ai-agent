"""Contact capture when a parent names two people, and the outage ask (2026-10-28).

Live: asked for name, number and time, a parent sent the number, then the
names of the mother and the grandmother in one message — „<name> <surname>
(დედა)" on one line, „<name> <surname> (ბებია)" on the next. Read as one run
it was a 5-token „name" and was dropped; the model then gave an empty answer,
and the no-answer reply asked for „სახელი და საკონტაქტო ნომერი" — the number
a second time — although the number had been saved a turn earlier.
"""
from __future__ import annotations

import pytest

from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


@pytest.mark.parametrize("text,name", [
    ("ნინო ბერიძე(დედა)\nთამარ ბერიძე (ბებია)", "ნინო ბერიძე"),
    ("ნინო (დედა)", "ნინო"),
    ("გამარჯობა\nნინო ბერიძე", "ნინო ბერიძე"),
    # a correction across lines still wins over „the first line"
    ("ლიზი\nარა ნინო", "ნინო"),
])
def test_the_first_person_named_is_the_contact(text, name):
    assert parent_flow._parse_name_phone(text)[0] == name


def test_a_name_and_a_number_on_separate_lines_are_both_read():
    assert parent_flow._parse_name_phone("ნინო ბერიძე\n595123456") == ("ნინო ბერიძე", "595123456")


def _conversation(last_reply: str, *, phone: str = "", name: str = "") -> Conversation:
    conv = Conversation(sender_id="cc-1028", platform="messenger")
    conv.segment = "PARENT"
    conv.history = [{"role": "assistant", "content": last_reply}]
    conv.lead = Lead(sender_id="cc-1028", platform="messenger", segment="PARENT",
                     phone=phone, name=name)
    return conv


@pytest.fixture
def _camp_over(monkeypatch):
    monkeypatch.setattr(parent_flow, "_camp_is_not_active", lambda: True)


def test_the_no_answer_reply_asks_only_for_the_name_when_the_number_is_known(_camp_over):
    conv = _conversation("ნომერი მივიღე. მომწერეთ თქვენი სახელი, რომ კონსულტაცია ჩავნიშნოთ.",
                         phone="905321234567")
    reply = parent_flow._engine_unavailable_reply(conv, "კარგით")
    assert reply == parent_flow._OUTAGE_ASK_NAME


def test_the_no_answer_reply_still_asks_for_both_when_neither_is_known(_camp_over):
    conv = _conversation("გსურთ, კონსულტაცია ჩავნიშნოთ?")
    assert parent_flow._engine_unavailable_reply(conv, "კარგით") == parent_flow._OUTAGE_ASK_CONTACT
