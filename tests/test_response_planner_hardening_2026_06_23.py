"""Response Planner Hardening — intent-aware answers, PII-safe recall, human
tone (2026-06-23). Deterministic (no LLM, no network).

Covers the six live findings, fixed CENTRALLY via the Turn Intent Gateway +
a single PII chokepoint:
  A — the user's OWN phone is never echoed in clear (masked everywhere).
  B — a consultation request (typo-tolerant) never returns the registration link.
  C — adult-self (age + self-ref) captures adult_age → no redundant for-whom.
  D — a pure human-tone request gets a short ack, not a meta self-description.
  F — general-knowledge / insult never triggers an event search.
"""

from __future__ import annotations

import pytest

from app.reasoning.reasoning_layer import analyze_turn_intent
from app.flows import parent_flow
from app.services.conversation_service import _mask_user_phone_in_response
from app.models.conversation import Conversation
from app.models.lead import Lead


def _conv_with_phone(phone: str = "595999733") -> Conversation:
    c = Conversation(sender_id="rp", platform="instagram")
    c.lead = Lead(sender_id="rp", platform="instagram", segment="PARENT")
    c.lead.phone = phone
    return c


# ---------------------------------------------------------------------------
# A — PII-safe recall (central mask)
# ---------------------------------------------------------------------------
def test_mask_user_phone_full_number():
    c = _conv_with_phone()
    out = _mask_user_phone_in_response(c, "ნომერი 595999733 და 30 წლის ბრძანდებით")
    assert "595999733" not in out
    assert "595***733" in out


@pytest.mark.parametrize("text,expect", [
    ("595 999 733", "595***733"),
    ("595-99-97-33", "595***733"),
    ("+995595999733", "595***733"),
])
def test_mask_user_phone_formats(text, expect):
    c = _conv_with_phone()
    assert expect in _mask_user_phone_in_response(c, f"ნომერი: {text}")


def test_mask_does_not_touch_manager_phone():
    c = _conv_with_phone()
    out = _mask_user_phone_in_response(c, "მენეჯერის ნომერია: 558 67 47 33")
    assert out == "მენეჯერის ნომერია: 558 67 47 33"


def test_mask_is_idempotent_on_already_masked():
    c = _conv_with_phone()
    assert _mask_user_phone_in_response(c, "შენახულია: 595***733") == "შენახულია: 595***733"


def test_mask_noop_when_no_phone_on_lead():
    c = _conv_with_phone(phone="")
    # Nothing stored → nothing to mask (a bare number that is NOT the user's
    # stored phone is left as-is; only the user's OWN phone is guarded).
    assert _mask_user_phone_in_response(c, "ნომერი 595999733") == "ნომერი 595999733"


def test_state_recall_intent_typo_tolerant():
    # The live leak phrase had typos „ემზე"/„ინფრომაცია" — the gateway still
    # recognises it as a state-recall question.
    assert analyze_turn_intent("ემზე რა ინფრომაცია გაქვს?").is_state_recall is True
    assert analyze_turn_intent("ჩემი ნომერი იცი?").is_state_recall is True
    assert analyze_turn_intent("რა იცი ჩემზე?").is_state_recall is True


# ---------------------------------------------------------------------------
# B — consultation outranks registration link
# ---------------------------------------------------------------------------
def test_consultation_typo_does_not_return_registration_link():
    # „კოსულტაცია" (missing „ნ") must still defer — no registration link.
    assert parent_flow._is_camp_registration_link_request(
        "კი მინდა კოსულტაციაზე ჩაწერა მეორე შვილი 15 წლის ბანაკში"
    ) is False


def test_consultation_correct_spelling_defers():
    assert parent_flow._is_camp_registration_link_request(
        "ბანაკის კონსულტაციაზე ჩაწერა მინდა"
    ) is False


def test_explicit_camp_registration_still_returns_link():
    assert parent_flow._is_camp_registration_link_request(
        "ბანაკზე რეგისტრაცია მინდა"
    ) is True
    assert parent_flow._is_camp_registration_link_request(
        "ბანაკის რეგისტრაციის ბმული გამომიგზავნე"
    ) is True


