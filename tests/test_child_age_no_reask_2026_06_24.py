"""Child-age no-re-ask defense-in-depth (Phase 1, 2026-06-24).

Reproduces the live „re-asks the child's age" bug (§0-A of FIX_PLAN_V2_5H):
a real model phrases the age question many ways that the old two-substring
tuple missed. After the fix three layers make the re-ask impossible —

  1. the shared AGE_QUESTION_RE recognises every real phrasing but NOT an
     eligibility statement („9–17 წლის ბავშვებისთვის");
  2. the engine guard `_suppress_redundant_age_question` replaces a redundant
     age question with the next booking step;
  3. the central validator `planner_final_validate` strips a leaked age
     question STATE-DRIVEN (child_age known) on any non-adult route, even when
     the planner did not set the forbidden flag.

All offline / deterministic — no OpenAI, Calendar, Sheets.
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.reasoning import conversation_planner as cp
from app.reasoning.age_question import AGE_QUESTION_RE

# The four real-model phrasings the narrow tuple missed.
AGE_QUESTIONS = [
    "რა წლისაა ბავშვი?",
    "ბავშვის ასაკი მითხარით",
    "შვილი რომელ კლასშია?",
    "რამდენ წლისაა?",
]
# An eligibility STATEMENT — must never be treated as an age question.
ELIGIBILITY = "ბანაკი 9–17 წლის ბავშვებისთვისაა."


def _parent_conv(child_age: str = "13", phone: str = "") -> Conversation:
    lead = Lead(
        sender_id="s", platform="messenger", segment="PARENT",
        child_age=child_age, phone=phone,
    )
    return Conversation(
        sender_id="s", platform="messenger", segment="PARENT", lead=lead,
    )


# ───────────────────────────── 1. shared regex ────────────────────────────────

@pytest.mark.parametrize("q", AGE_QUESTIONS)
def test_regex_matches_real_age_questions(q):
    assert AGE_QUESTION_RE.search(q.lower()) is not None


def test_regex_does_not_match_eligibility_statement():
    assert AGE_QUESTION_RE.search(ELIGIBILITY.lower()) is None


# ───────────────────── 2. engine anti-repeat guard ────────────────────────────

@pytest.mark.parametrize("q", AGE_QUESTIONS)
def test_engine_suppresses_redundant_age_question(q):
    conv = _parent_conv(child_age="13")
    out = parent_llm_engine._suppress_redundant_age_question(q, conv.lead, conv)
    assert AGE_QUESTION_RE.search(out.lower()) is None
    assert out.strip()                       # a real next-step reply, never empty
    assert "ნომერ" in out                    # phone unknown → ask for the number


def test_engine_guard_leaves_eligibility_statement_untouched():
    conv = _parent_conv(child_age="13")
    out = parent_llm_engine._suppress_redundant_age_question(
        ELIGIBILITY, conv.lead, conv,
    )
    assert out == ELIGIBILITY


def test_engine_guard_preserves_age_confirmation():
    """A CONFIRMATION that mentions the age (not a question) is left intact."""
    conv = _parent_conv(child_age="14")
    text = "თქვენი შვილის ასაკი 14 წელია — ბანაკი შესაბამისია."
    out = parent_llm_engine._suppress_redundant_age_question(text, conv.lead, conv)
    assert out == text


def test_engine_guard_noop_when_age_unknown():
    conv = _parent_conv(child_age="")
    out = parent_llm_engine._suppress_redundant_age_question(
        "რა წლისაა ბავშვი?", conv.lead, conv,
    )
    assert out == "რა წლისაა ბავშვი?"        # asking is correct when unknown


# ─────────────────── 3. central validator (state-driven) ──────────────────────

@pytest.mark.parametrize("q", AGE_QUESTIONS)
def test_validator_strips_leaked_age_question_state_driven(q):
    """A FLAGLESS camp plan with a known child_age still strips a leaked age
    question — the enforcement reads the state, not just the planner flag."""
    conv = _parent_conv(child_age="13")
    plan = cp.TurnPlan(active_topic="camp", child_age="13")   # no forbidden flags
    reply = f"ბანაკი ბავშვებს უვითარებს უნარებს. {q}"
    out = parent_flow.planner_final_validate(conv, plan, reply)
    assert AGE_QUESTION_RE.search(out.lower()) is None
    assert "უვითარებს" in out                # the real content is preserved


def test_validator_replaces_age_only_reply_with_next_step():
    conv = _parent_conv(child_age="13")
    plan = cp.TurnPlan(active_topic="camp", child_age="13")
    out = parent_flow.planner_final_validate(conv, plan, "რა წლისაა ბავშვი?")
    assert AGE_QUESTION_RE.search(out.lower()) is None
    assert out.strip()                       # never returns an empty reply


def test_validator_keeps_eligibility_statement():
    conv = _parent_conv(child_age="13")
    plan = cp.TurnPlan(active_topic="camp", child_age="13")
    out = parent_flow.planner_final_validate(conv, plan, ELIGIBILITY)
    assert "9–17" in out and "ბავშვებისთვის" in out


def test_validator_does_not_strip_age_question_on_adult_route():
    """Asking the child's age in an adult-for-child flow is legitimate, so the
    age-question strip is skipped when active_topic == adult_event."""
    conv = _parent_conv(child_age="13")
    plan = cp.TurnPlan(active_topic="adult_event", child_age="13")
    reply = "ზრდასრულთა ღონისძიება გვაქვს. შვილი რამდენ წლისაა?"
    out = parent_flow.planner_final_validate(conv, plan, reply)
    assert AGE_QUESTION_RE.search(out.lower()) is not None    # preserved


def test_validator_uses_lead_state_when_plan_child_age_missing():
    """State-driven: even if the plan object carries no child_age, the lead's
    child_age still drives the strip."""
    conv = _parent_conv(child_age="13")
    plan = cp.TurnPlan(active_topic="camp")   # plan.child_age is None
    reply = "ბანაკი საინტერესოა. რამდენ წლისაა?"
    out = parent_flow.planner_final_validate(conv, plan, reply)
    assert AGE_QUESTION_RE.search(out.lower()) is None
    assert "საინტერესოა" in out


def test_validator_noop_when_age_unknown():
    """No child_age on the lead/plan → the age question is a legitimate ask and
    must be preserved."""
    conv = _parent_conv(child_age="")
    plan = cp.TurnPlan(active_topic="camp")
    reply = "ბანაკი საინტერესოა. რა წლისაა ბავშვი?"
    out = parent_flow.planner_final_validate(conv, plan, reply)
    assert AGE_QUESTION_RE.search(out.lower()) is not None


# ─────────────────── 4. regex sentence-strip helper ───────────────────────────

def test_strip_sentences_matching_re_drops_only_matching_sentence():
    text = "ბანაკი 9–17 წლის ბავშვებისთვისაა. რა წლისაა ბავშვი?"
    out = parent_flow._strip_sentences_matching_re(text, AGE_QUESTION_RE)
    assert "9–17" in out                     # eligibility kept
    assert "რა წლისაა" not in out            # age question dropped


def test_validator_with_real_plan_strips_age_question():
    """Integration: a real camp-safety plan (built by the planner) with a known
    child_age strips a leaked age question end-to-end."""
    conv = _parent_conv(child_age="13")
    plan = cp.plan_turn("ბანაკში უსაფრთხოება დაცულია?", conv)
    assert plan.active_topic == "camp"
    reply = "ბავშვებზე ზრუნავენ. ბავშვის ასაკი მითხარით."
    out = parent_flow.planner_final_validate(conv, plan, reply)
    assert AGE_QUESTION_RE.search(out.lower()) is None
    assert "ზრუნავენ" in out
