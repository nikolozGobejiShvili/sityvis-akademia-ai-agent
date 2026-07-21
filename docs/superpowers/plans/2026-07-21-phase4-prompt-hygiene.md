# Phase 4 — Prompt & Sanitizer Hygiene (let the model reason) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let the PARENT model actually reason and vary its wording, by thinning the two layers that force its output to a fixed script — the 122 KB scripted prompt AND (the real culprit) the 183-entry post-LLM sanitizer. The Phase-3 measurement + the Phase-4 grounding proved the "botlike" ceiling is SCRIPTING, and that the sanitizer is the primary convergence engine (the eval harness's own docs: *"the sanitizer rewrites raw LLM output so it converges on the approved phrasing every time"*). Both changes are flag-gated, default OFF, byte-identical off, and measured against the free `botlike_proxy` footprint + the correctness cases before any enablement.

**Architecture (grounding-informed):** Two independent, separately-measured flags. (1) `USE_LEAN_PROMPT` → a NEW planner-independent `parent_lean.md` that keeps brand/tone + facts-via-tools + the ~30 guardrails as BEHAVIORAL constraints (react to backend `reason` codes) instead of mandated verbatim sentences. (2) `USE_LEAN_SANITIZER` → a thinned `sanitise_response_wording` path that keeps the ~36 strip-only safety entries + grammar fixes and drops the ~147 wording-mandate rewrites (the convergence engine). Neither touches the dormant slim/planner path. Every guardrail that a backend tool `reason` already enforces stays enforced; only the redundant verbatim SCRIPT is removed.

**Tech Stack:** Python 3.10, OpenAI gpt-4.1-mini (unchanged), the Phase-1 eval (`evals/` — `botlike_proxy` footprint is FREE + deterministic + usable now), pytest. No new dependency, no model change.

## Global Constraints

- **Both flags OFF ⇒ byte-identical.** `USE_LEAN_PROMPT=False` ⇒ `_build_system_prompt` loads `system_parent_v2` exactly as today; `USE_LEAN_SANITIZER=False` ⇒ the full 183-entry table runs exactly as today. The byte-exact tests (`tests/test_camp_age_bounds_migration_5a2_2026_06_22.py` assert `_build_system_prompt() == load_prompt("system_parent_v2").format(...)`) MUST stay green — so the flag check comes AFTER `_use_slim_prompts()` in an if/elif/else, default off. Full suite (~5071) green.
- **NO guardrail regresses (load-bearing, HIGHEST RISK IN THE PROJECT).** Every one of the ~30 CRITICAL blocks fixed a live bug. The lean prompt must PRESERVE each guarantee. The safe transform: where a backend tool `reason` code already enforces the guarantee (booking-success requires `success=true`+`event_id`; slot-mismatch/verification/reschedule/reason-code-table are all executor-enforced), the lean prompt keeps a SHORT behavioral instruction ("if the tool returns success=false, tell the user honestly + offer the manager; never claim a booking the tool didn't confirm") and drops the mandated exact sentence. Where NO backend signal exists (political off-topic phrase, sibling-discount trigger list, anti-fabrication redirect, PII-mask), the lean prompt KEEPS the constraint explicitly. A task reviewer maps each of the ~30 blocks → kept-behaviorally / kept-verbatim / dropped-as-backend-enforced.
- **Sanitizer thinning keeps the SAFETY net.** `USE_LEAN_SANITIZER` on ⇒ keep ALL ~36 strip-only entries (emoji, unfulfillable-promise strips, fake-booking-phrase strips, PII) + the structural passes (`_collapse_duplicated_tu`, `_strip_concern_wording`, fact-normalisation) + genuine grammar fixes; drop ONLY the ~147 two-sided wording→wording mandates. The strips are safety; the mandates are the convergence engine.
- **Measurement gate is footprint-first (works NOW, judge deferred).** The FREE, deterministic `evals.botlike_proxy` footprint + the correctness `require_any`/`forbid_any` cases (OpenAI-only) are the primary gate and run now. The Anthropic naturalness judge is DOWN (invalid key) — its half is deferred until the operator fixes the key + seeds an active offering. A flag ships only if: footprint DOWN + correctness HELD (100% on the guardrail-sensitive cases) + CRITICAL 22/22 held. Naturalness-up is confirmed later.
- **Measure each flag independently (Phase-3 lesson).** baseline → +lean-prompt → +lean-sanitizer, one flag per step, footprint + correctness at each — so a gain/regression is attributable.
- **No forbidden changes.** Do NOT edit the dormant slim/planner path, `OPENAI_MODEL`, `.env`, Calendar/Sheets/booking logic. New artifacts: `parent_lean.md` + two flags. `_build_sales_context` de-dup is explicitly DEFERRED (grounding rec (B) — lower priority, do after (1)+(2) show gain).
- **Interpreter:** `.venv/Scripts/python.exe`. **LOCAL-only** branch `feat/dynamic-programs`; push only with explicit consent. **No haiku.**
- **Expected pre-existing failure:** `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`. Any OTHER failure is in scope.

