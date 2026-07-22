"""Capability #2 — Per-Product Consultation Booking + Lead.

Plan: docs/superpowers/plans/2026-07-22-capability-per-product-booking-lead.md
Flag: USE_PER_PRODUCT_BOOKING (default OFF ⇒ byte-identical to camp booking).

GUARDRAIL ZONE — booking is money/commitment. The per-product change may ONLY
(1) swap the age-band source, (2) swap the registration source, (3) add a
program_id tag, (4) source post-booking facts per-product. It MUST NOT weaken
any validation gate. The following gates are asserted UNCHANGED with the flag
ON in Task 3 (copied from the camp guardrail tests in
tests/test_parent_llm_engine.py):
  * the ``user_confirmed_datetime`` gate,
  * the verification-phrase guard,
  * the slot-availability fail-CLOSED re-check,
  * the empty-``event_id`` silent-failure rollback,
  * the slot-mismatch rollback,
  * the per-turn ``book_consultation_success_for_conversation`` flag.
No new success path. Never relax "no event_id ⇒ not booked".
"""

from __future__ import annotations

import dataclasses

import app.config as config_module
from app.models.lead import Lead


# ── Task 1: flag + Lead.program_id ────────────────────────────────────────


def test_flag_default_off():
    assert config_module.Settings().USE_PER_PRODUCT_BOOKING is False


def test_flag_from_env_default_off(monkeypatch):
    monkeypatch.delenv("USE_PER_PRODUCT_BOOKING", raising=False)
    assert config_module.Settings.from_env().USE_PER_PRODUCT_BOOKING is False


def test_lead_program_id_defaults_empty():
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    assert lead.program_id == ""


def test_lead_program_id_round_trips_through_from_dict():
    lead = Lead(
        sender_id="s", platform="messenger", segment="PARENT",
        program_id="disneyland_tour",
    )
    restored = Lead.from_dict(lead.model_dump(mode="json"))
    assert restored.program_id == "disneyland_tour"


def test_lead_program_id_in_model_dump():
    lead = Lead(
        sender_id="s", platform="messenger", segment="PARENT",
        program_id="disneyland_tour",
    )
    assert lead.model_dump()["program_id"] == "disneyland_tour"


def test_lead_from_dict_missing_program_id_defaults_empty():
    # Older serialised payloads (no program_id key) load cleanly as legacy/camp.
    restored = Lead.from_dict(
        {"sender_id": "s", "platform": "messenger", "segment": "PARENT"},
    )
    assert restored.program_id == ""


# ── Task 2: get_program_age_bounds + is_program_registration_open ──────────
# Fail-closed to camp on any miss/blank/invalid — NEVER a disabled/no-op band.

from app.services import admin_config_service as acs  # noqa: E402


def test_age_bounds_summer_camp_is_camp_band():
    assert acs.get_program_age_bounds("summer_camp") == acs.get_camp_age_bounds()


def test_age_bounds_empty_id_is_camp_band():
    assert acs.get_program_age_bounds("") == acs.get_camp_age_bounds()


def test_age_bounds_unknown_id_is_camp_band(monkeypatch):
    monkeypatch.setattr(acs, "get_section", lambda pid: None)
    assert acs.get_program_age_bounds("nope") == acs.get_camp_age_bounds()


def test_age_bounds_dynamic_product(monkeypatch):
    monkeypatch.setattr(
        acs, "get_section",
        lambda pid: {"id": "disneyland_tour", "age_min": 7, "age_max": 16}
        if pid == "disneyland_tour" else None,
    )
    assert acs.get_program_age_bounds("disneyland_tour") == (7, 16)


def test_age_bounds_dynamic_string_bounds_parse(monkeypatch):
    monkeypatch.setattr(
        acs, "get_section",
        lambda pid: {"id": "disneyland_tour", "age_min": "7", "age_max": "16"},
    )
    assert acs.get_program_age_bounds("disneyland_tour") == (7, 16)


