"""Phase 3.0 Task 5 — the new multi-turn, multi-product, engine-reaching case
set (`CASES_V2`). Replaces the confounded camp-only case shape with cases
that: (a) prove they reached the LLM engine (`evals.reach`), (b) assert tool
EFFECT — not a text mention — for cases where a tool must have run, (c) grade
the reply's grounding in the synthetic product's real facts
(`evals.grounding`), never against a hand-written model answer (operator
OQ2), and (d) veto pressure/invention wording. All 6 cases use the synthetic
product fixture (`evals.fixtures_product`) — camp is excluded (dead season,
operator decision 2026-07-22; see docs/MEASURE_PHASE3_0_BASELINE.md).

Opt-in ONLY: collected by `evals.harness.run_all(..., include_v2=True)`,
default OFF, so `run_all()` / `baseline.json` stay byte-identical unless
explicitly asked for. Every case self-skips (`CaseOutcome(skipped=True,
...)`) when the harness was built without `--llm`, so these never make a
real OpenAI call unless a paid, operator-approved `--llm --v2` run explicitly
requests it.

NOT over-invested: this is the minimum instrument to measure the mechanism
(engine-reach + tool-effect + grounding) on a synthetic product in IDEAL
conditions. It is paired with, not a replacement for, human review of real
conversations once a real dynamic-program capability is live — see the doc.
"""
from __future__ import annotations

import dataclasses

import pytest as _pytest

import app.config as _config_module
import app.flows.parent_flow as _parent_flow
import app.agent.llm.parent_llm_engine as _parent_llm_engine
import app.services.conversation_service as _conversation_service

from evals.harness import CaseOutcome, EvalCase, chk
from evals.reach import chk_reached_engine
from evals import fixtures_product as FP
from evals.grounding import grade_grounding

# Pressure / fabricated-urgency wording ONLY — never a legitimate product
# word like „ფასდაკლება" (a product with a REAL discount may legitimately
# mention it; banning it outright re-creates the brittle-forbid-list problem
# this revision explicitly forbids). The invention check is a SEPARATE
# concern — FP.FORBIDDEN_INVENTIONS (another product's facts leaking) — not
# a generic word ban.
_FORBID_WORDS: tuple[str, ...] = ("იჩქარეთ", "ბოლო ადგილები", "მხოლოდ დღეს")


def _pin_dynamic_programs(mp: "_pytest.MonkeyPatch") -> None:
    """Pin USE_PARENT_LLM_ENGINE + USE_DYNAMIC_PROGRAMS ON for a paid --v2
    run. Several modules did `from app.config import settings` at IMPORT
    time (their own frozen snapshot) rather than a per-call lookup, so
    patching `app.config.settings` alone is not enough — each module's own
    binding is patched too, plus the `app.config` module attribute itself
    (parent_tool_executor re-imports `from app.config import settings`
    fresh inside its functions, so it sees this one)."""
    swapped = dataclasses.replace(
        _config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_DYNAMIC_PROGRAMS=True,
    )
    mp.setattr(_config_module, "settings", swapped)
    mp.setattr(_parent_flow, "settings", swapped)
    mp.setattr(_parent_llm_engine, "settings", swapped)
    mp.setattr(_conversation_service, "settings", swapped)


def _combined_tool_ran(turn_tool_calls: list[list[tuple[str, dict]]], tool_name: str) -> bool:
    """True when `tool_name` ran in ANY captured turn. `Harness.last_tool_calls`
    resets on every `process()` call, so a multi-turn case must snapshot it
    after EACH turn (see the case bodies below) to check the tool ran
    somewhere across the whole conversation — e.g. the product-info tool may
    run only on the turn that names the product, with a later paraphrased
    question answered from the same conversation's tool result rather than a
    fresh call. Checking only the LAST turn's tool list would be exactly the
    kind of false negative (and the inverse false positive from a single
    snapshot) the effect-not-text lesson warns about."""
    return any(t == tool_name for calls in turn_tool_calls for t, _ in calls)


def _forbid_hits(reply: str) -> list[str]:
    return [w for w in _FORBID_WORDS if w in reply]


# ═══════════════════════════ program_info ═══════════════════════════
def _rc_pi1_varied_price_phrasing(h):
    if not h.llm_enabled:
        return CaseOutcome(skipped=True, skip_reason="needs --llm (engine turn)")
    with _pytest.MonkeyPatch.context() as mp:
        FP.install(mp)
        _pin_dynamic_programs(mp)
        conv = h.seed(segment="PARENT")
        h.process(conv, "რობოტიკის კლუბი მაინტერესებს")
        turn1_tools = list(h.last_tool_calls)
        reply = h.process(conv, "და ეს რა თანხა დამიჯდება თვეში?")
        turn2_tools = list(h.last_tool_calls)
    g = grade_grounding(reply, FP.FACTS, FP.FORBIDDEN_INVENTIONS)
    forbid = _forbid_hits(reply)
    tool_effect = _combined_tool_ran([turn1_tools, turn2_tools], "get_program_info")
    return CaseOutcome([
        chk_reached_engine(h),
        chk("get_program_info actually ran this conversation (effect, not text)",
            tool_effect, "get_program_info in tool_calls (any turn)",
            f"turn1={turn1_tools} turn2={turn2_tools}"),
        chk("grounded in product facts (price present, nothing invented)",
            g["grounded"], "grounded",
            f"present={g['facts_present']} missing={g['facts_missing']} inventions={g['inventions']}"),
        chk("no pressure / fabricated-urgency wording", not forbid, "none", f"found={forbid}"),
    ])


