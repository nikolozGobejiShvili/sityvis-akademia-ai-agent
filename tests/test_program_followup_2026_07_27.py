"""Per-program follow-up (USE_PROGRAM_FOLLOWUP, 2026-07-27 live test #6).

Follow-up was PARENT-only, camp-copy-hardcoded, and globally gated on the summer_camp
registration flag — so a lead interested in a dynamic program (Disneyland / Formula 1) got
no follow-up. On: a lead tagged to a dynamic product is eligible, the camp-registration gate
applies to camp leads only, and the copy is program-aware (per-section
`auto_followup_template_id` → generic `followup_program_*` with the program NAME → fallback).
The send/skip rules (declined / asked-no-more / manager-handoff / booked) are UNCHANGED.
"""
import dataclasses
from datetime import datetime, timedelta
from types import SimpleNamespace

from app import config
from app.services import followup_service as fs
from app.services import admin_config_service as acs
import app.domain.decision.models as decision_models
from app.models.conversation import Conversation
from app.models.lead import Lead


def _conv(segment, program_id="", *, blocked="", stage="", booked=False):
    c = Conversation(sender_id="u1", platform="messenger")
    c.segment = segment
    c.followup_stage = stage
    c.followup_blocked_reason = blocked
    c.last_bot_message_at = (datetime.utcnow() - timedelta(hours=25)).isoformat()
    lead = Lead(sender_id="u1", platform="messenger", segment=segment)
    lead.name = "ნინო"
    lead.program_id = program_id
    lead.calendly_booked = booked
    c.lead = lead
    return c


def _pin(monkeypatch, flag, *, camp_open=True):
    monkeypatch.setattr(fs, "settings", dataclasses.replace(
        config.settings, USE_PROGRAM_FOLLOWUP=flag))
    monkeypatch.setattr(decision_models, "reserved_program_ids",
                        lambda: {"summer_camp", "sunday_school", "adult_events"})
    monkeypatch.setattr(acs, "get_section",
                        lambda pid: {"name": "დისნეილენდი", "auto_followup_template_id": ""})
    monkeypatch.setattr(acs, "is_camp_registration_open", lambda: camp_open)
    monkeypatch.setattr(fs, "_save_conversation_to_redis", lambda conv: None)
    rec = []
    monkeypatch.setattr(fs, "messenger_service",
                        SimpleNamespace(send_message=lambda **kw: rec.append(kw) or True))
    return rec


# --- eligibility ---

def test_off_is_byte_identical_parent_only(monkeypatch):
    _pin(monkeypatch, False)
    assert fs._followup_program_eligibility(_conv("PARENT"))[0] is True
    # a dynamic-tagged lead is NOT eligible when off (old non_parent_segment gate)
    assert fs._followup_program_eligibility(_conv("UNCLEAR", "disneyland_tour"))[0] is False


def test_on_dynamic_lead_is_eligible_with_name(monkeypatch):
    _pin(monkeypatch, True)
    eligible, name, is_dynamic, _tid = fs._followup_program_eligibility(
        _conv("UNCLEAR", "disneyland_tour"))
    assert eligible and is_dynamic and name == "დისნეილენდი"


def test_on_camp_lead_stays_camp(monkeypatch):
    _pin(monkeypatch, True)
    eligible, name, is_dynamic, _ = fs._followup_program_eligibility(_conv("PARENT"))
    assert eligible and not is_dynamic and name == ""


def test_on_adult_without_program_still_skipped(monkeypatch):
    _pin(monkeypatch, True)
    assert fs._followup_program_eligibility(_conv("ADULT"))[0] is False


# --- the send path ---

def test_dynamic_lead_sent_even_when_camp_registration_closed(monkeypatch):
    rec = _pin(monkeypatch, True, camp_open=False)  # camp closed must NOT block a dynamic lead
    result = fs._maybe_send_followup_for_conversation(
        _conv("UNCLEAR", "disneyland_tour"), fs.now_tbilisi())
    assert result == "sent"
    assert len(rec) == 1
    assert "დისნეილენდი" in rec[0]["text"]      # program-aware copy
    assert "ბანაკის" not in rec[0]["text"]        # not the camp template


def test_camp_lead_still_gated_by_camp_registration(monkeypatch):
    rec = _pin(monkeypatch, True, camp_open=False)
    result = fs._maybe_send_followup_for_conversation(_conv("PARENT"), fs.now_tbilisi())
    assert result == "skipped"                    # camp reg closed → camp lead skipped
    assert rec == []


def test_dynamic_lead_declined_is_blocked(monkeypatch):
    rec = _pin(monkeypatch, True, camp_open=False)
    result = fs._maybe_send_followup_for_conversation(
        _conv("UNCLEAR", "disneyland_tour", blocked="declined"), fs.now_tbilisi())
    assert result == "skipped"                    # decline still blocks
    assert rec == []


def test_off_dynamic_lead_not_sent(monkeypatch):
    rec = _pin(monkeypatch, False, camp_open=True)
    result = fs._maybe_send_followup_for_conversation(
        _conv("UNCLEAR", "disneyland_tour"), fs.now_tbilisi())
    assert result == "skipped"                    # byte-identical: non-PARENT skipped
    assert rec == []
