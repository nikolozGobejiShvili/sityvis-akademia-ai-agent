"""READ-ONLY enforcement for the eval harness.

Every external side-effect is replaced with a recording dry-run stub:
  * Google Calendar writes (book_slot / create_event / cancel)
  * Google Sheets writes (create_lead / update_lead / save_*)
  * Manager notifications (email / WhatsApp / notify_manager)
  * Outbound Messenger / Instagram DM (send_message / send_private_reply)
  * Follow-up sends (route through messenger_service.send_message → stubbed)

Hard tripwires that MUST stay at zero:
  * SMTP (smtplib) — always blocked (OpenAI never uses SMTP).
  * raw httpx.post / httpx.get — blocked in DETERMINISTIC-ONLY mode (no OpenAI
    in that mode). In --llm mode httpx is NOT blocked (the OpenAI SDK rides on
    httpx); READ-ONLY is then guaranteed at the service-stub layer instead.

OpenAI / Anthropic are the ONLY real external calls, and only when --llm /
--judge are passed — they are the models UNDER TEST, not a side-effect.
"""
from __future__ import annotations

import dataclasses
import importlib
from collections import defaultdict
from typing import Any

# Modules that hold their own `settings` binding (mirrors tests/conftest.py).
_SETTINGS_MODULES = (
    "app.config",
    "app.flows.parent_flow",
    "app.services.conversation_service",
    "app.agent.llm.parent_llm_engine",
    "app.agent.llm.adult_llm_engine",
    "app.services.followup_service",
    "app.services.notification_service",
    "app.services.messenger_service",
)


class SideEffectLog:
    """Records every intercepted side-effect + trips hard tripwires."""

    def __init__(self) -> None:
        self.tripwire: dict[str, int] = defaultdict(int)        # MUST be 0
        self.intercepted: dict[str, list[Any]] = defaultdict(list)

    def record(self, category: str, detail: Any) -> None:
        self.intercepted[category].append(detail)

    def trip(self, name: str) -> None:
        self.tripwire[name] += 1

    def live_total(self) -> int:
        return sum(self.tripwire.values())

    def count(self, category: str) -> int:
        return len(self.intercepted.get(category, []))


def _swap_settings() -> None:
    """Pin safe live-guard flags across every module that holds `settings`."""
    config_module = importlib.import_module("app.config")
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,        # legacy live mode (full_turn cases)
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
        ALLOW_LIVE_WHATSAPP=False,
        LIVE_BROADCAST_ENABLED=False,
        AGENT_ENABLED=True,
        REDIS_ENABLED=False,
    )
    for name in _SETTINGS_MODULES:
        try:
            m = importlib.import_module(name)
            if hasattr(m, "settings"):
                setattr(m, "settings", swapped)
        except Exception:
            pass


