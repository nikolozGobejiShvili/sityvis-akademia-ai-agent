"""Follow-up scheduler — Conversation-marker driven.

History (Follow-up Scheduler Patch, 2026-05-30):

The legacy `check_and_send_followups` read cold-lead rows from Google
Sheets and sent a one-shot PARENT/ADULT reminder. That path never
respected the per-Conversation follow-up markers that PATCH 3
captures on every turn (`last_bot_message_at`, `followup_stage`,
`followup_blocked_reason`, `last_meaningful_interest`,
`stopped_after`), so a parent who declined / booked / was handed off
to a manager could still be pinged again. It also defaulted the send
platform to the lead's Sheets row — which is rarely populated for
in-flight conversations — so the actual delivery channel was often
guessed.

This module is now driven by the Conversation snapshot. The cadence
(24h → 72h → 168h) lives in `app/agent/knowledge/followup_strategy.yaml`.
Stage names match that file's keys: ``first_24h`` → ``second_3d`` →
``third_7d`` → ``stopped``. After the third stage the conversation's
``followup_blocked_reason`` is set to ``followup_exhausted`` so a
future patch (Sentry / error monitoring) can surface this as a final
state rather than a silent stop.

Platform routing: Instagram DM is the production-tested channel; the
Conversation's `platform` field is preserved verbatim from the
webhook (`instagram` / `messenger` / `whatsapp`). The scheduler
delegates to `messenger_service.send_message` which already routes
the three platforms; unknown values are skipped + logged.

Kill switch: `AGENT_ENABLED=false` short-circuits the entire tick.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from app.agent.services.timestamps import TBILISI_TZ, now_tbilisi
from app.config import Settings, settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    admin_config_service,
    conversation_service,
    kill_switch,
    messenger_service,
    redis_state_service,
    sentry_service,
    sheets_service,
)
from data.prompts import ADULT_FOLLOWUP, ERROR_MESSAGE, PARENT_FOLLOWUP

logger = logging.getLogger(__name__)


# Cadence definition — matches the keys in
# `app/agent/knowledge/followup_strategy.yaml`. Each entry maps the
# CURRENT followup_stage to the (delay_from_last_bot_msg, next_stage,
# admin_template_id). When `next_stage == "stopped"` the scheduler
# additionally sets `followup_blocked_reason="followup_exhausted"` so
# the lead is permanently excluded.
#
# Follow-up Test Mode Patch (2026-06-06). The first-stage delay is
# resolved through `_first_delay()` at scheduler-tick time so the
# `FOLLOWUP_TEST_MODE` + `FOLLOWUP_FIRST_DELAY_SECONDS` operator
# overrides take effect WITHOUT mutating the module-level constant.
# Production cadence stages 2 and 3 (72h / 168h) are never overridden.
_PRODUCTION_FIRST_DELAY: timedelta = timedelta(hours=24)
_FOLLOWUP_CADENCE: list[dict[str, Any]] = [
    {
        "from_stage": "",
        "delay": _PRODUCTION_FIRST_DELAY,
        "to_stage": "first_24h",
        "template_id": "followup_24h",
    },
    {
        "from_stage": "first_24h",
        "delay": timedelta(hours=72),
        "to_stage": "second_3d",
        "template_id": "followup_3d",
    },
    {
        "from_stage": "second_3d",
        "delay": timedelta(hours=168),
        "to_stage": "third_7d",
        "template_id": "followup_7d",
    },
]


def _first_delay() -> timedelta:
    """Resolve the FIRST-stage follow-up delay.

    Live Test Mode Patch (2026-06-06):
      * `FOLLOWUP_TEST_MODE=true` AND `FOLLOWUP_FIRST_DELAY_SECONDS`
        positive → that many seconds.
      * Otherwise → production 24h delay.

    Invalid `FOLLOWUP_FIRST_DELAY_SECONDS` (zero, negative, missing) is
    treated as "no override" — the production delay is used and the
    scheduler does NOT crash.
    """
    try:
        test_mode = bool(getattr(settings, "FOLLOWUP_TEST_MODE", False))
        seconds = int(getattr(settings, "FOLLOWUP_FIRST_DELAY_SECONDS", 0) or 0)
    except Exception:
        return _PRODUCTION_FIRST_DELAY
    if test_mode and seconds > 0:
        return timedelta(seconds=seconds)
    return _PRODUCTION_FIRST_DELAY


def _effective_cadence() -> list[dict[str, Any]]:
    """Return the cadence list with the resolved first-stage delay.

    A fresh list is built per call so test isolation is easy (no
    module-level mutation). Stage 1 is the only entry that the
    test-mode override touches.
    """
    cadence: list[dict[str, Any]] = []
    for entry in _FOLLOWUP_CADENCE:
        if entry["from_stage"] == "":
            cadence.append({**entry, "delay": _first_delay()})
        else:
            cadence.append(dict(entry))
    return cadence

# Reasons that hard-block follow-up. Matches the values
# `conversation_service` sets in `_record_pre_response_followup_markers`
# + `_record_post_response_followup_markers`, plus the new
# `followup_exhausted` written by the scheduler after the 7-day stage.
_BLOCKED_REASONS: frozenset[str] = frozenset({
    "booked",
    "registered",
    "declined",
    "asked_no_more_messages",
    "manager_handoff_completed",
    "followup_exhausted",
})

# Supported send platforms. WhatsApp is *plumbed* (messenger_service
# routes it) but is not production-tested; we still allow follow-up
# sends there if the operator has a Conversation with platform=whatsapp,
# because the cost of refusing the send is higher than the cost of a
# possibly-failing WhatsApp call.
_SUPPORTED_PLATFORMS: frozenset[str] = frozenset({
    "instagram", "messenger", "whatsapp",
})


# Safe Georgian fallback messages. Used when the admin template is
# missing or render fails. Hardcoded strings stay short, calm, no
# fake urgency, no price claim, no booking promise.
_FALLBACK_FOLLOWUP_24H = (
    "გამარჯობა. ბანაკთან დაკავშირებით თუ კითხვა დაგრჩათ, "
    "მომწერეთ და დაგეხმარებით."
)
_FALLBACK_FOLLOWUP_3D = (
    "გამარჯობა. უბრალოდ შეგახსენებთ — თუ ბანაკის დეტალები ისევ "
    "გაინტერესებთ, შემიძლია პირობები ან კონსულტაციის დრო გაგიზიაროთ."
)
_FALLBACK_FOLLOWUP_7D = (
    "გამარჯობა. ბოლოს შეგახსენებთ ბანაკთან დაკავშირებით. "
    "თუ თემა ისევ აქტუალურია, მოგვწერეთ და დაგეხმარებით."
)

_FALLBACK_BY_TEMPLATE_ID: dict[str, str] = {
    "followup_24h": _FALLBACK_FOLLOWUP_24H,
    "followup_3d": _FALLBACK_FOLLOWUP_3D,
    "followup_7d": _FALLBACK_FOLLOWUP_7D,
}


class FollowupService:
    """Compatibility shim — kept so the legacy `build_followup` callers
    (template rendering for adult flows) keep working."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def build_followup(self, *, content: Any, variables: dict[str, Any]) -> str | None:
        if not self.settings.followup_enabled:
            return None

        values = {
            **variables,
            "followup_delay_minutes": self.settings.followup_delay_minutes,
        }
        return content.knowledge_text("messages", "followup", **values)


