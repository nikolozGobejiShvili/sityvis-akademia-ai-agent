"""NATURALNESS judge (Claude / Anthropic) — Phase 1 Task 3.

A SEPARATE strict rubric from `evals.judge.judge` (response_quality) and from
`evals.judge.grade_grammar` (Georgian grammar) — mirrors the grammar grader's
"own function, own criteria list" pattern. Never mixed into another rubric.

Scores whether an agent reply reads like a human consultant rather than a
scripted/templated bot, across 4 binary criteria (score = count met, 0-4):
  (a) reads like a human consultant, not a template
  (b) no robotic canned-menu phrasing
  (c) varied / context-fit wording, not a stock phrase
  (d) warm consultative tone appropriate to a parent

Grounding (Task 3 Step 1 — studied `evals/judge.py` before writing this):
  * `judge_available()` is the ONE canonical availability check (anthropic SDK
    importable + ANTHROPIC_API_KEY set) — reused here as `_judge_available`,
    not reinvented.
  * `judge()` / `grade_grammar()` each construct their OWN `anthropic.Anthropic()`
    client per call (judge.py holds no shared client singleton) and share the
    same `_JUDGE_MODEL` constant. `_judge_naturalness_once` below follows the
    identical construction pattern + reuses `_JUDGE_MODEL`, so this module
    never introduces a second judge model / a new dependency.
  * confirmed by reading: NEITHER `judge()` nor `_grammar_completion()` passes
    `temperature=` to `client.messages.create(...)` (Anthropic defaults to a
    non-zero sampling temperature). So temp=0 is NOT already enforced by the
    existing judge — this module passes `temperature=0` explicitly on its own
    `client.messages.create(...)` call, and additionally runs the judge `N`
    times (default 3) and reduces to the MEDIAN per-run score, so a single
    run's residual stochasticity can never decide the metric (fix C1).

Fail-safe, matching judge.py's contract: if the SDK/key is unavailable, OR
every run raises, `grade_naturalness` returns `score=None` — an explicit SKIP,
never a fake 0. `grade_naturalness` never raises.
"""
from __future__ import annotations

import json
import statistics
from typing import Any

from evals.judge import judge_available as _judge_available  # reuse, don't reinvent
from evals.judge import _JUDGE_MODEL  # reuse the same judge model config


# (id, short label shown in issues, exact criterion sent to the judge)
NATURALNESS_CRITERIA: list[tuple[str, str, str]] = [
    ("human_consultant", "ადამიანი-კონსულტანტი",
     "პასუხი ჟღერს როგორც ცოცხალი ადამიანი-კონსულტანტი, არა შაბლონური/templated "
     "ტექსტი, რომელიც ნებისმიერ მომხმარებელს ერთნაირად გაეგზავნებოდა."),
    ("no_canned_menu", "არა-კანონიკური მენიუ",
     "პასუხს არ აქვს რობოტული, canned-menu-ისებრი ფრაზირება (მექანიკური, უსულო "
     "ჩამონათვალი ვარიანტების/ღილაკების სტილში)."),
    ("varied_wording", "მრავალფეროვანი ფორმულირება",
     "სიტყვები/ფრაზები კონკრეტულ კონტექსტს შეესაბამება და არ არის stock/repeated "
     "ფრაზა, რომელიც იდენტურად გამოჩნდებოდა ნებისმიერ სხვა კონტექსტში."),
    ("warm_tone", "თბილი კონსულტაციური ტონი",
     "ტონი თბილი და კონსულტაციურია, შესაფერისი მშობელთან საუბრისთვის — არა "
     "ცივი, მშრალი ან გაყიდვითი წნეხის ქვეშ მყოფი."),
]

_NATURALNESS_SYSTEM = (
    "You are a STRICT evaluator of NATURALNESS for a Georgian-language sales "
    "agent's reply — whether it reads like a genuine human consultant rather "
    "than a scripted/templated bot. For each criterion answer ONLY whether it "
    "is satisfied. Be conservative: if uncertain, fail it. Judge solely the "
    "criterion stated, in Georgian context. Return STRICT JSON: a list where "
    'each item is {"index": <int>, "pass": <true|false>, "reason": "<short '
    'Georgian/English>"}.'
)


def _judge_naturalness_once(context: str, response: str) -> list[tuple[str, bool, str]]:
    """One judge run against NATURALNESS_CRITERIA at temperature=0. Returns a
    list aligned to NATURALNESS_CRITERIA: [(label, passed, note), ...].

    Raises only on a hard SDK/transport/parse error — `grade_naturalness`
    treats a raised run as a dropped run and continues with the remaining
    runs (never lets one bad run corrupt or crash the whole metric)."""
    import anthropic

    client = anthropic.Anthropic()
    numbered = "\n".join(
        f"{i}. {label}: {crit}" for i, (_cid, label, crit) in enumerate(NATURALNESS_CRITERIA)
    )
    user = (
        f"CONTEXT (conversation excerpt):\n{context}\n\n"
        f"AGENT REPLY TO EVALUATE:\n{response}\n\n"
        f"CRITERIA (binary, judge each independently):\n{numbered}\n\n"
        "Return the JSON list now."
    )
    resp = client.messages.create(
        model=_JUDGE_MODEL,
        max_tokens=1024,
        temperature=0,  # deterministic per-call; N-run median in grade_naturalness
        system=_NATURALNESS_SYSTEM,  # controls residual sampling stochasticity (fix C1)
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    start, end = text.find("["), text.rfind("]")
    parsed = json.loads(text[start:end + 1]) if start != -1 and end != -1 else []
    by_index = {int(item.get("index", -1)): item for item in parsed if isinstance(item, dict)}
    out: list[tuple[str, bool, str]] = []
    for i, (_cid, label, _crit) in enumerate(NATURALNESS_CRITERIA):
        item = by_index.get(i, {})
        out.append((label, bool(item.get("pass", False)), str(item.get("reason", "no verdict"))))
    return out


def grade_naturalness(context: str, response: str, *, runs: int = 3) -> dict[str, Any]:
    """STRICT NATURALNESS rubric via the SAME Claude judge client/model as
    `evals.judge`, at `temperature=0`, run `runs` times (default 3) with the
    MEDIAN per-run score returned — a single run is NEVER the returned score
    (controls residual judge stochasticity, Task 3 fix C1).

    Returns {"score": int 0-4 | None, "issues": [str], "runs": int}.
    `score=None` is an explicit SKIP (judge SDK/key unavailable, or every run
    failed) — NEVER a fake 0. Never raises.
    """
    try:
        available, _reason = _judge_available()
    except Exception:
        available = False
    if not available:
        return {"score": None, "issues": [], "runs": 0}

    run_results: list[list[tuple[str, bool, str]]] = []
    for _ in range(max(1, runs)):
        try:
            run_results.append(_judge_naturalness_once(context, response))
        except Exception:
            continue  # one failed run is dropped; the rest still aggregate

    if not run_results:
        return {"score": None, "issues": [], "runs": 0}

    scores = [sum(1 for _label, passed, _note in run if passed) for run in run_results]
    median_score = int(round(statistics.median(scores)))

    issues: list[str] = []
    for run in run_results:
        for label, passed, note in run:
            if not passed:
                text = f"{label}: {note}" if note else label
                if text not in issues:
                    issues.append(text)

    return {"score": median_score, "issues": issues, "runs": len(run_results)}
