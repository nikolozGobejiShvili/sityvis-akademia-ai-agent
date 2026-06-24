"""Email Content Cleanup (2026-06-10) — manager notification.

`lead.challenge` is captured from natural chat and can carry filler
("ასევე მაინტერესებს", "კი მინდა") and factual questions
("როდის ტარდება") mixed into the real parent goals. The manager email
must show only clean goals under „ინტერესი / გამოწვევა"; a factual
question (if any) goes to an optional „დამატებითი კითხვა" line; the
summary must not echo raw chat text. `lead.challenge` itself is NOT
mutated (Sheets/CRM unaffected).
"""

from __future__ import annotations

import pytest

from app.models.lead import Lead
from app.services import notification_service as ns


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _lead(**overrides) -> Lead:
    base = dict(
        sender_id="cleanup-1",
        platform="messenger",
        segment="PARENT",
        name="Nika Gobejishvili",
        phone="595999733",
        child_age="15",
        challenge="",
        calendly_booked=True,
        booked_datetime_iso="2026-06-11T19:00:00+04:00",
        status="Booked",
    )
    base.update(overrides)
    return Lead(**base)


_LIVE_RAW_CHALLENGE = (
    "მეგობრები, განვითარება, ასევე ეკრანიდან დისტანცია, "
    "ასევე მაინტერესებს ბანაკის დეტალებში როდის ტარდება"
)


# ===========================================================================
# 1. raw phrase not in challenge field
# ===========================================================================


def test_raw_filler_phrase_not_in_cleaned_challenge():
    cleaned = ns._clean_challenge_for_email(_LIVE_RAW_CHALLENGE)
    assert "ასევე მაინტერესებს" not in cleaned
    assert "მაინტერესებს" not in cleaned
    assert "როდის ტარდება" not in cleaned
    assert "დეტალებში" not in cleaned


def test_raw_filler_not_in_email_body():
    body = ns._manager_email_body(_lead(challenge=_LIVE_RAW_CHALLENGE))
    # The interest/challenge field and the whole body must be clean of
    # the raw chat/question text.
    interest_section = body.split("ინტერესი / გამოწვევა:", 1)[1]
    interest_line = interest_section.splitlines()[0]
    assert "ასევე მაინტერესებს" not in interest_line
    assert "როდის ტარდება" not in interest_line
    assert "კი მინდა" not in interest_line


# ===========================================================================
# 2. parent goals preserved (normalised)
# ===========================================================================


def test_parent_goals_preserved_normalised():
    cleaned = ns._clean_challenge_for_email(_LIVE_RAW_CHALLENGE)
    assert cleaned == "მეგობრები, განვითარება, ეკრანთან დროის შემცირება"


def test_unknown_goal_passes_through_untouched():
    cleaned = ns._clean_challenge_for_email("თვითგამოხატვა, თავდაჯერება")
    assert "თვითგამოხატვა" in cleaned
    assert "თავდაჯერება" in cleaned


def test_clean_phrase_unchanged():
    """A clean challenge (no filler / questions) is preserved verbatim —
    protects the existing email-wording fixture behaviour."""
    raw = "ახალი თავგადასავლები და ბავშვის განვითარება"
    assert ns._clean_challenge_for_email(raw) == raw


# ===========================================================================
# 3. factual question separated, not mixed into challenge
# ===========================================================================


def test_factual_question_separated_into_optional_field():
    q = ns._extract_additional_question(_LIVE_RAW_CHALLENGE)
    assert "როდის ტარდება" in q
    assert q.endswith("?")
    # And it is NOT in the cleaned challenge.
    cleaned = ns._clean_challenge_for_email(_LIVE_RAW_CHALLENGE)
    assert "როდის" not in cleaned


def test_additional_question_line_in_email_when_present():
    body = ns._manager_email_body(_lead(challenge=_LIVE_RAW_CHALLENGE))
    assert "დამატებითი კითხვა:" in body
    q_line = body.split("დამატებითი კითხვა:", 1)[1].splitlines()[0]
    assert "როდის ტარდება" in q_line


def test_no_additional_question_line_when_no_question():
    body = ns._manager_email_body(_lead(challenge="მეგობრები, განვითარება"))
    assert "დამატებითი კითხვა:" not in body


# ===========================================================================
# 4. summary does not duplicate raw user text
# ===========================================================================


def test_summary_excludes_raw_chat_text():
    body = ns._manager_email_body(_lead(challenge=_LIVE_RAW_CHALLENGE))
    summary_section = body.split("მოკლე რეზიუმე:", 1)[1]
    assert "ასევე მაინტერესებს" not in summary_section
    assert "როდის ტარდება" not in summary_section


def test_summary_uses_cleaned_goals():
    summary = ns._build_parent_summary(_lead(challenge=_LIVE_RAW_CHALLENGE))
    assert "ეკრანთან დროის შემცირება" in summary
    assert "ასევე მაინტერესებს" not in summary


# ===========================================================================
# 5. unknown challenge → "არ არის მითითებული"
# ===========================================================================


def test_unknown_challenge_placeholder_in_email():
    body = ns._manager_email_body(_lead(challenge=""))
    interest_line = body.split("ინტერესი / გამოწვევა:", 1)[1].splitlines()[0]
    assert "არ არის მითითებული" in interest_line


def test_challenge_that_is_only_filler_becomes_unknown():
    """A challenge made entirely of filler / questions cleans to empty
    → placeholder, never invented content."""
    body = ns._manager_email_body(
        _lead(challenge="ასევე მაინტერესებს, კი მინდა, როდის ტარდება"),
    )
    interest_line = body.split("ინტერესი / გამოწვევა:", 1)[1].splitlines()[0]
    assert "არ არის მითითებული" in interest_line
    assert "მაინტერესებს" not in interest_line


def test_clean_challenge_empty_for_pure_filler():
    assert ns._clean_challenge_for_email("ასევე მაინტერესებს, კი მინდა") == ""


# ===========================================================================
# 6. booking date/time, name, phone, child age still appear
# ===========================================================================


def test_structured_fields_still_present():
    body = ns._manager_email_body(_lead(challenge=_LIVE_RAW_CHALLENGE))
    assert "ბავშვის ასაკი: 15" in body
    assert "Nika Gobejishvili" in body
    assert "595999733" in body
    assert "11 ივნისი, 19:00" in body  # booked datetime, Georgian


# ===========================================================================
# 7. lead.challenge is NOT mutated (Sheets/CRM unaffected)
# ===========================================================================


def test_lead_challenge_not_mutated():
    lead = _lead(challenge=_LIVE_RAW_CHALLENGE)
    _ = ns._manager_email_body(lead)
    assert lead.challenge == _LIVE_RAW_CHALLENGE


# ===========================================================================
# 8. negation / edge inputs
# ===========================================================================


@pytest.mark.parametrize("raw", ["", None, "   "])
def test_empty_inputs_clean_to_empty(raw):
    assert ns._clean_challenge_for_email(raw) == ""
    assert ns._extract_additional_question(raw) == ""