def check_and_send_followups() -> None:
    """APScheduler tick: scan in-memory PARENT conversations and send
    the next due follow-up. Idempotent per stage — the second tick
    within the same window is a no-op because the stage already moved.

    Live Test Mode Patch (2026-06-06):
      * `FOLLOWUP_ENABLED=false` → tick is a no-op (logs the skip).
      * Otherwise logs whether test mode is active (with the resolved
        first-stage delay in seconds) or production cadence is active.
    """
    # Kill switch — short-circuit BEFORE reading any state.
    if not kill_switch.is_agent_enabled():
        kill_switch.log_disabled_skip(context="followup_scheduler")
        return

    # Follow-up master gate. The legacy `followup_enabled` property
    # also folds in FOLLOWUP_HOURS > 0; either branch leaving false
    # means "do nothing this tick".
    if not getattr(settings, "FOLLOWUP_ENABLED", True):
        logger.info(
            "[FOLLOWUP] disabled (FOLLOWUP_ENABLED=false) — tick skipped",
        )
        return

    # Privacy-safe mode banner so an operator can see at a glance whether
    # the live `.env` is running production or 2-minute test cadence.
    if bool(getattr(settings, "FOLLOWUP_TEST_MODE", False)):
        first_delay_secs = int(_first_delay().total_seconds())
        logger.info(
            "[FOLLOWUP] Test mode enabled: first delay = %ss",
            first_delay_secs,
        )
    else:
        logger.info("[FOLLOWUP] Production cadence active")

    snapshot = conversation_service.get_all_conversations_snapshot()
    # Follow-up Live-Test Hydrate Patch (2026-06-06): also surface the
    # PARENT subset + the count that already carries a `last_bot_message_at`
    # marker so an operator running a one-off CLI can see at a glance
    # whether the hydrator actually populated the working set.
    parent_count = sum(
        1 for c in snapshot if (c.segment or "") == "PARENT"
    )
    with_marker_count = sum(
        1 for c in snapshot if (c.last_bot_message_at or "")
    )
    logger.info(
        "[FOLLOWUP] scanning total=%d parent=%d with_marker=%d",
        len(snapshot), parent_count, with_marker_count,
    )

    now = now_tbilisi()
    sent = 0
    skipped = 0
    due = 0

    for conversation in snapshot:
        try:
            result = _maybe_send_followup_for_conversation(conversation, now)
        except Exception as exc:
            # Never let one bad conversation kill the whole tick.
            masked_sender = sentry_service.mask_sender(
                getattr(conversation, "sender_id", "") or "",
            )
            logger.exception(
                "[followup] error stage=%s platform=%s sender=%s error=%s",
                getattr(conversation, "followup_stage", "") or "",
                getattr(conversation, "platform", "") or "",
                masked_sender,
                type(exc).__name__,
            )
            # Sentry capture — stage stays a STRING ("first_24h" /
            # "second_3d" / "third_7d"), per the brief. No raw
            # sender id, no message content.
            sentry_service.capture_exception(
                exc,
                context={
                    "area": "followup_service",
                    "stage": getattr(conversation, "followup_stage", "") or "",
                    "platform": getattr(conversation, "platform", "") or "",
                    "sender": masked_sender,
                },
            )
            skipped += 1
            continue

        if result == "sent":
            sent += 1
            due += 1
        elif result == "due_send_failed":
            due += 1
            skipped += 1
        else:
            skipped += 1

    logger.info(
        "[FOLLOWUP] tick complete total=%d due=%d sent=%d skipped=%d",
        len(snapshot), due, sent, skipped,
    )


