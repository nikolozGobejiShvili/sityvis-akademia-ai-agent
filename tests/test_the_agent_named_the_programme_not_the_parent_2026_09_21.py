"""The shape the operator says real traffic actually has (2026-09-21):

    „a parent does not leave a number out of the blue. They leave it when the
     agent asks — and the agent asks after it has given information about a
     specific programme: the price, the location, the schedule."

So the programme IS established before the contact arrives — but it is the
AGENT that named it, not the parent. `_resolve_consultation_program_name` reads
the PARENT's words, so in this shape it resolves nothing:

    parent : „ფასი რა არის?"                     <- names no programme
    agent  : „პარიზის ბანაკის ღირებულებაა 4500…" <- names it
    agent  : „…leave your number…"
    parent : „593535551 ნანა"

Measured with Paris as the only programme on sale, the hand-off mail read
„საკვირაო სკოლა" — the literal `notify_sunday_school_handoff` falls back to.
The model's own hand-off tool got this right on the same panel, because
`_program_interest_phrase` already applies the sole-programme rule; this
deterministic path did not.

The fix is that same rule, applied where the lead is tagged rather than in the
notifier: the sole programme on sale owns an unattributed lead. Two or more and
it stays empty so the mail names none. Sunday School alone stays empty too, so
that mail is byte-identical to what the manager has always received — which is
what `test_lead_carries_the_panel_programme_2026_09_09` and
`test_external_email_side_effect_safety_2026_07_16` pin, and both still pass.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.services import admin_config_service
from app.services import notification_service as ns
from app.services import sheets_service

PARIS = {"id": "paris_camp", "name": "პარიზის ბანაკი", "type": "camp",
         "status": "active", "age_min": 10, "age_max": 17,
         "price_text": "4500 ლარი", "hashtags": ["parisi", "პარიზი", "paris"],
         "manager_contact": "599 11 22 33"}
ROBOTICS = {"id": "robotics_club", "name": "რობოტიკის სკოლა",
            "type": "kids_program", "status": "active",
            "age_min": 9, "age_max": 16, "price_text": "780 ლარი",
            "manager_contact": "577 44 55 66"}
SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17,
          "price_text": "595 ლარი", "manager_contact": "599 00 11 20"}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended"}


@pytest.fixture
def mails(monkeypatch):
    sent: list[dict] = []
    monkeypatch.setattr(
        ns, "_send_email",
        lambda subject, body, **k: (
            sent.append({"subject": subject, "body": body}) or True))
    monkeypatch.setattr(ns, "_send_manager_whatsapp", lambda *a, **k: False)
    monkeypatch.setattr(
        sheets_service, "log_sunday_school_lead", lambda *a, **k: True)
    parent_flow._sunday_school_notified_senders.clear()
    return sent


def _panel(monkeypatch, sections):
    active = [s for s in sections if s.get("status") == "active"]
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: list(active))
    monkeypatch.setattr(
        admin_config_service, "load_sections", lambda *a, **k: list(sections))
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda pid, *a, **k: next(
            (dict(s) for s in sections if s.get("id") == pid), {}))
    monkeypatch.setattr(
        admin_config_service, "is_camp_registration_open", lambda *a, **k: False)
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    settings = dataclasses.replace(
        config_module.settings,
        USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True,
        USE_PARENT_LLM_ENGINE=True, USE_DYNAMIC_WELCOME=True,
        USE_RESERVED_PROGRAMS_DYNAMIC=True, USE_PER_PRODUCT_BOOKING=True,
        USE_CONSULTATION_PROGRAM_NAME=True,
    )
    monkeypatch.setattr(parent_flow, "settings", settings)
    monkeypatch.setattr(ns, "settings", settings)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely", lambda c, m: "[ENGINE]")


def _conversation(agent_answer: str) -> Conversation:
    """The parent asked a generic question; the AGENT named the programme, then
    invited the contact. Nothing the parent typed names anything."""
    conv = Conversation(sender_id="agentnamed", platform="messenger")
    conv.segment = "PARENT"
    conv.state = "DONE"
    conv.history = [
        {"role": "user", "content": "ფასი რა არის?"},
        {"role": "assistant", "content": agent_answer},
        {"role": "user", "content": "მენეჯერთან დამაკავშირეთ"},
        {"role": "assistant",
         "content": parent_flow._render_manager_number_answer(None)},
    ]
    return conv


# --------------------------------------------------------------------------
# The live shape.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("section", [PARIS, ROBOTICS])
def test_the_sole_programme_on_sale_is_named_even_if_only_the_agent_said_it(
        monkeypatch, mails, section):
    _panel(monkeypatch, [CAMP_OFF, section])
    conv = _conversation(f"{section['name']}ის ღირებულებაა {section['price_text']}")
    parent_flow.handle(conv, "593535551 ნანა")
    assert mails, "the contact never reached the manager"
    assert section["name"] in mails[0]["subject"]
    assert "საკვირაო სკოლა" not in mails[0]["subject"]
    assert "საკვირაო სკოლა" not in mails[0]["body"]


def test_the_contact_still_travels(monkeypatch, mails):
    _panel(monkeypatch, [CAMP_OFF, PARIS])
    conv = _conversation("პარიზის ბანაკის ღირებულებაა 4500 ლარი")
    parent_flow.handle(conv, "593535551 ნანა")
    assert "ნანა" in mails[0]["body"]
    assert "593535551" in mails[0]["body"]


# --------------------------------------------------------------------------
# What must not move.
# --------------------------------------------------------------------------

def test_two_programmes_on_sale_still_name_neither(monkeypatch, mails):
    """With a real choice, guessing is the defect."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    conv = _conversation("ფასები დამოკიდებულია პროგრამაზე")
    parent_flow.handle(conv, "593535551 ნანა")
    assert mails
    assert "პარიზის ბანაკი" not in mails[0]["subject"]


def test_sunday_school_alone_reads_exactly_as_before(monkeypatch, mails):
    """The wording the manager has been receiving since this mail existed."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    conv = _conversation("საკვირაო სკოლის ღირებულებაა 595 ლარი")
    parent_flow.handle(conv, "593535551 ნანა")
    assert mails[0]["subject"] == "საკვირაო სკოლა — ახალი მოთხოვნა — ნანა"
    assert "ტიპი: საკვირაო სკოლა (sunday_school)" in mails[0]["body"]


def test_a_programme_the_parent_named_still_wins(monkeypatch, mails):
    """The resolver is asked first; the panel only fills a gap."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, PARIS])
    conv = Conversation(sender_id="named", platform="messenger")
    conv.segment = "PARENT"
    conv.state = "DONE"
    conv.history = [
        {"role": "user", "content": "პარიზის ბანაკი მაინტერესებს"},
        {"role": "assistant", "content": "პარიზის ბანაკი 10-დღიანია."},
        {"role": "user", "content": "მენეჯერთან დამაკავშირეთ"},
        {"role": "assistant",
         "content": parent_flow._render_manager_number_answer(None)},
    ]
    parent_flow.handle(conv, "593535551 ნანა")
    assert "პარიზის ბანაკი" in mails[0]["subject"]
