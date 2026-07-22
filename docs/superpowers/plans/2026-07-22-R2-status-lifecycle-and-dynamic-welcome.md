# R2 — Status Lifecycle + Data-Driven Welcome Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** The greeting menu offers the programs that are **active in the admin panel** (a live, data-driven menu), so a newly-added program (Disneyland) appears and an `ended`/`hidden` program drops — uniformly for every program, camp included. This delivers roadmap functions #1 (greeting → active programs) and #8 (`status` governs the menu).

**Architecture:** New flag `USE_DYNAMIC_WELCOME` (default OFF). When ON, `_maybe_static_welcome` builds the greeting from `admin_config_service.get_active_sections()` (each program by its `name`), keeping the brand opener/voice. When OFF, it returns the current hardcoded `PARENT_WELCOME` exactly — byte-identical. Status governance is already enforced (`get_active_sections` filters `status=="active"`; ended camp returns its ended message; dynamic ended is excluded) — R2 makes the *menu* respect it too, and verifies uniform behavior.

**Tech Stack:** Python 3.10. No new dependency. No agent-model change.

## Global Constraints

- **The welcome is the FIRST thing every customer sees — high-visibility.** Flag OFF ⇒ `_maybe_static_welcome` returns the current `PARENT_WELCOME` byte-for-byte, on every path it fires today (the existing tests `test_static_welcome_still_fires_on_plain_georgian_greeting` etc. MUST stay green). The explicit-camp-intent yield (`_has_explicit_georgian_camp_intent` → returns None) is unchanged.
- **Flag OFF ⇒ BYTE-IDENTICAL.** Full suite (~5200) green but the pre-existing `fast_track` failure. `evals/baseline.json` md5 `93973fcd...` unchanged.
- **Data-driven menu, brand voice preserved.** The ON menu keeps the opener „გამარჯობა.\n\nგვითხარით, რა გაინტერესებთ:" then one bullet („— {name}") per ACTIVE section, in the section order. Use each section's `name`. Fail-SAFE: if `get_active_sections()` is empty or raises, fall back to the hardcoded `PARENT_WELCOME` (never show an empty menu).
- **Status is the single switch (verify, don't rebuild).** `ended`/`hidden`/`full`/`coming_soon` sections are already excluded from `get_active_sections()` (only `active` passes). R2 must NOT weaken that. Camp's own `ended` handling (the "streams ended" message) stays. Do NOT add new status semantics — just consume `get_active_sections()`.
- Do NOT touch `OPENAI_MODEL`, `.env`, booking/lead/Calendar logic, the dormant slim/planner path, `data/admin_config/sections.yaml`, `evals/baseline.json`, `CLAUDE.md`, `HANDOFF.md`. **LOCAL-only** branch `feat/dynamic-programs`. Interpreter `.venv/Scripts/python.exe`. No haiku.
- **Expected pre-existing failure** (not in scope): `tests/test_approved_copy_service_2026_07_11.py::...fast_track`.

---

## File Structure

**Modify:** `app/config.py` (+`USE_DYNAMIC_WELCOME`) · `tests/conftest.py` (pin OFF) · `app/flows/parent_flow.py` (`_maybe_static_welcome` flag branch + a `_build_active_programs_welcome()` helper).
**Create:** `tests/test_dynamic_welcome_2026_07_22.py`; `docs/ENABLEMENT_USE_DYNAMIC_WELCOME.md`.

---

## Task 1: Flag `USE_DYNAMIC_WELCOME` (default OFF) + conftest pin

**Files:** `app/config.py`, `tests/conftest.py`; Test.

- [ ] **Step 1: Failing test** — `Settings().USE_DYNAMIC_WELCOME is False`; `from_env` parses it.
- [ ] **Step 2: Run → fail. Step 3: Implement** — `USE_DYNAMIC_WELCOME: bool = False` (near `USE_PROGRAM_TOPICS`) + `from_env` reader; pin OFF in `conftest.py`'s autouse replace.
- [ ] **Step 4: Run → pass. Step 5: Commit** — `feat(config): USE_DYNAMIC_WELCOME flag (default off) + conftest pin`

---

## Task 2: `_build_active_programs_welcome()` + flag-gated wiring in `_maybe_static_welcome`

**Files:** `app/flows/parent_flow.py`; Test.

**Interfaces:** Produces `parent_flow._build_active_programs_welcome() -> str | None` — the brand opener + one „— {name}" bullet per active section; returns `None` if there are no active sections OR on any exception (caller falls back to `PARENT_WELCOME`).

- [ ] **Step 1: Read** `_maybe_static_welcome` fully + `PARENT_WELCOME` (`data/prompts.py:59` → the current menu string) + `admin_config_service.get_active_sections()` (returns dicts with `name`).
- [ ] **Step 2: Failing tests:**
  - `_build_active_programs_welcome()` with two seeded active sections (names „ბავშვების საზაფხულო ბანაკი", „დისნეილენდის ტური") → a string starting „გამარჯობა." containing both names as „— " bullets, in order. (monkeypatch `get_active_sections`.)
  - empty active sections → `_build_active_programs_welcome()` returns `None`.
  - **flag OFF:** `_maybe_static_welcome(fresh START conv, "გამარჯობა")` returns exactly `PARENT_WELCOME` (byte-identical — the seeded sections must NOT change it).
  - **flag ON:** the same call returns the dynamic menu containing the seeded section names, NOT the hardcoded adult line.
  - **flag ON but get_active_sections empty/raises:** falls back to `PARENT_WELCOME` (never empty).
  - The explicit-camp-intent yield is unchanged in both flag states (`_has_explicit_georgian_camp_intent` message still returns None).
- [ ] **Step 3: Run → fail. Step 4: Implement:**
  - Add `_build_active_programs_welcome()`:
    ```python
    def _build_active_programs_welcome() -> str | None:
        try:
            from app.services import admin_config_service
            sections = admin_config_service.get_active_sections() or []
            names = [str(s.get("name") or "").strip() for s in sections]
            names = [n for n in names if n]
            if not names:
                return None
            bullets = "\n".join(f"— {n}" for n in names)
            return f"გამარჯობა.\n\nგვითხარით, რა გაინტერესებთ:\n{bullets}"
        except Exception:
            return None
    ```
  - In `_maybe_static_welcome`, where it currently returns `PARENT_WELCOME`, gate:
    ```python
    if getattr(settings, "USE_DYNAMIC_WELCOME", False):
        dynamic = _build_active_programs_welcome()
        if dynamic:
            return dynamic
    return PARENT_WELCOME   # flag off, or fail-safe
    ```
    Change NOTHING else in `_maybe_static_welcome` (the fire conditions, the explicit-camp yield, the state guards stay exactly as today).
- [ ] **Step 5: Run → pass. Step 6: Byte-identity gate** — the existing welcome tests + `test_dynamic_welcome_2026_07_22.py` green. **Step 7: Commit** — `feat(welcome): data-driven active-programs menu (flag-gated, byte-identical off)`

---

## Task 3: Status-governance verification + whole-suite + staging runbook

- [ ] **Step 1: Verify `status` governs uniformly** (test, not new code): an `ended` section is absent from `get_active_sections()` ⇒ absent from the dynamic menu; a `hidden`/`coming_soon` section likewise. Camp `status: ended` still returns its ended message (unchanged). Assert the dynamic menu excludes a seeded `ended` section.
- [ ] **Step 2: Full suite, flag OFF** → only the pre-existing `fast_track`. Record.
- [ ] **Step 3: `evals/baseline.json` md5 `93973fcd...` unchanged; offline eval READ-ONLY clean.**
- [ ] **Step 4: Write `docs/ENABLEMENT_USE_DYNAMIC_WELCOME.md`** — enable (env `USE_DYNAMIC_WELCOME=true` + restart), what changes (greeting lists active programs by name; ended/hidden drop automatically), rollback (flag off = the hardcoded 2-option menu), staging acceptance: with camp+adult+Disneyland active → the greeting lists all three; mark camp `ended` in `/admin/programs` → camp drops from the greeting and camp questions get the ended message; add a program → it appears in the greeting next turn.
- [ ] **Step 5: Commit** the runbook.

---

## Definition of Done

With `USE_DYNAMIC_WELCOME` ON, a bare greeting lists the programs active in the admin panel (each by name); adding a program makes it appear, marking one `ended`/`hidden` makes it drop — uniformly, camp included. With the flag OFF: byte-identical (the hardcoded 2-option `PARENT_WELCOME`), full suite green but the pre-existing failure, `evals/baseline.json` unchanged, the explicit-camp-intent yield unchanged. Fail-safe: no active sections ⇒ the hardcoded menu, never an empty one.

**Explicitly NOT in scope:** per-product booking/lead (R1); reserved-program un-gating (R3); reasoning quality (R4); enabling the flag.

## Self-Review
- Flag-off byte-identity: `_maybe_static_welcome` returns `PARENT_WELCOME` unchanged when off; only an additive gated branch. ✅
- Data-driven + brand voice: opener preserved, one bullet per active section name. ✅
- Status governance: consumes `get_active_sections()` (active-only) — ended/hidden excluded; not weakened. ✅
- Fail-safe: empty/exception ⇒ `PARENT_WELCOME`, never empty. ✅
