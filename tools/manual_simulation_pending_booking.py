"""Manual simulation — PART 10 of the pending-booking task.

Drives three multi-turn scenarios end-to-end through the real
``conversation_service`` routing, with external services stubbed so the
run is deterministic and offline:

  Scenario A — phone-only continuation
    1. გამარჯობა
    2. ბავშვების ბანაკის პირობები
    3. კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე    ← sets pending_booking
    4. 599123456                                  ← continuation, books

  Scenario B — manager interrupt mid-pending
    1. გამარჯობა, ბანაკი მაინტერესებს
    2. კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე    ← sets pending_booking
    3. მენეჯერი დამიკავშირდეს                    ← clears pending, hands off

  Scenario C — factual question mid-pending
    1. გამარჯობა, ბანაკი მაინტერესებს
    2. კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე    ← sets pending_booking
    3. ფასი რა არის?                             ← price + reminder, pending kept

Run:

    PYTHONIOENCODING=utf-8 python tools/manual_simulation_pending_booking.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import dataclasses  # noqa: E402

import app.config as config_module  # noqa: E402
from app.flows import parent_flow, parent_turn_router  # noqa: E402
from app.services import (  # noqa: E402
    calendar_service, conversation_service, messenger_service,
    notification_service, openai_service, sheets_service,
)

# P3-C PATCH 1 — pin the new LLM engine off so this legacy P1 sim drives
# the original pending-booking path even when .env flips the engine on.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=False,
)


_failures = 0


def _patch_environment(*, calendar_success: bool = True) -> None:
    """Stub every external service so this simulation never touches a
    real Meta / OpenAI / Google endpoint."""
    messenger_service.get_user_profile = lambda sender_id, platform: {
        "name": "ანა ლომიძე", "first_name": "ანა",
        "last_name": "ლომიძე", "username": "",
    }
    openai_service.detect_start_intent = lambda message: "GREETING"
    openai_service.generate_summary = lambda history: "summary"

    calendar_service.check_slot_available = (
        lambda dt, duration_minutes=30: calendar_success
    )
    calendar_service.book_slot = lambda **kwargs: calendar_success
    sheets_service.create_lead = lambda lead: True
    notification_service.send_manager_notification = (
        lambda lead, summary: True
    )


def _reset() -> None:
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()


def _send(sender: str, message: str) -> str:
    response = conversation_service.process_message(sender, message, "instagram")
    print(f"USER: {message}")
    print(f"BOT:  {response}")
    return response


def _check(condition: bool, label: str) -> None:
    marker = "PASS" if condition else "FAIL"
    print(f"  [{marker}] {label}")
    if not condition:
        global _failures
        _failures += 1


def _hr() -> None:
    print()
    print("=" * 60)


def scenario_a_phone_only_continuation() -> None:
    """A → user provides phone after pending was set; Calendar succeeds."""
    _hr()
    print("Scenario A — phone-only continuation (Calendar success)")
    _hr()
    _patch_environment(calendar_success=True)
    _reset()
    sender = "sim-pb-A"

    _send(sender, "გამარჯობა")
    _send(sender, "ბავშვების ბანაკის პირობები")
    r = _send(sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე")
    convo = conversation_service.conversations[sender]
    _check(convo.pending_booking is not None, "pending_booking was set")
    _check("T17:00:00" in (convo.pending_booking or {}).get("requested_datetime_iso", ""),
           "ISO datetime is 17:00 (PM heuristic for '5 საათზე')")
    _check("ნომერ" in r, "Response asks for the missing phone")
    for fake in ("დაჯავშნილია", "დაგაჯავშნე", "ჩაწერილი ხართ"):
        _check(fake not in r, f"No fake confirmation phrase {fake!r}")

    r = _send(sender, "599123456")
    _check(convo.lead.phone == "599123456", "Phone captured")
    _check(convo.lead.challenge == "", "Phone NOT stored as challenge")
    _check(convo.state == "DONE", "State transitioned to DONE on Calendar success")
    _check(convo.pending_booking is None, "pending_booking cleared after booking")
    _check("დაჯავშნილია" in r, "Real booking confirmation present")
    _check(convo.lead.calendly_booked is True, "lead.calendly_booked = True")


def scenario_b_manager_interrupt_during_pending() -> None:
    """B → user switches to manager request after pending is set."""
    _hr()
    print("Scenario B — manager interrupt during pending booking")
    _hr()
    _patch_environment(calendar_success=True)
    _reset()
    sender = "sim-pb-B"

    _send(sender, "გამარჯობა, ბანაკი მაინტერესებს")
    r = _send(sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე")
    convo = conversation_service.conversations[sender]
    _check(convo.pending_booking is not None, "pending_booking set after booking request")

    r = _send(sender, "მენეჯერი დამიკავშირდეს")
    _check(convo.pending_booking is None, "pending_booking cleared on manager interrupt")
    _check("მენეჯერ" in r, "Response acknowledges manager handoff")
    _check("ნომერ" in r, "Asks for phone (lead.phone empty)")
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        _check(forbidden not in r, f"No discovery cue {forbidden!r}")


def scenario_c_factual_interrupt_during_pending() -> None:
    """C → user asks price mid-pending; pending must remain active."""
    _hr()
    print("Scenario C — factual interrupt (price) during pending booking")
    _hr()
    _patch_environment(calendar_success=True)
    _reset()
    sender = "sim-pb-C"

    _send(sender, "გამარჯობა, ბანაკი მაინტერესებს")
    _send(sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე")
    convo = conversation_service.conversations[sender]
    _check(convo.pending_booking is not None, "pending_booking set")

    r = _send(sender, "ფასი რა არის?")
    _check("2150" in r, "Price content in response")
    _check("ნომერ" in r, "Reminder about missing phone")
    _check(convo.pending_booking is not None, "pending_booking preserved")
    for forbidden in ("რა აწუხებთ", "შინაგანი მიზეზი"):
        _check(forbidden not in r, f"No discovery cue {forbidden!r}")
    for fake in ("დაჯავშნილია", "დაგაჯავშნე"):
        _check(fake not in r, f"No fake confirmation {fake!r}")


def main() -> int:
    scenario_a_phone_only_continuation()
    scenario_b_manager_interrupt_during_pending()
    scenario_c_factual_interrupt_during_pending()

    print()
    print("=" * 60)
    if _failures == 0:
        print("✅ All pending-booking manual checks passed.")
    else:
        print(f"❌ {_failures} pending-booking check(s) failed.")
    print("=" * 60)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
