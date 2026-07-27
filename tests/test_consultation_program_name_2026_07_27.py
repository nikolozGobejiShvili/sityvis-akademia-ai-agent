"""Live test #6 (2026-07-27): each consultation records ITS program's name in the CRM.

The Leads sheet already appends a row per booking (no overwrite), but the flag-gated
„Program" column stored the internal `program_id` (empty for reserved camp/Sunday-School).
Operator: „whichever program's consultation is requested, that name should be written." On
(USE_CONSULTATION_PROGRAM_NAME) the booking resolves the NAME of the program the consultation
was requested for — the tagged dynamic product, else the program the conversation is about
(dynamic name / Sunday School / camp) — and writes it to the column. OFF ⇒ program_id (unchanged).
"""
import dataclasses
from unittest.mock import patch

from app import config
from app.flows import parent_flow as pf
from app.services import admin_config_service as acs, sheets_service
from app.models.conversation import Conversation
from app.models.lead import Lead

_SECS = [
    {"id": "summer_camp", "name": "ბანაკი", "status": "active", "type": "camp"},
    {"id": "sunday_school", "name": "საკვირაო სკოლა", "status": "active", "type": "kids_program"},
    {"id": "disneyland_tour", "name": "დისნეილენდი", "status": "active", "type": "other"},
]
_RESERVED = {"summer_camp", "sunday_school", "adult_events"}


def _sec(pid):
    return next((s for s in _SECS if s["id"] == pid), None)


def _resolve(program_id, user_msgs):
    c = Conversation(sender_id="s", platform="facebook")
    c.lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    c.lead.program_id = program_id
    c.history = [{"role": "user", "content": m} for m in user_msgs]
    with patch.object(pf, "settings", dataclasses.replace(config.settings, USE_FUZZY_PROGRAM_MATCH=True)), \
            patch.object(acs, "get_section", side_effect=_sec), \
            patch.object(acs, "get_active_sections", return_value=_SECS), \
            patch.object(pf, "reserved_program_ids", return_value=_RESERVED):
        return pf._resolve_consultation_program_name(c, c.lead)


# --- resolver: the program the consultation was requested for, by name ---

def test_resolve_dynamic_product_from_tag():
    assert _resolve("disneyland_tour", ["დისნეილენდის ფასი"]) == "დისნეილენდი"


def test_resolve_sunday_school_from_context():
    # reserved → not tagged; resolved from the recent conversation
    assert _resolve("", ["საკვირაო სკოლის ფასი მაინტერესებს", "კი ჩამწერეთ"]) == "საკვირაო სკოლა"


def test_resolve_camp_from_context():
    assert _resolve("", ["ბანაკის ფასი რა არის"]) == "ბანაკი"


def test_resolve_none_when_no_program():
    assert _resolve("", ["გამარჯობა"]) == ""


# --- the CRM „Program" column ---

def _program_cell(flag, program_id, consultation_name):
    lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    lead.program_id = program_id
    lead.consultation_program_name = consultation_name
    with patch.object(sheets_service, "settings", dataclasses.replace(
            config.settings, USE_PER_PRODUCT_BOOKING=True, USE_CONSULTATION_PROGRAM_NAME=flag)):
        return sheets_service._lead_to_row(lead, 1)[-1]


def test_column_off_is_program_id_byte_identical():
    assert _program_cell(False, "disneyland_tour", "დისნეილენდი") == "disneyland_tour"


def test_column_on_writes_the_name():
    assert _program_cell(True, "disneyland_tour", "დისნეილენდი") == "დისნეილენდი"


def test_column_on_falls_back_to_id_when_name_absent():
    assert _program_cell(True, "disneyland_tour", "") == "disneyland_tour"


def test_lead_roundtrips_consultation_program_name():
    lead = Lead(sender_id="s", platform="facebook", segment="PARENT")
    lead.consultation_program_name = "საკვირაო სკოლა"
    restored = Lead.from_dict(lead.model_dump(mode="json"))
    assert restored.consultation_program_name == "საკვირაო სკოლა"
