# Phase 3.0 — Eval Instrument Rebuild + Metric + Baseline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the evaluation harness into a VALID instrument for the Phase 3 rebuild — one that measures whether the LLM *reasons over product facts and calls tools* (EFFECT), not whether a canned string appears (TEXT) — and capture the per-domain canned baseline that polarity inversion must beat.

**Architecture:** Phase 3.0 is measurement-only: it changes **no `app/` production code**. All work is additive tooling under `evals/`. It adds three capabilities the current harness lacks — (1) an assertion that a case actually reached the LLM engine, (2) an assertion that a tool actually *ran* (not that its name appeared in the reply), and (3) a *grounding* grade that checks the reply used the product's real facts and invented none — then builds a small multi-turn, multi-product, camp-season-independent case set on those, and captures the canned baseline.

**Tech Stack:** Python 3.10, pytest. Eval judge is OpenAI `gpt-5.4-mini` (`EVAL_JUDGE_BACKEND=openai`, default). No new dependency. No agent-model change.

## Global Constraints

- **NO `app/` production code changes.** Phase 3.0 is instrument-only. Every file created/modified lives under `evals/` or `tests/`. If a task seems to need an `app/` change, stop and report — it belongs to Phase 3.1+, not here.
- **Protect `evals/baseline.json`** — md5 `93973fcd10349b447f87fa320e0807f3`. It is untracked/gitignored; git will not protect it. Snapshot before any `--llm` run, restore after, verify md5. Never commit it. `run_all(..., llm=True)` overwrites it — any paid run must snapshot+restore around it.
- **Camp is NOT a live product** (operator decision 2026-07-22). The camp season ended 2026-07-20, so any case that depends on live camp streams is confounded by the registration-closed fallback. New cases MUST use the synthetic product fixture (Task 3), never a real seasonal camp stream.
- **Ground truth is PRODUCT FACTS, not hand-written answers** (operator OQ2). A case asserts *the reply used the correct facts + invented nothing + answered the question* — never *the reply equals string X*. Authoring per-question model answers is forbidden: it re-creates the template pathology being removed.
- **Effect, not text** (the R4 lesson). An effect-case asserts the tool actually ran via `h.last_tool_calls`, never `("word" in reply)`. `OR`-ing a text mention with a tool check is the exact bug being fixed.
- **T1 (per-interceptor attribution) and T3 (exception-list count) are already DONE** — `docs/PHASE3_0_INTERCEPTOR_INVENTORY_2026_07_22.md`, commit `b019959`. Do not redo them. This plan is T2 (eval rebuild) + T4 (metric) + T5 (baseline).
- **Interpreter** `.venv/Scripts/python.exe`. **LOCAL-only** branch `feat/dynamic-programs`; push only with explicit consent. **No haiku for any subagent.**
- **Expected pre-existing failure** (not in scope): `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`. Any OTHER failure is in scope.

---

## File Structure

**Create:**
- `evals/reach.py` — engine-reach + tool-effect assertion helpers (the two anti-confound guards).
- `evals/fixtures_product.py` — the synthetic, season-independent product + its canonical facts.
- `evals/grounding.py` — the grounding grade (reply-uses-real-facts / invents-nothing).
- `evals/cases_v2.py` — the new multi-turn, multi-product, engine-reaching case set.
- `docs/MEASURE_PHASE3_0_BASELINE.md` — the metric definition + per-domain canned baseline + the paid-run runbook.
- `tests/test_eval_reach_2026_07_22.py`, `tests/test_eval_grounding_2026_07_22.py`, `tests/test_cases_v2_2026_07_22.py` — tests for the new tooling.

**Modify:**
- `evals/harness.py` — add an engine-invocation counter (parallel to `last_tool_calls`); wire `cases_v2` into collection behind a flag so it never perturbs the protected `run_all` default.

**Read-only reference (do not modify):** `evals/interception.py` (engine-spy pattern), `evals/cases.py` (the R4 OR-bug + `_DOMAIN_TAGS`), `evals/judge.py` (`_judge_completion`, `judge_available`), `app/reasoning/camp_topic_facts.py` (the topic-facts reader the interceptor delegates to).

