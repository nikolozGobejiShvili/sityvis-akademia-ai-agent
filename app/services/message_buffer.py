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
from app.services.session_key_service import canonical_session_key

logger = logging.getLogger(__name__)

# Per-session pending state
_pending_messages: dict[str, list[str]] = defaultdict(list)
_pending_tasks: dict[str, asyncio.Task] = {}
_buffer_started_at: dict[str, float] = {}
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

OnReady = Callable[[str, str, str, str], Awaitable[None]]


async def buffer_message(
    sender_id: str,
    message: str,
    platform: str,
    on_ready: OnReady,
    page_id: str = "",
) -> None:
    """Append a message to the per-session buffer and restart debounce.

    The callback `on_ready(sender_id, combined_text, platform, page_id)` is
    invoked once after debounce or MAX_WAIT_SECONDS elapses.
    """
    buffer_key = canonical_session_key(platform, page_id, sender_id)
    async with _locks[buffer_key]:
        _pending_messages[buffer_key].append(message)
        if buffer_key not in _buffer_started_at:
            _buffer_started_at[buffer_key] = time.time()

        existing = _pending_tasks.get(buffer_key)
        if existing and not existing.done():
            existing.cancel()
            logger.debug(
                "[message_buffer] Cancelled previous timer for sender=%s "
                "(buffer now has %d fragments)",
                buffer_key, len(_pending_messages[buffer_key]),
            )

        task = asyncio.create_task(
            _flush_after_delay(buffer_key, sender_id, platform, page_id, on_ready),
            name=f"buffer-flush-{buffer_key}",
        )
        _pending_tasks[buffer_key] = task
        logger.info(
            "[message_buffer] Buffered fragment for sender=%s (buffer_len=%d, debounce=%ds)",
            buffer_key, len(_pending_messages[buffer_key]), settings.DEBOUNCE_SECONDS,
        )


async def _flush_after_delay(
    buffer_key: str,
    sender_id: str,
    platform: str,
    page_id: str,
    on_ready: OnReady,
) -> None:
    debounce = max(1, settings.DEBOUNCE_SECONDS)
    max_wait = max(debounce, settings.MAX_WAIT_SECONDS)

    try:
        started_at = _buffer_started_at.get(buffer_key, time.time())
        elapsed = time.time() - started_at
        remaining_until_max = max(0.0, max_wait - elapsed)
        wait_time = min(float(debounce), remaining_until_max)

        if wait_time <= 0:
            logger.info(
                "[message_buffer] MAX_WAIT reached for sender=%s — flushing immediately",
                buffer_key,
            )
        else:
            await asyncio.sleep(wait_time)
    except asyncio.CancelledError:
        return

    async with _locks[buffer_key]:
        messages = _pending_messages.pop(buffer_key, [])
        _buffer_started_at.pop(buffer_key, None)
        _pending_tasks.pop(buffer_key, None)

    if not messages:
        return

    combined = " ".join(msg.strip() for msg in messages if msg and msg.strip())
    logger.info(
        "[message_buffer] Flushing for sender=%s — %d fragments → %r",
        buffer_key, len(messages), combined[:120],
    )

    try:
        await on_ready(sender_id, combined, platform, page_id)
    except Exception as exc:
        logger.exception(
            "[message_buffer] on_ready callback raised for sender=%s: %s", sender_id, exc,
        )
