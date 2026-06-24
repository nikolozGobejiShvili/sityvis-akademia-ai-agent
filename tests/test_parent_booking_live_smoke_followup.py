"""Live Smoke Followup (2026-06-10) — PARENT booking confirmation wording.

Two live-transcript bugs fixed here, deterministically:

PART 1 — Confirmation + extra question in the SAME message must still
register as a booking confirmation (so the agent answers the question
and proceeds to booking instead of re-asking „დავადასტუროთ?").
Root cause: `_user_confirmed_booking` only matched the WHOLE message
exactly; „კი მაწყობს ეს დრო, მენეჯერი რომელ საათამდე მუშაობს?" failed.
Also `_BOOKING_OFFER_STEMS` missed the real offer wording
(„თავისუფალია … დამიდასტურეთ … ჩავნიშნავ").

PART 2 — „მადლობა თქვენ" opener must appear on a booking confirmation
ONLY when the user actually thanked. For a plain „კი მინდა" confirmation
the opener is stripped deterministically.

PART 3 — eligible-age goal/challenge hint is asked once (when unknown)
and not re-asked once known; it never blocks an explicit booking.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine as engine
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _conv(history=None, child_age="12", challenge="", booked=False):
    conv = Conversation(sender_id="smoke_user", platform="instagram")
    conv.lead = Lead(
        sender_id="smoke_user", platform="instagram", segment="PARENT",
        child_age=child_age, challenge=challenge,
    )
    conv.lead.calendly_booked = booked
    conv.history = list(history or [])
    return conv


def _offer_turn():
    return {
        "role": "assistant",
        "content": (
            "11 ივნისს, 18:00 საათი თავისუფალია. თუ ეს დრო გაწყობთ, "
            "დამიდასტურეთ და კონსულტაციას ჩავნიშნავ."
        ),
    }


# ===========================================================================
# PART 1 — confirmation + extra question
# ===========================================================================


def test_offer_wording_is_recognised_as_booking_offer():
    """The real brand offer wording must register as a booking offer."""
    conv = _conv(history=[_offer_turn()])
    assert engine._last_bot_offered_booking(conv) is True


@pytest.mark.parametrize("msg", [
    "კი მაწყობს ეს დრო ის რომელ საათამდე მუშაობს მენეჯერი?",
    "კი მაწყობს ეს დრო, მენეჯერი რომელ საათამდე მუშაობს?",
    "კი მინდა, ეს დრო დამიტოვეთ",
    "მაწყობს, რამდენ ხანს გაგრძელდება?",
    "ვადასტურებ, ეს დრო შესანიშნავია",
    "დამიდასტურეთ ეს დრო",
])
def test_confirmation_with_extra_question_is_detected(msg):
    assert engine._user_confirmed_booking(msg) is True


@pytest.mark.parametrize("msg", [
    "კი",
    "დიახ",
    "მინდა",
    "კი მინდა",
    "კიმინდა",
    "მაწყობს",
])
def test_bare_confirmations_still_detected(msg):
    assert engine._user_confirmed_booking(msg) is True


@pytest.mark.parametrize("msg", [
    "არა, არ მინდა",
    "არ მაწყობს ეს დრო",
    "ვერ მოვალ ამ დროს",
    "კი, მაგრამ ჯერ ფასი მაინტერესებს",   # soft objection, not a clean yes
    "მინდა ვიცოდე ფასი",                    # unrelated "მინდა"
    "რამდენი ღირს?",
    "",
])
def test_non_confirmations_not_detected(msg):
    assert engine._user_confirmed_booking(msg) is False


def test_confirmation_after_offer_injects_proceed_hint_not_reask():
    """When the bot offered a slot and the user confirms (with a trailing
    question), the sales context tells the LLM to proceed directly and
    NOT re-ask for confirmation."""
    conv = _conv(history=[_offer_turn()])
    ctx = engine._build_sales_context(
        conv, conv.lead,
        "კი მაწყობს ეს დრო ის რომელ საათამდე მუშაობს მენეჯერი?",
    )
    assert "პირდაპირ გააგრძელე ჩაწერის ფლოუ" in ctx
    assert "book_consultation" in ctx
    # Must NOT instruct another "გსურთ კონსულტაცია?" question.
    assert "ნუ" in ctx and "გსურთ კონსულტაცია" in ctx


# ===========================================================================
# PART 2 — "მადლობა თქვენ" only on real thanks
# ===========================================================================


_BOOKING_CONFIRM_TEXT = (
    "მადლობა თქვენ. კონსულტაცია ჩანიშნულია 11 ივნისს, 18:00 საათზე. "
    "მენეჯერი დაგიკავშირდებათ."
)


@pytest.mark.parametrize("user_msg", ["კი მინდა", "კი მაწყობს", "ვადასტურებ"])
def test_thanks_opener_stripped_for_non_thanks_confirmation(user_msg):
    conv = _conv(booked=True)
    out = parent_flow._strip_unwarranted_thanks_in_booking_confirmation(
        conv, user_msg, _BOOKING_CONFIRM_TEXT,
    )
    assert not out.startswith("მადლობა თქვენ")
    # The actual confirmation content is preserved.
    assert "კონსულტაცია ჩანიშნულია" in out
    assert "მენეჯერი დაგიკავშირდებათ" in out


@pytest.mark.parametrize("user_msg", [
    "მადლობა",
    "დიდი მადლობა",
    "მადლობა თქვენ",
    "გმადლობთ ძალიან",
])
def test_thanks_opener_preserved_when_user_thanked(user_msg):
    conv = _conv(booked=True)
    out = parent_flow._strip_unwarranted_thanks_in_booking_confirmation(
        conv, user_msg, _BOOKING_CONFIRM_TEXT,
    )
    assert out.startswith("მადლობა თქვენ")


def test_strip_noop_for_non_booking_response():
    """A non-confirmation response is never altered."""
    conv = _conv()
    text = "მადლობა თქვენ. რით შემიძლია დაგეხმაროთ?"
    out = parent_flow._strip_unwarranted_thanks_in_booking_confirmation(
        conv, "კი მინდა", text,
    )
    assert out == text


def test_user_message_has_thanks_detection():
    assert parent_flow._user_message_has_thanks("დიდი მადლობა") is True
    assert parent_flow._user_message_has_thanks("გმადლობთ") is True
    assert parent_flow._user_message_has_thanks("კი მინდა") is False


# ===========================================================================
# PART 3 — challenge / goal capture hint
# ===========================================================================


def test_eligible_no_challenge_asks_goal_question():
    conv = _conv(child_age="12", challenge="")
    ctx = engine._build_sales_context(conv, conv.lead, "12 წლის არის")
    assert "რის მიღებაც გსურთ ბანაკიდან" in ctx
    # And explicitly tells the model not to let the goal block booking.
    assert "ჩაწერა" in ctx


def test_eligible_with_challenge_does_not_reask_goal():
    conv = _conv(child_age="12", challenge="ეკრანთან დროის შემცირება")
    ctx = engine._build_sales_context(conv, conv.lead, "ეკრანს ბევრს უყურებს")
    assert "რის მიღებაც გსურთ ბანაკიდან" not in ctx
    assert "მიზანი ცნობილია" in ctx


def test_confirmation_branch_takes_priority_over_goal_question():
    """An explicit booking confirmation after an offer must NOT trigger
    the goal question — booking is never blocked by challenge capture."""
    conv = _conv(child_age="12", challenge="", history=[_offer_turn()])
    ctx = engine._build_sales_context(conv, conv.lead, "კი მინდა")
    assert "პირდაპირ გააგრძელე ჩაწერის ფლოუ" in ctx
    assert "რის მიღებაც გსურთ ბანაკიდან" not in ctx
