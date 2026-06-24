"""Georgian Colloquial Time Patch (2026-06-10).

Live bug: the same colloquial hour was interpreted inconsistently across
Messenger conversations. "12 ივნის 8 საათზე" → 20:00 (correct) in one
account, but "12 ივნის მინდა 8 სათზე" (typo + „მინდა" before the time)
→ 08:00 / outside-hours in another. Root cause: the colloquial PM
heuristic lived only in the legacy router; the engine path left the hour
to the stochastic LLM, and neither parser supported the typo „სათზе".

These tests pin the deterministic normalization layer
(`timestamps.extract_colloquial_hour` / `apply_colloquial_time_to_iso`)
and the executor chokepoint
(`ParentToolExecutor._normalise_datetime_iso_from_message`) which runs
before check_consultation_slot / book_consultation / reschedule.
"""

from __future__ import annotations

import pytest

from app.agent.services import timestamps as ts
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.flows import parent_turn_router
from app.models.conversation import Conversation
from app.models.lead import Lead


def _hour(text: str):
    parsed = ts.extract_colloquial_hour(text)
    return None if parsed is None else parsed[0]


# ===========================================================================
# PART 2 — deterministic hour mapping (the 14 spec cases)
# ===========================================================================


@pytest.mark.parametrize("text, expected_hour", [
    ("12 ივნის 8 საათზე არის შესაძლებელი?", 20),   # 1
    ("12 ივნის მინდა 8 სათზე თუ არის თავისუფალი", 20),  # 2 typo + მინდა
    ("12 ივნისს 8-ზე", 20),                         # 3
    ("12 ივნისს 8 საათისთვის", 20),                 # 4
    ("12 ივნისს 8 სთ-ზე", 20),                       # 5
    ("8 საათზე თავისუფალია?", 20),                   # 6
    ("7 საათზე თავისუფალია?", 19),                   # 7
    ("6 საათზე თავისუფალია?", 18),                   # 8
    ("საღამოს 8 საათზე", 20),                        # 10
    ("10 საათზე", 10),                               # 12
    ("11 საათზე", 11),                               # 13
    ("12 საათზე", 12),                               # 14
    # extra variants from the spec body
    ("8 საათი", 20),
    ("8 სთ-ზე", 20),
    ("საღამოს 8", 20),
    ("8 საათი იგივე არ არის?", 20),
    ("1 საათზე", 13),
    ("9 საათზე", 21),
])
def test_unqualified_and_evening_hours_map_to_pm(text, expected_hour):
    assert _hour(text) == expected_hour


@pytest.mark.parametrize("text, expected_hour", [
    ("დილის 8 საათზე", 8),     # 9 — explicit morning stays morning
    ("დილით 9 საათზე", 9),
    ("დილის 8", 8),
])
def test_explicit_morning_stays_morning(text, expected_hour):
    assert _hour(text) == expected_hour


def test_evening_10_maps_to_22():
    # 11 — საღამოს 10 → 22:00 (outside hours, but parsed as 22)
    assert _hour("საღამოს 10 საათზე") == 22


def test_explicit_hhmm_is_literal():
    assert ts.extract_colloquial_hour("20:00 თავისუფალია?") == (20, 0)
    assert ts.extract_colloquial_hour("08:00 ხო?") == (8, 0)
    assert ts.extract_colloquial_hour("10:30") == (10, 30)


@pytest.mark.parametrize("text", [
    "გამარჯობა", "12 წლის არის", "8 წლის ბავშვი", "", "მინდა ჩაწერა",
])
def test_no_time_returns_none(text):
    assert ts.extract_colloquial_hour(text) is None


def test_age_phrase_not_parsed_as_hour():
    # "8 წლის" must NOT be read as a time.
    assert ts.extract_colloquial_hour("ბავშვი 8 წლის არის") is None


# ===========================================================================
# apply_colloquial_time_to_iso — preserves date, overrides hour
# ===========================================================================


def test_apply_overrides_hour_preserves_date():
    out = ts.apply_colloquial_time_to_iso(
        "2026-06-12T08:00:00+04:00", "12 ივნის მინდა 8 სათზე",
    )
    assert out.startswith("2026-06-12T20:00")


