"""Legacy-path child_age no-re-ask (live bug 2026-06-25).

In legacy/giant-prompt mode (USE_CONVERSATION_PLANNER=false,
CONVERSATION_PLANNER_AUTHORITATIVE=false, USE_SLIM_PROMPTS=false; the LLM engine
is ON) the agent sometimes re-asked the child's age even though it was already
given. The planner validator (`planner_final_validate`) is GATED OFF when the
planner is off, so the live guard is the engine path's
`_strip_redundant_age_question_if_known` + the engine's
`_suppress_redundant_age_question`. Both used NARROW marker lists that missed
real phrasings („რა წლისაა", „რამდენ წლისაა", „რომელ კლასში").

The fix routes both through the SHARED helpers
(app/reasoning/age_question.py): `contains_child_age_question` /
`strip_child_age_questions` (sentence-level — a useful fact answer survives).

These tests run with the planner OFF (engine ON) — i.e. the real legacy config.
"""
from __future__ import annotations

import dataclasses

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning.age_question import (
    contains_child_age_question,
    strip_child_age_questions,
)

# Real model phrasings that the old narrow lists missed.
AGE_QUESTIONS = [
    "თქვენი შვილი რამდენი წლისაა?",
    "რა წლისაა ბავშვი?",
    "ბავშვის ასაკი მითხარით",
    "შვილი რომელ კლასშია?",
    "რომელ კლასშია ბავშვი?",
    "რამდენ წლისაა?",
]
# Eligibility / value STATEMENTS that must NEVER be treated as a question.
ELIGIBILITY = [
    "ბანაკი 9–17 წლის ბავშვებისთვისაა.",
    "ბანაკი განკუთვნილია 9-17 წლის ასაკისთვის.",
]


def _conv(
    child_age: str = "13", segment: str = "PARENT", *, midflow: bool = False,
) -> Conversation:
    conv = Conversation(sender_id="legacy-age", platform="instagram")
    conv.segment = segment
    conv.lead = Lead(
        sender_id="legacy-age", platform="instagram", segment=segment,
        child_age=child_age,
    )
    if midflow:
        # Simulate that turns 1–2 already happened (greeting → asked age →
        # „13 წლის არის") so the static welcome menu is not re-emitted and the
        # turn reaches the (mocked) engine — the real mid-conversation state.
        conv.history = [
            {"role": "user", "content": "გამარჯობა ბანაკით ვინტერესდები"},
            {"role": "assistant", "content": "სიამოვნებით. თქვენი შვილი რამდენი წლისაა?"},
            {"role": "user", "content": "13 წლის არის"},
            {"role": "assistant", "content": "13 წელი ბანაკის ასაკს შეესაბამება."},
        ]
    return conv


@pytest.fixture
def legacy_engine(monkeypatch):
    """Operator's legacy config: LLM engine ON, planner + slim OFF."""
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_CONVERSATION_PLANNER=False,
        CONVERSATION_PLANNER_AUTHORITATIVE=False,
        USE_SLIM_PROMPTS=False,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    return swapped


# ── shared helper unit tests ──────────────────────────────────────────────────

@pytest.mark.parametrize("q", AGE_QUESTIONS)
def test_helper_detects_age_question(q):
    assert contains_child_age_question(q) is True


@pytest.mark.parametrize("s", ELIGIBILITY)
def test_helper_keeps_eligibility_statement(s):
    assert contains_child_age_question(s) is False
    assert strip_child_age_questions(s) == s


def test_helper_sentence_level_keeps_fact():
    out = strip_child_age_questions(
        "ბანაკში სხვადასხვა აქტივობაა. თქვენი შვილი რამდენი წლისაა?",
    )
    assert out == "ბანაკში სხვადასხვა აქტივობაა."


# ── legacy chokepoint: _strip_redundant_age_question_if_known ──────────────────

