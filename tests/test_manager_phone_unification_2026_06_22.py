"""Manager-phone source-of-truth unification (2026-06-22).

The audit found TWO manager-phone chains:
  1. `admin_config_service.get_manager_phone()` (canonical) — used by the
     deterministic disclosure paths (PARENT `_render_manager_number_answer`,
     under-age fallback, ADULT executor).
  2. `admin_config_service.get_camp_facts()['phone']` — sourced from the camp
     section's `manager_contact` / camp_2026.yaml, exposed via the
     `get_camp_info` tool to the LLM.

Both happened to return `558 67 47 33`, but they were INDEPENDENT — a phone
change in one source would not reach the other. Fix: `get_camp_facts()['phone']`
now defers to `get_manager_phone()` (canonical), so every user-facing path
returns the same number and one config edit propagates everywhere.

All offline / mocked — no real network.
"""
from __future__ import annotations

import inspect

import pytest

from app.flows import parent_flow
from app.models.lead import Lead
from app.services import admin_config_service


def _lead() -> Lead:
    return Lead(sender_id="x", platform="instagram", segment="PARENT")


# ===========================================================================
# The two chains now agree
# ===========================================================================


def test_camp_facts_phone_equals_canonical():
    assert admin_config_service.get_camp_facts().get("phone") == admin_config_service.get_manager_phone()


def test_shipped_default_manager_phone_is_the_safe_fallback():
    # company.yaml provides the safe fallback when no operator override exists.
    assert admin_config_service.get_manager_phone() == "558 67 47 33"


# ===========================================================================
# A single canonical change propagates to EVERY user-facing path (#6)
# ===========================================================================


def test_changing_canonical_propagates_everywhere(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "599 00 11 22")

    # camp-info tool phone follows the canonical helper now
    assert admin_config_service.get_camp_facts().get("phone") == "599 00 11 22"
    # PARENT explicit manager-number disclosure
    assert "599 00 11 22" in parent_flow._render_manager_number_answer(_lead())
    # under-age handoff fallback contact
    assert parent_flow._manager_contact_for_fallback() == "599 00 11 22"


def test_changing_operator_config_source_propagates(monkeypatch):
    """Editing the operator-editable manager_contacts mirror changes BOTH the
    canonical helper AND the camp-info phone (proves one source of truth)."""
    monkeypatch.setattr(
        admin_config_service, "load_manager_contacts_mirror",
        lambda: {"manager_phone": "555 12 34 56"},
    )
    assert admin_config_service.get_manager_phone() == "555 12 34 56"
    assert admin_config_service.get_camp_facts().get("phone") == "555 12 34 56"


# ===========================================================================
# Fallback when the canonical helper is unconfigured (#7)
# ===========================================================================


def test_camp_facts_falls_back_to_section_contact_when_canonical_empty(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_manager_phone", lambda: "")
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda sid: {
            "id": "summer_camp", "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"], "auto_dm_template_id": "summer_camp_comment_dm",
            "manager_contact": "577 88 99 00",
        } if sid == "summer_camp" else None,
    )
    assert admin_config_service.get_camp_facts().get("phone") == "577 88 99 00"


# ===========================================================================
# ADULT + Sunday-School + no-hardcode guards
# ===========================================================================


def test_adult_executor_uses_canonical_no_hardcode():
    from app.agent.tools import adult_tool_executor
    src = inspect.getsource(adult_tool_executor)
    assert "get_manager_phone()" in src
    assert "558 67 47 33" not in src and "558674733" not in src


def test_parent_disclosure_and_underage_fallback_have_no_hardcoded_number():
    src = inspect.getsource(parent_flow._render_manager_number_answer)
    assert "558 67 47 33" not in src and "558674733" not in src
    src2 = inspect.getsource(parent_flow._manager_contact_for_fallback)
    assert "558 67 47 33" not in src2 and "558674733" not in src2


def test_sunday_school_answer_discloses_no_phone():
    # SS handoff is email-only; the deterministic answer must not embed a number.
    out = parent_flow._render_sunday_school_answer()
    assert "558" not in out
    assert "599" not in out
