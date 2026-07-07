"""Self-tests for the persona multi-turn SIMULATION harness (evals/simulation.py).

These are DETERMINISTIC — NO live LLM. Every external dependency of the driver
(user_sim, the engine `process`, the Claude judge, the grammar evaluator, the
trace) is stubbed via `SimDeps`, so the harness itself is proven trustworthy
without spending a cent or touching the network.

Proven here:
  * the driver runs a fixed scripted conversation end-to-end + records handlers,
  * an injected adult-misroute reply is caught by the invariant check,
  * an injected age-reask (with a saved child_age) is caught,
  * a template-missed case is flagged,
  * an off_topic persona whose (stub) agent ANSWERS the math is a FAIL, and one
    that DECLINES is a PASS,
  * the READ-ONLY guard stays green (0 side-effects) — the driver never reaches
    any real Calendar / Sheets / Meta service.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.lead import Lead
from evals import personas as personas_mod
from evals import safety, simulation
from evals.simulation import SimDeps, run_conversation
from evals.personas import get_persona


# ── scripted-deps builder ─────────────────────────────────────────────────────
def _make_deps(user_msgs, replies, *, lead=None, blocks=None,
               judge_fn="pass", grammar_fn="pass", facts=None, mutations=None):
    """Build a fully-scripted SimDeps. `judge_fn`/`grammar_fn` accept the string
    "pass" (all-pass stub), None (skip), or a real callable."""
    lead = lead or Lead(sender_id="x", platform="messenger", segment="PARENT")

    def seed_fn(sid):
        return SimpleNamespace(sender_id=sid, lead=lead)

    umsgs = list(user_msgs)

    def user_responder(persona, transcript, facts_, *, turn_index=0):
        return umsgs[turn_index] if turn_index < len(umsgs) else None

    reps = list(replies)
    muts = list(mutations or [])

    state = {"i": 0}

    def process_fn(conv, msg):
        i = state["i"]
        state["i"] += 1
        if i < len(muts) and muts[i]:
            for k, v in muts[i].items():
                setattr(conv.lead, k, v)
        return reps[i] if i < len(reps) else ""

    blks = list(blocks or [])

    def trace_read():
        i = state["i"] - 1   # last processed turn
        return blks[i] if 0 <= i < len(blks) else None

    def _judge_pass(context, criteria):
        return [(c, True, "ok") for c in criteria]

    def _grammar_pass(reply):
        return [{"id": "spelling", "label": "მართლწერა", "pass": True, "errors": []}]

    jf = _judge_pass if judge_fn == "pass" else judge_fn
    gf = _grammar_pass if grammar_fn == "pass" else grammar_fn

    return SimDeps(
        seed_fn=seed_fn, process_fn=process_fn, trace_reset=lambda: None,
        trace_read=trace_read, user_responder=user_responder,
        judge_fn=jf, grammar_fn=gf, facts=facts or {"price_gel": 2150},
    )


_ENGINE_BLOCK = {"route": "parent_flow", "segment": "PARENT",
                 "answered_by": "parent_llm_engine", "handler": "run_parent_llm_turn"}


# ══════════════════════════ PURE-FUNCTION UNIT TESTS ══════════════════════════
def test_detect_template_intent_maps_price_and_avoids_informacia_falsepos():
    assert simulation.detect_template_intent("რა ღირს ბანაკი?") == "price"
    assert simulation.detect_template_intent("გადანაწილება თუ შეიძლება?") == "installment"
    assert simulation.detect_template_intent("რეგისტრაციის ბმული მომეცი") == "registration"
    assert simulation.detect_template_intent("მენეჯერის ნომერი მინდა") == "manager"
    # „ინფორმაცია" must NOT be read as a registration/„ფორმა" intent.
    assert simulation.detect_template_intent("ინფორმაცია მინდა ბანაკზე") is None


def test_template_satisfied_price_and_manager():
    facts = {"price_gel": 2150, "manager_phone": "558 67 47 33",
             "registration_url": "https://tinyurl.com/36jcae8z"}
    assert simulation.template_satisfied("price", "ფასი 2150 ₾-ია", facts)
    assert not simulation.template_satisfied("price", "ფასი ხელმისაწვდომია", facts)
    assert simulation.template_satisfied("manager", "მენეჯერი: 558 67 47 33", facts)
    assert simulation.template_satisfied(
        "registration", "აი ბმული https://tinyurl.com/36jcae8z", facts)


def test_handler_kind_engine_vs_deterministic_vs_adult():
    assert simulation.handler_kind(_ENGINE_BLOCK) == "engine"
    assert simulation.handler_kind({"route": "parent_flow"}) == "deterministic"
    assert simulation.handler_kind({"route": "adult_flow"}) == "adult"
    assert simulation.handler_kind(None) == "no-trace"


def test_phone_echo_invariant_flags_clear_not_masked():
    lead = Lead(sender_id="x", platform="messenger", segment="PARENT", phone="595999733")
    p = get_persona("booking_flow")
    # clear echo → breach
    assert "invariant_leak" in simulation.check_invariants(
        p, "ჩემი ნომერია", "დაგიკავშირდებით ნომერზე 595999733", None, lead)
    # masked echo → clean
    assert "invariant_leak" not in simulation.check_invariants(
        p, "ჩემი ნომერია", "დაგიკავშირდებით ნომერზე 595***733", None, lead)


def test_age_reask_invariant_excuses_new_child():
    p = get_persona("confused_parent")
    lead = Lead(sender_id="x", platform="messenger", segment="PARENT", child_age="13")
    # known age re-asked with no new-child cue → breach
    assert "age_reask" in simulation.check_invariants(
        p, "კიდევ მაქვს კითხვა", "თქვენი შვილი რამდენი წლისაა?", 13, lead)
    # a NEW/second child cue excuses the age question
    assert "age_reask" not in simulation.check_invariants(
        p, "მეორე შვილიც მყავს, 15 წლის", "მეორე შვილი რამდენი წლისაა?", 13, lead)


# ═══════════════════════════════ DRIVER TESTS ═════════════════════════════════
def test_driver_runs_fixed_scripted_conversation_end_to_end():
    p = get_persona("confused_parent")
    deps = _make_deps(
        user_msgs=["გამარჯობა", "ფასი რა ღირს?"],
        replies=["გამარჯობა! რით დაგეხმაროთ?",
                 "ბანაკის ფასი 2150 ₾-ია, გადანაწილება შესაძლებელია."],
        blocks=[_ENGINE_BLOCK, _ENGINE_BLOCK],
    )
    res = run_conversation(p, "sim-x-r0", deps)
    assert not res.errored
    assert len(res.turns) == 2
    assert res.turns[0].handler == "run_parent_llm_turn"
    assert res.turns[0].handler_kind == "engine"
    # price turn used the approved template (contains 2150)
    assert res.turns[1].template_intent == "price"
    assert res.turns[1].template_ok is True
    assert res.passed is True
    assert res.failure_types == set()


def test_injected_adult_misroute_is_caught():
    p = get_persona("confused_parent")
    deps = _make_deps(
        user_msgs=["13 წლის ბავშვი მყავს, ბანაკი მაინტერესებს"],
        replies=["ზრდასრულთა ღონისძიებები გაინტერესებთ?"],  # misroute for a 13yo
        mutations=[{"child_age": "13"}],
        blocks=[_ENGINE_BLOCK],
    )
    res = run_conversation(p, "sim-x-r0", deps)
    assert "adult_misroute" in res.turns[0].breaches
    assert "adult_misroute" in res.failure_types
    assert res.passed is False


def test_injected_age_reask_with_saved_age_is_caught():
    p = get_persona("confused_parent")
    deps = _make_deps(
        user_msgs=["ბავშვი 13 წლისაა", "ფასი როგორია?"],
        replies=["გასაგებია, გმადლობთ.", "თქვენი შვილი რამდენი წლისაა?"],
        mutations=[{"child_age": "13"}, None],
        blocks=[_ENGINE_BLOCK, _ENGINE_BLOCK],
    )
    res = run_conversation(p, "sim-x-r0", deps)
    # age known from turn 0 → re-ask on turn 1 is a breach
    assert "age_reask" in res.failure_types
    assert res.passed is False


def test_template_missed_is_flagged_but_not_a_hard_gate_on_its_own():
    p = get_persona("price_shopper")
    deps = _make_deps(
        user_msgs=["რა ღირს ბანაკი?"],
        replies=["ბანაკი ძალიან საინტერესოა, დაინტერესდით."],   # no 2150 → improvised
        blocks=[_ENGINE_BLOCK],
        facts={"price_gel": 2150},
    )
    res = run_conversation(p, "sim-x-r0", deps)
    assert res.turns[0].template_intent == "price"
    assert res.turns[0].template_ok is False
    assert "template_missed" in res.failure_types
    # template_missed alone (criteria pass, no breach, grammar ok) does NOT fail.
    assert res.passed is True


def test_off_topic_persona_answering_math_is_a_fail():
    p = get_persona("off_topic")
    deps = _make_deps(
        user_msgs=["რამდენია 17 + 25?"],
        replies=["42-ია. ახლა ბანაკზეც შემიძლია დაგეხმაროთ."],
        blocks=[_ENGINE_BLOCK],
    )
    res = run_conversation(p, "sim-x-r0", deps)
    assert res.answered_off_topic is True
    assert "answered_off_topic" in res.failure_types
    assert res.passed is False


def test_off_topic_persona_declining_math_is_a_pass():
    p = get_persona("off_topic")
    deps = _make_deps(
        user_msgs=["რამდენია 17 + 25?"],
        replies=["ბოდიში, ამაზე ვერ დაგეხმარებით — მაგრამ ბანაკზე სიამოვნებით მოგიყვებით."],
        blocks=[_ENGINE_BLOCK],
    )
    res = run_conversation(p, "sim-x-r0", deps)
    assert res.answered_off_topic is False
    assert res.passed is True


def test_errored_engine_turn_marks_conversation_errored_not_passed():
    p = get_persona("confused_parent")

    def boom(conv, msg):
        raise RuntimeError("engine exploded")

    deps = _make_deps(user_msgs=["გამარჯობა"], replies=["x"])
    deps.process_fn = boom
    res = run_conversation(p, "sim-x-r0", deps)
    assert res.errored is True
    assert res.passed is False
    assert "other" in res.failure_types


def test_judge_disabled_marks_criteria_skipped_and_does_not_silently_pass_as_quality():
    p = get_persona("confused_parent")
    deps = _make_deps(
        user_msgs=["გამარჯობა"], replies=["გამარჯობა!"],
        blocks=[_ENGINE_BLOCK], judge_fn=None, grammar_fn=None,
    )
    res = run_conversation(p, "sim-x-r0", deps)
    # criteria are recorded as skipped (None), never a silent True.
    assert all(passed is None for _c, passed, _r in res.criteria)
    # with judge/grammar off, an in-domain conv passes on invariants alone.
    assert res.passed is True


# ═══════════════════════════════ AGGREGATION ══════════════════════════════════
def test_summarize_splits_two_readiness_numbers():
    good_in = get_persona("confused_parent")
    off = get_persona("off_topic")
    r_pass_in = run_conversation(good_in, "a", _make_deps(
        ["გამარჯობა"], ["გამარჯობა!"], blocks=[_ENGINE_BLOCK]))
    r_fail_off = run_conversation(off, "b", _make_deps(
        ["რამდენია 17+25?"], ["42-ია"], blocks=[_ENGINE_BLOCK]))
    rep = simulation.summarize([r_pass_in, r_fail_off])
    assert rep.in_domain_total == 1 and rep.in_domain_passed == 1
    assert rep.off_topic_total == 1 and rep.off_topic_passed == 0
    assert rep.in_domain_pass_rate == 1.0
    assert rep.off_topic_refuse_rate == 0.0
    assert rep.failure_tally["answered_off_topic"] == 1


def test_render_report_is_stringable_and_shows_readiness_numbers():
    r = run_conversation(get_persona("confused_parent"), "a",
                         _make_deps(["გამარჯობა"], ["გამარჯობა!"], blocks=[_ENGINE_BLOCK]))
    rep = simulation.summarize([r])
    text = simulation.render_report(rep, [r], banner="✅ READ-ONLY VERIFIED — test")
    assert "IN-DOMAIN pass-rate" in text
    assert "OFF-TOPIC refuse-rate" in text
    assert "READ-ONLY VERIFIED" in text


# ═══════════════════════════════ READ-ONLY GUARD ═════════════════════════════
def test_readonly_guard_stays_green_driver_touches_no_real_service(monkeypatch):
    """The driver, with everything stubbed, must reach NO real Calendar / Sheets
    / Meta service. We monkeypatch those to tripwires (auto-restored) and assert
    none fire, and that the safety banner reports 0 live calls for an empty log."""
    from app.services import calendar_service, messenger_service, sheets_service

    hits: list[str] = []
    monkeypatch.setattr(messenger_service, "send_message",
                        lambda *a, **k: hits.append("send_message"))
    monkeypatch.setattr(calendar_service, "book_slot",
                        lambda *a, **k: hits.append("book_slot"))
    monkeypatch.setattr(sheets_service, "create_lead",
                        lambda *a, **k: hits.append("create_lead"))

    res = run_conversation(get_persona("confused_parent"), "a",
                           _make_deps(["გამარჯობა", "ფასი?"],
                                      ["გამარჯობა!", "2150 ₾-ია."],
                                      blocks=[_ENGINE_BLOCK, _ENGINE_BLOCK]))
    assert res.passed is True
    assert hits == []   # zero real side effects

    banner = safety.render_banner(safety.SideEffectLog(), llm_used=True, httpx_blocked=False)
    assert "READ-ONLY VERIFIED" in banner
    assert "0 live" in banner


# ═══════════════════════════════ PERSONA SANITY ═══════════════════════════════
def test_ten_personas_nine_in_domain_one_off_topic():
    assert len(personas_mod.PERSONAS) == 10
    in_domain = [p for p in personas_mod.PERSONAS if p.in_domain]
    off = [p for p in personas_mod.PERSONAS if not p.in_domain]
    assert len(in_domain) == 9
    assert len(off) == 1 and off[0].id == "off_topic"
    # every in-domain persona's topics are a subset of the allowed domain.
    for p in in_domain:
        for t in p.allowed_topics:
            assert t in personas_mod.ALLOWED_DOMAIN, (p.id, t)
    # the off_topic persona carries a deterministic math probe.
    assert any(pr.get("answer_re") for pr in off[0].off_topic_probes)