def _maybe_send_followup_for_conversation(
    conversation: Conversation, now: datetime,
) -> str:
    """Return ``"sent"`` if we actually delivered, otherwise ``"skipped"``.

    All the per-conversation skip rules from the brief Part 4 step 2
    live here. Failed sends DO update the stage / blocked_reason just
    like successful ones to avoid an infinite retry loop on a broken
    sender_id; a Sentry / error monitoring patch will surface the
    failures.
    """
    sender_id = (conversation.sender_id or "").strip()
    if not sender_id:
        logger.info("[followup] skipped reason=missing_sender_id")
        return "skipped"

    masked = sentry_service.mask_sender(sender_id)
    platform_raw = (conversation.platform or "").strip().lower()

    # Segment: only PARENT is in scope for this patch. ADULT flow is
    # not live-tested end-to-end (HANDOFF.md §5 IMPORTANT 5) and
    # UNCLEAR by definition has not chosen a direction yet.
    if conversation.segment != "PARENT":
        logger.info(
            "[followup] skipped reason=non_parent_segment segment=%s "
            "platform=%s sender=%s",
            conversation.segment or "", platform_raw, masked,
        )
        return "skipped"

    try:
        registration_open = admin_config_service.is_camp_registration_open()
    except Exception:  # pragma: no cover - registration actions fail closed
        logger.exception("[followup] camp registration gate failed")
        registration_open = False
    if not registration_open:
        logger.info(
            "[followup] skipped reason=camp_registration_closed platform=%s sender=%s",
            platform_raw, masked,
        )
        return "skipped"
    if conversation.followup_blocked_reason in _BLOCKED_REASONS:
        logger.info(
            "[followup] skipped reason=%s platform=%s sender=%s",
            conversation.followup_blocked_reason, platform_raw, masked,
        )
        return "skipped"

    # Lead-side confirmations. `_record_post_response_followup_markers`
    # already mirrors `lead.calendly_booked` → `followup_blocked_reason
    # = "booked"`, but a direct lead check is cheap insurance against
    # an out-of-band mutation.
    lead = conversation.lead
    if lead is not None and getattr(lead, "calendly_booked", False):
        logger.info(
            "[followup] skipped reason=lead_booked platform=%s sender=%s",
            platform_raw, masked,
        )
        return "skipped"

    platform = platform_raw
    if platform not in _SUPPORTED_PLATFORMS:
        logger.info(
            "[followup] skipped reason=unsupported_platform platform=%r sender=%s",
            platform, masked,
        )
        return "skipped"

    last_bot = _parse_last_bot_message_at(conversation.last_bot_message_at)
    if last_bot is None:
        logger.info(
            "[followup] skipped reason=missing_last_bot_message_at "
            "platform=%s sender=%s",
            platform, masked,
        )
        return "skipped"

    elapsed = now - last_bot
    cadence_entry = _pick_due_cadence(conversation.followup_stage, elapsed)
    if cadence_entry is None:
        return "skipped"

    template_id = cadence_entry["template_id"]
    text = _render_followup_text(template_id, conversation, lead)
    if not text:
        # Both admin template AND fallback empty — never happens with
        # the constants defined above, but be paranoid.
        logger.warning(
            "[followup] skip — empty body template_id=%s sender=%s",
            template_id, kill_switch.mask_sender(sender_id),
        )
        return "skipped"

    logger.info(
        "[followup] sending stage=%s → %s platform=%s sender=%s",
        cadence_entry["from_stage"] or "(none)",
        cadence_entry["to_stage"],
        platform,
        kill_switch.mask_sender(sender_id),
    )

    ok = False
    try:
        ok = bool(messenger_service.send_message(
            sender_id=sender_id, platform=platform, text=text,
        ))
    except Exception as exc:
        logger.exception(
            "[followup] send raised sender=%s platform=%s: %s",
            kill_switch.mask_sender(sender_id), platform, exc,
        )

    # Stage advances even on send failure so the scheduler does not
    # loop on a permanently broken sender_id. Operator sees this in
    # the [followup] WARN line + (future) Sentry alert.
    conversation.followup_stage = cadence_entry["to_stage"]
    conversation.last_bot_message_at = now.isoformat()
    if cadence_entry["to_stage"] == "third_7d":
        conversation.followup_blocked_reason = "followup_exhausted"

    _save_conversation_to_redis(conversation)

    if ok:
        logger.info(
            "[FOLLOWUP] sent stage=%s platform=%s sender=%s",
            cadence_entry["to_stage"], platform, masked,
        )
        return "sent"
    logger.warning(
        "[FOLLOWUP] send failed but stage advanced stage=%s sender=%s",
        cadence_entry["to_stage"],
        kill_switch.mask_sender(sender_id),
    )
    return "due_send_failed"


