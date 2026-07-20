# Agent-understanding eval harness (`evals/`)

Measures **how well the agent understands free-form Georgian and chooses the
right decision** — intent understanding, entity extraction, parent/adult
routing, response quality, and follow-up logic. This is *not* a unit-test suite
for functions (those already pass); it scores the agent's **decision quality**.

## Run

```bash
# deterministic, FREE, fully offline (no OpenAI, no network)
python -m evals.run_evals

# + full_turn cases (drives the real engine via process_message → real OpenAI)
python -m evals.run_evals --llm

# + Claude LLM-as-judge for nuanced response quality (needs ANTHROPIC_API_KEY)
python -m evals.run_evals --llm --judge

python -m evals.run_evals --category routing      # one dimension
python -m evals.run_evals --case E1               # one case

# Phase 1 gate metrics (interception + canned footprint + per-domain) —
# deterministic, FREE, fully offline. Writes evals/phase1_baseline.json,
# NEVER evals/baseline.json. See "Phase 1 gate" below.
python -m evals.phase1_report
```

Exit code `0` = all run checks passed **and** no READ-ONLY tripwire hit; `1` otherwise.

## What it scores (5 dimensions)

| dimension | what it checks | example case |
|---|---|---|
| understanding | free-form / non-standard phrasing intent | camp intent vs menu; parent→child contact vs socialization |
| extraction | age, Georgian relative dates/times, name | `ხვალ 11 საათზე`→tomorrow 11:00; `8 საათზე`→20:00 |
| routing | parent↔adult segment + action priority | camp action overrides sticky ADULT |
| response_quality | grounded (no invention), on-topic, polite | no invented room occupancy; price-objection value framing |
| followup | who/when/what (mocked clock) | +24h→`first_24h`; booked/declined→skip |

## Two check kinds

- **code** — objective, deterministic assertions. Most cases call the agent's
  real decision functions directly (no LLM) — cheap, exact, free.
- **judge** — Claude binary rubric (one criterion at a time) for the nuanced
  *response quality* dimension only. Disabled without `ANTHROPIC_API_KEY`
  (marked SKIPPED, never a silent pass).

## 🔴 READ-ONLY guarantee (`evals/safety.py`)

Every external side-effect is a recording **dry-run stub**: Calendar writes,
Sheets writes, manager email/WhatsApp, outbound Messenger/Instagram DM, and
follow-up sends. Hard tripwires that must stay at 0: **SMTP** (always) and raw
**httpx** (in deterministic-only mode). Live guards pinned:
`ALLOW_LIVE_WHATSAPP=False`, `LIVE_BROADCAST_ENABLED=False`, `REDIS_ENABLED=False`.
Every run ends with a `✅ READ-ONLY VERIFIED` line accounting for 0 live calls.

> OpenAI / Anthropic are the **models under test** (only with `--llm` / `--judge`)
> — not a side-effect. The default run touches neither.

## Layout

```
evals/
  safety.py           # READ-ONLY install + dry-run stubs + tripwires + banner
  judge.py            # Claude LLM-as-judge (binary rubric; skip if no key)
  harness.py          # Harness driver + runner + scoring + failure report
  cases.py            # ~50 cases across 5 dimensions + Task 4 domain tags
  run_evals.py        # CLI
  interception.py     # Phase 1 Layer A — free interception-rate instrument
  botlike_proxy.py    # Phase 1 Layer A — free canned/botlike-footprint proxy
  naturalness.py      # Phase 1 Layer B — paid Claude naturalness judge (--llm --judge)
  phase1_report.py    # Phase 1 — writes evals/phase1_baseline.json (free, offline)
  baseline.json         # Phase-0 reference, 90/100 — written ONLY by `--llm`, untouched by Phase 1
  phase1_baseline.json # Phase-1 Layer-A metrics — written by `python -m evals.phase1_report`
```

Cases are sourced from real failures: `tests/test_legacy_*` / `*_patch` /
`*regression`, the dated rules in `app/agent/prompts/system_parent_v2.md`, and
HANDOFF/CLAUDE bug history. Add a case by appending an `EvalCase` to
`cases.CASES` with a `run(h)` that returns a `CaseOutcome`.

## Phase 1 gate

Phase 1 adds a **behavioral eval safety net** on top of the harness above, so
that Phases 2–4 (the dynamic-programs rework) have an objective floor to hold
and a signal to improve against — without ever losing the original
decision-quality reference. Two layers:

- **Layer A (free, deterministic, in-CI)** — `evals/interception.py` +
  `evals/botlike_proxy.py` + `evals/phase1_report.py`. No API key, no
  network call, runs on every commit.
  - **interception rate** — `evals.interception.interception_rate(...)`: the
    % of PARENT turns that reach the LLM engine vs. are short-circuited by a
    deterministic pre-engine `_maybe_*` interceptor in
    `app/flows/parent_flow.py`. **This is DIAGNOSTIC, never a pass/fail
    target.** It tells you how much of the agent's behaviour is hand-written
    Python vs. LLM reasoning at a point in time — useful for deciding *where*
    to invest Phase 2+ effort — but it is extremely sensitive to calendar
    state and conversation history (a fresh conversation before any camp
    stream opens looks very different from one after every stream has
    closed), so it must never gate a merge.
  - **canned footprint** — `evals.botlike_proxy.canned_footprint` /
    `botlike_proxy_score`: a cheap proxy for "how templated does this reply
    look" (canned two-option menu, sanitizer-corrected stock phrases, brand
    boilerplate). Correlates with, but is not a substitute for, naturalness.
- **Layer B (paid, occasional, operator-gated)** — `evals/naturalness.py`:
  a Claude judge (temp=0, N-run median) scoring 4 binary criteria (reads like
  a human consultant / no canned-menu phrasing / varied wording / warm tone)
  over **advisory-domain turns only**. It is a **standalone, tested grader**
  (`evals.naturalness.grade_naturalness(context, response)`) — **not yet wired
  into the `--judge` run** (harness wiring was deliberately deferred; see the
  Phase-1 plan). Today it is invoked MANUALLY by the operator over advisory-domain
  turns; `phase1_baseline.json`'s `naturalness` stays `null` until that manual
  pass fills it. It NEVER runs in the free/offline path. (A follow-up may wire it
  into `--judge` so the number fills automatically — until then the README does
  not claim automatic integration.)

### The gate rule (binding on Phases 2–4)

A Phase 2, 3, or 4 change to the agent:

1. **MUST hold reliability = 100% on the guardrail domains** —
   `booking_reliability` and `contact_capture` (see the `_DOMAIN_TAGS` map in
   `evals/cases.py`). These are scored on grounding/reliability only (never
   confirm a booking without tool success, never invent a price, never store
   a filler word as a name, never book without a fresh availability check) —
   a HARD constraint, not something to trade off against naturalness.
2. **MUST NOT lower any domain's correctness** — the per-domain case counts
   in `phase1_baseline.json` (`per_domain`) are the coverage map; a change
   that regresses a passing case in ANY domain (guardrail or advisory) fails
   the gate, full stop.
3. **SHOULD lower canned footprint and raise naturalness on the advisory
   domains** — `objection`, `camp_topic`, `program_info`. This is the
   objective Phase 2+ is optimizing for, but it is a *should*, gated behind
   (1) and (2), not an independent pass/fail axis.
4. **%-reaching-LLM is reported as diagnostic, never pass/fail.** A Phase 2+
   change is free to raise or lower interception — e.g. replacing a
   hand-written interceptor with better LLM-driven reasoning is exactly the
   kind of change Phase 2+ might make, and would *lower* interception on
   purpose. The number is there to explain *why* naturalness/footprint moved,
   not to be optimized directly.

In short: **naturalness is a CONSTRAINED objective — maximize naturalness
(and minimize canned footprint) subject to reliability staying at 100% on
the guardrail domains and no domain regressing.** It is never raw
maximization; a more "natural"-sounding agent that breaks booking
reliability or hallucinates a price fails the gate regardless of its
naturalness score.

### Two separate artifacts — do not confuse them

- **`evals/baseline.json`** — the ORIGINAL, untouched Phase-0 reference (51
  adversarial cases, 90/100 · 🧠 92% · ⚙️ 86% · 🇬🇪 100%). Written ONLY by a
  full `python -m evals.run_evals --llm` run (see `harness.py::_report`,
  Part E). This is the decision-quality baseline every future change is
  measured against. **Phase 1 tooling never reads or writes this file.**
- **`evals/phase1_baseline.json`** — the NEW Phase-1 metrics artifact,
  written by `python -m evals.phase1_report` (free, offline, deterministic —
  see `evals/phase1_report.py`). Contains `interception` (representative +
  `tests/corpus/` real-turn samples, DIAGNOSTIC), `canned_footprint`
  (computed over genuine non-LLM replies only), `naturalness` (`null`
  offline — filled only by the permissioned `--llm --judge` run), and
  `per_domain` (case-count coverage map). Regenerate it any time with:

  ```bash
  python -m evals.phase1_report
  ```

  This is the pre-Phase-2 reference capture for the Layer-A metrics. The
  full naturalness + response_quality + grammar numbers for the SAME point
  in time come from a separately-run, explicitly permissioned
  `python -m evals.run_evals --llm --judge` (costs real OpenAI + Anthropic
  tokens — an operator step, not run automatically by this tooling).
