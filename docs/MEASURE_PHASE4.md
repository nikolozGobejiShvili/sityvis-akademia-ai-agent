# MEASURE_PHASE4 — staged A/B of `USE_LEAN_PROMPT` / `USE_LEAN_SANITIZER`

**Date:** 2026-07-21 · **Branch:** `feat/dynamic-programs` (local) · **HEAD at measurement:** `b13b391`
**Plan:** `docs/superpowers/plans/2026-07-21-phase4-prompt-hygiene.md` — Task 5, Step 4 (staged subset).
**Engine:** `USE_PARENT_LLM_ENGINE=true`, `OPENAI_MODEL=gpt-4.1-mini`. **Judge:** OpenAI (`EVAL_JUDGE_BACKEND` default), naturalness = judge-internal **N=3 median** per graded reply.
**Cases:** OB1, OB2, OB3, Q2, Q8 (objection / advisory). U-set not run.
**Baseline artifact:** `evals/baseline.json` snapshotted before and restored after every `--llm` run; final md5 **`93973fcd10349b447f87fa320e0807f3`** (unchanged).

> **Scope caveat, stated up front.** `tools/scenario_runner_full.py --priority CRITICAL` (22/22) and the
> guardrail-domain reliability check (`booking_reliability`, `contact_capture`) were **NOT run** in this
> staged pass — they are a separate spend approval. **The full binding gate is therefore incomplete by
> design.** Nothing below should be read as gate-clearing evidence for enablement.

---

## 1. Headline: OB1 is not measuring what Phase 4 changes

**The OB1 replies are byte-identical across all three configs, and byte-identical across all three
repetitions within each config.** md5 of the reply text is `2e0da6f5880214d904cf74b7ccefed49` in every
one of the nine OB1 runs.

The reason is not the giant prompt. OB1's message
(`ჩვენს ბიუჯეტს სცდება ეს თანხა, ფასდაკლება არ გაქვთ?`) matches
`app/flows/parent_flow.py::_is_camp_price_full_block_question` (verified `True`), which returns the
deterministic approved price block `_camp_price_full_block()` (copy from
`app/agent/templates/parent/price.yaml`), with the consultation CTA removed by
`_strip_closed_registration_cta()` because `_is_camp_registration_open()` is `False`.

**OB1 never reaches the parent LLM.** Corroborating instrumentation: `sanitise_response_wording()` — which
sits on the LLM reply path — was invoked **0 times** for OB1 in every config (see §5).

Consequence: **the 0.00/4 OB1 naturalness baseline is a deterministic template, not a prompt artifact.**
Neither `USE_LEAN_PROMPT` nor `USE_LEAN_SANITIZER` can move it, by construction. The earlier finding that
OB1 was byte-identical with the reasoning layer on vs off has the same explanation — it was never
evidence about the prompt at all. **OB1 is marked inconclusive for Phase 4** and cannot serve as the
anchor it was intended to be.

### OB1 reply, verbatim — all three configs

**baseline (both flags OFF)**
```
ბანაკის ფასი არის 2150 ლარი.

ამ თანხაში შედის ტრანსპორტირება, განთავსება, კვება და სრული პროგრამა.

გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ის და საქართველოს ბანკის საშუალებით.

10%-იანი ფასდაკლება მოქმედებს დედმამიშვილებისთვის და წინა ბანაკის მონაწილეებისთვის.
```

**+lean prompt (`USE_LEAN_PROMPT=true`)**
```
ბანაკის ფასი არის 2150 ლარი.

ამ თანხაში შედის ტრანსპორტირება, განთავსება, კვება და სრული პროგრამა.

გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ის და საქართველოს ბანკის საშუალებით.

10%-იანი ფასდაკლება მოქმედებს დედმამიშვილებისთვის და წინა ბანაკის მონაწილეებისთვის.
```

**+lean prompt +lean sanitizer**
```
ბანაკის ფასი არის 2150 ლარი.

ამ თანხაში შედის ტრანსპორტირება, განთავსება, კვება და სრული პროგრამა.

გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ის და საქართველოს ბანკის საშუალებით.

10%-იანი ფასდაკლება მოქმედებს დედმამიშვილებისთვის და წინა ბანაკის მონაწილეებისთვის.
```

**Do they differ? No — they are identical, byte for byte, in all three configs.**

---

## 2. Confounded cases

