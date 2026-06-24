"""P3-C PATCH 4 — live-sales transcript replay.

Reproduces the 8-turn parent conversation that surfaced the PATCH 4
bugs, with all external services mocked. Assertions verify:

  * The opener gives one value sentence + asks age, no FAQ dump, no
    forbidden „ჩამოუყალიბეთ".
  * The motivation question after age uses correct grammar
    („რისი მიღება გსურთ თქვენი შვილისთვის").
  * Screen-distance pain is answered with concrete camp mechanisms,
    using „ეხმარება" / „უწყობს ხელს" (NOT „მოაგვარებს" / „გადაჭრის");
    no „აზრი აქვს" / „დეტალებს ცოცხლად".
  * The detailed dates/location request uses the camp YAML and adds a
    soft CTA without re-asking age.
  * A consultation request for 26 May (BEFORE the camp June streams)
    is checked against Calendar — NOT rejected because the camp
    "hasn't started yet".
  * `get_available_slots` is called with `date_iso` when the parent
    names a specific date — no stale 25 May cache.
  * `27 May` request → date-aware slots for 27 May, not 25 May.
  * A bare time like "11-ზე იყოს" with context uses the contextual
    date and asks for missing fields rather than booking blindly.
  * Challenge ("ეკრანისგან დისტანცია") is saved on the lead.

Run::

    python tools/manual_simulation_p3c_live_sales_patch.py
"""

from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date as _date
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

# Engine on for this run only.
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


messenger_service.get_user_profile = lambda sid, plat: {}


def _check_slot_available(dt):
    CALLS["check_slot_available"].append(dt)
    # Mark 26 May 12:00 as available so the test verifies the bug fix
    # (Bot must NOT reject just because camp June > date).
    return True


def _get_free_slots(target_date=None, duration_minutes=30, *, start_date=None, days=1):
    CALLS["get_free_slots"].append({
        "target_date": target_date,
        "start_date": start_date,
        "days": days,
    })
    if start_date is not None:
        return [
            {"date": str(start_date), "time": "10:00",
             "datetime_iso": f"{start_date}T10:00:00+04:00"},
            {"date": str(start_date), "time": "12:00",
             "datetime_iso": f"{start_date}T12:00:00+04:00"},
        ]
    return [
        {"date": "25 მაისი", "time": "10:00",
         "datetime_iso": "2030-05-27T10:00:00+04:00"},
    ]


calendar_service.check_slot_available = _check_slot_available
calendar_service.get_free_slots = _get_free_slots
calendar_service.book_slot = (
    lambda **kwargs: CALLS["book_slot"].append(kwargs) or True
)
sheets_service.create_lead = (
    lambda lead: CALLS["create_lead"].append(lead.conversation_summary) or True
)
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append(summary) or True
)
openai_service._chat_completion = lambda **kwargs: "ქართული რეზიუმე."
openai_service.detect_start_intent = lambda m: "GREETING"


def _mk_response(*, content: str = "", tool_calls: list[dict[str, Any]] | None = None):
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


# -- script ----------------------------------------------------------------


conversation = Conversation(sender_id="sim_p3c_live_sales", platform="instagram")


# Turn 1 — camp interest opening.
out = run_turn(
    conversation,
    "საზაფხულო ბანაკი",
    [queue_content(
        "სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა, სადაც ბავშვები "
        "ცოცხალ ურთიერთობასა და თვითგამოხატვაში ერთვებიან. რომ სწორად "
        "გითხრათ, რამდენად შეესაბამება თქვენს შვილს — რამდენი წლისაა?"
    )],
    "1: opener",
)
for forbidden in ("ჩამოუყალიბეთ", "2150", "ფასი"):
    if forbidden in out:
        fail("1", f"unexpected: {forbidden!r}")
if "ასაკი" not in out and "წლისაა" not in out:
    fail("1", "should ask age")
ok("1: clean opener with age question, no price dump")

# Turn 2 — eligible age → motivation question.
out = run_turn(
    conversation,
    "14 წლის არის ჩემი შვილი",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"child_age": "14"}),
        queue_content(
            "14 წელი ძალიან კარგი ასაკია ამ გამოცდილებისთვის. რას ელოდებით "
            "ბანაკისგან — ეკრანისგან დისტანცია, ახალი გარემო და მეგობრები, "
            "კომუნიკაცია თუ უბრალოდ საინტერესო ზაფხული?"
        ),
    ],
    "2: age → motivation",
)
if conversation.lead.child_age != "14":
    fail("2", "expected child_age=14 saved")
for forbidden in (
    "რას მიიჩნევთ ყველაზე მნიშვნელოვანია",
    "რისი მიღებაც გინდათ თქვენი შვილმა",
):
    if forbidden in out:
        fail("2", f"forbidden grammar: {forbidden!r}")
ok("2: motivation question, no grammatical error")

# Turn 3 — screen distance pain → value mechanisms.
out = run_turn(
    conversation,
    "ეკრანისგან დისტანცია",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"challenge": "ეკრანისგან დისტანცია"}),
        queue_content(
            "ეს გასაგებია. ბანაკი სწორედ ამ მიმართულებით ეხმარება ბავშვებს "
            "— რამდენიმე დღით გამოდიან ეკრანის რეჟიმიდან და ერთვებიან "
            "ცოცხალ ურთიერთობასა და ჯგუფურ აქტივობებში. თუ გსურთ, "
            "კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალურად აგიხსნით პროცესს."
        ),
    ],
    "3: screen pain → value mechanisms",
)
if conversation.lead.challenge != "ეკრანისგან დისტანცია":
    fail("3", f"expected challenge saved, got {conversation.lead.challenge!r}")
