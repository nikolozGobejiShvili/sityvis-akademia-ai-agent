import dataclasses
import json

import pytest

import app.config as config_module
from app.agent.llm import adult_llm_engine, parent_llm_engine
from app.agent.tools import adult_tool_executor, parent_tool_executor
from app.flows import adult_flow, parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import conversation_trace
from app.services import (
    admin_config_service,
    conversation_service,
    notification_service,
    sheets_service,
)
from app.services.session_key_service import canonical_session_key


def _enable_trace(monkeypatch):
    monkeypatch.setattr(conversation_trace, "_enabled", lambda: True)
    monkeypatch.setattr(
        admin_config_service,
        "get_camp_registration_status",
        lambda: "open",
    )
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

def _mk_llm_response(content: str = "", tool_calls: list[dict] | None = None):
    return {
        "choices": [
            {
                "message": {
                    "content": content or None,
                    "tool_calls": tool_calls,
                },
            },
        ],
    }


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }


def _begin_trace_for_conversation(conversation: Conversation, message: str) -> None:
    conversation_trace.begin(
        conversation.sender_id,
        message,
        conversation.platform,
        page_id=conversation.page_id or "",
        session_key=conversation.session_key or "",
    )

MSG_PRICE_AMOUNT = "\u10d1\u10d0\u10dc\u10d0\u10d9\u10d8 \u10e0\u10d0 \u10e6\u10d8\u10e0\u10e1?"
MSG_PAYMENT_PROCESS = "\u10d2\u10d0\u10d3\u10d0\u10ee\u10d3\u10d0 \u10e0\u10dd\u10d2\u10dd\u10e0 \u10ee\u10d3\u10d4\u10d1\u10d0?"
MSG_RESERVATION_EXACT = "\u10ef\u10d0\u10d5\u10e8\u10dc\u10d8\u10e1 \u10e6\u10d8\u10e0\u10d4\u10d1\u10e3\u10da\u10d4\u10d1\u10d0 \u10e0\u10d0\u10db\u10d3\u10d4\u10dc\u10d8\u10d0?"
MSG_REGISTRATION_LINK = "\u10d1\u10d0\u10dc\u10d0\u10d9\u10d8\u10e1 \u10e0\u10d4\u10d2\u10d8\u10e1\u10e2\u10e0\u10d0\u10ea\u10d8\u10d8\u10e1 \u10da\u10d8\u10dc\u10d9\u10d8 \u10db\u10dd\u10db\u10ec\u10d4\u10e0\u10d4"
MSG_TRANSPORT = "\u10e2\u10e0\u10d0\u10dc\u10e1\u10de\u10dd\u10e0\u10e2\u10d8 \u10e0\u10dd\u10d2\u10dd\u10e0 \u10ee\u10d3\u10d4\u10d1\u10d0?"
MSG_ADULT_EVENTS = "adult events"
MSG_ADULT_IDENTITY = "\u10d5\u10d8\u10dc \u10ee\u10d0\u10e0?"
MSG_ADULT_GREETING = "hello"
MSG_ADULT_MANAGER = "\u10db\u10d4\u10dc\u10d4\u10ef\u10d4\u10e0\u10d8"


def _assert_single_route_decision(block: dict) -> None:
    decision_keys = [key for key in block if "route_decision" in key]
    assert decision_keys == ["route_decision"]
    assert "route_owner" not in block
    assert "answer_source" not in block
    decision = block.get("route_decision")
    assert isinstance(decision, dict)
    assert "route_decision" not in decision


def _assert_decision_private(
    decision: dict, forbidden_fragments: list[str | None],
) -> None:
    serialized = json.dumps(decision, ensure_ascii=False)
    for fragment in forbidden_fragments:
        if fragment:
            assert fragment not in serialized


def _assert_no_fallback_reason(decision: dict) -> None:
    assert "fallback_reason" not in decision


def _assert_deterministic_no_llm_tool(
    decision: dict, *, handoff_requested: bool = False,
) -> None:
    assert decision["used_llm"] is False
    assert decision["used_tool"] is False
    assert decision.get("handoff_requested", False) is handoff_requested
    _assert_no_fallback_reason(decision)


def _assert_llm_no_tool(decision: dict) -> None:
    assert decision["used_llm"] is True
    assert decision["used_tool"] is False


