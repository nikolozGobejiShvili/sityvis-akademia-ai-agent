"""Live QA Session 7 Patch — Reschedule cleanup, Adult dead-end,
Adult target wording revert, Manager email polish, WhatsApp blank-token,
Booking confirmation shortening.

Six bugs surfaced in the 2026-06-06 live Facebook/Messenger transcript
after the Session 6 FULL Live QA Patch shipped:

  Bug 1 CRITICAL — Reschedule created a new Calendar event but did
                   NOT cancel the old one. ``pending_booking`` state
                   was lost across the confirmation turn so the LLM
                   committed via ``book_consultation`` instead of
                   ``manage_consultation_booking``. Result: two active
                   consultations for one user.
  Bug 2          — PARENT engine dead-ended after the cross-flow
                   transition to ADULT („გასაგებია, ზრდასრულთა
                   ღონისძიებებზე დაგეხმარებით.") with no follow-up
                   question.
  Bug 3          — Adult target question wording reverted to brand-
                   owner-preferred „თქვენთვის თუ თქვენი შვილისთვის?".
                   The Session 6 intermediate „სხვა ადამიანისთვის?"
                   wording is gone.
  Bug 4          — Manager email subject was the placeholder „ახალი
                   ლიდი" even with a name on the lead; body duplicated
                   challenge text and used the same „ლიდი" headline
                   even on a booked consultation.
  Bug 5          — WhatsApp credentials empty in the live `.env`
                   produced „Illegal header value b'Bearer '" + noisy
                   traceback. Email channel must stay independent.
  Bug 6          — Booking confirmation included help CTA + privacy
                   note even on the immediate success turn — too long.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.agent.llm import adult_llm_engine
from app.agent.llm.adult_llm_engine import (
    _ADULT_FOLLOWUP_QUESTION_WHO,
    _ADULT_FOLLOWUP_QUESTION_WHO_OR_OTHER,
    _ensure_adult_intro_followup,
    sanitise_adult_response,
)
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import (
    ParentToolExecutor,
    RESCHEDULE_INTENT_PHRASES,
    _is_reschedule_scenario,
)
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import notification_service


TBILISI = ZoneInfo("Asia/Tbilisi")


def _conv_with_booking() -> tuple[Conversation, Lead]:
    """Helper: lead is already booked at 10 June 11:00 with a known
    event_id, simulating the live setup."""
    conv = Conversation(
        sender_id="s_session7", platform="instagram", segment="PARENT",
        state="DONE",
    )
    lead = Lead(
        sender_id="s_session7", platform="instagram", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
        calendly_booked=True,
        booked_datetime_iso="2026-12-10T11:00:00+04:00",
        calendar_event_id="evt_original_11_00",
        status="Booked",
    )
    conv.lead = lead
    return conv, lead


# =========================================================================
# BUG 1 — Reschedule cleanup
# =========================================================================


def test_is_reschedule_scenario_detects_active_booking_plus_new_slot():
    _, lead = _conv_with_booking()
    assert _is_reschedule_scenario(
        lead, "2026-12-10T19:00:00+04:00",
    ) is True


def test_is_reschedule_scenario_returns_false_when_no_active_booking():
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT")
    assert _is_reschedule_scenario(
        lead, "2026-12-10T19:00:00+04:00",
    ) is False


def test_is_reschedule_scenario_returns_false_when_same_slot():
    _, lead = _conv_with_booking()
    # Same as current booking → NOT a reschedule.
    assert _is_reschedule_scenario(
        lead, lead.booked_datetime_iso,
    ) is False


def test_is_reschedule_scenario_requires_calendar_event_id():
    _, lead = _conv_with_booking()
    lead.calendar_event_id = ""
    assert _is_reschedule_scenario(
        lead, "2026-12-10T19:00:00+04:00",
    ) is False


def test_reschedule_intent_phrases_cover_live_examples():
    # Phrases from the live trace.
    samples = [
        "მაგ დროს არ მცალია",
        "შესაძლებელია 10 ივნის 7 საათზე ჩამწეროთ?",
        "გადამიტანეთ ხუთშაბათს",
        "სხვა დროს მინდა",
        "ძველი წაშალეთ და ახალ დროზე ჩამწერეთ",
    ]
    for text in samples:
        lowered = text.lower()
        assert any(p in lowered for p in RESCHEDULE_INTENT_PHRASES), (
            f"no reschedule phrase matched in: {text!r}"
        )


def test_check_consultation_slot_marks_pending_as_reschedule(monkeypatch):
    """When the lead is already booked and the user proposes a
    DIFFERENT free slot, the pending_booking source is „reschedule"
    and the old event_id is stashed."""
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt: (True, None),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only", lambda dt: True,
    )

    conv, lead = _conv_with_booking()
    exe = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id="s_session7", platform="instagram",
        user_message="შესაძლებელია 10 ივნის 7 საათზე ჩამწეროთ?",
    )
    result = exe._check_consultation_slot({
        "datetime_iso": "2026-12-10T19:00:00+04:00",
    })
    assert result["available"] is True
    pending = conv.pending_booking
    assert pending is not None
    assert pending["source"] == "reschedule"
    assert pending["old_event_id"] == "evt_original_11_00"
    assert pending["old_booked_datetime_iso"] == "2026-12-10T11:00:00+04:00"
    assert pending["requested_datetime_iso"] == "2026-12-10T19:00:00+04:00"


def test_check_consultation_slot_keeps_user_requested_source_when_not_booked(
    monkeypatch,
):
    """When the lead is NOT already booked, the source stays the
    legacy „user_requested_exact_slot" — no reschedule marker."""
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "is_within_business_hours",
        lambda dt: (True, None),
    )
    monkeypatch.setattr(
        calendar_service, "check_slot_calendar_only", lambda dt: True,
    )

    conv = Conversation(
        sender_id="s_no_book", platform="instagram", segment="PARENT",
    )
    lead = Lead(
        sender_id="s_no_book", platform="instagram", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
    )
    conv.lead = lead
    exe = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id="s_no_book", platform="instagram",
        user_message="10 ივნისს 11 საათზე მინდა",
    )
    result = exe._check_consultation_slot({
        "datetime_iso": "2026-12-10T11:00:00+04:00",
    })
    assert result["available"] is True
    pending = conv.pending_booking
    assert pending is not None
    assert pending["source"] == "user_requested_exact_slot"
    assert "old_event_id" not in pending


