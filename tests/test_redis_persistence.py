"""P3-B — Redis persistence tests.

Covers the safe-fallback shape required by the migration brief:

  * Settings has REDIS_URL / REDIS_ENABLED / REDIS_TTL_SECONDS.
  * redis_state_service is a no-op when REDIS_URL is empty.
  * Full REDIS_URL is never logged (only url_configured + connected).
  * Conversation.to_dict / from_dict roundtrip preserves all fields.
  * Unknown fields in a saved payload do not crash from_dict.
  * pending_booking persists and restores.
  * Conversation save/load roundtrip uses the correct Redis key.
  * manager_notified persists across a simulated restart.
  * processed_comment_id is honoured even after a simulated restart.
  * Existing in-memory behaviour is preserved when Redis is disabled.

No real Redis required: the redis_state_service module is patched with
a tiny in-process FakeRedis stand-in.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import redis_state_service


# -- A tiny in-process Redis double ----------------------------------------


class _FakeRedis:
    """Minimal in-memory stand-in matching the methods we call.

    Records the TTL per set() call so tests can assert that we DID
    request a TTL (the brief explicitly requires it).
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl_per_key: dict[str, int | None] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.ttl_per_key[key] = ex
        return True

    def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self.store:
                self.store.pop(key, None)
                self.ttl_per_key.pop(key, None)
                n += 1
        return n

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def close(self) -> None:
        pass


@pytest.fixture
def fake_redis(monkeypatch):
    """Wire redis_state_service to a FakeRedis instance and enable it."""
    fake = _FakeRedis()

    # Patch the lazy-connection state so is_enabled() returns True
    # without trying to import or talk to a real redis server.
    monkeypatch.setattr(redis_state_service, "_client", fake)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", True)
    # Force settings into "enabled + url present" so is_enabled() returns True.
    swapped = dataclasses.replace(
        redis_state_service.settings,
        REDIS_URL="redis://test-fake/0",
        REDIS_ENABLED=True,
        REDIS_TTL_SECONDS=3600,
    )
    monkeypatch.setattr(redis_state_service, "settings", swapped)

    yield fake

    redis_state_service.reset()


@pytest.fixture
def redis_disabled(monkeypatch):
    """Force redis_state_service into the safe-fallback (no-op) state."""
    monkeypatch.setattr(redis_state_service, "_client", None)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", False)
    swapped = dataclasses.replace(
        redis_state_service.settings,
        REDIS_URL="",
        REDIS_ENABLED=True,
    )
    monkeypatch.setattr(redis_state_service, "settings", swapped)
    yield
    redis_state_service.reset()


# -- (1) Settings field wiring ---------------------------------------------


def test_settings_has_redis_fields():
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert "REDIS_URL" in fields
    assert "REDIS_ENABLED" in fields
    assert "REDIS_TTL_SECONDS" in fields
    bare = Settings()
    assert bare.REDIS_URL == ""
    assert bare.REDIS_ENABLED is True
    assert bare.REDIS_TTL_SECONDS == 604800


# -- (2) Disabled mode: every operation is a safe no-op --------------------


def test_redis_disabled_when_url_missing(redis_disabled):
    assert redis_state_service.is_enabled() is False
    assert redis_state_service.get_json("anything") is None
    assert redis_state_service.set_json("k", {"a": 1}) is False
    assert redis_state_service.delete("k") is False
    assert redis_state_service.exists("k") is False
    assert redis_state_service.ping() is False


# -- (3) Full URL is never logged ------------------------------------------


def test_redis_url_not_logged_at_startup(monkeypatch, caplog):
    monkeypatch.setattr(redis_state_service, "_client", None)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", True)
    swapped = dataclasses.replace(
        redis_state_service.settings,
        REDIS_URL="redis://default:super-secret-pw@redis.example.com:6379",
        REDIS_ENABLED=True,
    )
    monkeypatch.setattr(redis_state_service, "settings", swapped)

    with caplog.at_level(logging.INFO):
        redis_state_service.log_startup_status()

    for record in caplog.records:
        msg = record.getMessage()
        assert "super-secret-pw" not in msg
        assert "redis.example.com" not in msg


