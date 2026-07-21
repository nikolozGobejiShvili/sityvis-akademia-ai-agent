# Phase 4 — Prompt & Sanitizer Hygiene (let the model reason) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
>
> **v2 — rewritten 2026-07-21 per the adversarial critique.** Six findings drove the rewrite: **(C1)** guardrail-mapping now PRECEDES the lean prompt (Task 2 before Task 3) so the prompt is written from a verified map, not a guess; **(C2)** "a backend `reason` enforces it" is VERIFIED in `parent_tool_executor.py`, not assumed — guardrails with no backend signal (anti-fabrication, overpromise/pain-mechanism, price-digit, sibling-discount, political off-topic, PII) stay verbatim/explicit; **(C3)** footprint is DIAGNOSTIC only, not the sanitizer's gate (footprint↓ under `USE_LEAN_SANITIZER` is tautological — the sanitizer *produces* the approved phrases the footprint counts); **(H1)** the sanitizer partition is CONSERVATIVE (ambiguous entry → kept as safety); **(H2/S1)** build-now / enable-after-validation — but validation is now POSSIBLE because the naturalness judge works (see below); **(M2)** `_build_sales_context`'s embedded verbatim script is neutralised under the lean flag so the measurement isn't confounded.
>
> **What changed since v1: the validation loop is FIXED.** The eval judge now runs on the operator's live OpenAI key (`gpt-5.4-mini`, `EVAL_JUDGE_BACKEND=openai`), and the naturalness grader is wired into `evals.run_evals --llm --judge` (commit `e2bbba9`). It is proven to discriminate (botlike reply → 0/4, warm human reply → 4/4). **The live OB1 objection reply already scores 0.00/4 naturalness** — that is the concrete baseline this phase must move. So naturalness is no longer "deferred": it is the **binding enable gate**, measurable now.

**Goal:** Let the PARENT model actually reason and vary its wording, by thinning the two layers that force its output to a fixed script — the 122 KB scripted prompt AND (the real culprit) the 183-entry post-LLM sanitizer. Both changes are flag-gated, default OFF, byte-identical off, and enablement is gated on a naturalness gain (measured via the now-working OpenAI judge) with ZERO guardrail regression and correctness held.

**Architecture (grounding-informed):** Two independent, separately-measured flags. (1) `USE_LEAN_PROMPT` → a NEW planner-independent `parent_lean.md` that keeps brand/tone + facts-via-tools + guardrails, dropping a mandated verbatim sentence ONLY where a backend tool `reason` provably enforces the same guarantee. (2) `USE_LEAN_SANITIZER` → a thinned `sanitise_response_wording` path that keeps every strip-only safety entry + structural passes + grammar fixes and drops the wording→wording mandates (the convergence engine). Neither touches the dormant slim/planner path.

**Tech Stack:** Python 3.10, OpenAI gpt-4.1-mini for the agent (unchanged). The eval judge is OpenAI `gpt-5.4-mini` (`EVAL_JUDGE_BACKEND=openai`, default). No new dependency, no agent-model change.

## Global Constraints

