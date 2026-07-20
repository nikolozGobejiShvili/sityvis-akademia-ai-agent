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


def test_answered_by_does_not_leak_conversation_into_global_store():
    # review fix #2: driving a turn must not leave the fake eval conversation
    # in conversation_service.conversations (latent test-order hazard).
    from app.services import conversation_service
    from evals import interception
    before = dict(conversation_service.conversations)
    interception.answered_by_message("მენეჯერის ნომერი მინდა")
    after = dict(conversation_service.conversations)
    assert set(after) == set(before), "eval conversation leaked into the global store"


def test_guarded_turn_spies_adult_engine_for_readonly():
    # review fix #1: the ADULT engine must also be spied so a non-PARENT turn
    # can never reach live OpenAI.
    from evals import interception
    with interception._GuardedTurn():
        adult = interception._resolve(interception._ADULT_ENGINE_MODULE)
        assert getattr(adult, interception._ADULT_ENGINE_ATTR).__name__ == "_adult_spy"
    # restored after the guard exits
    adult2 = interception._resolve(interception._ADULT_ENGINE_MODULE)
    assert getattr(adult2, interception._ADULT_ENGINE_ATTR).__name__ != "_adult_spy"


# ---------------------------------------------------------------------------
# Task 2 — canned/botlike-footprint proxy (`evals/botlike_proxy.py`)
#
# FREE, deterministic, no-API signal. See the module docstring for the
# marker-source rationale (the static PARENT welcome menu + a curated,
# stable subset of `parent_llm_engine.FORBIDDEN_PHRASE_REPLACEMENTS`'
# right-hand-side values). These two tests are the ones named in the Task 2
# brief; the "natural" reply below was checked against the full curated
# marker list to confirm it is genuinely free of every chosen marker.
# ---------------------------------------------------------------------------


def test_canned_footprint_flags_menu_and_stock():
    from evals import botlike_proxy

    fp = botlike_proxy.canned_footprint("ბანაკი თუ ზრდასრულთა ღონისძიება?")  # menu-like
    assert fp["footprint"] >= 1
    assert fp["canned_menu"] is True

    natural = botlike_proxy.canned_footprint(
        "რა თქმა უნდა, სიამოვნებით მოგიყვებით — რა გაინტერესებთ ბანაკზე?",
    )
    assert natural["footprint"] == 0
    assert natural["canned_menu"] is False
    assert natural["sanitizer_hits"] == 0
    assert natural["stock_phrase_hits"] == 0


def test_canned_footprint_handles_none_and_empty_without_raising():
    from evals import botlike_proxy

    for bad in (None, ""):
        fp = botlike_proxy.canned_footprint(bad)
        assert fp == {
            "sanitizer_hits": 0,
            "canned_menu": False,
            "stock_phrase_hits": 0,
            "footprint": 0,
        }


def test_botlike_proxy_score_aggregates():
    from evals import botlike_proxy

    s = botlike_proxy.botlike_proxy_score(["ბანაკი თუ ღონისძიება?", "სუფთა ბუნებრივი პასუხი"])
    assert 0.0 <= s["canned_menu_rate"] <= 1.0 and s["n"] == 2


def test_botlike_proxy_score_empty_list_returns_zeros_never_raises():
    from evals import botlike_proxy

    s = botlike_proxy.botlike_proxy_score([])
    assert s == {"avg_footprint": 0.0, "canned_menu_rate": 0.0, "n": 0}


# ---------------------------------------------------------------------------
# Task 3 — NATURALNESS judge (`evals/naturalness.py`)
#
# Mocked/offline — `_judge_naturalness_once` and `_judge_available` are
# monkeypatched so these run free, deterministic, with no live Claude call.
# See the module docstring for the temp=0 + N-run-median rationale (fix C1)
# and the score=None-on-unavailable (skip, never fake-0) contract.
# ---------------------------------------------------------------------------


def test_grade_naturalness_majority_of_runs(monkeypatch):
    from evals import naturalness

    calls = {"n": 0}

    def _one(ctx, resp):
        calls["n"] += 1
        return [("a", True, ""), ("b", True, ""), ("c", True, ""), ("d", False, "flat")]

    monkeypatch.setattr(naturalness, "_judge_naturalness_once", _one)
    monkeypatch.setattr(naturalness, "_judge_available", lambda: (True, ""))

    out = naturalness.grade_naturalness("ctx", "resp", runs=3)

    assert out["score"] == 3 and calls["n"] == 3


def test_grade_naturalness_unavailable_is_skip(monkeypatch):
    from evals import naturalness

    monkeypatch.setattr(naturalness, "_judge_available", lambda: (False, "no key"))

    assert naturalness.grade_naturalness("c", "r")["score"] is None


def test_grade_naturalness_median_across_varying_runs(monkeypatch):
    # review Minor: prove MEDIAN aggregation (not first/last-run) with per-call
    # VARYING scores. Scores [2,3,4] -> median 3 (a last-run bug would give 4).
    from evals import naturalness
    seq = iter([
        [("a", True, ""), ("b", True, ""), ("c", False, ""), ("d", False, "")],   # 2
        [("a", True, ""), ("b", True, ""), ("c", True, ""), ("d", False, "")],    # 3
        [("a", True, ""), ("b", True, ""), ("c", True, ""), ("d", True, "")],     # 4
    ])
    monkeypatch.setattr(naturalness, "_judge_available", lambda: (True, ""))
    monkeypatch.setattr(naturalness, "_judge_naturalness_once", lambda c, r: next(seq))
    out = naturalness.grade_naturalness("ctx", "resp", runs=3)
    assert out["score"] == 3  # median of {2,3,4}, NOT 4 (last) or 2 (first)


