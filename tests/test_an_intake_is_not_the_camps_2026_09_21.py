"""Live regression, client Page 2026-09-21 13:31 and 2026-09-20/21 — two faults.

1. „ნაკად" was a camp keyword.

    parent : ეს სამთვიანი კურსები როდის იწყება და შემდეგი ნაკადის მიღება
             როდის მოხდება?
    agent  : საზაფხულო ბანაკი უკვე გაიმართა და რეგისტრაცია დასრულებულია.

   Railway 09:31:22 UTC, took_ms=105 — deterministic, the model never saw the
   turn. The parent was asking when the SUNDAY SCHOOL's next intake opens;
   „ნაკადი" is what any programme calls an intake, and Sunday School is sold in
   3-month modules that plainly have them.

   This is the third time the same shape has shipped: a word every programme
   owns, bound to one programme. „შეხვედრ" was deleted from ADULT_KEYWORDS on
   2026-09-19 for exactly this reason; „ნაკად" is its twin. The three words that
   remain — ბანაკ, საზაფხულო, ლაგერ — name the camp and nothing else.

2. Georgian the language does not contain.

   Five replies over two days, none of these strings anywhere in the repo or in
   the 183 sanitiser rules — the model wrote each one:

     „გაგიხარდებათ!"      (20 სექ 23:35, to „მინდა ბავშვის მოყვანა")
     „გაუმარჯოს! 🎉"      (21 სექ 01:49, to „რეგისტრაცია გავიარეთ")
     „გარდერობია! 🎉"     (a location question — the word means nothing at all)
     „სიამოვნება ჩემია!"  (21 სექ 09:48, answering thanks — a loan translation)
     „თუ მომავალში გაიზრდება" (21 სექ 07:32, about a child too young)

   Every one lands on a congratulation, a thank-you or a warm close — the exact
   moments the prompt gives the model no phrasing for, so it improvises. Growing
   the sanitiser list cannot keep up with that; supplying the missing phrasings
   can, which is how „გილოცავთ კითხვა" and „გადაგიხდიან ზარს" were fixed.
"""
from __future__ import annotations

import dataclasses

import pytest

from app import config as config_module
from app.agent.llm import parent_llm_engine as engine
from app.flows import parent_flow
from app.services import admin_config_service
from app.services import conversation_service as cs

SCHOOL = {"id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
          "status": "active", "age_min": 7, "age_max": 17,
          "price_text": "595 ლარი"}
CAMP_OFF = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
            "status": "ended", "price_text": "2150 ლარი"}

# The parent's own words, 13:31, plus the same shape said other ways.
INTAKE_TURNS = (
    "ეს სამთვიანი კურსები როდის იწყება და შემდეგი ნაკადის მიღება როდის მოხდება?",
    "შემდეგი ნაკადი როდის იწყება?",
    "ახალ ნაკადზე როგორ მოვხვდები?",
    "ნაკადები რამდენჯერ იმართება წელიწადში?",
)

# The camp still owns its own words.
CAMP_TURNS = (
    "ბანაკი მაინტერესებს",
    "საზაფხულო ბანაკის ფასი",
    "ლაგერი გაქვთ?",
)


@pytest.fixture
def school_only(monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_camp_status", lambda *a, **k: "ended")
    monkeypatch.setattr(
        admin_config_service, "is_camp_registration_open", lambda *a, **k: False)
    monkeypatch.setattr(
        admin_config_service, "get_active_sections", lambda *a, **k: [dict(SCHOOL)])
    monkeypatch.setattr(
        admin_config_service, "load_sections",
        lambda *a, **k: [dict(CAMP_OFF), dict(SCHOOL)])
    live = dataclasses.replace(
        config_module.settings,
        USE_DYNAMIC_PROGRAMS=True, USE_PROGRAM_ISOLATION=True,
    )
    for mod in (cs, parent_flow, engine):
        monkeypatch.setattr(mod, "settings", live)


# --------------------------------------------------------------------------
# 1. An intake belongs to whichever programme has one.
# --------------------------------------------------------------------------

def test_intake_is_not_a_camp_word():
    assert "ნაკად" not in parent_flow._CAMP_STATUS_KEYWORDS, (
        "every programme has intakes; Sunday School is sold in 3-month modules"
    )


def test_the_three_real_camp_words_remain():
    for stem in ("ბანაკ", "საზაფხულო", "ლაგერ"):
        assert stem in parent_flow._CAMP_STATUS_KEYWORDS


@pytest.mark.parametrize("message", INTAKE_TURNS)
def test_an_intake_question_is_not_the_camps(school_only, message):
    """`_msg_names_the_camp` is the predicate every guard shipped this week
    consults, so pinning it pins all of them at once."""
    assert parent_flow._msg_names_the_camp(message) is False


@pytest.mark.parametrize("message", CAMP_TURNS)
def test_a_camp_question_still_is_the_camps(school_only, message):
    assert parent_flow._msg_names_the_camp(message) is True


def test_the_live_turn_does_not_answer_about_the_closed_camp(school_only):
    """End to end, engine stubbed: the 13:31 message must not produce the
    camp-ended sentence."""
    answer = parent_flow._maybe_handle_camp_status(
        _conv(), INTAKE_TURNS[0])
    assert answer is None or "ბანაკ" not in answer, (
        "the closed camp answered a question about another programme's intake"
    )


def _conv():
    from app.models.conversation import Conversation
    from app.models.lead import Lead
    c = Conversation(sender_id="intake", platform="messenger")
    c.segment = "PARENT"
    c.lead = Lead(sender_id="intake", platform="messenger", segment="PARENT")
    return c


# --------------------------------------------------------------------------
# 2. The prompt supplies the phrasings the model was inventing.
# --------------------------------------------------------------------------

def test_the_prompt_answers_thanks_in_georgian():
    prompt = engine._build_system_prompt(message="x", segment="PARENT")
    assert "არაფრის" in prompt


def test_the_prompt_has_a_word_for_congratulating():
    prompt = engine._build_system_prompt(message="x", segment="PARENT")
    assert "გილოცავთ" in prompt


def test_the_prompt_names_the_inventions_it_replaces():
    """Taught by example, the way the polite verb forms already are — the point
    is the CORRECT form; the wrong one is shown so the contrast is visible."""
    prompt = engine._build_system_prompt(message="x", segment="PARENT")
    for invented in ("სიამოვნება ჩემია", "გაგიხარდებათ"):
        assert invented in prompt, (
            "the rule does not name the wording it is replacing"
        )