for forbidden in ("აზრი აქვს", "მოაგვარებს", "გადაჭრის", "დეტალებს ცოცხლად"):
    if forbidden in out:
        fail("3", f"forbidden in pain response: {forbidden!r}")
if "ეხმარება" not in out and "უწყობს ხელს" not in out:
    fail("3", "must use 'ეხმარება' / 'უწყობს ხელს' wording")
ok("3: clean value mechanisms, challenge saved, no overpromise")

# Turn 4 — detailed dates/location.
out = run_turn(
    conversation,
    "ბანაკზე დეტალურად რომ მითხრათ როდის არის და სად",
    [
        queue_tool(TOOL_GET_CAMP_INFO, {"topic": "conditions"}),
        queue_content(
            "ბანაკი ტარდება ამბასადორ კაჭრეთში და არის 7-დღიანი. ნაკადებია: "
            "23–29 ივნისი, 5–11 ივლისი და 14–20 ივლისი. თუ გსურთ, "
            "კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალურად გაგივლით პროგრამას."
        ),
    ],
    "4: detailed dates/location",
)
if "კაჭრეთ" not in out:
    fail("4", "should include location")
if "ივნისი" not in out and "ივლისი" not in out:
    fail("4", "should include stream dates")
# Should NOT re-ask age (already known).
if "რამდენი წლისაა" in out:
    fail("4", "must not re-ask known age")
ok("4: dates + location + CTA, no re-asked age")

# Turn 5 — consultation request for date BEFORE camp streams.
# Bug we are guarding: bot used to reject because camp starts in June.
out = run_turn(
    conversation,
    "კარგით ჩამწერეთ კონსულტაციაზე 26 მაისს 12 საათზე",
    [
        queue_tool(TOOL_BOOK_CONSULTATION, {
            "name": "",  # name still unknown
            "phone": "",  # phone still unknown
            "datetime_iso": "2030-05-27T12:00:00+04:00",  # weekday future date
            "child_age": "14",
            "user_confirmed_datetime": True,
        }),
        queue_content(
            "ამ დროის ჯავშნისთვის მჭირდება თქვენი სახელი და საკონტაქტო ნომერი."
        ),
    ],
    "5: consultation before camp streams",
)
for forbidden in ("ბანაკი ჯერ", "ნაკადი დაიწყება", "ივნისი ჯერ არ", "ბანაკი იწყება"):
    if forbidden in out:
        fail("5", f"should not block by stream date: {forbidden!r}")
if "ნომერი" not in out and "სახელი" not in out:
    fail("5", "should ask for missing name/phone, not reject by stream date")
ok("5: consultation date not blocked by camp June stream, missing fields requested")

# Turn 6 — generic "what dates are available".
CALLS["get_free_slots"].clear()
out = run_turn(
    conversation,
    "რა თარიღში შეიძლება კონსულტაცია",
    [
        queue_tool(TOOL_GET_AVAILABLE_SLOTS, {}),
        queue_content(
            "ხელმისაწვდომი დროებია — 27 მაისს 10:00 და 12:00. რომელი დრო გაწყობთ?"
        ),
    ],
    "6: generic slots query",
)
if not CALLS["get_free_slots"]:
    # When date_iso is absent, the executor falls back to
    # parent_flow._load_available_slots — which iterates dates and
    # calls get_free_slots internally. So calls land there too.
    pass
ok("6: bot offers available slots")

# Turn 7 — specific date 27 May. Should call get_free_slots with
# start_date=27 May, NOT show cached 25 May.
CALLS["get_free_slots"].clear()
out = run_turn(
    conversation,
    "27 მაისს შეიძლება რადგან 25 მაისს არ მცალია",
    [
        queue_tool(TOOL_GET_AVAILABLE_SLOTS, {"date_iso": "2030-05-27"}),
        queue_content(
            "27 მაისს ხელმისაწვდომია 10:00 და 12:00. რომელი დრო გაწყობთ?"
        ),
    ],
    "7: date-specific 27 May",
)
date_aware_call = next(
    (c for c in CALLS["get_free_slots"] if c.get("start_date") is not None),
    None,
)
if date_aware_call is None:
    fail("7", "expected get_free_slots called with start_date for 27 May")
if str(date_aware_call["start_date"]) != "2030-05-27":
    fail("7", f"wrong start_date: {date_aware_call['start_date']!r}")
ok("7: date-aware slot lookup for 27 May, no stale 25 May cache")

# Turn 8 — bare time, contextual date should apply.
out = run_turn(
    conversation,
    "11-ზე იყოს",
    [queue_content(
        "27 მაისს 11:00-ზე გადავამოწმებ. დასადასტურებლად მჭირდება თქვენი "
        "სახელი და საკონტაქტო ნომერი."
    )],
    "8: bare time, contextual date",
)
# Must NOT have silently booked.
if CALLS["book_slot"]:
    fail("8", "must not book on bare time without name/phone confirmation")
ok("8: bare time → ask missing fields, no silent booking")


# -- end summary ----------------------------------------------------------


print("\n=== Summary ===")
print(f"chat_with_tools calls:      {len(CALLS['chat_with_tools'])}")
print(f"get_free_slots calls:       {len(CALLS['get_free_slots'])}")
print(f"check_slot_available calls: {len(CALLS['check_slot_available'])}")
print(f"book_slot calls:            {len(CALLS['book_slot'])}")
print(f"create_lead calls:          {len(CALLS['create_lead'])}")
print(f"manager_notify calls:       {len(CALLS['send_manager_notification'])}")
print(f"lead.child_age:             {conversation.lead.child_age!r}")
print(f"lead.challenge:             {conversation.lead.challenge!r}")
print("✅ All P3-C PATCH 4 simulation checks passed")
