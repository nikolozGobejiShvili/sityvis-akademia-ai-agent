"""Reasoning Layer Phase 2 — central Turn Intent Gateway (2026-06-23).

The gateway (`reasoning_layer.analyze_turn_intent`) is a DETERMINISTIC, metadata-
only classifier that runs before the sticky domain handlers so they cannot
consume the wrong message. It NEVER answers the user, invents facts, or causes
side effects. It is ALWAYS-ON (independent of `USE_REASONING_LAYER`, which still
gates the Phase-1 `analyze_parent_turn` decline-defer).

These tests prove the live-test failures are fixed at the gateway level and that
the parent_flow integration gates the event interceptor:
  * „29 წლის" is an AGE, never a calendar day → no „29 რიცხვში".
  * a DECLINE after an event list is honoured → no „ამ სახელით" loop.
  * a topic switch (camp / Sunday-School / manager) clears the event context.
All deterministic (no LLM, no network).
"""

from __future__ import annotations

import dataclasses

import pytest

from app.reasoning import reasoning_layer
from app.reasoning.reasoning_layer import analyze_turn_intent, TurnIntent
from app.flows import parent_flow
from app.models.conversation import Conversation


def _conv_with_event_listing() -> Conversation:
    """A conversation whose last assistant turn was an active-events listing,
    so `_bot_recently_listed_events` is sticky-true (the live loop condition)."""
    c = Conversation(sender_id="gw-test", platform="instagram")
    c.history = [
        {"role": "user", "content": "ღონისძიება მაინტერესებს"},
        {"role": "assistant",
         "content": "ამ ეტაპზე ხელმისაწვდომი ღონისძიებებია:\n— fromula 1"},
    ]
    return c


# ---------------------------------------------------------------------------
# PART I.1/I.2/I.3 — age vs date
# ---------------------------------------------------------------------------
def test_age_statement_is_age_not_date():
    t = analyze_turn_intent("მე ვარ 29 წლის და მინდა ღონისძიებებს გავეცნო")
    assert t.age == 29
    assert t.date_text is None                     # the age-vs-date guarantee
    assert t.is_age_statement is True
    # Surgical narrowing (2026-06-24): an ADULT-EVENT age statement is NO LONGER
    # blocked just because it states an age — the age-as-date protection now
    # lives in date_text (None above) + the day-extractor's own guard, NOT in a
    # blanket block of event inquiry. (Non-event age statements still block —
    # see test_age_correction_still_blocks_event_lookup.)
    assert t.block_event_inquiry is False
    assert t.segment == "adult"
    assert t.topic == "adult_event"


def test_age_correction_still_blocks_event_lookup():
    t = analyze_turn_intent("29 წლის ვარ მე, შენ ალბათ რიცხვი გეგონა")
    assert t.age == 29
    assert t.date_text is None
    assert t.block_event_inquiry is True           # no „29 რიცხვში" repeat


def test_real_calendar_date_allows_event_lookup():
    t = analyze_turn_intent("29 აგვისტოს ღონისძიება არის?")
    assert t.date_text == "29"
    assert t.age is None
    assert t.block_event_inquiry is False          # date lookup allowed


def test_extract_event_day_age_guard():
    assert parent_flow._extract_event_day_reference("მე ვარ 29 წლის") is None
    assert parent_flow._extract_event_day_reference("29 აგვისტოს ღონისძიება") == 29
    assert parent_flow._extract_event_day_reference("16-ში ღონისძიებაა") == 16
    assert parent_flow._extract_event_day_reference("14 წლის შვილი") is None


# ---------------------------------------------------------------------------
# PART I.4/I.5/I.6/I.7 — decline + topic switch clear the sticky event context
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("msg", [
    "მადლობა არ მინდა",
    "აღარ მინდამადლობა",
    "აღარ მინდა",
    "არა მადლობა",
    "აღარ მაინტერესებს",
    "არ მინდა ღონისძიება",
])
def test_decline_blocks_and_clears_event_context(msg):
    t = analyze_turn_intent(msg)
    assert t.is_decline is True
    assert t.block_event_inquiry is True
    assert t.clear_event_context is True


def test_decline_gates_event_interceptor_even_when_sticky():
    """After the bot listed events, a decline must NOT re-fire the event search
    (the live loop). The gateway-gated interceptor returns None → the decline
    flows to the decline handler."""
    conv = _conv_with_event_listing()
    assert parent_flow._bot_recently_listed_events(conv) is True
    gw = parent_flow._turn_intent_gateway("მადლობა არ მინდა")
    assert parent_flow._maybe_handle_event_inquiry(conv, "მადლობა არ მინდა", gw) is None


def test_camp_topic_switch_clears_event_context():
    t = analyze_turn_intent("ბანაკის ფასი რა არის?")
    assert t.clear_event_context is True            # event context cleared
    assert t.topic == "price"


