"""Live regression, client Page 2026-09-20/21 — the manager's mail says „camp".

A parent talks about Sunday School, the booking does not complete, the agent
falls back to taking a name and number, and the hand-off mail reaches the
manager reading:

    მშობელი დაინტერესებულია ბანაკით — მთავარი ფოკუსი: …

Two live conversations of this exact shape: 2026-09-20 22:23 (the calendar had
no free slot the parent wanted, the agent took the contact instead) and
2026-09-21 13:31 (a Sunday-School intake question, contact taken). Neither
parent had mentioned the camp.

`_program_interest_phrase` resolves the programme from `consultation_program_
name`, then `program_id` — and when neither is set it returns the string
„ბანაკით". That default was written when the camp was the only product. It is
the same defect this week has closed everywhere else: the camp as the owner of
anything unattributed.

The rule, identical to the one in `_active_program_section` and
`_turn_belongs_to_the_camp`: a lead attributed to nothing belongs to the sole
programme on sale; with two or more on sale the mail names none and stays
neutral rather than guessing. Nothing about a lead that IS tagged changes.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.models.lead import Lead
from app.services import admin_config_service
from app.services import notification_service as ns

SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended"}
PARIS = {"id": "paris_camp", "name": "პარიზის ბანაკი", "type": "camp",
         "status": "active", "age_min": 10, "age_max": 17}
EVENTS = {"id": "adult_events", "name": "ზრდასრულთა ღონისძიებები",
          "type": "adult_events", "status": "active"}


def _lead(**kw) -> Lead:
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name = "სოფო"
    lead.phone = "599558844"
    lead.challenge = "ბავშვს უჭირს აზრის ჩამოყალიბება"
    for k, v in kw.items():
        setattr(lead, k, v)
    return lead


def _panel(monkeypatch, sections):
    active = [s for s in sections if (s.get("status") or "") == "active"]
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: list(active))
    monkeypatch.setattr(
        admin_config_service, "load_sections", lambda *a, **k: list(sections))
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda pid, *a, **k: next(
            (dict(s) for s in sections if s.get("id") == pid), {}))
    monkeypatch.setattr(
        ns, "settings",
        dataclasses.replace(config_module.settings, USE_PER_PRODUCT_BOOKING=True),
    )


# --------------------------------------------------------------------------
# The live fault.
# --------------------------------------------------------------------------

def test_an_untagged_lead_is_not_the_camps(monkeypatch):
    """Sunday School the one thing on sale, lead tagged to nothing — exactly the
    two live conversations."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    phrase = ns._program_interest_phrase(_lead())
    assert "ბანაკ" not in phrase, (
        "the manager was told the parent asked about the camp"
    )
    assert "საკვირაო სკოლა" in phrase


def test_the_summary_does_not_say_camp_either(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    summary = ns._build_parent_summary(_lead())
    assert "ბანაკ" not in summary


def test_the_handoff_mail_does_not_say_camp(monkeypatch):
    """End to end through the mail the manager actually receives."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    sent: dict[str, str] = {}
    monkeypatch.setattr(
        ns, "_send_email",
        lambda subject, body, **k: (sent.update(subject=subject, body=body) or True))
    monkeypatch.setattr(ns, "_send_manager_whatsapp", lambda *a, **k: False)
    ns.notify_manager_handoff(_lead(), "მშობელი ითხოვს მენეჯერთან დაკავშირებას")
    assert "ბანაკ" not in sent.get("body", "")
    assert "ბანაკ" not in sent.get("subject", "")


# --------------------------------------------------------------------------
# What must not move.
# --------------------------------------------------------------------------

def test_a_lead_tagged_to_the_camp_still_says_camp(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    phrase = ns._program_interest_phrase(
        _lead(program_id="summer_camp",
              consultation_program_name="საზაფხულო ბანაკი"))
    assert "საზაფხულო ბანაკი" in phrase


def test_a_tagged_lead_wins_over_the_sole_programme(monkeypatch):
    """The resolved name is still asked first — the panel only fills a gap."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    phrase = ns._program_interest_phrase(
        _lead(consultation_program_name="პარიზის ბანაკი"))
    assert "პარიზის ბანაკი" in phrase


