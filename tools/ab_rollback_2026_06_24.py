"""A/B harness for the surgical guard-narrowing (2026-06-24). READ-ONLY,
deterministic, offline (no LLM / no Calendar/Sheets/Meta/WhatsApp/email).

For each of the 5 regression snippets it prints the deterministic signals the
two surgical changes affect:

  Change A — gateway block_event_inquiry (adult_event must NOT be blocked just
             because a child age is mentioned).
  Change B — _maybe_capture_adult_target must NOT store the user's OWN age
             ("მე ვარ 30 წლის") as adult_target_age; adult_age/child_age stay
             separate.

Run BEFORE and AFTER the edits to compare:
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe tools/ab_rollback_2026_06_24.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.reasoning import reasoning_layer as rl
from app.services import conversation_service as cs
from app.agent.llm import adult_llm_engine as ae
from app.models.lead import Lead

SNIPPETS = [
    ("#1", "ზრდასრულთა კულტურული ღონისძიებები 7 წლის ბავშვებისთვის არის?"),
    ("#2", "ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება მე ვარ 30 წლის"),
    ("#3", "ჩემთვის მინდა ღონისძიებები რას შემომთავაზებთ?"),
    ("#4", "ჩემზე რა ინფრომაცია გაქვს?"),
    ("#5", "კოსულტაციაზე მინდა ჩაწერა"),
]


def main() -> None:
    print("=" * 78)
    print("A/B ROLLBACK HARNESS (2026-06-24) — deterministic, offline")
    print("=" * 78)
    for sid, text in SNIPPETS:
        ti = rl.analyze_turn_intent(text)
        seg = cs._classify_segment(text)
        reg = cs._is_registration_link_request(text)
        # Exercise the adult relative-target capture on a FRESH lead.
        lead = Lead(sender_id="ab-test", platform="messenger", segment="ADULT")
        try:
            ae._maybe_capture_adult_target(text, lead)
        except Exception as exc:  # pragma: no cover
            print(f"  [capture error: {exc!r}]")
        print("\n" + "-" * 78)
        print(f"[{sid}] {text}")
        print(f"  _classify_segment            = {seg}")
        print(f"  registration_link_request    = {reg}")
        print(f"  gateway.topic                = {ti.topic}")
        print(f"  gateway.is_age_statement     = {ti.is_age_statement}  age={ti.age}  date_text={ti.date_text}")
        print(f"  gateway.block_event_inquiry  = {ti.block_event_inquiry}   <-- Change A")
        print(f"  gateway.is_adult_self        = {ti.is_adult_self}   <-- Change B (gateway)")
        print(f"  capture.adult_target_relation= {lead.adult_target_relation!r}")
        print(f"  capture.adult_target_age     = {lead.adult_target_age!r}   <-- Change B (must NOT be '30' for #2)")
        print(f"  capture.adult_age            = {lead.adult_age!r}")
        print(f"  capture.child_age            = {lead.child_age!r}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
