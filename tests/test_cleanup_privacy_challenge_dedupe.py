"""Cleanup Fix (2026-06-11) — privacy-notice timing + challenge text dedupe.

BUG A — the child-data privacy notice must appear EXACTLY ONCE, and only on
the turn a consultation booking OR reschedule SUCCEEDS (executor signal). It
must never appear on contact-request / slot-offer / slot-check turns, on a
failed booking, or on the turn after a success.

BUG B — the PARENT `lead.challenge` (written verbatim to the Sheets CRM) must
not carry duplicated concepts or embedded factual questions, and a reschedule
must reuse the clean existing challenge without re-appending.

All deterministic; no network.
"""

from __future__ import annotations

import pytest

from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services.session_key_service import conversation_cache_key


@pytest.fixture
def success_flag():
    """Set/clear the per-conversation booking-success signal."""
    from app.agent.tools.parent_tool_executor import (
        book_consultation_success_for_conversation,
    )

    def _set(sender_id: str, value: bool) -> None:
        cache_key = conversation_cache_key(platform="instagram", sender_id=sender_id)
        if value:
            book_consultation_success_for_conversation[cache_key] = True
        else:
            book_consultation_success_for_conversation.pop(cache_key, None)

    yield _set
    book_consultation_success_for_conversation.clear()


def _conv(sender_id: str = "s_priv") -> Conversation:
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    return conv


_NOTE = "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის და საჯაროდ არ გამოქვეყნდება."


# ===========================================================================
# BUG A — privacy notice timing
# ===========================================================================


def test_a1_contact_request_no_notice(success_flag):
    conv = _conv()
    success_flag(conv.sender_id, False)
    out = parent_flow._apply_privacy_notice_policy(
        conv, f"მომწერეთ თქვენი 9-ნიშნა საკონტაქტო ნომერი. {_NOTE}",
    )
    assert "გამოქვეყნდება" not in out
    assert "საკონტაქტო ნომერი" in out


def test_a2_slot_offer_no_notice(success_flag):
    conv = _conv()
    success_flag(conv.sender_id, False)
    out = parent_flow._apply_privacy_notice_policy(
        conv, f"შემოგთავაზებთ თავისუფალ დროებს. {_NOTE}",
    )
    assert "გამოქვეყნდება" not in out


def test_a3_slot_check_free_no_notice(success_flag):
    conv = _conv()
    success_flag(conv.sender_id, False)
    out = parent_flow._apply_privacy_notice_policy(
        conv, f"ეს დრო თავისუფალია. {_NOTE}",
    )
    assert "გამოქვეყნდება" not in out
    assert "თავისუფალია" in out


def test_a4_successful_booking_notice_once(success_flag):
    conv = _conv()
    success_flag(conv.sender_id, True)
    out = parent_flow._apply_privacy_notice_policy(
        conv, "10 ივნისს, 11:00 საათზე კონსულტაცია ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ.",
    )
    assert out.count("გამოქვეყნდება") == 1
    assert out.endswith(_NOTE)


def test_a5_successful_reschedule_notice_once(success_flag):
    conv = _conv()
    success_flag(conv.sender_id, True)
    out = parent_flow._apply_privacy_notice_policy(
        conv, "ახალი დრო ჩაგინიშნეთ. ძველი კონსულტაცია გაუქმებულია.",
    )
    assert out.count("გამოქვეყნდება") == 1


def test_a6_failed_booking_no_notice(success_flag):
    conv = _conv()
    success_flag(conv.sender_id, False)
    out = parent_flow._apply_privacy_notice_policy(
        conv, "ამ დროის დაჯავშნა ვერ დავადასტურე.",
    )
    assert "გამოქვეყნდება" not in out


def test_a7_never_more_than_once_even_if_llm_repeats(success_flag):
    conv = _conv()
    success_flag(conv.sender_id, True)
    # The LLM emitted the note TWICE; the policy must collapse to one.
    out = parent_flow._apply_privacy_notice_policy(
        conv, f"კონსულტაცია ჩაგინიშნეთ. {_NOTE} {_NOTE}",
    )
    assert out.count("გამოქვეყნდება") == 1


def test_a8_turn_after_success_no_notice(success_flag):
    """The flag is per-turn; once it is cleared (next turn) no note."""
    conv = _conv()
    success_flag(conv.sender_id, False)  # next turn — flag cleared
    out = parent_flow._apply_privacy_notice_policy(
        conv, f"კი, კიდევ რით დაგეხმაროთ? {_NOTE}",
    )
    assert "გამოქვეყნდება" not in out


