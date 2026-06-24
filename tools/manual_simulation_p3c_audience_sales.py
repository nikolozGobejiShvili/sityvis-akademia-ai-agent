"""P3-C PATCH 3 — audience-aware sales + follow-up readiness simulation.

Drives 8 turns of a parent conversation through the LLM engine with
external services mocked. Assertions verify:

  * Camp interest does NOT dump full FAQ — child age is asked early.
  * Eligible age leads to motivation discovery, not problem-assumption.
  * Direct price question gets value framing + payment + soft CTA.
  * Empathic reflection on screen concern.
  * "დავფიქრდები" sets `stopped_after="will_think"`.
  * "არაფერი უბრალოდ გაშვება მინდა" handled without forced pain.
  * "არა მადლობა" sets `followup_blocked_reason="declined"`.
  * Adult-event interest flips conversation to ADULT segment.
  * Raw PDF/DOCX source text NEVER reaches the chat_with_tools prompt.

Run::

    python tools/manual_simulation_p3c_audience_sales.py
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

# Engine on for this script only.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=True,
)

# Reset state.
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
    "system_blocks": [],
}

messenger_service.get_user_profile = lambda sid, plat: {}
calendar_service.check_slot_available = lambda dt: True
calendar_service.book_slot = lambda **kwargs: True
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
    # Capture system blocks for raw-source-leak assertions.
    for msg in (kwargs.get("messages") or []):
        if msg.get("role") == "system":
            CALLS["system_blocks"].append(msg.get("content") or "")
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
    """Drive a turn via the public ``conversation_service.process_message``
    entry point so the follow-up marker capture (which lives there)
    runs the same way it would in production."""
    print(f"\n=== Turn — {label} ===")
    print(f"USER: {user_message}")
    _PENDING_STEPS.clear()
    _PENDING_STEPS.extend(steps)
    # Keep the test's conversation object in the live store under its
    # sender_id so subsequent process_message calls reuse it.
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


conversation = Conversation(sender_id="sim_p3c_audience", platform="instagram")


# Turn 1 — camp interest, no FAQ dump, asks age.
out = run_turn(
    conversation,
    "ბანაკი მაინტერესებს",
    [queue_content(
        "გამარჯობა 🌿 ბანაკი 7 დღიანი გამოცდილებაა, სადაც ბავშვი ცოცხალ "
        "გარემოში ერთვება. რამდენი წლისაა თქვენი შვილი?"
    )],
    "1: camp interest, no FAQ dump",
)
if "ასაკი" not in out and "წლის" not in out:
    fail("1", "expected an age question")
ok("1: opens with age question")

# Turn 2 — child age 14 → eligible → motivation discovery.
out = run_turn(
    conversation,
    "14 წლის არის",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"child_age": "14"}),
        queue_content(
            "ნათელია. რას ეძებთ ბანაკში — ცოცხალ გარემოს, ახალ მეგობრებს, "
            "ეკრანისგან დასვენებას, თუ უბრალოდ აზრიან ზაფხულს?"
        ),
    ],
    "2: motivation discovery",
)
if conversation.lead.child_age != "14":
    fail("2", "child_age must be saved as 14")
if "რა" not in out:
    fail("2", "should ask an open motivation question")
ok("2: motivation question without problem assumption")

# Turn 3 — screen concern → empathic reflection + value angle.
out = run_turn(
    conversation,
    "ეკრანთან ბევრ დროს ატარებს",
    [queue_content(
        "მესმის — ეს ბევრს აწუხებს ახლა. ბანაკის გარემო ბუნებრივად "
        "აშორებს ეკრანს და ცოცხალ ურთიერთობას აღვიძებს. თუ გსურთ, "
        "კონსულტაციაზე ჩაგწერთ და მენეჯერი დეტალებს გადაგცემთ."
    )],
    "3: screen concern → empathic value + CTA",
)
if "ეკრან" not in out:
    fail("3", "should reflect screen concern")
if "კონსულტაცი" not in out:
    fail("3", "should add soft consultation CTA")
ok("3: empathic reflection + soft consultation CTA")

# Turn 4 — direct price question.
out = run_turn(
    conversation,
    "ფასი რა არის?",
    [
        queue_tool(TOOL_GET_CAMP_INFO, {"topic": "price"}),
        queue_content(
            "ბანაკის ღირებულებაა 2150 ლარი. თანხაში შედის ტრანსპორტი, "
            "განთავსება, კვება და პროგრამა. გადახდის გადანაწილება "
            "შესაძლებელია 6 თვემდე. თუ გინდათ, კონსულტაციაზე ჩაგწერთ."
        ),
    ],
    "4: direct price question",
)
if "2150" not in out:
    fail("4", "price must be present")
if "კონსულტაცი" not in out:
    fail("4", "consultation CTA expected after price")
if "განვადებაში" in out:
    fail("4", "bad grammar 'განვადებაში' must not appear")
ok("4: price + value + CTA, no bad grammar")
if conversation.last_meaningful_interest != "price":
    fail("4", "expected last_meaningful_interest='price'")
if conversation.stopped_after != "price":
    fail("4", "expected stopped_after='price'")
ok("4: follow-up markers captured (price)")

# Turn 5 — will think.
out = run_turn(
    conversation,
    "კარგი, დავფიქრდები",
    [queue_content(
        "რა თქმა უნდა, გადაწყვეტილება მნიშვნელოვანია. თუ რამე გაგიჩნდებათ, "
        "შემეხმიანეთ."
    )],
    "5: will think",
)
if conversation.stopped_after != "will_think":
    fail("5", "expected stopped_after='will_think'")
ok("5: stopped_after='will_think' captured")

# Turn 6 — fresh conversation: parent with no concern.
conv2 = Conversation(sender_id="sim_p3c_audience_2", platform="instagram")
out = run_turn(
    conv2,
    "არაფერი უბრალოდ გაშვება მინდა ბანაკში",
    [queue_content(
        "გასაგებია. ბანაკი მაგარი ზაფხულის გამოცდილებაა — ცოცხალი "
        "ურთიერთობა, ახალი მეგობრები და გარემო, რომელიც ჩვეულებრივ "
        "ზაფხულს არ ჰგავს. რამდენი წლისაა შვილი?"
    )],
    "6: no concern",
)
if "პრობლემა" in out or "აწუხებთ" in out:
    fail("6", "must not force pain framing")
ok("6: handled without forced pain")

# Turn 7 — fresh conversation: decline.
conv3 = Conversation(sender_id="sim_p3c_audience_3", platform="instagram")
out = run_turn(
    conv3,
    "არა მადლობა",
    [queue_content("გასაგებია, კარგი დღე გისურვებთ.")],
    "7: decline",
)
# parent_flow.handle does NOT go through conversation_service so the
# marker isn't auto-captured here; assert via direct call.
conversation_service._record_pre_response_followup_markers(conv3, "არა მადლობა")
if conv3.followup_blocked_reason != "declined":
    fail("7", "expected followup_blocked_reason='declined'")
ok("7: followup_blocked_reason='declined' captured")

# Turn 8 — same conversation as turn 1 (segment already locked to PARENT)
# pivots to adult interest mid-flow. The engine must call
# `switch_to_adult_flow` so the NEXT message routes to adult_flow.
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
    "8: adult handoff mid-flow",
)
if conversation.segment != "ADULT":
    fail("8", "expected segment switch to ADULT via tool")
if "9-17" in out or "9–17" in out:
    fail("8", "must not leak camp age facts after adult switch")
ok("8: adult handoff via tool, segment=ADULT")


# Source-leak assertions ---------------------------------------------------


print("\n=== Source-leak assertions ===")
joined_system = " ".join(CALLS["system_blocks"])

pdf_phrases = (
    "სამიზნე აუდიტორიის დეტალური ანალიზი",
    "ფარული სურვილი",
    "ჰუკ-სათაურები",
    "კულტურული საზოგადოება",  # PDF section header for adult segment
)
for phrase in pdf_phrases:
    if phrase in joined_system:
        fail("source-leak", f"PDF phrase leaked into engine prompt: {phrase!r}")
ok("no raw PDF phrases in any engine prompt")

docx_phrases = (
    "ჩასაშენებელი follow up ლოგიკა",
    "FOLLOW-UP 1 - 24 საათში",
    "{{First_Name}}, გამარჯობა.",  # raw template string
)
for phrase in docx_phrases:
    if phrase in joined_system:
        fail("source-leak", f"DOCX phrase leaked into engine prompt: {phrase!r}")
ok("no raw DOCX phrases in any engine prompt")

# Each system block must stay under a sane bound. The richest block is
# the full system_parent_v2.md prompt; everything else (context +
# sales-context reminder) is hundreds of chars. The cap is bumped to
# 25 KB after PATCH 8 added the static-welcome rule, ineligible-age
# CTA ban, concern-conditional screen rule, and adult-switch wording
# guard. The engine-wide total-prompt cap stays at 25 KB (asserted
# separately by the test in test_parent_llm_engine.py).
max_block = max((len(b) for b in CALLS["system_blocks"]), default=0)
if max_block > 25_000:
    fail("source-leak", f"system block too large: {max_block} chars")
ok(f"all system blocks bounded (max {max_block} chars)")


print("\n================ PATCH 3 SIMULATION SUMMARY ================")
print(f"chat_with_tools calls:     {len(CALLS['chat_with_tools'])}")
print(f"system blocks captured:    {len(CALLS['system_blocks'])}")
print(f"create_lead calls:          {len(CALLS['create_lead'])}")
print(f"manager_notify calls:       {len(CALLS['send_manager_notification'])}")
print(f"conv2.lead.child_age:       {conv2.lead.child_age if conv2.lead else None!r}")
print(f"conversation.stopped_after: {conversation.stopped_after!r}")
print(f"conversation.last_meaningful_interest: "
      f"{conversation.last_meaningful_interest!r}")
print(f"conversation.segment:       {conversation.segment!r}")
print("✅ All P3-C PATCH 3 simulation checks passed")