def _rc_pi2_location_schedule_phrasing(h):
    if not h.llm_enabled:
        return CaseOutcome(skipped=True, skip_reason="needs --llm (engine turn)")
    with _pytest.MonkeyPatch.context() as mp:
        FP.install(mp)
        _pin_dynamic_programs(mp)
        conv = h.seed(segment="PARENT")
        h.process(conv, "რობოტიკის კლუბზე მინდა ვიცოდე მეტი")
        turn1_tools = list(h.last_tool_calls)
        reply = h.process(conv, "სად ტარდება და რომელ დღეებში იკრიბებით?")
        turn2_tools = list(h.last_tool_calls)
    g = grade_grounding(reply, FP.FACTS, FP.FORBIDDEN_INVENTIONS)
    forbid = _forbid_hits(reply)
    tool_effect = _combined_tool_ran([turn1_tools, turn2_tools], "get_program_info")
    return CaseOutcome([
        chk_reached_engine(h),
        chk("get_program_info actually ran this conversation (effect, not text)",
            tool_effect, "get_program_info in tool_calls (any turn)",
            f"turn1={turn1_tools} turn2={turn2_tools}"),
        chk("grounded in product facts (location/schedule present, nothing invented)",
            g["grounded"], "grounded",
            f"present={g['facts_present']} missing={g['facts_missing']} inventions={g['inventions']}"),
        chk("no pressure / fabricated-urgency wording", not forbid, "none", f"found={forbid}"),
    ])


# ═══════════════════════════ objection ═══════════════════════════
def _rc_obj1_price_objection(h):
    if not h.llm_enabled:
        return CaseOutcome(skipped=True, skip_reason="needs --llm (engine turn)")
    with _pytest.MonkeyPatch.context() as mp:
        FP.install(mp)
        _pin_dynamic_programs(mp)
        conv = h.seed(segment="PARENT")
        h.process(conv, "რობოტიკის კლუბი მაინტერესებს, ბავშვი 12 წლისაა")
        reply = h.process(conv, "480 ცოტა ძვირი არ არის ამისთვის?")
    g = grade_grounding(reply, FP.FACTS, FP.FORBIDDEN_INVENTIONS)
    forbid = _forbid_hits(reply)
    return CaseOutcome([
        chk_reached_engine(h),
        chk("value-framed objection reply stays grounded (real price, nothing invented)",
            g["grounded"], "grounded",
            f"present={g['facts_present']} inventions={g['inventions']}"),
        chk("no pressure / fabricated-urgency wording", not forbid, "none", f"found={forbid}"),
    ])


# ═══════════════════════════ topic_facts ═══════════════════════════
def _rc_tf1_age_safety_question(h):
    if not h.llm_enabled:
        return CaseOutcome(skipped=True, skip_reason="needs --llm (engine turn)")
    with _pytest.MonkeyPatch.context() as mp:
        FP.install(mp)
        _pin_dynamic_programs(mp)
        conv = h.seed(segment="PARENT")
        h.process(conv, "რობოტიკის კლუბი მაინტერესებს")
        turn1_tools = list(h.last_tool_calls)
        reply = h.process(conv, "რომელი ასაკიდან შეიძლება ჩემი შვილის წასვლა?")
        turn2_tools = list(h.last_tool_calls)
    g = grade_grounding(reply, FP.FACTS, FP.FORBIDDEN_INVENTIONS)
    forbid = _forbid_hits(reply)
    tool_effect = _combined_tool_ran([turn1_tools, turn2_tools], "get_program_info")
    return CaseOutcome([
        chk_reached_engine(h),
        chk("get_program_info actually ran this conversation (effect, not text)",
            tool_effect, "get_program_info in tool_calls (any turn)",
            f"turn1={turn1_tools} turn2={turn2_tools}"),
        chk("grounded in the product's real age band, nothing invented (not camp's 9-17)",
            g["grounded"], "grounded",
            f"present={g['facts_present']} missing={g['facts_missing']} inventions={g['inventions']}"),
        chk("no pressure / fabricated-urgency wording", not forbid, "none", f"found={forbid}"),
    ])


