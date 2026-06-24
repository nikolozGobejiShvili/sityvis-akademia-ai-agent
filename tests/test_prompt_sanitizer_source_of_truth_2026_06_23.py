"""Source-of-truth regression guards — prompt + sanitizer must NOT hardcode
camp age band / location (2026-06-23).

Background
----------
The PARENT system prompt (`system_parent_v2.md`) and the `parent_llm_engine`
sanitizer (`FORBIDDEN_PHRASE_REPLACEMENTS`) used to carry hardcoded camp facts:
the age literal „9–17" and the location „ამბასადორ კაჭრეთი". The sanitizer's
forbidden-phrase table even *re-injected* those literals into outgoing replies,
which meant an operator Admin-Config edit (age band / location) could be silently
overwritten by the prompt/sanitizer — a write-side source-of-truth bypass.

These tests prove that camp facts now flow ONLY from the canonical helpers
(`admin_config_service.get_camp_age_bounds` for the age band, `get_camp_info`
for location) and that neither the prompt nor the sanitizer reinserts a stale
literal when the operator config diverges from the shipped default.

IMPORTANT: assertions source the *current* band from the canonical helper rather
than hardcoding „9–17" as a universal truth (per the task brief).
"""

from __future__ import annotations

import pytest

from app.services import admin_config_service
from app.agent.llm.parent_llm_engine import (
    FORBIDDEN_PHRASE_REPLACEMENTS,
    _build_system_prompt,
    sanitise_response_wording,
)

# Literals that must NEVER appear baked into the prompt text or as a sanitizer
# replacement VALUE. These are the shipped-default facts; a divergent operator
# config must be able to override them everywhere. Both distinctive tokens of
# the shipped location „ამბასადორი კაჭრეთი" are guarded so no fragment survives.
_OLD_LOCATION_TOKENS = ("ამბასადორ", "კაჭრეთ")
_OLD_LOCATION_TOKEN = "ამბასადორ"  # back-compat alias for sentinel checks
_OLD_AGE_LITERALS = ("9–17", "9-17")


# ---------------------------------------------------------------------------
# PART B.3 — Prompt leakage / divergence
# ---------------------------------------------------------------------------
def test_prompt_renders_age_band_from_canonical_config(monkeypatch):
    """When the operator sets the canonical band to 10–16, the built prompt
    renders 10–16 everywhere and never the hardcoded 9–17."""
    monkeypatch.setattr(
        admin_config_service, "get_camp_age_bounds", lambda: (10, 16)
    )
    prompt = _build_system_prompt()
    assert "10–16" in prompt
    for stale in _OLD_AGE_LITERALS:
        assert stale not in prompt, f"prompt leaked hardcoded age band {stale!r}"


def test_prompt_has_no_hardcoded_location_literal():
    """The built prompt must not name the shipped location (neither „ამბასადორ"
    nor the „კაჭრეთ" fragment) — location flows through the `<ლოკაცია>` marker
    filled from get_camp_info, like `<streams>`."""
    prompt = _build_system_prompt()
    for token in _OLD_LOCATION_TOKENS:
        assert token not in prompt, f"prompt leaked location fragment {token!r}"
    # And the prompt still routes facts through the tool.
    assert "get_camp_info" in prompt


def test_prompt_age_band_matches_real_config():
    """PART B.5 — with the real shipped config the prompt still shows the
    current correct age band (sourced from the canonical helper)."""
    lo, hi = admin_config_service.get_camp_age_bounds()
    prompt = _build_system_prompt()
    assert f"{lo}–{hi}" in prompt