def _last_decision() -> tuple[dict, dict]:
    blocks = conversation_trace.history()
    assert len(blocks) == 1
    block = blocks[-1]
    _assert_single_route_decision(block)
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

def test_route_decision_records_parent_llm_direct_answer(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "PARENT-LLM-DIRECT-TRACE"
    session_key = _seed_parent_conversation(sender=sender)
    conversation = conversation_service.conversations[session_key]
    lead = conversation.lead
    monkeypatch.setattr(
        parent_llm_engine.openai_service,
        "chat_with_tools",
        lambda **kwargs: _mk_llm_response(content="PARENT_LLM_DIRECT"),
    )

    _begin_trace_for_conversation(conversation, "parent llm direct")
    response = parent_llm_engine.run_parent_llm_turn(
        user_message="parent llm direct",
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )
    conversation_trace.emit()

    block, decision = _last_decision()
    assert response == "PARENT_LLM_DIRECT"
    assert decision["route_owner"] == "parent_llm_engine"
    assert decision["domain"] == "camp"
    assert decision["intent"] == "parent_llm_response"
    assert decision["answer_source"] == "llm_direct"
    assert decision["used_llm"] is True
    assert decision["used_tool"] is False
    serialized = json.dumps(block, ensure_ascii=False)
    assert session_key not in serialized
    assert "PAGE-SECRET-A" not in serialized
    assert sender not in serialized


def test_route_decision_records_parent_llm_empty_fallback(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "PARENT-LLM-EMPTY-TRACE"
    session_key = _seed_parent_conversation(sender=sender)
    conversation = conversation_service.conversations[session_key]
    lead = conversation.lead
    monkeypatch.setattr(
        parent_llm_engine.openai_service,
        "chat_with_tools",
        lambda **kwargs: _mk_llm_response(content=""),
    )

    _begin_trace_for_conversation(conversation, "parent llm empty")
    response = parent_llm_engine.run_parent_llm_turn(
        user_message="parent llm empty",
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )
    conversation_trace.emit()

    _block, decision = _last_decision()
    assert response == ""
    assert decision["domain"] == "camp"
    assert decision["answer_source"] == "fallback"
    assert decision["used_llm"] is True
    assert decision["used_tool"] is False
    assert decision["fallback_reason"] == "llm_empty_final"


def test_route_decision_records_adult_llm_direct_answer(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "ADULT-LLM-DIRECT-TRACE"
    session_key = _seed_conversation(sender=sender, segment="ADULT")
    conversation = conversation_service.conversations[session_key]
    lead = Lead(sender_id=sender, platform="messenger", segment="ADULT")
    conversation.lead = lead
    monkeypatch.setattr(
        adult_llm_engine.openai_service,
        "chat_with_tools",
        lambda **kwargs: _mk_llm_response(content="ADULT_LLM_DIRECT"),
    )

    _begin_trace_for_conversation(conversation, "hello")
    response = adult_llm_engine.run_adult_llm_turn(
        user_message="hello",
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )
    conversation_trace.emit()

    _block, decision = _last_decision()
    assert response == "ADULT_LLM_DIRECT"
    assert decision["route_owner"] == "adult_llm_engine"
    assert decision["domain"] == "adult_events"
    assert decision["intent"] == "adult_llm_response"
    assert decision["answer_source"] == "llm_direct"
    assert decision["used_llm"] is True
    assert decision["used_tool"] is False


def test_route_decision_records_adult_llm_empty_fallback(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "ADULT-LLM-EMPTY-TRACE"
    session_key = _seed_conversation(sender=sender, segment="ADULT")
    conversation = conversation_service.conversations[session_key]
    lead = Lead(sender_id=sender, platform="messenger", segment="ADULT")
    conversation.lead = lead
    monkeypatch.setattr(
        adult_llm_engine.openai_service,
        "chat_with_tools",
        lambda **kwargs: _mk_llm_response(content=""),
    )

    _begin_trace_for_conversation(conversation, "hello")
    response = adult_llm_engine.run_adult_llm_turn(
        user_message="hello",
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )
    conversation_trace.emit()

    _block, decision = _last_decision()
    assert response == ""
    assert decision["domain"] == "adult_events"
    assert decision["answer_source"] == "fallback"
    assert decision["used_llm"] is True
    assert decision["used_tool"] is False
    assert decision["fallback_reason"] == "llm_empty_final"


def test_route_decision_records_adult_selected_event_detail_llm(monkeypatch):
    monkeypatch.setattr(
        adult_flow.openai_service,
        "generate_response",
        lambda **kwargs: "ADULT_EVENT_DETAIL_LLM",
    )

    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-SELECTED-DETAIL-TRACE",
        "1",
        events=[ADULT_TRACE_EVENT],
        state="SHOW_EVENTS",
    )

    assert "ADULT_EVENT_DETAIL_LLM" in response
    assert decision["route_owner"] == "adult_flow"
    assert decision["domain"] == "adult_events"
    assert decision["intent"] == "adult_events"
    assert decision["sub_intent"] == "selected_event_detail"
    assert decision["answer_source"] == "llm_direct"
    assert decision["used_llm"] is True
    assert decision["used_tool"] is False

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


def test_route_decision_records_parent_tool_executor_result(monkeypatch):
    _enable_trace(monkeypatch)
    parent_tool_executor.reset_state()
    sender = "PARENT-TOOL-TRACE"
    session_key = _seed_parent_conversation(sender=sender)
    conversation = conversation_service.conversations[session_key]
    lead = conversation.lead
    executor = parent_tool_executor.ParentToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )

    _begin_trace_for_conversation(conversation, "parent harmless tool trace")
    result = executor.execute(
        parent_tool_executor.TOOL_GET_CAMP_INFO,
        {"topic": "dates"},
    )
    conversation_trace.emit()

    block, decision = _last_decision()
    assert result["success"] is True
    assert decision["route_owner"] == "parent_tool_executor"
    assert decision["domain"] == "camp"
    assert decision["sub_intent"] == parent_tool_executor.TOOL_GET_CAMP_INFO
    assert decision["answer_source"] == "tool_result"
    assert decision["used_tool"] is True
    assert decision["handoff_requested"] is False
    serialized = json.dumps(block, ensure_ascii=False)
    assert "dates" not in serialized


def test_route_decision_records_parent_tool_handoff(monkeypatch):
    _enable_trace(monkeypatch)
    parent_tool_executor.reset_state()
    sender = "PARENT-TOOL-HANDOFF-TRACE"
    session_key = _seed_parent_conversation(sender=sender)
    conversation = conversation_service.conversations[session_key]
    lead = conversation.lead
    executor = parent_tool_executor.ParentToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )

    _begin_trace_for_conversation(conversation, "parent handoff tool trace")
    result = executor.execute(
        parent_tool_executor.TOOL_MANAGE_CONSULTATION_BOOKING,
        {"action": "cancel"},
    )
    conversation_trace.emit()

    _block, decision = _last_decision()
    assert result["manager_handoff_required"] is True
    assert decision["route_owner"] == "parent_tool_executor"
    assert decision["sub_intent"] == parent_tool_executor.TOOL_MANAGE_CONSULTATION_BOOKING
    assert decision["answer_source"] == "tool_result"
    assert decision["used_tool"] is True
    assert decision["handoff_requested"] is True


def test_route_decision_records_adult_tool_executor_result(monkeypatch):
    _enable_trace(monkeypatch)
    adult_tool_executor.reset_state()
    monkeypatch.setattr(
        admin_config_service,
        "get_active_adult_events",
        lambda user_age=None: [],
    )
    sender = "ADULT-TOOL-TRACE"
    session_key = _seed_conversation(sender=sender, segment="ADULT")
    conversation = conversation_service.conversations[session_key]
    lead = Lead(sender_id=sender, platform="messenger", segment="ADULT")
    conversation.lead = lead
    executor = adult_tool_executor.AdultToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )

    _begin_trace_for_conversation(conversation, "adult harmless tool trace")
    result = executor.execute(adult_tool_executor.TOOL_GET_ADULT_EVENTS, {})
    conversation_trace.emit()

    _block, decision = _last_decision()
    assert result["success"] is True
    assert decision["route_owner"] == "adult_tool_executor"
    assert decision["domain"] == "adult_events"
    assert decision["sub_intent"] == adult_tool_executor.TOOL_GET_ADULT_EVENTS
    assert decision["answer_source"] == "tool_result"
    assert decision["used_tool"] is True
    assert decision["handoff_requested"] is False


