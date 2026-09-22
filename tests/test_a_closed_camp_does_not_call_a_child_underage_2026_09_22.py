"""Live regression, client Page 2026-09-22 12:12 — the manager was told a
seven-year-old is below the camp's age band, in a conversation about a
programme that takes children from seven.

The mail, verbatim:

    მენეჯერთან გადასაცემი მოთხოვნა — თეონა
    სახელი: თეონა
    ტელეფონი: 577648731
    მიზეზი: 7 წლის ბავშვი — ასაკი ბანაკის ქვემოთ (9–17 წელი)

The camp was ENDED and Sunday School — 7 to 17 — was the only programme on
sale. The child is eligible. Nothing in that sentence is true of this lead, and
it is the only thing the manager was given about her.

The conversation, from Railway (deployment 461210ba):

    08:05  „577648731 თეონა"            → contact taken
    08:05  „შაბათი"                     → real calendar slots offered
    08:10  „…თერთმეტი საათი ჯობია"      → 11:00 agreed
    08:11  „გადასახდელი თანხა…?"        → answered 595 ლარი, Sunday School's
    08:11  „დიახ შვიდი წლის"            → booking then failed
    08:12  „კარგით,დამოკავშირდნენ"      → manager handoff dispatched

`_maybe_handle_underage_manager_handoff` compares the child's age to the CAMP's
band and hands over as under-age. It has a guard for exactly this — added
2026-09-18 — but every branch of it asks whether the PARENT named another
programme, and she never did. The AGENT named Sunday School: its price, its
schedule, its slots. `_conversation_names_other_program` reads only user turns,
deliberately, so that a wrong answer cannot pin itself in place.

Two of its siblings already stand down on the panel instead of on the
transcript, and both did so in this very conversation — the log shows
„camp-status deferred — the camp is ended, this turn is generic and another
programme is active" and „multi-child age deferred — the camp is closed and
another programme is active" on every one of these turns. This handler is the
third with the same problem and the only one without the guard.

Same three conditions, copied rather than invented: program isolation on, the
camp not running, the conversation never named the camp, another child
programme on sale. A camp that IS running, or a camp alone in the panel, keeps
this handoff exactly as it is — that is what it was written for.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import admin_config_service

SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17,
          "price_text": "595 ლარი", "manager_contact": "599 00 11 20"}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended", "age_min": 9, "age_max": 17}
CAMP_ON = dict(CAMP_OFF, status="active")


def _panel(monkeypatch, sections, camp_status):
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
        admin_config_service, "get_camp_status", lambda *a, **k: camp_status)
    monkeypatch.setattr(
        admin_config_service, "get_camp_age_bounds", lambda *a, **k: (9, 17))
    monkeypatch.setattr(
        parent_flow, "settings",
        dataclasses.replace(
            config_module.settings,
            USE_PROGRAM_ISOLATION=True, USE_DYNAMIC_PROGRAMS=True,
            USE_RESERVED_PROGRAMS_DYNAMIC=True),
    )


def _conversation(child_age: str = "7") -> Conversation:
    """Teona's conversation: the AGENT named the programme, never the parent."""
    conv = Conversation(sender_id="teona", platform="messenger")
    conv.segment = "PARENT"
    conv.state = "DONE"
    lead = Lead(sender_id="teona", platform="messenger", segment="PARENT")
    lead.name, lead.phone, lead.child_age = "თეონა", "577648731", child_age
    conv.lead = lead
    conv.history = [
        {"role": "user",
         "content": "გამარჯობა, თქვენი პირობები რომ მომწეროთ, ბავშვი არის "
                    "შვიდი წლის მეორე კლასში"},
        {"role": "assistant",
         "content": "595 ლარი არის 3-თვიანი მოდულის სრული ღირებულება."},
        {"role": "user", "content": "დიახ შვიდი წლის"},
        {"role": "assistant",
         "content": "მენეჯერთან დაკავშირება — 599 00 11 20. "
                    "ან შეგიძლიათ მოითხოვოთ, რომ ისინი დაგიკავშირდნენ."},
    ]
    return conv


# --------------------------------------------------------------------------
# The live fault.
# --------------------------------------------------------------------------

def test_a_seven_year_old_is_not_underage_when_the_camp_is_closed(monkeypatch):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL], "ended")
    out = parent_flow._maybe_handle_underage_manager_handoff(
        _conversation(), "კარგით,დამოკავშირდნენ")
    assert out is None, f"the closed camp still judged the age: {out!r}"


def test_the_manager_is_not_told_the_child_is_below_the_camps_band(monkeypatch):
    """Whatever answers this turn, the camp's band must not be the reason."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL], "ended")
    out = parent_flow._maybe_handle_underage_manager_handoff(
        _conversation(), "კარგით,დამოკავშირდნენ")
    assert out is None or "ბანაკის ქვემოთ" not in str(out)


@pytest.mark.parametrize("age", ["7", "8"])
def test_every_age_below_the_camps_floor_defers(monkeypatch, age):
    _panel(monkeypatch, [CAMP_OFF, SCHOOL], "ended")
    assert parent_flow._maybe_handle_underage_manager_handoff(
        _conversation(age), "კარგით,დამოკავშირდნენ") is None


# --------------------------------------------------------------------------
# What must not move — this handoff exists for a reason.
# --------------------------------------------------------------------------

def test_a_running_camp_still_hands_an_underage_child_over(monkeypatch):
    """The camp is on sale, so its age band is the one that applies."""
    _panel(monkeypatch, [CAMP_ON, SCHOOL], "active")
    monkeypatch.setattr(
        parent_flow.notification_service, "notify_manager_handoff",
        lambda lead, reason: True)
    out = parent_flow._maybe_handle_underage_manager_handoff(
        _conversation(), "კარგით,დამოკავშირდნენ")
    assert out is not None


def test_the_camp_alone_in_the_panel_is_unchanged(monkeypatch):
    """No other programme on sale ⇒ nothing else the parent could mean."""
    _panel(monkeypatch, [CAMP_OFF], "ended")
    monkeypatch.setattr(
        parent_flow.notification_service, "notify_manager_handoff",
        lambda lead, reason: True)
    out = parent_flow._maybe_handle_underage_manager_handoff(
        _conversation(), "კარგით,დამოკავშირდნენ")
    assert out is not None


def test_a_conversation_that_named_the_camp_is_unchanged(monkeypatch):
    """The parent said camp, so the camp answers — closed or not."""
    _panel(monkeypatch, [CAMP_OFF, SCHOOL], "ended")
    monkeypatch.setattr(
        parent_flow.notification_service, "notify_manager_handoff",
        lambda lead, reason: True)
    conv = _conversation()
    conv.history.insert(
        0, {"role": "user", "content": "საზაფხულო ბანაკი მაინტერესებს"})
    out = parent_flow._maybe_handle_underage_manager_handoff(
        conv, "კარგით,დამოკავშირდნენ")
    assert out is not None


def test_an_eligible_age_never_reached_this_handler_anyway(monkeypatch):
    _panel(monkeypatch, [CAMP_ON, SCHOOL], "active")
    assert parent_flow._maybe_handle_underage_manager_handoff(
        _conversation("12"), "კარგით,დამოკავშირდნენ") is None
