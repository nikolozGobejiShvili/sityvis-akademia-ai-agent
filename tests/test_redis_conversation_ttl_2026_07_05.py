"""Automatic Redis TTL for conversation memory — 8-day rolling expiration
(2026-07-05).

Contract:
  * New setting REDIS_CONVERSATION_TTL_SECONDS (default 691200 = 8 days).
  * redis_state_service.set_json(key, value, ttl_seconds=None) writes with a
    Redis EX expiry when a TTL is given; None preserves the old
    REDIS_TTL_SECONDS fallback. `ttl=` kept as a backward-compat alias.
  * conversation_service writes conversation state with the 8-day TTL, refreshed
    on every write-through (rolling window).
  * Per-user session guards (manager_notified, processed_comment) share the same
    rolling window.
  * Each user/conversation key expires independently.

No real Redis: redis_state_service is wired to a tiny in-process FakeRedis that
records the TTL (`ex`) requested per key.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.config import Settings
from app.models.conversation import Conversation
from app.services import (
    comment_service,
    conversation_service,
    redis_state_service,
)
from app.agent.tools import parent_tool_executor

EIGHT_DAYS = 691200


# -- FakeRedis + fixtures --------------------------------------------------


class _FakeRedis:
    """Minimal in-memory Redis double that records the `ex` TTL per key."""

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
            if self.store.pop(key, None) is not None:
                self.ttl_per_key.pop(key, None)
                n += 1
        return n

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def close(self) -> None:
        pass


def _enable_fake(monkeypatch, fake, **setting_overrides):
    monkeypatch.setattr(redis_state_service, "_client", fake)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", True)
    overrides = {
        "REDIS_URL": "redis://test-fake/0",
        "REDIS_ENABLED": True,
        # Deliberately DIFFERENT from the conversation TTL so a test can tell
        # which one a given write used.
        "REDIS_TTL_SECONDS": 3600,
        "REDIS_CONVERSATION_TTL_SECONDS": EIGHT_DAYS,
    }
    overrides.update(setting_overrides)
    swapped = dataclasses.replace(redis_state_service.settings, **overrides)
    monkeypatch.setattr(redis_state_service, "settings", swapped)
    return fake


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _enable_fake(monkeypatch, _FakeRedis())
    yield fake
    redis_state_service.reset()


# -- (6) Setting default ---------------------------------------------------


def test_setting_exists_and_defaults_to_eight_days():
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert "REDIS_CONVERSATION_TTL_SECONDS" in fields
    assert Settings().REDIS_CONVERSATION_TTL_SECONDS == EIGHT_DAYS


def test_conversation_ttl_accessor_reads_setting(monkeypatch):
    _enable_fake(monkeypatch, _FakeRedis(), REDIS_CONVERSATION_TTL_SECONDS=12345)
    try:
        assert redis_state_service.conversation_ttl_seconds() == 12345
    finally:
        redis_state_service.reset()


def test_conversation_ttl_accessor_defaults_when_missing_or_invalid(monkeypatch):
    # Missing attribute → default. Zero / negative / non-numeric → default.
    for bad in (None, 0, -5, "oops"):
        _enable_fake(
            monkeypatch, _FakeRedis(), REDIS_CONVERSATION_TTL_SECONDS=bad,
        )
        try:
            assert redis_state_service.conversation_ttl_seconds() == EIGHT_DAYS
        finally:
            redis_state_service.reset()


def test_from_env_missing_var_defaults_to_eight_days(monkeypatch):
    # The PRODUCTION default: settings are built via Settings.from_env(), whose
    # fallback literal (not the dataclass field default) is the live value when
    # the env var is absent. Guards against that from_env literal drifting.
    import app.config as config
    monkeypatch.delenv("REDIS_CONVERSATION_TTL_SECONDS", raising=False)
    s = config.Settings.from_env()
    assert s.REDIS_CONVERSATION_TTL_SECONDS == EIGHT_DAYS


def test_from_env_reads_operator_override(monkeypatch):
    import app.config as config
    monkeypatch.setenv("REDIS_CONVERSATION_TTL_SECONDS", "12345")
    s = config.Settings.from_env()
    assert s.REDIS_CONVERSATION_TTL_SECONDS == 12345


# -- (1) set_json uses EX when ttl_seconds is provided --------------------


def test_set_json_uses_ex_when_ttl_seconds_given(fake_redis):
    assert redis_state_service.set_json("k1", {"x": 1}, ttl_seconds=99) is True
    assert fake_redis.ttl_per_key["k1"] == 99


def test_set_json_positional_ttl_binds_to_ttl_seconds(fake_redis):
    assert redis_state_service.set_json("k2", {"x": 1}, 77) is True
    assert fake_redis.ttl_per_key["k2"] == 77


def test_set_json_backward_compat_ttl_alias(fake_redis):
    # Existing callers pass the legacy `ttl=` keyword — must still work.
    assert redis_state_service.set_json("k3", {"x": 1}, ttl=55) is True
    assert fake_redis.ttl_per_key["k3"] == 55


def test_set_json_ttl_seconds_wins_over_alias(fake_redis):
    redis_state_service.set_json("k4", {"x": 1}, ttl_seconds=10, ttl=999)
    assert fake_redis.ttl_per_key["k4"] == 10


# -- (2) set_json preserves old behaviour when ttl_seconds is None --------


def test_set_json_none_falls_back_to_redis_ttl_seconds(fake_redis):
    assert redis_state_service.set_json("k5", {"x": 1}) is True
    # Falls back to REDIS_TTL_SECONDS (3600), NOT the conversation TTL.
    assert fake_redis.ttl_per_key["k5"] == 3600


# -- (3) conversation save applies the 8-day TTL --------------------------


def _make_conversation(sender_id: str, platform: str = "messenger") -> Conversation:
    return Conversation(sender_id=sender_id, platform=platform)


def test_conversation_save_applies_eight_day_ttl(fake_redis):
    conv = _make_conversation("user_a")
    conversation_service._save_conversation_to_redis(conv)
    key = conversation_service._conversation_redis_key("messenger", "user_a")
    assert key in fake_redis.store
    assert fake_redis.ttl_per_key[key] == EIGHT_DAYS
    # NOT the generic REDIS_TTL_SECONDS default.
    assert fake_redis.ttl_per_key[key] != 3600


def test_conversation_save_uses_configured_ttl_dynamically(monkeypatch):
    fake = _enable_fake(
        monkeypatch, _FakeRedis(), REDIS_CONVERSATION_TTL_SECONDS=4242,
    )
    try:
        conv = _make_conversation("user_dyn")
        conversation_service._save_conversation_to_redis(conv)
        key = conversation_service._conversation_redis_key("messenger", "user_dyn")
        assert fake.ttl_per_key[key] == 4242
    finally:
        redis_state_service.reset()


# -- (4) a repeated message refreshes the TTL -----------------------------


def test_repeated_write_refreshes_ttl(fake_redis):
    conv = _make_conversation("user_refresh")
    key = conversation_service._conversation_redis_key("messenger", "user_refresh")

    conversation_service._save_conversation_to_redis(conv)
    assert fake_redis.ttl_per_key[key] == EIGHT_DAYS

    # Simulate the next message: TTL is re-applied (SET ... EX) on every write.
    fake_redis.ttl_per_key[key] = None  # pretend the recorded expiry decayed
    conversation_service._save_conversation_to_redis(conv)
    assert fake_redis.ttl_per_key[key] == EIGHT_DAYS


# -- (5) different users expire independently -----------------------------


def test_different_users_have_independent_ttls(fake_redis):
    conv_a = _make_conversation("mariam")
    conv_b = _make_conversation("nodari")
    conversation_service._save_conversation_to_redis(conv_a)
    conversation_service._save_conversation_to_redis(conv_b)

    key_a = conversation_service._conversation_redis_key("messenger", "mariam")
    key_b = conversation_service._conversation_redis_key("messenger", "nodari")

    assert key_a != key_b
    assert fake_redis.ttl_per_key[key_a] == EIGHT_DAYS
    assert fake_redis.ttl_per_key[key_b] == EIGHT_DAYS

    # Expiring one user's key does not touch the other's.
    fake_redis.delete(key_a)
    assert key_a not in fake_redis.store
    assert key_b in fake_redis.store
    assert fake_redis.ttl_per_key[key_b] == EIGHT_DAYS


# -- (7) processed_comment + manager_notified session guards have TTL -----


def test_processed_comment_write_has_ttl(fake_redis):
    comment_service._mark_comment_expired("cid_ttl_test")
    key = "processed_comment:cid_ttl_test"
    assert key in fake_redis.store
    assert fake_redis.ttl_per_key[key] == EIGHT_DAYS


def test_manager_notified_write_has_ttl(fake_redis):
    try:
        parent_tool_executor._mark_manager_notified("sender_notify")
        key = parent_tool_executor._manager_notified_redis_key("sender_notify")
        assert key in fake_redis.store
        assert fake_redis.ttl_per_key[key] == EIGHT_DAYS
    finally:
        parent_tool_executor.reset_state()


# -- Disabled Redis stays a safe no-op ------------------------------------


def test_disabled_redis_is_noop(monkeypatch):
    monkeypatch.setattr(redis_state_service, "_client", None)
    monkeypatch.setattr(redis_state_service, "_connection_attempted", True)
    monkeypatch.setattr(redis_state_service, "_connection_ok", False)
    swapped = dataclasses.replace(
        redis_state_service.settings, REDIS_URL="", REDIS_ENABLED=True,
    )
    monkeypatch.setattr(redis_state_service, "settings", swapped)
    try:
        # No crash, no write.
        conversation_service._save_conversation_to_redis(_make_conversation("z"))
        assert redis_state_service.set_json("k", {"x": 1}, ttl_seconds=5) is False
    finally:
        redis_state_service.reset()
