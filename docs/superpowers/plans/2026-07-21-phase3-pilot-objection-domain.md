# Phase 3 Pilot — Objection Domain (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Validate the BUILT reasoning/skills machinery on ONE real conversational domain — objections — before scaling. **The grounding reframed this pilot:** objection turns ALREADY reach the LLM engine today (no blocking interceptor to convert — bare "ძვირია" defers at `parent_flow.py:8335`; decline+objection defers at `:8363` by design). So this is **not** an interceptor→tool build. It is: (1) close the ONE narrow routing gap (hesitation+objection turns are still canned), flag-gated; (2) enable the already-built machinery on objections — `USE_SKILLS` (the `objection-handling.md` skill already triggers on "ძვირ") + `USE_REASONING_PASS` (the Phase-2 loop); (3) MEASURE it **incrementally** (one flag at a time) so we learn what actually helps, with reliability held. Model stays gpt-4.1-mini.

**⚠️ Scope honesty (critique S1):** this pilot validates the **machinery** (reasoning + skills) on objections; it does **NOT** prove the **interceptor→tool conversion pattern**, because objections have no real blocking interceptor. The pattern is proven later on a domain that DOES short-circuit the engine (e.g. `camp_topic_facts` — a deterministic YAML answer that bypasses the LLM entirely; that is the real interceptor→tool pilot, deferred). Naming this honestly prevents over-reading a good objection result as "the whole Phase-3 approach is validated."

## Global Constraints

- **Flag OFF ⇒ byte-identical.** The new flag `USE_OBJECTION_ENGINE_ROUTING` (default OFF) gates ONLY the hesitation-gate widening. Off ⇒ `_maybe_handle_decline_engine` behaves exactly as today. Pin OFF in `tests/conftest.py`. The full suite (~5061) stays green.
- **Every existing decline/objection guardrail is preserved (load-bearing).** The widening extends the `_DECLINE_OVERRIDE_INTEREST` deferral to the `is_will_think` branch ONLY, and ONLY when the flag is on. It must NOT change: (1) plain decline still declines (canned close); (2) decline + `მაგრამ/თუმცა/მაინც/ძვირ/მიჭირს` still defers; (3) explicit manager-contact inside a decline still routes to `_maybe_handle_explicit_manager_request`; (4) decline + `"?"` never cold-closed; (5) a hard decline still clears `pending_booking`/`book_consultation_success_for_conversation`. Task-1 tests assert all 5 survive.
- **Routing is only valuable WITH the machinery (critique C2).** Sending a hesitation+objection turn to the PLAIN engine (skills/reasoning off) may be no better — or worse — than the canned reply. So `USE_OBJECTION_ENGINE_ROUTING` is **never recommended for enablement alone**; it is measured and enabled only ON TOP OF `USE_SKILLS` + `USE_REASONING_PASS`. The measurement (Task 3) enforces this ordering.
- **Reliability is the HARD constraint; objection answers must still SELL (critique M1).** A "more natural" objection reply that drops the value→payment→CTA structure is a FAILURE, not a win — the giant prompt's 4-step objection script (`system_parent_v2.md:387`) exists because it converts. Objection measurement scores BOTH naturalness AND a conversion-proxy (the reply still contains value/what's-included + payment-split + a CTA, and never invents a discount). CRITICAL 22/22 + the Phase-1 guardrail domains (booking_reliability/contact_capture) reliability must not drop.
- **REFLECT payment-math watch (critique H2).** An objection reply often states the full price (2150) AND a derived monthly figure (e.g. 2150/6). REFLECT's "correct-value-absent" rule does NOT flag when 2150 is present alongside 360 (2150 ∈ tokens). The residual risk is a reply that gives ONLY the monthly figure without restating 2150 → REFLECT would flag it. The measurement MUST record REFLECT's replace-rate on the objection cases; if it replaces good payment-framed answers, that is a signal to tighten the price-class rule before enablement.
- **No forbidden changes.** Do NOT edit `system_parent_v2.md` or any `*.md` prompt, knowledge/admin YAML, Calendar, Sheets, `OPENAI_MODEL`, `.env`. Only code change: the flag + the gated widening in `parent_flow.py`; only eval change: new/tagged cases.
- **Interpreter:** `.venv/Scripts/python.exe`. **LOCAL-only** branch `feat/dynamic-programs`; push only with explicit consent. **No haiku.**
- **Expected pre-existing failure:** `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`. Any OTHER failure is in scope.