def test_camp_information_is_not_registration():
    assert parent_flow._is_camp_registration_link_request(
        "ბანაკის შესახებ ინფორმაცია მინდა"
    ) is False


def test_gateway_flags_consultation_and_child_concern():
    t = analyze_turn_intent(
        "კი მინდა კოსულტაციაზე ჩაწერა მეორე შვილი 15 წლის უბრალოდ "
        "არაკომუნიკაბელური ბავშვია და უჭირს მეგობრების შეძენა"
    )
    assert t.is_consultation_request is True
    assert t.is_child_concern is True


# ---------------------------------------------------------------------------
# C — adult-self suppresses redundant for-whom
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("msg", [
    "მაინტერესებს ღონისძიებები ჩემთვის მინდა ვარ 30 წლის",
    "ჩემთვის მინდა 30 წლის ვარ და რა ღონისძიებები გაქვთ?",
])
def test_gateway_detects_adult_self(msg):
    t = analyze_turn_intent(msg)
    assert t.is_adult_self is True
    assert t.is_child_reference is False


def test_adult_self_not_flagged_for_child():
    t = analyze_turn_intent("ჩემი 12 წლის შვილისთვის ღონისძიება მინდა")
    assert t.is_adult_self is False
    assert t.is_child_reference is True


# ---------------------------------------------------------------------------
# D — human-tone request
# ---------------------------------------------------------------------------
def test_pure_tone_request_gets_short_ack():
    gw = parent_flow._turn_intent_gateway(
        "შეგიძლია ადამიანურად მელაპარაკო დაზეპირებული ტექსტების გარეშე?"
    )
    assert gw.is_human_tone_request is True
    ack = parent_flow._maybe_handle_human_tone_request(
        "შეგიძლია ადამიანურად მელაპარაკო დაზეპირებული ტექსტების გარეშე?", gw
    )
    assert ack is not None
    # No meta self-description / apology.
    assert "ვცდილობ" not in ack and "ბოდიშ" not in ack


def test_tone_request_with_business_question_defers():
    gw = parent_flow._turn_intent_gateway("ადამიანურად მელაპარაკე, ბანაკი რა ღირს?")
    # The engine must still answer the price → tone handler defers.
    assert parent_flow._maybe_handle_human_tone_request(
        "ადამიანურად მელაპარაკე, ბანაკი რა ღირს?", gw
    ) is None


# ---------------------------------------------------------------------------
# F — off-topic / insult never triggers event search
# ---------------------------------------------------------------------------
def test_general_knowledge_question_blocks_event_inquiry():
    t = analyze_turn_intent("მუფასა ვინაა?")
    assert t.is_off_topic is True
    assert t.block_event_inquiry is True
    assert t.clear_event_context is True


def test_event_question_about_entity_still_allowed():
    # „მუფასა ღონისძიება გაქვთ?" is a genuine event question → NOT off-topic.
    t = analyze_turn_intent("მუფასა ღონისძიება გაქვთ?")
    assert t.is_off_topic is False
    assert t.block_event_inquiry is False


def test_insult_blocks_event_inquiry():
    t = analyze_turn_intent("დებილი ხარ")
    assert t.is_insult is True
    assert t.block_event_inquiry is True


def test_offtopic_event_interceptor_gated_even_when_sticky():
    """After an event listing, a general-knowledge „მუფასა ვინაა?" must NOT
    re-fire the event search (the „ამ სახელით" symptom)."""
    c = Conversation(sender_id="rp2", platform="instagram")
    c.history = [
        {"role": "assistant", "content": "ხელმისაწვდომი ღონისძიებებია:\n— fromula 1"},
    ]
    assert parent_flow._bot_recently_listed_events(c) is True
    gw = parent_flow._turn_intent_gateway("მუფასა ვინაა?")
    assert parent_flow._maybe_handle_event_inquiry(c, "მუფასა ვინაა?", gw) is None


# ---------------------------------------------------------------------------
# Regression: the gateway still never raises
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [None, "", "🙂", "asdf 12 ??"])
def test_gateway_failclosed(bad):
    t = analyze_turn_intent(bad)
    assert t is not None
    assert t.block_event_inquiry in (True, False)
