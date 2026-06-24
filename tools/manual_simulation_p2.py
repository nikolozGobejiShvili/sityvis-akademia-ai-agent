"""Manual simulation — P2 task.

Drives the live `conversation_service` through the multi-turn flow from
PART 11, with external services stubbed (Meta profile, OpenAI
start-intent, Calendar, Sheets, notification) so the run is
deterministic and offline.

Verifies:
  * Age input does not trigger problem-assumption framing.
  * "no concern" input is accepted naturally.
  * Payment-question grammar (no awkward phrases, locative location).
  * Booking attempt flow: ask for phone → continuation → real Calendar
    write only on success (no fake confirmation).
  * Invalid phone vs valid phone handling.
  * DONE state — gratitude, repeated gratitude, identity, name —
    each produce a DIFFERENT, non-awkward, non-template response.
  * After DONE: NO duplicate Calendar / Sheets / notification calls.

Run from repo root:

    PYTHONIOENCODING=utf-8 python tools/manual_simulation_p2.py
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

# P3-C PATCH 1 — this legacy simulation exercises the P0/P1/P2 path.
# If `.env` has flipped USE_PARENT_LLM_ENGINE=true for live testing the
# new engine, route through it would intercept every turn and break
# these assertions. Pin the flag off for the duration of this script.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=False,
)


_failures = 0
_calendar_calls: list[dict] = []
_sheets_calls: list[object] = []
_notify_calls: list[tuple] = []


AWKWARD_STRINGS = (
    "ბანაკის პირობებზე გელაპარაკოთ",
    "კაჭრეთი-ში",
    "რამდენად შეეფერება",
    "ცოტა ზუსტად რომ მესმოდეს",
)


def _patch_environment(*, calendar_success: bool = True) -> None:
    messenger_service.get_user_profile = lambda sender_id, platform: {
        "name": "ანა ლომიძე", "first_name": "ანა",
        "last_name": "ლომიძე", "username": "",
    }
    openai_service.detect_start_intent = lambda message: "GREETING"
    openai_service.generate_summary = lambda history: "summary"

    calendar_service.check_slot_available = (
        lambda dt, duration_minutes=30: calendar_success
    )

    def _book(**kwargs):
        _calendar_calls.append(dict(kwargs))
        return calendar_success
    calendar_service.book_slot = _book

    def _create(lead):
        _sheets_calls.append(lead)
        return True
    sheets_service.create_lead = _create

    def _notify(lead, summary):
        _notify_calls.append((lead, summary))
        return True
    notification_service.send_manager_notification = _notify


def _reset() -> None:
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()
    _calendar_calls.clear()
    _sheets_calls.clear()
    _notify_calls.clear()


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


def _assert_no_awkward(text: str, label: str) -> None:
    for bad in AWKWARD_STRINGS:
        _check(bad not in text, f"{label}: no '{bad}'")


def _hr() -> None:
    print()
    print("=" * 64)


def run() -> int:
    _patch_environment(calendar_success=True)
    _reset()
    sender = "sim-p2"

    _hr()
    print("PART 11 — P2 manual simulation")
    _hr()

    _send(sender, "გამარჯობა")

    _send(sender, "საზაფხულო ბანაკი")

    r = _send(sender, "14 წლის არის")
    _check("რა აწუხებთ" not in r, "Age input: no 'რა აწუხებთ' problem-framing")
    _check("შინაგანი მიზეზი" not in r, "Age input: no 'შინაგანი მიზეზი'")
    _check("?" in r or "—" in r, "Age input: bot asks a follow-up")
    _assert_no_awkward(r, "Age input")

    r = _send(sender, "არაფერი, უბრალოდ გაშვება მინდა")
    _check("რა აწუხებთ" not in r, "No-concern: no problem framing")
    _check("შინაგანი მიზეზი" not in r, "No-concern: no 'შინაგანი მიზეზი'")
    _assert_no_awkward(r, "No-concern")

    r = _send(sender, "პირობები მაინტერესებს გადახდის")
    _check("2150" in r, "Payment: contains price")
    _check("ამბასადორ კაჭრეთში" in r, "Payment: locative location")
    _assert_no_awkward(r, "Payment")

    r = _send(sender, "კი ჩამწერეთ 25 მაისს 12:00 საათზე თუ არის შესაძლებელი")
    _check("ნომერ" in r, "Booking-with-time: asks for phone")
    for fake in ("დაჯავშნილია", "დაგაჯავშნე"):
        _check(fake not in r, f"Booking-with-time: no fake '{fake}'")
    convo = conversation_service.conversations[sender]
    _check(convo.pending_booking is not None, "Booking-with-time: pending_booking set")

    r = _send(sender, "ნიკოლოზი 59599973")
    _check(
        any(t in r for t in ("9-ციფრიანი", "ნომერი")),
        "Invalid phone: asks for valid 9-digit",
    )
    _check(convo.lead.phone == "", "Invalid phone: not saved")

    r = _send(sender, "595999733")
    _check(convo.lead.phone == "595999733", "Valid phone: saved")
    _check(convo.state == "DONE", "State: DONE after successful booking")
    _check(convo.lead.calendly_booked is True, "lead.calendly_booked = True")
    _check(convo.lead.booked_datetime_iso != "", "lead.booked_datetime_iso set")
    _check("დაჯავშნილია" in r, "Real confirmation present")

    bookings_after_first = len(_calendar_calls)
    sheets_after_first = len(_sheets_calls)
    notifies_after_first = len(_notify_calls)

    _hr()
    print("DONE-state interactions")
    _hr()

    r1 = _send(sender, "მადლობა")
    _check("მადლობა" in r1 or "მოხარული" in r1 or "კონსულტანტი" in r1,
           "Gratitude #1: natural acknowledgement")
    _assert_no_awkward(r1, "Gratitude #1")
    _check(len(_calendar_calls) == bookings_after_first,
           "Gratitude #1: no extra Calendar call")
    _check(len(_sheets_calls) == sheets_after_first,
           "Gratitude #1: no extra Sheets row")
    _check(len(_notify_calls) == notifies_after_first,
           "Gratitude #1: no extra manager notification")

    r2 = _send(sender, "მადლობა")
    _check(r2.strip() != r1.strip(), "Gratitude #2 differs from #1")
    _assert_no_awkward(r2, "Gratitude #2")

    r3 = _send(sender, "შენ ვინ ხარ?")
    _check("ასისტენტი" in r3, "Identity question at DONE: assistant identity")
    _assert_no_awkward(r3, "Identity-at-DONE")

    r4 = _send(sender, "შენ რა გქვია?")
    _check("ასისტენტი" in r4, "Name question at DONE: identity reply")
    _assert_no_awkward(r4, "Name-at-DONE")

    _check(len(_calendar_calls) == bookings_after_first,
           "After DONE messages: no duplicate Calendar calls")
    _check(len(_sheets_calls) == sheets_after_first,
           "After DONE messages: no duplicate Sheets rows")
    _check(len(_notify_calls) == notifies_after_first,
           "After DONE messages: no duplicate manager notifications")

    _hr()
    if _failures == 0:
        print("✅ All P2 manual checks passed.")
    else:
        print(f"❌ {_failures} P2 manual check(s) failed.")
    _hr()
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(run())
