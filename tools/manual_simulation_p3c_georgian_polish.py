"""P3-C PATCH 2 — Georgian polish + consultation CTA + Georgian CRM.

Drives 6 turns of the live-test transcript that surfaced the PATCH 2
fixes, with all external services mocked. Assertions verify:

  * The forbidden-phrase sanitiser strips „განვადებაში", „მენეჯერის
    კავშირი", „რაც მალე იქნება შესაძლებელი" etc. from the engine's
    response.
  * Conditions / price answers retain a natural consultation CTA in
    the mocked LLM output (engine just needs to NOT clobber it).
  * The age-ineligible path does not offer direct booking and uses
    „მენეჯერთან დაკავშირება" wording.
  * After a valid phone, the manager-callback response says „მენეჯერი
    დაგიკავშირდებათ" — *without* the „რაც მალე იქნება შესაძლებელი"
    padding.
  * The CRM Sheets row + the manager notification body are Georgian.
    English manager-summary phrases ("Parent interested", "outside
    age range", "requested manager callback") never reach Sheets or
    notification.

Run::

    python tools/manual_simulation_p3c_georgian_polish.py
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

# Engine on for the simulation.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=True,
)

# Reset module-level state.
conversation_service.conversations.clear()
parent_turn_router.manager_offer_shown.clear()
parent_flow.available_slots.clear()
parent_flow.ask_name_retries.clear()
parent_flow.invalid_phone_retries.clear()
parent_flow.slots_shown_for_state.clear()
parent_tool_executor.reset_state()


CALLS: dict[str, list[Any]] = {
    "chat_with_tools": [],
    "create_lead": [],
    "send_manager_notification": [],
    "book_slot": [],
}


def _book_slot(**kwargs):
    CALLS["book_slot"].append(kwargs)
    return True


messenger_service.get_user_profile = lambda sid, plat: {}
calendar_service.check_slot_available = lambda dt: True
calendar_service.book_slot = _book_slot

# Sheets + notification record the EXACT summary that flows through —
# we assert on it at the end of the script.
sheets_service.create_lead = (
    lambda lead: CALLS["create_lead"].append(lead.conversation_summary) or True
)
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append(summary) or True
)

# The summary layer is deliberately exercised — we let the real
# generate_summary run, but stub the underlying chat completion so it
# returns the English text the live LLM was emitting. The Georgian
# fallback path must replace it.
openai_service._chat_completion = (
    lambda **kwargs: "Parent interested in camp, wants consultation."
)


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


def assert_not_contains(label: str, text: str, needle: str) -> None:
    if needle in text:
        fail(label, f"unexpected phrase: {needle!r}")
    ok(f"{label} (no {needle!r})")


# -- script ----------------------------------------------------------------


conversation = Conversation(sender_id="sim_p3c_polish", platform="instagram")


# Turn 1 — conditions question; LLM gives raw text with a soft CTA.
# We deliberately bake awkward Georgian into the LLM reply so the
# sanitiser has work to do.
out = run_turn(
    conversation,
    "ბანაკი მაინტერესებს რა პირობებია",
    [
        queue_tool(TOOL_GET_CAMP_INFO, {"topic": "conditions"}),
        queue_content(
            "ბანაკი 7 დღიანია, ტარდება ამბასადორ კაჭრეთში, 9-დან 17 წლამდე "
            "ბავშვებისთვის. ფასი 2150 ლარი მოიცავს ტრანსპორტს, განთავსებას, "
            "კვებას და პროგრამას. თუ გსურთ, კონსულტაციაზე ჩაგწერთ და "
            "მენეჯერი დეტალებს ცოცხლად აგიხსნით."
        ),
    ],
    "1: conditions + CTA",
)
assert_not_contains("1: typography ages", out, "9-დან 17 წლამდე")
if "9–17 წლის" not in out:
    fail("1", "missing modernised age typography (9–17 წლის)")
ok("1: age typography normalised to 9–17 წლის")
if "კონსულტაცია" not in out:
    fail("1", "soft consultation CTA missing")
ok("1: soft consultation CTA preserved")

# Turn 2 — price answer with bad payment grammar.
out = run_turn(
    conversation,
    "ფასი რა არის?",
    [
        queue_tool(TOOL_GET_CAMP_INFO, {"topic": "price"}),
        queue_content(
            "ბანაკის ღირებულებაა 2150 ლარი — შედის ტრანსპორტი, განთავსება, "
            "კვება და პროგრამა. გადანაწილება განვადებაში 6 თვემდე, TBC ან "
            "საქართველოს ბანკი. მოქმედებს 10%-იანი ფასდაკლება დედმამიშვილებისთვის. "
            "თუ გინდათ, კონსულტაციაზე ჩაგწერთ."
        ),
    ],
    "2: price polish",
)
assert_not_contains("2: bad payment grammar", out, "განვადებაში")
if "2150" not in out:
    fail("2", "price missing")
ok("2: price 2150 present")
if "კონსულტაცია" not in out:
    fail("2", "consultation CTA missing")
ok("2: consultation CTA preserved")

# Turn 3 — age-not-eligible (the live transcript bug).
out = run_turn(
    conversation,
    "ჩემი შვილი 7 წლის არის",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"child_age": "7"}),
        queue_content(
            "ეს ბანაკი 9–17 წლის ბავშვებისთვისაა, ამიტომ 7 წლის ბავშვის "
            "ჩაწერას ამ პროგრამაში ვერ დაგიდასტურებთ. თუ გსურთ, მენეჯერთან "
            "დაგაკავშირებთ და გადაამოწმებს, არის თუ არა ამ ასაკისთვის სხვა "
            "შესაფერისი ფორმატი."
        ),
    ],
    "3: age not eligible",
)
assert_not_contains("3: no 'მენეჯერის კავშირი'", out, "მენეჯერის კავშირი")
assert_not_contains("3: no direct booking", out, "ჩაგწერთ კონსულტაცი")
if "მენეჯერთან დაკავშირ" not in out and "მენეჯერთან დაგაკავშირ" not in out:
    fail("3", 'must use „მენეჯერთან დაკავშირება" wording')
ok("3: clean age-ineligible handoff wording")

# Turn 4 — user agrees to manager handoff, asks how it works.
out = run_turn(
    conversation,
    "კი როგორ ხდება მენეჯერთან დაკავშირება?",
    [queue_content(
        "მომწერეთ თქვენი 9-ნიშნა საკონტაქტო ნომერი და მენეჯერს გადავცემ."
    )],
    "4: manager handoff explanation",
)
assert_not_contains("4: no 'გთხოვთ მომწერეთ'", out, "გთხოვთ მომწერეთ")
assert_not_contains("4: no 'გადასცე' command", out, "მენეჯერს გადასცე")
if "ნომერ" not in out:
    fail("4", "should ask for phone")
ok("4: asks for phone naturally")

# Turn 5 — user provides phone.
# LLM is told to emit the padded „რაც მალე იქნება შესაძლებელი" phrase
# so the sanitiser is forced to do its job.
out = run_turn(
    conversation,
    "595999733",
    [
        queue_tool(TOOL_REQUEST_MANAGER_CALLBACK, {
            "name": "ნიკოლოზი",
            "phone": "595999733",
        }),
        queue_content(
            "მივიღე, მენეჯერი დაგიკავშირდებათ რაც მალე იქნება შესაძლებელი."
        ),
    ],
    "5: phone provided → handoff",
)
assert_not_contains("5: no 'რაც მალე'", out, "რაც მალე იქნება შესაძლებელი")
if "მენეჯერი დაგიკავშირდებათ" not in out:
    fail("5", 'should say „მენეჯერი დაგიკავშირდებათ"')
ok("5: clean callback acknowledgement")

# CRM payload assertions ----------------------------------------------------


print("\n=== CRM payload assertions ===")
if not CALLS["create_lead"]:
    fail("CRM", "Sheets row was never written")

sheets_summary = CALLS["create_lead"][-1]
notification_summary = CALLS["send_manager_notification"][-1]
print(f"sheets summary:        {sheets_summary!r}")
print(f"notification summary:  {notification_summary!r}")

for english in (
    "Parent interested",
    "outside age range",
    "requested manager callback",
    "wants consultation",
):
    if english in sheets_summary:
        fail("CRM", f"English phrase reached Sheets summary: {english!r}")
    if english in notification_summary:
        fail("CRM", f"English phrase reached manager notification: {english!r}")
ok("CRM: no English manager-summary phrases reached Sheets")
ok("CRM: no English manager-summary phrases reached notification")

# Must contain Georgian characters.
georgian_chars = sum(
    1 for ch in sheets_summary if 0x10A0 <= ord(ch) <= 0x10FF
)
if georgian_chars < 5:
    fail("CRM", "Sheets summary has no Georgian content")
ok(f"CRM: Sheets summary is Georgian ({georgian_chars} გ-chars)")


print("\n================ PATCH 2 SIMULATION SUMMARY ================")
print(f"chat_with_tools calls:     {len(CALLS['chat_with_tools'])}")
print(f"create_lead calls:          {len(CALLS['create_lead'])}")
print(f"manager_notify calls:       {len(CALLS['send_manager_notification'])}")
print(f"book_slot calls:            {len(CALLS['book_slot'])}")
print("✅ All P3-C PATCH 2 simulation checks passed")
