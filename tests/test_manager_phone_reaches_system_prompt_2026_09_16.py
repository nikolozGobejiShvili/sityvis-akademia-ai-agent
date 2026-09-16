"""The system prompt's own `{manager_phone}` substitution is a SEPARATE call
from the per-turn `manager_phone=` context fact fixed 2026-09-15
(`_build_context_message`). `_build_system_prompt` computed its own
`manager_phone` with no `program_id`, so a stray model-composed
"unconfirmed detail" redirect could still hand over the CAMP's number in a
Sunday-School conversation even after that fix — because the prompt TEXT
itself (not just the per-turn fact block) carries the number, from a
completely separate call site.

The age band (`{age_min}`/`{age_max}`) in the SAME function is a DIFFERENT
case, left unchanged on purpose: every sentence that uses it explicitly
NAMES the camp ("ბანაკი {age_min}-{age_max} წლის...") in every prompt
variant. Supplying a different programme's band there would state a WRONG
fact about the camp, by name — that is not a fix, it is a new bug. Only
`manager_phone` sits in programme-agnostic wording ("ამ დეტალებს მენეჯერი
გაგაცნობთ: {manager_phone}"), so only it follows the active programme.

Georgian strings are built from code points so no letter can drift.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine as ple
from app.flows import parent_flow as pf
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service as acs

EN_DASH = chr(0x2013)


def ka(text: str) -> str:
    for ch in text:
        assert ord(ch) < 128 or 0x10D0 <= ord(ch) <= 0x10FF, repr(text)
    return text


SUMMER_PHONE = "558 67 47 33"
SCHOOL_PHONE = "599 00 11 20"
SCHOOL_NAME = ka("საკვირაო სკოლა")
INTERESTED = ka("მაინტერესებს")

CAMP_WORD = ka("ბანაკი")
SUMMER_NAME = ka("საზაფხულო " + CAMP_WORD)
SUMMER = {"id": "summer_camp", "type": "camp", "status": "active",
          "name": SUMMER_NAME, "hashtags": [CAMP_WORD],
          "manager_contact": SUMMER_PHONE,
          "age_min": 9, "age_max": 17, "registration_status": "open"}
SCHOOL = {"id": "sunday_school", "type": "kids_program", "status": "active",
          "name": SCHOOL_NAME, "manager_contact": SCHOOL_PHONE,
          "age_min": 7, "age_max": 17, "registration_status": "open"}


@pytest.fixture
def panel(monkeypatch):
    sections = [SUMMER, SCHOOL]
    monkeypatch.setattr(acs, "load_sections", lambda: [dict(s) for s in sections])
    monkeypatch.setattr(acs, "get_active_sections",
                        lambda: [dict(s) for s in sections])
    monkeypatch.setattr(acs, "get_section",
                        lambda pid: next((dict(s) for s in sections
                                          if s["id"] == pid), None))
    monkeypatch.setattr(acs, "load_manager_contacts_mirror", lambda: {})
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config_module.settings, USE_DYNAMIC_PROGRAMS=True))


def _conv(*user_turns: str) -> Conversation:
    conv = Conversation(sender_id="sp-phone", platform="messenger", segment="PARENT")
    conv.lead = Lead(sender_id="sp-phone", platform="messenger", segment="PARENT")
    history = []
    for text in user_turns:
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": "ok"})
    conv.history = history
    return conv


def test_system_prompt_carries_the_sunday_schools_own_number_not_the_camps(panel):
    conv = _conv(SCHOOL_NAME + " " + INTERESTED)
    prompt = ple._build_system_prompt(
        "", "PARENT", conversation=conv, lead=conv.lead,
    )
    assert SCHOOL_PHONE in prompt
    assert SUMMER_PHONE not in prompt


def test_system_prompt_still_carries_the_camps_number_for_a_camp_conversation(panel):
    conv = _conv(CAMP_WORD + " " + INTERESTED)
    prompt = ple._build_system_prompt(
        "", "PARENT", conversation=conv, lead=conv.lead,
    )
    assert SUMMER_PHONE in prompt


def test_system_prompt_defaults_to_the_camp_when_no_conversation_is_given(panel):
    # Every pre-existing caller (every test calling `_build_system_prompt()`
    # with no conversation at all) must stay byte-identical.
    prompt = ple._build_system_prompt()
    assert SUMMER_PHONE in prompt


def test_the_age_band_stays_the_camps_own_even_in_a_sunday_school_conversation(panel):
    # Deliberately unchanged: every sentence using {age_min}/{age_max} names
    # the camp by word ("ბანაკი"), so this fact must not follow the active
    # programme the way the phone does.
    conv = _conv(SCHOOL_NAME + " " + INTERESTED)
    prompt = ple._build_system_prompt(
        "", "PARENT", conversation=conv, lead=conv.lead,
    )
    assert f"9{EN_DASH}17" in prompt
