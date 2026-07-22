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
