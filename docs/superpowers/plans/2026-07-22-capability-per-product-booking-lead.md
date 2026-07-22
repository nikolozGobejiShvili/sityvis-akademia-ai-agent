# Capability #2 — Per-Product Consultation Booking + Lead Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Let a parent book a **consultation** (Google Calendar) for a NON-camp admin product (first: "Disneyland tour"), using THAT product's age band and registration status, with the lead **tagged to the product** — so a new admin product has the same booking+lead function as camp. Flag-gated (default OFF, byte-identical off), staging-verified.

**Architecture:** New flag `USE_PER_PRODUCT_BOOKING` (default OFF). When ON, `_book_consultation` resolves the product id for the turn (from `match_dynamic_program(self.user_message, ...)`), and swaps ONLY the *age-band source* and *registration source* to that product's section, and tags the lead with `program_id`; post-booking facts source from the product's section. Everything else — every validation gate, the Calendar/slot machinery, the success contract — is unchanged. When OFF, or when the resolved product is camp/none: **byte-identical to today.**

**Tech Stack:** Python 3.10, Google Calendar/Sheets (unchanged). No new dependency. No agent-model change.

## Global Constraints

- **THIS IS THE BOOKING GUARDRAIL ZONE (money/commitment) — the highest-risk area in the project.** The per-product change may ONLY: (1) swap the age-band source, (2) swap the registration source, (3) add a `program_id` tag, (4) source post-booking facts per-product. It MUST NOT weaken any validation gate. Preserve exactly, unchanged: the `user_confirmed_datetime` gate (`parent_tool_executor.py:~1096`), the verification-phrase guard (`~1113`), the slot-availability fail-CLOSED re-check (`_book_selected_slot` `parent_flow.py:~11055`), the empty-`event_id` silent-failure rollback (`~1385-1444`), the slot-mismatch rollback (`~1464-1507`), and the per-turn `book_consultation_success_for_conversation` flag. **No new success path. Never relax "no `event_id` ⇒ not booked".**
- **Flag OFF ⇒ BYTE-IDENTICAL.** `USE_PER_PRODUCT_BOOKING=False` ⇒ camp booking behaves exactly as today: camp age band, camp registration, 17-column lead row (NO Program column written), camp post-booking facts. The CRITICAL scenario suite (`tools/scenario_runner_full.py --priority CRITICAL` → 22/22) MUST still pass, and the full suite green.
- **Fail-CLOSED on missing product data.** If the resolved product's `age_min`/`age_max` is missing/blank, fall back to the camp band (or refuse) — NEVER silently disable the age check. If registration status is missing, treat as closed (safe).
- **The Sheets "Program" column is a real schema change** — it is written ONLY when the flag is ON (flag OFF = today's 17-col A–Q row, byte-identical). Enabling the flag adds the column (an operator-visible, forward-only change; document it). The append-range logic (`_append_lead_row_aligned`, `sheets_service.py:~164`) must stay length-correct for both widths.
- **Resolve the product id from the backend, not the LLM.** Use `match_dynamic_program(self.user_message, get_active_sections())` inside the executor — do NOT add an LLM tool argument the model could get wrong.
- **Reserved products (Sunday School) are OUT of scope here** — that needs `PROGRAM_REGISTRY` un-gating (`program_registry.py` hard-raises on non-3-ids), a separate capability. Disneyland is a non-reserved dynamic product and does NOT need it.
- Do NOT touch `OPENAI_MODEL`, `.env`, the dormant slim/planner path, `data/admin_config/sections.yaml`, `evals/baseline.json`, `CLAUDE.md`, `HANDOFF.md`. **LOCAL-only** branch `feat/dynamic-programs`; never push. Interpreter `.venv/Scripts/python.exe`. No haiku.
- **Expected pre-existing failure** (not in scope): `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`.

---

## File Structure

**Modify:** `app/config.py` (+flag) · `tests/conftest.py` (pin) · `app/models/lead.py` (+`program_id`) · `app/services/admin_config_service.py` (+`get_program_age_bounds`, +per-product registration accessor) · `app/agent/tools/parent_tool_executor.py` (`_book_consultation` eligibility+registration source, product resolve, lead tag) · `app/services/sheets_service.py` (flag-gated Program column) · `app/flows/parent_flow.py` (`_facts_for_post_booking` per-product branch).
**Create:** `tests/test_per_product_booking_2026_07_22.py`; `docs/ENABLEMENT_USE_PER_PRODUCT_BOOKING.md`.

---

## Task 1: Flag + `Lead.program_id` field (no behavior change)

**Files:** `app/config.py`, `tests/conftest.py`, `app/models/lead.py`; Test.

- [ ] **Step 1: Failing tests** — `Settings().USE_PER_PRODUCT_BOOKING is False`; `Lead(...).program_id == ""`; `Lead.from_dict({...}).program_id` round-trips; `to_dict()`/serialization includes it.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — `USE_PER_PRODUCT_BOOKING: bool = False` in `config.py` (near `USE_PROGRAM_TOPICS`) + `from_env` reader; pin OFF in `conftest.py`. Add `program_id: str = ""` to the `Lead` dataclass + its `from_dict`/`to_dict`/any serialization (default `""` ⇒ legacy/camp). **No other code reads it yet** ⇒ byte-identical.
- [ ] **Step 4: Run → pass.** Full suite unaffected (new field defaults empty, unread).
- [ ] **Step 5: Commit** — `feat(config): USE_PER_PRODUCT_BOOKING flag + Lead.program_id (default off/empty)`

---

## Task 2: `get_program_age_bounds(program_id)` accessor (fail-closed to camp)

**Files:** `app/services/admin_config_service.py`; Test.

**Interfaces:** Produces `admin_config_service.get_program_age_bounds(program_id: str) -> tuple[int, int]` — returns the section's `(age_min, age_max)` for a non-camp program; returns `get_camp_age_bounds()` for `summer_camp`, empty id, unknown id, OR a section with missing/blank/invalid bounds (**fail-closed to camp — never a disabled/no-op band**).

- [ ] **Step 1: Failing tests** — `get_program_age_bounds("summer_camp") == get_camp_age_bounds()`; a seeded `disneyland_tour` (age_min=7, age_max=16) → `(7,16)`; `""`/`"nope"`/a section with blank `age_min` → `get_camp_age_bounds()` (fail-closed). Seed via monkeypatching `get_section`/`get_active_sections`, not sections.yaml.
- [ ] **Step 2: Run → fail. Step 3: Implement** near `admin_config_service.py:836`: read `get_section(program_id)`; parse int `age_min`/`age_max`; on any miss/blank/non-int/`summer_camp`/empty → return `get_camp_age_bounds()`. Never raises.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(admin-config): get_program_age_bounds (per-product band, fail-closed to camp)`

Also add a per-product registration accessor `is_program_registration_open(program_id) -> bool` here (section `registration_status == "open"`; missing ⇒ False/closed; `summer_camp`/empty ⇒ `is_camp_registration_open()`), same fail-closed discipline. Test it in the same file.

---

## Task 3: Per-product eligibility + registration in `_book_consultation` (flag-gated; guardrail-preserving)

**Files:** `app/agent/tools/parent_tool_executor.py`; Test.

**Interfaces:** Consumes `settings.USE_PER_PRODUCT_BOOKING`, `get_program_age_bounds`, `is_program_registration_open`, `match_dynamic_program`, `self.user_message`.

- [ ] **Step 1: Read** `_book_consultation` (`:1008`) fully — the registration gate (`:1063`), the age-eligibility block (`:1126-1163`), and confirm the exact lines. **List every validation gate you must leave untouched** (see Global Constraints) in the test file's docstring.
- [ ] **Step 2: Failing tests** (all with the engine executor, seeded lead):
  - flag OFF: a Disneyland-context turn books using the CAMP band (today's behavior) — byte-identical. (prove the resolve/branch is inert off.)
  - flag ON + resolved `disneyland_tour` + child age 7: eligibility uses `(7,16)` ⇒ **eligible** (today it would be `age_not_eligible`). Registration uses Disneyland's status.
  - flag ON + resolved camp/none: uses camp band + camp registration (unchanged).
  - flag ON + Disneyland section missing `age_min`: **fail-closed to camp band** (7yo → not eligible), never a disabled check.
  - **Guardrail regression tests:** the `user_confirmed_datetime` gate, verification-phrase guard, and empty-`event_id` rollback still behave identically with the flag ON (copy the existing camp guardrail tests, run them with the flag ON, assert same outcomes).
- [ ] **Step 3: Run → fail. Step 4: Implement** — at the top of the eligibility section, resolve `program_id`:
  ```python
  program_id = ""
  if getattr(settings, "USE_PER_PRODUCT_BOOKING", False):
      try:
          m = match_dynamic_program(self.user_message or "", admin_config_service.get_active_sections())
          pid = (m or {}).get("program_id") or ""
          if pid and pid not in _HARDCODED_PROGRAM_IDS:
              program_id = pid
      except Exception:
          program_id = ""   # fail-safe → camp
  age_min, age_max = admin_config_service.get_program_age_bounds(program_id or "summer_camp")
  ```
  Replace the registration gate similarly (per-product when `program_id` non-empty, else camp). **Change NOTHING else in the flow** — same gates, same order, same rollbacks. Stash `program_id` on `self`/the lead for Task 4.
- [ ] **Step 5: Run → pass. Step 6:** `.venv/Scripts/python.exe -m pytest tests/test_parent_llm_engine.py -q` (booking guardrail tests live here) → green. **Step 7: Commit** — `feat(booking): per-product age band + registration in book_consultation (flag-gated, guardrails preserved)`

---

## Task 4: Tag the lead with the product + flag-gated Sheets Program column

**Files:** `app/agent/tools/parent_tool_executor.py` / `app/flows/parent_flow.py` (set `lead.program_id`), `app/services/sheets_service.py`; Test.

- [ ] **Step 1: Failing tests** — after a flag-ON Disneyland booking, `lead.program_id == "disneyland_tour"`; `_lead_to_row(lead)` flag OFF ⇒ **17 values** (byte-identical, no Program cell); flag ON ⇒ **18 values** with the program id last; `HEADERS` length + `_append_lead_row_aligned` range are consistent for both widths.
- [ ] **Step 2: Run → fail. Step 3: Implement** — set `lead.program_id = program_id` where the booking commits (before `create_lead`). In `sheets_service`: add a flag-gated trailing "Program" column — flag OFF path writes the current 17-col A–Q row unchanged; flag ON path writes 18 cols (A–R) with `lead.program_id` last. The append-range/resize must match the width actually written. **Delete/alter nothing in the existing 17 columns.**
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(lead): tag booking lead with program_id + flag-gated Sheets Program column`

---

## Task 5: Per-product post-booking facts + confirmation wording (flag-gated)

**Files:** `app/flows/parent_flow.py` (`_facts_for_post_booking` `:~11247`); Test.

- [ ] **Step 1: Failing tests** — flag OFF ⇒ `_facts_for_post_booking` returns camp facts (byte-identical). flag ON + `lead.program_id == "disneyland_tour"` ⇒ facts sourced from `get_section("disneyland_tour")` (price/location/age from Disneyland, NOT camp). flag ON + empty program_id ⇒ camp facts.
- [ ] **Step 2: Run → fail. Step 3: Implement** — branch `_facts_for_post_booking` on `getattr(lead, "program_id", "")` under the flag: non-empty non-camp ⇒ source from the section; else camp (today). Optional: `calendar_service._build_event_title/description` drop the child label for a non-child product — only if trivial and flag-gated; otherwise leave (no "camp" literal exists there anyway).
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(booking): per-product post-booking facts (flag-gated)`

---

## Task 6: Whole-suite verification + guardrail gate + staging runbook

- [ ] **Step 1: Full suite, flag OFF** → only the pre-existing `fast_track` failure. Record.
- [ ] **Step 2: CRITICAL scenario gate** — `.venv/Scripts/python.exe tools/scenario_runner_full.py --priority CRITICAL` → **22/22** (real OpenAI; operator-approved — the booking guardrail proof). Confirm booking scenarios unchanged flag OFF.
- [ ] **Step 3: Flag-ON focused** — the per-product tests + a flag-ON camp booking still books correctly (camp unaffected when a camp turn resolves to camp).
- [ ] **Step 4: `evals/baseline.json` md5 `93973fcd...` unchanged.**
- [ ] **Step 5: Write `docs/ENABLEMENT_USE_PER_PRODUCT_BOOKING.md`** — enable (env `USE_PER_PRODUCT_BOOKING=true` + `USE_DYNAMIC_PROGRAMS=true` + restart), the **new Sheets Program column** (forward-only; the operator should add the header to the live sheet or let the resize logic add it — verify on staging first), rollback (flag off = 17-col + camp behavior), and the staging acceptance test: seed Disneyland in `/admin/programs` (age 7–16, registration open), book a consultation for a 7-year-old → succeeds, Calendar event created, lead row has `disneyland_tour` in Program, manager notified. Camp booking still works.
- [ ] **Step 6: Commit** the runbook.

---

## Definition of Done

With `USE_PER_PRODUCT_BOOKING` + `USE_DYNAMIC_PROGRAMS` ON, a parent can book a consultation for the Disneyland product using ITS age band + registration, the lead is tagged `program_id="disneyland_tour"` (new Sheets column) and post-booking follow-ups use Disneyland facts. With the flag OFF: **byte-identical** — camp band, camp registration, 17-col lead row, camp facts; CRITICAL 22/22; full suite green but the one pre-existing failure; `evals/baseline.json` unchanged. **Every booking validation gate is preserved (verified by running the camp guardrail tests with the flag ON).**

**Explicitly NOT in scope:** reserved-product (Sunday School) booking (needs PROGRAM_REGISTRY un-gating); per-product follow-up cadence; adult-flow; enabling the flag.

## Self-Review
- Guardrail preservation: Task 3 copies the camp guardrail tests and runs them flag-ON; only age-band/registration source swapped + tag added. ✅
- Flag-off byte-identity: every task's off path is today's path (unread field, camp band, 17-col row, camp facts). ✅
- Fail-closed: Task 2 returns the camp band on any missing/blank/unknown; registration missing ⇒ closed. ✅
- Product id from backend (`match_dynamic_program`), not the LLM. ✅
- Sheets column risk: flag-gated width; append-range matches; nothing in the 17 existing columns altered. ✅
