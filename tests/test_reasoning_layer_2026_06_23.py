"""Reasoning Layer Phase 1 — gated DETERMINISTIC intent analyzer (2026-06-23).

The analyzer (`app/reasoning/reasoning_layer.analyze_parent_turn`) returns
structured intent METADATA only — never user-facing text, never an LLM call,
never side effects, and never overrides a high-confidence deterministic handler.
Behind `settings.USE_REASONING_LAYER` (default OFF, pinned OFF in conftest).

Phase-1 live wiring is ONE ambiguous case: a decline that ALSO switches topic
(„არ მინდა, ფასი მაინტერესებს") — with the flag ON the cold-close is deferred so
the new topic reaches the engine; with the flag OFF behaviour is byte-identical.

All offline / mocked — no real OpenAI / Meta / Calendar / Sheets / email.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.reasoning import analyze_parent_turn
from app.reasoning.reasoning_layer import ReasoningAnalysis
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import messenger_service

_CTA = "ბანაკის ფასი 2150 ლარია. თუ გსურთ, კონსულტაციაზე ჩაგწერთ."
_ENGINE_REPLY = "ბანაკის ფასი 2150 ლარია. [ENGINE]"


@pytest.fixture(autouse=True)
def _reset_state():
    from app.services import conversation_service
    from app.agent.tools import parent_tool_executor
    parent_tool_executor.reset_state()
    conversation_service.conversations.clear()
    yield
    parent_tool_executor.reset_state()
    conversation_service.conversations.clear()


@pytest.fixture
def engine_only(monkeypatch):
    """Engine ON, reasoning layer OFF (baseline)."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True, USE_REASONING_LAYER=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


@pytest.fixture
def reasoning_on(monkeypatch):
    """Engine ON, reasoning layer ON."""
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True, USE_REASONING_LAYER=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


def _conv(sender_id="rl", *, child_age="12", last=_CTA):
    conv = Conversation(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender_id, platform="instagram", segment="PARENT")
    conv.lead.child_age = child_age
    conv.history.append({"role": "assistant", "content": last})
    return conv


def _mock_engine(monkeypatch, reply=_ENGINE_REPLY):
    seen = {"n": 0}
    def _eng(*a, **k):
        seen["n"] += 1
        return reply
    monkeypatch.setattr(parent_flow, "_run_llm_engine_safely", _eng)
    return seen


# =========================================================================
# FLAG OFF — behaviour unchanged
# =========================================================================
def test_off_default_flag_is_false():
    assert config_module.settings.USE_REASONING_LAYER is False


def test_off_decline_topic_switch_still_cold_closes(engine_only, monkeypatch):
    seen = _mock_engine(monkeypatch)
    conv = _conv()
    out = parent_flow.handle(conv, "არ მინდა მადლობა, ფასი მაინტერესებს")
    assert out != _ENGINE_REPLY            # NOT the engine — the decline close
    assert seen["n"] == 0                  # engine never reached (flag off)


def test_off_analyzer_not_consulted(engine_only):
    # Flag off → the gated analyzer helper returns None.
    assert parent_flow._maybe_reasoning_analysis(_conv(), "არ მინდა, ფასი") is None


def test_off_manager_self_call_still_deterministic():
    # The latest handoff fix is independent of the reasoning layer (flag off).
    from app.services import admin_config_service
    conv = _conv(child_age="7", last="თუ გსურთ, მენეჯერთან დაგაკავშირებთ.")
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "მე დავურეკავ მენჯერის ნომერი მომწერე",
    )
    phone = (admin_config_service.get_manager_phone() or "").strip()
    assert out is not None and phone in out
    assert conv.lead.name == ""


def test_off_nika_contact_still_captured():
    conv = _conv()
    conv.history.append(
        {"role": "assistant", "content": "მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი."},
    )
    parent_flow._maybe_handle_contact_collection(conv, "nika 595999733")
    assert conv.lead.name == "nika"
    assert conv.lead.phone == "595999733"


# =========================================================================
# FLAG ON — decline + topic switch reaches the topic answer
# =========================================================================
def test_on_decline_topic_switch_price_uses_deterministic_owner(reasoning_on, monkeypatch):
    seen = _mock_engine(monkeypatch)
    conv = _conv()
    out = parent_flow.handle(conv, "არ მინდა მადლობა, ფასი მაინტერესებს")
    assert "2150" in out
    assert "TBC" in out
    assert seen["n"] == 0

def test_on_plain_decline_still_closes(reasoning_on, monkeypatch):
    # A pure decline (no topic switch) must STILL cold-close — the layer only
    # defers decline+topic-switch.
    seen = _mock_engine(monkeypatch)
    conv = _conv()
    out = parent_flow.handle(conv, "არ მინდა მადლობა")
    assert out != _ENGINE_REPLY
    assert seen["n"] == 0


# =========================================================================
# FLAG ON — analyzer classification (the 6 required cases)
# =========================================================================
def test_analyzer_gratitude_plus_question():
    a = analyze_parent_turn("მადლობა, ბანაკის ფასი რა არის?")
    assert a.has_question is True
    assert a.is_affirmation is False
    assert a.topic == "price"
    assert a.intent == "ask_price"
    assert a.requested_action == "answer"