---

## Task 1: Engine-reach counter + assertion helper

**Why:** Phase 4 and 3.0b both silently measured deterministic templates because cases never checked they reached the LLM. This task makes "did the engine run this turn?" a first-class, assertable signal.

**Files:**
- Modify: `evals/harness.py` (add `Harness.engine_invocations` counter + spy install)
- Create: `evals/reach.py`
- Test: `tests/test_eval_reach_2026_07_22.py`

**Interfaces:**
- Produces: `Harness.engine_invocations: int` (reset per `process()` call, incremented when the parent LLM engine entrypoint runs). `evals/reach.py::reached_engine(h) -> bool`; `evals/reach.py::chk_reached_engine(h) -> Check` (uses harness `chk`).

- [ ] **Step 1: Read the current spy install.** Read `evals/harness.py:124-150` (the `process` method + the tool-call spy at ~:144) and `evals/interception.py::_install_engine_spy`. The engine entrypoint to count is `app.agent.llm.parent_llm_engine.run_parent_llm_turn` (offline it is spied; with `--llm` it makes the real call — the counter must count in BOTH modes, so wrap-and-delegate, do not replace).

- [ ] **Step 2: Failing test** — `tests/test_eval_reach_2026_07_22.py`:

```python
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
```

- [ ] **Step 3: Run → fail.** `.venv/Scripts/python.exe -m pytest tests/test_eval_reach_2026_07_22.py -q` — expect failures (`engine_invocations` missing / `reach` missing).

- [ ] **Step 4: Implement the counter in `evals/harness.py`.** In `Harness.__init__` add `self.engine_invocations: int = 0`. In `process()`, set `self.engine_invocations = 0` at the same place `self.last_tool_calls = []` is reset. Where the harness installs its tool-call spy, ALSO install an engine spy that increments the counter then delegates:

```python
# in Harness.process(), alongside the existing tool-call spy install:
import app.agent.llm.parent_llm_engine as _ple
_orig_run = _ple.run_parent_llm_turn
def _counting_run(*a, **k):
    h.engine_invocations += 1
    return _orig_run(*a, **k)
_ple.run_parent_llm_turn = _counting_run
try:
    ...  # existing process body
finally:
    _ple.run_parent_llm_turn = _orig_run
```
Match the harness's existing spy install/restore structure exactly (snapshot + `finally` restore) so no global leak — mirror how `last_tool_calls` is wired.

- [ ] **Step 5: Implement `evals/reach.py`:**

```python
"""Engine-reach + tool-effect assertions — the Phase-3.0 anti-confound guards.

reached_engine: did the LLM engine actually run this turn, or did a deterministic
interceptor short-circuit it? A case that means to measure the model MUST assert
this, or it silently grades a template (the Phase-4 / 3.0b failure).
"""
from evals.harness import chk


def reached_engine(h) -> bool:
    return getattr(h, "engine_invocations", 0) >= 1


def chk_reached_engine(h):
    return chk("reached the LLM engine (not a canned interceptor)",
               reached_engine(h), "engine_invocations>=1",
               f"engine_invocations={getattr(h, 'engine_invocations', 0)}")


def tool_ran(h, tool_name: str) -> bool:
    """EFFECT check: the tool actually executed this turn (not merely named in the reply)."""
    return any(t == tool_name for t, _ in getattr(h, "last_tool_calls", []))


def chk_tool_ran(h, tool_name: str):
    tools = [t for t, _ in getattr(h, "last_tool_calls", [])]
    return chk(f"tool `{tool_name}` actually ran (effect, not text)",
               tool_ran(h, tool_name), f"{tool_name} in tool_calls", f"tools={tools}")
```

- [ ] **Step 6: Run → pass.** `.venv/Scripts/python.exe -m pytest tests/test_eval_reach_2026_07_22.py -q`

- [ ] **Step 7: Guard the protected baseline is untouched.** `md5sum evals/baseline.json` → still `93973fcd10349b447f87fa320e0807f3`.

