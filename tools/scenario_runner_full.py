"""Full scenario test runner — 74 end-to-end conversations against the
real LLM engine with all external services (Calendar / Sheets /
Notification / Meta) mocked locally.

Reads scenarios from ``tools/scenario_library.py``.

Usage::

    # All scenarios (~74 × real OpenAI calls; expect ~10–15 min, ~$1–3)
    python tools/scenario_runner_full.py

    # One scenario only
    python tools/scenario_runner_full.py --id SC-01

    # By category (happy_path / booking / objection / adult / comment /
    #              difficult / security)
    python tools/scenario_runner_full.py --category happy_path

    # By priority (CRITICAL / IMPORTANT / NORMAL)
    python tools/scenario_runner_full.py --priority CRITICAL

    # Cap how many scenarios to run (useful for smoke / cost control)
    python tools/scenario_runner_full.py --limit 3

    # Skip the HTML report (still prints console summary)
    python tools/scenario_runner_full.py --no-html

Exit code 0 when nothing CRITICAL failed, 1 otherwise.

Mocks only: Calendar (book_slot, get_free_slots, check_slot_available,
check_slot_calendar_only, is_within_business_hours), Sheets
(create_lead, update_lead, save_comment, get_*), Notification
(notify_manager, send_manager_notification, _send_email,
_send_whatsapp), Messenger (send_message, send_private_reply,
get_user_profile). EVERYTHING else — including OpenAI — is the real
production code path.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import html
import re
import sys
import time
import traceback
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# -- production imports (must happen AFTER sys.path is set) --------------------

import app.config as config_module  # noqa: E402
from app.agent.tools import parent_tool_executor  # noqa: E402
from app.flows import parent_flow, parent_turn_router  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.services import (  # noqa: E402
    calendar_service,
    comment_service,
    conversation_service,
    messenger_service,
    notification_service,
    redis_state_service,
    sheets_service,
)
from tools.scenario_library import SAME_AS, SCENARIOS  # noqa: E402

# -- runner config -------------------------------------------------------------

USE_REAL_LLM = True
MOCK_CALENDAR = True
MOCK_SHEETS = True
MOCK_NOTIFICATION = True
MOCK_META = True
SAVE_HTML_REPORT = True
REPORT_DIR = REPO_ROOT / "tools" / "reports"
SCENARIO_TIMEOUT_SECONDS = 120

TBILISI_TZ = ZoneInfo("Asia/Tbilisi")

# Slot offerings the mocked Calendar returns. Future-date instances are
# stamped in at runtime, so authors don't ever hard-code a date.
MOCK_FREE_SLOT_TIMES: tuple[str, ...] = (
    "10:00", "10:30", "11:00", "11:30", "13:00", "15:00", "16:00",
)

# Georgian months (nominative) — for rendering {FUTURE_DATE_STR}.
_GEORGIAN_MONTHS_NOM: dict[int, str] = {
    1: "იანვარი", 2: "თებერვალი", 3: "მარტი", 4: "აპრილი",
    5: "მაისი", 6: "ივნისი", 7: "ივლისი", 8: "აგვისტო",
    9: "სექტემბერი", 10: "ოქტომბერი", 11: "ნოემბერი", 12: "დეკემბერი",
}

# Inflected (locative) forms used in user-typed dates ("28 ივლისს").
_GEORGIAN_MONTH_LOCATIVE: dict[int, str] = {
    1: "იანვარს", 2: "თებერვალს", 3: "მარტს", 4: "აპრილს",
    5: "მაისს", 6: "ივნისს", 7: "ივლისს", 8: "აგვისტოს",
    9: "სექტემბერს", 10: "ოქტომბერს", 11: "ნოემბერს", 12: "დეკემბერს",
}


def next_weekday(days_ahead: int = 3) -> datetime:
    """Return the next weekday at least ``days_ahead`` days from today,
    at 10:00 Asia/Tbilisi. Skips Saturday/Sunday so the bot's
    work-hours / weekend guards never block the scenario.
    """
    dt = datetime.now(TBILISI_TZ) + timedelta(days=days_ahead)
    while dt.weekday() >= 5:  # 5 = Sat, 6 = Sun
        dt += timedelta(days=1)
    return dt.replace(hour=10, minute=0, second=0, microsecond=0)


def _format_future_date_str(dt: datetime) -> str:
    """Render ``28 ივლისს`` form (day + locative month)."""
    return f"{dt.day} {_GEORGIAN_MONTH_LOCATIVE[dt.month]}"


# Per-runner cache. Computed once so all scenarios agree on a single
# "future date" and the mock Calendar slot list matches what scenarios
# embed in their user turns.
FUTURE_DT: datetime = next_weekday(3)
FUTURE_DATE_STR: str = _format_future_date_str(FUTURE_DT)
FUTURE_DATE_ISO: str = FUTURE_DT.date().isoformat()


# -- mock plumbing -------------------------------------------------------------

STATE: dict[str, Any] = {
    "booked_slots": [],
    "saved_leads": {},
    "manager_notifications": [],
    "sent_messages": [],
    "private_replies": [],
    "saved_comments": {},
    "calendar_busy_isos": set(),  # populated per-scenario
}


def _reset_runner_state() -> None:
    STATE["booked_slots"].clear()
    STATE["saved_leads"].clear()
    STATE["manager_notifications"].clear()
    STATE["sent_messages"].clear()
    STATE["private_replies"].clear()
    STATE["saved_comments"].clear()
    STATE["calendar_busy_isos"] = set()


def _book_slot(**kwargs: Any) -> bool:
    STATE["booked_slots"].append(kwargs)
    # Live QA Bug Fix Patch (2026-06-04) compat: the production
    # executor now requires `lead.calendar_event_id` to be non-empty
    # after `book_slot` returns True (Google Calendar HTTP 200 + empty
    # body was treated as silent failure). Mirror that here so the
    # mock matches the real-API contract.
    lead = kwargs.get("lead")
    if lead is not None:
        try:
            lead.calendar_event_id = "evt_runner_mock_id"
        except Exception:
            pass
    return True


def _check_slot_available(slot_datetime, duration_minutes: int = 30) -> bool:
    iso = (
        slot_datetime.isoformat() if hasattr(slot_datetime, "isoformat")
        else str(slot_datetime)
    )
    return iso not in STATE["calendar_busy_isos"]


def _check_slot_calendar_only(slot_datetime, duration_minutes: int = 30) -> bool:
    return _check_slot_available(slot_datetime, duration_minutes)


def _is_within_business_hours(slot_datetime, duration_minutes: int = 30):
    """Real production helper — re-export the live calendar_service
    function but call the real `is_within_business_hours` logic so the
    bot still rejects weekends / out-of-hours requests correctly. We
    only mock the part of Calendar that would hit the network.
    """
    return _REAL_IS_WITHIN_BUSINESS_HOURS(slot_datetime, duration_minutes)


def _get_free_slots(*args: Any, **kwargs: Any) -> list[dict]:
    """Return future-only Calendar slots. Honours either signature the
    production code uses (`target_date=...` legacy positional, or the
    new keyword-only `start_date=...` form from PATCH 4).
    """
    base_date = FUTURE_DT.date()
    if kwargs.get("start_date") is not None:
        try:
            base_date = kwargs["start_date"]
        except Exception:
            pass
    elif args:
        try:
            base_date = args[0]
        except Exception:
            pass
    slots: list[dict] = []
    for time_str in MOCK_FREE_SLOT_TIMES:
        iso = f"{base_date}T{time_str}:00+04:00"
        if iso in STATE["calendar_busy_isos"]:
            continue
        slots.append({
            "date": f"{base_date.day} {_GEORGIAN_MONTHS_NOM[base_date.month]}",
            "time": time_str,
            "datetime_iso": iso,
        })
    return slots[:6]  # honour the production "first 6" cap


def _format_slots_for_chat(slots: list[dict]) -> str:
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]
    lines = [
        f"{emojis[i]} {s.get('date')} - {s.get('time')}"
        for i, s in enumerate(slots[:6])
    ]
    return "\n".join(lines) + "\n\nგთხოვთ აირჩიოთ ნომერი."


def _create_lead(lead) -> bool:
    STATE["saved_leads"][getattr(lead, "sender_id", "")] = lead
    return True


def _save_comment(data: dict) -> bool:
    STATE["saved_comments"][data.get("comment_id", "")] = dict(data)
    return True


def _notify_manager(lead, event_type: str = "lead") -> bool:
    STATE["manager_notifications"].append(
        {"sender_id": getattr(lead, "sender_id", ""), "event_type": event_type},
    )
    return True


def _send_manager_notification(lead, summary) -> bool:
    return _notify_manager(lead, "lead")


def _send_message(sender_id: str, platform: str, text: str) -> bool:
    STATE["sent_messages"].append({
        "sender_id": sender_id, "platform": platform, "text": text,
    })
    return True


def _send_private_reply(comment_id: str, text: str) -> bool:
    STATE["private_replies"].append({"comment_id": comment_id, "text": text})
    return True


def _get_user_profile(sender_id: str, platform: str) -> dict:
    return {}


# Keep a real handle on `is_within_business_hours` BEFORE we install
# mocks, so the bot's business-hours / weekend guards keep working.
_REAL_IS_WITHIN_BUSINESS_HOURS = calendar_service.is_within_business_hours


def install_mocks() -> None:
    """Replace every external-IO function with the local in-memory stub.
    Calendar / Sheets / Notification / Messenger only.
    """
    if MOCK_CALENDAR:
        calendar_service.book_slot = _book_slot
        calendar_service.check_slot_available = _check_slot_available
        calendar_service.check_slot_calendar_only = _check_slot_calendar_only
        calendar_service.get_free_slots = _get_free_slots
        calendar_service.get_available_slots = (
            lambda: _get_free_slots(start_date=FUTURE_DT.date())
        )
        calendar_service.format_slots_for_chat = _format_slots_for_chat
        calendar_service.cancel_calendar_event = lambda *a, **k: True

    if MOCK_SHEETS:
        sheets_service.create_lead = _create_lead
        sheets_service.save_lead = _create_lead
        sheets_service.update_lead = lambda sid, updates: True
        sheets_service.get_cold_leads = lambda: []
        sheets_service.get_lead = (
            lambda sid: STATE["saved_leads"].get(sid)
        )
        sheets_service.save_comment = _save_comment
        sheets_service.update_comment = lambda cid, updates: True
        sheets_service.get_pending_comment_followups = lambda: []

    if MOCK_NOTIFICATION:
        notification_service.notify_manager = _notify_manager
        notification_service.send_manager_notification = _send_manager_notification
        notification_service._send_email = lambda *a, **k: True
        notification_service._send_whatsapp = lambda *a, **k: True
        # `_send_manager_whatsapp` is the REAL WhatsApp Cloud API POST used by the
        # under-age / Sunday-School manager handoffs. It is NOT covered by the
        # `_send_whatsapp` mock above and would otherwise reach Meta when live
        # credentials are present in `.env` — mock it so the scenario runner can
        # NEVER message the manager. (Defense-in-depth with the ALLOW_LIVE_WHATSAPP
        # guard; the runner loads the live `.env`, so the mock is what protects it.)
        notification_service._send_manager_whatsapp = lambda *a, **k: True
        notification_service._send_sms = lambda *a, **k: True

    if MOCK_META:
        messenger_service.send_message = _send_message
        messenger_service.send_private_reply = _send_private_reply
        messenger_service.get_user_profile = _get_user_profile


def force_engine_on() -> None:
    """Pin USE_PARENT_LLM_ENGINE=True on the parent_flow.settings ref.
    Mirrors the autouse pattern in tests/conftest.py. Also disables
    the public comment reply (which would otherwise call the live Meta
    Graph API with fake comment IDs).
    """
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    parent_flow.settings = swapped
    config_module.settings = swapped
    # The webhook reads settings via a module-level import; refresh it.
    from app.routes import webhook as _wh
    _wh.settings = swapped
    comment_service.settings = swapped


def force_redis_off() -> None:
    """Disable Redis fan-out so scenarios stay fully in-memory."""
    redis_state_service._client = None
    redis_state_service._connection_attempted = True
    redis_state_service._connection_ok = False
    redis_state_service.settings = dataclasses.replace(
        redis_state_service.settings, REDIS_URL="", REDIS_ENABLED=False,
    )


# -- semantic check helpers ----------------------------------------------------


def _expand(value: Any) -> tuple[bool, list[str]]:
    """Normalise an ``expected_in`` entry.

    Returns:
        (is_any_match, tokens) where ``is_any_match`` is True when at
        least ONE token must appear (list form), False when the entry
        is a literal string that must appear exactly.
    """
    if isinstance(value, list):
        return True, [t for t in value if t]
    return False, [str(value)]


def _check_expected(response: str, entry: Any) -> tuple[bool, str]:
    """Verify one ``expected_in`` entry against the response.

    Empty list → vacuously True. The runner uses an empty list as
    "no positive check, just make sure nothing crashes".
    """
    is_any, tokens = _expand(entry)
    if not tokens:
        return True, "(no positive check)"
    if is_any:
        hits = [t for t in tokens if t in response]
        if hits:
            return True, f"any-of OK: {hits[0]!r}"
        return False, f"any-of MISSING: {tokens!r}"
    token = tokens[0]
    if token in response:
        return True, f"OK: {token!r} found"
    return False, f"MISSING: {token!r}"


def _check_forbidden(response: str, token: str) -> tuple[bool, str]:
    if token in response:
        return False, f"FORBIDDEN: {token!r} found"
    return True, f"OK: {token!r} not present"


def _digits_only(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _check_final_assertion(
    key: str, expected: Any, conversation: Conversation,
) -> tuple[bool, str]:
    lead = conversation.lead
    # The runner accepts both exact and *_contains forms.
    if key == "lead.child_age":
        actual = (lead.child_age if lead else "") or ""
        # Allow loose match: lead.child_age might be "14 წლის" — compare
        # leading digits.
        a = _digits_only(actual)
        e = str(expected).strip()
        if a == e or actual.strip() == e:
            return True, f"{key}={actual!r} OK"
        return False, f"{key}={actual!r}, expected {expected!r}"
    if key == "lead.challenge_contains":
        actual = (lead.challenge if lead else "") or ""
        if str(expected) in actual:
            return True, f"{key} OK ({actual[:60]!r})"
        return False, f"{key}: {expected!r} not in {actual!r}"
    if key == "lead.name_contains":
        actual = (lead.name if lead else "") or ""
        if str(expected) in actual:
            return True, f"{key} OK ({actual!r})"
        return False, f"{key}: {expected!r} not in {actual!r}"
    if key == "lead.phone_digits_contain":
        actual = _digits_only(lead.phone if lead else "")
        if str(expected) in actual:
            return True, f"{key} OK ({actual!r})"
        return False, f"{key}: {expected!r} not in {actual!r}"
    if key == "lead.calendly_booked":
        actual = bool(lead and lead.calendly_booked)
        if actual == bool(expected):
            return True, f"{key}={actual} OK"
        return False, f"{key}={actual}, expected {expected!r}"
    if key == "conversation.state":
        actual = conversation.state
        if actual == expected:
            return True, f"{key}={actual!r} OK"
        return False, f"{key}={actual!r}, expected {expected!r}"
    if key == "conversation.followup_blocked_reason":
        actual = conversation.followup_blocked_reason or ""
        if str(expected) in actual:
            return True, f"{key}={actual!r} OK"
        return False, f"{key}={actual!r}, expected substring {expected!r}"
    if key == "conversation.stopped_after":
        actual = conversation.stopped_after or ""
        if str(expected) in actual:
            return True, f"{key}={actual!r} OK"
        return False, f"{key}={actual!r}, expected substring {expected!r}"
    return False, f"unknown assertion key {key!r}"


# -- result types --------------------------------------------------------------


@dataclasses.dataclass
class CheckResult:
    kind: str          # "expected" / "forbidden" / "final" / "comment"
    passed: bool
    detail: str


@dataclasses.dataclass
class TurnRecord:
    user: str
    response: str
    checks: list[CheckResult]
    elapsed_s: float
    note: str = ""


@dataclasses.dataclass
class ScenarioResult:
    id: str
    name: str
    category: str
    priority: str
    passed: bool
    elapsed_s: float
    turns: list[TurnRecord]
    final_checks: list[CheckResult]
    final_lead_repr: str
    final_state: str
    error: str = ""


# -- presetup hooks ------------------------------------------------------------
#
# Each hook receives the (fresh) conversation and may mutate it / its
# lead before the first user turn runs.


def _presetup_already_booked(conversation: Conversation) -> None:
    if conversation.lead is None:
        conversation.lead = Lead(
            sender_id=conversation.sender_id, platform=conversation.platform,
            segment="PARENT",
        )
    conversation.lead.calendly_booked = True
    conversation.lead.calendar_event_id = "evt-pre-booked"
    conversation.lead.booked_datetime_iso = f"{FUTURE_DATE_ISO}T11:00:00+04:00"
    conversation.lead.name = "ნინო"
    conversation.lead.phone = "595000000"
    conversation.lead.child_age = "14"
    conversation.state = "DONE"
    conversation.history.append({
        "role": "assistant",
        "content": "კონსულტაცია ჩაგინიშნავ. გნახავთ მალე.",
    })


def _presetup_phone_known(conversation: Conversation) -> None:
    if conversation.lead is None:
        conversation.lead = Lead(
            sender_id=conversation.sender_id, platform=conversation.platform,
            segment="PARENT",
        )
    conversation.lead.phone = "595000000"
    conversation.lead.name = "ნინო"
    conversation.lead.child_age = "14"
    conversation.history.append({"role": "user", "content": "ბანაკი"})
    conversation.history.append({
        "role": "assistant",
        "content": "გასაგებია, რა გაინტერესებთ კიდევ?",
    })


def _presetup_resume_after_gap(conversation: Conversation) -> None:
    """Simulate a 3-day gap where conversation state survived (Redis)."""
    if conversation.lead is None:
        conversation.lead = Lead(
            sender_id=conversation.sender_id, platform=conversation.platform,
            segment="PARENT",
        )
    conversation.lead.child_age = "14"
    conversation.state = "ASK_CHALLENGE"
    conversation.history.append({"role": "user", "content": "ბანაკი"})
    conversation.history.append({
        "role": "assistant",
        "content": "რამდენი წლისაა შვილი?",
    })
    conversation.history.append({"role": "user", "content": "14 წლის"})
    conversation.history.append({
        "role": "assistant",
        "content": "გასაგებია, რა გაწუხებთ?",
    })
    conversation.last_activity = datetime.utcnow() - timedelta(days=3)
    conversation.last_bot_message_at = (
        datetime.utcnow() - timedelta(days=3)
    ).isoformat()


_PRESETUP_HOOKS: dict[str, Any] = {
    "already_booked": _presetup_already_booked,
    "phone_known": _presetup_phone_known,
    "resume_after_gap": _presetup_resume_after_gap,
}


# -- scenario execution --------------------------------------------------------


def _substitute_placeholders(text: str) -> str:
    return (
        text
        .replace("{FUTURE_DATE_STR}", FUTURE_DATE_STR)
        .replace("{FUTURE_DATE_ISO}", FUTURE_DATE_ISO)
    )


def _normalize_caps(value: str) -> str:
    """Display-only normaliser used in the HTML transcript so Mkhedruli
    capitals render cleanly. We do NOT modify the user message before
    passing it to the agent — the bot is supposed to handle caps lock
    as-is.
    """
    try:
        return unicodedata.normalize("NFC", value)
    except Exception:
        return value


def _setup_scenario_state(scenario: dict, conversation: Conversation) -> None:
    """Apply per-scenario configuration (busy slots, presetup, etc.)."""
    STATE["calendar_busy_isos"] = set()
    for raw in scenario.get("calendar_busy", []) or []:
        STATE["calendar_busy_isos"].add(_substitute_placeholders(raw))

    presetup_name = scenario.get("presetup")
    if presetup_name:
        hook = _PRESETUP_HOOKS.get(presetup_name)
        if hook is None:
            raise RuntimeError(f"unknown presetup hook: {presetup_name!r}")
        hook(conversation)


def _wipe_per_sender_state(sender_id: str) -> None:
    """Mimic ``reset_conversation_for_sender`` but for the comment-flow
    path where the runner constructs the conversation directly.
    """
    try:
        conversation_service.reset_conversation_for_sender(sender_id)
    except Exception:
        conversation_service.conversations.pop(sender_id, None)


def run_dm_scenario(scenario: dict) -> ScenarioResult:
    sender_id = f"scn-{scenario['id'].lower()}"
    _wipe_per_sender_state(sender_id)
    parent_tool_executor.reset_state()

    conversation = conversation_service._get_or_create_conversation(
        sender_id, "instagram",
    )
    _setup_scenario_state(scenario, conversation)

    start = time.monotonic()
    turn_records: list[TurnRecord] = []
    error_msg = ""
    all_passed = True

    for raw_turn in scenario.get("turns") or []:
        user_msg = _substitute_placeholders(raw_turn.get("user") or "")
        expected_list = raw_turn.get("expected_in") or []
        forbidden_list = raw_turn.get("forbidden_in") or []
        note = raw_turn.get("note", "")

        turn_start = time.monotonic()
        try:
            response = conversation_service.process_message(
                sender_id, user_msg, "instagram",
            )
        except Exception as exc:  # pragma: no cover — production bug
            error_msg = f"{type(exc).__name__}: {exc}"
            turn_records.append(TurnRecord(
                user=user_msg, response=f"<exception> {error_msg}",
                checks=[CheckResult("exception", False, error_msg)],
                elapsed_s=time.monotonic() - turn_start,
                note=note,
            ))
            all_passed = False
            break
        elapsed = time.monotonic() - turn_start

        checks: list[CheckResult] = []
        for entry in expected_list:
            expanded_entry = (
                [_substitute_placeholders(t) for t in entry]
                if isinstance(entry, list)
                else _substitute_placeholders(entry)
            )
            ok, detail = _check_expected(response, expanded_entry)
            checks.append(CheckResult("expected", ok, detail))
            if not ok:
                all_passed = False
        for token in forbidden_list:
            tok = _substitute_placeholders(token)
            ok, detail = _check_forbidden(response, tok)
            checks.append(CheckResult("forbidden", ok, detail))
            if not ok:
                all_passed = False

        turn_records.append(TurnRecord(
            user=user_msg, response=response,
            checks=checks, elapsed_s=elapsed, note=note,
        ))

    # final assertions
    final_checks: list[CheckResult] = []
    for key, value in (scenario.get("final_assertions") or {}).items():
        ok, detail = _check_final_assertion(key, value, conversation)
        final_checks.append(CheckResult("final", ok, detail))
        if not ok:
            all_passed = False

    elapsed_total = time.monotonic() - start
    return ScenarioResult(
        id=scenario["id"], name=scenario["name"],
        category=scenario["category"], priority=scenario["priority"],
        passed=all_passed, elapsed_s=elapsed_total,
        turns=turn_records, final_checks=final_checks,
        final_lead_repr=_lead_repr(conversation.lead),
        final_state=conversation.state,
        error=error_msg,
    )


def _lead_repr(lead) -> str:
    if lead is None:
        return "Lead(None)"
    return (
        f"Lead(name={lead.name!r}, phone={lead.phone!r}, "
        f"child_age={lead.child_age!r}, challenge={(lead.challenge or '')[:50]!r}, "
        f"calendly_booked={lead.calendly_booked}, status={lead.status!r})"
    )


def run_comment_scenario(scenario: dict) -> ScenarioResult:
    """Drive the comment webhook handler instead of the DM path."""
    from app.routes import webhook as wh_route

    sender_id = f"cmt-{scenario['id'].lower()}"
    cfg = scenario.get("comment") or {}
    comment_id = cfg.get("comment_id") or f"cmt-{scenario['id']}"
    post_id = f"post-{scenario['id']}"
    post_hashtag = cfg.get("post_hashtag") or "ბანაკი"
    comment_text = cfg.get("comment_text") or "მაინტერესებს"
    duplicate = bool(cfg.get("duplicate_send"))

    # Stub the post-content fetch so determine_segment_from_post hits a
    # known caption containing the configured hashtag.
    original_fetch_post_content = comment_service.fetch_post_content
    fake_caption = f"ჩვენი ახალი პოსტი #{post_hashtag}"

    async def _fake_fetch_post(pid: str, platform: str) -> str:  # noqa: D401
        return fake_caption

    comment_service.fetch_post_content = _fake_fetch_post

    # In-memory fake Redis for the duplicate-comment guard. The
    # production guard short-circuits the webhook only when Redis is
    # enabled; we enable it here purely for the comment flow so SC-34
    # (and any future dedup scenario) can verify the behaviour without
    # standing up a real Redis instance.
    fake_redis_seen: set[str] = set()
    original_is_enabled = redis_state_service.is_enabled
    original_exists = redis_state_service.exists
    original_set_json = redis_state_service.set_json
    redis_state_service.is_enabled = lambda: True
    redis_state_service.exists = lambda key: key in fake_redis_seen
    redis_state_service.set_json = (
        lambda key, value=None, ttl=None: (fake_redis_seen.add(key) or True)
    )

    STATE["sent_messages"].clear()
    STATE["private_replies"].clear()
    STATE["saved_comments"].clear()
    _wipe_per_sender_state(sender_id)

    start = time.monotonic()
    error_msg = ""
    turn_records: list[TurnRecord] = []
    try:
        asyncio.run(wh_route.handle_comment(
            comment_id=comment_id, post_id=post_id,
            sender_id=sender_id, user_name="QA Tester",
            comment_text=comment_text, platform="facebook",
        ))
        first_dm_count = (
            len(STATE["private_replies"]) + len(STATE["sent_messages"])
        )

        second_dm_count = first_dm_count
        if duplicate:
            asyncio.run(wh_route.handle_comment(
                comment_id=comment_id, post_id=post_id,
                sender_id=sender_id, user_name="QA Tester",
                comment_text=comment_text, platform="facebook",
            ))
            second_dm_count = (
                len(STATE["private_replies"]) + len(STATE["sent_messages"])
            )
    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        first_dm_count = second_dm_count = 0
    finally:
        comment_service.fetch_post_content = original_fetch_post_content
        redis_state_service.is_enabled = original_is_enabled
        redis_state_service.exists = original_exists
        redis_state_service.set_json = original_set_json

    # Collect last DM text for the transcript.
    last_dm_text = ""
    if STATE["private_replies"]:
        last_dm_text = STATE["private_replies"][-1].get("text") or ""
    elif STATE["sent_messages"]:
        last_dm_text = STATE["sent_messages"][-1].get("text") or ""

    turn_records.append(TurnRecord(
        user=f"[comment] hashtag=#{post_hashtag} text={comment_text!r}",
        response=last_dm_text or "<no DM sent>",
        checks=[],
        elapsed_s=time.monotonic() - start,
        note=("duplicate-send variant" if duplicate else ""),
    ))

    # Evaluate comment assertions
    assertions = scenario.get("comment_assertions") or {}
    final_checks: list[CheckResult] = []
    all_passed = error_msg == ""

    if "dm_sent" in assertions:
        expected_sent = bool(assertions["dm_sent"])
        actual_sent = first_dm_count > 0
        ok = actual_sent == expected_sent
        final_checks.append(CheckResult(
            "comment", ok,
            f"dm_sent expected={expected_sent}, got={actual_sent}",
        ))
        if not ok:
            all_passed = False

    if "dm_sent_first" in assertions:
        expected = bool(assertions["dm_sent_first"])
        actual = first_dm_count > 0
        ok = actual == expected
        final_checks.append(CheckResult(
            "comment", ok,
            f"dm_sent_first expected={expected}, got={actual}",
        ))
        if not ok:
            all_passed = False

    if "dm_sent_second" in assertions:
        expected = bool(assertions["dm_sent_second"])
        # 'second' is the delta from the duplicate redelivery.
        delta = second_dm_count - first_dm_count
        actual = delta > 0
        ok = actual == expected
        final_checks.append(CheckResult(
            "comment", ok,
            f"dm_sent_second expected={expected}, got={actual} "
            f"(first={first_dm_count}, second_total={second_dm_count})",
        ))
        if not ok:
            all_passed = False

    for entry in assertions.get("dm_contains") or []:
        ok, detail = _check_expected(last_dm_text, entry)
        final_checks.append(CheckResult("comment", ok, "dm_contains " + detail))
        if not ok:
            all_passed = False
    for token in assertions.get("dm_not_contains") or []:
        ok, detail = _check_forbidden(last_dm_text, token)
        final_checks.append(CheckResult("comment", ok, "dm_not_contains " + detail))
        if not ok:
            all_passed = False

    if error_msg:
        final_checks.insert(0, CheckResult("exception", False, error_msg))

    return ScenarioResult(
        id=scenario["id"], name=scenario["name"],
        category=scenario["category"], priority=scenario["priority"],
        passed=all_passed,
        elapsed_s=time.monotonic() - start,
        turns=turn_records, final_checks=final_checks,
        final_lead_repr="(comment scenario — no DM-side lead)",
        final_state="(n/a)",
        error=error_msg,
    )


def run_scenario(scenario: dict) -> ScenarioResult:
    if scenario.get("input_type") == "comment":
        return run_comment_scenario(scenario)
    return run_dm_scenario(scenario)


# -- HTML report ---------------------------------------------------------------


def _h(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _badge(label: str, kind: str) -> str:
    return f'<span class="badge badge-{kind}">{_h(label)}</span>'


def _render_check_list(checks: list[CheckResult]) -> str:
    if not checks:
        return '<div class="check pass">— no checks —</div>'
    items = []
    for c in checks:
        cls = "pass" if c.passed else "fail"
        icon = "✅" if c.passed else "❌"
        items.append(
            f'<div class="check {cls}">{icon} '
            f'<span class="check-kind">{_h(c.kind)}</span> '
            f'{_h(c.detail)}</div>'
        )
    return "\n".join(items)


def render_html_report(results: list[ScenarioResult], out_path: Path) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    crit_total = sum(1 for r in results if r.priority == "CRITICAL")
    crit_passed = sum(1 for r in results if r.priority == "CRITICAL" and r.passed)
    imp_total = sum(1 for r in results if r.priority == "IMPORTANT")
    imp_passed = sum(1 for r in results if r.priority == "IMPORTANT" and r.passed)
    norm_total = sum(1 for r in results if r.priority == "NORMAL")
    norm_passed = sum(1 for r in results if r.priority == "NORMAL" and r.passed)
    total_elapsed = sum(r.elapsed_s for r in results)

    rows = []
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        status_cls = "pass" if r.passed else "fail"
        first_fail = ""
        if not r.passed:
            for tr in r.turns:
                for c in tr.checks:
                    if not c.passed:
                        first_fail = c.detail
                        break
                if first_fail:
                    break
            if not first_fail:
                for c in r.final_checks:
                    if not c.passed:
                        first_fail = c.detail
                        break
            if not first_fail and r.error:
                first_fail = r.error
        rows.append(
            f"<tr class='row-{status_cls}'>"
            f"<td><a href='#{_h(r.id)}'>{_h(r.id)}</a></td>"
            f"<td>{_h(r.name)}</td>"
            f"<td>{_h(r.category)}</td>"
            f"<td>{_h(r.priority)}</td>"
            f"<td class='status status-{status_cls}'>{status}</td>"
            f"<td>{r.elapsed_s:.1f}s</td>"
            f"<td>{_h(first_fail)}</td>"
            "</tr>"
        )

    details = []
    for r in results:
        status_cls = "pass" if r.passed else "fail"
        turn_html = []
        for ti, tr in enumerate(r.turns, start=1):
            turn_html.append(
                f"<div class='turn'>"
                f"<div class='turn-head'>Turn {ti} · {tr.elapsed_s:.1f}s"
                + (f" · <em>{_h(tr.note)}</em>" if tr.note else "")
                + "</div>"
                f"<div class='user'><b>[User]</b> "
                f"<pre>{_h(_normalize_caps(tr.user))}</pre></div>"
                f"<div class='agent'><b>[Agent]</b> "
                f"<pre>{_h(tr.response)}</pre></div>"
                f"<div class='checks'>{_render_check_list(tr.checks)}</div>"
                f"</div>"
            )
        final_html = (
            f"<div class='finals'><h4>Final assertions</h4>"
            f"{_render_check_list(r.final_checks)}</div>"
        )
        error_html = (
            f"<div class='error'><b>Error:</b><pre>{_h(r.error)}</pre></div>"
            if r.error else ""
        )
        details.append(
            f"<section id='{_h(r.id)}' class='scenario row-{status_cls}'>"
            f"<h3>{_h(r.id)} · {_h(r.name)} "
            f"{_badge(r.category, 'cat')} {_badge(r.priority, 'prio')} "
            f"{_badge('PASS' if r.passed else 'FAIL', status_cls)}</h3>"
            f"<div class='meta'>elapsed {r.elapsed_s:.1f}s · "
            f"final_state={_h(r.final_state)}</div>"
            f"<div class='lead-line'><b>Lead:</b> "
            f"<code>{_h(r.final_lead_repr)}</code></div>"
            + "\n".join(turn_html)
            + final_html + error_html
            + "</section>"
        )

    failed_list = "".join(
        f"<li><a href='#{_h(r.id)}'>{_h(r.id)} — {_h(r.name)}</a></li>"
        for r in results if not r.passed
    )

    css = """
    body { font: 14px/1.45 system-ui, sans-serif; margin: 0; padding: 0;
           color: #1a1a1a; background: #f5f6f8; }
    header { background: #1f2937; color: white; padding: 20px 28px; }
    header h1 { margin: 0 0 8px; font-size: 22px; }
    header .summary span { margin-right: 18px; opacity: .9; }
    main { max-width: 1100px; margin: 24px auto; padding: 0 24px; }
    table { width: 100%; border-collapse: collapse; background: white;
            box-shadow: 0 1px 2px rgba(0,0,0,.05); margin-bottom: 32px; }
    th, td { padding: 8px 10px; border-bottom: 1px solid #e5e7eb;
             text-align: left; font-size: 13px; vertical-align: top; }
    th { background: #f3f4f6; }
    .status-pass { color: #047857; font-weight: 600; }
    .status-fail { color: #b91c1c; font-weight: 600; }
    .row-fail td { background: #fef2f2; }
    .row-pass td { background: white; }
    .scenario { background: white; padding: 18px 22px; border-radius: 6px;
                margin-bottom: 18px; box-shadow: 0 1px 2px rgba(0,0,0,.04); }
    .scenario.row-fail { border-left: 4px solid #b91c1c; }
    .scenario.row-pass { border-left: 4px solid #047857; }
    .scenario h3 { margin: 0 0 6px; font-size: 16px; }
    .meta { color: #6b7280; font-size: 12px; margin-bottom: 6px; }
    .lead-line { font-size: 12px; margin-bottom: 10px; }
    .turn { border-top: 1px solid #e5e7eb; padding: 10px 0; }
    .turn-head { font-weight: 600; color: #374151; font-size: 13px; }
    .user pre, .agent pre {
        background: #f3f4f6; padding: 8px 10px; border-radius: 4px;
        margin: 4px 0; white-space: pre-wrap; word-break: break-word;
    }
    .user pre { background: #eff6ff; }
    .check { font-size: 12px; margin: 2px 0; padding: 3px 6px;
             border-radius: 3px; }
    .check.pass { color: #047857; }
    .check.fail { color: #b91c1c; background: #fef2f2; }
    .check-kind { color: #6b7280; font-size: 10px; text-transform: uppercase;
                  margin-right: 4px; }
    .badge { font-size: 11px; padding: 2px 6px; border-radius: 3px;
             color: white; margin-left: 6px; vertical-align: middle; }
    .badge-cat { background: #6b7280; }
    .badge-prio { background: #1f2937; }
    .badge-pass { background: #047857; }
    .badge-fail { background: #b91c1c; }
    .finals { margin-top: 10px; }
    .finals h4 { margin: 6px 0; font-size: 13px; color: #374151; }
    .error pre { background: #fef2f2; color: #7f1d1d; padding: 8px 10px;
                 border-radius: 4px; }
    """

    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Scenario report · {_h(datetime.now().strftime('%Y-%m-%d %H:%M'))}</title>
<style>{css}</style>
</head>
<body>
<header>
  <h1>AI Sales Agent — Scenario Report</h1>
  <div class="summary">
    <span>Total: <b>{passed}/{total}</b> passed</span>
    <span>CRITICAL: <b>{crit_passed}/{crit_total}</b></span>
    <span>IMPORTANT: <b>{imp_passed}/{imp_total}</b></span>
    <span>NORMAL: <b>{norm_passed}/{norm_total}</b></span>
    <span>Elapsed: {total_elapsed:.1f}s</span>
    <span>{_h(datetime.now().strftime('%Y-%m-%d %H:%M'))}</span>
  </div>
</header>
<main>
  <h2>Summary table</h2>
  <table>
    <thead><tr>
      <th>ID</th><th>Name</th><th>Category</th><th>Priority</th>
      <th>Status</th><th>Time</th><th>Fail reason</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  {'<h2>Failed scenarios</h2><ul>' + failed_list + '</ul>' if failed_list else ''}

  <h2>Per-scenario detail</h2>
  {''.join(details)}

  <h2>Notes for deploy</h2>
  <ul>
    <li>This report uses real LLM responses — wording will vary between
        runs. Failures should focus on missing facts, forbidden phrases,
        and wrong flow / final-assertion outcomes.</li>
    <li>Production bugs found by this run (if any) are listed in the
        console summary and the "Failed scenarios" list. Fix them in
        separate patches — this runner is a QA tool, not a fixer.</li>
  </ul>
</main>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")


# -- CLI -----------------------------------------------------------------------


def _filter_scenarios(args: argparse.Namespace) -> list[dict]:
    out = list(SCENARIOS)
    if args.id:
        wanted = {x.strip().upper() for x in args.id.split(",") if x.strip()}
        out = [s for s in out if s["id"].upper() in wanted]
    if args.category:
        out = [s for s in out if s["category"] == args.category]
    if args.priority:
        out = [s for s in out if s["priority"] == args.priority.upper()]
    if args.limit:
        out = out[: args.limit]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", help="Comma-separated scenario IDs (e.g. SC-01,SC-25)")
    parser.add_argument(
        "--category",
        choices=("happy_path", "booking", "objection", "adult",
                 "comment", "difficult", "security", "transcript"),
    )
    parser.add_argument(
        "--priority",
        choices=("CRITICAL", "IMPORTANT", "NORMAL"),
    )
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N scenarios (cost / smoke control)")
    parser.add_argument("--no-html", action="store_true",
                        help="Skip the HTML report; still print console summary")
    parser.add_argument("--report-dir", default=str(REPORT_DIR),
                        help="Where to write the HTML report")
    args = parser.parse_args()

    force_engine_on()
    force_redis_off()
    install_mocks()

    scenarios = _filter_scenarios(args)
    if not scenarios:
        print("No scenarios matched the filters.")
        return 0

    print(
        f"Running {len(scenarios)} scenario(s). "
        f"Engine flag is ON. External services mocked (Calendar/Sheets/"
        f"Notification/Meta). LLM calls hit real OpenAI."
    )
    print(f"Future date used in scenarios: {FUTURE_DATE_STR} ({FUTURE_DATE_ISO})\n")

    results: list[ScenarioResult] = []
    for i, scenario in enumerate(scenarios, start=1):
        sid = scenario["id"]
        name = scenario["name"]
        cat = scenario["category"]
        prio = scenario["priority"]
        print(f"[{i:>3}/{len(scenarios)}] {sid} · {name} ({cat}, {prio}) ... ",
              end="", flush=True)
        _reset_runner_state()
        t0 = time.monotonic()
        try:
            result = run_scenario(scenario)
        except Exception as exc:
            result = ScenarioResult(
                id=sid, name=name, category=cat, priority=prio,
                passed=False, elapsed_s=time.monotonic() - t0,
                turns=[], final_checks=[
                    CheckResult("exception", False,
                                f"{type(exc).__name__}: {exc}"),
                ],
                final_lead_repr="(unhandled exception)",
                final_state="(unknown)",
                error=traceback.format_exc(),
            )
        results.append(result)
        tag = "PASS" if result.passed else "FAIL"
        print(f"{tag} ({result.elapsed_s:.1f}s)")

    # console summary
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    crit_fail = [r for r in results if not r.passed and r.priority == "CRITICAL"]
    print()
    print("=" * 64)
    print(f"Total: {passed}/{total} passed")
    by_cat = {}
    for r in results:
        by_cat.setdefault(r.category, [0, 0])
        by_cat[r.category][1] += 1
        if r.passed:
            by_cat[r.category][0] += 1
    for cat, (p, t) in by_cat.items():
        print(f"  {cat:>12}: {p}/{t}")
    if crit_fail:
        print(f"\nCRITICAL failures ({len(crit_fail)}):")
        for r in crit_fail:
            print(f"  - {r.id} · {r.name}")
    print("=" * 64)

    if SAVE_HTML_REPORT and not args.no_html:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(args.report_dir) / f"scenario_report_{stamp}.html"
        render_html_report(results, out)
        print(f"\nHTML report: {out}")

    return 1 if crit_fail else 0


if __name__ == "__main__":
    sys.exit(main())
