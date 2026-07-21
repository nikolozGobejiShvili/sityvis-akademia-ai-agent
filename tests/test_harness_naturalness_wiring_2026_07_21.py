"""Harness naturalness wiring (2026-07-21, validation-loop fix).

`--llm --judge` now also grades bot-vs-human NATURALNESS via the OpenAI judge,
parallel to the Georgian-grammar grader. Deterministic (grade_naturalness
stubbed) — proves gating, one-reply-per-case dedupe, mean aggregation, and that
a per-case SKIP is COUNTED, never scored as a fake 0.
"""
from __future__ import annotations

from types import SimpleNamespace

from evals import harness


def _h(responses):
    return SimpleNamespace(responses=responses)


def test_gating_needs_llm():
    n = harness._grade_naturalness(_h([]), llm=False, judge_requested=True, judge_enabled=True)
    assert n["status"] == "N/A (needs --llm)"


def test_gating_needs_judge():
    n = harness._grade_naturalness(_h([]), llm=True, judge_requested=False, judge_enabled=True)
    assert n["status"] == "N/A (needs --judge)"


def test_gating_judge_disabled():
    n = harness._grade_naturalness(_h([]), llm=True, judge_requested=True, judge_enabled=False)
    assert n["status"].startswith("JUDGE-SKIPPED")


def test_scored_mean_and_dedupe(monkeypatch):
    calls = []

    def _fake(ctx, resp, **kw):
        calls.append((ctx, resp))
        warm = "warm" in resp
        return {"score": 4 if warm else 1,
                "issues": [] if warm else ["canned/menu phrasing"], "runs": 3}

    monkeypatch.setattr("evals.naturalness.grade_naturalness", _fake)
    h = _h([
        ("OB1", "ძვირია", "warm human reply"),
        ("OB1", "და კიდევ?", "warm second reply"),   # same case → deduped
        ("OB2", "მოვიფიქრებ", "canned bot reply"),
    ])
    n = harness._grade_naturalness(h, llm=True, judge_requested=True, judge_enabled=True)

    assert n["status"] == "scored"
    assert n["replies"] == 2                 # one representative per case
    assert n["score_sum"] == 5               # 4 (OB1) + 1 (OB2)
    assert len(calls) == 2                   # OB1's second reply skipped (dedupe)
    assert any("OB2" in b for b in n["blocks"])   # the canned tell surfaced


def test_per_case_skip_not_fake_zero(monkeypatch):
    monkeypatch.setattr("evals.naturalness.grade_naturalness",
                        lambda ctx, resp, **kw: {"score": None, "issues": [], "runs": 0})
    h = _h([("OB1", "ძვირია", "some reply")])
    n = harness._grade_naturalness(h, llm=True, judge_requested=True, judge_enabled=True)

    assert n["replies"] == 0 and n["skipped"] == 1
    assert n["score_sum"] == 0               # counted as skip, NOT a fake 0 in the mean
    assert n["status"].startswith("JUDGE-SKIPPED")
