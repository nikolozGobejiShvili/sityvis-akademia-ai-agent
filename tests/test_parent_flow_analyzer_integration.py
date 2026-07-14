"""Phase 3.9 integration tests — parent_flow + analyzer-driven router.

Strategy:

  * USE_LLM_TURN_ANALYZER is OFF by default. These tests force the router on
    via ``_router_enabled`` monkeypatch and supply a deterministic
    classifier in place of ``analyze_parent_turn``. No test reaches the
    real OpenAI client.

  * Where parent_flow would otherwise hit Meta / OpenAI / Sheets / Calendar /
    Notification services, we monkeypatch the function it actually calls.

  * Tests are written against the live conversation_service entry point to
    exercise the real routing + state machine. Conversations are isolated
    by sender_id and the conversations dict is cleared in setup.

Coverage maps to the Phase 3.9 spec "Integration tests with fake analyzer
enabled" section:

  1. Manager request mid-flow → phone in reply, no discovery push
  2. Soft human request → consultation/contact offer, no discovery
  3. Second human request → escalates to phone
  4. Age + dates → child_age stored, dates returned, no "რა აწუხებთ?"
  5. Age + price → price returned, no forced discovery
  6. No concern + dates → dates returned, no deeper psychological question
  7. Location → "ამბასადორი კაჭრეთი", no "აკადემია" appended
  8. Registration → URL returned
  9. Normal flow still works (analyzer returns continue_flow everywhere)
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.flows import parent_flow, parent_turn_router
from app.services import conversation_service


# -- fake analyzer ---------------------------------------------------------


def _classify(user_message: str, current_state: str) -> dict[str, Any] | None:
    """Deterministic substring-based classifier replacing the LLM.

    Returns the analyzer's normalised dict for high-value interruption
    intents, or a "continue_flow" dict so the existing state machine
    handles the turn. Returning None would also fall through, but we
    return a dict everywhere to better mirror what a real classifier
    does — the router's "low confidence → clarify" branch is exercised
    by the explicit low-confidence test.
    """
    msg = user_message.lower()

    explicit_manager = any(stem in msg for stem in (
        "მენეჯერ", "ნომერი", "ნომერ მო", "საკონტაქტო", "კონტაქტ",
    ))
    soft_human = any(phrase in msg for phrase in (
        "ვინმე დამეხმარება", "ადამიანს მინდა", "კონსულტაცია მინდა",
    ))
    if explicit_manager or soft_human:
        return {
            "primary_intent": "ask_manager",
            "provided_fields": {
                "child_age": None, "phone": None, "name": None,
                "challenge": None, "deeper_concern": None, "desired_change": None,
            },
            "user_wants_human": True,
            "user_rejects_discovery": False,
            "fact_types_requested": [],
            "suggested_backend_action": (
                "ask_phone_for_callback" if explicit_manager else "offer_manager"
            ),
            "confidence": 0.95,
            "reason_short": "manager/contact request",
        }

    if any(kw in msg for kw in ("ფასი", "ღირს", "გადახდ", "თანხა")):
        return _facts_dict("ask_price", ["price"],
                           child_age=_extract_age(user_message))

    if any(kw in msg for kw in ("თარიღ", "როდის", "ნაკადი", "ნაკადებ")):
        return _facts_dict("ask_dates", ["dates"],
                           child_age=_extract_age(user_message))

    if any(kw in msg for kw in ("სად ", "ლოკაცი")):
        return _facts_dict("ask_location", ["location"],
                           child_age=_extract_age(user_message))

    if any(kw in msg for kw in ("რეგისტრაცი", "ლინკი")):
        return {
            "primary_intent": "ask_registration",
            "provided_fields": _empty_fields(),
            "user_wants_human": False,
            "user_rejects_discovery": False,
            "fact_types_requested": ["registration"],
            "suggested_backend_action": "show_registration",
            "confidence": 0.9,
            "reason_short": "registration link request",
        }

    if "არაფერი" in msg and any(p in msg for p in (
        "არ აწუხებს", "პრობლემა არ", "გვინდა კონსულტ",
    )):
        # No-concern. If they also asked for dates / price, route that too.
        fact_types: list[str] = []
        if "თარიღ" in msg:
            fact_types.append("dates")
        if "ფას" in msg:
            fact_types.append("price")
        return {
            "primary_intent": "no_concern",
            "provided_fields": _empty_fields(),
            "user_wants_human": False,
            "user_rejects_discovery": True,
            "fact_types_requested": fact_types,
            "suggested_backend_action": (
                "answer_facts" if fact_types else "ask_clarifying_question"
            ),
            "confidence": 0.85,
            "reason_short": "user has no concern",
        }

    # Default: user is answering the script question. Provide_field is
    # populated based on the current state so the existing handler can
    # advance naturally.
    fields = _empty_fields()
    if current_state == "ASK_AGE":
        fields["child_age"] = _extract_age(user_message) or user_message.strip()
    return {
        "primary_intent": "answer_flow_question",
        "provided_fields": fields,
        "user_wants_human": False,
        "user_rejects_discovery": False,
        "fact_types_requested": [],
        "suggested_backend_action": "continue_flow",
        "confidence": 0.9,
        "reason_short": "on-script answer",
    }


def _facts_dict(intent: str, fact_types: list[str], *,
                child_age: str | None = None) -> dict[str, Any]:
    fields = _empty_fields()
    if child_age:
        fields["child_age"] = child_age
    return {
        "primary_intent": intent,
        "provided_fields": fields,
        "user_wants_human": False,
        "user_rejects_discovery": False,
        "fact_types_requested": fact_types,
        "suggested_backend_action": "answer_facts",
        "confidence": 0.92,
        "reason_short": f"{intent}",
    }


def _empty_fields() -> dict[str, str | None]:
    return {
        "child_age": None, "phone": None, "name": None,
        "challenge": None, "deeper_concern": None, "desired_change": None,
    }


def _extract_age(text: str) -> str | None:
    """Pull a 1-2-digit number out of the text, if present."""
    import re
    match = re.search(r"\b(\d{1,2})\b", text or "")
    return match.group(1) if match else None


# -- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module_state():
    """Wipe in-memory dicts between tests so state can't leak across tests."""
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    yield
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()


