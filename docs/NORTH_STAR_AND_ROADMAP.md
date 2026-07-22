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

### 1a. THE CORE PROBLEM (why this whole effort exists)

**Today the agent often does not understand the customer's reply and returns an answer that does not match the question.** That mismatch — a customer says X, the agent answers something unrelated — is the single reason for this rebuild. Everything below serves one end: **the agent understands what the customer actually asked (however phrased, whatever they just said) and returns the right, relevant answer.** A smart agent that answers the wrong question is worse than useless.

### 1b. THE FULL FUNCTION SET — every program has ALL of these, driven by its admin data

1. **Greeting → offer active programs.** When a customer just greets, the agent greets back and offers the programs that are **active in the admin panel** (a live, data-driven menu — not a hardcoded one). If instead the customer asks about a specific program, it answers that program directly (no forced menu).
2. **Smart info answering** — any question, any phrasing, answered from that program's real data.
3. **Topic reasoning** — safety, food, schedule, etc., reasoned from the program's details.
4. **Consultation booking** — Calendar, using the program's own age band + registration.
5. **Lead capture — named per program** (each program's leads are identifiable by its name on the Sheet).
6. **Follow-ups — for EVERY program** (not only camp): if the customer stops replying, a follow-up fires. Generalise the existing PARENT/camp-only follow-up to every program.
7. **Comment → DM flow — per program.** Every program has its own **#hashtag** that maps a post to that program; a comment on that post that shows interest/asks price → an automatic private message (DM) to the commenter. (This exists for camp/adult; make it work per program from admin data.)
8. **Lifecycle = the `status` switch.** `active` → offered/answerable/bookable; `ended`/`hidden` → fully off (camp included); `coming_soon` → answerable but not bookable. One rule, every program.
9. **Never re-ask known info.** Once the customer states the child's age (or name, phone, anything), the agent never asks for it again. (Exists partially — make it reliable.)
10. **Never mix programs.** A question about program A is never answered with program B's facts; the agent keeps each program's data separate.
11. **Use the right knowledge/skill.** The agent applies the appropriate sales knowledge/skill for the situation (objection handling, discovery, etc.) — the business's sales method, not a free-for-all.

**Nothing the agent does today is lost** — booking, lead, manager handoff, comment flow, follow-ups all continue; they get *generalised per program* and made *reliable*, never removed.

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

### R2 — `status` lifecycle for every program  ✅ **DONE — live-confirmed 2026-07-22** *(flag `USE_DYNAMIC_WELCOME`, on the test Page)*
The admin `status` field (`active` / `ended` / `coming_soon` / `hidden`) is the single switch that governs whether the agent offers, answers, and books a program — uniformly for EVERY program, camp included. Mark camp `ended` → the agent stops offering/booking it, cleanly. Replaces camp's bespoke registration/date special-casing with the one status rule.
**Delivers:** the operator fully controls each program's on/off from the panel.

### R3 — Un-gate the reserved products (camp / Sunday School / adult events)
Today camp, Sunday School and adult events are hardcoded (a closed 3-id enum, canned handlers). Generalise them to be data-driven like any other program, so Sunday School (and camp) reason over their admin data instead of returning canned text — and a 4th, 5th product is representable. This removes the last structural difference between "the 3 special programs" and "everything the operator adds."
**Delivers:** truly product-agnostic — Sunday School answers intelligently; no program is special.

### R4 — Reasoning quality + measurement (the openclaw polish) — solves §1a, the CORE PROBLEM
With the structure product-agnostic, make the agent reliably **understand the customer's reply and return the matching answer** (§1a) — including *never re-ask known info* (#9), *never mix programs* (#10), and *apply the right sales knowledge/skill* (#11). Measure it (the eval instrument + real-conversation review, one enabled flag at a time), including the open model-tier question (gpt-4.1-mini vs a stronger model) decided on real data.
**Delivers:** the CORE fix — the right answer to what was actually asked — proven, not assumed.

### Coverage — every function (§1b) has a home

| # | Function | Delivered by | Today |
|---|---|---|---|
| 1 | Greeting → offer ACTIVE programs | ✅ R2 done (status drives the live menu) | camp-only static menu |
| 2 | Smart info answering | R3 (all programs) | ✅ dynamic products; reserved=canned |
| 3 | Topic reasoning | done for dynamic; R3 for reserved | ✅ per-product verified |
| 4 | Consultation booking | **R1** | camp-only |
| 5 | Lead, named per program | **R1** | camp lead, unnamed |
| 6 | Follow-ups, every program | R1/R3 (rides the per-product lead) | PARENT/camp only |
| 7 | Comment #hashtag → DM, per program | R3 (generalise existing flow) | exists camp/adult |
| 8 | Lifecycle `status` (`ended`=off) | ✅ **R2 done** | camp bespoke dates |
| 9 | Never re-ask known info | R4 | partial (lead memory) |
| 10 | Never mix programs | R3 + R4 (routing precision) | partial |
| 11 | Right knowledge/skill | R4 (skills) | built, off |
| — | **§1a understand & answer right** | **R3 + R4 (the heart)** | the core bug |

## 5. The discipline (why this won't churn)

The direction (§1–§2) is fixed. What changed before was tactical detail as the codebase was learned — that learning is now done and captured here. The one rule that keeps every step honest:

> **Build one piece behind a flag → enable it on staging on a real test product → see it actually work for a real question → only then the next piece.**

This project's three prior negative phases were all "built behind a flag, never enabled, never measured." R1–R4 each end with *enabled on staging and seen working*, not *merged and hoped*. Money/commitment paths (booking, price, PII) stay deterministic and are gated by the CRITICAL scenario suite (22/22) before any enablement.

## 6. What this is NOT

- Not a rewrite — every step is additive and flag-gated; the live agent is unchanged until the operator enables a flag.
- Not full openclaw autonomy — booking/price/PII stay deterministic by design (invariant #3).
- Not "smart" by more machinery alone — R4 measures it on real conversations; if a step doesn't beat the current behavior, it doesn't ship (the honest lesson from the prompt-hygiene phase).

---

**Immediate next:** ~~R2~~ ✅ **DONE (live-confirmed 2026-07-22).** Next is **R1** (per-product booking + lead — plan ready), then **R3** (un-gate reserved products incl. Sunday School), then **R4** (the core reasoning problem, §1a). Each enabled + seen working on the Disneyland test product before moving on.