- [ ] **Step 8: Commit** — `feat(evals): engine-reach + tool-effect assertion helpers (anti-confound guards)`

---

## Task 2: Fix the R4 OR-bug — effect, not text

**Why:** `evals/cases.py::_r4_overage_adult_switch` passes on `("ზრდასრულ" in out) OR ("switch_to_adult_flow" in tools)`. The `OR` lets a *mention* of the word substitute for the tool actually running — 3.0b showed a reply scoring 3/3 while `switch_to_adult_flow` never ran and the segment never switched. This task makes the check require the effect, and proves the fix by mutation.

**Files:**
- Modify: `evals/cases.py` (`_r4_overage_adult_switch` only)
- Test: `tests/test_cases_v2_2026_07_22.py` (the R4 regression part)

**Interfaces:**
- Consumes: `evals/reach.py::tool_ran` (Task 1).

- [ ] **Step 1: Read** `evals/cases.py` around line 385-392 (the `_r4_overage_adult_switch` body shown below) to confirm the current `OR`:

```python
def _r4_overage_adult_switch(h):
    ...
    tools = [t for t, _ in h.last_tool_calls]
    suggested = ("ზრდასრულ" in out) or ("კულტურულ" in out) or ("switch_to_adult_flow" in tools)
    return CaseOutcome([chk("age>17 → adult switch / suggestion (not camp-eligible)", suggested, ...)])
```

- [ ] **Step 2: Failing test** — in `tests/test_cases_v2_2026_07_22.py`, a mutation test: a fake harness whose reply mentions „ზრდასრულ" but whose `last_tool_calls` is empty must now FAIL the R4 check.

```python
import types
from evals import cases

class _FakeH:
    def __init__(self, out, tools):
        self._out = out
        self.last_tool_calls = [(t, {}) for t in tools]
        self.llm_enabled = True
        self.engine_invocations = 1
    def seed(self, **k): return types.SimpleNamespace(**k)
    def process(self, conv, msg): return self._out

def test_r4_fails_on_mention_without_tool():
    # reply mentions the word but NO tool ran → must FAIL (was a false 3/3)
    h = _FakeH("ზრდასრულთა ღონისძიებები გაინტერესებთ?", tools=[])
    out = cases._r4_overage_adult_switch(h)
    assert all(not c.passed for c in out.checks)

def test_r4_passes_when_tool_actually_ran():
    h = _FakeH("გადავრთე ზრდასრულთა ფლოუზე", tools=["switch_to_adult_flow"])
    out = cases._r4_overage_adult_switch(h)
    assert any(c.passed for c in out.checks)
```

- [ ] **Step 3: Run → fail** (`test_r4_fails_on_mention_without_tool` fails because the current `OR` still passes on the mention).

- [ ] **Step 4: Implement** — change `_r4_overage_adult_switch` so the effect is required. Replace the `suggested` line with:

```python
from evals.reach import tool_ran
# EFFECT, not text: the switch must actually have run. A verbal suggestion
# with zero tool call is NOT a pass (3.0b false-3/3 fix, 2026-07-22).
switched = tool_ran(h, "switch_to_adult_flow")
```
and make the check assert `switched` (keep the verbal-suggestion text only as *supplementary* diagnostic in `actual=`, never as an alternative pass condition).

- [ ] **Step 5: Run → pass.** `.venv/Scripts/python.exe -m pytest tests/test_cases_v2_2026_07_22.py -q`

- [ ] **Step 6: Baseline guard.** `md5sum evals/baseline.json` unchanged.

- [ ] **Step 7: Commit** — `fix(evals): R4 requires the tool to actually run (effect, not a text mention)`

---

## Task 3: Synthetic, season-independent product fixture

**Why:** Camp is not a live product and its season is over, so any camp case is confounded. To measure the MECHANISM (LLM reasons over product facts via a tool) product-agnostically, inject a stable synthetic product with KNOWN facts. Its facts are the ground truth Task 4 grades against — no hand-written answers.

**Files:**
- Create: `evals/fixtures_product.py`
- Test: `tests/test_cases_v2_2026_07_22.py` (fixture part)