@pytest.fixture
def smart_router(monkeypatch):
    """Enable the router and inject the smart fake classifier."""
    monkeypatch.setattr(parent_turn_router, "_router_enabled", lambda: True)

    def _fake_analyze(*, current_state, user_message, lead,
                      conversation_history=None, knowledge=None):
        return _classify(user_message, current_state)

    monkeypatch.setattr(parent_turn_router, "analyze_parent_turn", _fake_analyze)


@pytest.fixture
def mock_messenger_profile(monkeypatch):
    """Replace messenger_service.get_user_profile with a static profile."""
    from app.services import messenger_service

    def _profile(sender_id, platform):
        return {
            "name": "ანა ლომიძე",
            "first_name": "ანა",
            "last_name": "ლომიძე",
            "username": "",
        }

    monkeypatch.setattr(messenger_service, "get_user_profile", _profile)


@pytest.fixture
def mock_start_intent_greeting(monkeypatch):
    """Force detect_start_intent to GREETING so the START handler is
    deterministic when the analyzer chooses continue_flow."""
    from app.services import openai_service
    monkeypatch.setattr(openai_service, "detect_start_intent",
                        lambda message: "GREETING")


@pytest.fixture
def routed(smart_router, mock_messenger_profile, mock_start_intent_greeting, camp_registration_open):
    """One-shot fixture combining everything required to drive a PARENT
    conversation under the analyzer."""
    return None


def _drive(sender_id: str, messages: list[str]) -> list[str]:
    """Send messages through the live conversation_service routing."""
    responses: list[str] = []
    for msg in messages:
        responses.append(
            conversation_service.process_message(sender_id, msg, "instagram")
        )
    return responses


# -- 1. Manager request mid-flow ------------------------------------------
#
# Post-PART-5.C: the manager handler routes purely by `lead.phone`
# presence. Without a known phone (the default state for these tests),
# the reply asks the user for their phone rather than handing back the
# official company line. Soft-vs-explicit two-step escalation has been
# removed.


