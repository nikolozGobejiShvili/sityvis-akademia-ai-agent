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
    # A SPECIFIC question about the product. The probe used to be the bare
    # „რობოტიკის კლუბი მაინტერესებს", but since 2026-09-05 a message that names
    # a programme and asks nothing of its own IS the overview turn and is
    # answered with the operator's `description_short` before the engine (the
    # test below pins that half). Both routes need `dynamic_program_match` to
    # resolve the fixture's name, so this still checks what it was written to
    # check — that the fixture is nameable.
    reply = h.process(conv, "რობოტიკის კლუბის განრიგი როგორია?")
    assert reply == "ok"
    assert reach.reached_engine(h) is True


def test_named_product_overview_returns_the_operator_text(monkeypatch):
    """The other half of the same routing, and the reason the probe above had to
    change: a general „<product> მაინტერესებს" is answered from the panel's
    `description_short`, as written, without the engine."""
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
    conv.history.append({"role": "assistant", "content": "_prior"})
    reply = h.process(conv, "რობოტიკის კლუბი მაინტერესებს")
    assert reply == (FP.PRODUCT.get("description_short") or "").strip()
    assert reply != "ok"


# ── Task 5: cases_v2 — multi-turn, engine-reaching, grounded case set ──────
def test_cases_v2_all_require_engine_and_are_tagged():
    from evals import cases_v2

    assert cases_v2.CASES_V2
    assert len(cases_v2.CASES_V2) == 6
    for c in cases_v2.CASES_V2:
        assert getattr(c, "requires_engine", False) is True
        assert c.domain in {"program_info", "objection", "topic_facts", "contact_capture"}


def test_cases_v2_case_ids_are_unique():
    from evals import cases_v2

    ids = [c.id for c in cases_v2.CASES_V2]
    assert len(ids) == len(set(ids))


def test_cases_v2_self_skip_offline():
    # Offline (no --llm): every v2 case must self-skip rather than attempt a
    # real engine turn — this is what keeps the free/default eval run free.
    from evals import cases_v2

    h = _mk_harness()
    for c in cases_v2.CASES_V2:
        outcome = c.run(h)
        assert outcome.skipped is True
        assert "--llm" in outcome.skip_reason


def test_run_all_default_excludes_v2_cases():
    # include_v2 defaults False — run_all() must not even import cases_v2,
    # let alone run it, so baseline.json stays byte-identical by default.
    import inspect

    from evals.harness import run_all

    sig = inspect.signature(run_all)
    assert sig.parameters["include_v2"].default is False


def test_collect_cases_include_v2_default_off_is_byte_identical():
    # include_v2 defaults False in _collect_cases too — the pure collection
    # helper run_all() delegates to. Not calling safety.install_readonly
    # (process-wide, non-reentrant stubs) keeps this test side-effect-free.
    from evals.cases import CASES
    from evals.harness import _collect_cases

    default_ids = [c.id for c in _collect_cases(category=None, case_id=None, include_v2=False)]
    assert default_ids == [c.id for c in CASES]


def test_collect_cases_include_v2_true_adds_cases_v2():
    from evals import cases_v2
    from evals.harness import _collect_cases

    with_v2 = _collect_cases(category=None, case_id=None, include_v2=True)
    v2_ids_present = {c.id for c in with_v2} & {c.id for c in cases_v2.CASES_V2}
    assert v2_ids_present == {c.id for c in cases_v2.CASES_V2}


def test_collect_cases_include_v2_respects_category_and_case_id_filters():
    from evals.harness import _collect_cases

    got = _collect_cases(category="extraction", case_id="RC-CC1", include_v2=True)
    assert [c.id for c in got] == ["RC-CC1"]
