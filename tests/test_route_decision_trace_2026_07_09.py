import dataclasses
import json

import pytest

import app.config as config_module
from app.flows import adult_flow, parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import conversation_trace
from app.services import conversation_service
from app.services.session_key_service import canonical_session_key


def _enable_trace(monkeypatch):
    monkeypatch.setattr(conversation_trace, "_enabled", lambda: True)
    conversation_trace.reset_history()
    conversation_service.conversations.clear()


def _seed_conversation(
    *,
    sender: str,
    platform: str = "messenger",
    page_id: str = "PAGE-SECRET-A",
    segment: str,
    state: str = "START",
) -> str:
    session_key = canonical_session_key(platform, page_id, sender)
    conversation_service.conversations[session_key] = Conversation(
        sender_id=sender,
        platform=platform,
        page_id=page_id,
        session_key=session_key,
        segment=segment,
        state=state,
    )
    return session_key


def _seed_parent_conversation(
    *,
    sender: str,
    state: str = "ASK_CHALLENGE",
    platform: str = "messenger",
    page_id: str = "PAGE-SECRET-A",
) -> str:
    session_key = _seed_conversation(
        sender=sender, platform=platform, page_id=page_id, segment="PARENT", state=state,
    )
    conversation = conversation_service.conversations[session_key]
    conversation.lead = Lead(
        sender_id=sender, platform=platform, segment="PARENT", child_age="12",
    )
    return session_key


def _configure_parent_engine(monkeypatch, *, enabled: bool) -> None:
    patched = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=enabled,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
    )
    monkeypatch.setattr(parent_flow, "settings", patched)
    monkeypatch.setattr(conversation_service, "settings", patched)


def _configure_adult_engine(monkeypatch, *, enabled: bool) -> None:
    patched = dataclasses.replace(
        config_module.settings,
        USE_ADULT_LLM_ENGINE=enabled,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
    )
    monkeypatch.setattr(adult_flow, "settings", patched)
    monkeypatch.setattr(conversation_service, "settings", patched)

def _process_parent_turn(monkeypatch, sender: str, message: str, *, engine: bool):
    _enable_trace(monkeypatch)
    _configure_parent_engine(monkeypatch, enabled=engine)
    _seed_parent_conversation(sender=sender)
    if engine:
        monkeypatch.setattr(
            parent_flow,
            "_run_llm_engine_safely",
            lambda *_: pytest.fail("LLM must not run for deterministic parent route"),
        )
    response = conversation_service.process_message(
        sender, message, "messenger", page_id="PAGE-SECRET-A",
    )
    _block, decision = _last_decision()
    return response, decision


ADULT_TRACE_EVENT = {
    "id": "adult_trace_event",
    "title": "Trace Adult Event",
    "status": "active",
    "date_text": "1 January 2031",
    "theme": "Trace theme",
    "guest": "Trace guest",
    "location": "Trace hall",
    "description": "Trace description",
    "reservation_url": "https://example.com/reserve",
    "min_age": 13,
}


def _process_adult_turn(
    monkeypatch,
    sender: str,
    message: str,
    *,
    events: list[dict],
    state: str = "START",
):
    _enable_trace(monkeypatch)
    _configure_adult_engine(monkeypatch, enabled=False)
    adult_flow.selected_events.clear()
    monkeypatch.setattr(
        adult_flow.admin_config_service,
        "get_active_adult_events",
        lambda: list(events),
    )
    _seed_conversation(sender=sender, segment="ADULT", state=state)
    response = conversation_service.process_message(
        sender, message, "messenger", page_id="PAGE-SECRET-A",
    )
    block, decision = _last_decision()
    return response, decision, block

MSG_PRICE_AMOUNT = "\u10d1\u10d0\u10dc\u10d0\u10d9\u10d8 \u10e0\u10d0 \u10e6\u10d8\u10e0\u10e1?"
MSG_PAYMENT_PROCESS = "\u10d2\u10d0\u10d3\u10d0\u10ee\u10d3\u10d0 \u10e0\u10dd\u10d2\u10dd\u10e0 \u10ee\u10d3\u10d4\u10d1\u10d0?"
MSG_RESERVATION_EXACT = "\u10ef\u10d0\u10d5\u10e8\u10dc\u10d8\u10e1 \u10e6\u10d8\u10e0\u10d4\u10d1\u10e3\u10da\u10d4\u10d1\u10d0 \u10e0\u10d0\u10db\u10d3\u10d4\u10dc\u10d8\u10d0?"
MSG_REGISTRATION_LINK = "\u10d1\u10d0\u10dc\u10d0\u10d9\u10d8\u10e1 \u10e0\u10d4\u10d2\u10d8\u10e1\u10e2\u10e0\u10d0\u10ea\u10d8\u10d8\u10e1 \u10da\u10d8\u10dc\u10d9\u10d8 \u10db\u10dd\u10db\u10ec\u10d4\u10e0\u10d4"
MSG_TRANSPORT = "\u10e2\u10e0\u10d0\u10dc\u10e1\u10de\u10dd\u10e0\u10e2\u10d8 \u10e0\u10dd\u10d2\u10dd\u10e0 \u10ee\u10d3\u10d4\u10d1\u10d0?"
MSG_ADULT_EVENTS = "adult events"
MSG_ADULT_IDENTITY = "\u10d5\u10d8\u10dc \u10ee\u10d0\u10e0?"