def test_manager_request_asks_for_phone_and_no_discovery(routed):
    sender = "int-manager-1"
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი მაინტერესებს",
        "8",
        "მირჩევნია პირდაპირ მენეჯერს ველაპარაკო",
    ])

    last = responses[-1]
    # No phone on file → ask the user for theirs. Premium phrasing.
    assert "ნომერ" in last, "must ask the user for their phone"
    assert "მენეჯერ" in last, "must mention the manager handoff"

    # No discovery cues whatsoever.
    for forbidden in ("შინაგანი მიზეზი", "ეკრანის გარეშე", "რა აწუხებთ"):
        assert forbidden not in last, (
            f"manager-handler reply must not push discovery, but contains {forbidden!r}"
        )

    # Robotic phrases forbidden.
    for robotic in ("გნებავთ A", "აირჩიეთ", "როგორ შემიძლია დაგეხმაროთ"):
        assert robotic not in last, f"robotic phrase {robotic!r} found"

    # The manager message must not be stored as a psychological field.
    convo = conversation_service.conversations[sender]
    lead = convo.lead
    assert "მენეჯერ" not in (lead.challenge or "")
    assert "მენეჯერ" not in (lead.deeper_concern or "")
    assert "მენეჯერ" not in (lead.desired_change or "")


# -- 2. Manager handoff WITH known phone ----------------------------------


def test_manager_request_with_known_phone_confirms_handoff(
    smart_router, mock_messenger_profile, mock_start_intent_greeting, monkeypatch,
):
    """When the lead already has a phone, the manager handler confirms
    handoff (and best-effort notifies) rather than re-asking."""
    from app.services import sheets_service, notification_service

    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )

    sender = "int-manager-with-phone"
    # Pre-seed the lead with a phone so the router takes the handoff path.
    conversation_service.process_message(
        sender, "გამარჯობა, ბანაკი მაინტერესებს", "instagram",
    )
    convo = conversation_service.conversations[sender]
    convo.lead.phone = "599123456"

    response = conversation_service.process_message(
        sender, "მენეჯერი დამიკავშირდეს", "instagram",
    )
    # Should confirm handoff without asking again for the number.
    assert "მენეჯერ" in response
    # No discovery.
    for forbidden in ("შინაგანი მიზეზი", "რა აწუხებთ"):
        assert forbidden not in response


# -- 4. Age + dates -------------------------------------------------------


def test_age_plus_dates_answers_dates_without_psychology(routed, monkeypatch):
    # Clock-robust (2026-06-23): freeze the camp-stream "now" before any stream
    # start so all three streams stay visible (the date filter hides started
    # streams; this test asserts all three dates are surfaced).
    import datetime as _dt
    from app.services import admin_config_service as _acs
    from app.agent.services.timestamps import TBILISI_TZ as _TZ
    monkeypatch.setattr(
        _acs, "_now_tbilisi",
        lambda: (_dt.datetime(2026, 6, 1, 12, 0, tzinfo=_TZ), _TZ),
    )
    sender = "int-age-dates-1"
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი მაინტერესებს",
        "8 წლის არის ჩემი შვილი, თარიღები რა არის?",
    ])
    last = responses[-1]
    # All three streams from camp_2026.yaml.
    assert "23-29 ივნისი" in last
    assert "5-11 ივლისი" in last
    assert "14-20 ივლისი" in last
    # Must not ask discovery questions.
    assert "რა აწუხებთ" not in last
    assert "შინაგანი მიზეზი" not in last
    # Best-effort age extraction (the "N წლის" pattern) populates the lead.
    convo = conversation_service.conversations[sender]
    assert convo.lead.child_age == "8"


# -- 5. Age + price -------------------------------------------------------


def test_age_plus_price_answers_price_with_includes(routed):
    sender = "int-age-price-1"
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი მაინტერესებს",
        "8 წლის არის, ფასი მაინტერესებს",
    ])
    last = responses[-1]
    assert "2150" in last
    # The "includes" list from camp_2026.yaml — verify the key tokens.
    for token in ("ტრანსპორტი", "განთავსება", "კვება"):
        assert token in last, f"price answer must list includes ({token!r})"
    # No forced discovery.
    assert "რა აწუხებთ" not in last
    convo = conversation_service.conversations[sender]
    assert convo.lead.child_age == "8"