---

## File Structure

**Create:** `app/agent/prompts/parent_lean.md` (the lean prompt); `tests/test_prompt_hygiene_2026_07_21.py`.
**Modify:** `app/config.py` (`USE_LEAN_PROMPT`, `USE_LEAN_SANITIZER`); `tests/conftest.py` (pin both OFF); `app/agent/llm/parent_llm_engine.py` (`_use_lean_prompt()` + the `_build_system_prompt` prompt_name if/elif/else; the `USE_LEAN_SANITIZER` branch in `sanitise_response_wording`).

---

## Task 1: Two flags (default OFF) + conftest pin

**Files:** Modify `app/config.py`, `tests/conftest.py`; Test `tests/test_prompt_hygiene_2026_07_21.py`.

- [ ] **Step 1: Failing tests** — `Settings().USE_LEAN_PROMPT is False`, `USE_LEAN_SANITIZER is False`; `from_env` parses both.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Add flags** (`app/config.py` near `USE_SLIM_PROMPTS` ~L349): `USE_LEAN_PROMPT: bool = False`, `USE_LEAN_SANITIZER: bool = False`; + both in `from_env` (~L564). Pin both OFF in `tests/conftest.py`'s `dataclasses.replace(...)` (reaches `parent_llm_engine.settings`, already patched).
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** — `feat(config): USE_LEAN_PROMPT + USE_LEAN_SANITIZER flags (default off) + conftest pin`

---

## Task 2: `parent_lean.md` — planner-independent lean prompt (guardrails preserved behaviorally)

**Files:** Create `app/agent/prompts/parent_lean.md`; Modify `app/agent/llm/parent_llm_engine.py`; Test.

**Interfaces:** `_use_lean_prompt() -> bool` (mirrors `_use_slim_prompts`). In `_build_system_prompt` (parent_llm_engine.py ~L2556), change `prompt_name = "parent_core" if _use_slim_prompts() else "system_parent_v2"` to:
```python
if _use_slim_prompts():
    prompt_name = "parent_core"
elif _use_lean_prompt():
    prompt_name = "parent_lean"
else:
    prompt_name = "system_parent_v2"
```
`parent_lean.md` uses the SAME `.format(company_name, age_min, age_max)` placeholders (double-escape any literal `{}`), and is paired with the EXISTING planner-independent `_build_context_message` + `_build_sales_context` (NOT the planner blocks). The three suffixes (dynamic-programs/approved-answer/skills) append automatically — no extra wiring.

- [ ] **Step 1: Write `parent_lean.md`** — target ~120-160 lines (vs 467). Structure:
  - **Role/tone/facts-via-tools** (grounding §1 buckets a+b) — keep near-verbatim (`system_parent_v2.md:1-20`, `:242-256`, `:307-320`): consultant-not-FAQ persona, Georgian-only, no emoji, never re-ask known facts, never hardcode price/dates — always call `get_camp_info`.
  - **Guardrails as BEHAVIORAL constraints (grounding §1 bucket c), the risky part** — for EACH of the ~30 CRITICAL blocks, write a SHORT behavioral rule, dropping the mandated exact sentence where a backend `reason` enforces it:
    - Booking: "only confirm a booking the tool returned `success=true` for (with a real event_id + matching datetime); on `success=false`/any failure `reason`, tell the user honestly and offer the manager — never claim a booking, never treat 'double-check' as confirmation." (replaces `:178-223` verbatim tables)
    - Age: "camp is {age_min}-{age_max}; a child outside that range → say so kindly + offer the manager; never invent eligibility." (replaces `:108-120`)
    - Anti-fabrication: "never invent operational details (menu, rooms, staff, exact schedule) — defer to the manager." (`:125-131`)
    - Decline: "on an explicit refusal, close warmly and stop selling." (`:231-232`)
    - Price objection: "on a price objection, empathize → connect price to value/what's-included → mention the 6-month TBC/Bank-of-Georgia split → one light CTA; never invent a discount." (behavioral, NOT the verbatim 4-step script at `:139-165,387`)
    - PII/privacy, sibling-discount trigger, political off-topic — KEEP explicit (no backend signal).
    - (The reviewer will verify all ~30 are covered — see Task 5.)
  - Do NOT include the reason-code → exact-phrasing tables (`:195-223`) — replace with "react honestly to the tool's `reason`".
