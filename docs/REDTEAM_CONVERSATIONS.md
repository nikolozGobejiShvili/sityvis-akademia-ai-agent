# RED-TEAM — CONVERSATION-LEVEL (non-linear, chaotic real-user) audit

**Date:** 2026-06-13 · **Mode:** AUDIT ONLY — no production code changed, no live server / webhook / tick / Meta / Redis / Calendar / Sheets / email / OpenAI. Only this file written.
**Baseline:** `pytest` 2222 passed / 0 failed. **Production NOT green.**
**Method:** read the deterministic guards (file:line) + a throw-away **read-only offline harness** (`_redteam_conv_scratch.py`) that called the REAL pure functions (`maybe_capture_child_age_fallback`, `_parse_name_phone`, `_distinct_valid_phones`, `_maybe_requalify_child`, `_is_reschedule_request`, `_maybe_capture_adult_target`, `is_interest_intent`, `_classify_segment`, `_is_parent_consultation_intent`, `resolve_relative_datetime`) on in-memory `Lead`/`Conversation` objects — no I/O. **The harness was DELETED after the run (confirmed `ls` → not found).** LLM-composed replies are marked **NEEDS LIVE CHECK** — not guessed, not called confirmed bugs.

> Scope note: previous red-teams tested individual INPUTS. This one tests whole NON-LINEAR CONVERSATIONS. The recurring theme: the deterministic guards are strong on FIRST capture and on hard safety (no fake/free bookings, no crashes), but **self-correction and multi-entity state ("no, actually…", "my second child…", "for myself instead") are weakly handled** — exactly what a chaotic client does.

---

## ✅ B-GROUP DEGRADED FINDINGS — FIXED (2026-06-13, Red-Team B Self-Correction Batch, 2222 → 2287)

All four DEGRADED findings (B5, B4, B2, B1) + the M1 metamorphic divergence were fixed deterministically, one at a time with a full-`pytest` gate after each (+65 tests in [tests/test_redteam_b_selfcorrection_fixes.py](../tests/test_redteam_b_selfcorrection_fixes.py)). Final suite **2287 passed / 28 skipped / 0 failed**, corpus 9/9, `RUN_PROPERTY_TESTS=1` property 28/0 (M1 now passes), CRITICAL 22/22. **Production STILL NOT green.**

- ✅ **B5 (DEGRADED → FIXED)** — `parent_flow._maybe_requalify_child` now has a `_lead_has_active_booking` guard: a booked child's age is never wiped/overwritten by „ჩემი მეორე შვილი 14 წლისაა"; returns `_BOOKED_SECOND_CHILD_MANAGER` (no clear, no booking, no Calendar/Sheets write).
- ✅ **B4 (DEGRADED → FIXED)** — `adult_llm_engine._maybe_capture_adult_target` reverts to self on „ჩემთვის"/„მე მინდა"/„მე მაინტერესებს"/„ჩემთან" when no relative cue (M4 child synonyms unaffected).
- ✅ **B2 (DEGRADED → FIXED)** — `parent_flow._parse_name_phone` / `_name_token_is_valid` strip a refusal/correction prefix („არა, ნინო მქვია" → „ნინო"); bare „არა" stays a refusal; „ბარბარა"/„ანა" (substring) uncorrupted.
- ✅ **B1 (DEGRADED → FIXED deterministically)** — `parent_llm_engine.maybe_capture_child_age_fallback` lets explicit correction markers (`არა`/`შევცვალე`/`უფრო სწორად`/`ვგულისხმობდი`/`აბა`) update an already-set `child_age`; second/different-child mentions excluded; fresh-lead keep-first unchanged. (No longer "NEEDS LIVE CHECK".)
- ✅ **M1 (metamorphic) — FIXED** — `_GEORGIAN_AGE_NUMERALS` (9–17) read with age context.

> The MINOR findings (A-asym, OVR-gap, DEC-fp, F1, F3, G1/G4) and the NEEDS-LIVE-CHECK clusters below remain **carried-open** (not addressed by this batch). The MINOR DEC-fp (partial-negation false-decline) and A-asym (PARENT→ADULT switch is LLM-only) are good candidates for a follow-up.

---

## ✅ P0 LIVE DEMO UX REGRESSION — FIXED (2026-06-14, 2287 → 2322)