def test_book_consultation_reroutes_to_reschedule_when_already_booked(
    monkeypatch,
):
    """The executor's safety net: even if `_check_consultation_slot`
    never ran, `_book_consultation` detects the already-booked-at-
    different-time scenario and reroutes through `_reschedule_booking`
    instead of creating a second event."""
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )

    book_calls: list[str] = []
    cancel_calls: list[str] = []

    def fake_book(conv, lead, slot):
        # First call: confirm new event_id stamped before old cancel.
        book_calls.append(slot["datetime_iso"])
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_new_19_00"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    def fake_cancel(event_id):
        cancel_calls.append(event_id)
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event", fake_cancel,
    )
    # Sheets is mocked to avoid hitting real Google Sheets.
    import app.services.sheets_service as sheets_service
    monkeypatch.setattr(
        sheets_service, "update_lead", lambda sender_id, payload: True,
    )

    conv, lead = _conv_with_booking()
    exe = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id="s_session7", platform="instagram",
        user_message="კი მაწყობს ეგ დრო",
    )
    result = exe._book_consultation({
        "name": "ლუკა",
        "phone": "595999733",
        "child_age": "11",
        "datetime_iso": "2026-12-10T19:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is True
    assert result["action"] == "reschedule"
    # New event was created BEFORE old was cancelled (safe ordering).
    assert book_calls == ["2026-12-10T19:00:00+04:00"]
    assert cancel_calls == ["evt_original_11_00"]
    # No two active bookings: the lead now points at the new event.
    assert lead.calendar_event_id == "evt_new_19_00"
    assert lead.booked_datetime_iso == "2026-12-10T19:00:00+04:00"
    assert lead.calendly_booked is True


def test_reschedule_does_not_cancel_old_when_new_booking_fails(monkeypatch):
    """If the new Calendar event creation fails, the old booking MUST
    remain intact — old Calendar event is never touched, lead state is
    restored."""
    import app.services.calendar_service as calendar_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )

    cancel_calls: list[str] = []

    def fake_book_fails(conv, lead, slot):
        # Simulate Calendar failure (no event created, no event_id).
        return False

    def fake_cancel(event_id):
        cancel_calls.append(event_id)
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book_fails)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event", fake_cancel,
    )

    conv, lead = _conv_with_booking()
    exe = ParentToolExecutor(
        conversation=conv, lead=lead,
        sender_id="s_session7", platform="instagram",
        user_message="კი მაწყობს",
    )
    result = exe._book_consultation({
        "name": "ლუკა",
        "phone": "595999733",
        "child_age": "11",
        "datetime_iso": "2026-12-10T19:00:00+04:00",
        "user_confirmed_datetime": True,
    })
    assert result["success"] is False
    # Old Calendar event must NOT have been cancelled.
    assert cancel_calls == []
    # Lead state restored to the original booking.
    assert lead.calendar_event_id == "evt_original_11_00"
    assert lead.booked_datetime_iso == "2026-12-10T11:00:00+04:00"
    assert lead.calendly_booked is True


