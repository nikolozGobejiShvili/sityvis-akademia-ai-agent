"""State Reuse Fix (2026-06-11) — cross-flow child_age reuse, adult→parent
reschedule state, and the bare „N საათი" PM time form.

Three live bugs, all fixed deterministically (generic + state-based; no
hardcoded sender_id / profile logic):

  * BUG 1 — the ADULT flow re-asked „თქვენი შვილი რამდენი წლისაა?" for a
    child whose age was already known from the PARENT/camp flow.
  * BUG 2 — an ADULT→PARENT consultation-reschedule lost the parent state
    (re-asked child_age / treated the user as fresh).
  * BUG 3 — the BARE „8 საათი" form (no „ზე") parsed as 08:00 instead of
    20:00. „8 საათზე" / „8-ზე" already worked (this EXTENDS the parser).

All external services mocked. No network.
"""

from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead


def _enable_parent_engine(monkeypatch) -> None:
    swapped = dataclasses.replace(
        config_module.settings, USE_PARENT_LLM_ENGINE=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)


def _booked_parent_conv(**lead_kwargs) -> Conversation:
    conv = Conversation(sender_id=lead_kwargs.pop("sender_id", "s_resched"),
                        platform="messenger")
    conv.segment = "PARENT"
    conv.state = lead_kwargs.pop("state", "DONE")
    lead = Lead(sender_id=conv.sender_id, platform=conv.platform, segment="PARENT")
    lead.child_age = lead_kwargs.pop("child_age", "12")
    lead.name = lead_kwargs.pop("name", "ნიკა")
    lead.phone = lead_kwargs.pop("phone", "595999733")
    lead.calendly_booked = lead_kwargs.pop("calendly_booked", True)
    lead.booked_datetime_iso = lead_kwargs.pop("booked_datetime_iso", "2030-06-18T15:00:00+04:00")
    lead.calendar_event_id = lead_kwargs.pop("calendar_event_id", "evt_old")
    for k, v in lead_kwargs.items():
        setattr(lead, k, v)
    conv.lead = lead
    return conv


def _adult_lead(**kwargs) -> Lead:
    lead = Lead(sender_id=kwargs.pop("sender_id", "s_adult"),
                platform=kwargs.pop("platform", "instagram"),
                segment=kwargs.pop("segment", "ADULT"))
    for k, v in kwargs.items():
        setattr(lead, k, v)
    return lead


# ===========================================================================
# BUG 1 — adult-for-child must not re-ask a known child_age
# ===========================================================================


def test_b1_01_known_child_age_reused_not_reasked():
    from app.agent.llm.adult_llm_engine import (
        _ensure_adult_intro_followup,
        _maybe_capture_adult_target,
    )
    lead = _adult_lead(child_age="12")
    _maybe_capture_adult_target("ჩემი შვილისთვის მინდა", lead)
    assert lead.adult_target_relation == "შვილი"
    assert lead.adult_target_age == "12"          # reused, not blank
    # Bare confirmation must NOT re-ask the child's age.
    out = _ensure_adult_intro_followup(
        "გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით.", lead,
    )
    assert "რამდენი წლისაა" not in out


def test_b1_02_uses_known_child_age_value():
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = _adult_lead(child_age="15")
    _maybe_capture_adult_target("ჩემი შვილისთვის", lead)
    assert lead.adult_target_age == "15"


def test_b1_03_no_child_age_asks():
    from app.agent.llm.adult_llm_engine import (
        _ensure_adult_intro_followup,
        _maybe_capture_adult_target,
    )
    lead = _adult_lead()  # child_age unknown
    _maybe_capture_adult_target("ჩემი შვილისთვის", lead)
    assert lead.adult_target_relation == "შვილი"
    assert (lead.adult_target_age or "") == ""
    out = _ensure_adult_intro_followup(
        "გასაგებია, ღონისძიებებზე დაგეხმარებით.", lead,
    )
    assert "რამდენი წლისაა" in out


def test_b1_04_different_child_requalifies():
    from app.agent.llm.adult_llm_engine import (
        _ensure_adult_intro_followup,
        _maybe_capture_adult_target,
    )
    lead = _adult_lead(child_age="12")
    _maybe_capture_adult_target("სხვა შვილისთვის მინდა", lead)
    # A DIFFERENT child → do NOT reuse the stored 12; ask the new age.
    assert (lead.adult_target_age or "") == ""
    out = _ensure_adult_intro_followup(
        "გასაგებია, ღონისძიებებზე დაგეხმარებით.", lead,
    )
    assert "რამდენი წლისაა" in out


