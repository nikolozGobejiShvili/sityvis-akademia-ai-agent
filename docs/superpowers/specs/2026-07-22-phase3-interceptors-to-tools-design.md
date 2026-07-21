# Phase 3 — Interceptors → Tools (polarity inversion) — Design Spec

**Date:** 2026-07-22 · **Status:** design approved, 2 OPEN QUESTIONS block Phase 3.0 start
**Branch:** `feat/dynamic-programs` (LOCAL only) · **Roadmap:** `docs/REASONING_AGENT_ROADMAP.md` Phase 3

---

## 1. Goal

> The model reasons and calls tools; **facts and commitments come from the backend, not the model's memory.**

Operator's stated aim: an agent that reasons, answers any question logically, and analyses the question itself — without inventing.

### Measurable criteria

| Metric | Today | Target |
|---|---|---|
| Turns reaching the LLM | ~3% | Materially higher (per-domain, set in 3.0) |
| Answer facts sourced from a tool payload | partial | **grounded or absent** — never model memory |
| Guardrail coverage | **path-dependent** | **path-independent** |
| CRITICAL scenarios | 22/22 | 22/22 unchanged |
| Per-turn latency | ~0ms (97% of turns) | ≤ ~2.5s (measured 2.03–2.14s, model-independent) |

---

## 2. Grounding — what is established, with evidence

Every claim below is measured, not assumed. Sources are in-repo.

1. **~97% of PARENT turns never reach the LLM.** 36 of 37 fresh turns short-circuited (`evals/phase1_baseline.json`). Direction, not exact figure — inflated by first-turn welcome + the registration-closed fallback.
2. **`parent_flow.py` has 43 `_maybe_*` interceptors** and is 11,318 lines.
3. **The hoist pattern already exists and works.** `parent_flow.py:1002` routes a dynamic-program turn straight to the engine, above the whole camp chain. Proven live 2026-07-20 ("ფორმულა1"). **Phase 3 generalises this; it does not invent it.**
4. **The hoist bypasses every guardrail below it.** It `return`s ~line 1021; injection (1082), political (1162), underage (1434), out-of-range age (1470), contact/PII (1478) and 2 post-engine ineligible-age scrubbers are all unreachable on that path. Audit: `.superpowers/sdd/p3-guardrail-bypass-audit.md`.
   - Under-age + program → ineligibility goes **unstated** (booking action still blocked by the executor).
   - Injection + program → was a **real gap**; **fixed** in `e7d2a1f` (guard now called inside the hoist branch; existing call site deliberately not moved).
   - PII + program → **no gap** (engine-internal phone fallback still runs).
5. **The PARENT prompt had no injection rule at all** — `_build_system_prompt` loads exactly one file (`parent_llm_engine.py:2710`). Rule added to both prompts in `e7d2a1f`.
6. **Prompt/sanitizer hygiene is NOT the root cause.** Phase 4 measured a negative result (`docs/MEASURE_PHASE4.md`): no naturalness gain, and Q2 correctness **regressed 3/3 → 0/3** under the lean prompt. Both flags stay OFF.
7. **The model is a secondary constraint, not the binding one.** `docs/MEASURE_PHASE3_0B_MODEL_PROBE.md`: gpt-4.1-mini 8/12 vs gpt-5.4-mini 10/12 correctness; 0 `forbid_any` violations either model; latency equal. *"Today's model is barely consulted"* — you cannot tell whether the model is the ceiling when it gets 3% of turns.
8. **The sharpest failure is grounding, not wording.** On Q2 the current model called `get_camp_info` and then **omitted the returned price in 3/3 reps**. This is precisely the failure that breaks "facts from the backend".
9. **The eval suite measures TEXT, not EFFECT, and is currently invalid as an instrument.** Only **4 of 23** stochastic cases reach the LLM (Q2, OB2, U11, R4); 12 are captured by the registration-closed fallback because the camp ended 2026-07-20 — *most of those would have reached the engine a week earlier*. And `evals/cases.py::_r4_overage_adult_switch` passes on `("ზრდასრულ" in out) OR (... in tools)` — an **OR**, so merely *mentioning* the word scores 3/3 while `switch_to_adult_flow` never ran. The harness already tracks `h.last_tool_calls`; it just doesn't require it.

