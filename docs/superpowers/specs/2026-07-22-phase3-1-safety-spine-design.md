# Phase 3.1 — Safety Spine — Design Spec

**Date:** 2026-07-22 · **Status:** DRAFT for operator review (before any plan/code)
**Branch:** `feat/dynamic-programs` (LOCAL) · **Parent spec:** `docs/superpowers/specs/2026-07-22-phase3-interceptors-to-tools-design.md` · **Grounding:** `docs/PHASE3_0_INTERCEPTOR_INVENTORY_2026_07_22.md` (T3)

---

## 1. Goal

Make the guardrail zone **path-independent** so that routing *more* turns to the LLM (Phase 3.2) is safe. Today the guardrails are scattered through one ordered ~40-interceptor chain, so **the dynamic-program hoist bypasses them** (the guardrail-bypass audit found injection / political / underage / PII unreachable on the hoist path). Phase 3.1 extracts them into **one small layer that runs first on EVERY path** — the normal chain, the hoist, and (3.2) the LLM-first default — and generalises the camp-hardcoded rules to be **program-scoped**.

**Phase 3.1 changes NO answers.** It is a structural move: the same guardrails, same outcomes, now reached identically on every path. It is a prerequisite for 3.2, not a behaviour change itself.

### Success criteria

| | |
|---|---|
| Guardrail coverage | **path-independent** (identical on chain AND hoist) — the audit gap closed structurally |
| Behaviour, flag OFF | **byte-identical** — every existing test green (5,270 pass / 1 pre-existing) |
| Age eligibility | **program-scoped** (a robotics-club under-age question never says "camp is 9–17") |
| CRITICAL scenarios | 22/22 unchanged |
| New instrument (Phase 3.0) | baseline `93973fcd` untouched |

---

## 2. What goes in the spine (grounded in T3, not guessed)

The T3 inventory counted the guardrails honestly: **11**, of which **≈6 are sole-enforcers** (no backend net) and **5 are already backend-double-enforced** by `parent_tool_executor`.

### Layer 0 — pure safety (always first, every path, NO business context)
These have **no backend enforcement** and answer with a fixed safe redirect — they must run before anything else on every path:

| Interceptor (`parent_flow.py`) | Guarantee |
|---|---|
| `_maybe_handle_offtopic_injection` | prompt-injection / exfiltration → safe redirect (already called inside the hoist — the pattern to generalise) |
| `_maybe_handle_political` | political bait → neutral redirect |
| `_maybe_memory_info_reply` | "what do you know about me?" → masked, never leaks PII |
| **age-eligibility** (`_maybe_handle_out_of_range_age` + `_maybe_handle_underage_manager_handoff`) | under-min age → eligibility + manager handoff — **but PROGRAM-SCOPED** (per-program bounds, not camp 9–17) |

### Layer 1 — commitment guardrails (deterministic, never the model's decision)
These own money / contact / handoff. Most are **already backend-enforced** (the executor blocks the unsafe outcome), so they are deterministic *fast-paths* rather than the sole safety net — but they stay deterministic per the operator's hard constraint (booking · lead capture · manager-number):

| Interceptor | Backend net? |
|---|---|
| `_maybe_commit_pending_booking_engine` | ✅ full `book_consultation` success contract |
| `_maybe_handle_contact_collection` / `_maybe_request_full_contact_on_intent` | ✅ `missing_name`/`missing_phone`/`invalid_phone` at commit |
| `_maybe_handle_explicit_manager_request` | ✗ sole enforcer (manager-number disclosure) |
| `_maybe_handle_contact_correction` | ✗ sole overwrite path (PII integrity) |
| `_maybe_handle_sunday_school` | ✗ sole enforcer (SS email handoff — until R3 generalises it) |

**Everything else (18 advisory + ~14 state/mechanics) is NOT in the spine** — those are Phase 3.2 inversion targets (advisory) or stay as plumbing (state). Phase 3.1 does not touch them.

---

## 3. Architecture

### 3.1 One entry point, called on every path

```python
def _safety_spine(conversation, message) -> str | None:
    """Layer 0 + Layer 1, in a fixed order, program-scoped. Returns a response
    to short-circuit, or None to continue. Pure — the SAME call is made at the
    top of the normal chain, inside the dynamic-program hoist, and (3.2) before
    the LLM-first default. This is what makes hoisting safe."""
    for guard in _SPINE:                 # ordered, small, explicit
        r = guard(conversation, message)
        if r is not None:
            return r
    return None
```

