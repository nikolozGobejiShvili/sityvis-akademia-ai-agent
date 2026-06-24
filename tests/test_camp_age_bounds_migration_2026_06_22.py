"""Camp age-band source-of-truth migration 5A-1 (2026-06-22).

The audit found 6 LIVE readers reading the camp age band (age_min/age_max)
directly from `camp_2026.yaml`, bypassing the canonical
`admin_config_service.get_camp_facts()`. This task migrates the FIRST 3:

  * parent_flow._age_status_for_lead   (eligibility classification)
  * parent_flow._camp_age_bounds       (under-age handoff bounds)
  * parent_llm_engine._age_status      (engine eligibility helper)

via a new canonical helper `admin_config_service.get_camp_age_bounds()`.
The other 3 readers (prompt age band, booking eligibility, adult-switch) are
INTENTIONALLY left for 5A-2 and are guarded here as still-camp_2026.

All offline / mocked — no real network.
"""
from __future__ import annotations

import inspect

import pytest

from app.agent.llm import parent_llm_engine
from app.flows import parent_flow
from app.models.lead import Lead
from app.services import admin_config_service


def _lead(age) -> Lead:
    return Lead(sender_id="x", platform="instagram", segment="PARENT", child_age=str(age))


# ===========================================================================
# (1,2,3) the canonical helper
# ===========================================================================


def test_helper_uses_admin_config(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_facts", lambda: {"age_min": 10, "age_max": 16})
    assert admin_config_service.get_camp_age_bounds() == (10, 16)


def test_helper_fallback_when_config_missing(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_facts", lambda: {})
    assert admin_config_service.get_camp_age_bounds() == (9, 17)


@pytest.mark.parametrize("bad", [
    {"age_min": "abc", "age_max": None},
    {"age_min": None, "age_max": "x"},
    {"age_min": "", "age_max": ""},
])
def test_helper_malformed_safe_fallback(monkeypatch, bad):
    monkeypatch.setattr(admin_config_service, "get_camp_facts", lambda: bad)
    assert admin_config_service.get_camp_age_bounds() == (9, 17)


def test_helper_does_not_raise_when_camp_facts_raises(monkeypatch):
    def _boom():
        raise RuntimeError("config down")
    monkeypatch.setattr(admin_config_service, "get_camp_facts", _boom)
    assert admin_config_service.get_camp_age_bounds() == (9, 17)


# ===========================================================================
# (4,5,6) the 3 migrated readers follow the canonical helper
# ===========================================================================


def test_parent_flow_age_status_uses_admin_band(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (10, 16))
    assert parent_flow._age_status_for_lead(_lead(9)) == "ineligible"
    assert parent_flow._age_status_for_lead(_lead(12)) == "eligible"
    assert parent_flow._age_status_for_lead(_lead(17)) == "ineligible"


def test_camp_age_bounds_uses_admin(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (11, 15))
    assert parent_flow._camp_age_bounds() == (11, 15)


def test_engine_age_status_uses_admin_band(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (10, 16))
    assert parent_llm_engine._age_status(_lead(9)) == "ineligible"
    assert parent_llm_engine._age_status(_lead(14)) == "eligible"
    assert parent_llm_engine._age_status(_lead(17)) == "ineligible"


# ===========================================================================
# (7,8) an Admin Config age-range edit changes the migrated classification
# ===========================================================================


def test_admin_age_min_10_makes_9_ineligible(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_facts", lambda: {"age_min": 10, "age_max": 17})
    assert parent_flow._age_status_for_lead(_lead(9)) == "ineligible"
    assert parent_llm_engine._age_status(_lead(9)) == "ineligible"
    assert parent_flow._camp_age_bounds() == (10, 17)


def test_admin_age_max_16_makes_17_ineligible(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_facts", lambda: {"age_min": 9, "age_max": 16})
    assert parent_flow._age_status_for_lead(_lead(17)) == "ineligible"
    assert parent_llm_engine._age_status(_lead(17)) == "ineligible"


# ===========================================================================
# (9,10) default 9–17 behaviour unchanged with the shipped config
# ===========================================================================


def test_default_band_unchanged_shipped_config():
    assert admin_config_service.get_camp_age_bounds() == (9, 17)
    assert parent_flow._camp_age_bounds() == (9, 17)
    for age, expected in [(8, "ineligible"), (9, "eligible"), (13, "eligible"),
                          (17, "eligible"), (18, "ineligible")]:
        assert parent_flow._age_status_for_lead(_lead(age)) == expected
        assert parent_llm_engine._age_status(_lead(age)) == expected


# ===========================================================================
# (13,14,15) the OTHER readers are intentionally NOT migrated (source guards)
# ===========================================================================


def test_migrated_helpers_no_longer_read_camp_2026_directly():
    for fn in (parent_flow._camp_age_bounds, parent_flow._age_status_for_lead,
               parent_llm_engine._age_status):
        assert 'load_knowledge("camp_2026")' not in inspect.getsource(fn), (
            f"{fn.__name__} must use get_camp_age_bounds, not camp_2026 directly"
        )


def test_prompt_age_band_and_booking_and_switch_migrated_by_5a2():
    # NOTE: 5A-2 finished migrating these three readers — they no longer read
    # camp_2026 directly (this assertion was inverted while only 5A-1 had run).
    assert 'load_knowledge("camp_2026")' not in inspect.getsource(
        parent_llm_engine._build_system_prompt)
    from app.agent.tools import parent_tool_executor
    src = inspect.getsource(parent_tool_executor)
    assert src.count("get_camp_age_bounds") >= 2          # booking + adult-switch
    assert src.count('load_knowledge("camp_2026")') == 1  # only get_camp_info fallback