---

## 3. Architecture

### 3.1 The key decision: polarity inversion

A domain classifier (`_is_llm_first_domain(message)`) would be a **44th substring interceptor** — the exact pathology being removed, and the "shared Achilles heel" already named in the project's own critique.

**So invert the polarity: do not classify what goes to the LLM. Classify what must NOT.**

```
default                = LLM-first
deterministic exception list = the guardrail zone (money / booking / contact / eligibility)
```

The exception list is small, stable, and semantically motivated — the roadmap already calls those interceptors "features, not bugs". **Its true size is unverified (see 3.0-T3); the previously-cited "~8–10" was a guess and must be counted.**

### 3.2 Four layers

```
Layer 0 — SAFETY SPINE (always, every path, program-scoped not camp-hardcoded)
          injection · political · PII · age eligibility
Layer 1 — DETERMINISTIC EXCEPTION LIST (short)
          booking commit · price quote · contact capture
          → never the model's decision
Layer 2 — LLM reasons + calls tools          ← DEFAULT
Layer 3 — POST-VALIDATOR (minimal)
          only cheaply checkable facts (digits, dates, phone)
```

Layer 0 is what makes hoisting safe. It does not exist today — guardrails are scattered through an ordered chain, which is why the hoist could bypass them.

**Generalisation requirement:** most bypassed layers hardcode camp wording. Re-running them wholesale would answer a robotics-club question with *"the camp is 9–17"*. Layer 0 must be **program-scoped** (`get_camp_age_bounds` → per-program bounds).

---

## 4. Phases

> **Decomposition note.** This spec covers a whole roadmap phase, which is too large for one implementation plan. **Phase 3.0 gets the first plan and is the only thing to be planned now.** 3.1 (a high-risk refactor of an 11k-line file) and 3.2 (N domains × measure) each get their own spec → plan cycle, written *after* 3.0's findings — because 3.0-T3 and 3.0-T5 can legitimately force both to be re-scoped.

### Phase 3.0 — Instrument & metric — **BEFORE any production code**

Direct answer to the project's repeated failure mode: *build → measure → nothing*, three times running (Phase 2 unmeasured, Phase 3-pilot no effect, Phase 4 negative).

- **T1 — Per-interceptor attribution.** Which of the 43 fires, how often. In the instrument, not in `app/` (same technique as the Task-5 sanitizer firing-rate probe).
- **T2 — Rebuild the eval as a valid instrument.**
  - cases that **provably reach the engine** (assert engine invocation ≥ 1, or the case is marked confounded and excluded from model/architecture comparisons)
  - **assert EFFECT, not text** — require the tool call (`AND`), never accept a mention of it (`OR`)
  - resolve the date-dependency introduced by the camp ending (see OPEN QUESTION 1)
- **T3 — Count the exception list.** Enumerate every guardrail-class interceptor honestly. If it is ~25 rather than ~10, polarity inversion buys materially less and the plan must be re-scoped **before 3.1**.
- **T4 — Define the metric.**
  ```
  PRIMARY   correctness + responsiveness (did it answer? are the facts right?)
  GROUNDING did the reply's facts come from a tool payload?   ← the Q2 failure
  VETO      forbid_any (invention / pressure) — one is enough to fail
  SECONDARY naturalness — tie-break only, never overrides correctness
  ```
  Rationale: Phase 4 proved *more natural* can mean *less correct*. Grounding is the advisory-domain answer to "effect is text" (§5, attack 2).
- **T5 — Per-domain baseline.** What does the **canned** answer score today, per domain, on this metric.