def test_b1_05_adult_age_and_child_age_coexist():
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = _adult_lead(child_age="12", adult_age="35")
    _maybe_capture_adult_target("ჩემი შვილისთვის", lead)
    assert lead.child_age == "12"
    assert lead.adult_age == "35"
    assert lead.adult_target_age == "12"


def test_b1_06_adult_age_never_overwritten_by_child_reuse():
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = _adult_lead(child_age="9", adult_age="40")
    _maybe_capture_adult_target("ჩემი შვილისთვის მინდა ღონისძიება", lead)
    assert lead.adult_age == "40"          # untouched
    assert lead.child_age == "9"           # untouched
    assert lead.adult_target_age == "9"    # reused into the target field


def test_b1_07_generic_across_sender_ids():
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    for sid, age in [("alpha", "10"), ("beta", "17"), ("12345", "14")]:
        lead = _adult_lead(sender_id=sid, child_age=age)
        _maybe_capture_adult_target("ჩემი შვილისთვის", lead)
        assert lead.adult_target_age == age


def test_b1_08_inline_age_still_wins_over_reuse():
    """An explicit inline age in the message takes precedence over the
    stored child_age (the user may be asking for a different-aged child)."""
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = _adult_lead(child_age="12")
    _maybe_capture_adult_target("ჩემი 16 წლის შვილისთვის", lead)
    assert lead.adult_target_age == "16"


def test_b1_09_bavshvi_relation_also_reuses():
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = _adult_lead(child_age="11")
    _maybe_capture_adult_target("ჩემი ბავშვისთვის მინდა", lead)
    assert lead.adult_target_relation == "ბავშვი"
    assert lead.adult_target_age == "11"


def test_b1_10_non_child_relative_does_not_reuse_child_age():
    """A sibling/friend inquiry must NOT inherit the child's age."""
    from app.agent.llm.adult_llm_engine import _maybe_capture_adult_target
    lead = _adult_lead(child_age="12")
    _maybe_capture_adult_target("ჩემი დისთვის მინდა", lead)
    assert lead.adult_target_relation == "და"
    assert (lead.adult_target_age or "") == ""  # sister's age unknown


# ===========================================================================
# BUG 2 — adult→parent reschedule must reuse parent state (no fresh re-ask)
# ===========================================================================


def test_b2_01_reschedule_entry_does_not_reask_age():
    conv = _booked_parent_conv(child_age="12")
    out = parent_flow._maybe_handle_reschedule_intent_engine(
        conv, "კონსულტაციის გადატანა მინდა ბანაკზე",
    )
    assert out is not None
    assert "რამდენი წლის" not in out          # never re-asks child age
    assert "გადატანა" in out                  # acknowledges the reschedule
    assert "რომელი ახალი დღე და დრო" in out    # asks for the new time


def test_b2_02_reschedule_entry_preserves_parent_state():
    conv = _booked_parent_conv(child_age="14", name="ანა", phone="599111222")
    parent_flow._maybe_handle_reschedule_intent_engine(conv, "გადატანა მინდა")
    assert conv.lead.child_age == "14"
    assert conv.lead.name == "ანა"
    assert conv.lead.phone == "599111222"
    assert conv.lead.calendly_booked is True


def test_b2_03_reschedule_with_datetime_defers_to_existing_flow():
    conv = _booked_parent_conv()
    out = parent_flow._maybe_handle_reschedule_intent_engine(
        conv, "18 ივნისს 15 საათზე გადავიტანოთ",
    )
    assert out is None  # slot selection handled by the existing flow


def test_b2_04_no_booking_asks_identifying_info_politely():
    conv = Conversation(sender_id="s_nobook", platform="messenger")
    conv.segment = "PARENT"
    lead = Lead(sender_id="s_nobook", platform="messenger", segment="PARENT")
    conv.lead = lead  # no booking, no pending
    out = parent_flow._maybe_handle_reschedule_intent_engine(conv, "გადატანა მინდა")
    assert out is not None
    assert "სახელი" in out and "ნომერი" in out  # asks identifying info
    assert "ღონისძიება" not in out               # never uses adult data