- [ ] **Step 2: Failing tests** — `_use_lean_prompt()` True when `USE_LEAN_PROMPT` on; `_build_system_prompt()` (flag off) still `== load_prompt("system_parent_v2").format(...)` (byte-identity); with `USE_LEAN_PROMPT` on, `_build_system_prompt(...)` contains a distinctive `parent_lean.md` marker AND is materially shorter than the giant (`len(lean) < 0.5 * len(giant)`); the three suffixes still append (skills marker present when `USE_SKILLS` on). Use the frozen-settings swap on `parent_llm_engine.settings`.
- [ ] **Step 3: Run → fail → Step 4: Implement** `_use_lean_prompt` + the if/elif/else + `parent_lean.md`. → **Step 5: Byte-identity check** — `.venv/Scripts/python.exe -m pytest tests/test_camp_age_bounds_migration_5a2_2026_06_22.py tests/test_prompt_hygiene_2026_07_21.py -q` → green (flag off unchanged). → **Step 6: Run → pass.**
- [ ] **Step 7: Commit** — `feat(prompt): parent_lean.md + USE_LEAN_PROMPT (planner-independent, guardrails behavioral)`

---

## Task 3: `USE_LEAN_SANITIZER` — thin the convergence engine (keep the safety net)

**Files:** Modify `app/agent/llm/parent_llm_engine.py`; Test.

**Interfaces:** In `sanitise_response_wording` (parent_llm_engine.py ~L1900), when `getattr(settings,"USE_LEAN_SANITIZER",False)`, apply the structural passes (`_collapse_duplicated_tu`, `_strip_concern_wording`, `_apply_dynamic_fact_normalisations`) + ONLY the strip-only/grammar subset of the table; SKIP the ~147 two-sided wording→wording mandates. Implement by partitioning `FORBIDDEN_PHRASE_REPLACEMENTS` into `_SANITIZER_SAFETY_ENTRIES` (empty-replacement strips + genuine grammar fixes, ~36-50) and `_SANITIZER_WORDING_MANDATES` (the rest); flag-off uses the full table (byte-identical), flag-on uses only the safety subset. Do NOT delete any entry — partition, so flag-off is provably the original table.

- [ ] **Step 1: Partition the table** — read `FORBIDDEN_PHRASE_REPLACEMENTS` (parent_llm_engine.py:843-1716). Classify each entry: SAFETY (right-hand side is `""` — a strip; OR a pure typo/grammar fix that changes only spelling/case) vs WORDING-MANDATE (a phrase→different-phrase rewrite forcing approved wording). Build `_SANITIZER_SAFETY_ENTRIES` as the SAFETY subset (reference the same tuples — do NOT retype the Georgian). Document the split count in the report.
- [ ] **Step 2: Failing tests** — flag OFF: `sanitise_response_wording(x)` uses the FULL table (assert a known wording-mandate still rewrites, e.g. a banned phrase → approved); flag ON: the same wording-mandate does NOT rewrite (passes through) BUT a known SAFETY strip (an emoji, a fake-booking phrase) IS still stripped. So: convergence relaxed, safety kept. Swap the flag via `dataclasses.replace` + `monkeypatch.setattr(parent_llm_engine, "settings", ...)`.
- [ ] **Step 3: Run → fail → Step 4: Implement** the partition + the flag-gated branch (flag-off = full table unchanged). → **Step 5: Run → pass.**
- [ ] **Step 6: Commit** — `feat(sanitizer): USE_LEAN_SANITIZER — keep safety strips, drop wording mandates (flag-gated)`

---

## Task 4: Full-suite gate + INCREMENTAL footprint measurement (judge deferred)

**Files:** none new (verification + docs).

