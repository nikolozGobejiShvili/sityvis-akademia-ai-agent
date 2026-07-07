"""P2 regression tests — timezone fix, DONE event composer, neutral
discovery, awkward-phrase removal.

15 tests numbered 1:1 with PART 10 of the P2 task brief.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.agent.llm import parent_reply_composer as composer
from app.agent.services.timestamps import format_tbilisi_datetime, to_tbilisi
from app.flows import parent_flow, parent_turn_router
from app.models.lead import Lead
from app.services import conversation_service, sheets_service


# Forbidden robotic / awkward strings — checked by the tone regression
# at the bottom of the file.
AWKWARD_STRINGS: tuple[str, ...] = (
    "ბანაკის პირობებზე გელაპარაკოთ",
    "კაჭრეთი-ში",
    "რამდენად შეეფერება",
    "ცოტა ზუსტად რომ მესმოდეს",
    "რომ ზუსტად გაიგოთ რამდენად შეეფერება",
)


ROBOTIC_PHRASES: tuple[str, ...] = (
    "გნებავთ A თუ B",
    "გნებავთ a თუ b",
    "აირჩიეთ",
    "როგორ შემიძლია",
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
def driver(mock_messenger_profile, mock_start_intent_greeting):
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


def _drive_to_booked(driver, sender_id: str, monkeypatch) -> str:
    """Drive a conversation to state=DONE with calendly_booked=True via
    the pending-booking continuation path. Returns the last response
    text (the booking confirmation)."""
    from app.services import (
        calendar_service, notification_service, openai_service,
        sheets_service as ss,
    )

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: True)
    monkeypatch.setattr(ss, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary",
                        lambda history: "summary")

    driver(sender_id, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender_id, "ASK_CHALLENGE", child_age="8")
    conversation_service.process_message(
        sender_id, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    last = conversation_service.process_message(sender_id, "599123456", "instagram")
    convo = conversation_service.conversations[sender_id]
    assert convo.state == "DONE"
    assert convo.lead.calendly_booked is True
    return last


# -- test 1. Timezone conversion -----------------------------------------


def test_1_timezone_conversion_utc_to_tbilisi():
    """A UTC datetime converts to Asia/Tbilisi with the +04:00 offset."""
    aware = datetime(2026, 5, 22, 14, 48, 51, tzinfo=timezone.utc)
    out = format_tbilisi_datetime(aware)
    assert out == "2026-05-22T18:48:51+04:00"

    # Naive input is treated as UTC by convention.
    naive = datetime(2026, 5, 22, 14, 48, 51)
    assert format_tbilisi_datetime(naive) == "2026-05-22T18:48:51+04:00"

    # Already-Tbilisi datetimes pass through unchanged in clock value.
    tb = datetime(2026, 5, 22, 18, 48, 51, tzinfo=ZoneInfo("Asia/Tbilisi"))
    assert format_tbilisi_datetime(tb).startswith("2026-05-22T18:48:51")


# -- test 2. Calendar booking timezone -----------------------------------


def test_2_calendar_booking_keeps_requested_hour(driver, monkeypatch):
    """Calendar booking time === the user's requested time. The Sheets
    timestamp is a SEPARATE thing — we do not assert any equality
    between the two."""
    from app.services import (
        calendar_service, notification_service,
        sheets_service as ss, openai_service,
    )

    booked: dict[str, Any] = {}

    def _book(**kwargs):
        booked["datetime_iso"] = kwargs.get("datetime_iso")
        return True

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot", _book)
    monkeypatch.setattr(ss, "create_lead", lambda lead: True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: True,
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda history: "summary")

    sender = "p2-tz-2"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    # Explicit HH:MM so PM heuristic doesn't fire.
    conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 12:00 საათზე", "instagram",
    )
    conversation_service.process_message(sender, "599123456", "instagram")

    iso = booked.get("datetime_iso", "")
    assert iso, "calendar_service.book_slot must have been called"
    dt = datetime.fromisoformat(iso)
    # Calendar hour stays 12 in Asia/Tbilisi.
    assert dt.hour == 12, f"expected 12:00, got {dt.isoformat()}"
    # And the slot is genuinely tz-aware in Tbilisi.
    tbilisi = ZoneInfo("Asia/Tbilisi")
    assert dt.astimezone(tbilisi).hour == 12


# -- test 3. Sheets timestamp timezone -----------------------------------


def test_3_sheets_timestamp_is_tbilisi_iso():
    """`_datetime_text` (the function `_lead_to_row` uses to render
    timestamps) writes Asia/Tbilisi ISO strings — naive UTC inputs are
    converted on the way out."""
    naive_utc = datetime(2026, 5, 22, 10, 0, 0)
    out = sheets_service._datetime_text(naive_utc)
    assert out.endswith("+04:00"), f"expected +04:00 suffix, got {out}"
    assert out.startswith("2026-05-22T14:00:00"), out

    # Full lead row uses the same helper for created_at / last_message_at.
    lead = Lead(
        sender_id="t3", platform="instagram", segment="PARENT",
        name="ანა", phone="599123456",
        created_at=naive_utc, last_message_at=naive_utc,
    )
    row = sheets_service._lead_to_row(lead, lead_id=1)
    # row[14] is "Created At", row[15] is "Last Activity" per HEADERS.
    assert "+04:00" in row[14]
    assert "+04:00" in row[15]
    assert "2026-05-22T14:00:00" in row[14]


# -- test 4. DONE + first "მადლობა" --------------------------------------


def test_4_done_first_gratitude(driver, monkeypatch):
    """First thanks at DONE → natural reply, NO calendar/sheets/notify
    side-effects."""
    from app.services import (
        calendar_service, notification_service,
        sheets_service as ss, openai_service,
    )

    booked_calls: list[Any] = []
    save_calls: list[Any] = []
    notify_calls: list[Any] = []

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: (booked_calls.append(kwargs) or True))
    monkeypatch.setattr(ss, "create_lead",
                        lambda lead: (save_calls.append(lead) or True))
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: (notify_calls.append((lead, summary)) or True),
    )
    monkeypatch.setattr(openai_service, "generate_summary", lambda history: "summary")

    sender = "p2-done-4"
    _drive_to_booked(driver, sender, monkeypatch)
    # one calendar call so far
    booked_before = len(booked_calls)
    save_before = len(save_calls)
    notify_before = len(notify_calls)

    response = conversation_service.process_message(sender, "მადლობა", "instagram")
    # No additional side-effects after the booking.
    assert len(booked_calls) == booked_before
    assert len(save_calls) == save_before
    assert len(notify_calls) == notify_before
    # Response is non-empty Georgian acknowledgement.
    assert response
    assert any(t in response for t in ("მადლობა", "მოხარული", "კონსულტანტი"))


# -- test 5. DONE + repeated "მადლობა" -----------------------------------


def test_5_done_repeated_gratitude_differs_from_previous(driver, monkeypatch):
    sender = "p2-done-5"
    _drive_to_booked(driver, sender, monkeypatch)
    first = conversation_service.process_message(sender, "მადლობა", "instagram")
    second = conversation_service.process_message(sender, "მადლობა", "instagram")
    assert first.strip() != second.strip(), (
        "Second 'მადლობა' must NOT return the same response as the first"
    )
    # Neither response is the legacy "booked confirmation" template.
    convo = conversation_service.conversations[sender]
    booked_template_marker = "კონსულტანტი მალე დაგიკავშირდებათ — შვილზე უფრო დეტალურად ისაუბრებთ"
    assert booked_template_marker not in second


# -- test 6. DONE + "შენ ვინ ხარ?" ----------------------------------------


def test_6_done_identity_question(driver, monkeypatch):
    sender = "p2-done-6"
    _drive_to_booked(driver, sender, monkeypatch)
    response = conversation_service.process_message(sender, "შენ ვინ ხარ?", "instagram")
    assert "ასისტენტი" in response or "კონსულტანტი" in response  # identity wording (2026-07-07)
    # Not the legacy DONE template.
    assert "კონსულტანტი მალე დაგიკავშირდებათ — შვილზე" not in response


# -- test 7. DONE + "შენ რა გქვია?" --------------------------------------


def test_7_done_name_question(driver, monkeypatch):
    sender = "p2-done-7"
    _drive_to_booked(driver, sender, monkeypatch)
    response = conversation_service.process_message(sender, "შენ რა გქვია?", "instagram")
    # Either explains identity or that it has no personal name.
    assert "ასისტენტი" in response or "კონსულტანტი" in response  # identity wording (2026-07-07)


# -- test 8. DONE + "ჩავეწერე?" ------------------------------------------


def test_8_done_booking_status_no_duplicate_writes(driver, monkeypatch):
    from app.services import (
        calendar_service, notification_service,
        sheets_service as ss,
    )

    booked_calls: list[Any] = []
    save_calls: list[Any] = []
    notify_calls: list[Any] = []

    sender = "p2-done-8"
    _drive_to_booked(driver, sender, monkeypatch)

    # Now bind the side-effect spies (after the initial booking).
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: booked_calls.append(kwargs) or True)
    monkeypatch.setattr(ss, "create_lead",
                        lambda lead: save_calls.append(lead) or True)
    monkeypatch.setattr(
        notification_service, "send_manager_notification",
        lambda lead, summary: notify_calls.append((lead, summary)) or True,
    )

    response = conversation_service.process_message(sender, "ჩავეწერე?", "instagram")
    assert booked_calls == [], "no second booking call allowed at DONE"
    assert save_calls == [], "no second Sheets write allowed at DONE"
    assert notify_calls == [], "no second manager notification allowed at DONE"
    # Reassurance that the booking is already in place.
    assert "კონსულტ" in response or "დაჯავშნილია" in response


# -- test 9. Age input without problem mention ---------------------------


def test_9_age_input_no_problem_assumption(driver):
    sender = "p2-9"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს"])
    # state is now ASK_AGE
    response = conversation_service.process_message(sender, "14 წლის არის", "instagram")
    # The neutral discovery template is used.
    assert "რა აწუხებთ" not in response
    assert "პრობლემა" not in response
    assert "ეკრანდამოკიდებულება" not in response
    # And it actually asks a follow-up question.
    assert "?" in response or "—" in response


# -- test 10. No concern input -------------------------------------------


def test_10_no_concern_accepted_naturally(driver):
    sender = "p2-10"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")

    response = conversation_service.process_message(
        sender, "არაფერი, უბრალოდ გაშვება მინდა ბანაკში", "instagram",
    )
    # Not a psychological-framing reply.
    assert "რა აწუხებთ" not in response
    assert "შინაგანი მიზეზი" not in response
    # And nothing awkward.
    for bad in AWKWARD_STRINGS:
        assert bad not in response, f"awkward string {bad!r} found"


# -- test 11. Payment-question grammar -----------------------------------


def test_11_payment_question_grammar(driver):
    sender = "p2-11"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    response = conversation_service.process_message(
        sender, "პირობები მაინტერესებს გადახდის", "instagram",
    )
    # Must NOT contain any of the awkward phrases.
    for bad in AWKWARD_STRINGS:
        assert bad not in response, f"awkward string {bad!r} found"
    # MAY contain the correct locative form.
    assert "ამბასადორ კაჭრეთში" in response or "კაჭრეთში" in response
    # And the price from knowledge.
    assert "2150" in response


# -- test 12. Grammar regression (all post-booking + interrupt paths) ----


def test_12_no_awkward_phrases_in_any_response(driver, monkeypatch):
    """Drive an extended conversation through every relevant intent and
    assert none of the live responses contain the flagged awkward
    phrases."""
    sender = "p2-12"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    samples = [
        "ფასი რა არის?",
        "სად ტარდება?",
        "როდის არის ბანაკი?",
        "პირობები მაინტერესებს",
        "შენ ვინ ხარ?",
        "უბრალოდ ბანაკი მინდა",
    ]
    for msg in samples:
        response = conversation_service.process_message(sender, msg, "instagram")
        for bad in AWKWARD_STRINGS:
            assert bad not in response, (
                f"awkward string {bad!r} found in response to {msg!r}:\n{response}"
            )


# -- test 13. Safety guard — fake booking --------------------------------


def test_13_validator_rejects_fake_booking_when_calendar_failed():
    """If `calendar_success=False`, any booking-confirmation stem in
    the LLM output must be rejected by the validator."""
    result = composer._validate_composed_response(
        response="დაჯავშნილია 🌿 კონსულტანტი დაგიკავშირდებათ.",
        context={
            "event": "booking_status_question",
            "calendar_success": False,
            "allowed_facts": {},
        },
        previous_assistant_messages=[],
    )
    assert result is False


# -- test 14. Safety guard — exact repetition ----------------------------


def test_14_validator_rejects_exact_repetition():
    prev = "მადლობა თქვენ — კონსულტანტი დაგიკავშირდებათ მოწერილ დროზე."
    result = composer._validate_composed_response(
        response=prev,
        context={"event": "gratitude_after_booking", "calendar_success": True,
                 "allowed_facts": {}},
        previous_assistant_messages=["other reply", prev],
    )
    assert result is False


def test_14b_validator_rejects_robotic_phrasing():
    result = composer._validate_composed_response(
        response="გნებავთ A თუ B?",
        context={"event": "other_after_booking", "calendar_success": True,
                 "allowed_facts": {}},
        previous_assistant_messages=[],
    )
    assert result is False


def test_14c_validator_accepts_clean_reply():
    result = composer._validate_composed_response(
        response="მადლობა თქვენ. კონსულტანტი დაგიკავშირდებათ.",
        context={"event": "gratitude_after_booking", "calendar_success": True,
                 "allowed_facts": {}},
        previous_assistant_messages=["something else"],
    )
    assert result is True


# -- test 15. Tone regression across every post-booking event -----------


def test_15_no_robotic_phrases_in_post_booking_fallbacks():
    """Every per-event fallback must be free of forbidden menu phrasing."""
    for event in composer.SUPPORTED_POST_BOOKING_EVENTS:
        fallback = composer.post_booking_fallback(event)
        lowered = fallback.lower()
        for robotic in ROBOTIC_PHRASES:
            assert robotic.lower() not in lowered, (
                f"event={event!r}: fallback contains forbidden phrase "
                f"{robotic!r}:\n{fallback}"
            )
        for bad in AWKWARD_STRINGS:
            assert bad not in fallback, (
                f"event={event!r}: fallback contains awkward phrase "
                f"{bad!r}:\n{fallback}"
            )
