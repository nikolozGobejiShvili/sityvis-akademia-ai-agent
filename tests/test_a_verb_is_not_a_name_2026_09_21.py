"""Live regression, 2026-09-21 — the manager was mailed a lead called „მყავს".

Surfaced while measuring whether a newly added programme works end to end. Mid
Sunday-School contact collection a parent wrote

    8 წლის ბავშვი მყავს          („I have an 8 year old child")

and the hand-off mail went out as

    საკვირაო სკოლა — ახალი მოთხოვნა — მყავს

Measured identical with and without this week's callback hand-off, so it is
older than that work.

WHY it happens, measured token by token. `_parse_name_phone` already rejects
every other word in that sentence — „8" is not a valid phone, „წლის" is an age
word, „ბავშვი" is a child word, both in `_NAME_REJECT_STEMS`. What survives is
„მყავს", a first-person verb, which no list had ever been told about. It carries
Georgian letters and sits under the token cap, so every gate said yes:

    _parse_name_phone('8 წლის ბავშვი მყავს') -> ('მყავს', '')
    is_valid_person_name('მყავს')            -> True
    _is_storable_person_name(...)            -> True
    _looks_like_contact_disclosure(...)      -> True

Two things are wrong, and both are already solved elsewhere in the same file.

1. „მყავს" is a verb. `_NAME_REJECT_STEMS` is exactly the list of verbs that are
   not names — it already holds „მომწერ", „დარეკ", „ჩაწერ", „გამომიგზავ", all
   added the same way after the same kind of live bug. This adds the one verb
   parents use constantly when they describe a child. No new mechanism, no new
   branch: one more entry in the data that already answers this question.

2. The Sunday-School capture had no age-sentence guard at all. The consultation
   capture has had one since 2026-06-27, added when „6 წლის არის მაგრამ 10 წლის
   ბავშვივით აზროვნებს" was stored as the name „მაგრამ აზროვნებს". The two paths
   parse the same messages; only one was protected. Restoring the symmetry closes
   the whole class, not just this sentence.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service
from app.services import notification_service as ns
from app.services import sheets_service

SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17,
          "price_text": "595 ლარი", "manager_contact": "599 00 11 20"}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended"}


# --------------------------------------------------------------------------
# The parser — no conversation, no panel.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "8 წლის ბავშვი მყავს",
    "10 წლის გოგონა მყავს",
    "ბავშვი მყავს 8 წლის",
    "ორი შვილი მყავს",
    "12 წლის ბიჭი მყავს",
])
def test_a_sentence_about_the_child_yields_no_name(text):
    name, _ = parent_flow._parse_name_phone(text)
    assert name == "", f"stored {name!r} as the parent's name"


def test_the_phone_is_still_taken_when_it_rides_along():
    """Rejecting the verb must not cost us the number."""
    name, phone = parent_flow._parse_name_phone("8 წლის ბავშვი მყავს 593535551")
    assert phone == "593535551"
    assert "მყავს" not in name


@pytest.mark.parametrize("text,expected", [
    ("ნანა", "ნანა"),
    ("593535551 ნანა", "ნანა"),
    ("ნანა 593535551", "ნანა"),
    ("ნინო ბერიძე 593535551", "ნინო ბერიძე"),
    ("მარიამი", "მარიამი"),
    ("ნანა მქვია", "ნანა"),
])
def test_real_names_are_untouched(text, expected):
    name, _ = parent_flow._parse_name_phone(text)
    assert name == expected


def test_the_verb_is_rejected_by_the_shared_validator():
    assert parent_flow.is_valid_person_name("მყავს") is False
    assert parent_flow.is_valid_person_name("ნანა") is True


@pytest.mark.parametrize("word", [
    "ერთი", "ორი", "სამი", "ოთხი", "ხუთი", "ათი",
])
def test_a_spelled_out_count_is_not_a_name(word):
    """Found while measuring the verb fix: with „მყავს" and „შვილი" rejected,
    „ორი შვილი მყავს" left the count standing as the name."""
    assert parent_flow.is_valid_person_name(word) is False