def _last_decision() -> tuple[dict, dict]:
    blocks = conversation_trace.history()
    assert len(blocks) == 1
    block = blocks[-1]
    decision = block.get("route_decision")
    assert isinstance(decision, dict)
    return block, decision


def test_route_decision_trace_is_nested_and_masks_identity(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "1234567890"
    page_id = "PAGE-SECRET-A"
    raw_key = canonical_session_key("messenger", page_id, sender)

    conversation_service.process_message(sender, "hello", "messenger", page_id=page_id)

    block, decision = _last_decision()
    assert block["session_hash"] == decision["session_hash"]
    assert decision["route_owner"] == "conversation_service"
    assert decision["domain"] == "unknown"
    assert decision["intent"] == "unclear_routing"
    assert decision["answer_source"] == "unclear_menu"
    assert decision["state_before"] == "START"
    assert decision["state_after"] == "START"
    assert decision["segment_after"] == "UNCLEAR"

    serialized = json.dumps(block, ensure_ascii=False)
    assert raw_key not in serialized
    assert page_id not in serialized
    assert sender not in serialized
    assert decision["session_key"] != raw_key
    assert decision["page_id_masked"] != page_id
    assert decision["sender_id_masked"] != sender


def test_route_decision_records_parent_top_level_route(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "PARENT-ROUTE-TRACE"
    _seed_conversation(sender=sender, segment="PARENT")

    conversation_service.process_message(
        sender, "hello", "messenger", page_id="PAGE-SECRET-A",
    )

    block, decision = _last_decision()
    assert block["route"] == "parent_flow"
    assert decision["route_owner"] == "parent_flow"
    assert decision["domain"] == "camp"
    assert decision["segment_before"] == "PARENT"
    assert decision["segment_after"] == "PARENT"


def test_route_decision_records_adult_top_level_route(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "ADULT-ROUTE-TRACE"
    _seed_conversation(sender=sender, segment="ADULT")

    conversation_service.process_message(
        sender, "hello", "messenger", page_id="PAGE-SECRET-A",
    )

    block, decision = _last_decision()
    assert block["route"] == "adult_flow"
    assert decision["route_owner"] == "adult_flow"
    assert decision["domain"] == "adult_events"
    assert decision["segment_before"] == "ADULT"
    assert decision["segment_after"] == "ADULT"


def test_route_decision_records_adult_no_active_admin_config(monkeypatch):
    sender = "ADULT-NO-ACTIVE-TRACE"
    response, decision, block = _process_adult_turn(
        monkeypatch, sender, MSG_ADULT_EVENTS, events=[],
    )

    assert response == adult_flow.admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY
    assert decision["route_owner"] == "adult_flow"
    assert decision["domain"] == "adult_events"
    assert decision["intent"] == "adult_events"
    assert decision["sub_intent"] == "no_active_events"
    assert decision["answer_source"] == "admin_config"
    assert decision["approved_copy_id"] == "adult_no_active_events"
    assert decision["used_llm"] is False
    assert decision["used_tool"] is False
    assert decision["deterministic_reason"] == "admin_config_no_active_events"

    serialized = json.dumps(block, ensure_ascii=False)
    raw_key = canonical_session_key("messenger", "PAGE-SECRET-A", sender)
    assert raw_key not in serialized
    assert "PAGE-SECRET-A" not in serialized
    assert sender not in serialized


def test_route_decision_records_adult_active_events_admin_config(monkeypatch):
    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-ACTIVE-LIST-TRACE",
        MSG_ADULT_EVENTS,
        events=[ADULT_TRACE_EVENT],
    )

    assert "Trace Adult Event" in response
    assert adult_flow.admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY not in response
    assert decision["route_owner"] == "adult_flow"
    assert decision["domain"] == "adult_events"
    assert decision["intent"] == "adult_events"
    assert decision["sub_intent"] == "active_events_list"
    assert decision["answer_source"] == "admin_config"
    assert decision["used_llm"] is False
    assert decision["used_tool"] is False
    assert decision["deterministic_reason"] == "admin_config_active_events"


def test_route_decision_records_adult_identity_deterministic_owner(monkeypatch):
    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-IDENTITY-TRACE",
        MSG_ADULT_IDENTITY,
        events=[ADULT_TRACE_EVENT],
        state="SHOW_EVENTS",
    )

    assert response
    assert "Trace Adult Event" not in response
    assert decision["route_owner"] == "adult_flow"
    assert decision["domain"] == "adult_events"
    assert decision["intent"] == "adult_global"
    assert decision["sub_intent"] == "identity"
    assert decision["answer_source"] == "deterministic_handler"
    assert decision["used_llm"] is False
    assert decision["used_tool"] is False
    assert decision["deterministic_reason"] == "adult_global_identity"

def test_route_decision_records_parent_price_amount_owner(monkeypatch):
    response, decision = _process_parent_turn(
        monkeypatch, "TRACE-PARENT-PRICE", MSG_PRICE_AMOUNT, engine=True,
    )

    assert "2150" in response
    assert decision["route_owner"] == "parent_flow"
    assert decision["domain"] == "camp"
    assert decision["intent"] == "camp_price"
    assert decision["sub_intent"] == "price_amount"
    assert decision["answer_source"] == "deterministic_handler"
    assert decision["approved_copy_id"] == "camp_price_full_block"
    assert decision["deterministic_reason"] == "camp_price_full_block_question"


def test_route_decision_records_parent_payment_process_owner(monkeypatch):
    response, decision = _process_parent_turn(
        monkeypatch, "TRACE-PARENT-PAYMENT", MSG_PAYMENT_PROCESS, engine=True,
    )

    assert "2150" not in response
    assert decision["route_owner"] == "parent_flow"
    assert decision["intent"] == "camp_price"
    assert decision["sub_intent"] == "payment_process"
    assert decision["answer_source"] == "approved_copy"
    assert decision["approved_copy_id"] == "camp_payment_process"
    assert decision["deterministic_reason"] == "camp_payment_process_question"


def test_route_decision_records_parent_reservation_exact_owner(monkeypatch):
    response, decision = _process_parent_turn(
        monkeypatch, "TRACE-PARENT-RESERVATION", MSG_RESERVATION_EXACT, engine=True,
    )

    assert "2150" not in response
    assert decision["route_owner"] == "parent_flow"
    assert decision["intent"] == "camp_price"
    assert decision["sub_intent"] == "reservation_exact_amount"
    assert decision["answer_source"] == "approved_copy"
    assert decision["approved_copy_id"] == "reservation_exact_amount_manager_deferral"
    assert decision["handoff_requested"] is True


def test_route_decision_records_parent_registration_and_transport(monkeypatch):
    _process_parent_turn(
        monkeypatch, "TRACE-PARENT-REGISTRATION", MSG_REGISTRATION_LINK, engine=True,
    )
    _block, registration_decision = _last_decision()
    assert registration_decision["route_owner"] == "parent_flow"
    assert registration_decision["intent"] == "camp_registration"
    assert registration_decision["sub_intent"] == "registration_link"
    assert registration_decision["answer_source"] == "admin_config"

    response, transport_decision = _process_parent_turn(
        monkeypatch, "TRACE-PARENT-TRANSPORT", MSG_TRANSPORT, engine=True,
    )
    assert "2150" not in response
    assert transport_decision["route_owner"] == "parent_flow"
    assert transport_decision["intent"] == "camp_logistics"
    assert transport_decision["sub_intent"] == "transport"
    assert transport_decision["answer_source"] == "deterministic_handler"


def test_route_decision_records_router_price_delegate(monkeypatch):
    response, decision = _process_parent_turn(
        monkeypatch, "TRACE-ROUTER-PAYMENT", MSG_PAYMENT_PROCESS, engine=False,
    )

    assert "2150" not in response
    assert decision["route_owner"] == "parent_turn_router"
    assert decision["domain"] == "camp"
    assert decision["intent"] == "camp_price"
    assert decision["sub_intent"] == "payment_process"
    assert decision["answer_source"] == "router_delegate"
    assert decision["approved_copy_id"] == "camp_payment_process"
    assert decision["deterministic_reason"] == "router_canonical_price_delegate"
