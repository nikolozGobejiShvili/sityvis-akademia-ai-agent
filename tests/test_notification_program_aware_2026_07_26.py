"""BUG-3 fix (2026-07-26 live test): the manager email named the WRONG program —
always „ბანაკით" even for a Disneyland (per-product) booking. `_program_interest_phrase`
now names the REAL program from ``lead.program_id`` when USE_PER_PRODUCT_BOOKING is on.
Flag OFF OR no program_id → „ბანაკით" (byte-identical). Reuses the existing flag — no new flag.
"""
import dataclasses

from app import config
from app.models.lead import Lead
from app.services import admin_config_service
from app.services import notification_service as ns


def _lead(**kw):
    d = dict(sender_id="s", platform="facebook", segment="PARENT")
    d.update(kw)
    return Lead(**d)


def _pin(monkeypatch, flag, section=None):
    monkeypatch.setattr(
        ns, "settings",
        dataclasses.replace(config.settings, USE_PER_PRODUCT_BOOKING=flag),
    )
    monkeypatch.setattr(admin_config_service, "get_section", lambda pid: section)


def test_phrase_camp_default_when_no_program(monkeypatch):
    _pin(monkeypatch, True)
    assert ns._program_interest_phrase(_lead()) == "ბანაკით"


def test_phrase_camp_default_when_flag_off(monkeypatch):
    _pin(monkeypatch, False, section={"name": "დისნეილენდი"})
    assert ns._program_interest_phrase(_lead(program_id="disneyland_tour")) == "ბანაკით"


def test_phrase_names_program_when_flag_on(monkeypatch):
    _pin(monkeypatch, True, section={"name": "დისნეილენდი"})
    out = ns._program_interest_phrase(_lead(program_id="disneyland_tour"))
    assert "დისნეილენდი" in out
    assert "ბანაკ" not in out


def test_phrase_failsafe_camp_when_section_missing(monkeypatch):
    _pin(monkeypatch, True, section=None)
    assert ns._program_interest_phrase(_lead(program_id="ghost")) == "ბანაკით"


def test_summary_names_program_when_on(monkeypatch):
    _pin(monkeypatch, True, section={"name": "დისნეილენდი"})
    lead = _lead(program_id="disneyland_tour", calendly_booked=True,
                 booked_datetime_iso="2030-07-27T17:00:00")
    summary = ns._build_parent_summary(lead)
    assert "დისნეილენდი" in summary
    assert "ბანაკით" not in summary


def test_summary_camp_byte_identical_when_off(monkeypatch):
    _pin(monkeypatch, False, section={"name": "დისნეილენდი"})
    lead = _lead(program_id="disneyland_tour", calendly_booked=True,
                 booked_datetime_iso="2030-07-27T17:00:00")
    assert "ბანაკით" in ns._build_parent_summary(lead)
