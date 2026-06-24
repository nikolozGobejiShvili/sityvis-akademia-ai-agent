"""Message debounce/batching layer.

Many users in messaging apps type in fragments — "გამარჯობა" / "ბანაკი" / "ფასი".
Without batching, the agent responds 3 separate times. With batching, we wait
DEBOUNCE_SECONDS after each message; if no new message arrives, we join the
buffered fragments into one combined message and process it as a single turn.

Edge cases handled:
  • New message resets the debounce timer (typical case)
  • MAX_WAIT_SECONDS cap so a chronically-typing user still gets a reply
  • Independent buffers per sender_id (no cross-user interference)
  • Cancellation safety: previous timer task is cancelled on each new message
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Awaitable, Callable

from app.config import settings

logger = logging.getLogger(__name__)

# Per-sender pending state
_pending_messages: dict[str, list[str]] = defaultdict(list)
_pending_tasks: dict[str, asyncio.Task] = {}
_buffer_started_at: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

OnReady = Callable[[str, str, str], Awaitable[None]]


async def buffer_message(
    sender_id: str,
    message: str,
    platform: str,
    on_ready: OnReady,
) -> None:
    """Append a message to the per-sender buffer and (re)start the debounce timer.

    The callback `on_ready(sender_id, combined_text, platform)` is invoked
    exactly once after the debounce window closes or MAX_WAIT_SECONDS elapses.
    """
    async with _locks[sender_id]:
        _pending_messages[sender_id].append(message)
        if sender_id not in _buffer_started_at:
            _buffer_started_at[sender_id] = time.time()

        existing = _pending_tasks.get(sender_id)
        if existing and not existing.done():
            existing.cancel()
            logger.debug(
                "[message_buffer] Cancelled previous timer for sender=%s "
                "(buffer now has %d fragments)",
                sender_id, len(_pending_messages[sender_id]),
            )

        task = asyncio.create_task(
            _flush_after_delay(sender_id, platform, on_ready),
            name=f"buffer-flush-{sender_id}",
        )
        _pending_tasks[sender_id] = task
        logger.info(
            "[message_buffer] Buffered fragment for sender=%s (buffer_len=%d, debounce=%ds)",
            sender_id, len(_pending_messages[sender_id]), settings.DEBOUNCE_SECONDS,
        )


async def _flush_after_delay(
    sender_id: str,
    platform: str,
    on_ready: OnReady,
) -> None:
    debounce = max(1, settings.DEBOUNCE_SECONDS)
    max_wait = max(debounce, settings.MAX_WAIT_SECONDS)

    try:
        started_at = _buffer_started_at.get(sender_id, time.time())
        elapsed = time.time() - started_at
        remaining_until_max = max(0.0, max_wait - elapsed)
        wait_time = min(float(debounce), remaining_until_max)

        if wait_time <= 0:
            logger.info(
                "[message_buffer] MAX_WAIT reached for sender=%s — flushing immediately",
                sender_id,
            )
        else:
            await asyncio.sleep(wait_time)
    except asyncio.CancelledError:
        return

    async with _locks[sender_id]:
        messages = _pending_messages.pop(sender_id, [])
        _buffer_started_at.pop(sender_id, None)
        _pending_tasks.pop(sender_id, None)

    if not messages:
        return

    combined = " ".join(msg.strip() for msg in messages if msg and msg.strip())
    logger.info(
        "[message_buffer] Flushing for sender=%s — %d fragments → %r",
        sender_id, len(messages), combined[:120],
    )

    try:
        await on_ready(sender_id, combined, platform)
    except Exception as exc:
        logger.exception(
            "[message_buffer] on_ready callback raised for sender=%s: %s", sender_id, exc,
        )
