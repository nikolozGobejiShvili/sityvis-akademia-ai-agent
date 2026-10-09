"""„ზრდასრული" names no programme (2026-10-09).

Live 2026-10-09 10:19 a Paris parent asked „რამდენი ზრდასრული მიყვება
ბავშვებს?" and was told the detail was not available — while the Paris brief
says „25 მონაწილესთან ერთად მოგზაურობს 5 ზრდასრული", and the same chat had
been answered „5 ზრდასრული" fourteen minutes earlier. The word matched the name
of the switched-off „ზრდასრულთა ღონისძიებები", the turn was attributed to that
closed programme, and Paris's facts did not travel with it. „ზრდასრულ" is a
word for who takes part, like „ბავშვ" and „მოზარდ": it alone names nothing.
"""
from __future__ import annotations

from app.agent.llm import parent_llm_engine
from app.reasoning.dynamic_program_match import match_dynamic_program
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _ADULT,
    _PARIS,
    _conversation,
    _no_network,
    _panel_only,
)

_TEAM = "25 მონაწილესთან ერთად მოგზაურობს 5 ზრდასრული."
_ADULT_ON = {"id": "adult_events", "name": "ზრდასრულთა ღონისძიებები",
             "type": "adult_events", "status": "active", "hashtags": []}


def _paris_chat(monkeypatch, adult_status: str, message: str):
    monkeypatch.setitem(_ADULT, "status", adult_status)
    monkeypatch.setitem(_PARIS, "description_full", _TEAM)
    with _panel_only("SS_PARIS"):
        conv = _conversation([
            ("user", "პარიზის ბანაკი მაინტერესებს"),
            ("assistant", "პარიზის ბანაკი 6-დღიანი საგანმანათლებლო ბანაკია."),
        ])
        conv.segment = "PARENT"
        attribution = parent_llm_engine.resolve_programme(conv, message, conv.lead)
        section = parent_llm_engine._active_program_section(conv, message, conv.lead)
        facts = parent_llm_engine._active_program_facts(section) if section else ""
    return attribution, facts


def test_the_word_alone_names_no_programme():
    assert match_dynamic_program("რამდენი ზრდასრული მიყვება ბავშვებს?", [_ADULT_ON]) is None
    assert match_dynamic_program("ზრდასრულებისთვის რამე გაქვთ?", [_ADULT_ON]) is None


def test_the_full_name_still_names_the_section():
    assert match_dynamic_program(
        "ზრდასრულთა ღონისძიებები მაინტერესებს", [_ADULT_ON],
    ) == {"program_id": "adult_events", "type": "adult_events"}


def test_a_paris_question_about_the_adults_keeps_paris_facts(monkeypatch):
    attribution, facts = _paris_chat(
        monkeypatch, "ended", "რამდენი ზრდასრული მიყვება ბავშვებს?")
    assert attribution.state == "open", attribution.state
    assert attribution.program_id == "paris_camp"
    assert _TEAM.rstrip(".") in facts, facts[-300:]


def test_naming_the_switched_off_programme_in_full_is_still_closed(monkeypatch):
    attribution, facts = _paris_chat(
        monkeypatch, "ended", "ზრდასრულთა ღონისძიებები მაინტერესებს")
    assert attribution.state == "closed"
    assert attribution.program_id == "adult_events"
    assert facts == ""