def test_route_decision_records_adult_tool_handoff_without_payload_leak(monkeypatch):
    _enable_trace(monkeypatch)
    adult_tool_executor.reset_state()
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "558 67 47 33")
    monkeypatch.setattr(sheets_service, "create_lead", lambda lead: None)
    monkeypatch.setattr(
        notification_service,
        "send_manager_notification",
        lambda lead, summary: None,
    )
    sender = "ADULT-TOOL-HANDOFF-TRACE"
    session_key = _seed_conversation(sender=sender, segment="ADULT")
    conversation = conversation_service.conversations[session_key]
    lead = Lead(sender_id=sender, platform="messenger", segment="ADULT")
    conversation.lead = lead
    executor = adult_tool_executor.AdultToolExecutor(
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )

    _begin_trace_for_conversation(conversation, "adult handoff tool trace")
    result = executor.execute(
        adult_tool_executor.TOOL_REQUEST_ADULT_MANAGER_CALLBACK,
        {
            "name": "Trace Adult Tool",
            "phone": "599123456",
            "event_interest": "Trace Event Payload",
        },
    )
    conversation_trace.emit()

    block, decision = _last_decision()
    assert result["success"] is True
    assert result["manager_notified"] is True
    assert decision["route_owner"] == "adult_tool_executor"
    assert decision["sub_intent"] == adult_tool_executor.TOOL_REQUEST_ADULT_MANAGER_CALLBACK
    assert decision["answer_source"] == "tool_result"
    assert decision["used_tool"] is True
    assert decision["handoff_requested"] is True
    serialized = json.dumps(block, ensure_ascii=False)
    assert "599123456" not in serialized
    assert "Trace Adult Tool" not in serialized
    assert "Trace Event Payload" not in serialized
    assert "558 67 47 33" not in serialized