The operator-reported real-Messenger live-demo transcript issues (intent routing + answer formatting) are **FIXED** deterministically (+35 tests in [tests/test_p0_live_demo_ux_fixes.py](../tests/test_p0_live_demo_ux_fixes.py)). Suite **2322 passed / 28 skipped / 0 failed**, corpus 9/9, `RUN_PROPERTY_TESTS=1` property 28/0 (M1–M6 hold), CRITICAL 22/22, new real-model transcript scenarios SC-TX-01/02/03 → 3/3. **Production STILL NOT green.** Details (file:line) in HANDOFF / REVIEW_PACK / CLAUDE. Summary: ISSUE 1 clear camp intent skips the disambiguation menu (`parent_flow._has_explicit_georgian_camp_intent` + `_maybe_static_welcome`); ISSUE 4 „ღონისძიების ფასი" never returns the camp price (`parent_flow._maybe_handle_event_inquiry`); ISSUE 5 unknown date/title/guest searched against the active list, found→from data, miss→list+manager-verify (`admin_config_service.find_active_events_by_reference` / `find_active_events_on_day`); ISSUE 2/3/6 paragraph formatting via deterministic `parent_flow._format_multipoint_paragraphs` (real output, not a mock). **Read-only active-data audit:** „გია მურღულია" IS present (answers from data), „გალაკტიონის საღამო" absent, no event on the 16th. **⚠️ The camp-price reorder prompt instruction was tried and REVERTED (caused the SC-26 price-omission regression) — do NOT re-introduce it.**

## ✅ LIVE P0 HOTFIX — FIXED (2026-06-14, 2322 → 2334)

