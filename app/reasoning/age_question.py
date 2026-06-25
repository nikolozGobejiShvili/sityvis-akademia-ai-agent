"""Shared child-age-QUESTION matcher (Phase 1 fix, 2026-06-24).

ONE regex used by BOTH the engine anti-repeat guard
(`parent_llm_engine._suppress_redundant_age_question`) and the central
validator (`parent_flow.planner_final_validate`), replacing the two narrow
substring tuples that were the direct cause of the live „re-asks the child's
age" bug (§0-A of the fix plan).

The narrow tuples only caught „რამდენი წლის" / „რა ასაკის". A real
gpt-4.1-mini asks the age many other ways in Georgian — „რა წლისაა ბავშვი",
„რამდენ წლისაა" (no trailing ი), „ბავშვის ასაკი მითხარით", „შვილი რომელ
კლასშია" — all of which slipped past the tuples and reached the user.

This regex RECOGNISES those real question forms but does NOT match an
ELIGIBILITY STATEMENT like „9–17 წლის ბავშვებისთვის" (it has no
„რა"/„რამდენ" + „წლ" pair), so it never corrupts a camp-eligibility answer.

Defined in its own tiny module so both consumers can import it at module load
without any circular-import risk.
"""
from __future__ import annotations

import re

# Recognises the real Georgian forms of "what age is the child?":
#   რამდენი/რამდენ წლისაა · რა წლისაა · რა ასაკისაა ·
#   ასაკი მითხარით/მეტყვით/გვითხარით/მაინტერესებს/დამიდასტურეთ/ასაკი რა ·
#   რომელ/რა კლასში (class = an age proxy)
# Does NOT match „9–17 წლის ბავშვებისთვის" (no „რა/რამდენ" + „წლ").
AGE_QUESTION_RE = re.compile(
    r"(რამდენ[ი]?\s*წლ)"          # რამდენი/რამდენ წლისაა
    r"|(რა\s*წლ)"                  # რა წლისაა
    r"|(რა\s*ასაკ)"               # რა ასაკისაა
    r"|(ასაკ\w*\s*(მითხ|მეტყ|გვითხ|მაინტერ|დამიდასტ|რა\b))"  # ასაკი მითხარით / ასაკი რა
    r"|((რომელ|რა)\s*კლას)"        # კლასი = ასაკის proxy
)

# Sentence terminators used by the sentence-level stripper.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")


def contains_child_age_question(text: str) -> bool:
    """True when ``text`` contains a child-age QUESTION in any of the real
    Georgian forms (r`AGE_QUESTION_RE`). An eligibility STATEMENT
    („9–17 წლის ბავშვებისთვის") is NOT a question and returns False."""
    return bool(AGE_QUESTION_RE.search((text or "").lower()))


def strip_child_age_questions(response: str) -> str:
    """Remove only the sentence(s) that ask the child's age, keeping the rest
    of the answer intact. Sentence-level so a useful fact answer survives
    („ბანაკში სხვადასხვა აქტივობაა. რა წლისაა ბავშვი?" → „ბანაკში სხვადასხვა
    აქტივობაა."). Returns "" only when the whole response WAS an age question —
    the caller decides the replacement."""
    if not response:
        return response
    kept = [
        s for s in _SENTENCE_SPLIT_RE.split(response)
        if s.strip() and not AGE_QUESTION_RE.search(s.lower())
    ]
    return " ".join(kept).strip()
