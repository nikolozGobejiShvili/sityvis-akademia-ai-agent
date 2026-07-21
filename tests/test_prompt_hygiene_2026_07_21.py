"""Phase 4 (prompt & sanitizer hygiene) — flag defaults + from_env parsing.

Both flags default OFF (flag-off ⇒ byte-identical). This file grows across
Phase-4 tasks; Task 1 covers only the two flags.
"""
from __future__ import annotations

import dataclasses

from app import config
from app.config import Settings


def test_lean_prompt_flag_defaults_off():
    assert config.settings.USE_LEAN_PROMPT is False


def test_lean_sanitizer_flag_defaults_off():
    assert config.settings.USE_LEAN_SANITIZER is False


def test_from_env_parses_lean_prompt_true(monkeypatch):
    monkeypatch.setenv("USE_LEAN_PROMPT", "true")
    assert Settings.from_env().USE_LEAN_PROMPT is True


def test_from_env_parses_lean_sanitizer_true(monkeypatch):
    monkeypatch.setenv("USE_LEAN_SANITIZER", "true")
    assert Settings.from_env().USE_LEAN_SANITIZER is True


def test_from_env_defaults_off_when_unset(monkeypatch):
    monkeypatch.delenv("USE_LEAN_PROMPT", raising=False)
    monkeypatch.delenv("USE_LEAN_SANITIZER", raising=False)
    s = Settings.from_env()
    assert s.USE_LEAN_PROMPT is False and s.USE_LEAN_SANITIZER is False


# ===========================================================================
# Task 3 — parent_lean.md (lean PARENT prompt) + USE_LEAN_PROMPT wiring
# ===========================================================================
#
# Flag OFF ⇒ `_build_system_prompt()` still loads `system_parent_v2.md`,
# byte-identical (mirrors the assertion in
# tests/test_camp_age_bounds_migration_5a2_2026_06_22.py so it stays green).
# Flag ON ⇒ the engine loads `parent_lean.md` instead — every guardrail is
# preserved per docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md, but the file is
# under half the size of the giant prompt.

from app.agent.llm import parent_llm_engine as ple
from app.agent.llm.prompt_loader import load_prompt

_LEAN_MARKER = "LEAN_PROMPT_MARKER_v1"


def _swap_settings(monkeypatch, **flags):
    swapped = dataclasses.replace(config.settings, **flags)
    monkeypatch.setattr(ple, "settings", swapped)
    return swapped


def _company_name():
    return ple.settings.COMPANY_NAME or "სიტყვის აკადემია"


def test_use_lean_prompt_true_iff_flag_on(monkeypatch):
    # Default (no swap) — flag is off.
    assert ple._use_lean_prompt() is False

    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True)
    assert ple._use_lean_prompt() is True

    _swap_settings(monkeypatch, USE_LEAN_PROMPT=False)
    assert ple._use_lean_prompt() is False


def test_build_system_prompt_byte_identical_flag_off():
    """Flag OFF ⇒ `system_parent_v2.md` still loads, byte-identical — mirrors
    `test_camp_age_bounds_migration_5a2_2026_06_22.py::test_prompt_default_band_unchanged`."""
    raw = load_prompt("system_parent_v2")
    assert ple._build_system_prompt() == raw.format(
        company_name=_company_name(), age_min=9, age_max=17,
    )


def test_build_system_prompt_flag_on_loads_lean_prompt_with_marker_and_is_shorter(monkeypatch):
    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True)
    lean_prompt = ple._build_system_prompt()

    assert _LEAN_MARKER in lean_prompt

    giant_raw = load_prompt("system_parent_v2")
    giant_prompt = giant_raw.format(company_name=_company_name(), age_min=9, age_max=17)
    assert len(lean_prompt) < 0.5 * len(giant_prompt)


def test_lean_prompt_accepts_same_three_format_kwargs_and_no_others():
    """parent_lean.md must accept exactly the same 3 `.format()` kwargs as
    the giant prompt (company_name/age_min/age_max) and never raise
    KeyError — proves any literal `{`/`}` shown to the LLM was doubled."""
    raw = load_prompt("parent_lean")
    formatted = raw.format(company_name="X", age_min=9, age_max=17)
    assert "{" not in formatted and "}" not in formatted


def test_skills_suffix_still_appends_with_lean_prompt_and_skills_on(monkeypatch):
    """The 3 prompt suffixes append AFTER prompt selection — proving the
    skills suffix still fires with USE_LEAN_PROMPT ON + USE_SKILLS ON."""
    from app.services import skills_service

    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True, USE_SKILLS=True)
    monkeypatch.setattr(
        skills_service, "select_skills",
        lambda m, s, **k: [{"id": "x", "name": "N", "body": "LEAN-SKILLS-MARKER"}],
    )
    out = ple._build_system_prompt("ძვირია", "PARENT")
    assert _LEAN_MARKER in out
    assert "LEAN-SKILLS-MARKER" in out


def test_build_sales_context_flag_off_thanks_byte_identical(monkeypatch):
    """`_build_sales_context`'s flag-OFF path (the hardcoded verbatim
    thank-you script) must be byte-identical to today's output — this is
    the branch Task 3 gated behind `_use_lean_prompt()` (M2)."""
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    _swap_settings(monkeypatch, USE_LEAN_PROMPT=False)

    conv = Conversation(sender_id="lean_ctx_off", platform="messenger", segment="PARENT")
    conv.history = []
    conv.adult_subscription_status = ""
    lead = Lead(
        sender_id="lean_ctx_off", platform="messenger", segment="PARENT",
        child_age="12", name="ნიკა", phone="", calendly_booked=True,
    )
    conv.lead = lead

    ctx = ple._build_sales_context(conv, lead, "მადლობა")
    expected = (
        "Sales context (აუდიტორიაზე მორგებული გაყიდვა):\n"
        "- მომხმარებელი მადლობას ხდის დაჯავშნის შემდეგ."
        " გამოიყენე: \"მადლობა თქვენ."
        " კონსულტაცია ჩანიშნულია და მენეჯერი დაგიკავშირდებათ.\"\n"
        "- *არასოდეს* გამოიყენო \"სიამოვნებით.\" — ეს ზედმეტად"
        " ფორმალური/რობოტური ჟღერს."
    )
    assert ctx == expected


def test_build_sales_context_flag_on_thanks_uses_behavioral_hint_not_dup_script(monkeypatch):
    """Flag ON ⇒ the thank-you hint is behavioral, not the literal hardcoded
    sentence (which now lives only in parent_lean.md itself, per M2) — proves
    the gate actually changes behavior rather than being dead code."""
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True)

    conv = Conversation(sender_id="lean_ctx_on", platform="messenger", segment="PARENT")
    conv.history = []
    conv.adult_subscription_status = ""
    lead = Lead(
        sender_id="lean_ctx_on", platform="messenger", segment="PARENT",
        child_age="12", name="ნიკა", phone="", calendly_booked=True,
    )
    conv.lead = lead

    ctx = ple._build_sales_context(conv, lead, "მადლობა")
    assert "დაჯავშნის შემდეგ" in ctx
    assert "\"მადლობა თქვენ. კონსულტაცია ჩანიშნულია და მენეჯერი დაგიკავშირდებათ.\"" not in ctx
    assert "სიამოვნებით" in ctx  # the ban is still present, just reworded
