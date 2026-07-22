import dataclasses

import app.config as config_module
import app.agent.llm.parent_llm_engine as ple
from app.flows import parent_flow
from evals import harness as H
from evals import reach, safety


def _mk_harness():
    log = safety.SideEffectLog()
    return H.Harness(log, llm_enabled=False, judge_enabled=False)


def test_engine_counter_starts_zero_and_resets_per_turn():
    h = _mk_harness()
    assert h.engine_invocations == 0


def test_reached_engine_false_when_engine_cannot_run():
    # In this bare-harness context the autouse conftest fixture pins
    # USE_PARENT_LLM_ENGINE=False, so the top-level engine gate short-circuits
    # before any interceptor question — the engine cannot run and
    # reached_engine must be False. (The flag-ON positive path is covered by
    # test_engine_counter_increments_when_engine_runs below.)
    h = _mk_harness()
    conv = h.seed(segment="PARENT", state="START", child_age="13")
    h.process(conv, "ფასი რა ღირს?")
    assert reach.reached_engine(h) is False


def test_engine_counter_increments_when_engine_runs(monkeypatch):
    # POSITIVE path (the direction the three False-asserting tests never
    # exercise): flip the engine flag ON and replace the engine entrypoint with
    # a fake so NO OpenAI call happens, then drive a turn that reaches the
    # engine and assert the counter actually increments. A counter hardwired to
    # 0 — or a wrong monkeypatch target — would fail HERE, not in the False
    # tests. Engine-enable idiom mirrors tests/test_parent_llm_engine.py
    # (Settings is a frozen dataclass → replace + setattr).
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(ple, "run_parent_llm_turn", lambda *a, **k: "ok")
    # Un-dead-season the run: the camp ended 2026-07-20, so a bare camp message
    # otherwise hits the registration-closed interceptor BEFORE the engine
    # (exactly the confound Phase 3.0 exists to remove). Reopen registration so
    # the turn actually reaches the engine — mirrors the camp_registration_open
    # fixture in tests/test_parent_llm_engine.py.
    monkeypatch.setattr(
        "app.services.admin_config_service.get_camp_registration_status",
        lambda: "open",
    )

    h = _mk_harness()
    conv = h.seed(segment="PARENT", state="START", child_age="13")
    # Pre-seed an assistant turn so the first-reply static-welcome bypass does
    # not short-circuit routing before the engine.
    conv.history.append({"role": "assistant", "content": "_prior"})
    reply = h.process(conv, "ბანაკი მაინტერესებს")  # explicit camp intent → reaches engine
    assert reply == "ok"
    assert h.engine_invocations == 1
    assert reach.reached_engine(h) is True

    # per-process reset: a second turn re-counts from 0 → 1, not 2
    h.process(conv, "ბანაკი მაინტერესებს")
    assert h.engine_invocations == 1

    # wrapper unconditionally restored after process() — no global leak
    assert ple.run_parent_llm_turn.__name__ != "_counting_run"


def test_chk_reached_engine_returns_failing_check_when_not_reached():
    h = _mk_harness()
    conv = h.seed(segment="PARENT", state="START", child_age="13")
    h.process(conv, "ფასი რა ღირს?")
    c = reach.chk_reached_engine(h)
    assert c.passed is False