# Tests 1–4 (required): a known age + a pure age question → question removed.
@pytest.mark.parametrize("q", [
    "თქვენი შვილი რამდენი წლისაა?",   # 1
    "რა წლისაა ბავშვი?",               # 2
    "ბავშვის ასაკი მითხარით",         # 3
    "შვილი რომელ კლასშია?",           # 4
])
def test_known_age_strips_age_question(q):
    conv = _conv(child_age="13")
    out = parent_flow._strip_redundant_age_question_if_known(conv, q)
    assert not contains_child_age_question(out)
    assert "რამდენი წლის" not in out
    assert "რომელ კლას" not in out


# Test 5 — useful answer + age question → keep the answer, drop the age question.
def test_known_age_keeps_useful_answer_drops_age():
    conv = _conv(child_age="13")
    out = parent_flow._strip_redundant_age_question_if_known(
        conv, "ბანაკში სხვადასხვა აქტივობაა. თქვენი შვილი რამდენი წლისაა?",
    )
    assert out == "ბანაკში სხვადასხვა აქტივობაა."


# Test 6 — unknown age → the age question is legitimate, NOT removed.
def test_unknown_age_keeps_question():
    conv = _conv(child_age="")
    resp = "გასაგებია. თქვენი შვილი რამდენი წლისაა?"
    assert parent_flow._strip_redundant_age_question_if_known(conv, resp) == resp


# Test 7 — eligibility sentence must stay even when the age is known.
@pytest.mark.parametrize("s", ELIGIBILITY)
def test_eligibility_statement_unchanged(s):
    conv = _conv(child_age="13")
    assert parent_flow._strip_redundant_age_question_if_known(conv, s) == s


# ── engine suppressor (Step 4) — used in legacy mode, now sentence-level ───────

def test_engine_suppressor_keeps_fact_strips_age():
    conv = _conv(child_age="13")
    out = parent_llm_engine._suppress_redundant_age_question(
        "ბანაკში სხვადასხვა აქტივობაა. რა წლისაა ბავშვი?", conv.lead, conv,
    )
    assert "ბანაკში სხვადასხვა აქტივობაა" in out
    assert not contains_child_age_question(out)


def test_engine_suppressor_noop_when_age_unknown():
    conv = _conv(child_age="")
    text = "რა წლისაა ბავშვი?"
    assert parent_llm_engine._suppress_redundant_age_question(
        text, conv.lead, conv,
    ) == text


# ── end-to-end legacy conversation (engine ON, planner OFF) ───────────────────

# Test 8 — „ბანაკში მოწვეული სტუმრები არიან?" after age is known.
def test_legacy_guests_question_no_age_reask(legacy_engine, monkeypatch, camp_registration_open):
    conv = _conv(child_age="13", midflow=True)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: (
            "ბანაკში მოწვეული სტუმრების შესახებ ინფორმაცია მითითებული არ არის. "
            "თქვენი შვილი რა წლისაა?"
        ),
    )
    out = parent_flow.handle(conv, "ბანაკში მოწვეული სტუმრები არიან?")
    assert conv.lead.child_age == "13"                  # state unchanged
    assert not contains_child_age_question(out)         # no age re-ask
    assert "მოწვეული სტუმრ" in out                      # the answer is kept


# Test 9 — „უსაფრთხოება დაცულია?" after age is known.
def test_legacy_safety_question_no_age_reask(legacy_engine, monkeypatch, camp_registration_open):
    conv = _conv(child_age="13", midflow=True)
    monkeypatch.setattr(
        parent_flow, "_run_llm_engine_safely",
        lambda c, m: "უსაფრთხოება ბანაკში პრიორიტეტულია. რომელ კლასშია ბავშვი?",
    )
    out = parent_flow.handle(conv, "უსაფრთხოება დაცულია?")
    assert conv.lead.child_age == "13"
    assert not contains_child_age_question(out)
    assert "უსაფრთხოება" in out