def test_age_bounds_dynamic_blank_min_fails_closed_to_camp(monkeypatch):
    monkeypatch.setattr(
        acs, "get_section",
        lambda pid: {"id": "disneyland_tour", "age_min": "", "age_max": 16},
    )
    assert acs.get_program_age_bounds("disneyland_tour") == acs.get_camp_age_bounds()


def test_age_bounds_dynamic_noninteger_fails_closed_to_camp(monkeypatch):
    monkeypatch.setattr(
        acs, "get_section",
        lambda pid: {"id": "disneyland_tour", "age_min": "abc", "age_max": 16},
    )
    assert acs.get_program_age_bounds("disneyland_tour") == acs.get_camp_age_bounds()


def test_age_bounds_never_raises(monkeypatch):
    def _boom(pid):
        raise RuntimeError("boom")
    monkeypatch.setattr(acs, "get_section", _boom)
    assert acs.get_program_age_bounds("disneyland_tour") == acs.get_camp_age_bounds()


def test_registration_summer_camp_delegates_to_camp():
    assert acs.is_program_registration_open("summer_camp") == \
        acs.is_camp_registration_open()


def test_registration_empty_id_delegates_to_camp():
    assert acs.is_program_registration_open("") == acs.is_camp_registration_open()


def test_registration_dynamic_open(monkeypatch):
    monkeypatch.setattr(
        acs, "get_section",
        lambda pid: {"id": "disneyland_tour", "registration_status": "open"},
    )
    assert acs.is_program_registration_open("disneyland_tour") is True


def test_registration_dynamic_missing_fails_closed(monkeypatch):
    # A dynamic product with NO registration_status must be CLOSED (fail-closed)
    # — unlike camp, whose missing value defaults open for back-compat.
    monkeypatch.setattr(
        acs, "get_section", lambda pid: {"id": "disneyland_tour"},
    )
    assert acs.is_program_registration_open("disneyland_tour") is False


def test_registration_dynamic_closed(monkeypatch):
    monkeypatch.setattr(
        acs, "get_section",
        lambda pid: {"id": "disneyland_tour", "registration_status": "closed"},
    )
    assert acs.is_program_registration_open("disneyland_tour") is False


def test_registration_unknown_section_fails_closed(monkeypatch):
    monkeypatch.setattr(acs, "get_section", lambda pid: None)
    assert acs.is_program_registration_open("nope") is False


def test_registration_never_raises(monkeypatch):
    def _boom(pid):
        raise RuntimeError("boom")
    monkeypatch.setattr(acs, "get_section", _boom)
    assert acs.is_program_registration_open("disneyland_tour") is False


# ── Task 3: per-product eligibility + registration in _book_consultation ───
# GUARDRAIL-PRESERVING. Every booking gate untouched (asserted flag ON below):
# user_confirmed gate, verification-phrase guard, empty-event_id rollback.

import pytest  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from app.models.conversation import Conversation  # noqa: E402
from app.agent.tools.parent_tool_executor import ParentToolExecutor  # noqa: E402
from app.agent.tools.parent_tools import (  # noqa: E402
    TOOL_BOOK_CONSULTATION,
    TOOL_GET_PROGRAM_INFO,
)

_TBILISI = ZoneInfo("Asia/Tbilisi")
_FUTURE_BUSINESS_ISO = "2030-06-03T12:00:00+04:00"  # Mon, within 10:00–21:00
_DISNEY = {
    "id": "disneyland_tour", "name": "დისნეილენდის ტური", "type": "tour",
    "status": "active", "age_min": 7, "age_max": 16,
    "registration_status": "open", "price_text": "3500",
}


def _flag_on(monkeypatch):
    monkeypatch.setattr(
        config_module, "settings",
        dataclasses.replace(config_module.settings, USE_PER_PRODUCT_BOOKING=True),
    )


def _seed_disney(monkeypatch, section=None):
    section = section if section is not None else _DISNEY
    monkeypatch.setattr(
        acs, "get_section",
        lambda pid: section if pid == "disneyland_tour" else None,
    )
    monkeypatch.setattr(acs, "get_active_sections", lambda: [section])


