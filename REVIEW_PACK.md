# REVIEW_PACK — AI Sales Agent (სიტყვის აკადემია)

**Read-only audit. No code modified.**
**Date:** 2026-06-01 (audit) · post-audit fixes section last refreshed 2026-06-22 (latest code work = **Live-Demo Polish batch, 2633 → 2676** — PARENT manager-number disclosure + context-aware, mid-greeting strip, anti-repeat contact-ask, price-objection≠decline, phone+name correction; 0 failed; corpus 9/9; property 28/28; CRITICAL effectively 22/22 (4 stochastic flakes pass on rerun); transcript 3/3; prompts byte-identical; YAML/event-KB/Calendar/Sheets/WhatsApp unchanged; production NOT green; new doc docs/LIVE_TEST_CHECKLIST_2026_06_22.md; prior = Consultation Flow Memory / Repeated Age Fix, 2608 → 2633; prior = Camp Stream Date Filter display fix, 2581 → 2608; prior = Camp registration/info routing live-path fixes + Manager WhatsApp manager-notification fix, 2440 → 2581; prior = Railway deploy-blockers PRE-STAGING fix (NO deploy), 2415 → 2440; prior = P0 data-integrity Google Sheets „Leads" row alignment, 2407 → 2415; prior = Saturday Scheduling Policy + P2 Sunday-wording cleanup, 2374 → 2407; prior = P1 Live Polish + date-bomb/stale-event cleanup + under-age manager-handoff dispatch, 2334 → 2374; prior = Live P0 Hotfix — BUG 1 stale-process (no code change) + BUG 2 named-event direct answer, 2322 → 2334; prior = P0 Live Demo UX Regression Batch ISSUE 1/2/3/4/5/6, 2287 → 2322; Red-Team B Self-Correction Batch B5/B2/B4/M1/B1, 2222 → 2287; Metamorphic property tests + Deploy-Readiness Audit + Railway-Safe Google Credentials, 2209 → 2222)
**Scope:** მთლიანი `ai-agent/` working tree — `app/`, `tests/`, `tools/`, root docs, `data/`.
**Author:** გარე reviewer-ისთვის. ყოველი მტკიცება file:line + verification method-ით.

---

## ⚠️ CURRENT STATUS (2026-06-24) — READ THIS FIRST (supersedes the 2026-06-23 state below)

**Authoritative status:** [`docs/CURRENT_STATUS_AND_LIVE_REGRESSION_2026_06_24.md`](docs/CURRENT_STATUS_AND_LIVE_REGRESSION_2026_06_24.md).

- **Production: NOT green. Open client test: NOT approved. Guided client test: PAUSED.**
- **Live agent behaviour regressed after/around Response Planner Hardening** — a **State Authority / Handler Priority** problem, NOT only booking (name misroute into stale underage flow, adult-event answered as camp eligibility, known child_age re-asked, camp-safety answered with consultation framing, confirmed booking dropped from general recall, mixed adult+child intent weak).
- **Do NOT say "only adult data remains" or "ready for open client test."**
- **Operator confirms Redis FLUSHALL + server restart before each live test → do NOT default to stale Redis as root cause.**
- **Done since the 2026-06-23 baseline below:** Source-of-truth prompt/sanitizer cleanup; Central Turn Intent Gateway (Phase 2); Response Planner Hardening (incl. central PII full-phone mask); WhatsApp env-mapping + test isolation (standalone smoke `sent=True`; scenario runner mocks `_send_manager_whatsapp`; new `ALLOW_LIVE_WHATSAPP` guard). Suite **2956 passed / 0 failed**, test_agent PASS, CRITICAL **22/22**, transcript **3/3** — green tests do NOT certify live behaviour.
- **NEXT TASK: "State Poisoning & Guard Regression Audit after Response Planner Hardening"** — diagnostic trace (replay transcripts; capture TurnIntent + state before/after + handler + deterministic-vs-LLM + side effects), PROVE root cause, then ONE targeted fix. No blind patching.
- **WhatsApp:** standalone works + isolation fixed, but **agent-flow WhatsApp did NOT arrive** live — trace env reload / booking-vs-handoff wiring / swallowed failure.

---

## 📍 CURRENT STATE (2026-06-23) — historical (numbers + "NEXT TASK Prompt Slimming" below are SUPERSEDED by the 2026-06-24 banner above)

**Baseline:** `pytest tests/` **2879 passed / 0 failed / 28 skipped** · corpus **9/9** · property **28/28** · `test_agent.py` ✅ · CRITICAL **22/22 clean** · transcript **3/3**. · **Production: NOT green** · **Client guided testing: pending final smoke** · **Reasoning Layer: Phase 1 implemented, gated, default OFF.**

Completed since the 2026-06-22 source-of-truth cleanup (each test-gated, 0 failed; no prompt/YAML/data/Calendar/Sheets/WhatsApp/model change):
- **Source-of-truth cleanup (Tasks 1→5A-3) — DONE:** stream dates → `get_camp_info`/visible-stream filter; Sunday-School status → `sections.yaml sunday_school`; Admin-Panel preserves Sunday-School fields; manager phone → `get_manager_phone()`; camp age band → `get_camp_age_bounds()`; post-booking facts → `get_camp_facts()`; comment rich DM → Admin-first; `camp_2026.yaml` = fallback/legacy only (not a live primary source).
- **Free-form robustness batch — DONE (2026-06-23):** Latin name capture for simple valid cases („nika 595999733"); deterministic state recall (masked phone); PARENT prompt-injection/off-topic guard. `tests/test_freeform_robustness_2026_06_23.py`.
- **Handoff/contact intent-priority blocker fix — DONE (2026-06-23):** manager-phone/self-call requests outrank contact collection; typo „მენჯერ" handled; action phrases & „კიმინდა" never stored as `lead.name`; pending handoff no longer traps later topics; canonical manager phone; **deterministic-only, NO LLM fallback**; no hardcoded manager phone in new tests. Shared validator `_is_storable_person_name`. `tests/test_handoff_intent_priority_2026_06_23.py`.
- **Reasoning Layer Phase 1 — DONE (2026-06-23):** `app/reasoning/reasoning_layer.py` + `__init__.py`; flag `USE_REASONING_LAYER` (default OFF, pinned OFF in conftest). DETERMINISTIC, metadata-only, NOT a free-form answer generator, NO LLM, no side effects, fail-closed; never overrides deterministic handlers; integrated narrowly for decline+topic-switch deferral; does NOT touch booking/Calendar/Sheets/WhatsApp/email. `docs/reference/reasoning_layer.py` is the FUTURE LLM-based vision — **reference-only, NOT imported into production**. `tests/test_reasoning_layer_2026_06_23.py`.

**NEXT TASK — Prompt Slimming / System-Prompt Cleanup:** remove hardcoded camp age „9–17" + location „ამბასადორ კაჭრეთი" duplicated in `system_parent_v2.md`; remove/dynamicise the `FORBIDDEN_PHRASE_REPLACEMENTS` fact-injection in `parent_llm_engine.py` (age :1176/1180, location :750/754) so it never injects hardcoded business facts; facts ONLY from canonical helpers/tools/config. Test-first, gated, `scenario_runner` CRITICAL gate. Other open: adult-events canonical cleanup; Sunday-School full program model / generic Admin program handler (NOT implemented — later phase); final internal smoke + guided client test; Railway staging + Meta App Review (operator).

---

## 📍 SOURCE-OF-TRUTH STATUS — Tasks 1 → 5A-3 DONE (2026-06-22)

Baseline: **2802 passed / 0 failed / 28 skipped** (2026-06-22 5A-3 snapshot; current is 2879 — see „CURRENT STATE (2026-06-23)" above), corpus 9/9, property 28/28, `test_agent.py` ✅, CRITICAL **22/22 clean (latest run)**, transcript 3/3, **Production NOT green.** Every live user-facing camp fact now flows through one canonical source: stream dates → `get_camp_info` (Task 1); Sunday-School status → `sections.yaml` (Task 2) + Admin-Panel preserve (Task 3); manager phone → `get_manager_phone()` (Task 4); camp age band (6 live readers) → `get_camp_age_bounds()` (5A-1/5A-2); post-booking facts → `get_camp_facts()` + comment DM verified admin-first (5A-3). **`parent_flow` has ZERO direct `camp_2026.yaml` reads; it is no longer a live primary source.** Open SoT: adult-events source, `price_text 5000`/`price_gel 4999` data mismatch, Sunday-School panel-UI, legacy archival (approval-gated). Open behavioural: router normalization / Latin-Georgian transliteration, negated-event recovery, PARENT→ADULT switch, prompt-injection guard. **Reasoning Layer (UPDATED 2026-06-23):** Phase 1 IMPLEMENTED — `app/reasoning/reasoning_layer.py`, flag `USE_REASONING_LAYER` default OFF, DETERMINISTIC metadata-only analyzer, no LLM, fail-closed (see „CURRENT STATE" above). `docs/reference/reasoning_layer.py` is the FUTURE LLM-based vision, reference-only. Docs: dated `SOURCE_OF_TRUTH_VERIFICATION_SWEEP_2026_06_22.md` is canonical; the non-dated duplicate is pending cleanup (deletion needs approval). Per-task detail below.

---

## Post-audit fixes — Camp-Facts Migration 5A-3 (2026-06-22, code work = 2792 → 2802)

Status: **2802 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **22/22 (clean this run)**. transcript **3/3**. ⚠️ **Production NOT green. NO prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change; camp_2026.yaml NOT deleted.**

Completes the LIVE camp_2026.yaml fact-reader cleanup. `parent_flow._facts_for_post_booking` migrated onto canonical `get_camp_facts()` (same shape, admin-first, canonical phone, streams still date-filtered). `comment_service._build_parent_rich_dm` VERIFIED already admin-first (`build_section_dm` renders from the admin section; camp_2026 only the fallback) — not refactored. Result: parent_flow has ZERO direct camp_2026 reads; no live PRIMARY camp-fact reader bypasses the canonical source (only fallbacks + legacy remain). +11 tests `tests/test_camp_facts_migration_5a3_2026_06_22.py`. The `camp_2026.yaml` direct-reader risk the audit flagged is now closed for all live paths.

---

## Post-audit fixes — Camp Age-Band Migration 5A-2 (2026-06-22, code work = 2783 → 2792)

Status: **2792 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (booking 3/3; SC-19/SC-26/SC-63 = documented objection/price flakes, all PASS on isolated rerun; the age band is unchanged at 9–17). transcript **3/3**. ⚠️ **Production NOT green. NO `.md`-prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change; camp_2026.yaml NOT deleted.**

Finishes the live age-band migration. The final 3 live readers — `parent_llm_engine._build_system_prompt` (runtime prompt context), `parent_tool_executor.book_consultation` eligibility, `parent_tool_executor.switch_to_adult_flow` age range — now use the canonical `get_camp_age_bounds()` (5A-1's helper) instead of direct `camp_2026.yaml` reads. ALL 6 live age-band readers are now canonical; only the source of `age_min`/`age_max` changed (logic/wording unchanged; default 9–17 byte-identical). +11 tests `tests/test_camp_age_bounds_migration_5a2_2026_06_22.py`. Remaining camp_2026 reads = the get_camp_info/get_camp_facts fallbacks + 5A-3 items (`_facts_for_post_booking`, comment rich DM) + legacy.

---

## Post-audit fixes — Camp Age-Band Migration 5A-1 (2026-06-22, code work = 2769 → 2783)

Status: **2783 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (SC-11/SC-13/SC-19 = documented flakes, all PASS on isolated rerun; the age band is unchanged at 9–17). transcript **3/3**. ⚠️ **Production NOT green. NO prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change; camp_2026.yaml NOT deleted/archived.**

First sub-task of the camp_2026.yaml-reader migration. The 5A inventory found 6 LIVE age-band readers reading `camp_2026.yaml` directly (bypassing canonical `get_camp_facts()`), so an operator age-range edit reached the `get_camp_info` tool but not eligibility/under-age/prompt. New canonical `admin_config_service.get_camp_age_bounds()` (reads only via `get_camp_facts()`; safe 9/17 default). Migrated the FIRST 3 (≤3-per-task rule): `parent_flow._age_status_for_lead`, `parent_flow._camp_age_bounds`, `parent_llm_engine._age_status`. Behaviour byte-identical today (band still 9–17). 5A-2/5A-3 will migrate the prompt band, booking eligibility, adult-switch, post-booking facts. +14 tests `tests/test_camp_age_bounds_migration_2026_06_22.py`.

---

## Post-audit fixes — Manager-Phone Source-of-Truth Unification (2026-06-22, code work = 2761 → 2769)

Status: **2769 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (SC-13 Slot-Change + SC-19 Screen-Concern + SC-26 Will-Think = documented flakes, all PASS on isolated rerun; the phone change touches none of them). transcript **3/3**. ⚠️ **Production NOT green. `admin_config_service` only — no prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model / DM-flow change.**

The audit's two manager-phone chains: `get_manager_phone()` (canonical — used by the PARENT/under-age/ADULT disclosure paths already) vs `get_camp_facts()['phone']` (the LLM's camp-info phone, sourced from the camp section's `manager_contact`/camp_2026.yaml). Both returned `558 67 47 33` but were independent. Fix: `get_camp_facts()` now sets `phone` from `get_manager_phone()` first (section contact / legacy camp phone are fallbacks only). One config edit now reaches every flow; the LLM's camp-info phone can no longer diverge from the deterministic disclosure. No live-prompt hardcode (`system_parent_v2.md` clean; legacy `system_parent.md:9` + dead `error.yaml` untouched). +8 tests in `tests/test_manager_phone_unification_2026_06_22.py`.

---

## Post-audit fixes — Admin-Panel Sunday-School Field Preservation (2026-06-22, code work = 2753 → 2761)

Status: **2761 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (SC-12 Slot-Busy + SC-25 Hard-Decline = documented flakes, both PASS on isolated rerun; this admin-route change is off the DM path). transcript **3/3**. ⚠️ **Production NOT green. Admin route only — no prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model / DM-flow change.**

Protection fix for Task 2: the Admin-Panel section form does not surface the new `sunday_school` config fields (`availability_text`/`details_text`/`handoff_enabled`/`lead_type`), so a metadata save via `POST /admin/programs/{id}` would have dropped them (it preserved only a 4-key whitelist). Fix: `admin.save_program` now preserves EVERY existing non-form field (generalised whitelist), EXCLUDING the form-managed list fields `streams`/`included_items`/`discounts` (so clear-on-empty + the stale-2150 guard hold); `price_gel`/`price_text` are always form-driven. `update_section` already deep-merged. No new panel UI (preservation over UI expansion). +8 end-to-end TestClient tests in `tests/test_admin_sunday_school_preservation_2026_06_22.py`.

---

## Post-audit fixes — Sunday-School Status → Admin Config (2026-06-22, code work = 2746 → 2753)

Status: **2753 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (SC-13 Slot-Change = documented flake, PASS on isolated rerun; the sunday_school config touches no slot logic). transcript **3/3**. ⚠️ **Production NOT green.** **No prompt / Calendar / Sheets-schema / WhatsApp / model change; YAML changed = ONLY the `sunday_school` section.**

Second Source-of-Truth cleanup. The Sunday-School launch month („ივლისში დაემატება") was hardcoded in `parent_flow._SUNDAY_SCHOOL_ANSWER` (drift risk). Moved to Admin Config: `sections.yaml` `sunday_school` gained `availability_text`/`details_text`/`handoff_enabled`/`lead_type`; new `admin_config_service.get_sunday_school_status()`; `_SUNDAY_SCHOOL_ANSWER` removed → `_render_sunday_school_answer()` builds the answer from config (safe no-date fallback on missing config; `handoff_enabled=false` → status only). Email-only handoff / SundaySchoolLeads tab / no-Calendar / no-WhatsApp / email-success-gate unchanged. +7 tests in `tests/test_sunday_school_handoff_2026_06_22.py`. (Admin PANEL form does not yet expose the new fields — YAML/`update_section`-editable now; panel exposure is a future enhancement.)

---

## Post-audit fixes — Stream-Date Prompt Cleanup (2026-06-22, code work = 2738 → 2746)

Status: **2746 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (SC-12 Exact-Slot-Busy + SC-63 Price-Manipulation are the documented real-model flakes — both PASS on isolated rerun; the stream-date change touches neither). transcript **3/3**. ⚠️ **Production NOT green.** **⚠️ FIRST PROMPT CHANGE in many batches** — and ONLY `system_parent_v2.md` + a new test changed; **no code / YAML / data / Calendar / Sheets / WhatsApp / model change.**

The one confirmed live fact-drift from the Source-of-Truth audit: `system_parent_v2.md:293` HARDCODED the three camp stream dates, which the live model could emit from prompt memory, bypassing `sections.yaml` AND the date-filter. Fix: replaced the literal-date line with a no-hardcode rule (stream dates ONLY from `get_camp_info` → visible-stream filter; never invent). Consultation-vs-stream teaching preserved; line 288's `<streams>` placeholder was already canonical. RED-first regression test new `tests/test_prompt_no_hardcoded_stream_dates_2026_06_22.py` (+8). Verified against `docs/SOURCE_OF_TRUTH_AUDIT_2026_06_22.md` + `docs/SOURCE_OF_TRUTH_VERIFICATION_SWEEP_2026_06_22.md` (line-293 = `SAFE_WITH_TEST`). Legacy `system_parent.md:6` literals remain (fallback-only, out of scope).

---

## Post-audit fixes — Sunday-School Manager Handoff + False-Success fix (2026-06-22, code work = 2704 → 2738)

Status: **2738 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (SC-13 Slot-Change is the documented real-model flake — PASS on isolated rerun; a 429 rate-limit also hit mid full-run). transcript **3/3**. ⚠️ **Production NOT green.** No deploy / live tick / real sends in tests. **No prompt / YAML / data / Calendar-internals / Sheets-booking-A-Q-schema / WhatsApp-send-logic / model change.**

Live bug: a Sunday-school enquirer who left name+phone was told „მენეჯერს გადავცემ" but **no manager notification dispatched**. Two root causes, both fixed deterministically:
- **No deterministic Sunday-school handoff** — „საკვირაო სკოლა" had no in-conversation handler; the LLM only *promised* the handoff (never called `request_manager_callback`). Fix: new `parent_flow._maybe_handle_sunday_school` (wired FIRST in `handle`, before the static welcome) → deterministic „ივლისში დაემატება" answer (no invented facts) + name/phone collection → `notification_service.notify_sunday_school_handoff` (EMAIL ONLY, no Calendar, no WhatsApp) → confirms „გადავეცი" ONLY on a real email send, else a safe failure message. Idempotent; returns None for all non-Sunday-school messages.
- **False-success in `_request_manager_callback`** — it ignored the dispatch result and always returned `success=True`. Fix: gate success on the real send; on failure return `{"success": False, "reason": "dispatch_failed"}` and don't mark notified. `send_manager_notification` is now **email-gated** (`notify_manager` refactored into `_dispatch_manager_channels`; `notify_manager`'s `email AND whatsapp` return contract preserved; WhatsApp still sent identically). Separate **`SundaySchoolLeads`** Sheets tab (`sheets_service.log_sunday_school_lead`) is best-effort and never touches the booking A-Q schema. SMTP itself verified working via a controlled test email.
- **Tests** — new [tests/test_sunday_school_handoff_2026_06_22.py](tests/test_sunday_school_handoff_2026_06_22.py) (+34, incl. adversarial-review hardening: intent requires „საკვირაო"+„სკოლ"; mid-collection camp/price/question pivot defers + never captures a topic word as the name; email-failure retry; callback writes CRM lead only on confirmed dispatch). A multi-agent adversarial review found the constraint/isolation dimension CLEAN and 4 real logic/regression issues — all fixed + test-gated before close. Earlier same-day: Under-age Handoff Name + Manager-Number fix (2676 → 2704), [tests/test_underage_handoff_name_and_manager_number_2026_06_22.py](tests/test_underage_handoff_name_and_manager_number_2026_06_22.py) (+28 — „კი მომწერე"/„მენეჯერის ნომერი მომწერე" no longer mis-captured / re-asked).

---

## Post-audit fixes — Live-Demo Polish batch (2026-06-21/22, code work = 2633 → 2676)

Status: **2676 passed, 28 skipped, 0 failed**. corpus **9/9**. property **28/28**. `test_agent.py` ✅. CRITICAL **effectively 22/22** (one full run 18/22; SC-26/SC-46/SC-63/SC-66 all real-model stochastic, passed on isolated rerun). transcript **3/3**. ⚠️ **Production NOT green** (gated by Meta App Review + Railway staging + live smoke). No deploy / live tick / real sends. **No prompt / YAML / event-KB / Calendar-schema / Sheets-schema / WhatsApp / follow-up change.**

Six narrow deterministic fixes from a live PARENT/camp transcript (all in `app/flows/parent_flow.py` unless noted):
- **Manager-number disclosure** — `_maybe_handle_explicit_manager_request` (pre-engine, after underage-handoff, before contact-collection): `მენეჯერ`+`ნომერ/ტელეფონ/კონტაქტ`+no-own-phone → `get_manager_phone()` (558 67 47 33) + callback. PARENT had no disclosure path before (ADULT did).
- **Context-aware** — `_render_manager_number_answer(lead)`: phone known → no re-ask; unknown → offer callback.
- **Mid-conversation greeting strip** — `parent_llm_engine._strip_mid_conversation_greeting` (after `_suppress_redundant_age_question` in `run_parent_llm_turn`): strips a leading „გამარჯობა/სალამი/მოგესალმებით" once an assistant turn exists.
- **Anti-repeat contact-ask** — `_maybe_request_full_contact_on_intent` returns `_CONTACT_REQUEST_*_RETRY` (varied, example-bearing) when the same ask was sent last turn (`_bot_last_reply_asked_for_contact`). WHAT is asked unchanged.
- **Price-objection ≠ decline** — `_maybe_handle_decline_engine` defers to engine when a decline phrase co-occurs with `_DECLINE_OVERRIDE_INTEREST = (მაგრამ, თუმცა, მაინც, ძვირ, მიჭირს)`; real declines (no contrast) still cold-close.
- **Phone + name correction** — `_maybe_handle_contact_correction` (pre-engine): overwrites `lead.phone` (markers `შევცდი/ეს არა/სხვა ნომერ/სწორი ნომერ/სწორია/არასწორ` + last valid phone) or `lead.name` (`კი არა/შევცდი/სახელი არ/არასწორ`/leading „არა" + last valid Georgian name token). In-memory only; committed booking → ack only, no Calendar/Sheets write. AGE correction untouched.

Tests: [tests/test_manager_number_and_greeting_2026_06_21.py](tests/test_manager_number_and_greeting_2026_06_21.py) (+19), [tests/test_objection_and_corrections_2026_06_22.py](tests/test_objection_and_corrections_2026_06_22.py) (+22). Operator checklist: [docs/LIVE_TEST_CHECKLIST_2026_06_22.md](docs/LIVE_TEST_CHECKLIST_2026_06_22.md).

**Known weakest spots still LLM-only (NEXT TASK to harden, operator-deferred):** off-topic deflection („მუფასა ვინ არის") has NO deterministic guard; Georgian-only / English-leak is prompt-enforced only. Hard-guarded already: mid-greeting, fake-booking (tool-success gated), age re-ask, registration link.

---

## Post-audit fixes — Consultation Flow Memory / Repeated Age Fix (2026-06-20, code work = 2608 → 2633)

Status: **2633 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **21/22 stable + SC-63 stochastic → effectively 22/22** (SC-63 Price Manipulation isolated reruns = PASS / FAIL / PASS; no pricing code touched). transcript **3/3**. ⚠️ **Production is NOT green** — live smoke for this fix pending. No deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta. **No prompt / event-data / Calendar-schema / Sheets-schema / WhatsApp-notification-logic / booking / `.env` / model change.**

- **Live bug.** A parent gave the child age + phone in one message — „14 წლის არის 595999733" — and the agent stored the phone but kept asking „რამდენი წლისაა თქვენი შვილი?" turn after turn.
- **Root cause — extraction (+ turn order), NOT a state-key mismatch.** `parent_llm_engine.maybe_capture_child_age_fallback` bailed on any `_PHONE_HINT_TOKENS` prefix (`595`/`598`/`599`…), so a message containing „595…" never captured the age; `child_age` stayed empty and the LLM (correctly, per its prompt) re-asked for the missing fact. Capture also ran POST-turn. `lead.child_age` / `lead.phone` are the single canonical fields, exposed to the model in `_build_context_message`.
- **Fix** (all in [app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py)): (1) `_strip_phone_numbers()` removes recognised Georgian phones BEFORE age parsing (reuses `parent_flow.PHONE_CANDIDATE_PATTERN`/`VALID_LOCAL_PREFIXES`; fallback strips 7+ digit runs) — age + phone now extract from the SAME message; (2) `maybe_capture_phone_fallback()` captures exactly one valid 9-digit phone (no-op on 0/2+, never overwrites, never touches `child_age`); (3) `_capture_turn_facts()` runs PRE-turn at the top of `run_parent_llm_turn` before the context is built; (4) `_suppress_redundant_age_question()` replaces a „რამდენი წლის"/„რა ასაკის" question with the next missing detail (phone, else day/time) once `child_age` is known. Pre-booking age correction („არა, 15 წლისაა" → 15) preserved.
- **No prompt change** — `system_parent_v2.md` already forbids re-asking known facts (lines 231/289/307); the bug was purely capture/timing. **No phrase hack.**
- **Confirmed**: „14 წლის არის 595999733" → child_age=14 + phone=595999733; combined/typo/Georgian-numeral variants; phone never erases age and vice-versa; two phones not guessed; no age re-ask on later turns; booking proceeds when age+phone+slot+confirmation known.
- **Preserved**: underage handoff · Saturday/Sunday scheduling · Sheets A–Q · WhatsApp manager notifications · camp registration link · camp info · camp stream date filter · event/KB data · Calendar/Sheets schema · prompts. No live integrations touched.
- **Tests** — new [tests/test_consultation_age_memory_2026_06_20.py](tests/test_consultation_age_memory_2026_06_20.py) (+25, through `parent_flow.handle`/`process_message`, engine ON, mocked OpenAI). Note: `data/admin_config/templates.yaml` mtime was bumped by the scenario runner's admin write-path but is byte-identical to its `.bak` — no content change; `sections.yaml`/`camp_2026.yaml` untouched.

---

## Post-audit fixes — Camp Stream Date Filter Fix (2026-06-20, code work = 2581 → 2608)

Status: **2608 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **22/22**. transcript **3/3**. ⚠️ **Production is NOT green.** No deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta. **No prompt / event-data / Calendar-schema / Sheets-schema / WhatsApp-notification-logic / booking / `.env` / model change.**

- **Business rule.** A camp stream is hidden from users once its Asia/Tbilisi start date arrives, even while still `active` in Admin/config. `active AND today < start_date` → visible; `active AND today >= start_date` → hidden (hidden ON the start day); `inactive` → hidden regardless of date; empty `dates_text` → visible; non-empty-unparseable → hidden (+ warning). Streams are **NOT** deleted/mutated — display/eligibility filter only.
- **Current streams.** I ნაკადი `23-29 ივნისი` → hidden from Jun 23 · II ნაკადი `5-11 ივლისი` → hidden from Jul 5 · III ნაკადი `14-20 ივლისი` → hidden from Jul 14. Jun 20/22 all visible; Jul 14 all hidden → agent does NOT invent dates (empty tool list / legacy manager fallback).
- **Timezone basis.** Existing `now_tbilisi` / `admin_config_service._now_tbilisi` helper (Asia/Tbilisi) — the same seam the sibling adult-event date filter uses. Year resolved from explicit 4-digit year → camp `year` (2026) → current Tbilisi year.
- **New helpers** — [app/services/admin_config_service.py](app/services/admin_config_service.py): `_parse_camp_stream_start_date()` (≈:1126), `is_camp_stream_visible()` (≈:1167), `get_visible_camp_streams()` (≈:1202). `get_camp_facts()` left RAW (data source).
- **Affected surfaces** (all route through `get_visible_camp_streams`): `admin_config_service` visible-stream helper; `parent_tool_executor._get_camp_info` (tool topics `dates`+`all`); `parent_reply_composer._format_knowledge_block`; `parent_turn_router._build_premium_dates_answer` (empty→manager fallback); `parent_turn_analyzer._format_knowledge_summary`; `parent_flow._facts_for_post_booking`; `comment_service` rich-DM; `admin_config_service.render_section_dm` (camp-type sections only).
- **Isolation.** Booking/Calendar/Sheets unchanged; WhatsApp notification logic unchanged; registration-link behaviour unchanged; camp-info behaviour unchanged; price/program/age answers unchanged; event/KB data unchanged; prompt files unchanged. A dedicated test asserts the filter path never reaches Calendar/Sheets/Messenger/notification code.
- **Static-copy note (future cleanup, NOT a live blocker).** `parent/price.yaml::info_first_response` still hard-codes the three stream dates; reachable only via the legacy/dead `PARENT_INFO_FIRST_RESPONSE` alias (not served by the live engine or any filtered dynamic surface), so not a live leak. Left unchanged; re-check if that template is ever wired live again.
- **Tests** — new [tests/test_camp_stream_date_filter_2026_06_20.py](tests/test_camp_stream_date_filter_2026_06_20.py) (+27, all date-frozen). The filter is a no-op at today's real date 2026-06-20 (all three streams still future), so the prior 2581 are unchanged.

---

## Post-audit fixes — Camp registration/info routing live-path + Manager WhatsApp (2026-06-18→20, code work = 2440 → 2581)

Status: **2581 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **22/22 clean**. transcript **3/3**. ⚠️ **Production is NOT green.** No deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta. **No prompt / event-data / Calendar-schema / Sheets-schema / WhatsApp-notification-logic / `.env` / model change.**

- **Camp registration LIVE-PATH fix (2026-06-19):** `parent_flow._maybe_handle_camp_registration_link` (wired in `handle()` after `_maybe_handle_event_inquiry`, before the engine) returns the Admin `registration_url` DETERMINISTICALLY for a clear camp registration/link/form/sign-up request — pre-engine, no age question, no menu, link from `admin_config_service.get_camp_facts()` (missing → safe manager/contact fallback, never invented). Prior tests passed while live failed because they STUBBED the engine; new tests run the REAL `process_message` path with an engine SPY proving the LLM is never consulted. Files: [app/flows/parent_flow.py](app/flows/parent_flow.py); tests [tests/test_live_camp_registration_link_2026_06_19.py](tests/test_live_camp_registration_link_2026_06_19.py).
- **Camp INFO over-fire fix (2026-06-20):** a general camp INFORMATION request wrongly returned the registration link — root cause: raw-substring marker `„ფორმა"` matched inside `„ინ-ფორმა-ცია"` (information). Fixed with a word-boundary regex `_CAMP_FORM_TOKEN_RE = re.compile(r"(?<![ა-ჰ])ფორმ(?!ატ)")` (standalone form token; never inside „ინფორმაცია"/„ფორმატი"). Same foot-gun fixed in `conversation_service._is_registration_link_request` (UNCLEAR helper) + `„ჩაწერ"`→`„ჩაწერა"` (no „ჩაწერილი"/already-enrolled match) + `import re`. Files: [app/flows/parent_flow.py](app/flows/parent_flow.py), [app/services/conversation_service.py](app/services/conversation_service.py); tests [tests/test_camp_info_vs_registration_2026_06_20.py](tests/test_camp_info_vs_registration_2026_06_20.py).
- **Security/logging (2026-06-19):** `messenger_service.get_user_profile` masks `access_token` in error logs (`_mask_access_token`); profile-fetch failure non-blocking.
- **Manager WhatsApp manager-notification fix (2026-06-18):** alias-aware `settings.get_whatsapp_access_token()` / `get_manager_whatsapp_number()` (E.164-normalised) / `is_whatsapp_configured()`; WhatsApp attempted in parallel with email for booking + handoff (non-blocking, email-independent); conftest `_block_real_meta_http` blocks real outbound Meta/WhatsApp HTTP in tests. Files: `app/config.py`, `app/services/notification_service.py`, `app/services/messenger_service.py`; tests `tests/test_manager_whatsapp_notification_2026_06_18.py`.
- **Live smoke (operator):** „გამარჯობა ბანაკის შესახებ ინფორმაცია რომ მომწერო" → camp info, NO link; „გამარჯობა ბანაკზე როგორ დავრეგისტრირდე?" → registration link `https://tinyurl.com/36jcae8z`.
- **Known blockers:** (1) consultation memory / repeated child-age bug („14 წლის არის 595999733" → keeps re-asking age) — needs slot-extraction + anti-repeat fix; (2) **camp stream date filter** (NEXT TASK) — hide I/II/III streams once their start date arrives (23 ივნ / 5 ივლ / 14 ივლ); (3) Railway staging deploy not done; (4) follow-up staging test not done; (5) Meta App Review open; (6) production NOT green.
- **NEXT TASK:** Camp Stream Date Filter Fix.

---

## Post-audit fixes — Railway deploy-blockers PRE-STAGING fix (2026-06-18, NO deploy, code work = 2415 → 2440)

Status: **2440 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **21/22 on one full run; effectively 22/22** — SC-63 (Price Manipulation, `difficult`) is real-model **stochastic** (isolated re-run PASS/FAIL/PASS); config-loading cannot affect agent behaviour. transcript **3/3**. ⚠️ **Production is NOT green.** Offline / pre-deploy: no deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta. **No prompt / event-data / agent-logic / booking / Calendar / Sheets-schema / Meta-webhook / broadcast / follow-up-scheduler / `.env` / model change.**

- **STEP 0 secrets:** No git repo exists → nothing tracked → **no tracked secret files, no STOP**. Created [.gitignore](.gitignore) + [.railwayignore](.railwayignore) (cover `.env`, `.env.*` with `!.env.example`, `credentials.json`, `*credentials*.json`, `*service-account*.json`, `*secret*.json`, `*token*.json`, `*.key`, `*.pem`, `keys/`, `secrets/`, caches). On-disk secrets (names only): `.env`, `credentials.json` (now ignored); `.env.example` stays tracked.
- **Root cause (Railway boot crash):** [app/config.py](app/config.py) `_env` read ONLY `ENV_VALUES = dotenv_values(.env)` (≈:14, :31-33) → Railway has no `.env` and injects vars into `os.environ` → every value empty → `Settings.from_env()` raised → boot crash.
- **Fix:** [app/config.py](app/config.py) `_env` now reads `os.environ` FIRST, `.env` fallback second (≈:31-50; added `import os`). No secret logging; local behaviour preserved (`load_dotenv` still loads `.env` into `os.environ`). Fixes `REDIS_URL` (`.env` fallback preserved; missing = safe no-op) and `LIVE_BROADCAST_ENABLED` env reads at once.
- **GOOGLE_CREDENTIALS_JSON** already Railway-safe ([app/services/google_credentials.py](app/services/google_credentials.py) reads `os.environ` directly) — preserved, local file fallback preserved, NOT changed.
- **[requirements.txt](requirements.txt)** += `redis`, `tzdata`, `python-multipart`. **Procfile** already safe (`web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`) + **runtime.txt** `python-3.11` — unchanged.
- **Tests:** new [tests/test_railway_env_loading_2026_06_18.py](tests/test_railway_env_loading_2026_06_18.py) (+25, offline) — env precedence, REDIS_URL, creds, LIVE_BROADCAST_ENABLED, deps, ignore-file coverage, no-secret-logging, WhatsApp + follow-up readiness. No existing test changed.
- **WhatsApp readiness (audit only, no send):** email-only / WhatsApp unconfigured; `_send_manager_whatsapp` short-circuits to False; `notify_manager_handoff` succeeds on email alone. Auto WhatsApp needs Cloud API env (`WHATSAPP_TOKEN`/`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `MANAGER_WHATSAPP_NUMBER`/`MANAGER_WHATSAPP`); Twilio alt identified, unconfigured; manager fallback phone ≠ automatic WhatsApp send.
- **Follow-up readiness (audit only, no send):** test after staging deploy with Redis attached; `REDIS_URL` now Railway-supported; in-memory fallback exists but not production-reliable; single replica / one uvicorn worker / always-on required to avoid duplicate APScheduler sends ([app/main.py](app/main.py) startup ≈:70-84). Scheduler logic unchanged.
- **DEFERRED (operator, unchanged):** booked-age overwrite; Formula/fromula parsing; Formula/fromula active-event data cleanup. Meta App Review still open.
- **NEXT TASK:** Railway **STAGING deploy ONLY** — create service, attach Redis, set dashboard env vars, `LIVE_BROADCAST_ENABLED=false`, `GOOGLE_CREDENTIALS_JSON`, Procfile start command, single replica / one worker, deploy to staging, health+smoke; do NOT connect client FB/IG; do NOT mark production green.

---

## Post-audit fixes — P0 data-integrity: Google Sheets „Leads" row alignment (2026-06-18, code work = 2407 → 2415)

Status: **2415 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **22/22 clean**. transcript **3/3**. ⚠️ **Production is NOT green.** **No prompt edit**; **event data `sections.yaml` unchanged** (`8cfe06c8…`); **Sheets schema unchanged** (`HEADERS` still 17 cols A–Q); Calendar event schema unchanged; no broadcast / follow-up scheduler / Meta webhook / OpenAI model / `.env` change.

- **Symptom (operator):** during a NORMAL consultation booking the „Leads" row was written under the WRONG / shifted columns — values landed right of the headers; older rows aligned, the new booking row did not (seen during a Saturday booking test). NOT the under-age manager handoff (that path emails the operator and never writes Sheets).
- **Root cause (cause I — unbounded append range):** [app/services/sheets_service.py](app/services/sheets_service.py) `save_lead` appended via `worksheet.append_row(row, value_input_option="USER_ENTERED")` with no `table_range`. Verified against gspread 6.2.1: that sends the Sheets `values.append` API the UNBOUNDED range `'Leads'` (`absolute_range_name("Leads", None)` → `'Leads'`), so Google's logical-table auto-detection chooses both the target row AND the start column — anchoring to the detected table's first column (right of A) on a non-A-anchored sheet. Aggravated by cause J (live sheet already shifted). `_lead_to_row` was already correct (17 values, ID first, header order A–Q → rules out B/C/G); the per-cell `update_lead` upsert was already A-correct via `COLUMN_INDEX`.
- **Fix (smallest change):** [app/services/sheets_service.py](app/services/sheets_service.py) new `_leads_last_col_a1()` + `_append_lead_row_aligned()` (≈:164-216); `save_lead` now writes `worksheet.update(range_name=f"A{n}:Q{n}", values=[row], value_input_option="USER_ENTERED")` (`n = len(get_all_values())+1`) — an explicit A-anchored full-row range, immune to table-detection. Same deterministic pattern as `_ensure_headers` / the events tab. `USER_ENTERED` preserves cell parsing (numeric ID, TRUE/FALSE, Tbilisi datetimes). Saturday & weekday bookings share this one aligned path; under-age handoff still writes no Sheets.
- **Tests:** new [tests/test_sheets_leads_alignment_2026_06_18.py](tests/test_sheets_leads_alignment_2026_06_18.py) (+8, fully mocked `FakeWorksheet`): row-builder header order, A-anchored `A2:Q2` append (no `append_row`), append-after-existing-rows (`A4:Q4`), Saturday booking aligned, weekday booking aligned, Sat==weekday range, `update_lead` correct row+columns (Status=N=14, Name=E=5), under-age handoff dispatches + no Sheets. Failing-first → fixed; no existing test changed.
- **Manual live cleanup needed (operator — NO live edits made):** delete/correct the misaligned live test row(s) — especially the latest row 19 / Saturday-test row; correct only genuinely shifted rows; keep A–Q headers unchanged; clear stray data in columns R+ on affected rows; re-test one live booking to confirm A–Q alignment.
- **Note (not changed):** `Lead.to_sheet_row()` omits the ID column but is dead for writes (only tests inspect its `[6]` challenge index); production uses `_lead_to_row`. Comment/events-tab appends share the `append_row` pattern but were left untouched (broadcast/Meta-webhook off-limits).
- **DEFERRED (operator, unchanged):** booked-age overwrite edge case; Formula/fromula parsing; Formula/fromula active-event data cleanup. Do NOT touch unless explicitly requested.
- **NEXT TASK:** Railway deploy blockers (`config._env` os.environ-first + `.env` fallback, `REDIS_URL`, missing runtime deps `redis`/`tzdata`/`python-multipart`, `.gitignore`/`.railwayignore` for secrets, Railway-safe `Procfile`/start command, single-worker always-on, `LIVE_BROADCAST_ENABLED=false` for staging, Meta App Review still open).

---

## Post-audit fixes — Saturday Scheduling Policy + P2 Sunday-wording cleanup (2026-06-16, code work = 2374 → 2407)

Status: **2407 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **22/22 clean** (no flake this run; the known PARENT booking/slot/screen stochasticity passes on re-run). transcript **3/3**. ⚠️ **Production is NOT green.** **No prompt edit** (no `app/agent/prompts/*.md` or `policies/*.md` touched); **event data `sections.yaml` unchanged** (`8cfe06c8…`); **`business_hours.yaml` + mirror unchanged**; no Calendar event schema / Sheets schema / broadcast / follow-up scheduler / Meta webhook / OpenAI model / `.env` change. Two sessions, recorded together:

- **Saturday scheduling policy — consultation bookings now allowed Mon–Sat; Sunday stays closed.** The old block was the WHOLE weekend (`weekday() >= 5`); now centralised in [app/services/calendar_service.py](app/services/calendar_service.py) `is_closed_booking_day(day)` + `CLOSED_WEEKDAYS = frozenset({6})` (≈:48-58; `6 == Sunday`). Rewired to the helper (logic-equivalent): `get_available_slots` (≈:80), `_get_free_slots_for_day` (≈:171), `is_within_business_hours` (≈:249 — still returns `(False, "weekend")` for Sunday), plus [app/agent/tools/parent_tool_executor.py](app/agent/tools/parent_tool_executor.py) `_book_consultation` pre-check (≈:955) and reschedule pre-check (≈:1688). **PRESERVED:** working hours (10:00–21:00, 60-min, last start 20:00), timezone (Asia/Tbilisi — day judged in Tbilisi not UTC), FreeBusy filtering, booking-conflict checks, Calendar event schema, Sheets schema. Verification: new [tests/test_saturday_scheduling_policy_2026_06_16.py](tests/test_saturday_scheduling_policy_2026_06_16.py) (32 — Sat allowed / Sun blocked + no Calendar query / weekday unchanged / Sat working-hours boundaries / TZ (UTC-instant + naive) / slot generation / FreeBusy / end-to-end executor booking) + updated `test_booking_availability_patch.py` (`test_saturday_now_allowed` + `test_sunday_still_rejected`) + `test_parent_llm_engine.py` (Sat allowed + Sun blocked).
- **P2 Sunday-wording cleanup (wording only — no logic, no prompt).** (1) User-facing Georgian — [app/flows/parent_flow.py](app/flows/parent_flow.py) `_format_repaired_slot_response` `weekend` branch (≈:1116-1119): „ამ დღეს (შაბათ-კვირას) კონსულტაციები არ ინიშნება…" → **„კვირას კონსულტაციები არ ინიშნება. შემიძლია სხვა დღეებში თავისუფალი დროები შემოგთავაზოთ."** (2) Internal LLM hint — [app/agent/tools/parent_tool_executor.py](app/agent/tools/parent_tool_executor.py) `outside_business_hours` result `business_hours` field (≈:972): **`(Mon-Fri, Asia/Tbilisi)` → `(Mon-Sat, Asia/Tbilisi)`**. The internal `"weekend"` reason string is unchanged (Sunday only). Verification: +2 wording tests in the new file + updated `test_parent_reschedule_state_and_time.py`. Left untouched on purpose: the `_WEEKEND_WORDS` input-detector and the `Mon-Fri` date-picker comment in `tools/manual_simulation_p3c_exact_slot_availability.py`.
- **DEFERRED (operator, unchanged):** booked-age overwrite edge case; Formula/fromula parsing; Formula/fromula active-event data cleanup. Do NOT touch unless explicitly requested.
- **NEXT TASK:** Railway deploy blockers (`config._env` os.environ-first, `REDIS_URL`, missing runtime deps `redis`/`tzdata`/`python-multipart`, `.gitignore`/`.railwayignore` for secrets, single-worker always-on, `LIVE_BROADCAST_ENABLED=false` for staging, Meta App Review still open).

---

## Post-audit fixes — P1 Live Polish + Date-bomb cleanup + Under-age handoff dispatch (2026-06-15/16, code work = 2334 → 2374)

Status: **2374 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **22/22**. transcript **3/3**. ⚠️ **Production is NOT green.** **No prompt edit** (combined prompt SHA-256 `bde41090…` unchanged); **event data `sections.yaml` unchanged** (`8cfe06c8…`); no Calendar internals / Sheets schema / broadcast / follow-up scheduler / Meta webhook / OpenAI model / `.env` change. Three sessions, recorded together:

- **BUG A — under-age manager handoff now ACTUALLY notifies the operator.** New `notification_service.notify_manager_handoff(lead, reason)` (message-only; reuses the existing `_send_email` + `_send_manager_whatsapp` transports; returns True only if AT LEAST ONE channel dispatched). Wired in `parent_flow._maybe_handle_underage_manager_handoff` (engine path, before contact-collection). NO Sheets/Calendar write. Success message only on real dispatch; on failure → manager direct contact (`558 67 47 33` via `admin_config_service.get_manager_phone()`) or a retry message. Idempotent.
- **BUG B — past/unknown NAMED events resolve BEFORE the self/child target question.** ADULT engine `_maybe_handle_named_adult_event` gained PAST (`უკვე გაიმართა` + active list) and NOT-FOUND (`ვერ მოვძებნე` + active list + manager-verify) branches, gated by `_has_genuine_event_name_token` (excludes generic/target/descriptor tokens incl. „ასევე") + a subscription-defer guard. New `admin_config_service.find_events_by_reference(message, include_past=…)`. PARENT camp-context interceptor `parent_flow._maybe_handle_event_inquiry` gained a named-event firing condition (C) + a PAST branch (`_render_past_event_inquiry`) so „ასევე მაინტერესებს გია მურღულიას ღონისძიება…" resolves first-try even after camp/under-age context. Generic „ღონისძიება მაინტერესებს" still defers to the engine.
- **BUG C / wording — „მოგიწოდებთ" → „გთხოვთ"** in BOTH `parent_llm_engine.FORBIDDEN_PHRASE_REPLACEMENTS` and `adult_llm_engine.ADULT_FORBIDDEN_PHRASE_REPLACEMENTS`; handoff/event answers paragraph-broken (`parent_flow._format_handoff_paragraphs`).
- **P1 polish — manager-handoff contact collection** (booking style): name+phone together when name unknown; phone-only ask when name known; ask the missing field on partial input; never claim „სახელი და ნომერი გადავეცი" unless both present (generic success „ინფორმაცია მენეჯერს გადავეცი").
- **Date-bomb / stale-event cleanup (tests/scenarios only):** active-event direct-answer tests use a SYNTHETIC active fixture (a real event would become the next date-bomb on expiry); Gia past behavior tested separately; SC-TX-03 U5 → past wording; `test_live_qa_bug_fix` slot + `test_parent_reschedule_state_and_time` date assertions made clock-relative; conftest `_block_real_smtp` net added so no test can open a real SMTP connection.
- **DEFERRED (operator):** booked-age overwrite edge case; Formula/fromula parsing; Formula/fromula active-event data cleanup. Do NOT touch unless explicitly requested.
- **NEXT TASK:** ~~Saturday consultation-booking scheduling policy~~ → **DONE (2026-06-16)** — see the top „Saturday Scheduling Policy + P2 Sunday-wording cleanup" section. The next task is now **Railway deploy blockers**.

---

## Post-audit fixes — Live P0 Hotfix (BUG 1 + BUG 2) (2026-06-14, code work = 2322 → 2334)

Status: **2334 passed, 28 skipped, 0 failed** (`pytest tests/ -q`; was 2322 → +12 new in [tests/test_p0_live_hotfix.py](tests/test_p0_live_hotfix.py)). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28 passed, 0 failed** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **22/22 on re-run** (single-run flakes confined to PARENT booking/slot/screen SC-11/12/13/19/46 → all pass on re-run; real-model stochasticity, NOT a regression, unrelated to the ADULT-only change). Transcript **SC-TX-01/02/03 → 3/3**. ⚠️ **Production is NOT green.** Two live-Messenger UX bugs, diagnosed-then-fixed under the conditional-fix rule. Files changed: **only** [app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py) (BUG 2 code) + [tests/test_p0_live_hotfix.py](tests/test_p0_live_hotfix.py). **No prompt edit** — `system_adult_v1.md` byte-identical (SHA-256 unchanged). No Calendar/Sheets-schema/booking-internals/broadcast/email/`.env`/model change.

- **BUG 1 — clear camp intent showed the generic menu in LIVE Messenger → root cause (d) STALE PROCESS / deploy gap; code already correct.** Full-path trace (Meta webhook → `message_buffer.buffer_message` merges fragments → `conversation_service._classify_segment` → `parent_flow._has_explicit_georgian_camp_intent` → `_maybe_static_welcome`) proved the current code does NOT emit the menu for „გამარჯობა საზაფხულო ბანაკი მაინტერესებს" (classify=PARENT, detector=True, static welcome yields, full-path response = engine answer, not the menu). **No code change** (conditional-fix rule). **Operator action: restart/redeploy the live process.** Test gap that hid it: existing ISSUE-1 tests were helper-level or engine-OFF; none ran the exact live string through full `process_message` with the engine ON. Closed by [tests/test_p0_live_hotfix.py](tests/test_p0_live_hotfix.py) full-path tests.
- **BUG 2 — a NAMED specific event asked self/child target + age first, and appended an unsolicited future-event subscription CTA.** Root cause (target/age) = **(a) MISSING LOGIC** (no „named event resolves → answer directly" branch; the ADULT prompt asks the target first — AD-1/AD-4 ordering). Root cause (CTA) = **(ii) PROMPT** (`system_adult_v1.md` „ფუტურული ღონისძიების შეტყობინებების წესი" — NOT in code). **Fix (CODE ONLY):** `adult_llm_engine._maybe_handle_named_adult_event` / `_render_named_adult_event` / `_has_specific_event_name`, wired in `run_adult_llm_turn` after the off-topic guard and before `_maybe_capture_adult_target`. A named event resolving to exactly one active event (`admin_config_service.find_active_events_by_reference`) → deterministic direct answer (title / date-time / format-location / price / link + soft „სხვა ღონისძიებებიც ჩამოგითვალოთ?"), bypassing the LLM → no target/age questions and the prompt CTA never produced. Safety: `_maybe_capture_adult_target` untouched (FIX 3/B4 intact); PARENT FIX 4/5 + event interceptor untouched (different flow / segment-separated); unknown/ambiguous → `None` → existing fallback; `_is_subscription_consent` untouched; subscription CTA still allowed on an explicit future-updates request. Verification: [tests/test_p0_live_hotfix.py](tests/test_p0_live_hotfix.py) + operator live confirmation („fromula 1" also resolves).
- **Data note (NOT a bug):** „fromula 1" (28 აგვისტო) is stored with a typo + price 5000 GEL in `data/admin_config/sections.yaml`; the agent shows it exactly as stored. Operator admin_config decision, not an agent bug.

---

## Post-audit fixes — P0 Live Demo UX Regression Batch (ISSUE 1/2/3/4/5/6) (2026-06-14, code work = 2287 → 2322)

Status: **2322 passed, 28 skipped, 0 failed** (`pytest tests/ -q`; was 2287 → +35 new). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28 passed, 0 failed** (M1–M6 hold). `test_agent.py` ✅. CRITICAL **22/22** (real OpenAI, Meta/Calendar/Sheets/Notification mocked). New real-model transcript scenarios **SC-TX-01/02/03 → 3/3**. FIX 3/4/5/M4 + M1–M6 regression guards still hold (`test_redteam_b_selfcorrection_fixes.py` + `test_prestaging_redteam_fixes.py` → 123 passed). ⚠️ **Production is NOT green.** Fixed the real-Messenger live-demo transcript issues (intent routing + answer formatting), deterministically. New file [tests/test_p0_live_demo_ux_fixes.py](tests/test_p0_live_demo_ux_fixes.py) (**+35**). **No change** to Calendar booking logic, Sheets schema/row-strategy, booking internals, email SMTP, Meta webhook, broadcast, OpenAI model, `.env`, or `LIVE_BROADCAST_ENABLED` (still `False`); the only prompt touch is ONE additive paragraph rule in `system_parent_v2.md` (no reorder).

- **ISSUE 1 — clear camp intent skips the generic two-option menu.** [app/flows/parent_flow.py](app/flows/parent_flow.py) `_has_explicit_georgian_camp_intent` (camp keyword + interest/info/sign-up marker) → `_maybe_static_welcome` yields. „ბანაკით ვარ დაინტერესებული"/„საზაფხულო ბანაკი მაინტერესებს" → greet + continue camp flow; bare greeting / bare „ბანაკი" still show the branded menu. Verification: `tests/test_p0_live_demo_ux_fixes.py` (detector + static-welcome + routing) + updated inverted tests in `test_parent_llm_engine.py` + SC-02/SC-TX-01.
- **ISSUE 2/3/6 — camp-price + price-objection paragraph formatting.** SINGLE LLM BLOB (audit #7). Deterministic post-processor on the REAL output (NOT a mock): [app/flows/parent_flow.py](app/flows/parent_flow.py) `_format_multipoint_paragraphs` (whitespace only; gate: no „\n\n" + ≥2 value-point groups + ≥3 sentences → split at sentence boundaries). Additive paragraph rule in [app/agent/prompts/system_parent_v2.md](app/agent/prompts/system_parent_v2.md) (no reorder). Verification: deterministic reformatter test (real dense-output shape) + real-model SC-TX-02.
- **ISSUE 4 — „ღონისძიების ფასი" never returns the camp price.** [app/flows/parent_flow.py](app/flows/parent_flow.py) `_maybe_handle_event_inquiry` pre-engine interceptor; fires on (A) „ღონისძიებ" + price/date or (B) established event context; bare „ღონისძიება მაინტერესებს" still reaches the engine's `switch_to_adult_flow`. Verification: `tests/test_p0_live_demo_ux_fixes.py` (no 2150, lists events) + SC-TX-03.
- **ISSUE 5 — unknown date/title/guest → searched against the active list; never invented.** [app/services/admin_config_service.py](app/services/admin_config_service.py) `find_active_events_by_reference` / `find_active_events_on_day` / `_event_query_tokens` / `_event_search_haystack`. found → answer FROM event data; miss → „not in active list" + active list + manager-verify. **READ-ONLY audit correction:** active events = „შეხვედრა გია მურღულიასთან" (14 ივნისი, price 29) + „fromula 1" (28 აგვისტო); „გია მურღულია" IS present (answers from data, not invented); „გალაკტიონის საღამო" ABSENT; no event on the 16th. Verification: `tests/test_p0_live_demo_ux_fixes.py` (date/title/guest/alias + found-from-data) + SC-TX-03.
- **⚠️ Reverted:** the camp-price **reorder** prompt instruction (price placed last) caused the model to occasionally OMIT the price number (SC-26 CRITICAL regression) — REVERTED; only „always state the price" + paragraph guidance kept. **Do NOT re-introduce a price-reorder prompt instruction.**

---

## Post-audit fixes — Red-Team B Self-Correction Batch (B5/B2/B4/M1/B1) (2026-06-13, code work = 2222 → 2287)

Status: **2287 passed, 28 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28 passed, 0 failed** (M1–M6 hold; M1 now passes). `test_agent.py` ✅. CRITICAL **22/22** (real OpenAI, Meta/Calendar/Sheets/Notification mocked). ⚠️ **Production is NOT green.** Fixed the deterministic self-correction findings from [docs/REDTEAM_CONVERSATIONS.md](docs/REDTEAM_CONVERSATIONS.md) + the M1 metamorphic divergence, ONE at a time with a full-pytest gate after each (never below 2222). New file [tests/test_redteam_b_selfcorrection_fixes.py](tests/test_redteam_b_selfcorrection_fixes.py) (**+65**). **No change** to Calendar booking logic, Sheets schema/row-strategy, booking internals (beyond the guarded B5 handoff message), email SMTP, Meta webhook, broadcast, OpenAI model, prompts, `.env`, or `LIVE_BROADCAST_ENABLED` (still `False`). No fix reverted.

- ✅ **B5 — multi-child collision** ([app/flows/parent_flow.py](app/flows/parent_flow.py) `_maybe_requalify_child`): a `_lead_has_active_booking(lead)` guard prevents a booked child's `child_age` from being wiped/overwritten by „ჩემი მეორე შვილი 14 წლისაა"; returns the deterministic `_BOOKED_SECOND_CHILD_MANAGER` handoff (no clear, no booking, no Calendar/Sheets write). Non-booked requalify unchanged.
- ✅ **B2 — name correction** ([app/flows/parent_flow.py](app/flows/parent_flow.py) `_parse_name_phone` / `_name_token_is_valid`): „არა, ნინო მქვია" → „ნინო" (was „არა ნინო"). `_name_token_is_valid` rejects `NAME_REFUSAL_KEYWORDS`; a correction-cut (`_NAME_CORRECTION_MARKERS = {"არა"}`) discards the mis-stated name before the last „არა" („ლიზი… არა ნინო" → „ნინო"). Bare „არა" stays a refusal; „ბარბარა"/„ანა" (substring) uncorrupted; happy paths unchanged.
- ✅ **B4 — adult target self-revert** ([app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py) `_maybe_capture_adult_target`): „ჩემთვის"/„მე მინდა"/„მე მაინტერესებს"/„ჩემთან" revert the target to self — only with NO relative cue, so „ჩემი შვილისთვის"/„ჩემ შვილს"/„ბავშვს" still mean the child (M4 holds). `child_age`/`adult_age` untouched.
- ✅ **M1 — spelled-out numerals** ([app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) `maybe_capture_child_age_fallback`): `_GEORGIAN_AGE_NUMERALS` (ცხრა=9…ჩვიდმეტი=17) read as whole tokens only with age context. „ცამეტი წლის" → 13; „ცამეტი" alone / „ცამეტი ბილეთი" → not captured; „9-17" still not captured; digit parsing unchanged.
- ✅ **B1 — age self-correction** ([app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) `maybe_capture_child_age_fallback`): correction markers (`არა`/`შევცვალე`/`უფრო სწორად`/`ვგულისხმობდი`/`აბა`) update an already-set `child_age` („13 → არა, 15 → აბა 9 წლის"). STRONG markers (no „აბა") also relax the bare-number gate so „არა, 15" → 15; „აბა" overwrites only with an age word. Second/different-child mentions (`მეორე შვილ`/`სხვა შვილ`) are excluded → „10 და 14 წლის" + „ჩემი მეორე შვილი 14 წლისაა" unchanged; fresh-lead keep-first (`test_age_fallback_two_children_keeps_first_valid`) unaffected.

### ⏳ STILL OPEN (carried) — two gates before production
- ⏳ **P0 — LIVE DEMO UX REGRESSION (intent routing + answer formatting), NOT done.** Operator clarification: „გალაკტიონის საღამო" is NOT in the active event list and there is NO active event on the 16th → the agent was CORRECT not to invent details. Pending: (A) clear camp intent → camp flow, no „ბანაკი თუ ღონისძიება?"; (B) „ღონისძიების ფასი" after camp context must NOT return the camp price → ask/list events; (C) unknown date/title/guest → list active events + manager-verify fallback, do NOT invent; (D) multi-part answers in paragraphs. Add regression tests for each.
- ⏳ **Railway deploy blockers (Deploy-Readiness Audit, audit only).** `config._env` is `.env`-only ([app/config.py](app/config.py) line 14/31-33) → Railway dashboard env vars (incl. `REDIS_URL`) invisible + boot crash on the 7 required vars; `requirements.txt` missing `redis`/`tzdata`/`python-multipart` (and unpinned); no `.gitignore`/`.railwayignore` for `.env`+`credentials.json`; Railway must run single replica / one uvicorn worker, always-on. Procfile/`app.main:app`/`$PORT`/APScheduler-in-web-process already OK.
- **Production is NOT green.**

---

## Post-audit fixes — Railway-Safe Google Credentials (2026-06-13, code work = 2209 → 2222)

Status: **2222 passed, 7 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. ⚠️ **Production is NOT green.** Google Sheets + Calendar now initialise from a single Railway env var instead of a local `credentials.json` file path. All credential loading is MOCKED in tests (no real credentials read, no network). New file [tests/test_google_credentials_railway.py](tests/test_google_credentials_railway.py) (**+13**). **No change** to Calendar booking logic, Sheets schema/row strategy, email SMTP, Meta webhook, broadcast, OpenAI model, prompts, or the follow-up scheduler.

- ✅ **Shared resolver** [app/services/google_credentials.py](app/services/google_credentials.py) → `load_google_credentials(scopes, *, file_value="")`. Priority: (1) **`GOOGLE_CREDENTIALS_JSON`** from `os.environ` (Railway-safe — Railway has no `.env` file, so it can't go through the `.env`-only `config._env`) → `json.loads` + `private_key` escaped-`\n` repair → `service_account.Credentials.from_service_account_info(info, scopes=...)`; (2) per-service `file_value` inline JSON or path; (3) **`GOOGLE_APPLICATION_CREDENTIALS`** path → `from_service_account_file(path, scopes=...)`; (4) nothing → clear, secret-free `RuntimeError`. `GOOGLE_CREDENTIALS_JSON` **wins** when both are set.
- ✅ **Both clients use it, no duplicated auth.** Sheets: `_sheets_client()` → `gspread.authorize(load_google_credentials(SHEETS_SCOPES, file_value=settings.GOOGLE_SHEETS_CREDENTIALS_JSON))`, shared by the 3 worksheet helpers. Calendar: `_calendar_service()` → `build("calendar","v3", credentials=load_google_credentials([CALENDAR_SCOPE], file_value=settings.GOOGLE_CALENDAR_CREDENTIALS_JSON))`. The duplicated per-file `_load_credentials_info` (+ now-unused `json`/`Path`/`service_account` imports in `calendar_service`) were removed.
- ✅ **Never logs credential contents**; the "not configured" error contains no `private_key` / `client_email` / token. New [runtime.txt](runtime.txt) = `python-3.11` (Railway build pin; no local-dev impact).
- **Railway:** `GOOGLE_CREDENTIALS_JSON=<full service-account JSON>` (paste the whole JSON; wins if both set). **Local fallback:** `GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json` (or the existing per-service `GOOGLE_SHEETS_CREDENTIALS_JSON` / `GOOGLE_CALENDAR_CREDENTIALS_JSON`). Do NOT commit `credentials.json`; do NOT log credentials.
- ⚠️ **Operator-config finding (fixed):** `.env` had `LIVE_BROADCAST_ENABLED=true` (added externally 06-12 23:45) — reset to `false` (the documented safe default) per operator confirmation; this also restored the 2 broadcast-safety-default tests to green.

---

## Post-audit fixes — Pre-Staging Fix Batch (A-1/A-2, B-1, F-D4, F-D6) (2026-06-12, code work = 2151 → 2209)

Status: **2209 passed, 7 skipped, 0 failed** (`pytest tests/ -q`). corpus **9/9**. `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **7/7**. `pytest -k comment` **196/0**. `pytest -k follow` **186/0**. `test_agent.py` ✅. CRITICAL **22/22** (real OpenAI, Meta/Calendar/Sheets/Notification mocked — happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3). ⚠️ **Production is NOT green.** Fixed the four cheap deterministic findings from the full-system audit ONE at a time with a full-pytest + corpus gate after each (never below 2151/9). New file [tests/test_prestaging_redteam_fixes.py](tests/test_prestaging_redteam_fixes.py) (**+58**). **No change** to Calendar internals, Sheets schema/row-strategy, adult subscription/broadcast SENDING, email SMTP, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED` (still `False`). No real broadcast sent. No hardcoded sender_id / profile names.

- ✅ **A-1/A-2** ([app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py)): the delivery-question handler `_maybe_handle_notification_delivery_question` was exact-substring / word-order bound (3/10 variants) and „შეტყობინება სად მომივა?" hit the forbidden „ამ კითხვაზე ვერ დაგეხმარებით" redirect. Replaced `_NOTIFICATION_DELIVERY_QUESTION_PATTERNS` with a stem-group detector (`_DELIVERY_WHERE_HOW_STEMS` / `_DELIVERY_SUBJECT_STEMS` / `_DELIVERY_ARRIVAL_STEMS` / `_DELIVERY_CHANNEL_STEMS` + `_has_standalone_here`): a delivery question is `(სად/როგორ + subject-or-arrival)` OR `(channel + arrival)` OR `(„აქ" + write/arrival + „?")`. Added „შეტყობინ"/„შემატყობ" to `_ADULT_IN_SCOPE_STEMS` and made `_maybe_adult_offtopic_reply` return `None` for any delivery question (defence-in-depth). **All 10 variants → platform-aware answer; none redirected; never re-subscribes; never reaches the LLM.** Narrow: price / location / consent („კი გამომიგზავნეთ", „შემატყობინეთ") are NOT intercepted.
- ✅ **B-1** ([app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py)): added the DATIVE needles „შვილს"/„ბავშვს" to `_ADULT_RELATIVE_PATTERNS` (not substrings of the genitive „შვილის"/„ბავშვის", so they never shadow them). „ჩემ შვილს უნდა" / „ბავშვს უნდა" capture the relation + reuse a known `child_age` → `adult_target_age`; min_age filtering unchanged; unknown age → still asks; cross-sender/platform isolation verified.
- ✅ **F-D4** ([app/flows/parent_flow.py](app/flows/parent_flow.py)): broadened `_CONTACT_REQUEST_MARKERS` (`ნომერ`/`ტელეფონ`/`კონტაქტ`/`დაგიკავშირდეთ`/`როგორ დაგიკავშირ`) so a bare valid phone is captured for non-brand contact-asks („მომწერეთ ნომერი" / „როგორ დაგიკავშირდეთ?"). The optative `-ეთ` form is matched, the future `-ებათ` confirmation („მენეჯერი დაგიკავშირდებათ") is NOT; the `in_contact_ctx` gate keeps a no-context bare phone → `None`.
- ✅ **F-D6** ([app/flows/parent_flow.py](app/flows/parent_flow.py)): `_maybe_request_full_contact_on_intent` parses + saves an inline phone (+ validly-disclosed name) BEFORE composing the ask, so „კი მინდა კონსულტაცია 595999733" never re-asks the phone (asks only the name, or proceeds to date/time when the name is known). Intent detection broadened for word-separated „მინდა … კონსულტაცია" (negation-guarded), „დამირეკეთ", „მინდა ჩაწერა"; „დარეკ"/„დამირეკ" added to `_NAME_REJECT_STEMS` so „დამირეკეთ" is never a name. Two distinct numbers → „ორი ნომერი მომწერეთ…". Eligibility gate preserved.

### ⏳ STILL OPEN (carried)
- ⏳ Deferred (unchanged): F-D3 Latin name, F-D7/M3/M4 half-hour/evening time, ROOT 4 multi-child (update its existing test first), WhatsApp wording. NEEDS LIVE SMOKE: comment webhook + DM send, follow-up tick, specific-post → event mapping, Meta token regenerate, WhatsApp. Operator Priority 0: Meta token regenerate; deactivate test adult events `formula_1`/`summer_fest`; Google creds Railway-safe; STAGING deploy first. **Production is NOT green.**

---

## Full-System Red-Team Audit + NEXT = Pre-Staging Fix (2026-06-12, AUDIT ONLY — no code changed)

Full report: [docs/REDTEAM_FULL_SYSTEM_AUDIT.md](docs/REDTEAM_FULL_SYSTEM_AUDIT.md). **Verified baseline:** pytest **2151 passed, 7 skipped, 0 failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1` property **7/7** · `test_agent.py` ✅ · CRITICAL **22/22** (last run) · `pytest -k comment` **196/0** · `pytest -k follow` **186/0**. **Production NOT green.**

Audit verdict: **0 BLOCKER · 8 DEGRADED · 2 active MINOR · 6 NEEDS-LIVE-SMOKE · 2 OPERATOR-DATA-CLEANUP.**
- **GREEN (offline-confirmed):** comment routing (no phone-in-comment contact corruption — `comment_service` never parses contact; `processed_comment` dedupe + segment routing present), follow-up (`_BLOCKED_REASONS` booked/registered/declined/asked_no_more/handoff/exhausted + non-parent skip + `lead.calendly_booked` double-check), CRM hygiene (garbage names rejected, challenge clean, `to_sheet_row` clean), cross-user/platform isolation (`conversation:{platform}:{sender_id}`), `LIVE_BROADCAST_ENABLED=False`, NO token/secret value in logs, adult-event date filter hides the past `მასტერკლასი`.
- **Highest-risk area:** the adult subscription delivery-question handler — deterministically emits the forbidden „ამ კითხვაზე ვერ დაგეხმარებით" redirect for „შეტყობინება სად მომივა?" and covers only 3/10 realistic phrasings.

### ⏳ NEXT TASK — PRE-STAGING FIX (4 cheap deterministic; per-bug pytest + corpus gate ≥2151 / 9)
- **FIX 1 (A-1/A-2):** broaden `adult_llm_engine._maybe_handle_notification_delivery_question` (word-order/morphology tolerant) and/or add „შეტყობინ"/„შემატყობ" to `_ADULT_IN_SCOPE_STEMS` so a delivery-channel question is NEVER off-topic-redirected. Platform-aware answer; no re-subscribe; no LLM.
- **FIX 2 (B-1):** add dative „შვილს"/„ბავშვს" to `adult_llm_engine._ADULT_RELATIVE_PATTERNS` (genitive-only today) so „ჩემ შვილს უნდა"/„ბავშვს უნდა" capture relation + reuse known `child_age`.
- **FIX 3 (F-D4):** broaden `parent_flow._CONTACT_REQUEST_MARKERS` so a bare valid 9-digit phone is captured regardless of the contact-ask wording (keep single-phone happy path corpus CONV 1/6 + the `in_contact_ctx` gate).
- **FIX 4 (F-D6):** `parent_flow._maybe_request_full_contact_on_intent` must parse + save an inline phone before asking („კი მინდა კონსულტაცია 595999733").
- **DEFER:** F-D3 Latin name, F-D7/M3/M4 half-hour/evening time, ROOT 4 multi-child (update `test_age_fallback_two_children_keeps_first_valid` FIRST), WhatsApp wording.
- **NEEDS LIVE SMOKE (6):** delivery-question LLM answers, comment webhook + DM send, follow-up live tick, specific-post → event mapping, Meta token regenerate, WhatsApp.
- **Operator Priority 0:** regenerate the Meta access token (leaked once in a terminal log — code does NOT log tokens); deactivate test adult events `formula_1` (price 4999) + `summer_fest` via Admin Panel; Google creds Railway-safe (env/base64); Railway env sync; STAGING deploy first (test Page); Railway smoke; Meta App Review. **Do NOT mark production green.**

---

## Post-audit fixes — Name-Capture Batch Fix (ROOT 1–4, 2026-06-12, code work = 2129 → 2151)

Status: **2151 passed, 7 skipped (property), 0 failed** (`pytest tests/ -q`). corpus **9/9**. `test_agent.py` ✅ green. **Property audit `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → 7/7 passed (P1/P2/P4 flipped to PASS; P3/P5/P6/P7 still pass).** CRITICAL **22/22**. ⚠️ **NOT production-approved.** Fixed ONE root cause at a time with a full-pytest + corpus gate after each. New file [tests/test_name_capture_batch_fix.py](tests/test_name_capture_batch_fix.py) (+22). **No change** to Calendar internals, Sheets schema/row-strategy, adult subscription/broadcast, email, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`. No hardcoded sender_id / profile names.

Roots fixed (from the red-team + Hypothesis P1/P2/P4 findings):
- ✅ **ROOT 1** ([parent_flow.py](app/flows/parent_flow.py)): added the function words `ჩემი, ან, და, გამარჯობა, არის, გთხოვთ` to `NAME_FILLER_WORDS` and the stems `ჯავშან` / `გადანიშ` to `_NAME_REJECT_STEMS` (the old `ჯავშნ` missed the nominative `ჯავშან-ი`; `გადანიშ` was absent). Exact-match filler keeps real names (ანა, დავითი, არისტო) safe; `არა` still blanked as a refusal; all previously-rejected words stay rejected.
- ✅ **ROOT 2 (CORE)** ([parent_flow.py](app/flows/parent_flow.py)): `_looks_like_contact_disclosure` no longer unconditionally returns `True` when a phone is present — the name candidate must be a non-empty run of ≤ `_NAME_TOKEN_CAP` (4) valid name tokens. „ჩემი ნომერია 595999733" → name not saved (asks for the name); „ჩემი სახელია ლიზი ნომერი 595999733" → name=`ლიზი` (filler stripped). **ROOT 2 (enhancement, DONE):** `_distinct_valid_phones` + a contact-handler branch — two distinct numbers („595999733 ან 595999734") → „ორი ნომერი მომწერეთ. რომელი ნომრით დაგიკავშირდეთ?" instead of silently picking the first / saving `ან`. A single spaced phone („595 999 733") still counts as one.
- ✅ **ROOT 3** ([parent_flow.py](app/flows/parent_flow.py)): `_parse_name_phone` drops a captured name longer than `_NAME_TOKEN_CAP` (4) tokens → a rambling paragraph + phone yields phone only (name empty), never the paragraph. Short names (1–2 tokens) unaffected.
- ⏸️ **ROOT 4 (DEFERRED)** — multi-child age „10 და 14 წლის" still keeps the first age. Implementing the „capture nothing → re-ask" guard broke the existing `tests/test_parent_llm_engine.py::test_age_fallback_two_children_keeps_first_valid`, which encodes the old „keep first" contract. Per the task's STOP rule (an existing test breaking halts that root cause) the change was reverted. **Recommendation:** in a dedicated follow-up, update that existing test to the new contract and add a deterministic „which child — 10 or 14?" clarification (no Sheets schema / lead-field change needed — clarification-only).

### ⏳ STILL OPEN (carried)
- ⏳ Live smoke for the name-capture fixes (no „ჩემი"/„ან"/paragraph saved as name; „ჯავშანი"/„გადანიშვნა" not a name; two-number clarification; single-phone happy path). ROOT 4 multi-child follow-up. Plus the carried operator items. **Production is NOT green.**

---

## Post-audit fixes — PARENT Contact-Capture (BUG 1–4, 2026-06-12, code work = 2086 → 2120)

Status: **2120 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **22/22** (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3 — real OpenAI, Meta/Calendar/Sheets/Notification mocked). ⚠️ **NOT production-approved.** Fixed ONE bug at a time with a full-pytest gate after each (≥2086). New file [tests/test_parent_contact_collection_livebug.py](tests/test_parent_contact_collection_livebug.py) (+34). **No change** to Calendar internals, Sheets schema/row-strategy, adult subscription/broadcast sending, email SMTP, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`. No real broadcast sent.

> **BUG 1 asymmetry trace (reported before any fix — the handoff hypothesis of a parser regression was DISPROVEN):**
> `_parse_name_phone("595999733")` → `("", "595999733")` — the parser extracts the bare phone correctly; there is **NO** deterministic rejection line. The asymmetry lived in the caller gating: the only deterministic contact capture (`_capture_contact_and_ask_time`) is gated behind an ACTIVE booking sub-flow (`booking_subflow_active = bool(stale_cleared or pending)`), so a contact turn with no `pending_booking` fell through to the stochastic LLM — which has `maybe_capture_child_age_fallback`/`maybe_capture_challenge_fallback` but **no phone fallback**. „595999733 ეს არის ნომერი" gave the LLM an explicit „this is the number" cue (reliable save); bare „595999733" was ambiguous (re-ask). Regression surface = the **PARENT Contact Extraction + Booking State** patch (2026-06-11) which introduced the pending-gated capture and left plain contact-collection LLM-dependent. `_parse_booking_datetime("595999733 ლიზი")` → `None` and `extract_colloquial_hour` → `None`, so BUG 2's „ეს დრო ძალიან ახლოსაა" came from the booking/time path acting on a non-bookable pending datetime during contact collection, NOT from parsing the phone as a time.

### ✅ Shipped + tested — Contact-Capture (+34 tests, 2086 → 2120)
- ✅ **BUG 1 + BUG 2** ([parent_flow.py](app/flows/parent_flow.py)): new deterministic `_maybe_handle_contact_collection` runs in the engine path BEFORE the LLM / commit helper. On a contact-only message (a parsed phone, NO explicit booking datetime, no time-change) inside a contact-collection context (`_bot_recently_asked_for_contact` via the latest assistant turn carrying „9-ნიშნა"/„საკონტაქტო ნომერ", OR a `pending_booking`), it captures the phone (any order, user phone wins over missing profile data) + a valid name, then replies deterministically — „ნომერი მივიღე. მომწერეთ თქვენი სახელი…" (name unknown) / „მადლობა, {name}. რომელი დღე…" (name+phone) / „ნომერი მივიღე. რომელი დღე…" (name known). Reversed „595999733 ლიზი" is contact, never booking/time. A genuinely future, bookable confirmed slot still books via the commit helper (`_pending_iso_is_future_bookable` defer). Over-long „555555555555555" → asks for a valid 9-digit. (gate → 2102)
- ✅ **BUG 3** ([parent_llm_engine.py](app/agent/llm/parent_llm_engine.py)): `_strip_concern_wording` extended with `_is_known_about_you_preamble` — strips a sentence carrying „თქვენი" + (ასაკ|სახელ|ინფორმაცია) + (უკვე ვიცი|უკვე მაქვს), so „თქვენი ასაკი უკვე ვიცი, 15 წლისაა" (15 = CHILD's age) and „თქვენი სახელი უკვე ვიცი" are removed. The „თქვენი" anchor preserves the legitimate „სახელი უკვე ვიცი" / „ბავშვის ასაკი უკვე ვიცი" wording and the Task 2 privacy notice (no „უკვე ვიცი/მაქვს") and booking confirmations. (gate → 2111)
- ✅ **BUG 4** ([parent_flow.py](app/flows/parent_flow.py)): `_maybe_request_full_contact_on_intent` — on an explicit consultation request („კი მინდა" / „კონსულტაცია მინდა" / „ჩამწერეთ", NOT a bare „კი") for an ELIGIBLE known age with contact incomplete and no bookable slot pending → asks the COMPLETE contact (name + 9-digit phone when the name is not validly known, phone-only when it is); never a partial name-less ask, never „სახელი უკვე ვიცი". Defers for unknown/ineligible age, browsing („კი მინდა ვიცოდე ფასი"), and the booking-confirmation path. (gate → 2120)
- ✅ **Scope:** generic + state-based (no hardcoded sender_id / profile names / father logic — the only names are test fixtures); no Calendar internals / Sheets schema / row-strategy / adult / broadcast / email / OpenAI-model / prompt / `LIVE_BROADCAST_ENABLED` change.

### ⏳ STILL OPEN (carried)
- ⏳ **Live smoke:** PARENT contact capture — bare „595999733" (name known → asks time; name unknown → asks name), reversed „595999733 ლიზი" (no booking/time path), no „თქვენი ასაკი/სახელი უკვე ვიცი" wording, „კი მინდა" → complete name+phone ask. Plus the carried operator items (reschedule Sheet-status live check; deactivate test adult events; Meta token regenerate; Google creds Railway-safe; STAGING deploy). **Production is NOT green.**

---

## Verification audit — comment routing + follow-up scheduler NOT broken by recent patches (2026-06-12, AUDIT ONLY)

Verdict: **LOW risk, isolated.** No code changed. Baseline **2086 passed, 0 failed**, CRITICAL 22/22, production NOT green.
- Recent patches modified ONLY `parent_flow.py` (06-11 21:12), `parent_tool_executor.py` (06-11 21:29), `parent_llm_engine.py` + `adult_llm_engine.py` (06-12 00:19). `comment_service.py` (06-10 21:49), `followup_service.py` (06-06), `main.py` APScheduler init (06-08) all PREDATE that window — NOT modified.
- `comment_service.py` and `followup_service.py` contain **zero** references to any recently-changed module/function/sanitizer.
- `pytest -k "comment"` → **196 passed / 0 failed / 0 skipped**; `pytest -k "follow"` → **186 passed / 0 failed / 0 skipped**.
- The wording sanitizers (`sanitise_response_wording` / `_strip_concern_wording`) run only on LLM engine output; the privacy-notice policy runs only inside `parent_flow._sanitise_booking_confirmation`. Comment first-contact DMs and follow-up copy are template-based and never invoke them. Challenge cleanup applies only when a comment-sourced user later discloses a goal in the shared DM engine — uniform, not a comment-specific regression.
- Recommended live smoke (standard, not due to a detected regression): comment #camp / #event / specific-tag · comment-triggered follow-up · subscription follow-up (DRY-RUN only; do NOT set `LIVE_BROADCAST_ENABLED=true`).

### ✅ ~~NEXT TASK (carried) — PARENT contact-capture (4 bugs)~~ — RESOLVED 2026-06-12 (see the Contact-Capture section at the top; +34 tests, 2086 → 2120)
- ✅ BUG 1 — bare „595999733" now captured deterministically by `_maybe_handle_contact_collection` (the parser was never broken; the trace DISPROVED the parser-regression hypothesis — the gap was the LLM-dependent no-pending contact turn).
- ✅ BUG 2 — reversed „595999733 ლიზი" handled as contact before the booking/time path.
- ✅ BUG 3 — `_is_known_about_you_preamble` strips „თქვენი ასაკი/სახელი/ინფორმაცია უკვე ვიცი" (Task 2 privacy notice + „სახელი უკვე ვიცი" preserved).
- ✅ BUG 4 — `_maybe_request_full_contact_on_intent` asks the complete name+phone on an explicit request.
- Still pending (operator): reschedule Sheet-status live check; deactivate test adult events; Meta token regenerate; Google creds Railway-safe; STAGING deploy. **Production is NOT green.**

---

## Post-audit fixes — Wording Fixes: ban „შეშფოთება"/info-already-known preamble + answer „where will the notification arrive?" (2026-06-11)

Status: **2086 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL ****22/22** (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3 — SC-01 passed this run)** (real OpenAI, Meta mocked). ⚠️ **NOT production-approved.** Fixed ONE bug at a time with a full-pytest gate after each (≥2066). New file [tests/test_wording_concern_and_subscription_delivery.py](tests/test_wording_concern_and_subscription_delivery.py) (+16). **No change** to Calendar internals, Sheets schema, adult subscription WRITE logic, broadcast sending, email SMTP, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`.

> **Audit findings (both are LLM free-generation; the prompts are intentionally NOT changed — deterministic sanitizers added instead):**
> - **BUG 1 (PARENT contact request):** the system prompt `system_parent_v2.md` uses „შეშფოთება" (concern/anxiety) as the term for the parent's challenge, and „თქვენი ინფორმაცია უკვე მაქვს ასაკისა და შეშფოთების შესახებ…" is not a literal template (no code match) → LLM-composed. Alarming word + hallucinated confidence when name/phone are still missing.
> - **BUG 2 (ADULT delivery question):** the deterministic off-topic guard `_maybe_adult_offtopic_reply` does NOT match „სად მომივა შეტყობინება?"; the „ამ კითხვაზე ვერ დაგეხმარებით…" redirect is LLM-composed from the system_adult_v1.md OFF-TOPIC rule.

### ✅ Shipped + tested — Wording Fixes (+20 tests, 2066 → 2086)
- ✅ **BUG 1** ([parent_llm_engine.py](app/agent/llm/parent_llm_engine.py)): `_strip_concern_wording` inside `sanitise_response_wording` strips a sentence carrying BOTH (ასაკ|შეშფოთებ) AND (უკვე მაქვს|უკვე ვიცი) — the legitimate „სახელი უკვე ვიცი/მაქვს" wording and the privacy notice are preserved — then replaces any residual „შეშფოთებ" stem with „მოლოდინ". (gate → 2076)
- ✅ **BUG 2** ([adult_llm_engine.py](app/agent/llm/adult_llm_engine.py)): `_maybe_handle_notification_delivery_question` in `run_adult_llm_turn`, before subscription / off-topic / LLM, answers the delivery question platform-aware (Messenger / Instagram). Never re-subscribes, never reaches the LLM (proven by an integration test mocking OpenAI to raise + flagging any subscribe). (gate → 2082; +4 adversarial-review regressions → 2086)
- ✅ **Privacy notice (Task 2) still works** — confirmed by a regression test: the privacy sentence passes through `sanitise_response_wording` unchanged (it has no „უკვე მაქვს"/„შეშფოთებ").
- ✅ **Adversarial multi-agent review on the diff** — 4 confirmed: (1+2) the concern-strip over-stripped legitimate „… უკვე ვიცი, … ასაკ …" sentences → re-anchored on „ინფორმაცია" via a sentence-split; (4) WhatsApp users got „Messenger-ში" → added a WhatsApp branch; (3) the „შეშფოთება"→„მოლოდინი" replacement is unconditional = BY-DESIGN (spec bans the word). +4 regression tests.
- ✅ **Scope:** no Calendar internals / Sheets schema / adult subscription WRITE / broadcast send / email SMTP / OpenAI model / prompt / `LIVE_BROADCAST_ENABLED` change.

### ⏳ STILL OPEN (carried into the next session)
- ⏳ **Live smoke:** A (clean PARENT contact request, no „შეშფოთება") + B (subscription-delivery answer, not off-topic); plus the carried-over operator items (deactivate the 3 placeholder adult events; full booking/reschedule/adult/comment smoke; `events`-tab audit; Meta client transfer · WhatsApp · Railway env sync). **Do NOT mark production green.**

---

## Post-audit fixes — Cleanup Fix: privacy-notice timing / challenge text dedupe / adult-events audit (2026-06-11)

Status: **2066 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL ****22/22** (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3 — SC-01 passed this run)** (real OpenAI, Meta mocked). ⚠️ **NOT production-approved.** Fixed ONE bug at a time with a full-pytest gate after each (≥2046). New file [tests/test_cleanup_privacy_challenge_dedupe.py](tests/test_cleanup_privacy_challenge_dedupe.py) (+20). **No change** to Calendar internals, Sheets schema/row-strategy, adult subscription/broadcast sending, email SMTP, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`.

> **Audit findings:**
> - **BUG A (privacy notice too early/often):** the system prompt instructs the LLM to add the child-data privacy notice when collecting child data, so it leaked onto contact/slot turns (and sometimes twice); the Session-7 „short confirmation" rule meanwhile STRIPPED it on the success turn — the opposite of the new rule.
> - **BUG B (challenge text duplicated in a row):** the email already deduped, but the SAVE path stored the raw merged `lead.challenge` (verbatim to the Sheets CRM) → „X Y X Y". (Multiple ROWS per sender are BY DESIGN — not a bug.)
> - **BUG C (test rows in the adult list):** dirty data, not a code bug.

### ✅ Shipped + tested — Cleanup Fix (+20 tests, 2046 → 2066)
- ✅ **BUG A** ([parent_flow.py](app/flows/parent_flow.py) + [parent_tool_executor.py](app/agent/tools/parent_tool_executor.py)): `_apply_privacy_notice_policy` in the universal chokepoint `_sanitise_booking_confirmation` strips the notice on EVERY turn and re-appends ONE canonical sentence iff `book_consultation_success_for_conversation` is set this turn (executor signal). `_reschedule_booking` now sets that flag too. No prompt change; the Session-7/8 sub-function tests stay green. (gate → 2056)
- ✅ **BUG B** ([parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) + [parent_tool_executor.py](app/agent/tools/parent_tool_executor.py)): `dedupe_challenge_text` (clause + verbatim repeated-block) inside `clean_challenge_for_storage`; `_save_lead_info` merge uses comma/space-insensitive `challenge_word_set` containment — substring containment and the „; " separator preserved. (gate → 2066, after fixing 2 gate-found regressions: the substring check + the „; " separator.)
- ✅ **BUG C — AUDIT ONLY, dirty data NOT code bug.** `get_active_adult_events()` correctly filters active + future (verified: past „მასტერკლასი" excluded; 5 future-active returned). Events come from `data/admin_config/sections.yaml` (operator config), NOT a Sheet; no test/staging flag column. **Operator action (do NOT auto-delete):** deactivate `id='ჯონი'`, `id='formula_1'`, `id='summer_fest'` via `/admin/programs/adult_events/events/{id}/deactivate`. Recommend a staging-vs-prod config separation / a `test:` convention.
- ✅ **Scope:** no Calendar internals / Sheets schema / Sheets row-strategy / adult subscription/broadcast send / email SMTP / OpenAI model / prompt / `LIVE_BROADCAST_ENABLED` change.

### ⏳ STILL OPEN (carried into the next session)
- ⏳ **Operator:** deactivate the 3 placeholder adult events above; full live smoke (privacy notice once on a real booking + reschedule; clean challenge in the Sheet row); READ-ONLY `events`-tab audit; Meta client transfer · WhatsApp · Railway env sync · production smoke. **Do NOT mark production green.**

---

## Post-audit fixes — State Reuse Fix: cross-flow child_age / adult→parent reschedule / bare „N საათი" (2026-06-11)

Status: **2046 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL ****22/22** (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3 — SC-01 passed this run)** (real OpenAI, Meta mocked). ⚠️ **NOT production-approved.** Fixed ONE bug at a time with a full-pytest gate after each (≥2021). All deterministic, generic (no hardcoded sender_id / profile logic). New file [tests/test_state_reuse_crossflow_and_pm_time.py](tests/test_state_reuse_crossflow_and_pm_time.py) (+25). **No change** to Calendar internals, Sheets schema/write, adult subscription/broadcast, email, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`.

> **Audit findings:**
> - **BUG 1 (adult re-asks known child_age):** the ADULT context surfaces `adult_target_age` (not `child_age`); `_maybe_capture_adult_target` set the relation „შვილი" from „ჩემი შვილისთვის" but left `adult_target_age` blank, so the LLM + `_ensure_adult_intro_followup` re-asked „თქვენი შვილი რამდენი წლისაა?". Entering ADULT never clears `child_age` (shared `conversation.lead`; `switch_to_adult_flow` only moves it to `adult_age` when out of [9,17]).
> - **BUG 2 (adult→parent reschedule loses state):** the segment override already routes „კონსულტაციის გადატანა მინდა" to PARENT, but the engine then sometimes re-asked the age / treated the user as fresh (stochastic).
> - **BUG 3 (bare „N საათი"):** ALREADY handled — `timestamps._COLLOQUIAL_HOUR_RE` already includes the `საათი` suffix; verified 20:00 across all three deterministic call-sites. No code change needed.

### ✅ Shipped + tested — State Reuse Fix (+25 tests, 2021 → 2046)
- ✅ **BUG 1** ([adult_llm_engine.py](app/agent/llm/adult_llm_engine.py)): `_maybe_capture_adult_target` reuses `child_age` → `adult_target_age` when the relation is the user's own child (`შვილი`/`ბავშვი`), no inline age, and the message is NOT „სხვა …". Copies, never moves; `child_age`/`adult_age` coexist and are untouched. New `_ADULT_CHILD_RELATIONS` + `_looks_like_child_age`. (gate → 2031)
- ✅ **BUG 2** ([parent_flow.py](app/flows/parent_flow.py)): new `_maybe_handle_reschedule_intent_engine` runs in the engine path before the commit helper. Reschedule intent (no datetime) + active booking → „კი, ბანაკის კონსულტაციის გადატანაში დაგეხმარებით. რომელი ახალი დღე და დრო გირჩევნიათ?" (reuses parent state, no age re-ask — reschedule intent wins over qualification). Reschedule + datetime → defers to the existing check/reschedule flow. No booking + not mid-build → asks for identifying info politely, never adult data. (gate → 2038)
- ✅ **BUG 3** — NO code change. `_COLLOQUIAL_HOUR_RE`'s `საათ(?:ზე|ისთვის|ისკენ|ი)?` already covers bare „საათი"; „18 ივნისი 8 საათი" → 20:00, „დილით 8 საათი" → 08:00 (outside-hours), „10 საათი" → 10:00, „20:00" literal — verified via `_parse_booking_datetime`, the executor normaliser, and `_repair_colloquial_hour_rejection`. +8 regression tests lock it. (gate → 2046)
- ✅ **Hardcode audit:** no hardcoded sender_id / profile name / live-conversation overfit in the changed production code (the only numeric/name literals in the touched files are pre-existing in explanatory comments). LLM owns language/composition; deterministic guards own child_age reuse, reschedule routing, and time parsing.

### ⏳ STILL OPEN (carried into the next session)
- ⏳ **Live smoke** — A–D above on a real Meta DM + the standing PARENT booking create path / reschedule completion / adult event list / adult subscription / comment routing. READ-ONLY `events`-tab audit. Meta client transfer · WhatsApp · Railway env sync · production smoke. **Do NOT mark production green.**

---

## Post-audit fixes — PARENT Contact Extraction + Booking State + Challenge Cleanup (2026-06-11)

Status: **2021 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **22/22 ✅** (real OpenAI, Meta mocked — happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3; SC-01 passed this run). ⚠️ **NOT production-approved.** Four live PARENT bugs; all fixes deterministic, generic (no hardcoded users), PARENT-only. New file [tests/test_parent_contact_booking_and_challenge_cleanup.py](tests/test_parent_contact_booking_and_challenge_cleanup.py) (+52).

> **Audit findings:**
> - **BUG 1 (contact-only → stale booking):** `parent_flow._maybe_commit_pending_booking_engine` booked a `_confirmed_pending_iso` (recorded earlier by `_check_consultation_slot`/`_record_pending_booking_for_slot`, `user_confirmed_datetime=True`) without checking it was still future. A 16:45 datetime had elapsed → `book_consultation` returned `datetime_in_past` → the LLM composed „…16:45 წარსული დროა". Contact capture was not separated from booking confirmation.
> - **BUG 2 (name corruption):** `_parse_name_phone` kept every non-digit leftover token as the name with no month/time/booking rejection → „595999733 16 ივნის მინდა 10 საათზე" → name=„ივნის".
> - **BUG 3 (false „სახელი უკვე ვიცი"):** the engine surfaces `name={lead.name}`; a corrupted/stale stored name made the LLM claim it knew the name. Adult-subscription data is NEVER used as PARENT contact (verified: `adult_subscription_service._validate_phone` reuses `_parse_name_phone` for read-only phone validation only; the `events` Sheets tab never hydrates `lead.name`/`lead.phone`).
> - **BUG 4 (challenge pollution):** the SAVE path (`_save_lead_info`, `maybe_capture_challenge_fallback`) stored the raw user message on `lead.challenge`, which `Lead.to_sheet_row` writes verbatim. Only the email rendering had been cleaned previously.

### ✅ Shipped + tested — PARENT Contact Extraction + Booking State + Challenge Cleanup (+54 tests, 1967 → 2021)
- ✅ **BUG 1 fix** ([parent_flow.py](app/flows/parent_flow.py)): `_pending_iso_is_stale` + `_clear_stale_pending_datetime` strip a past confirmed pending datetime (never booked); the inline compound datetime is only committed when still future; `_capture_contact_and_ask_time` saves the contact and returns the deterministic „მადლობა, {name}. რომელი დღე და დრო გირჩევნიათ კონსულტაციისთვის?". A FUTURE confirmed slot + „კი"/contact still books that exact slot.
- ✅ **BUG 2 fix** ([parent_flow.py](app/flows/parent_flow.py) + [parent_tool_executor.py](app/agent/tools/parent_tool_executor.py) + [parent_turn_router.py](app/flows/parent_turn_router.py)): `_name_token_is_valid` (rejects digit-bearing tokens, `GEORGIAN_MONTH_STEMS` declensions, time/date/booking stems + exacts; „მინდა" is exact so the name „მინდია" survives) drives `_parse_name_phone`; public `is_valid_person_name` guards `_save_lead_info`, `_book_consultation`, the engine pending-commit, and the legacy router. „ჯონი 595999733" → ჯონი; „სახელი ჯონი" → ჯონი.
- ✅ **BUG 3 fix** ([parent_flow.py](app/flows/parent_flow.py)): `_sanitise_invalid_stored_name(lead)` runs in `_run_llm_engine_safely` before the engine builds context — clears an invalid stored name so „სახელი უკვე ვიცი" is never said for a month/date artifact; valid names (Meta profile / disclosures) untouched.
- ✅ **BUG 4 fix** ([parent_llm_engine.py](app/agent/llm/parent_llm_engine.py)): `clean_challenge_for_storage` drops factual-question clauses (specific multi-char stems, not bare „სად"/„ღირ") + leading filler at the SAVE chokepoint (`_save_lead_info` challenge+notes, `maybe_capture_challenge_fallback`), preserving the parent's wording. This is the Sheets fix Bug 4 asked for — distinct from the email-only `_clean_challenge_for_email`.
- ✅ **Generic + state-based** — no hardcoded sender_ids / user-specific logic.
- ✅ **Scope guard** — no Calendar service, Sheets schema, email SMTP, OpenAI model, webhook, broadcast, or adult/comment logic change; no prompt change. Broadcasts DRY-RUN. No real DM sent.
- ✅ **Verification:** pytest **2021 passed, 0 failed**; `test_agent.py` green; CRITICAL **22/22**.

### ⏳ STILL OPEN (carried into the next session)
- ⏳ **Final live smoke** — run the A–E contact/booking/challenge smoke on a real Meta DM + the standing PARENT booking create path / reschedule / adult event list / adult subscription / comment routing. READ-ONLY audit of the `events` subscribers tab. Meta client transfer · WhatsApp · Railway env sync · production smoke. **Do NOT mark production green.**

---

## Post-audit fixes — State Consistency + Child-Age Extraction (2026-06-11)

Status: **1967 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **21/22** — sole miss is SC-01 turn-4 LLM word-choice stochasticity („ეხმარება" vs „მუშაობს" in the screen-concern reply); SC-01 passes 4/5 in isolation, the failing turn runs with `child_age="14"` already captured and is NOT touched by this change. ⚠️ **NOT production-approved.**

> **Audit finding (PART 1):** `parent_llm_engine.maybe_capture_child_age_fallback` used `(?<!\d)(\d{1,2})(?!\d)` and captured „9" from „9-17" (the camp's advertised age BAND / menu) → `child_age="9"`, so the agent treated the age as known and skipped asking the child's real age. „9-17" was NOT stored as a literal range — it was extracted as „9". The fallback also lacked any time/date guard („12 საათზე" / „11 ივნისს" could be misread as an age). PARENT-only; Sheets/adult/Calendar paths untouched.

### ✅ Shipped + tested — State Consistency + Child-Age Extraction (+52 tests, 1915 → 1967)
- ✅ **FIX 1 — extraction hardening** ([parent_llm_engine.py](app/agent/llm/parent_llm_engine.py)): `maybe_capture_child_age_fallback(lead, message, *, age_question_pending=False)` rejects ranges (`_contains_age_range`), rejects time/date numbers incl. the colloquial hour marker „N-ზე"/„Nზე" (`_number_is_time_or_date`), and requires age context (წლ/წელ word, child word, or `age_question_pending`); a bare standalone number is read as age ONLY right after the bot asked (`_bot_recently_asked_child_age`). `_save_lead_info` rejects range child_age args. Existing contracts preserved.
- ✅ **Adversarial multi-agent review run on the diff** — 1 confirmed real finding: „N-ზე"/„Nზე" colloquial-hour („at 8") still leaked as child_age (same bug class as „9-17", a different time form the project's own `timestamps.extract_colloquial_hour` treats as a clock hour). Fixed before finalising (added „ზე" to the time markers) + 5 regression tests.
- ✅ **FIX 2 — new-user camp age guard** ([parent_flow.py](app/flows/parent_flow.py)): `_ensure_camp_age_question` appends „თქვენი შვილი რამდენი წლისაა?" when segment=PARENT + child_age unknown + reply lacks an age-stem + not a handoff/adult redirect.
- ✅ **FIX 3 — resume transparency + re-qualification**: `_maybe_acknowledge_stored_state` (greeting/restart of a DONE, non-booked, non-pending conversation → acknowledge stored age once) + `_maybe_requalify_child` („სხვა შვილ"/„სხვა ბავშვ"/„სხვა ასაკ" → clear + re-ask, re-extract a new age if present; name/phone preserved). Booked users excluded from the resume-ack.
- ✅ **FIX 4 — safe state load** ([conversation.py](app/models/conversation.py)): `from_dict` already defaults every field via `.get`; added a privacy-safe stale-format log (no PII, no migration system).
- ✅ **Generic + state-based** — no hardcoded sender_ids / user-specific logic (tokeniser test asserts no ≥12-digit numeric literal in the changed sources; same input+state→same behavior across fake sender_ids).
- ✅ **Verification:** pytest **1967 passed, 0 failed**; `test_agent.py` green; parent-engine / booked-state / reschedule / ineligible-age suites all green.

### ⏳ STILL OPEN (carried into the next session)
- ✅ ~~**NEXT TASK — Name/Phone parser fix.**~~ — RESOLVED 2026-06-11 by **PARENT Contact Extraction + Booking State + Challenge Cleanup** (latest section at the top of this file; +54 tests, 1967 → 2021). Also fixed: contact-only no longer books a stale time, „სახელი უკვე ვიცი" is not said for an invalid stored name, and the challenge Sheet column is cleaned at the save path.
- ✅ ~~Clean-tree verification~~ — done 2026-06-11: repo-wide search found NO mutation-test artifacts in app code; `conversation.py::from_dict` holds the intended FIX 4 implementation. No files changed; pytest **1967 passed**, `test_agent.py` green.
- ✅ ~~Confirmatory CRITICAL run~~ — done: **21/22**, sole miss is SC-01 turn-4 LLM word-choice stochasticity (not a regression — see above).
- **SC-01 brittle assertion** — `expected_in:["ეხმარება"]` on the LLM-composed screen-concern reply flakes (~80% pass). Candidate to broaden to an OR-group („ეხმარება"/„მუშაობს"/„გამოდის") in `scenario_library.py` in a future scenario-calibration pass (NOT a code-fix task).
- **ADULT subscription Sheet-subscriber audit** (READ-ONLY, broadcast incident) · final live smoke (parent booking/reschedule, adult event list, adult subscription, comment #camp/#event/specific) · Meta client transfer · WhatsApp · Railway env sync. **Do NOT mark production green.**

---

## Post-audit fixes — ADULT Subscription Confirmation + Write (2026-06-11)

Status: **1915 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **22/22 ✅** re-run this session after the fix (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3). ⚠️ **NOT production-approved.**

> **Audit finding (PART 1):** `adult_subscription_service.is_subscription_consent_phrase` was defined but **called from nowhere** — the wiring (`_consent_phrase_matches`) was removed in the rolled-back Guardrails patch (2026-06-09). The deterministic UNSUBSCRIBE short-circuit existed in `run_adult_llm_turn`; the SUBSCRIBE path did not. `Conversation.adult_subscription_status` documented an `"asked"` value but **nothing set it** → no pending-offer state. So subscription depended 100% on the stochastic LLM calling `subscribe_to_adult_event_updates`. The Sheets write never FAILED — the service was never CALLED. (BUG 1: „კი გამომიგზავნეთ" → LLM off-topic redirect. BUG 2: „ჩამწერეთ სადმე…" → LLM acknowledged, no tool call, implied success.)

### ✅ Shipped + tested — ADULT Subscription Confirmation + Write (+42 tests incl. 6 adversarial-review regressions, 1873 → 1915)
- ✅ **Deterministic subscription layer** in `adult_llm_engine.run_adult_llm_turn` (after unsubscribe + parent-switch, before off-topic guard + LLM): `_has_pending_subscription_offer` (status `"asked"` OR last assistant turn = offer via `_is_subscription_offer_question`, keyed on subjunctive „გამოგიგზავნოთ"), `_is_subscription_consent` (two tiers: Tier 1 unambiguous send/notify verbs on the broad pending signal; Tier 2 whole-token short affirmations + PURE „მინდა" only when the offer was the *immediately-preceding* turn — hardened per adversarial review so „ბილეთი მინდა" never subscribes and a stale „asked" marker can't), `_is_direct_subscription_intent` (subscribes with no pending offer), `_deterministic_subscribe` (writes via `AdultToolExecutor`, confirms only after a written row).
- ✅ **Adversarial multi-agent review run on the diff** — 2 confirmed medium findings (bare „მინდა" substring false-positive; stale-marker window), both fixed before finalising and covered by 6 new regression tests.
- ✅ **Honest confirmation** — success „ჩაგწერეთ სიაში…"; already-subscribed „თქვენ უკვე ხართ სიაში…" (no duplicate row); missing name/phone → asks + keeps offer pending + no write; `sheets_save_failed`/error → „…ტექნიკურად ვერ მოხერხდა. მენეჯერს გადავცემ და შეგატყობინებთ." Sanitiser safety net `_strip_false_subscription_success` strips invented success claims from the LLM path when no confirmed write this turn (per-turn flag `adult_subscription_confirmed_for_conversation` in `adult_tool_executor`).
- ✅ **Sheet row** — status=subscribed, consent=TRUE, platform + sender_id + age (from lead) written via the existing `sheets_service.save_event_subscriber` upsert (no schema change; no duplicate on re-consent).
- ✅ **Broadcast safety** — subscription calls only `subscribe` → `save_event_subscriber`; never `broadcast_event` / `messenger_service.send_message`. Works with `LIVE_BROADCAST_ENABLED=false`. Unsubscribe path unchanged. ADULT prompt NOT changed (no broad prompt polish before the production smoke).
- ✅ **Verification:** pytest **1915 passed, 0 failed**; `test_agent.py` green; adult-subscription (73) + adult-engine + broadcast-safety + live-polish suites all green.

### ⏳ STILL OPEN (carried into the next session)
- ✅ ~~Confirmatory CRITICAL run~~ — done this session, **22/22 clean**.
- **Broadcast-incident follow-up (READ-ONLY):** audit the live `events` subscribers tab for recipients of the erroneous DM + stray `future_ev` / `Notified Event IDs` artifacts.
- Final live smoke (PARENT booking + reschedule, adult event list, **adult subscription**, comment routing #camp/#event/specific-tag); Meta client transfer; WhatsApp; Railway env sync; production smoke. **Do NOT mark production green.**

---

## Post-audit fixes — Broadcast Safety + PARENT Reschedule (2026-06-11)

Status: **1873 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **22/22** clean (Meta mocked — no real DMs). ⚠️ **NOT production-approved.**

### 🚨 Broadcast Safety Incident + Fix (+8 tests)
- **Incident:** a real Messenger DM reached a subscriber during patch work. **Root cause:** `tests/test_adult_event_past_filtering.py::test_broadcast_allows_future_event_resolution` called the REAL `broadcast_event` without mocking `sheets_service.list_event_subscribers` / `messenger_service.send_message` → on a dev box with live creds it read the real `events` tab and sent. The „15 ივნისი / ლისი / https://x/future" payload was the TEST FIXTURE (`now+5d`), not the real Admin `summer_fest` (28 აგვისტო, min_age 19) — so production source resolution is correct.
- **Fix:** new `LIVE_BROADCAST_ENABLED` flag (default **False**) → `broadcast_event` DRY-RUN unless explicitly enabled; `source` logged; all broadcast tests mock the transport; `kill_switch_on` fixture enables the flag so the 31 send-path tests still test the logic (mocked). After-save broadcast remains gated on the operator checkbox.

### ✅ PARENT Reschedule State + Segment Override (+25 tests)
- Live Redis audit (key `conversation:messenger:<id>`, ~7d TTL, child_age=14/name/phone/pending-reschedule persisted): state persistence WORKS; bugs were per-turn ROUTING.
- `conversation_service._is_parent_consultation_intent` flips sticky-ADULT→PARENT on consultation/reschedule signals; `parent_flow._strip_redundant_age_question_if_known` (never re-ask known age); `parent_flow._repair_colloquial_hour_rejection` forces the deterministic slot check on PM-normalized time (8→20:00). Weekend rule confirmed correct in `is_within_business_hours` (13/14 June = Sat/Sun).
- No Calendar / Sheets-schema / email / webhook / OpenAI-model / prompt-section change.

### ⏳ STILL OPEN (carried into the next session)
- ✅ ~~NEXT TASK — ADULT subscription confirms but does NOT save.~~ RESOLVED 2026-06-11 — see the "ADULT Subscription Confirmation + Write" section at the top of this file.
- **Broadcast-incident follow-up (READ-ONLY):** audit the live `events` subscribers tab for recipients of the erroneous DM + stray `future_ev` / `Notified Event IDs` artifacts.
- Final live smoke (PARENT booking + reschedule, adult event list, adult subscription, comment routing #camp/#event/specific-tag); Meta client transfer; WhatsApp; Railway env sync; production smoke. **Do NOT mark production green.**

---

## Post-audit fixes — Adult Event Date Filter Patch (2026-06-10)

Status: **1840 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL (real OpenAI): every scenario passes in isolation; per-sweep flakes (SC-11/SC-12/SC-46 across runs) are LLM stochasticity on PARENT booking/difficult scenarios this ADULT-only patch does NOT touch. ⚠️ **NOT production-approved** — full live booking + adult subscription + comment-routing smoke still pending.

> **Audit finding:** `get_active_adult_events` filtered ONLY by `active` (+ optional `min_age`) — **no date comparison anywhere**. A past-dated active event would surface in the adult DM list, generic `#event` comment DM, specific resolver, number selection, and broadcast. NOT a Calendar issue.

### ✅ Shipped + tested — Adult Event Date Filter (2026-06-10, +29 tests, 1811 → 1840)

- ✅ **Future-only chokepoint** — `admin_config_service.get_active_adult_events(user_age=None, *, include_past=False, now=None)` excludes past + non-empty-unparseable-date events by default. New `is_adult_event_past` + `_adult_event_visible_to_public` + `_parse_adult_event_datetime` (granularity time/date/month; „DD <month> [HH:MM]" / „<month>" / „2026 წლის ივლისი"; stem/typo-tolerant; explicit-year honoured; current-year w/ >180d Dec→Jan rollover).
- ✅ **Specific past event → ended message, no ticket link** — comment resolver reason `past_event` + `_build_past_event_dm`; executor `_get_adult_event_details` reason `event_past` + prompt rule.
- ✅ **Broadcast blocks past events** — `broadcast_event` reason `event_past` (manual / after-save / subscription) + Admin Panel operator message.
- ✅ **Empty date shows; Admin Panel internal view unchanged; PARENT/Calendar/Sheets/email/webhook/OpenAI-model/WhatsApp/Railway untouched.**
- ✅ **29 new tests** (`tests/test_adult_event_past_filtering.py`); 1 stale-date test updated (`test_generic_adult_event_comment_list.py`).
- ✅ **Verification:** pytest **1840 passed, 0 failed**; `test_agent.py` green; CRITICAL scenarios all pass in isolation (booking 3/3, happy_path 6/6, comment 1/1, security 3/3 confirmed across runs).

### Process / scope
- CRITICAL was run (this patch touches adult routing/tool core) as a safety check; the 22 CRITICAL scenarios contain no ADULT-event-list coverage, so the run confirms PARENT/comment/security are intact. No PARENT booking / Calendar / Sheets schema / email / webhook / OpenAI-model change. Design note: non-empty-unparseable date_text is hidden (rule 6) but not reported „ended"; common legitimate formats all parse; „all past" uses the existing no-events fallback.

### ⏳ STILL OPEN (blockers before production)
- ⏳ Full live PARENT booking smoke (create path), adult subscription smoke, comment-routing smoke, Meta client asset transfer, WhatsApp live credentials, Railway deploy + env.
- **Do NOT mark production green** until the final live smoke confirms: Calendar event + Sheet row + manager email + adult subscription + comment routing.

---

## Post-audit fixes — Georgian Colloquial Time Patch (2026-06-10)

Status: **1811 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **22/22** clean (real OpenAI; booking 3/3 — the earlier 21/22 was SC-01 stochasticity, passes 2/2 isolated, no time content). ⚠️ **NOT production-approved** — full live booking + adult subscription + comment-routing smoke still pending.

> **Live finding:** the same colloquial hour was parsed inconsistently across accounts — „12 ივნის 8 საათზე" → 20:00 (correct) but „12 ივნის მინდა 8 სათზе" (typo + „მინდა") → 08:00/outside-hours. Root cause: the PM heuristic lived only in the legacy router; the engine path left the hour to the stochastic LLM and no parser supported the typo „სათზე". NOT a Calendar issue.

### ✅ Shipped + tested — Georgian Colloquial Time (2026-06-10, +43 tests, 1768 → 1811)

- ✅ **Deterministic single source of truth** — `timestamps.extract_colloquial_hour` / `apply_colloquial_time_to_iso`: unqualified 1–9 → +12 (13:00–21:00); 10/11/12 literal; „დილ…"(morning) literal; „საღამო…"(evening) 1–11 → +12; explicit HH:MM literal. Typo-tolerant: საათზე / **სათზე** / საათი / საათისთვის / სთ / სთ-ზე / **8-ზე** / 8ზე. Bare hour trusted only with a morning/evening qualifier (guarded vs „N წლის").
- ✅ **Applied at the booking chokepoint** — `parent_tool_executor._normalise_datetime_iso_from_message` (check_consultation_slot + book_consultation + reschedule) runs the colloquial-hour pass after the relative-day override, so the hour is correct regardless of contact/booking state and independent of the LLM.
- ✅ **Legacy router parity** — `parent_turn_router._parse_booking_datetime` delegates to the shared parser (compound-booking fallback consistent).
- ✅ **43 new tests** (`tests/test_georgian_colloquial_time_parsing.py`) — 14 spec cases + variants, morning/evening, HH:MM literal, age-phrase guard, executor chokepoint, router parity.
- ✅ **Verification:** pytest **1811 passed, 0 failed**; `test_agent.py` green; CRITICAL **22/22** clean.

### Prompt bloat audit (Part 5)
- `system_parent_v2.md` = 108,632 bytes ≈ **36K chars** (Georgian ≈ 3 bytes/char), 446 lines. Engine prompt-size cap test asserts `< 48,000 chars` → PASS (~12K headroom).
- Time parsing is now **code-backed** (was prompt-only / LLM-inferred for the hour). The prompt has NO explicit colloquial-PM rule (only examples), which is why the LLM was inconsistent.
- **Prompt NOT cleaned**: its time rules also cover business-hours / half-hour / relative-dates / slot-selection (not all code-backed), and the LLM still composes the spoken reply — deleting guidance risks a spoken/checked mismatch. Per the task guard, no section was removed.

### Process / scope
- No Calendar service, Sheets schema, adult events, comment routing, webhooks, OpenAI model, or SMTP change. No Guardrails/token-waste reintroduction; no prompt deletion.

### ⏳ STILL OPEN (blockers before production)
- ⏳ Full live PARENT booking smoke (create path) — Calendar event + Sheet row + manager email end-to-end.
- ⏳ Adult subscription smoke, comment-routing smoke, Meta client asset transfer, WhatsApp live credentials, Railway deploy + env.
- **Do NOT mark production green** until the final live smoke confirms: Calendar event + Sheet row + manager email + adult subscription + comment routing.

---

## Post-audit fixes — Email Content Cleanup Patch (2026-06-10)

Status: **1768 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL NOT re-run (email-content formatting only; no booking/engine/Calendar/Sheets logic touched). ⚠️ **NOT production-approved** — full live booking + adult subscription + comment-routing smoke still pending. Manager email notification **arrives** (SMTP live-verified 2026-06-10).

### ✅ Shipped + tested — Email Content Cleanup (2026-06-10, +18 tests, 1750 → 1768)

- ✅ **Raw chat/filler removed from „ინტერესი / გამოწვევა"** — `notification_service._clean_challenge_for_email` splits the raw challenge on commas/„ასევე", drops factual-question clauses, strips filler („ასევე მაინტერესებს" / „მაინტერესებს" / „კი მინდა" / „ჩაწერა მინდა" / „კონსულტაცია მინდა" / „დეტალები" / „მომწერეთ" / „პირობებში რა იგულისხმება" / …), canonicalises ეკრან-variants → „ეკრანთან დროის შემცირება", dedupes. Live: „…ასევე ეკრანიდან დისტანცია, ასევე მაინტერესებს … როდის ტარდება" → „მეგობრები, განვითარება, ეკრანთან დროის შემცირება".
- ✅ **Factual question split out** — `_extract_additional_question` surfaces it on an optional „დამატებითი კითხვა:" line; never mixed into goals.
- ✅ **Clean, non-duplicated summary** — `_build_parent_summary` weaves in cleaned goals, never raw chat text.
- ✅ **Unknown challenge → „არ არის მითითებული"** (never invented). `lead.challenge` NOT mutated (Sheets/CRM unaffected).
- ✅ **18 new tests** (`tests/test_manager_email_content_cleanup.py`); 29 existing wording + 13 notification tests still pass (inline „label: value" layout preserved).

### Process / scope
- No Calendar service, Sheets schema, adult events, comment routing, webhooks, OpenAI model, SMTP config, or booking-flow change. Email-rendering helpers only.

### ⏳ STILL OPEN (blockers before production)
- ⏳ Full live PARENT booking smoke (create path) — Calendar event + Sheet row + manager email end-to-end.
- ⏳ Adult subscription smoke, comment-routing smoke, Meta client asset transfer, WhatsApp live credentials, Railway deploy + env.
- **Do NOT mark production green** until the final live smoke confirms: Calendar event + Sheet row + manager email + adult subscription + comment routing.

---

## Post-audit fixes — Live Smoke Followup Patch (2026-06-10)

Status: **1750 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **22/22** clean (real OpenAI). ⚠️ **NOT production-approved** — full live booking create-path smoke still pending.

> **Live finding:** busy-slot rejection **worked live** — `11 ივნისს 16:00` correctly detected unavailable (overlaps the real busy block 13:15–17:45), `18:00` offered free. Two booking-confirmation wording bugs remained and are fixed in this patch.

### ✅ Shipped + tested — Live Smoke Followup (2026-06-10, +33 tests, 1717 → 1750)

- ✅ **Confirmation + extra question now books (no re-ask)** — `parent_llm_engine._user_confirmed_booking` matches a strong confirmation phrase at the start of the leading clause (`_STRONG_CONFIRM_LEAD_PHRASES`) with a negation guard, in addition to whole-message exact match. `_BOOKING_OFFER_STEMS` extended with the real offer wording („ჩავნიშნავ"/„დამიდასტურეთ"/„თავისუფალია"). The „proceed directly to booking, don't re-ask" sales-context hint now fires for „კი მაწყობს ეს დრო, მენეჯერი რომელ საათამდე მუშაობს?".
- ✅ **„მადლობა თქვენ" only on real thanks** — `parent_flow._strip_unwarranted_thanks_in_booking_confirmation` strips the opener from a booking confirmation when the user's message has no thanks token; preserved when the user actually thanked.
- ✅ **Cleaner goal/challenge capture** — eligible-age sales-context hint asks one clean goal question when `lead.challenge` is empty, never blocks an explicit booking, and stops re-asking once known. Per-turn context hint only — `system_parent_v2.md` untouched (48 KB prompt-size cap test unaffected).
- ✅ **33 new tests** (`tests/test_parent_booking_live_smoke_followup.py`).
- ✅ **Verification:** pytest **1750 passed, 0 failed**; `test_agent.py` green; CRITICAL **22/22** clean.

### Process / scope
- No Calendar service, Sheets schema, email/SMTP, adult events, comment routing, webhook, or OpenAI-model change. No broad prompt polish; no system-prompt edit; no Guardrails/token-waste reintroduction.

### ⏳ STILL OPEN (blockers before production)
- ⏳ **Full live PARENT booking smoke (create path)** — busy-slot rejection confirmed live; the remaining check is that a real confirmation creates the Calendar event + Sheet row + fires the manager email.
- ⏳ **Manager email end-to-end** — `MANAGER_EMAIL` corrected; standalone SMTP send verified 2026-06-10; booking→email path not yet confirmed.
- ⏳ Meta client asset transfer, WhatsApp live credentials, Railway deploy + env.
- **Do NOT mark production green** until the final live smoke confirms: Calendar event + Sheet row + manager email + adult subscription + comment routing.

---

## Post-audit fixes — P0 Stabilization Patch (2026-06-09)

Status: **1717 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL **22/22** on a clean real-OpenAI run AFTER the P0 fix (`happy_path 6/6` with SC-06 stable, `booking 3/3`); SC-06 re-run isolated **5/5 PASS**. ⚠️ **NOT production-approved** — live PARENT booking through real Meta still pending (see below).

> **Audit context:** a full system regression audit (2026-06-09) found CRITICAL had silently drifted to **21/22** — the flaky scenario was **SC-06 "Ineligible Age — 8 წლის"** (~40% pass), while the docs claimed 22/22. The Calendar backend was **live-verified working** (read-only FreeBusy correctly flagged a real busy block; `check_consultation_slot` + `book_consultation` both re-check; a busy slot cannot be booked). The reported "busy slot still bookable" issue did NOT reproduce at the backend level. This patch fixes SC-06 and corrects the docs.

### ✅ Shipped + tested — P0 Stabilization (2026-06-09, +22 tests, 1695 → 1717)

- ✅ **SC-06 ineligible-young stabilized** — new deterministic `parent_flow._ensure_ineligible_young_age_message()` (wired after `_strip_consultation_cta_if_ineligible`). On the disclosure turn where the parent states a child age `< age_min`, the reply is replaced with a fixed message stating the 9–17 range, declining the booking, and offering the manager. Root cause: the old scrubber only appended the manager-handoff line when a booking CTA was present, so a CTA-free-but-vague LLM reply slipped through and failed `("9" OR "ასაკი") AND "მენეჯერ"`.
- ✅ **Scope guard** — `age < age_min` only. Over-age 18+ untouched (SC-07 unaffected); eligible 9–17 pass through; bounds read from `camp_2026.yaml`.
- ✅ **22 new tests** (`tests/test_ineligible_young_age_p0.py`): under-min 3–8 → canonical; eligible 9/10/14/16/17 + boundary 9/17 pass-through; over-age 18/25/40 pass-through; unknown pass-through; no over-fire on thank-you / time message; re-fires if age restated; e2e engine-mocked to the SC-06 failure mode.
- ✅ **Verification:** pytest **1717 passed, 0 failed**; `test_agent.py` green; SC-06 isolated **5/5**; CRITICAL **22/22** clean (one earlier sweep showed 21/22 due to a transient OpenAI **429 TPM rate-limit** on SC-12 — SC-12 passes isolated and in the clean re-run; not a regression).

### ⚠️ Process warning
- **Do NOT add broad prompt-polish patches before the live production smoke.** A prior broad Guardrails/token-waste polish caused a live PARENT booking regression (rolled back 2026-06-09). Keep changes narrow, deterministic, test-gated.

### ⏳ STILL OPEN (blockers before production)
- ⏳ **Live PARENT booking through real Meta — NOT verified.** Backend correct; the open question is whether the LLM calls `check_consultation_slot` before stating "თავისუფალია". Run the booking-conflict smoke (HANDOFF / CLAUDE) before any go. **Do NOT mark production green until it passes.**
- ⏳ Railway deploy, Railway env, Meta App Review, WhatsApp live test, client production setup — all unchanged.
- ⏳ Guardrails redesign postponed until after production smoke. Adult follow-up scheduler postponed.

---

## Post-audit fixes — Live Polish Patch (2026-06-09)

Status: **1695 passed, 0 failed** (`pytest tests/ -q`) at the time of that patch. `test_agent.py` ✅ green. (Superseded by the P0 Stabilization status above.) No Calendar / Sheets / webhook / auth logic changed.

### ✅ Shipped + tested — Live Polish (2026-06-09, +27 tests, 1668 → 1695)

- ✅ **"კიმინდა" normalized as confirmation** — joined form added to `_BOOKING_CONFIRMATION_PHRASES` and Booking Intent Flow CRITICAL block.
- ✅ **No repeated consultation confirmation after user says yes** — `_last_bot_offered_booking()` + `_user_confirmed_booking()` + `_build_sales_context()` injection; system prompt rule added.
- ✅ **Phone request always includes privacy wording** — new "კონტაქტ-ინფო კონფიდენციალობის წესი" section in `system_parent_v2.md`; privacy sentence mandatory on every phone ask (name-known / name-unknown variants).
- ✅ **"მიხარია ნომრის მიღება" removed** — 2 new sanitiser entries → "ნომერი მივიღე".
- ✅ **Standalone "სიამოვნებით." stripped** — banned in PARENT and ADULT sanitisers; system prompt specifies context-aware closings.
- ✅ **Context-aware thank-you closings** — `_user_said_thanks()` + updated `_build_sales_context()`; system prompt "მადლობის წესი" updated with specific examples and "სიამოვნებით." ban.
- ✅ **27 new tests** (`tests/test_live_polish_booking_wording.py`).
- ✅ **Prompt size cap raised 46 KB → 48 KB** (`test_parent_llm_engine.py`).

### ⏳ STILL OPEN (all unchanged from previous patch)
- ⏳ Railway deploy, Railway env, Meta App Review, WhatsApp live test, client production setup.
- ⏳ Guardrails redesign postponed until after production smoke test.
- ⏳ Adult follow-up scheduler.

---

## Post-audit fixes — Client Smoke Regression Patch (2026-06-09)

Status: **1668 passed, 0 failed** (`pytest tests/ -q`). `test_agent.py` ✅ green. CRITICAL 22/22 (re-run 2026-06-09). Google Sheet append ✅ LIVE VERIFIED. Google Calendar create+delete ✅ LIVE VERIFIED.

### ✅ Shipped + tested — Client Smoke Regression (2026-06-09, +28 tests, 1640 → 1668)

- ✅ **Booking Intent Flow CRITICAL block** (`system_parent_v2.md`). After "კი მინდა" / "ჩამწერეთ" / other booking confirmations, goal is `book_consultation` (Calendar event). Two paths documented: slots-first or name/phone-first. FORBIDDEN: calling `request_manager_callback` after collecting contact info without a selected slot.
- ✅ **Contact Info CRITICAL block** (`system_parent_v2.md`). "Phone + name text" in same message (e.g., "595999733 ნიკა") is valid — backend parser extracts phone automatically; LLM must NOT say "ნომერი სწორად ვერ ამოვიკითხე". If `name=X` is in context and X ≠ "—", name is already known; phone alone completes contact info.
- ✅ **"კომპიუტერის მეხსიერების" phrase banned** (`parent_llm_engine.py`). 4 new sanitiser entries strip "კომპიუტერის მეხსიერების მიხედვით" and "ჩემი მეხსიერების მიხედვით" (LLM hallucination); replaced with "ამ ეტაპზე".
- ✅ **28 new regression tests** (`tests/test_parent_client_booking_smoke_regression.py`). Covers: phone parser (phone-first and name-first order, 10 tests); bad phrase banned (4 tests); system prompt CRITICAL blocks present (6 tests); "კი მინდა" calls `get_available_slots` (2 tests); phone-only accepted when name known (2 tests); no fake-booking without Calendar success (2 tests); baseline sanity (2 tests).
- ✅ **Prompt size cap raised 44 KB → 46 KB** (`test_parent_llm_engine.py`). Accommodates ~1.6 KB of new policy text.
- ✅ **Root causes verified**: `_parse_name_phone("595999733 ტესტ")` → ("ტესტ", "595999733") — parser was always correct; "ნომერი სწორად ვერ ამოვიკითხე" was LLM hallucination from the system prompt example, not a parser bug. No service code changes needed.
- ✅ **Google integration LIVE VERIFIED 2026-06-09**: Sheet append `create_lead()` ✅; Calendar `create_event()` + `cancel_calendar_event()` ✅ — both work with client credentials.

## Post-audit fixes — Guardrails Patch ROLLED BACK (2026-06-09)

Status before rollback: **1727 passed** → rolled back → **1640 passed, 0 failed**.

### ❌ ROLLED BACK — Guardrails Patch (shipped and reverted 2026-06-09)

- ✅ **Scolding / defensive phrase ban** (Fix 1, both engines). 15 entries added to `FORBIDDEN_PHRASE_REPLACEMENTS` (PARENT) and `ADULT_FORBIDDEN_PHRASE_REPLACEMENTS` (ADULT). Phrases stripped to `""`: "უკანასკნელად გითხარით" / "როგორც უკვე გითხარით" / "ამაზე უკვე გიპასუხეთ" / "ამ კითხვაზე უკვე გიპასუხეთ" / "უკვე გიპასუხეთ" / "ეს ზემოთ ვთქვი" / "ზემოთ ვახსენეთ" + 8 variant forms. Sanitiser is idempotent; surrounding sentence context preserved.
- ✅ **Direct manager handoff** (Fix 2, both engines). New `_is_explicit_manager_request()` / `_parent_is_explicit_manager_request()` helpers with 15 closed-set Georgian phrases (მინდა მენეჯერი, მენეჯერის ნომერი, ადამიანთან ვისაუბრო, ნომერი მომეცი, …). Injected as pre-LLM check in both `run_adult_llm_turn` and `run_parent_llm_turn`. When matched, returns `"მენეჯერი: {phone}"` directly (sourced from `admin_config_service.get_manager_phone()`, hardcoded fallback `558 67 47 33`). No OpenAI call, no tool invocation. First-turn only — follow-up turns with contact info still invoke the tool normally. Existing test `test_manager_request_without_phone_does_not_notify` updated to match new direct-phone behavior.
- ✅ **Adult subscription clarification** (Fix 3). New "სუბსქრიფციის vs კონკრეტულ ღონისძიებაზე რეგისტრაციის განსხვავება — CRITICAL" block in `system_adult_v1.md`. Agent must: (a) never claim specific-event registration unless ticketing/payment confirmed it; (b) when subscribed user asks to register for a specific event, clarify that subscription = future notifications only, then provide link (`provide_adult_reservation_link`) or manager phone (`558 67 47 33`). Manager phone documented directly in prompt.
- ✅ **Token waste / low-value message guard** (Fix 4, both engines). Deterministic pre-LLM guard in both `run_adult_llm_turn` and `run_parent_llm_turn`. Catches: empty / whitespace, single-char, exact low-value strings (კაი, კარგი, გასაგებია, მადლობა, ოკ), emoji-only, repeated message (matches previous user turn in history). Returns canned ack without OpenAI call. Safety valve — guard skips when: (a) the last assistant turn contained `?` (protects consent / slot questions); (b) PARENT `conversation.pending_booking` is set. Acknowledged trade-off: `"კარგი"` after a bot statement with no `?` is treated as low-value even if user meant "proceed". Accepted.
- ✅ **Consent false-positive fix** (Fix 5, `adult_subscription_service`). New `_STANDALONE_CONSENT_TOKENS` frozenset (`{"კი", "ok", "yes"}`) + `_consent_phrase_matches(phrase, lowered)` with word-boundary checking (character before + after must not be `isalpha()`). `is_subscription_consent_phrase` now uses it. "კი" in "კიდევ ერთი კითხვა მაქვს" no longer triggers consent. Standalone "კი", "კი, მინდა", "ნამდვილად კი" still match. Multi-word / longer phrases use plain substring match (unchanged).

**Reason for rollback:** Live PARENT booking regression. `"კონსულტაციის ჩანიშვნა მინდა ბანაკთან დაკავშირებით"` triggered qualification questions instead of the booking flow. Pre-LLM guards introduced hidden interactions with PARENT flow state machine. Rolled back before client production setup.

**What was reverted:** 15 scolding phrases removed from both sanitiser tables; `_is_explicit_manager_request` / `_parent_is_explicit_manager_request` helpers and pre-LLM manager-shortcut + low-value-guard checks removed from both engines; `_STANDALONE_CONSENT_TOKENS` / `_consent_phrase_matches` removed from `adult_subscription_service`; Guardrails CRITICAL block removed from `system_adult_v1.md`; `tests/test_guardrails_token_waste.py` deleted; `test_manager_request_without_phone_does_not_notify` assertion restored to `"ნომერ" in out`.

### ⏳ STILL OPEN
- ⏳ **Client production setup** — client Google Sheet, Calendar, email, WhatsApp, Facebook Page / Instagram — currently tester values. **NEXT PRIORITY.**
- ⏳ **Local smoke test with client resources** — pending client config being in place.
- ⏳ **Railway deploy** — not deployed.
- ⏳ **Railway env setup** — `INSTAGRAM_APP_SECRET`, `INSTAGRAM_ACCESS_TOKEN`, `META_APP_SECRET`, Google credentials, `REDIS_URL`, WhatsApp tokens pending.
- ⏳ **Railway smoke test** — gated on Railway deploy.
- ⏳ **Meta App Review** — `pages_manage_engagement` pending.
- ⏳ **WhatsApp live test** — pending real credentials.
- ⏳ **Adult follow-up scheduler** — `followup_service` still short-circuits for `segment == "ADULT"`.
- ⏳ **Dead code / `.gitignore` / `requirements-dev` / v18→v19 / `mask_sender`** — ~1 hour quick-fixes, carried from Session 1 audit.
- ⏳ **Guardrails redesign** — scolding-phrase ban, manager handoff, low-value guard, subscription clarification — postponed to after production smoke test; redesign as smaller isolated patches.

---

## Post-audit fixes — Session 9-12 (2026-06-08 → 2026-06-09, latest)

Status snapshot for the eight patches shipped after the Session 8 wave. Test count progressed 1350 → 1402 → 1411 → 1442 → 1465 → 1520 → 1593 → 1615 → 1640. Two items are **LIVE VERIFIED** by operator on 2026-06-09 (Adult Event Subscription + Broadcast; Instagram Webhook Signature). The previously open **CURRENT LIVE BUG** (generic `#event` no-active-list fallback) is now resolved — pending live operator verification.

### ✅ Shipped + tested

- ✅ **Admin Panel multi-event** (+52 tests, 1350 → 1402). Multi-event editor at `/admin/programs/adult_events/events` with add / edit / activate / deactivate. `adult_events.events[]` is source of truth. `_normalize_adult_event` preserves description / facebook_post_id / tags / price_gel / payment_terms. New `update_adult_event`, `deactivate_adult_event`, `activate_adult_event`.
- ✅ **Admin Panel adult event add / edit / deactivate** (subset of above). Per-row deactivate (status=inactive) without losing the row; activate flips it back. Hard delete still available separately.
- ✅ **Admin Panel UI visibility fix** (+9 tests, 1402 → 1411). Programs list shows green "ღონისძიებების მართვა" button next to adult_events Edit; section-form blue banner linking to the events manager; "← Programs" back-link on events list.
- ✅ **Adult sold-out hallucination fixed** (part of +31 tests, 1411 → 1442). Operator-flagged `sold_out: true` or `status: sold_out` required before agent says „ადგილები ამოწურულია". Per-conversation `adult_sold_out_disclosed_for_conversation` flag; sanitiser strips invented sold-out copy sentence-level when flag not set. Compact event payload omits `seats_available` when zero (so LLM cannot read 0 as "empty").
- ✅ **Adult reservation / ticket link fixed** (part of +31). `_get_adult_event_details` payload now surfaces `reservation_url` + `payment_terms` directly alongside `has_reservation_url`. LLM includes the link inline on unique match. Missing link → manager-handoff line.
- ✅ **Adult partial title matching fixed** (part of +31). New `_GEORGIAN_NOUN_SUFFIXES` + `_stem_token_for_match` + `find_adult_events_matching` with priority exact-id → exact-title → casefolded-substring (≥3 chars) → stem-overlap. „ქართული პოეზია" now matches „ქართული პოეზიის საღამო". Multi-match returns `ambiguous_event` reason for LLM clarification ask.
- ✅ **Adult price hallucination fixed** (+23 tests, 1442 → 1465). Executor compact + details payloads surface `price_gel` (positive only) alongside `price_text`. New `adult_price_disclosed_for_conversation` flag mirrors the sold-out pattern. Sanitiser strips invented "price missing" copy ONLY when flag set. New prompt rule "ფასის რენდერინგის წესი" formalises decision tree (price_text → numeric → " ლარი" suffix; price_gel fallback; canonical missing only when both blank).
- ✅ **Comment → Specific Event Mapping** (+55 tests, 1465 → 1520). New `resolve_specific_adult_event` with Priority A (`facebook_post_id` exact) → B (event tag in comment) → C (event tag in caption, soft-fail on Meta errors) → D (no_match) → E (ambiguous). `send_dm_from_comment` tries specific-event branch before falling through to existing generic ADULT rich DM. New `_build_specific_adult_event_dm` renders title / date / location / price / description / link. **Live-verified 2026-06-09 by operator: `#event #fast` sends the exact "fast" event.**
- ✅ **Broad comment interest detection** (part of +55). New deterministic `is_interest_intent(comment_text)` matches 30+ Georgian + English broad-interest keywords (ფასი, ბმული, სად ტარდება, ბილეთი, რეგისტრირდე, price, link, where, when, register, …). Called BEFORE the LLM in `handle_comment`; LLM only consulted when no keyword match.
- ✅ **Camp broad-interest comment routing** (part of +55). Same `is_interest_intent` shortcut benefits camp #ბანაკი comments. „ფასი?" / „სად ტარდება?" under #ბანაკი now route through the existing camp DM via the keyword shortcut.
- ✅ **Adult event subscription + broadcast** (+73 tests, 1520 → 1593). **LIVE VERIFIED 2026-06-09 by operator: a newly created adult event was successfully broadcast to a subscribed user via Messenger DM.**
- ✅ **Sheets `events` tab** (part of +73). New 18-column events tab in Google Sheets (Created At, Updated At, Platform, Sender ID, Name, Phone, Status, Consent, Consent At, Source Event ID/Title/Link, Age, Last Notified Event ID, Last Notified At, Notified Event IDs, Unsubscribe At, Notes). Created on first write. Upsert by (platform, sender_id); partial updates preserve `Notified Event IDs`.
- ✅ **New event full-card broadcast** (part of +73). `build_broadcast_message` renders title + date + location + price (per ADULT price rule) + description + ticket link + unsubscribe footer. Skips missing fields. Sold-out banner only when operator-flagged.
- ✅ **Broadcast duplicate prevention** (part of +73). Dual-layer: caller-side `event_id in subscriber.notified_event_ids` check BEFORE send, AND `mark_event_subscriber_notified` re-checks and returns `(False, "duplicate")` if already present. Re-run yields 0 sends, `skipped_duplicate=N`.
- ✅ **Unsubscribe** (part of +73). Deterministic phrase detection BEFORE the LLM in `adult_llm_engine` for „აღარ გამომიგზავნოთ" / „აღარ მინდა შეტყობინებები" / „გამთიშეთ" / „unsubscribe" / „stop". Calls `adult_subscription_service.unsubscribe`, stamps `Unsubscribe At`, returns canned confirmation.
- ✅ **Admin Panel manual broadcast button** (part of +73). Per-row green "გაგზავნა subscribed მომხმარებლებთან" button on the events list. POST `/admin/programs/adult_events/events/{id}/broadcast` → renders results page with sent / skipped / failed counts and operator-friendly Georgian reason strings.
- ✅ **Admin Panel broadcast-after-save checkbox** (part of +73). Checkbox „შენახვის შემდეგ გაუგზავნე subscribed მომხმარებლებს" on create / edit event form (default off; only fires when checked AND event is active AND has link).
- ✅ **Instagram webhook signature** (+22 tests, 1593 → 1615). **LIVE VERIFIED 2026-06-09 by operator: added `INSTAGRAM_APP_SECRET` to local `.env`, restarted server, sent IG DM, observed `[webhook] signature accepted via instagram_app_secret` (no 403).** Multi-secret `_verify_meta_signature` tries Facebook first, falls back to `INSTAGRAM_APP_SECRET`. Returns `(accepted, label)` with privacy-safe labels.
- ✅ **Instagram privacy-safe diagnostics** (part of +22). New `_summarise_payload_fields(payload)` returns `{object, entries, fields, supported}` for a single log line. `_SUPPORTED_PAYLOAD_FIELDS` frozenset (`messaging`, `messages`, `changes`, `standby`). Unsupported fields produce `[webhook] instagram payload accepted but unsupported fields=[...]` warning + 200 OK (no retry-storm). NEVER logs: raw body, signature header, computed digest, app secrets, access tokens, sender ids, message text, phone numbers.
- ✅ **Instagram local/live DM response works after env setup** (operator-verified 2026-06-09). Agent responded to inbound IG DM via the existing handler routing once `INSTAGRAM_APP_SECRET` + `INSTAGRAM_ACCESS_TOKEN` were in local `.env`. Comment under Instagram post also passes signature.

### ✅ Shipped + tested — Generic `#event` → Active Adult Events List (2026-06-09, +25 tests, 1615 → 1640)

- ✅ **Generic `#event` comment now sends the active-events list when active events exist** (+25 tests, 1615 → 1640). New `_build_active_adult_events_list_dm()` helper in `comment_service.py` sources from `admin_config_service.get_active_adult_events()`, renders each event (title / date / location / price / link with the same `_format_event_price` rule as the specific-event DM), and substitutes the rendered block into the operator-editable `adult_events_comment_dm` template's `{events_list}` placeholder. Three-condition safety net guards against unrendered placeholder, missing template, or operator-mangled template (placeholder removed) — under no path does literal `{events_list}` reach the user.
- ✅ **Specific-event priority preserved** — Priority A (`facebook_post_id`) / B (event tag in comment) / C (event tag in caption) all run BEFORE the new list path in `send_dm_from_comment`. `#event #fast` still sends the exact „fast"-tagged event; `#event` alone sends the catalogue.
- ✅ **No fabricated schedule** — `_build_active_adult_events_list_dm()` returns `""` when no active titled events exist; caller falls through to the legacy `_build_adult_rich_dm()` → `ADULT_NO_EVENTS_DM` fallback. Inactive events excluded by `get_active_adult_events` `active=True` filter.
- ✅ **Platform-neutral** — works identically for Instagram and Facebook comments. Integration tests cover both private-reply paths.
- ✅ **Camp routing untouched** — PARENT segment still uses `_build_parent_rich_dm()`. Regression test asserts adult-event titles do not leak into camp DMs.
- ✅ **Legacy test helpers updated** — `_run_handle_comment` + `_run_handle_comment_for_platform` in `tests/test_comment_flow.py` now stub `admin_config_service.get_active_adult_events` to return `[]` so the existing 55 legacy comment-flow tests keep exercising the legacy `settings.EVENTS` fallback path explicitly.

### ⏳ STILL OPEN
- ⏳ **Railway deploy.** Not deployed.
- ⏳ **Railway env setup.** Production must include the secrets/tokens that unblocked the local live test: `INSTAGRAM_APP_SECRET`, `INSTAGRAM_ACCESS_TOKEN`, `META_APP_SECRET`, Google credentials, `REDIS_URL`, `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `MANAGER_WHATSAPP_NUMBER` when issued.
- ⏳ **Meta App Review.** `pages_manage_engagement` permission gating public comment replies.
- ⏳ **WhatsApp live test.** Pending real credentials.
- ⏳ **Client production setup.** Real client Google Sheet / Calendar / email / Meta assets — currently tester values.
- ⏳ **Adult follow-up scheduler.** `followup_service` extends to `segment == "ADULT"` with `adult_followup_24h` / `adult_followup_3d` / `adult_followup_7d` templates. Distinct from the shipped Adult Event Subscription Broadcast.

---

## Post-audit fixes — Session 7 + 8 + Follow-up (2026-06-06 → 2026-06-08, latest)

Status snapshot for everything shipped after the Session 4–7 wave. **Live-verified** items have an operator-driven smoke or screenshot confirmation.

| Item | სტატუსი | ვერიფიკაცია |
|---|---|---|
| **Reschedule pending state preserved across confirmation turn** | ✅ **Done + LIVE VERIFIED** | Session 7 LIVE QA Patch (2026-06-06). `_check_consultation_slot` marks `pending_booking["source"]="reschedule"` + stashes `old_event_id` + `old_booked_datetime_iso`. `_book_consultation` detects already-booked-at-different-time scenario via `_is_reschedule_scenario` and reroutes through `_reschedule_booking`. Operator-driven live test confirmed user's confirmation turn routes through the reschedule path, not a fresh booking. |
| **Old Calendar event cancelled after successful reschedule** | ✅ **Done + LIVE VERIFIED** | Safe-ordering preserved from Session 6 Bug 9 (book new → verify event_id → THEN cancel old). Session 7 reroute hooks the new booking into the same code path. Live test: old Calendar event verified deleted post-reschedule. |
| **Sheets consistency live verified** | ✅ **Done + LIVE VERIFIED** | Session 8 LIVE QA Patch (2026-06-07). `sheets_service.mark_old_booking_rescheduled(sender_id, *, new_status="Rescheduled")` targets the OLDEST sender_id row whose Status cell is `"Booked"`, leaves any LATER `"Booked"` row alone. Replaces legacy `update_lead(sender_id, ...)` matching. Operator screenshot (2026-06-07/08) confirmed old Sheets row → `Status="Rescheduled"`, current row → `Status="Booked"`. |
| **One active Booked row per sender live verified** | ✅ **Done + LIVE VERIFIED** | Same as above — operator screenshot on clean sender shows exactly one row with `Status="Booked"` after reschedule. |
| **Booking CTA removed (extra „თუ კიდევ რაიმე…", „თუ დამატებითი კითხვა გაქვთ…")** | ✅ **Done + LIVE VERIFIED** | Session 8 LIVE QA Patch (2026-06-07). `_BOOKED_NEW_BOOKING_CTA_PATTERNS` extended with the awkward post-booking CTA variants; `_strip_consultation_cta_if_booked` no longer auto-appends `_BOOKED_HELP_CTA`; `_BOOKING_SUCCESS_TRIM_PHRASES` mirrors the set for the immediate success turn. New `_DUP_TU_MIXED_PATTERN` collapses doubled mixed-verb clauses. Live response reads cleanly as „[date], [time] საათზე კონსულტაცია ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ.". |
| **WhatsApp credentials guard** | ✅ **Done + LIVE VERIFIED (skip path)** | Session 7. `_send_manager_whatsapp` early-returns with `[NOTIFICATION][WHATSAPP] Skipped: missing credentials (...)` when any of `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `MANAGER_WHATSAPP_NUMBER` is empty. No `httpx.post`, no traceback. Email channel stays independent. |
| **Email subject/body polish + challenge/interest dedupe** | ✅ **Done + LIVE VERIFIED** | Session 7. `_build_email_subject` returns „<name> — ახალი კონსულტაცია AI Agent-იდან" for booked leads with name; body headline branches on booking state; `_dedupe_repeated_phrase` collapses "X Y X Y" / "X X" patterns; `_build_parent_summary` weaves the deduped challenge into a short manager-friendly sentence. |
| **Flaky calendar weekend test fixed** | ✅ **Done** | Test Stability Patch (2026-06-06). `target_date = now_tbilisi() + 14 days` now advances past any weekend with a `while target_date.weekday() >= 5: target_date += timedelta(days=1)` loop. Test-side fix only — clean pytest baseline on every weekday. |
| **Follow-up test mode (FOLLOWUP_TEST_MODE + FOLLOWUP_FIRST_DELAY_SECONDS)** | ✅ **Done + LIVE VERIFIED** | Follow-up Test Mode + Live-QA Compatibility Patch (2026-06-06). `FOLLOWUP_ENABLED` master gate, `FOLLOWUP_TEST_MODE=true` + `FOLLOWUP_FIRST_DELAY_SECONDS=120` operator overrides. Override applies ONLY to the FIRST cadence step (24h); stages 2 (72h) + 3 (168h) NEVER overridden. Invalid override → silent fallback to production cadence. Mode banner per tick. **Production cadence remains unchanged** when test mode is off. Live verified end-to-end. |
| **Redis hydrate CLI for follow-up added (tools/run_followup_tick.py)** | ✅ **Done + LIVE VERIFIED** | Follow-up Live-Test Hydrate Patch (2026-06-06). `redis_state_service.scan_keys(pattern)` (non-blocking SCAN), `conversation_service.hydrate_from_redis()`, `tools/run_followup_tick.py` (`--dry-run` lists due / default sends). Enriched scheduler log: `[FOLLOWUP] scanning total=N parent=N with_marker=N` + `[FOLLOWUP] tick complete total=N due=N sent=N skipped=N`. CLI live verified to hydrate Redis and deliver PARENT follow-up via Messenger. |
| **PARENT follow-up live verified with Admin Panel template** | ✅ **Done + LIVE VERIFIED** | Operator-edited template text in `/admin/templates` (`followup_24h` / `followup_3d` / `followup_7d`) is read at send-time via `admin_config_service.render_template` and delivered through Messenger. Live test (2026-06-07/08) confirmed: edit template → wait 120 sec → trigger CLI tick → custom text delivered. |
| **Comment → Specific Event Mapping (broad interest detection + facebook_post_id / tag / caption priority cascade)** | ✅ **Done (2026-06-08, +55 tests, 1465 → 1520)** | New deterministic `is_interest_intent(comment_text)` (30+ Georgian + English broad-interest keywords; bypasses the LLM for short obvious comments). New `resolve_specific_adult_event(comment_text, post_id, platform)` returns `(event, candidates, reason ∈ {facebook_post_id, comment_tag, caption_tag, ambiguous, no_match})` — Priority A (`facebook_post_id`) → B (event tag in comment) → C (event tag in caption, soft-fail on Meta API errors) → D (no match) → E (ambiguous when 2+ events match). New `_build_specific_adult_event_dm` renders title / date / location / price / description / link per ADULT price-rendering rules; sold-out banner ONLY when operator flagged; missing link → manager-handoff line. New `_build_ambiguous_adult_event_dm` asks „რომელი გაინტერესებთ?". `send_dm_from_comment` tries specific-event resolver BEFORE the generic ADULT rich DM. `fetch_post_content` log lines no longer surface the access token, response body, or exception args. Admin event form gains operator-facing helper text. |
| **ADULT Live QA — price hallucination (price_text + price_gel surfacing)** | ✅ **Done (2026-06-08, +23 tests, 1442 → 1465)** | Executor compact + details payloads now surface `price_gel` (positive only) alongside `price_text`; new per-conversation `adult_price_disclosed_for_conversation` flag mirrors the sold-out pattern; sanitiser strips invented „დასწრების საფასური მითითებული არაა" / „ფასი კონფიგურაციაში მითითებული არ არის" copy ONLY when the flag is set (so the canonical missing-phrase fallback still passes through when both sources are genuinely blank); `system_adult_v1.md` gains the „ფასის რენდერინგის წესი — CRITICAL" block with the explicit price_text → numeric-render → price_gel-fallback decision tree. |
| **ADULT Live QA — sold-out hallucination + ticket link + partial title + wording polish** | ✅ **Done (2026-06-08, +31 tests, 1411 → 1442)** | `_normalize_adult_event` surfaces `sold_out` boolean; `_get_adult_events` compact OMITS `seats_available` when zero (Bug 1 — invented „ადგილები ამოწურულია" copy); `_get_adult_event_details` surfaces `reservation_url` + `payment_terms` directly (Bug 3); new `find_adult_events_matching` with Georgian noun-suffix stemming returns ALL candidates, `find_adult_event` returns unique or `None` (Bug 2 — „ქართული პოეზია" now matches „ქართული პოეზიის საღამო"); executor returns `ambiguous_event` / `event_inactive` reasons (Bug 2); per-conversation `adult_sold_out_disclosed_for_conversation` flag gates sanitiser sold-out strip (allows legitimate sold-out copy through when operator-flagged); sanitiser rewrites „გინდა"/"გინდათ" → „გსურთ" (Bug 5); sanitiser strips „გმადლობთ. რამდენი წლის ბრძანდებით?" filler opener while preserving mid-response thanks (Bug 4); `system_adult_v1.md` gains three new CRITICAL rule blocks (sold_out / selection / polite-form). |
| **Admin Panel multi-event** | ✅ **Done (2026-06-08, +52 tests for backend, +9 for UI visibility, 1350 → 1411)** | Operator-facing roster: `_normalize_adult_event` preserves `description` / `facebook_post_id` / `tags` / `price_gel` / `payment_terms`; new `update_adult_event` / `deactivate_adult_event` / `activate_adult_event` service functions; new `POST /admin/programs/adult_events/events/{id}/{deactivate,activate}` routes; list view shows status-aware action buttons. `save_adult_event` merges over existing entries so a partial save never strips previously-saved fields. 13-year `min_age` global floor enforced on read + write. `AdultToolExecutor._get_adult_events` compact payload extended with `description`. Section-level fallback (Bug 1A) still fires when `events[]` is empty; populated `events[]` always wins (no phantom duplicate). Multiple eligible events surface to the LLM together; system prompt drives the „რომელი ღონისძიება გაინტერესებთ?" multi-event listing pattern. |
| **Adult event subscription + new-event broadcast** | ✅ **Done (2026-06-08, +73 tests, 1520 → 1593)** | New `events` Sheets tab (18 columns; created on first write). New `adult_subscription_service` with deterministic consent / unsubscribe phrase detection, `subscribe()` with `missing_name` / `missing_phone` / `missing_name_and_phone` / `sheets_save_failed` reasons, `unsubscribe()`, `is_already_subscribed()`. New `adult_event_broadcast_service.broadcast_event()` with kill-switch + missing-link + inactive blocked branches; dual-layer duplicate prevention via `Notified Event IDs`; per-subscriber failure isolated. New ADULT tool `subscribe_to_adult_event_updates` + executor handler that pulls name/phone from lead state when args missing, never claims success without Sheets `(True, "ok")`. `adult_llm_engine` short-circuits on unsubscribe phrases BEFORE the LLM call. `Conversation.adult_subscription_status` field for in-session marker. New `system_adult_v1.md` "ფუტურული ღონისძიების შეტყობინებების წესი" block with exact brand wording + ban on misleading „ახალი ღონისძიების სიაში დაგამატოთ" / „დაგიმატეთ". Admin Panel: checkbox „შენახვის შემდეგ გაუგზავნე subscribed მომხმარებლებს" on create/edit form (default off); per-row manual broadcast button; results page with operator-friendly Georgian summary + counter table. |
| **Instagram webhook signature + payload diagnostic** | ✅ **Done (2026-06-09, +22 tests, 1593 → 1615)** | Multi-secret HMAC verifier — `_verify_meta_signature` returns `(accepted, label)` and tries Facebook (`META_APP_SECRET` / `MESSENGER_APP_SECRET`) first, falls back to `INSTAGRAM_APP_SECRET`. Log: `[webhook] signature accepted via facebook_app_secret` / `instagram_app_secret` / `[webhook] signature rejected: no configured secret matched`. New `_summarise_payload_fields(payload)` emits a single privacy-safe line with `object` + `entries` + sorted unique field names; unsupported Instagram fields surface as `[webhook] instagram payload accepted but unsupported fields=[...]` + 200 OK (no retry-storm). Boot log prints secret + token presence (`set` / `NOT set`). NEVER logs: raw body, signature header value, computed digest, app secrets, access tokens, sender ids, message text, phone numbers. Existing Facebook signature path + tests preserved byte-for-byte. |
| **Instagram access token + outbound DM wiring** | ⏳ **Pending — NEXT TASK** | Operator must generate the Instagram access token in the Meta Developer dashboard ("Generate token" still shows in the token column per the live screenshot) and add as `INSTAGRAM_ACCESS_TOKEN`. Boot log now surfaces missing-token state. `messenger_service.send_message(platform="instagram", ...)` outbound path needs verification once a real token is present. Instagram payload-field routing (if live `code.shelf` carries fields outside `_SUPPORTED_PAYLOAD_FIELDS`) is a follow-up patch. |
| **Comment → Event Mapping via `facebook_post_id`** | ⏳ **Pending — field captured, mapping logic next** | `facebook_post_id` is now persisted on each event row in `data/admin_config/sections.yaml` (`adult_events.events[*].facebook_post_id`). Next patch wires `comment_service.resolve_section_from_post` / `_build_adult_rich_dm` to pick the matching event by id when a comment lands on a known post, and to embed that event's title / date / link in the rich first-contact DM. Current comment routing continues to use post hashtags only — no regression. |
| **Adult follow-up scheduler** | ⏳ **Pending — not yet enabled** | Current `followup_service._maybe_send_followup_for_conversation` short-circuits with `reason=non_parent_segment` for ADULT / UNCLEAR. Distinct from the Adult event subscription broadcast (which is operator-initiated). Author `adult_followup_*` templates + extend cadence to `segment == "ADULT"`. |
| **Railway deploy** | ⏳ **Pending** | Procfile + always-on plan + Redis add-on. Single worker for v1. Sync live `.env` from `.env.example` (`META_APP_SECRET`, `AGENT_ENABLED`, `VERIFY_WEBHOOK_SIGNATURE`, `BOOKING_CALENDAR_ID`, `BUSY_CALENDAR_IDS`, `SENTRY_DSN`, `OPENAI_MODEL` confirmation). |
| **Meta App Review** | ⏳ **Pending** | `pages_manage_engagement` permission must be granted before public comment replies actually fire. Client must complete Business Verification first; SLA can be 5+ business days. |
| **WhatsApp live test** | ⏳ **Pending real credentials** | Empty-token guard ✅ (Session 7); waiting on operator to populate `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `MANAGER_WHATSAPP_NUMBER` once Meta WhatsApp Business credentials are issued. |
| **Production smoke test** | ⏳ **Pending** | Gated on Railway deploy. Not yet run; do NOT mark complete. |

**Session 8 live verification note:** Operator screenshot (2026-06-07/08) confirmed on a clean sender:
- Old Sheets row `Status = Rescheduled`
- Current Sheets row `Status = Booked`
- Exactly one active `Booked` row per sender after reschedule
- Booking confirmation reply: short brand form, no trailing „თუ კიდევ რაიმე…" / „თუ დამატებითი კითხვა გაქვთ…" filler.

**Production deployment is NOT marked complete.** Code path is ready; Railway + App Review + WhatsApp credentials + production smoke test remain pending operator action.

**pytest tests/ -q** as of 2026-06-09 (real measured, post Conversation Guardrails patch): **1727 passed, 0 failed** (1350 baseline + 52 multi-event + 9 UI visibility + 31 ADULT Live QA + 23 ADULT price surfacing + 55 comment specific-event mapping + 73 ADULT event subscription + broadcast + 22 Instagram webhook signature + 25 generic-`#event` active-list + 87 guardrails = 1727; 3 cosmetic warnings unchanged across runs). `test_agent.py` ✅ green.

---

## Post-audit fixes applied (2026-06-01)

შემოწმდა ამ audit-ის გამოშვების შემდეგ რომელი issue-ები მოგვარდა და რომელი დარჩა გადასაჭრელად. სტატუსები:

| Issue from audit | სტატუსი | ვერიფიკაცია |
|---|---|---|
| **Webhook signature unverified** (§8 BLOCKERS #2) | ✅ **Fixed** | Webhook Signature Verification Patch (2026-06-01). `_verify_meta_signature(raw, header)` HMAC-SHA256 gate at top of `POST /webhook`. `hmac.compare_digest` constant-time compare. 11 new tests in `tests/test_webhook_signature.py`. Fail-open when `META_APP_SECRET` empty. Pytest 791 → 802. |
| **Meta v18 → v19 in `notification_service`** (§9 #1, §10 Gap #3) | ⏳ **Pending quick fix** | Still hardcoded at [notification_service.py:28](ai-agent/app/services/notification_service.py#L28). 15-min replacement with `settings.META_GRAPH_API_BASE_URL` / `settings.META_GRAPH_API_VERSION`. |
| **`.gitignore` missing + `credentials.json` in working tree** (§8, §10 Gap #1) | ⏳ **Pending quick fix** | No `.gitignore` anywhere in repo tree (verified `ls -la "AI sales agent/.gitignore"` → not found). `credentials.json` (Google service account) still in working tree. Repo isn't currently a git repo, so nothing pushed yet — but Priority 1 before any `git init && git push`. |
| **`requirements.txt` missing dev/optional deps** (§7 ⚠️, §10 Gap #4) | ⏳ **Pending quick fix** | `pytest`, `sentry-sdk`, `redis`, `fakeredis`, `python-multipart` still absent. Add `requirements-dev.txt` (~15 min). |
| **`mask_sender` shape divergence** (§8, §10 Gap #12) | ⏳ **Pending quick fix** | `kill_switch.mask_sender` keeps trailing 4; `sentry_service.mask_sender` keeps leading 6. Both still mask. Standardize across both files together (~10 min). |
| **Dead code (`OpenAIService`, `ContentRepository`, `FlowContext`, `parent_flow._generate_parent_response`, etc.)** (§9, §10 Gap #11) | ⏳ **Deferred** | ~600 LOC inert per AUDIT_REPORT §9 + REVIEW §9. Not blocking deploy; cleanup deferred to a quality-of-life batch. |
| **Sentry DSN not yet configured in live `.env`** (§2.4 ⚠️, §10 Gap #5) | ⏳ **Pending operator action** | Sentry code ready (Basic Error Monitoring Patch 2026-05-31); operator must add `SENTRY_DSN` to live `.env` + `pip install "sentry-sdk[fastapi]"` for monitoring to actually fire. |
| **`META_APP_SECRET` not yet in live `.env`** (§2.4 ⚠️) | ⏳ **Pending operator action** | Webhook signature verification fail-open until secret is set. Single operator action ("paste app secret, restart"). |
| **Redis conversation index** (§10 Gap #6) | ⏳ **Deferred** | Cross-restart follow-up gap mitigated but not eliminated. Future patch can add `conversation:active:<platform>` set. |
| **WhatsApp manager + outbound live verification** (§10 Gap #7) | ⏳ **Pending operator action** | Plumbed, untested live. ~0.5 day operator test. |
| **Adult flow LLM engine** (§10 Gap #8, code half) | ✅ **Fixed** | ADULT LLM Engine Patch (2026-06-01). New `adult_llm_engine.py` + `adult_tools.py` + `adult_tool_executor.py` + `system_adult_v1.md` + `adult_sales_policy.md`. 6-tool registry; per-event `min_age` in admin_config; ADULT flow CONFIRMED never books Calendar; manager phone via `admin_config_service.get_manager_phone()` chain — never hard-coded. `USE_ADULT_LLM_ENGINE=true` default; legacy state machine preserved as fallback. 54 new tests. Pytest 802 → 856. **Live audit (P3-E) still pending** — needs real Instagram traffic. |

**Conclusion:** Of the 5 audit items flagged as actionable in §10 top-5 next steps, **1 fully fixed** (webhook signature) and **4 pending quick fixes** (`.gitignore`, requirements-dev, v18→v19, `mask_sender`) totalling ~1 hour of work. None block the next session.

---

## Post-audit fixes — Session 2 (2026-06-01 → 2026-06-02)

Five additional patches shipped after the original audit was published. Status snapshot:

| Item | სტატუსი | ვერიფიკაცია |
|---|---|---|
| **ADULT LLM Engine implementation** | ✅ **Done** | ADULT LLM Engine + Cultural Events Patch (2026-06-01). 5 new core files (`adult_llm_engine.py` + `adult_tools.py` + `adult_tool_executor.py` + `system_adult_v1.md` + `adult_sales_policy.md`); 6-tool registry; per-event `min_age` in admin_config; manager phone via `get_manager_phone()` chain; CONFIRMED no Calendar booking in adult flow. Pytest 802 → 856. |
| **ADULT off-topic guard (general-knowledge filter)** | ✅ **Done** | ADULT Off-Topic Guard + Event Grounding + Default Min-Age Fix Patch (2026-06-02). New `_maybe_adult_offtopic_reply` deterministic guard runs BEFORE OpenAI; checks configured event content + in-scope domain stems + general-knowledge interrogative patterns. Bot no longer explains Elton John / Mufasa / climate change. `ADULT_EVENT_DEFAULT_MIN_AGE` lowered 18 → 13 (per-event override preserved). 22 new tests. Pytest 873 → 896. |
| **ADULT event grounding (no invented dates/prices)** | ✅ **Done** (with 1 follow-up bug in §below) | ADULT Live QA Polish Patch (2026-06-02). 7 new sanitiser entries (broken who-question + „ახლახან ზუსტდება" placeholder family); STRICT EVENT GROUNDING section in `system_adult_v1.md` requires "ამ დეტალს მენეჯერი დაგიზუსტებთ." for empty fields; seed events flipped to `status: inactive`. Pytest 896 → 924. |
| **Expired booking memory** | ✅ **Done** | Expired Booking Memory Fix Patch (2026-06-02). `_expire_past_booking_if_needed` helper demotes stale `calendly_booked=True` without touching Calendar / `calendar_event_id` / `status`. Memory-info reply no longer echoes past dates as active. 17 new tests. Pytest 856 → 873. |
| **OpenAI model compatibility (gpt-5.4-mini support)** | ✅ **Done** | OpenAI Model Compatibility Patch (2026-06-02). `_uses_max_completion_tokens(model) → bool` + `_build_completion_kwargs` chokepoint. Live `BadRequestError: 'max_tokens' is not supported` resolved. Boot log `[openai] model=… token_param=…` confirms shape. 32 new tests. Pytest 924 → 956. |
| **ADULT live-bug trio (transition stops / child_age leak / „დის(თვის)" wrong PARENT switch)** | ⏳ **Pending next task** | Surfaced after Live QA Polish via multiple operator-driven live sessions on 2026-06-02. Bundled as Bug-Fix Task #1 in HANDOFF §7 Priority 1 (~3–4 hours). |
| **Quick fixes (`.gitignore` / `requirements-dev` / v18→v19 / `mask_sender`)** | ⏳ **Pending** | Unchanged from Session 1 audit — none progressed in Session 2 (engineering session was spent on adult engine + bugs). ~1 hour total. |
| **Railway deploy + `.env` sync + populate adult events** | ⏳ **Pending** | Engine is ready; operator must (a) deploy to Railway, (b) sync `.env` from `.env.example` (`META_APP_SECRET` + `SENTRY_DSN` + confirm `OPENAI_MODEL`), (c) populate real adult events via `/admin/programs/adult_events`. |
| **Adult flow live audit (P3-E)** | ⏳ **Partial** | Multiple live operator-driven sessions completed 2026-06-02 — exercised the full engine + tool registry + off-topic guard end-to-end. The 3 bugs above are what surfaced. Declaring "complete" is gated on Bug-Fix Task #1. |

**Session 2 net delivery:** 5 patches shipped, 154 new tests added (pytest 802 → 956), CRITICAL 22/22 preserved across every patch, no PARENT or security regression. Live ADULT testing now has a real-traffic feedback loop; 3 follow-up bugs identified for the next engineering session.

---

## Post-audit fixes — Session 4 → Session 7 (2026-06-04 → 2026-06-06)

This block consolidates the four post-Session-3 patch waves into one status table. Each row uses the same ✅ / ⏳ vocabulary as Sessions 1–3 so the reviewer can scan all six post-audit sessions consistently.

| Item | სტატუსი | ვერიფიკაცია |
|---|---|---|
| **Session 4 — Booking Date Parse + Lead Field Separation Patch (2026-06-04)** | ✅ **Done** | Pytest 1105 → 1135 (+30). New `resolve_relative_datetime(text, *, now=None)` in `app/agent/services/timestamps.py` parses Georgian relative-day phrases (ხვალ / ზეგ / დღეს / გუშინ + variants) + Georgian time forms (11 საათზე / 11:00 / 11-ზე / 11 სთ-ზე) into Tbilisi-aware datetime. `_build_context_message` always surfaces `today_iso_tbilisi=YYYY-MM-DD` + `now_iso_tbilisi=...` + (when applicable) `resolved_relative_datetime_iso=...`. New `_normalise_datetime_iso_from_message` helper on `ParentToolExecutor` overrides stale LLM ISOs with the resolved date. `_save_lead_info` rejects challenge/notes writes containing ADULT cultural-event vocabulary via `_looks_like_adult_event_interest` — strict PARENT challenge ↔ ADULT event_interest separation. |
| **Session 5 — Live QA Bug Fix Patch (2026-06-04)** | ✅ **Done** | Pytest 1135 → 1158 (+23). `sheets_service._scrub_event_interest_for_segment` strips ADULT vocabulary from PARENT Sheets rows' Event Interest cell. `_ends_with_dagexmarebit` catch-all in `adult_llm_engine` ensures bare „დაგეხმარებით." responses get the next-step question appended. `_BOOKING_VERIFICATION_PHRASES` closed-set in `parent_tool_executor` rejects `book_consultation` when the user message is a re-check question. Most importantly: `_book_consultation` now requires `lead.calendar_event_id` to be non-empty after `_book_selected_slot` returns True — silent Calendar HTTP 200 + empty body is detected as `reason=calendar_booking_failed`, half-written lead state rolled back, Sentry capture fires. |
| **Session 6 — Live QA Patch (Georgian wording, Adult events, Booking slot mismatch) (2026-06-05)** | ✅ **Done** | Pytest 1158 → 1196 (+38). 8 new sanitizer entries (PARENT + ADULT) fix awkward Georgian phrases (გმადლობთ, რომ გაზიარეთ / დასთვის / მიმოწმების შედეგად / გვერდში / გიჭერს მხარს / გჭირდებათ / პირვანდელ დროზე). `_ADULT_FOLLOWUP_QUESTION_WHO` updated to „სხვა ადამიანისთვის?" (later reverted per client preference — see Session 7 OPEN below). `_PARENT_SWITCH_KEYWORDS` tightened to HARD camp keywords only. 13-year floor enforced (`max(13, min_age)`). New `_extract_date_hint_from_message` + date-aware slot matching prevents the "5 ივნისი 10:00 → 8 ივნისი 10:00" mismatch bug; `_book_consultation` post-book compares actual vs requested ISO and yields `reason=slot_mismatch` on mismatch with full lead rollback + Sentry capture. |
| **Session 6 (Session 2 of 2026-06-05) — FULL Live QA Patch (Admin adult_events + 11 wording / routing / safety bugs)** | ✅ **Done** | Pytest 1196 → 1251 (+55). **CRITICAL fix:** `admin_config_service._build_fallback_event_from_section` derives one fallback event from section-level metadata when `events[]` is empty, so an operator who saved via the legacy section form still surfaces in the adult flow. **Minimal multi-event editor** at `/admin/programs/adult_events/events` (list/new/edit/delete) backed by new `save_adult_event` / `delete_adult_event` / `_load_adult_events_raw` / `_save_adult_events_list` / `_slugify_for_id`. New `templates/admin/adult_events.html` + `templates/admin/adult_event_form.html`. ADULT→PARENT carryover: `_build_context_message` surfaces `adult_target_relation` + `adult_target_age` so PARENT engine acknowledges instead of re-asking. `_strip_unwarranted_sibling_discount` post-process. `NAME_FILLER_WORDS` extended with 14 Georgian confirmation tokens (კაი / კარგი / კი / დიახ / ...). **Reschedule safe ordering** in `_reschedule_booking`: stash old → book new → verify event_id → cancel old. Sentry capture for new-fail and old-cancel-fail paths. 10 new verification phrases. Context-aware redundant-confirmation strip. CRITICAL scenario sweep (real OpenAI, operator-approved): **22/22 ✅**. Model: gpt-4.1-mini. |
| **Session 7 — Live QA findings (surfaced 2026-06-06, post-Session-6)** | ⏳ **Pending** | Five live-QA findings observed on 2026-06-06 after Session 6 patch shipped: **(1) Reschedule pending state lost across confirmation turn** — old Calendar event not cancelled in live even though Session 6 backend logic is correct. **(2) ADULT transition still dead-ends** on a gpt-4.1-mini phrasing variant the catch-all missed. **(3) Adult target question wording revert** — client prefers the original „თქვენი შვილისთვის?" form; Sessions 6 + 7 standardised on „სხვა ადამიანისთვის?". **(4) Manager email** challenge duplicated in body + generic subject „ახალი ლიდი" even when `lead.name` populated. **(5) WhatsApp notification** throws noisy traceback on blank Bearer token; needs early-return guard + operator `.env` population. None observed during CRITICAL scenario sweep on 2026-06-05; all surfaced via live operator follow-up testing. ~4–5 hours engineering pickup. See HANDOFF.md §5 STILL OPEN + §7 Priority 1. |
| **Quick fixes (`.gitignore` / `requirements-dev` / v18→v19 / `mask_sender`)** | ⏳ **Pending** | Carried over from Session 1 audit (still ~1 hour total). Engineering capacity Sessions 4–7 spent on live-QA bug fixes; these remain unchanged. HANDOFF.md §7 Priority 2 #6. |
| **Railway deploy + `.env` sync + populate adult events** | ⏳ **Partial** | Adult events: ✅ Working (Session 6 — see HANDOFF.md §11). Railway deploy + `.env` sync still pending. HANDOFF.md §7 Priority 2 #7. |
| **Adult flow live audit (P3-E)** | ⏳ **Partial** | Multiple operator-driven live sessions on 2026-06-02 + 2026-06-06 exercised the engine + tool registry end-to-end. Session 6 + Session 7 follow-up bugs all came from these sessions — the engine is being live-tested in earnest now, just not yet declared "complete" because each session surfaces new findings. Session 7 #2 (adult transition dead-end recurrence) is the most recent open item. |
| **WhatsApp manager + outbound live verification** | ⏳ **Pending** | Plumbed; Session 7 #5 adds the empty-token guard. Operator action to populate `WHATSAPP_TOKEN` + `MANAGER_WHATSAPP_NUMBER` is the remaining blocker. ~0.5 day post-Railway. |
| **Calendar wall-clock-day fragility (test-side only)** | ⏳ **Deferred** | `tests/test_calendar_multi_busy_patch.py::test_busy_10_30_to_19_00_blocks_11_through_18` uses `now_tbilisi() + 14 days` to pick a "future date". Today (Sat 2026-06-06) + 14 days = Sat 2026-06-20, which Calendar correctly rejects as a weekend; test fails on Sat/Sun runs. Pre-existing fragility (the +14 window itself can land on a weekend). Test-side fix only (pick next weekday); doc-only update window for Session 7 read-only constraint defers this fix. |

**Sessions 4–7 net delivery:** Four engineering patch waves (Sessions 4–6 net delivery; Session 7 is engineering pickup, not patch delivery). 146 new tests added across the four (pytest 1105 → 1251 = +146). CRITICAL 22/22 + security 4/4 + adult 3/3 preserved through every wave. Three new env vars (`BOOKING_CALENDAR_ID`, `BUSY_CALENDAR_IDS`, `OPENAI_MODEL`). Six new production-code helpers (`resolve_relative_datetime`, `_scrub_event_interest_for_segment`, `_ends_with_dagexmarebit`, `_BOOKING_VERIFICATION_PHRASES`, `_extract_date_hint_from_message`, `_build_fallback_event_from_section`). Two new Admin Panel routes (events list + events CRUD). Two new templates. Reschedule reordered to safe path. Sibling-discount guard + 14 new name filler tokens. **Status verdict: the audit's original BLOCKERS list remains all-✅; the new STILL OPEN list is now Session 7's five findings + the same four infrastructure items (`.gitignore` / `requirements-dev` / Railway / Meta App Review) that have carried since Session 1.**

---

## Post-audit fixes — Session 3 (2026-06-02 → 2026-06-04)

Four patches shipped in Session 3, all bug-fix / polish — no new features, no business logic change outside the booking-availability widening:

| Item | სტატუსი | ვერიფიკაცია |
|---|---|---|
| **ADULT live-bug trio (transition stops / child_age leak / „დის(თვის)" wrong PARENT switch)** | ✅ **Done** | **ADULT Context Routing Fix (2026-06-02)** resolved the three Session-2 follow-up bugs. `_user_wants_parent_flow` now requires *hard camp keyword* (`ბანაკ` / `საზაფხულო` / `ბავშვთა პროგრამა`) — soft cues + adult-event signal stay ADULT. New `_maybe_capture_adult_target` pre-LLM helper extracts „ჩემი 14 წლის დისთვის" → `(adult_target_relation="და", adult_target_age="14")`. `_ensure_adult_intro_followup` gains a broader `_looks_like_bare_intro` heuristic (ack opener + adult-event keyword + no question + ≤120 chars). New `lead.adult_target_relation` / `lead.adult_target_age` with strict separation from `child_age` and `adult_age`. `_get_adult_events` deterministic guard blocks the LLM from passing `user_age=<child_age>` when no relative target is on record. 44 new tests. Pytest 956 → 1000. |
| **Wording cleanup — manager handoff phrase standardised + decorative emojis removed** | ✅ **Done** | **Agent Wording Cleanup Patch (2026-06-03)**. Replaced awkward live-bug „მენეჯერთან კავშირს მოგიწყობთ" / variants with brand-standard „თუ გსურთ, დაგაკავშირებთ მენეჯერთან." in both prompts/policies (`adult_sales_policy.md` §7.1 / `parent_sales_policy.md` §11.1); 7+7 sanitiser rewrites in PARENT/ADULT engines. Removed 🌿/😊/✨/✅/❌ from every user-facing static template / fallback constant / deterministic redirect / prompt example response; sanitisers strip them as a safety net. Tone remains warm — carried by wording, not symbols. 44 new tests. Pytest 1000 → 1044. |
| **Booking 60-min slots / 10:00–21:00 window + fail-CLOSED on Calendar API failure** | ✅ **Done** | **Booking Availability Patch (2026-06-03)**. Window widened 10:00–18:00 → **10:00–21:00** Asia/Tbilisi. Slot duration standardised at **60 minutes** (was 30) — half-hour requests rejected with new `reason="half_hour_not_supported"`. First valid start 10:00; last valid start 20:00 (20:00–21:00); 21:00 is closing time, never a valid start. Pre-booking re-check fail-CLOSED on Calendar API exceptions (was fail-open). Partial-overlap busy hides adjacent slots; exact-boundary busy leaves neighbours free (strict-inequality interval overlap). 32 new tests. Pytest 1044 → 1076. |
| **Multi-calendar busy check + reschedule wording fix** | ✅ **Done** | **Calendar Multi-Busy Check + Reschedule Wording Patch (2026-06-04)**. New `BOOKING_CALENDAR_ID` + `BUSY_CALENDAR_IDS` envs with safe fallbacks. `_free_busy_intervals` queries every configured calendar in a single multi-item FreeBusy call; raises `_BusyCalendarQueryError` (caller fail-CLOSED) if ANY entry missing / per-calendar `errors` block / HTTP fail. Booking writes (`book_slot` / `cancel_calendar_event` / `create_event`) target `settings.booking_calendar_id()` only. Reschedule path uses the same `check_slot_available`. Prompt rule: "never say „თავისუფალია" / „დამიდასტურეთ" / „ჩავნიშნავ" without `check_consultation_slot` first". 6 sanitiser entries rewrite reschedule wording „გადატანას ..." → locative „გადატანაში დაგეხმარებით". 29 new tests. Pytest 1076 → 1105. |
| **Admin Panel multi-event editor** | ⏳ **Pending** | Existing `/admin/programs/<id>` form edits one section at a time. For `adult_events` with multiple events, operator currently edits `data/admin_config/sections.yaml` directly. Priority 1 next-task (~2–3 hours). |
| **Quick fixes (`.gitignore` / `requirements-dev` / v18→v19 / `mask_sender`)** | ⏳ **Pending** | Unchanged across Sessions 1–3 (engineering capacity went to live-bug fixes). ~1 hour total. |
| **`BUSY_CALENDAR_IDS` operator action** | ⏳ **Pending** | Patch shipped 2026-06-04; live `.env` doesn't yet list the manager's side-calendar id(s). Each calendar must be shared with the Google service account. ~5 min operator action; required for the patch to actually prevent the live bug it was authored against. |
| **Railway deploy + `.env` sync + populate adult events** | ⏳ **Pending** | Unchanged from Session 2. Engine is ready; operator must (a) deploy to Railway, (b) sync `.env` from `.env.example` (`META_APP_SECRET` + `SENTRY_DSN` + `BOOKING_CALENDAR_ID` + `BUSY_CALENDAR_IDS` + confirm `OPENAI_MODEL`), (c) populate real adult events via `/admin/programs/adult_events`. |
| **Adult flow live audit (P3-E)** | ⏳ **Partial** | The 3 live-bug-trio defects from Session 2 are resolved (Session 3 RESOLVED row above). One more operator-driven live session against the post-fix code is the gating item before declaring "live-tested complete." |

**Session 3 net delivery:** 4 patches shipped, 149 new tests added (pytest 956 → 1105 — **956 + 44 + 44 + 32 + 29 = 1105**), CRITICAL 22/22 preserved across every patch (last verified 2026-06-02), no PARENT / security / Sheets / Email / Redis / Follow-up / Kill Switch / Sentry / Webhook signature / Admin auth / Comment flow / scenario runner / OpenAI model regression. Three new env vars added (`BOOKING_CALENDAR_ID`, `BUSY_CALENDAR_IDS`, plus `OPENAI_MODEL` continues to point at `gpt-5.4-mini`). Reschedule path now uses the same availability backend as new booking — no weaker first-check path.

---

## 0. კონტექსტი

წყაროები:
- [CLAUDE.md](ai-agent/CLAUDE.md) — operator-facing project map (49 KB; ბოლო update 2026-05-31).
- [HANDOFF.md](ai-agent/HANDOFF.md) — historical patch log (88 KB; იგივე update).
- [AUDIT_REPORT.md](ai-agent/AUDIT_REPORT.md) — historical architectural audit (2026-05-22, **Phase 3.9 baseline**) — გადამოწმდა ახლანდელ კოდთან; ნაწილი dead-code findings და In-memory state findings **ჯერ კიდევ ძალაშია**, ნაწილი (Kill Switch missing, Error monitoring weak) **მოგვარდა**.
- [requirements.txt](ai-agent/requirements.txt) — `fastapi`, `uvicorn`, `python-dotenv`, `openai`, `httpx`, `gspread`, `google-auth`, `google-api-python-client`, `apscheduler`, `twilio`, `pyairtable`, `pyyaml`. **⚠️ Missing:** `pytest`, `sentry-sdk`, `redis`, `fakeredis`, `Jinja2`, `python-multipart` (FastAPI Form-ი ვერ მუშავდება Form parser-ის გარეშე).
- [app/](ai-agent/app/), [tests/](ai-agent/tests/) (26 ფაილი), [tools/scenario_library.py](ai-agent/tools/scenario_library.py) (74 entries).

Verification methods:
- `Read` (whole-file)
- `Grep -n` (file:line proof)
- `python -m pytest tests/ -q` (live count)
- `head -3 credentials.json` (existence verification, secret-ი არ დაბეჭდილია)

---

## 1. Executive Summary

ეს არის **production-ready core MVP** — ერთი კონცეპტუალური დამკვეთისთვის (სიტყვის აკადემია) Instagram DM + Facebook Messenger live-tested PARENT flow, Google Calendar booking, Google Sheets CRM, Gmail SMTP manager email, optional Redis persistence, optional Sentry error monitoring, kill switch, conversation-marker-driven follow-up scheduler 24h/72h/168h cadence, admin panel `/admin` operator UI. PARENT flow drives 8-tool LLM engine (P3-C SAFE) with backend-validated execution. Production blocker-ი არცერთი ღია არ არის — დარჩენილი ცნობილი gap-ები არიან Adult flow live-testing, webhook signature verification, multi-worker scaling, WhatsApp manager notification verification, Meta App Review pending.

**Headline numbers** (verified `python -m pytest tests/ -q`):
- **pytest:** 791 passed / 0 failed / 3 cosmetic warnings (171.91s).
- **test_agent.py** (live-mocked smoke): 63/63 checks ✅.
- **Full 74-scenario sweep** (real OpenAI, ბოლო run 2026-05-31): **74/74 (100%)**, CRITICAL 22/22 ([HANDOFF.md:556](ai-agent/HANDOFF.md#L556) test status block).
- **Codebase size:** `parent_flow.py` 2317 LOC, `parent_llm_engine.py` 1244 LOC, `parent_tool_executor.py` ~1450 LOC, `system_parent_v2.md` 305 LOC prompt.
- **18 patches shipped this session** ([HANDOFF.md:5](ai-agent/HANDOFF.md#L5)).

**Overall maturity verdict:** **production-ready core for the templated client (single-worker deploy).** Multi-worker / horizontal scaling გადახედვა საჭიროა (in-memory module-level dicts + APScheduler in-process SPOF). Live runtime ჩართულია Instagram DM-ისთვის; Facebook Messenger plumbed; WhatsApp plumbed but untested.

---

## 2. Architecture Map

### 2.1 ფენები (layers)

| ფენა | მოდულები | სად ცხოვრობს |
|---|---|---|
| Inbound webhook | [app/routes/webhook.py](ai-agent/app/routes/webhook.py) | `GET /webhook` verify; `POST /webhook` DM + comments |
| Admin UI | [app/routes/admin.py](ai-agent/app/routes/admin.py) | `/admin` Jinja2 + HTTP Basic Auth |
| Debounce | [app/services/message_buffer.py](ai-agent/app/services/message_buffer.py) | 5–15s per-sender batching |
| Routing brain | [app/services/conversation_service.py](ai-agent/app/services/conversation_service.py) | segment classifier + segment-to-flow |
| PARENT flow | [app/flows/parent_flow.py](ai-agent/app/flows/parent_flow.py) | P3-C engine gate + legacy state machine fallback |
| LLM engine | [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) | OpenAI chat-with-tools loop, max 5 iterations |
| Tool executor | [app/agent/tools/parent_tool_executor.py](ai-agent/app/agent/tools/parent_tool_executor.py) | 8 backend-validated tools |
| ADULT flow | [app/flows/adult_flow.py](ai-agent/app/flows/adult_flow.py) | state machine (untested live) |
| Comment flow | [app/services/comment_service.py](ai-agent/app/services/comment_service.py) | intent classify + private/public reply + rich DM |
| Persistence | [app/services/redis_state_service.py](ai-agent/app/services/redis_state_service.py) | lazy-connect Redis client (safe no-op) |
| Schedulers | [app/main.py:42-52](ai-agent/app/main.py#L42) | APScheduler 1h interval × 2 jobs (DM follow-up + comment follow-up) |
| Kill switch | [app/services/kill_switch.py](ai-agent/app/services/kill_switch.py) | `AGENT_ENABLED` global gate |
| Error monitoring | [app/services/sentry_service.py](ai-agent/app/services/sentry_service.py) | optional Sentry, safe no-op when DSN empty OR SDK missing |
| External I/O | `calendar_service.py`, `sheets_service.py`, `notification_service.py`, `messenger_service.py`, `openai_service.py` | Google Calendar v3, gspread, Gmail SMTP, Meta Graph v19, OpenAI SDK |

### 2.2 Message lifecycle (verified by AUDIT_REPORT.md §1 cross-check)

```
POST /webhook
   ├─ background_tasks.add_task(_process_payload, payload)
   │  ↓
   │  _extract_messages → per message: message_buffer.buffer_message
   │     ↓ (5–15s debounce, fragments joined)
   │     _dispatch_buffered_reply(sender_id, combined, platform)
   │        ↓
   │        conversation_service.process_message  [Sentry try/except wrapper]
   │           ↓ Kill switch check → AGENT_DISABLED_MESSAGE if false
   │           ↓ Conversation get-or-create (Redis miss → in-memory)
   │           ↓ Segment classifier (keyword stems)
   │           ↓ parent_flow.handle / adult_flow.handle / UNCLEAR_ROUTING
   │           ↓ Conversation.history.append + write-through Redis
   │        ← reply string
   │     messenger_service.send_message (3 retries × 2s)
   │
   └─ _process_comment_events
      ↓ per comment:
      handle_comment  [Kill switch check]
        ↓ duplicate guard (LRU + Redis processed_comment:<id>)
        ↓ detect_comment_intent (LLM)
        ↓ determine_segment_from_post (hashtag)
        ↓ sheets.save_comment (Comments tab)
        ↓ if ENABLE_PUBLIC_COMMENT_REPLY → public reply (Meta /replies)
        ↓ send_dm_from_comment → private reply (recipient.comment_id)
```

Background hourly schedulers ([app/main.py:42-52](ai-agent/app/main.py#L42)):
- `followup_service.check_and_send_followups()` — DM 24h/72h/168h cadence
- `comment_service.check_comment_followups()` — Meta /replies for `DMSent` rows older than `COMMENT_FOLLOWUP_HOURS`

### 2.3 ვინ არის brain?

**Backend Python is the brain. LLM is a specialist worker** (per AUDIT_REPORT §10a, still accurate).

- **Backend** decides: segment classification, state transitions, kill switch, slot availability, phone validation, age eligibility, manager-notified guard, follow-up cadence, booking commit, Sheets write, Calendar write. State machine + parsers + validators own the dangerous side-effects.
- **LLM** decides: factual answer phrasing (`get_camp_info` tool), tool-call selection (engine path), Georgian wording. Always wrapped by `ParentToolExecutor` backend validation that can reject any tool call with a structured `reason` code.

Critical invariant ([parent_flow.py:243-280](ai-agent/app/flows/parent_flow.py#L243)): the `_sanitise_booking_confirmation` guard runs on every engine response — confirmation language is allowed **only** when EITHER the booking tool succeeded *in the current turn* OR `lead.calendly_booked` is already true from a previous turn AND `conversation.state == "DONE"`. Fake confirmation → replaced with safe fallback.

### 2.4 Feature flags

| Flag | Code default | `.env` (live) | Effect |
|---|---|---|---|
| `USE_LLM_TURN_ANALYZER` | `False` ([config.py:225](ai-agent/app/config.py#L225)) | `true` | Analyzer fallback when deterministic detector returns None |
| `USE_LLM_COMPOSER` | `False` ([config.py:214](ai-agent/app/config.py#L214)) | `false` | LLM rewrites 4 discovery turns |
| `USE_PARENT_LLM_ENGINE` ⭐ | `False` ([config.py:238](ai-agent/app/config.py#L238)) | **`true`** (live) | P3-C tool-calling engine first |
| `ENABLE_PUBLIC_COMMENT_REPLY` ⭐ | `True` ([config.py:265-274](ai-agent/app/config.py#L265), flipped 2026-05-31) | `true` | Public comment reply attempted (Meta 400 until App Review) |
| `ENABLE_EMAIL_NOTIFICATIONS` | `True` ([config.py:168](ai-agent/app/config.py#L168)) | `true` | Gmail SMTP after booking |
| `ADMIN_PANEL_ENABLED` | `False` ([config.py:269](ai-agent/app/config.py#L269)) | `true` (local) | `/admin` Jinja2 routes mounted |
| `REDIS_ENABLED` | `True` ([config.py:261](ai-agent/app/config.py#L261)) | `true` | Conversation/processed-comment/manager-notified mirror |
| `AGENT_ENABLED` ⭐ | `True` ([config.py:286](ai-agent/app/config.py#L286)) | **⚠️ not present in `.env`** → defaults `True` | Kill switch |
| `SENTRY_DSN` ⭐ | `""` ([config.py:291](ai-agent/app/config.py#L291)) | **⚠️ not present in `.env`** → Sentry disabled | Optional error monitoring |
| `SENTRY_ENVIRONMENT` | `"production"` | not present | tag forwarded to Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.0` | not present | clamped to [0.0, 1.0] |

**⚠️ doc-vs-code mismatch:** `.env.example` documents `AGENT_ENABLED=true` and `SENTRY_DSN=` ([.env.example:155-179](ai-agent/.env.example#L155)) but the live `.env` (`grep -oE "^[A-Z_]+=" .env`) does NOT contain either of these keys — operator hasn't propagated the latest env additions. Behavior is safe (both default to live-on / disabled-respectively), but the operator should be told to sync `.env` from `.env.example`.

Boot prints flag status at [app/main.py:32-37](ai-agent/app/main.py#L32) including new Sentry status line.

---

## 3. Runtime & Cost

| Item | Value | Verification |
|---|---|---|
| **OpenAI model** | `gpt-4.1-mini` | [app/config.py:165](ai-agent/app/config.py#L165) default + [app/config.py:326](ai-agent/app/config.py#L326) env fallback |
| **Tool-loop iteration cap** | `MAX_TOOL_ITERATIONS = 5` | [parent_llm_engine.py:40](ai-agent/app/agent/llm/parent_llm_engine.py#L40) |
| **History window into the engine** | `HISTORY_WINDOW = 10` turns | [parent_llm_engine.py:205](ai-agent/app/agent/llm/parent_llm_engine.py#L205) + `_recent_history` at line 1166 |
| **LLM calls per typical PARENT turn (engine on)** | 1–5 (1 chat completion per tool iteration; most turns 1–2 iterations) | `chat_with_tools` loop in `run_parent_llm_turn` |
| **LLM calls per turn — defaults (composer/analyzer OFF, engine OFF) — legacy** | 0–2 (`detect_start_intent` once at START + `generate_summary` at booking) | AUDIT_REPORT §2 table still accurate for legacy path |
| **Static / deterministic-generated replies** | Kill-switch disabled message, UNCLEAR routing menu, identity short-circuit, decline/will-think reply, memory-info reply, static welcome menu, ineligible-age handoff, booked-state stripped CTA replacement, follow-up text (admin template or Georgian fallback) | All in `parent_flow._maybe_*` deterministic short-circuits + `kill_switch.AGENT_DISABLED_MESSAGE` + `data/prompts.UNCLEAR_ROUTING` |
| **Debounce window** | 5s default, 15s max | [config.py:206-207](ai-agent/app/config.py#L206) |
| **Per-conversation Redis TTL** | 604800s (7 days), sliding | [config.py:262](ai-agent/app/config.py#L262) |
| **Cost estimate (real OpenAI)** | $0.01–0.05 / manual sim; $1–3 / full 74-scenario sweep | [HANDOFF.md:553](ai-agent/HANDOFF.md#L553) test-status block + CLAUDE.md sweep comment |
| **Scenario runner cost-control** | `--priority CRITICAL` (22 scenarios ~3–5 min), `--limit N`, full ~10–15 min | [HANDOFF.md:218](ai-agent/HANDOFF.md#L218) |

**Critical invariant for cost:** every deterministic short-circuit returns BEFORE the engine call. Manager identity questions, declines, will-think, memory-info, static welcome, kill switch — all save a full OpenAI round trip ([parent_flow.py:127-188](ai-agent/app/flows/parent_flow.py#L127)).

---

## 4. Capability Matrix

ლეგენდა: ✅ live-tested · 🟩 done(unit-tested) · ⚠️ partial/untested · ❌ not built

| სფერო | ფუნქცია | სტატუსი | File / func | Verification |
|---|---|---|---|---|
| **არხები** | Instagram DM | ✅ | [messenger_service.send_message](ai-agent/app/services/messenger_service.py#L160) `platform="instagram"` | HANDOFF §4.1, live production channel ([HANDOFF.md:75](ai-agent/HANDOFF.md#L75)) |
| | Facebook Messenger | 🟩 | same, `platform="messenger"` | code path identical; live test only via Instagram historically |
| | WhatsApp inbound | 🟩 | [webhook._extract_whatsapp_messages](ai-agent/app/routes/webhook.py#L454) | unit-tested, untested live ([HANDOFF.md:329](ai-agent/HANDOFF.md#L329)) |
| | WhatsApp outbound | ⚠️ | [messenger_service.send_message](ai-agent/app/services/messenger_service.py#L170) `platform="whatsapp"` | plumbed, untested live; manager-WhatsApp also untested |
| **PARENT engine** | LLM engine + 8 tools | ✅ | [parent_llm_engine.run_parent_llm_turn](ai-agent/app/agent/llm/parent_llm_engine.py#L824) | 214 tests in [test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py); live-tested in production |
| | Static welcome bypass | ✅ | [_maybe_static_welcome](ai-agent/app/flows/parent_flow.py#L604) | 74-scenario sweep happy_path 10/10 |
| | Memory-info short-circuit | 🟩 | [_maybe_memory_info_reply](ai-agent/app/flows/parent_flow.py#L654) | 41 tests in `test_booked_state_polish.py`; live observation triggered the patch ([HANDOFF.md:582](ai-agent/HANDOFF.md#L582)) |
| | Booked-state CTA stripper | 🟩 | [_strip_consultation_cta_if_booked](ai-agent/app/flows/parent_flow.py#L606) | included in 41-test polish suite |
| | Decline / will-think handler | ✅ | [_maybe_handle_decline_engine](ai-agent/app/flows/parent_flow.py#L750) | scenario CRITICAL 22/22 includes Hard Decline + Will Think |
| | Pending-booking commit hook | ✅ | [_maybe_commit_pending_booking_engine](ai-agent/app/flows/parent_flow.py) | PATCH 5; live-tested booking commit flow |
| | Compound-booking parser | ✅ | [_parse_name_phone](ai-agent/app/flows/parent_flow.py) | SC-46 CRITICAL |
| | Fake-booking guard | ✅ | [_sanitise_booking_confirmation](ai-agent/app/flows/parent_flow.py#L218) | gating tool-success + state=DONE |
| | Booking via `book_consultation` tool | ✅ | [parent_tool_executor._book_consultation](ai-agent/app/agent/tools/parent_tool_executor.py) | live-tested, sets `lead.calendly_booked` + `calendar_event_id` |
| | Cancel/reschedule via `manage_consultation_booking` | 🟩 | same module | 8-tool registry tested |
| | Exact-slot check via `check_consultation_slot` | 🟩 | same | PATCH 6 |
| **ADULT flow** | State machine | ⚠️ | [adult_flow.handle](ai-agent/app/flows/adult_flow.py) | PATCH 7 global guard added; **never live-tested end-to-end** ([HANDOFF.md:329](ai-agent/HANDOFF.md#L329)) |
| | LLM engine | ❌ | not built | "P3-D" planned; ADULT still uses legacy `openai_service.generate_response` |
| **Comment flow** | Hashtag-based segment routing | ✅ | [comment_service.determine_segment_from_post](ai-agent/app/services/comment_service.py) | live-tested (HANDOFF.md Comment Flow PATCH 1–3) |
| | INTERESTED/NOT_INTERESTED LLM intent | ✅ | [comment_service.detect_comment_intent](ai-agent/app/services/comment_service.py) | 50 tests in `test_comment_flow.py` |
| | Private reply via `recipient.comment_id` | ✅ | [messenger_service.send_private_reply](ai-agent/app/services/messenger_service.py#L75) | live-tested "Page responded privately" notification |
| | Public reply | ⚠️ | gated by `ENABLE_PUBLIC_COMMENT_REPLY=True` (default flipped 2026-05-31) | code ready; Meta App Review pending; HTTP 400 logged-safely until then |
| | Rich first-contact DM (PARENT + ADULT) | ✅ | [_build_parent_rich_dm](ai-agent/app/services/comment_service.py#L163), `_build_adult_rich_dm` | live-tested via admin_config + camp_2026.yaml fallback chain |
| | Duplicate guard (LRU + Redis) | ✅ | [webhook._is_comment_processed_local](ai-agent/app/routes/webhook.py#L43) + `processed_comment:<id>` | live regression-tested |
| | Comment follow-up scheduler | 🟩 | [comment_service.check_comment_followups](ai-agent/app/services/comment_service.py#L726) | 27 new tests; HTTP 400 → mark `Expired` + no retry (Comment Follow-up Logic Fix 2026-05-31) |
| **Booking (Calendar)** | `book_slot` create | ✅ | [calendar_service.book_slot](ai-agent/app/services/calendar_service.py) | live-tested |
| | `cancel_calendar_event` | 🟩 | [calendar_service.cancel_calendar_event](ai-agent/app/services/calendar_service.py#L440) | unit-tested |
| | Free/Busy via `get_free_slots(start_date=..., days=...)` | ✅ | [calendar_service.get_free_slots](ai-agent/app/services/calendar_service.py) | PATCH 4 keyword-only range form |
| | Business-hours + today-buffer + `check_slot_calendar_only` | ✅ | [calendar_service.is_within_business_hours](ai-agent/app/services/calendar_service.py) | PATCH 6 |
| **CRM (Sheets)** | `Leads` tab append | ✅ | [sheets_service.save_lead](ai-agent/app/services/sheets_service.py#L102) | live-tested; 17 columns ([sheets_service.py:28-46](ai-agent/app/services/sheets_service.py#L28)) |
| | `update_lead(sender_id, updates)` | ✅ | [sheets_service.update_lead](ai-agent/app/services/sheets_service.py#L122) | live-tested |
| | `Comments` tab + `save_comment` / `update_comment` | ✅ | [sheets_service.save_comment](ai-agent/app/services/sheets_service.py#L358) | live-tested; 11 columns ([sheets_service.py:49-61](ai-agent/app/services/sheets_service.py#L49)) |
| | Cold-lead reader with tz-aware cutoff | 🟩 | [sheets_service.get_cold_leads](ai-agent/app/services/sheets_service.py#L148) | timezone bug fixed in Follow-up Scheduler Patch |
| | Pending-comment follow-up reader (DM Sent + DMSent) | 🟩 | [sheets_service.get_pending_comment_followups](ai-agent/app/services/sheets_service.py#L421) | Comment Follow-up Logic Fix |
| **Manager notify** | Gmail SMTP (with App Password) | ✅ | [notification_service._send_email](ai-agent/app/services/notification_service.py) | 20 tests in `test_manager_email_wording.py`; live-tested |
| | Email programmatic body (genitive, conditional deeper_concern) | ✅ | `_georgian_genitive`, `_build_parent_summary` | Email Wording Patch live-tested |
| | WhatsApp manager | ⚠️ | [notification_service._send_manager_whatsapp](ai-agent/app/services/notification_service.py) | **stale v18 URL** at line 28 ([AUDIT_REPORT.md:380](ai-agent/AUDIT_REPORT.md#L380)) — still hardcoded |
| | Twilio SMS | ⚠️ | [notification_service._send_sms](ai-agent/app/services/notification_service.py) | optional; untested live |
| **Follow-up scheduler** | Conversation-marker driven 24h/72h/168h | 🟩 | [followup_service.check_and_send_followups](ai-agent/app/services/followup_service.py#L147) | 35 tests in `test_followup_scheduler.py` + 8-scenario `tools/sim_followup.py` |
| | Admin templates + Georgian fallback | 🟩 | [followup_service._render_followup_text](ai-agent/app/services/followup_service.py#L324) | admin save→render round-trip test |
| | Platform routing preserved | 🟩 | [followup_service._SUPPORTED_PLATFORMS](ai-agent/app/services/followup_service.py#L96) | instagram + messenger tested; whatsapp plumbed |
| | Redis write-through after send | 🟩 | [_save_conversation_to_redis](ai-agent/app/services/followup_service.py#L370) | test_followup_scheduler covers both paths |
| **Admin panel** | `/admin` Jinja2 + Basic Auth | ✅ | [app/routes/admin.py](ai-agent/app/routes/admin.py) | 11 + 13 + 18 + 29 tests across 4 files; live-tested operator UI |
| | Section CRUD + template editor + settings | ✅ | same | live operator edits flowed into LLM `get_camp_info` tool |
| | Agent status row (Enabled/Disabled) | 🟩 | [templates/admin/dashboard.html](ai-agent/templates/admin/dashboard.html#L13) | added in Kill Switch Patch |
| **Persistence (Redis)** | Conversation/processed-comment/manager-notified mirror | ✅ | [redis_state_service](ai-agent/app/services/redis_state_service.py) | 13 tests in `test_redis_persistence.py`; live-tested restart safety |
| | Safe no-op when disabled / unavailable | ✅ | `is_enabled()` lazy connection | conftest autouse fixture pins OFF for full suite |
| **Kill switch** | `AGENT_ENABLED` DM / comment / follow-up gating | 🟩 | [app/services/kill_switch.py](ai-agent/app/services/kill_switch.py) | 21 tests in `test_kill_switch.py`; manual QA |
| | `AGENT_DISABLED_MESSAGE` canonical Georgian | 🟩 | [kill_switch.py:40](ai-agent/app/services/kill_switch.py#L40) | covered |
| | Admin dashboard status display | 🟩 | dashboard.html agent_enabled row | tested |
| **Sentry** | Optional init + 3 capture points | 🟩 | [app/services/sentry_service.py](ai-agent/app/services/sentry_service.py) | 30 tests in `test_sentry_service.py` |
| | Safe no-op when DSN empty OR SDK missing | 🟩 | `_SDK_AVAILABLE` + `_INITIALIZED` | both paths tested |
| | Privacy-safe context (masked sender, no message body) | 🟩 | `mask_sender`, area/platform/stage labels | leak-detection tests in `test_sentry_service.py` |
| | Live Sentry DSN configured | ❌ | `.env` does not contain `SENTRY_DSN` key | grep `.env` confirms; Sentry currently disabled in production |

---

## 5. Tool Registry

8 tools in [PARENT_TOOLS](ai-agent/app/agent/tools/parent_tools.py) (verified `grep ^TOOL_`):

| # | Tool | Purpose | Backend validation / reason codes |
|---|---|---|---|
| 1 | `get_camp_info(topic)` | Camp facts from admin_config (admin-first) + camp_2026.yaml fallback. Topics: `price` / `dates` / `location` / `conditions` / `registration` / `age_range` / `all` | `invalid_topic` (closed enum); `registration_url_missing` when admin URL absent; `knowledge_error` on YAML load failure |
| 2 | `get_available_slots(date_iso?, days?)` | Calendar slots. Date-aware via `get_free_slots(start_date=..., days=...)`. Without date → legacy `_load_available_slots` (max 6 slots returned) | `invalid_date_iso` |
| 3 | `book_consultation(name, phone, datetime_iso, child_age, user_confirmed_datetime, notes?)` | Calendar create + Sheets append + Lead.calendly_booked=True + state=DONE | `missing_name` / `missing_phone` / `missing_child_age` / `datetime_not_confirmed` / `invalid_child_age` / `age_not_eligible` (9–17) / `invalid_phone` / `invalid_datetime` / `datetime_in_past` / `outside_business_hours` / `slot_unavailable` (with `alternative_slots`) / `calendar_error` |
| 4 | `manage_consultation_booking(action, old_datetime_iso?, new_datetime_iso?, phone?, reason?)` | Cancel or reschedule existing booking | `missing_event_id` → `manager_handoff_required=true`; `no_active_booking`; Calendar delete failure → manager handoff |
| 5 | `request_manager_callback(name?, phone?, notes?)` | Manager handoff via Sheets save + notify (idempotent per conversation) | `missing_phone` (no valid 9-digit); idempotent via `manager_notified_for_conversation` |
| 6 | `save_lead_info(name?, phone?, child_age?, challenge?, notes?)` | In-memory Lead update ONLY. Never Sheets, never books, never notifies | challenge merge logic (substring no-op / richer promotion / unrelated append capped at 300 chars) |
| 7 | `switch_to_adult_flow(reason?)` | Soft handoff: sets `conversation.segment = "ADULT"` + `state = "START"` | pure routing; no side effects |
| 8 | `check_consultation_slot(datetime_iso)` | Direct Calendar question — bypasses truncated `get_available_slots` cap | `outside_business_hours` / `weekend` / `buffer_today` / `calendar_busy` / `past_datetime` / `invalid_datetime`; returns `alternative_slots` |

Tool dispatcher: [ParentToolExecutor.execute](ai-agent/app/agent/tools/parent_tool_executor.py#L149). Unknown tool → `{"success": False, "reason": "unknown_tool"}`. Defensive except catches all tool exceptions, captures to Sentry with `{area, tool}`, returns `{"success": False, "reason": "tool_error"}`.

---

## 6. Data Model

### 6.1 Lead ([app/models/lead.py:19-47](ai-agent/app/models/lead.py#L19))

ველები (sequence per dataclass):
`sender_id`, `platform`, `segment`, `name`, `phone`, `child_age`, `challenge`, `deeper_concern`, `desired_change`, `event_interest`, `calendly_booked`, `booked_datetime_iso`, `calendar_event_id`, `conversation_summary`, `status`, `followup_sent`, `created_at`, `last_message_at`.

JSON round-trip via `model_dump(mode="json")` + `from_dict` ([lead.py:49-83](ai-agent/app/models/lead.py#L49)).

### 6.2 Conversation ([app/models/conversation.py:22-70](ai-agent/app/models/conversation.py#L22))

`sender_id`, `platform`, `segment`, `state` (default "START"), `history` (list of `{role, content}`), `lead` (`Lead | None`), `created_at`, `last_activity`, `pending_booking` (JSON-safe dict | None), plus PATCH 3 follow-up readiness markers:
- `last_bot_message_at` (ISO string)
- `followup_stage` (`""` / `"first_24h"` / `"second_3d"` / `"third_7d"` / `"stopped"`)
- `followup_blocked_reason` (`""` / `"booked"` / `"registered"` / `"declined"` / `"asked_no_more_messages"` / `"manager_handoff_completed"` / `"followup_exhausted"`)
- `last_meaningful_interest`, `stopped_after`

`to_dict` / `from_dict` symmetric, JSON-safe ([conversation.py:72-123](ai-agent/app/models/conversation.py#L72)).

### 6.3 Redis keys + TTL ([redis_state_service.py](ai-agent/app/services/redis_state_service.py))

| Key pattern | Writer | Default TTL |
|---|---|---|
| `conversation:{platform}:{sender_id}` | `conversation_service._save_conversation_to_redis` | `REDIS_TTL_SECONDS = 604800` (7d sliding) |
| `manager_notified:{sender_id}` | `parent_tool_executor` post-success | same |
| `processed_comment:{comment_id}` | `webhook.handle_comment` + `comment_service._mark_comment_expired` | same |

Lazy connect ([redis_state_service.py:96-156](ai-agent/app/services/redis_state_service.py#L96)). Password never logged — only `url_configured=True/False` + `connected=True/False`. `REDIS_URL` empty OR `REDIS_ENABLED=false` → pure no-op.

### 6.4 Sheets ([sheets_service.py](ai-agent/app/services/sheets_service.py))

**`Leads` tab** (17 columns, [sheets_service.py:28-46](ai-agent/app/services/sheets_service.py#L28)):
`ID` · `Sender ID` · `Platform` · `Segment` · `Name` · `Phone` · `Child Age` · `Challenge` · `Deeper Concern` · `Desired Change` · `Event Interest` · `Consultation Booked` · `Conversation Summary` · `Status` · `Created At` · `Last Activity` · `Follow-up Sent`

**`Comments` tab** (11 columns, [sheets_service.py:49-61](ai-agent/app/services/sheets_service.py#L49)):
`Comment ID` · `Post ID` · `Sender ID` · `User Name` · `Platform` · `Segment` · `Comment Text` · `Intent` · `DM Sent` · `Status` · `Created At`

Status vocabulary (Comments): `CommentOnly` / `DMSent` / `FollowupSent` / `Expired` (Comment Follow-up Logic Fix 2026-05-31).
Status vocabulary (Leads): `New` / `Qualified` / `Booked` / `FollowUp`.

Datetime format: Asia/Tbilisi ISO with `+04:00` offset (`format_tbilisi_datetime` via [timestamps.py](ai-agent/app/agent/services/timestamps.py)).

### 6.5 Calendar event shape ([calendar_service.create_event:460-484](ai-agent/app/services/calendar_service.py#L460))

```json
{
  "summary": "<lead name + child age>",
  "description": "<lead background + phone + challenge>",
  "start": {"dateTime": "ISO", "timeZone": "Asia/Tbilisi"},
  "end":   {"dateTime": "ISO", "timeZone": "Asia/Tbilisi"}
}
```

**⚠️ doc-vs-code:** AUDIT_REPORT.md §7.2 ([line 360](ai-agent/AUDIT_REPORT.md#L360)) notes event title contains `lead.name + child_age`; this is generated by callers (e.g. `_book_consultation`), not the create_event signature itself.

---

## 7. Tests & QA

**Live pytest run** (verified `python -m pytest tests/ -q`):
```
791 passed, 3 warnings in 171.91s
```

Per-file breakdown (verified `grep -c "^def test_" tests/test_*.py`):

| File | Tests | Area |
|---|---|---|
| `test_parent_llm_engine.py` | 214 | P3-C engine + tools + executor + sanitiser + PATCH 1–8 |
| `test_comment_flow.py` | 50 | Comment Flow PATCH 1/2/3 + hashtag + private reply |
| `test_booked_state_polish.py` | 36 | Booked-state polish |
| `test_followup_scheduler.py` | 35 | Follow-up Scheduler Patch |
| `test_parent_turn_analyzer.py` | 31 | Phase 3.9 unit |
| `test_sentry_service.py` | 30 | Basic Error Monitoring |
| `test_admin_config.py` | 29 | Admin Panel MVP |
| `test_comment_followup_logic.py` | 27 | Comment Follow-up Logic Fix |
| `test_kill_switch.py` | 21 | Kill Switch |
| `test_manager_email_wording.py` | 20 | Email Wording Patch |
| `test_parent_reply_composer.py` | 19 | Phase 3.8 unit |
| `test_knowledge_loader.py` | 19 | knowledge loader |
| `test_admin_form_field_completion.py` | 18 | Admin Field Completion |
| `test_p2.py` | 17 | P2 |
| `test_parent_intent_router.py` | 16 | P0 |
| `test_pending_booking.py` | 15 | P1 |
| `test_admin_comment_routing.py` | 13 | Admin Panel section routing |
| `test_redis_persistence.py` | 13 | P3-B |
| `test_prompt_loader.py` | 13 | prompt loader |
| `test_template_loader.py` | 12 | template loader |
| `test_admin_panel.py` | 11 | Admin Panel routes |
| `test_wording_polish.py` | 11 | Georgian wording polish |
| `test_notification_service.py` | 11 | Booking Notification QA |
| `test_camp_facts_unification.py` | 9 | Config Unification |
| `test_parent_flow_analyzer_integration.py` | 9 | Phase 3.9 integration |
| `test_template_render_equivalence.py` | 3 | template byte-identity |
| **Sum** | **791** | |

**74-scenario suite** ([tools/scenario_library.py](ai-agent/tools/scenario_library.py), verified `grep -oE '"category": *"[a-z_]+"'`):

| Category | Count | Priority distribution |
|---|---|---|
| happy_path | 10 | mixed |
| booking | 8 | mixed |
| objection | 10 | mixed |
| adult | 3 | IMPORTANT-heavy |
| comment | 4 | mixed |
| difficult | 35 | mixed |
| security | 4 | all CRITICAL |
| **Total** | **74** | CRITICAL **23** (library) / **22** (runner reports) — see ⚠️ below |

⚠️ **doc-vs-code mismatch:** the library file contains **23** `priority: "CRITICAL"` entries (verified `grep -oE '"priority": *"[A-Z]+"'`); the runner output ([HANDOFF.md:560](ai-agent/HANDOFF.md#L560)) reports `CRITICAL 22/22`. Most likely 1 CRITICAL scenario is `input_type: comment` and the runner counts it separately under `Comment` bucket. Not a defect, just worth confirming the runner's bucketing rule before any future operator dashboard pulls these numbers.

**Adversarial coverage** (security + difficult categories):
- Jailbreak: SC-71 Role Jailbreak ✅
- Reveal system prompt: SC-72 ✅
- Fake manager identity: SC-73 ✅
- Impossible age: SC-74 ✅
- Prompt injection: SC-62 ✅
- Price manipulation: SC-63 ✅
- HTML injection: SC-64 ✅
- Spam / dots / single emoji / very long: SC-54/55/56/65 ✅

Last full sweep (2026-05-31): **74/74 (100%)**, CRITICAL 22/22 preserved ([HANDOFF.md:556-568](ai-agent/HANDOFF.md#L556)).

**⚠️ Missing dev-deps in `requirements.txt`**:
- `pytest` (tests run, but install assumption is "pip install pytest manually")
- `sentry-sdk` (intentionally optional per [sentry_service.py:46](ai-agent/app/services/sentry_service.py#L46) — but operator MUST install separately for monitoring)
- `redis` (intentionally optional — same pattern)
- `fakeredis` (test-only)
- `Jinja2` + `python-multipart` (transitive via FastAPI but FastAPI Form() parsing requires explicit `python-multipart`)

Production install command MUST include these as a separate pip step. No `requirements-dev.txt` exists.

---

## 8. Security & Ops Posture

| Area | Finding | File:line / verification |
|---|---|---|
| **Webhook signature** | ❌ **Not verified.** `receive_webhook` accepts any POST without `X-Hub-Signature-256` HMAC check. | grep `verify_signature|X-Hub-Signature|hmac` → no matches across `app/routes/`. HANDOFF §5 IMPORTANT 9 acknowledges. |
| **Secrets handling — .env** | Loaded via `dotenv_values(ENV_PATH)` ([config.py:14](ai-agent/app/config.py#L14)). All sensitive values pass through `_env()` and the read-only Settings dataclass; never logged. Password masking in `messenger_service.send_message`, `redis_state_service` (URL log only `url_configured=True/False`), `sentry_service.init` (DSN not logged). | manual trace |
| **`.gitignore`** | ❌ **No `.gitignore` anywhere in the repo tree.** Verified `ls -la "AI sales agent/.gitignore"` → "No such file or directory". HANDOFF.md states `არ commit .env, credentials.json — .gitignore-ში უკვე არის` ([CLAUDE.md:268](ai-agent/CLAUDE.md#L268)) — **⚠️ doc-vs-code mismatch.** | `ls` + parent dir scan |
| **`credentials.json` in working tree** | ⚠️ **Present.** `head -3 credentials.json` shows `"type": "service_account"` + `project_id`. The repo isn't currently a git repo (`Is a git repository: false` in env) so nothing is *pushed* — but the moment the operator runs `git init && git push` without a `.gitignore`, the Google service account credentials would be exposed. | `ls credentials.json` + Read |
| **Rate limiting** | ❌ **Not implemented.** Verified `grep -rE "RateLimit|rate_limit|limiter" app/` → no matches. | grep |
| **PII in logs** | Phone number is NOT masked in some logs (e.g. `[parent_flow] Invalid phone candidate rejected: '3 '` style — but only digit stub, not full phone). Sender IDs ARE masked through `kill_switch.mask_sender` (trailing 4 chars) and `sentry_service.mask_sender` (leading 6 chars). | grep `mask_sender` → 17 callsites |
| **Two `mask_sender` shapes** | ⚠️ **doc-vs-code-ish:** `kill_switch.mask_sender(id)` returns `"***" + id[-4:]`; `sentry_service.mask_sender(id)` returns `id[:6] + "***"`. Different shapes for the same intent across two files. Not a security bug — both still mask — but operator correlating logs from both surfaces will see two formats. | [kill_switch.py:58](ai-agent/app/services/kill_switch.py#L58) vs [sentry_service.py:203](ai-agent/app/services/sentry_service.py#L203) |
| **Single-worker vs multi-worker** | ⚠️ Single-worker only safe. Module-level dicts (`conversations`, `available_slots`, `manager_offer_shown`, `selected_events`, `_processed_comments_lru`, `_pending_messages`) are process-local. Redis handles cross-restart but not cross-process. | [conversation_service.py:15](ai-agent/app/services/conversation_service.py#L15), [parent_flow.py:66-69](ai-agent/app/flows/parent_flow.py#L66) |
| **Scheduler SPOF** | ⚠️ APScheduler runs **in-process** ([app/main.py:42](ai-agent/app/main.py#L42)). Process crash → follow-up tick is lost until next restart. No external job queue. | `BackgroundScheduler` inline init |
| **Observability** | 🟩 Sentry wrapper in place but DSN not configured in live `.env`; structured logs `[conversation] start/completed/error`, `[followup] sent/skipped/error`, `[COMMENT]`, `[booking]`, `[redis]`, `[sentry]`. No log aggregator wired. | `grep` |
| **Webhook GET verify token** | ✅ Implemented ([webhook.py:67-75](ai-agent/app/routes/webhook.py#L67)) — returns `Forbidden` 403 when token mismatch. |
| **Admin auth** | ✅ HTTP Basic with `secrets.compare_digest` constant-time check ([admin.py:52-87](ai-agent/app/routes/admin.py#L52)). Refuses 503 when ENABLED but no password set. |
| **OpenAI key / SMTP password handling** | ✅ Loaded from `.env` via `_env`, never appear in logs or git. SMTP password explicitly noted as Gmail App Password in `.env.example`. |

---

## 9. Known Bugs / TODO / Dead Code

Cross-referenced AUDIT_REPORT §8/9 against current code — flagging only items still present:

| Item | Status (against current code) | File:line |
|---|---|---|
| Meta v18 hardcoded in notification_service (manager-WhatsApp) | **⚠️ Still present** — AUDIT_REPORT §8.1 | [notification_service.py:28](ai-agent/app/services/notification_service.py#L28) — `https://graph.facebook.com/v18.0` |
| `.env.example` stale `CAMP_PRICE=2200` | **⚠️ Still present** (line 107) | [.env.example:107](ai-agent/.env.example#L107) `CAMP_PRICE=2200` — knowledge YAML resolves at runtime so behavior is OK but operator-facing doc misleading |
| In-memory conversation state | **⚠️ Partially mitigated** by P3-B Redis write-through — but the active scan in follow-up scheduler still uses `conversation_service.conversations` dict ([followup_service.py:163](ai-agent/app/services/followup_service.py#L163)). Restart can lose cold leads in the window between restart and next user message. HANDOFF acknowledges as "Redis conversation index" remaining risk |
| Webhook signature unverified | **❌ Still present.** See §8 above |
| Lead not stored in Sheets during discovery | **Still by design.** `create_lead` only runs at booking ([parent_tool_executor._book_consultation](ai-agent/app/agent/tools/parent_tool_executor.py)). Discovery-only leads ride on Conversation markers + Redis instead. **Risk lower now** that Redis is in place |
| `OpenAIService` / `ContentRepository` / `FlowContext` / `SafeFormatter` / `_extract_template_section` / `MessengerService` / `SheetsService` / `NotificationService` / `FollowupService` classes — dead | **⚠️ Still present** per AUDIT_REPORT §9 — legacy injection pattern, never instantiated. Removed in 0 patches since 2026-05-22. Inert but adds reading load. |
| `data/prompts.py:106` `PARENT_CHALLENGE_OPTIONS: list[str] = []` | **⚠️ Still present** |
| Dead `parent_flow` helpers: `_generate_parent_response`, `_end_with_consultation_offer`, `_format_available_slots`, `_wants_consultation` | **⚠️ Still present** |
| Calendar lazy client per call (rate-limit risk) | **⚠️ Still present** per AUDIT_REPORT §8.10 |
| Sheets lazy client per call | **⚠️ Still present** per AUDIT_REPORT §8.11 |
| `_extract_meta_messages` ignores attachments / postbacks | **⚠️ Still present** ([webhook.py:435-451](ai-agent/app/routes/webhook.py#L435)) — text-only event extraction; image/voice/sticker user messages silently dropped |
| `adult_flow._booking_question` template fragility | **⚠️ Still present** |
| ADULT KNOWLEDGE_FACT-ები still in `data/prompts.py` | **⚠️ Still present**, parallel to YAML |
| Sentry SDK + `redis` + `pytest` not in `requirements.txt` | **⚠️ Still present** — intentional for sentry/redis (optional), accidental for pytest |

No new code-level TODO/FIXME/XXX markers found in `app/` (verified `grep -nE "TODO|FIXME|XXX:"` → only docstring references in CLAUDE.md / HANDOFF.md).

---

## 10. Gaps & Improvement Backlog

რანჟირებული — impact × effort. ერთი წინადადება + სავარაუდო დრო.

| # | Item | Impact / Effort | Time | Why |
|---|---|---|---|---|
| 1 | **`.gitignore` add + secret rotation if pushed** | HIGH / TINY | 30 min | No `.gitignore`; `credentials.json` in working tree; immediate exposure when operator inits git. **Critical pre-deploy.** |
| 2 | **Webhook signature verification (`X-Hub-Signature-256` HMAC)** | HIGH / SMALL | 2–3h | Endpoint accepts any JSON; production attack surface; META_APP_SECRET already in `.env`. |
| 3 | **Meta v18 → v19 in notification_service** | MEDIUM / TINY | 15 min | Replace hardcoded URL with settings read; affects manager-WhatsApp delivery once v18 sunset. |
| 4 | **`requirements-dev.txt` + pin Sentry/redis/pytest** | MEDIUM / SMALL | 1h | Production install currently requires hidden pip steps; CI reproducibility risk. |
| 5 | **Connect Sentry DSN in `.env`** | MEDIUM / TINY | 5 min + Sentry account setup | Sentry code ready but disabled in production until operator adds DSN. |
| 6 | **Add Redis conversation index for restart-safe follow-up snapshot** | MEDIUM / MEDIUM | 1 day | Currently `get_all_conversations_snapshot` is in-memory only; restart loses follow-up eligibility window. Add `SADD conversation:active <sender_id>` + load on first tick. |
| 7 | **WhatsApp manager + outbound live verification** | MEDIUM / SMALL | 0.5 day | Plumbed but never run end-to-end; one careful operator test would close the loop. |
| 8 | **Adult flow LLM engine (P3-D) + first live test (P3-E)** | MEDIUM / LARGE | 3–5 days | ADULT state machine + PATCH 7 global guard work, but no LLM engine, no live driving of SHOW_EVENTS → SEND_BOOKING. |
| 9 | **`adult_defaults.yaml` migration — remove `data/prompts.py` constants** | LOW / SMALL | 2h | Duplicated knowledge layer per AUDIT_REPORT §8.14. |
| 10 | **Calendar/Sheets client caching** | LOW / SMALL | 2h | Per-call client rebuild creates rate-limit risk at scale (>100 leads/h). |
| 11 | **Dead-code purge (OpenAIService, FlowContext, parent_flow helpers, ADULT_DEFAULT_*)** | LOW / SMALL | 2h | ~600 LOC inert; quality-of-life, no behavior change. |
| 12 | **Unify `mask_sender` shape** between kill_switch and sentry_service | LOW / TINY | 15 min | Two different masks make log correlation across surfaces awkward. |
| 13 | **Image/postback/sticker webhook handling** (acknowledgment or routing) | LOW / SMALL | 2h | Currently silently ignored — user who sends a photo gets nothing back. |
| 14 | **Rate limiting (per-sender outbound throttle, anti-spam)** | LOW / MEDIUM | 1 day | Production hardening; not urgent for a single tester traffic level. |
| 15 | **Out-of-process job queue (RQ / Celery) for schedulers** | LOW / LARGE | 3 days | Removes APScheduler SPOF; only relevant once traffic > single-worker. |

---

## 11. რა ვერ დადასტურდა მხოლოდ კოდით

ფაქტები / artifacts რასაც screenshot, live transcript, ან external system სჭირდება:

| Item | რა გვჭირდება |
|---|---|
| **Google Sheets `Leads` tab — actual columns + sample row** | Header screenshot from the live spreadsheet + one anonymised data row to confirm `_lead_to_row` ordering matches reality. Code says 17 columns ([sheets_service.py:28-46](ai-agent/app/services/sheets_service.py#L28)) but column index alignment can only be verified against the actual sheet. |
| **Google Sheets `Comments` tab — actual columns + sample row** | Same for the 11-column `Comments` tab. The Comment Follow-up Logic Fix relies on column I = `DM Sent` AND column J = `Status`; operator confirmation of header text + value vocabulary (`CommentOnly` / `DMSent` / `FollowupSent` / `Expired`) would close the loop. |
| **Calendar event — real shape after `book_slot`** | One Google Calendar event ID (manually opened in calendar.google.com) showing the rendered `summary` + `description` + `start`/`end` zones. Helps verify the lead.name + child_age rendering. |
| **Admin panel screenshots** | `/admin` dashboard (Agent status row), `/admin/programs/summer_camp` edit form, `/admin/templates` (followup_24h textarea). The HTML templates in [templates/admin/](ai-agent/templates/admin/) describe the structure but the rendered UX needs eyes. |
| **`.env` keys list (without values)** | `grep -oE "^[A-Z_]+=" .env` already collected — see §2.4. Operator should confirm whether the missing keys (`AGENT_ENABLED`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`) are intentionally absent or pending sync from `.env.example`. **Don't paste values.** |
| **2–3 live transcripts** | One PARENT happy-path booking (Instagram DM) showing engine output. One PARENT booked-state recall ("ჩემზე რა ინფორმაცია გაქვს?") showing the deterministic memory-info reply in production. One comment INTERESTED flow showing private DM + (optional) public reply outcome. |
| **Meta App Review state** | Screenshot of the FB Developer Console showing `pages_manage_engagement` permission status — code is ready (`ENABLE_PUBLIC_COMMENT_REPLY=True` default) but the permission state can only be confirmed in Meta's UI. |
| **Email body for a real booking** | One manager-notification email (Gmail) for a real booking to confirm the programmatic body (`_georgian_genitive` + conditional `deeper_concern` + Georgian booking-datetime) renders without `სიტყვის აკადემიაის` or `ღრმა ფესვი:` artifacts. |
| **Comment follow-up scheduler tick — live log from the next hour** | After the 2026-05-31 Comment Follow-up Logic Fix deploy, one hourly log slice showing `[COMMENT] Pending follow-ups: 0` (or a small finite number) instead of the previous 400-retry-spam. |
| **Redis live state** | One `redis-cli KEYS conversation:*` output to confirm key shape + TTL behavior matches code expectations (`conversation:{platform}:{sender_id}`). Don't paste payload contents. |

---

## 12. Final Verdict

### 12.1 Per-area maturity

| Area | Maturity | Notes |
|---|---|---|
| PARENT flow (engine + tools + booking) | **production-ready core** | live-tested; 214 + 41 + 36 tests; 22/22 CRITICAL scenarios |
| ADULT flow | **MVP** | code complete, untested live end-to-end |
| Comment flow (intent + private DM + rich first-contact) | **production-ready** | live-tested; recent 2026-05-31 logic fix removed 400 retry-loop |
| Public comment reply | **ready-to-activate** | code default True; waiting on Meta App Review |
| Booking (Google Calendar) | **production-ready** | live-tested |
| CRM (Google Sheets) | **production-ready** | live-tested |
| Manager email | **production-ready** | live-tested Gmail SMTP |
| Manager WhatsApp / Twilio SMS | **MVP** | plumbed, untested live; v18 URL drift |
| Follow-up scheduler | **MVP** | 35 + 27 tests; QA via `tools/sim_followup.py`; restart-safety partial (Redis conversation index pending) |
| Admin panel | **production-ready** | live-tested operator UI |
| Redis persistence | **production-ready** | safe-fallback shape; live-tested restart |
| Kill switch | **production-ready** | 21 tests; manual QA verified |
| Sentry / Error Monitoring | **production-ready code, not connected** | 30 tests; SDK not in requirements; DSN not in live `.env` |
| Multi-worker scaling | **NOT READY** | module-level dicts process-local; APScheduler in-process SPOF |
| Webhook signature verification | **NOT BUILT** | acknowledged blocker |

### 12.2 Overall level

**Production-ready core for the templated client on a single-worker deploy.**

The PARENT happy-path is live and stable; the supporting infrastructure (Redis, Sentry, Kill Switch, Follow-up, Admin Panel) is in place but several pieces (Sentry DSN, multi-worker, webhook signature, WhatsApp manager) require the operator to do the last ~10% of integration / verification work before a wider rollout.

### 12.3 Top-5 next steps (descending priority)

1. **Add `.gitignore` + verify `credentials.json` never reaches a public remote.** Tiny effort, blocks the highest-impact failure mode.
2. **Webhook HMAC signature verification.** Closes the only outright security blocker.
3. **Sync `.env` from `.env.example`** — at minimum add `AGENT_ENABLED`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`. Then `pip install "sentry-sdk[fastapi]"` for live monitoring.
4. **Add `requirements-dev.txt` (pytest + sentry-sdk + redis + fakeredis + python-multipart)** for reproducible production installs.
5. **Adult flow live audit (P3-E)** OR **Meta App Review submission for `pages_manage_engagement`** — pick the higher-business-value one based on traffic mix.

---

**End of review. No code modified.**