# -- 6. No concern + dates ------------------------------------------------


def test_no_concern_plus_dates_answers_dates_without_psychology(routed, monkeypatch):
    # Clock-robust (2026-06-23): freeze the camp-stream "now" before any stream
    # start so all three streams stay visible.
    import datetime as _dt
    from app.services import admin_config_service as _acs
    from app.agent.services.timestamps import TBILISI_TZ as _TZ
    monkeypatch.setattr(
        _acs, "_now_tbilisi",
        lambda: (_dt.datetime(2026, 6, 1, 12, 0, tzinfo=_TZ), _TZ),
    )
    sender = "int-noconcern-dates-1"
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი მაინტერესებს",
        "8",
        "არაფერი არ აწუხებს, უბრალოდ თარიღები მაინტერესებს",
    ])
    last = responses[-1]
    assert "23-29 ივნისი" in last
    assert "5-11 ივლისი" in last
    assert "14-20 ივლისი" in last
    assert "შინაგანი მიზეზი" not in last
    assert "რა აწუხებთ" not in last


# -- 7. Location ----------------------------------------------------------


def test_location_returns_correct_location(routed):
    sender = "int-location-1"
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი მაინტერესებს",
        "სად ტარდება ბანაკი?",
    ])
    last = responses[-1]
    # P2: location rendered in the locative case — natural Georgian.
    assert "ამბასადორ კაჭრეთში" in last
    # Critical owner-flagged regression: never append "აკადემია" to "კაჭრეთი".
    assert "კაჭრეთის აკადემიაში" not in last
    assert "კაჭრეთის აკადემია" not in last


# -- 8. Registration ------------------------------------------------------


def test_registration_returns_url(routed):
    sender = "int-reg-1"
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი მაინტერესებს",
        "რეგისტრაციის ლინკი მომეცით",
    ])
    last = responses[-1]
    assert "tinyurl.com/36jcae8z" in last
    # Should not pivot to a discovery question.
    assert "რა აწუხებთ" not in last


# -- 9. Normal flow still works (full 7-step booking under analyzer) -----


