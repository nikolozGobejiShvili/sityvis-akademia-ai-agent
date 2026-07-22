# Phase 3.1 (increment 1) — Hoist-first Safety Spine — Implementation Plan

> Design: `docs/superpowers/specs/2026-07-22-phase3-1-safety-spine-design.md` (§7 hoist-first, operator-approved).

**Goal:** close the audit gap where the dynamic-program **hoist** bypasses the Layer-0 safety guardrails. Today the hoist runs ONLY `_maybe_handle_offtopic_injection` before the engine, so a political / PII ("what do you know about me?") turn on the hoist path skips those safe redirects. Build a `_safety_spine` (injection · political · memory-info — the 3 program-AGNOSTIC sole-enforcer safety guards) and, behind a flag, run it on the hoist instead of the lone injection call.

**Scope (deliberately small):** ONLY the hoist path, ONLY the 3 program-agnostic safety guards. Age-eligibility on the hoist is already owned per-product by the engine (R1 `book_consultation` + the routing fix), so it is NOT in this increment. Layer-1 commitment guards (booking/contact) are engine-owned on the hoist — NOT in this increment. The chain extraction + program-scoped eligibility are later Phase-3.1 increments.

## Global Constraints
- **Flag `USE_SAFETY_SPINE` default OFF ⇒ byte-identical.** OFF ⇒ the hoist runs exactly `_maybe_handle_offtopic_injection` as today.
- `_safety_spine` runs injection FIRST (so an injection turn is caught identically to today), then political, then memory-info.
- NO change to any guard's own logic; NO change to the normal chain (only the hoist call site). LOCAL branch `feat/dynamic-programs`; no push without consent.
- Interpreter `.venv/Scripts/python.exe`. Pre-existing failure `test_approved_copy_service...fast_track` is expected.

## Task 1 — Flag + `_safety_spine` + hoist wiring
**Files:** `app/config.py`, `tests/conftest.py`, `app/flows/parent_flow.py`; Test `tests/test_safety_spine_2026_07_22.py`.

- [ ] Failing tests: flag default off; `_safety_spine` returns the injection/political/memory-info redirect for each trigger and None for a normal turn; hoist flag-ON catches a political turn on a sticky dynamic-program conversation (engine NOT reached); hoist flag-OFF lets it reach the engine (byte-identical).
- [ ] Implement: `USE_SAFETY_SPINE: bool = False` (+ from_env, conftest pin). `_safety_spine(conversation, message)` iterates `(_maybe_handle_offtopic_injection, _maybe_handle_political, _maybe_memory_info_reply)` returning the first non-None (names resolved at call time). Hoist (parent_flow.py:1090): `spine = _safety_spine(...) if USE_SAFETY_SPINE else _maybe_handle_offtopic_injection(...)`.
- [ ] Run → pass; flag-OFF byte-identity (hoist/injection regression green); commit.

## Definition of Done
Flag OFF: hoist byte-identical (injection only). Flag ON: the hoist path also gives the safe political + PII redirects (audit gap closed on the path the operator actively uses for Disneyland). Full suite green but the pre-existing failure. No normal-chain change.
