"""A programme named after the company, and the other names parents use for
it (2026-10-12).

The operator adds „სიტყვის აკადემია მსოფლიოს გარშემო" — an online course for
children abroad, which its brief also calls „ონლაინ საკვირაო სკოლა". Measured
before this change, with it on sale beside Sunday School and Paris:

* a Paris or Sunday-School chat whose last reply mentioned the company
  („ბავშვებს სიტყვის აკადემიის გუნდი ახლავს") was handed the new programme's
  facts, price and number — the company's name is in every programme;
* the Paris description's „მსოფლიო დონის მიუზიკლი", quoted in a Paris chat,
  did the same;
* „ონლაინ საკვირაო სკოლის პირობები?" was answered as Tbilisi's Sunday School.

A bare „ონლაინ გაქვთ?" in a Sunday-School chat stays with Sunday School: the
word alone also means „online payment / registration".
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as ple
from app.flows import parent_flow
from app.reasoning.dynamic_program_match import match_dynamic_program
from app.routes import admin
from app.services import admin_config_service as acs
from tests import test_programme_attribution_and_booking_2026_10_05 as h
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _conversation,
    _no_network,
    _panel_only,
)

_WORLD = {
    "id": "wordwide", "name": "სიტყვის აკადემია მსოფლიოს გარშემო", "type": "kids_program",
    "status": "active", "registration_status": "open",
    "aliases": ["ონლაინ საკვირაო სკოლა"],
    "hashtags": ["მსოფლიოსგარშემო", "wordwide"], "age_min": 7, "age_max": 17,
    "price_text": "195 ევრო", "manager_contact": "599 00 11 20",
    "description_short": ("ონლაინ საკვირაო სკოლა უცხოეთში მცხოვრები ქართველი "
                          "ბავშვებისა და მოზარდებისთვის.\nსიტყვის აკადემია მსოფლიოს "
                          "გარშემო არის 3-თვიანი ონლაინ პროგრამა."),
}
_PARIS_REPLY = "„გმირის მოგზაურობა“ არის „სიტყვის აკადემიის“ 6-დღიანი პარიზის ბანაკი."
_SS_TALK = [("user", "საკვირაო სკოლა მაინტერესებს"),
            ("assistant", "საკვირაო სკოლა 3-თვიანი პროგრამაა.")]


@pytest.fixture(autouse=True)
def _three_on_sale(monkeypatch):
    original = h._sections

    def _with_world(panel):
        sections = original(panel)
        for s in sections:
            if s["id"] == "adult_events":
                s["status"] = "ended"
        return sections + [dict(_WORLD)]
    monkeypatch.setattr(h, "_sections", _with_world)


def _chosen(turns, tag: str, message: str) -> str:
    with _panel_only("SS_PARIS"):
        conv = _conversation(turns)
        conv.segment = "PARENT"
        conv.lead.program_id = tag
        section = ple._active_program_section(conv, message, conv.lead)
    return (section or {}).get("id") or "ask"


def _named(message: str):
    with _panel_only("SS_PARIS"):
        hit = match_dynamic_program(message, acs.get_active_sections())
    return hit and hit["program_id"]


def test_the_company_name_names_no_programme():
    assert _named("გამარჯობა, სიტყვის აკადემიიდან მომწერეთ") is None
    assert _chosen([], "", "გამარჯობა, სიტყვის აკადემიიდან მომწერეთ") == "ask"


def test_the_programme_is_named_by_the_rest_of_its_name():
    assert _named("მსოფლიოს გარშემო რა ღირს?") == "wordwide"
    assert _named("სიტყვის აკადემია მსოფლიოს გარშემო რა ღირს?") == "wordwide"


@pytest.mark.parametrize("turns,tag", [
    ([("user", "ვინ ახლავს ბავშვებს?"), ("assistant", "ბავშვებს სიტყვის აკადემიის გუნდი ახლავს.")],
     "paris_camp"),
    ([("user", "პარიზის ბანაკი მაინტერესებს"), ("assistant", _PARIS_REPLY)], "paris_camp"),
    ([("user", "პედაგოგები ვინ არიან?"),
      ("assistant", "სიტყვის აკადემიის პედაგოგები გამოცდილი ფსიქოლოგები არიან.")], "sunday_school"),
])
def test_a_reply_naming_the_company_keeps_the_chat_its_programme(turns, tag):
    assert _chosen(turns, tag, "რა ღირს?") == tag


def test_the_word_world_alone_names_nothing():
    turns = [("user", "რა შოუებს ნახავენ?"),
             ("assistant", "„მეფე ლომი“ — მსოფლიო დონის მიუზიკლი Théâtre Mogador-ის სცენაზე.")]
    assert _chosen(turns, "paris_camp", "რა ღირს?") == "paris_camp"


@pytest.mark.parametrize("message,expected", [
    ("ონლაინ საკვირაო სკოლის პირობები?", "wordwide"),
    ("ონლაინ საკვირაო სკოლა მაინტერესებს", "wordwide"),
    ("საკვირაო სკოლა რა ღირს?", "sunday_school"),
    ("ონლაინ რეგისტრაცია საკვირაო სკოლაზე შეიძლება?", "sunday_school"),
    ("საკვირაო სკოლაც და მსოფლიოს გარშემოც მაინტერესებს", "ask"),
])
def test_the_other_name_wins_over_the_shorter_name_inside_it(message, expected):
    assert _chosen([], "", message) == expected


def test_the_other_name_in_a_sunday_school_chat_moves_it():
    assert _chosen(_SS_TALK, "sunday_school", "ონლაინ საკვირაო სკოლაც გაქვთ?") == "wordwide"
    assert _chosen(_SS_TALK, "sunday_school", "ონლაინ გაქვთ?") == "sunday_school"


def test_the_short_description_sent_first_belongs_to_its_programme():
    # Its first line says „ონლაინ საკვირაო სკოლა": no tag yet (a comment DM).
    turns = [("assistant", _WORLD["description_short"])]
    assert _chosen(turns, "", "რა ღირს?") == "wordwide"


def test_the_other_name_tags_the_lead():
    with _panel_only("SS_PARIS"):
        conv = _conversation([])
        parent_flow._tag_per_product_booking(conv, "ონლაინ საკვირაო სკოლის პირობები?")
    assert conv.lead.program_id == "wordwide"


def test_other_names_are_saved_from_the_panel_form():
    common = dict(id="wordwide", name="x", type="kids_program", status="active",
                  hashtags="wordwide")
    saved = admin._form_to_section_dict(aliases="ონლაინ საკვირაო სკოლა,\nwordwide course", **common)
    assert saved["aliases"] == ["ონლაინ საკვირაო სკოლა", "wordwide course"]
    assert admin._form_to_section_dict(aliases="", **common)["aliases"] == []
