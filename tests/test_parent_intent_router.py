"""Regression tests for the Silent Parent Intent Router (PART 9, 16 cases).

These tests exercise the *deterministic-first* router end-to-end through
``conversation_service.process_message`` — the same entry point the
webhook uses. The LLM analyzer is not enabled by these tests (its
behaviour is covered by the analyzer's own unit tests), but the
deterministic detector always runs, so every interrupt scenario below
is fully exercised without touching OpenAI.

Test numbering matches PART 9 of the task brief 1:1, so a failing index
maps back to a numbered acceptance criterion.

Robotic-phrase regression (test 16) is intentionally a *cross-cutting*
test: it iterates every interrupt response from this file and asserts
no forbidden phrase appears in any of them.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from app.config import settings
from app.flows import parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import conversation_service


# Forbidden robotic phrases (PART 4 style guide).
ROBOTIC_PHRASES: tuple[str, ...] = (
    "გნებავთ a თუ b",
    "გნებავთ A თუ B",
    "აირჩიეთ სასურველი ვარიანტი",
    "როგორ შემიძლია დაგეხმაროთ",
)

CANONICAL_PRICE_TOKENS: tuple[str, ...] = (
    "2150",
    "ტრანსპორტირება",
    "განთავსება",
    "კვება",
    "სრული პროგრამა",
    "გადახდის გადანაწილება",
    "TBC",
    "საქართველოს ბანკ",
    "10%",
)
PAYMENT_PROCESS_ANSWER = (
    "ბანაკის ჯავშნის საფასურის გადახდა ხდება წინასწარ, ხოლო სრული თანხის — "
    "ხელშეკრულებით გათვალისწინებულ დროში. გადახდის გადანაწილება შესაძლებელია "
    "6 თვემდე TBC-ისა და საქართველოს ბანკის საშუალებით"
)
RESERVATION_FEE_DEFER = (
    "რაც შეეხება ჯავშნის საფასურს, ამ დეტალებს მენეჯერი გაგაცნობთ: 558 67 47 33"
)
LEGACY_PRICE_FALLBACK_FORBIDDEN: tuple[str, ...] = (
    "ბანაკის ღირებულებაა",
    "მენეჯერი აგიხსნით",
    "როგორც ზემოთ",
    "როგორც უკვე გითხარით",
    "ზემოთ მოგწერეთ",
)


def _assert_canonical_price_block(response: str) -> None:
    for token in CANONICAL_PRICE_TOKENS:
        assert token in response, token
    for forbidden in LEGACY_PRICE_FALLBACK_FORBIDDEN:
        assert forbidden not in response


# -- fixtures --------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_module_state():
    """Wipe in-memory dicts between tests so state can't leak."""
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
def driver(mock_messenger_profile, mock_start_intent_greeting, camp_registration_open):
    """Returns a (sender_id, messages) → list[response] driver."""
    def _drive(sender_id: str, messages: list[str]) -> list[str]:
        responses: list[str] = []
        for msg in messages:
            responses.append(
                conversation_service.process_message(sender_id, msg, "instagram"),
            )
        return responses
    return _drive


def _force_state(sender_id: str, state: str, *, child_age: str = "") -> None:
    """Drive a conversation into a chosen mid-flow state by sending real
    messages, then optionally override the conversation/lead fields."""
    convo = conversation_service.conversations.get(sender_id)
    assert convo is not None, "conversation must exist before forcing state"
    convo.state = state
    if child_age and convo.lead:
        convo.lead.child_age = child_age


# -- test 1. Runtime config ----------------------------------------------


def test_1_use_llm_turn_analyzer_loaded_from_env_as_true():
    """PART 1: settings.USE_LLM_TURN_ANALYZER reflects .env

    .env contains ``USE_LLM_TURN_ANALYZER=true``. The dataclass field is
    a boolean — assert by *value*, not by string.
    """
    assert settings.USE_LLM_TURN_ANALYZER is True, (
        "Expected settings.USE_LLM_TURN_ANALYZER == True when .env "
        "contains USE_LLM_TURN_ANALYZER=true"
    )
    # Companion check — USE_LLM_COMPOSER is currently false in .env.
    assert isinstance(settings.USE_LLM_COMPOSER, bool)


# -- test 2. Identity at ASK_CHALLENGE ------------------------------------


