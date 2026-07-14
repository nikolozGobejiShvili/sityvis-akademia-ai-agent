"""Camp age-band migration 5A-2 (2026-06-22) — finish the LIVE age-band move.

5A-1 migrated the parent_flow + engine age-status helpers. 5A-2 migrates the
final 3 LIVE age-band readers off direct `camp_2026.yaml` reads onto the
canonical `admin_config_service.get_camp_age_bounds()`:

  * parent_llm_engine._build_system_prompt  (runtime prompt age band)
  * parent_tool_executor.book_consultation   (booking eligibility)
  * parent_tool_executor.switch_to_adult_flow (adult-switch age range)

Default band stays 9–17, so today's behaviour is byte-identical; an operator
Admin-Config age edit now reaches all three. NO `.md` prompt / YAML edits.

All offline / mocked — no real Calendar/Sheets/email/WhatsApp/network.
"""
from __future__ import annotations

import inspect

import pytest

from app.agent.llm import parent_llm_engine
from app.agent.llm.prompt_loader import load_prompt
from app.agent.tools import parent_tool_executor
from app.agent.tools.parent_tool_executor import ParentToolExecutor
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service, calendar_service

_FUTURE_ISO = "2026-06-25T12:00:00+04:00"  # Thursday, in hours, future of 2026-06-22


@pytest.fixture(autouse=True)
def _reset():
    parent_tool_executor.reset_state()
    yield
    parent_tool_executor.reset_state()


def _executor(child_age="14", sender="ab-u"):
    conv = Conversation(sender_id=sender, platform="instagram", segment="PARENT")
    conv.lead = Lead(sender_id=sender, platform="instagram", segment="PARENT", child_age=child_age)
    return ParentToolExecutor(conversation=conv, lead=conv.lead, sender_id=sender, platform="instagram")


# ===========================================================================
# (1,2,3) runtime prompt context uses the canonical band — .md untouched
# ===========================================================================


def _company():
    return parent_llm_engine.settings.COMPANY_NAME or "სიტყვის აკადემია"


def test_prompt_band_follows_canonical_config(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (10, 16))
    raw = load_prompt("system_parent_v2")
    assert parent_llm_engine._build_system_prompt() == raw.format(
        company_name=_company(), age_min=10, age_max=16,
    )


def test_prompt_default_band_unchanged():
    raw = load_prompt("system_parent_v2")
    assert parent_llm_engine._build_system_prompt() == raw.format(
        company_name=_company(), age_min=9, age_max=17,
    )


# ===========================================================================
# (4,5,6,7) booking eligibility uses the canonical band
# ===========================================================================


def _mock_calendar(monkeypatch):
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda *a, **k: True)
    def _book(**kw):
        lead = kw.get("lead")
        if lead is not None:
            lead.calendar_event_id = "evt_age_test"
        return True
    monkeypatch.setattr(calendar_service, "book_slot", _book)


def test_booking_rejects_age_9_when_admin_min_is_10(monkeypatch, camp_registration_open):       # (#5)
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (10, 17))
    _mock_calendar(monkeypatch)
    res = _executor(child_age="9").execute("book_consultation", {
        "name": "ნიკოლოზი", "phone": "595999733", "child_age": "9",
        "datetime_iso": _FUTURE_ISO, "user_confirmed_datetime": True,
    })
    assert res["success"] is False and res["reason"] == "age_not_eligible"
    assert res["age_min"] == 10 and res["age_max"] == 17


def test_booking_rejects_age_17_when_admin_max_is_16(monkeypatch, camp_registration_open):      # (#6)
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (9, 16))
    _mock_calendar(monkeypatch)
    res = _executor(child_age="17").execute("book_consultation", {
        "name": "ნიკოლოზი", "phone": "595999733", "child_age": "17",
        "datetime_iso": _FUTURE_ISO, "user_confirmed_datetime": True,
    })
    assert res["success"] is False and res["reason"] == "age_not_eligible"


# (#7 — default 9–17 booking eligibility for age 9/14/17 is covered by the
# existing full booking suite; the band-CHANGE contrast above proves the
# canonical band now drives the gate.)


# ===========================================================================
# (8,9,10) adult-switch age range uses the canonical band
# ===========================================================================


def test_adult_switch_transfers_age_17_when_admin_max_is_16(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (9, 16))
    ex = _executor(child_age="17", sender="sw1")
    res = ex.execute("switch_to_adult_flow", {"reason": "adult_event_interest"})
    assert res["success"] is True and res["segment"] == "ADULT"
    assert res["transferred_adult_age"] == "17"   # 17 outside (9,16) → transferred
    assert (ex.lead.child_age or "") == ""        # cleared


def test_adult_switch_keeps_age_17_inside_default_band(monkeypatch):
    ex = _executor(child_age="17", sender="sw2")  # default band 9–17
    res = ex.execute("switch_to_adult_flow", {"reason": "adult_event_interest"})
    assert res["success"] is True
    assert res["transferred_adult_age"] is None   # 17 inside 9–17 → NOT transferred


def test_adult_switch_transfers_age_9_when_admin_min_is_10(monkeypatch):
    monkeypatch.setattr(admin_config_service, "get_camp_age_bounds", lambda: (10, 17))
    ex = _executor(child_age="9", sender="sw3")
    res = ex.execute("switch_to_adult_flow", {"reason": "adult_event_interest"})
    assert res["transferred_adult_age"] == "9"    # 9 outside (10,17) → transferred


# ===========================================================================
# (11,12) source guards — exactly these migrated, nothing else
# ===========================================================================


def test_all_live_age_band_readers_use_canonical_helper():
    # the three 5A-2 readers no longer read camp_2026 directly
    assert 'load_knowledge("camp_2026")' not in inspect.getsource(parent_llm_engine._build_system_prompt)
    exec_src = inspect.getsource(parent_tool_executor)
    # book_consultation + switch_to_adult_flow now use the canonical helper (2×)
    assert exec_src.count("get_camp_age_bounds") >= 2
    # the ONLY remaining camp_2026 read in the executor is the get_camp_info
    # canonical FALLBACK (admin-first) — not an age-band bypass.
    assert exec_src.count('load_knowledge("camp_2026")') == 1


def test_unmigrated_readers_unchanged():
    # NOTE: 5A-3 has since migrated parent_flow._facts_for_post_booking too, so
    # parent_flow now has ZERO direct camp_2026 reads (asserted in the 5A-3
    # test file). The 5A-1 migrated age helpers stay migrated:
    assert 'load_knowledge("camp_2026")' not in inspect.getsource(parent_flow._camp_age_bounds)
    assert 'load_knowledge("camp_2026")' not in inspect.getsource(parent_flow._age_status_for_lead)
