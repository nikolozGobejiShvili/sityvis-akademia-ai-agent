"""The camp answered in another programme's conversation (live 2026-09-12).

A parent spent nine turns on Sunday School — the syllabus, group sizes, lesson
length — and then asked:

    „ჩემი შვილი 6 წლის არის და შევძლებ მოყვანას?"

    → „ბანაკში მონაწილეობა შესაძლებელია 9–17 წლის ბავშვებისთვის.
       ამ ასაკისთვის ბანაკში ჩაწერას ვერ შემოგთავაზებთ."

    07:34:18 [parent_flow] ineligible-young deterministic message
             (child_age='6', bounds=9-17)

Sunday School takes children from 7 and runs a 7-8 group, and the camp was not
running at all. `_ensure_ineligible_young_age_message` replaced the reply
whenever a child's age fell below the CAMP's minimum — on any turn, in any
conversation, active camp or not.

It was the last of three layers that let an age decide something. The other two
went on 2026-09-11 (`book_consultation`'s `age_not_eligible` and the CTA
scrubber); this one was kept on the grounds that it only stated a fact about the
camp. It did not — it answered FOR the camp somewhere the camp had no business
being. All three are now gone.
"""
from __future__ import annotations

import dataclasses
import io
import re

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service as acs

_SCHOOL = {"id": "sunday_school", "type": "kids_program", "status": "active",
           "name": "საკვირაო სკოლა", "age_min": 7, "age_max": 17,
           "registration_status": "open",
           "description_short": "3-თვიანი პროგრამა — 12 შეხვედრა."}
_CAMP = {"id": "summer_camp", "type": "camp", "status": "ended",
         "name": "საზაფხულო ბანაკი", "hashtags": ["ბანაკი"],
         "age_min": 9, "age_max": 17, "registration_status": "closed"}


@pytest.fixture
def panel(monkeypatch):
    def _install(sections=(_SCHOOL, _CAMP)):
        sections = list(sections)
        monkeypatch.setattr(acs, "load_sections",
                            lambda: [dict(s) for s in sections])
        monkeypatch.setattr(acs, "get_active_sections",
                            lambda: [dict(s) for s in sections
                                     if s.get("status") == "active"])
        monkeypatch.setattr(acs, "get_section",
                            lambda pid: next((dict(s) for s in sections
                                              if s["id"] == pid), None))
        monkeypatch.setattr(acs, "get_camp_age_bounds", lambda: (9, 17))
        monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
        monkeypatch.setattr(parent_flow, "settings", dataclasses.replace(
            config_module.settings, USE_DYNAMIC_PROGRAMS=True,
            USE_PROGRAM_AUDIENCE=True))
    return _install


def _school_conversation(age: str = "6") -> Conversation:
    conv = Conversation(sender_id="leak", platform="messenger",
                        segment="PARENT")
    conv.lead = Lead(sender_id="leak", platform="messenger", segment="PARENT",
                     child_age=age)
    conv.state = "DONE"
    conv.history = [
        {"role": "user", "content": "საკვირაო სკოლის დეტალები მაინტერესებს"},
        {"role": "assistant",
         "content": "3-თვიანი პროგრამა — 12 ინტერაქციული შეხვედრა."},
        {"role": "user", "content": "ჯგუფში რამდენი ბავშვი არის?"},
        {"role": "assistant",
         "content": "მაქსიმუმ 15. ჯგუფები: 7-8, 9-10, 11-12, 13-14, 15-16-17."},
    ]
    return conv


# ── the layer is gone, and cannot come back unnoticed ──────────────────────

def test_the_replacement_no_longer_exists():
    assert not hasattr(parent_flow, "_ensure_ineligible_young_age_message")
    assert not hasattr(parent_flow, "_INELIGIBLE_YOUNG_MESSAGE_TEMPLATE")


def test_no_age_refusal_layer_survives_in_the_source():
    """All three layers let an age decide. A fourth must not appear quietly."""
    src = io.open(parent_flow.__file__, encoding="utf-8").read()
    # the sentence the live leak sent
    assert "ჩაწერას ვერ შემოგთავაზებთ" not in src
    assert "_INELIGIBLE_CTA_PATTERNS" not in src


# ── what the parent gets now ───────────────────────────────────────────────

def test_a_young_age_does_not_pull_the_camp_into_a_school_conversation(panel):
    """The live turn. The reply the flow was given must survive intact."""
    panel()
    conv = _school_conversation(age="6")
    reply = ("საკვირაო სკოლა 7 წლიდან იღებს ბავშვებს — 6 წლის ასაკი ჯერ "
             "არ ჯდება ჯგუფებში.")
    out = parent_flow._strip_consultation_cta_if_ineligible(conv, reply)
    assert out == reply
    assert "ბანაკ" not in out
    assert "9–17" not in out and "9-17" not in out


@pytest.mark.parametrize("age", ["4", "6", "8", "18", "19"])
def test_no_age_rewrites_the_reply(panel, age):
    panel()
    conv = _school_conversation(age=age)
    reply = "საკვირაო სკოლის შესახებ დეტალები ასეთია."
    assert parent_flow._strip_consultation_cta_if_ineligible(conv, reply) == reply


def test_the_camp_still_answers_its_own_conversation(panel):
    """Deleting the layer must not silence the camp where the camp IS the
    subject — that answer comes from the camp-status path, not from an age."""
    panel()
    out = parent_flow._camp_over_line()
    assert "საზაფხულო ბანაკი" in out
