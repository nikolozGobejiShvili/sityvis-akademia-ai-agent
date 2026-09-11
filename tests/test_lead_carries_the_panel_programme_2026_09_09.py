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


# ── the mail and the CRM must not disagree (live 2026-09-11) ───────────────


def test_the_mail_names_the_programme_the_crm_recorded(monkeypatch):
    """Live: a camp enquiry with every camp OFF left a name and number and the
    mail named Sunday School, while the Sheet row named the camp. The mail read
    `program_id` — empty, because `_program_id_for_turn` answers "" when no
    ACTIVE programme does — and the Sheet read the resolved name."""
    sent = {}
    monkeypatch.setattr(ns, "_send_email",
                        lambda subject, body: (sent.update(
                            subject=subject, body=body), True)[1])
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name, lead.phone = "ნიკა", "599123456"
    lead.program_id = ""                                  # the live shape
    lead.consultation_program_name = "საზაფხულო ბანაკი"   # what the CRM recorded
    assert ns.notify_sunday_school_handoff(lead) is True
    assert "საზაფხულო ბანაკი" in sent["subject"]
    assert "საზაფხულო ბანაკი" in sent["body"]


def test_the_booking_summary_names_the_programme():
    """A consultation booking reached the manager naming no programme at all."""
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.consultation_program_name = "საკვირაო სკოლა"
    assert "საკვირაო სკოლა" in ns._program_interest_phrase(lead)


def test_nothing_resolved_keeps_the_wording_the_manager_knows():
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    assert ns._program_interest_phrase(lead) == "ბანაკით"


# ── the mail the manager actually receives (live 2026-09-11) ───────────────
#
# The fix above resolved the name, but the HANDOFF path asked a different
# question: it set `program_id` from `_program_id_for_turn`, which answers only
# for an ACTIVE programme. With every camp off that is "", so the mail named
# Sunday School a second time while the Sheet row was right. Both now ask the
# one resolver.


def _dispatch(monkeypatch, history, text):
    """Run the real handoff and return (lead, captured mail)."""
    sent = {}
    monkeypatch.setattr(ns, "_send_email",
                        lambda subject, body: (sent.update(
                            subject=subject, body=body), True)[1])
    monkeypatch.setattr(ns, "settings", dataclasses.replace(
        config_module.settings, USE_PER_PRODUCT_BOOKING=True))
    monkeypatch.setattr("app.services.sheets_service.log_sunday_school_lead",
                        lambda *a, **k: True)
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.history = [{"role": "user", "content": h} for h in history]
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name, lead.phone = "ნიკა", "599123456"
    pf._sunday_school_dispatch(conv, lead, text)
    return lead, sent


def test_the_camp_handoff_mail_names_the_camp(panel, monkeypatch):
    """The live defect: camp enquiry, every camp off, contact left → the mail
    said the parent was interested in Sunday School."""
    panel([_CAMP, _SCHOOL])
    lead, sent = _dispatch(monkeypatch, ["ბანაკი მაინტერესებს"], "ნიკა 599123456")
    assert lead.consultation_program_name == "საზაფხულო ბანაკი"
    assert "საზაფხულო ბანაკი" in sent["subject"]
    assert "საზაფხულო ბანაკი" in sent["body"]
    assert "საკვირაო სკოლა" not in sent["body"]


def test_a_sunday_school_handoff_still_names_sunday_school(panel, monkeypatch):
    panel([_CAMP, _SCHOOL])
    lead, sent = _dispatch(monkeypatch, ["საკვირაო სკოლა მაინტერესებს"],
                           "ნიკა 599123456")
    assert lead.consultation_program_name == "საკვირაო სკოლა"
    assert "საკვირაო სკოლა" in sent["body"]


def test_the_turn_that_has_not_reached_history_yet_still_counts(panel, monkeypatch):
    """The contact turn is the one carrying the programme in a one-message
    enquiry; the resolver reads `extra_text` so it is not missed."""
    panel([_CAMP, _SCHOOL])
    lead, _ = _dispatch(monkeypatch, [], "ბანაკი მაინტერესებს ნიკა 599123456")
    assert lead.consultation_program_name == "საზაფხულო ბანაკი"


def test_an_already_resolved_name_is_not_overwritten(panel, monkeypatch):
    """A programme the flow already established outranks a late re-read."""
    panel([_CAMP, _SCHOOL])
    sent = {}
    monkeypatch.setattr(ns, "_send_email",
                        lambda subject, body: (sent.update(body=body), True)[1])
    monkeypatch.setattr("app.services.sheets_service.log_sunday_school_lead",
                        lambda *a, **k: True)
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.history = [{"role": "user", "content": "ბანაკი მაინტერესებს"}]
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name, lead.phone = "ნიკა", "599123456"
    lead.consultation_program_name = "პარიზის ბანაკი"
    pf._sunday_school_dispatch(conv, lead, "ნიკა 599123456")
    assert lead.consultation_program_name == "პარიზის ბანაკი"


def test_a_handoff_mail_says_nothing_about_a_consultation(monkeypatch):
    """Operator rule 2026-09-11: a consultation happens on an ACTIVE programme.
    On this path the manager just gets a name, a number and the programme — the
    headline used to add „(კონსულტაცია არ დაჯავშნილა)", which is the one thing
    that path is never about."""
    sent = {}
    monkeypatch.setattr(ns, "_send_email",
                        lambda subject, body: (sent.update(
                            subject=subject, body=body), True)[1])
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name, lead.phone = "ნიკა", "599123456"
    lead.consultation_program_name = "საზაფხულო ბანაკი"
    assert ns.notify_sunday_school_handoff(lead) is True
    assert "კონსულტაცი" not in sent["subject"]
    assert "კონსულტაცი" not in sent["body"]
    for expected in ("ნიკა", "599123456", "საზაფხულო ბანაკი"):
        assert expected in sent["body"]


def test_the_same_holds_when_no_programme_resolves(monkeypatch):
    sent = {}
    monkeypatch.setattr(ns, "_send_email",
                        lambda subject, body: (sent.update(
                            subject=subject, body=body), True)[1])
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name, lead.phone = "ნიკა", "599123456"
    assert ns.notify_sunday_school_handoff(lead) is True
    assert "კონსულტაცი" not in sent["body"]
