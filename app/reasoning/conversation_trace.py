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

import hashlib
import json
import logging
import re

from app.reasoning.route_decision import RouteDecision
from app.services.session_key_service import canonical_session_key

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


def _mask_identifier(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "?"
    if len(raw) <= 4:
        return raw[:1] + "***"
    if len(raw) <= 8:
        return raw[:2] + "***" + raw[-1:]
    return raw[:4] + "***" + raw[-2:]


def _mask_session_key(session_key: str | None) -> str:
    raw = str(session_key or "").strip()
    if not raw:
        return "?"
    parts = raw.split(":")
    if len(parts) == 3:
        return f"{parts[0]}:{_mask_identifier(parts[1])}:{_mask_identifier(parts[2])}"
    return _mask_identifier(raw)


def _session_hash(session_key: str | None) -> str:
    raw = str(session_key or "").strip()
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def begin(
    sender_id: str,
    text: str,
    platform: str,
    page_id: str = "",
    session_key: str = "",
) -> None:
    """Start a trace for an inbound turn. No-op when disabled."""
    global _turn
    if not _enabled():
        _turn = None
        return
    sid = sender_id or ""
    session = str(session_key or "").strip()
    if not session:
        try:
            session = canonical_session_key(
                platform, page_id, sender_id, require_page_id=False,
            )
        except Exception:
            session = ""
    _turn = {
        "sender": _mask_identifier(sid),
        "platform": platform,
        "page": _mask_identifier(page_id) if page_id else "",
        "session": _mask_session_key(session),
        "session_hash": _session_hash(session),
        "text": (text or "")[:200],
        "side_effects": [],
        "route_decision": RouteDecision.from_turn(
            session_key=session,
            platform=platform,
            page_id=page_id,
            sender_id=sid,
        ).to_trace_dict(),
    }


def set(**kwargs) -> None:  # noqa: A003 — deliberate compact API
    if _turn is not None:
        _turn.update(kwargs)


def set_route_decision(**kwargs) -> None:
    """Merge safe RouteDecision fields into the current trace block.

    Observability must never affect reply behavior, so malformed updates are
    ignored instead of raising.
    """
    if _turn is None:
        return
    try:
        current = RouteDecision.from_trace_dict(_turn.get("route_decision"))
        _turn["route_decision"] = current.with_updates(**kwargs).to_trace_dict()
    except Exception:
        return


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
