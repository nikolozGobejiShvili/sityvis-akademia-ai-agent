"""Sentry / Error Monitoring — optional, safe-fallback wrapper.

This is the ONLY place that talks to ``sentry_sdk`` directly. Every
other module calls the small API exposed here:

    init_sentry(dsn, environment, traces_sample_rate)
    capture_exception(exc, context=None)
    capture_message(message, level="error")
    set_tag(key, value)

Design rules (per the Basic Error Monitoring Patch brief):

  * **Optional.** App must boot whether or not ``sentry-sdk`` is
    installed AND whether or not ``SENTRY_DSN`` is configured.
  * **Privacy-safe.** Never forward raw user messages, phone numbers,
    SMTP / OpenAI / Meta tokens, Gmail App Password, Google private
    key, Redis URL with password, or full sender IDs. The capture
    points pass *masked* sender ids and structural labels only.
  * **Never break runtime.** Every public function catches its own
    exceptions and degrades to a no-op. Monitoring code must never
    cause a customer-visible failure.
  * **`send_default_pii=False`.** Even if Sentry's automatic
    instrumentation captures additional context, PII is suppressed.
  * Integrations (FastAPI / Asyncio) are best-effort; missing
    integration modules are not a startup failure.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Lazy SDK availability flag. We try to import once at module load —
# a missing `sentry-sdk` simply flips the flag and every public
# function becomes a safe no-op.
try:
    import sentry_sdk  # type: ignore
    _SDK_AVAILABLE = True
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]
    _SDK_AVAILABLE = False


# Toggled by ``init_sentry`` after a successful ``sentry_sdk.init`` call.
# Public capture functions consult this flag (and ``_SDK_AVAILABLE``)
# before doing any work — so before init, or after a failed init, every
# capture is a no-op.
_INITIALIZED: bool = False


def _is_active() -> bool:
    """Both the SDK AND a successful init are required."""
    return _SDK_AVAILABLE and _INITIALIZED


def init_sentry(
    dsn: str,
    environment: str = "production",
    traces_sample_rate: float = 0.0,
) -> None:
    """Initialise Sentry. No-op when DSN is empty or the SDK is missing.

    Safe to call multiple times — the second call is a no-op after a
    successful first init.
    """
    global _INITIALIZED

    if not (dsn or "").strip():
        logger.info("[sentry] DSN not configured — Sentry disabled")
        return

    if not _SDK_AVAILABLE:
        logger.info("[sentry] SDK not installed — Sentry disabled")
        return

    if _INITIALIZED:
        return

    # Integrations are best-effort — missing modules must not crash
    # startup. FastAPI integration is imported via its starlette
    # parent (Starlette is the FastAPI ASGI layer), AsyncIO from a
    # standard location.
    integrations: list[Any] = []
    try:
        from sentry_sdk.integrations.fastapi import (  # type: ignore
            FastApiIntegration,
        )
        integrations.append(FastApiIntegration())
    except Exception as exc:
        logger.info("[sentry] FastApi integration unavailable: %s", exc)
    try:
        from sentry_sdk.integrations.asyncio import (  # type: ignore
            AsyncioIntegration,
        )
        integrations.append(AsyncioIntegration())
    except Exception as exc:
        logger.info("[sentry] Asyncio integration unavailable: %s", exc)

    # Clamp the sample rate so an out-of-range env value does not make
    # Sentry over-sample or raise.
    try:
        rate = float(traces_sample_rate)
    except (TypeError, ValueError):
        rate = 0.0
    if rate < 0.0:
        rate = 0.0
    elif rate > 1.0:
        rate = 1.0

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=environment or "production",
            traces_sample_rate=rate,
            # PII safety — Sentry's auto-collected request bodies,
            # headers, etc. are suppressed. The capture points feed
            # only masked, structural context.
            send_default_pii=False,
            attach_stacktrace=True,
            integrations=integrations,
        )
        _INITIALIZED = True
        logger.info(
            "[sentry] initialised environment=%s traces_sample_rate=%s integrations=%d",
            environment, rate, len(integrations),
        )
    except Exception as exc:
        # Init itself failed (bad DSN format, network unreachable
        # transport, etc.). Stay disabled and continue.
        logger.warning(
            "[sentry] init failed — continuing without monitoring: %s", exc,
        )


def capture_exception(
    exc: BaseException, context: dict[str, Any] | None = None,
) -> None:
    """Forward an exception to Sentry with optional structural context.

    Context dict MUST contain only privacy-safe labels — see the
    capture points in `conversation_service`, `parent_tool_executor`,
    and `followup_service`. Never raises; degrades to a no-op on any
    internal failure.
    """
    if not _is_active():
        return
    try:
        if context:
            # `push_scope` ensures the extras are attached to THIS
            # event only and do not leak into the next captured event.
            with sentry_sdk.push_scope() as scope:  # type: ignore[union-attr]
                for key, value in context.items():
                    try:
                        scope.set_extra(key, value)
                    except Exception:
                        # Individual key failure must not skip the
                        # capture itself.
                        continue
                sentry_sdk.capture_exception(exc)  # type: ignore[union-attr]
        else:
            sentry_sdk.capture_exception(exc)  # type: ignore[union-attr]
    except Exception as monitoring_exc:  # pragma: no cover — defensive
        # Belt-and-braces: even if Sentry's internals fail, the agent
        # must keep running.
        logger.warning(
            "[sentry] capture_exception failed (event dropped): %s",
            monitoring_exc,
        )


def capture_message(message: str, level: str = "error") -> None:
    """Send a manual message event. No-op when disabled."""
    if not _is_active():
        return
    try:
        sentry_sdk.capture_message(message, level=level)  # type: ignore[union-attr]
    except Exception as monitoring_exc:  # pragma: no cover
        logger.warning(
            "[sentry] capture_message failed (event dropped): %s",
            monitoring_exc,
        )


def set_tag(key: str, value: str) -> None:
    """Pin a global tag on the current Sentry scope. No-op when
    disabled. Caller is responsible for ensuring `value` is not
    sensitive.
    """
    if not _is_active():
        return
    try:
        sentry_sdk.set_tag(key, value)  # type: ignore[union-attr]
    except Exception as monitoring_exc:  # pragma: no cover
        logger.warning(
            "[sentry] set_tag failed (key=%s dropped): %s",
            key, monitoring_exc,
        )


def mask_sender(sender_id: str | None) -> str:
    """Privacy helper: keep just enough of the sender id for log
    correlation without echoing the full Meta PSID.

    Matches the brief's required ``sender[:6] + "***"`` shape.
    """
    if not sender_id:
        return ""
    sid = str(sender_id)
    if len(sid) <= 6:
        return sid + "***"
    return sid[:6] + "***"