def test_two_programmes_on_sale_name_neither(monkeypatch):
    """With a real choice, guessing is the defect — the mail stays neutral."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    phrase = ns._program_interest_phrase(_lead())
    assert "საკვირაო სკოლა" not in phrase
    assert "პარიზის ბანაკი" not in phrase
    assert "ბანაკ" not in phrase


def test_the_camp_alone_on_sale_still_names_the_camp(monkeypatch):
    """Camp the sole programme ⇒ an untagged lead is the camp's, unchanged."""
    _panel(monkeypatch, [dict(CAMP_OFF, status="active")])
    assert "ბანაკ" in ns._program_interest_phrase(_lead())


def test_adult_events_do_not_count_as_the_sole_programme(monkeypatch):
    """A PARENT lead is never handed to the adult catalogue: Sunday School plus
    adult events is still one CHILD programme on sale."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, EVENTS])
    assert "საკვირაო სკოლა" in ns._program_interest_phrase(_lead())


def test_nothing_on_sale_never_raises(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF])
    phrase = ns._program_interest_phrase(_lead())
    assert isinstance(phrase, str) and phrase


# --------------------------------------------------------------------------
# Two programmes on sale: the mail must name the one the parent was ACTUALLY
# talking about, not fall back to neutral wording.
#
# The operator's question, in their words: with Paris and Sunday School both
# open, a parent talks about Sunday School and leaves a number — does the mail
# still say camp, or does the agent look at which programme the conversation
# was about?
#
# It looks. `_resolve_consultation_program_name` reads the conversation, and the
# handoff path records the answer on the lead before the mail is built. These
# tests pin that end of the chain so the neutral fallback above stays what it
# is — a last resort for a conversation that named nothing, not the normal case.
# --------------------------------------------------------------------------

def _history(*turns):
    return [{"role": r, "content": c} for r, c in turns]


SCHOOL_TALK = _history(
    ("user", "გამარჯობა"),
    ("assistant", "გამარჯობა 💙 რით შემიძლია დაგეხმაროთ?"),
    ("user", "საკვირაო სკოლა მაინტერესებს"),
    ("assistant", "საკვირაო სკოლა 3-თვიანი პროგრამაა."),
    ("user", "8 წლის ბავშვი მყავს"),
    ("assistant", "ჯდება 7-8 წლის ჯგუფში."),
    ("user", "მენეჯერთან დამაკავშირეთ"),
)
PARIS_TALK = _history(
    ("user", "გამარჯობა"),
    ("assistant", "გამარჯობა 💙"),
    ("user", "პარიზის ბანაკი მაინტერესებს"),
    ("assistant", "პარიზის ბანაკი 10-დღიანია."),
    ("user", "12 წლის ბავშვი მყავს"),
    ("assistant", "ჯდება."),
    ("user", "მენეჯერთან დამაკავშირეთ"),
)


def _resolved_phrase(monkeypatch, history):
    """The real chain: resolve the programme from the conversation, record it on
    the lead the way the handoff path does, then ask the mail builder."""
    from app.flows import parent_flow
    from app.models.conversation import Conversation

    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True,
            USE_PER_PRODUCT_BOOKING=True, USE_CONSULTATION_PROGRAM_NAME=True,
            USE_RESERVED_PROGRAMS_DYNAMIC=True,
        ),
    )
    conv = Conversation(sender_id="r", platform="messenger")
    conv.segment = "PARENT"
    conv.history = history
    lead = _lead()
    resolved = parent_flow._resolve_consultation_program_name(
        conv, lead, extra_text="599558844 სოფო")
    if resolved:
        lead.consultation_program_name = resolved
    return resolved, ns._program_interest_phrase(lead)


def test_a_sunday_school_conversation_is_named_in_the_mail(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    resolved, phrase = _resolved_phrase(monkeypatch, SCHOOL_TALK)
    assert resolved == "საკვირაო სკოლა"
    assert "საკვირაო სკოლა" in phrase
    assert "ბანაკ" not in phrase


def test_a_paris_conversation_is_named_in_the_mail(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    resolved, phrase = _resolved_phrase(monkeypatch, PARIS_TALK)
    assert resolved == "პარიზის ბანაკი"
    assert "პარიზის ბანაკი" in phrase
    assert "საზაფხულო" not in phrase


def test_a_conversation_that_named_nothing_stays_neutral(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    resolved, phrase = _resolved_phrase(
        monkeypatch,
        _history(("user", "გამარჯობა"),
                 ("assistant", "გამარჯობა 💙"),
                 ("user", "მენეჯერთან დამაკავშირეთ")))
    assert not resolved
    assert "ბანაკ" not in phrase