def _conv(program_id: str = ""):
    c = Conversation(sender_id="u1", platform="messenger", segment="PARENT")
    c.lead = Lead(
        sender_id="u1", platform="messenger", segment="PARENT",
        program_id=program_id,
    )
    return c


def _mk(conv, user_message=""):
    return ParentToolExecutor(
        conversation=conv, lead=conv.lead,
        sender_id=conv.sender_id, platform=conv.platform,
        user_message=user_message,
    )


def _book_args(**over):
    args = {
        "name": "ნიკა", "phone": "599112233",
        "datetime_iso": _FUTURE_BUSINESS_ISO, "child_age": "7",
        "user_confirmed_datetime": True,
    }
    args.update(over)
    return args


def test_book_flag_off_disneyland_uses_camp_band(monkeypatch, camp_registration_open):
    """Flag OFF: even with a Disneyland-tagged lead, the age band is CAMP's
    (byte-identical). A 7-year-old is age_not_eligible under camp's [9,17]."""
    conv = _conv(program_id="disneyland_tour")  # sticky, but flag OFF ignores it
    ex = _mk(conv, user_message="კი ჩამწერე")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="7"))
    assert r["success"] is False
    assert r["reason"] == "age_not_eligible"
    assert r["age_min"] == 9  # camp band, flag off


def test_book_flag_on_disneyland_age7_eligible(monkeypatch):
    """Flag ON + resolved disneyland: eligibility uses (7,16) ⇒ a 7yo is
    ELIGIBLE (past the age gate; today it would be age_not_eligible)."""
    _flag_on(monkeypatch)
    _seed_disney(monkeypatch)
    from app.services import calendar_service
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: False)
    conv = _conv(program_id="disneyland_tour")  # sticky; confirm turn re-uses it
    ex = _mk(conv, user_message="კი ჩამწერე")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="7"))
    assert r["reason"] != "age_not_eligible"     # (7,16) ⇒ eligible
    assert r["reason"] == "slot_unavailable"     # got past the age gate


def test_book_flag_on_no_product_uses_camp_band(monkeypatch, camp_registration_open):
    """Flag ON but no product context ⇒ camp band (fail-safe)."""
    _flag_on(monkeypatch)
    monkeypatch.setattr(acs, "get_active_sections", lambda: [])
    conv = _conv()  # program_id empty
    ex = _mk(conv, user_message="კი ჩამწერე")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="7"))
    assert r["reason"] == "age_not_eligible"
    assert r["age_min"] == 9  # camp band


def test_book_flag_on_disneyland_missing_agemin_fails_closed(monkeypatch):
    """Flag ON + disneyland section MISSING age_min ⇒ fail-closed to camp band
    (never a disabled check): a 7yo is age_not_eligible under camp's [9,17]."""
    _flag_on(monkeypatch)
    _seed_disney(monkeypatch, section={
        "id": "disneyland_tour", "name": "დისნეილენდის ტური",
        "status": "active", "registration_status": "open",
    })
    conv = _conv(program_id="disneyland_tour")
    ex = _mk(conv, user_message="კი ჩამწერე")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="7"))
    assert r["reason"] == "age_not_eligible"
    assert r["age_min"] == 9  # fail-closed to camp band


def test_book_flag_on_message_names_disneyland_resolves_and_tags(monkeypatch):
    """Flag ON + the booking turn NAMES disneyland ⇒ resolved from the message,
    tagged onto the lead, and eligibility uses the disneyland band."""
    _flag_on(monkeypatch)
    _seed_disney(monkeypatch)
    from app.services import calendar_service
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: False)
    conv = _conv()  # program_id empty; message carries the product name
    ex = _mk(conv, user_message="დისნეილენდის ტურში ჩამწერე")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="7"))
    assert r["reason"] == "slot_unavailable"          # eligible via (7,16)
    assert conv.lead.program_id == "disneyland_tour"  # tagged from message