def install_readonly(log: SideEffectLog, *, block_httpx: bool) -> None:
    """Install all dry-run stubs + tripwires. Idempotent enough for one run."""
    _swap_settings()

    # Redis hard-off (no remote persistence).
    try:
        r = importlib.import_module("app.services.redis_state_service")
        r._client = None
        r._connection_attempted = True
        r._connection_ok = False
    except Exception:
        pass

    def stub(category: str, ret: Any):
        def _f(*args: Any, **kwargs: Any) -> Any:
            log.record(category, {"args": [repr(a)[:60] for a in args],
                                  "kwargs": {k: repr(v)[:60] for k, v in kwargs.items()}})
            return ret
        return _f

    def _send_message_stub(sender_id=None, platform=None, text=None, **k):
        log.record("outbound_dm", {"sender_id": sender_id, "platform": platform, "text": text})
        return True

    patches = {
        "app.services.messenger_service": {
            "send_message": _send_message_stub,
            "send_private_reply": stub("outbound_dm", True),
            "get_user_profile": stub("profile_fetch", {}),
        },
        "app.services.calendar_service": {
            "book_slot": stub("calendar_write", "EVAL_MOCK_EVENT_ID"),
            "create_event": stub("calendar_write", "EVAL_MOCK_EVENT_ID"),
            "cancel_calendar_event": stub("calendar_write", True),
        },
        "app.services.sheets_service": {
            "create_lead": stub("sheets_write", True),
            "update_lead": stub("sheets_write", True),
            "save_lead": stub("sheets_write", True),
            "save_comment": stub("sheets_write", True),
            "log_sunday_school_lead": stub("sheets_write", (True, "ok")),
            "save_event_subscriber": stub("sheets_write", (True, "ok")),
            "mark_old_booking_rescheduled": stub("sheets_write", (True, "ok")),
        },
        "app.services.notification_service": {
            "notify_manager": stub("notify", True),
            "send_manager_notification": stub("notify", True),
            "notify_manager_handoff": stub("notify", True),
            "notify_sunday_school_handoff": stub("notify", True),
            "_send_email": stub("notify", True),
            "_send_whatsapp": stub("notify", True),
        },
    }
    for mod_name, fns in patches.items():
        try:
            m = importlib.import_module(mod_name)
        except Exception:
            continue
        for fn_name, stub_fn in fns.items():
            if hasattr(m, fn_name):
                setattr(m, fn_name, stub_fn)

    # SMTP hard-block (OpenAI does NOT use SMTP — always a valid tripwire).
    import smtplib

    class _BlockedSMTP:
        def __init__(self, *a: Any, **k: Any) -> None:
            log.trip("smtp")
            raise RuntimeError("eval harness: SMTP blocked (READ-ONLY)")

    smtplib.SMTP = _BlockedSMTP            # type: ignore[assignment]
    smtplib.SMTP_SSL = _BlockedSMTP        # type: ignore[assignment]

    # Raw httpx tripwire — only in deterministic-only mode (no OpenAI then).
    if block_httpx:
        import httpx

        def _blocked_post(*a: Any, **k: Any) -> Any:
            log.trip("httpx_post")
            raise RuntimeError("eval harness: httpx.post blocked (READ-ONLY)")

        def _blocked_get(*a: Any, **k: Any) -> Any:
            log.trip("httpx_get")
            raise RuntimeError("eval harness: httpx.get blocked (READ-ONLY)")

        httpx.post = _blocked_post          # type: ignore[assignment]
        httpx.get = _blocked_get            # type: ignore[assignment]


def render_banner(log: SideEffectLog, *, llm_used: bool, httpx_blocked: bool) -> str:
    live = log.live_total()
    ok = live == 0
    head = (
        "✅ READ-ONLY VERIFIED — 0 live external writes/sends"
        if ok else
        f"❌ READ-ONLY VIOLATED — {live} live call(s) detected!"
    )
    if httpx_blocked:
        tripwires = ("   tripwires (must be 0):  "
                     f"httpx.post={log.tripwire.get('httpx_post', 0)} · "
                     f"httpx.get={log.tripwire.get('httpx_get', 0)} · "
                     f"SMTP={log.tripwire.get('smtp', 0)}")
    else:
        # --llm: OpenAI SDK rides on httpx, so httpx is NOT blocked. The hard
        # tripwire is SMTP; READ-ONLY is enforced at the service-stub layer.
        tripwires = ("   tripwires (must be 0):  "
                     f"SMTP={log.tripwire.get('smtp', 0)}  "
                     "(httpx not blocked — OpenAI rides on it; side-effects "
                     "stubbed at the service layer)")
    lines = [
        head,
        tripwires,
        "   intercepted dry-run:    "
        f"Calendar={log.count('calendar_write')} · "
        f"Sheets={log.count('sheets_write')} · "
        f"outbound DM={log.count('outbound_dm')} · "
        f"manager notify={log.count('notify')}",
    ]
    if llm_used:
        lines.append("   OpenAI/Anthropic = models UNDER TEST (the only real external calls).")
    else:
        lines.append("   OpenAI NOT called (deterministic-only mode — fully offline).")
    return "\n".join(lines)
