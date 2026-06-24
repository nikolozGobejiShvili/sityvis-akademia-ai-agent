"""Per-turn diagnostic trace (Phase 3, 2026-06-24). Observability ONLY — no
behaviour change.

When `settings.CONVERSATION_TRACE_DEBUG` is True, the handler chain accumulates a
single compact structured block per inbound turn and logs it once at the end
(`[trace] {...}`). Every function is a safe no-op when the flag is off and never
raises. Phones are masked to the last 3 digits; tokens/secrets are never
recorded (only boolean presence / names).

Used by: conversation_service (begin/route/final/emit), parent_flow (planner /
handler / validator), adult flow + LLM engines (route / answered-by / prompt),
notification/calendar/sheets (side effects).
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_turn: dict | None = None
_HISTORY: list[dict] = []
_MAX_HISTORY = 50


def _enabled() -> bool:
    try:
        from app import config
        return bool(getattr(config.settings, "CONVERSATION_TRACE_DEBUG", False))
    except Exception:  # pragma: no cover — defensive
        return False


def mask_phone(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    return ("***" + digits[-3:]) if len(digits) >= 3 else ("***" if digits else "")


def begin(sender_id: str, text: str, platform: str) -> None:
    """Start a trace for an inbound turn. No-op when disabled."""
    global _turn
    if not _enabled():
        _turn = None
        return
    sid = sender_id or ""
    _turn = {
        "sender": (sid[:4] + "***") if sid else "?",
        "platform": platform,
        "text": (text or "")[:200],
        "side_effects": [],
    }


def set(**kwargs) -> None:  # noqa: A003 — deliberate compact API
    if _turn is not None:
        _turn.update(kwargs)


def note_side_effect(name: str) -> None:
    if _turn is not None:
        _turn.setdefault("side_effects", []).append(name)


def active() -> bool:
    """True when a trace turn is being recorded (flag on)."""
    return _turn is not None


def emit() -> None:
    """Log + archive the accumulated block. No-op when disabled."""
    global _turn
    if _turn is None:
        return
    block, _turn = _turn, None
    _HISTORY.append(block)
    if len(_HISTORY) > _MAX_HISTORY:
        del _HISTORY[0]
    try:
        logger.info("[trace] %s", json.dumps(block, ensure_ascii=False, default=str))
    except Exception:  # pragma: no cover — logging must never break a reply
        logger.info("[trace] %r", block)


def history() -> list[dict]:
    return list(_HISTORY)


def reset_history() -> None:
    _HISTORY.clear()