**Interfaces:**
- Produces: `evals/fixtures_product.py::PRODUCT` (a dict of canonical facts), `FACTS` (the grounding fact list — value strings that MUST appear), `FORBIDDEN_INVENTIONS` (fact-shaped strings that must NOT appear because they are not this product's facts), and `install(monkeypatch)` which makes the dynamic-program matcher + `admin_config_service.get_active_sections` see exactly this product, so a turn naming it hoists to the engine.

- [ ] **Step 1: Read** `app/reasoning/dynamic_program_match.py` (what `match_dynamic_program` reads) and `app/services/admin_config_service.get_active_sections` to learn the exact section shape to inject. **Do not edit them.**

- [ ] **Step 2: Failing test:**

```python
from evals import fixtures_product as FP

def test_fixture_defines_known_facts():
    assert FP.PRODUCT["id"] not in ("summer_camp", "sunday_school", "adult_events")
    assert FP.PRODUCT["price_text"] in "".join(FP.FACTS)
    assert FP.FACTS and FP.FORBIDDEN_INVENTIONS
    # forbidden inventions must not overlap the real facts
    assert not (set(FP.FACTS) & set(FP.FORBIDDEN_INVENTIONS))
```

- [ ] **Step 3: Run → fail.**

- [ ] **Step 4: Implement `evals/fixtures_product.py`.** Choose a clearly-synthetic, non-reserved product (e.g. a robotics club) with a FUTURE date so no season logic hides it. Facts must be distinctive tokens (so grounding checks are unambiguous):

```python
"""A synthetic, season-independent product for measuring the reasoning mechanism.

Camp is off-season and confounds every camp case, so we inject a stable
non-reserved product with KNOWN, distinctive facts. Its facts ARE the ground
truth (operator OQ2: facts, not hand-written answers).
"""
PRODUCT = {
    "id": "robotics_club_eval",
    "name": "რობოტიკის კლუბი",
    "type": "club",
    "status": "active",
    "age_min": 10, "age_max": 15,
    "price_text": "480",                       # distinctive — not any real product's price
    "location": "ვაკე, ჭავჭავაძის 12",
    "registration_url": "https://example.com/robotics-eval",
    "registration_status": "open",
    "description_short": "რობოტიკის კლუბი 10-15 წლის მოზარდებისთვის.",
    "schedule_text": "ორშაბათი და ხუთშაბათი 18:00",
    "hashtags": ["#რობოტიკა_eval"],
}
# Facts that a correct, grounded answer to the matching question MUST surface:
FACTS = ["480", "10", "15", "ვაკე", "18:00"]
# Fact-shaped strings that are NOT this product's facts — their appearance = invention:
FORBIDDEN_INVENTIONS = ["2150", "9", "17", "ამბასადორი", "კაჭრეთი"]  # camp's facts, must never leak


def install(monkeypatch):
    """Make the matcher + active-sections see exactly this product."""
    import app.services.admin_config_service as acs
    monkeypatch.setattr(acs, "get_active_sections", lambda: [dict(PRODUCT)])
    # If the matcher reads a different accessor, patch that too — see Step 1.
    return PRODUCT
```
Adjust the `install` targets to whatever Step 1 found the matcher actually reads.

- [ ] **Step 5: Run → pass.**

- [ ] **Step 6: Sanity — a turn naming the product reaches the engine.** Add a test that, with `install(monkeypatch)` applied and `USE_DYNAMIC_PROGRAMS`/`USE_PARENT_LLM_ENGINE` pinned on for the harness, driving „რობოტიკის კლუბი მაინტერესებს" gives `reach.reached_engine(h) is True` (offline, engine spied). If the product does not hoist, the fixture is wrong — fix it here, this is the whole point of the task.

- [ ] **Step 7: Baseline guard + Commit** — `feat(evals): synthetic season-independent product fixture (known facts = ground truth)`

---

## Task 4: The grounding grade

**Why:** The sharpest 3.0b failure was grounding, not wording — the model called `get_camp_info` and *omitted the returned price*. This grade catches exactly that: does the reply surface the product's real facts (grounding + responsiveness) and invent none (forbid)?

**Files:**
- Create: `evals/grounding.py`
- Test: `tests/test_eval_grounding_2026_07_22.py`

**Interfaces:**
- Consumes: `evals/fixtures_product.py::FACTS`, `FORBIDDEN_INVENTIONS`.
- Produces: `evals/grounding.py::grade_grounding(reply, facts, forbidden) -> dict` returning `{"grounded": bool, "facts_present": [...], "facts_missing": [...], "inventions": [...], "score": float}` where `score` = fraction of `facts` present, and `grounded` = (≥1 required fact present AND no `forbidden` invention present). VETO semantics: any invention → `grounded=False` regardless of score.

- [ ] **Step 1: Failing test:**

```python
from evals.grounding import grade_grounding

FACTS = ["480", "ვაკე", "18:00"]
FORBIDDEN = ["2150", "კაჭრეთი"]

def test_grounded_reply_scores_high_and_passes():
    r = grade_grounding("ღირს 480 ლარი, ვაკეში, ორშაბათს 18:00.", FACTS, FORBIDDEN)
    assert r["grounded"] is True and r["score"] == 1.0 and r["inventions"] == []

def test_omitted_fact_lowers_score_but_may_still_ground():
    r = grade_grounding("ვაკეში ტარდება, 18:00.", FACTS, FORBIDDEN)   # price omitted (the Q2 failure)
    assert r["grounded"] is True and r["score"] < 1.0 and "480" in r["facts_missing"]

def test_invented_fact_vetoes_grounding():
    r = grade_grounding("ღირს 2150 ლარი.", FACTS, FORBIDDEN)  # invented camp price
    assert r["grounded"] is False and "2150" in r["inventions"]

def test_no_facts_at_all_is_not_grounded():
    r = grade_grounding("გამარჯობა, როგორ ხართ?", FACTS, FORBIDDEN)
    assert r["grounded"] is False and r["score"] == 0.0
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement `evals/grounding.py`:**

```python
"""Grounding grade — did the reply use the product's real facts and invent none?

Ground truth = product facts (operator OQ2), never a hand-written answer. This
targets the Q2 failure: engine called the info tool, then omitted the price.
"""
def grade_grounding(reply: str, facts: list[str], forbidden: list[str]) -> dict:
    text = reply or ""
    present = [f for f in facts if f and f in text]
    missing = [f for f in facts if f and f not in text]
    inventions = [f for f in forbidden if f and f in text]
    score = (len(present) / len(facts)) if facts else 0.0
    grounded = (len(present) >= 1) and (len(inventions) == 0)
    return {"grounded": grounded, "facts_present": present,
            "facts_missing": missing, "inventions": inventions, "score": score}
```

- [ ] **Step 4: Run → pass.**

- [ ] **Step 5: Baseline guard + Commit** — `feat(evals): grounding grade (facts-present + no-invention, veto on invention)`

---

## Task 5: The metric + the multi-turn, multi-product live case set

**Why:** Encode the metric the whole rebuild is judged by, and replace the confounded camp cases with a small set that provably reaches the engine, asserts effect, uses the synthetic product, and is multi-turn.

**Files:**
- Create: `evals/cases_v2.py`
- Modify: `evals/harness.py` (opt-in collection of `cases_v2` behind a parameter, default OFF so `run_all` and `baseline.json` are untouched)
- Test: `tests/test_cases_v2_2026_07_22.py`

**Interfaces:**
- Consumes: `evals/reach.py` (Task 1), `evals/fixtures_product.py` (Task 3), `evals/grounding.py` (Task 4).
- Produces: `evals/cases_v2.py::CASES_V2` (list of `EvalCase`), each carrying `domain` + a flag `requires_engine=True`. The metric is documented in Task 6's doc; the cases encode it.

- [ ] **Step 1: Read** `evals/harness.py:38-80` (`CaseOutcome`, `EvalCase`, `chk`) and `evals/cases.py:940-964` (`_DOMAIN_TAGS` post-assignment pattern) so `cases_v2` cases match the existing shape.

- [ ] **Step 2: Failing test** — assert the set exists, every case declares `requires_engine`, and each references the synthetic product (no real camp stream):

```python
from evals import cases_v2

def test_cases_v2_all_require_engine_and_are_tagged():
    assert cases_v2.CASES_V2
    for c in cases_v2.CASES_V2:
        assert getattr(c, "requires_engine", False) is True
        assert c.domain in {"program_info", "objection", "topic_facts", "contact_capture"}
```

- [ ] **Step 3: Run → fail.**

- [ ] **Step 4: Implement `evals/cases_v2.py`.** Write 6 cases. Each: `install(monkeypatch)` the synthetic product, drive a MULTI-TURN exchange, then assert **(a)** `chk_reached_engine(h)`, **(b)** for effect-cases `chk_tool_ran(h, ...)`, **(c)** grounding via `grade_grounding(reply, FP.FACTS, FP.FORBIDDEN_INVENTIONS)`, **(d)** `forbid_any` (no pressure/invented discount). Example (varied-phrasing program info, the topic-facts analogue):

```python
from evals.harness import EvalCase, CaseOutcome, chk
from evals.reach import chk_reached_engine, chk_tool_ran
from evals import fixtures_product as FP
from evals.grounding import grade_grounding

def _pv1_varied_price_phrasing(h):
    if not h.llm_enabled:
        return CaseOutcome(skipped=True, skip_reason="needs --llm (engine turn)")
    # NOTE: install() runs via the harness monkeypatch hook for v2 cases.
    conv = h.seed(segment="PARENT", state="START")
    h.process(conv, "რობოტიკის კლუბი მაინტერესებს")            # turn 1: name it → hoist
    reply = h.process(conv, "და ეს რა თანხა დამიჯდება თვეში?")   # turn 2: varied price phrasing
    g = grade_grounding(reply, FP.FACTS, FP.FORBIDDEN_INVENTIONS)
    forbid = [w for w in ("იჩქარეთ", "ბოლო ადგილები", "ფასდაკლება") if w in reply]
    return CaseOutcome([
        chk_reached_engine(h),
        chk("grounded in product facts (price present, nothing invented)", g["grounded"],
            "grounded", f"present={g['facts_present']} inventions={g['inventions']}"),
        chk("no pressure / invented-discount wording", not forbid, "none", f"found={forbid}"),
    ])
```
Write the other 5 across `program_info` (a differently-phrased location/schedule question), `topic_facts` (a safety/logistics question answered from the product's `description`/`schedule` — the camp_topic_facts analogue, but on the synthetic product), `objection` (a price objection on the synthetic product — grounded value framing, no invented discount), and `contact_capture` (naming the product then giving a phone → assert the phone lands on the lead via effect, mirroring the camp contact flow but product-agnostic). Keep every case multi-turn and every assertion effect/grounding-based, never a literal-string equality.

- [ ] **Step 5: Wire opt-in collection in `evals/harness.py`.** Add a parameter to the collection path (e.g. `run_all(..., include_v2: bool = False)`) that appends `cases_v2.CASES_V2` ONLY when `include_v2=True`. Default OFF ⇒ `run_all()` and the protected `baseline.json` pipeline are byte-identical. Add the `requires_engine`/`domain` attributes via the same post-construction pattern as `cases.py:940-964`.

- [ ] **Step 6: Run → pass** (offline: the cases self-skip without `--llm`, and the structural tests pass). `.venv/Scripts/python.exe -m pytest tests/test_cases_v2_2026_07_22.py -q`

- [ ] **Step 7: Baseline guard + Commit** — `feat(evals): cases_v2 — multi-turn, engine-reaching, grounded, product-agnostic case set`

---

## Task 6: Metric doc + per-domain canned baseline (paid capture is an approval gate)

**Why:** Capture, per advisory domain, what the CANNED path scores today on the new metric — the number Phase 3.2 must beat — and document the metric + runbook. The paid `--llm` capture is a separate, approval-gated step; the free parts land now.

**Files:**
- Create: `docs/MEASURE_PHASE3_0_BASELINE.md`
- (verification only; no code)

- [ ] **Step 1: Full offline suite, no new regressions.** `.venv/Scripts/python.exe -m pytest -q` → only the declared pre-existing `fast_track` failure. Record counts.

- [ ] **Step 2: Offline READ-ONLY eval clean + baseline intact.** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m evals.run_evals` → READ-ONLY-clean; `md5sum evals/baseline.json` = `93973fcd10349b447f87fa320e0807f3`.

- [ ] **Step 3: Write `docs/MEASURE_PHASE3_0_BASELINE.md`** — the metric definition verbatim:
  ```
  PRIMARY    correctness + responsiveness — did it answer the question asked?
  GROUNDING  did the reply use the product's real facts (present) and invent none (veto)?
  VETO       forbid_any (invention / pressure) — one is enough to fail
  SECONDARY  naturalness — tie-break ONLY, never overrides correctness (Phase-4 lesson)
  DIAGNOSTIC canned-template firing count (from T1 attribution) — the anti-template signal
  ```
  Plus: why camp cases are excluded (dead season), why ground truth = facts not answers (OQ2), and the exact paid command for the baseline capture.

- [ ] **Step 4: Document the paid capture as an APPROVAL GATE.** In the doc, record the runbook but DO NOT run it here:
  ```
  # snapshot first — run_all(llm=True) overwrites baseline.json
  cp evals/baseline.json /tmp/bl.snap
  USE_PARENT_LLM_ENGINE=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
      -m evals.run_evals --llm --judge --v2         # (add the --v2 flag exposing include_v2=True)
  cp /tmp/bl.snap evals/baseline.json               # restore
  md5sum evals/baseline.json                        # must be 93973fcd...
  ```
  State: this captures the canned-vs-engine baseline on `cases_v2`; it costs real OpenAI spend and MUST be operator-approved; both flags stay default OFF.

- [ ] **Step 5: Commit** — `docs(phase3.0): metric definition + per-domain canned baseline runbook (paid capture gated)`

---

## Phase 3.0 Definition of Done

The eval is a valid instrument: a case cannot silently grade a template (Task 1 makes engine-reach assertable; Task 5 cases require it), a tool mention can no longer substitute for the tool running (Task 2; Task 5 asserts effect), the camp dead-season no longer confounds (Task 3 synthetic product), and "correct" now means grounded-in-real-facts-and-invents-nothing rather than matching a literal string (Task 4 + Task 5). The metric is written down (Task 6). **No `app/` production code changed; `evals/baseline.json` byte-identical throughout; full suite green but the one declared pre-existing failure.** The paid per-domain baseline capture is documented and left as an operator-approved step.

**Explicitly NOT in Phase 3.0:** no interceptor conversion, no safety-spine refactor, no fact canonicalisation, no `app/` change — those are Phase 3.1+, each with its own spec/plan. This plan only builds the instrument that will judge them.

## Self-Review

- **Spec coverage:** T2 (eval rebuild) → Tasks 1–3, 5; T4 (metric) → Tasks 4, 5, 6; T5 (baseline) → Task 6. T1/T3 pre-done (noted). ✅
- **Camp-not-live constraint:** Task 3 synthetic product; Task 5 cases use it exclusively; Task 6 documents the exclusion. ✅
- **Effect-not-text:** Task 1 `tool_ran`/`reached_engine`; Task 2 fixes R4; Task 5 asserts effect. ✅
- **Ground truth = facts not answers:** Task 3 FACTS/FORBIDDEN; Task 4 grades against them; no case asserts string equality. ✅
- **baseline.json protected:** guarded after every task; `run_all` default path untouched (Task 5 opt-in flag). ✅
- **No `app/` change:** every file under `evals/` or `tests/` + one doc. ✅
- **Type consistency:** `reached_engine`/`chk_reached_engine`/`tool_ran`/`chk_tool_ran` (Task 1) used verbatim in Tasks 2 & 5; `grade_grounding` signature (Task 4) used verbatim in Task 5. ✅
