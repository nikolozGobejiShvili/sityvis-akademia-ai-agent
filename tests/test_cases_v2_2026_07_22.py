"""Tests for the Phase 3.0 rebuild's Task 3 (synthetic product fixture) and
Task 5 (cases_v2 — multi-turn, engine-reaching, grounded case set). Task 2's
R4 effect-fix mutation test already lives in tests/test_r4_effect_fix_2026_07_22.py
(shipped ahead of this file) — not duplicated here.
"""
import dataclasses

import app.config as config_module
import app.agent.llm.parent_llm_engine as ple
from app.flows import parent_flow
from evals import harness as H
from evals import reach, safety
from evals import fixtures_product as FP


def _mk_harness():
    log = safety.SideEffectLog()
    return H.Harness(log, llm_enabled=False, judge_enabled=False)


# ── Task 3: synthetic, season-independent product fixture ──────────────────
def test_fixture_defines_known_facts():
    assert FP.PRODUCT["id"] not in ("summer_camp", "sunday_school", "adult_events")
    assert FP.PRODUCT["price_text"] in "".join(FP.FACTS)
    assert FP.FACTS and FP.FORBIDDEN_INVENTIONS
    # forbidden inventions must not overlap the real facts
    assert not (set(FP.FACTS) & set(FP.FORBIDDEN_INVENTIONS))


def test_named_product_turn_reaches_the_engine(monkeypatch):
    # Step 6 sanity check (Task 3): with the product installed + the two
    # flags pinned on, a turn NAMING the product must hoist straight to the
    # engine (offline, engine spied via a fake — no real OpenAI call). If
    # this doesn't hold the fixture itself is wrong (name/hashtags don't
    # match `dynamic_program_match`'s specificity rules) — that's the whole
    # point of this test.
    FP.install(monkeypatch)
    swapped = dataclasses.replace(
        config_module.settings,
        USE_PARENT_LLM_ENGINE=True,
        USE_DYNAMIC_PROGRAMS=True,
    )
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(ple, "run_parent_llm_turn", lambda *a, **k: "ok")

    h = _mk_harness()
    conv = h.seed(segment="PARENT", state="START", child_age="13")
    # Pre-seed an assistant turn so the first-reply static-welcome bypass
    # (which fires on ANY message on the bot's first reply at state=START,
    # regardless of content) does not short-circuit routing before the
    # dynamic-program hoist — same idiom as
    # test_eval_reach_2026_07_22.py::test_engine_counter_increments_when_engine_runs.
    conv.history.append({"role": "assistant", "content": "_prior"})
    reply = h.process(conv, "რობოტიკის კლუბი მაინტერესებს")
    assert reply == "ok"
    assert reach.reached_engine(h) is True
