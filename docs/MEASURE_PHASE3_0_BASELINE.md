# Phase 3.0 — Metric Definition + Canned Baseline (Instrument, not a fix)

**Status:** instrument complete (Tasks 1–5 landed). Paid per-domain baseline
capture is documented below as an **operator-approved gate** — it is
**NOT run by this document**. `evals/baseline.json` is untouched throughout
(md5 `93973fcd10349b447f87fa320e0807f3`, verified after every task — see
"Verification" below).

**Scope reminder:** Phase 3.0 is measurement-only. It changed **no `app/`
production code** — every file is under `evals/`, `tests/`, or this one doc.
It does not fix anything; it builds the instrument Phase 3.1+ will be judged
by.

---

## 1. The metric, verbatim

```
PRIMARY    correctness + responsiveness — did it answer the question asked?
GROUNDING  did the reply use the product's real facts (present) and invent none (veto)?
VETO       forbid_any (invention / pressure) — one is enough to fail
SECONDARY  naturalness — tie-break ONLY, never overrides correctness (Phase-4 lesson)
DIAGNOSTIC canned-template firing count (from T1 attribution) — the anti-template signal
```

**What the offline instrument (this phase) actually measures, and what it
does NOT:**

| Line | Measured by | Status |
|---|---|---|
| GROUNDING | `evals/grounding.py::grade_grounding` | ✅ built, free, deterministic |
| VETO (forbid_any) | `grade_grounding`'s `inventions` list + each case's narrow pressure-word `forbid` check | ✅ built |
| DIAGNOSTIC (canned-template firing) | Task 1/3 (interceptor attribution) — `docs/PHASE3_0_INTERCEPTOR_INVENTORY_2026_07_22.md` | ✅ already done (pre-Phase-3.0) |
| engine-reach anti-confound (prerequisite for all of the above) | `evals/reach.py::reached_engine` / `chk_reached_engine` | ✅ built (Task 1) |
| tool-effect, not text mention (prerequisite for GROUNDING to mean anything) | `evals/reach.py::tool_ran` / `chk_tool_ran` | ✅ built (Tasks 1–2) |
| **PRIMARY — "did it answer the question asked?"** | **the LLM judge** (`evals/judge.py`), paid | ⏳ NOT built by this phase — see §4 |
| **SECONDARY — naturalness** | `evals/naturalness.py`, paid, judge-gated | already exists from an earlier arc; tie-break only |

This is a deliberate, load-bearing distinction, not an oversight: **grounding
(facts present, nothing invented) is necessary but not sufficient for
PRIMARY.** A reply can be perfectly grounded (every fact correct, nothing
invented) and still fail PRIMARY by not actually answering the question that
was asked — e.g. answering "what age is it for?" with a grounded price
quote. A cheap substring check cannot tell "answered the question" from
"mentioned a true fact from the same product" — that distinction requires
semantic judgment, which is exactly what an LLM judge is for. **Do NOT fake
responsiveness with a substring/keyword check** — that was the false-3/3
failure mode 3.0b's R4 finding already burned us on once (a text mention
scored as if the effect had happened). The offline instrument therefore
grades **engine-reach + tool-effect + GROUNDING + VETO** — the four rows
above that a deterministic script CAN check honestly — and leaves PRIMARY
responsiveness and SECONDARY naturalness to the paid judge path that already
exists (`evals/judge.py`, `evals/naturalness.py`), gated the same way as
before.

---

## 2. Why camp cases are excluded from the new instrument

The 2026 summer camp season **ended 2026-07-20** (operator decision,
recorded 2026-07-22). Every existing camp case now runs against a
registration-CLOSED product: `get_camp_info` still returns real data, but
any case that expects a live registration link, an open eligibility CTA, or
a "book now" path is confounded by that fallback — a failure would prove
nothing about the model's reasoning, only that the season is over. Using camp
to measure the *mechanism* (does the LLM reason over a product's facts via a
tool and answer correctly) would silently conflate "season closed" with
"model got it wrong."

