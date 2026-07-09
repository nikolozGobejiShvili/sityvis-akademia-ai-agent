from __future__ import annotations

import json

from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.flows import adult_flow, parent_flow, parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import conversation_trace
from app.services import conversation_service, redis_state_service
from app.services.session_key_service import canonical_session_key, conversation_cache_key


def _conversation(sender: str = "S", platform: str = "messenger", page_id: str = "PAGE-A") -> Conversation:
    session_key = canonical_session_key(platform, page_id, sender)
    lead = Lead(sender_id=sender, platform=platform, segment="PARENT")
    return Conversation(
        sender_id=sender,
        platform=platform,
        page_id=page_id,
        session_key=session_key,
        segment="PARENT",
        lead=lead,
    )


def _adult_conversation(sender: str = "S", platform: str = "messenger", page_id: str = "PAGE-A") -> Conversation:
    conv = _conversation(sender=sender, platform=platform, page_id=page_id)
    conv.segment = "ADULT"
    conv.lead.segment = "ADULT"
    return conv


def _event(event_id: str, name: str) -> dict[str, str]:
    return {
        "id": event_id,
        "name": name,
        "date": "date",
        "time": "",
        "theme": name,
        "guest": "",
        "location": "",
        "price": "",
        "booking_link": "",
        "description": "",
        "atmosphere": "",
    }


def test_adult_selected_events_are_page_and_platform_scoped(monkeypatch):
    events = [_event("A", "Event A"), _event("B", "Event B")]
    monkeypatch.setattr(adult_flow, "_load_events", lambda: list(events))
    adult_flow.selected_events.clear()

    same_page_a = _adult_conversation(sender="SAME", platform="messenger", page_id="PAGE-A")
    same_page_b = _adult_conversation(sender="SAME", platform="messenger", page_id="PAGE-B")
    instagram = _adult_conversation(sender="SAME", platform="instagram", page_id="IG-PAGE")

    adult_flow.selected_events[conversation_cache_key(same_page_a)] = events[1]

    assert adult_flow._current_event(same_page_b)["id"] == "A"
    assert adult_flow._current_event(instagram)["id"] == "A"
    assert adult_flow.selected_events[conversation_cache_key(same_page_a)]["id"] == "B"
    assert set(adult_flow.selected_events) == {
        "facebook:PAGE-A:SAME",
        "facebook:PAGE-B:SAME",
        "instagram:IG-PAGE:SAME",
    }


def test_parent_slot_and_retry_caches_use_canonical_keys():
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()

    conv_a = _conversation(sender="SAME", page_id="PAGE-A")
    conv_b = _conversation(sender="SAME", page_id="PAGE-B")
    key_a = conversation_cache_key(conv_a)
    key_b = conversation_cache_key(conv_b)

    parent_flow.available_slots[key_a] = [{"date": "A", "time": "10:00", "datetime_iso": "A"}]
    parent_flow.available_slots[key_b] = [{"date": "B", "time": "11:00", "datetime_iso": "B"}]
    parent_flow.ask_name_retries[key_a] = True
    parent_flow.invalid_phone_retries[key_a] = True
    parent_flow.slots_shown_for_state[key_a] = True

    assert parent_flow._parse_slot(key_b, "1")["datetime_iso"] == "B"
    assert key_b not in parent_flow.ask_name_retries
    assert key_b not in parent_flow.invalid_phone_retries
    assert key_b not in parent_flow.slots_shown_for_state


def test_executor_caches_do_not_leak_across_pages_or_platforms():
    parent_tool_executor.manager_notified_for_conversation.clear()
    parent_tool_executor._last_slots_by_sender.clear()
    parent_tool_executor.book_consultation_success_for_conversation.clear()

    conv_a = _conversation(sender="SAME", platform="messenger", page_id="PAGE-A")
    conv_b = _conversation(sender="SAME", platform="messenger", page_id="PAGE-B")
    conv_ig = _conversation(sender="SAME", platform="instagram", page_id="IG-PAGE")
    ex_a = ParentToolExecutor(conv_a, conv_a.lead, conv_a.sender_id, conv_a.platform)
    ex_b = ParentToolExecutor(conv_b, conv_b.lead, conv_b.sender_id, conv_b.platform)
    ex_ig = ParentToolExecutor(conv_ig, conv_ig.lead, conv_ig.sender_id, conv_ig.platform)

    parent_tool_executor._mark_manager_notified(ex_a.cache_key, legacy_sender_id=ex_a.sender_id)
    parent_tool_executor._last_slots_by_sender[ex_a.cache_key] = [{"slot_id": 1}]
    parent_tool_executor.book_consultation_success_for_conversation[ex_a.cache_key] = True

    assert parent_tool_executor._is_manager_notified(ex_a.cache_key, legacy_sender_id=ex_a.sender_id)
    assert not parent_tool_executor._is_manager_notified(ex_b.cache_key, legacy_sender_id=ex_b.sender_id)
    assert not parent_tool_executor._is_manager_notified(ex_ig.cache_key, legacy_sender_id=ex_ig.sender_id)
    assert ex_b.cache_key not in parent_tool_executor._last_slots_by_sender
    assert ex_ig.cache_key not in parent_tool_executor.book_consultation_success_for_conversation


