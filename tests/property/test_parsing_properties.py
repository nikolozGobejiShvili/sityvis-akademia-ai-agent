"""AUDIT-ONLY Hypothesis property tests for the PARENT parsing layer.

These intentionally surface failing inputs (the red-team found garbage
captured into ``lead.name``). They MUST NOT run in the normal suite and
MUST NOT fix anything — they only generate inputs through the REAL
deterministic parser functions (no OpenAI, no network).

Run (audit):    RUN_PROPERTY_TESTS=1 python -m pytest tests/property/ -q
Normal suite:   python -m pytest tests/ -q      # these are skipped

Functions under test (file:line at the time of writing):
  * _parse_name_phone              app/flows/parent_flow.py:3767
  * _name_token_is_valid           app/flows/parent_flow.py:3725
  * _looks_like_contact_disclosure app/flows/parent_flow.py:3128
  * is_valid_person_name           app/flows/parent_flow.py:3749
  * NAME_FILLER_WORDS              app/flows/parent_flow.py:3651
  * _NAME_REJECT_STEMS             app/flows/parent_flow.py:3692
  * _NAME_REJECT_EXACT             app/flows/parent_flow.py:3709
  * GEORGIAN_MONTH_STEMS           app/flows/parent_flow.py:89
  * maybe_capture_child_age_fallback   app/agent/llm/parent_llm_engine.py:103
  * _contains_age_range                app/agent/llm/parent_llm_engine.py:78
  * extract_colloquial_hour / _COLLOQUIAL_HOUR_RE  app/agent/services/timestamps.py:128 / :113
  * _parse_booking_datetime        app/flows/parent_turn_router.py
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PROPERTY_TESTS") != "1",
    reason="audit-only property tests",
)

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
from app.agent.services.timestamps import extract_colloquial_hour
from app.flows.parent_flow import _parse_name_phone
from app.flows.parent_turn_router import _parse_booking_datetime
from app.models.lead import Lead

PHONE = "595999733"  # valid 9-digit Georgian mobile (prefix 5)

# A pool of innocuous Georgian syllables verified NOT to hit any
# filler / month / time / booking reject list — so they survive
# `_name_token_is_valid` and can be used to probe name-length bounds.
SAFE_WORDS = ["ლა", "მო", "ნი", "რე", "ბუ", "ქა", "ზო", "ფი", "ტუ", "ხე"]


def _name(msg: str) -> str:
    return _parse_name_phone(msg)[0]


def _name_tokens(msg: str) -> list[str]:
    return [t for t in _name(msg).split() if t]


# ===========================================================================
# PROPERTY 1 — the name parser never saves a function / filler word
# ===========================================================================
_FILLER_WORDS = [
    "ჩემი", "ან", "და", "გამარჯობა", "მე", "ვარ", "არის",
    "ნომერია", "სახელია", "კი", "არა", "გთხოვთ", "მინდა", "ნომერი",
]


@settings(deadline=None, max_examples=200)
@given(word=st.sampled_from(_FILLER_WORDS))
def test_property_1_name_never_saves_filler_word(word):
    """„{word} {phone}" and „{phone} {word}" must NOT capture {word} as the
    name. (Red-team: „ჩემი ნომერია 595999733" → name=„ჩემი".)"""
    assert word not in _name_tokens(f"{word} {PHONE}"), (
        f"filler {word!r} captured as name from '{word} {PHONE}'"
    )
    assert word not in _name_tokens(f"{PHONE} {word}"), (
        f"filler {word!r} captured as name from '{PHONE} {word}'"
    )


# ===========================================================================
# PROPERTY 2 — the name parser never saves a month / time / booking word
# „მარტი"/„მარტა" (March) is intentionally EXCLUDED: the code deliberately
# allows it because it collides with the real first names მარტი/მარტა.
# ===========================================================================
_MONTHS = [
    "იანვარი", "თებერვალი", "აპრილი", "მაისი", "ივნისი", "ივლისი",
    "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
    "ივნისს", "ივლისს", "მაისს", "ივნისში",
]
_TIME_WORDS = ["საათი", "საათზე", "სთ", "წუთი", "საათისთვის"]
_BOOKING_WORDS = [
    "კონსულტაცია", "ჩაწერა", "ჩამწერეთ", "რეგისტრაცია", "გადატანა",
    "დაჯავშნა", "ჯავშანი", "გადანიშვნა",
]


@settings(deadline=None, max_examples=300)
@given(word=st.sampled_from(_MONTHS + _TIME_WORDS + _BOOKING_WORDS))
def test_property_2_name_never_saves_month_time_booking_word(word):
    """A month / time / booking word must never become the saved name,
    alone or beside a phone."""
    assert word not in _name_tokens(word), (
        f"{word!r} treated as a name on its own"
    )
    assert word not in _name_tokens(f"{word} {PHONE}"), (
        f"{word!r} captured as name from '{word} {PHONE}'"
    )
    assert word not in _name_tokens(f"{PHONE} {word}"), (
        f"{word!r} captured as name from '{PHONE} {word}'"
    )


# ===========================================================================
# PROPERTY 3 — phone extraction is separator-invariant
# ===========================================================================
@settings(deadline=None, max_examples=300)
@given(
    first=st.sampled_from(["5", "7", "8"]),
    rest=st.lists(st.sampled_from("0123456789"), min_size=8, max_size=8),
    seps=st.lists(st.sampled_from([" ", "-", ""]), min_size=8, max_size=8),
)
def test_property_3_phone_extraction_separator_invariant(first, rest, seps):
    """A valid 9-digit phone with arbitrary internal separators from
    [' ', '-', ''] must still be extracted as the same 9 digits."""
    digits = first + "".join(rest)
    parts = [digits[0]]
    for d, s in zip(digits[1:], seps):
        parts.append(s + d)
    formatted = "".join(parts)
    _name_out, phone_out = _parse_name_phone(formatted)
    extracted = "".join(ch for ch in phone_out if ch.isdigit())
    assert extracted == digits, (
        f"separators broke extraction: {formatted!r} -> {phone_out!r}"
    )


# ===========================================================================
# PROPERTY 4 — saved name length is bounded (a paragraph is never a name)
# ===========================================================================
_NAME_TOKEN_CAP = 4


@settings(deadline=None, max_examples=300)
@given(words=st.lists(st.sampled_from(SAFE_WORDS), min_size=1, max_size=30))
def test_property_4_saved_name_length_bounded(words):
    """A phone followed by N arbitrary Georgian words must not yield a name
    with more than a small token cap. (Red-team: a whole rambling message
    was saved as the name.)"""
    msg = PHONE + " " + " ".join(words)
    tokens = _name_tokens(msg)
    assert len(tokens) <= _NAME_TOKEN_CAP, (
        f"name has {len(tokens)} tokens (cap {_NAME_TOKEN_CAP}): {tokens!r}"
    )


# ===========================================================================
# PROPERTY 5 — an age range never collapses to a single age
# ===========================================================================
@settings(deadline=None, max_examples=300)
@given(a=st.integers(min_value=1, max_value=98),
       b=st.integers(min_value=2, max_value=99))
def test_property_5_age_range_never_collapses(a, b):
    """„{a}-{b}" and „{a}-{b} წლის" must NOT set child_age to a or b."""
    assume(a < b)
    for msg in (f"{a}-{b}", f"{a}-{b} წლის"):
        lead = Lead(sender_id="prop", platform="instagram", segment="PARENT")
        maybe_capture_child_age_fallback(lead, msg, age_question_pending=True)
        captured = (lead.child_age or "").strip()
        assert captured not in {str(a), str(b)}, (
            f"range {msg!r} collapsed to child_age={captured!r}"
        )


# ===========================================================================
# PROPERTY 6 — colloquial PM inference is consistent across suffixes
# ===========================================================================
@settings(deadline=None, max_examples=50)
@given(h=st.integers(min_value=1, max_value=9))
def test_property_6_colloquial_pm_consistent(h):
    """„{h} საათი" and „{h} საათზე" produce the same PM-inferred result,
    and an unqualified 1–9 maps to h+12 (within working hours)."""
    r_i = extract_colloquial_hour(f"{h} საათი")
    r_ze = extract_colloquial_hour(f"{h} საათზე")
    assert r_i == r_ze, f"suffix mismatch: საათი={r_i!r} საათზე={r_ze!r}"
    assert r_ze == (h + 12, 0), f"unqualified {h} -> {r_ze!r}, expected {(h + 12, 0)}"


# ===========================================================================
# PROPERTY 7 — a contact-only message never parses a booking datetime
# ===========================================================================
@settings(deadline=None, max_examples=300)
@given(words=st.lists(st.sampled_from(SAFE_WORDS), min_size=1, max_size=4))
def test_property_7_contact_only_no_booking(words):
    """name + phone with NO datetime must not parse a booking datetime /
    colloquial hour (contact parsing must not trigger booking)."""
    name = " ".join(words)
    for msg in (f"{name} {PHONE}", f"{PHONE} {name}"):
        assert _parse_booking_datetime(msg) is None, (
            f"contact-only {msg!r} parsed a booking datetime"
        )
        assert extract_colloquial_hour(msg) is None, (
            f"contact-only {msg!r} parsed a colloquial hour"
        )