**Exit:** we know which domain is worst today **and** how we will detect improvement.

### Phase 3.1 — Safety spine — 🔴 highest-risk phase

Extract scattered guardrails into one layer that runs identically on every path, and generalise camp-hardcoded rules to program-scoped.

**This is a refactor of an 11,318-line file with 5,151 tests, where the guards are order-dependent.** This project's history is full of ordering bugs (sanitizer entry 69 shadowing 71; the hoist's precedence). It requires its own risk plan, byte-identity proofs per guard, and incremental landing — it is not a single task.

**Exit:** hoisting is safe; §2.4 is structurally closed.

### Phase 3.2 — Invert polarity, domain by domain

Per domain: move it from the exception list to LLM-first behind a flag → measure with the 3.0 metric → **LLM ≥ canned keeps it; LLM < canned reverts it.**

Start with a domain where the canned answer is **bad today** — not one where it is good.

**Model upgrade rides alongside as de-risking** (grounding was measurably better on gpt-5.4-mini), **not as a prerequisite.**

### Phase 3.3 — Knowledge → tools
As a domain flips, its knowledge becomes a tool backed by an operator-editable file.

### Out of scope (Phase 5)
semantic matching (replacing substring triggers) · closing the learning loop · ADULT parity · operator UI for skills/approved-answers.

---

## 5. Adversarial review — attacks and resolutions

| # | Attack | Resolution |
|---|---|---|
| 1 | **Phase 3 may complete and change nothing** if canned beats LLM on most domains | **Accepted as a real outcome.** 3.0-T5 tests it before 3.2 commits. Written into the plan rather than discovered late. |
| 2 | "Assert effect" doesn't work for advisory domains — there, effect *is* text | **Grounding assertion** (3.0-T4): are the reply's facts traceable to a tool payload? Checkable, and targets the exact Q2 failure. |
| 3 | "~8–10 exceptions" was invented | **3.0-T3 counts it.** Re-scope gate before 3.1. |
| 4 | 3.1 is a high-risk refactor described in one paragraph | Flagged 🔴; gets its own risk plan and incremental landing. |
| 5 | We author the ground truth we then optimise against | **RESOLVED (§6/OQ2):** ground truth = grounding-in-product-facts + responsiveness + forbid, NOT hand-written answers. Operator rejected hand-written answers as re-creating the template pathology. |
| 6 | The camp is over — what is the agent even selling? | **RESOLVED (§6/OQ1):** whatever the operator adds to the panel — product-agnostic. This *forces* polarity inversion (no interceptor can exist for a not-yet-added product). |

---

## 6. OPEN QUESTIONS — RESOLVED 2026-07-22 (operator)

**OQ1 — RESOLVED: the product is not fixed; it is whatever the operator adds.**
There is no single "what to sell". The camp is over; Sunday School will come; adult events; **and anything the operator adds in the admin panel later.** The requirement is therefore product-agnostic: *whatever is added in the panel must be sold correctly, and the customer's question analysed.*

**Design consequence (this is the strongest argument for polarity inversion in the whole spec):** you **cannot** write a deterministic interceptor for a product that does not exist yet. A hardcoded handler can only serve the products someone hand-coded (camp / Sunday School / adult events). The only mechanism that can sell an *arbitrary future admin-added product* is the LLM reasoning over that product's data via a **generic tool**. Polarity inversion is thus not a stylistic preference — it is **forced** by the operator's goal.
- The **info-answering** half of this is already built and proven live: `USE_DYNAMIC_PROGRAMS` → `list_programs`/`get_program_info` answered "ფორმულა1" from admin data with no code change (2026-07-20).
- The **not-yet-built** half: each product type needs its *appropriate* action + lead, generalising what camp has. Camp = consultation booking + lead. Sunday School = email handoff + lead. Adult events = subscription + lead. A new admin product today gets info-answering only. **Generalising "every product gets its own function + lead, per product type" is a Phase 3.2/3.3 goal** — partially built, not to be scoped now.

