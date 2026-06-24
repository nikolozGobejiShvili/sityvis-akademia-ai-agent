"""P3-C PATCH 8 — final wording cleanup transcript replay.

Eight scenarios verify the patch's user-visible wording fixes:

  * A: pure greeting at START → exact static UNCLEAR_ROUTING menu,
       LLM engine NOT consulted.
  * B: intent-bearing first message ("ბანაკი მაინტერესებს") → engine
       runs.
  * C: price-first first message → engine runs.
  * D: ineligible age (8 y/o) + price ask → response carries facts
       AND age-not-eligible AND NO consultation booking CTA.
  * E: communication concern → response has NO screen mention.
  * F: screen concern → response DOES mention screen-distance.
  * G: adult interest → response has NO "ერთ წუთში გავხსნი",
       NO false delayed-message promise.
  * H: greeting inside locked PARENT state=START → still static menu,
       no LLM-generated free-form greeting.

Run::

    python tools/manual_simulation_p3c_final_wording_cleanup.py
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
calendar_service.book_slot = (
    lambda **kwargs: CALLS["book_slot"].append(kwargs) or True
)
sheets_service.create_lead = (
    lambda lead: CALLS["create_lead"].append(lead) or True
)
notification_service.send_manager_notification = (
    lambda lead, summary: CALLS["send_manager_notification"].append(summary) or True
)


def queue_content(text: str) -> dict[str, Any]:
    return {"type": "content", "content": text}


def queue_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_call", "name": name, "arguments": json.dumps(args)}


def run_turn(conv: Conversation, user_message: str, steps, label: str):
    print(f"\n=== Turn — {label} ===")
    print(f"USER: {user_message}")
    _PENDING_STEPS.clear()
    _PENDING_STEPS.extend(steps)
    conversation_service.conversations[conv.sender_id] = conv
    response = conversation_service.process_message(
        conv.sender_id, user_message, conv.platform,
    )
    print(f"BOT:  {response}")
    return response


def fail(label, msg):
    print(f"❌ {label}: {msg}")
    raise SystemExit(1)


def ok(label):
    print(f"✅ {label}")


# =========================================================================
# A — pure greeting → static menu, no engine call
# =========================================================================

print("\n################ A — pure greeting → static menu ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_a = Conversation(sender_id="sim_p8_a", platform="instagram")
conv_a.segment = "PARENT"  # lock to PARENT to prove the engine bypass
out_a = run_turn(conv_a, "გამარჯობა", [], "A1: pure greeting")
if "გვითხარით, რა გაინტერესებთ" not in out_a:
    fail("A1", f"static menu wording missing: {out_a!r}")
if "ბავშვების საზაფხულო ბანაკი" not in out_a:
    fail("A1", "static menu must mention camp option")
if "ზრდასრულთა კულტურული საღამოები" not in out_a:
    fail("A1", "static menu must mention adult option")
if CALLS["chat_with_tools"]:
    fail("A1", "LLM engine must NOT be consulted for pure greeting")
ok("A1: pure greeting → exact static menu, engine bypassed")


# =========================================================================
# B — intent-bearing first message → engine runs
# =========================================================================

print("\n################ B — intent-bearing first message ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_b = Conversation(sender_id="sim_p8_b", platform="instagram")
out_b = run_turn(
    conv_b,
    "საზაფხულო ბანაკი მაინტერესებს",
    [queue_content(
        "სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა. რამდენი წლისაა "
        "თქვენი შვილი?"
    )],
    "B1: camp interest first turn",
)
if not CALLS["chat_with_tools"]:
    fail("B1", "engine must run for intent-bearing message")
if "რამდენი წლისაა" not in out_b:
    fail("B1", "expected age question, not menu")
ok("B1: intent-bearing message routes through engine, asks age")


# =========================================================================
# C — price-first first message
# =========================================================================

print("\n################ C — price-first first message ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_c = Conversation(sender_id="sim_p8_c", platform="instagram")
out_c = run_turn(
    conv_c,
    "ბანაკის ფასი მაინტერესებს",
    [
        queue_tool(TOOL_GET_CAMP_INFO, {"topic": "price"}),
        queue_content("ბანაკის ფასი 2150 ლარია — სრული პაკეტი."),
    ],
    "C1: price first",
)
if not CALLS["chat_with_tools"]:
    fail("C1", "engine must run for price intent")
if "2150" not in out_c:
    fail("C1", f"expected price answer, got {out_c!r}")
ok("C1: price-first answered via engine, no menu-only response")


# =========================================================================
# D — ineligible age + price ask → no consultation booking CTA
# =========================================================================

print("\n################ D — ineligible-age no CTA ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_d = Conversation(sender_id="sim_p8_d", platform="instagram")
conv_d.segment = "PARENT"
conv_d.lead = Lead(
    sender_id=conv_d.sender_id, platform="instagram", segment="PARENT",
    child_age="8",
)
out_d = run_turn(
    conv_d,
    "8 წლის არის და ფასი რა არის?",
    [queue_content(
        "ბანაკის ფასი 2150 ლარია. ეს ბანაკი 9–17 წლის ბავშვებისთვისაა, "
        "ამიტომ ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დაგიდასტურებთ. "
        "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    )],
    "D1: 8 y/o + price",
)
# Ineligible scrubber must strip "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ"
for cta in (
    "კონსულტაციაზე ჩაგწერთ",
    "კონსულტაცია ჩავნიშნოთ",
    "კონსულტაცია ჩაგინიშნავთ",
):
    if cta in out_d:
        fail("D1", f"forbidden CTA for ineligible age: {cta!r}")
if "9–17" not in out_d and "9-17" not in out_d:
    fail("D1", "must explain age window")
if "მენეჯერთან" not in out_d:
    fail("D1", "must offer manager handoff alternative")
ok("D1: ineligible 8 y/o — no consultation-booking CTA, manager handoff offered")


# =========================================================================
# E — communication concern → no screen mention
# =========================================================================

print("\n################ E — communication concern, no screen mention ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_e = Conversation(sender_id="sim_p8_e", platform="instagram")
conv_e.segment = "PARENT"
conv_e.lead = Lead(
    sender_id=conv_e.sender_id, platform="instagram", segment="PARENT",
    child_age="12",
)
out_e = run_turn(
    conv_e,
    "კომუნიკაცია და ახალი გამოცდილება",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {
            "challenge": "კომუნიკაცია და ახალი გამოცდილება",
        }),
        queue_content(
            "ეს გასაგები სურვილია. ბანაკი ეხმარება ბავშვებს ახალ გარემოში "
            "ჩართვაში, ჯგუფურ აქტივობებში მონაწილეობასა და ცოცხალ "
            "ურთიერთობაში. თუ გსურთ, კონსულტაციაზე ჩაგწერთ და მენეჯერი "
            "დეტალურად აგიხსნით პროცესს."
        ),
    ],
    "E1: communication concern",
)
for screen_token in ("ეკრან", "ტელეფონ"):
    if screen_token in out_e:
        fail("E1", f"screen mention leaked: {screen_token!r}")
if conv_e.lead.challenge != "კომუნიკაცია და ახალი გამოცდილება":
    fail("E1", f"challenge not saved: {conv_e.lead.challenge!r}")
ok("E1: communication concern, no screen mention, challenge saved")


# =========================================================================
# F — screen concern → mention IS allowed
# =========================================================================

print("\n################ F — screen concern allowed to mention screen ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_f = Conversation(sender_id="sim_p8_f", platform="instagram")
conv_f.segment = "PARENT"
conv_f.lead = Lead(
    sender_id=conv_f.sender_id, platform="instagram", segment="PARENT",
    child_age="12",
)
out_f = run_turn(
    conv_f,
    "ეკრანისგან დისტანცია",
    [
        queue_tool(TOOL_SAVE_LEAD_INFO, {"challenge": "ეკრანისგან დისტანცია"}),
        queue_content(
            "ეს გასაგები მოთხოვნაა. ბანაკი ამ მიმართულებითაც ეხმარება "
            "ბავშვებს — რამდენიმე დღით გამოდიან ეკრანის რეჟიმიდან და "
            "ერთვებიან ცოცხალ ურთიერთობაში, ჯგუფურ აქტივობებსა და "
            "ბუნებრივ გარემოში."
        ),
    ],
    "F1: screen concern",
)
if "ეკრან" not in out_f:
    fail("F1", "screen-concern response must mention screen")
if conv_f.lead.challenge != "ეკრანისგან დისტანცია":
    fail("F1", f"challenge not saved: {conv_f.lead.challenge!r}")
ok("F1: screen concern → screen mechanisms mentioned, challenge saved")


# =========================================================================
# G — adult interest, no "ერთ წუთში"
# =========================================================================

print("\n################ G — adult-switch wording, no 'ერთ წუთში' ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_g = Conversation(sender_id="sim_p8_g", platform="instagram")
conv_g.segment = "PARENT"  # parent decides to switch — lock so engine runs
out_g = run_turn(
    conv_g,
    "ზრდასრულთა საღამოები მაინტერესებს",
    [
        queue_tool(TOOL_SWITCH_TO_ADULT_FLOW, {"reason": "adult interest"}),
        queue_content(
            "გასაგებია, ზრდასრულთა ღონისძიებებზე გადაგამისამართებთ — "
            "ერთ წუთში გავხსნი თქვენთვის სწორ მიმართულებას."
        ),
    ],
    "G1: adult interest",
)
for forbidden in (
    "ერთ წუთში გავხსნი",
    "ერთ წუთში",
    "ცოტა ხანში მოგწერთ",
    "გადაგამისამართებთ —",
):
    if forbidden in out_g:
        fail("G1", f"false-promise leaked: {forbidden!r}")
ok("G1: adult-switch wording cleaned, no false delayed-message promise")


# =========================================================================
# H — bare greeting at locked PARENT segment → still static menu
# =========================================================================

print("\n################ H — locked PARENT greeting at START ################")
reset_runtime()
CALLS = {k: [] for k in CALLS}

conv_h = Conversation(sender_id="sim_p8_h", platform="instagram")
conv_h.segment = "PARENT"  # already locked
conv_h.state = "START"
out_h = run_turn(conv_h, "გამარჯობა", [], "H1: locked PARENT + greeting")
if "გვითხარით, რა გაინტერესებთ" not in out_h:
    fail("H1", "expected static menu for locked PARENT + bare greeting")
if "როგორ შემიძლია დაგეხმაროთ" in out_h:
    fail("H1", "forbidden generic assistant phrase leaked")
if CALLS["chat_with_tools"]:
    fail("H1", "engine must not run for bare greeting")
ok("H1: locked PARENT + bare greeting → static menu, no LLM call")


print("\n=== PATCH 8 simulation summary ===")
print("A: pure greeting → static menu:                  PASS")
print("B: intent-bearing first message → engine:        PASS")
print("C: price-first first message:                    PASS")
print("D: ineligible-age CTA stripped:                  PASS")
print("E: communication concern, no screen mention:     PASS")
print("F: screen concern, mention allowed:              PASS")
print("G: adult-switch wording cleaned:                 PASS")
print("H: locked PARENT + greeting → static menu:       PASS")
print("✅ All P3-C PATCH 8 simulation checks passed")
