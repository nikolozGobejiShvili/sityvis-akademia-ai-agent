"""Adult Event Broadcast Service (2026-06-08).

Fan-out path that sends „ახალი ღონისძიება დაემატა" private DMs to
operator-consented subscribers when a new adult event is activated.

Distinct from the PARENT follow-up scheduler — this one is
operator-triggered (Admin Panel checkbox or manual button), reads
the Sheets `events` tab for subscribers, and respects:

  * status == "subscribed"
  * consent == TRUE
  * platform supported (currently messenger / instagram / facebook —
    same vocabulary as `messenger_service.send_message`)
  * duplicate prevention via the per-row `Notified Event IDs` cell

Kill-switch gated. Missing link blocks the entire broadcast (caller
gets a structured reason — the operator sees a clear UI message).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


_SUPPORTED_PLATFORMS: frozenset[str] = frozenset({
    "messenger", "instagram", "facebook",
})


def _format_event_price(event: dict) -> str:
    """Mirror of `comment_service._format_event_price` — kept inline
    so this module has no cross-service dependency for a tiny helper."""
    price_text = (event.get("price_text") or "").strip()
    if price_text:
        marker_present = (
            "ლარი" in price_text.casefold()
            or "gel" in price_text.casefold()
            or "$" in price_text
            or "€" in price_text
        )
        if marker_present:
            return price_text
        return f"{price_text} ლარი"
    price_gel = event.get("price_gel")
    if isinstance(price_gel, int) and price_gel > 0:
        return f"{price_gel} ლარი"
    return ""


def build_broadcast_message(event: dict) -> str:
    """Render the full new-event broadcast message.

    Includes only the operator-saved fields that are non-blank. Never
    fabricates seat availability, sold-out status, or a fake link.
    """
    title = (event.get("title") or "").strip()
    if not title:
        return ""

    lines: list[str] = [
        "ახალი ზრდასრულთა ღონისძიება დაემატა:",
        "",
        title,
        "",
    ]

    date_text = (event.get("date_text") or "").strip()
    if date_text:
        lines.append(f"თარიღი: {date_text}")
    location = (event.get("location") or "").strip()
    if location:
        lines.append(f"ლოკაცია: {location}")
    price = _format_event_price(event)
    if price:
        lines.append(f"ფასი: {price}")

    description = (event.get("description") or "").strip()
    if description:
        lines.append("")
        lines.append("აღწერა:")
        lines.append(description)

    link = (
        (event.get("reservation_url") or "").strip()
        or (event.get("payment_terms") or "").strip()
    )
    # Caller is supposed to gate on link presence — but if the message
    # builder is called directly we still emit the link section so the
    # output is self-consistent.
    if link:
        lines.append("")
        lines.append("ბილეთის ბმული:")
        lines.append(link)

    lines.append("")
    lines.append(
        "თუ აღარ გსურთ მსგავსი შეტყობინებების მიღება, "
        "მოგვწერეთ: აღარ გამომიგზავნოთ.",
    )
    return "\n".join(lines).strip()


def broadcast_event(
    event_id_or_event: str | dict, *, source: str = "unknown",
) -> dict[str, Any]:
    """Fan out a new-event broadcast to consented subscribers.

    Broadcast Safety Patch (2026-06-11): when
    ``settings.LIVE_BROADCAST_ENABLED`` is False (the DEFAULT), this runs
    in DRY-RUN mode — it resolves the event and counts candidates but
    NEVER calls ``messenger_service.send_message`` and NEVER marks
    subscribers notified. ``source`` (``admin_manual`` / ``after_save`` /
    ``test`` / ``script`` / ``unknown``) is logged so every broadcast is
    attributable.

    Accepts either an event id (looked up via
    `admin_config_service.find_adult_event`) or a fully-built event
    dict. Returns a structured result the operator UI surfaces:

        {
            "success": True | False,
            "reason": "ok" | "missing_event" | "inactive" | "missing_link"
                      | "kill_switch_disabled",
            "event_id": "...",
            "event_title": "...",
            "sent": <int>,
            "skipped_duplicate": <int>,
            "skipped_no_consent": <int>,
            "skipped_platform": <int>,
            "failed": <int>,
            "total_candidates": <int>,
        }

    Never raises. A per-subscriber send failure does NOT block other
    subscribers — counters track each branch separately.
    """
    from app.config import settings
    from app.services import (
        admin_config_service,
        kill_switch,
        messenger_service,
        sheets_service,
    )

    live = bool(getattr(settings, "LIVE_BROADCAST_ENABLED", False))
    result: dict[str, Any] = {
        "success": False,
        "reason": "",
        "event_id": "",
        "event_title": "",
        "sent": 0,
        "skipped_duplicate": 0,
        "skipped_no_consent": 0,
        "skipped_platform": 0,
        "failed": 0,
        "total_candidates": 0,
        "dry_run": not live,
        "source": source,
    }
    logger.info(
        "[ADULT_BROADCAST] start source=%s live=%s (dry_run=%s)",
        source, live, not live,
    )

    if not kill_switch.is_agent_enabled():
        kill_switch.log_disabled_skip(context="adult_broadcast")
        result["reason"] = "kill_switch_disabled"
        return result

    # Resolve the event. Use `get_adult_events()` directly so we can
    # detect inactive events too — `find_adult_event` filters them
    # out via `find_adult_events_matching`'s active-only pool, which
    # would make this branch report "missing_event" for an inactive
    # event id (the operator needs the explicit "inactive" reason).
    if isinstance(event_id_or_event, dict):
        event = event_id_or_event
    else:
        eid = str(event_id_or_event).strip()
        event = None
        try:
            for candidate in admin_config_service.get_adult_events():
                if candidate.get("id") == eid:
                    event = candidate
                    break
        except Exception as exc:
            logger.warning(
                "[ADULT_BROADCAST] event lookup raised: %s", exc,
            )
            event = None
        if not event:
            result["reason"] = "missing_event"
            result["event_id"] = eid
            return result

    result["event_id"] = (event.get("id") or "").strip()
    result["event_title"] = (event.get("title") or "").strip()

    if not bool(event.get("active")):
        result["reason"] = "inactive"
        return result

    # Adult Event Date Filter (2026-06-10): never broadcast a PAST event —
    # neither via the Admin Panel manual/after-save button nor the
    # subscription „new event" fan-out. The operator sees an explicit
    # reason on the results page.
    try:
        if admin_config_service.is_adult_event_past(event):
            logger.info(
                "[ADULT_BROADCAST] blocked past event id=%s title=%r",
                result["event_id"], result["event_title"],
            )
            result["reason"] = "event_past"
            return result
    except Exception as exc:
        logger.warning("[ADULT_BROADCAST] past-event check raised: %s", exc)

    link = (
        (event.get("reservation_url") or "").strip()
        or (event.get("payment_terms") or "").strip()
    )
    if not link:
        result["reason"] = "missing_link"
        return result

    message = build_broadcast_message(event)
    if not message:
        # Defensive — shouldn't happen if event has title + link.
        result["reason"] = "empty_message"
        return result

    try:
        subscribers = sheets_service.list_event_subscribers(
            status="subscribed", consent_required=True,
        )
    except Exception as exc:
        logger.warning(
            "[ADULT_BROADCAST] subscriber list failed: %s", exc,
        )
        result["reason"] = "subscriber_list_failed"
        return result

    result["total_candidates"] = len(subscribers)

    for sub in subscribers:
        platform = (sub.get("platform") or "").strip().lower()
        sender_id = (sub.get("sender_id") or "").strip()
        if platform not in _SUPPORTED_PLATFORMS:
            result["skipped_platform"] += 1
            continue
        if not sender_id:
            result["skipped_platform"] += 1
            continue
        # Duplicate-prevention shortcut — the per-subscriber mark
        # function ALSO checks this; we re-check here so we don't
        # waste an outbound network call.
        if result["event_id"] in (sub.get("notified_event_ids") or []):
            result["skipped_duplicate"] += 1
            continue
        # Broadcast Safety Patch (2026-06-11): DRY-RUN — never send a real
        # DM and never mark notified unless LIVE_BROADCAST_ENABLED is set.
        # This is the hard safety net for tests / scripts / dev machines.
        if not live:
            result.setdefault("dry_run_would_send", 0)
            result["dry_run_would_send"] += 1
            logger.info(
                "[ADULT_BROADCAST] DRY-RUN would send event=%s platform=%s "
                "(no real DM; set LIVE_BROADCAST_ENABLED=true to enable)",
                result["event_id"], platform,
            )
            continue
        try:
            sent_ok = messenger_service.send_message(
                sender_id, platform, message,
            )
        except Exception as exc:
            logger.warning(
                "[ADULT_BROADCAST] send raised event=%s: %s",
                result["event_id"], exc,
            )
            sent_ok = False
        if not sent_ok:
            result["failed"] += 1
            continue
        try:
            mark_ok, mark_reason = (
                sheets_service.mark_event_subscriber_notified(
                    platform, sender_id, result["event_id"],
                )
            )
        except Exception as exc:
            logger.warning(
                "[ADULT_BROADCAST] mark_notified raised event=%s: %s",
                result["event_id"], exc,
            )
            mark_ok, mark_reason = False, "exception"
        if mark_ok:
            result["sent"] += 1
        elif mark_reason == "duplicate":
            # Race: another tick beat us to it. Treat as duplicate, not
            # a fresh send.
            result["skipped_duplicate"] += 1
        else:
            # The DM went out but Sheets failed to record it — counts
            # as sent (the user got the message) but log warning.
            logger.warning(
                "[ADULT_BROADCAST] mark_notified failed reason=%s "
                "event=%s — DM was delivered, CRM out-of-sync",
                mark_reason, result["event_id"],
            )
            result["sent"] += 1

    result["success"] = True
    result["reason"] = "ok"
    logger.info(
        "[ADULT_BROADCAST] complete event=%s title=%r candidates=%d "
        "sent=%d skipped_duplicate=%d skipped_platform=%d "
        "skipped_no_consent=%d failed=%d",
        result["event_id"], result["event_title"],
        result["total_candidates"], result["sent"],
        result["skipped_duplicate"], result["skipped_platform"],
        result["skipped_no_consent"], result["failed"],
    )
    return result
