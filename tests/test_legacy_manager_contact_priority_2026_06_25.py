"""Legacy mixed negative + explicit manager-contact request (live bug 2026-06-25).

Manual transcript:
  User : „უსაფრთხოების ზომები დაცულია ? ბავშვთან კომუნიკაციას შევძლებ ?"  → agent offers consultation
  User : „კონსულტაცია არ მინდა მენეჯერის ნომერი რომ მომწეროთ და მეთვითონ დავურეკავ"
  Bad  : „გასაგებია. თუ რამე შეიცვლება ან კითხვა გაგიჩნდებათ, მომწერეთ."   ← decline close
  Want : „მენეჯერის ნომერია: 558 67 47 33. შეგიძლიათ პირდაპირ დაუკავშირდეთ."

Root cause: the message contains TWO intents — decline the consultation AND ask
for the manager's number. The legacy decline handler („არ მინდა") fired BEFORE
the explicit-manager interceptor and cold-closed the conversation.

Fix (deterministic, intent-level — NO phrase handler, NO sections.yaml change,
planner/slim OFF):
  * parent_flow._maybe_handle_decline_engine defers when the message is a
    POSITIVE explicit manager-contact request (self-call intent OR
    manager+number with a give-me/write-me marker) → the existing
    _maybe_handle_explicit_manager_request discloses the number.
  * _render_manager_number_answer suppresses the „leave your number" callback
    offer on a self-call intent („მე თვითონ დავურეკავ").
  * reasoning.legacy_actions.detect_legacy_explicit_action promotes
    manager_contact above the generic decline / consultation stems.

Legacy mode: USE_PARENT_LLM_ENGINE=True, planner + slim OFF.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning.legacy_actions import detect_legacy_explicit_action
from app.services import conversation_service, messenger_service

_MANAGER_NUMBER = "558 67 47 33"
_DECLINE_CLOSE = "თუ რამე შეიცვლება ან კითხვა გაგიჩნდებათ"   # the cold-close text
_AGE_Q = ("რამდენი წლის", "რა წლისაა", "რომელ კლას", "ბავშვის ასაკი")
_ASK_OWN_NUMBER = "დატოვეთ თქვენი ნომერი"                    # callback offer (asks phone)


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    """Legacy mode: engine ON, planner + slim OFF (matches live .env)."""
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    # The engine is only reached for a genuine booking turn (test 6); make sure
    # a real OpenAI call never happens.
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: "კარგი, კონსულტაციას მოვაგვარებთ. რომელი დღე გირჩევნიათ?",
    )
    return swapped


def _conv(child_age: str = "", phone: str = "") -> Conversation:
    """A turn-2 PARENT conversation: an assistant turn already exists (so the
    static welcome bypass steps aside) and the agent has just offered a
    consultation — exactly the bug-transcript state."""
    conv = Conversation(sender_id="mgr-prio", platform="instagram", segment="PARENT")
    conv.state = "OFFER_BOOKING"
    conv.history.append(
        {"role": "assistant",
         "content": "შემიძლია უფასო კონსულტაცია შემოგთავაზოთ — გნებავთ ჩაგწეროთ?"},
    )
    conv.lead = Lead(
        sender_id="mgr-prio", platform="instagram", segment="PARENT",
        child_age=child_age, phone=phone,
    )
    return conv


def _no_age_question(text: str) -> bool:
    low = (text or "").lower()
    return not any(m in low for m in _AGE_Q)


# =====================================================================
# Required test 1 — Mixed decline + manager phone
# =====================================================================
def test_1_mixed_decline_and_manager_phone(engine_on):
    conv = _conv()
    out = parent_flow.handle(
        conv, "კონსულტაცია არ მინდა მენეჯერის ნომერი რომ მომწეროთ და მეთვითონ დავურეკავ",
    )
    assert _MANAGER_NUMBER in out                 # returns the manager phone
    assert _DECLINE_CLOSE not in out              # does NOT cold-close
    assert _ASK_OWN_NUMBER not in out             # does NOT ask for the user's phone
    assert _no_age_question(out)                  # does NOT ask child age


# =====================================================================
# Required test 2 — Decline only (unchanged)
# =====================================================================
def test_2_decline_only_unchanged(engine_on):
    conv = _conv()
    out = parent_flow.handle(conv, "კონსულტაცია არ მინდა")
    assert _DECLINE_CLOSE in out                  # polite decline behaviour unchanged
    assert _MANAGER_NUMBER not in out             # does NOT volunteer the manager phone


# =====================================================================
# Required test 3 — Manager phone direct
# =====================================================================
def test_3_manager_phone_direct(engine_on):
    conv = _conv()
    out = parent_flow.handle(conv, "მენეჯერის ნომერი მომწერეთ")
    assert _MANAGER_NUMBER in out
    assert _DECLINE_CLOSE not in out


# =====================================================================
# Required test 4 — „I will call myself" wording
# =====================================================================
def test_4_self_call_returns_manager_phone(engine_on):
    conv = _conv()
    out = parent_flow.handle(conv, "ნომერი მომეცით, მე თვითონ დავურეკავ")
    assert _MANAGER_NUMBER in out
    # They will call themselves → never ask for their number.
    assert _ASK_OWN_NUMBER not in out
    assert _no_age_question(out)


# =====================================================================
# Required test 5 — Registration link NOT broken
# =====================================================================
def test_5_registration_link_not_broken(engine_on):
    conv = _conv()
    out = parent_flow.handle(conv, "ბანაკის სარეგისტრაციო ლინკი მომწერე")
    # Returns the deterministic camp registration-link answer …
    assert out == parent_flow._render_camp_registration_answer()
    # … and never the manager phone.
    assert _MANAGER_NUMBER not in out


# =====================================================================
# Required test 6 — Booking NOT broken
# =====================================================================
def test_6_booking_not_broken(engine_on):
    conv = _conv()                                # unknown age → engine handles it
    out = parent_flow.handle(conv, "კი მინდა კონსულტაცია")
    assert _MANAGER_NUMBER not in out             # never the manager phone
    assert _DECLINE_CLOSE not in out              # never a cold-close
    assert "კონსულტაცი" in out                    # consultation flow continues


# =====================================================================
# Self-call wording — manager disclosure does not promise an unrequested call
# =====================================================================
def test_self_call_render_is_just_the_number():
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    answer = parent_flow._render_manager_number_answer(lead, self_call=True)
    assert _MANAGER_NUMBER in answer
    assert _ASK_OWN_NUMBER not in answer
    assert "შეგიძლიათ პირდაპირ დაუკავშირდეთ" in answer


def test_non_self_call_render_still_offers_callback():
    """Regression guard: the default (non-self-call) path is unchanged."""
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    answer = parent_flow._render_manager_number_answer(lead)
    assert _MANAGER_NUMBER in answer
    assert _ASK_OWN_NUMBER in answer


# =====================================================================
# „ნომერი არ მინდა" — declining the NUMBER itself still closes politely
# =====================================================================
def test_declining_the_number_itself_still_closes(engine_on):
    conv = _conv()
    out = parent_flow.handle(conv, "მენეჯერის ნომერი არ მინდა")
    assert _DECLINE_CLOSE in out                  # genuine decline → cold-close
    assert _MANAGER_NUMBER not in out             # never disclosed against the user's wish


# =====================================================================
# Detection layer — legacy_actions.detect_legacy_explicit_action priority
# =====================================================================
def test_detect_mixed_decline_plus_manager_is_manager_contact():
    out = detect_legacy_explicit_action(
        "კონსულტაცია არ მინდა მენეჯერის ნომერი რომ მომწეროთ და მე თვითონ დავურეკავ",
    )
    assert out["action"] == "camp_manager_contact"


def test_detect_decline_only_is_decline():
    out = detect_legacy_explicit_action("კონსულტაცია არ მინდა")
    assert out["action"] == "stop_or_decline"


def test_detect_manager_number_direct():
    out = detect_legacy_explicit_action("მენეჯერის ნომერი მომწერეთ")
    assert out["action"] == "camp_manager_contact"


def test_detect_self_call_with_number_is_manager_contact():
    out = detect_legacy_explicit_action("ნომერი მომეცით, მე თვითონ დავურეკავ")
    assert out["action"] == "camp_manager_contact"


def test_detect_manager_contact_outranks_consultation_stem():
    # „კონსულტ" stem present, but the explicit manager-number request wins.
    out = detect_legacy_explicit_action("კონსულტაცია არ მინდა, მენეჯერის ნომერი მომწერეთ")
    assert out["action"] == "camp_manager_contact"


def test_detect_adult_manager_contact_topic():
    out = detect_legacy_explicit_action("ღონისძიების მენეჯერის ნომერი მომწერეთ")
    assert out["action"] == "manager_contact"
    assert out["topic"] == "adult_event"


def test_detect_registration_link_not_manager_contact():
    out = detect_legacy_explicit_action("ბანაკის სარეგისტრაციო ლინკი მომწერე")
    assert out["action"] == "camp_registration_link"


def test_detect_consultation_request_not_manager_contact():
    out = detect_legacy_explicit_action("კი მინდა კონსულტაცია")
    assert out["action"] == "consultation_request"