def test_2_identity_question_at_ask_challenge_preserves_state(driver):
    sender = "p2"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")

    response = conversation_service.process_message(
        sender, "შენ ვინ ხარ?", "instagram",
    )
    # Identity answer must mention what the bot is/does.
    # Identity vocabulary is „AI აგენტი" since 2026-08-02 (operator wording);
    # the contract is that the reply says what the agent IS, not which noun.
    assert any(w in response for w in ("აგენტი", "ასისტენტი", "კონსულტანტი"))
    # Must not repeat the segment-routing menu.
    assert "ბავშვების საზაფხულო ბანაკი" not in response
    assert "ზრდასრულთა კულტურული საღამოები" not in response
    # No psychological discovery question.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი", "ეკრანის გარეშე"):
        assert forbidden not in response
    # State preserved.
    convo = conversation_service.conversations[sender]
    assert convo.state == "ASK_CHALLENGE"


# -- test 3. Identity wins over price ------------------------------------


def test_3_identity_wins_over_price_at_ask_deeper(driver):
    sender = "p3"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8", "ბევრს ზის ტელეფონზე"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "შენ ვინ ხარ და ბანაკი რა ღირს?", "instagram",
    )
    # Identity (priority 3) wins over price (priority 4).
    # Identity vocabulary is „AI აგენტი" since 2026-08-02 (operator wording);
    # the contract is that the reply says what the agent IS, not which noun.
    assert any(w in response for w in ("აგენტი", "ასისტენტი", "კონსულტანტი"))
    # Critically: bare-price stems must not be the headline — the
    # identity reply is the entire response, no price digits.
    assert "2150" not in response
    # State preserved.
    convo = conversation_service.conversations[sender]
    assert convo.state == "ASK_DEEPER"


# -- test 4. Booking request without datetime ----------------------------


def test_4_booking_request_no_datetime_asks_for_time(driver):
    sender = "p4"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")

    response = conversation_service.process_message(
        sender, "კონსულტაციაზე ჩაწერა მინდა", "instagram",
    )
    # Acknowledges booking + asks for date/time (or contact).
    assert any(token in response for token in ("დღე", "საათ")), (
        "booking ask must mention day/time"
    )
    # No psychological discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response
    # No fake confirmation.
    for fake in ("დაჯავშნილია", "დაგაჯავშნე", "ჩაწერილი ხართ"):
        assert fake not in response


# -- test 5. Booking with date/time but no phone --------------------------


def test_5_booking_with_datetime_asks_for_contact_no_fake_confirmation(driver):
    sender = "p5"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")

    # lead.name is populated from Meta profile; lead.phone is NOT.
    response = conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    # Booking pathway took over — no discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი", "ეკრანის გარეშე"):
        assert forbidden not in response
    # No fake confirmation (book_slot was never called — no phone yet).
    for fake in ("დაჯავშნილია", "დაგაჯავშნე", "ჩაწერილი ხართ"):
        assert fake not in response
    # Asks for the missing piece (phone).
    assert "ნომერ" in response


# -- test 6. Booking + price conflict ------------------------------------


def test_6_booking_wins_over_price(driver):
    sender = "p6"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8", "ბევრს ზის ტელეფონზე"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "ფასი მაინტერესებს და კონსულტაციაზე ჩამწერე", "instagram",
    )
    # Main action is booking — asks for day/time (or contact).
    assert any(token in response for token in ("დღე", "საათ", "ნომერ"))
    # PART 3 allows brief price acknowledgement.
    # No psychological discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 7. Manager request, no phone known -----------------------------


def test_7_manager_request_asks_phone_no_state_advance(driver):
    sender = "p7"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8", "ბევრს ზის ტელეფონზე"])
    _force_state(sender, "ASK_DEEPER")
    state_before = conversation_service.conversations[sender].state

    response = conversation_service.process_message(
        sender, "მენეჯერი დამიკავშირდეს", "instagram",
    )
    # Asks for phone + mentions manager handoff.
    assert "ნომერ" in response
    assert "მენეჯერ" in response
    # No discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი", "ეკრანის გარეშე"):
        assert forbidden not in response
    # State unchanged.
    assert conversation_service.conversations[sender].state == state_before


# -- test 8. Manager wins over price -------------------------------------


def test_8_manager_wins_over_price(driver):
    sender = "p8"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8", "ბევრს ზის ტელეფონზე"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "მენეჯერი დამიკავშირდეს, ფასი მაინტერესებს", "instagram",
    )
    # Manager wins → asks for phone, no price answer.
    assert "ნომერ" in response
    assert "მენეჯერ" in response
    # Price digits must NOT appear — manager intent suppresses lower-priority
    # factual replies (PART 3).
    assert "2150" not in response
    # No discovery.
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        assert forbidden not in response


# -- test 9. Price question — value framing -------------------------------


