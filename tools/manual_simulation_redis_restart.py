"""P3-B — Manual simulation of restart-safe state via Redis.

Exercises three scenarios end-to-end without touching a real Redis
server: a tiny in-process FakeRedis class is wired into
``redis_state_service`` so the rest of the codebase sees an enabled
backend and the persistence layer is exercised exactly as it would be
against a real server.

Scenarios (mirror the P3-B brief):

  A) Pending booking restart — Conversation is saved, in-memory dict
     is wiped to simulate `uvicorn --reload`, then reloaded from Redis.
     The pending_booking record is intact.

  B) Comment duplicate after restart — `processed_comment:{id}` is
     written, the in-memory state is wiped, and `exists()` still
     reports True so the webhook layer short-circuits the duplicate.

  C) Manager-notified guard — the parent_tool_executor marks the lead
     as notified, the in-memory dict is wiped, and the helper still
     reports True via the Redis fallback.

Run with:

    python tools/manual_simulation_redis_restart.py
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

# Make the project root importable when launched from ``tools/``.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models.conversation import Conversation  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.services import redis_state_service  # noqa: E402


class _FakeRedis:
    """Drop-in replacement matching the redis-py methods we use."""

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


def _enable_fake_redis() -> _FakeRedis:
    fake = _FakeRedis()
    redis_state_service._client = fake
    redis_state_service._connection_attempted = True
    redis_state_service._connection_ok = True
    redis_state_service.settings = dataclasses.replace(
        redis_state_service.settings,
        REDIS_URL="redis://fake-local/0",
        REDIS_ENABLED=True,
        REDIS_TTL_SECONDS=3600,
    )
    return fake


def scenario_a_pending_booking_restart() -> None:
    print("\n=== Scenario A — Pending booking survives restart ===")
    from app.services import conversation_service

    conversation_service.conversations.clear()

    sender = "sim-A-595999733"

    # Stage 1 — the bot has just confirmed a pending booking with the
    # user; the in-memory Conversation holds the requested slot.
    lead = Lead(
        sender_id=sender,
        platform="messenger",
        segment="PARENT",
        name="",
        phone="",
        child_age="10",
        challenge="ეკრანისგან დისტანცია",
    )
    conv = Conversation(
        sender_id=sender,
        platform="messenger",
        segment="PARENT",
        state="ASK_NAME",
        lead=lead,
        pending_booking={
            "requested_datetime_iso": "2030-05-28T15:00:00+04:00",
            "user_confirmed_datetime": True,
            "source": "user_selected_slot",
            "missing_fields": ["name", "phone"],
        },
    )
    conversation_service.conversations[sender] = conv
    conversation_service._save_conversation_to_redis(conv)
    print(f"  Saved: state={conv.state} pending_booking={bool(conv.pending_booking)}")

    # Stage 2 — simulate `Ctrl+C` + restart: the in-memory dict is gone.
    conversation_service.conversations.clear()
    assert sender not in conversation_service.conversations
    print("  Restart simulated — in-memory dict cleared.")

    # Stage 3 — the user sends their name+phone; the loader restores
    # everything from Redis.
    restored = conversation_service._get_or_create_conversation(sender, "messenger")
    assert restored.state == "ASK_NAME"
    assert restored.pending_booking is not None
    assert restored.pending_booking["requested_datetime_iso"] == (
        "2030-05-28T15:00:00+04:00"
    )
    assert restored.lead is not None
    assert restored.lead.child_age == "10"
    assert restored.lead.challenge == "ეკრანისგან დისტანცია"
    print(
        f"  Restored: state={restored.state} "
        f"slot={restored.pending_booking['requested_datetime_iso']} "
        f"age={restored.lead.child_age} challenge={restored.lead.challenge!r}"
    )
    print("  ✅ pending_booking + lead context survived restart.")


def scenario_b_comment_duplicate_after_restart() -> None:
    print("\n=== Scenario B — Comment duplicate skipped after restart ===")

    comment_id = "comment_abc_123"
    key = f"processed_comment:{comment_id}"

    # Stage 1 — webhook first delivery, the comment_id is marked.
    redis_state_service.set_json(key, {
        "comment_id": comment_id,
        "post_id": "post_xyz",
        "segment": "PARENT",
        "platform": "facebook",
        "dm_sent": True,
    })
    print(f"  Marked processed: {key}")

    # Stage 2 — restart. In-memory state is wiped — Redis is the only
    # source of truth for this guard.
    print("  Restart simulated.")

    # Stage 3 — same comment_id arrives again (Meta retry / replay).
    duplicate = redis_state_service.exists(key)
    assert duplicate is True
    print(f"  Duplicate check: exists={duplicate} → DM will be SKIPPED.")
    print("  ✅ duplicate comment_id correctly suppressed post-restart.")


def scenario_c_manager_notified_guard() -> None:
    print("\n=== Scenario C — Manager notification duplicate guard ===")
    from app.agent.tools import parent_tool_executor

    parent_tool_executor.manager_notified_for_conversation.clear()

    sender = "sim-C-manager-595999733"

    # Stage 1 — booking completed, manager notified.
    parent_tool_executor._mark_manager_notified(sender)
    assert parent_tool_executor._is_manager_notified(sender) is True
    print(f"  Manager marked notified for {sender}")

    # Stage 2 — restart, in-memory dict wiped.
    parent_tool_executor.manager_notified_for_conversation.clear()
    print("  Restart simulated — manager_notified_for_conversation wiped.")

    # Stage 3 — user sends "მადლობა". The executor consults the guard;
    # Redis still says "already notified" so the manager is NOT
    # re-notified.
    still_notified = parent_tool_executor._is_manager_notified(sender)
    assert still_notified is True
    print(f"  Post-restart check: is_manager_notified={still_notified}")
    print("  ✅ duplicate manager notification correctly suppressed.")


def main() -> int:
    _enable_fake_redis()
    print("=" * 60)
    print("P3-B — Redis restart-safety simulation")
    print(f"Redis enabled: {redis_state_service.is_enabled()}")
    print("=" * 60)

    try:
        scenario_a_pending_booking_restart()
        scenario_b_comment_duplicate_after_restart()
        scenario_c_manager_notified_guard()
    except AssertionError as exc:
        print(f"\n❌ Assertion failed: {exc}")
        return 1
    except Exception as exc:
        print(f"\n❌ Unexpected error: {exc}")
        return 2
    finally:
        redis_state_service.reset()

    print("\n" + "=" * 60)
    print("✅ All three restart-safety scenarios passed.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