| case | status | evidence |
|---|---|---|
| **OB1** | **INCONCLUSIVE — deterministic price-block interceptor** | Never reaches the LLM; identical in 9/9 runs. Not the "registration closed" fallback — a different, harder confound. |
| **OB3** | **INCONCLUSIVE — registration-closed fallback** | `ბანაკის ბოლო ნაკადი უკვე დაიწყო და რეგისტრაცია დასრულებულია.` in **3/3 reps in all 3 configs**. Correct behaviour (last stream ended 20 July 2026), but it measures nothing about objection handling. |
| **Q8** | **INCONCLUSIVE — registration-closed fallback** | Same: 3/3 reps in all 3 configs. |
| OB2 | live LLM turn | 0/3 fallback in every config. |
| Q2 | live LLM turn | 0/3 fallback in every config. |

**Only OB2 and Q2 carry any signal.** Three of the five requested cases, including the designated anchor,
measured nothing. Neither "no regression" nor "no improvement" may be claimed for OB1, OB3 or Q8.

---

## 3. Per-config results

### 3a. Naturalness — the binding metric

Harness metric (one representative reply per case, judge-internal N=3 median). No case was SKIPped;
every `0.00/4` below is a real judged score, not a missing value.

| case | baseline | +lean prompt | +lean prompt +lean sanitizer | note |
|---|---|---|---|---|
| OB1 | 0.00/4 | 0.00/4 | 0.00/4 | **confounded** — deterministic template |
| OB2 | 2.00/4 | 1.00/4 | 3.00/4 | live |
| OB3 | 0.00/4 | 0.00/4 | 0.00/4 | **confounded** — fallback |
| Q2  | 3.00/4 | 2.00/4 | 4.00/4 | live |
| Q8  | 0.00/4 | 0.00/4 | 0.00/4 | **confounded** — fallback |

Because that column rests on a single graded reply per cell, all three reps of the two live cases were
additionally graded (judge-only replay of already-captured text — no extra engine calls, `baseline.json`
untouched):

| case | metric | baseline | +lean prompt | +lean prompt +lean sanitizer |
|---|---|---|---|---|
| OB2 | per-rep | 2, 2, 2 | 1, 2, 4 | 3, 0, 4 |
| OB2 | **median** | **2** | **2** | **3** |
| OB2 | mean | 2.00 | 2.33 | 2.33 |
| Q2 | per-rep | 3, 1, 3 | 2, 3, 3 | 4, 3, 3 |
| Q2 | **median** | **3** | **3** | **3** |
| Q2 | mean | 2.33 | 2.67 | 3.33 |

**This materially weakens the single-reply column.** Q2's apparent `3.00 → 2.00 → 4.00` swing collapses to
a flat median of 3 once all reps are graded; OB2's `2.00 → 1.00 → 3.00` collapses to `2 → 2 → 3`. The
per-rep spread is large (OB2 under both flags: 3, 0, 4). **At N=3 reps on 2 live cases there is no
statistically meaningful naturalness change** — only a weak, non-significant upward drift in the means.

### 3b. Correctness — conversion proxy (`require_any` / `forbid_any`, majority-of-3)

| case | baseline | +lean prompt | +lean prompt +lean sanitizer |
|---|---|---|---|
| OB1 | 2/2 ✅ | 2/2 ✅ | 2/2 ✅ (confounded) |
| OB2 | 1/2 | 1/2 | 1/2 |
| OB3 | 1/2 | 1/2 | 1/2 (confounded) |
| **Q2** | **1/1 ✅** | **0/1 ❌** | **0/1 ❌** |
| Q8 | 1/2 | 1/2 | 1/2 (confounded) |

Per-rep tallies for the checks that failed:

| case | check | baseline | +lean prompt | +lean prompt +lean sanitizer |
|---|---|---|---|---|
| **Q2** | `value/payment framing present` | **3/3 pass** | **1/3 pass** | **0/3 pass** |
| OB2 | `require_any(კარგ/მოგვიანებით/ნებისმიერ/დაგვიკავშირ/შემოგწერ)` | 1/3 | 0/3 | 1/3 |
| OB3 | `require_any(განვადება/გადახდის/…)` | 0/3 | 0/3 | 0/3 (fallback) |
| Q8 | `require_any(განვადება/გადახდის/…)` | 0/3 | 0/3 | 0/3 (fallback) |

**`forbid_any` held everywhere.** The `avoids wrong-behaviour signals` check failed in **0 of 15**
case×config runs: no invented discount (`50%`, `100%`, `20%`, `ფასდაკლება 50`) and no pressure wording
(`დღესვე`, `ბოლო ადგილ`, `აუცილებლად ახლავე`) appeared in any reply, in any config.