def test_sunday_school_blocks_event_inquiry():
    t = analyze_turn_intent("საკვირაო სკოლა მაინტერესებს")
    assert t.topic == "sunday_school"
    assert t.block_event_inquiry is True
    assert t.clear_event_context is True


def test_decline_plus_topic_switch_answers_new_topic():
    t = analyze_turn_intent("არ მინდა, ბანაკის ფასი რა არის?")
    assert t.is_decline is True
    assert t.intent == "topic_switch"
    assert t.clear_event_context is True


# ---------------------------------------------------------------------------
# PART I.8/I.9/I.10 — parent→adult event interest (engine handles the answer)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("msg", [
    "ჩემთვის მინდა ღონისძიება",
    "ბავშვისთვის არა, ჩემთვის ღონისძიება მინდა",
    "ზრდასრულებისთვის რა გაქვთ?",
])
def test_adult_event_interest_not_blocked_routes_to_engine(msg):
    t = analyze_turn_intent(msg)
    # The gateway must NOT block the engine's adult handling, and must not
    # mis-classify these as a calendar-day event lookup.
    assert t.block_event_inquiry is False
    assert t.date_text is None


# ---------------------------------------------------------------------------
# PART I.12/I.13 — affirmation, manager self-call
# ---------------------------------------------------------------------------
def test_affirmation_is_not_blocked_and_not_a_name():
    t = analyze_turn_intent("კი მინდა")
    assert t.is_affirmation is True
    assert t.block_event_inquiry is False
    assert t.intent == "affirm"


def test_self_call_manager_phone_request():
    t = analyze_turn_intent("მე თვითონ დავურეკავ, მენეჯერის ნომერი მომწერე")
    assert t.is_manager_phone_request is True
    assert t.topic == "manager_contact"
    assert t.block_event_inquiry is True
    assert t.requested_action == "give_manager_phone"


# ---------------------------------------------------------------------------
# PART I.15/I.16 — contact / action phrase
# ---------------------------------------------------------------------------
def test_single_phone_recognised_as_contact():
    t = analyze_turn_intent("nika 595999733")
    assert t.phone == "595999733"
    assert t.block_event_inquiry is False


def test_action_phrase_is_not_misrouted_to_event():
    t = analyze_turn_intent("ხვალ დაგირეკავთ")
    assert t.block_event_inquiry is False
    assert t.phone is None


# ---------------------------------------------------------------------------
# PART I.18/I.19 — metadata only, no side effects, no user text
# ---------------------------------------------------------------------------
def test_gateway_returns_metadata_only():
    t = analyze_turn_intent("მე ვარ 29 წლის და ღონისძიება მინდა")
    assert isinstance(t, TurnIntent)
    d = t.to_dict()
    assert isinstance(d, dict)
    # No user-facing answer field — metadata only.
    assert "answer" not in d
    assert set(d).issuperset({"segment", "topic", "intent", "block_event_inquiry"})


def test_gateway_does_not_mutate_conversation():
    conv = _conv_with_event_listing()
    before = dataclasses.asdict(conv)
    gw = parent_flow._turn_intent_gateway("მადლობა არ მინდა")
    parent_flow._maybe_handle_event_inquiry(conv, "მადლობა არ მინდა", gw)
    after = dataclasses.asdict(conv)
    assert before == after  # the gateway / gated interceptor mutate nothing


# ---------------------------------------------------------------------------
# PART I.20/I.21 — fail-closed + flag independence
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [None, "", "asdf qwerty 12 ??", "🙂🙂🙂"])
def test_gateway_never_raises_failclosed(bad):
    t = analyze_turn_intent(bad)
    assert isinstance(t, TurnIntent)


def test_gateway_whitespace_only_is_low_confidence():
    t = analyze_turn_intent("   ")
    assert t.confidence == 0.0
    assert t.block_event_inquiry is False


def test_gateway_is_flag_independent(monkeypatch):
    """The Phase-2 gateway is always-on (deterministic). It must classify the
    same regardless of USE_REASONING_LAYER (which only gates Phase-1)."""
    from app import config as config_module
    base = config_module.settings
    for flag in (False, True):
        monkeypatch.setattr(
            config_module, "settings",
            dataclasses.replace(base, USE_REASONING_LAYER=flag),
        )
        t = analyze_turn_intent("მე ვარ 29 წლის და ღონისძიება მინდა")
        # adult-event age statement is not blocked (2026-06-24 narrowing); the
        # point of this test is flag-independence — the result is identical for
        # both USE_REASONING_LAYER values.
        assert t.age == 29 and t.block_event_inquiry is False


def test_phase1_analyzer_unchanged():
    """Phase-1 `analyze_parent_turn` / `ReasoningAnalysis` still exists and is
    untouched (backward compat for the existing decline-defer wiring)."""
    a = reasoning_layer.analyze_parent_turn("არ მინდა, ფასი მაინტერესებს")
    assert isinstance(a, reasoning_layer.ReasoningAnalysis)
    assert a.is_decline is True