def test_b2_05_fresh_booking_in_progress_not_hijacked():
    """A half-built NEW booking (pending set, not booked) must keep
    flowing through the engine, not get hijacked by the reschedule ask."""
    conv = Conversation(sender_id="s_pending", platform="messenger")
    conv.segment = "PARENT"
    conv.lead = Lead(sender_id="s_pending", platform="messenger", segment="PARENT")
    conv.pending_booking = {"missing_fields": ["phone"], "attempts": 0}
    out = parent_flow._maybe_handle_reschedule_intent_engine(conv, "გადატანა")
    assert out is None


def test_b2_06_handle_returns_reschedule_prompt_without_llm(monkeypatch):
    """Integration: with the engine ON, a reschedule entry returns the
    deterministic prompt WITHOUT calling the LLM."""
    _enable_parent_engine(monkeypatch)

    def _boom(*a, **k):  # the LLM must NOT be reached
        raise AssertionError("LLM engine should not run on reschedule entry")

    from app.agent.llm import parent_llm_engine
    monkeypatch.setattr(parent_llm_engine, "run_parent_llm_turn", _boom)

    conv = _booked_parent_conv(child_age="13")
    out = parent_flow.handle(conv, "კონსულტაციის გადატანა მინდა")
    assert "რომელი ახალი დღე და დრო" in out
    assert "რამდენი წლის" not in out
    assert conv.lead.child_age == "13"


def test_b2_07_non_reschedule_message_not_intercepted():
    conv = _booked_parent_conv()
    assert parent_flow._maybe_handle_reschedule_intent_engine(
        conv, "გამარჯობა, ფასი რა ღირს?",
    ) is None


# ===========================================================================
# BUG 3 — bare „N საათი" (no „ზე") → PM. Already covered by the shared
# colloquial parser (the `საათი` suffix is in `_COLLOQUIAL_HOUR_RE`); these
# lock the behavior across every call-site so a future edit can't regress it.
# ===========================================================================


def _hour(text: str) -> int:
    from app.agent.services.timestamps import extract_colloquial_hour
    parsed = extract_colloquial_hour(text)
    assert parsed is not None, f"no time parsed from {text!r}"
    return parsed[0]


def test_b3_01_bare_8_saati_is_2000():
    from app.flows.parent_turn_router import _parse_booking_datetime
    assert _hour("18 ივნისი 8 საათი") == 20
    iso = _parse_booking_datetime("18 ივნისი 8 საათი")
    assert iso is not None and iso.split("T")[1].startswith("20:00")


def test_b3_02_bare_7_saati_is_1900():
    from app.flows.parent_turn_router import _parse_booking_datetime
    assert _hour("17 ივნისი 7 საათი") == 19
    iso = _parse_booking_datetime("17 ივნისი 7 საათი")
    assert iso is not None and iso.split("T")[1].startswith("19:00")


def test_b3_03_8_saatze_regression_still_2000():
    assert _hour("8 საათზე") == 20


def test_b3_04_8_ze_regression_still_2000():
    assert _hour("8-ზე") == 20


def test_b3_05_dilit_8_saati_is_0800_and_outside_hours():
    from app.services import calendar_service
    from app.flows.parent_flow import TBILISI_TZ
    from datetime import datetime
    assert _hour("დილით 8 საათი") == 8  # morning literal
    # 08:00 must be rejected as outside business hours.
    dt = datetime(2030, 6, 18, 8, 0, tzinfo=TBILISI_TZ)
    ok, _reason = calendar_service.is_within_business_hours(dt)
    assert ok is False


def test_b3_06_bare_10_saati_is_morning():
    assert _hour("18 ივნისი 10 საათი") == 10


def test_b3_07_explicit_2000_unchanged():
    assert _hour("18 ივნისი 20:00") == 20


def test_b3_08_executor_normaliser_corrects_bare_form():
    """When the LLM passes 08:00 for a bare „8 საათი", the executor
    normaliser corrects it to 20:00 (defense in depth)."""
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    conv = Conversation(sender_id="s", platform="instagram")
    conv.lead = Lead(sender_id="s", platform="instagram", segment="PARENT")
    ex = ParentToolExecutor(
        conversation=conv, lead=conv.lead, sender_id="s",
        platform="instagram", user_message="18 ივნისი 8 საათი",
    )
    out = ex._normalise_datetime_iso_from_message("2030-06-18T08:00:00+04:00")
    assert out.split("T")[1].startswith("20:00")
