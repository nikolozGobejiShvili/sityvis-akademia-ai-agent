"""Follow-up Live-Test Hydrate Patch (2026-06-06).

A one-off Python invocation of
``followup_service.check_and_send_followups()`` starts in a fresh
process — `conversation_service.conversations` is empty, the scheduler
scans zero entries, and no follow-up DM is sent even when the live
server is holding a perfectly due conversation.

This file covers the patch that closes the gap:

  * ``redis_state_service.scan_keys`` enumerates persisted
    `conversation:*` keys via SCAN (non-blocking).
  * ``conversation_service.hydrate_from_redis`` loads them into the
    in-memory dict.
  * ``followup_service.check_and_send_followups`` enriches its tick
    log with `total=`, `parent=`, `with_marker=`, `due=`, `sent=`,
    `skipped=` counters so an operator can see what happened.
  * ``tools/run_followup_tick.py`` exposes the same combination as a
    CLI helper (hydrate + tick).
"""

from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    conversation_service,
    followup_service,
    redis_state_service,
)


# =========================================================================
# A FakeRedis with SCAN support
# =========================================================================


class _ScanFakeRedis:
    """In-memory stand-in matching the methods the patch calls.

    Supports SCAN (cursor pagination, MATCH glob). The match logic is a
    plain Python ``fnmatch`` so the tests stay portable.
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

    def scan(self, cursor: int = 0, match: str = "*", count: int = 100):
        """Single-shot scan — returns everything that matches in one go.

        The cursor-based interface is preserved so the caller's
        `while cursor != 0` loop terminates after a single iteration.
        """
        import fnmatch
        keys = [k for k in self.store if fnmatch.fnmatchcase(k, match)]
        return 0, keys

    def close(self) -> None:
        pass


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _ScanFakeRedis()
    monkeypatch.setattr(redis_state_service, "_client", fake)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", True)
    swapped = dataclasses.replace(
        redis_state_service.settings,
        REDIS_URL="redis://test-fake/0",
        REDIS_ENABLED=True,
        REDIS_TTL_SECONDS=3600,
    )
    monkeypatch.setattr(redis_state_service, "settings", swapped)
    yield fake
    redis_state_service.reset()


@pytest.fixture(autouse=True)
def _clear_conversations():
    """Each test starts with an empty in-memory dict — simulating a
    fresh CLI process."""
    original = dict(conversation_service.conversations)
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()
    conversation_service.conversations.update(original)


# =========================================================================
# redis_state_service.scan_keys
# =========================================================================


def test_scan_keys_returns_empty_when_redis_disabled():
    # No fixture — redis defaults to disabled by the autouse fixture in
    # tests/conftest.py.
    assert redis_state_service.scan_keys("conversation:*") == []


def test_scan_keys_finds_only_matching_pattern(fake_redis):
    fake_redis.store["conversation:messenger:abc"] = json.dumps({"x": 1})
    fake_redis.store["conversation:instagram:def"] = json.dumps({"x": 1})
    fake_redis.store["processed_comment:cmt-1"] = json.dumps({"x": 1})
    keys = redis_state_service.scan_keys("conversation:*")
    assert "conversation:messenger:abc" in keys
    assert "conversation:instagram:def" in keys
    assert "processed_comment:cmt-1" not in keys


def test_scan_keys_no_match_returns_empty_list(fake_redis):
    fake_redis.store["other_thing:1"] = "value"
    assert redis_state_service.scan_keys("conversation:*") == []


# =========================================================================
# conversation_service.hydrate_from_redis
# =========================================================================


def _persist_conv(
    fake_redis: _ScanFakeRedis,
    sender_id: str,
    platform: str,
    *,
    segment: str = "PARENT",
    last_bot_iso: str | None = None,
    followup_stage: str = "",
    blocked_reason: str = "",
    booked: bool = False,
) -> Conversation:
    lead = Lead(sender_id=sender_id, platform=platform, segment=segment)
    lead.calendly_booked = booked
    conv = Conversation(
        sender_id=sender_id, platform=platform, segment=segment,
        lead=lead, followup_stage=followup_stage,
        followup_blocked_reason=blocked_reason,
    )
    if last_bot_iso is not None:
        conv.last_bot_message_at = last_bot_iso
    key = f"conversation:{platform}:{sender_id}"
    fake_redis.store[key] = json.dumps(conv.to_dict(), default=str)
    return conv


def test_hydrate_loads_persisted_conversations(fake_redis):
    _persist_conv(
        fake_redis, sender_id="cli-1", platform="messenger",
        last_bot_iso="2026-06-06T10:00:00",
    )
    _persist_conv(
        fake_redis, sender_id="cli-2", platform="instagram",
        last_bot_iso="2026-06-06T11:00:00",
    )

    loaded = conversation_service.hydrate_from_redis()
    assert loaded == 2
    assert "cli-1" in conversation_service.conversations
    assert "cli-2" in conversation_service.conversations
    assert conversation_service.conversations["cli-1"].segment == "PARENT"


def test_hydrate_does_not_overwrite_in_memory_entry(fake_redis):
    # Already in memory — older state.
    fresh = Conversation(
        sender_id="cli-1", platform="messenger", segment="PARENT",
    )
    fresh.followup_stage = "first_24h"  # already advanced in memory
    conversation_service.conversations["cli-1"] = fresh

    # Persisted state is the OLDER, unadvanced stage.
    _persist_conv(
        fake_redis, sender_id="cli-1", platform="messenger",
        followup_stage="",
    )
    loaded = conversation_service.hydrate_from_redis()
    assert loaded == 0  # skipped_existing
    # In-memory advanced stage preserved.
    assert (
        conversation_service.conversations["cli-1"].followup_stage
        == "first_24h"
    )


def test_hydrate_safe_when_redis_disabled():
    # No fake_redis fixture used — Redis stays disabled by the autouse
    # fixture in conftest.
    loaded = conversation_service.hydrate_from_redis()
    assert loaded == 0
    assert conversation_service.conversations == {}


def test_hydrate_skips_keys_with_invalid_payload(fake_redis):
    fake_redis.store["conversation:messenger:good"] = json.dumps(
        Conversation(
            sender_id="good", platform="messenger", segment="PARENT",
        ).to_dict(), default=str,
    )
    fake_redis.store["conversation:messenger:bad"] = "not json"
    fake_redis.store["conversation::"] = json.dumps({"x": 1})  # empty sender_id
    loaded = conversation_service.hydrate_from_redis()
    # Only the good one loads.
    assert loaded == 1
    assert "good" in conversation_service.conversations
    assert "bad" not in conversation_service.conversations


# =========================================================================
# Scheduler logging — total / parent / with_marker / due / sent / skipped
# =========================================================================


def _patch_followup_settings(monkeypatch, **overrides):
    swapped = dataclasses.replace(followup_service.settings, **overrides)
    monkeypatch.setattr(followup_service, "settings", swapped)
    return swapped


def _utc_iso(seconds_ago: int) -> str:
    return (datetime.utcnow() - timedelta(seconds=seconds_ago)).isoformat()


def test_scheduler_log_includes_counters_when_due(monkeypatch, caplog):
    _patch_followup_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        FOLLOWUP_ENABLED=True,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    lead = Lead(sender_id="m1", platform="messenger", segment="PARENT")
    conv = Conversation(
        sender_id="m1", platform="messenger", segment="PARENT",
        lead=lead, last_bot_message_at=_utc_iso(seconds_ago=200),
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "scanning total=1 parent=1 with_marker=1" in full
    assert "tick complete total=1 due=1 sent=1 skipped=0" in full


def test_scheduler_log_counts_zero_when_empty(monkeypatch, caplog):
    _patch_followup_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        FOLLOWUP_ENABLED=True,
        AGENT_ENABLED=True,
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "scanning total=0 parent=0 with_marker=0" in full
    assert "tick complete total=0 due=0 sent=0 skipped=0" in full


def test_scheduler_log_separates_parent_from_other(monkeypatch, caplog):
    _patch_followup_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        FOLLOWUP_ENABLED=True,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    parent = Conversation(
        sender_id="p1", platform="messenger", segment="PARENT",
        lead=Lead(sender_id="p1", platform="messenger", segment="PARENT"),
        last_bot_message_at=_utc_iso(seconds_ago=200),
    )
    adult = Conversation(
        sender_id="a1", platform="messenger", segment="ADULT",
        last_bot_message_at=_utc_iso(seconds_ago=200),
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [parent, adult],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "total=2 parent=1 with_marker=2" in full
    # ADULT conversation skipped — only PARENT advances.
    assert send.call_count == 1


def test_scheduler_log_marks_due_when_send_fails(monkeypatch, caplog):
    _patch_followup_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        FOLLOWUP_ENABLED=True,
        AGENT_ENABLED=True,
    )
    # Send returns False (Meta 400 / network) — stage still advances per
    # scheduler design, due counter still increments.
    send = MagicMock(return_value=False)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    conv = Conversation(
        sender_id="fail-1", platform="messenger", segment="PARENT",
        lead=Lead(sender_id="fail-1", platform="messenger", segment="PARENT"),
        last_bot_message_at=_utc_iso(seconds_ago=200),
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "due=1 sent=0 skipped=1" in full


# =========================================================================
# End-to-end CLI: hydrate → check_and_send_followups → DM sent
# =========================================================================


def test_cli_simulation_sends_followup_after_hydrate(
    monkeypatch, caplog, fake_redis,
):
    """Reproduce the live-bug scenario:
      1. Live server stamped `last_bot_message_at` 200 seconds ago
         and wrote the conversation through to Redis.
      2. Operator runs a fresh `python -c "..."` — `conversations` dict
         starts empty.
      3. WITHOUT hydrate → 0 conversations → 0 sends (the bug).
      4. WITH hydrate → 1 conversation → 1 send.
    """
    # Step 1: persist the live state.
    _persist_conv(
        fake_redis,
        sender_id="live-1",
        platform="messenger",
        last_bot_iso=_utc_iso(seconds_ago=200),
        followup_stage="",
    )

    _patch_followup_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        FOLLOWUP_ENABLED=True,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)

    # Step 3 — without hydrate. In-memory dict is empty.
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "total=0 parent=0 with_marker=0" in full
    send.assert_not_called()

    caplog.clear()

    # Step 4 — hydrate first, then tick.
    loaded = conversation_service.hydrate_from_redis()
    assert loaded == 1

    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "total=1 parent=1 with_marker=1" in full
    assert "tick complete total=1 due=1 sent=1 skipped=0" in full
    assert send.call_count == 1
    _, kwargs = send.call_args
    assert kwargs.get("platform") == "messenger"
    assert kwargs.get("sender_id") == "live-1"


def test_cli_helper_module_imports_without_side_effects():
    # Smoke import — the CLI tool should import cleanly without
    # configuring logging or talking to Redis.
    import importlib
    module = importlib.import_module("tools.run_followup_tick")
    assert hasattr(module, "main")
    # `main` is callable but we don't run it (would talk to real Redis).
    assert callable(module.main)
