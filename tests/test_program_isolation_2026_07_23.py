"""Program isolation — USE_PROGRAM_ISOLATION (2026-07-23).

The cases_v2 synthetic-product eval leaked the camp location „ამბასადორი"
into a robotics-product answer (RC-PI2: present=['ვაკე'] inventions=['ამბასადორი']).
Root cause: the giant camp-centric prompt + camp tools load on EVERY turn, and the
dynamic-programs suffix told the LLM „facts only from the tool" but NOT „never mix
another program's facts". With USE_PROGRAM_ISOLATION ON, the dynamic suffix gains an
explicit anti-mixing instruction so a specific program's answer draws ONLY from that
program's get_program_info data. Gated on top of USE_DYNAMIC_PROGRAMS; OFF ⇒ the
dynamic suffix is byte-identical to before this flag existed.
"""
import dataclasses

from app.agent.llm import parent_llm_engine
from app.config import Settings
from app.services import admin_config_service

_TWO_PROGRAMS = [
    {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "active"},
    {"id": "robotics_club", "name": "რობოტიკის კლუბი", "status": "active"},
]


def _pin(monkeypatch, **flags):
    swapped = dataclasses.replace(parent_llm_engine.settings, **flags)
    monkeypatch.setattr(parent_llm_engine, "settings", swapped)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda: list(_TWO_PROGRAMS),
    )


# --- flag default ---

def test_flag_defaults_false():
    assert Settings().USE_PROGRAM_ISOLATION is False


def test_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_PROGRAM_ISOLATION", "true")
    assert Settings.from_env().USE_PROGRAM_ISOLATION is True


# --- suffix content ---

def test_isolation_absent_when_flag_off(monkeypatch):
    """USE_DYNAMIC_PROGRAMS on, USE_PROGRAM_ISOLATION off → suffix is the
    pre-existing dynamic text with NO isolation clause (byte-identical arm)."""
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=False)
    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()

    assert "list_programs" in suffix                      # base suffix still there
    assert "დამოუკიდებელია" not in suffix                 # isolation clause absent
    assert "არ ჩაანაცვლო" not in suffix


def test_isolation_present_when_flag_on(monkeypatch):
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True)
    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()

    assert "list_programs" in suffix                      # base suffix preserved
    assert "დამოუკიდებელია" in suffix                     # isolation clause added
    assert "არ ჩაანაცვლო" in suffix
    # names it as an example of what NOT to borrow
    assert "ბანაკის" in suffix


def test_isolation_forbids_camp_value_framing(monkeypatch):
    """Live test 2026-07-28: isolation must also forbid borrowing camp's VALUE
    framing/opener (ცოცხალი ურთიერთობა / აზროვნება / …), not only its facts —
    the model was applying camp's value opener to Disneyland."""
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True)
    suffix = parent_llm_engine._dynamic_programs_prompt_suffix()
    assert "ღირებულების ჩარჩო" in suffix       # value-framing clause added
    assert "ცოცხალი ურთიერთობა" in suffix       # names the camp value opener
    # flag OFF → value-framing clause absent (byte-identical off)
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=False)
    off = parent_llm_engine._dynamic_programs_prompt_suffix()
    assert "ღირებულების ჩარჩო" not in off


def test_isolation_extends_base_suffix(monkeypatch):
    """The ON suffix is a strict superset (starts-with) of the OFF suffix — the
    isolation clause is appended, the base text is not rewritten."""
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=False)
    base = parent_llm_engine._dynamic_programs_prompt_suffix()

    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True)
    extended = parent_llm_engine._dynamic_programs_prompt_suffix()

    assert extended.startswith(base)
    assert len(extended) > len(base)


def test_no_suffix_at_all_when_dynamic_off(monkeypatch):
    """USE_DYNAMIC_PROGRAMS off short-circuits to '' regardless of isolation
    flag — the isolation clause can never appear without the dynamic gate."""
    _pin(monkeypatch, USE_DYNAMIC_PROGRAMS=False, USE_PROGRAM_ISOLATION=True)
    assert parent_llm_engine._dynamic_programs_prompt_suffix() == ""


def test_no_suffix_when_no_dynamic_programs(monkeypatch):
    """Only the camp is active → no non-reserved programs → '' even with both
    flags on (nothing to isolate)."""
    swapped = dataclasses.replace(
        parent_llm_engine.settings,
        USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True,
    )
    monkeypatch.setattr(parent_llm_engine, "settings", swapped)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda: [{"id": "summer_camp", "name": "საზაფხულო ბანაკი", "status": "active"}],
    )
    assert parent_llm_engine._dynamic_programs_prompt_suffix() == ""