---

## File Structure

**Modify:** `app/config.py` (flag), `tests/conftest.py` (pin), `app/flows/parent_flow.py` (gated widening in `_maybe_handle_decline_engine` ~L8363), `evals/cases.py` (objection cases + tags).
**Create:** `tests/test_objection_pilot_2026_07_21.py`.

---

## Task 1: `USE_OBJECTION_ENGINE_ROUTING` flag + hesitation-gate widening (guardrails preserved)

**Files:** Modify `app/config.py`, `tests/conftest.py`, `app/flows/parent_flow.py`; Test `tests/test_objection_pilot_2026_07_21.py`.

**Interfaces:** In `_maybe_handle_decline_engine` (`parent_flow.py:8363`), change the deferral guard from:
```python
if is_decline and any(m in text for m in _DECLINE_OVERRIDE_INTEREST):
    return None
```
to (flag-gated; OFF ⇒ byte-identical):
```python
_widen = getattr(settings, "USE_OBJECTION_ENGINE_ROUTING", False)
if (is_decline or (_widen and is_will_think)) and any(m in text for m in _DECLINE_OVERRIDE_INTEREST):
    return None
```
Flag ON ⇒ a hesitation phrase ("მოვიფიქრებ") co-occurring with an objection marker ("ძვირ"/"მიჭირს"/"მაგრამ"/…) defers to the engine like a decline+objection already does. Flag OFF ⇒ the `_widen and is_will_think` term is False ⇒ identical to today.

- [ ] **Step 1: Add the flag** — `app/config.py` near `USE_REASONING_PASS: bool = False`: `USE_OBJECTION_ENGINE_ROUTING: bool = False`; `from_env`: `USE_OBJECTION_ENGINE_ROUTING=_parse_bool_optional("USE_OBJECTION_ENGINE_ROUTING", False),`. Pin OFF in `tests/conftest.py`'s `dataclasses.replace(...)` (reaches `parent_flow.settings`, already patched at conftest.py:132).
- [ ] **Step 2: Failing tests** (`tests/test_objection_pilot_2026_07_21.py`). Study `tests/test_objection_and_corrections_2026_06_22.py` FIRST for the conversation-construction + assertion idiom. Call `parent_flow._maybe_handle_decline_engine(conversation, message)` directly. Swap the flag via `dataclasses.replace(config.settings, USE_OBJECTION_ENGINE_ROUTING=True)` + `monkeypatch.setattr(parent_flow, "settings", swapped)`:
  - flag ON: `"მოვიფიქრებ, ძვირია"` → `None` (defers);
  - flag OFF: same → a non-None canned will-think string (today);
  - **guardrails (flag ON, all must still hold):** `"არა მადლობა"` → canned decline (non-None); `"არ მინდა, მაგრამ ბავშვი მინდა"` → `None`; `"არ მინდა, მენეჯერის ნომერი მომწერეთ"` → does NOT return the will-think/decline canned text (manager path wins); `"არ მინდა?"` → `None`; a hard decline (`"არ მინდა"` on a conversation with `pending_booking` set) still clears `pending_booking`.
- [ ] **Step 3: Run → fail → Step 4: Implement** the one-line gated widening (touch ONLY that guard + a local flag read; no other branch of `_maybe_handle_decline_engine` changes). → **Step 5: Run → pass.**
- [ ] **Step 6: Byte-identity (flag OFF)** — `.venv/Scripts/python.exe -m pytest tests/test_objection_and_corrections_2026_06_22.py tests/test_objection_pilot_2026_07_21.py -q` → green (existing objection/decline tests unchanged, flag off).
- [ ] **Step 7: Commit** — `feat(objection): flag-gated hesitation+objection routing to the engine (USE_OBJECTION_ENGINE_ROUTING)`

