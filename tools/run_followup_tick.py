"""One-off CLI helper to trigger the follow-up scheduler.

Follow-up Live-Test Hydrate Patch (2026-06-06).

Why this exists:
  The follow-up scheduler reads from the in-memory
  ``conversation_service.conversations`` dict. A fresh Python process
  (e.g. ``python -c "..."``) has an EMPTY dict — it cannot see what
  the live server is holding. Without hydrate, a manual tick reports
  ``[FOLLOWUP] scanning total=0`` and silently skips everything.

  This helper hydrates the in-memory dict from Redis FIRST and then
  runs the standard ``check_and_send_followups()``. The same tick the
  live server would run from APScheduler is reproduced from a console
  — useful for QA against the 2-minute test cadence.

Usage:
  python tools/run_followup_tick.py            # hydrate + tick once
  python tools/run_followup_tick.py --dry-run  # hydrate + print due
                                                # conversations, NO send
  python tools/run_followup_tick.py --once     # same as default

Requirements:
  * Redis must be live and reachable. The same `REDIS_URL` /
    `REDIS_ENABLED` env values the server uses.
  * `AGENT_ENABLED` must be true (the kill switch otherwise
    short-circuits the tick).
  * `FOLLOWUP_ENABLED` must be true.
"""

from __future__ import annotations

import sys
from pathlib import Path

# When `tools/run_followup_tick.py` is executed directly (e.g.
# `python tools/run_followup_tick.py`), Python does NOT add the
# project root to `sys.path` automatically, so the downstream
# `from app.services ...` imports fail with `ModuleNotFoundError:
# No module named 'app'`. Insert the project root before any app.*
# import so the CLI works the same way as the in-process scheduler.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import logging


def _configure_logging() -> None:
    """Stream logs straight to stdout so the operator sees the same
    `[FOLLOWUP] …` lines the live server emits.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stdout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hydrate Redis-persisted conversations then run "
                    "the follow-up scheduler tick once.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Hydrate + print a summary of due conversations without "
             "sending any DM.",
    )
    args = parser.parse_args(argv)

    _configure_logging()
    logger = logging.getLogger("tools.run_followup_tick")

    # Late imports — the logging config above must run first so the
    # service-level INFO lines are visible.
    from app.services import (
        conversation_service,
        followup_service,
        redis_state_service,
    )

    logger.info("[CLI] Redis enabled=%s url_configured=%s",
                redis_state_service.is_enabled(),
                bool(redis_state_service._redis_url()))

    loaded = conversation_service.hydrate_from_redis()
    logger.info("[CLI] hydrated conversations=%d", loaded)

    if args.dry_run:
        snapshot = conversation_service.get_all_conversations_snapshot()
        from app.agent.services.timestamps import now_tbilisi
        now = now_tbilisi()
        due_count = 0
        for conv in snapshot:
            try:
                if (conv.segment or "") != "PARENT":
                    continue
                if conv.followup_blocked_reason in followup_service._BLOCKED_REASONS:
                    continue
                last_bot = followup_service._parse_last_bot_message_at(
                    conv.last_bot_message_at,
                )
                if last_bot is None:
                    continue
                elapsed = now - last_bot
                cadence = followup_service._pick_due_cadence(
                    conv.followup_stage, elapsed,
                )
                if cadence is None:
                    continue
                due_count += 1
                logger.info(
                    "[CLI] due sender_masked=%s platform=%s stage=%s→%s "
                    "elapsed_seconds=%d",
                    (conv.sender_id[:6] + "***") if conv.sender_id else "",
                    conv.platform, conv.followup_stage or "(none)",
                    cadence["to_stage"], int(elapsed.total_seconds()),
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("[CLI] dry-run inspect failed: %s", exc)
        logger.info("[CLI] dry-run summary due=%d", due_count)
        return 0

    followup_service.check_and_send_followups()
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry
    sys.exit(main())
