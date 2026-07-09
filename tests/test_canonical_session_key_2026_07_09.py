from __future__ import annotations

import asyncio

import pytest

from app.services import conversation_service, message_buffer
from app.services.session_key_service import canonical_session_key


def test_canonical_session_key_normalizes_platform_and_requires_sender():
    assert (
        canonical_session_key("messenger", "1716573211895723", "1234567890")
        == "facebook:1716573211895723:1234567890"
    )
    assert canonical_session_key(" instagram ", "PAGE", "S") == "instagram:PAGE:S"
    assert canonical_session_key("whatsapp", "PHONE", "S") == "whatsapp:PHONE:S"
    assert canonical_session_key("", "", "S") == "unknown:unknown:S"
    with pytest.raises(ValueError):
        canonical_session_key("messenger", "PAGE", "")


def test_canonical_session_key_can_require_page_id():
    with pytest.raises(ValueError):
        canonical_session_key("messenger", "", "S", require_page_id=True)


def test_message_buffer_uses_page_scoped_canonical_keys():
    async def _run() -> None:
        calls: list[tuple[str, str, str, str]] = []

        async def _ready(sender_id: str, combined: str, platform: str, page_id: str) -> None:
            calls.append((sender_id, combined, platform, page_id))

        try:
            await message_buffer.buffer_message(
                sender_id="S", message="one", platform="messenger", page_id="P1", on_ready=_ready,
            )
            await message_buffer.buffer_message(
                sender_id="S", message="two", platform="messenger", page_id="P2", on_ready=_ready,
            )
            assert message_buffer._pending_messages["facebook:P1:S"] == ["one"]
            assert message_buffer._pending_messages["facebook:P2:S"] == ["two"]
        finally:
            for task in list(message_buffer._pending_tasks.values()):
                task.cancel()
            message_buffer._pending_messages.clear()
            message_buffer._pending_tasks.clear()
            message_buffer._buffer_started_at.clear()
            message_buffer._locks.clear()

    asyncio.run(_run())

def test_conversation_store_separates_same_sender_by_page_and_platform():
    conversation_service.conversations.clear()
    try:
        fb_a = conversation_service._get_or_create_conversation("S", "messenger", "PAGE-A")
        fb_b = conversation_service._get_or_create_conversation("S", "messenger", "PAGE-B")
        ig = conversation_service._get_or_create_conversation("S", "instagram", "IG-1")

        assert fb_a is not fb_b
        assert fb_a is not ig
        assert set(conversation_service.conversations.keys()) == {
            "facebook:PAGE-A:S",
            "facebook:PAGE-B:S",
            "instagram:IG-1:S",
        }
        assert "S" not in conversation_service.conversations
    finally:
        conversation_service.conversations.clear()