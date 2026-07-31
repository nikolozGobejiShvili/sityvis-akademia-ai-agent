"""Live test 2026-07-29/30 — four defects proven by the Railway logs.

Each test pins the FACT the live run got wrong, not the wording used to say it.

1. `[book_consultation] BLOCKED reason=datetime_in_past slot=2026-05-27T10:00`
   — the model copied the prompt's most-repeated example date. No literal
   Georgian month+day may remain in a live prompt.
2. „30 ივნისს შემდეგი დროები გვაქვს თავისუფალი" sent on 29 July, then the
   user's pick from that very list refused as past. A past day has no slots.
3. „სამუშაო საათები არის 10:00 – 17:00" — a figure that appears nowhere in
   the repo. The booking window must travel in the per-turn context, next to
   the dates, sourced from the module the executor enforces.
4. After booking 10:00 the parent asked to also cover Sunday School; the
   re-check hit their OWN consultation and the agent answered
   „ეს დრო ვეღარ ხელმისაწვდომია". Own booking is not a conflict.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from unittest.mock import patch

from app.agent.llm.prompt_loader import load_prompt, reset_cache
from app.models.conversation import Conversation
from app.models.lead import Lead

# A number followed by a Georgian month name, in any declension.
LITERAL_DATE_RE = re.compile(
    r"\d{1,2}\s*(?:მაის|ივნის|ივლის|აგვისტო)[ა-ჿ]*"
)


# ── 1. no literal example dates in the live prompts ────────────────────────


def test_live_prompts_carry_no_literal_georgian_dates():
    reset_cache()
    for stem in ("system_parent_v2", "parent_lean", "system_adult_v1"):
        found = LITERAL_DATE_RE.findall(load_prompt(stem))
        assert not found, f"{stem}.md still carries literal dates: {sorted(set(found))}"


def test_live_prompts_still_format_with_only_the_supplied_keys():
    """Removing the dates must not disturb the `.format()` contract — an
    unescaped `{...}` anywhere raises KeyError at engine start-up."""
    reset_cache()
    supplied = {"company_name", "age_min", "age_max"}
    for stem in ("system_parent_v2", "parent_lean", "system_adult_v1"):
        raw = load_prompt(stem)
        fields = set(re.findall(r"(?<!\{)\{([^{}]*)\}(?!\})", raw))
        assert fields <= supplied, f"{stem}.md has unsupplied placeholders: {fields - supplied}"
    load_prompt("system_parent_v2").format(
        company_name="სიტყვის აკადემია", age_min=9, age_max=17,
    )


# ── 2. a past day has no free slots ────────────────────────────────────────


def test_past_day_returns_no_slots_future_day_unaffected():
    from app.services import calendar_service as cal

    today = cal.datetime.now(cal.TIMEZONE).date()
    with patch.object(cal, "_free_busy_intervals", return_value=[]):
        assert cal._get_free_slots_for_day(today - timedelta(days=1), 60) == []
        assert cal._get_free_slots_for_day(today - timedelta(days=30), 60) == []
        # A future weekday still yields a full slate — the guard is past-only.
        future = today + timedelta(days=1)
        while cal.is_closed_booking_day(future):
            future += timedelta(days=1)
        assert cal._get_free_slots_for_day(future, 60)


def test_get_free_slots_range_starting_in_the_past_yields_only_future_days():
    """The live shape: the model asked for a range beginning on a past date."""
    from app.services import calendar_service as cal

    today = cal.datetime.now(cal.TIMEZONE).date()
    with patch.object(cal, "_free_busy_intervals", return_value=[]):
        slots = cal.get_free_slots(start_date=today - timedelta(days=3), days=3)
    assert slots == [], "a fully-past range must offer nothing"


# ── 3. the booking window travels with the turn ────────────────────────────


def test_context_message_carries_the_booking_window_from_calendar_service():
    from app.agent.llm.parent_llm_engine import _build_context_message
    from app.services import calendar_service as cal

    conv = Conversation(sender_id="s1", platform="messenger", segment="PARENT")
    lead = Lead(sender_id="s1", platform="messenger", segment="PARENT")
    out = _build_context_message(conv, lead, "ხვალ 17:00 შეიძლება?")

    expected = (
        f"{cal.BUSINESS_HOUR_START.strftime('%H:%M')}-"
        f"{cal.BUSINESS_HOUR_END.strftime('%H:%M')}"
    )
    assert f"booking_hours_tbilisi={expected}" in out
    assert "booking_slot_minutes=60" in out
    # It must sit with the dates, not drift to the end of a long block.
    assert out.index("booking_hours_tbilisi") < out.index("child_age=")


# ── 4. the lead's own booking is not a conflict ────────────────────────────


def _booked_lead(iso: str) -> Lead:
    lead = Lead(sender_id="s1", platform="messenger", segment="PARENT")
    lead.calendly_booked = True
    lead.calendar_event_id = "ev-1"
    lead.booked_datetime_iso = iso
    return lead


def test_own_booking_detected_only_for_the_exact_slot():
    from app.agent.tools.parent_tool_executor import _is_own_existing_booking

    lead = _booked_lead("2026-07-31T10:00:00+04:00")
    assert _is_own_existing_booking(lead, "2026-07-31T10:00:00+04:00")
    assert not _is_own_existing_booking(lead, "2026-07-31T11:00:00+04:00")
    assert not _is_own_existing_booking(lead, "")

    lead.calendly_booked = False
    assert not _is_own_existing_booking(lead, "2026-07-31T10:00:00+04:00")

    lead.calendly_booked = True
    lead.calendar_event_id = ""
    assert not _is_own_existing_booking(lead, "2026-07-31T10:00:00+04:00")


def test_own_booking_and_a_stranger_booking_are_reported_differently():
    """Both hit a busy Calendar; only the stranger's block offers alternatives."""
    from app.agent.tools import parent_tool_executor as X
    from app.services import calendar_service as cal

    # A near-future weekday, so only the Calendar stub decides availability.
    target = date.today() + timedelta(days=2)
    while cal.is_closed_booking_day(target):
        target += timedelta(days=1)
    iso = f"{target.isoformat()}T10:00:00+04:00"

    def _run(lead: Lead) -> dict:
        conv = Conversation(sender_id="s1", platform="messenger", segment="PARENT")
        conv.lead = lead
        ex = X.ParentToolExecutor(
            conversation=conv, lead=lead, sender_id="s1",
            platform="messenger", user_message="10 საათზე",
        )
        # `calendar_service` is imported inside the method — patch the source.
        # Registration state is a separate concern and is closed once every
        # camp stream has started; pin it open so this test isolates the
        # busy-slot branch.
        with patch.object(cal, "check_slot_calendar_only", return_value=False), \
             patch.object(ex, "_registration_open_for_booking", return_value=True), \
             patch.object(ex, "_alternative_slots_for", return_value=[{"slot_id": 1}]):
            return ex._check_consultation_slot({"datetime_iso": iso})

    own = _run(_booked_lead(iso))
    assert own["reason"] == "already_booked_by_this_lead"
    assert own["available"] is False
    assert own["alternative_slots"] == [], "never offer to move an appointment nobody asked to move"
    assert own["booked_datetime_iso"] == iso

    stranger = _run(Lead(sender_id="s1", platform="messenger", segment="PARENT"))
    assert stranger["reason"] == "calendar_busy"
    assert stranger["alternative_slots"], "a genuine conflict still offers alternatives"


def test_prompt_tells_the_model_what_the_new_reason_code_means():
    """A reason code the prompt never mentions leaves the model to improvise —
    which is how the live run produced „ვეღარ ხელმისაწვდომია" plus two apologies."""
    reset_cache()
    text = load_prompt("system_parent_v2")
    assert "already_booked_by_this_lead" in text
