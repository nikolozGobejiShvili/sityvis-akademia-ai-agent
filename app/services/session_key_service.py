"""Canonical conversation/session key helpers.

The public transport platform can differ from the identity namespace
we want for storage. Messenger traffic is still sent through the
``messenger`` transport branch, but a Facebook Page conversation is
keyed under ``facebook`` so page-scoped sessions do not collide.
"""

from __future__ import annotations

from typing import Any

UNKNOWN_KEY_PART = "unknown"


def _clean_part(value: str | None) -> str:
    return str(value or "").strip()


def canonical_platform_key(platform: str | None) -> str:
    value = _clean_part(platform).lower()
    if value in {"messenger", "facebook", "page"}:
        return "facebook"
    if value in {"instagram", "whatsapp"}:
        return value
    return value or UNKNOWN_KEY_PART


def canonical_session_key(
    platform: str | None,
    page_id: str | None,
    sender_id: str | None,
    *,
    require_page_id: bool = False,
) -> str:
    """Return ``platform:page_id:sender_id`` for conversation identity."""
    sender = _clean_part(sender_id)
    if not sender:
        raise ValueError("sender_id is required for a session key")

    page = _clean_part(page_id)
    if require_page_id and not page:
        raise ValueError("page_id is required for a session key")

    return f"{canonical_platform_key(platform)}:{page or UNKNOWN_KEY_PART}:{sender}"


def conversation_cache_key(
    conversation: Any | None = None,
    *,
    session_key: str | None = None,
    platform: str | None = None,
    page_id: str | None = None,
    sender_id: str | None = None,
) -> str:
    """Return the best available per-conversation cache key.

    Runtime conversations created through conversation_service carry the
    canonical session_key. Legacy direct tests sometimes construct model
    objects without it, so this helper derives a transitional canonical
    key when possible and falls back to raw sender_id only as a last resort.
    """
    explicit_session = _clean_part(session_key)
    if explicit_session:
        return explicit_session

    conversation_session = _clean_part(getattr(conversation, "session_key", None))
    if conversation_session:
        return conversation_session

    sender = _clean_part(sender_id) or _clean_part(getattr(conversation, "sender_id", None))
    if sender:
        try:
            return canonical_session_key(
                platform if platform is not None else getattr(conversation, "platform", None),
                page_id if page_id is not None else getattr(conversation, "page_id", None),
                sender,
                require_page_id=False,
            )
        except Exception:
            return sender

    return UNKNOWN_KEY_PART
