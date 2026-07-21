# Phase 3.0 — Interceptor Inventory (T3 classification) + Attribution (T1)

**Date:** 2026-07-22 · **Status:** measurement only — NO production code changed.
**Scope:** `app/flows/parent_flow.py` (11,318 lines), 43 `_maybe_*` interceptors.
**Spec:** `docs/superpowers/specs/2026-07-22-phase3-interceptors-to-tools-design.md` (Phase 3.0, tasks T1 + T3).
**Method:** every interceptor body read (self + 3 read-only sub-agents); backend cross-checked
against `app/agent/tools/parent_tool_executor.py` and `docs/PHASE4_GUARDRAIL_MAP_2026_07_21.md`
(reused, not re-derived). T1 driven through `evals.interception.answered_by_message` with the
LLM engine spied — **zero OpenAI calls, entirely free/offline.**

---

## 0. Headline (the re-scope gate)

| Bucket | Count |
|---|---|
| **GUARDRAIL** (deterministic exception list — Layer 0/1) | **11** |
| **ADVISORY** (invert → LLM + tool, Phase 3.2 targets) | **18** |
| **STATE / MECHANICS** (plumbing — neither answer nor guardrail) | **14** |
| **Total** | **43** |

**True exception-list size = 11** (with 2 borderline items that could push it to ~13 —
`_maybe_handle_camp_status` and `_maybe_requalify_child`, both discussed below).

**Compared to the previous "~8–10" guess: the count is 11 — a modest overshoot, NOT ~25.**

**VERDICT — the plan's central claim SURVIVES.** The guardrail zone is small (11, ≈¼ of the
file). The invertible ADVISORY set is large (18), and if the 4 acknowledgement/close STATE
handlers (which are also not guardrails and carry no safety guarantee) are counted, **~22 of the
43 interceptors are candidates to move off the deterministic chain.** Most of the file is NOT
guardrail: 32 of 43 are advisory or mechanics. Polarity inversion buys a lot.

**It is even smaller than 11 in the strict sense.** Only **6 of the 11 guardrails are the
irreducible safety spine with NO backend enforcement**: injection, political, memory-info (PII),
explicit-manager-number, Sunday-School handoff, contact-correction. The other **5**
(`out_of_range_age`, `underage_manager_handoff`, `contact_collection`,
`request_full_contact_on_intent`, `commit_pending_booking_engine`) are **also independently
enforced by `parent_tool_executor`** — the interceptor is a deterministic fast-path, and the
executor already blocks the unsafe outcome (`age_not_eligible`, `invalid_phone`, `missing_name`,
the full `book_consultation` success contract). Per the brief's own rule, a backend-enforced
guardrail is a *weaker* reason to keep the interceptor pre-LLM. So the hard, must-stay-forever
spine is ≈6, and the plan's Layer-0/Layer-1 design covers it exactly (injection · political · PII ·
age-eligibility · booking-commit · contact-capture · manager-handoff).

---

## 1. T3 — Full 43-interceptor classification

Legend: **GR** = GUARDRAIL · **ADV** = ADVISORY · **SM** = STATE/MECHANICS.
"Backend?" = does `parent_tool_executor.py` (or another deterministic backend guard) independently
enforce the same guarantee (only meaningful for GR rows).