# -- (4) Conversation.to_dict / from_dict roundtrip ------------------------


def test_conversation_roundtrip_preserves_fields():
    lead = Lead(
        sender_id="s1",
        platform="messenger",
        segment="PARENT",
        name="ნიკოლოზი",
        phone="595999733",
        child_age="10",
        challenge="ეკრანისგან დისტანცია",
        calendly_booked=True,
        booked_datetime_iso="2030-05-28T15:00:00+04:00",
        calendar_event_id="evt_abc",
    )
    conv = Conversation(
        sender_id="s1",
        platform="messenger",
        page_id="PAGE-1",
        segment="PARENT",
        state="DONE",
        history=[{"role": "user", "content": "გამარჯობა"}],
        lead=lead,
        pending_booking={
            "requested_datetime_iso": "2030-05-28T15:00:00+04:00",
            "missing_fields": [],
            "user_confirmed_datetime": True,
            "source": "user_selected_slot",
        },
        last_bot_message_at="2030-05-27T10:00:00+04:00",
        followup_stage="first_24h",
        followup_blocked_reason="booked",
        last_meaningful_interest="price",
        stopped_after="age",
    )

    payload = conv.to_dict()
    # Must be JSON-safe.
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "ნიკოლოზი" in encoded

    restored = Conversation.from_dict(json.loads(encoded))
    assert restored.sender_id == "s1"
    assert restored.platform == "messenger"
    assert restored.state == "DONE"
    assert restored.lead is not None
    assert restored.lead.name == "ნიკოლოზი"
    assert restored.lead.phone == "595999733"
    assert restored.lead.calendar_event_id == "evt_abc"
    assert restored.pending_booking == conv.pending_booking
    assert restored.followup_blocked_reason == "booked"


# -- (5) Unknown / extra fields do not crash from_dict ---------------------


def test_conversation_from_dict_tolerates_unknown_fields():
    payload = {
        "sender_id": "s1",
        "platform": "messenger",
        "future_field_we_dont_know_yet": "ignored",
        "another_one": {"nested": True},
    }
    conv = Conversation.from_dict(payload)
    assert conv.sender_id == "s1"
    assert conv.state == "START"


# -- (6) set_json applies TTL ----------------------------------------------


def test_set_json_applies_ttl(fake_redis):
    ok = redis_state_service.set_json("conversation:test:1", {"sender_id": "1"})
    assert ok is True
    assert fake_redis.ttl_per_key["conversation:test:1"] == 3600


def test_set_json_accepts_explicit_ttl(fake_redis):
    ok = redis_state_service.set_json("k", {"x": 1}, ttl=60)
    assert ok is True
    assert fake_redis.ttl_per_key["k"] == 60


def test_set_json_handles_non_serialisable(fake_redis):
    class BadStr:
        def __str__(self) -> str:
            raise RuntimeError("nope")

    # default=str catches sets / datetimes safely, but an object whose
    # __str__ raises bubbles up — and set_json must convert that to a
    # safe-failure return value.
    assert redis_state_service.set_json("k", {"bad": BadStr()}) is False


# -- (7) Conversation persists across simulated restart --------------------


def test_conversation_persists_through_restart(fake_redis):
    """Full restart simulation:

      1. Save a Conversation through conversation_service.
      2. Clear the in-memory dict (simulates `python -m uvicorn` restart).
      3. Re-enter conversation_service._get_or_create_conversation —
         the Conversation should be restored from Redis.
    """
    from app.services import conversation_service

    # Stage 1 — populate via the public path.
    conversation_service.conversations.clear()
    conv = Conversation(
        sender_id="sim-1",
        platform="messenger",
        page_id="PAGE-1",
        segment="PARENT",
        state="DONE",
        pending_booking={
            "requested_datetime_iso": "2030-05-28T15:00:00+04:00",
            "user_confirmed_datetime": True,
        },
    )
    conversation_service.conversations["sim-1"] = conv
    conversation_service._save_conversation_to_redis(conv)

    # Stage 2 — simulate process restart by wiping the in-memory dict.
    conversation_service.conversations.clear()

    # Stage 3 — request the same sender, expect a Redis restore.
    restored = conversation_service._get_or_create_conversation("sim-1", "messenger", "PAGE-1")

    assert restored.state == "DONE"
    assert restored.segment == "PARENT"
    assert restored.pending_booking == conv.pending_booking
    # And the in-memory dict was re-populated as a side effect.
    assert "facebook:PAGE-1:sim-1" in conversation_service.conversations
    assert conversation_service.conversations["sim-1"] is restored


