"""P3-B — Redis-backed persistence layer (safe-fallback).

This module is the ONLY place that talks to Redis directly. Everything
else (conversation_service, parent_tool_executor, webhook comment
handler) goes through the small API exposed here:

    is_enabled()         → bool   — feature flag + connection both up
    ping()               → bool   — round-trip health check
    get_json(key)        → dict | None
    set_json(key, value, ttl_seconds=None) → bool
    delete(key)          → bool
    exists(key)          → bool

Design rules (per the P3-B brief):

  * No crash on boot if Redis is unavailable. The connection is
    attempted lazily on first use and any error is logged + cached so
    subsequent calls return safe-failure defaults without retrying
    every call.
  * No password ever logged. We log only `url_configured=True/False`
    and `connected=True/False`.
  * Datetimes are caller-serialised to ISO strings. This module sees
    only JSON-safe dicts.
  * `ensure_ascii=False` so Georgian text round-trips.
  * If REDIS_URL is empty OR REDIS_ENABLED=false → the module is a
    pure no-op (get_json returns None, set_json returns False) and
    callers transparently fall back to their in-memory state.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


# Lazy connection state. The real ``redis.Redis`` instance lives in
# ``_client``; ``_connection_attempted`` is set after the first connect
# attempt (success OR failure) so we don't retry on every call.
_client: Any = None
_connection_attempted: bool = False
_connection_ok: bool = False


def _redis_url() -> str:
    return str(getattr(settings, "REDIS_URL", "") or "").strip()


def _redis_flag_enabled() -> bool:
    return bool(getattr(settings, "REDIS_ENABLED", False))


def _redis_ttl() -> int:
    try:
        return int(getattr(settings, "REDIS_TTL_SECONDS", 0) or 0)
    except (TypeError, ValueError):
        return 0


# Per-conversation / per-user session TTL (rolling 8-day window). Used by the
# conversation write-through and the per-user session guards (manager_notified,
# processed_comment) so a user's Redis memory expires ~8 days after their last
# activity; every write refreshes the expiry. Default 691200 = 8 days.
_CONVERSATION_TTL_DEFAULT = 691200


def _conversation_ttl() -> int:
    try:
        value = int(
            getattr(settings, "REDIS_CONVERSATION_TTL_SECONDS", _CONVERSATION_TTL_DEFAULT)
            or _CONVERSATION_TTL_DEFAULT
        )
    except (TypeError, ValueError):
        return _CONVERSATION_TTL_DEFAULT
    return value if value > 0 else _CONVERSATION_TTL_DEFAULT


def conversation_ttl_seconds() -> int:
    """Public accessor for the rolling per-conversation / per-user session TTL
    in seconds (``settings.REDIS_CONVERSATION_TTL_SECONDS``, default 8 days).

    Callers pass this to :func:`set_json` for any per-user key so it expires a
    fixed window after the user's last activity, refreshed on every write."""
    return _conversation_ttl()


def _url_configured() -> bool:
    return bool(_redis_url())


def _safe_url_log_value() -> str:
    """Never return the password — just whether the URL is set."""
    return "True" if _url_configured() else "False"


def is_enabled() -> bool:
    """Feature flag + successful connection. Callers gate Redis use on this."""
    if not _redis_flag_enabled():
        return False
    if not _url_configured():
        return False
    _ensure_client()
    return _connection_ok


def reset() -> None:
    """Clear cached connection state. Intended for tests."""
    global _client, _connection_attempted, _connection_ok
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _connection_attempted = False
    _connection_ok = False