- **Both flags OFF ⇒ byte-identical.** `USE_LEAN_PROMPT=False` ⇒ `_build_system_prompt` loads `system_parent_v2` exactly as today AND `_build_sales_context` emits its current text exactly as today; `USE_LEAN_SANITIZER=False` ⇒ the full 183-entry table runs exactly as today. The byte-exact tests (`tests/test_camp_age_bounds_migration_5a2_2026_06_22.py` asserts `_build_system_prompt() == load_prompt("system_parent_v2").format(...)`) MUST stay green — the flag check comes AFTER `_use_slim_prompts()` in an if/elif/else, default off. Full suite (~5071) green.
- **NO guardrail regresses (load-bearing, HIGHEST RISK IN THE PROJECT).** Every one of the ~30 CRITICAL blocks fixed a live bug. A verbatim rule may be replaced by a short behavioral rule ONLY when Task 2's map proves a backend `reason` code in `parent_tool_executor.py` already enforces the guarantee. Where NO backend signal exists, the lean prompt KEEPS the constraint explicitly (verbatim if that's what makes it hold). Task 2 (the map) is the gate on Task 3 (the prompt) — the prompt is not written until the map is reviewed.
- **Sanitizer thinning keeps the SAFETY net, conservatively.** `USE_LEAN_SANITIZER` on ⇒ keep ALL strip-only entries (emoji, unfulfillable-promise strips, fake-booking-phrase strips, PII, mid-conversation-greeting strip) + the structural passes (`_collapse_duplicated_tu`, `_strip_concern_wording`, fact-normalisation) + genuine grammar/spelling fixes; drop ONLY the two-sided wording→wording mandates. **Ambiguous entries (grammar-vs-mandate, e.g. `მოგიწოდებთ→გთხოვთ`, `განვადებაში→განვადებით`) stay in the SAFETY subset** — when unsure, keep it. Nothing is deleted; the table is partitioned, so flag-off is provably the original.
- **The binding ENABLE gate (all must hold, per config):** naturalness ↑ vs the flag-OFF baseline on the advisory cases (OpenAI judge, N=3 median — the OB1 baseline is 0/4 today) **AND** correctness held (the `require_any`/`forbid_any` conversion-proxy still passes — the reply still SELLS, no invented discount/pressure) **AND** CRITICAL 22/22 **AND** guardrail-domain reliability (`booking_reliability`, `contact_capture`) not dropped. Footprint is DIAGNOSTIC only, never a pass/fail target (it is tautologically down under the lean sanitizer). Flags stay OFF regardless; enablement is a separate operator step on this gate.
- **Measure each flag independently, and by the RIGHT metric (Phase-3 lesson + C3):** baseline → +lean-prompt → +lean-sanitizer, one flag per step. The lean PROMPT is measured by naturalness + footprint + correctness. The lean SANITIZER is measured by **naturalness + correctness ONLY** (footprint is meaningless for it — it counts the very phrases the sanitizer produces).
- **No forbidden changes.** Do NOT edit the dormant slim/planner path, `OPENAI_MODEL`, `.env`, Calendar/Sheets/booking logic. Do NOT overwrite `evals/baseline.json` (md5 `93973fcd10349b447f87fa320e0807f3`; snapshot+restore around any `--llm` run). Do NOT commit `data/admin_config/sections.yaml`. New artifacts: `parent_lean.md` + two flags + one guardrail-map doc.
- **Interpreter:** `.venv/Scripts/python.exe`. **LOCAL-only** branch `feat/dynamic-programs`; push only with explicit consent. **No haiku for any subagent.**
- **Expected pre-existing failure:** `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`. Any OTHER failure is in scope.

---

## File Structure

**Create:** `app/agent/prompts/parent_lean.md` (the lean prompt); `docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md` (the CRITICAL-block → treatment map); `tests/test_prompt_hygiene_2026_07_21.py`.
**Modify:** `app/config.py` (`USE_LEAN_PROMPT`, `USE_LEAN_SANITIZER`); `tests/conftest.py` (pin both OFF); `app/agent/llm/parent_llm_engine.py` (`_use_lean_prompt()` + the `_build_system_prompt` prompt_name if/elif/else; the lean-flag branch in `_build_sales_context`; the `USE_LEAN_SANITIZER` partition + branch in `sanitise_response_wording`).

---

## Task 1: Two flags (default OFF) + conftest pin

**Files:** Modify `app/config.py`, `tests/conftest.py`; Test `tests/test_prompt_hygiene_2026_07_21.py`.

**Interfaces:** Produces `settings.USE_LEAN_PROMPT: bool` and `settings.USE_LEAN_SANITIZER: bool` (both default False), consumed by Tasks 3 and 4.

- [ ] **Step 1: Failing tests** — `Settings().USE_LEAN_PROMPT is False`, `Settings().USE_LEAN_SANITIZER is False`; `Settings.from_env` parses both via `_parse_bool_optional`.
- [ ] **Step 2: Run → fail.** `.venv/Scripts/python.exe -m pytest tests/test_prompt_hygiene_2026_07_21.py -q`
- [ ] **Step 3: Add flags** — `app/config.py` near `USE_SLIM_PROMPTS` (~L349): `USE_LEAN_PROMPT: bool = False`, `USE_LEAN_SANITIZER: bool = False`; + both in `from_env` (~L564) via `_parse_bool_optional("USE_LEAN_PROMPT", False)` / `_parse_bool_optional("USE_LEAN_SANITIZER", False)`. Pin BOTH OFF in `tests/conftest.py`'s autouse `dataclasses.replace(config_module.settings, ...)` (it already patches `parent_llm_engine.settings`).
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** — `feat(config): USE_LEAN_PROMPT + USE_LEAN_SANITIZER flags (default off) + conftest pin`

---

## Task 2: Guardrail-coverage MAP (executor-verified) — the input to the lean prompt

> **C1 + C2: this precedes the lean prompt.** The lean prompt (Task 3) is written FROM this map. No verbatim rule is dropped until this map proves — by reading `parent_tool_executor.py` — that a backend `reason` code enforces the same guarantee.

