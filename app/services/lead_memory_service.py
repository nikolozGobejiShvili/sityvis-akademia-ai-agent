"""Durable per-lead memory (USE_LEAD_MEMORY). A compact, long-lived record of a
lead's identity facts, keyed by the canonical session key, so a returning lead's
child age / name / interests survive past the 8-day conversation TTL and seed a
new conversation. Wraps redis_state_service; never raises; no-op when Redis off
or the flag is off."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.models.lead import Lead
from app.services import redis_state_service, session_key_service

logger = logging.getLogger(__name__)

# Identity facts worth remembering across conversations. EXCLUDES per-booking /
# calendar state — that is conversation-scoped, not durable identity.
DURABLE_FIELDS: tuple[str, ...] = (
    "name", "phone", "child_age", "challenge", "deeper_concern",
    "desired_change", "event_interest", "preferred_event",
    "adult_age", "adult_target_relation", "adult_target_age",
)
LEAD_MEMORY_TTL_SECONDS: int = 31_536_000  # ~1 year (bounded, not infinite)
_PREFIX = "leadmem:"


def memory_key(session_key: str) -> str:
    return _PREFIX + (session_key or "")


def save(session_key: str, lead: Lead) -> None:
    if not session_key or lead is None or not redis_state_service.is_enabled():
        return
    try:
        record: dict[str, Any] = {
            f: getattr(lead, f) for f in DURABLE_FIELDS if getattr(lead, f, "")
        }
        if not record:
            return
        record["updated_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        redis_state_service.set_json(memory_key(session_key), record, LEAD_MEMORY_TTL_SECONDS)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[lead_memory] save failed for %s: %s", session_key, exc)


def load(session_key: str) -> dict | None:
    if not session_key or not redis_state_service.is_enabled():
        return None
    try:
        data = redis_state_service.get_json(memory_key(session_key))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[lead_memory] load failed for %s: %s", session_key, exc)
        return None


def delete(session_key: str) -> bool:
    if not session_key or not redis_state_service.is_enabled():
        return False
    try:
        return bool(redis_state_service.delete(memory_key(session_key)))
    except Exception:  # pragma: no cover - best-effort
        return False


def seed_lead(lead: Lead, memory: dict | None) -> None:
    """Fill ONLY empty Lead fields from memory (never overwrite a fact the
    current turn already established; each field maps to itself — no cross-
    assign)."""
    if lead is None or not memory:
        return
    for field in DURABLE_FIELDS:
        if getattr(lead, field, ""):
            continue
        value = memory.get(field)
        if value:
            setattr(lead, field, str(value))


def maybe_seed_new_lead(conversation) -> None:
    """Called by `_ensure_lead` right after it creates a fresh Lead. Flag-gated
    no-op: seeds the new lead from durable memory keyed by the conversation's
    session key. Never raises."""
    if not getattr(settings, "USE_LEAD_MEMORY", False):
        return
    lead = getattr(conversation, "lead", None)
    if lead is None:
        return
    try:
        key = session_key_service.conversation_cache_key(conversation)
        seed_lead(lead, load(key))
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[lead_memory] maybe_seed_new_lead failed: %s", exc)