@pytest.mark.parametrize("name", ["ანა", "ნინო", "დავითი", "მარიამი", "ნანა"])
def test_real_names_are_not_caught_by_the_count_rule(name):
    assert parent_flow.is_valid_person_name(name) is True


# --------------------------------------------------------------------------
# The Sunday-School capture, which had no age guard at all.
# --------------------------------------------------------------------------

def _lead() -> Lead:
    return Lead(sender_id="s", platform="messenger", segment="PARENT")


def test_the_sunday_school_capture_stores_no_name_for_an_age_sentence():
    lead = _lead()
    parent_flow._ss_capture_contact(lead, "8 წლის ბავშვი მყავს")
    assert (lead.name or "") == ""


def test_the_sunday_school_capture_keeps_a_real_name():
    lead = _lead()
    parent_flow._ss_capture_contact(lead, "593535551 ნანა")
    assert lead.name == "ნანა"
    assert lead.phone == "593535551"


def test_the_older_description_sentence_is_covered_too():
    """The shape the consultation guard was written for, 2026-06-27."""
    lead = _lead()
    parent_flow._ss_capture_contact(
        lead, "6 წლის არის მაგრამ 10 წლის ბავშვივით აზროვნებს")
    assert (lead.name or "") == ""


# --------------------------------------------------------------------------
# End to end: the mail the manager receives.
# --------------------------------------------------------------------------

@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [dict(SCHOOL)])
    monkeypatch.setattr(
        admin_config_service, "load_sections",
        lambda *a, **k: [dict(CAMP_OFF), dict(SCHOOL)])
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda pid, *a, **k: (
            dict(SCHOOL) if pid == "sunday_school" else dict(CAMP_OFF)))
    monkeypatch.setattr(
        admin_config_service, "is_camp_registration_open", lambda *a, **k: False)
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    settings = dataclasses.replace(
        config_module.settings,
        USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True,
        USE_PARENT_LLM_ENGINE=True, USE_DYNAMIC_WELCOME=True,
        USE_RESERVED_PROGRAMS_DYNAMIC=True, USE_PER_PRODUCT_BOOKING=True,
        USE_CONSULTATION_PROGRAM_NAME=True,
    )
    monkeypatch.setattr(parent_flow, "settings", settings)
    monkeypatch.setattr(ns, "settings", settings)
    # A realistic model reply for the age sentence: it answers about the child
    # AND asks for the contact, which is what the prompt tells it to do. A bare
    # marker here would disarm the collection and make the chain look broken
    # when it is the stub that is unrealistic.
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: (
            "8 წლის ბავშვი ჯდება საკვირაო სკოლის ასაკობრივ ჩარჩოში 💙\n\n"
            "მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი."))
    sent: list[dict] = []
    monkeypatch.setattr(
        ns, "_send_email",
        lambda subject, body, **k: (
            sent.append({"subject": subject, "body": body}) or True))
    monkeypatch.setattr(ns, "_send_manager_whatsapp", lambda *a, **k: False)
    monkeypatch.setattr(
        sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    parent_flow._sunday_school_notified_senders.clear()
    return sent


def test_the_manager_is_mailed_the_parents_real_name(live):
    """The live sequence: the flow asks, the parent describes her child, then
    gives her contact. The name on the mail must be hers."""
    conv = Conversation(sender_id="verb", platform="messenger")
    conv.segment = "PARENT"
    conv.state = "DONE"
    conv.history = [
        {"role": "user", "content": "საკვირაო სკოლა მაინტერესებს"},
        {"role": "assistant",
         "content": parent_flow._render_sunday_school_answer()},
    ]
    for turn in ("8 წლის ბავშვი მყავს", "593535551 ნანა"):
        reply = str(parent_flow.handle(conv, turn))
        conv.history.append({"role": "user", "content": turn})
        conv.history.append({"role": "assistant", "content": reply})
    assert live, "no mail reached the manager"
    assert "მყავს" not in live[0]["subject"]
    assert "ნანა" in live[0]["subject"]