def _parse_last_bot_message_at(raw: str) -> datetime | None:
    """Parse the ISO-string `last_bot_message_at` into a tz-aware
    datetime. `conversation_service.process_message` writes this with
    `datetime.utcnow().isoformat()` — that's NAIVE UTC by convention
    (matches the rest of the codebase). Promote it via the
    canonical `to_tbilisi` helper so comparisons match `now_tbilisi()`.
    """
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        # Treat naive as UTC then shift to Tbilisi — `now_tbilisi()` is
        # aware Tbilisi, so both sides match.
        from datetime import timezone
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(TBILISI_TZ)


def _pick_due_cadence(
    current_stage: str, elapsed: timedelta,
) -> dict[str, Any] | None:
    """Return the cadence entry whose `from_stage` matches and whose
    delay has elapsed. None when no transition is due (stage already
    past, elapsed too small, or already in terminal `stopped`/`third_7d`).

    Live Test Mode Patch (2026-06-06): reads `_effective_cadence()` so
    the FIRST-stage delay reflects the `FOLLOWUP_TEST_MODE` override
    when set. Stage 2 and 3 are never overridden.
    """
    current = (current_stage or "").strip()
    if current in {"third_7d", "stopped"}:
        return None
    for entry in _effective_cadence():
        if entry["from_stage"] != current:
            continue
        if elapsed >= entry["delay"]:
            return entry
        return None
    return None


