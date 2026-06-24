"""Adult-route generic-discovery vs named-event lookup fix (2026-06-24).

Live residual after the planner-first stabilization patch: a GENERIC adult-events
question routed correctly to adult_flow but the adult route's deterministic
named-event interceptor could still answer „ამ სახელით ღონისძიება ვერ მოვძებნე"
before listing active events. Generic discovery is NOT a named-event lookup.

These tests exercise the REAL `run_adult_llm_turn` path (only the OpenAI call is
mocked, so the deterministic named-event interceptor runs) with the planner
authoritative. The planner flags generic discovery (`F_NO_NAMED_EVENT_LOOKUP`)
and the adult route now respects it; a genuine named reference
(`adult_event_named`) keeps the interceptor allowed.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import adult_llm_engine, parent_llm_engine
from app.flows import adult_flow, parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import conversation_planner as cp
from app.services import (
    admin_config_service, conversation_service, openai_service,
)

_FLAGS = dict(
    USE_CONVERSATION_PLANNER=True,
    CONVERSATION_PLANNER_AUTHORITATIVE=True,
    USE_PARENT_LLM_ENGINE=True,
    USE_ADULT_LLM_ENGINE=True,
)
_LLM_CANNED = "ზრდასრულთა აქტიური ღონისძიებების სია გიჩვენებთ."


class _FakeMsg:
    def __init__(self, content):
        self.content = content
        self.tool_calls = None


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMsg(content)


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


@pytest.fixture
def live_adult(monkeypatch):
    for mod in (
        conversation_service, parent_flow, adult_flow,
        parent_llm_engine, adult_llm_engine, config_module,
    ):
        monkeypatch.setattr(mod, "settings", dataclasses.replace(mod.settings, **_FLAGS))
    # Run the REAL run_adult_llm_turn (and its deterministic interceptor); mock
    # only the OpenAI call so a non-skipped interceptor is observable.
    monkeypatch.setattr(
        openai_service, "chat_with_tools", lambda **k: _FakeResp(_LLM_CANNED),
    )
    conversation_service.conversations.clear()
    parent_flow._sunday_school_notified_senders.clear()
    yield


def _conv(sender, segment="ADULT", **lk):
    lead = Lead(sender_id=sender, platform="messenger", segment=segment)
    for k, v in lk.items():
        setattr(lead, k, v)
    conv = Conversation(
        sender_id=sender, platform="messenger", segment=segment, state="IN_PROGRESS",
        lead=lead, history=[{"role": "assistant", "content": "ზრდასრულთა ღონისძიებები"}],
    )
    conversation_service.conversations[sender] = conv
    return conv


def _send(sender, text):
    return conversation_service.process_message(sender, text, "messenger")


# ── 1 + 2: generic discovery must NOT say „ვერ მოვძებნე" ──────────────────────

@pytest.mark.parametrize("msg", [
    "ამ ეტაპზე რა ღონისძიებები გაქვთ?",
    "ზრდასრულთა ღონისძიებებს ვგულისხმობ",
    "რა ღონისძიებები გაქვთ?",
])
def test_generic_discovery_no_named_event_not_found(live_adult, msg):
    conv = _conv(f"gd_{abs(hash(msg))%9999}")
    resp = _send(conv.sender_id, msg)
    assert "ვერ მოვძებნე" not in resp
    assert conv.segment == "ADULT"                       # routed to adult flow
    # the planner flagged generic discovery, so the interceptor was skipped and
    # the (mocked) LLM answered
    assert resp == _LLM_CANNED


def test_generic_discovery_planner_forbids_named_lookup():
    """Planner-level: generic discovery sets F_NO_NAMED_EVENT_LOOKUP; the adult
    gate then returns True (skip the interceptor)."""
    conv = _conv("gd_unit")
    conv._turn_plan = cp.plan_turn("ამ ეტაპზე რა ღონისძიებები გაქვთ?", conv)
    assert conv._turn_plan.user_current_intent == "adult_event_discovery"
    assert cp.F_NO_NAMED_EVENT_LOOKUP in conv._turn_plan.forbidden_response_patterns
    swapped = dataclasses.replace(adult_llm_engine.settings, **_FLAGS)
    orig = adult_llm_engine.settings
    try:
        adult_llm_engine.settings = swapped
        assert adult_llm_engine._planner_forbids_named_event_lookup(conv) is True
    finally:
        adult_llm_engine.settings = orig


# ── 3: a genuine named-event lookup STILL works ───────────────────────────────

def test_named_event_lookup_still_works(live_adult, monkeypatch):
    """A turn that NAMES a specific event is classified adult_event_named (the
    interceptor is NOT skipped) and resolves to a direct answer."""
    fake_event = {
        "title": "ფესტივალი გალაკი", "date_text": "20 ივლისი 19:00",
        "location": "თბილისი", "price_text": "50", "reservation_url": "https://x/y",
    }
    monkeypatch.setattr(
        admin_config_service, "find_active_events_by_reference",
        lambda msg: [fake_event],
    )
    conv = _conv("named_1")
    msg = "ფესტივალი გალაკი ღონისძიება მაინტერესებს"
    # planner classifies a genuine named reference and does NOT forbid the lookup
    plan = cp.plan_turn(msg, conv)
    assert plan.user_current_intent == "adult_event_named"
    assert cp.F_NO_NAMED_EVENT_LOOKUP not in plan.forbidden_response_patterns
    resp = _send("named_1", msg)
    assert "ფესტივალი გალაკი" in resp                         # direct named answer
    assert "ვერ მოვძებნე" not in resp


def test_named_lookup_not_skipped_when_planner_allows():
    """The adult gate returns False (interceptor allowed) for a named reference."""
    conv = _conv("named_unit")
    conv._turn_plan = cp.plan_turn("ფესტივალი გალაკი ღონისძიება მაინტერესებს", conv)
    assert conv._turn_plan.user_current_intent == "adult_event_named"
    swapped = dataclasses.replace(adult_llm_engine.settings, **_FLAGS)
    orig = adult_llm_engine.settings
    try:
        adult_llm_engine.settings = swapped
        assert adult_llm_engine._planner_forbids_named_event_lookup(conv) is False
    finally:
        adult_llm_engine.settings = orig


# ── 5: flag-off regression — interceptor unaffected when planner off ──────────

def test_interceptor_runs_when_planner_off():
    """With the planner off the gate is False (legacy interceptor behaviour)."""
    conv = _conv("off_1")
    conv._turn_plan = None
    assert adult_llm_engine._planner_forbids_named_event_lookup(conv) is False
