"""Adult Event Subscription Service (2026-06-08).

A standalone service that owns the operator-facing "subscribe to
future adult-event broadcasts" feature. Distinct from the 24/72/168h
PARENT follow-up scheduler — that drives unconditional cadence per
conversation; this one only ever fires when the operator activates a
new adult event AND the user explicitly opted in.

This module is the orchestration layer between:

  * `sheets_service` — the `events` tab CRUD (one row per
    (platform, sender_id) subscriber).
  * `adult_tool_executor._subscribe_to_adult_event_updates` — the
    LLM-facing tool surface.
  * `adult_event_broadcast_service` — the fan-out path that reads
    the subscribers and sends private DMs.

Public API:

  * `is_subscription_consent_phrase(text) -> bool`
  * `is_unsubscribe_phrase(text) -> bool`
  * `is_already_subscribed(platform, sender_id) -> bool`
  * `subscribe(...) -> dict` (returns a structured result the LLM /
    tool executor surfaces to the user)
  * `unsubscribe(platform, sender_id) -> dict`

Privacy: callers must never log raw phones. The Sheets layer masks
phones with `_mask_phone`; this service mirrors that for its own
logs.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phrase detectors
# ---------------------------------------------------------------------------


# Closed-set Georgian + English subscription-consent phrases. Substring
# match on casefolded text. Kept conservative — the LLM is the final
# arbiter; this list catches the most common live phrasings so the
# stochastic LLM never misses a clear "yes".
_CONSENT_PHRASES: tuple[str, ...] = (
    # Georgian — explicit yes / send-me
    "კი, გამომიგზავნეთ",
    "კი გამომიგზავნეთ",
    "კი, შემატყობინეთ",
    "კი შემატყობინეთ",
    "კი, მინდა",
    "კი მინდა",
    "კი, დამამატეთ",
    "კი დამამატეთ",
    "კი",
    "დიახ",
    "მინდა",
    "მინდა რომ გამომიგზავნოთ",
    "გამომიგზავნეთ",
    "შემატყობინეთ",
    "დამამატეთ",
    "მომწერეთ როცა ახალი",
    "მსგავსი ღონისძიებების მიღება",
    "მსგავსი ღონისძიებების მიღება მინდა",
    # English
    "yes",
    "ok",
    "okay",
    "sure",
    "send me",
    "subscribe",
)


_NEGATIVE_PHRASES: tuple[str, ...] = (
    "არა",
    "არ მინდა",
    "არ გამომიგზავნოთ",
    "ჯერ არა",
    "მოგვიანებით",
    "არ შემატყობინოთ",
    "არ მსურს",
    "no",
    "not now",
    "later",
)


# Unsubscribe phrases. Detected BEFORE the LLM in the ADULT engine; if
# any matches, the deterministic unsubscribe path fires.
_UNSUBSCRIBE_PHRASES: tuple[str, ...] = (
    "აღარ გამომიგზავნოთ",
    "აღარ მინდა შეტყობინებები",
    "აღარ მინდა ღონისძიებები",
    "აღარ მინდა შეტყობინება",
    "აღარ მომწეროთ",
    "გამთიშეთ",
    "unsubscribe",
    "stop",
)


def _casefold(text: str | None) -> str:
    return (text or "").casefold().strip()


def is_subscription_consent_phrase(text: str | None) -> bool:
    """True when the user message looks like an explicit subscription
    consent. Negative phrases ("არ მინდა" / "არა, არ მინდა") are
    checked first so „არა" doesn't accidentally match „კი" via
    substring overlap.
    """
    lowered = _casefold(text)
    if not lowered:
        return False
    # Negative wins over positive — "არ მინდა" must not trigger
    # subscribe just because "მინდა" appears as a substring.
    for neg in _NEGATIVE_PHRASES:
        if neg in lowered:
            return False
    return any(phrase in lowered for phrase in _CONSENT_PHRASES)


def is_negative_subscription_phrase(text: str | None) -> bool:
    lowered = _casefold(text)
    if not lowered:
        return False
    return any(neg in lowered for neg in _NEGATIVE_PHRASES)


def is_unsubscribe_phrase(text: str | None) -> bool:
    lowered = _casefold(text)
    if not lowered:
        return False
    return any(phrase in lowered for phrase in _UNSUBSCRIBE_PHRASES)


# ---------------------------------------------------------------------------
# Lookups + subscribe / unsubscribe
# ---------------------------------------------------------------------------


def is_already_subscribed(platform: str, sender_id: str) -> bool:
    """Lazy import to avoid pulling Sheets into modules that don't need
    it. Returns False on any failure — the caller will simply re-ask
    the consent question, which is harmless."""
    try:
        from app.services import sheets_service
        record = sheets_service.get_event_subscriber(platform, sender_id)
        if not record:
            return False
        return record.get("status") == "subscribed" and bool(
            record.get("consent"),
        )
    except Exception as exc:
        logger.warning(
            "[ADULT_SUBSCRIPTION] is_already_subscribed lookup failed: %s",
            exc,
        )
        return False


def _validate_phone(raw: str | None) -> str:
    """Reuse the PARENT booking phone parser so behaviour is identical
    across the two flows. Returns the normalised 9-digit phone, or ""
    when nothing valid is found."""
    if not raw:
        return ""
    try:
        from app.flows import parent_flow
        _name, phone = parent_flow._parse_name_phone(str(raw))
        return phone or ""
    except Exception:
        return ""


def subscribe(
    *,
    platform: str,
    sender_id: str,
    name: str | None,
    phone: str | None,
    source_event_id: str | None = None,
    source_event_title: str | None = None,
    source_event_link: str | None = None,
    age: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Subscribe a user to adult-event broadcasts.

    Returns a structured result the LLM / tool executor surfaces:

      * ``{"success": True, "status": "subscribed"}`` on save success.
      * ``{"success": False, "reason": "missing_name"}`` — phone OK,
        name still required.
      * ``{"success": False, "reason": "missing_phone"}`` — name OK or
        not required, phone still required.
      * ``{"success": False, "reason": "missing_name_and_phone"}`` —
        both required.
      * ``{"success": False, "reason": "sheets_save_failed",
        "detail": <reason>}`` — Sheets write failed; caller must NOT
        claim success.
    """
    from datetime import datetime, timezone
    from app.services import sheets_service

    platform_clean = (platform or "").strip()
    sender_clean = (sender_id or "").strip()
    if not platform_clean or not sender_clean:
        return {"success": False, "reason": "missing_identity"}

    name_clean = (name or "").strip()
    phone_clean = _validate_phone(phone) if phone else ""

    if not name_clean and not phone_clean:
        return {"success": False, "reason": "missing_name_and_phone"}
    if not name_clean:
        return {"success": False, "reason": "missing_name"}
    if not phone_clean:
        return {"success": False, "reason": "missing_phone"}

    # Stamp consent_at in Tbilisi-local time so the row Times line up
    # with the rest of the Sheets timestamps.
    try:
        consent_at = sheets_service._datetime_text(
            sheets_service.now_tbilisi(),
        )
    except Exception:
        # Defensive — never block the subscribe on a timestamp helper.
        consent_at = datetime.now(timezone.utc).isoformat()

    payload = {
        "platform": platform_clean,
        "sender_id": sender_clean,
        "name": name_clean,
        "phone": phone_clean,
        "status": "subscribed",
        "consent": True,
        "consent_at": consent_at,
        "source_event_id": (source_event_id or "").strip(),
        "source_event_title": (source_event_title or "").strip(),
        "source_event_link": (source_event_link or "").strip(),
        "age": (age or "").strip(),
        "notes": (notes or "").strip(),
    }

    ok, reason = sheets_service.save_event_subscriber(payload)
    if not ok:
        return {
            "success": False,
            "reason": "sheets_save_failed",
            "detail": reason,
        }
    return {"success": True, "status": "subscribed"}


def unsubscribe(platform: str, sender_id: str) -> dict[str, Any]:
    """Mirror of `subscribe` for the opt-out path.

    Returns:
      * ``{"success": True, "status": "unsubscribed"}`` on success.
      * ``{"success": False, "reason": "not_subscribed"}`` when no
        row exists for (platform, sender_id).
      * ``{"success": False, "reason": "sheets_failure",
        "detail": <reason>}`` on Sheets failure.
    """
    from app.services import sheets_service

    ok, reason = sheets_service.unsubscribe_event_subscriber(
        platform, sender_id,
    )
    if ok:
        return {"success": True, "status": "unsubscribed"}
    if reason == "not_subscribed":
        return {"success": False, "reason": "not_subscribed"}
    return {
        "success": False,
        "reason": "sheets_failure",
        "detail": reason,
    }