| # | Interceptor (`parent_flow.py`) | Line | One-line purpose | Bucket | Guarantee / backend-enforced? |
|---|---|---|---|---|---|
| 1 | `_maybe_handle_final_camp_public_policy` | 304 | Camp registration-closed / status / SS-pending / future-info policy gate (canned) | **ADV** | Booking-block guarantee is backend-enforced (`camp_registration_closed`); the *answer* is canned status text → invertible |
| 2 | `_maybe_reasoning_analysis` | 370 | Gated (`USE_REASONING_LAYER`, OFF) deterministic intent metadata; no text, no side effects | **SM** | Reasoning hook; dormant |
| 3 | `_maybe_handle_camp_status` | 759 | Admin camp-status gate — answers a camp Q with the status line when camp ≠ active | **ADV** | *(borderline GR)* "don't sell a hidden/ended camp" — but the booking block is **backend-enforced** in the executor (`camp_registration_closed`), so the interceptor is an advisory status answer |
| 4 | `_maybe_capture_challenge_on_goal_reply` | 864 | Capture parent's stated goal/challenge onto the lead (returns None always) | **SM** | Pure `lead.challenge` mutation; MUST stay pre-LLM (feeds manager email/Sheet) |
| 5 | `_maybe_handle_multi_child_age` | 2208 | Record 2+ child ages, ack, continue | **SM** | Captures `lead.child_age` + full list into `deeper_concern`; MUST stay pre-LLM |
| 6 | `_maybe_requalify_child` | 2582 | Clear child_age & re-qualify on "different child"; block if booked | **SM** | *(borderline GR)* embeds a booked-age-integrity guard + 2nd-child→manager handoff; **no** backend enforcement (Python-only). Dominant behaviour is re-qualification state mgmt |
| 7 | `_maybe_acknowledge_stored_state` | 2639 | Acknowledge stored child_age once on a resumed/greeting turn | **SM** | Resume acknowledgement; reads only |
| 8 | `_maybe_handle_out_of_range_age` | 3668 | Under-min disclosed age → eligibility + manager msg (before it's mis-stored as a name) | **GR** | Eligibility. **Backend-enforced**: `age_not_eligible` (executor L1118), `invalid_child_age` (L1101) |
| 9 | `_maybe_handle_repeat_camp_price` | 4123 | Camp price / payment-process / reservation-fee split (approved copy) | **ADV** | Price answer from config/YAML → invert to LLM + `get_camp_info` |
| 10 | `_maybe_handle_multi_question` | 4256 | Answer TWO distinct camp parts in one turn (≤2 canned/YAML blocks) | **ADV** | Composed canned/YAML answers |
| 11 | `_maybe_handle_exact_detail` | 4314 | Known general answer + exact-unknown manager defer (food/staff/peers) | **ADV** | camp_topic_facts YAML + defer |
| 12 | `_maybe_handle_adult_context_relative` | 4406 | Keep "ჩემი შვილისთვის" in adult-events context (don't flip to camp) | **SM** | Segment/context routing; reads only |
| 13 | `_maybe_handle_parent_contact_visit` | 4513 | "Can I call/visit my child?" → daily-updates fact + manager defer | **ADV** | Approved/YAML copy + defer |
| 14 | `_maybe_handle_identity` | 4586 | "Are you AI/GPT/human?" → canned brand-consultant identity | **ADV** | Canned identity text *(borderline: sits pre-LLM to avoid political/age misfire, but payload is informational)* |
| 15 | `_maybe_handle_political` | 4600 | Political / party-bait → neutral fixed redirect (`camp_topic_facts.political_reply`) | **GR** | Political safety. **SOLE enforcer** (no backend tool). Layer 0 |
| 16 | `_maybe_handle_unclear_phrase` | 4617 | Recognised unclear Georgian phrase → polished clarification | **ADV** | YAML clarification |
| 17 | `_maybe_handle_unknown_operational_early` | 4656 | Anti-invention manager defer for unsupported ops details (seats/rooms/towels) | **ADV** | YAML defer; anti-hallucination flavour, no PII/money/commitment |
| 18 | `_maybe_handle_reservation_fee_question` | 4797 | Unknown reservation-fee amount → manager defer | **ADV** | Approved YAML defer |
| 19 | `_maybe_handle_transport_logistics` | 4990 | Transport as transport (beats "სპორტ" substring) — included-in-price fact + defer | **ADV** | Approved YAML + defer |
| 20 | `_maybe_handle_camp_topic_facts` | 5038 | Focused camp-topic fact block for a specific concern | **ADV** | camp_topic_facts YAML |
| 21 | `_maybe_handle_underage_manager_handoff` | 5185 | Under-age handoff with a REAL operator dispatch (message-only) | **GR** | Eligibility + real manager dispatch. **Backend-enforced**: `age_not_eligible` (L1118) + `_request_manager_callback` (L1533, gated on real send) |
| 22 | `_maybe_handle_sunday_school` | 5552 | SS status + lead capture + EMAIL-only manager handoff | **GR** | Lead-capture + handoff commitment ("გადავეცი" only on real email). **SOLE enforcer** — no LLM tool exists for SS. *(info-answer portion is advisory; dispatch/capture is the guardrail)* |
| 23 | `_maybe_handle_camp_registration_link` | 5850 | Return the configured Admin `registration_url` for a link/form request | **ADV** | Admin-config value; anti-invention (`registration_url_missing`) partially backend-covered → invert to `get_camp_info('registration')` |
| 24 | `_maybe_handle_explicit_manager_request` | 6042 | Disclose the manager's phone on explicit / self-call request | **GR** | Manager-number handoff (operator hard-constraint). **SOLE enforcer** — PARENT LLM path has no disclosure route |
| 25 | `_maybe_handle_contact_correction` | 6116 | Overwrite `lead.phone`/`lead.name` on an explicit correction | **GR** | Contact/PII integrity. **SOLE overwrite path** (`_save_lead_info`/`_request_manager_callback` set name only when empty). *(borderline SM — a lead-fact capture)* |
| 26 | `_maybe_handle_camp_stream_lifecycle` | 6374 | "Has stream N started / when do streams run?" facts | **ADV** | Admin-derived stream facts |
| 27 | `_maybe_handle_camp_stream_query` | 6393 | Stream cohort age-band and/or price direct answer | **ADV** | admin `get_camp_facts()` facts |
| 28 | `_maybe_static_welcome` | 6541 | First-reply branded two-option menu at `state==START` | **SM** | Static welcome; brand opener. MUST stay pre-LLM by design |
| 29 | `_maybe_handle_camp_intro` | 6625 | Exact approved camp intro + age question (child age unknown) | **ADV** | Canned approved intro copy |
| 30 | `_maybe_handle_human_tone_request` | 6738 | "Talk like a human" → short natural ack | **SM** | Canned acknowledgement, no fact payload |
| 31 | `_maybe_handle_availability_question` | 7660 | "Nearest free time / is today free?" → deterministic Tbilisi Calendar listing | **ADV** | Informational Calendar availability; *defers* ineligible to engine (does not enforce) |
| 32 | `_maybe_handle_booking_datetime_reply` | 7769 | Keep a day/date/daypart reply in booking flow; offer REAL free slots | **SM** | Booking datetime flow; MUST stay pre-LLM (keeps daypart replies in booking, surfaces real slots) |
| 33 | `_maybe_handle_event_inquiry` | 7821 | Adult-EVENT inquiry answer inside PARENT (event data / which-event / not-found list) | **ADV** | admin event data |
| 34 | `_maybe_handle_offtopic_injection` | 8051 | Prompt-injection / exfiltration / "who built you" → safe redirect | **GR** | Injection safety. **SOLE enforcer**. Layer 0 (also called inside the dynamic-program hoist) |
| 35 | `_maybe_memory_info_reply` | 8094 | "What do you know about me?" → masked summary of safe fields only | **GR** | PII/privacy — never leaks sender_id/tokens/full phone. **SOLE enforcer**. Layer 0 |
| 36 | `_maybe_handle_thanks_farewell` | 8311 | Pure thanks/farewell → warm close, no funnel continuation | **SM** | Canned close/acknowledgement; defers inside active booking |
| 37 | `_maybe_handle_decline_engine` | 8332 | Decline / "I'll think" → warm close; clears `pending_booking` | **SM** | Close/ack + pending-booking clear; no safety guarantee (token-cost + wording control) |
| 38 | `_maybe_handle_time_change` | 8460 | Confirmed pending + new datetime → re-check slot, rewrite `pending_booking` | **SM** | Manages pending-booking state; MUST stay pre-LLM. Backend re-checks slot at commit |
| 39 | `_maybe_handle_reschedule_intent_engine` | 8647 | Reschedule entry — reuse known state, ask new time (don't re-qualify) | **SM** | Booking-state flow; MUST stay pre-LLM |
| 40 | `_maybe_handle_contact_collection` | 8966 | Deterministic phone/name (PII) capture during contact collection | **GR** | Contact capture (never lost to stochastic LLM). **Backend-enforced at commit**: `missing_name` L1029 / `missing_phone` L1032 / `invalid_phone` L1134 |
| 41 | `_maybe_request_full_contact_on_intent` | 9220 | On explicit consult request, capture inline contact + ask for the complete set | **GR** | Contact capture; eligibility-gated. **Backend-enforced at commit** (same reason codes) |
| 42 | `_maybe_commit_pending_booking_engine` | 9320 | Deterministic BOOKING COMMIT via the executor | **GR** | Booking commit (money/commitment). **Backend authoritative**: full `book_consultation` success contract (L1029–L1457) |
| 43 | `_maybe_plan_turn` | 6771 | Conversation-planner hook (SHADOW by default; authoritative only both flags ON) | **SM** | Planner hook; dormant in live |

### Bucket rosters

- **GUARDRAIL (11):** `out_of_range_age`, `political`, `underage_manager_handoff`, `sunday_school`,
  `explicit_manager_request`, `contact_correction`, `offtopic_injection`, `memory_info_reply`,
  `contact_collection`, `request_full_contact_on_intent`, `commit_pending_booking_engine`.
  - *Sole enforcers (no backend safety net → hard spine, ≈6):* `offtopic_injection`, `political`,
    `memory_info_reply`, `explicit_manager_request`, `sunday_school`, `contact_correction`.
  - *Also backend-enforced (fast-paths, ≈5):* `out_of_range_age`, `underage_manager_handoff`,
    `contact_collection`, `request_full_contact_on_intent`, `commit_pending_booking_engine`.
- **ADVISORY (18):** `final_camp_public_policy`, `camp_status`, `repeat_camp_price`,
  `multi_question`, `exact_detail`, `parent_contact_visit`, `identity`, `unclear_phrase`,
  `unknown_operational_early`, `reservation_fee_question`, `transport_logistics`,
  `camp_topic_facts`, `camp_registration_link`, `camp_stream_lifecycle`, `camp_stream_query`,
  `camp_intro`, `availability_question`, `event_inquiry`.
- **STATE/MECHANICS (14):** `reasoning_analysis`, `capture_challenge_on_goal_reply`,
  `multi_child_age`, `requalify_child`, `acknowledge_stored_state`, `adult_context_relative`,
  `static_welcome`, `human_tone_request`, `plan_turn`, `booking_datetime_reply`,
  `thanks_farewell`, `decline_engine`, `time_change`, `reschedule_intent_engine`.

### Borderline calls (stated honestly)

- **`camp_status` (#3)** and **`final_camp_public_policy` (#1)** — classed ADV. They carry a "don't
  sell a hidden/ended camp" flavour, but the actual booking block is backend-enforced
  (`camp_registration_closed`), and the spec's Layer-0/1 does not list camp-status. If counted as
  GR, the exception list becomes 12–13.
- **`requalify_child` (#6)** — classed SM; embeds a real booked-age-integrity + 2nd-child→manager
  guard with **no** backend enforcement. If counted as GR → 12. (A sub-agent read it as GR.)
- **`contact_correction` (#25)** — classed GR (contact/PII integrity, sole overwrite path); could
  be read as SM (a lead-fact capture). Kept GR because the PII-integrity stake is real and
  unbacked.
- Even at the maximum reasonable reading (≈13), the count is nowhere near ~25 → verdict unchanged.

---

## 2. T1 — Per-interceptor attribution (firing rate)

Instrument: throwaway script monkeypatch-wraps all 43 `_maybe_*` on the `parent_flow` module with
an (invoked, fired=returned-non-None) counter, then drives the **same 37-message Phase-1 set**
(`evals.phase1_report.REPRESENTATIVE_PARENT_MESSAGES` = 28 + `CORPUS_USER_TURNS` = 9) through
`evals.interception.answered_by_message`. The LLM engine is spied → **no OpenAI call**.

**Result: 1 / 37 turns reached the LLM engine.** Only **4 of 43** interceptors fired at all.

| Interceptor | Invoked | Fired (non-None) | Owned turns | Bucket |
|---|---:|---:|---:|---|
| `_maybe_static_welcome` | 25 | **24** | 24 | SM |
| `_maybe_handle_final_camp_public_policy` | 35 | **10** | 10 | ADV |
| `_maybe_handle_sunday_school` | 37 | **1** | 1 | GR |
| `_maybe_handle_offtopic_injection` | 36 | **1** | 1 | GR |
| *(engine reached)* | — | — | 1 | — |
| **all other 39 interceptors** | ≥1 | **0** | 0 | — |

- **Never invoked (dead code): none.** Every interceptor was invoked ≥1 time; 39 of 43 returned
  None on every turn of this set.
- Owner distribution: `static_welcome` 24, `final_camp_public_policy` 10, `sunday_school` 1,
  `offtopic_injection` 1, engine 1. The two top handlers own **34/37 (92%)**.

### Dead-season / fresh-turn caveat (spec-flagged) — which counts are inflated

Both dominant firing counts are **artifacts of the measurement shape, not steady-state traffic:**

1. **`_maybe_static_welcome` (24 owners) is inflated by the fresh-turn methodology.** Each of the
   37 messages is driven as a brand-new PARENT/START conversation, and the static welcome owns the
   bot's *first* reply. In a real multi-turn conversation it fires exactly once, at the start.
2. **`_maybe_handle_final_camp_public_policy` (10 owners) is inflated by the dead season.** It is
   the registration-closed / camp-status gate. As of today all 2026 camp streams have already
   started (the camp is over), so a fresh camp question short-circuits to the closed answer. **A
   week earlier most of these 10 would have reached the LLM engine** (the spec's §2.9 point: 12 of
   23 stochastic eval cases are currently captured by this same fallback).
3. **The mid-conversation guardrails read `fired = 0` here only because they are never reached.**
   On a fresh first turn, `static_welcome` or the dead-season gate short-circuits before
   `contact_collection` / `commit_pending_booking_engine` / `out_of_range_age` /
   `underage_manager_handoff` / `camp_topic_facts` / `repeat_camp_price` are even invoked (they show
   invoked=1 — the single turn that reached the engine — fired=0). **Their zero firing rate is a
   deflation artifact of the fresh-turn + dead-season set, NOT evidence they are dead weight.**

**Honest read of T1:** on real-shaped fresh traffic the interception is dominated by two handlers
that both evaporate under normal conditions (multi-turn history removes the static welcome; a live
camp removes the registration-closed gate). The 37-turn fresh set **cannot exercise** the
mid-conversation contact/booking/eligibility/advisory interceptors, so T1 tells us *which handlers
can own a fresh first turn* but understates the advisory/guardrail handlers that dominate deeper in
a conversation. A multi-turn driver (Phase 3.0-T2's rebuilt eval) is required to get real
per-interceptor firing rates for the advisory inversion targets.

---

## 3. Notes for Phase 3.1 / 3.2

- The **irreducible safety spine is ≈6** sole-enforcer guardrails (injection, political, PII,
  manager-number, Sunday-School handoff, contact-correction). These are exactly the Layer-0 items
  plus two handoff/PII commitments — small, stable, semantically motivated.
- **5 more guardrails are backend-double-enforced** (eligibility ×2, contact ×2, booking-commit).
  The executor already blocks the unsafe outcome, so even these interceptors are, in principle,
  removable without losing the guarantee — they are latency/wording fast-paths.
- **18 ADVISORY + 4 non-guardrail acknowledgement/close STATE handlers ≈ 22 inversion candidates.**
  The highest-value Phase-3.2 targets (camp topic facts, transport, price, exact-detail, stream
  facts, event inquiry, camp intro, registration link) are all ADVISORY and all currently answer
  from canned/YAML/admin data — precisely what `list_programs` / `get_program_info` /
  `get_camp_info` can ground instead.
- Method note: `answered_by`/`answered_by_message` lump all interceptor firings under the generic
  `by_handler.interceptor` bucket because interceptors don't call
  `conversation_trace.set(answered_by=...)`. This inventory's monkeypatch-wrap resolves that at the
  instrument level (no app change), giving the per-interceptor owner attribution above.