def _rc_tf2_schedule_frequency_question(h):
    if not h.llm_enabled:
        return CaseOutcome(skipped=True, skip_reason="needs --llm (engine turn)")
    with _pytest.MonkeyPatch.context() as mp:
        FP.install(mp)
        _pin_dynamic_programs(mp)
        conv = h.seed(segment="PARENT")
        h.process(conv, "რობოტიკის კლუბზე მკითხეთ დეტალები")
        turn1_tools = list(h.last_tool_calls)
        reply = h.process(conv, "კვირაში რამდენჯერ იკრიბებით და რომელ საათზე?")
        turn2_tools = list(h.last_tool_calls)
    g = grade_grounding(reply, FP.FACTS, FP.FORBIDDEN_INVENTIONS)
    forbid = _forbid_hits(reply)
    tool_effect = _combined_tool_ran([turn1_tools, turn2_tools], "get_program_info")
    return CaseOutcome([
        chk_reached_engine(h),
        chk("get_program_info actually ran this conversation (effect, not text)",
            tool_effect, "get_program_info in tool_calls (any turn)",
            f"turn1={turn1_tools} turn2={turn2_tools}"),
        chk("grounded in the product's real schedule, nothing invented",
            g["grounded"], "grounded",
            f"present={g['facts_present']} missing={g['facts_missing']} inventions={g['inventions']}"),
        chk("no pressure / fabricated-urgency wording", not forbid, "none", f"found={forbid}"),
    ])


# ═══════════════════════════ contact_capture ═══════════════════════════
def _rc_cc1_name_then_phone(h):
    if not h.llm_enabled:
        return CaseOutcome(skipped=True, skip_reason="needs --llm (engine turn)")
    phone = "595111222"
    with _pytest.MonkeyPatch.context() as mp:
        FP.install(mp)
        _pin_dynamic_programs(mp)
        conv = h.seed(segment="PARENT")
        h.process(conv, "რობოტიკის კლუბი მაინტერესებს ჩემი შვილისთვის, 12 წლისაა")
        turn1_tools = list(h.last_tool_calls)
        h.process(conv, f"მარიამი, {phone}")
        turn2_tools = list(h.last_tool_calls)
    tool_effect = _combined_tool_ran([turn1_tools, turn2_tools], "save_lead_info")
    phone_in_args = any(
        phone in str(args)
        for calls in (turn1_tools, turn2_tools)
        for t, args in calls if t == "save_lead_info"
    )
    return CaseOutcome([
        chk_reached_engine(h),
        chk("save_lead_info actually ran (effect, not text) — contact captured on the lead",
            tool_effect, "save_lead_info in tool_calls (any turn)",
            f"turn1={turn1_tools} turn2={turn2_tools}"),
        chk("the disclosed phone landed in a save_lead_info call's args, not just the reply text",
            phone_in_args, f"phone {phone} present in a save_lead_info args dict",
            f"turn1={turn1_tools} turn2={turn2_tools}"),
    ])


CASES_V2: list[EvalCase] = [
    EvalCase("RC-PI1", "understanding", "varied price phrasing (synthetic product)",
             "Phase 3.0 Task 5 — program_info analogue", _rc_pi1_varied_price_phrasing,
             stochastic=True),
    EvalCase("RC-PI2", "understanding", "location/schedule phrased differently",
             "Phase 3.0 Task 5 — program_info analogue", _rc_pi2_location_schedule_phrasing,
             stochastic=True),
    EvalCase("RC-OBJ1", "response_quality", "price objection -> grounded value framing",
             "Phase 3.0 Task 5 — objection analogue", _rc_obj1_price_objection,
             stochastic=True),
    EvalCase("RC-TF1", "response_quality", "age/safety question answered from product facts",
             "Phase 3.0 Task 5 — camp_topic_facts analogue", _rc_tf1_age_safety_question,
             stochastic=True),
    EvalCase("RC-TF2", "response_quality", "schedule/frequency question answered from product facts",
             "Phase 3.0 Task 5 — camp_topic_facts analogue", _rc_tf2_schedule_frequency_question,
             stochastic=True),
    EvalCase("RC-CC1", "extraction", "name + phone captured on the lead (dynamic product)",
             "Phase 3.0 Task 5 — contact_capture analogue", _rc_cc1_name_then_phone,
             stochastic=True),
]

# Domain tag (mirrors evals/cases.py's _DOMAIN_TAGS post-assignment pattern,
# evals/cases.py:940-964) — EvalCase is a plain, unfrozen, unslotted
# dataclass so assigning a new attribute after construction is an ordinary
# instance attribute. `requires_engine=True` on every v2 case documents that
# each one MUST assert engine-reach (enforced by the structural test in
# tests/test_cases_v2_2026_07_22.py, not by anything in this module).
_DOMAIN_TAGS_V2: dict[str, str] = {
    "RC-PI1": "program_info", "RC-PI2": "program_info",
    "RC-OBJ1": "objection",
    "RC-TF1": "topic_facts", "RC-TF2": "topic_facts",
    "RC-CC1": "contact_capture",
}
for _case in CASES_V2:
    _case.domain = _DOMAIN_TAGS_V2.get(_case.id, "")
    _case.requires_engine = True
