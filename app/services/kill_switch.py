"""Emergency Kill Switch — production-side disable.

When ``settings.AGENT_ENABLED`` is False the agent must:

* return ``AGENT_DISABLED_MESSAGE`` to inbound DMs;
* skip every comment-origin DM / public reply;
* skip every follow-up sender tick.

What it must NOT do:

* block ``GET /webhook`` verification;
* block ``/health`` or ``/admin``;
* call OpenAI, Calendar, Sheets, notification_service, or the
  Meta send APIs;
* mutate sales state.

The check is intentionally trivial — one canonical constant + one
``is_agent_enabled()`` helper — so every entry point (DM, comment,
follow-up) reads the same flag and shares the same safe-offline string.
A second parallel kill switch would defeat the operator's expectation
that flipping ``AGENT_ENABLED=false`` in ``.env`` actually disables the
agent everywhere.

``is_agent_enabled()`` resolves the flag dynamically from
``settings.AGENT_ENABLED`` so tests / live operators can flip it at
runtime via monkeypatch / process restart respectively. Default-on so
a missing ``AGENT_ENABLED`` line in ``.env`` leaves the agent live.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


# Georgian-only safe-offline message. Short, no booking promise, no
# fake confirmation. Same constant reused by every entry point so the
# user never sees two different "disabled" wordings.
AGENT_DISABLED_MESSAGE = (
    "ამ მომენტში ავტომატური ასისტენტი დროებით გათიშულია. "
    "მოგვწერეთ და მენეჯერი დაგიკავშირდებათ."
)


def is_agent_enabled() -> bool:
    """True iff ``settings.AGENT_ENABLED`` is True.

    Default-on: when the field is missing entirely (e.g. a frozen
    Settings constructed without the flag in an older test) we return
    True so the kill switch never trips by accident.
    """
    return bool(getattr(settings, "AGENT_ENABLED", True))


def mask_sender(sender_id: str | None) -> str:
    """Best-effort PII-light sender id for log lines.

    Keeps the trailing 4 chars so the operator can correlate a single
    skipped event with a real DM in Meta — but strips the rest so the
    log is not a clean PSID dump.
    """
    if not sender_id:
        return "?"
    sid = str(sender_id)
    if len(sid) <= 4:
        return "*" * len(sid)
    return "***" + sid[-4:]


def log_disabled_skip(
    *, context: str, sender_id: str | None = None, extra: str = "",
) -> None:
    """Single safe log line per skipped event.

    No message contents, no secrets, no tokens. Sender id masked.
    """
    parts = [f"context={context}"]
    if sender_id:
        parts.append(f"sender={mask_sender(sender_id)}")
    if extra:
        parts.append(extra)
    logger.info("[kill_switch] AGENT_ENABLED=false; skipped %s", " ".join(parts))
