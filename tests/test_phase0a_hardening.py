"""Phase 0a hardening — boot-log flags + normalized active-status +
reserved-id prompt-suffix consistency.

Context: `USE_DYNAMIC_PROGRAMS` was enabled in production but an admin-added
program wasn't recognized. An audit found (a) NO boot-log signal for the
smart-agent feature flags, and (b) `get_active_sections()` did an
un-normalized exact `status == "active"` match, and (c) the dynamic-programs
prompt suffix only excluded `summer_camp` from the "dynamic programs" list
even though `get_program_info` refuses all THREE reserved ids
(`summer_camp` / `sunday_school` / `adult_events`).

Fix 1 (boot-log) has no unit-testable behavior beyond "the app still boots"
— covered indirectly by the full test suite importing `app.main`. This file
covers Fix 2 and Fix 3.
"""


def test_get_active_sections_normalizes_case_and_whitespace(monkeypatch):
    """status "Active" / " active " must be included (previously silently
    excluded by the exact-match compare) — the live bug this patch fixes."""
    from app.services import admin_config_service

    sections = [
        {"id": "a", "status": "Active"},
        {"id": "b", "status": " active "},
        {"id": "c", "status": "active"},
        {"id": "d", "status": "coming_soon"},
        {"id": "e", "status": ""},
        {"id": "f"},  # missing status entirely
    ]

    monkeypatch.setattr(admin_config_service, "load_sections", lambda: sections)
    active_ids = {s["id"] for s in admin_config_service.get_active_sections()}

    assert active_ids == {"a", "b", "c"}
    # coming_soon / empty / missing must NEVER be defaulted to active.
    assert "d" not in active_ids
    assert "e" not in active_ids
    assert "f" not in active_ids


def test_get_active_sections_shipped_data_unchanged(monkeypatch):
    """Shipped sections.yaml already uses lowercase active/coming_soon —
    behavior for existing data must be byte-identical (same ids as an exact
    '== \"active\"' compare would have returned)."""
    from app.services import admin_config_service

    sections = admin_config_service.load_sections()
    exact_match_ids = {s.get("id") for s in sections if s.get("status") == "active"}
    normalized_ids = {s.get("id") for s in admin_config_service.get_active_sections()}
    assert normalized_ids == exact_match_ids


# ---------------------------------------------------------------------------
# Fix 3 — `_dynamic_programs_prompt_suffix` must exclude ALL reserved ids
# (summer_camp / sunday_school / adult_events), not just summer_camp.
#
# FROZEN-SETTINGS PATTERN (mirrors tests/test_dynamic_programs.py): `Settings`
# is a frozen dataclass, so `USE_DYNAMIC_PROGRAMS` is toggled via
# `dataclasses.replace(...)` + swapping the MODULE-level `settings` binding
# that `parent_llm_engine` reads.
# ---------------------------------------------------------------------------


def test_dynamic_programs_prompt_suffix_excludes_all_reserved_ids(monkeypatch):
    import dataclasses
    from app.agent.llm import parent_llm_engine
    from app.services import admin_config_service

    on_settings = dataclasses.replace(parent_llm_engine.settings, USE_DYNAMIC_PROGRAMS=True)
    monkeypatch.setattr(parent_llm_engine, "settings", on_settings)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda: [
            {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "active"},
            {"id": "sunday_school", "name": "საკვირაო სკოლა", "status": "active"},
            {"id": "adult_events", "name": "ზრდასრულთა ღონისძიება", "status": "active"},
            {"id": "robotics_club", "name": "რობოტიკის კლუბი", "status": "active"},
        ],
    )

    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()

    # Only the genuinely dynamic program is listed.
    assert suffix != ""
    assert "robotics_club" in suffix or "რობოტიკის კლუბი" in suffix
    # None of the three reserved ids/names ever appear as "dynamic".
    for reserved_id, reserved_name in (
        ("summer_camp", "საზაფხულო ბანაკი"),
        ("sunday_school", "საკვირაო სკოლა"),
        ("adult_events", "ზრდასრულთა ღონისძიება"),
    ):
        assert reserved_id not in suffix
        assert reserved_name not in suffix


def test_dynamic_programs_prompt_suffix_empty_when_only_reserved_ids_active(monkeypatch):
    """When every active section is reserved, there is nothing "dynamic" to
    announce — the suffix must be empty (not an empty-looking list)."""
    import dataclasses
    from app.agent.llm import parent_llm_engine
    from app.services import admin_config_service

    on_settings = dataclasses.replace(parent_llm_engine.settings, USE_DYNAMIC_PROGRAMS=True)
    monkeypatch.setattr(parent_llm_engine, "settings", on_settings)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda: [
            {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "active"},
            {"id": "sunday_school", "name": "საკვირაო სკოლა", "status": "active"},
            {"id": "adult_events", "name": "ზრდასრულთა ღონისძიება", "status": "active"},
        ],
    )

    assert parent_llm_engine._dynamic_programs_prompt_suffix() == ""


def test_reserved_program_ids_matches_program_id_enum():
    """The module-level reserved-id set must stay in sync with the canonical
    `ProgramId` enum (the same single source `parent_flow._HARDCODED_PROGRAM_IDS`
    and `parent_tool_executor._get_program_info` derive theirs from)."""
    from app.agent.llm import parent_llm_engine
    from app.domain.decision.models import ProgramId

    assert parent_llm_engine._RESERVED_PROGRAM_IDS == frozenset(
        p.value for p in ProgramId
    )
    assert parent_llm_engine._RESERVED_PROGRAM_IDS == {
        "summer_camp", "sunday_school", "adult_events",
    }
