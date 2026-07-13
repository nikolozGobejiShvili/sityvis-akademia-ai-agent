"""Regression tests for the pending-booking continuation flow (P1 task).

15 tests numbered 1:1 with PART 9 of the task brief.

What this proves end-to-end:

  * Conversation.to_dict / from_dict round-trip preserves
    ``pending_booking`` and the whole conversation is JSON-serialisable
    (Redis-ready).
  * A booking request with a parseable date/time but missing contact
    info sets ``conversation.pending_booking`` instead of dropping the
    intent on the floor.
  * Subsequent bare-phone or bare-name messages are recognised as
    continuation — never stored as ``lead.challenge`` /
    ``lead.deeper_concern`` / ``lead.desired_change``.
  * Identity / manager / factual interrupts during pending booking are
    honoured (identity preserves, manager clears + hands off, factual
    answers + reminder, cancel clears + polite response).
  * No fake booking confirmation under ANY calendar-failure path.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service


# Robotic-phrase regression set (PART 8 + style-guide cross-check).
ROBOTIC_PHRASES: tuple[str, ...] = (
    "გნებავთ a თუ b",
    "გნებავთ A თუ B",
    "აირჩიეთ სასურველი ვარიანტი",
    "როგორ შემიძლია დაგეხმაროთ",
)


# -- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module_state():
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
def mock_messenger_profile(monkeypatch):
    from app.services import messenger_service
    monkeypatch.setattr(
        messenger_service, "get_user_profile",
        lambda sid, plat: {
            "name": "ანა ლომიძე", "first_name": "ანა",
            "last_name": "ლომიძე", "username": "",
        },
    )


@pytest.fixture
def mock_start_intent_greeting(monkeypatch):
    from app.services import openai_service
    monkeypatch.setattr(openai_service, "detect_start_intent", lambda m: "GREETING")


@pytest.fixture
def mock_no_meta_profile(monkeypatch):
    """For tests where the Meta profile should NOT auto-populate lead.name."""
    from app.services import messenger_service
    monkeypatch.setattr(
        messenger_service, "get_user_profile",
        lambda sid, plat: {"name": "", "first_name": "", "last_name": "", "username": ""},
    )


@pytest.fixture
def camp_registration_open(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_registration_status", lambda: "open",
    )


@pytest.fixture
def driver(mock_messenger_profile, mock_start_intent_greeting, camp_registration_open):
    def _drive(sender_id: str, messages: list[str]) -> list[str]:
        responses: list[str] = []
        for msg in messages:
            responses.append(
                conversation_service.process_message(sender_id, msg, "instagram"),
            )
        return responses
    return _drive


def _force_state(sender_id: str, state: str, *, child_age: str = "") -> None:
    convo = conversation_service.conversations.get(sender_id)
    assert convo is not None
    convo.state = state
    if child_age and convo.lead:
        convo.lead.child_age = child_age


# -- test 1. Serialization includes pending_booking -----------------------


def test_1_conversation_serialization_round_trip_with_pending_booking():
    """to_dict / from_dict round-trip + JSON-safety + datetime-as-string."""
    pending = {
        "requested_datetime_iso": "2026-05-22T17:00:00+04:00",
        "requested_date_text": "22 მაისი",
        "requested_time_text": "17:00",
        "source": "booking_interrupt",
        "missing_fields": ["phone"],
        "created_at": "2026-05-22T14:30:00+04:00",
        "attempts": 0,
    }
    conv = Conversation(
        sender_id="ser-1",
        platform="instagram",
        segment="PARENT",
        state="ASK_CHALLENGE",
        history=[{"role": "user", "content": "ჩამწერე"}],
        lead=Lead(sender_id="ser-1", platform="instagram", segment="PARENT", name="ანა"),
        pending_booking=dict(pending),
    )

    data = conv.to_dict()
    assert "pending_booking" in data
    assert data["pending_booking"] == pending

    # Datetime fields inside pending_booking are strings — Redis-safe.
    assert isinstance(data["pending_booking"]["requested_datetime_iso"], str)
    assert isinstance(data["pending_booking"]["created_at"], str)
    # Top-level Conversation datetimes are also strings.
    assert isinstance(data["created_at"], str)
    assert isinstance(data["last_activity"], str)
    # Nested Lead datetimes are strings.
    assert isinstance(data["lead"]["created_at"], str)
    assert isinstance(data["lead"]["last_message_at"], str)

    # Full JSON round-trip — must not raise.
    text = json.dumps(data, ensure_ascii=False)
    assert "pending_booking" in text

    restored = Conversation.from_dict(json.loads(text))
    assert restored.pending_booking == pending
    assert restored.lead is not None
    assert restored.lead.name == "ანა"
    assert restored.state == "ASK_CHALLENGE"
    assert restored.sender_id == "ser-1"


# -- test 2. Booking request + datetime + no phone → pending set ----------


def test_2_booking_request_with_datetime_sets_pending(driver):
    sender = "pb-2"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")

    response = conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    convo = conversation_service.conversations[sender]
    pending = convo.pending_booking
    assert pending is not None, "pending_booking must be set"
    assert "requested_datetime_iso" in pending
    assert isinstance(pending["requested_datetime_iso"], str)
    # "22 მაისს 5 საათზე" → date=22, time=17:00
    assert "T17:00:00" in pending["requested_datetime_iso"]
    # Phone is missing (no Meta profile populates phone).
    assert "phone" in pending["missing_fields"]

    # Response asks for phone/name, no discovery, no fake confirmation.
    assert "ნომერ" in response
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response
    for fake in ("დაჯავშნილია", "დაგაჯავშნე", "ჩაწერილი ხართ"):
        assert fake not in response


# -- test 3. Bare phone continues pending booking -------------------------


def test_3_bare_phone_continues_pending_booking_attempts_booking(
    driver, monkeypatch,
):
    from app.services import calendar_service, sheets_service, notification_service

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: True)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )

    sender = "pb-3"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    # Trigger pending. lead.name is set from Meta profile fixture.
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    convo = conversation_service.conversations[sender]
    assert convo.pending_booking is not None
    assert convo.lead.name == "ანა ლომიძე"
    assert convo.lead.phone == ""

    # Bare phone arrives.
    response = conversation_service.process_message(sender, "599123456", "instagram")

    # Phone must NOT be stored as a psychological field.
    assert convo.lead.challenge == ""
    assert convo.lead.deeper_concern == ""
    assert convo.lead.desired_change == ""
    # Phone IS captured on the lead.
    assert convo.lead.phone == "599123456"
    # Booking succeeded (mocks) → pending cleared + state DONE.
    assert convo.pending_booking is None
    assert convo.state == "DONE"
    # No discovery cues.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 4. Phone with spaces / +995 ------------------------------------


def test_4_phone_with_country_code_continues_pending(driver, monkeypatch):
    from app.services import calendar_service, sheets_service, notification_service

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: True)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )

    sender = "pb-4"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    response = conversation_service.process_message(
        sender, "+995 599 12 34 56", "instagram",
    )

    convo = conversation_service.conversations[sender]
    # Canonical parser normalises with the +995 prefix.
    assert convo.lead.phone.startswith("+995") or convo.lead.phone == "599123456"
    assert convo.lead.challenge == ""
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 5. Name + phone in one message ---------------------------------


def test_5_name_plus_phone_in_one_message_completes_booking(
    mock_no_meta_profile, mock_start_intent_greeting, monkeypatch, camp_registration_open,
):
    from app.services import calendar_service, sheets_service, notification_service

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: True)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )

    sender = "pb-5"
    # No Meta profile name — lead.name starts empty.
    conversation_service.process_message(
        sender, "გამარჯობა, ბანაკი მაინტერესებს", "instagram",
    )
    conversation_service.process_message(sender, "8", "instagram")
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    convo = conversation_service.conversations[sender]
    convo.lead.name = ""
    # Trigger pending without name or phone.
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    assert convo.pending_booking is not None
    assert "name" in convo.pending_booking["missing_fields"]
    assert "phone" in convo.pending_booking["missing_fields"]

    response = conversation_service.process_message(
        sender, "მარიამი 599123456", "instagram",
    )
    assert convo.lead.name == "მარიამი"
    assert convo.lead.phone == "599123456"
    assert convo.state == "DONE"
    assert convo.pending_booking is None
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 6. Invalid phone during pending booking ------------------------


def test_6_invalid_phone_during_pending_asks_for_valid(driver):
    sender = "pb-6"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    response = conversation_service.process_message(sender, "5777", "instagram")

    convo = conversation_service.conversations[sender]
    # Pending stays active — user hasn't given a valid contact yet.
    assert convo.pending_booking is not None
    # Phone not stored.
    assert convo.lead.phone == ""
    # Not stored as challenge.
    assert convo.lead.challenge == ""
    # Asks for valid 9-digit phone.
    assert "9-ციფრიანი" in response or "9 ციფრიანი" in response or "ნომერი" in response
    # No discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 7. Missing name after phone -----------------------------------


def test_7_phone_first_then_asks_for_name(
    mock_no_meta_profile, mock_start_intent_greeting, monkeypatch, camp_registration_open,
):
    sender = "pb-7"
    # Skip mocking calendar — we expect the booking attempt to NOT fire
    # (name still missing).
    conversation_service.process_message(
        sender, "გამარჯობა, ბანაკი მაინტერესებს", "instagram",
    )
    conversation_service.process_message(sender, "8", "instagram")
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    convo = conversation_service.conversations[sender]
    convo.lead.name = ""

    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    assert convo.pending_booking is not None

    response = conversation_service.process_message(sender, "599123456", "instagram")
    # Phone captured.
    assert convo.lead.phone == "599123456"
    # Name still missing → pending active.
    assert convo.pending_booking is not None
    assert "name" in convo.pending_booking["missing_fields"]
    assert "phone" not in convo.pending_booking["missing_fields"]
    # Asks for name; no booking attempted.
    assert "სახელ" in response
    assert convo.state != "DONE"
    # Phone not stored as challenge.
    assert convo.lead.challenge == ""


# -- test 8. Name after phone completes booking --------------------------


def test_8_name_after_phone_completes_pending_booking(
    mock_no_meta_profile, mock_start_intent_greeting, monkeypatch, camp_registration_open,
):
    from app.services import calendar_service, sheets_service, notification_service

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: True)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )

    sender = "pb-8"
    conversation_service.process_message(
        sender, "გამარჯობა, ბანაკი მაინტერესებს", "instagram",
    )
    conversation_service.process_message(sender, "8", "instagram")
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    convo = conversation_service.conversations[sender]
    convo.lead.name = ""

    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    conversation_service.process_message(sender, "599123456", "instagram")
    assert convo.lead.phone == "599123456"
    assert convo.lead.name == ""

    response = conversation_service.process_message(sender, "ნიკა", "instagram")
    assert convo.lead.name == "ნიკა"
    assert convo.state == "DONE"
    assert convo.pending_booking is None
    # No discovery cues.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 9. Calendar failure → no fake confirmation ---------------------


def test_9_calendar_failure_does_not_confirm_booking(driver, monkeypatch):
    from app.services import calendar_service

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: False)  # busy
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: False)

    sender = "pb-9"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    response = conversation_service.process_message(sender, "599123456", "instagram")

    convo = conversation_service.conversations[sender]
    # No fake confirmation.
    for fake in (
        "დაგაჯავშნე", "დაჯავშნილია", "ჩაწერილი ხართ", "ჩაგწერეთ",
    ):
        assert fake not in response, f"fake confirmation {fake!r} leaked"
    # State not DONE.
    assert convo.state != "DONE"
    # Lead not marked booked.
    assert convo.lead.calendly_booked is False


# -- test 10. Calendar success → real confirmation ----------------------


def test_10_calendar_success_confirms_booking(driver, monkeypatch):
    from app.services import calendar_service, sheets_service, notification_service

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: True)
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )

    sender = "pb-10"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    response = conversation_service.process_message(sender, "599123456", "instagram")

    convo = conversation_service.conversations[sender]
    # Confirmation language is the legitimate PARENT_BOOKING_CONFIRMED.
    assert "დაჯავშნილია" in response
    assert convo.lead.calendly_booked is True
    assert convo.state == "DONE"
    assert convo.pending_booking is None


# -- test 11. Identity during pending booking -----------------------------


def test_11_identity_during_pending_preserves_pending(driver):
    sender = "pb-11"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    response = conversation_service.process_message(sender, "შენ ვინ ხარ?", "instagram")

    convo = conversation_service.conversations[sender]
    # Identity reply.
    assert "ასისტენტი" in response or "კონსულტანტი" in response  # identity wording (2026-07-07)
    # Pending preserved.
    assert convo.pending_booking is not None
    # State preserved.
    assert convo.state == "ASK_CHALLENGE"


# -- test 12. Manager request during pending booking ---------------------


def test_12_manager_during_pending_clears_pending_and_hands_off(driver):
    sender = "pb-12"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    convo = conversation_service.conversations[sender]
    assert convo.pending_booking is not None

    response = conversation_service.process_message(
        sender, "მენეჯერი დამიკავშირდეს", "instagram",
    )

    # Manager handoff text.
    assert "მენეჯერ" in response
    assert "ნომერ" in response  # lead.phone empty → asks for it
    # Pending cleared (transitioned to handoff).
    assert convo.pending_booking is None
    # No discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 13. Price during pending → answer + reminder --------------------


def test_13_price_during_pending_answers_and_reminds(driver):
    sender = "pb-13"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    response = conversation_service.process_message(sender, "ფასი რა არის?", "instagram")

    # Price content present.
    assert "2150" in response
    # Reminder about missing field present.
    assert "ნომერ" in response, "must remind that phone is needed for booking"
    # Pending preserved.
    convo = conversation_service.conversations[sender]
    assert convo.pending_booking is not None
    # No discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 14. Cancel pending booking --------------------------------------


def test_14_cancel_pending_clears_pending(driver):
    sender = "pb-14"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )

    response = conversation_service.process_message(sender, "აღარ მინდა", "instagram")

    convo = conversation_service.conversations[sender]
    assert convo.pending_booking is None
    # Polite cancel response.
    assert "მოგვიანებით" in response or "კარგი" in response
    # No discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 15. Tone regression — no robotic phrases ----------------------


def test_15_no_robotic_phrases_in_pending_responses(driver):
    """Drive multiple pending-flow scenarios and assert that every reply
    is free of forbidden menu-style phrasing (PART 8 style guide)."""
    cases: list[tuple[str, str]] = [
        ("pb-15a", "599123456"),     # bare phone continuation
        ("pb-15b", "5777"),           # invalid phone
        ("pb-15c", "შენ ვინ ხარ?"),   # identity during pending
        ("pb-15d", "ფასი რა არის?"),  # price during pending
        ("pb-15e", "აღარ მინდა"),     # cancel
    ]
    for sender, follow_up in cases:
        driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
        _force_state(sender, "ASK_CHALLENGE", child_age="8")
        conversation_service.process_message(
            sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
        )
        response = conversation_service.process_message(sender, follow_up, "instagram")
        lowered = response.lower()
        for robotic in ROBOTIC_PHRASES:
            assert robotic not in lowered, (
                f"sender={sender}: forbidden robotic phrase {robotic!r} in:\n"
                f"--- {response} ---"
            )
