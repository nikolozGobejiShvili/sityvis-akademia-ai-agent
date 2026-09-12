"""A question was answered as though it were a phone number (live 2026-09-12).

    11:50  „საკვირაო სკოლის პედაგოგები ამინტერესებს"
           → „საკვირაო სკოლის გუნდი შედგება…"    an ordinary informational answer
    11:51  „სილაბუსი რომ მომწეროთ"
           → „მენეჯერს გადავცე — მომწერეთ ნომერი"   never reached the model
    11:53  „სილაბუსი რა იქნება?"
           → answered properly from the panel

Two conditions had to meet. `_bot_in_sunday_school_collection` decided the flow
was collecting a contact because the words „საკვირაო სკოლ" appeared in the bot's
OWN previous sentence — so any answer that named the programme armed it. And the
only thing that made the flow step aside mid-collection was a question mark,
which the 11:51 message did not have. Georgian parents often leave it out, so
the same question got two different answers two minutes apart.

Naming a programme is not asking for a number. Collection now arms only on the
messages this flow itself sends to ask or to offer — never on a reply written by
the model, whatever words it happens to use.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import response_policy
from app.services import admin_config_service as acs

# the real 11:50 reply: informational, opens with the programme's name
_PEDAGOGUES = (
    "საკვირაო სკოლის გუნდი შედგება გამოცდილი და მაღალკვალიფიციური "
    "ფსიქოლოგებისა და ლიტერატორებისგან."
)
_PRICE = "საკვირაო სკოლის ღირებულებაა 595 ლარი — 3-თვიანი მოდული."


@pytest.fixture
def panel(monkeypatch):
    section = {"id": "sunday_school", "status": "active",
               "name": "საკვირაო სკოლა"}
    monkeypatch.setattr(acs, "get_section",
                        lambda pid: dict(section) if pid == "sunday_school" else None)
    monkeypatch.setattr(acs, "get_active_sections", lambda: [dict(section)])
    monkeypatch.setattr(acs, "load_sections", lambda: [dict(section)])
    monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
    monkeypatch.setattr(parent_flow, "settings", dataclasses.replace(
        config_module.settings, USE_DYNAMIC_PROGRAMS=True))


def _conv(last_assistant: str) -> Conversation:
    conv = Conversation(sender_id="syl", platform="messenger", segment="PARENT")
    conv.lead = Lead(sender_id="syl", platform="messenger", segment="PARENT")
    conv.history = [
        {"role": "user", "content": "საკვირაო სკოლის პედაგოგები ამინტერესებს"},
        {"role": "assistant", "content": last_assistant},
    ]
    return conv


# ── the model's words never arm contact collection ─────────────────────────

@pytest.mark.parametrize("reply", [_PEDAGOGUES, _PRICE])
def test_an_answer_that_merely_names_the_programme_does_not_arm(panel, reply):
    assert parent_flow._bot_in_sunday_school_collection(_conv(reply)) is False


@pytest.mark.parametrize("message", [
    "სილაბუსი რომ მომწეროთ",            # the live one, no question mark
    "მოწვეული სტუმრები ვინები იქნებიან",
    "გასვლები სად ექნებათ კონკრეტულად",
])
def test_a_question_without_a_question_mark_still_reaches_the_model(panel, message):
    """A question mark was the only thing that saved these turns."""
    assert parent_flow._maybe_handle_sunday_school(_conv(_PEDAGOGUES), message) is None


# ── the flow's OWN invitations still arm it ────────────────────────────────

@pytest.mark.parametrize("asked", [
    "_SUNDAY_SCHOOL_ASK_PHONE",
    "_SUNDAY_SCHOOL_ASK_NAME",
    "_SUNDAY_SCHOOL_INVALID_PHONE",
    "_SUNDAY_SCHOOL_COMING_SOON",
    "_SUNDAY_SCHOOL_FAIL",
])
def test_the_flows_own_ask_arms_collection(panel, asked):
    assert parent_flow._bot_in_sunday_school_collection(
        _conv(getattr(parent_flow, asked))) is True


def test_the_consent_offers_arm_collection(panel):
    """The offers the consent-first policy sends — what the live flow uses."""
    for offer in (response_policy.SUNDAY_SCHOOL_CONSENT_OFFER_CONTACT_KNOWN,
                  response_policy.SUNDAY_SCHOOL_CONSENT_OFFER_CONTACT_UNKNOWN):
        reply = f"საკვირაო სკოლის დეტალები ზუსტდება. {offer}"
        assert parent_flow._bot_in_sunday_school_collection(_conv(reply)) is True


def test_a_phone_after_a_real_ask_is_still_captured(panel):
    conv = _conv(parent_flow._SUNDAY_SCHOOL_ASK_PHONE)
    assert parent_flow._maybe_handle_sunday_school(conv, "595999733") is not None


def test_success_ends_collection(panel):
    """After a handoff there is nothing left to collect."""
    assert parent_flow._bot_in_sunday_school_collection(
        _conv(parent_flow._SUNDAY_SCHOOL_SUCCESS)) is False


# ── the asks are read from the messages, not copied ────────────────────────

def test_the_asks_are_derived_from_the_messages_themselves(panel, monkeypatch):
    """Reword an ask and the detector follows — no second copy to keep in sync."""
    for ask in parent_flow._SUNDAY_SCHOOL_CONTACT_ASKS:
        assert ask, "an empty ask would arm on every reply"
        assert any(
            ask in getattr(parent_flow, name, "") or
            ask in getattr(response_policy, name, "")
            for name in (
                "_SUNDAY_SCHOOL_OFFER_TAIL", "_SUNDAY_SCHOOL_ASK_NAME",
                "_SUNDAY_SCHOOL_ASK_PHONE", "_SUNDAY_SCHOOL_INVALID_PHONE",
                "_SUNDAY_SCHOOL_COMING_SOON", "_SUNDAY_SCHOOL_FAIL",
                "_SUNDAY_SCHOOL_NOT_OFFERED",
                "SUNDAY_SCHOOL_CONSENT_OFFER_CONTACT_KNOWN",
                "SUNDAY_SCHOOL_CONSENT_OFFER_CONTACT_UNKNOWN",
            )
        ), f"{ask!r} is not part of any message this flow sends"