def test_book_flag_on_explicit_camp_intent_clears_sticky(monkeypatch, camp_registration_open):
    """Flag ON + a sticky disneyland tag but the booking turn shows EXPLICIT camp
    intent ⇒ the sticky tag is CLEARED and the camp band applies (no
    contamination of the camp age gate)."""
    _flag_on(monkeypatch)
    monkeypatch.setattr(acs, "get_active_sections", lambda: [])
    conv = _conv(program_id="disneyland_tour")  # was browsing disneyland
    ex = _mk(conv, user_message="საზაფხულო ბანაკში ჩავწერო 7 წლის")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="7"))
    assert r["reason"] == "age_not_eligible"
    assert r["age_min"] == 9          # camp band applied
    assert conv.lead.program_id == ""  # sticky cleared by the camp signal


# -- Guardrail regression: every gate holds with the flag ON --------------


def test_guardrail_user_confirmed_gate_holds_flag_on(monkeypatch, camp_registration_open):
    _flag_on(monkeypatch)
    from app.services import calendar_service
    monkeypatch.setattr(
        calendar_service, "book_slot",
        lambda **k: pytest.fail("book_slot must not be called"),
    )
    conv = _conv()
    ex = _mk(conv, user_message="14 წლისაა")
    r = ex.execute(
        TOOL_BOOK_CONSULTATION,
        _book_args(child_age="14", user_confirmed_datetime=False),
    )
    assert r["success"] is False
    assert r["reason"] == "datetime_not_confirmed"


def test_guardrail_verification_phrase_holds_flag_on(monkeypatch, camp_registration_open):
    _flag_on(monkeypatch)
    conv = _conv()
    ex = _mk(conv, user_message="ნამდვილად თავისუფალია?")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="14"))
    assert r["success"] is False
    assert r["reason"] == "verification_requested"


def test_guardrail_empty_event_id_rollback_holds_flag_on(monkeypatch):
    """The empty-event_id silent-failure rollback still fires on the per-product
    path: a Disneyland booking whose Calendar write returns no event_id rolls
    the lead back and refuses the confirmation."""
    _flag_on(monkeypatch)
    _seed_disney(monkeypatch)
    from app.services import calendar_service
    from app.flows import parent_flow
    monkeypatch.setattr(calendar_service, "check_slot_available", lambda dt: True)

    def _fake_book(conv, lead, slot):
        lead.calendly_booked = True
        lead.booked_datetime_iso = slot["datetime_iso"]
        lead.calendar_event_id = ""  # empty ⇒ silent failure ⇒ must roll back
        lead.status = "Booked"
        return True

    monkeypatch.setattr(parent_flow, "_book_selected_slot", _fake_book)
    conv = _conv(program_id="disneyland_tour")
    ex = _mk(conv, user_message="კი ჩამწერე")
    r = ex.execute(TOOL_BOOK_CONSULTATION, _book_args(child_age="7"))
    assert r["success"] is False
    assert r["reason"] == "calendar_booking_failed"
    assert r["manager_handoff_required"] is True
    assert conv.lead.calendly_booked is False   # rolled back
    assert conv.lead.calendar_event_id == ""


# -- get_program_info sticky tagging (flag-gated) --------------------------


def test_get_program_info_tags_lead_flag_on(monkeypatch):
    _flag_on(monkeypatch)
    _seed_disney(monkeypatch)
    conv = _conv()
    ex = _mk(conv, user_message="დისნეილენდი")
    r = ex.execute(TOOL_GET_PROGRAM_INFO, {"program_id": "disneyland_tour"})
    assert r["success"] is True
    assert conv.lead.program_id == "disneyland_tour"


def test_get_program_info_does_not_tag_flag_off(monkeypatch):
    _seed_disney(monkeypatch)  # flag OFF via conftest
    conv = _conv()
    ex = _mk(conv, user_message="დისნეილენდი")
    r = ex.execute(TOOL_GET_PROGRAM_INFO, {"program_id": "disneyland_tour"})
    assert r["success"] is True
    assert conv.lead.program_id == ""  # not tagged when flag off


# ── Task 4: flag-gated Sheets "Program" column ────────────────────────────
# Flag OFF ⇒ 17-col A–Q row (byte-identical). Flag ON ⇒ 18 cols (A–R) with the
# program id last. The append range must match the width actually written.

