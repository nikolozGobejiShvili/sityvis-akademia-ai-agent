"""Prompt-leak regression — `system_parent_v2.md` must NOT hardcode camp
stream dates (source-of-truth cleanup, 2026-06-22).

Camp stream dates are canonical in `data/admin_config/sections.yaml` →
`admin_config_service.get_camp_facts()` → the `get_camp_info("streams")` tool +
the visible-stream date filter (`is_camp_stream_visible`). A literal stream
date in the LIVE PARENT prompt can drift from Admin Config AND from the
date-filter (e.g. keep showing a stream that has already started), so the
prompt must route stream/date questions through `get_camp_info` and never emit
a date from prompt memory.

This test is asserted against the prompt text the live engine actually loads
(`prompt_loader.load_prompt("system_parent_v2")`). It was written to FAIL on
the pre-cleanup prompt (which hardcoded the three stream ranges at line ~293).
"""
from __future__ import annotations

import re

import pytest

from app.agent.llm.prompt_loader import load_prompt

PROMPT = load_prompt("system_parent_v2")

# Both hyphen (U+002D) and en-dash (U+2013) variants of each stream range.
_LITERAL_STREAM_DATES = [
    "23-29 ივნისი", "23–29 ივნისი",
    "5-11 ივლისი", "5–11 ივლისი",
    "14-20 ივლისი", "14–20 ივლისი",
]

# Any „<dd>-<dd> <summer-month>" range — catches future re-introductions too,
# not just today's three literal streams. (A single date like „26 მაისს" — the
# consultation example — is not a range and not a summer month, so it is safe.)
_SUMMER_RANGE_RE = re.compile(r"\d{1,2}\s*[-–]\s*\d{1,2}\s*(ივნის|ივლის|აგვისტ)")


@pytest.mark.parametrize("literal", _LITERAL_STREAM_DATES)
def test_v2_prompt_has_no_literal_stream_date(literal):
    assert literal not in PROMPT, (
        f"system_parent_v2.md must NOT hardcode the stream date {literal!r}; "
        "camp stream dates must come from get_camp_info, not the prompt."
    )


def test_v2_prompt_has_no_summer_month_date_range():
    m = _SUMMER_RANGE_RE.search(PROMPT)
    assert m is None, (
        "system_parent_v2.md contains a hardcoded summer date range "
        f"{m.group(0)!r}; camp stream dates must come from get_camp_info."
    )


def test_v2_prompt_still_routes_streams_through_get_camp_info():
    # The cleanup must PRESERVE tool-grounding, not just delete the dates.
    assert "get_camp_info" in PROMPT, "stream/date questions must use get_camp_info"
    assert "ნაკად" in PROMPT, "stream concept must still be taught"
    # And it must explicitly forbid emitting a stream date from memory/prompt.
    assert any(
        marker in PROMPT
        for marker in ("არ გამოიგონო", "მეხსიერებიდან", "არ დაწერო")
    ), "prompt must forbid inventing/memory stream dates"
