"""A consultation is booked for the programme the parent asked about (2026-09-11).

Two rules decide whether a consultation may be booked at all — the AGE BAND and
the REGISTRATION GATE. Both were read from the CAMP for any programme with a
curated conversation, because `_resolve_booking_program_id` discarded every
reserved id. Measured against the operator's own panel (camp 9-17, Sunday School
6-12):

    „საკვირაო სკოლაზე კონსულტაცია მინდა"  → band 9-17, camp gate
                                            (its own band is 6-12 and its own
                                             registration was closed)

So a 7-year-old was refused in the camp's words and a 15-year-old accepted for a
programme that stops at 12. `_registration_open_for_booking` carries the same
defect fixed for DYNAMIC products on 2026-07-23 — the reserved programme was
left behind.

`admin_config_service` already reads any programme's section, so the fix is to
stop discarding the id. The camp keeps "" — which IS the camp band and the camp
gate — so nothing about the camp moves.
"""
import dataclasses

import pytest

from app import config as config_module
from app.agent.tools import parent_tool_executor as pte
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service as acs

_CAMP = {"id": "summer_camp", "type": "camp", "status": "ended",
         "name": "საზაფხულო ბანაკი", "hashtags": ["ბანაკი"],
         "age_min": 9, "age_max": 17}
_SCHOOL = {"id": "sunday_school", "type": "kids_program", "status": "active",
           "name": "საკვირაო სკოლა", "age_min": 6, "age_max": 12,
           "registration_status": "closed"}
_PARIS = {"id": "disneyland", "type": "kids_program", "status": "active",
          "name": "პარიზის ბანაკი", "hashtags": ["პარიზი"],
          "age_min": 10, "age_max": 14, "registration_status": "open"}
_ADULT = {"id": "adult_events", "type": "adult_events", "status": "active",
          "name": "ზრდასრულთა ღონისძიებები", "events": []}
_ALL = [_CAMP, _SCHOOL, _PARIS, _ADULT]


@pytest.fixture
def panel(monkeypatch):
    def _install(sections=_ALL):
        monkeypatch.setattr(acs, "load_sections",
                            lambda: [dict(s) for s in sections])
        monkeypatch.setattr(acs, "get_active_sections",
                            lambda: [dict(s) for s in sections
                                     if s.get("status") == "active"])
        monkeypatch.setattr(acs, "get_section",
                            lambda pid: next((dict(s) for s in sections
                                              if s["id"] == pid), None))
        live = dataclasses.replace(config_module.settings,
                                   USE_PER_PRODUCT_BOOKING=True,
                                   USE_DYNAMIC_PROGRAMS=True)
        monkeypatch.setattr(pte, "settings", live, raising=False)
        monkeypatch.setattr(config_module, "settings", live)
    return _install


def _resolve(message, tagged=""):
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.program_id = tagged
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    ex = pte.ParentToolExecutor(conv, lead, "s", "messenger", message)
    return ex._resolve_booking_program_id(), ex


def _band(pid):
    return acs.get_program_age_bounds(pid) if pid else acs.get_camp_age_bounds()


# ── the band ───────────────────────────────────────────────────────────────

def test_a_sunday_school_consultation_uses_the_sunday_school_band(panel):
    """The defect: this read the camp's 9-17."""
    panel()
    pid, _ = _resolve("საკვირაო სკოლაზე კონსულტაცია მინდა")
    assert pid == "sunday_school"
    assert _band(pid) == (6, 12)


def test_a_dynamic_programme_is_unchanged(panel):
    panel()
    pid, _ = _resolve("პარიზის ბანაკზე კონსულტაცია მინდა")
    assert pid == "disneyland"
    assert _band(pid) == (10, 14)


def test_the_camp_still_resolves_to_the_camp_default(panel):
    """"" IS the camp band and the camp gate — camp behaviour must not move."""
    panel()
    pid, _ = _resolve("საზაფხულო ბანაკზე კონსულტაცია მინდა")
    assert pid == ""
    assert _band(pid) == (9, 17)


def test_the_band_is_the_operators(panel):
    """Change it in the panel and the booking guardrail changes with it."""
    panel([_CAMP, dict(_SCHOOL, age_min=8, age_max=10), _PARIS, _ADULT])
    pid, _ = _resolve("საკვირაო სკოლაზე კონსულტაცია მინდა")
    assert _band(pid) == (8, 10)


def test_a_programme_without_its_own_band_falls_back_to_the_camp(panel):
    """Fail-closed: a missing bound must never disable the check."""
    school = {k: v for k, v in _SCHOOL.items()
              if k not in ("age_min", "age_max")}
    panel([_CAMP, school, _PARIS, _ADULT])
    pid, _ = _resolve("საკვირაო სკოლაზე კონსულტაცია მინდა")
    assert pid == "sunday_school"
    assert _band(pid) == (9, 17)


# ── the registration gate ──────────────────────────────────────────────────

def test_the_gate_is_the_programmes_own(panel):
    """Sunday-School registration is closed here while the camp's is open; the
    booking was judged by the camp's."""
    panel()
    _, ex = _resolve("საკვირაო სკოლაზე კონსულტაცია მინდა")
    assert pte._is_camp_registration_open() is True
    assert ex._registration_open_for_booking() is False