def test_9_price_question_returns_canonical_full_block(driver):
    sender = "p9"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "ფასი რა არის?", "instagram",
    )
    _assert_canonical_price_block(response)
    # State preserved.
    assert conversation_service.conversations[sender].state == "ASK_DEEPER"


def test_9b_payment_process_router_fallback_has_no_price(driver):
    sender = "p9-payment"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "გადახდა როგორ ხდება?", "instagram",
    )
    assert PAYMENT_PROCESS_ANSWER in response
    assert "2150" not in response
    assert "ბანაკის ფასი" not in response
    assert conversation_service.conversations[sender].state == "ASK_DEEPER"


def test_9c_reservation_exact_amount_router_fallback_defers_only(driver):
    sender = "p9-reservation"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "ჯავშნის ღირებულება რამდენია?", "instagram",
    )
    assert response == RESERVATION_FEE_DEFER
    assert "2150" not in response
    assert conversation_service.conversations[sender].state == "ASK_DEEPER"


def test_9d_analyzer_no_concern_price_fact_uses_canonical_delegate(monkeypatch):
    conversation = Conversation(sender_id="p9-analyzer", platform="instagram")
    conversation.segment = "PARENT"
    conversation.state = "ASK_DEEPER"
    lead = Lead(sender_id="p9-analyzer", platform="instagram", segment="PARENT")
    conversation.lead = lead

    monkeypatch.setattr(parent_turn_router, "detect_parent_interrupt_intent", lambda m: None)
    monkeypatch.setattr(parent_turn_router, "_analyzer_enabled", lambda: True)

    def _fake_analyze(**_: Any) -> dict[str, Any]:
        return {
            "primary_intent": "no_concern",
            "provided_fields": {},
            "user_wants_human": False,
            "user_rejects_discovery": True,
            "fact_types_requested": ["price"],
            "suggested_backend_action": "answer_facts",
            "confidence": 0.95,
            "reason_short": "price fact after no concern",
        }

    monkeypatch.setattr(parent_turn_router, "analyze_parent_turn", _fake_analyze)

    response = parent_turn_router.maybe_handle_analyzer_interrupt(
        conversation, lead, "არაფერი, ფასი მაინტერესებს",
    )
    assert response is not None
    _assert_canonical_price_block(response)


# -- test 10. Dates question --------------------------------------------


def test_10_dates_question_returns_streams_from_knowledge(driver, monkeypatch):
    # Clock-robust (2026-06-23): freeze the camp-stream "now" before any stream
    # start so all three streams stay visible (the date filter hides started
    # streams; this test asserts all three dates are returned).
    import datetime as _dt
    from app.services import admin_config_service as _acs
    from app.agent.services.timestamps import TBILISI_TZ as _TZ
    monkeypatch.setattr(
        _acs, "_now_tbilisi",
        lambda: (_dt.datetime(2026, 6, 1, 12, 0, tzinfo=_TZ), _TZ),
    )
    sender = "p10"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "როდის არის ბანაკი?", "instagram",
    )
    # All three streams from camp_2026.yaml.
    assert "23-29 ივნისი" in response
    assert "5-11 ივლისი" in response
    assert "14-20 ივლისი" in response
    assert conversation_service.conversations[sender].state == "ASK_DEEPER"


# -- test 11. Location question -----------------------------------------


def test_11_location_question_returns_camp_location(driver):
    sender = "p11"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "სად ტარდება?", "instagram",
    )
    # P2: rendered in the locative case — "ამბასადორ კაჭრეთში" — so the
    # text reads as natural Georgian instead of "ამბასადორი კაჭრეთი-ში".
    assert "ამბასადორ კაჭრეთში" in response
    # Owner-flagged regression: never append "აკადემია" to "კაჭრეთი".
    assert "კაჭრეთის აკადემიაში" not in response
    assert "კაჭრეთის აკადემია" not in response
    # And the awkward "-ში" hyphen form is also gone.
    assert "კაჭრეთი-ში" not in response
    assert conversation_service.conversations[sender].state == "ASK_DEEPER"


# -- test 12. Conditions question ----------------------------------------


def test_12_conditions_question_returns_concise_conditions(driver):
    sender = "p12"
    # Mid-flow check — drive to ASK_DEEPER first.
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "ბავშვების ბანაკის პირობები", "instagram",
    )
    # Core facts from knowledge.
    for token in ("ტრანსპორტი", "კვება", "განთავსება"):
        assert token in response
    # No hallucinated facts (registration URL shouldn't appear in conditions).
    assert "tinyurl.com/36jcae8z" not in response
    # No menu phrasing.
    for robotic in ROBOTIC_PHRASES:
        assert robotic not in response.lower()


