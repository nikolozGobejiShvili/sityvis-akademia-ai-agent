"""P3-C SAFE — manual simulation of the PARENT LLM engine.

Runs 10 turns of a synthetic conversation against a *mocked*
``chat_with_tools`` so the engine, tool executor, and final response
guard all light up without needing a live OpenAI key or real Google
services.

Why a separate script rather than a pytest file: this is a narrative
end-to-end view of one parent's journey through the new engine, the
kind of thing that's useful to eyeball before a deploy. The pytest file
(`tests/test_parent_llm_engine.py`) covers each invariant in isolation;
this script proves they stay consistent across a multi-turn session.

Run from the repo root::

    python tools/manual_simulation_p3c.py

Exits non-zero if any expected invariant is violated. Side-effects on
Calendar / Sheets / notifications are all blocked via monkeypatching.
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

# Windows console defaults to cp1252; Georgian characters need UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import app.config as config_module  # noqa: E402
from app.agent.tools import parent_tool_executor  # noqa: E402
from app.agent.tools.parent_tools import (  # noqa: E402
    TOOL_BOOK_CONSULTATION,
    TOOL_GET_AVAILABLE_SLOTS,
    TOOL_GET_CAMP_INFO,
    TOOL_REQUEST_MANAGER_CALLBACK,
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

# Toggle USE_PARENT_LLM_ENGINE=True in the parent_flow module reference
# for the duration of this script.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=True,
)

# Block real side-effects.
conversation_service.conversations.clear()
parent_turn_router.manager_offer_shown.clear()
parent_flow.available_slots.clear()
parent_flow.ask_name_retries.clear()
parent_flow.invalid_phone_retries.clear()
parent_flow.slots_shown_for_state.clear()
parent_tool_executor.reset_state()


CALLS: dict[str, list[Any]] = {
    "book_slot": [],
    "create_lead": [],
    "send_manager_notification": [],
    "chat_with_tools": [],
}

messenger_service.get_user_profile = lambda sid, plat: {}
calendar_service.check_slot_available = lambda dt: True
calendar_service.book_slot = lambda **kwargs: CALLS["book_slot"].append(kwargs) or True
sheets_service.create_lead = lambda lead: CALLS["create_lead"].append(lead) or True
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append((lead, summary)) or True
)
openai_service.generate_summary = lambda h: "summary"


# A scripted reply queue per user message — index = turn number.
SCRIPT: list[list[dict[str, Any]]] = []


def queue_assistant(text: str) -> dict[str, Any]:
    return {"type": "content", "content": text}


def queue_tool_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_call", "name": name, "arguments": json.dumps(args)}


# -- helpers to build SimpleNamespace OpenAI responses -------------------


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
    msg = SimpleNamespace(
        content=content or None,
        tool_calls=tc_objs or None,
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def chat_with_tools_mock(**kwargs):
    CALLS["chat_with_tools"].append(kwargs)
    # Pop the next step from SCRIPT[current_turn].
    step_list = _PENDING_STEPS
    if not step_list:
        return _mk_response(content="(no more scripted steps)")
    step = step_list.pop(0)
    if step["type"] == "content":
        return _mk_response(content=step["content"])
    return _mk_response(tool_calls=[{
        "id": f"call_{len(CALLS['chat_with_tools'])}",
        "name": step["name"],
        "arguments": step["arguments"],
    }])


openai_service.chat_with_tools = chat_with_tools_mock


# -- driver -------------------------------------------------------------


_PENDING_STEPS: list[dict[str, Any]] = []


def run_turn(
    conversation: Conversation,
    user_message: str,
    expected_steps: list[dict[str, Any]],
    label: str,
) -> str:
    print(f"\n=== Turn — {label} ===")
    print(f"USER: {user_message}")
    _PENDING_STEPS.clear()
    _PENDING_STEPS.extend(expected_steps)
    response = parent_flow.handle(conversation, user_message)
    print(f"BOT:  {response}")
    return response


def assert_eq(label: str, got: Any, expected: Any) -> None:
    if got != expected:
        print(f"❌ {label}: expected {expected!r}, got {got!r}")
        raise SystemExit(1)
    print(f"✅ {label}")


def assert_contains(label: str, haystack: str, needle: str) -> None:
    if needle not in haystack:
        print(f"❌ {label}: {needle!r} missing from {haystack!r}")
        raise SystemExit(1)
    print(f"✅ {label}")


def assert_not_contains(label: str, haystack: str, needle: str) -> None:
    if needle in haystack:
        print(f"❌ {label}: {needle!r} unexpectedly present in {haystack!r}")
        raise SystemExit(1)
    print(f"✅ {label}")


def assert_no_side_effect(label: str, key: str) -> None:
    if CALLS[key]:
        print(f"❌ {label}: {key} called {len(CALLS[key])}x — should be 0")
        raise SystemExit(1)
    print(f"✅ {label} (no {key} call)")


# -- script -------------------------------------------------------------


conversation = Conversation(sender_id="sim_p3c", platform="instagram")

# Turn 1 — greeting
out = run_turn(
    conversation,
    "გამარჯობა",
    [queue_assistant("გამარჯობა! რას გაინტერესებთ ბანაკთან დაკავშირებით? 🌿")],
    "1: greeting",
)
assert_contains("welcome contains 'გამარჯობა'", out, "გამარჯობა")
assert_no_side_effect("greeting has no booking", "book_slot")
assert_no_side_effect("greeting has no manager notify", "send_manager_notification")

# Turn 2 — conditions question (calls get_camp_info("conditions"))
out = run_turn(
    conversation,
    "ბანაკის პირობები",
    [
        queue_tool_call(TOOL_GET_CAMP_INFO, {"topic": "conditions"}),
        queue_assistant(
            "ბანაკი 7 დღიანია, ამბასადორი კაჭრეთში. 9-17 წლის მოზარდებისთვის. "
            "ფასი 2150 ლარი — სრული პაკეტი."
        ),
    ],
    "2: conditions",
)
assert_contains("conditions answer mentions price", out, "2150")
assert_contains("conditions answer mentions location", out, "კაჭრეთ")

# Turn 3 — age out of range
out = run_turn(
    conversation,
    "ჩემი შვილი 7 წლისაა",
    [
        queue_tool_call(TOOL_BOOK_CONSULTATION, {
            "name": "მშობელი",
            "phone": "599123456",
            "datetime_iso": "2030-06-03T12:00:00+04:00",
            "child_age": "7",
        }),
        queue_assistant("ბანაკი 9-17 წლის მოზარდებისთვისაა — 7 წლის ბავშვი ჯერ პატარაა."),
    ],
    "3: child too young",
)
assert_contains("age-out-of-range answer mentions range", out, "9")
assert_eq("no fake booking", conversation.lead.calendly_booked, False)
assert_no_side_effect("no Calendar write on age reject", "book_slot")

# Turn 4 — clarifies, gives a different age
out = run_turn(
    conversation,
    "14 წლის არის სინამდვილეში",
    [
        queue_tool_call(TOOL_SAVE_LEAD_INFO, {"child_age": "14"}),
        queue_assistant("ნათელია — 14 წლის ბავშვი ბანაკის ფორმატს კარგად ერგება."),
    ],
    "4: corrects age",
)
assert_eq("save_lead_info stored age=14", conversation.lead.child_age, "14")
assert_no_side_effect("save_lead_info did NOT write Sheets", "create_lead")

# Turn 5 — decline
out = run_turn(
    conversation,
    "მადლობა არ მინდა",
    [queue_assistant("გასაგებია, კარგი დღე გისურვებთ. თუ რამე გაგიჩნდებათ — შეგვეხმიანეთ.")],
    "5: decline",
)
assert_not_contains("decline has no fake booking word", out, "დაგაჯავშნე")
assert_no_side_effect("decline has no notification", "send_manager_notification")

# Turn 6 — booking request missing child_age (executor returns missing_child_age)
# We deliberately wipe lead.child_age to simulate the LLM ignoring stored state.
conversation.lead.child_age = ""
out = run_turn(
    conversation,
    "კონსულტაციაზე ჩამწერე 25 მაისს 12 საათზე",
    [
        queue_tool_call(TOOL_BOOK_CONSULTATION, {
            "name": "ნიკოლოზი",
            "phone": "599999733",
            "datetime_iso": "2030-06-03T12:00:00+04:00",
            "child_age": "",  # missing → executor must reject
        }),
        queue_assistant("რა ასაკისაა ბავშვი?"),
    ],
    "6: missing child age",
)
assert_contains("missing-age response asks about age", out, "ასაკი")
assert_no_side_effect("no booking when child_age missing", "book_slot")

# Turn 7 — full booking
out = run_turn(
    conversation,
    "ნიკოლოზი 595999733, ბავშვი 14 წლის არის",
    [
        queue_tool_call(TOOL_BOOK_CONSULTATION, {
            "name": "ნიკოლოზი",
            "phone": "595999733",
            "datetime_iso": "2030-06-03T12:00:00+04:00",
            "child_age": "14",
            # PATCH 1 — explicit datetime confirmation required.
            "user_confirmed_datetime": True,
        }),
        queue_assistant("დაჯავშნილია 3 ივნისი 12:00 — მენეჯერი დაგიკავშირდებათ."),
    ],
    "7: successful booking",
)
assert_eq("lead.calendly_booked=True", conversation.lead.calendly_booked, True)
assert_eq("state=DONE", conversation.state, "DONE")
assert len(CALLS["book_slot"]) == 1, "expected exactly one Calendar write"
assert len(CALLS["create_lead"]) == 1, "expected exactly one Sheets write"
assert len(CALLS["send_manager_notification"]) == 1, "expected one manager notify"
assert_contains("confirmation mentions date", out, "ივნისი")
print("✅ booking pipeline fired once each")

# Turn 8 — thanks after booking
out = run_turn(
    conversation,
    "მადლობა",
    [queue_assistant("მოხარული ვარ. ბანაკის შესახებ თუ რამე გაგიჩნდებათ — შემეხმიანეთ.")],
    "8: thanks after booking",
)
assert_not_contains("post-booking thanks no longer asks for slot", out, "აირჩიე")

# Turn 9 — identity
out = run_turn(
    conversation,
    "შენ ვინ ხარ?",
    [queue_assistant("მე {company}-ის ონლაინ-კონსულტანტი ვარ.".format(
        company=config_module.settings.COMPANY_NAME,
    ))],
    "9: identity",
)
assert_contains("identity mentions company", out, config_module.settings.COMPANY_NAME)

# Turn 10 — price after DONE — still routes through engine, calls get_camp_info("price")
out = run_turn(
    conversation,
    "ფასი?",
    [
        queue_tool_call(TOOL_GET_CAMP_INFO, {"topic": "price"}),
        queue_assistant("ბანაკის ფასი 2150 ლარია — სრული პაკეტი."),
    ],
    "10: price after booking",
)
assert_contains("price answer mentions 2150", out, "2150")

print("\n================ P3-C SIMULATION SUMMARY ================")
print(f"chat_with_tools calls: {len(CALLS['chat_with_tools'])}")
print(f"book_slot calls:        {len(CALLS['book_slot'])}")
print(f"create_lead calls:      {len(CALLS['create_lead'])}")
print(f"manager_notify calls:   {len(CALLS['send_manager_notification'])}")
print("✅ All P3-C simulation checks passed")
