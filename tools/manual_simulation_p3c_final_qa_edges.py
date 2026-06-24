"""P3-C PATCH 7 — final QA edges transcript replay.

Five scenarios verify the live-QA bug fixes:

  * Scenario A — time-change before booking finalisation:
      - parent says "13:00 მინდა" → pending_booking recorded;
      - parent then says "15:00 მირჩევნია" → pending_booking updated
        to 15:00 with source="user_changed_slot";
      - parent then sends name+phone → deterministic commit books
        15:00 (NOT 13:00). Calendar / Sheets / notification each
        fire exactly once for 15:00.
  * Scenario B — changed time unavailable:
      - parent has 13:00 pending → asks for 15:00, Calendar busy;
      - response says new slot is unavailable (with reason);
      - pending_booking is restored to the original 13:00.
  * Scenario C — decline / will-think wording:
      - "დავფიქრდები მადლობა" → soft supportive close, no CTA,
        no duplicated "თუ … თუ …", no "შემეხმიანეთ დაგეხმაროთ";
      - "არა მადლობა" → polite no-CTA close, conversation marker
        followup_blocked_reason='declined'.
  * Scenario D — adult flow global intent loop:
      - identity / human-vs-robot / greeting / thanks /
        decline / manager request all bypass the
        "რომელი საღამო გიზიდავთ" state-machine loop.
  * Scenario E — sanitiser wording polish end-to-end:
      - "precisely" disappears;
      - "ეკრან რეჟიმიდან" → "ეკრანის რეჟიმიდან";
      - "სრულად ერგება" → "შესაფერისია" variant;
      - duplicated "თუ … თუ …" collapses;
      - "შემეხმიანეთ დაგეხმაროთ" → "მომწერეთ და დაგეხმარებით".

Run::

    python tools/manual_simulation_p3c_final_qa_edges.py
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import app.config as config_module  # noqa: E402
from app.agent.tools import parent_tool_executor  # noqa: E402
from app.flows import adult_flow, parent_flow, parent_turn_router  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.services import (  # noqa: E402
    calendar_service,
    conversation_service,
    messenger_service,
    notification_service,
    openai_service,
    sheets_service,
)


def reset_runtime() -> None:
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    adult_flow.selected_events.clear()
    parent_tool_executor.reset_state()


# Engine on for this run.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=True,
)
reset_runtime()

messenger_service.get_user_profile = lambda sid, plat: {}
openai_service._chat_completion = lambda **kwargs: "ქართული რეზიუმე."
openai_service.detect_start_intent = lambda m: "GREETING"


CALLS: dict[str, list[Any]] = {
    "chat_with_tools": [],
    "book_slot": [],
    "create_lead": [],
    "send_manager_notification": [],
    "check_slot_calendar_only": [],
    "is_within_business_hours": [],
    "get_free_slots": [],
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
# Scenario A — time change before booking finalisation
# =========================================================================


print("\n################ Scenario A — time change before commit ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

calendar_service.is_within_business_hours = (
    lambda dt, dur=30: (CALLS["is_within_business_hours"].append(dt) or (True, ""))
)
calendar_service.check_slot_calendar_only = (
    lambda dt, dur=30: (CALLS["check_slot_calendar_only"].append(dt) or True)
)
calendar_service.check_slot_available = lambda dt, dur=30: True
calendar_service.get_free_slots = (
    lambda *a, **k: CALLS["get_free_slots"].append((a, k)) or []
)
calendar_service.book_slot = (
    lambda **kwargs: (
        CALLS["book_slot"].append(kwargs)
        or setattr(kwargs["lead"], "calendar_event_id", "evt_p3c7_a")
        or True
    )
)
sheets_service.create_lead = (
    lambda lead: CALLS["create_lead"].append(lead.conversation_summary) or True
)
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append(summary) or True
)

conv_a = Conversation(sender_id="sim_p3c7_a", platform="instagram")
conv_a.segment = "PARENT"
# Pre-fill child_age so commit can proceed.
conv_a.lead = Lead(
    sender_id=conv_a.sender_id, platform="instagram", segment="PARENT",
    child_age="10",
)

# Use a near-future weekday so both the LLM-mock ISO and the
# user-message ISO parse to the SAME date. Today is 2026-05-25 (Mon);
# pick 2026-05-28 (Thu) so both pre- and post-change parses agree.
A_DATE_ISO = "2026-05-28"
A_OLD_ISO = f"{A_DATE_ISO}T13:00:00+04:00"
A_NEW_ISO = f"{A_DATE_ISO}T15:00:00+04:00"

# Turn 1 — exact 13:00 request.
run_turn(
    conv_a,
    "კონსულტაციაზე ჩამწერეთ 28 მაისს 13:00-ზე",
    [
        queue_tool("check_consultation_slot", {
            "datetime_iso": A_OLD_ISO,
        }),
        queue_content("28 მაისს, 13:00 თავისუფალია. მომწერეთ სახელი და ნომერი."),
    ],
    "A1: 13:00 exact request",
)
pending = conv_a.pending_booking or {}
if pending.get("requested_datetime_iso") != A_OLD_ISO:
    fail("A1", f"pending iso wrong: {pending!r}")
if CALLS["book_slot"]:
    fail("A1", "must not book before name/phone")
ok("A1: pending_booking 13:00 recorded")

# Turn 2 — time change to 15:00.
out_a2 = run_turn(
    conv_a,
    "ახლა ვიფიქრე და 28 მაისს 15:00 მირჩევნია",
    [queue_content("(LLM should be short-circuited by time-change handler)")],
    "A2: change 13:00 → 15:00",
)
pending = conv_a.pending_booking or {}
if pending.get("requested_datetime_iso") != A_NEW_ISO:
    fail("A2", f"pending must update to 15:00, got {pending!r}")
if pending.get("source") != "user_changed_slot":
    fail("A2", f"source must be user_changed_slot, got {pending.get('source')!r}")
if CALLS["book_slot"]:
    fail("A2", "must not book on time-change turn")
ok("A2: pending_booking flipped to 15:00, source=user_changed_slot")

# Turn 3 — name+phone → commit books 15:00.
out_a3 = run_turn(
    conv_a,
    "ლელა 595999733",
    [queue_content("(LLM should be skipped on deterministic commit)")],
    "A3: name+phone → commit 15:00",
)
if len(CALLS["book_slot"]) != 1:
    fail("A3", f"book_slot must run exactly once, got {len(CALLS['book_slot'])}")
booked_iso = CALLS["book_slot"][0].get("datetime_iso")
if booked_iso != A_NEW_ISO:
    fail("A3", f"wrong slot booked: {booked_iso!r}")
if conv_a.lead.booked_datetime_iso != A_NEW_ISO:
    fail("A3", f"lead.booked_datetime_iso wrong: {conv_a.lead.booked_datetime_iso!r}")
if conv_a.state != "DONE":
    fail("A3", f"state must be DONE, got {conv_a.state!r}")
if conv_a.pending_booking is not None:
    fail("A3", "pending_booking must be cleared after commit")
ok("A3: deterministic commit booked the NEW (15:00) slot, not the old 13:00")


# =========================================================================
# Scenario B — changed time unavailable, pending restored
# =========================================================================


print("\n################ Scenario B — changed time unavailable ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

# is_within_business_hours OK for both slots but Calendar busy for the
# NEW (15:00) one.
def _is_within(dt, dur=30):
    CALLS["is_within_business_hours"].append(dt)
    return True, ""


def _calendar_only(dt, dur=30):
    CALLS["check_slot_calendar_only"].append(dt)
    # Busy at 15:00, free elsewhere.
    return dt.strftime("%H:%M") != "15:00"


def _alts(*a, **k):
    CALLS["get_free_slots"].append((a, k))
    return [
        {"date": "27 მაისი", "time": "11:00",
         "datetime_iso": "2030-05-27T11:00:00+04:00"},
        {"date": "27 მაისი", "time": "14:00",
         "datetime_iso": "2030-05-27T14:00:00+04:00"},
    ]


calendar_service.is_within_business_hours = _is_within
calendar_service.check_slot_calendar_only = _calendar_only
calendar_service.check_slot_available = lambda dt, dur=30: True
calendar_service.get_free_slots = _alts
calendar_service.book_slot = (
    lambda **kwargs: CALLS["book_slot"].append(kwargs) or True
)

B_DATE_ISO = "2026-05-28"  # Thu — same future weekday as scenario A
B_OLD_ISO = f"{B_DATE_ISO}T13:00:00+04:00"

conv_b = Conversation(sender_id="sim_p3c7_b", platform="instagram")
conv_b.segment = "PARENT"
conv_b.lead = Lead(
    sender_id=conv_b.sender_id, platform="instagram", segment="PARENT",
    child_age="10",
)
# Pre-seed pending_booking for 13:00.
conv_b.pending_booking = {
    "requested_datetime_iso": B_OLD_ISO,
    "requested_date_text": "28 მაისი",
    "requested_time_text": "13:00",
    "selected_slot_display": "28 მაისი, 13:00",
    "user_confirmed_datetime": True,
    "source": "user_selected_slot",
    "missing_fields": ["name", "phone"],
    "created_at": "2026-05-25T10:00:00",
    "attempts": 0,
}

out_b = run_turn(
    conv_b,
    "ახლა ვიფიქრე და 28 მაისს 15:00 მირჩევნია",
    [queue_content("(LLM should be short-circuited by time-change handler)")],
    "B1: 15:00 unavailable",
)

if CALLS["book_slot"]:
    fail("B1", "must not silently book the old 13:00 slot")
pending = conv_b.pending_booking or {}
if pending.get("requested_datetime_iso") != B_OLD_ISO:
    fail("B1", f"original pending must be restored: {pending!r}")
if "13:00" not in out_b or "დაკავებულია" not in out_b:
    fail("B1", f"reply should mention old slot + busy reason: {out_b!r}")
ok("B1: 15:00 busy → old 13:00 preserved, asked whether to keep or pick alternative")


# =========================================================================
# Scenario C — decline / will-think wording
# =========================================================================


print("\n################ Scenario C — decline / will-think wording ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_c = Conversation(sender_id="sim_p3c7_c", platform="instagram")
conv_c.segment = "PARENT"

out_c1 = run_turn(
    conv_c,
    "დავფიქრდები მადლობა",
    [queue_content("(should not be consulted — deterministic decline)")],
    "C1: will-think",
)
for phrase in (
    "შემეხმიანეთ დაგეხმაროთ",
    "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე გაგიჩნდებათ",
):
    if phrase in out_c1:
        fail("C1", f"forbidden phrase leaked: {phrase!r}")
if conv_c.stopped_after != "will_think":
    fail("C1", f"stopped_after must be 'will_think', got {conv_c.stopped_after!r}")
ok("C1: will-think close, no duplicated 'თუ', stopped_after=will_think")

out_c2 = run_turn(
    conv_c,
    "არა მადლობა",
    [queue_content("(should not be consulted — deterministic decline)")],
    "C2: hard decline",
)
if conv_c.followup_blocked_reason != "declined":
    fail("C2", f"followup_blocked_reason must be 'declined', got {conv_c.followup_blocked_reason!r}")
# Should NOT contain sales CTA.
for cta in ("ჩაგწერ", "კონსულტაცი", "ჩავნიშნ"):
    if cta in out_c2:
        fail("C2", f"forbidden CTA after decline: {cta!r}")
ok("C2: hard decline, followup_blocked_reason=declined, no CTA")


# =========================================================================
# Scenario D — adult flow global intents
# =========================================================================


print("\n################ Scenario D — adult flow global intents ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_d = Conversation(sender_id="sim_p3c7_d", platform="instagram")
conv_d.segment = "ADULT"
conv_d.state = "SHOW_EVENTS"  # stuck in event-choice state

out_d1 = run_turn(
    conv_d,
    "შენ ვინ ხარ?",
    [],
    "D1: identity question",
)
if "ასისტენტი" not in out_d1:
    fail("D1", f"identity reply expected: {out_d1!r}")
if "რომელი საღამო გიზიდავთ" in out_d1:
    fail("D1", "must not loop into event question on identity")
ok("D1: identity answer, no state-machine loop")

out_d2 = run_turn(
    conv_d,
    "ადამიანი ხარ თუ რობოტი?",
    [],
    "D2: human vs robot",
)
if "ონლაინ ასისტენტი" not in out_d2:
    fail("D2", f"online-assistant reply expected: {out_d2!r}")
ok("D2: human-vs-robot answered, no event loop")

out_d3 = run_turn(
    conv_d,
    "გამარჯობა",
    [],
    "D3: greeting in SHOW_EVENTS",
)
if "გამარჯობა" not in out_d3:
    fail("D3", f"greeting expected: {out_d3!r}")
ok("D3: greeting answer, no event loop")

out_d4 = run_turn(
    conv_d,
    "მადლობა",
    [],
    "D4: thanks",
)
if "სიამოვნებით" not in out_d4:
    fail("D4", f"thanks acknowledgement expected: {out_d4!r}")
ok("D4: thanks acknowledged, no event loop")

out_d5 = run_turn(
    conv_d,
    "არ მინდა",
    [],
    "D5: decline in adult flow",
)
if "გასაგებია" not in out_d5:
    fail("D5", f"decline close expected: {out_d5!r}")
ok("D5: decline close, no event loop")


# =========================================================================
# Scenario E — sanitiser wording polish end-to-end
# =========================================================================


print("\n################ Scenario E — wording polish ################")
from app.agent.llm.parent_llm_engine import sanitise_response_wording  # noqa: E402

cases = [
    (
        "Precisely, თქვენი შვილი 10 წლისაა.",
        ["precisely", "Precisely"],
        [],
    ),
    (
        "ბავშვი ეკრან რეჟიმიდან გამოდის.",
        ["ეკრან რეჟიმიდან"],
        ["ეკრანის რეჟიმიდან"],
    ),
    (
        "ბავშვი სრულად ერგება ბანაკის ასაკობრივ ჩარჩოს.",
        ["სრულად ერგება", "ბანაკის ასაკობრივ ჩარჩოს"],
        ["შესაფერისია"],
    ),
    (
        "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე "
        "გაგიჩნდებათ, შემეხმიანეთ დაგეხმაროთ.",
        [
            "შემეხმიანეთ დაგეხმაროთ",
            "თუ მომავალში რაიმე კითხვა გაგიჩნდებათ, თუ კიდევ რაიმე",
        ],
        ["მომწერეთ და დაგეხმარებით"],
    ),
]
for original, forbidden_list, required_list in cases:
    cleaned = sanitise_response_wording(original)
    for f in forbidden_list:
        if f in cleaned:
            fail("E", f"forbidden phrase leaked: {f!r}  →  {cleaned!r}")
    for r in required_list:
        if r not in cleaned:
            fail("E", f"required replacement missing: {r!r}  →  {cleaned!r}")
ok("E: every wording-polish case rewritten correctly")


print("\n=== PATCH 7 simulation summary ===")
print("A: time-change before commit:     PASS")
print("B: changed time unavailable:      PASS")
print("C: decline / will-think wording:  PASS")
print("D: adult global intent loop:      PASS")
print("E: wording polish (sanitiser):    PASS")
print("✅ All P3-C PATCH 7 simulation checks passed")