def test_pending_commit_reschedule_response_mentions_old_cancellation(
    monkeypatch,
):
    """End-to-end through `_maybe_commit_pending_booking_engine`:
    when the pending booking is a reschedule and the executor
    succeeds, the response includes „ძველი კონსულტაცია გაუქმებულია"."""
    import app.services.calendar_service as calendar_service
    import app.services.sheets_service as sheets_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )

    def fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_new_19_00"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event", lambda event_id: True,
    )
    monkeypatch.setattr(
        sheets_service, "update_lead", lambda sender_id, payload: True,
    )

    conv, lead = _conv_with_booking()
    # Seed the reschedule pending_booking (set by _check_consultation_slot
    # in the previous turn).
    conv.pending_booking = {
        "requested_datetime_iso": "2026-12-10T19:00:00+04:00",
        "requested_date_text": "10 დეკემბერი",
        "requested_time_text": "19:00",
        "user_confirmed_datetime": True,
        "source": "reschedule",
        "old_event_id": "evt_original_11_00",
        "old_booked_datetime_iso": "2026-12-10T11:00:00+04:00",
        "missing_fields": [],
    }
    response = parent_flow._maybe_commit_pending_booking_engine(
        conv, "კი მაწყობს",
    )
    assert response is not None
    assert "ჩაგინიშნეთ" in response
    assert "ძველი კონსულტაცია გაუქმებულია" in response
    assert "მენეჯერი დაგიკავშირდებათ" in response
    # Lead now points at the new booking.
    assert lead.calendar_event_id == "evt_new_19_00"
    assert lead.booked_datetime_iso == "2026-12-10T19:00:00+04:00"