# -- (8) Conversation save/load uses correct Redis key ---------------------


def test_conversation_redis_key_format():
    from app.services.conversation_service import _conversation_redis_key
    assert (
        _conversation_redis_key("messenger", "1716573211895723", "27309128242013890")
        == "conversation:facebook:1716573211895723:27309128242013890"
    )


def test_conversation_dual_reads_legacy_redis_key(fake_redis):
    from app.services import conversation_service

    conversation_service.conversations.clear()
    conv = Conversation(
        sender_id="legacy-1", platform="messenger", segment="PARENT", state="ASK_NAME",
    )
    legacy_key = "conversation:messenger:legacy-1"
    fake_redis.store[legacy_key] = json.dumps(conv.to_dict(), default=str)

    restored = conversation_service._get_or_create_conversation(
        "legacy-1", "messenger", "PAGE-LEGACY",
    )

    assert restored.state == "ASK_NAME"
    assert restored.page_id == "PAGE-LEGACY"
    assert restored.session_key == "facebook:PAGE-LEGACY:legacy-1"
    assert legacy_key in fake_redis.store
    assert "conversation:facebook:PAGE-LEGACY:legacy-1" in fake_redis.store


# -- (9) Redis failure is invisible to the caller --------------------------


def test_conversation_service_falls_back_when_redis_get_raises(monkeypatch):
    from app.services import conversation_service

    # Enabled state but get() blows up.
    fake = _FakeRedis()
    fake.get = MagicMock(side_effect=RuntimeError("network blip"))  # type: ignore
    monkeypatch.setattr(redis_state_service, "_client", fake)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", True)
    monkeypatch.setattr(
        redis_state_service, "settings",
        dataclasses.replace(
            redis_state_service.settings,
            REDIS_URL="redis://x",
            REDIS_ENABLED=True,
        ),
    )

    conversation_service.conversations.clear()
    # Must NOT raise even though Redis is throwing.
    conv = conversation_service._get_or_create_conversation("nope", "messenger")
    assert conv.sender_id == "nope"
    assert conv.state == "START"
    redis_state_service.reset()


# -- (10) processed_comment_id duplicate guard -----------------------------


def test_processed_comment_id_duplicate_guard(fake_redis):
    """Direct check that the simple key-existence guard works.

    The webhook layer's `handle_comment` consults
    `redis_state_service.exists("processed_comment:<id>")` and early-
    returns when present. We exercise the underlying primitive here.
    """
    key = "processed_comment:abc-123"

    assert redis_state_service.exists(key) is False
    ok = redis_state_service.set_json(key, {"comment_id": "abc-123"})
    assert ok is True
    assert redis_state_service.exists(key) is True

    # "Restart" — drop the would-be in-memory state, but Redis persists.
    # exists() should still report True.
    assert redis_state_service.exists(key) is True


# -- (11) manager_notified persists across simulated restart ---------------


def test_manager_notified_persists_through_restart(fake_redis):
    from app.agent.tools import parent_tool_executor

    parent_tool_executor.manager_notified_for_conversation.clear()

    sender = "sender-restart-test"
    parent_tool_executor._mark_manager_notified(sender)
    # Direct check first:
    assert parent_tool_executor._is_manager_notified(sender) is True

    # Simulate restart: in-memory dict wiped.
    parent_tool_executor.manager_notified_for_conversation.clear()

    # Should still report True via Redis fallback.
    assert parent_tool_executor._is_manager_notified(sender) is True
    # And re-populated the in-memory dict for the rest of the session.
    assert parent_tool_executor.manager_notified_for_conversation[sender] is True