> Note (critique H3): this task proves the turn now DEFERS; it does NOT prove the engine handles it better than the canned reply. That value is established only by the Task-3 measurement (with the machinery on). Do not claim improvement from Task 1 alone.

---

## Task 2: Objection eval coverage — enough cases + conversion-proxy checks

**Files:** Modify `evals/cases.py`; Test `tests/test_objection_pilot_2026_07_21.py`.

**Interfaces:** Grow the objection full-turn cases to **≥6** (critique H1: 3-4 stochastic cases can't show a domain-level shift) spanning: bare price objection, decline+objection, hesitation+objection (the gap case), "need to think with spouse", "budget exceeded / discount?", "why so expensive". EACH advisory objection case asserts a **conversion-proxy** via `require_any` (value/what's-included stems `შედის`/`ღირებულება` OR payment stems `განვადება`/`გადახდის`) AND `forbid_any` (pressure `დღესვე`/`ბოლო ადგილ`/`აუცილებლად ახლავე`, and invented discount `50%`/`100%`). Tag all `objection`.

- [ ] **Step 1: Study** OB1 (`cases.py:628-634`)/OB2 (`:637-643`)/Q8 (`:590-596`) + `_DOMAIN_TAGS`. Confirm whether Q8 is a true duplicate of OB1 (critique M2); if so, differentiate its message or drop it from the objection count. Mirror the `_run_full_turn` shape (`require_any`/`forbid_any`/`seed`/`stochastic=True`).
- [ ] **Step 2: Add cases** — new `OB3` (hesitation+objection `"მოვიფიქრებ, ცოტა ძვირია"`) + `OB4`/`OB5` (distinct objection phrasings) so ≥6 objection-tagged cases exist, each with the conversion-proxy `require_any`/`forbid_any`. `stochastic=True` (self-skip offline).
- [ ] **Step 3: Smoke test** (append to the pilot test file, deterministic/offline): assert ≥6 cases carry `domain == "objection"` and each objection case has non-empty `require_any` AND `forbid_any` (so the conversion-proxy is actually enforced, not just naturalness).
- [ ] **Step 4: Offline eval stays clean** — `.venv/Scripts/python.exe -m evals.run_evals` → READ-ONLY-clean, `evals/baseline.json` byte-identical (new stochastic cases self-skip offline).
- [ ] **Step 5: Commit** — `feat(evals): objection coverage (>=6 cases, conversion-proxy require/forbid) for the pilot`

---

## Task 3: Full-suite gate + INCREMENTAL pilot measurement (critique C1)

**Files:** none new (verification + docs).

- [ ] **Step 1: Flag-OFF full suite (byte-identity).** `.venv/Scripts/python.exe -m pytest -q` → no NEW failures beyond `fast_track`. Record.
- [ ] **Step 2: Flag-ON focused.** `.venv/Scripts/python.exe -m pytest tests/test_objection_pilot_2026_07_21.py -q` → green.
- [ ] **Step 3: Eval gate — READ-ONLY offline.** `.venv/Scripts/python.exe -m evals.run_evals` → clean, baseline byte-identical.
- [ ] **Step 4: INCREMENTAL PILOT MEASUREMENT (PERMISSIONED — operator step on STAGING, costs tokens; NOT run without explicit permission).** Measure ONE flag at a time so we learn WHAT helps (critique C1) — never all three at once as the primary read. On the ≥6 objection cases, N=3 each, median:
  1. **Baseline:** `USE_PARENT_LLM_ENGINE=true`, everything else off. Record correctness (conversion-proxy pass), naturalness, REFLECT-replace-rate (0 — reasoning off).
  2. **+ skills:** turn ON `USE_SKILLS` only. Record deltas (does the objection skill alone help?).
  3. **+ reasoning:** add `USE_REASONING_PASS`. Record deltas AND the **REFLECT-replace-rate on objection cases** (critique H2 — flag any payment-math false-positive: a good value/payment reply replaced by the canned fallback).
  4. **+ routing:** add `USE_OBJECTION_ENGINE_ROUTING`. Record the marginal effect on the hesitation cases (OB3) specifically (critique C2 — routing measured only on top of the machinery, never alone).
  - **Guardrails + CRITICAL (each step):** `python tools/scenario_runner_full.py --priority CRITICAL` → 22/22; Phase-1 guardrail domains reliability not dropped.
  - **Latency:** ANALYZE p95 (≤ ~1.5 s) at steps 3-4.
  - **Honesty (critique H1):** ≥6 stochastic cases × N=3 is a **pilot signal, not statistical proof** — state this in the write-up; real-traffic confirmation (Redis objection transcripts) is the follow-up before broad enablement.
  - **The binding gate:** a step is a WIN only if it raises naturalness AND holds the conversion-proxy (still sells) AND holds CRITICAL 22/22 + guardrail reliability AND stays within latency AND (for step 3-4) does not introduce REFLECT false-positives. Recommend enabling ONLY the flag(s) that individually clear the gate, as a trio on staging. If none clear it, STOP — report per-step numbers.
