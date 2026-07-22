# Phase 3.2 (first domain) — Camp → Product-Agnostic — Design Spec

**Date:** 2026-07-22 · **Status:** DRAFT for operator review (before any plan/code)
**Parent:** `docs/superpowers/specs/2026-07-22-phase3-interceptors-to-tools-design.md` (§3.2 invert polarity) · **Grounding:** `docs/PHASE3_0_INTERCEPTOR_INVENTORY_2026_07_22.md`, `docs/PHASE3_KNOWLEDGE_LANDSCAPE_2026_07_22.md`

---

## 1. Goal (the operator's visible fix)

Make **camp** flow through the SAME smart LLM+tool path as a dynamic product (Disneyland/Formula1 already do), so:
- marking camp **`ended`** removes it from active programs → **fully off** (no bleeding into other conversations);
- the agent stops **mixing** camp into a Disneyland answer;
- a non-camp under-age question stops leaking **"camp is 9–17"**;
- camp answers are **reasoned from its data**, not emitted by ~15 canned handlers.

This is the phase where the operator **sees** the agent become product-agnostic for its own flagship product.

## 2. The real blocker (grounded — corrects Survey D)

Survey D pointed at `app/domain/decision/ProgramRegistry`'s exactly-3-ids invariant. **Confirmed 2026-07-22: that class is UNWIRED** — only the `ProgramId` *enum* is imported live. So the real, live blocker is smaller and more tractable:

1. **The dynamic tool REFUSES camp.** `parent_tool_executor._get_program_info` returns `use_specific_tool` for any id in `_HARDCODED_PROGRAM_IDS = {summer_camp, sunday_school, adult_events}` (line 432). So the LLM cannot answer camp from its section data the way it answers Disneyland.
2. **The hoist EXCLUDES camp.** `_is_dynamic_program_turn` / `match_dynamic_program` deliberately treat camp's name tokens as ambiguous, so a camp turn never hoists to the engine — it falls into the deterministic camp chain.
3. **~15 dedicated camp advisory handlers** answer camp turns with canned/YAML text (the 18 ADVISORY interceptors, most camp-specific).

Camp's FACTS already live in `sections.yaml` (`summer_camp`) and are read by `get_camp_info`. So the data exists; only the *routing + refusal* forces the canned path.

## 3. Approach — invert camp incrementally, MEASURED

Not a big-bang. Camp is the live-business core — but it is **OFF-SEASON right now** (season ended 2026-07-20, no live camp customers), which makes **now the lowest-risk window** to restructure it. Still, discipline:

- **Flag-gated** (`USE_CAMP_AS_PROGRAM`, default OFF) ⇒ byte-identical camp behaviour until enabled.
- **Per-domain**, using the Phase-3.0 instrument: for each camp advisory domain (topic-facts, price, streams, intro, transport, operational…), let the LLM answer it from a tool instead of the canned handler → **measure canned vs LLM on the metric** → LLM ≥ canned keeps it, LLM < canned reverts it.
- **Reuse what's built:** the topic-facts inversion already exists (`USE_PROGRAM_TOPICS` + `get_program_topic`); R1 gives camp per-product booking+lead if camp is treated as a product; the safety spine (3.1) keeps the hoist safe; the routing fix keeps a camp booking on the engine.

### 3.1 The core switch
Behind `USE_CAMP_AS_PROGRAM`:
1. **Un-refuse camp in `_get_program_info`** (remove/relax the `_HARDCODED_PROGRAM_IDS` gate for `summer_camp`) so the LLM can read camp's section facts generically.
2. **Let a camp turn hoist** (treat `summer_camp` as hoist-eligible) so camp reaches the engine + tools instead of the canned chain.
3. **The camp advisory handlers yield** when the flag is on (like they already don't fire for a dynamic product) — the engine answers from `get_camp_info`/`get_program_info`/`get_program_topic`.
4. **`ended`/status governs** via `get_active_sections` (already filters `active`) — no camp-specific status handler needed.

### 3.2 What stays deterministic (Layer 1 — the operator's hard constraint)
**Booking · lead capture · manager-number handoff stay deterministic**, via the existing executor guardrails (R1's `book_consultation`, contact capture, manager disclosure). Inverting camp changes how it ANSWERS, never how it COMMITS.

## 4. Sunday School + adult events
Same pattern, later increments. Sunday School currently has a bespoke email-handoff (sole enforcer) — un-refusing it needs the handoff generalised first (the §3 lead-store/action seam). Adult events already have their own engine. Camp is the first + highest-value domain; SS/adult follow once camp proves the pattern.

## 5. Risks

| Risk | Control |
|---|---|
| Camp is the live business | OFF-SEASON now (no live customers) + flag OFF default + measured before enable |
| LLM answers camp worse than canned | Per-domain measure (3.0 instrument); LLM < canned → revert that domain |
| Losing a camp guardrail | Booking/lead/manager stay deterministic (Layer 1); safety spine on the hoist |
| Ordering/precedence bugs | Flag-gated, byte-identical off, one domain at a time |
| Measurement needs paid runs | The per-domain canned-vs-LLM capture is the one operator-approved ~$1 gate |

## 6. Definition of done (per domain)
Flag OFF: byte-identical canned camp. Flag ON: that camp domain is answered by the LLM from a tool, measured ≥ the canned baseline, guardrails intact, `ended` fully off. Full suite green.

## 7. Open question for the operator
Camp is off-season → **do we invert camp now (ideal low-risk timing) or wait?** Recommendation: **now** — it is the lowest-risk window we will get, the operator is actively hitting the camp-bleed bug, and the instrument to measure it is built.
