"""AUDIT-ONLY metamorphic property tests (2026-06-13).

Metamorphic relation: the SAME user intent expressed DIFFERENTLY should
produce the SAME deterministic result. Each test below feeds several
phrasings of one intent through the REAL pure parser/classifier functions
(no OpenAI, no network, no Redis/Calendar/Sheets/Meta/email) and asserts the
outputs agree with the canonical reference phrasing.

Run (audit):    RUN_PROPERTY_TESTS=1 python -m pytest tests/property/ -q
Normal suite:   python -m pytest tests/ -q      # this whole file is skipped

These intentionally SURFACE divergences as failures — they are documentation
of behaviour, not a contract to keep green. Do NOT "fix" a divergence by
weakening the assertion; the failing pair IS the finding. A known divergence
is annotated inline (KNOWN DIVERGENCE).

Functions under test (file:line at the time of writing):
  * maybe_capture_child_age_fallback   app/agent/llm/parent_llm_engine.py:103
  * _parse_name_phone                  app/flows/parent_flow.py:3884
  * _distinct_valid_phones             app/flows/parent_flow.py:3974
  * _is_explicit_consultation_request  app/flows/parent_flow.py:2775
  * _maybe_capture_adult_target        app/agent/llm/adult_llm_engine.py:546
  * extract_colloquial_hour            app/agent/services/timestamps.py:128
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_PROPERTY_TESTS") != "1",
    reason="audit-only property tests",
)

from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
from app.agent.llm.parent_llm_engine import maybe_capture_child_age_fallback
from app.agent.services.timestamps import extract_colloquial_hour
from app.flows.parent_flow import (
    _distinct_valid_phones,
    _is_explicit_consultation_request,
    _parse_name_phone,
)
from app.models.lead import Lead

PHONE = "595999733"
_CHILD_RELATIONS = frozenset({"შვილი", "ბავშვი"})


# --- pure-function adapters (fresh state per call, no I/O) -------------------

def _age(message: str) -> str:
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    maybe_capture_child_age_fallback(lead, message)
    return lead.child_age


def _relation(message: str) -> str:
    lead = Lead(sender_id="s", platform="messenger", segment="ADULT")
    _maybe_capture_adult_target(message, lead)
    return lead.adult_target_relation or ""


def _intent(message: str) -> bool:
    return _is_explicit_consultation_request(message)


def _hour(message: str) -> int | None:
    parsed = extract_colloquial_hour(message)
    return parsed[0] if parsed else None


def _phone(message: str) -> str:
    return _parse_name_phone(message)[1]


# ===========================================================================
# M1 — Age phrasings → child_age == "13"
#   Reference phrasing: "13 წლის".
#   KNOWN DIVERGENCE: "ცამეტი წლის" (spelled-out thirteen) → "" — the digit
#   parser does not read spelled-out Georgian numerals. Left failing on
#   purpose (audit finding; do not fix here).
# ===========================================================================
@pytest.mark.parametrize("phrasing", [
    "13 წლის",
    "ცამეტი წლის",          # KNOWN DIVERGENCE → "" (spelled-out not parsed)
    "13 წლისაა",
    "ჩემი შვილი 13 წლის",
])
def test_m1_age_phrasings_all_capture_13(phrasing):
    got = _age(phrasing)
    assert got == "13", (
        f"M1 divergence: reference '13 წლის' -> '13' BUT {phrasing!r} -> {got!r}"
    )


# ===========================================================================
# M2 — Name+phone order → ("ლიზი", "595999733")
# ===========================================================================
@pytest.mark.parametrize("phrasing", [
    "ლიზი 595999733",
    "595999733 ლიზი",
    "ლიზი, 595999733",
    "595999733, ლიზი",
])
def test_m2_name_phone_order_invariant(phrasing):
    got = _parse_name_phone(phrasing)
    assert got == ("ლიზი", PHONE), (
        f"M2 divergence: reference 'ლიზი 595999733' -> ('ლიზი','{PHONE}') "
        f"BUT {phrasing!r} -> {got!r}"
    )


# ===========================================================================
# M3 — Consultation-intent synonyms → all classified as an explicit request
# ===========================================================================
@pytest.mark.parametrize("phrasing", [
    "მინდა კონსულტაცია",
    "კონსულტაცია მსურს",
    "ჩამწერეთ კონსულტაციაზე",
])
def test_m3_intent_synonyms_all_true(phrasing):
    got = _intent(phrasing)
    assert got is True, (
        f"M3 divergence: reference 'მინდა კონსულტაცია' -> True "
        f"BUT {phrasing!r} -> {got!r}"
    )


# ===========================================================================
# M4 — Child-relation synonyms → all set a child-relation target.
#   Note: the LABEL differs ("შვილი" vs "ბავშვი"); the metamorphic relation
#   asked for is "all set a CHILD-relation target", so the result is
#   normalised to membership in {"შვილი","ბავშვი"}.
# ===========================================================================
@pytest.mark.parametrize("phrasing", [
    "ჩემი შვილისთვის",
    "ჩემ შვილს",
    "ბავშვისთვის",
    "ბავშვს",
])
def test_m4_child_relation_synonyms_all_set_child_target(phrasing):
    rel = _relation(phrasing)
    assert rel in _CHILD_RELATIONS, (
        f"M4 divergence: {phrasing!r} -> rel={rel!r} "
        f"(expected a child relation in {sorted(_CHILD_RELATIONS)})"
    )


# ===========================================================================
# M5 — Time phrasings → consistent hour == 19
# ===========================================================================
@pytest.mark.parametrize("phrasing", [
    "7 საათზე",
    "19:00",
])
def test_m5_time_phrasings_hour_19(phrasing):
    got = _hour(phrasing)
    assert got == 19, (
        f"M5 divergence: reference '7 საათზე' -> 19 BUT {phrasing!r} -> {got!r}"
    )


# ===========================================================================
# M6 — Phone separators → same 9 digits
# ===========================================================================
@pytest.mark.parametrize("phrasing", [
    "595999733",
    "595 999 733",
    "595-999-733",
])
def test_m6_phone_separators_same_digits(phrasing):
    got = _phone(phrasing)
    assert got == PHONE, (
        f"M6 divergence: reference '595999733' -> '{PHONE}' "
        f"BUT {phrasing!r} -> {got!r}"
    )


def test_m6_phone_separators_distinct_is_single(phrasing="595 999 733"):
    # A single spaced/dashed phone must count as ONE distinct number, not many.
    assert _distinct_valid_phones("595 999 733") == [PHONE]
    assert _distinct_valid_phones("595-999-733") == [PHONE]
