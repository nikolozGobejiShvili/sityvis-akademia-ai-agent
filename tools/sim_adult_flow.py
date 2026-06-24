"""ADULT LLM Engine — manual QA simulation.

Drives 3 end-to-end scenarios against the ADULT engine. Real OpenAI
calls are made; Calendar / Sheets / Notification / Meta send are all
mocked so no real customer is contacted and no real CRM row is
written. Run from the project root:

    python tools/sim_adult_flow.py
    python tools/sim_adult_flow.py --scenario A
    python tools/sim_adult_flow.py --scenario B
    python tools/sim_adult_flow.py --scenario C

Scenarios:

  A — Direct adult interest:
      1. User: "ზრდასრულთა კულტურული საღამოები"
      2. Agent asks for the user's age.
      3. User: "30 წლის"
      4. Agent shows events where min_age <= 30.
      5. User asks for details on one event.
      6. User: "მენეჯერთან საუბარი მინდა"
      7. Agent: saves lead + sends mocked email + returns manager phone.

  B — Child inquiry then adult switch:
      1. User: "ბანაკი მაინტერესებს"  (PARENT flow)
      2. Agent: "რამდენი წლისაა შვილი?"
      3. User: "20 წლის"  (out of camp range)
      4. Agent: polite adult-events offer.
      5. User: "კი, მაინტერესებს"  (switch to ADULT)
      6. Agent: "რამდენი წლის ბრძანდებით?"

  C — Adult-to-parent switch:
      1. User in ADULT: "ბანაკის შესახებ მითხარი"
      2. Agent switches to PARENT.
      3. Agent asks about child's age.
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure project root is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.config as config_module  # noqa: E402
from app.flows import adult_flow, parent_flow  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.services import (  # noqa: E402
    calendar_service,
    notification_service,
    sheets_service,
)


def _enable_engines(monkeypatch_stack):
    """Force USE_ADULT_LLM_ENGINE=True + USE_PARENT_LLM_ENGINE=True for
    the duration of the sim. Both modules cache a settings reference."""
    swapped = dataclasses.replace(
        config_module.settings,
        USE_ADULT_LLM_ENGINE=True,
        USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch_stack.enter_context(patch.object(adult_flow, "settings", swapped))
    monkeypatch_stack.enter_context(patch.object(parent_flow, "settings", swapped))


def _mock_externals(monkeypatch_stack):
    """Hard-stop every external side-effect so the sim is safe to run."""
    def _no_meta(*args, **kwargs):
        print(f"  [MOCK] messenger_service.send_message blocked: {args!r} {kwargs!r}")
        return True

    def _no_calendar(*args, **kwargs):
        print(f"  [MOCK] calendar_service blocked: {args!r}")
        raise RuntimeError("Calendar must NOT be called in adult sim")

    def _mock_sheets(lead):
        print(f"  [MOCK] sheets_service.create_lead: segment={lead.segment} "
              f"event_interest={lead.event_interest!r} status={lead.status!r}")
        return True

    def _mock_notify(lead, summary):
        print(f"  [MOCK] notification_service.send_manager_notification: "
              f"segment={lead.segment} summary_len={len(summary or '')}")
        return True

    from app.services import messenger_service
    monkeypatch_stack.enter_context(patch.object(
        messenger_service, "send_message", _no_meta,
    ))
    monkeypatch_stack.enter_context(patch.object(
        sheets_service, "create_lead", _mock_sheets,
    ))
    monkeypatch_stack.enter_context(patch.object(
        notification_service, "send_manager_notification", _mock_notify,
    ))
    monkeypatch_stack.enter_context(patch.object(
        calendar_service, "book_slot", _no_calendar,
    ))
    monkeypatch_stack.enter_context(patch.object(
        calendar_service, "create_event", _no_calendar,
    ))


def _fresh_conversation(segment: str = "ADULT") -> Conversation:
    conv = Conversation(
        sender_id=f"sim_sender_{segment.lower()}",
        platform="instagram",
        segment=segment,
    )
    conv.lead = Lead(
        sender_id=conv.sender_id,
        platform=conv.platform,
        segment=segment,
    )
    return conv


def _drive(conv: Conversation, message: str, handler) -> str:
    """Push one user message through the given flow handler and print
    the bot's reply."""
    print(f"\n  USER:  {message}")
    reply = handler(conv, message)
    print(f"  BOT:   {reply}")
    print(f"         (segment={conv.segment} state={conv.state})")
    return reply


def scenario_a() -> None:
    print("\n========== SCENARIO A — Direct adult interest ==========")
    conv = _fresh_conversation("ADULT")
    handler = adult_flow.handle
    _drive(conv, "ზრდასრულთა კულტურული საღამოები მაინტერესებს", handler)
    _drive(conv, "30 წლის ვარ", handler)
    _drive(conv, "პოეზიის საღამოს შესახებ მითხარით მეტი", handler)
    _drive(conv, "მენეჯერთან საუბარი მინდა, ჩემი ნომერია 599 12 34 56", handler)
    print(f"\n  Final reservation_status: {conv.lead.reservation_status!r}")


def scenario_b() -> None:
    print("\n========== SCENARIO B — Child inquiry → adult switch ==========")
    conv = _fresh_conversation("PARENT")
    parent_handler = parent_flow.handle
    adult_handler = adult_flow.handle
    _drive(conv, "ბანაკი მაინტერესებს", parent_handler)
    _drive(conv, "20 წლის", parent_handler)
    _drive(conv, "კი, მაინტერესებს ზრდასრულთა საღამოები", parent_handler)
    # By now conversation.segment should be ADULT.
    if conv.segment == "ADULT":
        _drive(conv, "30 წლის ვარ", adult_handler)


def scenario_c() -> None:
    print("\n========== SCENARIO C — Adult → parent switch ==========")
    conv = _fresh_conversation("ADULT")
    _drive(conv, "ბანაკის შესახებ მითხარი", adult_flow.handle)
    # Segment should now be PARENT.
    if conv.segment == "PARENT":
        _drive(conv, "12 წლის", parent_flow.handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", choices=("A", "B", "C", "all"), default="all",
    )
    args = parser.parse_args()

    import contextlib
    with contextlib.ExitStack() as stack:
        _enable_engines(stack)
        _mock_externals(stack)

        if args.scenario in ("A", "all"):
            scenario_a()
        if args.scenario in ("B", "all"):
            scenario_b()
        if args.scenario in ("C", "all"):
            scenario_c()

    print("\nDONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
