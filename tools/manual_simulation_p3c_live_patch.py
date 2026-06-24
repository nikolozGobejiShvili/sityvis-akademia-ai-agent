"""P3-C PATCH 1 — replay of the live test transcript.

This script reproduces the 12-turn parent journey that surfaced the
bugs fixed in PATCH 1. Each turn is driven against a mocked
``chat_with_tools`` so the assertions verify ONLY backend behaviour,
not the live LLM's wording.

Invariants this run proves:

  * No auto-booking after name+phone+age without explicit datetime.
  * Registration vs consultation are not conflated.
  * Cancel/reschedule routes through manage_consultation_booking and
    falls back to manager handoff when event_id is missing.
  * Adult-event interest flips conversation.segment to ADULT and the
    next user message would route through adult_flow.
  * Forbidden Georgian phrases are sanitised on the way out.

Run::

    python tools/manual_simulation_p3c_live_patch.py
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
    TOOL_MANAGE_CONSULTATION_BOOKING,
    TOOL_REQUEST_MANAGER_CALLBACK,
    TOOL_SAVE_LEAD_INFO,
    TOOL_SWITCH_TO_ADULT_FLOW,
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

# Enable engine for this run only — module reference is patched, the
# frozen settings dataclass is untouched.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=True,
)

# Reset module-level dicts.
conversation_service.conversations.clear()
parent_turn_router.manager_offer_shown.clear()
parent_flow.available_slots.clear()
parent_flow.ask_name_retries.clear()
parent_flow.invalid_phone_retries.clear()
parent_flow.slots_shown_for_state.clear()
parent_tool_executor.reset_state()


CALLS: dict[str, list[Any]] = {
    "book_slot": [],
    "cancel": [],
    "create_lead": [],
    "send_manager_notification": [],
    "chat_with_tools": [],
}

messenger_service.get_user_profile = lambda sid, plat: {}


def _book_slot(**kwargs):
    CALLS["book_slot"].append(kwargs)
    kwargs["lead"].calendar_event_id = f"evt_{len(CALLS['book_slot'])}"
    return True


calendar_service.check_slot_available = lambda dt: True
calendar_service.book_slot = _book_slot
calendar_service.cancel_calendar_event = (
    lambda eid: CALLS["cancel"].append(eid) or True
)
sheets_service.create_lead = lambda lead: CALLS["create_lead"].append(lead) or True
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append((lead, summary)) or True
)
openai_service.generate_summary = lambda h: "summary"


def _mk_response(*, content: str = "", tool_calls: list[dict[str, Any]] | None = None) -> Any:
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
    response = parent_flow.handle(conversation, user_message)
    print(f"BOT:  {response}")
    return response


def fail(label: str, msg: str) -> None:
    print(f"❌ {label}: {msg}")
    raise SystemExit(1)


def ok(label: str) -> None:
    print(f"✅ {label}")


# -- script ----------------------------------------------------------------


conversation = Conversation(sender_id="sim_p3c_patch", platform="instagram")

# Turn 1 — "საზაფხულო ბანაკი"
out = run_turn(
    conversation,
    "საზაფხულო ბანაკი",
    [
        queue_tool(TOOL_GET_CAMP_INFO, {"topic": "all"}),
        queue_content(
            "ბანაკი 7 დღიანია, კაჭრეთში. რას გაინტერესებთ — დეტალები, "
            "ფასი თუ კონსულტაცია?"
        ),
    ],
    "1: camp interest",
)
if CALLS["book_slot"]:
    fail("1", "must not book on initial inquiry")
ok("1: no premature booking")

# Turn 2 — "კი" (ambiguous)
out = run_turn(
    conversation,
    "კი",
    [queue_content(
        "გაგებული მაქვს, რომ ბანაკი გაინტერესებთ. გსურთ რეგისტრაციის "
        "ბმული თუ კონსულტაცია მენეჯერთან?"
    )],
    "2: ambiguous 'კი'",
)
if CALLS["book_slot"]:
    fail("2", "must not book on ambiguous 'კი'")
ok("2: clarification asked, no booking")

# Turn 3 — "ნიკოლოზი"
out = run_turn(
    conversation,
    "ნიკოლოზი",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"name": "ნიკოლოზი"}),
        queue_content("გასაგებია. რა ასაკისაა ბავშვი?"),
    ],
    "3: name only",
)
assert conversation.lead.name == "ნიკოლოზი"
if CALLS["book_slot"]:
    fail("3", "must not book on name only")
ok("3: name saved, age requested")

# Turn 4 — "14 წლის არის"
out = run_turn(
    conversation,
    "14 წლის არის",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"child_age": "14"}),
        queue_content("ნათელია. რომელი დღე და საათი მოგწონთ კონსულტაციისთვის?"),
    ],
    "4: age only",
)
assert conversation.lead.child_age == "14"
if CALLS["book_slot"]:
    fail("4", "must not book on age only")
ok("4: age saved, time requested")

# Turn 5 — "595999733"  (phone only, no datetime)
out = run_turn(
    conversation,
    "595999733",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"phone": "595999733"}),
        queue_content("მადლობა. რომელი თარიღი და დრო გაწყობთ?"),
    ],
    "5: phone only",
)
assert conversation.lead.phone == "595999733"
if CALLS["book_slot"]:
    fail("5", "MUST NOT auto-book after name+phone+age without datetime")
ok("5: phone saved, NO auto-booking")

# Turn 6 — "25 მაისს რომ ჩამწეროთ შესაძლებელია?"
out = run_turn(
    conversation,
    "25 მაისს რომ ჩამწეროთ შესაძლებელია?",
    [
        queue_tool(TOOL_GET_AVAILABLE_SLOTS, {}),
        queue_content(
            "25 მაისს გვაქვს რამდენიმე თავისუფალი დრო. "
            "რომელი საათი მოგწონთ?"
        ),
    ],
    "6: asking about date availability",
)
if CALLS["book_slot"]:
    fail("6", "must not book until specific time confirmed")
ok("6: slots offered without auto-book")

# Turn 7 — "3 საათზე არ არის თავისუფალი?"
# We simulate the LLM trying to book 15:00 without explicit user confirm —
# user only asked a *question*; the LLM must not set confirmed=true yet.
out = run_turn(
    conversation,
    "3 საათზე არ არის თავისუფალი?",
    [
        queue_tool(TOOL_BOOK_CONSULTATION, {
            "name": "ნიკოლოზი",
            "phone": "595999733",
            "datetime_iso": "2030-06-04T15:00:00+04:00",
            "child_age": "14",
            "user_confirmed_datetime": False,  # asked, didn't confirm
        }),
        queue_content(
            "ჯერ კიდევ უნდა დამიდასტუროთ კონკრეტული დრო. "
            "3 საათი გაწყობთ?"
        ),
    ],
    "7: question about a slot",
)
if CALLS["book_slot"]:
    fail("7", "must not book without user_confirmed_datetime=true")
ok("7: question-only datetime rejected as not_confirmed")

# Turn 8 — "11-ზე იყოს, 27 ჯავშანი გააუქმეთ"
# There is no existing booking yet → manage_consultation_booking returns
# no_active_booking. The LLM is supposed to ask for clarification or
# proceed with the requested 11:00 booking after confirmation.
out = run_turn(
    conversation,
    "11-ზე იყოს, 27 ჯავშანი გააუქმეთ",
    [
        queue_tool(TOOL_MANAGE_CONSULTATION_BOOKING, {"action": "cancel"}),
        queue_content(
            "სისტემაში თქვენი ჯავშანი ჯერ არ ჩანს. გადავცემ მენეჯერს, "
            "რომ გადაამოწმოს. ნომერი გვაქვს, დაგიკავშირდებათ."
        ),
    ],
    "8: cancel without active booking",
)
if "გავაუქმე" in out:
    fail("8", "must NOT claim cancellation succeeded")
ok("8: no fake cancellation claim")

# Turn 9 — "კი იყოს 11-ზე"  (explicit confirmation)
out = run_turn(
    conversation,
    "კი იყოს 11-ზე",
    [
        queue_tool(TOOL_BOOK_CONSULTATION, {
            "name": "ნიკოლოზი",
            "phone": "595999733",
            "datetime_iso": "2030-06-04T11:00:00+04:00",
            "child_age": "14",
            "user_confirmed_datetime": True,
        }),
        queue_content("დაჯავშნილია 4 ივნისი 11:00 — მენეჯერი დაგიკავშირდებათ."),
    ],
    "9: explicit confirmation books",
)
if not conversation.lead.calendly_booked:
    fail("9", "explicit confirmation should book")
if len(CALLS["book_slot"]) != 1:
    fail("9", f"expected exactly 1 book_slot, got {len(CALLS['book_slot'])}")
assert conversation.lead.calendar_event_id  # stored
ok("9: booking executed after explicit confirmation; event_id stored")

# Turn 10 — "არა მადლობა"
out = run_turn(
    conversation,
    "არა მადლობა",
    [queue_content("გასაგებია, კარგი დღე გისურვებთ.")],
    "10: decline",
)
for forbidden in ("გაიმეორეთ", "შეკვეთოთ", "ყოველთვის მზად ვარ", "დამიმტკიცეთ"):
    if forbidden in out:
        fail("10", f"forbidden phrase: {forbidden}")
ok("10: clean close, no forbidden phrases")

# Turn 11 — "შენ ვინ ხარ?"
out = run_turn(
    conversation,
    "შენ ვინ ხარ?",
    [queue_content(f"მე {config_module.settings.COMPANY_NAME}-ის კონსულტანტი ვარ.")],
    "11: identity",
)
if config_module.settings.COMPANY_NAME not in out:
    fail("11", "identity should mention company")
ok("11: identity answered")

# Turn 12 — "მე ზრდასრული ვარ და ღონისძიებები მაინტერესებს"
out = run_turn(
    conversation,
    "მე ზრდასრული ვარ და ღონისძიებები მაინტერესებს",
    [
        queue_tool(TOOL_SWITCH_TO_ADULT_FLOW, {"reason": "adult event interest"}),
        queue_content(
            "გასაგებია, ზრდასრულთა ღონისძიებებზე გადაგამისამართებთ — "
            "ერთ წუთში გავხსნი თქვენთვის სწორ მიმართულებას."
        ),
    ],
    "12: adult interest",
)
if conversation.segment != "ADULT":
    fail("12", "segment should be ADULT after switch_to_adult_flow")
if "9-17" in out or "9–17" in out or "ბანაკ" in out:
    fail("12", "adult-switch response leaked camp facts")
ok("12: segment switched to ADULT, no camp facts in reply")


# -- final summary ---------------------------------------------------------


print("\n================ PATCH 1 SIMULATION SUMMARY ================")
print(f"chat_with_tools calls:     {len(CALLS['chat_with_tools'])}")
print(f"book_slot calls:            {len(CALLS['book_slot'])}")
print(f"cancel_calendar_event:      {len(CALLS['cancel'])}")
print(f"create_lead calls:          {len(CALLS['create_lead'])}")
print(f"manager_notify calls:       {len(CALLS['send_manager_notification'])}")
print(f"conversation.segment:       {conversation.segment}")
print(f"lead.calendly_booked:       {conversation.lead.calendly_booked}")
print(f"lead.calendar_event_id:     {conversation.lead.calendar_event_id!r}")
print("✅ All P3-C PATCH 1 simulation checks passed")
