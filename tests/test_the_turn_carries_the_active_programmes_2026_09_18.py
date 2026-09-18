"""Live regression, client Page 2026-09-18 08:46 — a payment question was
answered with the camp, by the MODEL this time.

  08:46:50  „თანხას წინასწარ ვიხდით?"
  08:47:03  „საბანაკო პროგრამა 2026 უკვე დასრულებულია და ახალი მიღება ჯერ არ
             გახსნილა. … 📞 558 67 47 33 … მომდევნო ბანაკის შესახებ …"

The deterministic gate shipped that morning did stand down (the reply is free
prose, not the approved camp-status text), so the turn reached the engine — and
the engine answered from the camp anyway. Measured on the captured model input
for that exact message, with the camp ended and Sunday School the only active
programme:

  system prompt      55 744 chars — „ბანაკ" ×51, „საკვირაო" ×1, „2150" ×4
  SYSTEM DATA block  camp_status=ended, camp_intake_list=…, manager_phone=
                     558 67 47 33  (the CAMP's number)
  active programmes  ABSENT

So the model was told what is closed and never told what is open. It answered
with the only programme it had.

The fix supplies the missing fact, panel-driven: the programmes on sale travel
with the turn, and when exactly one is on sale its own manager number is the one
handed over. No wording rule, no forbidden phrase.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.agent.llm import parent_llm_engine as ple
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service

SCHOOL = {
    "id": "sunday_school", "name": "საკვირაო სკოლა", "type": "sunday_school",
    "status": "active", "manager_contact": "599 00 11 20",
}
EVENTS = {
    "id": "adult_events", "name": "ზრდასრულთა ღონისძიებები",
    "type": "adult_events", "status": "active", "manager_contact": "577 10 10 10",
}
CAMP_PHONE = "558 67 47 33"
PAYMENT_QUESTION = "თანხას წინასწარ ვიხდით?"


@pytest.fixture
def camp_ended_school_on_sale(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [dict(SCHOOL)])
    monkeypatch.setattr(
        admin_config_service, "get_manager_phone",
        lambda program_id=None: (
            SCHOOL["manager_contact"] if program_id == "sunday_school" else CAMP_PHONE
        ),
    )
    monkeypatch.setattr(
        ple, "settings",
        dataclasses.replace(config_module.settings, USE_DYNAMIC_PROGRAMS=True),
    )


def _context(message: str) -> str:
    conv = Conversation(sender_id="ctx", platform="messenger")
    lead = Lead(sender_id="ctx", platform="messenger", segment="PARENT")
    conv.lead = lead
    return ple._build_context_message(conv, lead, message)


def test_the_turn_carries_the_programme_that_is_on_sale(camp_ended_school_on_sale):
    context = _context(PAYMENT_QUESTION)
    assert "საკვირაო სკოლა" in context, (
        "the model was told what is closed and never what is open: " + context[:400]
    )


def test_a_sole_programme_hands_over_its_own_manager_number(camp_ended_school_on_sale):
    context = _context(PAYMENT_QUESTION)
    assert "599 00 11 20" in context, (
        "one programme on sale, so its own number is the one to hand over"
    )
    assert CAMP_PHONE not in context, (
        "the closed camp's number was handed over for the programme on sale"
    )


def test_two_programmes_on_sale_are_both_named(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda *a, **k: [dict(SCHOOL), dict(EVENTS)])
    monkeypatch.setattr(
        ple, "settings",
        dataclasses.replace(config_module.settings, USE_DYNAMIC_PROGRAMS=True),
    )
    context = _context(PAYMENT_QUESTION)
    assert "საკვირაო სკოლა" in context
    assert "ზრდასრულთა ღონისძიებები" in context


def test_the_camp_status_fact_is_still_carried(camp_ended_school_on_sale):
    """The camp being over is true and useful — it must not be dropped."""
    assert "camp_status=ended" in _context(PAYMENT_QUESTION)