def _render_followup_text(
    template_id: str, conversation: Conversation, lead: Lead | None,
) -> str:
    """Try the admin template first, fall back to the safe Georgian
    constant if missing / empty / render-errored.
    """
    context = _followup_context(conversation, lead)
    try:
        rendered = admin_config_service.render_template(template_id, context)
    except Exception as exc:
        logger.warning(
            "[followup] admin render template_id=%s failed: %s",
            template_id, exc,
        )
        rendered = ""
    if rendered:
        return rendered.strip()
    fallback = _FALLBACK_BY_TEMPLATE_ID.get(template_id, "")
    return fallback.strip()


def _followup_context(
    conversation: Conversation, lead: Lead | None,
) -> dict[str, Any]:
    """Build the placeholder dict for `render_template`. Keeps the
    template rendering crash-proof — every placeholder either has a
    real value or an empty string (handled by admin_config_service's
    `_SafeDict`).
    """
    name = ""
    if lead is not None:
        name = (getattr(lead, "name", "") or "").strip()
    return {
        "name": name,
        "First_Name": name,
        "company_name": getattr(settings, "COMPANY_NAME", ""),
        "followup_link": getattr(settings, "FOLLOWUP_CONTENT_LINK", "") or "",
        "stopped_after": conversation.stopped_after or "",
        "last_meaningful_interest": conversation.last_meaningful_interest or "",
    }


def _save_conversation_to_redis(conversation: Conversation) -> None:
    """Write-through to Redis after the scheduler advances the stage.

    Delegates to `conversation_service._save_conversation_to_redis` so
    the key format + serialization stays in one place. Redis disabled
    / unavailable → no-op (same safe-fallback shape as the live
    write-through path in `process_message`).
    """
    if not redis_state_service.is_enabled():
        return
    try:
        conversation_service._save_conversation_to_redis(conversation)
    except Exception as exc:
        logger.warning(
            "[followup] redis write-through failed sender=%s: %s",
            kill_switch.mask_sender(conversation.sender_id), exc,
        )


# -- Legacy helpers kept for back-compat ----------------------------------
#
# `_followup_message` was the legacy Sheets-driven body builder. The
# new scheduler renders via `_render_followup_text`, but the legacy
# helper is still importable for any external caller (tests, ad-hoc
# scripts) that depends on `from app.services.followup_service import
# _followup_message`.


def _followup_message(lead: Lead) -> str:
    if lead.segment == "PARENT":
        return PARENT_FOLLOWUP.format(
            company_name=settings.COMPANY_NAME,
            followup_link=settings.FOLLOWUP_CONTENT_LINK,
        ).strip()

    if lead.segment == "ADULT":
        return ADULT_FOLLOWUP.format(
            company_name=settings.COMPANY_NAME,
            followup_link=settings.FOLLOWUP_CONTENT_LINK,
        ).strip()

    return ERROR_MESSAGE.format().strip()
