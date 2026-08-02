import logging
import re
from time import sleep
from typing import Any

import httpx

from app.config import Settings, has_value, settings
from app.models.conversation import IncomingMessage

logger = logging.getLogger(__name__)

# Security (2026-06-19): the Graph API passes `access_token` as a URL query
# param in `get_user_profile`, so an httpx error string (which echoes the
# full request URL) would otherwise leak the full token into logs. Scrub it.
_ACCESS_TOKEN_RE = re.compile(r"(access_token=)[^&\s\"']+", re.IGNORECASE)


def _mask_access_token(text: object) -> str:
    """Replace any `access_token=<value>` with a masked marker. Used on
    error strings before logging so a token is never written to disk."""
    return _ACCESS_TOKEN_RE.sub(r"\1***masked***", str(text))


def _graph_base_url() -> str:
    return f"{settings.META_GRAPH_API_BASE_URL}/{settings.META_GRAPH_API_VERSION}"


# Markdown → plain text (2026-08-02). A Meta DM has no renderer: `**bold**`,
# `| tables |` and `---` arrive as literal asterisks, pipes and dashes. The
# per-turn context already states the medium and the prompt now shows a worked
# example, but guidance is probabilistic — the live log of 13:12:40 still sent
# „- **ბანაკი (2026)** — …". So this sits in the RENDERING layer, where the
# constraint actually lives: a channel that cannot display markup.
#
# It converts, it does not forbid. Nothing is deleted from the reply's meaning
# and emoji are untouched — the model keeps its own voice, the channel gets
# characters it can show.
_MD_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_BOLD_UNDERSCORE_RE = re.compile(r"__(.+?)__", re.DOTALL)
# Single-asterisk emphasis, but never a „* item" bullet: the character after
# the opening `*` must not be a space.
_MD_ITALIC_RE = re.compile(r"(?<![\*\w])\*([^\s*][^*\n]*?)\*(?![\*\w])")
_MD_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_MD_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_MD_RULE_RE = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)
_MD_TABLE_SEP_RE = re.compile(
    r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)+\|?[ \t]*$",
    re.MULTILINE,
)
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def to_plain_text(text: str) -> str:
    """Strip Markdown syntax the DM channel would show literally.

    Table rows become „cell — cell" lines; the `|---|---|` separator and any
    `---` rule are dropped. Bold/italic/code/heading markers are removed and
    a `[label](url)` link becomes „label (url)" so the URL still travels.

    Returns the text unchanged when it carries none of the marker characters,
    so the overwhelmingly common clean reply is untouched.
    """
    if not text or not any(ch in text for ch in "*_`#|["):
        return text
    out = _MD_LINK_RE.sub(r"\1 (\2)", text)
    out = _MD_BOLD_RE.sub(r"\1", out)
    out = _MD_BOLD_UNDERSCORE_RE.sub(r"\1", out)
    out = _MD_ITALIC_RE.sub(r"\1", out)
    out = _MD_INLINE_CODE_RE.sub(r"\1", out)
    out = _MD_HEADING_RE.sub("", out)
    out = _MD_TABLE_SEP_RE.sub("", out)
    out = _MD_RULE_RE.sub("", out)

    lines = []
    for line in out.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            line = " — ".join(c for c in cells if c)
        lines.append(line)
    return _BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip()


def get_user_profile(sender_id: str, platform: str) -> dict:
    token = settings.MESSENGER_PAGE_ACCESS_TOKEN or settings.META_ACCESS_TOKEN
    if not token:
        logger.warning(
            "[messenger] get_user_profile skipped — no access token configured",
        )
        return {}

    logger.info(
        "[messenger] Fetching profile for sender_id=%s platform=%s",
        sender_id, platform,
    )

    if platform == "instagram":
        fields = "name,username,profile_pic"
    else:
        fields = "first_name,last_name,profile_pic"

    url = f"{_graph_base_url()}/{sender_id}"
    params = {"fields": fields, "access_token": token}

    try:
        response = httpx.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        # Mask the access_token before logging — the httpx error string
        # echoes the full request URL (which carries access_token=…).
        logger.warning(
            "[messenger] get_user_profile failed for sender_id=%s platform=%s: %s",
            sender_id, platform, _mask_access_token(exc),
        )
        return {}

    if platform == "instagram":
        name = (data.get("name") or "").strip()
        parts = name.split()
        result = {
            "name": name,
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]) if len(parts) > 1 else "",
            "username": data.get("username", ""),
        }
    else:
        first = (data.get("first_name") or "").strip()
        last = (data.get("last_name") or "").strip()
        result = {
            "name": f"{first} {last}".strip(),
            "first_name": first,
            "last_name": last,
            "username": "",
        }

    logger.info(
        "[messenger] Profile fetched: name=%r username=%r",
        result.get("name", ""), result.get("username", ""),
    )
    return result