def test_route_decision_parent_llm_tool_loop_preserves_tool_marker(monkeypatch):
    _enable_trace(monkeypatch)
    parent_tool_executor.reset_state()
    sender = "PARENT-LLM-TOOL-TRACE"
    session_key = _seed_parent_conversation(sender=sender)
    conversation = conversation_service.conversations[session_key]
    lead = conversation.lead
    responses = iter([
        _mk_llm_response(
            tool_calls=[
                _tool_call(
                    "call_parent_info",
                    parent_tool_executor.TOOL_GET_CAMP_INFO,
                    {"topic": "dates"},
                ),
            ],
        ),
        _mk_llm_response(content="PARENT_TOOL_LOOP_FINAL"),
    ])
    monkeypatch.setattr(
        parent_llm_engine.openai_service,
        "chat_with_tools",
        lambda **kwargs: next(responses),
    )

    _begin_trace_for_conversation(conversation, "parent llm tool loop")
    response = parent_llm_engine.run_parent_llm_turn(
        user_message="parent llm tool loop",
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )
    conversation_trace.emit()

    block, decision = _last_decision()
    assert response == "PARENT_TOOL_LOOP_FINAL"
    assert decision["route_owner"] == "parent_llm_engine"
    assert decision["domain"] == "camp"
    assert decision["answer_source"] == "llm_tool_loop"
    assert decision["used_llm"] is True
    assert decision["used_tool"] is True
    serialized = json.dumps(block, ensure_ascii=False)
    assert "dates" not in serialized


def test_route_decision_adult_llm_tool_loop_preserves_tool_marker(monkeypatch):
    _enable_trace(monkeypatch)
    adult_tool_executor.reset_state()
    monkeypatch.setattr(
        admin_config_service,
        "get_active_adult_events",
        lambda user_age=None: [],
    )
    sender = "ADULT-LLM-TOOL-TRACE"
    session_key = _seed_conversation(sender=sender, segment="ADULT")
    conversation = conversation_service.conversations[session_key]
    lead = Lead(sender_id=sender, platform="messenger", segment="ADULT")
    conversation.lead = lead
    responses = iter([
        _mk_llm_response(
            tool_calls=[
                _tool_call(
                    "call_adult_events",
                    adult_tool_executor.TOOL_GET_ADULT_EVENTS,
                    {},
                ),
            ],
        ),
        _mk_llm_response(content="ADULT_TOOL_LOOP_FINAL"),
    ])
    monkeypatch.setattr(
        adult_llm_engine.openai_service,
        "chat_with_tools",
        lambda **kwargs: next(responses),
    )

    _begin_trace_for_conversation(conversation, "adult llm tool loop")
    response = adult_llm_engine.run_adult_llm_turn(
        user_message="adult llm tool loop",
        conversation=conversation,
        lead=lead,
        sender_id=sender,
        platform="messenger",
    )
    conversation_trace.emit()

    _block, decision = _last_decision()
    assert response == "ADULT_TOOL_LOOP_FINAL"
    assert decision["route_owner"] == "adult_llm_engine"
    assert decision["domain"] == "adult_events"
    assert decision["answer_source"] == "llm_tool_loop"
    assert decision["used_llm"] is True
    assert decision["used_tool"] is True


