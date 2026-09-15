"""Each active programme has its OWN "manager contact" field in the admin
panel — confirmed live 2026-09-15: summer_camp=558 67 47 33,
sunday_school=599 00 11 20, set independently by the operator. But
`get_manager_phone()` read ONLY summer_camp's field (then a shared mirror,
then adult_events) — a leftover from the era when the camp was the only
programme. Every general-purpose caller used that one function with no
knowledge of which programme the conversation was actually about, so a
Sunday-School conversation's "unconfirmed detail" answers, and its explicit
"give me the manager's number" answers, disclosed the SUMMER CAMP's manager.

Proven live (Railway logs, deploy cddb60db, after yesterday's manager-phone
fix was already deployed):

    "მოწვეული სტუმრები ვინები არიან?"  (Sunday School) -> "...558 67 47 33..."
    "როგორ დავრეგისტრირდე?"            (Sunday School) -> "...558 67 47 33..."

both routed through `_build_context_message`'s `manager_phone=` turn fact,
which called the summer-camp-scoped function with no programme argument, even
though the SAME function, a few lines above it in the SAME function body,
already resolves `_active_program_id` for this exact conversation.

Fix: `get_manager_phone` takes an optional `program_id`, checking that
section's OWN `manager_contact` first (falling back to the existing
summer_camp -> mirror -> adult_events chain when empty or omitted, so every
caller that does not pass one is unaffected). The two general-purpose
callers -- the per-turn context fact, and the explicit "give me the number"
handler (and its callers) -- now pass the active programme's id.
Camp-specific handlers (transport, camp reservation fee, camp call/visit,
camp registration, camp_topic_facts.py) are UNCHANGED on purpose: a question
about the CAMP's own operations is the camp's manager's to answer, in a
multi-programme panel same as before.

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


def ka(text: str) -> str:
    for ch in text:
        assert ord(ch) < 128 or 0x10D0 <= ord(ch) <= 0x10FF, repr(text)
    return text


SUMMER_PHONE = "558 67 47 33"
SCHOOL_PHONE = "599 00 11 20"
SCHOOL_NAME = ka("საკვირაო სკოლა")
INTERESTED = ka("მაინტერესებს")
GUESTS_Q = ka("მოწვეული სტუმრები"
              " ვინები არიან?")


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


# ── the core function: additive, backward-compatible ───────────────────────

def test_no_program_id_keeps_the_old_summer_camp_first_behaviour(panel):
    assert acs.get_manager_phone() == SUMMER_PHONE


def test_a_programmes_own_number_wins_when_given(panel):
    assert acs.get_manager_phone("sunday_school") == SCHOOL_PHONE


def test_falls_back_to_the_default_chain_when_the_given_programme_has_none(panel, monkeypatch):
    monkeypatch.setattr(acs, "get_section",
                        lambda pid: {"id": pid} if pid == "adult_events" else
                        next((dict(s) for s in (SUMMER, SCHOOL) if s["id"] == pid), None))
    assert acs.get_manager_phone("adult_events") == SUMMER_PHONE


# ── the proven live bug: the per-turn fact now resolves per programme ──────

def _conv(*user_turns: str) -> Conversation:
    conv = Conversation(sender_id="ss-phone", platform="messenger", segment="PARENT")
    conv.lead = Lead(sender_id="ss-phone", platform="messenger", segment="PARENT")
    history = []
    for text in user_turns:
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": "ok"})
    conv.history = history
    return conv


def test_the_per_turn_manager_phone_fact_uses_the_active_programmes_own_number(panel):
    conv = _conv(SCHOOL_NAME + " " + INTERESTED)
    ctx = ple._build_context_message(conv, conv.lead, GUESTS_Q)
    assert ("manager_phone=" + SCHOOL_PHONE) in ctx
    assert ("manager_phone=" + SUMMER_PHONE) not in ctx


def test_a_camp_conversation_still_gets_the_camps_own_number(panel):
    conv = _conv(CAMP_WORD + " " + INTERESTED)
    ctx = ple._build_context_message(conv, conv.lead, GUESTS_Q)
    assert ("manager_phone=" + SUMMER_PHONE) in ctx


def test_no_programme_named_falls_back_to_the_default_chain(panel):
    conv = _conv()
    ctx = ple._build_context_message(conv, conv.lead, GUESTS_Q)
    assert ("manager_phone=" + SUMMER_PHONE) in ctx


# ── the explicit "give me the manager's number" handler ────────────────────

def test_explicit_manager_request_in_a_sunday_school_conversation_gives_its_own_number(panel):
    conv = _conv(SCHOOL_NAME + " " + ka("მაინტერესებს"))
    out = pf._render_manager_number_answer(conv.lead, conversation=conv)
    assert SCHOOL_PHONE in out
    assert SUMMER_PHONE not in out


def test_explicit_manager_request_with_no_conversation_keeps_old_behaviour(panel):
    lead = Lead(sender_id="x", platform="messenger", segment="PARENT")
    out = pf._render_manager_number_answer(lead)
    assert SUMMER_PHONE in out
