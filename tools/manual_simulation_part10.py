"""Manual simulation script — PART 10 of the Silent-Intent-Router task.

Drives the live conversation_service through the exact eight-message
flow from the task spec and prints each response, with assertions that
match the per-turn expected behaviour. External services (Meta profile
fetch, OpenAI start-intent classifier) are stubbed so the run is
deterministic and offline.

Run from repo root:

    PYTHONIOENCODING=utf-8 python tools/manual_simulation_part10.py
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
    conversation_service, messenger_service, openai_service,
)

# P3-C PATCH 1 — pin the new LLM engine off so this legacy P0 sim drives
# the original silent-intent-router path even when .env flips it on.
parent_flow.settings = dataclasses.replace(
    config_module.settings, USE_PARENT_LLM_ENGINE=False,
)


def _patch_environment() -> None:
    """Stub Meta profile + OpenAI start-intent so no external calls fire."""
    messenger_service.get_user_profile = lambda sender_id, platform: {
        "name": "ანა ლომიძე", "first_name": "ანა",
        "last_name": "ლომიძე", "username": "",
    }
    openai_service.detect_start_intent = lambda message: "GREETING"


def _reset() -> None:
    conversation_service.conversations.clear()
    parent_turn_router.manager_offer_shown.clear()
    parent_flow.available_slots.clear()
    parent_flow.ask_name_retries.clear()
    parent_flow.invalid_phone_retries.clear()
    parent_flow.slots_shown_for_state.clear()


def _send(sender: str, message: str) -> str:
    return conversation_service.process_message(sender, message, "instagram")


def _check(condition: bool, label: str) -> None:
    marker = "PASS" if condition else "FAIL"
    print(f"  [{marker}] {label}")
    if not condition:
        global _failures
        _failures += 1


_failures = 0


def main() -> int:
    _patch_environment()
    _reset()
    sender = "sim-part10"

    print("=" * 60)
    print("PART 10 — manual simulation")
    print("=" * 60)

    # Turn 1 — generic greeting routes via UNCLEAR (segment classifier).
    r = _send(sender, "გამარჯობა")
    print("\nUSER: გამარჯობა\nBOT:", r)
    _check(
        "ბავშვების საზაფხულო ბანაკი" in r or "ASSISTANT" not in r.upper(),
        "Welcome / segment-routing reply",
    )

    # Turn 2 — conditions question
    r = _send(sender, "ბავშვების ბანაკის პირობები")
    print("\nUSER: ბავშვების ბანაკის პირობები\nBOT:", r)
    _check("2150" in r or "ტრანსპორტი" in r, "Concise conditions answer")
    _check("რა აწუხებთ" not in r, "No psychological discovery")
    _check("გნებავთ A თუ B" not in r, "No robotic menu phrasing")

    # Turn 3 — booking request without datetime
    r = _send(sender, "კონსულტაციაზე ჩაწერა მინდა")
    print("\nUSER: კონსულტაციაზე ჩაწერა მინდა\nBOT:", r)
    _check(
        any(token in r for token in ("დღე", "საათ")),
        "Booking ask-for-time response",
    )
    _check("რა აწუხებთ" not in r, "No psychological discovery after booking ask")
    _check("შინაგანი მიზეზი" not in r, "No deeper-probe phrase")

    # Turn 4 — identity question
    r = _send(sender, "შენ ვინ ხარ?")
    print("\nUSER: შენ ვინ ხარ?\nBOT:", r)
    _check("ასისტენტი" in r, "Identity reply mentions assistant role")
    _check("ბავშვების საზაფხულო ბანაკი" not in r, "No menu repetition")

    # Turn 5 — booking with datetime, no fake confirmation
    r = _send(sender, "კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე")
    print("\nUSER: კონსულტაციაზე ჩამწერე 22 მაისს 5 საათზე\nBOT:", r)
    _check("დაჯავშნილია" not in r, "No fake 'დაჯავშნილია'")
    _check("დაგაჯავშნე" not in r, "No fake 'დაგაჯავშნე'")
    _check("ჩაწერილი ხართ" not in r, "No fake 'ჩაწერილი ხართ'")
    _check("ნომერ" in r, "Asks for missing contact info (phone)")

    # Turn 6 — manager request without phone
    r = _send(sender, "მენეჯერი დამიკავშირდეს")
    print("\nUSER: მენეჯერი დამიკავშირდეს\nBOT:", r)
    _check("ნომერ" in r, "Asks for phone (no phone known yet)")
    _check("მენეჯერ" in r, "Acknowledges manager handoff")
    _check("რა აწუხებთ" not in r, "No discovery question")

    # Turn 7 — price question
    r = _send(sender, "ფასი რა არის?")
    print("\nUSER: ფასი რა არის?\nBOT:", r)
    _check("2150" in r, "Includes the price")
    _check(
        any(t in r for t in ("ტრანსპორტი", "კვება", "განთავსება", "პროგრამა")),
        "Value framing — what is included",
    )

    # Turn 8 — combined location + dates
    r = _send(sender, "სად ტარდება და როდის არის?")
    print("\nUSER: სად ტარდება და როდის არის?\nBOT:", r)
    _check(
        any(t in r for t in ("23-29 ივნისი", "5-11 ივლისი", "14-20 ივლისი")),
        "Dates wins (strict priority) — at least one stream date present",
    )

    print()
    print("=" * 60)
    if _failures == 0:
        print("✅ All PART 10 checks passed.")
    else:
        print(f"❌ {_failures} PART 10 check(s) failed.")
    print("=" * 60)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