@pytest.mark.parametrize(
    (
        "message",
        "expected_intent",
        "expected_sub_intent",
        "expected_source",
        "contains_price",
        "handoff_requested",
    ),
    [
        (
            MSG_PRICE_AMOUNT,
            "camp_price",
            "price_amount",
            "deterministic_handler",
            True,
            False,
        ),
        (
            MSG_PAYMENT_PROCESS,
            "camp_price",
            "payment_process",
            "approved_copy",
            False,
            False,
        ),
        (
            MSG_RESERVATION_EXACT,
            "camp_price",
            "reservation_exact_amount",
            "approved_copy",
            False,
            True,
        ),
        (
            MSG_REGISTRATION_LINK,
            "camp_registration",
            "registration_link",
            "admin_config",
            False,
            False,
        ),
        (
            MSG_TRANSPORT,
            "camp_logistics",
            "transport",
            "deterministic_handler",
            False,
            False,
        ),
    ],
)
def test_route_decision_parent_deterministic_invariants(
    monkeypatch,
    message,
    expected_intent,
    expected_sub_intent,
    expected_source,
    contains_price,
    handoff_requested,
):
    response, decision = _process_parent_turn(
        monkeypatch,
        f"TRACE-PARENT-C-{expected_sub_intent}",
        message,
        engine=True,
    )

    assert ("2150" in response) is contains_price
    assert decision["route_owner"] == "parent_flow"
    assert decision["domain"] == "camp"
    assert decision["intent"] == expected_intent
    assert decision["sub_intent"] == expected_sub_intent
    assert decision["answer_source"] == expected_source
    _assert_deterministic_no_llm_tool(
        decision, handoff_requested=handoff_requested,
    )


def test_route_decision_adult_deterministic_invariants(monkeypatch):
    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-C-NO-ACTIVE",
        MSG_ADULT_EVENTS,
        events=[],
    )
    assert response == adult_flow.admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY
    assert decision["route_owner"] == "adult_flow"
    assert decision["domain"] == "adult_events"
    assert decision["sub_intent"] == "no_active_events"
    assert decision["answer_source"] == "admin_config"
    _assert_deterministic_no_llm_tool(decision)

    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-C-ACTIVE",
        MSG_ADULT_EVENTS,
        events=[ADULT_TRACE_EVENT],
    )
    assert "Trace Adult Event" in response
    assert decision["route_owner"] == "adult_flow"
    assert decision["domain"] == "adult_events"
    assert decision["sub_intent"] == "active_events_list"
    assert decision["answer_source"] == "admin_config"
    _assert_deterministic_no_llm_tool(decision)

    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-C-IDENTITY",
        MSG_ADULT_IDENTITY,
        events=[ADULT_TRACE_EVENT],
        state="SHOW_EVENTS",
    )
    assert response
    assert decision["route_owner"] == "adult_flow"
    assert decision["intent"] == "adult_global"
    assert decision["sub_intent"] == "identity"
    assert decision["answer_source"] == "deterministic_handler"
    _assert_deterministic_no_llm_tool(decision)

    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-C-GREETING",
        MSG_ADULT_GREETING,
        events=[ADULT_TRACE_EVENT],
        state="SHOW_EVENTS",
    )
    assert response
    assert decision["route_owner"] == "adult_flow"
    assert decision["intent"] == "adult_global"
    assert decision["sub_intent"] == "greeting"
    assert decision["answer_source"] == "deterministic_handler"
    _assert_deterministic_no_llm_tool(decision)

    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "ADULT-C-MANAGER",
        MSG_ADULT_MANAGER,
        events=[ADULT_TRACE_EVENT],
        state="SHOW_EVENTS",
    )
    assert response
    assert decision["route_owner"] == "adult_flow"
    assert decision["intent"] == "adult_global"
    assert decision["sub_intent"] == "manager_request"
    assert decision["answer_source"] == "deterministic_handler"
    _assert_deterministic_no_llm_tool(decision, handoff_requested=True)


