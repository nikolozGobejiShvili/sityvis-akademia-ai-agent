"""Controlled smoke-trace harness for the planner-first stabilization patch
(Phase 3 Stage 2, 2026-06-24).

Runs the EXACT controlled smoke transcript through the REAL
`conversation_service.process_message` handler with:
  * USE_CONVERSATION_PLANNER=True
  * CONVERSATION_PLANNER_AUTHORITATIVE=True
  * CONVERSATION_TRACE_DEBUG=True
  * USE_SLIM_PROMPTS=True
  * USE_PARENT_LLM_ENGINE=True / USE_ADULT_LLM_ENGINE=True

The PARENT and ADULT LLM engines are mocked (no OpenAI); Calendar / Sheets /
WhatsApp / email are never reached. The ADULT flow's REAL routing runs (only its
LLM call is stubbed) so the trace shows the true route. Prints one compact
`[trace]` block per turn — proving route / planner / prompt-mode / selected_state
/ validator / final answer for each turn.

Run:
    PYTHONIOENCODING=utf-8 python tools/trace_planner_smoke_2026_06_24.py
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as config_module
from app.agent.llm import adult_llm_engine, parent_llm_engine
from app.flows import adult_flow, parent_flow
from app.models.lead import Lead
from app.reasoning import conversation_trace as trace
from app.services import (
    conversation_service as cs,
    kill_switch,
    notification_service,
    redis_state_service,
    sheets_service,
)

_FLAGS = dict(
    USE_CONVERSATION_PLANNER=True,
    CONVERSATION_PLANNER_AUTHORITATIVE=True,
    CONVERSATION_TRACE_DEBUG=True,
    USE_SLIM_PROMPTS=True,
    USE_PARENT_LLM_ENGINE=True,
    USE_ADULT_LLM_ENGINE=True,
    REDIS_ENABLED=False,
    AGENT_ENABLED=True,
)

_PARENT_CANNED = "ბანაკის შესახებ დაგეხმარებით."
_ADULT_CANNED = "ზრდასრულთა აქტიური ღონისძიებები: დეტალებს გაგიზიარებთ."


def _enable():
    swapped = dataclasses.replace(config_module.settings, **_FLAGS)
    for mod in (
        config_module, cs, parent_flow, adult_flow,
        parent_llm_engine, adult_llm_engine, redis_state_service, kill_switch,
    ):
        if hasattr(mod, "settings"):
            mod.settings = swapped


def _mocks():
    def _parent(conv, msg):
        trace.note_side_effect("parent_engine(mock)")
        return _PARENT_CANNED
    parent_flow._run_llm_engine_safely = _parent

    def _adult(conv, lead, msg):
        trace.note_side_effect("adult_engine(mock)")
        # exercise the REAL slim prompt build so prompt_mode + the genuine
        # topic-scoped selected_state (which excludes child_age) are recorded.
        try:
            slim_state, _policy = adult_llm_engine._build_slim_context(conv, lead)
            adult_llm_engine._trace_prompt_mode("slim", slim_state)
        except Exception:
            pass
        return _ADULT_CANNED
    adult_flow._run_adult_engine_safely = _adult

    notification_service.notify_sunday_school_handoff = lambda lead: True
    sheets_service.log_sunday_school_lead = lambda *a, **k: True
    # Stub ALL manager-notification sends so this offline demo never touches the
    # real Meta / WhatsApp / SMTP network (it runs outside pytest's safety nets).
    notification_service.notify_manager_handoff = (
        lambda *a, **k: (trace.note_side_effect("notify_manager_handoff(mock)"), True)[1]
    )
    notification_service.send_manager_notification = (
        lambda *a, **k: (trace.note_side_effect("send_manager_notification(mock)"), True)[1]
    )
    try:
        notification_service._send_manager_whatsapp = lambda *a, **k: (False, "mocked")
    except Exception:
        pass


TRANSCRIPT = [
    "გამარჯობა ბანაკზე ინფრომაციამაინტერესებს",
    "7 წლის არის",
    "კი დამაკავშირეთ",
    "ჯონი 595999733",
    "მადლობა და კიდევ მაინტერესებს საკვირაო სკოლა როდის ემატება?",
    "მენეჯერის ნომერი მომწერეთ და მეთვითონ დავურეკავ",
    "ამ ეტაპზე რა ღონისძიებები გაქვთ?",
    "ზრდასრულთა ღონისძიებებს ვგულისხმობ",
    "ჩემთვის მინდა",
    "ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია",
    "ჩემზე რა ინფრომაცია გაქვს?",
    "არ მინდა მადლობა",
    "გამარჯობა ბანაკზე როგორ დავრეგისტრირდე?",
    "რეგისტრაცია მინდა",
]

SENDER = "planner_smoke_0001"


def _seed():
    conv = cs._get_or_create_conversation(SENDER, "messenger")
    lead = conv.lead or Lead(sender_id=SENDER, platform="messenger", segment="PARENT")
    # Reproduce the post-contact state (turns 1–4 establish this live).
    lead.name = "ჯონი"
    lead.phone = "595999733"
    lead.child_age = "7"
    conv.lead = lead
    conv.segment = "PARENT"
    conv.state = "IN_PROGRESS"
    conv.history = [{"role": "assistant", "content": "(prior)"}]


def main():
    _enable()
    _mocks()
    trace.reset_history()
    _seed()

    print("=" * 92)
    print("CONTROLLED SMOKE TRACE — planner authoritative + slim prompts + trace ON")
    print("LLM (parent+adult) MOCKED; Calendar/Sheets/WhatsApp/email never reached.")
    print("=" * 92)

    for i, text in enumerate(TRANSCRIPT, 1):
        try:
            cs.process_message(SENDER, text, "messenger")
        except Exception as exc:  # pragma: no cover
            print(f"[{i}] EXCEPTION: {exc!r}")
        hist = trace.history()
        blk = hist[-1] if hist else {}
        print("\n" + "-" * 92)
        print(f"=== TURN {i}: {text}")
        print(json.dumps(blk, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
