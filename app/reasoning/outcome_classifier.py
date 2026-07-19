"""Pure outcome classifier for Phase 5 (bounded, human-gated learning).

Classifies the coarse OUTCOME of a single turn — used by the (flag-gated,
Task 3+) learning-log capture hook. This module is intentionally PURE: no
I/O, no settings import, no side effects, never raises. It only reads
attributes off the objects it is given (defensively, via ``getattr`` with
safe defaults) and returns one of a closed set of short strings.

Priority order (first match wins):
    1. empty/blank ``response``                          -> "empty"
    2. ``lead.calendly_booked`` OR ``lead.booked_datetime_iso`` -> "booked"
    3. ``manager_notified`` is truthy                     -> "handed_off"
    4. ``conversation.segment == "UNCLEAR"``               -> "unclear"
    5. otherwise                                           -> "answered"

There is deliberately NO "declined" outcome here — a decline is a *user
intent* detected earlier in the turn (by the deterministic decline
handlers), not something reliably visible from the post-response state.
For v1 a declined turn still lands in "answered" (or another bucket per
the priority order above).
"""
from __future__ import annotations

from typing import Any


def classify_outcome(
    conversation: Any,
    lead: Any,
    response: Any,
    *,
    manager_notified: bool = False,
) -> str:
    # 1. empty / blank response.
    if not isinstance(response, str) or not response.strip():
        return "empty"

    # 2. booked — either explicit flag or a stored booked datetime.
    calendly_booked = bool(getattr(lead, "calendly_booked", False))
    booked_datetime_iso = getattr(lead, "booked_datetime_iso", "") or ""
    if calendly_booked or booked_datetime_iso:
        return "booked"

    # 3. handed off to a human manager this turn.
    if manager_notified:
        return "handed_off"

    # 4. the deterministic segment classifier could not place the lead.
    segment = getattr(conversation, "segment", "") or ""
    if segment == "UNCLEAR":
        return "unclear"

    # 5. default — a normal answered turn.
    return "answered"