@pytest.mark.parametrize(
    (
        "message",
        "expected_sub_intent",
        "expected_copy_id",
        "contains_price",
        "handoff_requested",
    ),
    [
        (
            MSG_PRICE_AMOUNT,
            "price_amount",
            "camp_price_full_block",
            True,
            False,
        ),
        (
            MSG_PAYMENT_PROCESS,
            "payment_process",
            "camp_payment_process",
            False,
            False,
        ),
        (
            MSG_RESERVATION_EXACT,
            "reservation_exact_amount",
            "reservation_exact_amount_manager_deferral",
            False,
            True,
        ),
    ],
)
def test_route_decision_router_delegate_split_directly(
    monkeypatch,
    message,
    expected_sub_intent,
    expected_copy_id,
    contains_price,
    handoff_requested,
):
    _enable_trace(monkeypatch)
    sender = f"ROUTER-C-{expected_sub_intent}"
    session_key = _seed_parent_conversation(sender=sender)
    conversation = conversation_service.conversations[session_key]

    _begin_trace_for_conversation(conversation, message)
    response = parent_turn_router._build_premium_price_answer(conversation, message)
    conversation_trace.emit()

    assert response
    assert ("2150" in response) is contains_price
    _block, decision = _last_decision()
    assert decision["route_owner"] == "parent_turn_router"
    assert decision["domain"] == "camp"
    assert decision["intent"] == "camp_price"
    assert decision["sub_intent"] == expected_sub_intent
    assert decision["answer_source"] == "router_delegate"
    assert decision["approved_copy_id"] == expected_copy_id
    _assert_deterministic_no_llm_tool(
        decision, handoff_requested=handoff_requested,
    )


def test_route_decision_merge_safety_preserves_fields_and_privacy(monkeypatch):
    _enable_trace(monkeypatch)
    sender = "RAW-SENDER-C-123456"
    page_id = "PAGE-SECRET-C"
    session_key = canonical_session_key("messenger", page_id, sender)

    conversation_trace.begin(
        sender,
        "OPENAI_API_KEY=sk-test-route-secret PASSWORD=route-secret",
        "messenger",
        page_id=page_id,
        session_key=session_key,
    )
    conversation_trace.set_route_decision(
        route_owner="parent_tool_executor",
        domain="camp",
        sub_intent="request_manager_callback",
        answer_source="tool_result",
        used_tool=True,
        handoff_requested=True,
    )
    conversation_trace.set_route_decision(
        answer_source="llm_tool_loop",
        used_llm=True,
    )
    conversation_trace.set_route_decision(
        fallback_reason="llm_empty_final",
    )
    conversation_trace.set_route_decision(
        unknown_payload={
            "name": "Trace Secret Name",
            "phone": "599123456",
            "token": "sk-test-route-secret",
        },
        route_owner=None,
        used_tool=None,
    )
    conversation_trace.emit()

    _block, decision = _last_decision()
    assert decision["route_owner"] == "parent_tool_executor"
    assert decision["answer_source"] == "llm_tool_loop"
    assert decision["used_tool"] is True
    assert decision["used_llm"] is True
    assert decision["handoff_requested"] is True
    assert decision["fallback_reason"] == "llm_empty_final"
    _assert_decision_private(
        decision,
        [
            sender,
            page_id,
            session_key,
            "Trace Secret Name",
            "599123456",
            "sk-test-route-secret",
            "OPENAI_API_KEY",
            "PASSWORD=route-secret",
        ],
    )


def test_route_decision_non_fallback_paths_do_not_record_fallback_reason(monkeypatch):
    response, decision = _process_parent_turn(
        monkeypatch, "TRACE-C-NON-FALLBACK-PARENT", MSG_PRICE_AMOUNT, engine=True,
    )
    assert "2150" in response
    _assert_no_fallback_reason(decision)

    response, decision, _block = _process_adult_turn(
        monkeypatch,
        "TRACE-C-NON-FALLBACK-ADULT",
        MSG_ADULT_EVENTS,
        events=[ADULT_TRACE_EVENT],
    )
    assert "Trace Adult Event" in response
    _assert_no_fallback_reason(decision)