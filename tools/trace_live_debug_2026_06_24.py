"""Live-debug replay harness (2026-06-24). Runs the A-J trace transcript through
the REAL conversation_service.process_message handler with CONVERSATION_TRACE_DEBUG
on and both planner flags on, while MOCKING the LLM + external services (no real
OpenAI / Calendar / Sheets / Meta / WhatsApp / email).

It prints one compact [trace] block per turn (from app.reasoning.conversation_trace)
so we can see exactly: route (parent/adult/unclear), planner output, who answered,
validator action, side effects, and masked lead state after each turn.

Run:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/trace_live_debug_2026_06_24.py
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config as config_module
from app.services import conversation_service as cs
from app.flows import parent_flow
from app.flows import adult_flow
from app.services import redis_state_service
from app.services import kill_switch
from app.reasoning import conversation_trace as trace
from app.models.lead import Lead


def _enable_flags():
    swapped = dataclasses.replace(
        config_module.settings,
        USE_CONVERSATION_PLANNER=True,
        CONVERSATION_PLANNER_AUTHORITATIVE=True,
        CONVERSATION_TRACE_DEBUG=True,
        USE_PARENT_LLM_ENGINE=True,
        REDIS_ENABLED=False,
        AGENT_ENABLED=True,
    )
    for mod in (config_module, cs, parent_flow, adult_flow, redis_state_service, kill_switch):
        if hasattr(mod, "settings"):
            mod.settings = swapped


def _install_mocks():
    # LLM (parent) — return a recognizable mock so we never hit OpenAI.
    parent_flow._run_llm_engine_safely = (
        lambda conv, msg: "[MOCK parent LLM answer for: " + (msg or "")[:40] + "]"
    )
    # ADULT flow — stub so we observe the ROUTE without running the adult engine
    # / OpenAI. (The decisive point is that the planner is not consulted here.)
    def _adult_stub(conversation, message):
        trace.set(answered_by="adult_flow", handler="adult_flow.handle(mock)")
        return "[MOCK adult_flow answer]"
    adult_flow.handle = _adult_stub
    # External side effects — record + no-op.
    try:
        from app.services import calendar_service
        calendar_service.book_slot = lambda *a, **k: (trace.note_side_effect("calendar.book_slot"), "")[1]
    except Exception:
        pass
    try:
        from app.services import sheets_service
        sheets_service.create_lead = lambda *a, **k: (trace.note_side_effect("sheets.create_lead"), True)[1]
    except Exception:
        pass
    try:
        from app.services import notification_service
        notification_service.send_manager_notification = (
            lambda *a, **k: (trace.note_side_effect("notification.send_manager"), True)[1]
        )
        notification_service.notify_manager_handoff = (
            lambda *a, **k: (trace.note_side_effect("notification.handoff"), True)[1]
        )
    except Exception:
        pass


TRANSCRIPT = [
    ("A", "მადლობა და კიდევ მაინტერესებს საკვირაო სკოლა როდის ემატება?"),
    ("B", "მენეჯერის ნომერი მომწერეთ და მე თვითონ დავურეკავ"),
    ("C", "ამ ეტაპზე რა ღონისძიებები გაქვთ?"),
    ("D", "ზრდასრულთა ღონისძიებებს ვგულისხმობ"),
    ("E", "ჩემთვის მინდა"),
    ("F", "ჩემი ასაკი ეგ არა, ჩემი ასაკია 29 წელი, ეგ ჩემი შვილის ასაკია"),
    ("G", "ჩემზე რა ინფრომაცია გაქვს?"),
    ("H", "არ მინდა მადლობა"),
    ("I", "გამარჯობა ბანაკზე როგორ დავრეგისტრირდე?"),
    ("J", "რეგისტრაცია მინდა"),
]

SENDER = "trace_demo_sender_0001"


def _seed_state():
    """Reproduce the live precondition: a known parent lead with a stale
    child_age=7 (so we can see whether the agent mixes it into adult flow)."""
    conv = cs._get_or_create_conversation(SENDER, "messenger")
    lead = conv.lead or Lead(sender_id=SENDER, platform="messenger", segment="PARENT")
    lead.name = "ნუცა"
    lead.phone = "595999733"
    lead.child_age = "7"
    conv.lead = lead
    conv.segment = ""          # let the recovery loop classify each turn
    conv.state = "IN_PROGRESS"
    conv.history = [{"role": "assistant", "content": "(prior)"}]
    return conv


def main():
    _enable_flags()
    _install_mocks()
    trace.reset_history()
    _seed_state()

    print("=" * 90)
    print("LIVE-DEBUG REPLAY (A-J) — flags: USE_CONVERSATION_PLANNER=True "
          "CONVERSATION_PLANNER_AUTHORITATIVE=True CONVERSATION_TRACE_DEBUG=True")
    print("LLM + Calendar/Sheets/Meta/WhatsApp/email MOCKED. No live calls.")
    print("=" * 90)

    blocks = []
    for tid, text in TRANSCRIPT:
        try:
            cs.process_message(SENDER, text, "messenger")
        except Exception as exc:  # pragma: no cover
            print(f"[{tid}] EXCEPTION: {exc!r}")
        hist = trace.history()
        blk = hist[-1] if hist else {}
        blocks.append((tid, blk))

    for tid, blk in blocks:
        print("\n" + "-" * 90)
        print(f"=== TURN {tid} ===")
        print(json.dumps(blk, ensure_ascii=False, indent=2, default=str))

    print("\n" + "=" * 90)
    print("PROMPT SIZES (full prompt sent every LLM turn): "
          "system_parent_v2.md=111675B/451L · system_adult_v1.md=54636B/244L")
    print("=" * 90)


if __name__ == "__main__":
    main()