**Files:** Create `docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md`. Read-only against `app/agent/prompts/system_parent_v2.md` + `app/agent/tools/parent_tool_executor.py` + `app/agent/llm/parent_llm_engine.py::_build_sales_context`.

**Interfaces:** Produces the table Task 3 consumes: each CRITICAL block → `{treatment: backend-enforced | prompt-only-behavioral | prompt-only-verbatim, backend_reason: <exact reason code + tool + executor line>, lean_text: <the short rule or the kept verbatim sentence>}`.

- [ ] **Step 1: Enumerate the guardrail blocks.** List every dated "CRITICAL" / "წესი" block in `system_parent_v2.md` (~30). For each, state the guarantee it enforces and the live bug it fixed (from CLAUDE.md's RESOLVED log).
- [ ] **Step 2: Verify backend enforcement in the executor (C2 — the load-bearing step).** For each block, open `parent_tool_executor.py` and find whether a `reason`/return contract ACTUALLY enforces it. Confirmed backend-enforced (verbatim droppable → behavioral): booking success requires `success=true` + non-empty `event_id` (`_book_consultation`); `slot_mismatch`; `verification_requested`; `calendar_booking_failed`; `event_past`; `half_hour_not_supported`; reschedule safe-ordering reasons; age eligibility in `_book_consultation` / `switch_to_adult_flow`. **Confirmed PROMPT-ONLY (NO backend signal — MUST stay verbatim/explicit in the lean prompt):** anti-fabrication of menu/rooms/staff/exact-schedule; overpromise/pain-mechanism ("screen-time"/"განკურნავს" framing); price-digit-always-stated; sibling-discount trigger list; political / off-topic redirect; PII / phone-mask wording; decline-close. If a block's status is uncertain, classify it PROMPT-ONLY (conservative).
- [ ] **Step 3: Write `docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md`** with the full table + a summary count (N backend-enforced, N behavioral, N verbatim-kept). Any block that is neither backend-enforced nor given lean text is a BLOCKER — it must get explicit lean text.
- [ ] **Step 4: Dispatch a reviewer** (sonnet or opus, NOT haiku) to audit the map against the real `parent_tool_executor.py`: does every "backend-enforced" row cite a real `reason` code at a real line? Any mis-classified row (claimed backend-enforced but actually prompt-only) is a re-introduced-bug risk — fix before Task 3.
- [ ] **Step 5: Commit** — `docs(phase4): executor-verified guardrail-coverage map (CRITICAL blocks → lean treatment)`

---

## Task 3: `parent_lean.md` — planner-independent lean prompt (written FROM the Task 2 map)

**Files:** Create `app/agent/prompts/parent_lean.md`; Modify `app/agent/llm/parent_llm_engine.py` (`_use_lean_prompt`, `_build_system_prompt` if/elif/else, `_build_sales_context` lean branch); Test.

**Interfaces:** Consumes Task 2's map. `_use_lean_prompt() -> bool` (mirrors `_use_slim_prompts`). In `_build_system_prompt` (~L2556):
```python
if _use_slim_prompts():
    prompt_name = "parent_core"
elif _use_lean_prompt():
    prompt_name = "parent_lean"
else:
    prompt_name = "system_parent_v2"
```
`parent_lean.md` uses the SAME `.format(company_name, age_min, age_max)` placeholders (double-escape any literal `{}`), paired with the EXISTING planner-independent `_build_context_message` + `_build_sales_context`. The three suffixes (dynamic-programs/approved-answer/skills) append automatically.

- [ ] **Step 1: Write `parent_lean.md`** — target ~120-160 lines (vs 467), each guardrail rendered EXACTLY as Task 2's map prescribes (behavioral where backend-enforced, verbatim/explicit where prompt-only):
  - **Role/tone/facts-via-tools** (keep near-verbatim from `system_parent_v2.md:1-20, 242-256, 307-320`): consultant-not-FAQ, Georgian-only, no emoji, never re-ask known facts, never hardcode price/dates — always call `get_camp_info`.
  - **Backend-enforced guardrails → SHORT behavioral rules**, e.g. booking: "only confirm a booking the tool returned `success=true` for (real `event_id` + matching datetime); on any failure `reason`, tell the user honestly + offer the manager — never claim a booking, never treat 'double-check' as confirmation." (replaces the `:178-223` verbatim reason-code→phrasing tables)
  - **Prompt-only guardrails → KEEP explicit** (anti-fabrication, overpromise/pain-mechanism, price-digit, sibling-discount trigger list, political off-topic, PII wording, decline-close) — verbatim where Task 2 says the guarantee depends on the exact wording.
  - Price objection: behavioral rule ("empathize → connect price to value/what's-included → mention the 6-month TBC/BoG split → one light CTA; never invent a discount"), NOT the verbatim 4-step script — this is the block most likely to lift naturalness (OB1 is the 0/4 case).
- [ ] **Step 2 (M2): neutralise `_build_sales_context` embedded script under the lean flag.** Read `_build_sales_context` (~L2859-2990). Where it injects hardcoded verbatim script (thanks/booking/discovery sentences) EVERY turn, gate that portion behind `_use_lean_prompt()` so the lean config doesn't fight the lean prompt with a second script. Flag-off path unchanged (byte-identical). If it injects only structured facts (no verbatim script), document that and skip — no change needed.
- [ ] **Step 3: Failing tests** — `_use_lean_prompt()` True iff `USE_LEAN_PROMPT` on; `_build_system_prompt()` (flag off) still `== load_prompt("system_parent_v2").format(...)` (byte-identity); `_build_sales_context(...)` (flag off) byte-identical to today; with `USE_LEAN_PROMPT` on, `_build_system_prompt` contains a distinctive `parent_lean` marker AND `len(lean) < 0.5*len(giant)`; the three suffixes still append (skills marker present when `USE_SKILLS` on). Frozen-settings swap on `parent_llm_engine.settings`.
- [ ] **Step 4: Run → fail → Step 5: Implement** `_use_lean_prompt` + if/elif/else + `_build_sales_context` lean branch + `parent_lean.md`.
- [ ] **Step 6: Byte-identity gate** — `.venv/Scripts/python.exe -m pytest tests/test_camp_age_bounds_migration_5a2_2026_06_22.py tests/test_prompt_hygiene_2026_07_21.py -q` → green. → **Step 7: Run → pass.**
- [ ] **Step 8: Commit** — `feat(prompt): parent_lean.md + USE_LEAN_PROMPT (planner-independent, guardrails per executor-verified map)`

---

## Task 4: `USE_LEAN_SANITIZER` — thin the convergence engine (keep the safety net, conservatively)

**Files:** Modify `app/agent/llm/parent_llm_engine.py`; Test.

**Interfaces:** In `sanitise_response_wording` (~L1900), when `getattr(settings,"USE_LEAN_SANITIZER",False)`, apply the structural passes + ONLY the SAFETY subset of the table; SKIP the wording→wording mandates. Partition `FORBIDDEN_PHRASE_REPLACEMENTS` (L843-1716) into `_SANITIZER_SAFETY_ENTRIES` (references the same tuples — do NOT retype Georgian) and the implicit remainder; flag-off uses the FULL table (byte-identical), flag-on uses only the safety subset. Delete nothing.

- [ ] **Step 1: Partition the table (conservative — H1).** Classify each of the 183 entries: SAFETY (right-hand side `""` = a strip; OR a pure spelling/grammar fix; OR AMBIGUOUS grammar-vs-mandate) vs WORDING-MANDATE (a phrase→different-approved-phrase rewrite whose only purpose is convergence). **When unsure, put it in SAFETY.** Build `_SANITIZER_SAFETY_ENTRIES` as the SAFETY subset. Record the split count (expect materially fewer than 147 dropped after the conservative rule) in the report.
- [ ] **Step 2: Failing tests** — flag OFF: a known wording-mandate STILL rewrites (full table). flag ON: that same wording-mandate passes through (not rewritten) BUT a known SAFETY strip (emoji, a fake-booking phrase, a mid-conversation greeting) IS still stripped, AND an ambiguous grammar entry is still applied. So: convergence relaxed, safety + grammar kept. Swap via `dataclasses.replace` + `monkeypatch.setattr(parent_llm_engine, "settings", ...)`.
- [ ] **Step 3: Run → fail → Step 4: Implement** the partition + flag-gated branch (flag-off = full table unchanged). → **Step 5: Run → pass.**
- [ ] **Step 6: Commit** — `feat(sanitizer): USE_LEAN_SANITIZER — keep safety+grammar strips, drop wording mandates (flag-gated, conservative)`

---

## Task 5: INCREMENTAL measurement — naturalness is the binding gate (works NOW)

**Files:** none new (verification + a measurement note appended to `docs/MEASURE_OBJECTION_PILOT.md` or a new `docs/MEASURE_PHASE4.md`).

- [ ] **Step 1: Both-flags-OFF full suite.** `.venv/Scripts/python.exe -m pytest -q` → only the pre-existing `fast_track` failure. Record.
- [ ] **Step 2: Flag-ON focused + byte-identity.** `.venv/Scripts/python.exe -m pytest tests/test_prompt_hygiene_2026_07_21.py tests/test_camp_age_bounds_migration_5a2_2026_06_22.py -q` → green.
- [ ] **Step 3: Eval READ-ONLY offline.** `.venv/Scripts/python.exe -m evals.run_evals` → READ-ONLY-clean, `evals/baseline.json` byte-identical.
- [ ] **Step 4: Incremental A/B measurement (naturalness = binding gate; OpenAI judge, works now).** Snapshot `evals/baseline.json` first. For each config — baseline (both off) → +lean-prompt → +lean-prompt+lean-sanitizer — run the advisory/objection full-turn cases via `USE_PARENT_LLM_ENGINE=true PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m evals.run_evals --llm --judge --case <id>` (OB1/OB2/OB3/Q2/Q8 + the U-set). Record per config: **naturalness mean (the binding metric — OB1 baseline is 0/4; expect UP under lean)**, correctness `require_any`/`forbid_any` (expect HELD), footprint (diagnostic only). Restore `evals/baseline.json` after (byte-identical; md5 `93973fcd...`).
  - **C3 note:** for the +lean-SANITIZER step, read naturalness + correctness ONLY. Footprint DOWN there is tautological and MUST NOT be reported as evidence.
- [ ] **Step 5: CRITICAL + guardrail-domain hold.** `.venv/Scripts/python.exe tools/scenario_runner_full.py --priority CRITICAL` → 22/22. Confirm `booking_reliability` + `contact_capture` reliability not dropped.
- [ ] **Step 6: Write the measurement note** — the per-config table + the binding-gate verdict per flag. State plainly whether naturalness rose from the 0/4 baseline and whether every guardrail held. **Enablement recommendation only if the full binding gate clears; flags stay OFF pending the operator's supervised staging smoke.**
- [ ] **Step 7: Commit** the measurement note.

---

## Phase 4 Definition of Done

With `USE_LEAN_PROMPT` + `USE_LEAN_SANITIZER` ON, the PARENT model answers from a ~130-line behavioral prompt (not a 467-line script), `_build_sales_context` no longer injects a competing verbatim script, and its output is NOT forced through the wording-mandate rewrites — so it can reason and vary — while EVERY one of the ~30 guardrails is preserved (behaviorally where an executor `reason` code enforces it, verbatim/explicit where it's prompt-only, all mapped + reviewer-verified in Task 2) and ALL safety strips + structural passes still run. With both flags OFF: byte-identical (giant prompt + full sanitizer + current `_build_sales_context`), full suite green. **Measured (now, via the OpenAI judge):** naturalness UP from the 0/4 baseline + correctness HELD + CRITICAL 22/22 + guardrail-domain reliability not dropped, across baseline→+prompt→+sanitizer, measuring the sanitizer by naturalness/correctness only. **Flags stay OFF — enablement is a separate operator step gated on the full binding gate + a supervised staging smoke.**

**Explicitly NOT in Phase 4:** no `_build_sales_context` full de-dup beyond neutralising the verbatim script under the lean flag; no slim/planner change; no agent-model change; no interceptor→tool (that's Phase 3-full / `camp_topic_facts`).

## Self-Review

**Spec coverage:** lean prompt → Task 3 (from Task 2's map); thin sanitizer → Task 4; guardrail preservation → Task 2 (moved up, executor-verified) + reviewer; measurement → Task 5 (naturalness binding, works now). ✅
**C1 (order):** guardrail map (Task 2) precedes the lean prompt (Task 3). ✅
**C2 (verify, don't assume):** Task 2 Step 2 reads `parent_tool_executor.py`; prompt-only guardrails (anti-fabrication, overpromise, price-digit, sibling, political, PII) stay verbatim/explicit. ✅
**C3 (footprint not the sanitizer gate):** binding gate is naturalness + correctness; footprint is diagnostic; the sanitizer step explicitly reads naturalness/correctness only. ✅
**H1 (conservative partition):** ambiguous sanitizer entries kept as safety. ✅
**H2/S1 (build-now / enable-after) + validation now works:** flags ship OFF; naturalness gate is measurable now (OpenAI judge), OB1 0/4 is the documented baseline; enablement is a separate operator step. ✅
**M2 (`_build_sales_context`):** neutralised under the lean flag so the measurement isn't confounded (Task 3 Step 2). ✅
**Both-flags-off byte-identity:** if/elif/else (default `system_parent_v2`) + `_build_sales_context` flag-off unchanged + sanitizer partition (flag-off = full table); byte-exact tests run in Tasks 3 + 5. ✅
