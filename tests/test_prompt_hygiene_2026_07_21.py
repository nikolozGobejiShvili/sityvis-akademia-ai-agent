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


def test_dynamic_programs_suffix_still_appends_with_lean_prompt(monkeypatch):
    """M-6: the dynamic-programs suffix appends AFTER prompt selection, so it
    must still fire with USE_LEAN_PROMPT ON + USE_DYNAMIC_PROGRAMS ON."""
    from app.services import admin_config_service

    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True, USE_DYNAMIC_PROGRAMS=True)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda *a, **k: [{"id": "lean_prog_x", "name": "ლინ-პროგრამა"}],
    )
    out = ple._build_system_prompt("რა პროგრამებია?", "PARENT")
    assert _LEAN_MARKER in out
    assert "[დინამიური პროგრამები]" in out
    assert "lean_prog_x" in out


def test_approved_answer_suffix_still_appends_with_lean_prompt(monkeypatch):
    """M-6: the approved-answer suffix appends AFTER prompt selection, so it
    must still fire with USE_LEAN_PROMPT ON + USE_LEARNING ON."""
    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True, USE_LEARNING=True)
    out = ple._build_system_prompt("გაურკვეველი კითხვა", "PARENT")
    assert _LEAN_MARKER in out
    assert "[დამტკიცებული პასუხები]" in out
    assert "get_approved_answer(question)" in out


# --- Restored guardrail strings (review findings C-1/C-2/I-1/I-3/I-4/M-2/M-3/M-4) ---
#
# Each string below was dropped from the first draft of `parent_lean.md` and
# restored verbatim from `system_parent_v2.md` (line cited). A future edit must
# not silently drop them again — the sanitizer is being thinned in Task 4, so
# for several of these the prompt is the ONLY remaining defense.
_RESTORED_LEAN_GUARDRAILS = (
    # C-1 — banned-phrase bullets (system_parent_v2.md L363/365/369/373/379/380)
    "შესაძლებლისთანავე",
    "ადგილი - ",
    "რას მიიჩნევთ ყველაზე მნიშვნელოვანია",
    "კიდევ რაიმეში დაგჭირდეთ დახმარება?",
    "თუ რამე დაგჭირდებათ, თუ კიდევ რამე…",
    "დაგეხმარებით როცა დაგჭირდებათ",
    # C-2 — old-phrase ban attached to the approved intro (L263)
    "თვითგამოხატვის პროცესში ერთვებიან",
    # I-1 — price objection: the never-invent-a-discount rule (L150)
    "გამოიგონო ფასდაკლება/ფასი",
    # I-3 — two-questions sub-rule (L128/L131)
    "ჩააგდო ერთი მათგანი",
    # I-4 — შეშფოთების შენახვა (L298–300). Distinctive string (occurs exactly
    # once in parent_lean.md) — "save_lead_info"/"challenge" were replaced
    # here because each occurs 3x in the file for unrelated reasons, so the
    # test could not fail even when this entire bullet was deleted
    # (empirically verified: deleting parent_lean.md:127 still gave
    # `1 passed` with the old sentinels).
    "შეშფოთების შენახვა",
    # M-2 — repeated thanks must not reuse the same text (L239)
    "გამეორებულ",
    # M-3 — banned booking-error wording on a past date (L403)
    "ამ დროის დაჯავშნა ვერ დავადასტურე",
    # M-4 — „ადგილზე მოსვლა" mention-ban (L343)
    "ადგილზე მოსვლა",
)


def test_lean_prompt_keeps_restored_guardrail_strings():
    raw = load_prompt("parent_lean")
    missing = [s for s in _RESTORED_LEAN_GUARDRAILS if s not in raw]
    assert not missing, f"parent_lean.md dropped restored guardrails: {missing}"


def test_lean_prompt_price_objection_is_behavioral_not_verbatim_script():
    """I-1: the 4-step price-objection script must NOT be transcribed — the two
    fixed quoted sentences from system_parent_v2.md:387 stay out of the lean
    prompt, while every actual guarantee stays explicit."""
    raw = load_prompt("parent_lean")
    assert "გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია" not in raw
    for guarantee in ("მოტივაცია", "იაფია", "განვადება", "TBC"):
        assert guarantee in raw


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


