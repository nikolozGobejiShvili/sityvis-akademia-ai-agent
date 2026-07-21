"""Phase 4, Task 4 — `USE_LEAN_SANITIZER` (thin the convergence engine).

Contract under test
-------------------
* Flag **OFF** (default, pinned OFF in ``tests/conftest.py``) ⇒
  ``sanitise_response_wording`` applies the FULL 183-entry
  ``FORBIDDEN_PHRASE_REPLACEMENTS`` table, in declaration order,
  byte-identical to the pre-Task-4 behaviour.
* Flag **ON** ⇒ the structural passes still run (duplicate-„თუ" collapse,
  concern-preamble strip, dynamic fact/typography normalisations, double-space
  and orphaned-punctuation cleanup) and the SAFETY subset of the table is still
  applied — only the pure wording-mandate entries (one approved phrasing forced
  over another equally-correct one) stop firing.

Nothing is deleted: ``_SANITIZER_SAFETY_ENTRIES`` holds *references* to the very
tuple objects already in ``FORBIDDEN_PHRASE_REPLACEMENTS`` (asserted by identity
below), in the same relative order.

Every phrase used here is read out of the live table **by index** rather than
retyped, so a test can never silently disagree with the guardrail it guards.
"""
from __future__ import annotations

import dataclasses
import re

import pytest