def test_pending_commit_reschedule_old_cancel_failure_does_not_claim_success(
    monkeypatch,
):
    """When new booking succeeded but old cancel failed, the response
    must NOT claim the old was cancelled — surface a manager-handoff
    line instead."""
    import app.services.calendar_service as calendar_service
    import app.services.sheets_service as sheets_service

    monkeypatch.setattr(parent_flow, "TBILISI_TZ", TBILISI)
    monkeypatch.setattr(
        calendar_service, "check_slot_available", lambda dt: True,
    )

    def fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_new_19_00"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", fake_book)
    monkeypatch.setattr(
        calendar_service, "cancel_calendar_event", lambda event_id: False,
    )
    monkeypatch.setattr(
        sheets_service, "update_lead", lambda sender_id, payload: True,
    )

    conv, lead = _conv_with_booking()
    conv.pending_booking = {
        "requested_datetime_iso": "2026-12-10T19:00:00+04:00",
        "requested_date_text": "10 დეკემბერი",
        "requested_time_text": "19:00",
        "user_confirmed_datetime": True,
        "source": "reschedule",
        "old_event_id": "evt_original_11_00",
        "old_booked_datetime_iso": "2026-12-10T11:00:00+04:00",
        "missing_fields": [],
    }
    response = parent_flow._maybe_commit_pending_booking_engine(
        conv, "კი მაწყობს",
    )
    assert response is not None
    assert "გაუქმებულია" not in response  # NEVER claim the old was cancelled
    assert "მენეჯერ" in response


# =========================================================================
# BUG 2 — Adult intro followup catches PARENT-engine cross-flow dead-end
# =========================================================================


def test_parent_flow_adult_intro_followup_appends_question():
    conv = Conversation(
        sender_id="s_pf_a", platform="instagram", segment="PARENT",
    )
    response = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
    out = parent_flow._ensure_adult_intro_followup_for_parent_flow(
        conv, response,
    )
    assert "?" in out
    assert "თქვენი შვილისთვის" in out


def test_parent_flow_adult_intro_followup_skips_long_responses():
    conv = Conversation(
        sender_id="s_pf_a", platform="instagram", segment="PARENT",
    )
    # Over 120 chars OR already contains a question — no append.
    response = (
        "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. "
        "თქვენთვის ხომ? "  # already has a question mark
    )
    out = parent_flow._ensure_adult_intro_followup_for_parent_flow(
        conv, response,
    )
    # Question already present → only the original text returned.
    assert out.count("?") == 1


def test_parent_flow_adult_intro_followup_skips_when_no_topic_keyword():
    conv = Conversation(
        sender_id="s_pf_a", platform="instagram", segment="PARENT",
    )
    response = "გასაგებია, დაგეხმარებით."  # no adult-event keyword
    out = parent_flow._ensure_adult_intro_followup_for_parent_flow(
        conv, response,
    )
    # No topic keyword → no append.
    assert out == response


def test_adult_engine_intro_followup_uses_shvilistvis_wording():
    """The adult engine's followup question now uses the reverted
    brand-owner-preferred „თქვენი შვილისთვის?" wording."""
    response = "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით."
    lead = Lead(sender_id="s_ad", platform="instagram", segment="ADULT")
    out = _ensure_adult_intro_followup(response, lead)
    assert "?" in out
    assert "თქვენი შვილისთვის" in out


# =========================================================================
# BUG 3 — Adult target wording revert
# =========================================================================


def test_adult_followup_question_who_uses_shvilistvis_form():
    assert "თქვენი შვილისთვის" in _ADULT_FOLLOWUP_QUESTION_WHO
    assert "სხვა ადამიანისთვის" not in _ADULT_FOLLOWUP_QUESTION_WHO


def test_adult_followup_question_who_or_other_uses_shvilistvis_form():
    assert "თქვენი შვილისთვის" in _ADULT_FOLLOWUP_QUESTION_WHO_OR_OTHER


def test_sanitiser_normalises_skhva_adamianistvis_to_shvilistvis():
    raw = "ღონისძიების შერჩევა თქვენთვის გსურთ თუ სხვა ადამიანისთვის?"
    out = sanitise_adult_response(raw)
    assert "სხვა ადამიანისთვის" not in out
    assert "თქვენი შვილისთვის" in out


