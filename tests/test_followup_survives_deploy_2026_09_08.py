"""A deploy cost parents their follow-up (2026-09-08).

The in-memory conversation store starts empty after every restart, and a
conversation only returns to it when THAT parent writes again. The follow-up
scheduler scans that store, so everyone who wrote before the restart was
invisible to it. Live evidence: on 2026-09-08 every hourly tick logged

    [FOLLOWUP] scanning total=1 parent=1 with_marker=1

— one conversation, the only sender who had written since the last deploy —
while Redis still held the others. `hydrate_from_redis` has existed since
2026-06-06 for the one-off CLI and was simply never called from the server.

The worry this had to answer first was whether loading everyone back could mix
two parents up. It cannot, and these tests are the proof rather than the
argument: keys are derived by the same `canonical_session_key` the live path
uses, the sender id is part of every key, and an in-memory session always wins.

Two guards ship with it:
  * a stored conversation with no page_id is NOT loaded — it derives to
    `<platform>:unknown:<sender>` while the same parent writing today derives
    to `<platform>:<page>:<sender>`, which is one person with two entries;
  * a conversation past Meta's 24h messaging window is NOT loaded — it can only
    produce a refused send that still advances the stage.
"""
import dataclasses
from datetime import timedelta

import pytest

from app import config as config_module
from app.agent.services.timestamps import now_tbilisi
from app.services import conversation_service as cs
from app.services import followup_service as fs


def _payload(sender, page, platform="messenger", name="", hours_ago=1.0):
    stamp = (now_tbilisi() - timedelta(hours=hours_ago)).isoformat()
    return {
        "sender_id": sender, "platform": platform, "page_id": page,
        "segment": "PARENT", "state": "DONE",
        "last_bot_message_at": stamp,
        "lead": {"sender_id": sender, "name": name},
    }


@pytest.fixture
def redis_holding(monkeypatch):
    """Stub the Redis surface `hydrate_from_redis` actually calls."""
    swapped = dataclasses.replace(config_module.settings, REDIS_ENABLED=True,
                                  REDIS_URL="redis://stub")
    monkeypatch.setattr(cs, "settings", swapped)
    monkeypatch.setattr("app.services.redis_state_service.is_enabled",
                        lambda: True)

    def _install(stored):
        monkeypatch.setattr("app.services.redis_state_service.scan_keys",
                            lambda pattern: list(stored.keys()))
        monkeypatch.setattr("app.services.redis_state_service.get_json",
                            lambda key: stored.get(key))
    monkeypatch.setattr(cs, "conversations", {})
    return _install


# ── the fix itself ─────────────────────────────────────────────────────────

def test_a_conversation_written_before_the_restart_comes_back(redis_holding):
    """The whole point: after a deploy the scheduler can see it again."""
    redis_holding({"conversation:messenger:P1:1001": _payload("1001", "P1")})
    assert cs.hydrate_from_redis() == 1
    assert len(cs.get_all_conversations_snapshot()) == 1


def test_the_scheduler_hydrates_before_it_scans(monkeypatch, redis_holding):
    """`scanning total=1` was the symptom; the tick must load first."""
    redis_holding({
        "conversation:messenger:P1:1001": _payload("1001", "P1"),
        "conversation:messenger:P1:1002": _payload("1002", "P1"),
    })
    monkeypatch.setattr(fs, "_maybe_send_followup_for_conversation",
                        lambda conv, now: "skipped")
    fs.check_and_send_followups()
    assert len(cs.conversations) == 2


# ── the worry: can two parents be mixed up? ────────────────────────────────

def test_each_parent_keeps_their_own_conversation(redis_holding):
    """Two parents on one page, plus one sender id used on two platforms."""
    redis_holding({
        "k1": _payload("1001", "P1", name="ანა"),
        "k2": _payload("1002", "P1", name="ბექა"),
        "k3": _payload("1001", "P2", platform="instagram", name="ანა-ინსტა"),
    })
    cs.hydrate_from_redis()
    by_key = {k: (c.sender_id, c.lead.name) for k, c in cs.conversations.items()}
    assert len(by_key) == 3
    for key, (sender, name) in by_key.items():
        assert sender in key, f"{key} holds {sender}"
    names = {sender: name for sender, name in by_key.values()}
    assert names["1002"] == "ბექა"          # never ანა's