def send_private_reply(comment_id: str, text: str) -> bool:
    """COMMENT FLOW PATCH 2 — private reply to a Facebook / Instagram
    public comment via the Page's ``/messages`` endpoint with
    ``recipient = {"comment_id": …}``.

    Why this is separate from ``send_message``:

      * Comment-origin DM cannot use a Messenger PSID. The id Meta
        hands us on a comment webhook (``value.from.id`` for FB feed
        or ``value.from.id`` for IG comments) is the user's
        FBID / IG-actor-id, NOT a Messenger PSID. Sending to
        ``recipient.id = <FBID>`` returns a Meta permission error.
      * Meta's documented path is the Private Reply API: post to
        ``/{PAGE_ID}/messages`` (Facebook) or ``/me/messages`` (IG,
        when the call is authorised against the IG-paired Page token)
        with ``recipient = {"comment_id": …}``. This works for both
        Facebook Page comments and Instagram comments and does not
        require a PSID.

    Returns True on Meta's first 2xx response, False after three
    failed attempts. Same retry policy / 2-second backoff as
    ``send_message`` so log lines align across both paths.
    """
    if not comment_id:
        logger.error("[private_reply] missing comment_id — cannot send")
        return False

    token = settings.MESSENGER_PAGE_ACCESS_TOKEN or settings.META_ACCESS_TOKEN
    if not token:
        logger.error(
            "[private_reply] missing access token — cannot send comment_id=%s",
            comment_id,
        )
        return False

    base_url = _graph_base_url()
    # If META_PAGE_ID is set we hit /{PAGE_ID}/messages — the canonical
    # endpoint for FB Page private replies. If it is not configured,
    # /me/messages also works for the page token but is less explicit.
    page_id = (getattr(settings, "META_PAGE_ID", "") or "").strip() or "me"
    url = f"{base_url}/{page_id}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    body = {
        "recipient": {"comment_id": comment_id},
        "message": {"text": text},
    }

    logger.info(
        "[private_reply] -> POST %s comment_id=%s len=%d",
        url, comment_id, len(text),
    )

    for attempt in range(3):
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=15)
            if response.is_success:
                logger.info(
                    "[private_reply] ✅ SENT comment_id=%s: %s",
                    comment_id, text[:50],
                )
                print(f"[PRIVATE REPLY] {comment_id}: {text[:50]}...")
                return True
            logger.warning(
                "[private_reply] non-success status=%s attempt=%d body=%s",
                response.status_code,
                attempt + 1,
                (response.text or "")[:300],
            )
        except Exception as exc:
            logger.exception(
                "[private_reply] attempt %d failed comment_id=%s: %s",
                attempt + 1, comment_id, exc,
            )
            print(f"[PRIVATE REPLY ERROR] attempt {attempt + 1}: {exc}")

        if attempt < 2:
            sleep(2)

    logger.error(
        "[private_reply] ❌ FAILED after 3 attempts comment_id=%s — dropped",
        comment_id,
    )
    return False


def send_message(sender_id: str, platform: str, text: str) -> bool:
    # Last stop before the channel — every outbound DM (engine reply,
    # deterministic answer, follow-up) passes here, so this is the one place
    # that can guarantee the customer never sees raw markup.
    text = to_plain_text(text)
    base_url = _graph_base_url()
    if platform in {"instagram", "messenger"}:
        url = f"{base_url}/me/messages"
        token = settings.MESSENGER_PAGE_ACCESS_TOKEN or settings.META_ACCESS_TOKEN
        body = {
            "recipient": {"id": sender_id},
            "message": {"text": text},
            "messaging_type": "RESPONSE",
        }
    elif platform == "whatsapp":
        # Manager WhatsApp Notification Fix (2026-06-18): resolve the token
        # + phone-number-id through the centralised, alias-aware accessors
        # (WHATSAPP_ACCESS_TOKEN / WHATSAPP_TOKEN) so a token present under
        # either env name is found — this is the line that previously logged
        # "Missing access token for platform=whatsapp" when the token was
        # only resolvable from the process env / the alternate name.
        url = f"{base_url}/{settings.get_whatsapp_phone_number_id()}/messages"
        token = settings.get_whatsapp_access_token()
        body = {
            "messaging_product": "whatsapp",
            "to": sender_id,
            "type": "text",
            "text": {"body": text},
        }
    else:
        logger.warning("[send_message] Unsupported platform: %s", platform)
        return False

    if not token:
        logger.error("[send_message] Missing access token for platform=%s — cannot send", platform)
        return False

    headers = {"Authorization": f"Bearer {token}"}
    logger.info("[send_message] -> %s POST %s recipient=%s len=%d",
                platform, url, sender_id, len(text))

    for attempt in range(3):
        try:
            response = httpx.post(url, headers=headers, json=body, timeout=15)
            if response.is_success:
                logger.info("[send_message] ✅ SENT [%s] to %s: %s",
                            platform, sender_id, text[:50])
                print(f"[SENT][{platform}] To {sender_id}: {text[:50]}...")
                return True
            logger.warning(
                "[send_message] Non-success status=%s on attempt %d, body=%s",
                response.status_code,
                attempt + 1,
                (response.text or "")[:300],
            )
        except Exception as exc:
            logger.exception(
                "[send_message] Attempt %d failed [%s] to %s: %s",
                attempt + 1, platform, sender_id, exc,
            )
            print(f"[SEND ERROR][{platform}] Attempt {attempt + 1}: {exc}")

        if attempt < 2:
            sleep(2)

    logger.error(
        "[send_message] ❌ FAILED after 3 attempts [%s] to %s — message DROPPED",
        platform, sender_id,
    )
    return False


class MessengerService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return has_value(self.settings.META_ACCESS_TOKEN)

    def verify(
        self,
        mode: str | None,
        verify_token: str | None,
        challenge: str | None,
    ) -> str | None:
        if mode and verify_token and challenge and verify_token == self.settings.META_VERIFY_TOKEN:
            return challenge
        return None

    def extract_messages(self, payload: dict[str, Any]) -> list[IncomingMessage]:
        messages: list[IncomingMessage] = []
        platform = "instagram" if payload.get("object") == "instagram" else "messenger"
        for entry in payload.get("entry", []):
            for event in entry.get("messaging", []):
                text = event.get("message", {}).get("text")
                sender_id = event.get("sender", {}).get("id")
                if text:
                    messages.append(
                        IncomingMessage(
                            sender_id=sender_id,
                            message=text,
                            channel=platform,
                            metadata={"raw_event": event},
                        ),
                    )
        return messages

    def send_text(self, recipient_id: str, text: str) -> bool:
        return send_message(recipient_id, "messenger", text)