- **Flag-gated** `USE_SAFETY_SPINE` (default OFF). OFF ⇒ the existing chain runs exactly as today (byte-identical); the spine is not called.
- ON ⇒ `_safety_spine` runs first on the normal chain **and inside the hoist** (replacing the hoist's lone `_maybe_handle_offtopic_injection` call with the full spine). The individual interceptors are ALSO left in their current chain positions initially (redundant but harmless — a guard that already fired returns the same thing), then removed from the chain only once the spine is proven to own them (incremental, per §4).

### 3.2 Program-scoped eligibility (the one real generalisation)

The only guardrail that is camp-hardcoded is age-eligibility. R1 already built the fix: `admin_config_service.get_program_age_bounds(program_id)` (fail-closed to camp). The spine resolves the turn's program (reusing R1's `_resolve_booking_program_id` / the sticky `lead.program_id`) and checks eligibility against **that program's** bounds. So an under-age robotics-club question gets the robotics club's range, never "camp is 9–17". Flag OFF / no program ⇒ camp bounds ⇒ byte-identical.

---

## 4. Landing strategy — incremental, byte-identity per guard (🔴 the risk control)

This is a refactor of an 11,318-line file with 5,270 tests where **guards are order-dependent** — the project's history is full of ordering bugs (sanitizer entry 69 shadowing 71; the hoist precedence). So:

1. **Build the spine additively, flag OFF** — `_safety_spine` + `_SPINE` list, not yet called. Prove it composes.
2. **Enable on the hoist path first** — the hoist today only runs injection; give it the full spine. This is pure *addition* of safety to a path that lacked it (the audit gap) — nothing to break, because the hoist had no guardrails to be byte-identical against.
3. **Enable on the normal chain, one guard at a time** — for each guard, prove flag-ON == flag-OFF on that guard's own test set (the guard fires at the spine position identically to its chain position), THEN remove it from its old chain position. One commit per guard, each with its byte-identity proof.
4. **Program-scope eligibility last** — the only behaviour *generalisation*; gated + tested against both camp (unchanged) and a synthetic non-camp program (new correct behaviour).

**No big-bang.** If any guard can't be proven byte-identical at the spine position, it stays in the chain and we document why.

---

## 5. What this is NOT

- **Not** a behaviour change (flag OFF byte-identical; flag ON = same guardrails, path-independent + program-scoped eligibility).
- **Not** the polarity inversion — that is 3.2, and it becomes *safe* only after the spine exists.
- **Not** touching the 18 advisory interceptors or the state/mechanics plumbing.
- **Not** removing camp — camp's advisory handlers stay until 3.2 inverts them; the spine only generalises the one *guardrail* that was camp-hardcoded (eligibility).

---

## 6. Risks

| Risk | Control |
|---|---|
| Ordering bug when a guard moves to the spine | Byte-identity proof PER guard before removing it from the chain (§4.3); one commit per guard |
| Spine changes an answer | Flag OFF default + full suite green + CRITICAL 22/22 before any enablement |
| Eligibility generalisation regresses camp | `get_program_age_bounds` fail-closes to camp; camp path tested unchanged |
| Hoist double-fires a guard | The hoist's existing lone injection call is REPLACED by the spine (not added alongside) |
| Scope creep into 3.2 | Spine is exactly the ~11 T3 guardrails; advisory handlers are explicitly out |

---

## 7. Open question for the operator (before the plan)

**Q: land the spine on the hoist path only first (fixes the audit gap, lowest risk, no chain reorder), ship/observe, THEN do the chain extraction — or do both in one Phase 3.1?**
Recommendation: **hoist-first, as its own increment.** It closes the real security gap (guardrails bypassed on the dynamic-program path — the path the operator is actively using for Disneyland) with the least risk, and it is independently valuable. The chain extraction (steps §4.3–4.4) can follow once the spine is proven on the hoist.

---

## 8. Effort

| Increment | Sessions |
|---|---|
| Spine built + enabled on the hoist path (closes the audit gap) | 1–2 |
| Chain extraction, one guard at a time (byte-identity each) | 2–4 |
| Program-scoped eligibility | 1 |
| **Phase 3.1 total** | **4–7** (matches the parent-spec estimate) |