def test_analyzer_decline_plus_topic_switch():
    a = analyze_parent_turn("არ მინდა მადლობა, ფასი მაინტერესებს")
    assert a.is_decline is True
    assert a.is_topic_switch is True
    assert a.topic == "price"
    assert a.confidence >= 0.6


def test_analyzer_affirmation():
    a = analyze_parent_turn("კი მინდა")
    assert a.is_affirmation is True
    assert a.intent == "affirm"
    assert a.requested_action == "continue_existing_flow"


def test_analyzer_self_call_manager():
    a = analyze_parent_turn("მე თვითონ დავურეკავ, მენეჯერის ნომერი მომწერე")
    assert a.intent == "self_call_manager"
    assert a.requested_action == "give_manager_phone"
    assert a.topic == "manager_contact"


def test_analyzer_sunday_school():
    a = analyze_parent_turn("საკვირაო სკოლა მაინტერესებს")
    assert a.topic == "sunday_school"
    assert a.segment == "parent"


def test_analyzer_parent_to_adult_switch():
    a = analyze_parent_turn("ჩემთვის მინდა ღონისძიება")
    assert a.segment == "adult"
    assert a.topic == "adult_event"


# =========================================================================
# FLAG ON — analyzer never overrides high-confidence deterministic handlers
# =========================================================================
def test_on_manager_request_still_deterministic(reasoning_on, monkeypatch):
    seen = _mock_engine(monkeypatch)
    from app.services import admin_config_service
    phone = (admin_config_service.get_manager_phone() or "").strip()
    conv = _conv(child_age="7", last="თუ გსურთ, მენეჯერთან დაგაკავშირებთ.")
    out = parent_flow.handle(conv, "მენჯერის ნომერი მინდა")
    assert phone in out                    # deterministic disclosure, not engine
    assert seen["n"] == 0
    assert conv.lead.name == ""


def test_on_low_confidence_does_not_defer_decline():
    # A greeting is low-signal → must NOT trigger the decline deferral.
    a = analyze_parent_turn("გამარჯობა")
    assert a.confidence < 0.6
    assert parent_flow._reasoning_defers_decline(a) is False


# =========================================================================
# fail-closed / malformed / no side effects / no user text
# =========================================================================
def test_analyzer_failclosed_on_none():
    a = analyze_parent_turn(None)
    assert isinstance(a, ReasoningAnalysis)
    assert a.confidence == 0.0
    assert a.requested_action == "none"


def test_analyzer_failclosed_on_internal_error(monkeypatch):
    # Force the inner analysis to raise → analyze_parent_turn must not propagate.
    import app.reasoning.reasoning_layer as rl
    monkeypatch.setattr(rl, "_analyze", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    a = rl.analyze_parent_turn("ფასი რა არის?")
    assert isinstance(a, ReasoningAnalysis)
    assert a.confidence == 0.0


def test_helper_failclosed_when_analyzer_raises(reasoning_on, monkeypatch):
    import app.reasoning.reasoning_layer as rl
    monkeypatch.setattr(
        rl, "analyze_parent_turn",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    # _maybe_reasoning_analysis swallows the error and returns None (fail closed).
    assert parent_flow._maybe_reasoning_analysis(_conv(), "ფასი მაინტერესებს") is None


def test_analysis_is_metadata_only():
    a = analyze_parent_turn("არ მინდა მადლობა, ფასი მაინტერესებს")
    keys = set(a.to_dict().keys())
    assert keys == {
        "segment", "topic", "intent", "has_question", "is_topic_switch",
        "is_affirmation", "is_decline", "requested_action", "confidence", "reason",
    }
    # `reason` is a short INTERNAL string, not a user-facing answer.
    assert len(a.reason) < 80
    # No field carries a generated Georgian sentence / answer.
    assert "ლარი" not in a.reason


def test_analyzer_has_no_side_effects(monkeypatch):
    tripped: list[str] = []
    from app.services import (
        calendar_service, notification_service, sheets_service,
    )
    monkeypatch.setattr(messenger_service, "send_message",
                        lambda *a, **k: tripped.append("messenger"))
    monkeypatch.setattr(notification_service, "notify_manager_handoff",
                        lambda *a, **k: tripped.append("notify") or True)
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda *a, **k: tripped.append("calendar"))
    monkeypatch.setattr(sheets_service, "save_lead",
                        lambda *a, **k: tripped.append("sheets"))
    for msg in (
        "არ მინდა მადლობა, ფასი მაინტერესებს",
        "მე თვითონ დავურეკავ, მენეჯერის ნომერი მომწერე",
        "nika 595999733",
        "საკვირაო სკოლა მაინტერესებს",
    ):
        analyze_parent_turn(msg, _conv())
    assert tripped == []


# =========================================================================
# source-of-truth guard (not regressed)
# =========================================================================
def test_sot_parent_flow_zero_direct_camp_2026_reads():
    import inspect
    src = inspect.getsource(parent_flow)
    assert 'load_knowledge("camp_2026")' not in src
    assert "load_knowledge('camp_2026')" not in src
