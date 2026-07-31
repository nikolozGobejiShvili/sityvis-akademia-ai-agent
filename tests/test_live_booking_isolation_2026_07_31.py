"""Live test 2026-07-31 (fourth run) — a confirmed booking was DELETED.

The parent booked a Disneyland consultation at 15:00, then asked for a SUNDAY
SCHOOL consultation. The logs show what happened:

    [book_consultation] reschedule scenario — rerouting to _reschedule_booking:
                        old_event_id=klq48ir1… old_iso=…15:00 new_iso=…10:00
    [CALENDAR] ✅ Event cancelled: event_id=klq48ir1…

"already booked + a different time" was read as "move it", so the Disneyland
appointment disappeared from the calendar. Three more defects in the same run:

  * tool_call args={'phone': '595***733'} → phone_valid=False → invalid_phone.
    The model handed back the MASKED phone from its own earlier message.
  * in='595999733' → [slot_check] requested_datetime=2025-07-16T17:00:00 →
    past_datetime. The confirmed-slot anchor stood down because the blanket
    digit test counted a bare phone as "names a datetime".
  * The prompts offered „მენეჯერს/კონსულტანტს" as interchangeable, so the
    booking confirmation told the parent a *consultant* would call.
"""
from __future__ import annotations

from pathlib import Path

from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    _is_masked_phone,
    _is_reschedule_scenario,
    _message_names_a_datetime,
)
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

BOOKED_ISO = "2026-08-01T15:00:00+04:00"
OTHER_ISO = "2026-08-01T10:00:00+04:00"
EVENT_ID = "klq48ir17gsgbt454s6prg37rk"


def _booked_lead() -> Lead:
    lead = Lead(sender_id="t-9", platform="messenger", segment="PARENT")
    lead.calendly_booked = True
    lead.calendar_event_id = EVENT_ID
    lead.booked_datetime_iso = BOOKED_ISO
    return lead


# ── A. a second program's consultation must not cancel the first ───────────


def _conversation() -> Conversation:
    return Conversation(sender_id="t-9", platform="messenger")


def _pin_current_program(monkeypatch, name: str) -> None:
    monkeypatch.setattr(
        parent_flow, "_resolve_consultation_program_name", lambda c, l: name,
    )


def test_legacy_callers_keep_the_old_behaviour_exactly():
    """Compatibility: with no `conversation` the classification is unchanged,
    so every existing caller and test stays byte-identical."""
    assert _is_reschedule_scenario(_booked_lead(), OTHER_ISO) is True


def test_a_new_time_for_the_SAME_program_still_moves_the_booking(monkeypatch):
    """Operator rule: one consultation per program. A parent must not end up
    holding both Monday and Tuesday for the same program, so naming a new time
    moves the existing appointment."""
    lead = _booked_lead()
    lead.consultation_program_name = "დისნეილენდი"
    _pin_current_program(monkeypatch, "დისნეილენდი")
    assert (
        _is_reschedule_scenario(lead, OTHER_ISO, conversation=_conversation()) is True
    )


def test_a_consultation_for_ANOTHER_program_never_cancels_the_first(monkeypatch):
    """The live data loss: a Sunday School consultation cancelled the parent's
    Disneyland appointment. Different programs are separate appointments."""
    lead = _booked_lead()
    lead.consultation_program_name = "დისნეილენდი"
    _pin_current_program(monkeypatch, "საკვირაო სკოლა")
    assert (
        _is_reschedule_scenario(lead, OTHER_ISO, conversation=_conversation()) is False
    )


def test_red_an_unresolvable_current_program_keeps_the_previous_behaviour(monkeypatch):
    """RED-check: the program comparison is the ONLY thing that spares the
    first booking. When the current program cannot be resolved, the old
    same-program behaviour returns rather than changing silently."""
    lead = _booked_lead()
    lead.consultation_program_name = "დისნეილენდი"
    _pin_current_program(monkeypatch, "")
    assert (
        _is_reschedule_scenario(lead, OTHER_ISO, conversation=_conversation()) is True
    )