Two live-Messenger UX bugs (+12 tests in [tests/test_p0_live_hotfix.py](../tests/test_p0_live_hotfix.py)). Suite **2334 passed / 28 skipped / 0 failed**, corpus 9/9, property 28/0, CRITICAL **22/22 on re-run** (PARENT booking/slot/screen flakes are real-model stochasticity, not a regression), transcript 3/3. **Production STILL NOT green.**
- **BUG 1** (clear camp intent → generic menu in live) = **(d) STALE PROCESS** — code already correct (full-path trace), NO code change; **operator must restart the live process**. Full-path regression tests added (process_message, engine ON).
- **BUG 2** (named event asked self/child target + age first, then a future-event subscription CTA) = **(a) missing logic** + **(ii) prompt-emitted CTA**. Fixed with a deterministic named-event direct-answer branch in `adult_llm_engine` (`_maybe_handle_named_adult_event` / `_render_named_adult_event` / `_has_specific_event_name`, wired before `_maybe_capture_adult_target`): a named event resolving to one active event is answered directly (title/date/format-location/price/link + soft „სხვა ღონისძიებებიც ჩამოგითვალოთ?"), bypassing the LLM → no target/age questions, no subscription CTA. `_maybe_capture_adult_target` untouched (**FIX 3 / B4 intact**); unknown/ambiguous → existing fallback; `_is_subscription_consent` untouched; subscription CTA still allowed on an explicit future-updates request. **NO prompt edit** (`system_adult_v1.md` byte-identical). Operator confirmed both fixed in live testing.
- Carried-open prompt-audit findings (separate gated tasks): **SL-1** (CRM summary can echo unverified event facts — ADOPT recommended), **AD-2** (ADULT CTA over-repetition), **AD-1** (revise: list active events after target known), system_parent_v2.md bloat consolidation, lost-in-the-middle probe; plus a P1 polish — a vague event mention („მოწვეული სტუმრები გყავთ?") deflects to a manager instead of checking the active list.

## 🟦 B5 × B1 on a booked lead — VERIFIED, then DEFERRED by operator (2026-06-16)

**Update (2026-06-15/16):** the full agent test sweep VERIFIED this risk — on a BOOKED lead a direct first-child age correction („არა, 15") DOES silently overwrite the booked `child_age` (10→15) with no manager handoff (5/5 runs; evidence in [docs/FULL_AGENT_TEST_SWEEP_REPORT.md](FULL_AGENT_TEST_SWEEP_REPORT.md)). The **operator has DEFERRED the fix** (unrealistic edge case) — do **NOT** fix unless explicitly requested later. The recommended fix, if/when requested, is a booked-lead guard on the B1 fallback at the `parent_llm_engine.run_parent_llm_turn` call site (manager-handoff instead of silent overwrite). Original analysis below.

Self-correction × booking interaction not yet resolved: on a **booked** lead, a direct **first-child** age correction („არა, 15" — a self-correction, NOT a second child) may take the **B1** path (`parent_llm_engine.maybe_capture_child_age_fallback`) and **silently overwrite the booked `child_age`** with no manager handoff — the **B5** guard (`parent_flow._maybe_requalify_child` `_lead_has_active_booking`) only covers the re-qualify / second-child path, not the B1 fallback. **UNVERIFIED** whether the booked/DONE state short-circuits the age fallback first. Decision needed: confirm, and if unsafe add a booked-lead guard to the B1 fallback (manager-handoff instead of silent overwrite). Do NOT assume it is safe. (Scheduled to be probed in the upcoming full test sweep.)

---

## ✅ P1 Live Polish + under-age handoff dispatch + named past events (2026-06-15/16, 2334 → 2374)

Suite **2374 passed / 28 skipped / 0 failed**, corpus 9/9, `RUN_PROPERTY_TESTS=1` property 28/28, `test_agent.py` ✅, CRITICAL 22/22, transcript 3/3. **Prompts byte-identical; event data `sections.yaml` unchanged; production STILL NOT green.** Three sessions, recorded together (full file:line in HANDOFF „✅ LATEST" / REVIEW_PACK / CLAUDE):

- ✅ **Under-age manager handoff now ACTUALLY dispatches** (`parent_flow._maybe_handle_underage_manager_handoff` → `notification_service.notify_manager_handoff`, message-only, NO Sheets/Calendar; success only on real dispatch; fallback `558 67 47 33` or retry).
- ✅ **Manager-handoff contact collection polished** (booking style): name+phone together when name unknown; phone-only when known; ask the missing field on partial input; never „სახელი და ნომერი გადავეცი" unless both present (generic success „ინფორმაცია მენეჯერს გადავეცი").
- ✅ **Past / unknown NAMED events resolve BEFORE the self/child target question** — fresh ADULT (`adult_llm_engine._maybe_handle_named_adult_event` past/not-found branches, gated by `_has_genuine_event_name_token`) AND after camp/under-age context (`parent_flow._maybe_handle_event_inquiry` named-event firing + `_render_past_event_inquiry`). Gia Murghulia (14 ივნისი) → „უკვე გაიმართა"; never „თქვენთვის თუ შვილისთვის?" first. Closes the carried-open „vague/named event deflects" item for named/past events. (A truly generic „ღონისძიება მაინტერესებს" still defers to the engine.)
- ✅ **Wording** — „მოგიწოდებთ" → „გთხოვთ" (PARENT+ADULT sanitisers); handoff/event answers paragraph-broken.
- ✅ **Date-bomb / stale-event cleanup (tests/scenarios only)** — active-event direct-answer tests use a synthetic active fixture; Gia past behavior tested separately; SC-TX-03 U5 → past wording; `test_live_qa_bug_fix` + `test_parent_reschedule_state_and_time` date assertions made clock-relative; conftest `_block_real_smtp` net so no test opens a real SMTP connection.

**DEFERRED by operator (do NOT fix unless requested):** booked-age overwrite (B5×B1, see section above); Formula/fromula parsing; Formula/fromula active test-event data cleanup.

**NEXT TASK:** Saturday consultation-booking scheduling policy (allow Saturday, keep Sunday blocked, weekdays unchanged; preserve hours/TZ/FreeBusy/conflict checks/Calendar+Sheets schema).

**Live-smoke re-test checklist (operator, after a local restart — needed because the fixes are in code but a stale process may run old code):**
1. „გამარჯობა ბანაკიმაინტერსებს" (typo / no-space camp intent) → camp flow, no generic menu.
2. „8 წლის არის" → „დამაკავშირეთ მენეჯერთან" → agent asks name+phone together (name unknown) → on real dispatch confirms; manager email shows name + phone + reason; NO Calendar/Sheets row.
3. „ასევე მაინტერესებს გია მურღულიას ღონისძიება როდის არის?" → „უკვე გაიმართა — 14 ივნისი 20:00" + active list on the FIRST try, no target/age.
4. Saturday consultation — AFTER the scheduling-policy task is implemented.

---

## ✅ LATEST — UNDER-AGE HANDOFF NAME + MANAGER-NUMBER FIX (2026-06-22, 2676 → 2704)

A live PARENT transcript for an **8-year-old (under-age)** exposed two deterministic-layer bugs in the manager-handoff contact collection — exactly the "self-correction / chaotic real input" class this audit tracks, now in the under-age path.

- **Name false-positive (comms verb stored as a name).** „კი მომწერე" → the parser stored „მომწერე" as the parent's NAME („სახელი მივიღე…"). Fixed: `_NAME_REJECT_STEMS` now rejects the comms-imperative verbs („მომწერ"/„გამომიგზავ"/„გამიგზავ") and the role word „მენეჯერ" at every name chokepoint (`is_valid_person_name`). Real names (ნინო/ნიკოლოზი/მარიამი) unaffected. Adjacent to the B2 / name-capture class.
- **Manager-number request shadowed by the under-age handoff.** „მენეჯერის ნომერი მომწერე" was re-routed to contact collection (re-asking the PARENT's number) because `_maybe_handle_underage_manager_handoff` runs before `_maybe_handle_explicit_manager_request` and intercepts any „მენეჯერ" mention for an under-age lead. Fixed: the under-age handoff now serves a pure manager-NUMBER request itself (`_is_explicit_manager_number_request` → `_render_manager_number_answer`, the configured `558 67 47 33`), in-memory only — no Sheets/Calendar/dispatch.
- **Bonus (determinism).** „კი მომწერე" is now recognised as a handoff affirmative (leading კი/დიახ/ჰო/ხო/კარგი/ოკ + a „contact me" verb) → it asks for name + phone instead of falling to the LLM.

`pytest tests/` **2704 / 0 failed / 28 skipped** (2676 → +28 in `tests/test_underage_handoff_name_and_manager_number_2026_06_22.py`). All in `app/flows/parent_flow.py`. **No prompt/YAML/Calendar/Sheets/WhatsApp change. Production STILL NOT green** (live smoke of this fix pending — replay the 8yo transcript after a hard restart).

---

## ✅ LIVE-DEMO POLISH BATCH (2026-06-21/22, 2633 → 2676)

Three of these six fixes directly close conversation-level chaotic-client weaknesses this audit flagged (self-correction + objection handling), found via a live transcript + a read-only multi-agent adversarial review (→ `docs/LIVE_TEST_CHECKLIST_2026_06_22.md`).

- **Price-objection ≠ decline (NEW conversation bug).** „…არ მინდა, მაგრამ ბავშვი ძალიან მინდა" was cold-closed as a refusal (substring „არ მინდა"). Fixed: `parent_flow._maybe_handle_decline_engine` defers to the engine when a decline phrase co-occurs with `_DECLINE_OVERRIDE_INTEREST = (მაგრამ, თუმცა, მაინც, ძვირ, მიჭირს)`. Real declines (no contrast) still close.
- **Phone correction (adjacent to B-group self-correction).** „ნომერი შევცდი, სწორია 595…" was ignored (phone captured only when empty). New `_maybe_handle_contact_correction` overwrites `lead.phone` (last valid number) on an explicit correction. In-memory only; committed booking → ack, no Calendar/Sheets write.
- **Name correction (extends B2).** „ნინო კი არა, მარიამი" was ignored once a name was set. Same interceptor overwrites `lead.name` (last valid Georgian name token). AGE correction (B1) untouched.
- Plus (non-conversation-state): PARENT manager-number disclosure + context-aware, mid-conversation „გამარჯობა" strip, anti-repeat varied contact-ask. Full detail in HANDOFF „✅ LATEST" / REVIEW_PACK / CLAUDE.

Suite **2676 / 0 failed / 28 skipped**, corpus 9/9, property 28/28, CRITICAL effectively 22/22 (4 stochastic flakes pass on rerun), transcript 3/3. **No prompt / YAML / Calendar / Sheets / WhatsApp change. Production STILL NOT green.**

> Carried-open conversation weaknesses still LLM-only (no deterministic guard): **off-topic deflection** (e.g. „მუფასა ვინ არის") and **Georgian-only / English-leak** — flagged as the NEXT hardening task (operator-deferred).

---

## ✅ CONSULTATION FLOW MEMORY / REPEATED AGE FIX (2026-06-20, 2608 → 2633)

Closes a cross-turn STATE-MEMORY weakness of exactly the class this audit flagged ("self-correction and multi-entity state are weakly handled"): a fact the parent already gave was not remembered, so the agent re-asked it like a script. Live bug — „14 წლის არის 595999733" (child age + phone in ONE message) stored the phone but kept asking „რამდენი წლისაა თქვენი შვილი?" turn after turn.

- **Root cause — extraction (+ turn order), NOT a state-key mismatch.** `parent_llm_engine.maybe_capture_child_age_fallback` bailed on any `_PHONE_HINT_TOKENS` prefix (`595`/`598`/`599`…), so a message carrying a phone never captured the age; `child_age` stayed empty and the LLM (correctly, per its prompt) re-asked for the genuinely-missing fact. Capture also ran POST-turn. Canonical fields `lead.child_age` / `lead.phone` were never in conflict.
- **Fix** (all in `app/agent/llm/parent_llm_engine.py`): strip phones BEFORE age parsing (`_strip_phone_numbers`, reuses the canonical `parent_flow` phone detector); deterministic single-phone fallback (`maybe_capture_phone_fallback` — never overwrites, never touches `child_age`); PRE-turn merge (`_capture_turn_facts` at the top of `run_parent_llm_turn`, before the context is built); state-driven anti-repeat guard (`_suppress_redundant_age_question` → next missing detail: phone, else day/time). Pre-booking age correction („არა, 15 წლისაა" → 15) preserved. **No phrase hack; no prompt change** — the prompt already forbade re-asking known facts.
- **Relation to B1.** B1 (age self-correction capture) is the adjacent deterministic-age weakness; this fix hardens the same capture layer for the compound age+phone message and adds the cross-turn anti-repeat guard.
- **Tests** — new `tests/test_consultation_age_memory_2026_06_20.py` (+25, through `parent_flow.handle` / `process_message`, engine ON, mocked OpenAI). Suite **2633 passed / 0 failed / 28 skipped**, corpus 9/9, property 28/28, CRITICAL effectively 22/22 (SC-63 stochastic — PASS/FAIL/PASS, no pricing code touched), transcript 3/3. **Prompts byte-identical; event/KB (`sections.yaml`/`camp_2026.yaml`) + Calendar/Sheets schema unchanged; production STILL NOT green — live smoke pending.**

---

## Summary counts

| Severity | Count | IDs |
|---|---|---|
| **BLOCKER** | **0** | — |
| **DEGRADED** | **4** | B5, B4, B2, B1 |
| **MINOR** | **6** | A-asym, OVR-gap, DEC-fp, F1, F3, G1/G4 |
| **NEEDS LIVE CHECK** | **7 clusters** | A1–A4 wording, B1 LLM-correct, C1–C5, D1–D6, E1–E5, F5, G3 |

**Deterministically SAFE (proven offline):** B3 (phone contradiction), C2 (vague age), F2 (un-offered slot), F4 (past date), G2 (comment „ფასი?"), A2 final decline, plus the DATA layer of D (price/booking grounded + executor-validated) and E3 (challenge/name/age capture cleaned).
**Need live testing:** all LLM-composed wording (A topic-jumps, C vagueness, D manipulation phrasing, E emotional/off-topic/mixed-language), B1 age self-correction (does the LLM call `save_lead_info`?), F5 multi-person, G3 in-DM topic change.

**Top 3 risks for a chaotic client**
1. **Self-correction blind spots** — "არა, 15" (age), "ჩემთვის" after "შვილისთვის" (target), "არა, ნინო" (name) can leave **stale / wrong / corrupted** lead data (B1, B4, B2). Chaotic clients self-correct constantly.
2. **Multi-child parent** — booking for a 2nd child overwrites the single-child lead and collides with the 1st booking (B5).
3. **Topic-jump dead-ends & silent booking abandonment** — a PARENT-segment user who wants adult events is not switched deterministically (A-asym); a "not this day, the other day" phrasing fires a full decline and drops the in-progress booking (DEC-fp).

---

# BLOCKER

**None.** No chaotic multi-turn sequence produced a fake/free booking, a crash, a wrong-slot commit, or an unrecoverable loop in the deterministic layer. Hard safety holds: the booking executor validates eligibility + slot availability + future-only datetime and compares the actual booked ISO to the requested ISO (`slot_mismatch` rollback); the fake-booking sanitiser gates "ჩაგინიშნე" on real tool success; segment routing never crashes; price comes from grounded `get_camp_info` (camp_2026.yaml), not free text. The CRITICAL security suite (SC-62 Prompt Injection, SC-63 Price Manipulation, SC-64 HTML Injection, SC-71 Role Jailbreak, SC-72 Reveal System Prompt, SC-73 Fake Manager Identity) passes 22/22.

---

# DEGRADED

## B5 — Multi-child after booking corrupts the age↔booking linkage
**Conversation:**
1. „გამარჯობა, ბანაკი მაინტერესებს" → PARENT
2. „10 წლის შვილი მყავს" → `child_age=10`
3. books a consultation → `calendly_booked=True`, `booked_datetime_iso=…`, `calendar_event_id=evt_10yo`
4. „მეორე შვილი 14 წლისაა, ისიც მინდა ჩავწერო"

**What broke (proven offline):** `_maybe_requalify_child` ([parent_flow.py:848-874](../app/flows/parent_flow.py#L848)) matches „მეორე შვილ" (in `_REQUALIFY_CHILD_PHRASES`, [:827-836](../app/flows/parent_flow.py#L827)) and **clears `child_age` 10 → 14 even though the lead is BOOKED** — there is no `calendly_booked` guard at [:856](../app/flows/parent_flow.py#L856). Harness result: `child_age='14' | calendly_booked still: True | booked_iso still: 2026-07-01T10:00 | event_id still: evt_10yo`. The lead now claims child 14 but holds a consultation booked for the 10-year-old. The data model is **one child + one booking per lead** (single `child_age` / `booked_datetime_iso` / `calendar_event_id`), so a 2nd booking will reschedule/cancel or shadow the 1st.
**Expected:** keep the 1st child's booking intact and tell the parent "one consultation per child — for a second child I'll connect the manager", OR model children separately.
**Code path:** `_maybe_requalify_child` (clears on a booked lead) → single-child `Lead` fields ([lead.py]) → 2nd booking reuses the same booking fields.
**Severity:** DEGRADED (wrong CRM age + booking collision for any 2-child parent — a very common real case).
**Smallest fix:** add a `calendly_booked` guard to `_maybe_requalify_child` (don't silently wipe a booked child's age) and emit a "second child → manager / separate booking" message. **Fix-now** for the booked-guard (cheap); full multi-child modelling = **defer** (this is the carried ROOT 4).

## B4 — Adult target never reverts to "self" after a correction
**Conversation (ADULT flow):**
1. „კულტურული ღონისძიება მაინტერესებს" → ADULT
2. „შვილისთვის" → `adult_target_relation='შვილი'`
3. „არა, ჩემთვის" (correcting — for myself)

**What broke (proven offline):** `_maybe_capture_adult_target` ([adult_llm_engine.py:546](../app/agent/llm/adult_llm_engine.py#L546)) captures the relation from `_ADULT_RELATIVE_PATTERNS` but **has no pattern for a self-reference ("ჩემთვის") that would CLEAR the stored relation**. Harness: after „შვილისთვის" → `rel='შვილი'`; after „ჩემთვის" → **still `rel='შვილი'`**. The agent keeps filtering events for the child and asks the child's age when the user now wants events for themselves.
**Expected:** "ჩემთვის" / "ჩემთვის მინდა" clears `adult_target_relation`/`adult_target_age` and reverts to self.
**Code path:** `_maybe_capture_adult_target` only ADDS a relation, never removes it.
**Severity:** DEGRADED (wrong audience/eligibility after a normal self-correction).
**Smallest fix:** detect self-reference stems ("ჩემთვის", "მე მინდა", "ჩემთვის არის") and clear the adult-target fields before re-evaluating. **Fix-now** (cheap, self-contained).

## B2 — Name corruption: the refusal word "არა" leaks into the saved name
**Conversation (contact turn, with a phone in the message):**
1. bot: „მომწერეთ თქვენი სახელი და ნომერი"
2. „არა, ნინო მქვია 595999733" (user correcting a previously-misheard name)

**What broke (proven offline):** `_parse_name_phone("არა, ნინო მქვია")` → **`name="არა ნინო"`** (and `is_valid_person_name("არა ნინო")` → `True`, because at least one token is valid). „მქვია" (the verb "is called") is correctly dropped, but **„არა" (no) is kept as a name token** — `NAME_FILLER_WORDS` only blanks „არა" when it is the WHOLE message ([parse at parent_flow.py:3884](../app/flows/parent_flow.py#L3884)). With a phone in the same message, the contact handler would save `name="არა ნინო"`, `phone=595999733`.
**Expected:** strip the leading „არა" → `name="ნინო"`.
**Code path:** `_parse_name_phone` token filter — "არა" not in the filler/strip set for multi-token candidates.
**Severity:** DEGRADED (CRM name corruption on a natural correction). Live-reachability: requires a contact-collection turn that carries a phone — common for "no, my name is X, number Y".
**Smallest fix:** add "არა"/"არ" (and a leading-refusal strip) to the name-token filter so the token is dropped but a real following name survives; keep the existing whole-message "არა" blank-as-refusal behaviour. **Fix-now** (cheap; add a regression test).

## B1 — Age self-correction is NOT captured by the deterministic layer
**Conversation:**
1. „13 წლის" → `child_age=13`
2. „არა, 15" (correction)
3. „აბა 9 წლის" (correction again)

**What broke (proven offline):** `maybe_capture_child_age_fallback` **early-returns whenever `child_age` is already set** ([parent_llm_engine.py:135-136](../app/agent/llm/parent_llm_engine.py#L135)). Harness: `'13' → 'არა,15' stays '13' → '9 წლის' stays '13'`. The deterministic safety net therefore **cannot self-correct an age** — the FIRST value is locked. The executor `_save_lead_info` DOES allow an overwrite ([parent_tool_executor.py:1436](../app/agent/tools/parent_tool_executor.py#L1436)), so the correction lands **only if the LLM calls `save_lead_info(child_age=…)`** on the terse correction. Whether it reliably does so for „არა, 15" is **NEEDS LIVE CHECK**.
**Expected:** the final value (9, eligible) wins; Sheets/email/eligibility use 9, not 13.
**Code path:** fallback early-return (locks first) + LLM-only overwrite path.
**Severity:** DEGRADED (risk of a stale/wrong child age persisted) / partly NEEDS LIVE CHECK. Note: final value 9 is *eligible* (age_min=9), so this is a data-accuracy bug, not an eligibility break — but a final „8" with a locked „13" would also mask the ineligible-young guard.
**Smallest fix:** when the message is a clear correction (a refusal/contradiction stem + a fresh in-context age) allow the fallback to overwrite (or clear-then-recapture). **Defer**-able but real; pair with a live check of the LLM's correction behaviour.

---

# MINOR

## A-asym — PARENT→ADULT topic switch is LLM-only (asymmetric routing)
**Conversation:** „ბანაკი" (→PARENT) … later „არა, ღონისძიება მინდა".
**What broke:** segment is **sticky** — `process_message` re-classifies only when the segment is NOT already PARENT/ADULT ([conversation_service.py:405-412](../app/services/conversation_service.py#L405)). ADULT→PARENT has a deterministic override (`_is_parent_consultation_intent`, [:420-429](../app/services/conversation_service.py#L420)), but **there is no deterministic PARENT→ADULT override**. A PARENT-segment user asking for adult events stays in PARENT unless the LLM calls the age-gated `switch_to_adult_flow` tool. `_classify_segment("ღონისძიება")` returns ADULT in isolation, but that classifier isn't consulted once the conversation is PARENT. **child_age IS preserved** across the (non-)switch (lead untouched).
**Severity:** MINOR (+ NEEDS LIVE CHECK on whether the LLM switches). **Smallest fix:** add a deterministic PARENT→ADULT override on hard adult-event keywords when no active camp booking. **Defer** (needs care so a parent asking "is there an event at camp?" isn't hijacked).

## OVR-gap — bare „გადამიტანე" from a sticky-ADULT conversation isn't overridden
**What broke (proven offline):** `_is_parent_consultation_intent("გადამიტანე")` → **False**. `_PARENT_CONSULTATION_OVERRIDE_PHRASES` ([conversation_service.py:241-253](../app/services/conversation_service.py#L241)) has „გადავიტანოთ"/„გადატანა მინდა" but not the „გადამიტ" stem that the PARENT side uses (`_RESCHEDULE_INTENT_STEMS`, [parent_flow.py:2293](../app/flows/parent_flow.py#L2293)). So a user whose conversation is stuck on ADULT who types bare „გადამიტანე" (reschedule my consultation) stays in ADULT (no booking there).
**Severity:** MINOR (needs prior sticky-ADULT state). **Smallest fix:** add „გადამიტ"/„გადანიშ" to the override list to align with the parent reschedule stems. **Fix-now** (cheap).

## DEC-fp — partial negation fires a full decline and drops the pending booking
**Conversation:** mid-booking → „ამ დღეს არ მინდა, ზეგ მინდა" (not this day — the day after).
**What broke:** `_maybe_handle_decline_engine` ([parent_flow.py:2052-2096](../app/flows/parent_flow.py#L2052)) matches „არ მინდა" (`_DECLINE_PHRASES`) and only skips when the text contains „?" ([:2081](../app/flows/parent_flow.py#L2081)). A "not-this-but-that" phrasing with no „?" → a full warm decline **and clears `pending_booking`** ([:2092](../app/flows/parent_flow.py#L2092)) — abandoning the in-progress booking the user actually wanted to move.
**Expected:** treat „X არ მინდა, Y მინდა" as a slot change, not a cancellation.
**Severity:** MINOR–DEGRADED (silent booking abandonment on a natural rephrase). **Smallest fix:** skip the decline when a positive „მინდა"/a date/time also appears (not just „?"). **Fix-now** (cheap, add a regression test).

## F1 — No deterministic "revert to the original slot" after a reschedule
**Conversation:** book 13:00 → „გადამიტანე" → 14:00 → „აბა პირვანდელი" / „ძველი დრო მინდა".
**What broke (proven offline):** `_is_reschedule_request("აბა პირვანდელი")` / „ძველი დრო მინდა" / „როგორც იყო ისე" → **all False** (`_RESCHEDULE_INTENT_STEMS` has no revert stem, [parent_flow.py:2293](../app/flows/parent_flow.py#L2293)). After a reschedule the original calendar event was already **cancelled**, so "revert" can't restore it — at best the LLM re-books the old time as a fresh reschedule, and that slot may now be taken by someone else.
**Severity:** MINOR / NEEDS LIVE CHECK. **Smallest fix:** detect revert phrases + compare to the stashed `pending_booking["old_booked_datetime_iso"]` and re-book that exact slot if still free. **Defer** (uncommon; moderate effort).

## F3 — „მომავალ კვირას" (next week) not parsed
**What broke (proven offline):** `resolve_relative_datetime("მომავალ კვირას")` → **None** (only single-day stems: „ხვალ"→tomorrow, „ზეგ"→+2, „გუშინ"→yesterday all resolve). The agent must ask for a concrete date (LLM).
**Severity:** MINOR. **Smallest fix:** add week-relative stems or have the LLM ask for a specific date. **Defer.**

## G1 / G4 — comment-routing by post (not text), and per-comment-id dedup
**G1 (by design):** segment is decided by the POST's hashtag, never the comment TEXT (`determine_segment_from_post`, [comment_service.py ~968-1050](../app/services/comment_service.py#L968)). A user commenting "ღონისძიება მაინტერესებს" under a #ბანაკი post gets the **camp** DM. **G4 (by design):** dedup is per-`comment_id` (LRU + Redis `processed_comment:{id}`); 5 DIFFERENT comments from one user → 5 DMs; a re-delivered same id → deduped. Both are intentional but can mismatch/over-DM a chaotic commenter.
**Severity:** MINOR. **Defer** (by-design; revisit only if clients complain).

---

# NEEDS LIVE CHECK (LLM-composed — cannot prove offline; do NOT call these bugs)

- **A1–A4 (topic jumping):** segment stickiness + lead preservation are deterministic and safe; the *wording* and the PARENT→ADULT switch decision are LLM-driven. **A3 (ADULT→„ბანაკზე კონსულტაცია მინდა"→PARENT) IS deterministic and works** (override fires). A1/A2/A4 final replies need live confirmation.
- **B1 (age correction):** does the LLM reliably call `save_lead_info` on „არა, 15"? (deterministic fallback won't — see DEGRADED B1).
- **C1–C5 (vague/evasive/one-word):** DATA layer is safe — „პატარაა"/„სკოლის ასაკის" capture **no** age (no digit, proven), „რამდენია?" is NOT auto-classified as interest (`is_interest_intent`→False), one-word „კი/არა/რა?" classify UNCLEAR. Whether the bot asks the right clarifying question / survives one-word chains is LLM wording → live.
- **D1–D6 (manipulation):** the DATA can't be manipulated — price is grounded (camp_2026.yaml via `get_camp_info`), the booking executor never grants free/discount, sanitisers strip scolding/fabricated-success, and the CRITICAL suite (injection / jailbreak / price-manip / reveal-prompt / fake-manager) passes 22/22. Exact replies to NOVEL phrasings ("დირექტორი ვარ", "გუშინ 1000 ლარი მითხარით", "answer in English") are LLM → live-confirm, but the deterministic floor is solid.
- **E1–E5 (emotional/off-topic/mixed-language):** **E3 DATA safety is deterministic** — a long emotional message is NOT saved wholesale: `clean_challenge_for_storage` strips question/filler clauses, `is_valid_person_name` blocks a paragraph-as-name, and the age fallback needs in-context digits. PARENT has **no** deterministic off-topic guard (only ADULT does), so „ამინდი როგორია?" in PARENT → LLM (live). Mixed-language classification may fall to UNCLEAR/LLM (live).
- **F5 (multi-person „მე და ჩემი მეგობარი გვინდა"):** single-person data model (one sender → one subscription/booking); handling is LLM → live.
- **G3 (comment→DM then change topic):** same PARENT→ADULT stickiness as A-asym → live.

---

## Deterministically SAFE — proven offline (no live test needed)
- **B3 phone contradiction:** „595999733 ან 595999734" → multi-phone guard `['595999733','595999734']` → "which number?" ask; across turns the last phone overwrites; „არა, 595999734" parses to `('','595999734')` (no name garbage).
- **C2 vague age:** „პატარაა"/„სკოლის ასაკის" → no capture (no misparse, no wrong age).
- **F2 un-offered slot:** `_user_explicit_slot_choice` returns None on a date-mismatch → defers to `check_consultation_slot`; `_book_consultation` compares actual vs requested ISO (`slot_mismatch`) → never silently books a wrong slot.
- **F4 past date:** „გუშინ 10 საათზე" resolves to a past datetime → executor past-date refusal („წარსულ თარიღზე… ვერ ჩავნიშნავთ").
- **G2 comment „ფასი?":** `is_interest_intent` → True → DM (per post segment), no LLM round-trip.
- **A2 final decline:** „არ მინდა" → deterministic decline + `pending_booking` cleared.
- **C2b under-min age:** „8 წლის" → captured `child_age=8`; ineligible-young guard owns the decline.

---

## Confirmations
- ✅ No production code changed. The only file written is `docs/REDTEAM_CONVERSATIONS.md`.
- ✅ Temporary harness `_redteam_conv_scratch.py` was **read-only/offline** and **DELETED** after the run (verified — file not found).
- ✅ No live server / webhook / `run_followup_tick.py` / scheduler run. No Messenger/Instagram send. No Redis / Calendar / Sheets / email / Meta write. No OpenAI call.
- ✅ Production is **NOT green**.

## Recommended fix order (cheap, deterministic, test-gated — do NOT bundle with a live client test)
1. **B2** add "არა"/leading-refusal strip to the name token filter (CRM corruption; cheap + regression test).
2. **B4** clear adult-target on "ჩემთვის" self-reference (wrong audience; cheap).
3. **DEC-fp** don't full-decline when a positive "მინდა"/date/time is present (silent booking drop; cheap).
4. **OVR-gap** add "გადამიტ"/"გადანიშ" to the ADULT→PARENT override stems (cheap).
5. **B5** add a `calendly_booked` guard to `_maybe_requalify_child` + "second child → manager" message (booked-guard cheap; full multi-child = defer/ROOT 4).
6. **B1** allow the age fallback to overwrite on a clear correction (pair with a live check of the LLM's `save_lead_info` behaviour).
7. **Defer:** A-asym PARENT→ADULT override, F1 reschedule-revert, F3 next-week parsing, G1/G4 (by-design).

**Do NOT mark production green.**