def test_apply_noop_when_no_time_in_message():
    iso = "2026-06-12T20:00:00+04:00"
    assert ts.apply_colloquial_time_to_iso(iso, "კი მინდა") == iso


def test_apply_morning_keeps_0800():
    out = ts.apply_colloquial_time_to_iso(
        "2026-06-12T15:00:00+04:00", "დილის 8 საათზე",
    )
    assert out.startswith("2026-06-12T08:00")


def test_apply_unparseable_iso_returns_input():
    assert ts.apply_colloquial_time_to_iso("not-an-iso", "8 საათზე") == "not-an-iso"


# ===========================================================================
# Executor chokepoint — used by check / book / reschedule
# ===========================================================================


def _executor(message: str) -> ParentToolExecutor:
    conv = Conversation(sender_id="t_time", platform="instagram")
    lead = Lead(sender_id="t_time", platform="instagram", segment="PARENT")
    conv.lead = lead
    return ParentToolExecutor(
        conversation=conv, lead=lead, sender_id="t_time",
        platform="instagram", user_message=message,
    )


def test_executor_normalises_typo_hour_to_2000():
    ex = _executor("12 ივნის მინდა 8 სათზე თუ არის თავისუფალი")
    # LLM wrongly passed 08:00 — chokepoint must correct to 20:00.
    out = ex._normalise_datetime_iso_from_message("2026-06-12T08:00:00+04:00")
    assert out.startswith("2026-06-12T20:00")


def test_executor_keeps_correct_llm_time():
    ex = _executor("12 ივნის 8 საათზე არის შესაძლებელი?")
    out = ex._normalise_datetime_iso_from_message("2026-06-12T20:00:00+04:00")
    assert out.startswith("2026-06-12T20:00")


def test_executor_morning_not_remapped():
    ex = _executor("დილის 8 საათზე")
    out = ex._normalise_datetime_iso_from_message("2026-06-12T08:00:00+04:00")
    assert out.startswith("2026-06-12T08:00")


def test_executor_active_date_time_only_followup():
    """Time-only follow-up („8 საათზე თავისუფალია?") keeps the date the
    LLM carried from the active booking context, hour normalised to 20."""
    ex = _executor("8 საათზე თავისუფალია?")
    out = ex._normalise_datetime_iso_from_message("2026-06-12T09:00:00+04:00")
    assert out.startswith("2026-06-12T20:00")


def test_executor_seven_oclock_followup():
    ex = _executor("7 საათზე თავისუფალია?")
    out = ex._normalise_datetime_iso_from_message("2026-06-12T09:00:00+04:00")
    assert out.startswith("2026-06-12T19:00")


def test_executor_noop_without_user_message():
    ex = _executor("")
    iso = "2026-06-12T20:00:00+04:00"
    assert ex._normalise_datetime_iso_from_message(iso) == iso


def test_executor_contact_state_irrelevant_to_parsing():
    """Same message → same normalized hour regardless of whether
    name/phone are already on the lead (contact state must not change
    time parsing)."""
    for name, phone in (("", ""), ("ნიკა", "595999733"), ("", "595999733")):
        conv = Conversation(sender_id="cs", platform="instagram")
        lead = Lead(
            sender_id="cs", platform="instagram", segment="PARENT",
            name=name, phone=phone,
        )
        conv.lead = lead
        ex = ParentToolExecutor(
            conversation=conv, lead=lead, sender_id="cs",
            platform="instagram", user_message="12 ივნის 8 სათზე",
        )
        out = ex._normalise_datetime_iso_from_message(
            "2026-06-12T08:00:00+04:00",
        )
        assert out.startswith("2026-06-12T20:00"), (name, phone)


# ===========================================================================
# Legacy router parser shares the same behaviour (compound-booking path)
# ===========================================================================


def test_router_parser_typo_and_pm_heuristic():
    iso = parent_turn_router._parse_booking_datetime("12 ივნის მინდა 8 სათზე")
    assert iso is not None
    assert "T20:00" in iso


def test_router_parser_morning_kept():
    iso = parent_turn_router._parse_booking_datetime("12 ივნის დილის 8 საათზე")
    assert iso is not None
    assert "T08:00" in iso


def test_router_parser_literal_double_digit():
    iso = parent_turn_router._parse_booking_datetime("12 ივნის 11 საათზე")
    assert iso is not None
    assert "T11:00" in iso