def test_grade_naturalness_runs_zero_makes_no_call(monkeypatch):
    # review Important: runs<=0 must skip with zero paid calls.
    from evals import naturalness
    called = {"n": 0}
    def _boom(c, r):
        called["n"] += 1
        raise AssertionError("must not be called when runs<=0")
    monkeypatch.setattr(naturalness, "_judge_available", lambda: (True, ""))
    monkeypatch.setattr(naturalness, "_judge_naturalness_once", _boom)
    out = naturalness.grade_naturalness("ctx", "resp", runs=0)
    assert out == {"score": None, "issues": [], "runs": 0}
    assert called["n"] == 0


# ---------------------------------------------------------------------------
# Task 4 — per-domain tags + guardrail-vs-advisory coverage cases
# (`evals/cases.py`)
#
# `EvalCase` (defined in evals/harness.py) is a plain, non-frozen, non-slotted
# dataclass with no `domain` field. Task 4 does not touch harness.py, so
# `evals/cases.py` tags cases by assigning `case.domain = "..."` as an ordinary
# post-construction instance attribute (see `_DOMAIN_TAGS` at the bottom of
# that file) — readable via `getattr(case, "domain", None)` exactly like a
# real dataclass field. This smoke test is the one named in the Task 4 brief.
# ---------------------------------------------------------------------------


def test_domain_coverage_present():
    from evals import cases

    doms = set()
    for c in cases.CASES:
        d = getattr(c, "domain", None) if not isinstance(c, dict) else c.get("domain")
        if d:
            doms.add(d)
    for d in ("objection", "camp_topic", "program_info", "booking_reliability", "contact_capture"):
        assert d in doms, f"missing domain coverage: {d}"


# ---------------------------------------------------------------------------
# Task 5 — Phase-1 baseline report generator (`evals/phase1_report.py`)
#
# FREE, deterministic, fully offline — every turn driven here goes through
# the SAME read-only guard + engine spy the Task 1 interception instrument
# already uses (see evals/interception.py), so no live OpenAI/Anthropic call
# is ever made. Nothing here is mocked to fake "free" — it already is.
#
# `generate_phase1_report()` writes NOTHING by itself; only
# `write_phase1_baseline()` touches disk, and only
# evals/phase1_baseline.json — the original evals/baseline.json (the 90/100
# `--llm --judge` decision-quality reference) must stay byte-identical.
# ---------------------------------------------------------------------------


def test_generate_phase1_report_has_expected_keys():
    from evals import phase1_report

    report = phase1_report.generate_phase1_report()

    for key in ("interception", "canned_footprint", "naturalness", "per_domain", "generated_at", "note"):
        assert key in report, f"missing key: {key}"


def test_generate_phase1_report_interception_pct_is_a_fraction():
    from evals import phase1_report

    report = phase1_report.generate_phase1_report()

    pct = report["interception"]["pct_reached_llm"]
    assert isinstance(pct, float)
    assert 0.0 <= pct <= 1.0

    # the exact 4-key interception_rate() shape is present at the top level
    for key in ("intercepted", "reached_llm", "pct_reached_llm", "by_handler"):
        assert key in report["interception"]


def test_generate_phase1_report_naturalness_is_null_offline():
    # naturalness is a PAID Claude judge (evals.naturalness) — this module
    # makes no Anthropic call, so it must always be explicit None, never a
    # fabricated score.
    from evals import phase1_report

    report = phase1_report.generate_phase1_report()

    assert report["naturalness"] is None


def test_generate_phase1_report_per_domain_matches_cases_domains():
    from evals import cases, phase1_report

    report = phase1_report.generate_phase1_report()

    expected_domains = {getattr(c, "domain", "") or "untagged" for c in cases.CASES}
    assert set(report["per_domain"]) == expected_domains
    assert sum(report["per_domain"].values()) == len(cases.CASES)


def test_generate_phase1_report_never_raises_and_stays_read_only():
    # Driving ~37 turns must not leak the eval conversations into the global
    # in-memory store (mirrors the Task 1 leak-guard test above) and must not
    # raise even though nothing here is mocked.
    from app.services import conversation_service
    from evals import phase1_report

    before = dict(conversation_service.conversations)
    report = phase1_report.generate_phase1_report()  # must not raise
    after = dict(conversation_service.conversations)

    assert report is not None
    assert set(after) == set(before), "phase1 report leaked a conversation into the global store"


def test_write_phase1_baseline_never_touches_original_baseline_json():
    # The hard invariant of Task 5: evals/baseline.json (the 90/100 reference)
    # must be byte-identical before and after generating phase1_baseline.json.
    # write_phase1_baseline() targets the real repo path by design (it's a
    # committed artifact, re-generated as part of the normal Task 5
    # workflow) — this test verifies the ONE file it must never touch.
    from pathlib import Path

    import evals.phase1_report as phase1_report_module
    from evals import phase1_report

    baseline_path = Path(phase1_report_module.__file__).resolve().parent / "baseline.json"
    before = baseline_path.read_bytes() if baseline_path.exists() else None

    written = phase1_report.write_phase1_baseline(
        phase1_report.generate_phase1_report(),
    )

    assert written.name == "phase1_baseline.json"
    assert written != baseline_path
    after = baseline_path.read_bytes() if baseline_path.exists() else None
    assert before == after, "evals/baseline.json was modified — must stay untouched"