- [ ] **Step 1: Both-flags-OFF full suite.** `.venv/Scripts/python.exe -m pytest -q` → only the pre-existing `fast_track`. Record. (Confirms both flags off = inert.)
- [ ] **Step 2: Flag-ON focused.** `.venv/Scripts/python.exe -m pytest tests/test_prompt_hygiene_2026_07_21.py -q` → green.
- [ ] **Step 3: Eval gate — READ-ONLY offline.** `.venv/Scripts/python.exe -m evals.run_evals` → READ-ONLY-clean, `evals/baseline.json` byte-identical.
- [ ] **Step 4: FREE incremental footprint + correctness measurement (works NOW — OpenAI only, no Anthropic).** For each config — baseline (both off) → +lean-prompt → +lean-prompt+lean-sanitizer — run the objection/quality full-turn cases (OB1-3, Q1-10, U-set) capturing the REPLY, and compute `evals.botlike_proxy.canned_footprint(reply)` per reply (FREE, deterministic) + the `require_any`/`forbid_any` correctness. Use a small harness-direct script (like the Phase-3 measurement) so `baseline.json` is never written. Report: avg footprint per config (expect DOWN as flags turn on), correctness pass-rate (expect HELD), and `python tools/scenario_runner_full.py --priority CRITICAL` (must stay 22/22). Protect `baseline.json` (snapshot/restore) if any `--llm` run_evals path is used.
- [ ] **Step 5: DEFERRED naturalness gate (PERMISSIONED — needs the operator's fixed Anthropic key + an active offering).** Once the key works + a future camp / active dynamic program is seeded: run `evals.run_evals --llm --judge` on the OB/Q/U cases A/B (flags off vs on), N=3 median. The binding enablement gate = footprint DOWN + correctness HELD + CRITICAL 22/22 + naturalness UP. Document the exact commands (reuse `docs/MEASURE_OBJECTION_PILOT.md`'s incremental shape).
- [ ] **Step 6: Commit** the measurement note.

---

## Task 5: Guardrail-coverage review (the ~30 CRITICAL blocks)

**Files:** none (a documented mapping + a reviewer gate).

- [ ] **Step 1: Map every CRITICAL block → its lean treatment.** Produce a table: each of the ~30 `system_parent_v2.md` guardrail blocks (grounding §1 list) → in `parent_lean.md` it is [kept-behaviorally / kept-verbatim / dropped-because-backend-enforced], with the backend `reason`/tool that enforces it when dropped. Any block with NO lean coverage AND NO backend enforcement is a BLOCKER — add it to `parent_lean.md`.
- [ ] **Step 2: Dispatch a reviewer** specifically to audit this mapping against the real `parent_lean.md` + the executor's `reason` codes (`parent_tool_executor.py`) — does every dropped verbatim guardrail have a genuine backend enforcement? Any gap = a re-introduced live bug.
- [ ] **Step 3: Commit** the mapping doc.

---

## Phase 4 Definition of Done

With `USE_LEAN_PROMPT` + `USE_LEAN_SANITIZER` ON, the PARENT model answers from a ~130-line behavioral prompt (not a 467-line script) and its output is NOT forced through the 147 wording-mandate rewrites — so it can reason and vary — while EVERY one of the ~30 guardrails is preserved (behaviorally in the prompt or via a backend `reason` code, mapped + reviewed in Task 5) and ALL ~36 safety strips + structural passes still run. With both flags OFF: byte-identical (the giant prompt + full sanitizer), full suite green. Measured (FREE, now): footprint DOWN + correctness HELD + CRITICAL 22/22 across baseline→+prompt→+sanitizer. The naturalness-UP half is DEFERRED to the operator's permissioned `--llm --judge` run once the Anthropic key is fixed + an active offering is seeded. **Flags stay OFF — enablement is a separate operator step gated on the full measurement.**

**Explicitly NOT in Phase 4:** no `_build_sales_context` de-dup (deferred rec (B)); no slim/planner change; no model change; no interceptor→tool (that's Phase 3-full / camp_topic_facts).

## Self-Review

**Spec coverage:** grounding rec (A) lean prompt → Task 2; rec (C) thin sanitizer → Task 3; the guardrail-preservation risk → Task 5; measurement → Task 4. ✅
**Both-flags-off byte-identity:** lean prompt behind an if/elif/else (default `system_parent_v2`); lean sanitizer partitions (flag-off = full table); byte-exact tests run in Task 2 Step 5. ✅
**Guardrail preservation (highest risk):** Task 5 maps + reviews every CRITICAL block; a dropped verbatim rule requires a proven backend `reason` enforcement, else it's kept. ✅
**Measurement honesty:** the free footprint + correctness gate works NOW; the naturalness half is explicitly deferred to the operator's key+offering fix, not claimed. ✅
**The real lever named:** the sanitizer (not just the prompt) is the convergence engine (grounding §4 + the harness's own docs) — Task 3 addresses it as a SEPARATE gated flag, so its risk + effect are isolated. ✅