def test_an_open_programme_is_bookable_while_the_camp_is_shut(panel):
    """The mirror case, and the 2026-07-23 bug: the camp ending must not shut
    every other programme's consultation."""
    panel([dict(_CAMP, registration_status="closed"),
           dict(_SCHOOL, registration_status="open"), _PARIS, _ADULT])
    _, ex = _resolve("საკვირაო სკოლაზე კონსულტაცია მინდა")
    assert ex._registration_open_for_booking() is True


# ── what must stay out ─────────────────────────────────────────────────────

def test_the_adult_programme_never_becomes_a_booking_programme(panel):
    """The adult flow has no Calendar booking at all."""
    panel()
    pid, _ = _resolve("ზრდასრულთა ღონისძიებები მაინტერესებს", tagged="adult_events")
    assert pid == ""


# ── the tag across the conversation ────────────────────────────────────────

def test_a_bare_confirm_keeps_the_programme_already_established(panel):
    """The booking turn is often „კი" — the programme has to survive it."""
    panel()
    pid, _ = _resolve("კი, ჩამწერეთ", tagged="sunday_school")
    assert pid == "sunday_school"


def test_explicit_camp_intent_clears_a_stale_tag(panel):
    panel()
    pid, _ = _resolve("საზაფხულო ბანაკი მაინტერესებს", tagged="sunday_school")
    assert pid == ""


def test_the_flag_off_is_byte_identical(panel, monkeypatch):
    panel()
    monkeypatch.setattr(pte, "settings", dataclasses.replace(
        config_module.settings, USE_PER_PRODUCT_BOOKING=False), raising=False)
    monkeypatch.setattr(config_module, "settings", dataclasses.replace(
        config_module.settings, USE_PER_PRODUCT_BOOKING=False))
    pid, _ = _resolve("საკვირაო სკოლაზე კონსულტაცია მინდა")
    assert pid == ""


# ── an age never refuses a consultation (operator, 2026-09-11) ─────────────
#
# „ასაკი გამო კონსულტაციაზე ჩანიშვნა არ უნდა იყოს შეზღუდული."
# The band is a fact ABOUT the programme — whether the child can take part —
# not a condition on being allowed to sit down with a manager.


def _book(monkeypatch, message, child_age):
    from app.flows import parent_flow as pf
    from app.services import calendar_service as cal
    monkeypatch.setattr(cal, "check_slot_available", lambda *a, **k: True)

    def _booked(conv, lead, slot, *a, **k):
        lead.calendar_event_id = "evt"
        lead.booked_datetime_iso = str(slot.get("datetime_iso"))
        lead.calendly_booked = True
        return True
    monkeypatch.setattr(pf, "_book_selected_slot", _booked)
    monkeypatch.setattr("app.services.sheets_service.create_lead", lambda *a, **k: True)
    monkeypatch.setattr("app.services.notification_service.notify_manager",
                        lambda *a, **k: True)
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.name, lead.phone = "ნიკა", "599123456"
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.lead = lead  # one lead object: the stub writes what the executor reads
    ex = pte.ParentToolExecutor(conv, lead, "s", "messenger", message)
    return ex._book_consultation({
        "name": "ნიკა", "phone": "599123456",
        "datetime_iso": "2030-06-10T14:00:00+04:00",
        "child_age": child_age, "user_confirmed_datetime": True,
    })


@pytest.mark.parametrize("age", ["4", "7", "8", "15", "18", "19"])
def test_no_age_refuses_a_consultation(panel, monkeypatch, age):
    """Every one of these was `age_not_eligible` outside the band before."""
    panel()
    res = _book(monkeypatch, "საკვირაო სკოლაზე კონსულტაცია მინდა", age)
    assert res.get("reason") != "age_not_eligible"


def test_an_age_outside_the_band_books(panel, monkeypatch):
    """A 4-year-old, on a programme whose band starts at 6, reaches a booked
    slot. Registration has to be open — that gate is a real one and unrelated
    to age."""
    panel([_CAMP, dict(_SCHOOL, registration_status="open"), _PARIS, _ADULT])
    res = _book(monkeypatch, "საკვირაო სკოლაზე კონსულტაცია მინდა", "4")
    assert res.get("success") is True, res


def test_the_offer_is_never_removed_for_an_age(panel):
    """The other half of the restriction: the CTA was stripped, so the parent was
    handed a manager instead of the slot they were about to be offered."""
    from app.flows import parent_flow as pf
    panel()
    lead = Lead(sender_id="s", platform="messenger", segment="PARENT")
    lead.child_age = "4"
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    conv.lead = lead
    reply = "თუ გნებავთ, კონსულტაციაზე ჩაგწერთ."
    assert pf._strip_consultation_cta_if_ineligible(conv, reply) == reply


# ── the gate when the panel says nothing ───────────────────────────────────

def test_a_silent_panel_inherits_the_camp_gate(panel):
    """The regression shipped earlier the same day: a programme with no
    `registration_status` was read as CLOSED, so its consultation stopped being
    bookable although it had the camp's gate the day before."""
    school = {k: v for k, v in _SCHOOL.items() if k != "registration_status"}
    panel([_CAMP, school, _PARIS, _ADULT])
    _, ex = _resolve("საკვირაო სკოლაზე კონსულტაცია მინდა")
    assert pte._is_camp_registration_open() is True
    assert ex._registration_open_for_booking() is True
