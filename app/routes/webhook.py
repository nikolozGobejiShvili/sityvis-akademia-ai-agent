import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import PlainTextResponse

from app.agent.services.timestamps import now_tbilisi_iso
from app.config import settings
from app.services import (
    comment_service,
    conversation_service,
    kill_switch,
    message_buffer,
    messenger_service,
    redis_state_service,
    sheets_service,
)

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()


# In-process duplicate-comment guard.
#
# Redis remains the source of cross-restart persistence. This bounded
# LRU is a belt-and-braces fallback for the case where Redis is
# disabled or unavailable — without it a Meta webhook redelivery within
# the same process would re-fire the rich DM. The cap is intentionally
# low (1000 ids) so process memory cannot grow without bound.
_PROCESSED_COMMENTS_LRU_MAX = 1000
_processed_comments_lru: "OrderedDict[str, float]" = OrderedDict()


def _is_comment_processed_local(comment_id: str) -> bool:
    """Return True iff this ``comment_id`` was already handled in the
    current process. Bumps the entry's LRU position on hit.
    """
    if not comment_id:
        return False
    if comment_id in _processed_comments_lru:
        _processed_comments_lru.move_to_end(comment_id)
        return True
    return False


def _mark_comment_processed_local(comment_id: str) -> None:
    """Insert ``comment_id`` into the in-process LRU and evict the
    oldest entries past the cap.
    """
    if not comment_id:
        return
    _processed_comments_lru[comment_id] = time.time()
    _processed_comments_lru.move_to_end(comment_id)
    while len(_processed_comments_lru) > _PROCESSED_COMMENTS_LRU_MAX:
        _processed_comments_lru.popitem(last=False)


# Instagram Webhook Signature Patch (2026-06-08): top-level payload
# field names the existing handler routes on. Anything outside this
# set surfaces in the diagnostic log as "unsupported" — the handler
# still returns 200 so Meta doesn't retry, but the operator sees
# clearly that the field isn't wired yet.
_SUPPORTED_PAYLOAD_FIELDS: frozenset[str] = frozenset({
    "messaging",  # Facebook Messenger / Instagram messaging events
    "messages",   # Instagram Direct messages alt key (some payload shapes)
    "changes",    # Facebook Page feed / comments
    "standby",    # Page handover protocol
})