**But `require_any` did NOT hold.** Q2 is a clean, monotonic correctness regression under the lean prompt:
the price objection `ძვირია` stops being answered with value/installment framing and becomes a bare
discovery question. Baseline (all 3 reps open with the value block):

> `გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია.` / `ბანაკის ღირებულებაში შედის ტრანსპორტირება, კომფორტული განთავსება, სრულყოფილი კვება და მრავალმხრივი პროგრამა.` / `გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ისა და საქართველოს ბანკის საშუალებით.` / `რა არის მთავარი, რის მიღებაც გსურთ ბანაკიდან …`

Under both flags (all 3 reps, no value or payment content at all):

> `გასაგებია. მაინტერესებს, რას ელოდებით ბანაკისგან და რა არის მთავარი, რაც თქვენი შვილისთვის მნიშვნელოვანი იქნება ზაფხულის პერიოდში?`

The replies read better and **sell less**. That is precisely the failure mode the conversion-proxy
`require_any` exists to catch, and it is the most important result in this document.

### 3c. Canned footprint — DIAGNOSTIC ONLY

Reported for the lean-**PROMPT** step only. **Not reported as evidence for the lean-SANITIZER step**: the
sanitizer produces the very phrases the footprint counts, so a drop there is tautological.

`evals/botlike_proxy.canned_footprint`, mean over 3 reps:

| case | baseline | +lean prompt |
|---|---|---|
| OB1 | 0.00 | 0.00 |
| OB2 | 0.00 | 0.00 |
| OB3 | 0.00 | 0.00 |
| Q2 | 0.00 | 0.33 |
| Q8 | 0.00 | 0.00 |

The footprint proxy is **uninformative on this turn set** — it is at or near zero everywhere, including
for OB1, which is a maximally canned deterministic template. It detects neither the confound nor the Q2
regression, and the one non-zero cell moved the wrong way. It should not be relied on here.

---

## 4. Per-entry sanitizer firing rates (Task 4 review item A)

Measured by wrapping `parent_llm_engine.sanitise_response_wording` in a throwaway instrumented delegate
(production code unmodified). For each call the wrapper reproduces the structural pre-passes
(`_collapse_duplicated_tu` → `_strip_concern_wording` → `_apply_dynamic_fact_normalisations`), then walks
the rewrite table in declaration order exactly as the real loop does, recording which indexes actually
fire — both against the **full 183-entry table** (what would fire) and against the **171-entry safety
subset** (what did fire) — before delegating to the real function.

**Result, all three configs: `sanitise_response_wording` was invoked 6 times per config, and ZERO of the
183 entries fired.**

| config | invocations | per-case | distinct table entries fired |
|---|---|---|---|
| baseline | 6 | OB1 0, OB2 3, OB3 0, Q2 3, Q8 0 | **0 / 183** |
| +lean prompt | 6 | OB1 0, OB2 3, OB3 0, Q2 3, Q8 0 | **0 / 183** |
| +lean prompt +lean sanitizer | 6 | OB1 0, OB2 3, OB3 0, Q2 3, Q8 0 | **0 / 183** |

Firing count for each of the 12 dropped indexes, in every config:

| idx | 24 | 58 | 59 | 60 | 68 | 69 | 98 | 155 | 156 | 157 | 161 | 162 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| firings | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

**Top-N most-fired retained entries: there are none.** No retained entry fired either.

**Instrumentation validation.** In the baseline config the real sanitizer did change 3 of its 6 inputs.
Those changes were traced and attributed entirely to `_strip_concern_wording` — a *structural* pass that
is retained under the lean flag — not to the literal table; applying the table to the post-structural text
reproduced the real output exactly (`post-table == final` in all 3 cases). The zero-firing result is
therefore a measurement, not an instrumentation failure.

**Interpretation.** On this turn set the sanitizer's rewrite table is inert. OB1, OB3 and Q8 never reach
it at all (deterministic paths), and on the 6 replies that do reach it, nothing matched. The Task 4 review's
open question — whether "12 of 183" understates impact because the dropped entries cluster in
high-frequency turn positions (closings 155–157, slot questions 161–162) — **is not answered by this pass**:
those positions simply did not occur in an objection/advisory turn set. It remains open and needs a turn set
that exercises closings and slot questions. What this pass does establish is that the lean-**sanitizer**
flag was a **no-op on every turn measured here**, so no difference between config 2 and config 3 can be
attributed to it.

---

## 5. Did sanitizer entries 99/100 fire on OB1? (Task 4 review item B)

