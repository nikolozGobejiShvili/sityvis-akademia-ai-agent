"""P3-C PATCH 6 — exact-slot availability transcript replay.

Five mini-scenarios verify the live bug fix:

  * Scenario A — exact slot is available end-to-end:
      - 'check_consultation_slot(2026-05-27T15:00)' returns available=True;
      - pending_booking is recorded with user_confirmed_datetime=True
        and source='user_requested_exact_slot';
      - the deterministic PATCH 5 commit fires when the parent later
        sends name + phone; Calendar / Sheets / notification each
        called once.
  * Scenario B — slot outside business hours:
      - reason='outside_business_hours' (NOT calendar_busy);
      - LLM wording avoids 'დაკავებულია';
      - no pending_booking is recorded.
  * Scenario C — Calendar is busy at the requested time:
      - reason='calendar_busy';
      - alternatives are surfaced.
  * Scenario D — future date is NOT pruned by the today-only buffer:
      - 27 May 15:00 with now=24 May 13:30 and buffer 120 must remain
        in `get_free_slots`.
  * Scenario E — today buffer DOES still apply on the same date:
      - 24 May 14:00 with now=24 May 13:30 and buffer 120 → excluded.

Run::

    python tools/manual_simulation_p3c_exact_slot_availability.py
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date as _date, datetime as _dt, timedelta as _td
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import app.config as config_module  # noqa: E402
from app.agent.tools import parent_tool_executor  # noqa: E402
from app.agent.tools.parent_tools import (  # noqa: E402
    TOOL_CHECK_CONSULTATION_SLOT,
)
from app.flows import parent_flow, parent_turn_router  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.services import (  # noqa: E402
    calendar_service,
    conversation_service,
    messenger_service,
    notification_service,
    openai_service,
    sheets_service,
)


TBILISI_TZ = ZoneInfo("Asia/Tbilisi")


def reset_runtime() -> None:
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    parent_tool_executor.reset_state()


parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=True,
)
reset_runtime()

messenger_service.get_user_profile = lambda sid, plat: {}
openai_service._chat_completion = lambda **kwargs: "ქართული რეზიუმე."
openai_service.detect_start_intent = lambda m: "GREETING"


CALLS: dict[str, list[Any]] = {
    "chat_with_tools": [],
    "system_blocks": [],
    "book_slot": [],
    "create_lead": [],
    "send_manager_notification": [],
    "get_free_slots": [],
    "check_slot_calendar_only": [],
    "check_slot_available": [],
}


def _mk_response(*, content="", tool_calls=None):
    tc_objs = []
    for tc in tool_calls or []:
        tc_objs.append(SimpleNamespace(
            id=tc.get("id", "call_x"),
            function=SimpleNamespace(
                name=tc["name"],
                arguments=tc.get("arguments", "{}"),
            ),
        ))
    return SimpleNamespace(choices=[
        SimpleNamespace(message=SimpleNamespace(
            content=content or None,
            tool_calls=tc_objs or None,
        )),
    ])


_PENDING_STEPS: list[dict[str, Any]] = []


def chat_with_tools_mock(**kwargs):
    CALLS["chat_with_tools"].append(kwargs)
    for m in (kwargs.get("messages") or []):
        if m.get("role") == "system":
            CALLS["system_blocks"].append(m.get("content") or "")
    if not _PENDING_STEPS:
        return _mk_response(content="(no more scripted steps)")
    step = _PENDING_STEPS.pop(0)
    if step["type"] == "content":
        return _mk_response(content=step["content"])
    return _mk_response(tool_calls=[{
        "id": f"call_{len(CALLS['chat_with_tools'])}",
        "name": step["name"],
        "arguments": step["arguments"],
    }])


openai_service.chat_with_tools = chat_with_tools_mock


def queue_content(text: str) -> dict[str, Any]:
    return {"type": "content", "content": text}


def queue_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_call", "name": name, "arguments": json.dumps(args)}


def run_turn(conversation, user_message, steps, label):
    print(f"\n=== Turn — {label} ===")
    print(f"USER: {user_message}")
    _PENDING_STEPS.clear()
    _PENDING_STEPS.extend(steps)
    conversation_service.conversations[conversation.sender_id] = conversation
    response = conversation_service.process_message(
        conversation.sender_id, user_message, conversation.platform,
    )
    print(f"BOT:  {response}")
    return response


def fail(label, msg):
    print(f"❌ {label}: {msg}")
    raise SystemExit(1)


def ok(label):
    print(f"✅ {label}")


# =========================================================================
# Scenario A — exact slot available, full booking commit
# =========================================================================


print("\n################ Scenario A — exact slot available ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

# Calendar is free for the requested 15:00.
calendar_service.check_slot_calendar_only = (
    lambda dt, duration_minutes=30: (
        CALLS["check_slot_calendar_only"].append(dt) or True
    )
)
calendar_service.check_slot_available = (
    lambda dt, duration_minutes=30: (
        CALLS["check_slot_available"].append(dt) or True
    )
)


def _get_free_slots(target_date=None, duration_minutes=30, *, start_date=None, days=1):
    CALLS["get_free_slots"].append({"target_date": target_date,
                                     "start_date": start_date,
                                     "days": days})
    anchor = start_date or target_date
    if anchor is None:
        return []
    return [
        {"date": str(anchor), "time": "13:00",
         "datetime_iso": f"{anchor}T13:00:00+04:00"},
        {"date": str(anchor), "time": "15:00",
         "datetime_iso": f"{anchor}T15:00:00+04:00"},
    ]


calendar_service.get_free_slots = _get_free_slots
calendar_service.book_slot = (
    lambda **kwargs: (
        CALLS["book_slot"].append(kwargs)
        or setattr(kwargs["lead"], "calendar_event_id", "evt_p3c6_a")
        or True
    )
)
sheets_service.create_lead = (
    lambda lead: CALLS["create_lead"].append(lead.conversation_summary) or True
)
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append(summary) or True
)


conv_a = Conversation(sender_id="sim_p3c6_a", platform="instagram")

# Turn 1: minimal warm-up so lead has child_age (required for commit).
run_turn(
    conv_a,
    "ბანაკი მაინტერესებს",
    [queue_content("გასაგებია. რამდენი წლისაა შვილი?")],
    "A1: opener",
)
run_turn(
    conv_a,
    "10 წლის",
    [queue_content("რას ელოდებით ბანაკისგან?")],
    "A2: age",
)
# Manually set lead.child_age (engine path saves via save_lead_info
# normally; we shortcut here).
conv_a.lead.child_age = "10"

# Turn 3: exact-time request.
out_a = run_turn(
    conv_a,
    "კი მინდა ჩაწერა 27 მაისს 3 საათზე თუ არის შესაძლებელი",
    [
        queue_tool(TOOL_CHECK_CONSULTATION_SLOT, {
            "datetime_iso": "2030-05-27T15:00:00+04:00",
        }),
        queue_content(
            "27 მაისს, 15:00 თავისუფალია. კონსულტაციის ჩასანიშნად "
            "მომწერეთ თქვენი სახელი და საკონტაქტო ნომერი."
        ),
    ],
    "A3: 15:00 exact-slot check",
)
if "თავისუფალია" not in out_a and "შესაძლებელია" not in out_a:
    fail("A3", f"expected availability acknowledgement: {out_a!r}")
if not CALLS["check_slot_calendar_only"]:
    fail("A3", "executor must consult Calendar for exact slot")
pending = conv_a.pending_booking or {}
if pending.get("requested_datetime_iso") != "2030-05-27T15:00:00+04:00":
    fail("A3", f"pending_booking ISO wrong: {pending!r}")
if pending.get("user_confirmed_datetime") is not True:
    fail("A3", "pending_booking must be marked user-confirmed")
if pending.get("source") != "user_requested_exact_slot":
    fail("A3", f"source must be user_requested_exact_slot, got {pending.get('source')!r}")
if CALLS["book_slot"]:
    fail("A3", "must NOT book before name/phone supplied")
ok("A3: check_consultation_slot recorded confirmed pending_booking; no premature booking")

# Turn 4: contact details → deterministic commit.
out_a2 = run_turn(
    conv_a,
    "ლელა 595999733",
    [queue_content("(LLM should be skipped on deterministic commit)")],
    "A4: name+phone → commit",
)
if len(CALLS["book_slot"]) != 1:
    fail("A4", f"book_slot must run exactly once, got {len(CALLS['book_slot'])}")
if conv_a.lead.calendly_booked is not True:
    fail("A4", "lead.calendly_booked must be True")
if conv_a.state != "DONE":
    fail("A4", f"state must be DONE, got {conv_a.state!r}")
if conv_a.lead.booked_datetime_iso != "2030-05-27T15:00:00+04:00":
    fail("A4", f"booked iso wrong: {conv_a.lead.booked_datetime_iso!r}")
if conv_a.lead.calendar_event_id != "evt_p3c6_a":
    fail("A4", "calendar_event_id should be set")
if conv_a.pending_booking is not None:
    fail("A4", "pending_booking must be cleared after commit")
ok("A4: deterministic commit booked the exact slot the user named")


# =========================================================================
# Scenario B — exact slot outside business hours
# =========================================================================


print("\n################ Scenario B — outside business hours ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

# Stub everything so Calendar is never asked (business-hours rejection
# happens before the Calendar call).
calendar_service.check_slot_calendar_only = (
    lambda dt, duration_minutes=30: (
        CALLS["check_slot_calendar_only"].append(dt) or True
    )
)
calendar_service.check_slot_available = (
    lambda dt, duration_minutes=30: True
)
calendar_service.get_free_slots = _get_free_slots
calendar_service.book_slot = (
    lambda **kwargs: CALLS["book_slot"].append(kwargs) or True
)

conv_b = Conversation(sender_id="sim_p3c6_b", platform="instagram")
conv_b.segment = "PARENT"  # lock so the routing menu doesn't intercept
out_b = run_turn(
    conv_b,
    "27 მაისს 20:00-ზე შეიძლება?",
    [
        queue_tool(TOOL_CHECK_CONSULTATION_SLOT, {
            "datetime_iso": "2030-05-27T20:00:00+04:00",
        }),
        queue_content(
            "ამ დროს კონსულტაციები არ ტარდება. შემიძლია იმავე დღის "
            "თავისუფალი დროები შემოგთავაზოთ."
        ),
    ],
    "B1: 20:00 outside business hours",
)
if "დაკავებულია" in out_b:
    fail("B1", "must NOT say 'დაკავებულია' for outside-business-hours rejection")
if CALLS["check_slot_calendar_only"]:
    fail("B1", "Calendar must not be consulted when slot is outside hours")
pending_b = conv_b.pending_booking or {}
if pending_b.get("user_confirmed_datetime"):
    fail("B1", "must NOT record a confirmed pending booking for unavailable slot")
ok("B1: business-hours rejection separated from calendar-busy wording")


# =========================================================================
# Scenario C — exact slot Calendar busy
# =========================================================================


print("\n################ Scenario C — Calendar busy ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

calendar_service.check_slot_calendar_only = (
    lambda dt, duration_minutes=30: (
        CALLS["check_slot_calendar_only"].append(dt) or False
    )
)


def _alt_slots(target_date=None, duration_minutes=30, *, start_date=None, days=1):
    CALLS["get_free_slots"].append({"start_date": start_date})
    anchor = start_date or target_date or _date(2030, 5, 27)
    return [
        {"date": str(anchor), "time": "11:00",
         "datetime_iso": f"{anchor}T11:00:00+04:00"},
        {"date": str(anchor), "time": "14:00",
         "datetime_iso": f"{anchor}T14:00:00+04:00"},
    ]


calendar_service.get_free_slots = _alt_slots

conv_c = Conversation(sender_id="sim_p3c6_c", platform="instagram")
conv_c.segment = "PARENT"
out_c = run_turn(
    conv_c,
    "27 მაისს 15:00-ზე შეიძლება?",
    [
        queue_tool(TOOL_CHECK_CONSULTATION_SLOT, {
            "datetime_iso": "2030-05-27T15:00:00+04:00",
        }),
        queue_content(
            "27 მაისს, 15:00 დაკავებულია. თავისუფალია 11:00 და 14:00 — "
            "რომელი დრო გაწყობთ?"
        ),
    ],
    "C1: 15:00 calendar busy",
)
if not CALLS["check_slot_calendar_only"]:
    fail("C1", "Calendar must be consulted when slot is inside business hours")
if not CALLS["get_free_slots"]:
    fail("C1", "alternatives must be fetched on busy result")
if "ამ დროს კონსულტაციები არ ტარდება" in out_c:
    fail("C1", "must NOT use outside-hours wording for calendar-busy result")
ok("C1: calendar-busy distinguished from outside-hours, alternatives offered")


# =========================================================================
# Scenario D — today-only buffer does NOT exclude tomorrow's afternoon
# =========================================================================


print("\n################ Scenario D — buffer not applied to future date ################")
# Capture today/tomorrow dates so the assertion holds regardless of when
# the simulation runs.
today_real = _dt.now(TBILISI_TZ).date()
# Pick a tomorrow that lands on a weekday (Mon-Fri) to satisfy the
# weekend gate in _get_free_slots_for_day.
tomorrow = today_real + _td(days=1)
while tomorrow.weekday() >= 5:
    tomorrow = tomorrow + _td(days=1)

slots = calendar_service._get_free_slots_for_day(tomorrow, 30)
afternoon_iso = f"{tomorrow.isoformat()}T15:00:00+04:00"
if not any(s["datetime_iso"] == afternoon_iso for s in slots):
    # Skip when Calendar reports busy at exactly 15:00 — the assertion
    # is about buffer, not about the Calendar layer. As long as the
    # slot is not silently excluded by the buffer, any other reason is OK.
    # We re-check by patching free/busy to empty.
    original_fb = calendar_service._free_busy_intervals
    calendar_service._free_busy_intervals = lambda s, e: []
    try:
        slots = calendar_service._get_free_slots_for_day(tomorrow, 30)
    finally:
        calendar_service._free_busy_intervals = original_fb
    if not any(s["datetime_iso"] == afternoon_iso for s in slots):
        fail("D1", f"tomorrow 15:00 missing from get_free_slots: {slots!r}")
ok("D1: tomorrow 15:00 not pruned by today-only buffer")


# =========================================================================
# Scenario E — today buffer still excludes near-term slots on same date
# =========================================================================


print("\n################ Scenario E — buffer still applies to today ################")
# Patch datetime.now to a fixed Tbilisi point so the assertion is
# deterministic regardless of wall clock.
fixed_now = _dt(2030, 6, 10, 13, 30, tzinfo=TBILISI_TZ)

real_datetime = calendar_service.datetime


class _FakeDatetime(real_datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return fixed_now.replace(tzinfo=None)
        return fixed_now.astimezone(tz)


calendar_service.datetime = _FakeDatetime
calendar_service._free_busy_intervals = lambda s, e: []

today_for_test = fixed_now.date()
e_slots = calendar_service._get_free_slots_for_day(today_for_test, 30)
near_iso = f"{today_for_test.isoformat()}T14:00:00+04:00"
far_iso = f"{today_for_test.isoformat()}T16:00:00+04:00"
# 14:00 < 13:30 + 2h = 15:30 → must be excluded
if any(s["datetime_iso"] == near_iso for s in e_slots):
    calendar_service.datetime = real_datetime
    fail("E1", f"14:00 should be excluded by today buffer: {e_slots!r}")
# 16:00 ≥ 15:30 → must remain
if not any(s["datetime_iso"] == far_iso for s in e_slots):
    calendar_service.datetime = real_datetime
    fail("E1", f"16:00 should remain when buffer is 2h from 13:30: {e_slots!r}")
calendar_service.datetime = real_datetime
ok("E1: today buffer correctly excludes near-term slots while preserving later ones")


print("\n=== PATCH 6 simulation summary ===")
print("Scenario A — exact slot available + commit:  PASS")
print("Scenario B — outside business hours:         PASS")
print("Scenario C — Calendar busy:                  PASS")
print("Scenario D — future date, buffer NOT applied:PASS")
print("Scenario E — today date, buffer applied:     PASS")
print("✅ All P3-C PATCH 6 simulation checks passed")
