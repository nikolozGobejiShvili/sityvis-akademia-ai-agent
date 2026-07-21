from evals import harness as H
from evals import reach, safety


def _mk_harness():
    log = safety.SideEffectLog()
    return H.Harness(log, llm_enabled=False, judge_enabled=False)


def test_engine_counter_starts_zero_and_resets_per_turn():
    h = _mk_harness()
    assert h.engine_invocations == 0


def test_reached_engine_false_when_interceptor_short_circuits():
    # A bare camp-price question is answered by a deterministic interceptor,
    # so the engine must NOT run and reached_engine must be False.
    h = _mk_harness()
    conv = h.seed(segment="PARENT", state="START", child_age="13")
    h.process(conv, "ფასი რა ღირს?")
    assert reach.reached_engine(h) is False


def test_chk_reached_engine_returns_failing_check_when_not_reached():
    h = _mk_harness()
    conv = h.seed(segment="PARENT", state="START", child_age="13")
    h.process(conv, "ფასი რა ღირს?")
    c = reach.chk_reached_engine(h)
    assert c.passed is False