Phase 3.0's new cases (`evals/cases_v2.py`) therefore use exclusively the
**synthetic, season-independent product** built in Task 3
(`evals/fixtures_product.py` — "რობოტიკის კლუბი", a robotics club with a
future/season-independent identity, price 480, age 10–15, location ვაკე,
schedule Mon/Thu 18:00). It is non-reserved (not `summer_camp` /
`sunday_school` / `adult_events`) and installed via `install(monkeypatch)`,
which patches BOTH `admin_config_service.get_active_sections` (so the
dynamic-program matcher hoists a naming turn straight to the engine) and
`admin_config_service.get_section` (so `get_program_info` returns its
facts) — proven live by the Task 3 sanity test
(`tests/test_cases_v2_2026_07_22.py::test_named_product_turn_reaches_the_engine`).

The old camp-based cases in `evals/cases.py` are **not deleted** — they still
measure real, still-relevant behaviour (decline handling, age routing,
contact capture, etc.) that has nothing to do with registration being open.
Only the *new* engine-reasoning-over-product-facts case set avoids camp.

---

## 3. Why ground truth = facts, not hand-written answers (operator OQ2)

A case in `cases_v2.py` never asserts `reply == "<scripted string>"` and
never grades against a human-authored "correct answer." It asserts three
independent, structural things:

1. **The turn reached the engine** (`chk_reached_engine`) — not a
   deterministic interceptor silently answering from a template (the
   Phase-4 / 3.0b failure mode this whole rebuild exists to catch).
2. **The relevant tool actually ran** (`chk_tool_ran` / the
   `_combined_tool_ran` helper in `cases_v2.py`, which checks across BOTH
   turns of a multi-turn case, since `last_tool_calls` resets every
   `process()` call) — a verbal mention of a fact is not evidence the model
   consulted the tool; only the tool call is.
3. **The reply is grounded in `FP.FACTS`** (this product's real, distinctive
   facts: `480`, `10`, `15`, `ვაკე`, `18:00`) **and free of
   `FP.FORBIDDEN_INVENTIONS`** (the real camp's facts: `2150`, `9`, `17`,
   `ამბასადორი`, `კაჭრეთი` — leaking these into a reply about the robotics
   club is direct proof of fact cross-contamination / invention).

Authoring a per-question model answer was explicitly forbidden by the
operator (OQ2): scripting "the correct sentence" for each question
re-creates exactly the canned-template pathology Phase 3.0 exists to
replace with something that measures reasoning. Facts are the only thing
that can serve as ground truth without becoming a new template.

---

## 4. The negation guard, and the synthetic-vs-real caveat

### 4.1 Negation guard (`evals/grounding.py`)

A pure substring check would wrongly count `"480"` as PRESENT inside
`"არა 480 არ ღირს"` (the reply explicitly saying it is **NOT** 480).
`grade_grounding` guards against exactly this: a fact occurrence immediately
preceded (within ~3 whitespace characters, in the same clause — no
`. , ! ? ;` or newline in between) by a Georgian negation particle
(`არა` / `არ` / `აღარ`) is not counted as present for that occurrence. A
fact with at least one non-negated occurrence anywhere in the reply still
counts as present (a negated mention doesn't erase a genuine, separate
assertion of the same fact elsewhere). See
`tests/test_eval_grounding_2026_07_22.py` for the exact cases this covers,
including a negation-in-an-earlier-clause case that must NOT suppress an
unrelated later fact, and a negation-word-embedded-in-a-longer-word case
that must NOT be mistaken for the particle itself.

This is explicitly a **cheap, deterministic, structural** guard — documented
as a limitation in `grounding.py`'s own module docstring — not a
negation-scope parser and not a responsiveness judge. It catches the
textbook "explicitly says NOT this value" case; it will not catch every
grammatical negation construction in Georgian (e.g. negation several clauses
away with no punctuation boundary, or negation expressed by other means
entirely). Where it's wrong, it is wrong in the conservative direction for
GROUNDING (it may occasionally under-count a present fact as negated when it
wasn't, which lowers `score` but — because `grounded` only needs ONE present
fact — rarely flips `grounded` itself) rather than the dangerous direction
(counting an explicitly-denied fact as evidence of correct grounding).

