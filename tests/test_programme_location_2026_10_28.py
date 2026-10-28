"""Each programme on the list carries where it takes place (2026-10-28).

Live: before choosing a programme, a parent asked whether there is a branch in
Batumi and was told „სამწუხაროდ, ბათუმში ფილიალი არ გვაქვს" — while Sunday
School's panel location reads „თბილისი და ბათუმი". With no programme chosen the
model reads only the list of programmes on sale, and the list had each one's
name and first sentence but not where it runs. Replayed on the deployed commit
with the live panel: wrong 5 of 5, four of them offering the online course for
children abroad instead. With the panel's own `location` on each line: right
4 of 4, and „სად ხართ?" still lists the programmes and asks which.
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as ple
from tests import test_programme_attribution_and_booking_2026_10_05 as h
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _conversation,
    _no_network,
    _panel_only,
)

_WORLD = {
    "id": "wordwide", "name": "სიტყვის აკადემია მსოფლიოს გარშემო", "type": "kids_program",
    "status": "active", "registration_status": "open", "hashtags": ["wordwide"],
    "price_text": "195 ევრო", "location": "ონლაინ (zoom)",
    "description_short": ("ონლაინ საკვირაო სკოლა უცხოეთში მცხოვრები ქართველი ბავშვებისა და "
                          "მოზარდებისთვის.\nღირებულება: 195 ევრო"),
}
_SCHOOL_LINE = "საკვირაო სკოლა (id: sunday_school) — location: თბილისი და ბათუმი"
_WORLD_LINE = ("სიტყვის აკადემია მსოფლიოს გარშემო (id: wordwide) — ონლაინ საკვირაო სკოლა "
               "უცხოეთში მცხოვრები ქართველი ბავშვებისა და მოზარდებისთვის. — location: "
               "ონლაინ (zoom)")


@pytest.fixture(autouse=True)
def _school_in_two_cities_and_the_online_course(monkeypatch):
    original = h._sections

    def sections(panel):
        out = []
        for section in original(panel):
            section = dict(section)
            if section.get("id") == "sunday_school":
                section["location"] = "თბილისი და ბათუმი"
            out.append(section)
        return out + [dict(_WORLD)]

    monkeypatch.setattr(h, "_sections", sections)


def _context(turns, tag: str, message: str) -> str:
    with _panel_only("SS_PARIS"):
        conv = _conversation(turns)
        conv.segment = "PARENT"
        conv.lead.program_id = tag
        return ple._build_context_message(conv, conv.lead, message)


def test_an_unchosen_turn_says_where_each_programme_runs():
    ctx = _context([], "", "ბათუმში ხომ არ გაქვთ ფილიალი?")
    listed = ctx.split("programme_not_chosen=", 1)[1]
    assert _SCHOOL_LINE in listed
    assert _WORLD_LINE in listed


def test_a_programme_with_no_location_in_the_panel_is_listed_as_before():
    ctx = _context([], "", "ბათუმში ხომ არ გაქვთ ფილიალი?")
    listed = ctx.split("programme_not_chosen=", 1)[1]
    assert "პარიზის ბანაკი (id: paris_camp);" in listed


def test_the_other_programmes_beside_a_chosen_one_say_where_they_run_and_no_price():
    ctx = _context([("user", "საკვირაო სკოლა მაინტერესებს")], "sunday_school",
                   "ონლაინ გაქვთ? უცხოეთში ვცხოვრობთ")
    assert "active_program=საკვირაო სკოლა" in ctx
    other = ctx.split("other_programmes_on_sale=", 1)[1]
    assert _WORLD_LINE in other
    assert "195" not in other


def test_a_location_with_no_short_description_follows_the_name():
    line = ple._programme_line({"id": "x", "name": "X", "location": "ბათუმი"})
    assert line == "X (id: x) — location: ბათუმი"
    assert ple._programme_line({"id": "x", "name": "X"}) == "X (id: x)"