**OQ2 — RESOLVED, and the original proposal was WRONG (operator corrected it).**
The proposal was: operator hand-writes model answers for 15–20 questions. The operator rejected this with the decisive insight: *"if I write the answer to a specific question, it then works like a bot and can't understand a differently-phrased question."* **Writing per-question answers re-creates the exact template pathology we are removing.** So:
- **Client provides PRODUCT FACTS** (price, dates, eligibility, what's included, handoff rules) — via the admin panel / data files. **Not answers.**
- **Operator QAs grammar** on the Georgian output.
- **Ground truth for the eval is therefore NOT a hand-written answer.** It is: *did the reply (a) answer the question that was actually asked, (b) use the correct product facts from the tool payload (**grounding** — the Q2 failure), and (c) invent nothing / apply no pressure (**forbid**).* This is checkable from the product facts alone, needs no canned reference answer, and **cannot be gamed by parroting a template** — a template that ignores the question fails (a); one that invents fails (c).
- The existing `approved_answers.yaml` (operator-written answer for a trigger) stays only as a narrow **escape hatch**, never the primary path — using it as the mechanism is the bot behaviour the operator is rejecting.

### Hard constraint added by the operator (2026-07-22): existing capabilities must NOT break

These are the deterministic exception list (Layer 1) and are explicitly OUT of scope for relaxation:
- **booking** (ჯავშანი) · **lead capture** (ლიდების ჩაწერა) · **manager-number handoff** (მენეჯერის ნომრის გადაცემა).

And the product goal, stated plainly by the operator: *"the main thing is the agent be as smart and human as possible and not return memorised text templates."*
**How the anti-template win is achieved — and how it is NOT measured:** the improvement comes **structurally**, from removing the interceptors that emit canned templates, not from optimising a naturalness score. Phase 4 proved naturalness fails as a gate (Q2 got *more natural and less correct*). So the metric (§3.0-T4) **guards against correctness/grounding regression**; the "smart and human, not templated" gain is delivered by the architecture change itself, and confirmed by the drop in canned-template firing (T1's attribution counter), not by chasing a naturalness number.

---

## 7. Risks

| Risk | Status |
|---|---|
| LLM may not beat canned on most domains | Untested. 3.0-T5 gates it. |
| 3.1 refactor breaks ordering | 🔴 High. Own risk plan; byte-identity per guard. |
| Exception list larger than assumed | Unverified. 3.0-T3 re-scope gate. |
| Cost/latency of inverting ~97% of turns | Latency measured ≈2s, model-independent. Per-turn **cost** is an operator decision. |
| `USE_DYNAMIC_PROGRAMS` state in Railway | **Unknown to us.** Code is on the deploy branch (`origin/feat/camp-topic-facts@5435237`); flag state is an operator fact. |
| **Another re-plan** | **~30–40%**, based on this project's measured base rate: the last three measured phases returned negative or no effect. |

---

## 8. Effort estimate

Working sessions (1 session ≈ 1 focused day):

| Stage | Sessions |
|---|---|
| 3.0 instrument + eval rebuild + metric | 3–5 |
| 3.1 safety spine | 4–7 |
| 3.2 domain-by-domain (meaningful subset) | 5–9 |
| **Architecture inverted** | **12–21** |
| Phase 5 | 8–15 |
| **"openclaw-like"** | **20–36** |

With one re-plan cycle included: **30–50 sessions.**

---

## 9. What this will and will not produce

**Will:** an agent that analyses varied questions, searches via tools, and does not invent — because facts come from the backend.

**Will not:** full openclaw. Booking, price and PII will **never** be the model's decision. Claude Code can improvise because a mistake means bad code; here a mistake means a wrong price quoted to a customer.

The correct target, in the operator's own words:

> **openclaw-like in reasoning — deterministic in commitments.**
