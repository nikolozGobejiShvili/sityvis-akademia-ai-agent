"""P0 LIVE HOTFIX regression tests (2026-06-14).

BUG 1 — clear camp intent must skip the generic two-option menu. Diagnosis:
the live full conversation path (conversation_service.process_message →
parent_flow.handle → _maybe_static_welcome → engine) is ALREADY correct
(root cause = stale live process, not a code gap). These FULL-PATH tests
(not helper-level) lock that correct behavior for the exact live inputs.

BUG 2 — a NAMED specific event that resolves in the active data must be
answered directly (no self/child + age questions first) and must NOT carry
the future-event subscription CTA. Fixed by a deterministic named-event
branch in adult_llm_engine that bypasses the LLM for that turn.

All offline / mocked — no real OpenAI, Meta, Calendar, Sheets, Redis.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import adult_llm_engine
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, conversation_service

_MENU = "გვითხარით, რა გაინტერესებთ"


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


# =========================================================================
# BUG 1 — FULL-PATH (process_message) regression, engine ON (live config)
# =========================================================================

@pytest.fixture
def parent_engine_on(monkeypatch):
    """Pin USE_PARENT_LLM_ENGINE=True (live) and stub the OpenAI engine so
    the full path runs without a real model call. The stub returns a camp
    sentinel — if the static-welcome menu shows instead, the sentinel is
    absent and the test fails."""
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(
        "app.agent.llm.parent_llm_engine.run_parent_llm_turn",
        lambda **k: "CAMP_ENGINE_REPLY",
    )
    from app.services import messenger_service
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


_BUG1_CLEAR_CAMP = [
    "გამარჯობა საზაფხულო ბანაკი მაინტერესებს",
    "გამარჯობა, საზაფხულო ბანაკი მაინტერესებს",
    "საზაფხულო ბანაკი მაინტერესებს",
    "გამარჯობა, სიტყვის აკადემიის ბანაკით ვარ დაინტერესებული",
    "ბავშვების ბანაკი მაინტერესებს",
]


@pytest.mark.parametrize("msg", _BUG1_CLEAR_CAMP)
def test_bug1_fullpath_clear_camp_skips_menu(parent_engine_on, msg, camp_registration_open):
    """FULL PATH: clear camp intent → NO menu, camp flow continues (engine
    consulted). Goes through conversation_service.process_message, not just
    the _has_explicit_georgian_camp_intent helper."""
    conversation_service.conversations.clear()
    out = conversation_service.process_message("b1-fp", msg, "instagram")
    assert _MENU not in out, f"menu wrongly shown for: {msg!r}"
    # Camp flow continues — now via the deterministic approved intro
    # (client hotfix 2026-07-03) instead of the LLM engine reply.
    assert "ციფრულ ხმაურს" in out, f"camp flow did not continue for: {msg!r}"
    assert conversation_service.conversations["b1-fp"].segment == "PARENT"


def test_bug1_fullpath_bare_greeting_still_allows_menu(parent_engine_on):
    """A bare greeting may still show the (UNCLEAR) menu — preserved."""
    conversation_service.conversations.clear()
    out = conversation_service.process_message("b1-greet", "გამარჯობა", "instagram")
    assert _MENU in out


# =========================================================================
# BUG 2 — named specific event → direct answer, no target/age, no sub CTA
# =========================================================================

_SUB_CTA = "ახალი ზრდასრულთა ღონისძიება დაემატება"


def _adult_conv(sid):
    conv = Conversation(sender_id=sid, platform="instagram", segment="ADULT")
    conv.lead = Lead(sender_id=sid, platform="instagram", segment="ADULT")
    return conv


@pytest.fixture
def llm_spy(monkeypatch):
    """Record whether the OpenAI engine was consulted. For a resolved named
    event the deterministic branch must answer WITHOUT the LLM."""
    calls = []
    from app.services import openai_service
    monkeypatch.setattr(
        openai_service, "chat_with_tools", lambda **k: calls.append(1),
    )
    return calls


# Date-bomb cleanup (2026-06-15): the original BUG-2 active-direct-answer
# tests named the „გია მურღულია" event (14 ივნისი), which is now PAST — so
# they tested an event that silently expired. The ACTIVE direct-answer
# contract is now exercised against a SYNTHETIC active fixture (resolver
# monkeypatched to one active match) so it can never become a date-bomb.
# The Gia event keeps a DEDICATED past-event test below.
_ACTIVE_FIXTURE = {
    "title": "ქართული პოეზიის საღამო",
    "date_text": "20 ოქტომბერი 19:00",
    "location": "თბილისი",
    "price_text": "40",
    "reservation_url": "https://wordacademy.ge/tickets",
}


def _patch_one_active_event(monkeypatch, event):
    """Force the named-event resolver to see exactly one ACTIVE match,
    independent of the real (date-filtered) event list / wall clock."""
    monkeypatch.setattr(
        admin_config_service,
        "find_active_events_by_reference",
        lambda message, **k: [event],
    )


def test_bug2_named_event_direct_no_target_no_age(llm_spy, monkeypatch):
    _patch_one_active_event(monkeypatch, _ACTIVE_FIXTURE)
    conv = _adult_conv("b2-1")
    out = adult_llm_engine.run_adult_llm_turn(
        user_message="ქართული პოეზიის საღამო როდის არის",
        conversation=conv, lead=conv.lead, sender_id="b2-1", platform="instagram",
    )
    assert llm_spy == [], "LLM must NOT be consulted for a resolved active event"
    assert "ქართული პოეზიის საღამო" in out and "20 ოქტომბერი" in out  # event data
    assert "თქვენთვის თუ" not in out                   # no self/child question
    assert "რამდენი წლის" not in out                   # no age question


def test_bug2_named_event_answer_fields_and_no_subscription_cta(llm_spy, monkeypatch):
    _patch_one_active_event(monkeypatch, _ACTIVE_FIXTURE)
    conv = _adult_conv("b2-5")
    out = adult_llm_engine.run_adult_llm_turn(
        user_message="ქართული პოეზიის საღამო როდის არის",
        conversation=conv, lead=conv.lead, sender_id="b2-5", platform="instagram",
    )
    assert llm_spy == []
    # title / date / price / link present
    assert "ქართული პოეზიის საღამო" in out and "20 ოქტომბერი" in out and "40 ლარი" in out
    assert "https://" in out
    # the future-event subscription CTA must NOT appear on a direct answer
    assert _SUB_CTA not in out
    # a soft list-others follow-up is allowed
    assert "სხვა ღონისძიებებიც ჩამოგითვალოთ" in out


def test_bug2_past_named_event_gia_no_active_answer_no_invention(llm_spy):
    """Dedicated PAST-event test for „გია მურღულია" (14 ივნისი, now past).

    LIVE data path — Gia is permanently past, so the named-event branch must
    NOT give the stale active direct-answer. It must answer deterministically
    (LLM bypassed) with „already took place" (or, if an operator later removes
    the event, „not found") — never the self/child target / age question and
    never an invented price / ticket link."""
    conv = _adult_conv("b2-gia-past")
    out = adult_llm_engine.run_adult_llm_turn(
        user_message="გია მურღულიას საღამო როდის არის",
        conversation=conv, lead=conv.lead, sender_id="b2-gia-past", platform="instagram",
    )
    assert llm_spy == [], "deterministic past/not-found answer — LLM bypassed"
    assert ("უკვე გაიმართა" in out) or ("ვერ მოვძებნე" in out)  # past or not-found
    assert "მურღულია" in out or "ვერ მოვძებნე" in out           # names it / honest miss
    assert "თქვენთვის თუ" not in out                            # no target question
    assert "რამდენი წლის" not in out                            # no age question
    assert "29 ლარი" not in out                                 # no stale/invented price
    assert "https://" not in out                                # no stale/invented link


def test_bug2_unknown_named_event_defers_no_invention():
    # named event NOT in active data → Live P0/P1 Hotfix BUG B (2026-06-15):
    # the branch now answers deterministically „ვერ მოვძებნე" + active list +
    # manager-verify (NO target/age question, NO invented event data) instead
    # of deferring to the stochastic LLM.
    out = adult_llm_engine._maybe_handle_named_adult_event(
        "გალაკტიონის საღამოს ვგულისხმობ",
    )
    assert out is not None
    assert "ვერ მოვძებნე" in out          # honest not-found, no invention
    assert "მენეჯერ" in out               # manager-verify offered
    assert "თქვენთვის თუ" not in out       # no self/child target question
    # still genuinely absent from the active pool (no invented match)
    assert admin_config_service.find_active_events_by_reference(
        "გალაკტიონის საღამოს ვგულისხმობ",
    ) == []


def test_bug2_generic_event_query_defers_to_llm():
    # no specific event name → branch defers; LLM asks which / lists (existing)
    assert adult_llm_engine._maybe_handle_named_adult_event(
        "ღონისძიება მაინტერესებს",
    ) is None
    assert adult_llm_engine._maybe_handle_named_adult_event(
        "რომელი ღონისძიება გაქვთ ივლისში?",
    ) is None


def test_bug2_fix3_adult_self_revert_still_holds():
    # explicit „ჩემთვის" → reverts a prior child target to self (B4 / FIX 3)
    lead = Lead(sender_id="x", platform="instagram", segment="ADULT")
    lead.adult_target_relation = "შვილი"
    lead.adult_target_age = "14"
    adult_llm_engine._maybe_capture_adult_target("ჩემთვის მინდა", lead)
    assert (lead.adult_target_relation or "") == ""
    assert (lead.adult_target_age or "") == ""
    # mixed cue („მე მინდა შვილს") → child wins (self-revert does NOT fire)
    lead2 = Lead(sender_id="y", platform="instagram", segment="ADULT")
    adult_llm_engine._maybe_capture_adult_target("მე მინდა შვილს", lead2)
    assert (lead2.adult_target_relation or "") != ""


def test_bug2_future_updates_request_not_suppressed():
    # a future-event-updates request must NOT be intercepted by the
    # direct-answer branch (so the subscription path/LLM can still offer it)
    assert adult_llm_engine._maybe_handle_named_adult_event(
        "ახალ ღონისძიებებზე შემატყობინეთ",
    ) is None