from app import config
from app.agent.llm import parent_llm_engine as ple
from app.agent.llm.parent_llm_engine import (
    FORBIDDEN_PHRASE_REPLACEMENTS,
    sanitise_response_wording,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _swap_settings(monkeypatch, **flags):
    """Mirror the settings swap used by the other engine tests."""
    swapped = dataclasses.replace(config.settings, **flags)
    monkeypatch.setattr(ple, "settings", swapped)
    return swapped


def _lean_on(monkeypatch):
    return _swap_settings(monkeypatch, USE_LEAN_SANITIZER=True)


def _reference_sanitise_full_table(text: str) -> str:
    """Independent re-implementation of the pre-Task-4 pipeline.

    Uses the engine's own structural helpers but iterates the FULL table
    unconditionally, so any drift between it and the flag-OFF production path
    is a real behaviour change.
    """
    if not text:
        return text
    out = text
    out = ple._collapse_duplicated_tu(out)
    out = ple._strip_concern_wording(out)
    out = ple._apply_dynamic_fact_normalisations(out)
    for needle, replacement in FORBIDDEN_PHRASE_REPLACEMENTS:
        if needle in out:
            out = out.replace(needle, replacement)
    if "  " in out:
        out = re.sub(r"  +", " ", out)
    out = re.sub(r"\s+\.", ".", out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r"\.{2,}", ".", out)
    return out.strip()


# Table indexes (stable positions in FORBIDDEN_PHRASE_REPLACEMENTS).
#
# Wording mandates — dropped when the flag is ON.
IDX_MANDATE_DISCOVERY_QUESTION = 24  # „რას მიიჩნევთ ყველაზე მნიშვნელოვნად"
IDX_MANDATE_GENERIC_HELP_OFFER = 68  # „როგორ შემიძლია დაგეხმაროთ დღეს?"
IDX_MANDATE_AGE_FIT_STYLE = 60  # „სრულად ერგება" → „შესაფერისია"
IDX_MANDATE_INTENSIFIER = 98  # „ბუნებრივი სურვილია"
IDX_MANDATE_SIDE_BY_SIDE = 153  # „სიამოვნებით დაგიდგებით გვერდში."
IDX_MANDATE_SLOT_QUESTION = 161  # „რომელი დრო გჭირდებათ?"

# Safety entries — must keep firing when the flag is ON.
IDX_SAFETY_GREETING_LEAK = 71  # „მოგესალმებით! როგორ შემიძლია დაგეხმაროთ?"
IDX_SAFETY_BOOKING_ECHO_STRIP = 145  # „ საათზე ჩამწერეთ კონსულტაცია."
IDX_SAFETY_EMOJI_STRIP = 176  # „😊" → ""
IDX_SAFETY_GRAMMAR_PREFER = 37  # „რომელი დრო გირჩევთ" → „…გირჩევნიათ"
IDX_SAFETY_GRAMMAR_ANIMATE = 30  # „შვილები გაქვთ" → „შვილები გყავთ"
IDX_SAFETY_SPELLING = 82  # „დაეჭვება" → „კითხვა"
IDX_SAFETY_FALSE_PROMISE = 66  # „ერთ წუთში გავხსნი" → ""
IDX_SAFETY_STALE_HOURS = 137  # „10:00–18:00" → „10:00–21:00"
IDX_SAFETY_INTERNAL_LEAK = 169  # „ჩემი მეხსიერების მიხედვით"
IDX_SAFETY_LOCATIVE = 133  # „შეცვლას დაგეხმარებით" → „შეცვლაში …"

_MANDATE_INDEXES = (
    IDX_MANDATE_DISCOVERY_QUESTION,
    IDX_MANDATE_GENERIC_HELP_OFFER,
    IDX_MANDATE_AGE_FIT_STYLE,
    IDX_MANDATE_INTENSIFIER,
    IDX_MANDATE_SIDE_BY_SIDE,
    IDX_MANDATE_SLOT_QUESTION,
)

_SAFETY_INDEXES = (
    # NB: IDX_SAFETY_BOOKING_ECHO_STRIP's needle starts with a space, which the
    # structural passes trim off a bare-needle input — it gets its own test with
    # a realistic carrier („15 საათზე …") below.
    IDX_SAFETY_GREETING_LEAK,
    IDX_SAFETY_EMOJI_STRIP,
    IDX_SAFETY_GRAMMAR_PREFER,
    IDX_SAFETY_GRAMMAR_ANIMATE,
    IDX_SAFETY_SPELLING,
    IDX_SAFETY_FALSE_PROMISE,
    IDX_SAFETY_STALE_HOURS,
    IDX_SAFETY_INTERNAL_LEAK,
    IDX_SAFETY_LOCATIVE,
)


# ---------------------------------------------------------------------------
# 0. flag plumbing
# ---------------------------------------------------------------------------
def test_use_lean_sanitizer_defaults_off_and_follows_flag(monkeypatch):
    assert ple._use_lean_sanitizer() is False
    _lean_on(monkeypatch)
    assert ple._use_lean_sanitizer() is True


# ---------------------------------------------------------------------------
# 1. partition integrity — nothing deleted, nothing retyped, order preserved
# ---------------------------------------------------------------------------
def test_full_table_still_has_183_entries():
    assert len(FORBIDDEN_PHRASE_REPLACEMENTS) == 183


def test_safety_subset_holds_the_same_tuple_objects_not_copies():
    """References, never retyped Georgian — identity, not equality."""
    full_by_id = {id(entry) for entry in FORBIDDEN_PHRASE_REPLACEMENTS}
    for entry in ple._SANITIZER_SAFETY_ENTRIES:
        assert id(entry) in full_by_id


def test_safety_subset_preserves_relative_order():
    """A subsequence by IDENTITY — `.index()` would lie, the table has literal
    duplicates (e.g. „კონსულტაცია დაგიბარებთ" appears twice)."""
    positions = []
    cursor = 0
    for entry in ple._SANITIZER_SAFETY_ENTRIES:
        while id(FORBIDDEN_PHRASE_REPLACEMENTS[cursor]) != id(entry):
            cursor += 1
        positions.append(cursor)
        cursor += 1
    assert positions == sorted(positions)
    assert len(positions) == len(ple._SANITIZER_SAFETY_ENTRIES)


def test_safety_subset_is_a_strict_subset_and_materially_smaller_drop():
    n_full = len(FORBIDDEN_PHRASE_REPLACEMENTS)
    n_safety = len(ple._SANITIZER_SAFETY_ENTRIES)
    dropped = n_full - n_safety
    assert 0 < dropped < 147, "conservative partition: far fewer than 147 dropped"
    assert n_safety > 147


def test_every_strip_entry_is_safety():
    """Rule S1 — a right-hand side of "" is always SAFETY."""
    strips = [e for e in FORBIDDEN_PHRASE_REPLACEMENTS if e[1] == ""]
    assert len(strips) == 36
    kept = {id(e) for e in ple._SANITIZER_SAFETY_ENTRIES}
    for entry in strips:
        assert id(entry) in kept, f"strip dropped: {entry[0]!r}"


def test_declared_mandate_indexes_match_the_dropped_set():
    kept = {id(e) for e in ple._SANITIZER_SAFETY_ENTRIES}
    dropped_idx = {
        idx
        for idx, entry in enumerate(FORBIDDEN_PHRASE_REPLACEMENTS)
        if id(entry) not in kept
    }
    assert dropped_idx == set(ple._SANITIZER_WORDING_MANDATE_INDEXES)


def test_table_size_guard_falls_back_to_full_table_if_table_changes():
    """If someone edits the table, the indexes are stale — fail SAFE (full table)."""
    grown = FORBIDDEN_PHRASE_REPLACEMENTS + (("ტესტი", "ტესტი"),)
    assert ple._build_sanitizer_safety_entries(grown) is grown


# ---------------------------------------------------------------------------
# 2. flag OFF — the full table still applies (byte-identical)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("idx", _MANDATE_INDEXES)
def test_flag_off_wording_mandate_still_rewrites(idx):
    needle, replacement = FORBIDDEN_PHRASE_REPLACEMENTS[idx]
    out = sanitise_response_wording(needle)
    assert replacement.strip(" .") in out
    if needle not in replacement:  # idx 98 only widens the phrase
        assert needle not in out


def test_flag_off_output_is_byte_identical_to_the_full_table_reference():
    corpus = [needle for needle, _ in FORBIDDEN_PHRASE_REPLACEMENTS]
    corpus += [
        "გამარჯობა. " + needle + " მადლობა."
        for needle, _ in FORBIDDEN_PHRASE_REPLACEMENTS
    ]
    corpus += [
        "",
        "ბანაკის ღირებულება 2150 ლარია.",
        "ადგილი — ამბასადორი კაჭრეთი",
        "სრულად ერგება 9–17 წლის ბავშვების ბანაკს",
    ]
    for text in corpus:
        assert sanitise_response_wording(text) == _reference_sanitise_full_table(text)


# ---------------------------------------------------------------------------
# 3. flag ON — wording mandates pass through un-rewritten
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("idx", _MANDATE_INDEXES)
def test_flag_on_wording_mandate_passes_through(monkeypatch, idx):
    needle, _replacement = FORBIDDEN_PHRASE_REPLACEMENTS[idx]
    _lean_on(monkeypatch)
    out = sanitise_response_wording(needle)
    assert needle.strip() in out


def test_flag_on_relaxes_the_same_entry_the_flag_off_test_rewrites(monkeypatch):
    """The single clearest before/after pair, spelled out end-to-end."""
    needle, replacement = FORBIDDEN_PHRASE_REPLACEMENTS[IDX_MANDATE_SLOT_QUESTION]
    assert replacement in sanitise_response_wording(needle)  # flag OFF
    _lean_on(monkeypatch)
    assert sanitise_response_wording(needle) == needle  # flag ON


# ---------------------------------------------------------------------------
# 4. flag ON — the safety net still fires
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("idx", _SAFETY_INDEXES)
def test_flag_on_safety_entry_still_applies(monkeypatch, idx):
    needle, _replacement = FORBIDDEN_PHRASE_REPLACEMENTS[idx]
    _lean_on(monkeypatch)
    out = sanitise_response_wording(needle)
    assert needle.strip() not in out


def test_flag_on_emoji_is_still_stripped(monkeypatch):
    _lean_on(monkeypatch)
    assert sanitise_response_wording("კონსულტაცია ჩანიშნულია 😊") == (
        "კონსულტაცია ჩანიშნულია"
    )


def test_flag_on_fake_booking_echo_is_still_stripped(monkeypatch):
    needle, _ = FORBIDDEN_PHRASE_REPLACEMENTS[IDX_SAFETY_BOOKING_ECHO_STRIP]
    _lean_on(monkeypatch)
    out = sanitise_response_wording("15" + needle)
    assert "ჩამწერეთ კონსულტაცია" not in out


def test_flag_on_mid_conversation_greeting_is_still_removed(monkeypatch):
    needle, replacement = FORBIDDEN_PHRASE_REPLACEMENTS[IDX_SAFETY_GREETING_LEAK]
    _lean_on(monkeypatch)
    out = sanitise_response_wording(needle)
    assert "მოგესალმებით" not in out
    assert out == replacement


def test_flag_on_ambiguous_grammar_entry_is_still_applied(monkeypatch):
    needle, replacement = FORBIDDEN_PHRASE_REPLACEMENTS[IDX_SAFETY_GRAMMAR_PREFER]
    _lean_on(monkeypatch)
    out = sanitise_response_wording(needle + "?")
    assert out == replacement + "?"


def test_flag_on_keeps_every_guardrail_map_section5_family(monkeypatch):
    """docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md §5 — sanitizer-coupled rows."""
    _lean_on(monkeypatch)
    kept = {id(e) for e in ple._SANITIZER_SAFETY_ENTRIES}
    section5_indexes = (
        3, 5, 6, 7, 8, 10, 16, 17, 18, 19, 20, 21, 22,  # row 37 family
        25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,  # rows 30 + 37
        40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54,
        77, 78, 79, 80, 81,  # „გეთანხმებით" ban
        82, 83,  # spelling
        110, 111, 112,  # row 41 angry customer
        118, 119, 120, 121,  # row 44 sensitive needs
        129, 130, 131, 132, 133, 134,  # row 22 locative
        173, 174, 175, 176, 177, 178, 179, 180, 181, 182,  # emoji ban
    )
    for idx in section5_indexes:
        assert id(FORBIDDEN_PHRASE_REPLACEMENTS[idx]) in kept


# ---------------------------------------------------------------------------
# 5. flag ON — the structural passes are untouched
# ---------------------------------------------------------------------------
def test_flag_on_dynamic_fact_normalisation_still_runs(monkeypatch):
    _lean_on(monkeypatch)
    assert sanitise_response_wording("ადგილი — ამბასადორი კაჭრეთი").startswith(
        "ლოკაცია — "
    )


def test_flag_on_age_band_normalisation_still_runs(monkeypatch):
    _lean_on(monkeypatch)
    out = sanitise_response_wording("სრულად ერგება 9–17 წლის ბავშვების ბანაკს")
    assert "სრულად ერგება" not in out


def test_flag_on_still_collapses_duplicated_tu_clause(monkeypatch):
    text = (
        "თუ კიდევ რაიმე კითხვა გაგიჩნდებათ, "
        "თუ კიდევ რაიმე კითხვა გაგიჩნდებათ, მომწერეთ."
    )
    _lean_on(monkeypatch)
    out = sanitise_response_wording(text)
    assert out.count("გაგიჩნდებათ") == 1


def test_flag_on_still_tidies_whitespace_after_a_strip(monkeypatch):
    _lean_on(monkeypatch)
    out = sanitise_response_wording("კარგი 😊  მადლობა.")
    assert "  " not in out


def test_flag_on_empty_text_is_returned_unchanged(monkeypatch):
    _lean_on(monkeypatch)
    assert sanitise_response_wording("") == ""