def test_a9_sanitise_chokepoint_strips_on_non_success(success_flag):
    """Through the real _sanitise_booking_confirmation chokepoint: a
    non-booking turn with a leaked note gets the note stripped."""
    conv = _conv()
    success_flag(conv.sender_id, False)
    out = parent_flow._sanitise_booking_confirmation(
        conv, f"რა გაინტერესებთ ბანაკის შესახებ? {_NOTE}",
    )
    assert "გამოქვეყნდება" not in out


def test_a10_ordinary_sentence_not_removed(success_flag):
    """The matcher must not eat an ordinary sentence lacking the triple."""
    conv = _conv()
    success_flag(conv.sender_id, False)
    msg = "მეტი ინფორმაცია მენეჯერთან შეგიძლიათ მიიღოთ."
    out = parent_flow._apply_privacy_notice_policy(conv, msg)
    assert out == msg


# ===========================================================================
# BUG B — challenge TEXT duplication within a row
# ===========================================================================


def _save_challenge(sender_id: str, *challenges: str) -> Lead:
    """Save one or more challenge strings through the real executor and
    return the resulting lead."""
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = lead
    ex = ParentToolExecutor(
        conversation=conv, lead=lead, sender_id=sender_id, platform="instagram",
    )
    for c in challenges:
        ex.execute("save_lead_info", {"challenge": c})
    return lead


def test_b1_clean_list_unchanged():
    lead = _save_challenge("b1", "ეკრანისგან დისტანცია, მეგობრები, კომუნიკაცია")
    assert lead.challenge == "ეკრანისგან დისტანცია, მეგობრები, კომუნიკაცია"


def test_b2_embedded_question_dropped():
    lead = _save_challenge("b2", "კომუნიკაცია, მეგობრები და ასევე მაინტერესებს ფასი?")
    assert "ფასი" not in lead.challenge
    assert "კომუნიკაცია" in lead.challenge


def test_b3_repeated_concept_collapsed():
    from app.agent.llm.parent_llm_engine import dedupe_challenge_text
    assert dedupe_challenge_text(
        "მეგობრები კომუნიკაცია მეგობრები კომუნიკაცია",
    ) == "მეგობრები კომუნიკაცია"
    lead = _save_challenge("b3", "მეგობრები კომუნიკაცია მეგობრები კომუნიკაცია")
    assert lead.challenge == "მეგობრები კომუნიკაცია"


def test_b4_resaving_same_challenge_does_not_duplicate():
    """Re-saving the same concept across turns (booking / reschedule /
    adult→parent re-entry) must never double the text."""
    lead = _save_challenge(
        "b4", "მეგობრები კომუნიკაცია", "მეგობრები კომუნიკაცია",
    )
    assert lead.challenge == "მეგობრები კომუნიკაცია"
    assert lead.challenge.count("მეგობრები") == 1


def test_b5_reschedule_does_not_touch_challenge():
    """`_reschedule_booking` must not append to / duplicate the challenge."""
    import inspect
    from app.agent.tools import parent_tool_executor
    src = inspect.getsource(parent_tool_executor.ParentToolExecutor._reschedule_booking)
    assert "lead.challenge" not in src  # never writes challenge


def test_b6_merge_across_turns_dedupes():
    lead = _save_challenge(
        "b6", "მეგობრები", "კომუნიკაცია", "მეგობრები კომუნიკაცია",
    )
    # No concept appears twice.
    assert lead.challenge.lower().count("მეგობრები") == 1
    assert lead.challenge.lower().count("კომუნიკაცია") == 1


def test_b7_adult_interest_not_leaked_into_parent_challenge():
    lead = _save_challenge("b7", "ზრდასრულთა კულტურული საღამო მაინტერესებს")
    assert lead.challenge == ""  # rejected, not stored as parent challenge


def test_b8_parent_executor_never_writes_event_interest():
    lead = _save_challenge("b8", "მეგობრები, კომუნიკაცია")
    assert (lead.event_interest or "") == ""  # parent executor owns challenge only


def test_b9_sheet_payload_matches_email_payload():
    from app.services.notification_service import _clean_challenge_for_email
    lead = _save_challenge("b9", "მეგობრები კომუნიკაცია მეგობრები კომუნიკაცია")
    sheet_payload = lead.to_sheet_row("ok")[6]            # the challenge column
    email_payload = _clean_challenge_for_email(lead.challenge)
    assert sheet_payload == "მეგობრები კომუნიკაცია"
    # No „ეკრან" canonicalisation here, so both are byte-identical + clean.
    assert email_payload == sheet_payload
    assert email_payload.count("მეგობრები") == 1


def test_b10_question_only_not_saved():
    lead = _save_challenge("b10", "ბანაკი როდის ტარდება?")
    assert lead.challenge == ""
