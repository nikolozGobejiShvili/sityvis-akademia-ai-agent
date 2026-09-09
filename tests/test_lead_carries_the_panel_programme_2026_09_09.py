"""A contact was handed to the manager under the wrong programme (2026-09-09).

The contact-handoff flow takes a name and number for any programme that has no
booking of its own, and named Sunday School unconditionally. Measured through
the real flow with every camp switched off:

    „ბანაკი მაინტერესებს"  → the camp-off answer, which now asks for a contact
    „ნიკა 599123456"       → „ინფორმაცია გადავეცი მენეჯერს"
    dispatched             → notify_sunday_school_handoff, logged as a
                             Sunday-School lead

The manager was reached, so nothing the agent said was untrue — but the record
said the wrong programme, and asking for the contact outright means more of
these records, not fewer.

Both the mail and the CRM column now take the name the OPERATOR gave the
programme in the panel, resolved by the one function that already answers
„which programme is this turn about" for routing. The name on the record and
the programme that answered therefore cannot disagree.
"""
import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow as pf
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import notification_service as ns

_CAMP = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
         "status": "ended", "hashtags": ["ბანაკი"],
         "description_short": "ბანაკი."}
_SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა",
           "type": "kids_program", "status": "active",
           "description_short": "საკვირაო სკოლა."}
_PARIS = {"id": "disneyland", "name": "პარიზის ბანაკი", "type": "kids_program",
          "status": "active", "description_short": "პარიზის ბანაკი."}


@pytest.fixture
def panel(monkeypatch):
    def _install(sections):
        active = [s for s in sections if s.get("status") == "active"]
        monkeypatch.setattr(
            "app.services.admin_config_service.get_active_sections",
            lambda: [dict(s) for s in active])
        monkeypatch.setattr("app.services.admin_config_service.get_section",
                            lambda pid: next((dict(s) for s in sections
                                              if s["id"] == pid), None))
        monkeypatch.setattr(pf, "settings", dataclasses.replace(
            config_module.settings, USE_CONSULTATION_PROGRAM_NAME=True,
            USE_DYNAMIC_PROGRAMS=True, USE_RESERVED_PROGRAMS_DYNAMIC=True))
    return _install


def _named(history=(), program_id=""):
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.history = [{"role": "user", "content": h} for h in history]
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.program_id = program_id
    return pf._resolve_consultation_program_name(conv, lead)


# ── the name on the record ─────────────────────────────────────────────────

def test_a_camp_enquiry_is_recorded_as_the_camp(panel):
    """The defect: this returned "" for a camp, so the handoff fell back to
    naming Sunday School."""
    panel([_CAMP, _SCHOOL])
    assert _named(history=["ბანაკი მაინტერესებს"]) == "საზაფხულო ბანაკი"


def test_a_generic_word_names_the_camp_that_is_running(panel):
    panel([dict(_CAMP, status="ended"), _SCHOOL, _PARIS])
    assert _named(history=["ბანაკი მაინტერესებს"]) == "პარიზის ბანაკი"


def test_a_reserved_programme_the_lead_is_tagged_to_is_still_named(panel):
    """Naming is not routing: a reserved programme keeps its curated flow and
    still has to appear on the record. The exclusion here wrote "" instead."""
    panel([_CAMP, _SCHOOL])
    assert _named(program_id="summer_camp") == "საზაფხულო ბანაკი"
    assert _named(program_id="sunday_school") == "საკვირაო სკოლა"


def test_the_name_is_the_operators(panel):
    """Rename it in the panel and the record renames with it."""
    panel([dict(_CAMP, name="ზაფხულის ბანაკი 2027"), _SCHOOL])
    assert _named(history=["ბანაკი მაინტერესებს"]) == "ზაფხულის ბანაკი 2027"


def test_sunday_school_is_unchanged(panel):
    panel([_CAMP, _SCHOOL])
    assert _named(history=["საკვირაო სკოლა მაინტერესებს"]) == "საკვირაო სკოლა"


def test_nothing_named_stays_empty(panel):
    panel([_CAMP, _SCHOOL])
    assert _named(history=["გამარჯობა"]) == ""


# ── what the manager is told ───────────────────────────────────────────────

def _mail(monkeypatch, program_id, sections=(_CAMP, _SCHOOL, _PARIS)):
    """The programme travels on the LEAD, so no caller signature changed and
    every existing stub of this notifier keeps working."""
    sent = {}
    monkeypatch.setattr("app.services.admin_config_service.get_section",
                        lambda pid: next((dict(s) for s in sections
                                          if s["id"] == pid), None))
    monkeypatch.setattr(ns, "_send_email",
                        lambda subject, body: (sent.update(
                            subject=subject, body=body), True)[1])
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name, lead.phone = "ნიკა", "599123456"
    lead.program_id = program_id
    assert ns.notify_sunday_school_handoff(lead) is True
    return sent


def test_the_mail_names_the_programme_asked_about(monkeypatch):
    sent = _mail(monkeypatch, "summer_camp")
    assert "საზაფხულო ბანაკი" in sent["subject"]
    assert "საზაფხულო ბანაკი" in sent["body"]
    assert "sunday_school" not in sent["body"]


def test_the_mail_still_carries_the_contact(monkeypatch):
    sent = _mail(monkeypatch, "disneyland")
    assert "ნიკა" in sent["body"] and "599123456" in sent["body"]


def test_no_name_keeps_the_wording_the_mail_always_had(monkeypatch):
    """A resolution failure must not change what the manager is used to."""
    sent = _mail(monkeypatch, "")
    assert "საკვირაო სკოლა" in sent["subject"]
    assert "sunday_school" in sent["body"]


def test_the_dispatch_result_is_still_the_real_one(monkeypatch):
    """„გადავეცი" is only said on a true send — that contract is untouched."""
    monkeypatch.setattr(ns, "_send_email", lambda subject, body: False)
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    assert ns.notify_sunday_school_handoff(lead) is False