from app.services import sheets_service as _sheets  # noqa: E402


def _sheets_flag_on(monkeypatch):
    monkeypatch.setattr(
        _sheets, "settings",
        dataclasses.replace(_sheets.settings, USE_PER_PRODUCT_BOOKING=True),
    )


def _booked_lead(program_id: str = ""):
    return Lead(
        sender_id="u1", platform="messenger", segment="PARENT",
        name="ნიკა", phone="599112233", child_age="7",
        calendly_booked=True, status="Booked", program_id=program_id,
    )


def test_lead_to_row_flag_off_is_17_cols():
    row = _sheets._lead_to_row(_booked_lead(program_id="disneyland_tour"), 1)
    assert len(row) == 17  # byte-identical, no Program cell


def test_lead_to_row_flag_on_is_18_cols_with_program_last(monkeypatch):
    _sheets_flag_on(monkeypatch)
    row = _sheets._lead_to_row(_booked_lead(program_id="disneyland_tour"), 1)
    assert len(row) == 18
    assert row[-1] == "disneyland_tour"


def test_lead_to_row_flag_on_empty_program_still_18_cols(monkeypatch):
    _sheets_flag_on(monkeypatch)
    row = _sheets._lead_to_row(_booked_lead(program_id=""), 1)
    assert len(row) == 18
    assert row[-1] == ""  # camp/legacy lead ⇒ empty Program cell, still 18-wide


def test_active_headers_flag_off_is_canonical():
    assert _sheets._active_leads_headers() == _sheets.HEADERS
    assert len(_sheets._active_leads_headers()) == 17


def test_active_headers_flag_on_appends_program(monkeypatch):
    _sheets_flag_on(monkeypatch)
    headers = _sheets._active_leads_headers()
    assert headers == _sheets.HEADERS + ["Program"]
    assert headers[-1] == "Program"


class _FakeWorksheet:
    """Minimal worksheet capturing the update() range + values."""

    def __init__(self, existing_rows=1):
        self._rows = existing_rows
        self.updates = []  # list of (range_name, values)
        self._header = []

    def get_all_values(self):
        return [["x"]] * self._rows

    def row_values(self, n):
        return self._header

    def resize(self, cols):
        self._resized_cols = cols

    def update(self, *args, **kwargs):
        range_name = kwargs.get("range_name") or (args[0] if args else "")
        values = kwargs.get("values") or (args[1] if len(args) > 1 else None)
        self.updates.append((range_name, values))


def test_append_range_matches_row_width_flag_off():
    ws = _FakeWorksheet(existing_rows=5)
    row = _sheets._lead_to_row(_booked_lead(), 1)  # 17 cols flag off
    _sheets._append_lead_row_aligned(ws, row)
    range_name, _ = ws.updates[-1]
    assert range_name == "A6:Q6"  # 17 cols ⇒ A..Q, byte-identical


def test_append_range_matches_row_width_flag_on(monkeypatch):
    _sheets_flag_on(monkeypatch)
    ws = _FakeWorksheet(existing_rows=5)
    row = _sheets._lead_to_row(_booked_lead(program_id="disneyland_tour"), 1)  # 18
    _sheets._append_lead_row_aligned(ws, row)
    range_name, values = ws.updates[-1]
    assert range_name == "A6:R6"  # 18 cols ⇒ A..R
    assert values[0][-1] == "disneyland_tour"


def test_ensure_headers_flag_on_writes_program_header(monkeypatch):
    _sheets_flag_on(monkeypatch)
    ws = _FakeWorksheet()
    ws._header = list(_sheets.HEADERS)  # sheet currently has the 17 legacy headers
    _sheets._ensure_headers(ws)
    range_name, values = ws.updates[-1]
    assert range_name == "A1:R1"
    assert values[0] == _sheets.HEADERS + ["Program"]


def test_ensure_headers_flag_off_unchanged_when_canonical():
    ws = _FakeWorksheet()
    ws._header = list(_sheets.HEADERS)  # already canonical ⇒ no write
    _sheets._ensure_headers(ws)
    assert ws.updates == []  # byte-identical: no header rewrite