- [ ] **Step 5: Commit** the measurement-protocol note.

---

## Phase 3 Pilot — Definition of Done

The objection domain has: (1) a flag-gated routing widening so hesitation+objection turns reach the engine like price objections already do, EVERY decline guardrail preserved (5 assertions), flag-OFF byte-identical; (2) ≥6 objection eval cases with conversion-proxy require/forbid (so "natural" can't win by dropping the sell); (3) a documented, permissioned, INCREMENTAL measurement (baseline → +skills → +reasoning → +routing, one flag at a time, N=3 median) gated on reliability=100% (CRITICAL + guardrail domains) + conversion-proxy held + directional naturalness gain + latency budget + no REFLECT payment-math false-positives. No live behavior change until an operator enables flags after the measurement. Model stays gpt-4.1-mini.

**Honest boundaries:** (a) this validates the reasoning/skills MACHINERY on objections, NOT the interceptor→tool pattern (objections had no blocking interceptor — that pattern is proven later on `camp_topic_facts`, a real short-circuiting interceptor). (b) ≥6 stochastic cases are a pilot signal, not proof — real-traffic (Redis) confirmation precedes broad enablement. (c) routing is never enabled alone (only atop the machinery).

## Self-Review / Critique → Fix

| v1 finding | Sev | Resolution in v2 |
|---|---|---|
| **C1 — trio measured at once → can't isolate what helps** | 🔴 | Task 3 is INCREMENTAL: baseline → +skills → +reasoning → +routing, one flag at a time, per-step deltas. |
| **C2 — routing valuable only with the machinery; alone may be worse** | 🔴 | Global Constraint + measurement order: routing measured/enabled ONLY atop skills+reasoning, never alone. |
| **H1 — 3-4 stochastic cases can't show a domain shift** | 🟠 | ≥6 objection cases, N=3 median, and "pilot signal not proof" stated + real-traffic follow-up. |
| **H2 — REFLECT payment-math false-positive on objections** | 🟠 | Measurement records REFLECT-replace-rate on objection cases; a good payment reply being replaced is a stop-signal to tighten the price rule. |
| **H3 — Task 1 proves defer, not improvement** | 🟠 | Task-1 note: value established only by the Task-3 measurement, not the unit test. |
| **M1 — "natural" objection may sell worse** | 🟡 | Conversion-proxy (value/payment/CTA preserved, no invented discount) is a scored HARD requirement, not just naturalness. |
| **M2 — Q8 ≈ OB1 double-count** | 🟡 | Task 2 Step 1 checks Q8-vs-OB1 duplication; differentiate or exclude from the count. |
| **S1 — objection doesn't prove the interceptor→tool pattern** | ⚫ | Reframed throughout: this is MACHINERY validation; the pattern pilot is `camp_topic_facts`, deferred + named. |

**Flag-off byte-identity / guardrail preservation / spec coverage:** unchanged from v1's self-review (all ✅) — v2 tightens measurement rigor, conversion-proxy, and scope honesty without changing the one-line routing mechanism.
