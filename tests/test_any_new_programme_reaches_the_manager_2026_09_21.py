"""The operator's question, 2026-09-21: „will every NEW programme I add work
the same way?"

Measured on two programmes invented for this file — `robotics_club` and
`winter_camp`. Neither id, name nor hashtag has a code path anywhere; they exist
only as panel rows, which is exactly how the operator adds one. Nothing in the
code was changed for them, and these tests are what that answer rests on.

Answer: yes, as soon as the conversation is about the programme — which is what
resolves it, and what the manager's mail and the CRM column both read.

ONE EDGE IS NOT COVERED, deliberately. A parent who names no programme at all —
opens with „connect me to the manager" and leaves a number — produces a lead
tagged to nothing, and the hand-off mail then falls back to the literal wording
it has always had („საკვირაო სკოლა"). With a brand-new programme as the only one
on sale that is the wrong name.

Naming it from the panel was tried and reverted: two shipped contracts answer
that exact case with „do not guess" —

    test_lead_carries_the_panel_programme_2026_09_09
        ::test_nothing_named_stays_empty
        ::test_no_name_keeps_the_wording_the_mail_always_had

Both were written when Sunday School was the only non-camp programme, so the
fallback was accidentally right. Changing it is a decision about those contracts,
not a bug fix, so it is left to the operator rather than taken unilaterally.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.models.lead import Lead
from app.services import admin_config_service
from app.services import notification_service as ns

# Invented here; no code branch exists for either.
ROBOTICS = {"id": "robotics_club", "name": "რობოტიკის სკოლა",
            "type": "kids_program", "status": "active",
            "age_min": 9, "age_max": 16}
WINTER = {"id": "winter_camp", "name": "ზამთრის ბანაკი", "type": "camp",
          "status": "active", "age_min": 8, "age_max": 15}
SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended"}


def _lead(**kw) -> Lead:
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name = "ნანა"
    lead.phone = "593535551"
    for k, v in kw.items():
        setattr(lead, k, v)
    return lead


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
        ns, "settings",
        dataclasses.replace(config_module.settings, USE_PER_PRODUCT_BOOKING=True))


def _mail(monkeypatch, lead) -> dict:
    sent: dict[str, str] = {}
    monkeypatch.setattr(
        ns, "_send_email",
        lambda subject, body, **k: (sent.update(subject=subject, body=body) or True))
    ns.notify_sunday_school_handoff(lead)
    return sent


# --------------------------------------------------------------------------
# A programme the code has never heard of, named by the conversation.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("section", [ROBOTICS, WINTER])
def test_a_brand_new_programme_is_named_in_the_mail(monkeypatch, section):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, section])
    sent = _mail(monkeypatch, _lead(consultation_program_name=section["name"]))
    assert section["name"] in sent["subject"]
    assert section["name"] in sent["body"]
    assert "საკვირაო სკოლა" not in sent["subject"]


@pytest.mark.parametrize("section", [ROBOTICS, WINTER])
def test_a_brand_new_programme_tagged_by_id_is_named_too(monkeypatch, section):
    """The other tier: a per-product booking tags the id, the panel supplies
    the operator's own name for it."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, section])
    sent = _mail(monkeypatch, _lead(program_id=section["id"]))
    assert section["name"] in sent["subject"]


def test_renaming_it_in_the_panel_renames_it_on_the_record(monkeypatch):
    renamed = dict(ROBOTICS, name="რობოტიკა და ხელოვნური ინტელექტი")
    _panel(monkeypatch, [CAMP_OFF, SCHOOL, renamed])
    sent = _mail(monkeypatch, _lead(program_id="robotics_club"))
    assert "რობოტიკა და ხელოვნური ინტელექტი" in sent["subject"]


def test_two_new_programmes_do_not_bleed_into_each_other(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, ROBOTICS, WINTER])
    sent = _mail(monkeypatch, _lead(consultation_program_name="ზამთრის ბანაკი"))
    assert "ზამთრის ბანაკი" in sent["subject"]
    assert "რობოტიკის სკოლა" not in sent["subject"]
    assert "საკვირაო სკოლა" not in sent["subject"]


def test_the_contact_still_travels_whatever_the_programme(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, ROBOTICS])
    sent = _mail(monkeypatch, _lead(program_id="robotics_club"))
    assert "ნანა" in sent["body"]
    assert "593535551" in sent["body"]


def test_sunday_school_reads_exactly_as_it_always_has(monkeypatch):
    """The wording the manager has been receiving since this mail existed."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL])
    sent = _mail(monkeypatch, _lead())
    assert sent["subject"] == "საკვირაო სკოლა — ახალი მოთხოვნა — ნანა"
    assert "ტიპი: საკვირაო სკოლა (sunday_school)" in sent["body"]
