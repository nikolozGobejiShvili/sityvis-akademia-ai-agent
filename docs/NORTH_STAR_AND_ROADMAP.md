# North Star & Roadmap — the openclaw-like, fully operator-driven agent

**Date:** 2026-07-22 · **Status:** CANONICAL. This is the single, stable reference. The *direction* here does not change; only tasks get checked off.

---

## 1. The final agent — the picture

**One data-driven sales agent. The operator manages everything from the admin panel; the agent reasons.**

- The operator adds/edits ANY program in the admin panel — camp, Sunday School, Disneyland tour, adult events, anything future — with its own price, days, age, safety, details, and lifecycle. **No code change to add a program.**
- The customer asks **anything, however phrased**. The agent **understands the intent, reasons, and answers from that specific program's real data** — not a memorised template, not a canned block, not an invented fact.
- Every program has the **same full function set**, driven by its data: *info answering · topic reasoning (safety/food/etc.) · consultation booking · a lead tagged with the program's name · lifecycle (active / ended / coming soon)*.
- **`status` is the single lifecycle switch.** Mark a program `ended` in the panel → the agent fully turns it off (no info, no offer, no booking) — for ANY program, camp included.

In one line, the operator's own formula:

> **openclaw-like in reasoning · deterministic in commitments · fully operator-driven.**

## 2. The four invariants (these NEVER change)

1. **Reasoning, not scripts.** The model understands varied phrasing and answers naturally — like openclaw. We remove the deterministic keyword-routers that force canned text.
2. **Facts & commitments from the backend, never the model's memory.** Price, dates, age, booking, lead, manager phone — always from admin data / validated tools. The model reasons the *wording*, never invents the *facts*.
3. **Deterministic guardrails stay for money/commitments.** Booking success, price digits, PII/contact capture, age eligibility — these NEVER become "the model's guess." (openclaw improvises because a mistake means bad code; here a mistake means a wrong price to a customer.)
4. **Operator-driven, no code per program.** Everything about a program lives in the admin panel. Adding the Nth product requires zero engineering.

## 3. Where we are (done + live)

- ✅ **Dynamic programs** — a new admin product answers info questions from its own data. **LIVE in production** (proven with "ფორმულა1", 2026-07-20).
- ✅ **Persistence** — admin edits survive redeploys (Railway volume). **LIVE.**
- ✅ **Per-product topic reasoning** — a separate product's safety/details questions already reason over ITS data (via the dynamic-programs path + `get_program_info`). **Verified.**
- ✅ **Camp topic tool + review + fixes** — the camp's rich 502-line knowledge is a tool the model reasons over; the 20-conversation review + V4/V5 fixes landed and were verified live (wins on V1/V4/V5). Flag-gated, off by default.
- **Safety net:** every change is flag-gated, byte-identical off, ~5200 tests green, the eval baseline protected, nothing pushed.

## 4. The roadmap to the goal — four remaining pieces (stable, in order)

Each piece is flag-gated and follows the **discipline** in §5. Nothing here is speculative; each closes a concrete gap between today and §1.

### R1 — Per-product consultation booking + lead  *(plan ready: `2026-07-22-capability-per-product-booking-lead.md`)*
A new product (Disneyland) gets camp's booking function: a parent books a consultation using THAT product's age band + registration; the lead is tagged with the program's name (a per-program identity on the Sheet). Surgical change to `book_consultation`, every booking guardrail preserved.
**Delivers:** "same functions as camp" for any new product.

### R2 — `status` lifecycle for every program  *(the piece you just added)*
The admin `status` field (`active` / `ended` / `coming_soon` / `hidden`) is the single switch that governs whether the agent offers, answers, and books a program — uniformly for EVERY program, camp included. Mark camp `ended` → the agent stops offering/booking it, cleanly. Replaces camp's bespoke registration/date special-casing with the one status rule.
**Delivers:** the operator fully controls each program's on/off from the panel.

### R3 — Un-gate the reserved products (camp / Sunday School / adult events)
Today camp, Sunday School and adult events are hardcoded (a closed 3-id enum, canned handlers). Generalise them to be data-driven like any other program, so Sunday School (and camp) reason over their admin data instead of returning canned text — and a 4th, 5th product is representable. This removes the last structural difference between "the 3 special programs" and "everything the operator adds."
**Delivers:** truly product-agnostic — Sunday School answers intelligently; no program is special.

### R4 — Reasoning quality + measurement (the openclaw polish)
With the structure product-agnostic, tune the reasoning so answers are consistently smart and human across programs, and measure it (the eval instrument + real-conversation review, one enabled flag at a time). This is where "feels openclaw-smart" is earned and proven — including the open model-tier question (gpt-4.1-mini vs a stronger model) decided on real data.
**Delivers:** the quality bar of §1, proven, not assumed.

## 5. The discipline (why this won't churn)

The direction (§1–§2) is fixed. What changed before was tactical detail as the codebase was learned — that learning is now done and captured here. The one rule that keeps every step honest:

> **Build one piece behind a flag → enable it on staging on a real test product → see it actually work for a real question → only then the next piece.**

This project's three prior negative phases were all "built behind a flag, never enabled, never measured." R1–R4 each end with *enabled on staging and seen working*, not *merged and hoped*. Money/commitment paths (booking, price, PII) stay deterministic and are gated by the CRITICAL scenario suite (22/22) before any enablement.

## 6. What this is NOT

- Not a rewrite — every step is additive and flag-gated; the live agent is unchanged until the operator enables a flag.
- Not full openclaw autonomy — booking/price/PII stay deterministic by design (invariant #3).
- Not "smart" by more machinery alone — R4 measures it on real conversations; if a step doesn't beat the current behavior, it doesn't ship (the honest lesson from the prompt-hygiene phase).

---

**Immediate next:** execute **R1** (per-product booking + lead — plan ready), then fold in **R2** (the `status`/`ended` lifecycle). R3 and R4 follow. Each enabled + seen working on the Disneyland test product before moving on.
