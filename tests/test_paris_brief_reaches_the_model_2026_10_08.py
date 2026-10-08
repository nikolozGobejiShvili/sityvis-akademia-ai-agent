"""The whole Paris brief reaches the model (operator's choice B, 2026-10-08).

The brief of 2026-10-08 has a 1 934-character short description and a
7 717-character full description; with the other panel fields the facts block is
10 558 characters. At the old 6000 ceiling the model read only the first 3 139
characters of the full description — flights and luggage, hotel, meals, what is
not included, passport and notary consent, phone rules and the final meeting
never reached it. The ceiling stays a guard against a pasted document.
"""
from __future__ import annotations

from app.agent.llm import parent_llm_engine
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _PARIS,
    _REAL_PARIS,
    _no_network,
    _panel_only,
)
from app.services import admin_config_service as acs

# Same sizes as the brief; the last section's words at the very end.
_SHORT = "მოკლე. " * 276                       # 1 932 characters
_LAST = "სიტყვის აკადემიის საკონტაქტო ნომერი: 599 00 11 20"
_FULL = "აღწერა. " * 958 + _LAST                # ≈ 7 700 characters


def _facts(monkeypatch, short: str, full: str) -> str:
    monkeypatch.setitem(_PARIS, "name", _REAL_PARIS)
    monkeypatch.setitem(_PARIS, "price_text", "€2690 (გადახდა ლარში, კურსით)")
    monkeypatch.setitem(_PARIS, "registration_url", "https://wordacademy.ge/course/hero-journey/")
    monkeypatch.setitem(_PARIS, "description_short", short)
    monkeypatch.setitem(_PARIS, "description_full", full)
    with _panel_only("SS_PARIS"):
        return parent_llm_engine._active_program_facts(acs.get_section("paris_camp"))


def test_a_brief_sized_paris_description_reaches_the_model_to_its_last_line(monkeypatch):
    assert len(_SHORT) > 1900 and len(_FULL) > 7700
    facts = _facts(monkeypatch, _SHORT, _FULL)
    assert facts.endswith(_LAST), facts[-200:]
    assert "https://wordacademy.ge/course/hero-journey/" in facts


def test_a_pasted_document_is_still_cut(monkeypatch):
    facts = _facts(monkeypatch, _SHORT, "აღწერა. " * 3000 + _LAST)
    assert len(facts) == parent_llm_engine._PROGRAM_FACTS_MAX_CHARS
    assert _LAST not in facts
    # what is cut is only the end of the long description
    assert "https://wordacademy.ge/course/hero-journey/" in facts
    assert "€2690" in facts