def test_normal_flow_still_works_with_analyzer_on(
    smart_router, mock_messenger_profile, mock_start_intent_greeting,
    monkeypatch,
):
    """With analyzer ON but every message classified as answer_flow_question
    (the smart fake's default branch), the existing 7-step booking flow
    must still complete: present_value → ask phone → show slots → book →
    save lead → notify manager."""
    from app.services import (
        calendar_service, openai_service, sheets_service, notification_service,
    )

    booked: list[dict[str, Any]] = []
    saved_leads: list[Any] = []
    notifications: list[dict[str, Any]] = []

    monkeypatch.setattr(
        openai_service, "generate_parent_value_response",
        lambda **kwargs: "ბანაკის გარემო ეხმარება ბავშვს...",
    )
    monkeypatch.setattr(
        openai_service, "generate_summary",
        lambda history: "summary",
    )

    slots = [
        {"date": "15 მაისი", "time": "14:00",
         "datetime_iso": "2026-05-15T14:00:00+04:00"},
        {"date": "15 მაისი", "time": "16:00",
         "datetime_iso": "2026-05-15T16:00:00+04:00"},
        {"date": "16 მაისი", "time": "11:00",
         "datetime_iso": "2026-05-16T11:00:00+04:00"},
    ]
    monkeypatch.setattr(calendar_service, "get_free_slots",
                        lambda d, duration_minutes=30: slots)
    monkeypatch.setattr(calendar_service, "get_available_slots",
                        lambda: slots)
    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(
        calendar_service, "format_slots_for_chat",
        lambda s: "\n".join(
            f"{i+1}. {sl['date']} - {sl['time']}" for i, sl in enumerate(s)
        ) + "\n\nაირჩიეთ ნომერი",
    )

    def _book_slot(datetime_iso, lead, duration_minutes=30):
        booked.append({"iso": datetime_iso, "name": lead.name,
                       "phone": lead.phone})
        return True
    monkeypatch.setattr(calendar_service, "book_slot", _book_slot)

    def _create_lead(lead):
        saved_leads.append(lead)
        return True
    monkeypatch.setattr(sheets_service, "create_lead", _create_lead)

    def _notify(lead, summary):
        notifications.append({"lead": lead, "summary": summary})
        return True
    monkeypatch.setattr(notification_service,
                        "send_manager_notification", _notify)

    sender = "int-normal-1"
    # Parent-greeting fix: the bot's first reply at state=START is the
    # static PARENT_WELCOME menu for a bare topic word; the camp-pick turn
    # ("ბავშვების საზაფხულო ბანაკი") kicks the existing discovery flow.
    # P0 Live Demo UX — ISSUE 1 (2026-06-13): an EXPLICIT intent statement
    # ("ბანაკი მაინტერესებს") now skips the menu, so this full-flow test
    # opens with the bare topic word "ბანაკი" to keep the menu opener.
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი",
        "ბავშვების საზაფხულო ბანაკი",
        "8",
        "ბევრს ზის ტელეფონზე",
        "ერთ ოთახში გამოიკეტება",
        "უფრო კომუნიკაბელური გახდეს",
        "599123456",
        "1",
    ])

    assert len(responses) == 8
    convo = conversation_service.conversations[sender]

    # Booking-side effects.
    assert len(booked) == 1
    assert booked[0]["phone"] == "599123456"
    assert booked[0]["name"] == "ანა ლომიძე"
    assert len(saved_leads) == 1
    assert saved_leads[0].status == "Booked"
    assert len(notifications) == 1
    assert convo.state == "DONE"

    # Confirmation includes the picked slot.
    assert "15 მაისი" in responses[-1]
    assert "14:00" in responses[-1]


# -- 10. Deterministic detector runs even with LLM analyzer off -----------


def test_deterministic_detector_catches_manager_with_analyzer_off(monkeypatch):
    """Post-PART-7: the deterministic detector ALWAYS runs, even when
    USE_LLM_TURN_ANALYZER is off. An obvious manager request must be
    caught and NOT stored as a psychological field.

    This replaces the prior `test_default_off_does_not_invoke_analyzer`,
    which encoded the previous "byte-identical baseline when flag is off"
    behaviour. The new design intentionally always honours user intent —
    the flag now only gates the LLM fallback path.
    """
    from app.agent.llm import parent_turn_analyzer as analyzer_mod
    # Disable the LLM analyzer entirely.
    monkeypatch.setattr(analyzer_mod, "_analyzer_enabled", lambda: False)
    monkeypatch.setattr(parent_turn_router, "_router_enabled", lambda: False)

    from app.services import messenger_service, openai_service
    monkeypatch.setattr(messenger_service, "get_user_profile",
                        lambda sid, plat: {"name": "ანა ლომიძე"})
    monkeypatch.setattr(openai_service, "detect_start_intent",
                        lambda m: "GREETING")

    # Sanity: the LLM analyzer must NOT be called.
    def _explode(**kwargs):
        raise AssertionError(
            "openai_service.analyze_parent_turn must not run when analyzer is off",
        )
    monkeypatch.setattr(openai_service, "analyze_parent_turn", _explode,
                        raising=False)

    sender = "int-det-only-1"
    responses = _drive(sender, [
        "გამარჯობა, ბანაკი მაინტერესებს",
        "8",
        "მენეჯერი მინდა",
    ])

    convo = conversation_service.conversations[sender]
    # Deterministic detector caught the manager request — message is NOT
    # stored as challenge, response asks for the user's phone, no
    # discovery push.
    assert "მენეჯერ" not in (convo.lead.challenge or "")
    assert "ნომერ" in responses[-1]
    assert "მენეჯერ" in responses[-1]
    for forbidden in ("შინაგანი მიზეზი", "რა აწუხებთ"):
        assert forbidden not in responses[-1]
