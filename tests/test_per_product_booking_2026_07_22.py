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
