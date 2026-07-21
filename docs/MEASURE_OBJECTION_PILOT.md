# Objection Pilot — Incremental Measurement Runbook

**Audience:** operator. This is the permissioned, paid (OpenAI + Anthropic tokens) STAGING measurement that decides whether the built reasoning/skills machinery improves the objection domain enough to enable it. The assistant does NOT run this (it costs money + needs staging + your keys). Run it yourself with `.venv/Scripts/python.exe`.

## Why incremental (one flag at a time)
Turning on `USE_SKILLS` + `USE_REASONING_PASS` + `USE_OBJECTION_ENGINE_ROUTING` all at once tells you nothing about WHICH one helped (or hurt). Measure each flag's MARGINAL effect, in this order, so a win (or a regression) is attributable.

## The objection cases (8 tagged; 4 are `--llm` full-turn)
`OB1` (budget objection), `OB2` (soft hesitation), `OB3` (hesitation+objection — the gap this pilot closes), `Q2`/`Q8` (price objection) are the full-turn ones. Run each **N=3** and take the median (both the engine turn and the naturalness judge are stochastic).

## The four steps (record correctness, naturalness, REFLECT-replace-rate, latency at each)

Set `USE_PARENT_LLM_ENGINE=true` throughout. Change ONE flag per step.

1. **Baseline** — all pilot flags OFF:
   ```
   USE_SKILLS=false USE_REASONING_PASS=false USE_OBJECTION_ENGINE_ROUTING=false \
     .venv/Scripts/python.exe -m evals.run_evals --llm --judge --case OB1   # then OB2, OB3, Q2, Q8
   ```
   Record: conversion-proxy pass (require_any hit + no forbid_any), naturalness score, latency. (REFLECT-rate = 0, reasoning off.)

2. **+ skills** — `USE_SKILLS=true` only. Rerun the same cases. Does the `objection-handling.md` skill ALONE move naturalness/correctness?

3. **+ reasoning** — add `USE_REASONING_PASS=true`. Rerun. Record the deltas AND the **REFLECT-replace-rate on the objection cases** — watch the log line `[parent_llm_engine] REFLECT replaced a hallucinated fact`. If a GOOD value/payment reply gets replaced by the canned manager-handoff fallback (the payment-math false-positive: a reply that states only "~360 ლარი თვეში" without restating 2150), that is a STOP signal — the price-class REFLECT rule needs tightening before enablement.

4. **+ routing** — add `USE_OBJECTION_ENGINE_ROUTING=true`. Rerun, focusing on **OB3** (the hesitation gap). This measures routing's marginal effect ON TOP OF the machinery — routing is never enabled alone.

At every step also run:
```
.venv/Scripts/python.exe tools/scenario_runner_full.py --priority CRITICAL   # must stay 22/22
```
and confirm the Phase-1 guardrail domains (`booking_reliability`, `contact_capture`) reliability has NOT dropped.

## The binding gate (a step is a WIN only if ALL hold)
- naturalness ↑ on the objection cases (directional — this is a pilot SIGNAL over ~5 stochastic cases, not statistical proof; confirm on real Redis objection transcripts before broad enablement), AND
- the conversion-proxy still passes (the reply still SELLS: value/what's-included + payment-split + a CTA, never an invented discount), AND
- CRITICAL 22/22 held AND guardrail-domain reliability not dropped, AND
- ANALYZE latency p95 ≤ ~1.5 s added (steps 3-4), AND
- no REFLECT payment-math false-positives (step 3-4).

## Decision
- **All gates clear** for a flag → recommend enabling that flag (routing only atop skills+reasoning) as a TRIO on staging, run a supervised objection smoke on the test Page, then a scoped production enablement.
- **A step regresses** (naturalness down, or conversion-proxy broken, or CRITICAL/guardrail drop, or REFLECT false-positives, or latency over budget) → STOP; report the per-step numbers. The flag that regressed does not ship; isolate and fix (e.g. tighten REFLECT, or revise the objection skill body) before retrying.

## Rollback
Every pilot flag is default OFF. Remove/false the env var(s) + restart → today's behavior. Byte-identical.

## Honest scope
This validates the reasoning/skills MACHINERY on objections. It does NOT prove the interceptor→tool conversion pattern (objections already reached the engine — there was no blocking interceptor). That pattern is proven later on a domain with a real short-circuiting interceptor (e.g. `camp_topic_facts`).