def test_a_booking_with_no_recorded_program_keeps_the_previous_behaviour():
    assert (
        _is_reschedule_scenario(
            _booked_lead(), OTHER_ISO, conversation=_conversation(),
        )
        is True
    )


def test_the_same_moment_is_never_a_reschedule():
    assert _is_reschedule_scenario(_booked_lead(), BOOKED_ISO) is False


# ── B. a masked phone is a display artefact, not a phone ───────────────────


def test_masked_phone_is_recognised():
    for value in ("595***733", "595•••733", "5 9 5 * * * 7 3 3"):
        assert _is_masked_phone(value), value


def test_a_real_phone_is_not_treated_as_masked():
    for value in ("595999733", "595 999 733", "+995595999733", ""):
        assert not _is_masked_phone(value), value


# ── C. a bare phone does not name a datetime ───────────────────────────────


def test_a_bare_phone_reply_names_no_datetime():
    for message in ("595999733", "595 999 733", "ჩემი ნომერია 595999733"):
        assert not _message_names_a_datetime(message), message


def test_a_real_day_or_hour_is_still_detected():
    for message in (
        "ხვალ 3 საათზე",
        "იყოს 1 აგვისტო 10 საათი",
        "17:00",
        "ხვალ",
        "1 აგვისტოს",
    ):
        assert _message_names_a_datetime(message), message


def test_the_anchor_now_survives_a_bare_phone_reply():
    """The live failure: the parent re-sent their phone, the anchor stood down,
    and the model's 2025-07-16 reached Calendar as a past date."""
    conversation = Conversation(sender_id="t-9", platform="messenger")
    conversation.pending_booking = {"requested_datetime_iso": BOOKED_ISO}
    executor = ParentToolExecutor(
        conversation=conversation,
        lead=Lead(sender_id="t-9", platform="messenger", segment="PARENT"),
        sender_id="t-9",
        platform="messenger",
        user_message="595999733",
    )
    assert (
        executor._normalise_datetime_iso_from_message("2025-07-16T17:00:00+04:00")
        == BOOKED_ISO
    )


# ── D. the manager answer never refuses ────────────────────────────────────


def test_manager_number_answer_never_refuses():
    """`_render_manager_number_answer` either gives the configured number or
    promises a callback. Every „I'm not allowed to share it" reply seen live
    was model-written, which means the deterministic handler never ran."""
    out = parent_flow._render_manager_number_answer(
        Lead(sender_id="t-9", platform="messenger", segment="PARENT")
    )
    assert out.strip()
    for refusal in ("ვერ გაგიზიარებ", "არ შემიძლია", "კომპეტენცი", "უფლება"):
        assert refusal not in out, out


def test_the_exact_live_manager_requests_are_detected():
    for message in (
        "მენჯერის ნომერი რომ მომწეროთ შეგიძლიათ ?",
        "მენჯერის ნომრი რომმომწეროთ",
    ):
        assert parent_flow._is_explicit_manager_number_request(message), message


# ── E. the prompts name ONE role for the person who calls back ─────────────

_AGENT = Path(parent_flow.__file__).resolve().parents[1] / "agent"


def test_live_prompts_no_longer_offer_manager_or_consultant_as_a_choice():
    """The „მენეჯერს/კონსულტანტს" alternative let the model pick either, and
    live it told the parent a consultant would call."""
    for stem in ("system_parent_v2.md", "parent_lean.md"):
        text = (_AGENT / "prompts" / stem).read_text(encoding="utf-8")
        assert "/კონსულტანტ" not in text, stem


def test_parent_templates_say_the_manager_calls_back():
    for name in ("booking.yaml", "contact.yaml"):
        text = (_AGENT / "templates" / "parent" / name).read_text(encoding="utf-8")
        assert "კონსულტანტი" not in text, name


def test_the_agent_may_still_describe_itself_as_a_consultant():
    """Only the CALLBACK role was wrong. The agent itself is an online
    consultant, and that self-description must survive."""
    text = (_AGENT / "prompts" / "system_parent_v2.md").read_text(encoding="utf-8")
    assert "ონლაინ-კონსულტანტი" in text