Entries 99/100 rewrite the objection opener `ეს გასაგები მოტივაციაა` →
`გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია`. They were deliberately kept because
`parent_lean.md:88` carries the prompt ban `აკრძალული: „მოტივაცია", „იაფია"`, so they should fire only
if the model violates that ban.

**Answer: NO. Entries 99 and 100 did not fire in any config — 0 firings in baseline, 0 under the lean
prompt, and 0 under lean prompt + lean sanitizer.** They also would not have fired under the full table
in any config (`would_fire: 99=0, 100=0` everywhere).

They could not have fired on **OB1** under any circumstances: OB1 never reaches
`sanitise_response_wording` at all (0 invocations). On the two cases that do reach it:

* **Baseline** — the model *emitted the approved replacement text verbatim on its own*
  (`გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია.` opens all 3 Q2 replies). It is mandated
  word-for-word at `system_parent_v2.md:387`, so entries 99/100 had nothing left to rewrite. The
  convergence was achieved by the **prompt**, not the sanitizer.
* **Under the lean prompt** — that phrase disappears from the output entirely, and the banned
  `მოტივაცია` / `იაფია` wording did not appear in its place.

**The ban was not violated.** There is no red flag here. The finding worth carrying forward is the
mechanism it exposes: on these turns the giant prompt, not the rewrite table, is what forces the
canned phrasing.

---

## 6. Verdict against the binding gate

Binding gate (partial — see the scope caveat): **naturalness ↑ from the 0.00/4 baseline AND correctness held.**

### `USE_LEAN_PROMPT` — **GATE NOT CLEARED**

* **Naturalness ↑ from 0.00/4:** **NO.** The 0.00/4 anchor is OB1, which is a deterministic template the
  flag cannot reach; OB1 is byte-identical across all three configs. On the two cases that are live,
  all-rep medians are flat (OB2 2→2, Q2 3→3).
* **Correctness held:** **NO.** Q2 regressed from 3/3 to 1/3 reps on `value/payment framing present`.
  `forbid_any` did hold (0/15 failures), but the reply stopped selling.
* **Recommendation:** do not enable. The flag traded a real correctness loss for no measurable
  naturalness gain.

### `USE_LEAN_SANITIZER` — **INCONCLUSIVE (measured nothing)**

* Zero of the 183 rewrite entries fired on any evaluated turn in any config, so the flag was a **no-op on
  this turn set**. The config-2→3 naturalness differences cannot be attributed to it.
* Q2 correctness remained regressed at 0/1 (0/3 reps) with the flag on — i.e. it did not repair the lean
  prompt's regression.
* Per instruction, footprint is **not** cited as evidence here.
* **Recommendation:** do not enable, and do not re-measure it on objection/advisory turns — measure it on
  a turn set that actually exercises closings (155–157) and slot questions (161–162).

### Not run in this pass

`tools/scenario_runner_full.py --priority CRITICAL` (22/22) and `booking_reliability` / `contact_capture`
guardrail-domain reliability were **not executed** (separate spend approval). **The full binding gate is
incomplete by design.** Since the flags already fail the portion of the gate that *was* measured, running
the remainder would not change the recommendation.

### What this measurement actually taught us

The Phase 4 hypothesis — that the 467-line scripted prompt is what makes the objection reply robotic — is
**not supported for the case it was built around.** OB1's 0.00/4 comes from a deterministic pre-LLM
interceptor in `parent_flow.py`, and OB3/Q8 come from the registration-closed fallback. Three of five
cases in the designated measurement set never invoke the LLM. If the objection reply is to be made more
natural, the work is in `_is_camp_price_full_block_question` / `_camp_price_full_block` — the deterministic
template path — not in the system prompt or the sanitizer. **A prompt-level fix cannot move a reply the
prompt never produces.**

---

## 7. Reproduction

```
# per config, one fresh process (settings are @lru_cache'd)
cp evals/baseline.json <safe>
USE_PARENT_LLM_ENGINE=true PYTHONIOENCODING=utf-8 \
  .venv/Scripts/python.exe -m evals.run_evals --llm --judge --case OB1
# ... + USE_LEAN_PROMPT=true ... + USE_LEAN_PROMPT=true USE_LEAN_SANITIZER=true
cp <safe> evals/baseline.json
```

`evals/baseline.json` was snapshotted before and restored after every `--llm` run. **Final md5:
`93973fcd10349b447f87fa320e0807f3` — byte-identical to the pinned value.** It was never committed.

Measurement scripts were throwaway and live outside the repository; no file under `app/`, `tests/`,
`evals/`, `data/admin_config/`, `CLAUDE.md` or `HANDOFF.md` was modified. Both flags remain default OFF.