def test_a_live_message_lands_on_that_parents_own_conversation(redis_holding):
    redis_holding({
        "k1": _payload("1001", "P1", name="ანა"),
        "k2": _payload("1002", "P1", name="ბექა"),
    })
    cs.hydrate_from_redis()
    conv = cs._get_or_create_conversation("1002", "messenger", "P1")
    assert conv.sender_id == "1002"
    assert conv.lead.name == "ბექა"


def test_a_live_conversation_is_never_overwritten(redis_holding):
    """The running process is the source of truth for fresh state."""
    redis_holding({"k1": _payload("1001", "P1", name="ძველი")})
    cs.hydrate_from_redis()
    cs.conversations[next(iter(cs.conversations))].lead.name = "ახალი"
    assert cs.hydrate_from_redis() == 0
    assert [c.lead.name for c in cs.conversations.values()] == ["ახალი"]


def test_the_key_is_the_same_one_the_live_path_builds(redis_holding):
    redis_holding({"k1": _payload("1001", "P1")})
    cs.hydrate_from_redis()
    assert list(cs.conversations) == [
        cs._conversation_session_key("1001", "messenger", "P1"),
    ]


# ── the two guards ─────────────────────────────────────────────────────────

def test_a_record_with_no_page_id_is_still_reachable_by_sender(redis_holding):
    """A record written before the canonical key existed derives to
    `<platform>:unknown:<sender>`, not to the page-scoped key a live message
    builds. That is not a mixed conversation — the sender id is in both — and
    the store resolves a bare sender id anyway, so the parent is still found.

    Guarding against it was considered and dropped: such a record is older than
    the field itself, so the 7-day Redis TTL has already removed every one, and
    the guard broke the documented behaviour in `test_followup_hydrate_patch`.
    """
    legacy = _payload("1003", "")
    legacy.pop("page_id")
    redis_holding({"k1": legacy})
    assert cs.hydrate_from_redis() == 1
    assert list(cs.conversations) == ["facebook:unknown:1003"]


def test_a_conversation_past_metas_window_is_not_loaded(redis_holding):
    """Meta refuses a `RESPONSE` send past 24h, and a refused send still
    advances the stage — so loading it would burn a stage that never arrived."""
    redis_holding({
        "fresh": _payload("1001", "P1", hours_ago=2),
        "stale": _payload("1002", "P1", hours_ago=48),
    })
    assert cs.hydrate_from_redis(keep=fs._within_messaging_window) == 1
    assert [c.sender_id for c in cs.conversations.values()] == ["1001"]


def test_a_conversation_the_bot_has_not_answered_is_kept(redis_holding):
    """No marker means nothing is stale about it."""
    fresh = _payload("1001", "P1")
    fresh["last_bot_message_at"] = ""
    redis_holding({"k1": fresh})
    assert cs.hydrate_from_redis(keep=fs._within_messaging_window) == 1


def test_a_broken_filter_never_costs_the_hydration(redis_holding):
    redis_holding({"k1": _payload("1001", "P1")})
    def _raises(_conv):
        raise RuntimeError("boom")
    assert cs.hydrate_from_redis(keep=_raises) == 1


def test_redis_unavailable_is_a_safe_no_op(monkeypatch, redis_holding):
    redis_holding({"k1": _payload("1001", "P1")})
    monkeypatch.setattr("app.services.redis_state_service.is_enabled",
                        lambda: False)
    assert cs.hydrate_from_redis() == 0


def test_a_hydration_fault_never_skips_the_tick(monkeypatch, redis_holding):
    """The tick must still run for whatever is already in memory."""
    redis_holding({})
    monkeypatch.setattr(cs, "hydrate_from_redis",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(fs, "_maybe_send_followup_for_conversation",
                        lambda conv, now: "skipped")
    fs.check_and_send_followups()      # must not raise
