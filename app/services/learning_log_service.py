"""Phase 5 — bounded, human-gated learning: PII-masked, capped, durable
outcome-log store (USE_LEARNING). Mirrors ``lead_memory_service``'s
never-raises / Redis-graceful / flag-agnostic structure: this module does
NOT read any feature flag itself — callers (a later task) decide whether to
invoke ``log_turn`` at all. Wraps ``redis_state_service``; never raises;
no-op when Redis is disabled/unavailable.

The log is a single bounded JSON list under one Redis key (``LOG_KEY``),
capped at ``MAX_RECORDS`` entries with a ``LOG_TTL_SECONDS`` (~90 day)
rolling expiry. Every record's free-text fields are PII-masked (phone-like
digit runs) before being written, since this log may later be surfaced to
a human reviewer (Phase 5's "human-gated" approval step).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.services import redis_state_service

logger = logging.getLogger(__name__)

MAX_RECORDS: int = 500
LOG_TTL_SECONDS: int = 7_776_000  # ~90 days
LOG_KEY: str = "learninglog"

# Masks a run of digits (optionally interleaved with spaces/dashes) that
# totals 6 or more digits — enough to catch a Georgian phone number
# (9-digit local, or spaced/dashed groups like "555 12 34 56") without
# touching short numbers like ages or prices. Defensive/simple by design:
# a single \d[\d\s-]{5,}\d pattern, not a full phone-number grammar.
_PHONE_LIKE_RE = re.compile(r"\d[\d\s-]{5,}\d")
_PII_MASK = "[ტელეფონი]"


def _mask_pii(text: str) -> str:
    """Mask phone-like digit runs in ``text``. Never raises; non-str input
    is coerced to ``""``."""
    try:
        if not isinstance(text, str):
            return ""
        return _PHONE_LIKE_RE.sub(_PII_MASK, text)
    except Exception:  # pragma: no cover - defensive, regex is static
        return text if isinstance(text, str) else ""


def log_turn(record: dict) -> None:
    """Append a masked ``record`` to the bounded learning log.

    No-op when Redis is disabled/unavailable or ``record`` isn't a dict.
    Never raises."""
    if not redis_state_service.is_enabled():
        return
    try:
        if not isinstance(record, dict):
            return
        safe_record: dict[str, Any] = dict(record)
        if "question" in safe_record:
            safe_record["question"] = _mask_pii(safe_record.get("question", ""))
        if "answer_preview" in safe_record:
            safe_record["answer_preview"] = _mask_pii(safe_record.get("answer_preview", ""))

        existing = redis_state_service.get_json(LOG_KEY)
        records: list = list(existing) if isinstance(existing, list) else []
        records.append(safe_record)
        if len(records) > MAX_RECORDS:
            records = records[-MAX_RECORDS:]
        redis_state_service.set_json(LOG_KEY, records, LOG_TTL_SECONDS)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[learning_log] log_turn failed: %s", exc)


def recent(n: int = 50) -> list:
    """Return the last ``n`` records (most-recent-last order preserved),
    or ``[]`` on any failure / when Redis is disabled."""
    if not redis_state_service.is_enabled():
        return []
    try:
        existing = redis_state_service.get_json(LOG_KEY)
        records = existing if isinstance(existing, list) else []
        if n <= 0:
            return []
        return records[-n:]
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[learning_log] recent failed: %s", exc)
        return []


def reset() -> None:
    """Best-effort delete of the whole learning log. Never raises."""
    try:
        redis_state_service.delete(LOG_KEY)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[learning_log] reset failed: %s", exc)
