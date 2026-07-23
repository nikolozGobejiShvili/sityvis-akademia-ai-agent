"""Reserved programs → dynamic — USE_RESERVED_PROGRAMS_DYNAMIC (2026-07-23).

Live bug: „საკვირაო სკოლა დაიწყო?" got „გთხოვთ, დააზუსტოთ რას გულისხმობთ" — the agent
didn't recognise Sunday School, because it is a RESERVED program handled by canned
flows, not the LLM engine. With USE_RESERVED_PROGRAMS_DYNAMIC on, sunday_school drops
out of the effective reserved set (single source `reserved_program_ids()`), so the
dynamic hoist fires for it and get_program_info reasons over its admin data — like
any program the operator adds. Camp + adult_events keep their curated flows.
OFF ⇒ reserved set is the full ProgramId set ⇒ byte-identical.
"""
import dataclasses

import app.config as cfg
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.config import Settings
from app.domain.decision.models import reserved_program_ids
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service

_SS = {"id": "sunday_school", "name": "საკვირაო სკოლა", "status": "active",
       "type": "kids_program", "price_monthly": "200 ₾/თვე"}


def _pin(monkeypatch, on: bool):
    swapped = dataclasses.replace(cfg.settings, USE_RESERVED_PROGRAMS_DYNAMIC=on)
    monkeypatch.setattr(cfg, "settings", swapped)


def _executor():
    conv = Conversation(sender_id="x", platform="instagram", segment="PARENT")
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    return ParentToolExecutor(conv, lead, "x", "instagram", user_message="")


# --- flag + helper ---

def test_flag_defaults_false():
    assert Settings().USE_RESERVED_PROGRAMS_DYNAMIC is False


def test_reserved_set_off_vs_on(monkeypatch):
    _pin(monkeypatch, False)
    assert "sunday_school" in reserved_program_ids()
    _pin(monkeypatch, True)
    assert "sunday_school" not in reserved_program_ids()
    assert "summer_camp" in reserved_program_ids()      # camp stays curated
    assert "adult_events" in reserved_program_ids()     # adult stays curated


# --- get_program_info now serves Sunday School when ON ---

def test_get_program_info_rejects_ss_when_off(monkeypatch):
    _pin(monkeypatch, False)
    r = _executor()._get_program_info({"program_id": "sunday_school"})
    assert r["reason"] == "use_specific_tool"           # reserved → canned (unchanged)


def test_get_program_info_serves_ss_when_on(monkeypatch):
    _pin(monkeypatch, True)
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda pid: dict(_SS) if pid == "sunday_school" else None,
    )
    r = _executor()._get_program_info({"program_id": "sunday_school"})
    assert r["success"] is True
    assert r["name"] == "საკვირაო სკოლა"
    assert "price_monthly" in r["facts"]                # reasons over the monthly fee


# --- the hoist fires for Sunday School when ON ---

def test_hoist_matches_ss_when_on(monkeypatch):
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(parent_flow.settings, USE_DYNAMIC_PROGRAMS=True),
    )
    _pin(monkeypatch, True)
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [dict(_SS)])
    assert parent_flow._is_dynamic_program_turn("საკვირაო სკოლა მაინტერესებს") is True


def test_hoist_skips_ss_when_off(monkeypatch):
    """Flag off → sunday_school stays reserved → hoist does NOT fire (canned path)."""
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(parent_flow.settings, USE_DYNAMIC_PROGRAMS=True),
    )
    _pin(monkeypatch, False)
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [dict(_SS)])
    assert parent_flow._is_dynamic_program_turn("საკვირაო სკოლა მაინტერესებს") is False
