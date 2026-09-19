"""Live regression, client Page 2026-09-19 09:49 — screenshots 28 and 29.

    parent : შეხვედრებს როდიდან ანახლებთ?
    agent  : გუნდი მუდმივად მუშაობს ახალი ღონისძიებების დაგეგმვაზე! 🎉
    parent : ბავშვი დამყავს 11-12წლის ჯგუფში და მაინტერესებს როდიდან იწყება
             შეხვედრები
    agent  : გადაგამისამართე! თქვენი შეკითხვა 11-12 წლის ჯგუფთან დაკავშირებით
             მიღებულია … სწორ ნაკადზე ხართ!

A parent asking when her child's group resumes was answered by the ADULT
cultural-events flow, which then had to hand her back („switch_to_parent_flow"
is in the Railway log at 05:49:37 UTC) with a sentence the code does not
contain — the model wrote it, and reached for „ნაკადი", the camp's word for its
streams.

The cause is one entry in `ADULT_KEYWORDS`: the stem „შეხვედრ". A cultural
evening is „ღონისძიება" or „საღამო"; „შეხვედრა" is simply a meeting, and Sunday
School is sold as „12 ინტერაქციული შეხვედრა" — the word is in its own panel
description. The same stem is already documented in `conversation_service` as
having mis-assigned a Sunday-School enquiry on 2026-09-10; the fix then added a
panel lookup for turns that NAME a programme, which cannot help a turn that
names none.

Removing the stem is a deletion, not a new branch: with the word gone the turn
is UNCLEAR, and `_sole_active_program_segment` routes it from the PANEL — to
whichever single programme is on sale, adult events included. Two on sale and
the agent asks. The seven unambiguous adult stems are untouched.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.services import admin_config_service
from app.services import conversation_service as cs

SCHOOL = {
    "id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
    "status": "active", "age_min": 7, "age_max": 17, "price_text": "595 ლარი",
    "description_short": "12 ინტერაქციული შეხვედრა ლიტერატურასა და ფსიქოლოგიაში.",
}
EVENTS = {
    "id": "adult_events", "name": "ზრდასრულთა ღონისძიებები",
    "type": "adult_events", "status": "active",
}

# The two live messages, plus the same shape without the child word.
MEETING_TURNS = (
    "შეხვედრებს როდიდან ანახლებთ?",
    "ბავშვი დამყავს 11-12წლის ჯგუფში და მაინტერესებს როდიდან იწყება შეხვედრები",
    "შეხვედრები როდის იწყება",
    "ერთი შეხვედრა რამდენ ხანს გრძელდება?",
)

# A cultural evening says so. These must not move.
REAL_ADULT_TURNS = (
    "ღონისძიება მაინტერესებს",
    "ბილეთი მინდა",
    "კულტურული საღამო გაქვთ?",
    "პოეზიის საღამოზე როგორ დავრეგისტრირდე",
)


@pytest.fixture
def school_only(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [dict(SCHOOL)])
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        cs, "settings",
        dataclasses.replace(config_module.settings, USE_DYNAMIC_PROGRAMS=True),
    )


@pytest.mark.parametrize("message", MEETING_TURNS)
def test_a_meeting_is_not_an_adult_event(message):
    """The stem decides this before any panel is consulted, so it is checked on
    its own."""
    assert cs._classify_segment(message) != "ADULT", (
        "a meeting is a meeting; every programme has them"
    )


@pytest.mark.parametrize("message", REAL_ADULT_TURNS)
def test_a_cultural_evening_still_says_so(message):
    assert cs._classify_segment(message) == "ADULT"


@pytest.mark.parametrize("message", MEETING_TURNS)
def test_with_one_programme_on_sale_the_panel_routes_the_meeting(
    school_only, message,
):
    """Deleting the stem does not leave the turn homeless: it is UNCLEAR, and
    the sole-programme rule sends it to what is actually on sale."""
    assert cs._classify_segment(message) != "ADULT"
    assert cs._sole_active_program_segment() == "PARENT"


def test_the_panel_can_still_route_a_meeting_to_the_adult_flow(monkeypatch):
    """With adult events the only thing on sale, the same question is theirs —
    decided by the panel rather than by a guess about one word."""
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [dict(EVENTS)])
    monkeypatch.setattr(
        cs, "settings",
        dataclasses.replace(config_module.settings, USE_DYNAMIC_PROGRAMS=True),
    )
    assert cs._sole_active_program_segment() == "ADULT"


def test_both_on_sale_leaves_the_choice_to_the_parent(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_active_sections",
        lambda *a, **k: [dict(SCHOOL), dict(EVENTS)])
    monkeypatch.setattr(
        cs, "settings",
        dataclasses.replace(config_module.settings, USE_DYNAMIC_PROGRAMS=True),
    )
    assert cs._sole_active_program_segment() is None


def test_the_seven_unambiguous_adult_stems_are_untouched():
    for stem in ("ღონისძიებ", "საღამო", "ბილეთ", "კულტურ", "პოეზი", "მუსიკ", "კლუბ"):
        assert stem in cs.ADULT_KEYWORDS
    assert "შეხვედრ" not in cs.ADULT_KEYWORDS
