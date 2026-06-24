"""Rollback-safety regression tests for the 2026-06-24 surgical guard
narrowing (Response Planner Hardening / Turn Intent Gateway).

Two surgical changes are covered:
  Change A — reasoning_layer.block_event_inquiry no longer blocks an ADULT-EVENT
             question merely because it states a (child) age; the age-as-date
             protection is preserved for every other topic.
  Change B — reasoning_layer.is_adult_self fires for a mixed self+child message
             with an explicit self-ref; adult_llm_engine._maybe_capture_adult_target
             records the user's OWN age as adult_age (never as adult_target_age),
             keeping adult_age and child_age separate.

Plus regression guards that the KEPT safety fixes still hold (PII mask;
consultation-typo registration deferral).

Deterministic / offline — no LLM, no Calendar/Sheets/Meta/WhatsApp/email.
"""
from __future__ import annotations

import types

from app.reasoning.reasoning_layer import analyze_turn_intent
from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
from app.flows.parent_flow import _is_camp_registration_link_request
from app.services.conversation_service import _mask_user_phone_in_response
from app.models.lead import Lead


def _lead() -> Lead:
    return Lead(sender_id="t", platform="messenger", segment="ADULT")


# ─────────────────── Change A — adult-event age guard ───────────────────

def test_adult_event_question_with_child_age_not_blocked():
    """PART E #1 — an adult cultural-event question that mentions a child age
    must NOT be blocked (was routed to camp underage before the narrowing)."""
    t = analyze_turn_intent(
        "ზრდასრულთა კულტურული ღონისძიებები 7 წლის ბავშვებისთვის არის?"
    )
    assert t.topic == "adult_event"
    assert t.age == 7
    assert t.is_age_statement is True
    assert t.block_event_inquiry is False


def test_non_event_age_statement_still_blocks_event_inquiry():
    """The age-as-date protection is PRESERVED for non-adult-event topics —
    a bare camp/other age statement still blocks the event interceptor so a
    number is never read as a calendar day."""
    t = analyze_turn_intent("13 წლის არის")
    assert t.age == 13
    assert t.date_text is None
    assert t.topic != "adult_event"
    assert t.block_event_inquiry is True


def test_real_date_event_question_still_resolves():
    """A genuine calendar date must still NOT be blocked (regression guard for
    the day path)."""
    t = analyze_turn_intent("28 აგვისტოს რა ღონისძიებაა?")
    assert t.block_event_inquiry is False


# ─────────────────── Change B — mixed self+child intent ───────────────────

def test_mixed_self_child_does_not_store_own_age_as_child_target():
    """PART E #2 — „მე ვარ 30 წლის" is the USER'S age; it must NOT become the
    child's adult_target_age. adult_age and child_age stay separate."""
    lead = _lead()
    _maybe_capture_adult_target(
        "ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება მე ვარ 30 წლის", lead,
    )
    assert lead.adult_target_age != "30"
    assert (lead.adult_target_age or "") == ""     # child age unknown, not 30
    assert lead.adult_age == "30"                   # own age captured separately
    assert (lead.child_age or "") == ""             # never cross-written


def test_mixed_self_child_gateway_is_adult_self_true():
    t = analyze_turn_intent(
        "ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება მე ვარ 30 წლის"
    )
    assert t.is_self_reference is True
    assert t.is_child_reference is True
    assert t.is_adult_self is True                  # broadened (was False)


def test_pure_relative_age_still_captured():
    """„ჩემი 14 წლის დისთვის" has NO self-age marker, so 14 is the relative's
    age and must still be captured (no regression to the working case)."""
    lead = _lead()
    _maybe_capture_adult_target("ჩემი 14 წლის დისთვის ღონისძიება მინდა", lead)
    assert lead.adult_target_relation == "და"
    assert lead.adult_target_age == "14"
    assert (lead.adult_age or "") == ""


def test_pure_child_message_is_not_adult_self():
    """A pure child message (no self-ref) must still NOT be adult-self."""
    t = analyze_turn_intent("ჩემი 8 წლის შვილისთვის ღონისძიება მინდა")
    assert t.is_child_reference is True
    assert t.is_self_reference is False
    assert t.is_adult_self is False


def test_pure_adult_self_still_works():
    """Pure adult-self behavior (the RPH fix) is preserved."""
    t = analyze_turn_intent("ჩემთვის მინდა ღონისძიებები რას შემომთავაზებთ?")
    assert t.is_adult_self is True


# ─────────────────── Kept safety fixes (regression guards) ───────────────────

def test_full_phone_never_leaks():
    """PART E #3 — the user's own full phone is always masked in the reply."""
    conv = types.SimpleNamespace(lead=types.SimpleNamespace(phone="595999733"))
    out = _mask_user_phone_in_response(
        conv, "დაგიკავშირდებით 595999733 ნომერზე.",
    )
    assert "595999733" not in out
    assert "595***733" in out


def test_consultation_typo_does_not_trigger_registration_link():
    """PART E #4/#5 — the consultation typo („კოსულტ") still defers, so a camp
    registration LINK is not returned."""
    assert _is_camp_registration_link_request("კოსულტაციაზე მინდა ჩაწერა") is False
    # a real registration ask still qualifies
    assert _is_camp_registration_link_request("ბანაკის რეგისტრაციის ბმული მინდა") is True
