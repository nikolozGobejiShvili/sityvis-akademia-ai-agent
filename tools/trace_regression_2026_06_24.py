"""Local-only / test-only diagnostic trace harness for the
State Poisoning & Guard Regression Audit (2026-06-24).

READ-ONLY. No LLM call, no Calendar/Sheets/Meta/WhatsApp/email, no Redis write,
no webhook/tick. It only exercises DETERMINISTIC, pure classifiers on the exact
live-regression transcript messages and prints:

  1. raw user text
  2. the central Turn Intent Gateway output (reasoning_layer.analyze_turn_intent)
  3. conversation_service._classify_segment (the routing classifier)
  4. whether the deterministic state-recall handler (_maybe_memory_info_reply)
     WOULD trigger on this text (exact-substring stems — NOT typo-tolerant)
  5. whether the registration-link interceptor would fire
  6. the event-day extraction the event interceptor uses

This isolates WHY each turn routed the way it did, without running the agent.

Run:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/trace_regression_2026_06_24.py
"""
from __future__ import annotations

import os
import sys

# Make the project root importable when run as `tools/trace_regression_*.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.reasoning import reasoning_layer as rl
from app.services import conversation_service as cs
from app.flows import parent_flow as pf

try:
    from app.services import admin_config_service as acs
    from app.agent.llm.adult_llm_engine import _has_genuine_event_name_token
except Exception:  # pragma: no cover
    acs = None
    _has_genuine_event_name_token = None


# Exact live-regression transcript turns (in order). `note` = the prior-state
# context the operator described for that turn (set earlier in the SAME
# conversation; Redis is flushed + server restarted before each test).
TURNS = [
    ("T1",  "ჩემი სახელია ნიკოლოზი",
            "prior same-conv state: child_age=7 (underage) from an earlier turn"),
    ("T2",  "ზრდასრულთა კულტურული ღონისძიებები 7 წლის ბავშვებისთვის არის?",
            "adult cultural-event question that also mentions a 7yo child"),
    ("T3a", "შემეძლება ბანაკის განმავლობაში ბავშვს რომ დავურეკო?",
            "camp-period: can I call my child during camp?"),
    ("T3b", "13 წლის არის, უსაფრთხოება დაცულია? შემეძლება რომ ბავშვი მოვინახულო?",
            "camp safety + visit question"),
    ("T4p", "13 წლის არის",
            "child age disclosure (should persist child_age=13)"),
    ("T4",  "ბანაკში მოწვეული სტუმრები არიან?",
            "are there invited guests at camp? (child_age=13 already known)"),
    ("T5a", "ნუცა 595999733",
            "name + phone for the consultation booking"),
    ("T5b", "უახლოეს პერიოდში რომ დავუკავშირდე",
            "soonest available, please"),
    ("T5c", "25 ში 12 საათზე ჩამწერეთ",
            "book me on the 25th at 12:00"),
    ("T5d", "გასაგებია ჩემზე რა ინფრომაცია გავქს?",
            "GENERAL recall — note typos: 'ინფრომაცია', 'გავქს'"),
    ("T6",  "კონსულტაცია როდის მაქვს შეგიძლია შემახსენო?",
            "NARROW booking recall — works live"),
    ("T7a", "ჩემთვის მინდა ღონისძიებები რას შემომთავაზებთ?",
            "adult event discovery for self (generic, no event name)"),
    ("T7b", "ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება მე ვარ 30 წლის",
            "mixed self(30)+child event intent"),
]


def _memory_recall_trigger(text: str) -> str:
    low = (text or "").lower().strip().rstrip("?!.,;:")
    is_general = any(s in low for s in pf._MEMORY_INFO_TRIGGER_STEMS)
    is_name = any(s in low for s in pf._NAME_RECALL_TRIGGER_STEMS)
    is_phone = any(s in low for s in pf._PHONE_RECALL_TRIGGER_STEMS)
    hits = []
    if is_general:
        hits.append("general")
    if is_name:
        hits.append("name")
    if is_phone:
        hits.append("phone")
    return ",".join(hits) if hits else "NONE (falls through to LLM)"


def _event_tokens(text: str) -> str:
    if acs is None:
        return "n/a"
    try:
        toks = acs._event_query_tokens(text)
        genuine = (
            _has_genuine_event_name_token(toks)
            if _has_genuine_event_name_token else "n/a"
        )
        return f"tokens={toks} genuine_event_name={genuine}"
    except Exception as exc:  # pragma: no cover
        return f"error: {exc!r}"


GATEWAY_FIELDS = [
    "segment", "topic", "intent", "age", "date_text", "phone",
    "is_decline", "is_affirmation", "is_age_statement",
    "is_self_reference", "is_child_reference", "is_genuine_event_reference",
    "is_consultation_request", "is_child_concern", "is_off_topic",
    "is_state_recall", "is_adult_self", "is_manager_phone_request",
    "block_event_inquiry", "clear_event_context", "confidence",
]


def main() -> None:
    print("=" * 78)
    print("STATE POISONING & GUARD REGRESSION — DETERMINISTIC TRACE (2026-06-24)")
    print("read-only; gateway + classifiers only; NO LLM / NO live integrations")
    print("=" * 78)
    for tid, text, note in TURNS:
        ti = rl.analyze_turn_intent(text)
        seg = cs._classify_segment(text)
        recall = _memory_recall_trigger(text)
        reg = cs._is_registration_link_request(text)
        day = pf._extract_event_day_reference(text)
        print("\n" + "-" * 78)
        print(f"[{tid}] {text}")
        print(f"      note: {note}")
        print(f"  routing._classify_segment      = {seg}")
        print(f"  state_recall_handler_triggers  = {recall}")
        print(f"  registration_link_request      = {reg}")
        print(f"  event_day_reference            = {day}")
        print(f"  event_name_gate                = {_event_tokens(text)}")
        print("  gateway.analyze_turn_intent:")
        d = ti.to_dict()
        for f in GATEWAY_FIELDS:
            print(f"      {f:30s}= {d.get(f)}")
        print(f"      reason                        = {d.get('reason')}")
    print("\n" + "=" * 78)
    print("KEY: block_event_inquiry=True -> the PARENT event interceptor is")
    print("suppressed; state_recall_handler_triggers=NONE -> the turn reaches the")
    print("LLM (which may continue stale/pending flow). is_state_recall is computed")
    print("by the gateway but consumed NOWHERE (dead signal).")
    print("=" * 78)


if __name__ == "__main__":
    main()
