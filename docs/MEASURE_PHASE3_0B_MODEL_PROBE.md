# MEASURE — Phase 3.0b · Model-Tier Probe (`gpt-4.1-mini` vs `gpt-5.4-mini`)

**Date:** 2026-07-22 · **Branch:** `feat/dynamic-programs` (local only)
**Question:** the remaining roadmap (converting ~40 deterministic interceptors so the model
drives the conversation) assumes the model is good enough that more latitude produces
better answers. Phase 4 case **Q2** pointed the other way (scripted prompt 3/3, lean
prompt 0/3). **Is the model the binding constraint, or is the ceiling elsewhere?**

Scope guard: prompt held constant (`USE_LEAN_PROMPT` / `USE_LEAN_SANITIZER` both OFF —
the lean prompt already failed its own measurement). The ONLY variable is `OPENAI_MODEL`,
supplied per-process via the environment. `.env` and `app/config.py` were not modified.

---

## 1. Step 1 — which eval cases GENUINELY reach the LLM

### Method

The Phase 4 lesson was that the eval set silently measured deterministic templates
(**OB1** is intercepted by `parent_flow._is_camp_price_full_block_question` →
`_camp_price_full_block()` and never reaches the model). So before spending anything,
engine invocation was measured empirically rather than assumed.

- Spy installed on **`app.services.openai_service.chat_with_tools`** — *not* on
  `run_parent_llm_turn`, so every engine-internal fallback stays intact and a case that
  enters the engine but bails inside it is still counted honestly.
- Each case was driven through its **own** seed + message via the real
  `conversation_service.process_message` path (the case functions themselves were
  executed — no re-implementation of their inputs).
- Ran under `evals.safety.install_readonly(log, block_httpx=True)` — httpx hard-blocked,
  so a live OpenAI call was physically impossible. **Zero cost, zero tripwires.**
- All **23** cases flagged `stochastic=True` in `evals/cases.py` were probed.
- Driver: `probe_interception.py` (throwaway, kept outside the repo).

### Result — 4 live, 19 confounded

| Verdict | Cases | Count |
|---|---|---|
| **LIVE — genuinely invokes the LLM** | **Q2, OB2, U11, R4** | **4 / 23** |
| Confounded — deterministic reply | U4, Q1, U7, U8, U9, U10, R7, R8, R9, R10, R11, Q6, Q7, Q8, Q9, Q10, OB1, OB3, PI2 | 19 / 23 |

Confounded cases broken down by **which** deterministic path answered them:

| Interceptor / path | Cases | Note |
|---|---|---|
| Registration-closed fallback (`ბანაკის ბოლო ნაკადი უკვე დაიწყო...`) | U7, U9, U10, R7, R8, R11, Q6, Q8, Q9, Q10, OB3, PI2 (12) | **Correct behaviour** — the camp genuinely ended 2026-07-20. Not a bug. |
| Camp-price full block template | U4, OB1 (2) | The OB1 confound identified in Phase 4; U4 shares it. |
| Manager-number disclosure | U8 | |
| Sunday-School status render | R9 | |
| Static welcome menu | R10 | |
| Prompt-injection guard | Q7 | |
| Never enters the flow at all (calls `camp_topic_facts` directly) | Q1 | Tagged `stochastic=True` but is a pure helper assertion. |

**This is itself a major finding.** Only 17% of the eval suite's "LLM" cases currently
exercise the model. Two structural causes:

1. **Date-dependent.** 12 of the 19 are confounded *only* because the camp ended two days
   ago. Before 2026-07-20 most of these would have reached the engine. The suite's LLM
   coverage silently collapses as the season ends — it is not a stable instrument.
2. **Architectural.** The remaining 7 are confounded permanently by interceptors and
   templates. This is exactly the ~97% interception rate the roadmap intends to invert,
   observed from the eval side.

Practical consequence: **any conclusion below rests on 4 cases, 2 of which
(`OB2`, `U11`) are near-duplicates** (both are soft-hesitation/decline turns sharing the
same `require_any` list). The evidence is **directional, not conclusive.**

---

## 2. Step 2 — the A/B

Both configs identical except `OPENAI_MODEL`. `USE_PARENT_LLM_ENGINE=true`, both lean
flags OFF, verified from the boot line in each process:

```
[A] [openai] model=gpt-4.1-mini  token_param=max_tokens
[B] [openai] model=gpt-5.4-mini  token_param=max_completion_tokens
```

Config B resolved through the `5.4` → `max_completion_tokens` branch of
`openai_service._build_completion_kwargs` correctly, so B was measured, not a broken
config. N = 3 reps per case per config (24 engine turns total). Driver:
`probe_model_ab.py` — deliberately does **not** call `evals.harness.run_all`, because
`run_all(llm=True)` overwrites `evals/baseline.json`.

### Correctness (PRIMARY) + forbid_any (VETO) + naturalness (SECONDARY) + latency

| Case | Metric | **A · gpt-4.1-mini** | **B · gpt-5.4-mini** |
|---|---|---|---|
| **Q2** — price objection → value framing | `require_any` | **3/3** | **3/3** |
| | `forbid_any` | n/a (none defined) | n/a |
| | naturalness (median of 3) | 3/4 | 3/4 |
| | latency mean | 3.50 s | 3.05 s |
| **OB2** — soft hesitation → patient close | `require_any` | **2/3** | **3/3** |
| | `forbid_any` | 3/3 clean | 3/3 clean |
| | naturalness | 1/4 | **3/4** |
| | latency mean | 1.47 s | 1.49 s |
| **U11** — soft decline + future intent | `require_any` | **0/3** | **1/3** |
| | `forbid_any` | 3/3 clean | 3/3 clean |
| | naturalness | 2/4 | 2/4 |
| | latency mean | 1.38 s | 1.39 s |
| **R4** — age > 17 → adult switch | `require_any` | **3/3** | **3/3** |
| | `forbid_any` | n/a | n/a |
| | naturalness | 3/4 | 2/4 |
| | latency mean | 1.75 s | 2.65 s |
| **TOTAL** | **correctness reps passing** | **8 / 12** | **10 / 12** |
| | **forbid_any violations** | **0 / 6** | **0 / 6** |
| | naturalness (mean of medians) | 2.25 / 4 | 2.50 / 4 |
| | **latency mean / p95 (all turns)** | **2.03 s / 3.48 s** | **2.14 s / 2.90 s** |

**VETO: neither model produced a single `forbid_any` violation.** No invented discount, no
pressure wording, in any of the 24 turns. This is the one unambiguous result: the safety
floor is held by the prompt + sanitiser, and does not depend on the model tier.

### Caveats on the correctness numbers

- **U11 is a weak proxy, not a model failure.** Its `require_any` demands one of
  `("კარგ", "მოგვიანებით", "ნებისმიერ", "დაგვიკავშირ", "შემოგწერ")`. B's two "failing"
  reps read `„გასაგებია. როცა უფრო ახლოს იქნებით, მომწერეთ და დაგეხმარებით."` — a
  correct, warm, non-pressuring reply that simply misses the literal token list. Both
  models are being under-credited here; the case measures vocabulary, not conversion.
- **OB2 is a real difference.** A's failing rep abandoned the hesitation entirely and
  emitted a generic camp description (`„სიტყვის აკადემიის ბანაკი 7-დღიანი
  გამოცდილებაა..."`). B stayed on the user's actual turn in all 3 reps.

---

## 3. Tool-calling behaviour — the sharpest difference found

| Case | A · tools called (3 reps) | B · tools called (3 reps) |
|---|---|---|
| Q2 | `get_camp_info` ×3 | `get_camp_info` ×3 |
| OB2 | none | none |
| U11 | none | none |
| **R4** | **none (0/3)** | **`switch_to_adult_flow` (3/3)** |

Engine-loop iterations per turn (OpenAI calls): A = 2,1,1,1; B = 2,1,1,**2**. The extra B
iteration is exactly the R4 tool round-trip.

Two grounding findings, both favouring B:

1. **R4 — A answers correctly-looking text without performing the action.** A replies
   `„ჩვენი ბანაკი 9–17 წლის ბავშვებისთვისაა..."` — recited from the system prompt, with
   **no tool call**, so `switch_to_adult_flow` never ran and the conversation's segment was
   never actually switched. The eval check passes on the wording, so the suite scores this
   3/3 for both models — but only B actually mutated backend state. **A passes the test
   while doing nothing.**
