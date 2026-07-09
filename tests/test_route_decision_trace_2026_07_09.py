import json

from app.models.conversation import Conversation
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