def _ensure_client() -> Any:
    """Lazy-connect to Redis on first call. Never raises.

    On success sets ``_client`` and ``_connection_ok=True``. On any
    failure (missing redis library, bad URL, network error,
    authentication failure) logs a one-time warning and leaves
    ``_client=None``, ``_connection_ok=False`` — every subsequent
    public call then returns its safe-failure default.
    """
    global _client, _connection_attempted, _connection_ok

    if _connection_attempted:
        return _client

    _connection_attempted = True

    if not _redis_flag_enabled():
        logger.info("[redis] enabled=False url_configured=%s",
                    _safe_url_log_value())
        return None

    if not _url_configured():
        logger.info(
            "[redis] enabled=True url_configured=False — running in-memory only",
        )
        return None

    try:
        import redis  # type: ignore
    except ImportError as exc:
        logger.warning(
            "[redis] redis package not installed: %s — falling back to in-memory state",
            exc,
        )
        return None

    try:
        client = redis.Redis.from_url(
            _redis_url(),
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        # Round-trip the connection so we know it actually works
        # before any caller depends on it.
        client.ping()
    except Exception as exc:
        logger.warning(
            "[redis] unavailable; falling back to in-memory state "
            "(url_configured=%s error=%s)",
            _safe_url_log_value(), exc,
        )
        return None

    _client = client
    _connection_ok = True
    logger.info(
        "[redis] enabled=True url_configured=%s connected=True",
        _safe_url_log_value(),
    )
    return _client


def ping() -> bool:
    if not is_enabled():
        return False
    try:
        return bool(_client and _client.ping())
    except Exception as exc:
        logger.warning("[redis] ping failed: %s", exc)
        return False


def get_json(key: str) -> dict | None:
    """Return the JSON-decoded value or None on miss/error."""
    if not is_enabled():
        return None
    try:
        raw = _client.get(key)
    except Exception as exc:
        logger.warning("[redis] get_json key=%s failed: %s", key, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning(
            "[redis] get_json key=%s — invalid JSON, discarding: %s",
            key, exc,
        )
        return None


def set_json(
    key: str,
    value: dict,
    ttl_seconds: int | None = None,
    *,
    ttl: int | None = None,
) -> bool:
    """Write a JSON-safe value with an optional per-call TTL.

    ``ttl_seconds`` — when provided (and > 0) the key is written with a Redis
    ``EX`` expiry, which is REFRESHED on every write (a rolling window). When
    ``None`` the behaviour is unchanged: it falls back to the module default
    ``settings.REDIS_TTL_SECONDS``. ``ttl`` is a backward-compatible keyword
    alias for ``ttl_seconds`` (kept for existing callers); ``ttl_seconds``
    wins when both are given.

    Returns True on success, False on any failure. Never raises.
    """
    if not is_enabled():
        return False
    if ttl_seconds is None:
        ttl_seconds = ttl
    if ttl_seconds is None:
        ttl_seconds = _redis_ttl()
    try:
        payload = json.dumps(value, ensure_ascii=False, default=str)
    except Exception as exc:
        logger.warning(
            "[redis] set_json key=%s — value not JSON-serialisable: %s",
            key, exc,
        )
        return False
    try:
        if ttl_seconds and ttl_seconds > 0:
            _client.set(key, payload, ex=ttl_seconds)
        else:
            _client.set(key, payload)
        return True
    except Exception as exc:
        logger.warning("[redis] set_json key=%s failed: %s", key, exc)
        return False


def delete(key: str) -> bool:
    if not is_enabled():
        return False
    try:
        _client.delete(key)
        return True
    except Exception as exc:
        logger.warning("[redis] delete key=%s failed: %s", key, exc)
        return False


def exists(key: str) -> bool:
    if not is_enabled():
        return False
    try:
        return bool(_client.exists(key))
    except Exception as exc:
        logger.warning("[redis] exists key=%s failed: %s", key, exc)
        return False


def scan_keys(pattern: str, count: int = 200) -> list[str]:
    """Return every Redis key matching `pattern` using non-blocking SCAN.

    Follow-up Live-Test Hydrate Patch (2026-06-06). The follow-up
    scheduler runs against an in-memory snapshot; a one-off CLI
    invocation has no shared memory with the live server. This helper
    enumerates known conversation keys (`conversation:*`) without
    blocking the live server (SCAN, not KEYS — KEYS holds the Redis
    main thread for every match and is forbidden in production).

    Returns ``[]`` when Redis is disabled / unavailable. Never raises.
    """
    if not is_enabled():
        return []
    out: list[str] = []
    try:
        cursor = 0
        while True:
            cursor, batch = _client.scan(
                cursor=cursor, match=pattern, count=count,
            )
            for key in batch or []:
                out.append(key)
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning(
            "[redis] scan_keys pattern=%s failed: %s — partial result %d",
            pattern, exc, len(out),
        )
    return out


def log_startup_status() -> None:
    """Called once from app.main at boot — emits the expected log lines.

    Output examples:
      [redis] enabled=True url_configured=True
      [redis] connected=True
      OR
      [redis] unavailable; falling back to in-memory state
    """
    if not _redis_flag_enabled():
        logger.info(
            "[redis] enabled=False url_configured=%s",
            _safe_url_log_value(),
        )
        return
    if not _url_configured():
        logger.info("[redis] enabled=True url_configured=False — running in-memory only")
        return
    logger.info(
        "[redis] enabled=True url_configured=%s",
        _safe_url_log_value(),
    )
    if is_enabled():
        logger.info("[redis] connected=True")
    else:
        logger.warning("[redis] unavailable; falling back to in-memory state")