# -- test 13. Multiple factual questions ---------------------------------


def test_13_two_factual_questions_priority_takes_one(driver, camp_streams_visible):
    """Per PART 3 priority: only the highest-priority intent is handled.

    For ``ask_dates`` (priority 4 in the dates slot) and ``ask_location``
    (priority 5), the detector returns whichever stem it sees first in
    its priority walk — dates outranks location. The reply may NOT
    contain a booking-style next step.
    """
    sender = "p13"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_DEEPER")

    response = conversation_service.process_message(
        sender, "სად ტარდება და როდის არის?", "instagram",
    )
    # Dates priority (5) wins over location (6) — at least one stream date
    # must appear in the reply.
    assert any(t in response for t in (
        "23-29 ივნისი", "5-11 ივლისი", "14-20 ივლისი",
    )), "dates question must produce stream dates"
    # State preserved, no booking attempted.
    assert conversation_service.conversations[sender].state == "ASK_DEEPER"
    for fake in ("დაჯავშნილია", "დაგაჯავშნე", "ჩაწერილი ხართ"):
        assert fake not in response


# -- test 14. Continue flow at ASK_AGE -----------------------------------


def test_14_continue_flow_at_ask_age_no_interrupt(driver):
    """A bare age answer triggers no interrupt; existing state machine
    handles the turn and advances to ASK_CHALLENGE."""
    sender = "p14"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს"])
    _force_state(sender, "ASK_AGE")

    response = conversation_service.process_message(
        sender, "14 წლის არის", "instagram",
    )
    # Normal discovery — state machine renders PARENT_ASK_CHALLENGE.
    convo = conversation_service.conversations[sender]
    assert convo.state == "ASK_CHALLENGE"
    assert convo.lead.child_age == "14 წლის არის"  # stored as-is by state handler
    # No interrupt-style response (no manager / phone-ask).
    assert "მენეჯერ" not in response
    assert "2150" not in response


# -- test 15. Fake booking prevention -----------------------------------


def test_15_fake_booking_prevention_when_calendar_fails(
    driver, monkeypatch,
):
    """PART 8: with calendar_service.book_slot mocked to fail, the
    response must NOT contain confirmation language even though the
    user provided a full date/time + the lead has name + phone."""
    from app.services import calendar_service

    monkeypatch.setattr(calendar_service, "check_slot_available",
                        lambda dt, duration_minutes=30: False)
    # Should never even be called — but make the failure explicit.
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda **kwargs: False)

    sender = "p15"
    driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს", "8"])
    _force_state(sender, "ASK_CHALLENGE", child_age="8")
    # Pre-populate phone so the router takes the booking-attempt path.
    convo = conversation_service.conversations[sender]
    convo.lead.phone = "599123456"

    response = conversation_service.process_message(
        sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე", "instagram",
    )
    # Forbidden confirmation language.
    for fake in (
        "დაგაჯავშნე", "დაჯავშნილია", "ჩაწერილი ხართ", "ჩაგწერეთ",
    ):
        assert fake not in response, f"fake confirmation {fake!r} leaked"
    # State must not transition to DONE.
    assert convo.state != "DONE"


# -- test 16. Tone regression — no robotic phrases ----------------------


def test_16_no_robotic_phrases_in_any_interrupt_response(driver, monkeypatch):
    """Iterate every interrupt intent and assert the response is free of
    forbidden menu-style phrasing (PART 4 style guide)."""
    samples: list[tuple[str, str]] = [
        ("p16-identity",     "შენ ვინ ხარ?"),
        ("p16-booking-no-dt", "კონსულტაციაზე ჩაწერა მინდა"),
        ("p16-manager",      "მენეჯერი დამიკავშირდეს"),
        ("p16-price",        "ფასი რა არის?"),
        ("p16-dates",        "როდის არის ბანაკი?"),
        ("p16-location",     "სად ტარდება?"),
        ("p16-conditions",   "ბავშვების ბანაკის პირობები"),
        ("p16-registration", "რეგისტრაციის ლინკი მომეცით"),
    ]
    for sender, message in samples:
        driver(sender, ["გამარჯობა, ბანაკი მაინტერესებს"])
        _force_state(sender, "ASK_CHALLENGE")
        response = conversation_service.process_message(sender, message, "instagram")
        lowered = response.lower()
        for robotic in ROBOTIC_PHRASES:
            assert robotic not in lowered, (
                f"sender={sender} (message={message!r}): "
                f"forbidden robotic phrase {robotic!r} in response\n"
                f"--- response ---\n{response}\n--- /response ---"
            )
