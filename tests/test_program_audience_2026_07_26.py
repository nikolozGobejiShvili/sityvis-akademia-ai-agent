"""Program audience + camp-off offer (USE_PROGRAM_AUDIENCE, 2026-07-26 live test).

Fix 2: a camp-off reply offered „საკვირაო სკოლა" even when it was INACTIVE. When on, the
camp-off „what else" line lists the ACTIVE child/family programs by name from the config;
OFF ⇒ the approved static Sunday-School offer (byte-identical). Audience derives from an
explicit `audience` field, else from `type` (camp/kids_program→child, adult_events→adult,
else family). The admin form persists `audience`.
"""
import dataclasses
from unittest.mock import patch

from app import config
from app.flows import parent_flow as pf
from app.services import admin_config_service as acs
from app.routes.admin import _form_to_section_dict


# --- audience derivation ---

def test_audience_explicit_wins():
    assert acs.get_program_audience({"audience": "child", "type": "adult_events"}) == "child"


def test_audience_derived_from_type():
    assert acs.get_program_audience({"type": "camp"}) == "child"
    assert acs.get_program_audience({"type": "kids_program"}) == "child"
    assert acs.get_program_audience({"type": "adult_events"}) == "adult"
    assert acs.get_program_audience({"type": "other"}) == "family"        # unknown → safe family
    assert acs.get_program_audience({}) == "family"


# --- active child/family names ---

_SECS = [
    {"id": "summer_camp", "name": "ბანაკი", "status": "active", "type": "camp"},
    {"id": "disneyland_tour", "name": "დისნეილენდი", "status": "active", "audience": "child"},
    {"id": "formula_1", "name": "ფორმულა 1", "status": "active", "type": "other"},   # family
    {"id": "adult_events", "name": "ღონისძიებები", "status": "active", "type": "adult_events"},
    {"id": "sunday_school", "name": "საკვირაო სკოლა", "status": "coming_soon", "type": "kids_program"},
]


def test_active_child_names_excludes_camp_adult_and_inactive(monkeypatch):
    monkeypatch.setattr(acs, "get_active_sections",
                        lambda: [s for s in _SECS if s["status"] == "active"])
    names = acs.get_active_child_program_names()
    assert "დისნეილენდი" in names          # child
    assert "ფორმულა 1" in names            # family
    assert "ბანაკი" not in names           # camp excluded
    assert "ღონისძიებები" not in names     # adult excluded
    assert "საკვირაო სკოლა" not in names   # inactive (coming_soon) excluded


# --- the camp-off offer ---

def _msg(monkeypatch, flag, secs):
    monkeypatch.setattr(pf, "settings", dataclasses.replace(config.settings, USE_PROGRAM_AUDIENCE=flag))
    monkeypatch.setattr(acs, "get_active_sections", lambda: secs)
    return pf._camp_status_message("ended")


def test_camp_off_offer_off_is_byte_identical(monkeypatch):
    out = _msg(monkeypatch, False, [s for s in _SECS if s["status"] == "active"])
    assert "საკვირაო სკოლა" in out          # the approved static offer, unchanged


def test_camp_off_offer_on_lists_active_child_programs(monkeypatch):
    out = _msg(monkeypatch, True, [s for s in _SECS if s["status"] == "active"])
    assert "დისნეილენდი" in out and "ფორმულა 1" in out
    assert "საკვირაო სკოლა" not in out       # inactive → not offered (the live bug)


def test_camp_off_offer_on_no_child_programs_offers_manager(monkeypatch):
    out = _msg(monkeypatch, True, [{"id": "adult_events", "name": "ღონ", "status": "active", "type": "adult_events"}])
    assert "მენეჯერთან" in out
    assert "საკვირაო სკოლა" not in out


# --- admin form persists audience ---

def test_admin_form_saves_audience():
    d = _form_to_section_dict(id="disneyland_tour", name="დისნეილენდი", audience="child")
    assert d["audience"] == "child"
    # invalid → family
    assert _form_to_section_dict(id="x", name="x", audience="bogus")["audience"] == "family"


# --- Fix 3: participant-age rule (audience surfaced to the LLM) ---

def test_dynamic_suffix_participant_age_rule(monkeypatch):
    from app.agent.llm import parent_llm_engine as ple
    secs = [{"id": "formula_1", "name": "ფორმულა 1", "status": "active", "type": "other"}]

    def suffix(flag):
        monkeypatch.setattr(ple, "settings", dataclasses.replace(
            config.settings, USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_AUDIENCE=flag))
        monkeypatch.setattr("app.services.admin_config_service.get_active_sections", lambda: secs)
        return ple._dynamic_programs_prompt_suffix()

    assert "მონაწილის ასაკი" not in suffix(False)   # off ⇒ byte-identical
    on = suffix(True)
    assert "მონაწილის ასაკი" in on                  # participant-age guidance added
    assert "audience" in on
