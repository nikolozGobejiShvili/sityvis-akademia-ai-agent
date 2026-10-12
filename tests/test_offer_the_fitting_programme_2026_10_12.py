"""The model is told what the OTHER programmes on sale are for (2026-10-12).

Operator: a parent who says they live abroad is offered „სიტყვის აკადემია
მსოფლიოს გარშემო", the online course for children abroad. Live, a Sunday-School
chat's „ონლაინ გაქვთ? უცხოეთში ვცხოვრობთ" was answered from Sunday School alone
4 times of 4: the model had that programme's facts and the others' NAMES only.
Each programme now travels with the first sentence of its own short
description — in the list in the system prompt and beside the turn's facts.
Measured after: offered 4 of 4, and a plain „რა ღირს?" still Sunday School.
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
    "price_text": "195 ევრო",
    "description_short": ("ონლაინ საკვირაო სკოლა უცხოეთში მცხოვრები ქართველი ბავშვებისა და "
                          "მოზარდებისთვის.\nღირებულება: 195 ევრო"),
}
_LINE = ("სიტყვის აკადემია მსოფლიოს გარშემო (id: wordwide) — ონლაინ საკვირაო სკოლა "
         "უცხოეთში მცხოვრები ქართველი ბავშვებისა და მოზარდებისთვის.")


@pytest.fixture(autouse=True)
def _three_on_sale(monkeypatch):
    original = h._sections
    monkeypatch.setattr(h, "_sections", lambda panel: original(panel) + [dict(_WORLD)])


def _context(turns, tag: str, message: str) -> str:
    with _panel_only("SS_PARIS"):
        conv = _conversation(turns)
        conv.segment = "PARENT"
        conv.lead.program_id = tag
        return ple._build_context_message(conv, conv.lead, message)


def test_a_sunday_school_turn_sees_what_the_other_programmes_are_for():
    ctx = _context([("user", "საკვირაო სკოლა მაინტერესებს")], "sunday_school",
                   "ონლაინ გაქვთ? უცხოეთში ვცხოვრობთ")
    assert "active_program=საკვირაო სკოლა" in ctx
    assert "other_programmes_on_sale=" in ctx and _LINE in ctx
    # only who it is for — never another programme's price
    other = ctx.split("other_programmes_on_sale=", 1)[1]
    assert "195" not in other


def test_an_unchosen_turn_lists_each_programme_with_who_it_is_for():
    ctx = _context([], "", "გამარჯობა, ამერიკაში ვცხოვრობთ, ქართულის პროგრამა მაინტერესებს")
    assert "programme_not_chosen=" in ctx and _LINE in ctx


def test_the_programme_list_says_who_each_programme_is_for():
    with _panel_only("SS_PARIS"):
        suffix = ple._dynamic_programs_prompt_suffix()
    assert _LINE in suffix
    # no short description in the panel → the name alone, as before
    assert "საკვირაო სკოლა (id: sunday_school);" in suffix
