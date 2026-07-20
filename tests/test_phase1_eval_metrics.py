"""Phase 1 behavioral eval safety net — Task 1: interception-rate instrument.

FREE, deterministic, READ-ONLY tests for `evals/interception.py`. No live
OpenAI / Calendar / Sheets / Meta call is made — the engine is spied (never
invoked for real), and every other external side effect is stubbed via the
same `evals.safety.install_readonly` guard the rest of the harness uses.

Test message choice: the audit (Task 1 brief) named
`_maybe_handle_explicit_manager_request` as a currently-wired PRE-engine
interceptor for a manager-number request. Verified directly against the real
`app/flows/parent_flow.py` matchers before writing this test:
`_is_explicit_manager_number_request` requires `_mentions_manager` (the
message contains "მენეჯერ") AND a contact marker from
`_MANAGER_CONTACT_MARKERS = ("ნომერ", "ტელეფონ", "კონტაქტ")` AND no digits
that parse as a valid phone. "მენეჯერის ნომერი მინდა" satisfies all three
("მენეჯერ" + "ნომერ" + no digits), and `_maybe_handle_explicit_manager_request`
runs well before the engine dispatch inside `parent_flow._handle_impl`
(after the under-age-handoff check, before contact-collection) — so it
short-circuits the turn deterministically. Confirmed via a manual probe of
the real code that the trace block for this turn carries NO `answered_by` /
`handler` key at all (the CAVEAT case: this interceptor never calls
`conversation_trace.set(answered_by=...)`), which is exactly why the
engine-invocation spy (not trace inspection alone) is the reliable signal
this instrument relies on.
"""
from __future__ import annotations


def test_answered_by_reports_interceptor_when_short_circuited():
    from evals import interception

    r = interception.answered_by_message("მენეჯერის ნომერი მინდა")

    assert r["reached_llm"] is False
    assert r["handler"] != "engine"


def test_interception_rate_aggregates():
    from evals import interception

    s = [
        {"handler": "engine", "reached_llm": True},
        {"handler": "_maybe_handle_camp_intro", "reached_llm": False},
        {"handler": "engine", "reached_llm": True},
    ]
    a = interception.interception_rate(s)

    assert a["reached_llm"] == 2 and a["intercepted"] == 1
    assert abs(a["pct_reached_llm"] - 2 / 3) < 1e-6
    assert a["by_handler"]["_maybe_handle_camp_intro"] == 1


def test_interception_rate_handles_empty_samples():
    from evals import interception

    a = interception.interception_rate([])

    assert a == {
        "intercepted": 0,
        "reached_llm": 0,
        "pct_reached_llm": 0.0,
        "by_handler": {},
    }


def test_answered_by_reaches_engine_for_a_generic_mid_conversation_question():
    """Positive control: a conversation PAST the first turn (so the
    state=START static-welcome interceptor cannot fire) asking something no
    deterministic `_maybe_*` handler recognises reaches the engine — proving
    the spy correctly detects the engine-reached case, not just the
    interceptor-reached case in the test above."""
    from evals.harness import Harness
    from evals import interception, safety

    h = Harness(safety.SideEffectLog(), llm_enabled=False, judge_enabled=False)
    conv = h.seed(segment="PARENT", state="ASK_CHALLENGE", child_age="13")

    r = interception.answered_by(conv, "გამარჯობა")

    assert r["reached_llm"] is True
    assert r["handler"] == "engine"


def test_read_only_guard_settings_do_not_leak_after_answered_by_message():
    """The guard installed inside `answered_by_message` must be fully
    restored afterwards — a later, unrelated caller must see whatever
    `app.config.settings` had before this test ran, not a forced
    USE_PARENT_LLM_ENGINE=True / CONVERSATION_TRACE_DEBUG=True left behind."""
    import app.config as config_module

    before = config_module.settings

    from evals import interception

    interception.answered_by_message("მადლობა")

    assert config_module.settings is before