2. **Q2 — A calls the grounding tool and then ignores the result.** Both models call
   `get_camp_info` 3/3. B's reply contains the literal price **`2150` in 3/3 reps**; A's
   contains it in **0/3** — A passes the check only on the softer token `„ღირებულება"`.
   B additionally surfaces the installment terms (TBC / Bank of Georgia, up to 6 months)
   and the 10% sibling discount from the tool payload. Same tool, same data, materially
   more of it used.

This is the most decision-relevant observation in the probe: the gap between the two
models is not mainly in *wording* — it is in **whether tool output actually reaches the
answer**. Grounding is the entire point of the interceptor-conversion work.

---

## 4. Latency

Per-turn, measured end-to-end through `process_message`:

| | mean | p95 | min | max |
|---|---|---|---|---|
| A · gpt-4.1-mini | 2.03 s | 3.48 s | 1.32 s | 3.80 s |
| B · gpt-5.4-mini | 2.14 s | 2.90 s | 1.33 s | 3.65 s |

**Latency is a non-issue for the model choice.** B is ~5% slower on the mean and *faster*
at p95 (it is more consistent). The roadmap's real latency cost is not the model tier —
it is inverting ~97% of turns from free-and-instant interceptors to a ~1.4–3.5 s model
call. That cost is essentially identical under either model, so it must be justified by
answer quality, not deferred to a model upgrade.

---

## 5. Verdict

**The model is a real but secondary constraint. The binding constraint is the
architecture — specifically how much of the conversation the model is allowed to touch,
and whether tool output survives into the answer.**

On the four cases that genuinely reach the LLM, `gpt-5.4-mini` is modestly better on the
conversion-proxy (10/12 vs 8/12 reps), better on the one case with a substantive
difference (OB2 3/3 vs 2/3), and neither model ever violated a `forbid_any` veto — the
safety floor is prompt-and-sanitiser-owned, not model-owned. Naturalness barely moved
(2.50 vs 2.25 of 4) and, consistent with Phase 4, should not be treated as a gate. Latency
is not a differentiator. What *did* separate the two models is grounding discipline: on
R4 the current model produced a correct-looking reply with **zero** tool calls (the
segment switch silently never happened, yet the eval scored it 3/3), and on Q2 it called
`get_camp_info` and then omitted the price figure the tool returned in 3/3 reps, where
`gpt-5.4-mini` called the right tool and used its payload every time. That argues a model
upgrade would make interceptor conversion *safer* — more of the answer would be
tool-grounded rather than prompt-recited — but it does not show that today's model is
what is capping quality, because today's model is barely being consulted: **19 of 23
"LLM" eval cases never reach it at all.** So the honest sequencing is: the upgrade is a
sensible de-risking step to take *alongside* interceptor conversion, not a prerequisite
that unlocks it, and it should not be used to justify raising expectations for the
roadmap. **Strength of evidence: directional only.** Four live cases, two of them
near-duplicates, N=3 — this cannot support a confident quality claim in either direction,
and the biggest single finding here is that the eval suite is not currently a valid
instrument for measuring the model at all (its LLM coverage is date-dependent and
collapsed to 17% once the camp season ended on 2026-07-20). **Rebuilding a small set of
cases that provably reach the engine should precede any further model-vs-model
measurement.**

---

## Appendix — protocol / integrity

- Spend: 24 engine turns + 24 single-run naturalness gradings. Well inside the approved
  $1–3. The 74-scenario runner was **not** run; `--llm` over all 61 eval cases was
  **not** run.
- `evals/baseline.json` snapshotted before the first paid run and md5-verified after
  every step. `run_all()` was deliberately bypassed so nothing could write it.
  **Final md5 = `93973fcd10349b447f87fa320e0807f3`** — byte-identical, never committed.
- READ-ONLY guard active for every turn; tripwires `{}` (zero) in both configs. Calendar /
  Sheets / notifications / outbound DM all stubbed.
- Untouched: `app/`, `tests/`, `data/admin_config/sections.yaml`, `.env`, `CLAUDE.md`,
  `HANDOFF.md`. Model swapped by per-process environment variable only.
- Throwaway drivers live in `~/.claude/jobs/008f606c/tmp/`
  (`probe_interception.py`, `probe_model_ab.py`, `grade_nat.py`), not in the repo.
