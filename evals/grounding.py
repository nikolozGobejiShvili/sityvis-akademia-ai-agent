"""Grounding grade — did the reply use the product's real facts and invent
none? (Phase 3.0, Task 4.)

Ground truth = product facts (operator OQ2), never a hand-written answer.
This targets the sharpest 3.0b failure: the engine called `get_camp_info`
then OMITTED the returned price — grounded-but-incomplete, not wrong-but-
confident. `grade_grounding` scores fact coverage (`score`) and separately
VETOES on any invented fact (`grounded=False` regardless of `score`).

LIMITATION (read before trusting this in a report): this is a CHEAP,
DETERMINISTIC, STRUCTURAL substring check — a fact "counts" if its token
appears in the reply text outside a narrow negation window. It is NOT a
semantic/entailment check and NOT a responsiveness judge: it cannot tell
"the price is 480" from "the price is NOT 480 dollars, it's 480 lari" if
both surface the same digits without a directly-adjacent negation particle,
and it cannot tell whether the reply actually ANSWERED the question that was
asked (see docs/MEASURE_PHASE3_0_BASELINE.md — responsiveness is judge-only,
paid, gated). Use this to catch the Q2-class omission/invention failures; use
the LLM judge (evals/judge.py) for "did it actually answer the question."

Negation guard: a fact token immediately preceded (within ~3 whitespace
chars, in the SAME clause — i.e. no ".", ",", "!", "?", ";" or newline in
between) by a Georgian negation particle ("არა" / "არ" / "აღარ") is treated
as NOT present for that occurrence. `"480" in "არა 480 არ ღირს"` must not
count "480" as present — this is exactly that case. A fact with at least one
non-negated occurrence still counts as present.
"""
from __future__ import annotations

import re

_NEGATIONS: tuple[str, ...] = ("არა", "არ", "აღარ")
_CLAUSE_BOUNDARIES = ".,!?;\n"
_LOOKBACK_WINDOW = 20   # chars of context scanned before a fact occurrence
_MAX_GAP = 3            # max whitespace chars between the negation word and the fact


def _clause_tail(prefix: str) -> str:
    """The portion of `prefix` since the last clause boundary, capped to a
    short lookback window (negation must be structurally close, not just
    somewhere earlier in the reply)."""
    tail = prefix[-_LOOKBACK_WINDOW:]
    for boundary in _CLAUSE_BOUNDARIES:
        idx = tail.rfind(boundary)
        if idx != -1:
            tail = tail[idx + 1:]
    return tail


def _is_negated_occurrence(text: str, start: int) -> bool:
    """True when a Georgian negation particle sits immediately before
    `text[start:]`, within `_MAX_GAP` whitespace chars, in the same clause."""
    tail = _clause_tail(text[:start])
    for neg in _NEGATIONS:
        pattern = re.escape(neg) + r"\s{0,%d}$" % _MAX_GAP
        m = re.search(pattern, tail)
        if m is None:
            continue
        # Word-boundary guard: `neg` must not itself be the tail of a longer
        # word (e.g. "...მარ" + "არ" false match) — the char right before
        # the match must be non-alphanumeric or the match is at position 0.
        if m.start() == 0 or not tail[m.start() - 1].isalnum():
            return True
    return False


def _fact_present(text: str, fact: str) -> bool:
    """True when `fact` occurs in `text` at least once OUTSIDE a negation
    window (see module docstring)."""
    if not fact:
        return False
    start = 0
    while True:
        idx = text.find(fact, start)
        if idx == -1:
            return False
        if not _is_negated_occurrence(text, idx):
            return True
        start = idx + 1


def grade_grounding(reply: str, facts: list[str], forbidden: list[str]) -> dict:
    """Grade `reply` against `facts` (this product's real facts — presence
    is good) and `forbidden` (another product's facts — presence is an
    invention, VETO).

    Returns ``{"grounded": bool, "facts_present": [...], "facts_missing":
    [...], "inventions": [...], "score": float}`` where ``score`` is the
    fraction of `facts` present (negation-aware) and ``grounded`` is
    ``(>=1 required fact present) AND (no forbidden invention present)`` —
    an invention VETOES grounding regardless of how high `score` is.
    """
    text = reply or ""
    present = [f for f in facts if f and _fact_present(text, f)]
    missing = [f for f in facts if f and f not in present]
    # Inventions are checked as a PLAIN substring (no negation guard): even a
    # negated mention of another product's fact ("it's not 2150") means the
    # model is discussing facts that don't belong to this product at all —
    # the veto list is deliberately strict, not negation-aware.
    inventions = [f for f in forbidden if f and f in text]
    score = (len(present) / len(facts)) if facts else 0.0
    grounded = (len(present) >= 1) and (len(inventions) == 0)
    return {
        "grounded": grounded,
        "facts_present": present,
        "facts_missing": missing,
        "inventions": inventions,
        "score": score,
    }