def test_relative_capture_for_dis_still_works():
    """The wording revert must NOT break sister/brother handling — the
    relative-capture path still records „და" → adult_target_relation."""
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = Lead(sender_id="s_rel", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target("ჩემი დისთვის მინდა ღონისძიება", lead)
    assert lead.adult_target_relation == "და"


def test_relative_capture_for_dzma_still_works():
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = Lead(sender_id="s_rel", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target(
        "ჩემი 30 წლის ძმისთვის მინდა ღონისძიება", lead,
    )
    assert lead.adult_target_relation == "ძმა"
    assert lead.adult_target_age == "30"


def test_relative_capture_for_friend_still_works():
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = Lead(sender_id="s_rel", platform="instagram", segment="ADULT")
    _maybe_capture_adult_target(
        "ჩემი მეგობრისთვის მინდა ღონისძიება", lead,
    )
    assert lead.adult_target_relation == "მეგობარი"


# =========================================================================
# BUG 4 — Manager email polish
# =========================================================================


def _lead_booked_with_name() -> Lead:
    return Lead(
        sender_id="s_email_booked", platform="instagram", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
        challenge="კომუნიკაცია განვითარება კომუნიკაცია განვითარება",
        calendly_booked=True,
        booked_datetime_iso="2026-12-10T19:00:00+04:00",
        status="Booked",
    )


def _lead_not_booked_with_name() -> Lead:
    return Lead(
        sender_id="s_email_new", platform="instagram", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
        challenge="კომუნიკაცია",
        status="Qualified",
    )


def _lead_no_name() -> Lead:
    return Lead(
        sender_id="s_email_anon", platform="instagram", segment="PARENT",
        phone="595999733", child_age="11",
    )


def test_email_subject_includes_name_when_booked():
    subj = notification_service._build_email_subject(_lead_booked_with_name())
    assert subj.startswith("ლუკა — ")
    assert "ახალი კონსულტაცია" in subj


def test_email_subject_includes_name_when_not_booked():
    subj = notification_service._build_email_subject(
        _lead_not_booked_with_name(),
    )
    assert subj.startswith("ლუკა — ")
    assert "ახალი ლიდი" in subj


def test_email_subject_falls_back_when_no_name():
    subj = notification_service._build_email_subject(_lead_no_name())
    assert subj == "ახალი ლიდი AI Agent-იდან"


def test_dedupe_collapses_repeated_phrase_pair():
    raw = "კომუნიკაცია განვითარება კომუნიკაცია განვითარება"
    out = notification_service._dedupe_repeated_phrase(raw)
    assert out == "კომუნიკაცია განვითარება"


def test_dedupe_collapses_single_repeated_token():
    raw = "კომუნიკაცია კომუნიკაცია"
    out = notification_service._dedupe_repeated_phrase(raw)
    assert out == "კომუნიკაცია"


def test_dedupe_returns_input_when_no_repetition():
    raw = "ეკრანისგან დისტანცია"
    out = notification_service._dedupe_repeated_phrase(raw)
    assert out == raw


def test_email_body_dedupes_challenge_phrase():
    body = notification_service._manager_email_body(_lead_booked_with_name())
    # The raw 4-word doubled phrase MUST be collapsed; it may legitimately
    # appear twice across distinct sections (structured details + summary)
    # but never four words long.
    assert (
        "კომუნიკაცია განვითარება კომუნიკაცია განვითარება" not in body
    )


def test_email_body_headline_changes_for_booked_lead():
    body = notification_service._manager_email_body(_lead_booked_with_name())
    assert "ახალი კონსულტაცია" in body
    assert "სახელი: ლუკა" in body
    assert "ტელეფონი: 595999733" in body
    assert "ბავშვის ასაკი: 11" in body


def test_email_body_headline_stays_lid_for_new_lead():
    body = notification_service._manager_email_body(
        _lead_not_booked_with_name(),
    )
    # First line should NOT carry „კონსულტაცია ჩაინიშნა" — lead is new.
    first_line = body.splitlines()[0]
    assert "ახალი ლიდი" in first_line
    assert "კონსულტაცია ჩაინიშნა" not in first_line


def test_email_body_summary_is_short_and_concrete_for_booked():
    body = notification_service._manager_email_body(_lead_booked_with_name())
    assert "მოკლე რეზიუმე:" in body
    # The booked summary mentions the consultation time.
    assert "კონსულტაცია ჩანიშნულია" in body


# =========================================================================
# BUG 5 — WhatsApp blank-token skip
# =========================================================================


def _patch_settings(monkeypatch, **overrides):
    swapped = dataclasses.replace(notification_service.settings, **overrides)
    monkeypatch.setattr(notification_service, "settings", swapped)


def test_whatsapp_skips_when_token_blank(monkeypatch):
    import app.services.notification_service as ns
    _patch_settings(
        monkeypatch,
        WHATSAPP_TOKEN="",
        WHATSAPP_PHONE_NUMBER_ID="1234",
        MANAGER_WHATSAPP_NUMBER="995595999733",
    )
    httpx_post = MagicMock()
    monkeypatch.setattr(ns.httpx, "post", httpx_post)
    result = ns._send_manager_whatsapp("body")
    assert result is False
    httpx_post.assert_not_called()


def test_whatsapp_skips_when_phone_number_id_blank(monkeypatch):
    import app.services.notification_service as ns
    _patch_settings(
        monkeypatch,
        WHATSAPP_TOKEN="EAAxyz",
        WHATSAPP_PHONE_NUMBER_ID="",
        MANAGER_WHATSAPP_NUMBER="995595999733",
    )
    httpx_post = MagicMock()
    monkeypatch.setattr(ns.httpx, "post", httpx_post)
    result = ns._send_manager_whatsapp("body")
    assert result is False
    httpx_post.assert_not_called()


def test_whatsapp_skips_when_manager_number_blank(monkeypatch):
    import app.services.notification_service as ns
    _patch_settings(
        monkeypatch,
        WHATSAPP_TOKEN="EAAxyz",
        WHATSAPP_PHONE_NUMBER_ID="1234",
        MANAGER_WHATSAPP_NUMBER="",
    )
    httpx_post = MagicMock()
    monkeypatch.setattr(ns.httpx, "post", httpx_post)
    result = ns._send_manager_whatsapp("body")
    assert result is False
    httpx_post.assert_not_called()


def test_whatsapp_skip_does_not_raise(monkeypatch):
    """Belt-and-braces — calling notify_manager with blank WhatsApp
    config must NOT raise even when httpx would have failed."""
    import app.services.notification_service as ns
    _patch_settings(
        monkeypatch,
        WHATSAPP_TOKEN="",
        WHATSAPP_PHONE_NUMBER_ID="",
        MANAGER_WHATSAPP_NUMBER="",
        ENABLE_EMAIL_NOTIFICATIONS=False,  # avoid SMTP setup
    )
    lead = Lead(
        sender_id="s_wa", platform="instagram", segment="PARENT",
        name="ლუკა", phone="595999733",
    )
    # Should NOT raise — both channels short-circuit cleanly.
    notification_service.notify_manager(lead, event_type="lead")


def test_whatsapp_skip_does_not_block_email(monkeypatch):
    """Email path must run independently of the WhatsApp skip."""
    import app.services.notification_service as ns
    _patch_settings(
        monkeypatch,
        WHATSAPP_TOKEN="",
        WHATSAPP_PHONE_NUMBER_ID="",
        MANAGER_WHATSAPP_NUMBER="",
        ENABLE_EMAIL_NOTIFICATIONS=True,
        MANAGER_EMAIL="ops@example.com",
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=587,
        SMTP_USER="ops@example.com",
        SMTP_PASSWORD="app-password",
        SMTP_FROM_EMAIL="ops@example.com",
    )
    send_email_mock = MagicMock(return_value=True)
    monkeypatch.setattr(ns, "_send_email", send_email_mock)
    lead = Lead(
        sender_id="s_wa", platform="instagram", segment="PARENT",
        name="ლუკა", phone="595999733",
    )
    ns.notify_manager(lead, event_type="lead")
    # Email was attempted; WhatsApp was NOT — no traceback.
    send_email_mock.assert_called_once()


# =========================================================================
# BUG 6 — Booking confirmation shortened
# =========================================================================


def test_trim_booking_success_strips_help_cta_when_tool_succeeded():
    from app.agent.tools.parent_tool_executor import (
        book_consultation_success_for_conversation,
    )
    conv = Conversation(
        sender_id="s_trim", platform="instagram", segment="PARENT",
    )
    book_consultation_success_for_conversation[conv.sender_id] = True
    raw = (
        "10 ივნისს, 19:00 საათზე კონსულტაცია ჩაგინიშნეთ. "
        "თუ დამატებითი კითხვა გაქვთ, მომწერეთ და დაგეხმარებით. "
        "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის და "
        "საჯაროდ არ გამოქვეყნდება."
    )
    out = parent_flow._trim_booking_success_response(conv, raw)
    assert "თუ დამატებითი კითხვა გაქვთ" not in out
    assert "საჯაროდ არ გამოქვეყნდება" not in out
    assert "კონსულტაცია ჩაგინიშნეთ" in out
    book_consultation_success_for_conversation.pop(conv.sender_id, None)


def test_trim_booking_success_no_op_when_not_success_turn():
    from app.agent.tools.parent_tool_executor import (
        book_consultation_success_for_conversation,
    )
    conv = Conversation(
        sender_id="s_no_trim", platform="instagram", segment="PARENT",
    )
    # Make sure no flag is set.
    book_consultation_success_for_conversation.pop(conv.sender_id, None)
    raw = (
        "10 ივნისს, 19:00 საათზე კონსულტაცია ჩაგინიშნეთ. "
        "თუ დამატებითი კითხვა გაქვთ, მომწერეთ და დაგეხმარებით."
    )
    out = parent_flow._trim_booking_success_response(conv, raw)
    # Untouched when no booking-success flag is set this turn.
    assert "თუ დამატებითი კითხვა გაქვთ" in out


def test_pending_commit_message_is_concise():
    """The deterministic pending-commit success response must be
    short: greeting + datetime + manager line. No help CTA, no privacy
    note."""
    # Build the success branch manually by walking the response
    # builder via a small stub.
    import app.services.calendar_service as calendar_service
    import app.services.sheets_service as sheets_service

    def fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.calendar_event_id = "evt_short"
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.status = "Booked"
        return True

    def with_monkeypatching():
        return None

    # Use pytest's monkeypatch fixture via a sub-call.
    conv = Conversation(
        sender_id="s_short", platform="instagram", segment="PARENT",
    )
    lead = Lead(
        sender_id="s_short", platform="instagram", segment="PARENT",
        name="ლუკა", phone="595999733", child_age="11",
    )
    conv.lead = lead
    conv.pending_booking = {
        "requested_datetime_iso": "2026-12-15T11:00:00+04:00",
        "requested_date_text": "15 დეკემბერი",
        "requested_time_text": "11:00",
        "user_confirmed_datetime": True,
        "source": "user_selected_slot",
        "missing_fields": [],
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(parent_flow, "TBILISI_TZ", TBILISI)
        mp.setattr(
            calendar_service, "check_slot_available", lambda dt: True,
        )
        mp.setattr(parent_flow, "_book_selected_slot", fake_book)
        mp.setattr(
            sheets_service, "update_lead",
            lambda sender_id, payload: True,
        )
        response = parent_flow._maybe_commit_pending_booking_engine(
            conv, "კი",
        )
    assert response is not None
    assert "ჩაგინიშნეთ" in response
    assert "მენეჯერი დაგიკავშირდებათ" in response
    # The short response MUST NOT carry the privacy / help filler.
    assert "თუ დამატებითი კითხვა გაქვთ" not in response
    assert "საჯაროდ არ გამოქვეყნდება" not in response