def test_manager_notified_redis_dual_reads_legacy_sender_key(monkeypatch):
    parent_tool_executor.manager_notified_for_conversation.clear()
    stored: dict[str, dict] = {"manager_notified:SAME": {"notified": True}}

    monkeypatch.setattr(redis_state_service, "is_enabled", lambda: True)
    monkeypatch.setattr(redis_state_service, "exists", lambda key: key in stored)
    monkeypatch.setattr(redis_state_service, "conversation_ttl_seconds", lambda: 3600)

    def _set_json(key: str, payload: dict, ttl: int | None = None) -> bool:
        stored[key] = dict(payload)
        return True

    monkeypatch.setattr(redis_state_service, "set_json", _set_json)

    canonical = "facebook:PAGE-A:SAME"
    assert parent_tool_executor._is_manager_notified(canonical, legacy_sender_id="SAME")
    assert parent_tool_executor.manager_notified_for_conversation[canonical] is True
    assert stored["manager_notified:facebook:PAGE-A:SAME"]["session_key"] == canonical
    assert stored["manager_notified:facebook:PAGE-A:SAME"]["sender_id"] == "SAME"


def test_trace_records_page_aware_masked_session_identity(monkeypatch):
    monkeypatch.setattr(conversation_trace, "_enabled", lambda: True)
    conversation_trace.reset_history()

    sender = "1234567890"
    page_a = "PAGE-SECRET-A"
    page_b = "PAGE-SECRET-B"
    key_a = canonical_session_key("messenger", page_a, sender)
    key_b = canonical_session_key("messenger", page_b, sender)

    conversation_trace.begin(sender, "hello", "messenger", page_id=page_a, session_key=key_a)
    conversation_trace.emit()
    conversation_trace.begin(sender, "hello", "messenger", page_id=page_b, session_key=key_b)
    conversation_trace.emit()

    first, second = conversation_trace.history()[-2:]
    assert first["session_hash"] != second["session_hash"]
    assert first["session"] != second["session"]
    serialized = json.dumps([first, second], ensure_ascii=False)
    assert page_a not in serialized
    assert page_b not in serialized
    assert sender not in serialized


def test_reset_conversation_for_sender_clears_canonical_side_caches():
    sender = "RESET-SENDER"
    conv = _conversation(sender=sender, page_id="PAGE-A")
    key = conversation_cache_key(conv)
    conversation_service.conversations[key] = conv
    parent_flow.available_slots[key] = [{"slot_id": 1}]
    parent_flow.ask_name_retries[key] = True
    parent_flow.invalid_phone_retries[key] = True
    parent_flow.slots_shown_for_state[key] = True
    parent_turn_router.manager_offer_shown[key] = True
    adult_flow.selected_events[key] = _event("A", "Event A")
    parent_tool_executor.manager_notified_for_conversation[key] = True
    parent_tool_executor._last_slots_by_sender[key] = [{"slot_id": 1}]
    parent_tool_executor.book_consultation_success_for_conversation[key] = True

    assert conversation_service.reset_conversation_for_sender(sender) is True

    assert key not in conversation_service.conversations
    assert key not in parent_flow.available_slots
    assert key not in parent_flow.ask_name_retries
    assert key not in parent_flow.invalid_phone_retries
    assert key not in parent_flow.slots_shown_for_state
    assert key not in parent_turn_router.manager_offer_shown
    assert key not in adult_flow.selected_events
    assert key not in parent_tool_executor.manager_notified_for_conversation
    assert key not in parent_tool_executor._last_slots_by_sender
    assert key not in parent_tool_executor.book_consultation_success_for_conversation