# ===========================================================================
# I-2 — the still-injected discovery script must be gated behind the flag
# ===========================================================================
#
# `_build_sales_context` injected a hardcoded verbatim Georgian discovery
# question on EVERY eligible-age turn where `lead.challenge` was empty,
# flag-agnostic. Under the lean prompt that second script fights the lean
# prompt's own „ask one natural motivational question" rule (parent_lean.md).
# Only the thanks branch had been gated; this pins the discovery branch too.
# The flag-OFF path stays byte-identical.

_DISCOVERY_SCRIPT_SENTENCE = (
    "დასვი ერთი მკაფიო კითხვა: „რა არის მთავარი, რის "
    "მიღებაც გსურთ ბანაკიდან — ახალი მეგობრები, ეკრანთან "
    "დროის შემცირება, თვითგამოხატვა, თავდაჯერება თუ სხვა?“ "
)


def _discovery_conv_lead(sender_id):
    from app.models.conversation import Conversation
    from app.models.lead import Lead

    conv = Conversation(sender_id=sender_id, platform="messenger", segment="PARENT")
    conv.history = []
    conv.adult_subscription_status = ""
    lead = Lead(
        sender_id=sender_id, platform="messenger", segment="PARENT",
        child_age="12", name="", phone="", challenge="",
    )
    conv.lead = lead
    return conv, lead


def test_build_sales_context_flag_off_discovery_script_byte_identical(monkeypatch):
    """Flag OFF ⇒ the hardcoded verbatim discovery question is emitted exactly
    as today (byte-identical)."""
    _swap_settings(monkeypatch, USE_LEAN_PROMPT=False)
    conv, lead = _discovery_conv_lead("lean_disc_off")

    ctx = ple._build_sales_context(conv, lead, "გამარჯობა")
    expected = (
        "Sales context (აუდიტორიაზე მორგებული გაყიდვა):\n"
        "- ასაკი დიაპაზონშია, მშობლის მიზანი ჯერ უცნობია — "
        + _DISCOVERY_SCRIPT_SENTENCE
        + "შეშფოთება არ აიძულო. თუ მომხმარებელი ცხადად ითხოვს "
        "ჩაწერას — ჯერ ჩაწერა, მიზანი ნუ დაბლოკავს."
    )
    assert ctx.startswith(expected)


def test_build_sales_context_flag_on_discovery_is_behavioral_pointer(monkeypatch):
    """Flag ON ⇒ no second verbatim script; a behavioral pointer instead, with
    every guarantee (don't force a concern, don't block an explicit booking
    request) preserved."""
    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True)
    conv, lead = _discovery_conv_lead("lean_disc_on")

    ctx = ple._build_sales_context(conv, lead, "გამარჯობა")
    assert _DISCOVERY_SCRIPT_SENTENCE not in ctx
    assert "ახალი მეგობრები, ეკრანთან" not in ctx
    assert "მოტივაციური კითხვა" in ctx
    assert "შეშფოთება" in ctx
    assert "ჩაწერის" in ctx


def test_build_sales_context_known_challenge_branch_unchanged_by_flag(monkeypatch):
    """The already-known-goal branch is NOT part of the I-2 gate — it carries no
    verbatim script, so it must read the same with the flag on or off."""
    conv_off, lead_off = _discovery_conv_lead("lean_disc_known_off")
    lead_off.challenge = "ახალი მეგობრები"
    _swap_settings(monkeypatch, USE_LEAN_PROMPT=False)
    ctx_off = ple._build_sales_context(conv_off, lead_off, "გამარჯობა")

    conv_on, lead_on = _discovery_conv_lead("lean_disc_known_on")
    lead_on.challenge = "ახალი მეგობრები"
    _swap_settings(monkeypatch, USE_LEAN_PROMPT=True)
    ctx_on = ple._build_sales_context(conv_on, lead_on, "გამარჯობა")

    assert ctx_off == ctx_on