def _summarise_payload_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Walk one webhook payload and return a privacy-safe summary
    suitable for a single log line.

    The summary surfaces only:
      * the top-level ``object`` field (e.g. "page" / "instagram"),
      * the entry count,
      * the deduplicated set of top-level entry field names actually
        present (e.g. ["messaging"] or ["changes"]),
      * whether at least one supported field was found.

    NEVER includes message text, sender ids, access tokens, or any
    field value beyond the key name.
    """
    out: dict[str, Any] = {
        "object": "",
        "entries": 0,
        "fields": [],
        "supported": False,
    }
    if not isinstance(payload, dict):
        return out
    out["object"] = str(payload.get("object") or "")
    entries = payload.get("entry") or []
    if not isinstance(entries, list):
        return out
    out["entries"] = len(entries)
    field_names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key in entry.keys():
            if key in {"id", "time"}:
                continue
            field_names.add(key)
    out["fields"] = sorted(field_names)
    out["supported"] = bool(field_names & _SUPPORTED_PAYLOAD_FIELDS)
    return out


def _candidate_app_secrets() -> list[tuple[str, str]]:
    """Return the ordered list of ``(label, secret)`` pairs the
    signature verifier should try.

    Labels are privacy-safe identifiers (``facebook_app_secret`` /
    ``instagram_app_secret``) used in log lines — actual secrets are
    NEVER emitted. Empty secrets are filtered out; the deployed
    operator only needs to set whichever variants they actually use.
    """
    candidates: list[tuple[str, str]] = []
    fb_secret = (
        getattr(settings, "META_APP_SECRET", "")
        or getattr(settings, "MESSENGER_APP_SECRET", "")
        or ""
    )
    if fb_secret:
        candidates.append(("facebook_app_secret", fb_secret))
    ig_secret = getattr(settings, "INSTAGRAM_APP_SECRET", "") or ""
    if ig_secret:
        candidates.append(("instagram_app_secret", ig_secret))
    return candidates


def _verify_meta_signature(
    raw: bytes, header: str | None,
) -> tuple[bool, str]:
    """Verify Meta's ``X-Hub-Signature-256`` HMAC over the RAW request body.

    Instagram Webhook Signature Patch (2026-06-08) — now multi-secret.

    Returns ``(accepted, label)``:

      * ``(True, "")`` — verification disabled via
        ``VERIFY_WEBHOOK_SIGNATURE=False`` OR no secret configured at
        all (legacy fail-open path; a one-line warning is logged).
      * ``(True, "facebook_app_secret")`` / ``(True,
        "instagram_app_secret")`` — header matches the named secret.
      * ``(False, "")`` — header is missing / malformed / no
        configured secret produced a matching digest.

    The raw bytes (not a re-serialised JSON) MUST be used — Meta signs
    the original payload byte-for-byte, so any whitespace normalisation
    or key reordering changes the digest.

    Never logs the raw body, header value, computed digest, app
    secret, or payload contents — only the verdict and the privacy-
    safe label of the matched secret.
    """
    if not getattr(settings, "VERIFY_WEBHOOK_SIGNATURE", True):
        return True, ""

    candidates = _candidate_app_secrets()
    if not candidates:
        # Fail-open: legacy / local-dev installs where neither
        # FB nor IG secret has been propagated yet keep working.
        # Operator must set at least one secret before enforcement
        # actually kicks in.
        logger.warning(
            "[webhook] signature check skipped: META_APP_SECRET not set "
            "(also no INSTAGRAM_APP_SECRET configured)",
        )
        return True, ""

    if not header or not header.startswith("sha256="):
        return False, ""

    received = header.split("=", 1)[1]
    for label, secret in candidates:
        expected = hmac.new(
            secret.encode("utf-8"), raw, hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, received):
            return True, label
    return False, ""


@router.get("/webhook")
def verify_webhook(request: Request) -> PlainTextResponse:
    verify_token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if verify_token == settings.META_VERIFY_TOKEN and challenge:
        return PlainTextResponse(challenge)

    return PlainTextResponse("Forbidden", status_code=403)


@router.post("/webhook")
async def receive_webhook(
    request: Request, background_tasks: BackgroundTasks,
) -> Any:
    # Read the RAW body BEFORE parsing JSON so the HMAC computation
    # sees Meta's exact bytes (re-serialising a parsed dict changes
    # ordering / whitespace and invalidates the digest).
    raw = await request.body()
    signature_header = request.headers.get("X-Hub-Signature-256")

    accepted, signature_label = _verify_meta_signature(
        raw, signature_header,
    )
    if not accepted:
        logger.warning(
            "[webhook] signature rejected: no configured secret matched",
        )
        return PlainTextResponse("Forbidden", status_code=403)

    if signature_label:
        logger.info(
            "[webhook] signature accepted via %s", signature_label,
        )
    else:
        # Fail-open path (no secret configured OR
        # VERIFY_WEBHOOK_SIGNATURE=False). The verifier already logged
        # its one-line warning; we still emit an info trace so
        # operators can correlate POST-N with "accepted-but-unverified".
        logger.info("[webhook] signature accepted (verification disabled)")

    try:
        payload = json.loads(raw) if raw else {}
        logger.info("[webhook] Received payload object=%s entries=%d",
                    payload.get("object"), len(payload.get("entry", [])))

        # Instagram Webhook Signature Patch (2026-06-08): privacy-safe
        # field summary so the operator can see whether an Instagram
        # webhook came in as `messaging` / `messages` / `changes` and
        # whether it lines up with the existing handler. NEVER logs
        # message text or sender ids.
        summary = _summarise_payload_fields(payload)
        logger.info(
            "[webhook] accepted object=%s entries=%d fields=%s",
            summary["object"], summary["entries"], summary["fields"],
        )
        if (
            summary["object"] == "instagram"
            and not summary["supported"]
            and summary["fields"]
        ):
            # Operator-facing note: signature was OK, but the existing
            # handler does not yet route this Instagram field. Returns
            # 200 below so Meta does not retry-storm.
            logger.warning(
                "[webhook] instagram payload accepted but unsupported "
                "fields=%s — handler will no-op",
                summary["fields"],
            )

        # -- TEMPORARY DEBUG LOGS (comment delivery investigation) --------
        # Lets us see whether Page comment webhooks actually arrive and
        # whether their payload carries entry.changes feed-comment data
        # before anything routes / branches downstream.
        logger.info(
            "[webhook_debug] payload_keys=%s",
            list(payload.keys()) if isinstance(payload, dict)
            else type(payload).__name__,
        )

        if isinstance(payload, dict) and "entry" in payload:
            for entry in payload.get("entry", []):
                logger.info(
                    "[webhook_debug] entry_keys=%s changes_count=%s messaging_count=%s",
                    list(entry.keys()) if isinstance(entry, dict)
                    else type(entry).__name__,
                    len(entry.get("changes", [])) if isinstance(entry, dict) else 0,
                    len(entry.get("messaging", [])) if isinstance(entry, dict) else 0,
                )

                for change in (entry.get("changes", []) if isinstance(entry, dict) else []):
                    value = change.get("value", {}) if isinstance(change, dict) else {}
                    logger.info(
                        "[webhook_debug] change_field=%s change_value_keys=%s item=%s verb=%s",
                        change.get("field") if isinstance(change, dict) else None,
                        list(value.keys()) if isinstance(value, dict)
                        else str(value)[:100],
                        value.get("item") if isinstance(value, dict) else None,
                        value.get("verb") if isinstance(value, dict) else None,
                    )
        # -- END TEMPORARY DEBUG LOGS -------------------------------------

        background_tasks.add_task(_process_payload, payload)
    except Exception as exc:
        logger.exception("[webhook] Failed to parse incoming payload: %s", exc)

    return {"status": "ok"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "company": settings.COMPANY_NAME}


def _extract_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for entry in payload.get("entry", []):
        messages.extend(_extract_meta_messages(payload, entry))
        messages.extend(_extract_whatsapp_messages(entry))

    return messages


async def _process_payload(payload: dict[str, Any]) -> None:
    try:
        httpx.URL("https://graph.facebook.com")
        messages = _extract_messages(payload)
        logger.info("[webhook] Extracted %d DM messages from payload", len(messages))

        for incoming in messages:
            sender_id = incoming["sender_id"]
            message_text = incoming["message_text"]
            platform = incoming["platform"]

            logger.info("[%s] Message from %s: %s", platform, sender_id, message_text[:120])
            await message_buffer.buffer_message(
                sender_id=sender_id,
                message=message_text,
                platform=platform,
                on_ready=_dispatch_buffered_reply,
            )
    except Exception as exc:
        logger.exception("[webhook] Background processing error: %s", exc)

    try:
        _process_comment_events(payload)
    except Exception as exc:
        logger.exception("[webhook] Comment processing error: %s", exc)


async def _dispatch_buffered_reply(sender_id: str, combined_message: str, platform: str) -> None:
    """Called once per debounced batch — sends a single response for joined fragments."""
    logger.info(
        "[webhook] Dispatching buffered reply for sender=%s combined=%r",
        sender_id, combined_message[:120],
    )
    try:
        response = conversation_service.process_message(
            sender_id=sender_id,
            message_text=combined_message,
            platform=platform,
        )
    except Exception as exc:
        logger.exception("[webhook] process_message raised for sender=%s: %s", sender_id, exc)
        return

    logger.info(
        "[webhook] process_message returned response (len=%d): %s",
        len(response or ""),
        (response or "")[:120],
    )

    if not response:
        logger.warning("[webhook] Empty response — skipping send for %s", sender_id)
        return

    sent = messenger_service.send_message(sender_id, platform, response)
    if sent:
        logger.info("[webhook] ✅ Done — delivered to %s on %s", sender_id, platform)
    else:
        logger.error("[webhook] ❌ Failed to deliver to %s on %s", sender_id, platform)


def _process_comment_events(payload: dict[str, Any]) -> None:
    # -- TEMPORARY DEBUG LOGS (comment delivery investigation) --------
    logger.info("[comment_debug] _process_comment_events called")
    entries = payload.get("entry", []) if isinstance(payload, dict) else []
    logger.info("[comment_debug] entries_count=%s", len(entries))
    for _dbg_entry in entries:
        try:
            logger.info(
                "[comment_debug] entry=%s",
                json.dumps(_dbg_entry, ensure_ascii=False, default=str)[:800],
            )
        except Exception as _dbg_exc:
            logger.warning(
                "[comment_debug] entry serialise failed: %s (type=%s)",
                _dbg_exc, type(_dbg_entry).__name__,
            )
    # -- END TEMPORARY DEBUG LOGS -------------------------------------
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            field_name = change.get("field")

            if field_name == "comments":
                comment_id = value.get("id")
                post_id = value.get("media", {}).get("id")
                sender_id = value.get("from", {}).get("id")
                user_name = value.get("from", {}).get("username", "")
                comment_text = value.get("text", "")
                if comment_id and sender_id:
                    _run_async(
                        handle_comment(
                            comment_id,
                            post_id,
                            sender_id,
                            user_name,
                            comment_text,
                            "instagram",
                        )
                    )

            elif field_name == "feed":
                if value.get("item") != "comment" or value.get("verb") != "add":
                    continue
                comment_id = value.get("comment_id")
                post_id = value.get("post_id")
                sender_id = value.get("from", {}).get("id")
                user_name = value.get("from", {}).get("name", "")
                comment_text = value.get("message", "")
                if comment_id and sender_id:
                    _run_async(
                        handle_comment(
                            comment_id,
                            post_id,
                            sender_id,
                            user_name,
                            comment_text,
                            "facebook",
                        )
                    )


def _run_async(coro: Any) -> None:
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        asyncio.run(coro)


async def handle_comment(
    comment_id: str,
    post_id: str,
    sender_id: str,
    user_name: str,
    comment_text: str,
    platform: str,
) -> None:
    try:
        logger.info("[comment] Processing comment %s on post %s from %s",
                    comment_id, post_id, sender_id)

        # Emergency Kill Switch. When the agent is disabled the comment
        # handler MUST NOT classify intent (LLM), send a public reply,
        # send a private reply, or fire a rich DM. It also must not
        # write to Sheets — the kill switch is a "the agent did
        # nothing" promise, and a comment row in the CRM tagged
        # `dm_sent=true` while no DM actually went out would mislead
        # the operator. The webhook itself still returns 200 (handled
        # upstream) so Meta does not retry.
        if not kill_switch.is_agent_enabled():
            kill_switch.log_disabled_skip(
                context="comment", sender_id=sender_id,
                extra=f"comment_id={comment_id} platform={platform}",
            )
            return

        # Duplicate webhook guard. Meta may redeliver the same comment
        # webhook multiple times (retries on 5xx, page-level backfills,
        # App Review tooling). Two layers:
        #
        #   * Redis (P3-B) — persists across restarts when enabled.
        #   * In-process LRU — always runs; protects against duplicate
        #     deliveries inside the same process even when Redis is off.
        #
        # Either layer reporting "already processed" short-circuits the
        # handler.
        if comment_id:
            if _is_comment_processed_local(comment_id):
                logger.info(
                    "[comment] duplicate comment_id=%s skipped (in-process LRU)",
                    comment_id,
                )
                return
            if redis_state_service.is_enabled():
                dup_key = f"processed_comment:{comment_id}"
                if redis_state_service.exists(dup_key):
                    logger.info(
                        "[comment] duplicate comment_id=%s skipped (redis)",
                        comment_id,
                    )
                    # Mirror into the LRU so a subsequent in-process
                    # check is just as fast.
                    _mark_comment_processed_local(comment_id)
                    return

        # Comment → Specific Event Mapping Patch (2026-06-08): the
        # deterministic broad-interest keyword check short-circuits
        # the LLM round-trip for the closed set of obvious price /
        # location / link / registration / generic-interest phrases.
        # Falls back to the LLM classifier for everything else, so
        # unrelated comments still get filtered as NOT_INTERESTED.
        if comment_service.is_interest_intent(comment_text):
            intent = "INTERESTED"
            logger.info("[comment] Intent detected: INTERESTED (deterministic)")
        else:
            intent = await comment_service.detect_comment_intent(comment_text)
            logger.info("[comment] Intent detected: %s", intent)

        if intent == "NOT_INTERESTED":
            logger.info("[comment] Ignored - not interested: %s", comment_text[:50])
            print(f"[COMMENT] Ignored - not interested: {comment_text[:50]}")
            return

        segment = await comment_service.determine_segment_from_post(post_id, platform)
        has_dm_history = sender_id in conversation_service.conversations
        logger.info(
            "[comment] Segment=%s, has_dm_history=%s, intent=%s",
            segment, has_dm_history, intent,
        )

        sheets_service.save_comment(
            {
                "comment_id": comment_id,
                "post_id": post_id,
                "sender_id": sender_id,
                "user_name": user_name,
                "platform": platform,
                "segment": segment,
                "comment_text": comment_text,
                "intent": intent,
                "dm_sent": has_dm_history,
                "status": "DMSent" if has_dm_history else "CommentOnly",
                "created_at": now_tbilisi_iso(),
            }
        )

        # COMMENT FLOW PATCH 1 — public reply is OPTIONAL and must
        # never block the DM. Default off (settings.ENABLE_PUBLIC_COMMENT_REPLY).
        # Failure/exception → log, continue to DM.
        if getattr(settings, "ENABLE_PUBLIC_COMMENT_REPLY", False):
            try:
                public_ok = await comment_service.reply_to_comment(
                    comment_id, user_name, has_dm_history,
                )
                if not public_ok:
                    logger.warning(
                        "[COMMENT] Public reply failed; continuing to DM "
                        "(comment_id=%s)", comment_id,
                    )
            except Exception:
                logger.warning(
                    "[COMMENT] Public reply exception; continuing to DM "
                    "(comment_id=%s)", comment_id, exc_info=True,
                )
        else:
            logger.info(
                "[COMMENT] Public reply disabled; skipping (comment_id=%s)",
                comment_id,
            )

        # DM (or comment-private-reply) is the primary action for
        # INTERESTED comments and runs regardless of public-reply
        # outcome. `has_dm_history` no longer gates the send — Meta's
        # private-reply policy permits a page→user message after a
        # recent comment.
        #
        # PATCH 2 — pass comment_id through so send_dm_from_comment
        # can pick the private-reply API for Facebook/Instagram
        # comment-origin DMs. Without this the FB path used to call
        # send_message(platform="facebook") and hit the
        # "Unsupported platform" branch.
        logger.info(
            "[COMMENT] Attempting DM/private reply comment_id=%s "
            "segment=%s sender=%s platform=%s",
            comment_id, segment, sender_id, platform,
        )
        dm_ok = False
        try:
            dm_ok = await comment_service.send_dm_from_comment(
                sender_id, platform, post_id, segment,
                comment_id=comment_id,
                comment_text=comment_text,
            )
        except Exception:
            logger.warning(
                "[COMMENT] DM/private reply exception comment_id=%s sender=%s",
                comment_id, sender_id, exc_info=True,
            )
        if dm_ok:
            logger.info(
                "[COMMENT] DM/private reply sent comment_id=%s", comment_id,
            )
        else:
            logger.warning(
                "[COMMENT] DM/private reply failed comment_id=%s "
                "segment=%s sender=%s platform=%s",
                comment_id, segment, sender_id, platform,
            )

        logger.info(
            "[comment] Handled: %s on %s - %s (dm_ok=%s)",
            sender_id, post_id, intent, dm_ok,
        )
        print(f"[COMMENT] Handled: {sender_id} on {post_id} - {intent}")

        # Mark this comment_id processed so duplicate deliveries of the
        # same webhook (or replays after a server restart) skip the DM.
        # In-process LRU always; Redis (with the configured TTL,
        # default 7 days) when enabled. If the DM failed we still mark
        # — Meta will not redeliver to fix OUR send failure, so a
        # retry attempt at our layer would also fail and re-failures
        # should not loop forever.
        if comment_id:
            _mark_comment_processed_local(comment_id)
            if redis_state_service.is_enabled():
                redis_state_service.set_json(
                    f"processed_comment:{comment_id}",
                    {
                        "comment_id": comment_id,
                        "post_id": post_id,
                        "segment": segment,
                        "platform": platform,
                        "created_at": now_tbilisi_iso(),
                        "dm_sent": bool(dm_ok),
                    },
                )

    except Exception as exc:
        logger.exception("[comment] Error processing comment %s: %s", comment_id, exc)
        print(f"[COMMENT ERROR] {exc}")


def _extract_meta_messages(payload: dict[str, Any], entry: dict[str, Any]) -> list[dict[str, str]]:
    platform = _meta_platform(payload)
    messages: list[dict[str, str]] = []

    for event in entry.get("messaging", []):
        message_text = event.get("message", {}).get("text")
        sender_id = event.get("sender", {}).get("id")
        if sender_id and message_text:
            messages.append(
                {
                    "sender_id": sender_id,
                    "message_text": message_text,
                    "platform": platform,
                },
            )

    return messages


def _extract_whatsapp_messages(entry: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for change in entry.get("changes", []):
        value = change.get("value", {})
        for message in value.get("messages", []):
            message_text = message.get("text", {}).get("body")
            sender_id = message.get("from")
            if sender_id and message_text:
                messages.append(
                    {
                        "sender_id": sender_id,
                        "message_text": message_text,
                        "platform": "whatsapp",
                    },
                )

    return messages


def _meta_platform(payload: dict[str, Any]) -> str:
    if payload.get("object") == "instagram":
        return "instagram"
    return "messenger"