### 4.2 Synthetic-vs-real caveat — READ THIS BEFORE trusting a green `cases_v2` run

`cases_v2` measures the mechanism (engine-reach, tool-effect, grounding,
forbid) on ONE synthetic product, under IDEAL conditions: a single,
unambiguous product name; clean, well-formed facts; no real user typos,
code-switching, or the genuinely messy phrasing real parents use. **Green on
`cases_v2` proves the mechanism CAN work — it does not prove the mechanism
WORKS WELL on real, messy admin-configured products**, several of which will
have incomplete fields, ambiguous names, or facts that don't fit neatly into
short distinctive tokens the way this fixture's do.

Per the plan's explicit revision note: **do not over-invest in the synthetic
automated score.** This instrument is the minimum viable measurement of the
mechanism, not a finished quality bar. It is meant to be **paired with, not
a replacement for, human review of ~20 real conversations once the first
real dynamic-program capability is live** (i.e. once an operator actually
configures a second admin product and real users start asking it real
questions). Do not report a `cases_v2` pass rate as "the model handles
dynamic programs well" without that human review sitting alongside it.

---

## 5. What Tasks 1–5 built (instrument inventory)

| Task | File(s) | What it adds |
|---|---|---|
| 1 | `evals/reach.py`, `evals/harness.py` (`Harness.engine_invocations`) | `reached_engine` / `chk_reached_engine` — was this turn answered by the real LLM engine, or a deterministic interceptor? |
| 1 | `evals/reach.py` | `tool_ran` / `chk_tool_ran` — did a tool actually EXECUTE, not just get mentioned in the reply text? |
| 2 | `evals/cases.py::_r4_overage_adult_switch` | Fixed the R4 OR-bug: a verbal "adult events exist" mention can no longer substitute for `switch_to_adult_flow` actually running. |
| 3 | `evals/fixtures_product.py` | The synthetic, season-independent product (`robotics_club_eval`) + `FACTS` / `FORBIDDEN_INVENTIONS` (ground truth) + `install(monkeypatch)` (patches `get_active_sections` AND `get_section`). |
| 4 | `evals/grounding.py` | `grade_grounding(reply, facts, forbidden) -> dict` — facts-present score + invention veto + negation guard (§4.1). |
| 5 | `evals/cases_v2.py`, `evals/harness.py` (`_collect_cases`, `run_all(..., include_v2=False)`), `evals/run_evals.py` (`--v2`) | `CASES_V2` — 6 multi-turn cases (program_info ×2, objection, topic_facts ×2, contact_capture) on the synthetic product, each tagged `requires_engine=True` and a `domain`. Opt-in collection: `run_all()`'s default is untouched (`include_v2=False`), so `baseline.json` cannot be perturbed by an ordinary run. |

---

## 6. Verification (this document's own gate — read-only, free, run today)

Ran in this order, each command's output captured verbatim:

**(a) Full offline pytest suite (run 2026-07-22, after all 5 Phase 3.0 commits):**
```
.venv/Scripts/python.exe -m pytest tests/ -q
```
Result: **`1 failed, 5270 passed, 28 skipped, 3 warnings in 376.06s`**
The one failure is exactly the ONE pre-existing, declared-out-of-scope
failure: `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`
(a fast-track/booking wording assertion unrelated to Phase 3.0 — it fails
the same way with or without this phase's changes). No Phase 3.0 file
(`evals/reach.py`, `evals/fixtures_product.py`, `evals/grounding.py`,
`evals/cases_v2.py`, the `evals/harness.py` / `evals/run_evals.py` edits, or
their tests) caused any other failure.

**(b) Offline READ-ONLY eval (no `--llm`, no cost):**
```
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m evals.run_evals
```
Result: **`93/100 checks (93%) · 40 cases run, 22 skipped`** —
`✅ READ-ONLY VERIFIED — 0 live external writes/sends` (tripwires
httpx.post=0, httpx.get=0, SMTP=0; OpenAI not called — "OpenAI NOT called
(deterministic-only mode — fully offline)"). The one deterministic failure
in this run (`R3` — camp registration link) reflects the CURRENT
deterministic case set's pre-existing condition (the camp registration link
case fails because the season is closed — see §2), which is unrelated to
any Phase 3.0 file: all of Task 3–5's additions are either new modules never
imported by the default `CASES` list, or an `evals/harness.py` change whose
default behaviour (`include_v2=False`) is provably byte-identical (see
`tests/test_cases_v2_2026_07_22.py::test_collect_cases_include_v2_default_off_is_byte_identical`).

**(c) `evals/baseline.json` protected throughout:**
```
md5sum evals/baseline.json
```
Result: **`93973fcd10349b447f87fa320e0807f3`** — unchanged from before Task
3, confirmed after every task's commit. Tasks 3–5 never ran with `--llm`, so
`run_all(..., llm=True)`'s baseline-write branch never executed.

---

## 7. The paid capture — APPROVAL GATE, not run by this document

The per-domain canned-vs-engine baseline on `cases_v2` costs real OpenAI
spend (best-of-3 stochastic cases × 6 cases × however many turns/checks) and
therefore **requires explicit operator approval before running**. Both
`USE_DYNAMIC_PROGRAMS` and `USE_PARENT_LLM_ENGINE` being pinned on inside
each `cases_v2` case is a TEST-TIME monkeypatch (`evals/cases_v2.py::_pin_dynamic_programs`)
— it does not touch the live `.env`/deployed flags.

**Runbook (do not run without operator sign-off):**

```bash
# 1. SNAPSHOT FIRST — run_all(llm=True) overwrites evals/baseline.json.
cp evals/baseline.json /tmp/bl.snap

# 2. RUN — real OpenAI calls, judge scoring, cases_v2 included.
USE_PARENT_LLM_ENGINE=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe \
    -m evals.run_evals --llm --judge --v2

# 3. RESTORE — baseline.json is protected; the paid run's own summary output
#    (stdout) is what you actually want to read/archive, NOT a new
#    baseline.json.
cp /tmp/bl.snap evals/baseline.json

# 4. VERIFY — must be the same md5 as before step 2.
md5sum evals/baseline.json    # must be 93973fcd10349b447f87fa320e0807f3
```

What this captures: the per-domain (`program_info` / `objection` /
`topic_facts` / `contact_capture`) score on `cases_v2` — the number that a
future Phase 3.1+ "make dynamic programs actually good" effort must beat.
`--v2` alone (without `--llm`) is free and inert — every `cases_v2` case
self-skips without a real engine turn, so accidentally passing `--v2` to a
free run changes nothing observable except 6 additional "SKIPPED" lines.

**This document does NOT execute step 2.** Both flags in the runbook stay
default OFF in every environment this phase touches; nothing above was run
as part of Task 6 beyond the free, read-only verification in §6.

---

## 8. Definition of done (Phase 3.0, all tasks)

- A case can no longer silently grade a deterministic template — engine-reach
  is assertable and asserted by every `cases_v2` case (Tasks 1, 5).
- A tool mention in reply text can no longer substitute for the tool actually
  running — fixed at the source (`_r4_overage_adult_switch`, Task 2) and
  required by every effect-checking `cases_v2` case (Task 5).
- Camp's dead season no longer confounds the new case set — the synthetic
  product fixture is season-independent and provably hoists to the engine
  (Task 3).
- "Correct" means grounded-in-real-facts-and-invents-nothing, not a literal
  string match — `grade_grounding` with a negation guard (Task 4), consumed
  by every `cases_v2` case (Task 5).
- The metric is written down (this document), including the honest gap
  (PRIMARY responsiveness is judge-only, not yet captured) and the synthetic-
  vs-real caveat.
- **No `app/` production code changed.** `evals/baseline.json` byte-identical
  throughout (md5 `93973fcd10349b447f87fa320e0807f3`). Full offline suite
  green except the one declared pre-existing failure. The paid per-domain
  baseline capture is documented and left as an operator-approved step —
  **not run here.**
