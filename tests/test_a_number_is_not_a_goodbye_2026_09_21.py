"""Live regression, client Page 2026-09-21 19:42 — a phone number was read as
a goodbye and the lead was lost.

A parent asked for the manager, was told the number and invited to leave her
own, and sent three messages seven seconds apart:

    593535551
    nana
    madloba + heart

The debounce buffer merges fragments that arrive together, so the agent saw one
turn: "593535551 nana madloba". `_is_thanks_or_farewell_close` counts words and
looks for PROCEED words (ki, minda, chamtseret, nomeri...); it found none, the
turn was six words or fewer, and it closed the conversation warmly. The name and
the number were never stored and the manager was never told.

Railway, deployment 9831eac9:

    19:42:31  out  „the manager's number is 599 00 11 20 ... leave yours"
    19:42:47  in   „593535551"
    19:42:49  in   „nana"
    19:42:54  in   „madloba"
    19:42:59  [message_buffer] 3 fragments -> „593535551 nana madloba"
    19:42:59  out  „thank you, write if you need anything else"

Removing only the trailing thanks makes the same turn work, which is what
identifies the gate: „593535551 nana" IS captured, name and phone both.

The predicate asks whether a proceed WORD is present. A phone number is a
proceed FACT — the strongest one there is. Someone handing over their number is
not saying goodbye, whatever polite word rides along with it. This adds that
fact to the check and nothing else: a thanks or farewell carrying no number
closes exactly as before.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.services import admin_config_service
from app.services import notification_service as ns
from app.services import sheets_service

SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17,
          "price_text": "595 ლარი", "manager_contact": "599 00 11 20"}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended"}

# The agent's own words on the turn before, verbatim from the Railway log.
ASKED_FOR_NUMBER = (
    "მენეჯერის ნომერია: 599 00 11 20. შეგიძლიათ პირდაპირ დაუკავშირდეთ. "
    "თუ გირჩევნიათ, დატოვეთ თქვენი ნომერი და მენეჯერი თავად დაგიკავშირდებათ."
)
# The merged turn the agent actually received.
LIVE_TURN = "593535551 ნანა მადლობა💚"


# --------------------------------------------------------------------------
# The predicate itself — no panel, no engine, no conversation.
# --------------------------------------------------------------------------

def test_the_live_turn_is_not_a_goodbye():
    assert parent_flow._is_thanks_or_farewell_close(LIVE_TURN) is False


def test_a_number_with_thanks_and_no_name_is_not_a_goodbye():
    assert parent_flow._is_thanks_or_farewell_close("593535551 მადლობა") is False


def test_the_second_live_shape_is_not_a_goodbye():
    """2026-09-20 18:20, the same evening — same shape, same loss."""
    assert parent_flow._is_thanks_or_farewell_close(
        "555449474 ირინე მადლობა") is False


def test_a_number_with_a_farewell_is_not_a_goodbye_either():
    assert parent_flow._is_thanks_or_farewell_close(
        "კარგად 593535551") is False


# --------------------------------------------------------------------------
# What must not move: a close with no number still closes.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "მადლობა💚",
    "მადლობა",
    "დიდი მადლობა ინფორმაციისთვის",
    "გმადლობთ",
    "ნახვამდის",
    "მშვიდობით",
    "კარგად",
    "მერე მოგწერთ",
])
def test_a_real_close_still_closes(text):
    assert parent_flow._is_thanks_or_farewell_close(text) is True


@pytest.mark.parametrize("text", [
    "მადლობა, 2 შვილი მყავს",      # a digit that is not a phone
    "მადლობა, 8 წლისაა",
    "გმადლობთ, 12 შეხვედრაა?",     # a question was never a close
])
def test_a_digit_that_is_not_a_phone_does_not_change_the_verdict(text):
    """The new fact is a PHONE, not any number — an age or a count must not
    start keeping a genuine thank-you open."""
    expected = "?" not in text
    assert parent_flow._is_thanks_or_farewell_close(text) is expected


@pytest.mark.parametrize("text", [
    "კი, მადლობა",
    "მადლობა, ჩამწერეთ",
    "მადლობა, მენეჯერის ნომერი რომ მომწეროთ",
])
def test_a_proceed_word_still_wins(text):
    """The existing proceed-word escape is untouched."""
    assert parent_flow._is_thanks_or_farewell_close(text) is False


# --------------------------------------------------------------------------
# The live turn through the real chain.
# --------------------------------------------------------------------------

def _panel(monkeypatch):
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
    live = dataclasses.replace(
        config_module.settings,
        USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True,
        USE_PARENT_LLM_ENGINE=True, USE_DYNAMIC_WELCOME=True,
        USE_RESERVED_PROGRAMS_DYNAMIC=True, USE_PER_PRODUCT_BOOKING=True,
        USE_CONSULTATION_PROGRAM_NAME=True,
    )
    monkeypatch.setattr(parent_flow, "settings", live)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely", lambda c, m: "[ENGINE]")
    # This turn answers a callback the flow promised, so the hand-off fires —
    # captured here so no test reaches a real transport.
    monkeypatch.setattr(ns, "_send_email", lambda *a, **k: True)
    monkeypatch.setattr(ns, "_send_manager_whatsapp", lambda *a, **k: False)
    monkeypatch.setattr(
        sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    parent_flow._sunday_school_notified_senders.clear()


def _conversation() -> Conversation:
    conv = Conversation(sender_id="nana", platform="messenger")
    conv.segment = "PARENT"
    conv.state = "DONE"
    conv.history = [
        {"role": "user",
         "content": "მე დავუკავშირდები. მადლობა. 12 წლის რომ დავარეგისტრირო"},
        {"role": "assistant", "content": ASKED_FOR_NUMBER},
    ]
    return conv


def test_the_live_turn_stores_the_name_and_the_number(monkeypatch):
    _panel(monkeypatch)
    conv = _conversation()
    parent_flow.handle(conv, LIVE_TURN)
    lead = conv.lead
    assert lead is not None, "the turn closed the conversation, no lead was made"
    assert (lead.phone or "") == "593535551"
    assert (lead.name or "") == "ნანა"


def test_the_live_turn_no_longer_answers_with_a_goodbye(monkeypatch):
    _panel(monkeypatch)
    reply = str(parent_flow.handle(_conversation(), LIVE_TURN))
    assert "თუ კიდევ დაგჭირდებათ ინფორმაცია" not in reply


def test_a_thank_you_alone_still_gets_the_warm_close(monkeypatch):
    """The 2026-06-29 client hotfix this predicate exists for — unchanged."""
    _panel(monkeypatch)
    reply = str(parent_flow.handle(_conversation(), "მადლობა💚"))
    assert "თუ კიდევ დაგჭირდებათ ინფორმაცია" in reply
