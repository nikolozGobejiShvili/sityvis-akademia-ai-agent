"""Conversation Planner — AUTHORITATIVE mode (Phase 3 Stage 2) RESPONSE-LEVEL
tests. These drive `parent_flow.handle()` with both planner flags ON and assert
the FINAL response text / state effects (not just the planner decision).

Deterministic / offline: the LLM is either not reached (the planner answers
recall/booking/decline/name deterministically) or mocked (camp-safety validator).
No Calendar/Sheets/WhatsApp/email/Meta.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.models.lead import Lead
from app.models.conversation import Conversation
from app.flows import parent_flow
from app.reasoning import conversation_planner as cp


def _conv(state="IN_PROGRESS", **lead_kw):
    lead = Lead(sender_id="s1", platform="messenger", segment="PARENT")
    for k, v in lead_kw.items():
        setattr(lead, k, v)
    return Conversation(
        sender_id="s1", platform="messenger", segment="PARENT", state=state,
        lead=lead, history=[{"role": "assistant", "content": "prev"}],
    )


@pytest.fixture
def authoritative(monkeypatch):
    """Enable both planner flags (engine OFF — recall/booking/decline/name are
    answered deterministically by the planner, no LLM needed)."""
    swapped = dataclasses.replace(
        parent_flow.settings,
        USE_CONVERSATION_PLANNER=True,
        CONVERSATION_PLANNER_AUTHORITATIVE=True,
        USE_PARENT_LLM_ENGINE=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    return swapped


# ─────────────────── state recall (incl. typo) — response level ───────────────

def test_state_recall_typo_returns_summary_not_booking_question(authoritative):
    conv = _conv(
        state="DONE", name="ნუცა", phone="595999733", child_age="13",
        calendly_booked=True, booked_datetime_iso="2026-06-25T12:00",
    )
    resp = parent_flow.handle(conv, "გასაგებია ჩემზე რა ინფრომაცია გავქს?")
    assert "ნუცა" in resp
    assert "595***733" in resp and "595999733" not in resp     # masked, not leaked
    assert "13" in resp
    assert "კონსულტაცია" in resp                                # booking included
    # must NOT continue the booking flow / ask for a date-time
    assert "რომელი თარიღი" not in resp and "რა დროს" not in resp
    assert "რომელი დღე" not in resp


def test_booking_recall_uses_confirmed_booking(authoritative):
    conv = _conv(
        state="DONE", name="ნუცა", phone="595999733", child_age="13",
        calendly_booked=True, booked_datetime_iso="2026-06-25T12:00",
    )
    resp = parent_flow.handle(conv, "კონსულტაცია როდის მაქვს?")
    assert "25" in resp and "12" in resp                        # the booked slot
    assert "ახალ ჩაწერას აღარ" in resp                          # no new-consultation offer


def test_calm_correction_uses_existing_booking(authoritative):
    conv = _conv(
        state="DONE", name="ნუცა", phone="595999733", child_age="13",
        calendly_booked=True, booked_datetime_iso="2026-06-25T12:00",
    )
    resp = parent_flow.handle(conv, "აბა რატო მთავაზობ ახალ კონსულტაციას?")
    assert "ჩანიშნულია" in resp
    assert "ახალ ჩაწერას აღარ" in resp


# ─────────────────── decline closes adult context — response level ────────────

def test_decline_clears_adult_target_state(authoritative):
    conv = _conv(adult_target_relation="შვილი", adult_target_age="13")
    parent_flow.handle(conv, "არ მინდა მადლობა")
    assert (conv.lead.adult_target_relation or "") == ""
    assert (conv.lead.adult_target_age or "") == ""


# ─────────────────── name update does not continue underage flow ──────────────

def test_name_update_does_not_continue_underage(authoritative):
    conv = _conv(child_age="7")     # stale underage child on record
    resp = parent_flow.handle(conv, "ჩემი სახელია ნიკოლოზი")
    # must NOT answer with the 9–17 underage/camp-eligibility narrative
    assert "9" not in resp
    assert "ვერ შემოგთავაზებთ" not in resp
    assert "ასაკი" not in resp


# ─────────────────── camp safety must not use consultation format ─────────────

def test_camp_safety_strips_consultation_format(monkeypatch):
    """Engine ON + mocked: the LLM leaks the consultation phone/video format on a
    camp-safety turn; the authoritative validator strips it from the final
    response."""
    swapped = dataclasses.replace(
        parent_flow.settings,
        USE_CONVERSATION_PLANNER=True,
        CONVERSATION_PLANNER_AUTHORITATIVE=True,
        USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: (
            "ბანაკი უსაფრთხო და ორგანიზებული გარემოა. "
            "კონსულტაცია ძირითადად ტელეფონით ან ვიდეოზარით ტარდება და "
            "ვიზიტის ფორმატი არ მოიცავს ადგილზე მოსვლას."
        ),
    )
    conv = _conv(state="IN_PROGRESS", child_age="13")
    resp = parent_flow.handle(
        conv, "ბანაკზე უსაფრთხოება დაცულია? რამდენი ზედამხედველი ეყოლებათ?",
    )
    assert "ვიდეოზარით" not in resp
    assert "ვიზიტის ფორმატი" not in resp
    # the camp content (or a safe manager redirect) survives
    assert ("უსაფრთხო" in resp) or ("მენეჯერ" in resp)


def test_validator_unit_strips_consultation_format():
    """Direct response-transform check of the policy validator."""
    conv = _conv(child_age="13")
    plan = cp.plan_turn("ბანაკზე უსაფრთხოება დაცულია?", conv)
    polluted = (
        "ბანაკი უსაფრთხოა. კონსულტაცია ტელეფონით ან ვიდეოზარით ტარდება."
    )
    out = parent_flow._planner_validate_response(conv, plan, polluted)
    assert "ვიდეოზარით" not in out
    assert "უსაფრთხოა" in out or "მენეჯერ" in out


# ─────────────────── generic adult discovery not a named-event lookup ─────────

def test_discovery_suppresses_named_event_interceptor(monkeypatch):
    """A generic adult-event discovery (sticky PARENT) must not be consumed by
    the named-event interceptor („ამ სახელით ვერ ვპოულობ"). With the planner
    authoritative the interceptor is skipped and the turn proceeds."""
    swapped = dataclasses.replace(
        parent_flow.settings,
        USE_CONVERSATION_PLANNER=True,
        CONVERSATION_PLANNER_AUTHORITATIVE=True,
        USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: "ზრდასრულთა აქტიური ღონისძიებები გიჩვენებთ.",
    )
    # fail if the named-event interceptor runs at all
    def _boom(*a, **k):
        raise AssertionError("named-event interceptor must be skipped on discovery")
    monkeypatch.setattr(parent_flow, "_maybe_handle_event_inquiry", _boom)

    conv = _conv(state="IN_PROGRESS")
    resp = parent_flow.handle(conv, "ჩემთვის მინდა ღონისძიებები რას შემომთავაზებთ?")
    assert "ვერ ვპოულობ" not in resp


# ─────────────────── flags OFF → no authoritative effect (regression) ─────────

def test_flags_off_no_authoritative_effect(monkeypatch):
    """With CONVERSATION_PLANNER_AUTHORITATIVE OFF, the planner does not force a
    recall answer — behaviour falls through to the existing flow."""
    swapped = dataclasses.replace(
        parent_flow.settings,
        USE_CONVERSATION_PLANNER=True,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,   # shadow only
        USE_PARENT_LLM_ENGINE=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    conv = _conv(
        state="DONE", name="ნუცა", phone="595999733", child_age="13",
        calendly_booked=True, booked_datetime_iso="2026-06-25T12:00",
    )
    # typo recall is NOT force-answered by the planner (shadow) → no summary
    resp = parent_flow.handle(conv, "გასაგებია ჩემზე რა ინფრომაცია გავქს?")
    assert "თქვენზე შენახული ინფორმაციაა" not in resp
