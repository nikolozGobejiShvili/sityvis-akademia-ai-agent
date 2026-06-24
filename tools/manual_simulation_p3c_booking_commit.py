"""P3-C PATCH 5 — booking commit + modality preservation transcript.

Reproduces the live booking-gap bug end-to-end with all external
services mocked. Assertions verify:

  * The opener asks age without dumping facts.
  * The age + challenge get saved on the lead.
  * Asking price + dates is answered without re-asking age.
  * Asking 15:00 on 27 May → date-aware get_available_slots; LLM
    offers alternatives. No booking yet.
  * The user says "13:00 საათზე იყოს" — backend records pending_booking
    with `requested_datetime_iso` matching the 13:00 alternative, and
    `user_confirmed_datetime=True`.
  * The user asks the modality question — the LLM answers
    phone/video without clearing pending_booking, and no
    "დაგიბარებთ" leaks through.
  * The user sends "ნიკოლოზი 595999733" — backend commits the
    booking *deterministically* (no reliance on the LLM):
      - `calendar_service.book_slot` is called once.
      - `sheets_service.create_lead` is called once.
      - `notification_service.send_manager_notification` is called.
      - `lead.calendly_booked == True`, `state == "DONE"`,
        `pending_booking is None`.
      - `lead.challenge` ("ეკრანისგან დისტანცია") is preserved.
      - Final response contains booking confirmation language that is
        allowed by the strengthened guard (tool success bit set).
      - No "დაგიბარებთ" / "რომ სწორად გითხრათ" / "გაგივლით" in any
        bot reply.

Run::

    python tools/manual_simulation_p3c_booking_commit.py
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
from app.agent.tools.parent_tools import (  # noqa: E402
    TOOL_BOOK_CONSULTATION,
    TOOL_GET_AVAILABLE_SLOTS,
    TOOL_GET_CAMP_INFO,
    TOOL_SAVE_LEAD_INFO,
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

# Engine on for this simulation only.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=True,
)

conversation_service.conversations.clear()
parent_turn_router.manager_offer_shown.clear()
parent_flow.available_slots.clear()
parent_flow.ask_name_retries.clear()
parent_flow.invalid_phone_retries.clear()
parent_flow.slots_shown_for_state.clear()
parent_tool_executor.reset_state()


CALLS: dict[str, list[Any]] = {
    "chat_with_tools": [],
    "system_blocks": [],
    "book_slot": [],
    "create_lead": [],
    "send_manager_notification": [],
    "get_free_slots": [],
    "check_slot_available": [],
}


# Step 5 mocks 15:00 as busy and 13:00 as free.
BUSY_HOURS = {"15:00"}


def _check_slot_available(dt):
    CALLS["check_slot_available"].append(dt)
    hh_mm = dt.strftime("%H:%M") if hasattr(dt, "strftime") else ""
    return hh_mm not in BUSY_HOURS


def _get_free_slots(target_date=None, duration_minutes=30, *, start_date=None, days=1):
    CALLS["get_free_slots"].append({
        "target_date": target_date,
        "start_date": start_date,
        "days": days,
    })
    anchor = start_date or target_date
    if anchor is not None:
        # 13:00 and 16:00 free on the requested date.
        return [
            {"date": str(anchor), "time": "13:00",
             "datetime_iso": f"{anchor}T13:00:00+04:00"},
            {"date": str(anchor), "time": "16:00",
             "datetime_iso": f"{anchor}T16:00:00+04:00"},
        ]
    return []


calendar_service.check_slot_available = _check_slot_available
calendar_service.get_free_slots = _get_free_slots
calendar_service.book_slot = (
    lambda **kwargs: (
        CALLS["book_slot"].append(kwargs)
        or setattr(kwargs["lead"], "calendar_event_id", "evt_sim_p3c5")
        or True
    )
)
sheets_service.create_lead = (
    lambda lead: CALLS["create_lead"].append(lead.conversation_summary) or True
)
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append(summary) or True
)
openai_service._chat_completion = lambda **kwargs: "ქართული რეზიუმე."
openai_service.detect_start_intent = lambda m: "GREETING"

# Profile fetch should NEVER crash booking even with v19 400 error.
def _profile_explodes(sid, plat):
    raise RuntimeError("Graph API v19 returned 400 (simulated)")


messenger_service.get_user_profile = _profile_explodes


def _mk_response(*, content: str = "", tool_calls=None):
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


def run_turn(
    conversation: Conversation,
    user_message: str,
    steps: list[dict[str, Any]],
    label: str,
) -> str:
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


def fail(label: str, msg: str) -> None:
    print(f"❌ {label}: {msg}")
    raise SystemExit(1)


def ok(label: str) -> None:
    print(f"✅ {label}")


def assert_clean_wording(response: str, label: str) -> None:
    """No PATCH 5 forbidden phrases must leak past the sanitiser."""
    for forbidden in (
        "დაგიბაროთ",
        "დაგიბარებთ",
        "რომ სწორად გითხრათ",
        "გაგივლით",
    ):
        if forbidden in response:
            fail(label, f"forbidden wording leaked: {forbidden!r}")


# -- script ----------------------------------------------------------------


conversation = Conversation(sender_id="sim_p3c_commit", platform="instagram")


# Turn 1 — camp interest opening.
out = run_turn(
    conversation,
    "საზაფხულო ბანაკი",
    [queue_content(
        "სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა. რამდენი წლისაა "
        "თქვენი შვილი?"
    )],
    "1: opener",
)
assert_clean_wording(out, "1")
if "ასაკი" not in out and "წლისაა" not in out:
    fail("1", "should ask age")
ok("1: clean opener + age question")


# Turn 2 — age 14.
out = run_turn(
    conversation,
    "14 წლის",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"child_age": "14"}),
        queue_content(
            "14 წელი კარგი ასაკია. რას ელოდებით ბანაკისგან?"
        ),
    ],
    "2: age 14",
)
assert_clean_wording(out, "2")
if conversation.lead.child_age != "14":
    fail("2", f"expected child_age=14, got {conversation.lead.child_age!r}")
ok("2: age saved + motivation question")


# Turn 3 — challenge.
out = run_turn(
    conversation,
    "ეკრანისგან დისტანცია",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"challenge": "ეკრანისგან დისტანცია"}),
        queue_content(
            "ეს გასაგებია. ბანაკი ამ მიმართულებით ეხმარება ბავშვებს."
        ),
    ],
    "3: challenge saved",
)
assert_clean_wording(out, "3")
if conversation.lead.challenge != "ეკრანისგან დისტანცია":
    fail("3", f"expected challenge saved, got {conversation.lead.challenge!r}")
ok("3: challenge saved + value mechanism")


# Turn 4 — price + dates.
out = run_turn(
    conversation,
    "ფასი მაინტერესებს და როდის არის ბანაკი?",
    [
        queue_tool(TOOL_GET_CAMP_INFO, {"topic": "all"}),
        queue_content(
            "ბანაკის ფასი 2150 ლარია. ნაკადებია 23–29 ივნისი, 5–11 ივლისი და "
            "14–20 ივლისი. თუ გსურთ, კონსულტაციაზე ჩაგწერთ."
        ),
    ],
    "4: price + dates",
)
assert_clean_wording(out, "4")
if "რამდენი წლისაა" in out:
    fail("4", "must not re-ask known age")
ok("4: facts + soft CTA, no re-asked age")


# Turn 5 — request 27 May 15:00 (busy) → alternatives shown.
CALLS["get_free_slots"].clear()
out = run_turn(
    conversation,
    "კი მინდა ჩაწერა 27 მაისს 3 საათზე თუა შესაძლებელი",
    [
        queue_tool(TOOL_GET_AVAILABLE_SLOTS, {"date_iso": "2030-05-27"}),
        queue_content(
            "27 მაისს 15:00 თავისუფლად არ ჩანს. ხელმისაწვდომია 13:00 და "
            "16:00 — რომელი დრო გაწყობთ?"
        ),
    ],
    "5: 15:00 busy → alternatives",
)
assert_clean_wording(out, "5")
if not CALLS["get_free_slots"]:
    fail("5", "expected get_free_slots called with the requested date")
if not CALLS["chat_with_tools"]:
    fail("5", "expected LLM was consulted")
if CALLS["book_slot"]:
    fail("5", "must NOT book before user picks an alternative")
ok("5: alternatives offered, no booking yet")


# Turn 6 — user picks 13:00. Backend must record pending_booking with
# user_confirmed_datetime=true; LLM asks for missing name/phone.
out = run_turn(
    conversation,
    "13:00 საათზე იყოს",
    [queue_content(
        "კარგი, 27 მაისს 13:00 საათისთვის ჩასანიშნად მომწერეთ თქვენი "
        "სახელი და საკონტაქტო ნომერი."
    )],
    "6: select 13:00",
)
assert_clean_wording(out, "6")
pending = conversation.pending_booking or {}
if not pending.get("user_confirmed_datetime"):
    fail("6", f"pending_booking should be user-confirmed, got {pending!r}")
if pending.get("requested_datetime_iso") != "2030-05-27T13:00:00+04:00":
    fail("6", f"pending_booking iso wrong: {pending.get('requested_datetime_iso')!r}")
if pending.get("source") != "user_selected_slot":
    fail("6", f"pending_booking source wrong: {pending.get('source')!r}")
if "name" not in pending.get("missing_fields", []):
    fail("6", "expected 'name' in missing_fields")
if "phone" not in pending.get("missing_fields", []):
    fail("6", "expected 'phone' in missing_fields")
if CALLS["book_slot"]:
    fail("6", "must NOT book yet — no name/phone")
ok("6: pending_booking recorded, user_confirmed=true, no booking yet")


# Turn 7 — modality question. Pending must persist, no fake booking.
out = run_turn(
    conversation,
    "ადგილზე ხდება კონსულტაცია თუ ტელეფონით?",
    [queue_content(
        "კონსულტაცია ძირითადად ტელეფონით ან ვიდეოზარით ტარდება. 27 მაისს "
        "13:00 საათისთვის ჩასანიშნად მომწერეთ თქვენი სახელი და საკონტაქტო "
        "ნომერი."
    )],
    "7: modality question",
)
assert_clean_wording(out, "7")
if conversation.pending_booking is None:
    fail("7", "pending_booking must survive modality question")
if conversation.pending_booking.get("requested_datetime_iso") != "2030-05-27T13:00:00+04:00":
    fail("7", "pending_booking datetime drifted across modality question")
if CALLS["book_slot"]:
    fail("7", "must NOT book before user provides name/phone")
ok("7: pending preserved, modality answered, still no booking")


# Turn 8 — user provides name + phone. Backend should commit the
# booking deterministically (no reliance on the LLM call).
out = run_turn(
    conversation,
    "ნიკოლოზი 595999733",
    [queue_content(
        "(this LLM step should NOT be consulted on a deterministic commit)"
    )],
    "8: name + phone → commit",
)
assert_clean_wording(out, "8")

if len(CALLS["book_slot"]) != 1:
    fail("8", f"book_slot expected 1 call, got {len(CALLS['book_slot'])}")
if len(CALLS["create_lead"]) < 1:
    fail("8", "sheets create_lead should have fired")
if not CALLS["send_manager_notification"]:
    fail("8", "manager notification should have fired")
if conversation.lead.calendly_booked is not True:
    fail("8", "lead.calendly_booked must be True after commit")
if conversation.state != "DONE":
    fail("8", f"state must be DONE, got {conversation.state!r}")
if conversation.pending_booking is not None:
    fail("8", "pending_booking must be cleared after commit")
if not conversation.lead.booked_datetime_iso:
    fail("8", "booked_datetime_iso must be set")
if not conversation.lead.calendar_event_id:
    fail("8", "calendar_event_id must be set by Calendar mock")
if conversation.lead.challenge != "ეკრანისგან დისტანცია":
    fail("8", f"challenge lost: {conversation.lead.challenge!r}")
if conversation.lead.phone != "595999733":
    fail("8", f"phone mis-stored: {conversation.lead.phone!r}")
if "ნიკოლოზ" not in (conversation.lead.name or ""):
    fail("8", f"name not captured: {conversation.lead.name!r}")
# Final response must reference booking (subjunctive/past-tense allowed
# because the guard checks tool_success_this_turn).
if not any(kw in out for kw in ("ჩაგინიშნე", "ჩანიშნულ", "13:00", "მენეჯერი")):
    fail("8", f"final response should acknowledge booking: {out!r}")
ok("8: booking committed deterministically, lead+state+pending all correct")


# -- end summary ----------------------------------------------------------


print("\n=== Summary ===")
print(f"chat_with_tools calls:      {len(CALLS['chat_with_tools'])}")
print(f"get_free_slots calls:       {len(CALLS['get_free_slots'])}")
print(f"check_slot_available calls: {len(CALLS['check_slot_available'])}")
print(f"book_slot calls:            {len(CALLS['book_slot'])}")
print(f"create_lead calls:          {len(CALLS['create_lead'])}")
print(f"manager_notify calls:       {len(CALLS['send_manager_notification'])}")
print(f"lead.name:                  {conversation.lead.name!r}")
print(f"lead.phone:                 {conversation.lead.phone!r}")
print(f"lead.child_age:             {conversation.lead.child_age!r}")
print(f"lead.challenge:             {conversation.lead.challenge!r}")
print(f"lead.calendly_booked:       {conversation.lead.calendly_booked!r}")
print(f"lead.booked_datetime_iso:   {conversation.lead.booked_datetime_iso!r}")
print(f"lead.calendar_event_id:     {conversation.lead.calendar_event_id!r}")
print(f"conversation.state:         {conversation.state!r}")
print(f"conversation.pending_booking: {conversation.pending_booking!r}")
print("✅ All P3-C PATCH 5 simulation checks passed")