# ---------------------------------------------------------------------------
# PART B.1/B.4 — Sanitizer must source the band from the canonical helper
# ---------------------------------------------------------------------------
def test_sanitizer_underage_softener_uses_divergent_config(monkeypatch):
    """Age divergence: with canonical band 10–16, the harsh under-age softener
    renders 10–16 and never reinserts the hardcoded 9–17."""
    monkeypatch.setattr(
        admin_config_service, "get_camp_age_bounds", lambda: (10, 16)
    )
    out = sanitise_response_wording(
        "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დავადასტურებთ."
    )
    assert "ვერ დავადასტურებთ" not in out
    assert "10–16" in out
    for stale in _OLD_AGE_LITERALS:
        assert stale not in out, f"sanitizer reinserted hardcoded age {stale!r}"


def test_sanitizer_underage_softener_matches_real_config():
    """PART B.5 — with the real config the softener still states the current
    correct band (sourced from the canonical helper, not a literal)."""
    lo, hi = admin_config_service.get_camp_age_bounds()
    out = sanitise_response_wording(
        "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დაგიდასტურებთ."
    )
    assert "ვერ დაგიდასტურებთ" not in out
    assert f"{lo}–{hi}" in out


def test_sanitizer_age_typography_is_number_agnostic():
    """The „N-დან M წლამდე" → „N–M წლის" typography fix must preserve whatever
    band the model produced (from get_camp_info) — not snap to 9–17."""
    out = sanitise_response_wording("ბანაკი 10-დან 16 წლამდე ბავშვებისთვის.")
    assert "10–16 წლის" in out
    assert "10-დან 16 წლამდე" not in out
    assert "9–17" not in out


def test_sanitizer_default_age_typography_still_works():
    """Existing behaviour preserved for the shipped band."""
    out = sanitise_response_wording("ბანაკი 9-დან 17 წლამდე ბავშვებისთვის.")
    assert "9–17 წლის ბავშვებისთვის" in out
    assert "9-დან 17 წლამდე" not in out


# ---------------------------------------------------------------------------
# PART B.2 — Location divergence via the sanitizer label-fix
# ---------------------------------------------------------------------------
def test_sanitizer_location_label_is_location_agnostic():
    """The „ადგილი - X" → „ლოკაცია — X" label fix must keep the operator's own
    location text and never reinsert the shipped „ამბასადორ კაჭრეთი"."""
    out = sanitise_response_wording("ადგილი - ტესტ ლოკაცია")
    assert "ლოკაცია — ტესტ ლოკაცია" in out
    assert "ადგილი -" not in out
    assert _OLD_LOCATION_TOKEN not in out


def test_sanitizer_location_label_em_dash_variant():
    out = sanitise_response_wording("ადგილი — ტესტ ლოკაცია")
    assert "ლოკაცია — ტესტ ლოკაცია" in out
    assert _OLD_LOCATION_TOKEN not in out


# ---------------------------------------------------------------------------
# PART B.4 — Structural guard: the sanitizer table must hold no camp facts
# ---------------------------------------------------------------------------
def test_forbidden_phrase_table_contains_no_hardcoded_camp_facts():
    """No needle OR replacement in the static forbidden-phrase table may carry
    the camp location or age band — those belong to canonical config only."""
    for needle, replacement in FORBIDDEN_PHRASE_REPLACEMENTS:
        for cell in (needle, replacement):
            for loc in _OLD_LOCATION_TOKENS:
                assert loc not in cell, (
                    f"hardcoded location in forbidden table: {cell!r}"
                )
            for stale in _OLD_AGE_LITERALS:
                assert stale not in cell, (
                    f"hardcoded age band in forbidden table: {cell!r}"
                )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "ამ პროგრამაში თქვენი ბავშვის ჩაწერას ვერ დავადასტურებთ.",
        "ადგილი - ტესტ ლოკაცია",
        "ბანაკი 10-დან 16 წლამდე ბავშვებისთვის.",
        "სრულად ერგება 9–17 წლის ბავშვების ბანაკს.",
    ],
)
def test_sanitizer_dynamic_passes_are_idempotent(text):
    once = sanitise_response_wording(text)
    twice = sanitise_response_wording(once)
    assert once == twice
