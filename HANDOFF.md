# HANDOFF — AI Sales Agent (სიტყვის აკადემია)

---

## ⚠️ CURRENT STATUS (2026-06-25) — READ THIS FIRST (LEGACY MODE)

**Newest handoff:** [`docs/HANDOFF_LEGACY_STABILIZATION_2026_06_25.md`](docs/HANDOFF_LEGACY_STABILIZATION_2026_06_25.md). **HEAD = `a2dcc5b`.**

- **Operating mode = legacy/giant-prompt** by operator decision (live answers were better than planner/slim). **Planner + slim are OFF and must stay OFF unless a future task explicitly requests otherwise.** The planner stack below is preserved but **dormant**.
- **Live `.env` flags (legacy):** `USE_CONVERSATION_PLANNER=false` · `CONVERSATION_PLANNER_AUTHORITATIVE=false` · `CONVERSATION_TRACE_DEBUG=false` · `USE_SLIM_PROMPTS=false` · `USE_PARENT_LLM_ENGINE=true`. ⚠️ This supersedes any "all four flags LIVE" claim in the 2026-06-24 sections below.
- **Four accepted legacy fixes this session** (deterministic; no phrase-specific handlers; no `.env`/data change): `9dd0b84` Georgian relationship words never saved as contact names; `68b0004` known `child_age` never re-asked (shared `app/reasoning/age_question.py`); `a3c5c17` explicit camp action after adult context → registration link / topic switch back (new `app/reasoning/legacy_actions.py`); `a2dcc5b` consultation booking slot-merge — known slots never re-asked, „კი ჩანიშნეთ" = confirmation, not a name.
- **Production NOT green.** `pytest tests/` = **3108 passed / 28 skipped / 5 failed** — all 5 pre-existing & unrelated (2× `test_p1_live_polish` = operator `sections.yaml` has 0 active adult events; 3× `test_conversation_planner_authoritative` = date-bomb `2026-06-25T12:00`, planner-path only). CRITICAL **22/22** on committed data. Do NOT hide these — production not fully green until resolved/isolated.
- **Next step = ONE full real legacy smoke (10-turn transcript in the handoff), NOT another patch.** After it passes, the next likely fix is factual grounding for camp-safety / child-contact answers (source from admin_config/tools; never invent).
- ⚠️ **`data/admin_config/sections.yaml` is an uncommitted operator edit (0 active adult events) — never commit it; seed a real active event before adult-event smoke.**

---

## ⚠️ CURRENT STATUS (2026-06-24) — superseded for operating mode by the 2026-06-25 banner above

**LATEST handoff (read after the status doc):** [`docs/HANDOFF_LIVE_PLANNER_TRACE_2026_06_24.md`](docs/HANDOFF_LIVE_PLANNER_TRACE_2026_06_24.md) — Live Planner/Route Trace root-cause + the planner-first / topic-routing / selected-state / slim-prompt / validator fix plan (Classes 1–6). The Conversation Planner Stage 1+2 (commits `b402834`/`284b60b`) + live trace diagnostics (`b703e22`) are in; **authoritative planner controls only 4 intents and runs after the Sunday-School/pending handlers, so live answers still mix.** Diagnostic only — no behaviour patched.

**Authoritative status doc:** [`docs/CURRENT_STATUS_AND_LIVE_REGRESSION_2026_06_24.md`](docs/CURRENT_STATUS_AND_LIVE_REGRESSION_2026_06_24.md) — where any older doc disagrees, that file wins.

- **Production: NOT green. Open client test: NOT approved. Guided client test: PAUSED.**
- The **live agent behaviour regressed after/around the Response Planner Hardening batch** — this is a **State Authority / Handler Priority** problem, **NOT only booking**: name messages misrouted into a stale underage/camp flow ("ჩემი სახელია ნიკოლოზი" → "თქვენი შვილის ასაკი 7 წელი…"); adult cultural-event questions answered as camp underage eligibility; a known `child_age=13` re-asked; camp-safety/visit/call questions answered with consultation-FORMAT framing; a confirmed booking ("25 ივნისს 12:00 ჩაგინიშნეთ") dropped from general state recall while a narrow phrasing still recalls it; mixed adult+child intent still weak.
- **Do NOT say "only adult data remains" and do NOT say "ready for open client test."** Adult-event operator data ("fromula 1" price_text 5000 vs price_gel 4999; removed gia event) is STILL a problem but is **NOT the only blocker**.
- **Operator confirms Redis is FLUSHALL-cleared AND the server restarted before each live test → do NOT assume stale Redis / old session pollution as the default root cause.** Investigate current-session state transitions, pending state not cleared in the same conversation, and handler priority overriding current intent first.
- **Done since the 2026-06-23 baseline below (each batch automated-test-gated, 0 failed):** Prompt/Sanitizer source-of-truth cleanup; Central Turn Intent Gateway (Phase 2, `reasoning_layer.analyze_turn_intent`, deterministic always-on); Response Planner Hardening (PII full-phone masking via final outgoing-response mask; consult-vs-registration; adult-self; human tone; off-topic/insult); WhatsApp env-mapping + test-isolation fix. Standalone WhatsApp smoke `configured=True allow_live=True recipient=995595999733 sent=True`; scenario runner now mocks `_send_manager_whatsapp`; new `ALLOW_LIVE_WHATSAPP` guard. Suite: **2956 passed / 0 failed / 28 skipped**, `test_agent.py` PASS, CRITICAL **22/22**, transcript **3/3**. **Green automated tests do NOT certify live behaviour** — the regression is in live multi-source state / handler-priority paths the suite does not yet replay.
- **NEXT TASK (record exactly): "State Poisoning & Guard Regression Audit after Response Planner Hardening"** — diagnostic trace, NOT blind patching. Replay the exact live transcripts; capture `TurnIntent`, state before/after each turn (lead / booking_state / conversation history / Calendar busy / Sheets row / latest CTA / pending flow), the selected handler, whether the reply came from a deterministic handler or the LLM, and all Calendar/Sheets/email/WhatsApp side effects; verify Redis was truly clean and the server saw fresh env; PROVE the root cause, then do ONE targeted architectural fix. **No blind fixes; no new keyword paths before trace evidence.**
- **WhatsApp:** standalone send works + test isolation fixed, BUT the **agent-flow WhatsApp notification did NOT arrive** in the live test. The trace must determine: did the app process see `ALLOW_LIVE_WHATSAPP=true` (env reload / restart)? does the booking path call WhatsApp at all? is WhatsApp wired ONLY for the handoff (not booking notification)? is a notification failure swallowed?
- **Verify (hypothesis):** the PII final-mask must only mask the FINAL user-facing text and must NOT mutate state/history used by routing.

---

## ✅ CURRENT STATE (2026-06-23) — historical (baseline numbers + "NEXT TASK Prompt Slimming" below are SUPERSEDED by the 2026-06-24 banner above)

**Baseline (verified 2026-06-23):** `pytest tests/` **2879 passed / 0 failed / 28 skipped** · corpus **9/9** · `RUN_PROPERTY_TESTS=1` property **28/28** · `python test_agent.py` ✅ · `scenario_runner_full --priority CRITICAL` **22/22 (clean)** · `--category transcript` **3/3**.

**Production: NOT green.** · **Client guided testing: pending final smoke.** · **Reasoning Layer: Phase 1 implemented, gated, default OFF.**

**Completed since the 2026-06-22 source-of-truth cleanup (each batch test-gated, 0 failed):**

1. **Source-of-truth cleanup — DONE** (Tasks 1→5A-3): stream dates → `get_camp_info`/visible-stream filter; Sunday-School status → `sections.yaml sunday_school`; Admin-Panel preserves Sunday-School fields; manager phone → `get_manager_phone()`; camp age band → `get_camp_age_bounds()`; post-booking facts → `get_camp_facts()`; comment rich DM → Admin-first; **`camp_2026.yaml` is fallback/legacy only, NOT a live primary source.**

2. **Free-form robustness batch — DONE** (2026-06-23): Latin-script name capture for simple valid cases („nika 595999733"); deterministic state recall („ჩემი სახელი/ნომერი იცი?" with masked phone); deterministic PARENT prompt-injection / off-topic guard (`_maybe_handle_offtopic_injection`). New tests `tests/test_freeform_robustness_2026_06_23.py`.

3. **Live-smoke handoff/contact blocker fix — DONE** (2026-06-23): explicit manager-phone / self-call requests OUTRANK contact collection; typo „მენჯერ"/„მენჯერის" handled (`_mentions_manager`); action phrases never stored as `lead.name`; „კიმინდა"/„კი მინდა" never stored as a name; pending handoff no longer traps later topic switches; manager phone from the canonical helper; **no hardcoded manager phone in new tests; deterministic-only, NO LLM fallback.** Shared validator `_is_storable_person_name`. New tests `tests/test_handoff_intent_priority_2026_06_23.py`.

4. **Reasoning Layer — Phase 1 DONE** (2026-06-23): module `app/reasoning/reasoning_layer.py` + `app/reasoning/__init__.py`; config flag `USE_REASONING_LAYER` (**default OFF**, pinned OFF in conftest). **Deterministic-only, metadata-only, NOT a free-form answer generator, NO LLM call, NO side effects, fail-closed.** Integrated NARROWLY for one ambiguous case (decline + topic-switch deferral); does NOT override deterministic handlers; does NOT touch booking/Calendar/Sheets/WhatsApp/email. `docs/reference/reasoning_layer.py` is the LLM-based 4-step vision (`analyze→ground→answer→reflect`) and remains **reference-only — NOT imported into production**. New tests `tests/test_reasoning_layer_2026_06_23.py`.

**Open risks / next work (before client testing):**
- **NEXT TASK — Prompt Slimming / System-Prompt Cleanup:** remove hardcoded camp age „9–17" and location „ამბასადორ კაჭრეთი" duplicated in `system_parent_v2.md`; remove/dynamicise the `FORBIDDEN_PHRASE_REPLACEMENTS` fact-injection in `parent_llm_engine.py` (age :1176/1180, location :750/754) so it never injects hardcoded business facts; facts must come ONLY from canonical helpers/tools/config. Test-first (prompt-leak regression), gated, `scenario_runner` CRITICAL gate.
- **Sunday School:** `sections.yaml sunday_school.availability_text` = „საკვირაო სკოლა ივლისში დაემატება." — this is operator config/data, NOT a code/prompt bug; change via Admin Panel/config if the business wants different wording. A full Sunday-School program model / generic discovery is NOT implemented (current support is status/details/handoff-oriented).
- **Generic Admin Program Handler:** NOT implemented — adding arbitrary new programs in the Admin Panel preserves data, but the agent will not auto-answer from them until a generic discovery/renderer is built (later feature phase, not a live-stability blocker).
- **Adult events:** canonical-source cleanup still pending; the „fromula 1" `price_text 5000` vs `price_gel 4999` operator-data mismatch must be checked before free-form adult testing.
- **Production readiness:** final internal smoke + guided client test script still required; production remains NOT green; Railway staging + Meta App Review still open (operator).

---

**Last updated:** 2026-06-22 — latest state is in the „✅ LATEST" section directly below (**Live-Demo Polish Batch (2026-06-21/22)**: 6 narrow deterministic fixes for a client test — (1) PARENT manager-number disclosure (`558 67 47 33`) + (2) context-aware (no re-ask if phone known) + (3) mid-conversation „გამარჯობა" strip + (4) anti-repeat varied contact-ask + (5) **price-objection „…არ მინდა, მაგრამ…" no longer cold-closes the lead** + (6) **phone & name correction** („ნომერი შევცდი, სწორია 595…" / „ნინო კი არა, მარიამი" → updates lead, in-memory only). `pytest tests/` **2676 passed / 0 failed / 28 skipped**, corpus 9/9, property 28/28, `test_agent.py` ✅, CRITICAL effectively 22/22 (4 stochastic flakes pass on rerun), transcript 3/3, **no prompt/YAML/Calendar/Sheets/WhatsApp change**, production NOT green. New: `docs/LIVE_TEST_CHECKLIST_2026_06_22.md` (operator adversarial checklist). Known weakest spots still LLM-only: off-topic deflection + English-leak (NEXT TASK to harden). Earlier **Consultation Flow Memory / Repeated Age Fix (2026-06-20)**: the agent now REMEMBERS the child age + phone given in ONE message („14 წლის არის 595999733" → `child_age=14`, `phone=595999733`) and never re-asks a known fact. Root cause = extraction: the age fallback bailed on any phone-prefix („595…"); fixed by stripping the phone before age parsing, capturing both pre-turn before the LLM context is built, a deterministic phone fallback, and a state-driven anti-repeat guard. `pytest tests/` **2633 passed / 0 failed / 28 skipped**, corpus 9/9, property 28/28, `test_agent.py` ✅, CRITICAL effectively 22/22 (21 stable + SC-63 stochastic), transcript 3/3, prompts unchanged, production NOT green — **live smoke for this fix still pending**. Earlier **Camp Stream Date Filter Fix (2026-06-20)**: each camp stream is now HIDDEN once its Asia/Tbilisi start date arrives — I ნაკადი from Jun 23, II from Jul 5, III from Jul 14; `active AND today<start → visible`, `today≥start OR inactive → hidden`; streams are NOT deleted/mutated in Admin/config — a display/eligibility filter only; if no future streams remain the agent does NOT invent dates. `pytest tests/` **2608 passed / 0 failed / 28 skipped**. Earlier **Camp registration/info routing — live-path fixes (2026-06-19/20)**: a clear camp registration/link/form/sign-up request now returns the Admin `Registration URL` (`https://tinyurl.com/36jcae8z`) DETERMINISTICALLY, pre-engine — no age question, no generic menu, link read from Admin/config (missing → safe fallback); a camp INFORMATION request no longer over-fires the link (token-aware „ფორმა", which previously matched inside „ინფორმაცია"); `get_user_profile` masks `access_token`. `pytest tests/` **2581 passed / 0 failed / 28 skipped**, corpus 9/9, property 28/28, `test_agent.py` ✅, CRITICAL 22/22 clean, transcript 3/3, prompts unchanged, production NOT green). Earlier 2026-06-18/19 Manager WhatsApp manager-notification fix + camp-registration intent detector + general/live registration-link routing (2440 → 2548). Earlier 2026-06-18 Railway deploy-blockers PRE-STAGING fix (no deploy; os.environ-first env loading, `REDIS_URL`, ignore files, runtime deps, 2415 → 2440). Earlier 2026-06-18 P0 Sheets „Leads" row-alignment fix (A-anchored append, 2407 → 2415). Earlier 2026-06-16 Saturday scheduling policy (bookings Mon–Sat, Sunday closed) + P2 Sunday-wording cleanup (2374 → 2407). Earlier P1 Live Polish + date-bomb/stale-event cleanup + under-age manager-handoff dispatch (2334 → 2374). Earlier 2026-06-14 (**LIVE P0 HOTFIX BATCH DONE** → BUG 1 diagnosed as stale-process/deploy gap (no code change; operator restart required), BUG 2 named-event direct-answer fix, +12 tests, **2322 → 2334**; see the „✅ LIVE P0 HOTFIX" section below. Prior: P0 Live Demo UX Regression Batch (ISSUE 1/2/3/4/5/6, +35, 2287 → 2322), Red-Team B Self-Correction Batch (B5/B2/B4/M1/B1, 2222 → 2287), Metamorphic property tests, Deploy-Readiness Audit (Railway blockers — see below), Railway-Safe Google Credentials (2209 → 2222), Pre-Staging Fix Batch (2151 → 2209))
**Status:** ⚠️ **NOT production-approved.** Code-side test status is green: `test_agent.py` ✅, `pytest tests/` **2879 passed, 28 skipped, 0 failed** (current, 2026-06-23 — see „✅ CURRENT STATE" at the very top; the per-batch deltas in the rest of this paragraph are historical). Historical: **2802 passed** (2792 → +10 across the Camp-Facts Migration 5A-3, 2026-06-22 — `parent_flow._facts_for_post_booking` now uses `get_camp_facts()`; comment rich DM VERIFIED already admin-first; **parent_flow now has ZERO direct `camp_2026.yaml` reads and no LIVE PRIMARY camp-fact reader bypasses the canonical source** — only intended fallbacks/legacy remain; no prompt/YAML/data change; see the top „✅ LATEST" section; CRITICAL effectively 22/22 — SC-13 Slot-Change is the documented real-model flake, PASS on isolated rerun; corpus 9/9; property 28/28; transcript 3/3) (2633 → +43 across the Live-Demo Polish batch: manager-number disclosure/context-aware, greeting strip, anti-repeat contact-ask, price-objection≠decline, phone+name correction; earlier 2608 → +25 across the Consultation Flow Memory / Repeated Age fix; earlier 2581 → +27 across the Camp Stream Date Filter display fix; earlier 2440 → +141 across the Manager WhatsApp manager-notification fix, the camp-registration intent detector + general/live registration-link routing, the camp info-vs-registration over-fire fix, and `get_user_profile` token masking; see the top „✅ LATEST" section). corpus **9/9**; property audit `RUN_PROPERTY_TESTS=1` → **28 passed, 0 failed** (M1–M6 all hold); `pytest -k comment` **196/0**; `pytest -k follow` **186/0**. CRITICAL (real OpenAI, Meta/Calendar/Sheets mocked) **22/22 on re-run** — known real-model stochasticity on PARENT booking/slot/screen scenarios (SC-11/12/13/19/46 flake on a single full run but pass on re-run; NOT a regression, and unrelated to the ADULT-only BUG 2 change). New real-model transcript scenarios **SC-TX-01/02/03 → 3/3**. Follow-up works; Facebook + Instagram comments worked in live smoke; Google credentials Railway-safe. **Model:** `gpt-4.1-mini` (unchanged). No real broadcast sent; no Calendar-booking/Sheets-schema/email/broadcast/`.env`/model/**prompt** change in the hotfix (`system_adult_v1.md` byte-identical). `LIVE_BROADCAST_ENABLED` default **False**. ⚠️ **OPERATOR: restart/redeploy the live process** — BUG 1's fix is already in code; the live process was running stale code.
**⚠️ Two open gates before production:** (1) **Railway staging deploy** — the *code-side* Railway blockers are now FIXED (os.environ-first env loading, REDIS_URL support, ignore files, runtime deps); what remains is the actual staging deploy itself (create service, attach Redis, set dashboard env vars incl. `GOOGLE_CREDENTIALS_JSON` + `LIVE_BROADCAST_ENABLED=false`, single replica/one worker, health+smoke); (2) **Meta App Review** (real-customer comment/DM blocked with error #10 until messaging/metadata/engagement perms approved + app switched to Live). (P0 LIVE DEMO UX REGRESSION is now RESOLVED — see the section directly below.) **Live demo is local (`uvicorn --reload`) — editing `.py` may auto-reload it, BUT BUG 1 below proved the live process can run STALE code — verify a restart actually took effect.**

---

## 📍 NEXT-TASK STARTING STATE — Source-of-Truth cleanup consolidated (read this first)

**Baseline (verified 2026-06-23, latest sync):** `pytest tests/` **2879 passed / 0 failed / 28 skipped** · corpus **9/9** · `RUN_PROPERTY_TESTS=1` property **28/28** · `python test_agent.py` ✅ · `scenario_runner_full --priority CRITICAL` **22/22 (clean)** · `--category transcript` **3/3** · **Production: NOT green.** (The 2802 baseline below is the 2026-06-22 5A-3 snapshot; current is 2879 after the free-form robustness, handoff/contact blocker fix, and Reasoning Layer Phase 1 batches — see „✅ CURRENT STATE (2026-06-23)" at the top.)

**✅ Completed source-of-truth cleanup (Tasks 1 → 5A-3, all 2026-06-22, each test-gated, 0 failed):**
- **Task 1** — stream-date literal facts removed from the LIVE parent prompt (`system_parent_v2.md`); stream dates must come from `get_camp_info` / the visible-stream filter.
- **Task 2** — Sunday-School „July" hardcode moved out of `parent_flow.py` into `sections.yaml` `sunday_school` (`availability_text`/`details_text`/`handoff_enabled`/`lead_type`) via `admin_config_service.get_sunday_school_status()`.
- **Task 3** — Admin-Panel section save (`save_program`) now PRESERVES the Sunday-School fields + any unknown config key (generalised the keep-whitelist; form-managed list fields still clear-on-empty).
- **Task 4** — manager phone unified: `get_camp_facts()['phone']` now defers to canonical `admin_config_service.get_manager_phone()`.
- **Task 5A inventory** — 14 `camp_2026.yaml` readers catalogued; 6 LIVE age-band readers identified; >3 → split into sub-tasks.
- **Task 5A-1** — first 3 live age-band readers (`_age_status_for_lead`, `_camp_age_bounds`, engine `_age_status`) → new `admin_config_service.get_camp_age_bounds()`.
- **Task 5A-2** — remaining 3 (`_build_system_prompt` prompt context, `book_consultation` eligibility, `switch_to_adult_flow`) → `get_camp_age_bounds()`. **All 6 live age-band readers now canonical.**
- **Task 5A-3** — `parent_flow._facts_for_post_booking` → `get_camp_facts()`; comment rich DM VERIFIED already admin-first. **`parent_flow` now has ZERO direct `camp_2026.yaml` reads.**

**📊 Current canonical sources (live user-facing camp facts):**
| Fact | Canonical source | Status |
|---|---|---|
| Camp stream dates | `get_camp_info` / `get_visible_camp_streams` filter | ✅ Task 1 |
| Sunday-School status | `sections.yaml` `sunday_school` | ✅ Task 2 (+3 panel-preserve) |
| Manager phone | `admin_config_service.get_manager_phone()` | ✅ Task 4 |
| Camp age band (all 6 live readers) | `admin_config_service.get_camp_age_bounds()` | ✅ 5A-1 + 5A-2 |
| Camp post-booking facts | `admin_config_service.get_camp_facts()` | ✅ 5A-3 |
| Comment rich DM | Admin Config first (`build_section_dm`), `camp_2026` fallback only | ✅ 5A-3 (verified) |
| `camp_2026.yaml` | **No longer a LIVE PRIMARY source** for user-facing camp facts — fallback / legacy / boot-default / test / doc only | ✅ |

**🔧 Remaining SOURCE-OF-TRUTH work (not yet done):**
- Adult-events canonical source cleanup.
- `sections.yaml` adult „fromula 1" `price_text: 5000` vs `price_gel: 4999` mismatch (operator data, not code).
- Sunday-School Admin-Panel **UI** fields (currently preserved + YAML/`update_section`-editable, but not panel-editable) — optional/future.
- Legacy archive / docs cleanup — later, approval-gated.

**🧭 BEHAVIORAL work — status (updated 2026-06-23):**
- ✅ **State recall** „ჩემზე რა ინფორმაცია გაქვს?" / „ჩემი სახელი/ნომერი იცი?" — DONE (deterministic, masked phone; free-form robustness batch).
- ✅ **PARENT prompt-injection / off-topic deterministic guard** — DONE (`_maybe_handle_offtopic_injection`; mirrors ADULT `_maybe_adult_offtopic_reply`).
- ✅ **Handoff/contact intent priority** — DONE (manager-phone/self-call outranks contact collection; action phrases never stored as name; typo „მენჯერ" handled; pending handoff no longer traps topic switches — handoff/contact blocker fix batch).
- ✅ **Latin-Georgian name capture (simple valid cases)** — DONE for „nika 595999733" (intent/greeting words still rejected). Broader transliteration of arbitrary intent remains future work.
- 🟡 **gratitude + new-question / decline + topic-switch** — addressed by **Reasoning Layer Phase 1** (gated, default OFF): the analyzer classifies these and Phase-1 wiring defers a decline+topic-switch to the topic answer. Live enablement pending a flag-ON `scenario_runner` comparison.
- 🟡 **PARENT ↔ ADULT topic switch** — analyzer now CLASSIFIES segment/topic (parent↔adult); deterministic live flip not yet wired (PARENT→ADULT still LLM `switch_to_adult_flow` when flag OFF).
- ⏳ Router normalization + a central high-priority intent router; negated event intent recovery — still open.

**🧪 Reasoning Layer status (UPDATED 2026-06-23):** **Phase 1 is implemented, gated, default OFF.** Production module `app/reasoning/reasoning_layer.py` (+ `app/reasoning/__init__.py`); config flag **`USE_REASONING_LAYER`** (code default **False**, env-absent → False, pinned OFF in `tests/conftest.py`). It is a **DETERMINISTIC, metadata-only intent analyzer** (`analyze_parent_turn`) — NOT a free-form answer generator, **NO LLM call**, no side effects, fail-closed; it never overrides a high-confidence deterministic handler. Phase-1 live wiring covers ONE ambiguous case (decline + topic-switch deferral). `docs/REASONING_LAYER_BRIEF.md` + `docs/reference/reasoning_layer.py` describe the FUTURE LLM-based `analyze→ground→answer→reflect` vision (the brief's flag name `USE_REASONING_PASS` is superseded by `USE_REASONING_LAYER`); the reference scaffold is **reference-only and NOT imported into production**. Any LLM-based expansion is a later phase and must ship behind the same flag with a flag-ON `scenario_runner` comparison.

**⚠️ Flakes (be honest):** `scenario_runner_full` CRITICAL has documented real-model stochastic flakes (the set seen across this work: SC-11/12/13/19/26/46/63 — booking/slot/objection/price). They PASS on isolated rerun. The latest 5A-3 CRITICAL run was a clean **22/22**, but **an isolated-rerun pass is NOT production-green** — treat `scenario_runner` (not bulk pytest, which pins the engines OFF via conftest) as the live regression gate.

**🗂️ Docs note (duplicate):** the verification sweep exists as BOTH `docs/SOURCE_OF_TRUTH_VERIFICATION_SWEEP_2026_06_22.md` (**CANONICAL**) and a non-dated `docs/SOURCE_OF_TRUTH_VERIFICATION_SWEEP.md` (**pending docs cleanup — duplicate**). Identical content. **Deletion/archive of the non-dated copy requires explicit approval** (not done here).

---

## ✅ LATEST — CAMP-FACTS MIGRATION 5A-3 (2026-06-22) — read this first

**Production STILL NOT green.** Completes the LIVE camp_2026.yaml fact-reader cleanup (after the age-band migration in 5A-1/5A-2).

**The change:**
- `app/flows/parent_flow.py` `_facts_for_post_booking` — migrated off the direct `camp_2026.yaml` read onto canonical `admin_config_service.get_camp_facts()`. Same return shape (`price_gel`/`location`/`duration_days`/`registration_url`/`phone`/`includes`/`streams`), admin-first with camp_2026 fallback inside `get_camp_facts`; the RAW streams are still date-filtered by `get_visible_camp_streams`. Bonus: the post-booking `phone` is now the **canonical** manager phone (Task-4 unified). With the shipped config every value is byte-identical (price 2150, location ამბასადორი კაჭრეთი, phone 558 67 47 33).
- `app/services/comment_service.py` `_build_parent_rich_dm` — **VERIFIED, not refactored.** It is already Admin-FIRST: step 1 `admin_config_service.build_section_dm(section)` renders from the admin section's own fields (`context = dict(section)`); `camp_2026.yaml` is only the step-2 fallback.

**Result: `parent_flow` has ZERO direct `camp_2026.yaml` reads, and no LIVE PRIMARY camp-fact reader bypasses the canonical source.** The only remaining `camp_2026` reads are the intended fallbacks — `admin_config_service.get_camp_facts` fallback (:561), `parent_tool_executor._get_camp_info` fallback (:313), the comment rich-DM step-2 fallback (:194), `config.py` boot default — plus the legacy composer/analyzer/router (engine-fail/flag-off only) and tests/docs.

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2802 passed, 0 failed, 28 skipped** (2792 → +10)
- corpus **9/9**; property **28/28**; `test_agent.py` ✅
- `scenario_runner_full --priority CRITICAL` → **22/22 (clean this run)**; `--category transcript` → **3/3**
- new `tests/test_camp_facts_migration_5a3_2026_06_22.py` (11 — post-booking facts follow Admin Config price/location/registration/canonical-phone; safe fallback when camp facts raise; default byte-identical; comment rich DM admin-first via `build_section_dm` + camp_2026 fallback when no admin; source guards: parent_flow 0 camp_2026 reads, comment camp_2026 is only the fallback). A stale 5A-2 forward-assertion (post-booking „still camp_2026") was corrected.
- **NO prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change. camp_2026.yaml NOT deleted.** Production NOT green.

---

## ✅ CAMP AGE-BAND MIGRATION 5A-2 (2026-06-22)

**Production STILL NOT green.** Finishes the live age-band source-of-truth migration. 5A-1 moved the 3 parent_flow/engine age-status helpers onto `admin_config_service.get_camp_age_bounds()`; **5A-2 moves the final 3 live readers** so ALL six are canonical:
- `app/agent/llm/parent_llm_engine.py` `_build_system_prompt` — the runtime PARENT prompt age band now comes from `get_camp_age_bounds()` (the `.md` template `{age_min}`/`{age_max}` placeholders are untouched; with the shipped config it still renders 9–17).
- `app/agent/tools/parent_tool_executor.py` — `book_consultation` eligibility AND `switch_to_adult_flow` age range (an identical 4-line block, migrated together) now use `get_camp_age_bounds()`.

Only the **source** of `age_min`/`age_max` changed; booking/switch LOGIC and prompt WORDING are unchanged, and with the default 9–17 config behaviour is byte-identical. The only remaining `camp_2026.yaml` reads are the intended fallbacks (`parent_tool_executor:313` get_camp_info fallback, `admin_config_service:561` get_camp_facts fallback), the 5A-3 items (`parent_flow._facts_for_post_booking`, comment rich DM), `config.py` boot default, and the legacy composer/analyzer/router.

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2792 passed, 0 failed, 28 skipped** (2783 → +9)
- corpus **9/9**; property **28/28**; `test_agent.py` ✅
- `scenario_runner_full --priority CRITICAL` → **19/22** (booking 3/3; SC-19/SC-26/SC-63 = documented objection/price flakes, all PASS on isolated rerun; the age band is unchanged at 9–17) → effectively **22/22**; `--category transcript` → **3/3**
- new `tests/test_camp_age_bounds_migration_5a2_2026_06_22.py` (11 — prompt renders the canonical band exactly (10–16 fixture / 9–17 default); booking rejects age 9 when admin min=10 and age 17 when admin max=16; adult-switch transfers an out-of-band age and keeps an in-band one; source guards that all live age-band readers now use the helper and only the get_camp_info fallback still reads camp_2026). The 5A-1 source-guard test was updated (its „still camp_2026" assertion is now inverted — these readers are migrated).
- **NO `.md` prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change. camp_2026.yaml NOT deleted.** Production NOT green.

---

## ✅ CAMP AGE-BAND MIGRATION 5A-1 (2026-06-22)

**Production STILL NOT green.** First sub-task of the camp_2026.yaml-reader migration (the audit found 6 LIVE readers of the age band reading `camp_2026.yaml` directly, bypassing the canonical `get_camp_facts()` — so an operator age-range edit reached the `get_camp_info` tool but NOT eligibility/under-age/prompt). **This sub-task migrates only the FIRST 3** (per the ≤3-reader-per-task safety rule from the 5A inventory).

**The change:**
- `app/services/admin_config_service.py` — new **`get_camp_age_bounds() -> (age_min, age_max)`** reading ONLY through `get_camp_facts()` (admin-first; `camp_2026.yaml` via its existing fallback). Safe `(9, 17)` default on missing/malformed; never raises; never reads camp_2026 directly.
- Migrated 3 readers to it: `parent_flow._age_status_for_lead` (eligibility), `parent_flow._camp_age_bounds` (under-age handoff bounds), `parent_llm_engine._age_status` (engine eligibility). With the shipped config the band is still `9–17`, so behaviour is byte-identical today; an operator age edit now reaches these paths.

**INTENTIONALLY NOT migrated (5A-2 / 5A-3):** `parent_llm_engine._build_system_prompt:1924` (prompt age band), `parent_tool_executor:868` (book_consultation eligibility), `parent_tool_executor:2041` (adult-switch), `parent_flow:5885` (`_facts_for_post_booking`), `comment_service:194` (rich DM, admin-first). The `get_camp_info` canonical fallback (`parent_tool_executor:313`) + `get_camp_facts`'s own fallback (`admin_config_service:561`) STAY. Legacy composer/analyzer/router untouched.

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2783 passed, 0 failed, 28 skipped** (2769 → +14)
- corpus **9/9**; property **28/28**; `test_agent.py` ✅
- `scenario_runner_full --priority CRITICAL` → **19/22** (SC-11/SC-13/SC-19 = documented flakes, all PASS on isolated rerun; the age band is unchanged at 9–17 so eligibility is identical) → effectively **22/22**; `--category transcript` → **3/3**
- new `tests/test_camp_age_bounds_migration_2026_06_22.py` (14 — helper admin-driven + safe fallback/malformed/raise; the 3 migrated readers follow the band; admin age_min=10→9 ineligible / age_max=16→17 ineligible; default 9–17 unchanged; source guards that the 3 migrated helpers no longer read camp_2026 AND the prompt/booking/adult-switch readers still do).
- **NO prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change. camp_2026.yaml NOT deleted/archived.** Production NOT green.

---

## ✅ MANAGER-PHONE SOURCE-OF-TRUTH UNIFICATION (2026-06-22)

**Production STILL NOT green.** Fourth Source-of-Truth cleanup. The audit flagged TWO independent manager-phone chains: (1) `admin_config_service.get_manager_phone()` (canonical; manager_contacts.yaml → env → company.yaml → adult_events.manager_contact) used by the deterministic disclosure paths (PARENT `_render_manager_number_answer`, under-age fallback, ADULT executor — already canonical); and (2) `get_camp_facts()['phone']` (camp section `manager_contact` / camp_2026.yaml), exposed via the `get_camp_info` tool to the LLM. Both returned `558 67 47 33` today, but a phone change in one source would NOT reach the other.

**The fix (one chokepoint, `app/services/admin_config_service.py`):** `get_camp_facts()` now sets `phone` from `get_manager_phone()` (canonical) first, falling back to the section's `manager_contact` then the legacy camp `phone` only when the canonical helper is unconfigured. So the LLM's camp-info phone now agrees with the disclosure paths, and a single edit (manager_contacts.yaml/company.yaml) propagates to EVERY user-facing manager-phone path. **No live disclosure path needed changing — they already used `get_manager_phone()`.**

**Audit notes:** no hardcoded manager phone in the LIVE prompt (`system_parent_v2.md`); the legacy `system_parent.md:9` + the unused `templates/common/error.yaml` still carry `558 67 47 33` but are fallback/dead (out of scope, untouched). `data/admin_config/sections.yaml:21` `manager_contact` and `camp_2026.yaml:31` `phone` remain as fallbacks.

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2769 passed, 0 failed, 28 skipped** (2761 → +8)
- corpus **9/9**; property **28/28**; `test_agent.py` ✅
- `scenario_runner_full --priority CRITICAL` → **19/22** (SC-13 Slot-Change + SC-19 Screen-Concern + SC-26 Will-Think = documented real-model flakes, **all three PASS on isolated rerun**; the phone-unification touches none of them) → effectively **22/22**; `--category transcript` → **3/3**
- new `tests/test_manager_phone_unification_2026_06_22.py` (8 — the two chains now agree; default = `558 67 47 33`; a canonical change propagates to camp-info + PARENT disclosure + under-age fallback; an operator manager_contacts edit propagates to both; section-contact fallback when canonical empty; ADULT/PARENT no-hardcode guards; Sunday-School discloses no number).
- **NO prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change; no DM-flow behaviour change.** Production NOT green.

---

## ✅ ADMIN-PANEL SUNDAY-SCHOOL FIELD PRESERVATION (2026-06-22)

**Production STILL NOT green.** A protection fix for Task 2. Task 2 added operator config to `sections.yaml` `sunday_school` (`availability_text` / `details_text` / `handoff_enabled` / `lead_type`), but the Admin-Panel section form does NOT surface those fields — so a metadata save of `sunday_school` through `POST /admin/programs/{id}` would have silently DROPPED them (the route rebuilt the section from the form + preserved only a 4-key whitelist).

**Root cause:** `admin.save_program` (`app/routes/admin.py`) preserved only `discovery_questions`/`duration_days`/`schedule_text`/`events` from the existing section; everything else not on the form was dropped. (Saving summer_camp/adult_events was already safe — `save_section` only replaces the matching-id entry; `update_section` already deep-merges.)

**The fix (admin route only):** `save_program` now preserves EVERY existing field the form does not manage — generalising the 4-key whitelist to all non-form keys (incl. the Sunday-School fields and any custom key). The form-managed LIST fields (`streams`/`included_items`/`discounts`) are explicitly EXCLUDED so they keep their clear-on-empty behaviour, and `price_gel`/`price_text` are always in the form payload so the stale-2150 guard is intact. `validate_section` does not reject unknown keys, so preservation is safe. NO new Admin-Panel UI was added (preservation over UI expansion, per the task) — the fields remain YAML/`update_section`-editable.

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2761 passed, 0 failed, 28 skipped** (2753 → +8)
- corpus **9/9**; property **28/28**; `test_agent.py` ✅
- `scenario_runner_full --priority CRITICAL` → **20/22** (SC-12 Slot-Busy + SC-25 Hard-Decline = documented flakes, **both PASS on isolated rerun**; this admin-route change is off the DM path) → effectively **22/22**; `--category transcript` → **3/3**
- new `tests/test_admin_sunday_school_preservation_2026_06_22.py` (8 — sunday_school fields + unknown custom key survive a partial form save; summer_camp / adult_events save does not drop sunday_school (events list preserved too); handler reads config after admin save; changed-month survives; a section save touches no Calendar/Sheets/WhatsApp; `update_section` deep-merge guard).
- **NO prompt / YAML-data / Calendar / Sheets-schema / WhatsApp / model change; no DM-flow behaviour change.** ⚠️ Note: the new fields still aren't EDITABLE in the panel UI (only preserved); a small panel-form addition is a future enhancement. Production NOT green.

---

## ✅ SUNDAY-SCHOOL STATUS → ADMIN CONFIG (2026-06-22)

**Production STILL NOT green.** Second Source-of-Truth cleanup task. The Sunday-School launch month („ივლისში დაემატება") was HARDCODED in `parent_flow.py` (`_SUNDAY_SCHOOL_ANSWER` constant) — it would drift when July arrives / the month changes / details firm up. Moved to operator-editable Admin Config.

**The fix:**
- `data/admin_config/sections.yaml` — the `sunday_school` section gained `availability_text: საკვირაო სკოლა ივლისში დაემატება.`, `details_text: დეტალები ზუსტდება`, `handoff_enabled: true`, `lead_type: sunday_school`. (ONLY the sunday_school section touched; summer_camp / adult_events untouched.)
- `app/services/admin_config_service.py` — new `get_sunday_school_status()` reads those fields (safe no-date defaults, never raises).
- `app/flows/parent_flow.py` — `_SUNDAY_SCHOOL_ANSWER` constant REMOVED; new `_render_sunday_school_answer()` builds the answer from config (`availability_text` + `details_text` + a fixed handoff OFFER tail). Missing config → safe fallback „საკვირაო სკოლის დეტალები ზუსტდება." (no invented month). `handoff_enabled=false` → status only (no contact ask). The fixed OFFER tail keeps the name+phone ask; the config availability keeps the „საკვირაო სკოლ" collection marker. Email-only handoff / SundaySchoolLeads tab / no-Calendar / no-WhatsApp / email-success-gate ALL unchanged.

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2753 passed, 0 failed, 28 skipped** (2746 → +7)
- corpus **9/9**; property **28/28**; `test_agent.py` ✅
- `scenario_runner_full --priority CRITICAL` → **21/22** (SC-13 Slot-Change = documented flake, **PASS on isolated rerun**; sunday_school config touches no slot logic) → effectively **22/22**; `--category transcript` → **3/3**
- `test_sunday_school_handoff_2026_06_22.py` +7 config tests (answer uses config not hardcoded; July when config says July; reflects changed status; missing-config safe fallback no invented facts; handoff_enabled=false omits ask; real-default-config drives July; source-guard: no hardcoded month in `parent_flow`). Verified both „საკვირაო სკოლა დაემატა უკვე?" / „მაინტერესებს" → config-driven answer.
- **NO prompt / Calendar / Sheets-schema / WhatsApp / model change. YAML changed: ONLY the `sunday_school` section.** ⚠️ Admin PANEL form does not yet expose the new fields (YAML/`update_section`-editable now; panel exposure = future enhancement). Production NOT green; live smoke pending.

---

## ✅ STREAM-DATE PROMPT CLEANUP (2026-06-22)

**Production STILL NOT green.** First task off the **Source-of-Truth audit + verification sweep** (`docs/SOURCE_OF_TRUTH_AUDIT_2026_06_22.md` + `docs/SOURCE_OF_TRUTH_VERIFICATION_SWEEP_2026_06_22.md`). A surgical, test-gated source-of-truth fix — **the one confirmed live fact-drift bug**.

**The bug (verified):** `system_parent_v2.md:293` (the LIVE PARENT engine prompt) HARDCODED the three camp stream dates `(23–29 ივნისი / 5–11 ივლისი / 14–20 ივლისი)`. The model could emit these from prompt memory, bypassing both `sections.yaml` (Admin Config) AND the camp-stream date-filter (`is_camp_stream_visible`) — so an Admin edit or an already-started stream would silently drift.

**The fix (PROMPT ONLY — `system_parent_v2.md` is the ONLY file changed besides tests):** replaced the literal-date line with a no-hardcode rule — ნაკადების თარიღები *არასოდეს* მეხსიერებიდან/prompt-იდან; *მხოლოდ* `get_camp_info` → ხილული ნაკადებით; tool მომავალ ნაკადს არ აბრუნებს → თარიღი არ გამოიგონო. The consultation-vs-stream teaching is preserved; line 288's `<streams>` placeholder + `get_camp_info("conditions"/"dates")` were already the canonical path. **NO code / YAML / data / Calendar / Sheets / WhatsApp / model change.** (Legacy `system_parent.md:6` still carries the literals — out of scope, fallback-only.)

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2746 passed, 0 failed, 28 skipped** (2738 → +8)
- corpus **9/9**; `RUN_PROPERTY_TESTS=1` property **28/28**; `python test_agent.py` ✅
- `scenario_runner_full.py --priority CRITICAL` → **20/22**, the two misses SC-12 (Exact Slot Busy) + SC-63 (Price Manipulation) are the **documented real-model flakes — both PASS on isolated rerun**; the stream-date change touches neither slot nor price logic → effectively **22/22**
- `--category transcript` → **3/3**
- new `tests/test_prompt_no_hardcoded_stream_dates_2026_06_22.py` (8 — written RED-first: asserts no literal stream date (hyphen+en-dash ×3), no summer `dd–dd ივნის/ივლის/აგვისტ` range, AND the prompt still routes streams through `get_camp_info` + forbids memory dates). Prompt-size cap (`<48 KB`) still passes.

**Note:** stream-question LLM behaviour („ნაკადები როდის არის?") is now **prompt-enforced** + the `get_camp_info`/date-filter chain is deterministically tested (`test_camp_stream_date_filter_2026_06_20.py`), but there is **no dedicated real-model stream-question scenario** in `scenario_library.py` — a live smoke (or a new NORMAL scenario) is the only way to confirm the live model actually calls the tool. Live smoke of THIS cleanup still pending.

---

## ✅ SUNDAY-SCHOOL MANAGER HANDOFF + FALSE-SUCCESS FIX (2026-06-22)

**Production STILL NOT green.** A live test showed the agent telling a Sunday-school enquirer „მენეჯერს გადავცემ" (future tense — a PROMISE) after collecting name+phone, but **no manager notification was ever dispatched**. Root-caused + fixed deterministically + test-gated.

**Root causes (two):**
1. **No deterministic dispatch for the Sunday-School (non-camp) handoff.** „საკვირაო სკოლა" had NO in-conversation handler — it fell to the LLM, which generated a manager-handoff *promise* without calling `request_manager_callback`, so nothing dispatched. (SMTP is fine — confirmed with a real controlled test email to `wordacademyleads@gmail.com`.)
2. **False-success in `_request_manager_callback`.** It called `send_manager_notification` in a try/except, **ignored the result**, and **always returned `{"success": True, "manager_notified": True}`** — so even a failed/never-sent email read as success. Compounded by `notify_manager`'s `email AND whatsapp` contract: with WhatsApp intentionally unconfigured in production, the combined result was False on every real email-only send.

**The fix (deterministic, EMAIL-ONLY for Sunday School):**
- `app/flows/parent_flow.py` — new `_maybe_handle_sunday_school` (wired FIRST in `handle`, before the static welcome). „საკვირაო სკოლა" → deterministic answer **„საკვირაო სკოლა ივლისში დაემატება…"** (no invented price/dates/program) + collects name+phone → calls `notification_service.notify_sunday_school_handoff` → confirms **„მადლობა, ინფორმაცია გადავეცი მენეჯერს…" ONLY on a real email send**; on failure → safe **„ტექნიკური მიზეზით… ვერ დადასტურდა"** (never a false „გადავეცი"). NO Calendar, NO WhatsApp. Idempotent per conversation. Returns None for every non-Sunday-school message. Name-reject stems also extended (`საკვირაო/სკოლ/მაინტერეს` + the under-age batch's `მომწერ/გამომიგზავ/გამიგზავ/მენეჯერ`).
- `app/services/notification_service.py` — new EMAIL-ONLY `notify_sunday_school_handoff(lead)` (no WhatsApp); `notify_manager` refactored to `_dispatch_manager_channels` (return contract `email AND whatsapp` UNCHANGED); **`send_manager_notification` is now EMAIL-GATED** (returns `email_ok` — WhatsApp still SENT identically, just no longer poisons the boolean; fixes the email-only-in-prod case).
- `app/services/sheets_service.py` — separate **`SundaySchoolLeads`** tab (`log_sunday_school_lead`, columns `created_at/channel/sender_id_masked/name/phone/lead_type/source/user_message/status/notification_status`). Best-effort: returns False / never raises, **never blocks the email**, and **never touches the camp booking A-Q `Leads` schema**.
- `app/agent/tools/parent_tool_executor.py` — `_request_manager_callback` now **gates success on the real dispatch** (email-only success counts; on failure returns `{"success": False, "reason": "dispatch_failed"}` and does NOT mark notified). Under-age handoff path (`notify_manager_handoff`, OR semantics) unchanged.

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2738 passed, 0 failed, 28 skipped** (2704 → +34)
- corpus **9/9**; `RUN_PROPERTY_TESTS=1` property **28/28**; `python test_agent.py` ✅
- `scenario_runner_full.py --priority CRITICAL` → **21/22**, the one miss SC-13 (Slot Change Mid-Flow) is the documented real-model flake — **PASS on isolated rerun** (a 429 rate-limit also hit mid-run); my changes don't touch slot/booking logic → effectively **22/22**
- `--category transcript` → **3/3**
- new `tests/test_sunday_school_handoff_2026_06_22.py` (34 — email-only/no-WhatsApp dispatch, email-gated success, false-success fix, no-Calendar, no-booking-sheet, separate-tab logged, sheet-failure-non-blocking, idempotency, name+phone-in-one, camp-not-hijacked, transcript end-to-end, regression smoke; **+ adversarial-review hardening**: intent requires „საკვირაო"+„სკოლ" (bare „საკვირაო ბანაკი" no longer hijacked), mid-collection camp/price/question pivot DEFERS and never stores a topic word as the name, email-failure → retry works (FAIL keeps the collection marker), and the manager-callback writes its CRM lead ONLY after a confirmed dispatch (no duplicate row on retry))

**Adversarial-review note (multi-agent, 2026-06-22):** the constraint/isolation dimension came back CLEAN; the logic + regression dimensions surfaced 4 real issues (2 major / 2 minor), all FIXED above and test-gated before this batch closed: (1) mid-collection topic pivot trapped the user + mis-captured „ბანაკი" as a name; (2) email-failure was non-retryable; (3) bare-„საკვირაო" hijacked camp questions; (4) failed-then-retried camp callback could append a duplicate CRM Leads row.
- **No prompt / YAML / data / Calendar / model / WhatsApp-send-logic change. Production NOT green.** Live smoke of THIS fix still pending (replay the Sunday-school sequence after a hard restart; then confirm the manager email at `wordacademyleads@gmail.com`).

---

## ✅ UNDER-AGE HANDOFF NAME + MANAGER-NUMBER FIX (2026-06-22)

**Production STILL NOT green.** A real live PARENT transcript for an **8-year-old (under-age)** surfaced two deterministic bugs in the under-age manager-handoff contact collection. Both fixed, in-memory only — **NO** prompt / YAML / event-data / Calendar / Sheets / WhatsApp / notification-logic change.

**Live transcript that broke it** (child age 8 → ineligible → manager handoff offered):
- „კი მომწერე" → ❌ „სახელი მივიღე…" — the verb „მომწერე" („write to me") was stored as the parent's NAME.
- „მენეჯერის ნომერი მომწერე" → ❌ re-asked for THE PARENT's number instead of giving the MANAGER's number.

**Root cause (two independent):**
1. **Name false-positive** — `_NAME_REJECT_STEMS` had no entry for the comms-imperative verbs („მომწერ" / „გამომიგზავ" / „გამიგზავ") or the role word „მენეჯერ", so `is_valid_person_name` accepted „მომწერე" / „მენეჯერის მომწერე" as a name.
2. **Manager-number request shadowed** — in `handle`, `_maybe_handle_underage_manager_handoff` (runs first, by design „under-age takes precedence") intercepted any „მენეჯერ"-bearing message for an under-age lead, so the dedicated `_maybe_handle_explicit_manager_request` (one step later) never saw a pure manager-NUMBER request.

**The three fixes (all in `app/flows/parent_flow.py`, in-memory only):**
- **A** — added „მომწერ", „გამომიგზავ", „გამიგზავ", „მენეჯერ" to `_NAME_REJECT_STEMS` (every name chokepoint now rejects them; real names ნინო/ნიკოლოზი/მარიამი unaffected).
- **B** — the under-age handoff now serves an explicit manager-NUMBER request itself: `if _is_explicit_manager_number_request(text): return _render_manager_number_answer(lead)` (the configured `558 67 47 33`, callback offer when phone unknown) — placed right after the in-context gate, before contact parsing. No Sheets/Calendar/dispatch.
- **C** — `_is_handoff_affirmative` now also recognises a leading affirmative token (კი/დიახ/ჰო/ხო/კარგი/ოკ) + a „contact me" verb (`_HANDOFF_CONTACT_VERBS` = მომწერ/დამირეკ/დამიკავშირ/დამაკავშირ/გადაეც/გადამეც), so „კი მომწერე" is read as handoff agreement → asks for name + phone (not a name capture).

**GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2704 passed, 0 failed, 28 skipped** (2676 → +28)
- new `tests/test_underage_handoff_name_and_manager_number_2026_06_22.py` (28 — comms-verb/role-word name rejection, real-name still valid, affirmative+contact-verb, „კი მომწერე" asks name+phone/no name capture, manager-number disclosed mid-handoff, real name+phone still dispatches, transcript end-to-end through `parent_flow.handle` engine-ON + mocked OpenAI never consulted)
- driven through `_maybe_handle_underage_manager_handoff` + `parent_flow.handle`; engine ON; mocked OpenAI; no real Meta/Calendar/Sheets/network.

**Known remaining blockers** unchanged: Meta App Review (#10), Railway staging deploy, follow-up staging test, live smoke. **Live smoke of THIS fix still pending** (replay the 8yo transcript after a hard process restart). **Production is NOT green.**

---

## ✅ LIVE-DEMO POLISH BATCH (2026-06-21/22)

**Production STILL NOT green.** Six narrow, deterministic, test-gated fixes from a live PARENT/camp transcript, prepping the agent for a **controlled client test** (NOT production). No deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta writes; **no prompt / YAML / event-data / Calendar-schema / Sheets-schema / WhatsApp / follow-up change.**

**Latest GREEN code state (verified 2026-06-22):**
- `pytest tests/ -q` → **2676 passed, 0 failed, 28 skipped** (2633 → +43 across this batch)
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28**
- `python test_agent.py` → ✅
- `tools/scenario_runner_full.py --priority CRITICAL` → **effectively 22/22** — one full run showed 18/22 but all four (SC-26 Will-Think, SC-46 Everything-in-One, SC-63 Price-Manipulation, SC-66 Manager-Request) are **real-model stochastic** and passed on isolated rerun (SC-63 is the documented flake). No real regression.
- `tools/scenario_runner_full.py --category transcript` → **3/3**

### The six fixes (all in `app/flows/parent_flow.py` unless noted)
1. **Manager-number disclosure (PARENT)** — new pre-engine `_maybe_handle_explicit_manager_request` (after underage-handoff, before contact-collection). Fires on `მენეჯერ` + `ნომერ/ტელეფონ/კონტაქტ` + NO own-phone → discloses `admin_config_service.get_manager_phone()` (`558 67 47 33`) + offers callback. PARENT previously had NO disclosure path (only ADULT did).
2. **Manager-number is CONTEXT-AWARE** — `_render_manager_number_answer(lead)`: if `lead.phone` is already known (e.g. booked) it does NOT re-ask for the number — „მენეჯერი ასევე თავად დაგიკავშირდებათ"; if unknown it offers a callback.
3. **Mid-conversation greeting strip** (`app/agent/llm/parent_llm_engine.py`) — `_strip_mid_conversation_greeting`: removes a sentence-initial „გამარჯობა/სალამი/მოგესალმებით" once the conversation already has an assistant turn (first reply keeps it).
4. **Anti-repeat contact-ask** — when the same contact-ask was already sent last turn, `_maybe_request_full_contact_on_intent` returns a **varied** wording (`_CONTACT_REQUEST_*_RETRY`, with a format example) instead of byte-identical repetition. WHAT is asked is unchanged (no lead-capture risk).
5. **Price-objection ≠ decline** — `_maybe_handle_decline_engine` now defers to the engine (returns None) when a decline phrase co-occurs with an interest/contrast marker `_DECLINE_OVERRIDE_INTEREST = (მაგრამ, თუმცა, მაინც, ძვირ, მიჭირს)`. So „…არ მინდა, **მაგრამ** ბავშვი ძალიან მინდა" is handled as an objection (value + 6-month split + consultation), NOT a cold-close. Real declines (no contrast) still close.
6. **Phone + name correction** — new pre-engine `_maybe_handle_contact_correction` (after manager-number, before contact-collection). Phone: on `შევცდი/ეს არა/სხვა ნომერ/სწორი ნომერ/სწორია/არასწორ` + a valid phone → overwrite `lead.phone` (last valid number). Name: on `კი არა / შევცდი / სახელი არ / არასწორ / leading „არა"` + no phone → overwrite `lead.name` (last valid Georgian name token). **In-memory only — never touches Calendar/Sheets/notifications.** Committed-booking → acks „შესწორებულ…მენეჯერს გადავცემ" without re-writing Calendar/Sheets. AGE correction logic untouched.

### Files changed this batch
- product: `app/flows/parent_flow.py`, `app/agent/llm/parent_llm_engine.py`
- tests: `tests/test_manager_number_and_greeting_2026_06_21.py` (+19), `tests/test_objection_and_corrections_2026_06_22.py` (+22)
- new doc: `docs/LIVE_TEST_CHECKLIST_2026_06_22.md` — operator adversarial test checklist (🔴 top-8 + 6 categories, ~45 Georgian scenarios, code-grounded; built by a read-only multi-agent review).

### New code-level Georgian strings (operator should grammar-confirm)
„მენეჯერის ნომერია: 558 67 47 33. შეგიძლიათ პირდაპირ დაუკავშირდეთ. {მენეჯერი ასევე თავად დაგიკავშირდებათ | თუ გირჩევნიათ, დატოვეთ თქვენი ნომერი…}" · „გასაგებია, ნომერი შევასწორე — {phone}." · „გასაგებია, {name}." (+ committed variants „…მენეჯერს გადავცემ").

### ⚠️ Known weak spots NOT yet hardened (operator briefed; client findings here are expected, not new bugs)
- **Hard-guarded (won't happen):** mid-greeting · fake booking (tool-success gated) · age re-ask · invented registration link.
- **Prompt/context-reliant (very reliable, not a hard guard):** name/phone re-ask, invented price/dates, **Georgian-only (English leak)**.
- **LLM-only, NO deterministic guard (weakest):** **off-topic deflection** (e.g. „მუფასა ვინ არის"). Usually deflects, not guaranteed.

### Known remaining blockers
1. **Production-green is gated primarily by Meta App Review** (external; error #10) + Railway staging deploy + follow-up staging test + live smoke. Not datable by us; mostly NOT code.
2. **Live smoke of this demo-polish batch** still pending (hard-restart the process first — `--reload` has run stale code before).
3. **Follow-up 24h+ delivery** blocked by Meta policy (`send_message` uses `messaging_type:"RESPONSE"` with NO message tag; out-of-24h needs `HUMAN_AGENT` tag + approved permission, OR Recurring Notifications). Not a scheduler bug.
4. Railway staging deploy / follow-up staging test not done.
5. **Production is NOT green.**

### NEXT PLANNED TASK — HARDEN OFF-TOPIC + ENGLISH GUARDS (operator deferred „ჯერ არ მინდა")
Add narrow deterministic guards for #4 (off-topic deflection — e.g. „მუფასა ვინ არის") and #5 (non-Georgian/English reply → Georgian fallback), prompt-untouched, test-gated. The other prompt-reliant items (name/phone re-ask, price/date hallucination) are acceptable for now.

---

## ✅ CONSULTATION FLOW MEMORY / REPEATED AGE FIX (2026-06-20)

**Production STILL NOT green** (live smoke for THIS fix pending; Railway staging deploy not done; Meta App Review open). The agent now REMEMBERS the child age + phone a parent gives in ONE message and never re-asks a fact it already holds. No deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta writes; no prompt / event-data / Calendar-schema / Sheets-schema / WhatsApp-notification-logic / booking / `.env` / model change.

**Latest GREEN code state (verified 2026-06-20):**
- `pytest tests/ -q` → **2633 passed, 0 failed, 28 skipped** (2608 → +25)
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold)
- `python test_agent.py` → ✅ all checks pass
- `tools/scenario_runner_full.py --priority CRITICAL` → **21/22 stable + SC-63 stochastic → effectively 22/22**. SC-63 (Price Manipulation, `difficult`) is the documented real-model flake; isolated reruns this session = **PASS / FAIL / PASS**; no pricing code was touched, so it is unrelated to this fix.
- `tools/scenario_runner_full.py --category transcript` → **3/3**
- **Prompt files unchanged**; **event data `sections.yaml` / `camp_2026.yaml` unchanged**; Calendar + Sheets schema unchanged; model `gpt-4.1-mini` unchanged.

### The live bug
A parent gave the child age + phone in ONE message — „14 წლის არის 595999733" — and the agent stored the phone but kept asking „რამდენი წლისაა თქვენი შვილი?" turn after turn (scripted-bot behaviour).

### Root cause — extraction (+ turn order), NOT a state-key mismatch
`parent_llm_engine.maybe_capture_child_age_fallback` had a blanket phone-hint guard: `for tok in _PHONE_HINT_TOKENS: if tok in text: return`. `_PHONE_HINT_TOKENS` includes phone prefixes (`595`/`598`/`599`…), so a message containing „595…" **bailed out of age capture entirely** → `child_age` was never set → the LLM (correctly, per its prompt — which already forbids re-asking known facts) re-asked for the genuinely-missing age. Compounding it, the capture ran POST-turn (after the reply was already generated). The canonical fields were never in conflict: `lead.child_age` and `lead.phone` are single canonical fields, exposed to the model in `_build_context_message`.

### The fix (all in `app/agent/llm/parent_llm_engine.py`)
1. **Phone-aware age extraction** — new `_strip_phone_numbers()` removes recognised Georgian phone numbers (reuses `parent_flow.PHONE_CANDIDATE_PATTERN` / `VALID_LOCAL_PREFIXES`; fallback strips 7+ digit runs) BEFORE age parsing, so a phone in the same turn no longer blocks age capture and its digits are never misread as an age. The age-context gate (`წლ`/`წელ`/child-word/pending) + range/time/date guards are unchanged.
2. **Deterministic phone capture** — new `maybe_capture_phone_fallback()` captures exactly ONE valid 9-digit Georgian phone (no-op on 0 or 2+ phones; never overwrites an existing phone; never touches `child_age`). Reuses the canonical `_parse_name_phone` / `_distinct_valid_phones`.
3. **Pre-turn fact merge** — new `_capture_turn_facts(conversation, lead, user_message)` runs at the TOP of `run_parent_llm_turn`, BEFORE `_build_context_message` / `_build_sales_context`, so the model sees the age + phone the SAME turn. The post-turn fallback stays as an idempotent safety layer.
4. **State-driven anti-repeat guard** — new `_suppress_redundant_age_question()` on the engine's final reply: if `child_age` is known AND the reply asks „რამდენი წლის"/„რა ასაკის", replace it with the next missing detail (phone if unknown, else preferred day/time, via `_next_missing_contact_prompt`). Markers kept tight so a CONFIRMATION mentioning the age is never tripped. When the age is genuinely unknown the reply is untouched (asking is correct then).

### Confirmed behaviour
- „14 წლის არის 595999733" → persists `child_age="14"` AND `phone="595999733"`.
- „14 წლისაა 595999733" → both. „14 წლის არისს" → age (typo-tolerant). „ცამეტი/თოთხმეტი წლისაა" → 13/14 via the existing parser.
- Phone capture never erases a known age; age capture never erases a known phone; two phones → not guessed.
- Once the age is known the agent does NOT re-ask it on later turns (slots request / time selection / confirmation).
- Pre-booking age correction still works: „არა, 15 წლისაა" updates 14 → 15.
- **No phrase hack** — the fix is phone-stripping + pre-turn state merge + a state-driven guard.

### Preserved (unchanged)
Underage handoff · Saturday/Sunday scheduling · Sheets A–Q alignment · WhatsApp manager notifications · camp registration link · camp info behaviour · camp stream date filter · prompt files · event/KB data · Calendar/Sheets schema · no live integrations touched.

### Files changed
- product: `app/agent/llm/parent_llm_engine.py`
- tests: new `tests/test_consultation_age_memory_2026_06_20.py` (+25, through `parent_flow.handle` / `process_message`, engine ON, mocked OpenAI)
- **Note:** `data/admin_config/templates.yaml` mtime was bumped by the scenario runner's admin write-path but is byte-identical to its `.bak` — NO content change. `sections.yaml` / `camp_2026.yaml` untouched.

### Live smoke still needed (operator — flush Redis first)
1. „ბანაკზე რეგისტრაცია მინდა" → registration URL + consultation offer.
2. „კი მინდა" → asks for the missing contact/age.
3. „14 წლის არის 595999733" → persists child_age=14 + phone=595999733; does NOT re-ask age; moves to day/time or offers slots.
4. „შემომთავაზეთ თავისუფალი დღეები" → offers slots; does NOT re-ask age.
5. „იყოს 10 საათი" → selects/confirms slot; does NOT re-ask age.
6. „მაწყობს" → books if all required fields are known.

### Known remaining blockers
1. **Live smoke test for this consultation-memory fix** still pending (the 6-step sequence above).
2. **Railway staging deploy** not done.
3. **Follow-up staging test** not done.
4. **Meta App Review / production permissions** open.
5. **Production is NOT green.**

### NEXT PLANNED TASK — LIVE SMOKE TEST: CONSULTATION MEMORY / BOOKING FLOW
Operator flushes Redis and replays the 6-step Messenger sequence above on the live process, verifying age+phone persistence, no repeated child-age question, and booking on confirmation.

---

## ✅ CAMP STREAM DATE FILTER FIX (2026-06-20)

**Production STILL NOT green** (Railway staging deploy not done; Meta App Review open). A user-facing **display / eligibility filter** that hides each camp stream once its Asia/Tbilisi start date arrives. **No stream is deleted or mutated in Admin/config.** No deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta writes; no prompt / event-data / Calendar-schema / Sheets-schema / WhatsApp-notification-logic / booking / `.env` / model change.

**Latest GREEN code state (verified 2026-06-20):**
- `pytest tests/ -q` → **2608 passed, 0 failed, 28 skipped** (2581 → +27 date-frozen tests; the filter is a **no-op at today's real date 2026-06-20** — all three streams are still future — so the prior 2581 are unchanged)
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold)
- `python test_agent.py` → ✅ all checks pass
- `tools/scenario_runner_full.py --priority CRITICAL` → **22/22**
- `tools/scenario_runner_full.py --category transcript` → **3/3**
- **Prompt files unchanged**; **event data `sections.yaml` / `camp_2026.yaml` unchanged** (streams NOT deleted); Calendar + Sheets schema unchanged; model `gpt-4.1-mini` unchanged.

### The fix — Camp Stream Date Filter
Camp streams stay in Admin/config; a user-facing filter decides which to SHOW. **Visibility rule** (Asia/Tbilisi „today" via the existing `now_tbilisi` / `admin_config_service._now_tbilisi` helper — the same seam the sibling adult-event date filter uses):
- `active AND today <  start_date` → **visible**
- `active AND today >= start_date` → **hidden** (hidden ON the start day)
- `inactive` → **hidden** regardless of date
- empty `dates_text` → visible; non-empty-but-unparseable → hidden (+ warning)

Start date = the FIRST day of the `„DD-DD <month>"` range (e.g. `23-29 ივნისი` → 23 June), parsed with the existing Georgian `_find_month` stems.

**Current streams & behaviour:**
- **I ნაკადი | 23-29 ივნისი | active** → hidden from **June 23**
- **II ნაკადი | 5-11 ივლისი | active** → hidden from **July 5**
- **III ნაკადი | 14-20 ივლისი | active** → hidden from **July 14**
- June 20 / 22 → all three visible · June 23 → I hidden · July 5 → I+II hidden · July 14 → all hidden.
- **If no future streams remain, the agent must NOT invent dates** — the `get_camp_info` tool returns an empty stream list and the legacy dates answer falls back to the manager-handoff line.

### New helpers — `app/services/admin_config_service.py`
`_parse_camp_stream_start_date()` (≈:1126), `is_camp_stream_visible(stream, *, now=None, year=None)` (≈:1167), `get_visible_camp_streams(streams=None, *, now=None, year=None)` (≈:1202). Grouped with the sibling adult-event date filter; reuse `_find_month` + `_now_tbilisi`. `get_camp_facts()` itself is left RAW (the data source — never filtered).

### Affected user-facing surfaces (all route through `get_visible_camp_streams`)
- `admin_config_service` visible-stream helper (`get_visible_camp_streams` / `is_camp_stream_visible`)
- `parent_tool_executor._get_camp_info` (engine `get_camp_info` tool, topics `dates` + `all`)
- `parent_reply_composer._format_knowledge_block`
- `parent_turn_router._build_premium_dates_answer` (empty → existing manager fallback)
- `parent_turn_analyzer._format_knowledge_summary`
- `parent_flow._facts_for_post_booking` (post-booking composer facts)
- `comment_service` rich-DM (legacy canonical build)
- `admin_config_service.render_section_dm` (camp-type sections only; adult sections untouched)

### Isolation (unchanged behaviour)
Booking / Calendar / Sheets unchanged · WhatsApp notification logic unchanged · registration-link behaviour unchanged · camp-info behaviour unchanged · price / program / age answers unchanged · event/KB data unchanged · prompt files unchanged. A dedicated test asserts the filter path never reaches Calendar / Sheets / Messenger / notification code.

### Static-copy note (future cleanup, NOT a live blocker)
`parent/price.yaml::info_first_response` still hard-codes the three stream dates. It is reachable only via the legacy/dead `PARENT_INFO_FIRST_RESPONSE` alias — **not served by the live engine or any of the filtered dynamic surfaces**, so it is NOT a live leak. Left unchanged (making a static YAML date-aware would need a copy/prompt edit). Should be re-checked if that template is ever wired live again.

### Files changed
- product: `app/services/admin_config_service.py` (3 new helpers + `render_section_dm` camp-type gate), `app/agent/tools/parent_tool_executor.py`, `app/agent/llm/parent_reply_composer.py`, `app/flows/parent_turn_router.py`, `app/agent/llm/parent_turn_analyzer.py`, `app/flows/parent_flow.py`, `app/services/comment_service.py`.
- tests: new `tests/test_camp_stream_date_filter_2026_06_20.py` (+27, all date-frozen).
- **No prompt / event-data / Calendar-schema / Sheets-schema / `.env` / model change.**

### Known remaining blockers
1. **Consultation flow memory / repeated child-age bug** (NEXT TASK). Live: user sent `„14 წლის არის 595999733"` (age + phone together) and the agent kept re-asking the child age. Needs state/slot-extraction + anti-repeat (extract age + phone from one message; never re-ask a known child age).
2. **Railway staging deploy** not done (code-side blockers fixed; deploy + attach Redis + dashboard env vars + single replica/one worker + health/smoke remain).
3. **Follow-up staging test** not done (run after staging deploy with Redis attached).
4. **Meta App Review / production permissions** still open (real-customer comment/DM blocked with error #10).
5. **Production is NOT green.**

### NEXT PLANNED TASK — CONSULTATION FLOW MEMORY / REPEATED AGE FIX
Extract child age + phone from a single message (e.g. `„14 წლის არის 595999733"`), persist them as filled slots, and stop the agent from re-asking a known child age. Preserve booking / Calendar / Sheets, prompts, and event/KB data.

---

## ✅ CAMP REGISTRATION / INFO ROUTING + LIVE SMOKE (2026-06-19/20)

**Production STILL NOT green** (Railway staging deploy not done; Meta App Review open). A sequence of live-Messenger fixes to camp registration / information routing, all verified through the REAL `conversation_service.process_message` final-response path (NOT only helper-level), plus a WhatsApp manager-notification fix and a logging-security cleanup. No deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta writes in tests.

**Latest GREEN code state (verified 2026-06-20):**
- `pytest tests/ -q` → **2581 passed, 0 failed, 28 skipped**
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold)
- `python test_agent.py` → ✅ all checks pass
- `tools/scenario_runner_full.py --priority CRITICAL` → **22/22 clean**
- `tools/scenario_runner_full.py --category transcript` → **3/3**
- **Prompt files unchanged**; **event data `sections.yaml` unchanged** (`8cfe06c8…`); `camp_2026.yaml` unchanged; Calendar event schema + Sheets schema unchanged; model `gpt-4.1-mini` unchanged; `LIVE_BROADCAST_ENABLED` default **False**. No booking / Calendar-internals / Sheets-schema / WhatsApp-notification-logic / broadcast / follow-up-scheduler / Meta-webhook / `.env` change.

### Completed fixes (this batch)
1. **Camp registration LIVE-PATH fix (2026-06-19).** A clear camp registration/link/form/sign-up request now returns the Admin `Registration URL` DETERMINISTICALLY via a pre-engine interceptor — the prior fix only made the *menu* skip, but the live final response still reached the LLM engine (which asked the child age / gave an intro). Root cause of the test gap: prior tests STUBBED the engine and asserted a sentinel, never the real outgoing text.
   - New deterministic interceptor `parent_flow._maybe_handle_camp_registration_link` (+ `_is_camp_registration_link_request`, `_render_camp_registration_answer`), wired in `parent_flow.handle()` AFTER `_maybe_handle_event_inquiry` and BEFORE the engine block (runs on engine + legacy paths).
   - The answer LEADS with the link, read from `admin_config_service.get_camp_facts()` → `registration_url` (admin-first over `camp_2026.yaml`; same source as `get_camp_info("registration")`). **No age question, no generic menu, link never invented**; missing URL → safe manager/contact fallback.
   - The LLM engine is bypassed for transactional registration-link requests (verified by an engine SPY that is never called).
2. **Camp INFO over-fire fix (2026-06-20).** A general camp INFORMATION request wrongly returned the registration link. **Root cause: raw-substring marker `„ფორმა"` matched inside `„ინ-ფორმა-ცია"` (information).** Fixed with a word-boundary regex `_CAMP_FORM_TOKEN_RE = re.compile(r"(?<![ა-ჰ])ფორმ(?!ატ)")` so `„ფორმა"` only counts as a standalone form token — never inside `„ინფორმაცია"` or `„ფორმატი"` (format). The same foot-gun was fixed in `conversation_service._is_registration_link_request` (the UNCLEAR clarification helper), plus `„ჩაწერ"`→`„ჩაწერა"` there (so the past participle `„ჩაწერილი"`/„already enrolled" never matches), and `import re` added.
   - `„ბანაკის შესახებ ინფორმაცია"` → general camp info; `„სარეგისტრაციო ფორმა" / „რეგისტრაციის ფორმა" / „ლინკი" / „დავრეგისტრირდე" / „ჩაწერა"` → registration link. False positives around `„ინფორმაცია"`, `„ფორმატი"`, `„ჩაწერილი"` are guarded.
3. **Security / logging cleanup (2026-06-19).** `messenger_service.get_user_profile` now masks `access_token` in its error log (`access_token=***masked***` via `_mask_access_token`); profile-fetch failure remains non-blocking (returns `{}`).

(Earlier in this batch: **Manager WhatsApp manager-notification fix (2026-06-18)** — alias-aware `get_whatsapp_access_token()` / `get_manager_whatsapp_number()` (E.164-normalised) / `is_whatsapp_configured()`; WhatsApp attempted in parallel with email for booking + handoff, non-blocking, email-independent; conftest `_block_real_meta_http` guard so no test ever sends a real WhatsApp/Meta HTTP call. And the **camp-registration intent detector** menu-skip fix + the **general registration-link routing** with an UNCLEAR registration-specific clarification.)

### Live smoke results (operator)
- `„გამარჯობა ბანაკის შესახებ ინფორმაცია რომ მომწერო"` → **camp information response, NO registration link**. ✅
- `„გამარჯობა ბანაკზე როგორ დავრეგისტრირდე?"` → **registration link returned** (`https://tinyurl.com/36jcae8z`). ✅

### Files changed across this batch
- product: `app/flows/parent_flow.py` (camp-registration interceptor + token-aware `ფორმა`), `app/services/conversation_service.py` (registration-link clarification + token-aware `ფორმა` + `import re`), `app/services/messenger_service.py` (`access_token` masking + WhatsApp token/recipient accessors), `app/services/notification_service.py` (WhatsApp parallel send + masked recipient), `app/config.py` (WhatsApp accessors + `normalize_whatsapp_number`).
- tests: new `test_camp_info_vs_registration_2026_06_20.py`, `test_live_camp_registration_link_2026_06_19.py`, `test_camp_registration_intent_2026_06_19.py`, `test_registration_link_routing_2026_06_19.py`, `test_manager_whatsapp_notification_2026_06_18.py`; updated `tests/conftest.py` (`_block_real_meta_http`).
- **No prompt / event-data / Calendar-schema / Sheets-schema / `.env` / model change.**

### Known remaining blockers
1. **Consultation memory / repeated child-age bug.** Live: user sent `„14 წლის არის 595999733"` (age + phone together) and the agent kept re-asking the child age. Needs a separate state/slot-extraction + anti-repeat fix (extract age + phone from one message; don't re-ask a known age). NOT addressed in this batch.
2. **Camp stream date filter (NEXT TASK).** Streams must hide once their start date arrives: **I ნაკადი 23–29 ივნისი** (hide from Jun 23), **II ნაკადი 5–11 ივლისი** (hide from Jul 5), **III ნაკადი 14–20 ივლისი** (hide from Jul 14). Currently all show regardless of date.
3. **Railway staging deploy** not done (code-side blockers fixed; deploy + attach Redis + dashboard env vars + single replica/one worker + health/smoke remain).
4. **Follow-up staging test** not done (run after staging deploy with Redis attached).
5. **Meta App Review / production permissions** still open (real-customer comment/DM blocked with error #10).
6. **Production is NOT green.**

### NEXT PLANNED TASK — CAMP STREAM DATE FILTER FIX
Hide each camp stream once its start date arrives (Asia/Tbilisi), so expired streams are no longer offered/listed. Preserve: camp facts source (`get_camp_facts` / `camp_2026.yaml` streams), timezone, no event-data edit unless explicitly requested, no prompt change unless impossible in code.

---

## ✅ RAILWAY DEPLOY-BLOCKERS PRE-STAGING FIX (2026-06-18, NO DEPLOY)

**Production STILL NOT green** (Meta App Review open; staging deploy not yet performed). This was an **offline / pre-deploy** task — no deploy, no live server/webhook/tick, no real Messenger/IG/WhatsApp/email, no real Redis/Calendar/Sheets/Meta writes. It removes the *code-side* Railway blockers so the NEXT task can deploy to **staging only**.

**Latest GREEN code state (verified 2026-06-18):**
- `pytest tests/ -q` → **2440 passed, 0 failed, 28 skipped** (was 2415 → +25 new)
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold)
- `python test_agent.py` → ✅ all checks pass
- `tools/scenario_runner_full.py --priority CRITICAL` → **21/22 on one full run; effectively 22/22** — SC-63 (Price Manipulation, `difficult`) is real-model **stochastic** (isolated re-run PASS / FAIL / PASS); the config-loading change cannot affect agent behaviour.
- `tools/scenario_runner_full.py --category transcript` → **3/3**
- **Prompt files unchanged**; **event data `sections.yaml` unchanged** (`8cfe06c8…`); Sheets + Calendar schema unchanged; model `gpt-4.1-mini` unchanged; `LIVE_BROADCAST_ENABLED` default **False**. No agent/business logic / booking / Calendar / Sheets-schema / Meta-webhook / broadcast / follow-up-scheduler change.

### STEP 0 — Secrets protection (done first)
- **No git repository exists** anywhere in the workspace → `git status`/`git ls-files` cannot run → **nothing is tracked → no tracked secret files → no STOP condition.** Git will be `init`-ed before the Railway push, so the ignore files were created NOW so secrets are never added.
- **Created [.gitignore](.gitignore) + [.railwayignore](.railwayignore)** covering: `.env`, `.env.*` (with `!.env.example` kept trackable), `credentials.json`, `*credentials*.json`, `*service-account*.json`, `*secret*.json`, `*token*.json`, `*.key`, `*.pem`, `keys/`, `secrets/`, plus Python caches / `.venv` / `tools/reports/` / `*.bak`.
- Secret-like files **on disk** (names only): `.env`, `credentials.json` (real — now ignored); `.env.example` (template, stays tracked). The other `*credential*` matches are code/docs/tests, not secrets.

### Railway blockers FIXED (code/config only)
1. **`config._env` now reads `os.environ` FIRST, `.env` fallback second** ([app/config.py](app/config.py) `_env`, ≈:31-50; added `import os`). Root cause was the `.env`-only read (`ENV_VALUES = dotenv_values(.env)`) → on Railway (no `.env`, vars in `os.environ`) every value was empty → `Settings.from_env()` crashed boot. No secret logging; local behaviour preserved (`load_dotenv` still populates `os.environ` from `.env`).
2. **`REDIS_URL` Railway env supported** (same `_env` fix; `redis_state_service` reads `settings.REDIS_URL`). **`.env` fallback preserved.** Missing URL = safe no-op (in-memory fallback, no crash).
3. **`GOOGLE_CREDENTIALS_JSON` support preserved** — [app/services/google_credentials.py](app/services/google_credentials.py) already reads `os.environ` directly (Railway-safe); **local credential-file fallback preserved**. Not changed.
4. **`requirements.txt`** — added `redis`, `tzdata`, `python-multipart` (unpinned, matching existing style; no other deps touched).
5. **Procfile already Railway-safe** (unchanged): `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT` (one worker). **`runtime.txt` preserved**: `python-3.11`.
6. **`LIVE_BROADCAST_ENABLED=false`** is the staging expectation (and the default).
7. **Single replica / one uvicorn worker / always-on** required — the APScheduler follow-up + comment-follow-up jobs start in-process per worker ([app/main.py](app/main.py) startup, ≈:70-84); multiple workers/replicas → duplicate scheduler → duplicate sends.

### Tests — new [tests/test_railway_env_loading_2026_06_18.py](tests/test_railway_env_loading_2026_06_18.py) (+25, fully offline)
os.environ-beats-`.env` / `.env` fallback / empty-shadow fallback / missing→"" / strip; `REDIS_URL` env + `.env` fallback + `Settings.from_env` integration + missing-is-safe; Google creds env read + `GOOGLE_CREDENTIALS_JSON` env-wins (`\n` repair) + local file fallback (mocked, no Google call); `LIVE_BROADCAST_ENABLED` env-true / default-false; requirements include `redis`/`tzdata`/`python-multipart`; `.gitignore`/`.railwayignore` cover secrets; Redis URL never logged in clear / creds error secret-free / config imports no logging; WhatsApp skipped-when-unconfigured + email-independent dispatch; follow-up Redis-disabled-is-safe. No existing test changed.

### WhatsApp readiness (audit only — NO real send)
- **Current status: email-only / WhatsApp unconfigured.** [notification_service._send_manager_whatsapp](app/services/notification_service.py) short-circuits to `False` (no network) when any var is empty; `notify_manager_handoff` succeeds on **email alone** (email works independently).
- Automatic WhatsApp manager notification requires the **WhatsApp Cloud API** env vars (names only): `WHATSAPP_TOKEN` (or `WHATSAPP_ACCESS_TOKEN`), `WHATSAPP_PHONE_NUMBER_ID`, `MANAGER_WHATSAPP_NUMBER` (or `MANAGER_WHATSAPP`).
- A **Twilio** alternative exists (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `MANAGER_PHONE_NUMBER`) — identified, not configured.
- The **manager fallback phone** (`admin_config_service.get_manager_phone()`, e.g. `558 67 47 33`) is a *displayed* contact, NOT an automatic WhatsApp send.

### Follow-up readiness (audit only — NO real send)
- Follow-up should be smoke-tested **after** the Railway staging deploy, with **Redis attached**. `REDIS_URL` now supports the Railway env. In-memory fallback exists but is **not reliable for production** (lost on restart).
- **Single replica / one uvicorn worker / always-on** required to avoid duplicate scheduler sends. Scheduler logic unchanged.

### Files changed this session
- new: `.gitignore`, `.railwayignore`, `tests/test_railway_env_loading_2026_06_18.py`.
- product/config: `app/config.py` (`_env` os.environ-first), `requirements.txt` (+3 deps).
- **No prompt / event-data / agent-logic / booking / Calendar / Sheets-schema / Meta-webhook / broadcast / follow-up-scheduler / `.env` / model change.** Procfile + runtime.txt unchanged (already safe).
- *Determinism note:* the dev shell had a stray `OPENAI_API_KEY` ≠ `.env`; with os.environ-first it would win at import, so the real-OpenAI gates were run with `env -u OPENAI_API_KEY` to use the project `.env` key (mocked unit suite unaffected).

### Operator decisions / accepted deferred items (unchanged — still in force)
1. **Booked-age overwrite edge case — DEFERRED.** 2. **Formula/fromula parsing — DEFERRED.** 3. **Formula/fromula active test/demo event cleanup** may still be needed before launch. 4. **Meta App Review still open.** 5. **Production is NOT green.**

### NEXT PLANNED TASK — Railway STAGING deploy ONLY (not production)
1. Create / prepare the Railway service. 2. Attach Redis. 3. Set Railway dashboard env vars. 4. Set `LIVE_BROADCAST_ENABLED=false`. 5. Set `GOOGLE_CREDENTIALS_JSON` (full service-account JSON). 6. Use the Procfile start command. 7. Ensure single replica / one uvicorn worker / always-on. 8. Deploy to **staging only**. 9. Run health + smoke tests. 10. Do NOT connect client Facebook/Instagram yet. 11. Do NOT mark production green.

---

## ✅ P0 DATA-INTEGRITY FIX: GOOGLE SHEETS „LEADS" ROW ALIGNMENT (2026-06-18)

**Production STILL NOT green** (Railway deploy blockers + Meta App Review open — unchanged). Operator-reported P0: during a NORMAL consultation booking the Google Sheets „Leads" row was written under the WRONG / shifted columns (values landed to the right of the headers; older rows aligned, the new booking row did not — observed during a Saturday booking test). **NOT the under-age manager handoff** (that path correctly emails the operator and never writes Sheets).

**Latest GREEN code state (verified 2026-06-18):**
- `pytest tests/ -q` → **2415 passed, 0 failed, 28 skipped** (was 2407 → +8 new)
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold)
- `python test_agent.py` → ✅ all checks pass
- `tools/scenario_runner_full.py --priority CRITICAL` → **22/22 clean** (no flake this run)
- `tools/scenario_runner_full.py --category transcript` → **3/3**
- **Prompt files unchanged** (no `app/agent/prompts/*.md` or `policies/*.md` touched); **event data `data/admin_config/sections.yaml` unchanged** (SHA-256 `8cfe06c879b669d1b9dcf4219c4a69a8c2dac9b3a3c8c34001cf198f781645cb`); **Sheets schema unchanged** (`HEADERS` still 17 cols A–Q, same order/names — no add/remove/rename/reorder); Calendar event schema unchanged; model `gpt-4.1-mini` unchanged; `LIVE_BROADCAST_ENABLED` default **False**. No broadcast / follow-up scheduler / Meta webhook / `.env` change.

### Root cause (cause I — unbounded append range)
`app/services/sheets_service.py` `save_lead` (the booking write, reached via `parent_flow._book_selected_slot` → `sheets_service.create_lead` → `save_lead`) appended with `worksheet.append_row(row, value_input_option="USER_ENTERED")` and **no `table_range`**. Verified against gspread 6.2.1: that sends the Sheets `values.append` API the **UNBOUNDED** range `'Leads'` (`absolute_range_name("Leads", None)` → `'Leads'`). Google then uses *logical-table auto-detection* to choose BOTH the target row AND the **start column**; on a live sheet whose data region isn't cleanly A-anchored, it anchors the new row to the detected table's first column — to the right of A — so every value shifts under the wrong header. Aggravated by **cause J** (the live sheet already had a shifted region). The row builder `_lead_to_row` was already correct (17 values, ID first, header order A–Q → rules out causes B/C/G); the per-cell `update_lead` upsert was already A-correct via `COLUMN_INDEX` (not the bug).

### Fix (smallest change — explicit A-anchored write)
`app/services/sheets_service.py` — new `_leads_last_col_a1()` + `_append_lead_row_aligned(worksheet, row)` (≈:164-216); `save_lead` now writes `worksheet.update(range_name=f"A{n}:Q{n}", values=[row], value_input_option="USER_ENTERED")` where `n = len(get_all_values())+1`. This pins all 17 values to columns A..Q in header order, independent of table-detection heuristics — the same deterministic pattern already used by `_ensure_headers` and the events tab. `USER_ENTERED` preserves the historical cell parsing (numeric ID, TRUE/FALSE booleans, Asia/Tbilisi datetime strings) so new rows match older correctly-aligned rows. Saturday and weekday bookings share this one aligned path; the under-age handoff still never writes Sheets.

### Tests — new [tests/test_sheets_leads_alignment_2026_06_18.py](tests/test_sheets_leads_alignment_2026_06_18.py) (+8, fully mocked `FakeWorksheet` — no live Sheets/Calendar/Meta/email/Redis)
Added failing-first, then fixed: (1) `_lead_to_row` matches header order (ID first, no shift); (2) `save_lead` writes an A-anchored `A2:Q2` range and never the unbounded `append_row`; (3) append lands after existing rows (`A4:Q4` with 2 data rows); (4) Saturday booking writes an aligned row; (5) weekday booking writes an aligned row; (6) Saturday & weekday use the identical `A2:Q2` range; (7) `update_lead` targets the correct row + correct A-based columns (Status=N=14, Name=E=5), not the wrong sender row; (8) under-age 8yo manager handoff dispatches the notification and writes NO Sheets. Pre-fix the 5 alignment tests were RED; post-fix all 8 pass. No existing test changed.

### Manual live-sheet cleanup needed (operator — NO live edits were made in this task)
- **Delete or correct** the misaligned live test row(s) — especially the **latest row 19 / the Saturday-test booking row** that landed shifted.
- Correct **only genuinely shifted** rows; leave correctly-aligned older rows alone.
- **Keep the A–Q headers unchanged** (do not reorder/rename/add/remove).
- If an affected misaligned row left stray values in columns **R+**, clear them so Google's table detection can't latch onto a right-shifted region.
- After cleanup, **re-test ONE live booking** and confirm the new row aligns under A–Q (ID→A, Sender ID→B, Platform→C, Segment→D, Name→E, Phone→F, Child Age→G … Status→N).

### Note (not changed, flagged)
`Lead.to_sheet_row()` (`app/models/lead.py`) is a legacy helper that omits the ID column, but it is **dead for writes** (only used by tests inspecting the challenge column `[6]`); production writes use `_lead_to_row`. Left untouched. The comment / events-tab appends use the same `append_row` pattern but were intentionally NOT touched (broadcast / Meta-webhook off-limits).

### Files changed this session
- product: `app/services/sheets_service.py` (only `save_lead` + 2 new private helpers).
- tests: new `tests/test_sheets_leads_alignment_2026_06_18.py`.
- **No prompt / event-data / Sheets-schema / Calendar-schema / `business_hours.yaml` / `.env` / model change.**

### Operator decisions / accepted deferred items (unchanged — still in force)
1. **Booked-age overwrite edge case — DEFERRED** by operator. Do NOT fix unless explicitly requested.
2. **Formula / fromula parsing fix — DEFERRED** by operator. Do NOT implement Formula 1 parsing.
3. **Formula / fromula active test/demo event cleanup** may still be needed before real launch IF it remains active. Do NOT change event data unless explicitly requested.
4. **Production is NOT green.**

### NEXT PLANNED TASK — Railway deploy blockers (audit only so far, NOT fixed)
- `config._env` must read `os.environ` FIRST, `.env` fallback (Railway dashboard env vars currently invisible → boot crash).
- `REDIS_URL` Railway support (shares the `_env` bug).
- `requirements.txt` missing runtime deps: `redis`, `tzdata`, `python-multipart`.
- `.gitignore` / `.railwayignore` for `.env`, `credentials.json`, `*credentials*.json`, `secrets/`, `*.key`.
- `Procfile` / start command Railway-safe.
- single replica / one uvicorn worker / always-on service (else duplicate APScheduler → duplicate follow-up DMs).
- `LIVE_BROADCAST_ENABLED=false` for staging.
- Meta App Review / permissions still open (real-customer comment/DM blocked with error #10).

**Production NOT green until:** deploy blockers fixed → Railway staging deployed → live smoke passes → Meta permissions / App Review addressed.

---

## ✅ SATURDAY SCHEDULING POLICY + P2 SUNDAY-WORDING CLEANUP (2026-06-16)

**Production STILL NOT green** (Railway deploy blockers + Meta App Review open — unchanged). Two code sessions, recorded here: **(A) Saturday scheduling policy update** (allow Sat bookings, keep Sun closed) and **(B) P2 Sunday-wording cleanup** (stale „შაბათ-კვირას" / „Mon-Fri" strings). **The NEXT planned task is Railway deploy blockers — see „Active known / pending items" below.**

**Latest GREEN code state (verified 2026-06-16):**
- `pytest tests/ -q` → **2407 passed, 0 failed, 28 skipped**
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold)
- `python test_agent.py` → ✅ all checks pass
- `tools/scenario_runner_full.py --priority CRITICAL` → **22/22 clean** (no flake this run; the known PARENT booking/slot/screen stochasticity — SC-01/11/12/13/19/46 — passes on re-run when it does flake)
- `tools/scenario_runner_full.py --category transcript` → **3/3**
- **Prompt files unchanged** (no `app/agent/prompts/*.md` or `policies/*.md` touched — all predate these sessions); **event data `data/admin_config/sections.yaml` unchanged** (SHA-256 `8cfe06c879b669d1b9dcf4219c4a69a8c2dac9b3a3c8c34001cf198f781645cb`); `app/agent/knowledge/business_hours.yaml` + its mirror unchanged; model `gpt-4.1-mini` unchanged; `LIVE_BROADCAST_ENABLED` default **False**. No Calendar event schema / Sheets schema / broadcast / follow-up scheduler / Meta webhook / OpenAI model / `.env` change.

### (A) Saturday scheduling policy — DONE
Consultation bookings are now allowed **Monday–Saturday**; **Sunday** stays closed. The block used to be the WHOLE weekend (`weekday() >= 5`); it is now centralised in one helper so only Sunday is closed.

1. **Mon–Sat allowed; Sunday blocked.** New single source of truth: `app/services/calendar_service.py` `is_closed_booking_day(day)` + `CLOSED_WEEKDAYS = frozenset({6})` (≈:48-58) — `6 == Sunday` (Python `weekday()`: Mon=0 … Sat=5, Sun=6).
2. **Working hours UNCHANGED:** 10:00–21:00, 60-minute slots, last valid start 20:00 (20:00–21:00). `business_hours.yaml` not touched.
3. **Timezone UNCHANGED:** Asia/Tbilisi. The booking day is evaluated in Tbilisi, not UTC (a Sat-22:00-UTC = Sun-02:00-Tbilisi instant is still `weekend`).
4. **FreeBusy still respected:** a busy Saturday slot is filtered from offered slots and cannot be booked.
5. **Calendar event schema UNCHANGED** (`book_slot` / `create_event` bodies untouched). **Sheets schema UNCHANGED.**
6. **Internal `weekend` reason string still exists — now fires for Sunday only** (Sunday is part of the weekend, so every downstream branch + the prompt rule keep working unchanged).
7. **Five gate sites rewired** to the helper (logic-equivalent, Sat→open, Sun→closed): `calendar_service.py` `get_available_slots` (≈:80), `_get_free_slots_for_day` (≈:171), `is_within_business_hours` (≈:249, returns `(False, "weekend")` for Sunday); `app/agent/tools/parent_tool_executor.py` `_book_consultation` pre-check (≈:955) and reschedule pre-check (≈:1688).
8. **Tests:** new [tests/test_saturday_scheduling_policy_2026_06_16.py](tests/test_saturday_scheduling_policy_2026_06_16.py) (**32 tests** — Sat allowed / Sun blocked / weekday unchanged / working-hours boundaries on Sat / timezone (UTC-instant + naive) / slot generation (Sat yields 11 slots, Sun yields 0 and never queries Calendar) / FreeBusy filtering / end-to-end executor booking; **plus the 2 P2 wording tests below**). Updated existing weekend-blocked tests to the new contract (NOT weakened to allow all weekends): [tests/test_booking_availability_patch.py](tests/test_booking_availability_patch.py) (`test_weekend_still_rejected` → `test_saturday_now_allowed` + `test_sunday_still_rejected`), [tests/test_parent_llm_engine.py](tests/test_parent_llm_engine.py) (`test_patch6_is_within_business_hours_rejects_weekend` now asserts Sunday blocked + Saturday allowed).

### (B) P2 Sunday-wording cleanup — DONE
Two stale strings (Saturday is now open) — wording only, **no scheduling logic / no prompt edit**:

9. **User-facing Georgian** — [app/flows/parent_flow.py](app/flows/parent_flow.py) `_format_repaired_slot_response` `weekend` branch (≈:1116-1119): was „ამ დღეს (შაბათ-კვირას) კონსულტაციები არ ინიშნება…" → now **„კვირას კონსულტაციები არ ინიშნება. შემიძლია სხვა დღეებში თავისუფალი დროები შემოგთავაზოთ."** (no more „შაბათ-კვირას"; names Sunday only; „სამუშაო დღეებში" → „სხვა დღეებში" so Saturday isn't implicitly excluded).
10. **Internal LLM hint** — [app/agent/tools/parent_tool_executor.py](app/agent/tools/parent_tool_executor.py) `_book_consultation` `outside_business_hours` result `business_hours` field (≈:972): **`(Mon-Fri, Asia/Tbilisi)` → `(Mon-Sat, Asia/Tbilisi)`**.
11. **Tests:** +2 in `tests/test_saturday_scheduling_policy_2026_06_16.py` (`test_weekend_rejection_text_names_sunday_not_saturday` — asserts „კვირას"/„არ ინიშნება" present and „შაბათ" absent; `test_saturday_outside_hours_hint_says_mon_sat_not_mon_fri` — asserts the hint reads `Mon-Sat`, never `Mon-Fri`). Updated [tests/test_parent_reschedule_state_and_time.py](tests/test_parent_reschedule_state_and_time.py) (2 assertions that referenced the old „შაბათ-კვირას" string). Left untouched on purpose: the `_WEEKEND_WORDS` input-detector tuple (it correctly detects a user *saying* „შაბათ"/„კვირა") and the `Mon-Fri` comment in `tools/manual_simulation_p3c_exact_slot_availability.py` (a date-picker comment, not user-facing).

**Files changed across these two sessions** — product: `app/services/calendar_service.py`, `app/agent/tools/parent_tool_executor.py`, `app/flows/parent_flow.py`. tests: new `tests/test_saturday_scheduling_policy_2026_06_16.py`; updated `tests/test_booking_availability_patch.py`, `tests/test_parent_llm_engine.py`, `tests/test_parent_reschedule_state_and_time.py`. **No prompt / event-data / `business_hours.yaml` / `.env` / model change.**

### Operator decisions / accepted deferred items (unchanged — still in force)
1. **Booked-age overwrite edge case — DEFERRED** by operator. Do NOT fix unless explicitly requested. (See the demoted P1 section below for the full risk note.)
2. **Formula / fromula parsing fix — DEFERRED** by operator. Do NOT implement Formula 1 parsing — it will not be a real future event.
3. **Formula / fromula active test/demo event cleanup** may still be needed before real launch IF it remains active (the only active adult event is „fromula 1", 28 აგვისტო, status active). Do NOT change event data unless explicitly requested.
4. **Production is NOT green.**

### Active known / pending items
**NEXT PLANNED TASK — Railway deploy blockers (audit only so far, NOT fixed):**
- `config._env` must read `os.environ` FIRST, `.env` fallback (Railway dashboard env vars currently invisible → boot crash).
- `REDIS_URL` Railway support (shares the `_env` bug).
- `requirements.txt` missing runtime deps: `redis`, `tzdata`, `python-multipart`.
- `.gitignore` / `.railwayignore` needed for `.env`, `credentials.json`, `*credentials*.json`, `secrets/`, `*.key`.
- single replica / one uvicorn worker / always-on service (else duplicate APScheduler → duplicate follow-up DMs).
- `LIVE_BROADCAST_ENABLED=false` for staging.
- Meta App Review / permissions still open (real-customer comment/DM blocked with error #10).

**Production NOT green until:** deploy blockers fixed → Railway staging deployed → live smoke passes → Meta permissions / App Review addressed.

### Suggested live smoke before Railway (operator, after a local restart)
1. **Saturday** consultation request inside working hours → booking flow is allowed (no „weekend" rejection).
2. **Sunday** consultation request → rejected with the **Sunday-only** wording („კვირას კონსულტაციები არ ინიშნება…", no „შაბათ-კვირას").
3. Under-age manager handoff → asks **name + phone together** when the profile name is unavailable; real notification dispatched.
4. „გია მურღულია" → **past-event** answer on the first try, no „თქვენთვის თუ შვილისთვის?" / age first.
5. „ბანაკიმაინტერსებს" (typo / no-space camp intent) → camp flow, **no** generic two-option menu.

---

## ✅ P1 LIVE POLISH + DATE-BOMB CLEANUP + UNDER-AGE HANDOFF DISPATCH (2026-06-15/16)

**Production STILL NOT green** (Railway deploy blockers + Meta App Review open — unchanged). Three code sessions since the 2026-06-14 LIVE P0 HOTFIX, recorded here: (1) Live P0/P1 Hotfix (under-age handoff dispatch + past/unknown named events + wording/paragraphs), (2) Date-bomb / stale-event TEST cleanup, (3) P1 Live Polish (manager-handoff name+phone collection + named past-event first-turn routing).

**Latest GREEN code state (verified 2026-06-16):**
- `pytest tests/ -q` → **2374 passed, 0 failed, 28 skipped**
- corpus **9/9**; `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28/28** (M1–M6 hold)
- `python test_agent.py` → ✅ all checks pass
- `tools/scenario_runner_full.py --priority CRITICAL` → **22/22**
- `tools/scenario_runner_full.py --category transcript` → **3/3**
- **Prompt files unchanged** (combined SHA-256 `bde4109021e0140d1b54340a937e4fb1fb30c98242df60900b50d4069ee1a203`); **event data `data/admin_config/sections.yaml` unchanged** (`8cfe06c879b669d1b9dcf4219c4a69a8c2dac9b3a3c8c34001cf198f781645cb`); model `gpt-4.1-mini` unchanged; `LIVE_BROADCAST_ENABLED` default **False**. No Calendar internals / Sheets schema / broadcast / follow-up scheduler / Meta webhook / OpenAI model / `.env` change.

### Recent completed fixes (cumulative since 2026-06-14)
1. **Clear camp intent** continues the camp flow (no generic two-option menu).
2. **Typo / no-space camp intent** works (e.g. „ბანაკიმაინტერსებს").
3. **Specific ACTIVE named event** → direct answer (title / date / format-location / price / link), NO self/child target + age first, NO subscription CTA — `adult_llm_engine._maybe_handle_named_adult_event`.
4. **Past / unknown named events** no longer fall into the self/child target/age question first.
5. **Gia Murghulia is now PAST** → „… უკვე გაიმართა — 14 ივნისი 20:00" + active list; never „თქვენთვის თუ შვილისთვის?" first. Works in fresh ADULT context (adult engine) AND after camp / under-age context (PARENT interceptor `parent_flow._maybe_handle_event_inquiry` — new named-event firing condition + past branch + `_render_past_event_inquiry`).
6. **Under-age manager handoff actually dispatches** via the EXISTING `notification_service.notify_manager_handoff` (message-only).
7. Under-age handoff does **NOT** write Calendar / Sheets (message-only handoff).
8. On a **successful** dispatch the agent may say the info was sent („ინფორმაცია მენეჯერს გადავეცი…").
9. On a **failed** dispatch the agent must NOT claim success → fallback to the manager's direct contact when configured, else a retry message.
10. **Fallback manager contact exists: `558 67 47 33`** (`admin_config_service.get_manager_phone()`).
11. **Manager-handoff contact collection polished** (consultation-booking style, `parent_flow._maybe_handle_underage_manager_handoff`):
    - stored/profile name known → ask **phone only**;
    - name unknown → ask **name + phone together**;
    - phone-only, no name → ask name, **do NOT notify yet**;
    - name-only, no phone → ask phone, **do NOT notify yet**;
    - never say „სახელი და ნომერი გადავეცი" unless BOTH are actually present (success wording is the generic „ინფორმაცია მენეჯერს გადავეცი").
12. Long handoff / event answers **preserve paragraph breaks** (`parent_flow._format_handoff_paragraphs`; deterministic messages built multi-paragraph).
13. **„მოგიწოდებთ" sanitized** → „გთხოვთ" in BOTH the PARENT (`parent_llm_engine.FORBIDDEN_PHRASE_REPLACEMENTS`) and ADULT (`adult_llm_engine.ADULT_FORBIDDEN_PHRASE_REPLACEMENTS`) sanitizers.
14. **Date-bomb Gia tests/scenarios cleaned:** active-event direct-answer tests use a SYNTHETIC active fixture (a real event would just become the next date-bomb when it expires); Gia past behavior remains tested separately; SC-TX-03 U5 updated to the past-event wording; `test_live_qa_bug_fix` slot + `test_parent_reschedule_state_and_time` date assertions made clock-relative.

### Operator decisions / accepted deferred items
1. **Booked-age overwrite edge case — DEFERRED** by operator. Do NOT fix unless explicitly requested. Known risk: on a BOOKED lead, a direct first-child age correction („არა, 15") can overwrite the booked `child_age` — the B1 fallback (`parent_llm_engine.maybe_capture_child_age_fallback`) at the engine call site has no booked guard; the B5 guard only protects the requalify / second-child path. Unrealistic edge case; accepted as-is.
2. **Formula / fromula parsing fix — DEFERRED** by operator. Do NOT implement Formula 1 parsing — it will not be a real future event.
3. **Formula / fromula active test/demo event cleanup** may still be needed before real launch IF it remains active (currently the ONLY active adult event is „fromula 1", 28 აგვისტო, status active). Do NOT change event data unless explicitly requested.
4. **Production is NOT green.**
5. **Railway deploy blockers remain open** (below).

### Active known / pending items
**~~NEXT PLANNED TASK — Scheduling policy update (Saturday bookings)~~ → DONE (2026-06-16).** Saturday bookings are now allowed and Sunday stays closed; the Sunday-wording cleanup followed. See the top „✅ LATEST — SATURDAY SCHEDULING POLICY + P2 SUNDAY-WORDING CLEANUP" section for the implementation, file:line, and tests. The next planned task is now **Railway deploy blockers** (also listed in that top section).

**Railway deploy blockers (still open — audit only, NOT fixed):**
- `config._env` must read `os.environ` FIRST, `.env` fallback (Railway dashboard env vars currently invisible → boot crash).
- `REDIS_URL` Railway support (shares the `_env` bug).
- `requirements.txt` missing runtime deps: `redis`, `tzdata`, `python-multipart`.
- `.gitignore` / `.railwayignore` needed for `.env`, `credentials.json`, `*credentials*.json`, `secrets/`, `*.key`.
- single replica / one uvicorn worker / always-on (else duplicate APScheduler → duplicate follow-up DMs).
- `LIVE_BROADCAST_ENABLED=false` for staging.
- Meta App Review / permissions still open (real-customer comment/DM blocked with error #10).

**Production NOT green until:** deploy blockers fixed → Railway staging deployed → live smoke passes → Meta permissions / App Review addressed.

### Latest live-smoke observations + re-test checklist (after local restart)
- Under-age flow: 8yo correctly gets the ineligible message; the manager-handoff notification path exists; the latest polish requires name + phone together when the name is unavailable.
- Gia Murghulia: the 2nd try returned the correct past-event answer; the latest polish fixed the FIRST-turn named past event after camp context.
- **Re-test after local restart** (operator):
  1. „გამარჯობა ბანაკიმაინტერსებს" (typo / no-space camp intent)
  2. „8 წლის არის" → „დამაკავშირეთ მენეჯერთან" → name + phone together → real notification dispatched
  3. „ასევე მაინტერესებს გია მურღულიას ღონისძიება როდის არის?" → past-event answer on the FIRST try, no target/age
  4. Saturday consultation (scheduling task now DONE — see the top „✅ LATEST" section + its live-smoke list)

**Files changed across these three sessions** — product: `app/flows/parent_flow.py`, `app/agent/llm/adult_llm_engine.py`, `app/agent/llm/parent_llm_engine.py`, `app/services/notification_service.py` (new `notify_manager_handoff`), `app/services/admin_config_service.py` (new `find_events_by_reference(include_past=…)`). tests/scenarios/infra: `tests/conftest.py` (`_block_real_smtp` net), `tests/test_live_p0p1_hotfix_2026_06_15.py` (new), `tests/test_p1_live_polish_2026_06_16.py` (new), `tests/test_p0_live_hotfix.py`, `tests/test_live_qa_bug_fix.py`, `tests/test_parent_reschedule_state_and_time.py`, `tools/scenario_library.py` (SC-TX-03). **No prompt / event-data / `.env` change.**

---

## ✅ LIVE P0 HOTFIX — DONE (2026-06-14, code work = 2322 → 2334) — read this first

Two live-Messenger UX bugs, diagnosed-then-fixed (conditional-fix rule respected). New tests file [tests/test_p0_live_hotfix.py](tests/test_p0_live_hotfix.py) (**+12**). **Production is STILL NOT green.**

**Verified after the batch:** `pytest tests/ -q` → **2334 passed, 28 skipped, 0 failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28 passed, 0 failed (M1–M6 hold)** · `test_agent.py` ✅ · CRITICAL **22/22 on re-run** (single-run flakes confined to PARENT booking/slot/screen SC-11/12/13/19/46 → all pass on re-run; real-model stochasticity, NOT a regression) · transcript **SC-TX-01/02/03 → 3/3**. No Calendar/Sheets-schema/booking-internals/broadcast/email/`.env`/model/**prompt** change. Files changed this batch: **only** [app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py) (BUG 2 code) + [tests/test_p0_live_hotfix.py](tests/test_p0_live_hotfix.py) (tests). `system_adult_v1.md` confirmed **byte-identical** (SHA-256 unchanged).

- ✅ **BUG 1 — clear camp intent showed the generic menu in LIVE Messenger.** Root cause = **(d) STALE PROCESS / deploy gap — the code is already correct.** A full-path trace (Meta webhook → [message_buffer.py](app/services/message_buffer.py) `buffer_message` merges fragments with `" ".join` → [conversation_service.py](app/services/conversation_service.py) `_classify_segment` → [parent_flow.py](app/flows/parent_flow.py) `_has_explicit_georgian_camp_intent` → `_maybe_static_welcome`) proved the current code does **NOT** emit the menu for „გამარჯობა საზაფხულო ბანაკი მაინტერესებს" (classify=**PARENT**, detector=**True**, static welcome **yields**, full-path response = engine camp answer + age question, **not** the menu). **No code change was made** (conditional-fix rule). **⚠️ OPERATOR ACTION REQUIRED: restart/redeploy the live process** so it picks up the existing P0 fix (the live process was running pre-P0 code; `uvicorn --reload` was expected to auto-reload but didn't take effect). **Test gap that hid it:** existing ISSUE-1 tests were helper-level (call `_has_explicit_georgian_camp_intent` / `_maybe_static_welcome` directly) or engine-OFF (`test_issue1_legacy_routing_skips_menu_and_continues_camp`) or handle-level engine-ON — none ran the exact live string through the full `process_message` entry with the engine ON. **Now closed** by [tests/test_p0_live_hotfix.py](tests/test_p0_live_hotfix.py) full-path tests (process_message, engine ON): „გამარჯობა საზაფხულო ბანაკი მაინტერესებს" (with/without comma), bare „საზაფხულო ბანაკი მაინტერესებს", „…სიტყვის აკადემიის ბანაკით ვარ დაინტერესებული", „ბავშვების ბანაკი მაინტერესებს" → no menu + camp flow; bare „გამარჯობა" → menu still allowed.
- ✅ **BUG 2 — a NAMED specific event still asked self/child target + age first, and appended an unsolicited future-event subscription CTA.** Root cause (target/age) = **(a) MISSING LOGIC** — no deterministic „named event resolves → answer directly, skip target/age" branch existed; the ADULT prompt instructs asking the target first (the prompt-audit's AD-1/AD-4 ordering). Root cause (subscription CTA) = **(ii) PROMPT** — [system_adult_v1.md](app/agent/prompts/system_adult_v1.md) line ~91/93 „ფუტურული ღონისძიების შეტყობინებების წესი" emits „გსურთ, როცა ახალი ზრდასრულთა ღონისძიება დაემატება…"; it is NOT in code. **Fix (CODE ONLY, no prompt edit):** new deterministic branch in [app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py) — `_maybe_handle_named_adult_event` (≈:1809) / `_render_named_adult_event` (≈:1784) / `_has_specific_event_name` (≈:1754), wired into `run_adult_llm_turn` (≈:1968) **after the off-topic guard, before `_maybe_capture_adult_target`**. When a message names a specific event resolving to exactly one active event (`admin_config_service.find_active_events_by_reference`), it returns a deterministic answer (title / date-time / format-location / price / link + a soft „სხვა ღონისძიებებიც ჩამოგითვალოთ?") and **bypasses the LLM** → no target/age questions and the prompt's subscription CTA is never produced. **Safety:** `_maybe_capture_adult_target` untouched → FIX 3 (B4 self-revert) intact; PARENT FIX 4/5 untouched (different flow); the PARENT event interceptor is segment-separated. Unknown/ambiguous event → returns `None` → existing unknown-event fallback unchanged. A generic „რომელი ღონისძიება გაქვთ?" defers to the LLM (the `_has_specific_event_name` gate stops a description word like „რომელიც" from spuriously resolving). `_is_subscription_consent` not touched; the subscription CTA is still allowed when the user explicitly asks for future-event updates. **Both bugs confirmed FIXED in live testing by the operator** (named-event direct answer works; „fromula 1" also resolves from the active list).

**Data note (NOT a bug):** active event „fromula 1" (28 აგვისტო) is stored with a typo („fromula") and price 5000 GEL in [data/admin_config/sections.yaml](data/admin_config/sections.yaml); the agent displays it exactly as stored (correct behaviour). Fixing the spelling/price is an **operator decision in admin_config event data**, not an agent bug.

---

## ✅ P0 LIVE DEMO UX REGRESSION — DONE (2026-06-14, code work = 2287 → 2322)

The real-Messenger live-demo transcript issues (intent routing + answer formatting) are **FIXED** deterministically. New tests file [tests/test_p0_live_demo_ux_fixes.py](tests/test_p0_live_demo_ux_fixes.py) (**+35**). **Production is STILL NOT green.**

**Verified after the batch:** `pytest tests/ -q` → **2322 passed, 28 skipped, 0 failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28 passed, 0 failed (M1–M6 hold)** · `test_agent.py` ✅ · CRITICAL **22/22** (real OpenAI, Meta/Calendar/Sheets/Notification mocked) · new real-model transcript scenarios **SC-TX-01/02/03 → 3/3**. No Calendar/Sheets-schema/booking-internals/broadcast/email/`.env`/model change; the only prompt touch is ONE additive paragraph rule (no reorder). No prior fix reverted (FIX 3/4/5/M4 + M1–M6 all still hold — confirmed by property 28/0 and `test_redteam_b_selfcorrection_fixes.py` + `test_prestaging_redteam_fixes.py` 123 passed).

- ✅ **ISSUE 1 — clear camp intent skips the generic two-option menu.** „გამარჯობა, სიტყვის აკადემიის ბანაკით ვარ დაინტერესებული" / „საზაფხულო ბანაკი მაინტერესებს" / „ბავშვის ბანაკზე მინდა ინფორმაცია" now greet + continue the camp flow (ask the age) instead of re-asking „ბანაკი თუ ღონისძიება?". A bare greeting („გამარჯობა") or a bare topic word („ბანაკი") STILL shows the branded menu. [app/flows/parent_flow.py](app/flows/parent_flow.py) — new `_has_explicit_georgian_camp_intent` (camp keyword + interest/info/sign-up marker) + `_maybe_static_welcome` yields for it (alongside the existing English-intent yield).
- ✅ **ISSUE 2/3/6 — camp-price + price-objection paragraph formatting.** These answers are a SINGLE LLM BLOB (the engine composes them; audit #7). Live QA showed the real model returning them as ONE dense paragraph. Enforced by a DETERMINISTIC post-processor on the REAL output — NOT a mock: [app/flows/parent_flow.py](app/flows/parent_flow.py) `_format_multipoint_paragraphs` (whitespace only — splits a dense multi-point price/value answer into paragraphs at sentence boundaries; never alters a fact/token; narrow gate: no existing „\n\n" + ≥2 value-point groups + ≥3 sentences). Plus ONE additive paragraph rule in [app/agent/prompts/system_parent_v2.md](app/agent/prompts/system_parent_v2.md) (paragraph guidance + „always state the price number" — **no reorder**, see the do-not note below). Validated end-to-end with the real model via SC-TX-02.
- ✅ **ISSUE 4 — „ღონისძიების ფასი" after camp context never returns the camp price.** [app/flows/parent_flow.py](app/flows/parent_flow.py) `_maybe_handle_event_inquiry` — a pre-engine interceptor; an explicit event-PRICE / event-DATE question (or established event context) routes to event resolution instead of the camp price. Fires only on (A) „ღონისძიებ" + price/date, or (B) the bot just listed events — a bare „ღონისძიება მაინტერესებს" still reaches the engine's `switch_to_adult_flow` (never preempts the segment switch). Does NOT fire when the camp is named (no hijack of „ბანაკში რა ღონისძიებებია?").
- ✅ **ISSUE 5 — unknown date / title / guest → searched against the active list; never invented.** [app/services/admin_config_service.py](app/services/admin_config_service.py) — new `find_active_events_by_reference` (lenient stem-aware search across title/description/guest/theme/location/tags; „#" stripped so a hashtag alias matches), `find_active_events_on_day` (date search), `_event_query_tokens` (drops generic event vocabulary + question scaffolding), `_event_search_haystack`. Found → answer FROM event data (title/date/location/price/short description/link); date-miss → „{N} რიცხვში აქტიურ ღონისძიებას სიაში ვერ ვპოულობ" + active list; name-miss → „ამ სახელით … ვერ ვპოულობ" + active list + „ბმული/screenshot გამომიგზავნოთ და მენეჯერთან გადავამოწმებთ"; ambiguous → „რომელი ღონისძიება?" + list.

**Active event data (read-only audit — record for the next session):**
- Active events are **„აღზრდა … შეხვედრა გია მურღულიასთან" (14 ივნისი, price 29)** and **„fromula 1" (28 აგვისტო)** in [data/admin_config/sections.yaml](data/admin_config/sections.yaml).
- **CORRECTION to the earlier handoff assumption:** „გია მურღულია" IS present in the active data (title + description + tag `#გიამურღულიასთან`) — so „გია მურღულია იქნებოდა" is answered FROM event data, NOT invented.
- „გალაკტიონის საღამო" is **ABSENT** → lists active events + manager-verify.
- No active event on the **16th** (events are 14th & 28th) → „no active event on the 16th" + list.

**⚠️ Do-not note (do not lose):** the camp-price **reorder** prompt instruction (price placed last) was tried and **REVERTED** — it caused the real model to occasionally OMIT the price number (SC-26 CRITICAL regression). Only „always state the price number" + paragraph guidance was kept. **Do NOT re-introduce a price-reorder prompt instruction.** Paragraph formatting is owned by the deterministic `_format_multipoint_paragraphs` post-processor, not by reordering the model.

**Tests:** new file [tests/test_p0_live_demo_ux_fixes.py](tests/test_p0_live_demo_ux_fixes.py) (+35). Existing tests updated to the new ISSUE-1 contract: [tests/test_parent_llm_engine.py](tests/test_parent_llm_engine.py) (2 static-welcome tests inverted), [tests/test_parent_flow_analyzer_integration.py](tests/test_parent_flow_analyzer_integration.py) (turn-1 message), [test_agent.py](test_agent.py) (TEST 1 turn-1 + `test_single_message_explicit_camp`), and [tools/scenario_library.py](tools/scenario_library.py) **SC-02** (its assertion encoded the pre-fix „menu fires for clear camp intent" behaviour). New real-model transcript scenarios **SC-TX-01/02/03** (category `transcript`, priority **NORMAL** so CRITICAL stays exactly **22**); `tools/scenario_runner_full.py` gained the `transcript` `--category` choice.

---

## ✅ RED-TEAM B SELF-CORRECTION BATCH — DONE (2026-06-13, code work = 2222 → 2287) — read this first

The deterministic self-correction findings from [docs/REDTEAM_CONVERSATIONS.md](docs/REDTEAM_CONVERSATIONS.md) (B-group) plus the M1 metamorphic divergence are **FIXED**, ONE at a time with a full-`pytest` gate after each (never below the 2222 baseline). New tests file [tests/test_redteam_b_selfcorrection_fixes.py](tests/test_redteam_b_selfcorrection_fixes.py) (**+65**). **Production is STILL NOT green.**

**Verified after the batch:** `pytest tests/ -q` → **2287 passed, 28 skipped, 0 failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **28 passed, 0 failed (M1 now passes; M2–M6 hold)** · `test_agent.py` ✅ · CRITICAL **22/22** (real OpenAI, Meta/Calendar/Sheets/Notification mocked). No Calendar/Sheets-schema/booking-internals/broadcast/email/model/prompt/`.env` change. No fix reverted.

- ✅ **B5 — multi-child collision** ([app/flows/parent_flow.py](app/flows/parent_flow.py) `_maybe_requalify_child`): a booked child's age is no longer overwritten by „ჩემი მეორე შვილი 14 წლისაა". When `_lead_has_active_booking(lead)` is true, the requalify guard keeps the booked child's `child_age`/booking ISO/event_id/name/phone intact and returns a deterministic „second child → manager" handoff message (constant `_BOOKED_SECOND_CHILD_MANAGER`) — no clear, no booking, no Calendar/Sheets write. Non-booked requalify behaviour unchanged.
- ✅ **B2 — name correction** ([app/flows/parent_flow.py](app/flows/parent_flow.py) `_parse_name_phone` / `_name_token_is_valid`): „არა, ნინო მქვია" → „ნინო" (was „არა ნინო"). `_name_token_is_valid` now also rejects `NAME_REFUSAL_KEYWORDS`; a leading/mid „არა" is a correction-cut (`_NAME_CORRECTION_MARKERS = {"არა"}`) that discards the mis-stated name before it („ლიზი… არა ნინო" → „ნინო"). Bare „არა" stays a refusal; real names („ბარბარა"/„ანა") are token-matched so the „არა" substring never corrupts them.
- ✅ **B4 — adult target self-revert** ([app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py) `_maybe_capture_adult_target`): after „შვილისთვის", a later „ჩემთვის"/„მე მინდა"/„მე მაინტერესებს"/„ჩემთან" now reverts `adult_target_relation`/`adult_target_age` to self — but only when the message has NO relative cue, so „ჩემი შვილისთვის"/„ჩემ შვილს"/„ბავშვს" still mean the child (M4 holds). Never touches `child_age`/`adult_age`.
- ✅ **M1 — spelled-out Georgian numerals** ([app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) `maybe_capture_child_age_fallback`): camp-band cardinals (`ცხრა=9, ათი=10, თერთმეტი=11, თორმეტი=12, ცამეტი=13, თოთხმეტი=14, თხუთმეტი=15, თექვსმეტი=16, ჩვიდმეტი=17`) are read WITH age context. „ცამეტი წლის" → 13; „ცამეტი" alone / „ცამეტი ბილეთი" → not captured; „9-17" still not captured; digit parsing unchanged.
- ✅ **B1 — age self-correction (deterministic)** ([app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) `maybe_capture_child_age_fallback`): an explicit correction marker (`არა`, `შევცვალე`, `უფრო სწორად`, `ვგულისხმობდი`, `აბა`) lets a correction UPDATE an already-set `child_age` („13 → არა, 15 → აბა 9 წლის" works). „აბა" only overwrites alongside an age word (it is too common a filler to relax the bare-number gate); the STRONG markers (no „აბა") also relax the bare-number gate so „არა, 15" updates the age. A SECOND/different-child mention is NOT a correction (`მეორე შვილ`/`სხვა შვილ` excluded), so „10 და 14 წლის" and „ჩემი მეორე შვილი 14 წლისაა" keep their existing behaviour; the documented fresh-lead „keep first valid age" (`test_age_fallback_two_children_keeps_first_valid`) is unaffected (it never hits the already-set path).

---

## ✅ P0 — LIVE DEMO UX REGRESSION (intent routing + answer formatting) — RESOLVED 2026-06-14

Real Messenger live-demo transcript review (operator clarification). The real issues were routing + formatting, NOT a hallucination. **RESOLVED 2026-06-14** (see the „✅ P0 LIVE DEMO UX REGRESSION — DONE" section at the top). All four points fixed deterministically (+35 tests, 2287 → 2322; CRITICAL 22/22; transcript 3/3):

- ✅ **A. Clear camp intent skips generic disambiguation** → `parent_flow._has_explicit_georgian_camp_intent` + `_maybe_static_welcome` yield.
- ✅ **B. „ღონისძიების ფასი" after camp context never answers the camp price** → `parent_flow._maybe_handle_event_inquiry` pre-engine interceptor.
- ✅ **C. Unknown date/title/guest → searched against the active list; found = answer from event data, miss = „not in active list" + list + manager-verify; never invents** → `admin_config_service.find_active_events_by_reference` / `find_active_events_on_day` / `_event_query_tokens` / `_event_search_haystack`.
- ✅ **D. Multi-part answers use paragraph breaks** → deterministic `parent_flow._format_multipoint_paragraphs` (real output, not a mock) + additive paragraph rule in `system_parent_v2.md` (no reorder — see the do-not note above). **Read-only audit correction:** „გია მურღულია" IS in the active data — answered from event data, not invented.

---

## ⏳ RAILWAY DEPLOY BLOCKERS (from the Deploy-Readiness Audit, 2026-06-13) — audit only, NOT fixed

App boots + tests green locally, but **as-is it will NOT work on Railway**. Confirmed-OK: `Procfile` exists and is correct (`web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`); app object `app.main:app`; `$PORT` supported via the Procfile; APScheduler auto-starts on FastAPI startup ([app/main.py](app/main.py) `@app.on_event("startup")`) so **follow-ups run inside the web process — no separate worker needed**, but Railway must run a **single replica / one uvicorn worker** (else duplicate schedulers → duplicate follow-up DMs) and the service must be **always-on** (no scale-to-zero).

**MUST-fix before deploy:**
1. **`config._env` reads the `.env` FILE ONLY** ([app/config.py](app/config.py) line 14/31-33: `ENV_VALUES = dotenv_values(.env)`) — Railway dashboard env vars (in `os.environ`) are **invisible**, and `settings = get_settings()` raises `ConfigurationError` on the 7 required vars at import → **the app crashes on boot**. Fix: make `_env` read `os.environ` first, then the `.env` file as fallback. (Only `GOOGLE_CREDENTIALS_JSON` already reads `os.environ`, via the Google-creds helper.)
2. **`REDIS_URL` is `.env`-only too** (same root) → Redis invisible on Railway → in-memory mode → state lost on every restart. Fixed by #1.
3. **`requirements.txt` missing runtime deps:** `redis` (else `import redis` fails → no persistence), `tzdata` (else `ZoneInfo("Asia/Tbilisi")` can crash on a slim image at import), `python-multipart` (else Admin Panel form POSTs fail). Loose/unpinned versions = breaking-update risk; pin before deploy.
4. **No `.gitignore` / `.railwayignore`** — `.env` (secrets) and `credentials.json` (service-account key) are both in the working tree. Add an ignore file excluding `.env`, `credentials.json`, `*credentials*.json`, `secrets/`, `*.key` BEFORE any `git init` / `railway up`.
5. **Set the Railway env vars** (client values): the 7 required (`OPENAI_API_KEY`, `GOOGLE_SHEET_ID`, `GOOGLE_CALENDAR_ID`, `META_PAGE_ID`, `INSTAGRAM_ACCOUNT_ID`, `MESSENGER_PAGE_ACCESS_TOKEN`, `MESSENGER_VERIFY_TOKEN`) + `GOOGLE_CREDENTIALS_JSON`, `META_APP_SECRET`/`INSTAGRAM_APP_SECRET`/`INSTAGRAM_ACCESS_TOKEN`, SMTP/`MANAGER_EMAIL`, `REDIS_URL`, `USE_PARENT_LLM_ENGINE=true`. Keep `LIVE_BROADCAST_ENABLED=false` for staging.

---

## ⏳ META APP REVIEW — HARD BLOCKER for real customers (still open)

Comment/DM automation currently works **ONLY for app role-holders (testers/admins/developers)**. A **real customer** (not added to the app) is blocked by Meta with **error #10** (permission) until the app passes App Review for `pages_messaging` / `pages_manage_metadata` / `pages_read_engagement` / `instagram_manage_messages` / `instagram_manage_comments` AND is switched from Development to **Live**. This is independent of the existing `ENABLE_PUBLIC_COMMENT_REPLY` / `pages_manage_engagement` note (which is only about PUBLIC comment replies). **Do NOT claim real-customer comment/DM works until App Review passes and the app is Live.** Requires Business Verification first (SLA can be 5+ business days).

---

## ⏳ OPEN QUESTION — B5 × B1 on a booked lead (decision needed, not yet resolved)

On a **booked** lead, a **direct first-child age correction** („არა, 15" — a self-correction, NOT a second child) may take the **B1** age-self-correction path ([parent_llm_engine.maybe_capture_child_age_fallback](app/agent/llm/parent_llm_engine.py)) and **silently overwrite a booked `child_age`** with no manager handoff — whereas the **B5** guard ([parent_flow._maybe_requalify_child](app/flows/parent_flow.py) `_lead_has_active_booking`) only protects the *re-qualify / second-child* path, not the B1 fallback. **UNVERIFIED** whether the booked/DONE state short-circuits the age fallback first (the engine's booked-state guards may already block it). **Decision needed** next session: confirm whether a booked lead's age can be silently corrected, and if so, add a booked-lead guard to the B1 fallback (manager-handoff instead of silent overwrite). Do NOT assume it is safe. (Scheduled to be probed in the upcoming full test sweep.)

---

## ⏳ OPEN — Prompt-audit findings + observed polish (not yet adopted)

From the read-only Prompt Engineering Audit (2026-06-14, audit-only; real prompts byte-identical, scratch deleted) and live observation. None applied yet — each is a separate, gated decision:

- **SL-1 (P1, ADOPT recommended) — CRM summary can echo unverified event facts.** [app/agent/prompts/summary.md](app/agent/prompts/summary.md) has „don't invent facts" but no rule against echoing an unverified event NAME / DATE / PRICE from the user's messages into the permanent manager CRM summary. **Proven in scratch A/B**: variant A wrote „გალაკტიონის საღამო"+„16 რიცხვი" into the summary; variant B (with a one-line guard) did not. Surgical add to summary.md, no logic change.
- **AD-2 (P1) — ADULT manager-callback CTA over-repetition.** [app/agent/prompts/system_adult_v1.md](app/agent/prompts/system_adult_v1.md) repeats „თუ გსურთ, დაგაკავშირებთ მენეჯერთან" verbatim 6+ times across scenarios → robotic in multi-scenario chats. Add tonal variants (prompt task).
- **AD-1 (REVISE before adopting) — ADULT unknown_event „ან აჩვენე აქტიური ღონისძიებები" is optional.** Should list active events; but the single-turn A/B was inconclusive because the adult flow asks the self/child target before it can age-filter+list — rework to „list after target known / offer to list", then re-A/B.
- **system_parent_v2.md bloat/redundancy (P1, dedicated task).** 451 lines of date-tagged „CRITICAL" rules; booking-flow / contact-collection / CTA / forbidden-phrase blocks overlap and much duplicates the deterministic layer. Consolidate carefully in its own gated task (regression-prone) — NOT piecemeal.
- **Lost-in-the-middle of system_parent_v2.md (451 lines) not yet probed** — a rule buried mid-prompt may be under-weighted by the model; needs a focused probe.
- **P1 polish (observed live) — vague event mention deflects to manager instead of checking the active list.** „მოწვეული სტუმრები გყავთ?" / „პოსტში ღონისძიება ვნახე" → the agent hands off to a manager rather than checking the active event list first.

**Determinism-consistency conclusion (audit):** the LIVE prompts have **NO active conflicts** with the deterministic layer; the price number is protected; **no price-reorder instruction is present** (the reverted SC-26 regression is correctly absent — do NOT re-introduce one).

---

## ⏳ Recommended next steps (ranked)

**MUST before Railway deploy:** (1) fix `config._env` so `os.environ` wins over the `.env` fallback; (2) add `redis`, `tzdata`, `python-multipart` to `requirements.txt`; (3) add `.gitignore`/`.railwayignore` for `.env` + `credentials.json`; (4) set Railway env vars; (5) single replica / one uvicorn worker; (6) keep `LIVE_BROADCAST_ENABLED=false` for staging; (7) run full gates.

**✅ DONE — P0 LIVE DEMO UX REGRESSION (chaotic-UX retest):** all four points fixed deterministically (2026-06-14, 2287 → 2322; CRITICAL 22/22; transcript 3/3). See the „✅ P0 LIVE DEMO UX REGRESSION — DONE" section at the top.

**MUST before real-customer launch:** (1) Meta App Review + switch app to Live (else error #10 for non-testers — see the META APP REVIEW section above); (2) Railway deploy blockers (above).

**SHOULD before production:** (1) re-run the conversation-level red-team; (2) re-run comment/follow-up smoke; (3) add Sentry if desired; (4) decide Admin Panel persistence strategy (writes are ephemeral on Railway); (5) regenerate/confirm the Meta token before final Railway deploy.

**CAN defer:** WhatsApp live integration; unused-deps cleanup (`twilio`/`pyairtable`); `requirements-dev` split; FastAPI lifespan modernization; broader LLM wording polish after the core routing fixes.

**⚠️ Important warnings:** Production is **NOT green** — do not mark it green in docs. Do not claim Railway deploy-ready until the env/config/dependency blockers are closed and a staging smoke passes. Do not claim real-customer comment/DM works until Meta App Review passes and the app is switched to Live (error #10 for non-testers). Do NOT re-introduce a camp-price reorder prompt instruction (it caused the SC-26 price-omission regression — see the do-not note in the P0 section). The live demo is local (`uvicorn --reload`) — editing `.py` files *may* auto-reload it, **but the LIVE P0 HOTFIX (BUG 1) proved the live process can run STALE code** — always verify a restart actually took effect after a fix. **CRITICAL is 22/22 on re-run, not always on a single first run** — the PARENT booking/slot/screen scenarios (SC-11/12/13/19/46) flake under real-model stochasticity; that is NOT a regression, do not treat a single-run miss as one.

---

## ✅ RAILWAY-SAFE GOOGLE CREDENTIALS — DONE (2026-06-13)

Google Sheets + Google Calendar can now initialise from a single Railway env var instead of a local `credentials.json` file path. **Production is STILL NOT green.**

**Verified:** `pytest tests/ -q` → **2222 passed, 7 skipped, 0 failed** (2209 + **13** new in [tests/test_google_credentials_railway.py](tests/test_google_credentials_railway.py)). No real credentials read (all mocked), no network. No change to Calendar booking logic, Sheets schema/row strategy, email SMTP, Meta webhook, broadcast, OpenAI model, prompts, or the follow-up scheduler.

**What changed:**
- New shared resolver [app/services/google_credentials.py](app/services/google_credentials.py) → `load_google_credentials(scopes, *, file_value="")`. Resolution priority: (1) **`GOOGLE_CREDENTIALS_JSON`** read straight from `os.environ` (Railway-safe — Railway has no `.env` file, so this can't go through the `.env`-only `config._env`) → `json.loads` + `private_key` escaped-`\n` repair → `service_account.Credentials.from_service_account_info(info, scopes=...)`; (2) per-service `file_value` (`GOOGLE_SHEETS_CREDENTIALS_JSON` / `GOOGLE_CALENDAR_CREDENTIALS_JSON` — inline JSON OR file path); (3) **`GOOGLE_APPLICATION_CREDENTIALS`** file path → `from_service_account_file(path, scopes=...)`; (4) nothing → a clear, **secret-free** `RuntimeError`. **`GOOGLE_CREDENTIALS_JSON` wins** when both are set.
- [app/services/sheets_service.py](app/services/sheets_service.py): the 3 worksheet helpers (`_worksheet` / `_comments_worksheet` / `_event_subscribers_worksheet`) now share `_sheets_client()` → `gspread.authorize(load_google_credentials(SHEETS_SCOPES, file_value=settings.GOOGLE_SHEETS_CREDENTIALS_JSON))`. The duplicated `_load_credentials_info` was removed.
- [app/services/calendar_service.py](app/services/calendar_service.py): `_calendar_service()` → `build("calendar","v3", credentials=load_google_credentials([CALENDAR_SCOPE], file_value=settings.GOOGLE_CALENDAR_CREDENTIALS_JSON))`. Its duplicated `_load_credentials_info` (and the now-unused `json`/`Path`/`service_account` imports) were removed.
- New [runtime.txt](runtime.txt) = `python-3.11` (Railway build pin; does not affect local dev).
- **Never logs credential contents**; the "not configured" error contains no `private_key` / `client_email` / token.

**Railway env (operator):**
```
GOOGLE_CREDENTIALS_JSON=<full service-account JSON>     # paste the whole JSON; wins if both set
```
Local fallback stays:
```
GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json
# (or the existing per-service GOOGLE_SHEETS_CREDENTIALS_JSON / GOOGLE_CALENDAR_CREDENTIALS_JSON)
```
⚠️ Do NOT commit `credentials.json`; do NOT log credentials. `GOOGLE_CREDENTIALS_JSON` wins over the file path.

---

## ✅ PRE-STAGING FIX BATCH — DONE (2026-06-12, code work = 2151 → 2209) — read this first

The four cheap deterministic findings from the full-system red-team audit are **FIXED**, ONE at a time with a full-`pytest` + corpus gate after each (never below the 2151/9 baseline). New tests file [tests/test_prestaging_redteam_fixes.py](tests/test_prestaging_redteam_fixes.py) (**+58**). **Production is STILL NOT green.**

**Verified after the batch:** `pytest tests/ -q` → **2209 passed, 7 skipped, 0 failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **7/7** · `pytest -k comment` **196/0** · `pytest -k follow` **186/0** · `test_agent.py` ✅ · CRITICAL **22/22** (real OpenAI, Meta/Calendar/Sheets/Notification mocked). Model `gpt-4.1-mini` (unchanged). **No real broadcast sent.** No change to Calendar internals, Sheets schema/row-strategy, adult subscription/broadcast SENDING, email, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED` (still `False`). No hardcoded sender_id / profile names.

- ✅ **FIX 1 — A-1/A-2** ([app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py)): replaced the word-order-locked `_NOTIFICATION_DELIVERY_QUESTION_PATTERNS` substring list with a morphology / word-order tolerant **stem-group detector** — a delivery question is `(სად/როგორ + subject-or-arrival)` OR `(channel + arrival)` OR `(standalone „აქ" + write/arrival + „?")`. Added „შეტყობინ"/„შემატყობ" to `_ADULT_IN_SCOPE_STEMS` AND taught `_maybe_adult_offtopic_reply` to return `None` for a delivery question, so the FORBIDDEN „ამ კითხვაზე ვერ დაგეხმარებით" redirect can never fire on one. **All 10 Section-A variants now answer platform-aware (Messenger/Instagram/WhatsApp); none redirects; never re-subscribes; never reaches the LLM.** Stays narrow — price („ფასი რა არის?"), location („სად ტარდება?"), and subscription-consent („კი გამომიგზავნეთ", „შემატყობინეთ") are NOT intercepted.
- ✅ **FIX 2 — B-1** ([app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py)): added the DATIVE needles „შვილს"/„ბავშვს" to `_ADULT_RELATIVE_PATTERNS` (they are not substrings of the genitive „შვილის"/„ბავშვის" needles, so they never shadow them). „ჩემ შვილს უნდა" / „ბავშვს უნდა" now capture the relation deterministically and reuse a known `child_age` → `adult_target_age`; min_age filtering unchanged (age 12 → no 13+ events; unknown age → asks).
- ✅ **FIX 3 — F-D4** ([app/flows/parent_flow.py](app/flows/parent_flow.py)): broadened `_CONTACT_REQUEST_MARKERS` (`ნომერ`, `ტელეფონ`, `კონტაქტ`, `დაგიკავშირდეთ`, `როგორ დაგიკავშირ`) so a bare valid 9-digit phone is captured even when the bot's contact-ask used non-brand wording („მომწერეთ ნომერი" / „როგორ დაგიკავშირდეთ?"). The optative `-ეთ` question form is matched but the future `-ებათ` confirmation („მენეჯერი დაგიკავშირდებათ") is NOT, so a booking confirmation never arms the capture; the `in_contact_ctx` gate + phone-required trigger keep stray numbers out (no-context bare phone → still `None`).
- ✅ **FIX 4 — F-D6** ([app/flows/parent_flow.py](app/flows/parent_flow.py)): `_maybe_request_full_contact_on_intent` now parses + saves an inline phone (and a validly-disclosed name) BEFORE composing the ask, so „კი მინდა კონსულტაცია 595999733" never re-asks the phone — it asks only for the name (or proceeds to date/time when the name is known). Intent detection broadened for word-separated „მინდა … კონსულტაცია" (with a negation guard so „კონსულტაცია არ მინდა" is excluded), „დამირეკეთ", and „მინდა ჩაწერა"; „დარეკ"/„დამირეკ" added to `_NAME_REJECT_STEMS` so „დამირეკეთ" is never stored as a name. Two distinct inline numbers → „ორი ნომერი მომწერეთ…". Eligibility gate preserved (unknown/ineligible age still defers to qualification).

### ⏳ STILL OPEN (carried)
- ⏳ **Deferred (unchanged):** F-D3 (Latin-script name dropped), F-D7/M3/M4 (half-hour „5 საათსა და ნახევარზე"→17:00 / evening „საღამოს 11"→23:00), ROOT 4 multi-child („10 და 14"→only 10 — update `test_age_fallback_two_children_keeps_first_valid` FIRST), WhatsApp wording.
- ⏳ **NEEDS LIVE SMOKE:** comment webhook + DM send (real Meta), follow-up live tick, specific-post → event mapping, Meta token regenerate, WhatsApp. (Delivery-question LLM fallthrough is now moot — all 10 are deterministic.)
- ⏳ **Operator Priority 0:** regenerate the Meta access token (leaked once in a terminal log — code does NOT log tokens); deactivate the test adult events `formula_1` (price 4999) + `summer_fest` via Admin Panel; Google creds Railway-safe (env/base64); Railway env sync; STAGING deploy first; Railway smoke; Meta App Review. **Do NOT mark production green.**

---

## ▶ SESSION HANDOFF (2026-06-12) — Full-System Audit + NEXT = Pre-Staging Fix — read this first

**Verified baseline (current, no code changed since the batch fix):** `pytest tests/ -q` → **2151 passed, 7 skipped (audit-only property), 0 failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **7/7 (P1–P7 pass)** · `test_agent.py` ✅ · CRITICAL **22/22** (last run) · `pytest -k comment` **196/0**, `pytest -k follow` **186/0**. **Production is NOT green.** Model `gpt-4.1-mini`. Broadcasts DRY-RUN.

**Full-system red-team audit ([docs/REDTEAM_FULL_SYSTEM_AUDIT.md](docs/REDTEAM_FULL_SYSTEM_AUDIT.md)) — audit-only, NO code changed:**
- **0 BLOCKER · 8 DEGRADED · 2 active MINOR · 6 NEEDS LIVE SMOKE · 2 OPERATOR DATA CLEANUP.**
- **GREEN confirmed offline:** comment routing (196 tests; `comment_service` never parses contact → a phone in a comment does NOT corrupt name/contact; dedupe `processed_comment` guard + segment routing present); follow-up (186 tests; `_BLOCKED_REASONS` = booked/registered/declined/asked_no_more/handoff/exhausted + non-parent skip + `lead.calendly_booked` double-check); CRM hygiene (garbage names rejected, challenge clean, `to_sheet_row` clean); cross-user/platform isolation (`conversation:{platform}:{sender_id}`); `LIVE_BROADCAST_ENABLED=False`; **NO token/secret value in logs** (the terminal leak was one-off — the code does not log tokens); the adult-event date filter correctly hides the past `მასტერკლასი` (9 ივნისი).
- **Highest-risk area:** the adult subscription **delivery-question handler** — deterministically emits the *forbidden* „ამ კითხვაზე ვერ დაგეხმარებით" redirect for „შეტყობინება სად მომივა?" and covers only 3/10 realistic phrasings (FIX 1 below).

**NEXT TASK — PRE-STAGING FIX (4 cheap deterministic; per-bug pytest + corpus gate after each, must stay ≥2151 / 9):**
- **FIX 1 (A-1/A-2)** — `adult_llm_engine._maybe_handle_notification_delivery_question` is exact-substring/word-order bound (3/10 variants); „შეტყობინება სად მომივა?" (reversed order) misses → off-topic guard emits the banned „ამ კითხვაზე ვერ დაგეხმარებით". Broaden the patterns (loose „შეტყობინ"+„სად/როგორ/აქ/მესენჯერ/მეილ"/„ვნახავ/მოვა/გავიგებ") and/or add „შეტყობინ"/„შემატყობ" to `_ADULT_IN_SCOPE_STEMS` so a delivery question is never redirected. Failing variants: „შეტყობინება სად მომივა?", „ლინკებზე სად მოდის შეტყობინება?", „აქ მომწერთ?", „მეილზე მოდის თუ აქ?", „სად ვნახავ შეტყობინებას?", „შეტყობინება სად მოვა?", „…სად გავიგებ?".
- **FIX 2 (B-1)** — `adult_llm_engine._ADULT_RELATIVE_PATTERNS` is genitive-only (`შვილისთვის`/`შვილის`/`ბავშვისთვის`); dative „ჩემ შვილს უნდა" / „ბავშვს უნდა" (შვილს/ბავშვს) is NOT captured → adult-for-child becomes LLM-lucky (the live „inconsistent on one account"). Add `შვილს` / `ბავშვს` to the patterns. Keep `child_age` reuse + min_age filtering intact (verified working for genitive).
- **FIX 3 (F-D4)** — `parent_flow._CONTACT_REQUEST_MARKERS` only arms the bare-phone capture on „9-ნიშნა"/„საკონტაქტო ნომერ"; if the bot asks for contact with other wording (no `pending_booking`), a bare „595999733" loops to the LLM. Broaden markers (e.g. „ნომერ" + a request verb) or arm on any bare valid Georgian phone in a contact/booking state.
- **FIX 4 (F-D6)** — `parent_flow._maybe_request_full_contact_on_intent` (explicit „კი მინდა კონსულტაცია 595999733") asks for the phone the user just gave. Parse + save the inline phone before composing the ask.

**DEFER (do NOT do in the pre-staging batch):** F-D3 (Latin name dropped), F-D7/M3/M4 (half-hour „5 საათსა და ნახევარზე"→17:00 / evening „საღამოს 11"→23:00), ROOT 4 multi-child („10 და 14"→only 10 — needs the existing `test_age_fallback_two_children_keeps_first_valid` updated FIRST), WhatsApp wording.

**NEEDS LIVE SMOKE (6 — cannot prove offline):** delivery-question LLM answers (deterministic after FIX 1), comment webhook + DM send (real Meta), follow-up live tick (24h cadence), specific-post → event mapping (real Meta), Meta token regenerate, WhatsApp.

**OPERATOR / DEPLOY PREP (Priority 0 — do before any live test):** ⚠️ **regenerate the Meta access token** (leaked once in a terminal error log); **deactivate the test adult events** `formula_1` (price 4999) + `summer_fest` (and `ჯონი` if it reappears) via Admin Panel — do NOT auto-delete; **Google credentials Railway-safe** (env var / base64, not a file path — Railway has no persistent filesystem); Railway env sync; **STAGING deploy first** (a test Page, NOT the client live Page); Railway smoke test; Meta App Review (privacy-policy URL + demo recording).

### ⏭️ Next Claude Code prompt (ready to paste) — PRE-STAGING FIX (4 deterministic)
```
Read HANDOFF.md, CLAUDE.md, REVIEW_PACK.md first.

PRE-STAGING FIX — 4 cheap deterministic fixes from the full-system audit
(docs/REDTEAM_FULL_SYSTEM_AUDIT.md). Production NOT green.

Baseline: pytest 2151 passed, 7 skipped, 0 failed · corpus 9/9 ·
RUN_PROPERTY_TESTS=1 property 7/7 · CRITICAL 22/22 · gpt-4.1-mini.

CRITICAL RULE: fix ONE at a time. After each:
  python -m pytest tests/ -q
  python -m pytest tests/corpus/ -q
If pytest < 2151, corpus < 9, OR any existing test breaks → STOP and
report which fix caused it. Do NOT continue.

Do NOT touch: Calendar internals, Sheets schema/row strategy, adult
subscription/broadcast sending, email, OpenAI model, Railway, prompts,
LIVE_BROADCAST_ENABLED. No hardcoded sender_id / profile names.

FIX 1 (A-1/A-2) — adult delivery question. adult_llm_engine.
_maybe_handle_notification_delivery_question is word-order/exact bound
(only 3/10 variants); „შეტყობინება სად მომივა?" misses → off-topic guard
emits the FORBIDDEN „ამ კითხვაზე ვერ დაგეხმარებით". Broaden the patterns
AND/OR add „შეტყობინ"/„შემატყობ" to _ADULT_IN_SCOPE_STEMS so a delivery
question is NEVER redirected off-topic. Must still answer platform-aware
(Messenger / Instagram / WhatsApp), never re-subscribe, never reach LLM.
Cover: „შეტყობინება სად მომივა?", „სად ვნახავ შეტყობინებას?", „შეტყობინება
სად მოვა?", „აქ მომწერთ?", „მეილზე მოდის თუ აქ?", „ლინკებზე სად მოდის
შეტყობინება?", „…სად გავიგებ?".  [gate]

FIX 2 (B-1) — dative child relation. adult_llm_engine._ADULT_RELATIVE_
PATTERNS is genitive-only; add „შვილს" / „ბავშვს" so „ჩემ შვილს უნდა" /
„ბავშვს უნდა" capture relation (+ reuse known child_age). Keep child_age
NEVER overwritten and min_age filtering intact.  [gate]

FIX 3 (F-D4) — bare-phone capture marker dependence. parent_flow.
_CONTACT_REQUEST_MARKERS only arms on „9-ნიშნა"/„საკონტაქტო ნომერ".
Broaden so a bare valid 9-digit phone is captured during contact
collection regardless of the exact ask wording (keep single-phone happy
path ჯონი/ლიზი 595999733 — corpus CONV 1/6 — and the in_contact_ctx gate
so unrelated digit messages aren't hijacked).  [gate]

FIX 4 (F-D6) — explicit intent + inline phone. parent_flow.
_maybe_request_full_contact_on_intent („კი მინდა კონსულტაცია 595999733")
must parse + save the inline phone before asking, then ask only for the
still-missing field.  [gate]

DEFER: F-D3 Latin name, F-D7/M3/M4 half-hour/evening time, ROOT 4
multi-child (needs test_age_fallback_two_children_keeps_first_valid
updated first), WhatsApp wording.

After all 4: python -m pytest tests/ -q ; python -m pytest tests/corpus/ -q ;
RUN_PROPERTY_TESTS=1 python -m pytest tests/property/ -q ; python test_agent.py ;
python tools/scenario_runner_full.py --priority CRITICAL
Expected: 2151+ passed / 7 skipped / 0 failed · corpus 9/9 · property 7/7 ·
CRITICAL 22/22. Add tests for each fix. Update HANDOFF/CLAUDE/REVIEW_PACK.
Do NOT mark production green.
```

---

## ▶ SESSION HANDOFF (2026-06-12) — Name-Capture Batch Fix (ROOT 1–4) — read this first

**Verified baseline:** `pytest tests/ -q` → **2151 passed, 7 skipped, 0 failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **7/7 (P1/P2/P4 now PASS)** · `test_agent.py` ✅ · CRITICAL **22/22**. **Production is NOT green.** Fixed ONE root cause at a time, full-pytest + corpus gate after each. New file [tests/test_name_capture_batch_fix.py](tests/test_name_capture_batch_fix.py) (+22). No Calendar/Sheets-schema/adult/broadcast/email/model/prompt change; no hardcoded sender_id/profile names.

Root causes fixed (from the red-team + Hypothesis P1/P2/P4 findings):
- **ROOT 1** ([parent_flow.py](app/flows/parent_flow.py)) — `NAME_FILLER_WORDS` += `ჩემი, ან, და, გამარჯობა, არის, გთხოვთ`; `_NAME_REJECT_STEMS` += `ჯავშან` (the old `ჯავშნ` missed the nominative `ჯავშან-ი`) + `გადანიშ`. Exact-match filler keeps real names (ანა/დავითი/არისტო); `არა` still blanked; all previously-rejected words stay rejected.
- **ROOT 2 CORE** ([parent_flow.py](app/flows/parent_flow.py)) — `_looks_like_contact_disclosure` drops the unconditional `if candidate_phone: return True`; the name candidate must be a non-empty run of ≤ `_NAME_TOKEN_CAP` (4) valid name tokens. „ჩემი ნომერია 595999733" → name not saved; „ჩემი სახელია ლიზი ნომერი 595999733" → name=`ლიზი`. **ROOT 2 enhancement (done):** `_distinct_valid_phones` → two numbers („595999733 ან 595999734") → „ორი ნომერი მომწერეთ. რომელი ნომრით დაგიკავშირდეთ?" (single spaced phone = one).
- **ROOT 3** ([parent_flow.py](app/flows/parent_flow.py)) — `_parse_name_phone` drops a captured name longer than `_NAME_TOKEN_CAP` (4) tokens → a rambling paragraph + phone yields phone only.
- **ROOT 4 DEFERRED** — multi-child „10 და 14 წლის" still keeps the first age. The „capture nothing → re-ask" guard broke the existing `test_parent_llm_engine.py::test_age_fallback_two_children_keeps_first_valid` (old „keep first" contract) → reverted per the STOP rule. Follow-up: update that existing test to the new contract, then add a deterministic „which child — 10 or 14?" clarification (NO Sheets-schema / lead-field change needed).

**Live smoke after fix (operator) — Production is NOT green until these pass on a real Meta DM:**
- **A.** „ჩემი ნომერია 595999733" → phone saved, name NOT „ჩემი" (asks for the name).
- **B.** „595999733 ან 595999734" → „ორი ნომერი მომწერეთ. რომელი ნომრით დაგიკავშირდეთ?".
- **C.** „ჯონი 595999733" / „ლიზი 595999733" → name+phone (single-phone happy path intact).
- **D.** A rambling first message with a phone → phone captured, no paragraph saved as a name.

---

## ▶ SESSION HANDOFF (2026-06-12) — PARENT Contact-Capture (BUG 1–4) — read this first

**Verified baseline:** `pytest tests/ -q` → **2120 passed, 0 failed** · `python test_agent.py` → ✅ green · `scenario_runner_full.py --priority CRITICAL` → **22/22**. **Production is NOT green.** Fixed ONE bug at a time, full-pytest gate after each (≥2086). New file [tests/test_parent_contact_collection_livebug.py](tests/test_parent_contact_collection_livebug.py) (+34). **No change** to Calendar internals, Sheets schema/row-strategy, adult subscription/broadcast sending, email SMTP, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`. No hardcoded sender_id / profile names (test fixtures only).

**BUG 1 asymmetry trace — REPORTED BEFORE THE FIX (the handoff's parser-regression hypothesis was DISPROVEN):**
- `_parse_name_phone("595999733")` → `("", "595999733")` — the parser extracts the bare phone correctly; there is **NO** deterministic rejection line for a standalone phone. `_parse_name_phone("595999733 ეს არის ნომერი")` → `("ეს არის", "595999733")`. Both parse the phone identically.
- The asymmetry lived in the **caller gating + LLM fallthrough**: the only deterministic contact capture, `parent_flow._capture_contact_and_ask_time`, is gated behind `booking_subflow_active = bool(stale_cleared or pending)`, so a contact turn with no `pending_booking` returned `None` and fell through to the LLM. The engine (`run_parent_llm_turn`) has `maybe_capture_child_age_fallback` + `maybe_capture_challenge_fallback` but **no phone fallback** — so when the LLM didn't call `save_lead_info(phone=…)`, the phone was dropped and it re-asked. „595999733 ეს არის ნომერი" gave the LLM an explicit „this is the number" cue (reliable save); bare „595999733" was ambiguous (re-ask). Hence phone+text worked, phone-alone failed — backwards.
- **Regression source:** not a parser break. The closest recent patch is **PARENT Contact Extraction + Booking State (2026-06-11)**, which introduced the pending-gated `_capture_contact_and_ask_time` and left plain (no-pending) contact collection LLM-dependent.
- **BUG 2:** `_parse_booking_datetime("595999733 ლიზი")` → `None` and `extract_colloquial_hour` → `None` — the phone digits are NOT parsed as a time. The „ეს დრო ძალიან ახლოსაა" wording came from the booking/time path acting on a non-bookable (stale/buffer) pending datetime during contact collection — i.e. booking/time logic running instead of contact capture.

**Fixes (deterministic, generic, per-bug pytest-gated):**
- **BUG 1 + BUG 2** ([parent_flow.py](app/flows/parent_flow.py)) — new `_maybe_handle_contact_collection` runs in the engine path BEFORE the LLM / commit helper. On a contact-only message (parsed phone, NO explicit datetime, no time-change) in a contact-collection context (`_bot_recently_asked_for_contact` — latest assistant turn carrying „9-ნიშნა"/„საკონტაქტო ნომერ" — OR a `pending_booking`), it captures the phone (any order; user phone wins over missing profile data) + a valid name, then replies deterministically: name unknown → „ნომერი მივიღე. მომწერეთ თქვენი სახელი, რომ კონსულტაცია ჩავნიშნოთ."; name+phone → „მადლობა, {name}. რომელი დღე და დრო გირჩევნიათ კონსულტაციისთვის?"; name known → „ნომერი მივიღე. რომელი დღე…". Reversed „595999733 ლიზი" is contact, never booking/time. A genuinely future, bookable confirmed slot still books via the commit helper (`_pending_iso_is_future_bookable` defers). Over-long „555555555555555" → „ნომერი სწორად ვერ ამოვიკითხე. მომწერეთ 9-ნიშნა…". (gate → 2102) — Cross-interference caught by the gate: two `test_parent_llm_engine` engine tests fed a phone to exercise the sanitizer/guard; gating firing on `in_contact_ctx` (not unconditional) preserved them.
- **BUG 3** ([parent_llm_engine.py](app/agent/llm/parent_llm_engine.py)) — `_strip_concern_wording` extended with `_is_known_about_you_preamble`: strips a sentence with „თქვენი" + (ასაკ|სახელ|ინფორმაცია) + (უკვე ვიცი|უკვე მაქვს) → removes „თქვენი ასაკი უკვე ვიცი, 15 წლისაა" (15 = CHILD's age) and „თქვენი სახელი უკვე ვიცი". The „თქვენი" anchor preserves legitimate „სახელი უკვე ვიცი"/„ბავშვის ასაკი უკვე ვიცი", the Task 2 privacy notice (no „უკვე ვიცი/მაქვს"), and booking confirmations. (gate → 2111)
- **BUG 4** ([parent_flow.py](app/flows/parent_flow.py)) — `_maybe_request_full_contact_on_intent`: on an explicit consultation request („კი მინდა"/„კონსულტაცია მინდა"/„ჩამწერეთ", NOT a bare „კი") for an ELIGIBLE known age with contact incomplete and no bookable slot pending → asks the COMPLETE contact (name + 9-digit phone when the name is not validly known, phone-only when it is). Defers for unknown/ineligible age, browsing („კი მინდა ვიცოდე ფასი"), and the booking-confirmation path. (gate → 2120)

**Live smoke after fix (operator) — Production is NOT green until these pass on a real Meta DM:**
- **A.** Agent asks for contact → send bare „595999733" → name known: „ნომერი მივიღე. რომელი დღე…"; name unknown: „ნომერი მივიღე. მომწერეთ თქვენი სახელი…" (NO re-ask loop, NO „თქვენი სახელი უკვე ვიცი").
- **B.** Send reversed „595999733 ლიზი" → „მადლობა, ლიზი. რომელი დღე…" (NO „ეს დრო ძალიან ახლოსაა").
- **C.** „კი მინდა" (eligible, contact missing) → complete „მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი…".
- **D.** Confirm BUG 3: no „თქვენი ასაკი/სახელი უკვე ვიცი" anywhere in contact collection; privacy notice still only on a successful booking; regression suite (ჯონი/ლიზი 595999733 / „9-17" not child_age / booking + reschedule) intact.

---

## ▶ SESSION HANDOFF (2026-06-11) — read this first for the next Claude Code session

**Verified baseline (current):** `pytest tests/ -q` → **2086 passed, 0 failed** (3 warnings) · `python test_agent.py` → ✅ green · `scenario_runner_full.py --priority CRITICAL` → ****22/22** (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3 — SC-01 passed this run)** (standing flake = SC-01 turn-4 word-choice stochasticity, NOT touched by these deterministic guards). **Production is NOT green.** Model `gpt-4.1-mini`. Broadcasts DRY-RUN (`LIVE_BROADCAST_ENABLED` default **False**).

**Wording Fixes (2026-06-11) — fixed one bug at a time, full pytest gate after each (≥2066):**
- **BUG 1 — awkward „შეშფოთება" / „info already known about age & concern" preamble in the PARENT contact request.** Live: after „კი მინდა" the agent said „თქვენი ინფორმაცია უკვე მაქვს ასაკისა და შეშფოთების შესახებ. მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი…". ROOT CAUSE: **LLM free-generation** — the system prompt (`system_parent_v2.md`) uses „შეშფოთება" (concern/anxiety) as the term for the parent's challenge, and the exact preamble is not a template (no literal match in code). „შეშფოთება" reads as alarming/medical and the „I already have your info…" preamble is hallucinated confidence when name/phone are still missing. FIX (deterministic sanitizer, NO prompt change): new `parent_llm_engine._strip_concern_wording` (called inside `sanitise_response_wording`, which post-processes every LLM PARENT reply) (a) strips a whole sentence that carries BOTH (ასაკ|შეშფოთებ) AND (უკვე მაქვს|უკვე ვიცი) — so the live preamble is removed while the legitimate „სახელი უკვე ვიცი/მაქვს" contact wording is preserved; (b) replaces any residual „შეშფოთებ"-stem word with a neutral declension („მოლოდინი"). The privacy notice (Task 2) is untouched (no „უკვე მაქვს"/„შეშფოთებ" in it). (gate → 2076)
- **BUG 2 — „where will the notification arrive?" redirected as off-topic.** Live: after subscribing, „და სად მომივა შეტყობინება მესენჯერში?" got „ამ კითხვაზე ვერ დაგეხმარებით…". ROOT CAUSE: the deterministic off-topic guard `_maybe_adult_offtopic_reply` does NOT match this question — the redirect is **LLM free-generation** from the system_adult_v1.md OFF-TOPIC rule (the LLM misclassified a legitimate delivery question as off-topic). FIX (deterministic, NO prompt change): new `adult_llm_engine._maybe_handle_notification_delivery_question` runs in `run_adult_llm_turn` BEFORE the subscription / off-topic / LLM layers — on a „where/how will the notification arrive" question it returns a platform-aware answer (Messenger / „Instagram-ის პირად შეტყობინებაში"). It never re-subscribes (writes nothing) and never reaches the off-topic guard/LLM (proven by an integration test that mocks OpenAI to raise + flags any subscribe). (gate → 2082)

**Adversarial multi-agent review run on the diff** (2 dimensions → per-finding verification): 4 confirmed. Fixed before finalising: (1+2) **HIGH** — the BUG 1 concern-strip over-stripped legitimate sentences that merely contain „უკვე ვიცი"+„ასაკ" with a comma between („სახელი უკვე ვიცი, რა არის ბავშვის ასაკი?" / „ბავშვის ასაკი უკვე ვიცი, ხუთი წლის.") → re-anchored on the word „ინფორმაცია" via a precise sentence-split so only the real „I have your INFORMATION about age/concern" preamble is dropped (the legitimate name/age wording lacks „ინფორმაცია"); (4) **HIGH** — the BUG 2 delivery handler told a WhatsApp user „Messenger-ში" → added a WhatsApp branch („WhatsApp-ში"). Finding (3) — the „შეშფოთება"→„მოლოდინი" word replacement is unconditional — is BY-DESIGN (the spec bans „შეშფოთება" from user-facing PARENT replies; „მოლოდინი" is an allowed alternative). +4 regression tests lock these. CRITICAL (22/22) ran before the review fixes; those are deterministic refinements that don't touch any CRITICAL path.

New tests: [tests/test_wording_concern_and_subscription_delivery.py](tests/test_wording_concern_and_subscription_delivery.py) (+20). All deterministic; no hardcoded sender_id / profile names. **No change** to Calendar internals, Sheets schema, adult subscription WRITE logic, broadcast sending, email SMTP, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`.

**Live smoke after fix (operator):**
- **A.** PARENT booking → „კი მინდა" → contact request reads simply („მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი…"), NO „შეშფოთება", NO „ინფორმაცია უკვე მაქვს ასაკისა და…".
- **B.** Subscribe in ADULT → „და სად მომივა შეტყობინება მესენჯერში?" → platform-aware delivery answer, NOT an off-topic redirect, no duplicate subscribe.

---

**Verification audit (2026-06-12, AUDIT ONLY — no code change):** confirmed comment routing + follow-up scheduler were NOT broken by the recent patches.
- `comment_service.py` (mtime 06-10 21:49), `followup_service.py` (06-06), `main.py` APScheduler init (06-08) all PREDATE the recent-patch window (parent_flow 06-11 21:12, parent_tool_executor 06-11 21:29, parent_llm_engine + adult_llm_engine 06-12 00:19) — none modified by recent patches.
- Both files contain ZERO references to any recently-changed module/function/sanitizer.
- `pytest -k "comment"` → **196 passed, 0 failed, 0 skipped**; `pytest -k "follow"` → **186 passed, 0 failed, 0 skipped**.
- The new wording sanitizers (`sanitise_response_wording`/`_strip_concern_wording`) and the privacy-notice policy (`_apply_privacy_notice_policy`, only inside `parent_flow.handle`) do NOT run on comment first-contact DMs or follow-up copy (both are template-based). Challenge cleanup applies only when a comment-sourced user later discloses a goal in the shared DM engine — uniform, not a comment-specific regression.
- **Verdict: LOW risk** (isolated, all targeted tests pass). Standard live smoke still recommended: comment #camp / #event / specific-tag, comment-triggered follow-up, subscription follow-up (DRY-RUN only).

**✅ LIVE SMOKE confirmed working (manual Messenger, 2026-06-11/12):** name auto-read from Meta profile · child_age reuse cross-flow („ჩემი შვილისთვის" doesn't re-ask) · booking + Calendar event + Sheet row · reschedule (Calendar updates) · PM time („5 საათი"→17:00, „8 საათი"→20:00) · privacy notice appears once after booking · adult subscription write · „სად მომივა შეტყობინება" answered (not redirected) · profile-fetch 400 graceful (tester role removed → flow doesn't break).

---

**Cleanup Fix (2026-06-11) — fixed one bug at a time, full pytest gate after each (≥2046):**
- **BUG A — privacy notice repeated too early/often.** ROOT CAUSE: the system prompt instructs the LLM to add the child-data privacy notice („თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის…") when collecting child data, so it leaked onto contact-request / slot-offer / slot-check turns and sometimes appeared twice; meanwhile the Session-7 „short confirmation" rule STRIPPED it on the success turn — the opposite of the new business rule. FIX (deterministic, executor-signal-driven, NO prompt change): new `parent_flow._apply_privacy_notice_policy` runs at the universal final chokepoint `_sanitise_booking_confirmation` (called by every `handle()` return path) — it strips every privacy-note occurrence on EVERY turn, then re-appends ONE canonical sentence iff `book_consultation_success_for_conversation` (the executor's booking/reschedule-success signal) is set THIS turn. So: success → notice once; fail / contact / slot / turn-after → none. `_reschedule_booking` now also sets the success flag so a reschedule via `manage_consultation_booking` gets the notice too. The Session-7/8 sub-function tests stay green (they test `_trim_booking_success_response` / the commit helper directly; the policy lives in the chokepoint). (gate → 2056)
- **BUG B — challenge TEXT duplicated within a row.** (Multiple ROWS per sender are BY DESIGN — not touched.) ROOT CAUSE: the manager email already deduped via `notification_service._dedupe_repeated_phrase`, but the SAVE path stored the raw merged `lead.challenge` (written verbatim to the Sheets CRM), so „მეგობრები კომუნიკაცია მეგობრები კომუნიკაცია" reached the Sheet. FIX at the save chokepoint: `parent_llm_engine.dedupe_challenge_text` (clause-level + verbatim repeated-block collapse) now runs inside `clean_challenge_for_storage`, and `_save_lead_info`'s merge uses comma/space-insensitive **word-set containment** (`challenge_word_set`) so a re-save of the same concepts (booking / reschedule / adult→parent re-entry) never doubles the text — while the existing substring containment (a shorter rephrase „ეკრანი" ⊂ „ეკრანისგან დისტანცია" stays) and the „; " separator for genuinely-unrelated concepts are preserved. Reschedule reuses the clean existing challenge as-is (`_reschedule_booking` never writes challenge); adult-interest is still rejected from the PARENT challenge and vice-versa; the Sheet payload and the email payload derive from the same cleaned value. (gate → 2066, after fixing 2 regressions found by the gate: the substring check + the „; " separator.)
- **BUG C — adult events list shows test/dummy rows (AUDIT ONLY).** **Dirty data, NOT a code bug.** Adult events come from `data/admin_config/sections.yaml` → `adult_events.events[]` (operator config), **not a Sheet** (the `events` Sheets tab is subscribers only). There is **no test/staging flag column**. The active+future filter is CORRECT — `admin_config_service.get_active_adult_events()` returns 5 future events and correctly excludes the past „მასტერკლასი" (9 ივნისი < today 11 ივნისი). The placeholder rows are active + future, so they correctly appear. **Operator action (do NOT auto-delete):** set these to `status: inactive` via `/admin/programs/adult_events/events/{id}/deactivate` (or in `sections.yaml`):
  - `id='ჯონი'` (title „ჯონი") — a person name, not an event.
  - `id='formula_1'` (title „formula 1") — not a cultural event.
  - `id='summer_fest'` (title „summer fest") — English placeholder, `min_age=19` (anomalous).
  Legitimate events: „ქართული პოეზიის საღამო", „აღზრდა — შეხვედრა გია მურღულიასთან", „მასტერკლასი" (past — already auto-hidden). **Recommendation:** a staging-vs-prod config separation (or a `test: true` convention) to keep placeholders out of the live list.

New tests: [tests/test_cleanup_privacy_challenge_dedupe.py](tests/test_cleanup_privacy_challenge_dedupe.py) (+20). All deterministic. **No change** to Calendar internals, Sheets schema/row-strategy, adult subscription/broadcast sending, email SMTP, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`.

---

## ▶ PRIOR SESSION — State Reuse Fix (2026-06-11) — fixed one bug at a time, full pytest gate after each (≥2021):

- **BUG 1 — adult-for-child re-asked a known child_age.** ROOT CAUSE: the ADULT flow's `adult_llm_engine._maybe_capture_adult_target` captured `adult_target_relation="შვილი"` from „ჩემი შვილისთვის" but never set `adult_target_age`; the adult context surfaces `adult_target_age` (not `child_age`), so it was „—" and both the LLM and `_ensure_adult_intro_followup` asked „თქვენი შვილი რამდენი წლისაა?". Entering ADULT never clears `child_age` (same shared `conversation.lead`; `switch_to_adult_flow` only moves it to `adult_age` when out of [9,17]). FIX: when the relation is the user's OWN child (`შვილი`/`ბავშვი`), no inline age, and the message is NOT „სხვა …" (a DIFFERENT child), deterministically reuse the known `child_age` → `adult_target_age`. Copies, never moves; `child_age`/`adult_age` coexist and are untouched. (gate → 2031)
- **BUG 2 — ADULT→PARENT reschedule lost parent state.** ROOT CAUSE: the segment override (`conversation_service._is_parent_consultation_intent`) already routes „კონსულტაციის გადატანა მინდა" back to PARENT, but the engine then sometimes re-asked the age / treated the user as fresh (stochastic LLM). FIX: new deterministic `parent_flow._maybe_handle_reschedule_intent_engine` runs in the engine path BEFORE the commit helper — a clear reschedule request with NO new datetime + an active booking → returns „კი, ბანაკის კონსულტაციის გადატანაში დაგეხმარებით. რომელი ახალი დღე და დრო გირჩევნიათ?" (reuses child_age/name/phone/booking, never re-asks age — clear reschedule intent wins over qualification). A reschedule WITH a datetime defers to the existing check_consultation_slot/reschedule flow (slot selection directly). No active booking + not mid-build → asks for identifying info politely, never touching adult data. (gate → 2038)
- **BUG 3 — bare „N საათი" (no „ზე").** AUDIT FINDING: **already handled** — `timestamps._COLLOQUIAL_HOUR_RE` already includes the `საათი` suffix (`საათ(?:ზე|ისთვის|ისკენ|ი)?`), so „18 ივნისი 8 საათი" → 20:00 across ALL three deterministic call-sites (`parent_turn_router._parse_booking_datetime`, executor `_normalise_datetime_iso_from_message`, post-engine `_repair_colloquial_hour_rejection`), „დილით 8 საათი" → 08:00 (rejected as outside hours), „10 საათი" → 10:00, „20:00" literal. NO code change (the prior Georgian Colloquial Time patch already extended the regex); +8 regression tests lock it so a future edit can't re-break it. (gate → 2046)

New tests: [tests/test_state_reuse_crossflow_and_pm_time.py](tests/test_state_reuse_crossflow_and_pm_time.py) (+25). All deterministic, generic (no hardcoded sender_id / profile logic). **No change** to Calendar internals, Sheets schema/write, adult subscription/broadcast, email, OpenAI model, Railway, prompts, `LIVE_BROADCAST_ENABLED`. Architecture: the LLM still composes replies; the deterministic guards own the critical state transitions (child_age reuse, reschedule routing, time parsing).

**Live smoke after fix (operator):**
- **A.** PARENT booked (child_age known) → ADULT → „ჩემი შვილისთვის" → must NOT re-ask the child's age (reuses it).
- **B.** „სხვა შვილისთვის" → re-asks the new child's age.
- **C.** PARENT booked → ADULT → „კონსულტაციის გადატანა მინდა ბანაკზე" → „კი, … რომელი ახალი დღე და დრო გირჩევნიათ?" (no age re-ask) → next message names the new time → reschedule completes.
- **D.** „18 ივნისი 8 საათი" (bare) → 20:00; „დილით 8 საათი" → 08:00 rejected.

**Fixed + verified this session (all deterministic, all tested):**
- **ADULT subscription confirmation + write** (+42 tests, 1873 → 1915). Root cause: the consent wiring was removed in the rolled-back Guardrails patch, so subscription depended entirely on the stochastic LLM calling the tool (and there was no pending-offer state). New deterministic consent/direct-intent layer in `adult_llm_engine.run_adult_llm_turn` writes the `events`-tab row (`status=subscribed`, `consent=TRUE`, platform+sender_id) via `AdultToolExecutor` and confirms („ჩაგწერეთ სიაში") **only after a successful write**; honest failure fallback; already-subscribed handled; **never triggers broadcast**. Hardened per adversarial review (token-boundary „კი", immediate-offer-adjacency, pure-„მინდა" whitelist). See patch section below.
- **State consistency + child-age extraction** (+52 tests, 1915 → 1967). „9-17" (camp age BAND / menu) is no longer read as `child_age` (range rejection `_contains_age_range`); time/date numbers („12 საათზე", „11 ივნისს", „20:00", colloquial „N-ზე") are not treated as age; a new PARENT/camp user with unknown age is always asked (`_ensure_camp_age_question`); resume transparency (acknowledge stored age once + re-qualify on „სხვა შვილ"); safe-load defaults for old Redis snapshots. **Generic + state-based — NO hardcoded user IDs.** Colloquial-hour „N-ზე" leak found + fixed by adversarial review. See patch section below.
- **Clean-tree verification** — repo-wide search confirmed **no mutation-test artifacts remain** in application code; `app/models/conversation.py` `from_dict` holds the intended FIX 4 implementation (stale-format log + safe `.get` defaults), not a `pass`/`MUTATION-FIX4-LOG` stub. No files changed by the verification.

**✅ SOLVED — the „different behavior per Facebook account" mystery (it was input + stored state, never per-user code):**
- **Father's account:** typed the menu text „ბავშვების საზაფხულო ბანაკი 9-17" → „9" was extracted as `child_age` → the age question was skipped. **FIXED** (range rejection).
- **Own account:** old Redis test state was silently reused → felt unstable/random. **FIXED** (resume transparency: acknowledge stored age once + allow re-qualify; safe-load defaults).
- **Mariam's account:** fresh state → always worked (this was the correct baseline).
- **Conclusion:** the code was always consistent; only the input text + stored Redis state differed. Behavior is now generic and state-based: same input + same state → same behavior.

**Pending before production (do NOT mark green until all pass):**
1. **NEXT TASK — PARENT contact-capture 4-bug fix** (see the ⏭️ prompt block below). Live blockers: standalone „595999733" rejected as phone while „595999733 ეს არის ნომერი" is accepted (asymmetry — trace first, possible prior phone-parse regression); „595999733 ლიზი" (phone+name reversed) wrongly triggers the booking/time path; agent announces „თქვენი ასაკი უკვე ვიცი, 15 წლისაა" to a PARENT (15 is the CHILD's age — same family as the banned „შეშფოთება" preamble); soft-CTA vs explicit contact-request wording.
2. **Reschedule Sheet status check** — verify in live smoke that the OLD Sheet row flips to „Rescheduled" and exactly one „Booked" row remains per sender.
3. **Full live smoke:** PARENT booking + reschedule · ADULT subscription · comment routing (#camp / #event / specific tag) · follow-up. Plus the A–B wording smoke above.
4. **Deactivate test adult events** (`ჯონი` / `formula_1` / `summer_fest` in `sections.yaml`) before client launch — dirty data, NOT a code bug (filter works).
5. **Meta access token REGENERATE** — a token leaked in a terminal error log; rotate it before production.
6. **Google credentials Railway-safe** — provide via env / base64, not a file path.
7. **Railway env sync + deploy → STAGING first** (a test Page, not the client's live Page) → Meta App Review submission.

### ⏭️ Next Claude Code prompt (paste after /clear)

> **URGENT LIVE BLOCKER — PARENT contact capture (4 bugs). Fix ONE AT A TIME, full pytest gate after each. Do NOT mark production green.**
>
> Read HANDOFF.md, CLAUDE.md, REVIEW_PACK.md first. Baseline: `pytest tests/ -q` → **2086 passed, 0 failed**, CRITICAL 22/22, production NOT green.
>
> **CRITICAL EXECUTION RULE:** fix ONE bug at a time. After EACH fix run `python -m pytest tests/ -q`. If the count drops below 2086 OR any existing test breaks → STOP, report which bug's fix caused it, do NOT continue.
>
> **Do NOT touch:** Calendar internals, Sheets schema, adult subscription WRITE logic, broadcast SENDING, email SMTP, OpenAI model, Railway, prompt cleanup, `LIVE_BROADCAST_ENABLED`. **Do NOT** hardcode sender_id or profile names. The Gmail `reservation_url` is an intentional placeholder, NOT a bug.
>
> **BUG 1 (REGRESSION — trace WHY first, before fixing):** a standalone „595999733" is REJECTED as a phone, but „595999733 ეს არის ნომერი" (same digits + extra text) is ACCEPTED. This asymmetry is backwards. A previous phone-parse fix may have regressed `parent_flow._parse_name_phone` (or a caller / a pending-booking continuation guard). AUDIT FIRST: trace exactly which branch rejects the standalone form vs accepts the with-text form (e.g. is a bare 9-digit message being swallowed by an age/booking/“low-value” guard before the parser runs?). Report the root cause, THEN fix so BOTH „595999733" and „595999733 …" parse the phone. Keep „ჯონი 595999733" / „595 999 733 ნიკა" working. [gate]
>
> **BUG 2:** „595999733 ლიზი" (phone FIRST, then name) wrongly routes to the booking/time path („ეს დრო ძალიან ახლოსაა…"). Contact parsing must take PRIORITY over booking/time parsing when the message is clearly contact (a valid 9-digit phone + a name). Ensure phone+name in either order saves both and does NOT trigger a time/slot interpretation. [gate]
>
> **BUG 3:** the agent says „თქვენი ასაკი უკვე ვიცი, 15 წლისაა" to a PARENT — wrong (15 is the CHILD's age, not the parent's) and it announces known info during contact collection. Same family as the banned „შეშფოთება" preamble (Wording Fix BUG 1). EXTEND the deterministic sanitizer (`parent_llm_engine._strip_concern_wording` / `sanitise_response_wording`) to also strip an age-announcing preamble („თქვენი/ბავშვის ასაკი უკვე ვიცი/მაქვს …", „… X წლისაა" confidence opener) during contact collection. MUST NOT break the Task 2 privacy notice or the legitimate „სახელი უკვე ვიცი" (anchor on the announce-the-age preamble, not on the contact-request line). Add regression tests incl. the legitimate-name-known case + the privacy notice. [gate]
>
> **BUG 4 (lower priority):** soft CTA („თუ გსურთ, …") vs explicit contact request wording — prefer the explicit „მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, რომ კონსულტაცია ჩავნიშნოთ." form during contact collection. [gate]
>
> Per-bug: deterministic, generic (no hardcoded users), add focused tests (incl. the exact live strings „595999733", „595999733 ეს არის ნომერი", „595999733 ლიზი", and the age-announce preamble), keep `pytest ≥2086` + `test_agent.py` green. Run CRITICAL only if the parser/sanitizer core is touched (explain SC-01 stochasticity if it appears). Update HANDOFF/CLAUDE/REVIEW_PACK. Keep changes narrow and test-gated.

---

**PARENT Contact Extraction + Booking State + Challenge Cleanup Patch (2026-06-11, pytest 1967 → 2021, +54 tests):**

Four live PARENT bugs from production conversations. All fixes are deterministic, generic (NO hardcoded sender_ids / user-specific logic), PARENT-only. **No change** to Calendar service, Sheets schema, email SMTP, OpenAI model, webhook, broadcast, adult subscription/event logic, or any prompt. New tests: [tests/test_parent_contact_booking_and_challenge_cleanup.py](tests/test_parent_contact_booking_and_challenge_cleanup.py) (52).

**LIVE BUG 1 — contact-only („ჯონი 595999733") triggered a stale booking („16:45 წარსული დროა").**
- ROOT CAUSE: the engine pending-commit path `parent_flow._maybe_commit_pending_booking_engine` reads `_confirmed_pending_iso(conversation)` and, when name+phone+child_age are all present, calls `book_consultation` against it. A `requested_datetime_iso` recorded earlier (via `_check_consultation_slot` → `_record_pending_booking_for_slot`, `user_confirmed_datetime=True`) at **16:45** had already elapsed by the time the contact-only message arrived → `book_consultation` rejects it (`reason="datetime_in_past"`) → the commit helper returned `None` → the LLM then composed „…ვერ დავადასტურე, რადგან 16:45 წარსული დროა". The minute value (:45, not a top-of-hour slot) shows the time was a `now`-derived / LLM-echoed datetime, not a clean offered slot. Contact capture was NOT separated from booking confirmation.
- FIX ([app/flows/parent_flow.py](app/flows/parent_flow.py)): new `_pending_iso_is_stale(iso)` (past relative to Tbilisi now) + `_clear_stale_pending_datetime(conversation)` (strips only the datetime fields, keeps contact/bookkeeping). In `_maybe_commit_pending_booking_engine`, a confirmed pending datetime that is stale is cleared and **never booked**; the inline compound-booking datetime is likewise only committed when still future. New `_capture_contact_and_ask_time(...)` (fires inside an active booking sub-flow) saves any contact via the fixed parser and returns the deterministic „მადლობა, {name}. რომელი დღე და დრო გირჩევნიათ კონსულტაციისთვის?" — so a contact-only message never books a random/stale time. A FUTURE confirmed pending slot + „კი"/contact still books that exact slot (unchanged).

**LIVE BUG 2 — a month/date word was saved as the name („595999733 16 ივნის მინდა 10 საათზე" → name=„ივნის").**
- ROOT CAUSE: `parent_flow._parse_name_phone` kept every leftover non-digit token around the phone as the name, with no month/time/booking rejection. „ივნის მინდა საათზე" became the name and the agent greeted „ივნის".
- FIX: new `_name_token_is_valid(token)` rejects any digit-bearing token, Georgian month declensions (reusing `GEORGIAN_MONTH_STEMS`), and the time/date/booking stems (`საათ`, `სთ`, `წლ`, `დღეს`, `ხვალ`, `ზე` (exact), `მინდა` (exact, so the name „მინდია" is NOT rejected), `კონსულტაც`, `ჩაწერ`, `გადატან`, …). `_parse_name_phone` filters name tokens through it. New public `is_valid_person_name(name)` mirror is applied at EVERY save chokepoint: `parent_tool_executor._save_lead_info` (rejects `name="ივნის"` → `invalid_fields`), `_book_consultation` (drops a non-name arg → falls back to a valid stored name or blocks `missing_name`), the engine pending-commit name capture, and the legacy `parent_turn_router.maybe_handle_pending_booking_continuation`. Reused existing month stems; no parallel month list. „ჯონი 595999733" still → name=ჯონი; „სახელი ჯონი" → ჯონი (added „სახელი" to `NAME_FILLER_WORDS`).

**LIVE BUG 3 — „თქვენი სახელი უკვე ვიცი" for invalid/unclear contact data.**
- ROOT CAUSE: the engine surfaces `name={lead.name}` in `_build_context_message`; a corrupted/stale stored name (e.g. „ივნის" from the old parser) made the LLM claim it knew the name. AUDIT: adult-subscription data is **never** used as PARENT contact — `adult_subscription_service._validate_phone` only reuses `_parse_name_phone` for read-only phone validation and writes to the `events` Sheets tab; no code hydrates PARENT `lead.name`/`lead.phone` from a subscription row. PARENT contact comes only from Meta profile, the disclosure parser, and the PARENT LLM tools.
- FIX: new `_sanitise_invalid_stored_name(lead)` runs in `_run_llm_engine_safely` BEFORE the engine builds context — clears `lead.name` when `is_valid_person_name` is false, so the engine never greets by a non-name or claims „სახელი უკვე ვიცი" for invalid data. Real names (Meta profile / valid disclosures) are untouched (test 14 keeps „ჯონი").

**LIVE BUG 4 — a tacked-on factual question polluted the Sheets challenge column.**
- ROOT CAUSE: the email rendering was cleaned previously (`notification_service._clean_challenge_for_email`) but the **SAVE path** (`_save_lead_info`, `maybe_capture_challenge_fallback`) stored the raw user message on `lead.challenge`, which `Lead.to_sheet_row` writes verbatim to the CRM.
- FIX ([app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py)): new `clean_challenge_for_storage(raw)` splits on commas/„ასევე", DROPS factual-question clauses (specific multi-char stems — „როდის", „რა ღირს", „ფასი", „სად ტარდება", „რა შედის", „როგორ ჩავეწერ", „?" — deliberately not bare „სად"/„ღირ" so „ახალი გარემო"/„თვითღირსება" survive), strips leading connective filler, and preserves the parent's own wording (no canonicalisation). Applied at the SAVE chokepoint: `_save_lead_info` (challenge + notes args) and `maybe_capture_challenge_fallback`. „ეკრანისგან დისტანცია, გარემო, მეგობრები და ასევე მაინტერესებს ბანაკი როდის ტარდება?" → stored „ეკრანისგან დისტანცია, გარემო, მეგობრები"; the agent still answers the question normally. NOTE: this is the SAVE path — distinct from the earlier email-only rule. `lead.challenge` is what the Sheets row reads, so cleaning it IS the Sheets fix Bug 4 asked for.

**Adversarial multi-agent review run on the diff** (4 review dimensions → per-finding verification): 14 findings, 9 confirmed. Fixed before finalising: (a) **HIGH** — `_capture_contact_and_ask_time` could hijack a discovery question („რა ღირს?") after a stale slot was cleared if the lead already had contact → now gated strictly on contact captured THIS turn (regression test `test_08b`); (b) **HIGH** — the real Georgian name „მარტი"/„მარტა" was rejected by the 4-char March stem „მარტ" → March (irrelevant to a summer camp + name collision) excluded from the NAME guard only, all summer months still rejected (`test_27`); (c) **HIGH** — a goal joined to a question by a plain „და" („კომუნიკაცია და როდის ტარდება?") dropped both → `_split_challenge_clauses` now splits on the standalone „და" connector, and the ambiguous „ღირებულება" was removed from the question stems so a „ღირებულებები"/values goal survives (`test_28`). Reviewed-and-dismissed (false positives / by-design): legacy ASK_NAME writes + Meta-profile name (both fed only by the now-pre-filtered `_parse_name_phone` / trusted platform name), the `<=` staleness compare (intentional — a slot at exactly „now" cannot be booked), and the in-loop cleanup timing (the SAVE chokepoint is the correct place).

**Verification:** `pytest tests/ -q` → **2021 passed, 0 failed**; `python test_agent.py` → ✅ green; `scenario_runner_full.py --priority CRITICAL` → **22/22** (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3 — SC-01 passed this run; the only standing risk is its turn-4 word-choice stochasticity). No Calendar/Sheets-schema/email/broadcast/model/prompt change. No real broadcast (DRY-RUN). The benign log „Invalid phone candidate rejected: '15 '" during booking scenarios is the future date „15 ივნისს" passing through `_parse_name_phone` — pre-existing, not a regression.

**Live smoke after fix (operator, run before production):**
- **A. New PARENT user:** „ბავშვების საზაფხულო ბანაკი 9-17" → asks the child's age, does NOT save „9".
- **B. Contact-only:** „ჯონი 595999733" → saves name+phone, does NOT book a random/stale time, asks for the preferred date/time.
- **C. Phone + date/time:** „595999733 16 ივნის მინდა 10 საათზე" → keeps a known name (never „ივნის"), parses 10:00, asks/continues booking.
- **D. Challenge + question:** „ეკრანისგან დისტანცია, გარემო, მეგობრები და ასევე მაინტერესებს ბანაკი როდის ტარდება?" → answers the date question; the Sheet challenge column saves only the goal.
- **E. Mixed-state user:** must not confuse adult/parent and must not reuse an invalid stale name.

---

**State Consistency + Child-Age Extraction Patch (2026-06-11, pytest 1915 → 1967, +52 tests):**

Live bug: a fresh PARENT user wrote „ბავშვების საზაფხულო ბანაკი 9-17" (the camp's advertised age BAND / menu text, NOT the child's age). The agent answered with general camp info and **did NOT ask the child's real age**.

ROOT CAUSE (PART 1): the deterministic fallback `parent_llm_engine.maybe_capture_child_age_fallback` matched „9" inside „9-17" (regex `(?<!\d)(\d{1,2})(?!\d)` — „9" is followed by „-", not a digit) and set `child_age="9"`. With `child_age` now „known", the downstream flow never asked the age. „9-17" was NOT saved as a literal range — it was extracted as „9" and stored as the child age. The Sheets/adult paths were untouched (this is a PARENT extraction bug). The fallback ALSO had no time/date guard, so „12 საათზე" / „11 ივნისს" could be misread as an age.

FIX (generic + state-based, no hardcoded users; PARENT-only — no Calendar/Sheets-schema/adult/comment/email/model/prompt change):
- [app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) — **FIX 1**: `maybe_capture_child_age_fallback(lead, message, *, age_question_pending=False)` now (a) rejects numeric ranges via `_contains_age_range` („9-17", „9 - 17", „9–17", „9 დან 17 წლამდე", „… წლამდე"); (b) skips numbers that are a clock time / calendar date via `_number_is_time_or_date` („12 საათზე", „20:00", „11 ივნისს", AND the colloquial hour marker „N-ზე"/„Nზე" — e.g. „შვილი 8-ზე მოვა" — added after the adversarial review found that form still leaked); (c) requires AGE CONTEXT — an explicit „წლ/წელ" word, a child word („შვილ"/„ბავშვ"), OR `age_question_pending`; a bare standalone number is captured ONLY when the bot just asked the age. New `_bot_recently_asked_child_age(conversation)` scans the last assistant turn; the engine call site passes it. Existing contracts preserved („14 წლის"→14, „ორი ბავშვი მყავს 11 და 14 წლის"→11, phone→"", „50 წლის"→"", „4 წლისაა"→"").
- [app/agent/tools/parent_tool_executor.py](app/agent/tools/parent_tool_executor.py) — **FIX 1 defense**: `_save_lead_info` rejects a `child_age` arg that is a range (so the LLM can't poison child_age with „9-17" either) → `invalid_fields=["child_age"]`.
- [app/flows/parent_flow.py](app/flows/parent_flow.py) — **FIX 2** `_ensure_camp_age_question` (last post-engine post-processor): when `segment=="PARENT"` AND `child_age` unknown AND the reply has no age-stem AND it is not an adult-redirect / manager handoff, appends „თქვენი შვილი რამდენი წლისაა?". **FIX 3** `_maybe_requalify_child` (a „სხვა შვილ"/„სხვა ბავშვ"/„სხვა ასაკ" message clears the stored child_age, re-extracts a new age from the same message if present, else re-asks) and `_maybe_acknowledge_stored_state` (on a greeting/restart of a RESUMED conversation — `_conversation_looks_resumed` = `state=="DONE"` AND NOT booked AND no `pending_booking` — acknowledges the stored child_age ONCE: „გამარჯობა! წინა საუბრიდან ვიცი, რომ თქვენი შვილი N წლისაა. ბანაკით ისევ ინტერესდებით?"). Both wired EARLY in `handle()`, after the memory-info short-circuit. Booked users are excluded from the resume-ack (the engine owns their resume) — preserves `test_handle_greeting_does_not_restart_for_booked_user`.
- [app/models/conversation.py](app/models/conversation.py) — **FIX 4**: `Conversation.from_dict` already defaults every field via `.get` (safe load — no crash on an old/partial Redis snapshot); added a privacy-safe one-line log (`[conversation] loaded stale-format snapshot — N missing field(s) defaulted: […]`, no values/ids). No migration system.
- [tests/test_age_extraction_state_consistency.py](tests/test_age_extraction_state_consistency.py) **(NEW, 52 tests)** — FIX 1 extraction matrix (range/menu/time-date rejection, colloquial-hour „N-ზე" rejection, explicit ages, standalone+pending vs not, `_save_lead_info` range rejection, adult_age never→child_age, `_contains_age_range`, `_bot_recently_asked_child_age`); FIX 2 guard (append when missing / no-op when known / no-op when already asks / no-op for ADULT / no-op on handoff) + e2e new-user range message + camp-interest + price-question + known-age-no-reask + adult_age-only-still-asks-child + dirty-mixed-state-reuses; FIX 3 resume-ack + confirm-continues + re-qualify (with/without new age) + preserves name/phone + no-ack-mid-flow + no-ack-for-booked; scalability (same input+state→same behavior across fake sender_ids; same input+different state→state-appropriate; NO hardcoded numeric sender-id literals in changed sources via tokeniser); FIX 4 stale-snapshot safe load.

Behaviour change: „9-17" (or any range / menu echo / time / date) is NEVER read as the child's age; a new PARENT/camp user with an unknown child_age is always eventually asked the age; an explicit „different child" re-qualifies; a resumed (completed, non-booked) conversation acknowledges the stored age once instead of silently reusing it. Generic + state-based — no per-user logic.

CRITICAL re-run: **EXECUTED — 21/22**. The single miss is SC-01 turn 4 LLM word-choice stochasticity (the screen-concern reply must contain the literal „ეხმარება"; the model sometimes phrases it „მუშაობს"/„გამოდიან"). Verified isolated: SC-01 passes 4/5 in isolation and the failing turn runs with `child_age="14"` ALREADY captured (FIX 1 works) — none of the new guards (FIX 1/2/3) touch the screen-concern turn. Not a regression from this change; the scenario assertion is a brittle exact-word check on an LLM-composed sentence. The other 21 pass cleanly.

**ADULT Subscription Confirmation + Write Patch (2026-06-11, pytest 1873 → 1915, +42 tests):**

Live bug: after the agent's future-event notification offer, the user explicitly consented (`„კი გამომიგზავნეთ"`) — the agent replied „ამ კითხვაზე ვერ დაგეხმარებით…" (BUG 1, the off-topic redirect) and never subscribed; on a retry („ჩამწერეთ სადმე? რომ ღონისძიება ავტომატურად მომივიდეს?") it implied notifications would arrive (BUG 2) but **never wrote an `events`-tab row**.

ROOT CAUSE (audit, PART 1):
- `adult_subscription_service.is_subscription_consent_phrase` was defined but **called from NOWHERE** — the helper that wired consent into the engine (`_consent_phrase_matches`) was removed in the **rolled-back Guardrails patch** (2026-06-09). The deterministic UNSUBSCRIBE short-circuit existed in `run_adult_llm_turn`; the SUBSCRIBE path did not.
- There was **no pending-offer state**: `Conversation.adult_subscription_status` documented an `"asked"` value but nothing ever set it. So subscription depended 100% on the stochastic LLM remembering to call `subscribe_to_adult_event_updates`.
- BUG 1: „კი გამომიგზავნეთ" has no in-scope stem, so the LLM (without a recorded pending offer) treated it as off-topic and returned the generic redirect. BUG 2: „ჩამწერეთ სადმე…" contains „ღონისძიება" (in-scope) so the LLM ran but only acknowledged — no tool call, no Sheets write, yet implied success. Sheets write did NOT fail; the service was simply **never called**.

FIX (deterministic, ADULT-subscription-only; no Calendar/Sheets-schema/email/webhook/model/broadcast-send change):
- [app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py) — new deterministic subscription layer wired into `run_adult_llm_turn`, running **after** the unsubscribe + parent-switch checks and **before** the off-topic guard and the LLM:
  - `_has_pending_subscription_offer(conv)` — True when `adult_subscription_status=="asked"` OR the last assistant turn was the offer question (inference fallback via `_is_subscription_offer_question`, which keys on the subjunctive „გამოგიგზავნოთ" so it never matches the indicative success copy „გამოგიგზავნით").
  - `_is_subscription_consent(msg, conversation=)` — two tiers, both requiring an open offer; negatives always lose. **Tier 1** — unambiguous "send/notify ME" verbs (`გამომიგზავნეთ`/`შემატყობინეთ`/`ჩამწერეთ`/`დამამატეთ` + subjunctive `გამომიგზავნოთ`, distinct from the offer's `გამოგიგზავნოთ`) accepted on the broader pending signal (status `"asked"` OR last-assistant-was-offer). **Tier 2** — short standalone affirmations (`კი`/`დიახ`/`ok`/`yes`, whole-token via `_tokenize_ka` so „კი"⊄„კიდევ") AND a PURE „მინდა" affirmation (`„მინდა"` only when every token is in the affirmation whitelist — so „ბილეთი მინდა"/„მინდა ფასი ვიცოდე" are NOT consent) accepted ONLY when the offer was the IMMEDIATELY-preceding assistant turn (closes the stale-marker window). **This two-tier hardening was added in response to the adversarial review** (it flagged that bare „მინდა" substring-matched any „I want X" message, and that a stale „asked" marker could turn a later unrelated „კი" into a subscribe).
  - `_is_direct_subscription_intent(msg)` — strong unambiguous requests subscribe even with NO pending offer („ჩამწერეთ სადმე", „სიაში ჩამწერეთ", „ავტომატურად მომივიდეს", „შემატყობინეთ როცა", „ახალი ღონისძიებების შესახებ მომწერეთ", …).
  - `_deterministic_subscribe(...)` — routes the write through `AdultToolExecutor.execute(subscribe_to_adult_event_updates, {})` (reuses name/phone fallback from the lead, source-event recovery from `preferred_event`, lead mirroring, conversation-status marking). Checks `is_already_subscribed` first (→ „თქვენ უკვე ხართ სიაში…", no duplicate row); on success → „ჩაგწერეთ სიაში…"; on missing name/phone → asks for it and keeps the offer pending; on `sheets_save_failed`/error → honest „ამ მომენტში სიაში დამატება ტექნიკურად ვერ მოხერხდა. მენეჯერს გადავცემ და შეგატყობინებთ." (never claims success).
  - `_mark_subscription_offer_if_present(conv, response)` — sets `adult_subscription_status="asked"` when the agent's outgoing reply IS the offer question, so the NEXT turn's „კი" is caught deterministically even when the LLM phrased the question itself.
  - Sanitiser safety net `_strip_false_subscription_success` (wired into `sanitise_adult_response` only when `sender_id` is provided AND no confirmed write this turn) — strips invented „ჩაგწერეთ სიაში"/„დაგამატეთ სიაში"/„უკვე ხართ სიაში" success claims from the LLM path and appends the honest failure line, so the agent can never imply a subscription that wasn't persisted (Core rule). Skipped entirely when `sender_id=None` (unit-test path) and when the executor confirmed a real write.
- [app/agent/tools/adult_tool_executor.py](app/agent/tools/adult_tool_executor.py) — new per-turn flag `adult_subscription_confirmed_for_conversation` + `mark/is/clear_subscription_confirmed`; set on a successful `subscribe_to_adult_event_updates`; cleared at turn start; consumed by the sanitiser safety net. Added to `reset_state()`.
- [tests/test_adult_subscription_confirmation_and_write.py](tests/test_adult_subscription_confirmation_and_write.py) **(NEW, 42 tests)** — consent-after-pending (კი / კი გამომიგზავნეთ / მინდა / გამომიგზავნეთ / დიახ; inference-from-history; bare-yes-no-offer does NOT subscribe; „კიდევ" token-boundary regression); direct-intent (5 phrases write a row with no pending offer); honest confirmation (success says „ჩაგწერეთ სიაში"; already-subscribed says „უკვე ხართ სიაში" + no duplicate; failed write never says „ჩაგწერეთ"/„გამოგიგზავნით" and returns the technical fallback; missing-phone asks + no write + offer stays pending); Sheet fields (status=subscribed, consent=TRUE, platform, sender_id, age from lead); sanitiser safety net (strips when unconfirmed, keeps when confirmed, no-op when sender_id=None); broadcast safety (never calls `broadcast_event`, works with `LIVE_BROADCAST_ENABLED=false`, never calls `messenger_service.send_message`); adult-state reuse (`„მადლობა"` doesn't reset adult_age; child_age+adult_age coexist; context surfaces adult_age); pending-offer marker set when the LLM asks the offer; negative-with-pending → declined, no write.

Behaviour change: an explicit subscription consent/intent now ALWAYS performs the Sheets write deterministically (independent of the LLM), and the agent only ever confirms success after the row is written. The ADULT prompt was NOT changed (its honest-confirmation rule already exists; per the standing rule, no broad prompt polish before the production smoke). The existing deterministic UNSUBSCRIBE path is unchanged and still wins. Subscription never touches the broadcast path — `LIVE_BROADCAST_ENABLED=false` stays safe.

CRITICAL re-run: **EXECUTED — 22/22 ✅** (happy_path 6/6, booking 3/3, objection 3/3, comment 1/1, difficult 6/6, security 3/3) after the fix. 42 dedicated tests cover the new surface (incl. 6 adversarial-review regression tests); the existing 73 adult-subscription tests + adult-engine/broadcast-safety/live-polish suites stay green.

**🚨 BROADCAST SAFETY — do NOT run a real broadcast on a dev machine.** Outbound adult-event broadcasts are now DRY-RUN by default. `broadcast_event` only sends real Messenger/Instagram DMs when `LIVE_BROADCAST_ENABLED=true` (default **False**). Local/dev/test (which hold real Meta + Sheets credentials) can never DM real subscribers. Production must set `LIVE_BROADCAST_ENABLED=true` to enable fan-out.

**Broadcast Safety Incident + Fix (2026-06-11, pytest +8 tests):**

INCIDENT: a real Messenger DM was delivered to a subscribed user during patch work — „ახალი ზრდასრულთა ღონისძიება დაემატა: summer fest, თარიღი: 15 ივნისი 23:51, ლოკაცია: ლისი, ფასი: 100 ლარი, ბილეთების ბმული: https://x/future".

ROOT CAUSE: a broadcast test in the Adult Event Date Filter patch (`tests/test_adult_event_past_filtering.py::test_broadcast_allows_future_event_resolution`) called the REAL `adult_event_broadcast_service.broadcast_event("future_ev")` **without mocking** `sheets_service.list_event_subscribers` or `messenger_service.send_message`. On a dev machine with live Meta + Google Sheets credentials, it read the real `events` subscriber tab and sent a real DM. The „15 ივნისი 23:51 / ლისი / https://x/future" payload was MY TEST FIXTURE (`future = now+5 days`, computed at test runtime) — NOT the real Admin `summer_fest` (28 აგვისტო 19:00, min_age 19). So production source resolution is correct; the data mismatch was purely the test fixture leaking through an unmocked send. NOT an Admin/after-save auto-trigger (those are gated on the operator checkbox) and NOT a script.

FIX (broadcast-only; no booking/Calendar/Sheets-schema/email/webhook/model change):
- [app/config.py](app/config.py) — new `LIVE_BROADCAST_ENABLED: bool = False` (env `LIVE_BROADCAST_ENABLED`, default false).
- [app/services/adult_event_broadcast_service.py](app/services/adult_event_broadcast_service.py) — `broadcast_event(event_id_or_event, *, source="unknown")`. When `LIVE_BROADCAST_ENABLED` is False → DRY-RUN: resolves the event + loads candidates but NEVER calls `messenger_service.send_message` and NEVER marks subscribers notified; result carries `dry_run=True`, `source`, `dry_run_would_send`. Start/each-skip logged with `source` + `live`/`dry_run`.
- [app/routes/admin.py](app/routes/admin.py) — manual-broadcast route passes `source="admin_manual"`; after-save passes `source="after_save"` (after-save remains gated on the operator checkbox — unchanged).
- [tests/test_broadcast_safety_guard.py](tests/test_broadcast_safety_guard.py) **(NEW)** — dry-run default never sends (even with a subscriber + even if the transport is unmocked, an asserting-raise send is never reached); live flag (mocked transport) sends; `source` recorded; broadcast payload matches the resolved Admin event (28 აგვისტო, not a fixture date); past event blocked even when live; after-save checkbox gate.
- [tests/test_adult_event_past_filtering.py](tests/test_adult_event_past_filtering.py) — the two broadcast tests now MOCK `sheets_service.list_event_subscribers` + `messenger_service.send_message` and assert no real send; new dry-run-default test.
- [tests/test_adult_event_broadcast.py](tests/test_adult_event_broadcast.py) — the `kill_switch_on` fixture now also sets `LIVE_BROADCAST_ENABLED=True` so the existing 31 send-path tests still exercise the send logic — always against the MOCKED messenger.

RECIPIENTS: every `status=subscribed, consent=TRUE` row in the live Google Sheet `events` tab at that moment (the test passed no filter beyond the service default). The operator should review the `events` tab to see exactly who; going forward the dry-run default prevents recurrence. NO broadcast can now be sent from tests/dev.

**PARENT Reschedule State + Segment Override Patch (2026-06-10/11, pytest +25 tests):**

Live Redis audit (key `conversation:messenger:<sender_id>`, TTL ≈ 7 days, `child_age='14'` + name + phone + `calendly_booked` + `pending_booking.source=reschedule` all persisted, alongside `adult_age='30'` from earlier adult-event testing) proved state persistence WORKS — the three bugs were per-turn ROUTING, not memory:
1. **Adult misrouting** — `conversation_service` only re-classified the segment when it was NOT already PARENT/ADULT, so a conversation stuck on ADULT (from adult-event testing) routed „კონსულტაციის გადატანა მინდა" to the ADULT engine, which answered with an adult-event date. The escape hatch (`adult_llm_engine._user_wants_parent_flow`) only fired on hard camp keywords.
2. **Age re-ask** — after the eventual switch, the flow asked the child's age even though `child_age=14` was on the lead.
3. **Colloquial time bypass** — the LLM directly rejected an unqualified „8 საათზე" / „7 საათზე" as outside-hours WITHOUT calling `check_consultation_slot`, so the executor's PM normalization (8→20:00) never ran. (Weekend rule itself is correct: 13/14 June 2026 ARE Sat/Sun; `is_within_business_hours` returns `weekend` — the live bug was the LLM giving the HOUR as the reason and wrongly rejecting 15 June (Monday) 8→should be 20:00.)

Fixes (all deterministic, code-side; no Calendar/Sheets/email/prompt-section change):
- [app/services/conversation_service.py](app/services/conversation_service.py) — new `_is_parent_consultation_intent(message)` (closed set: კონსულტაცი / გადავიტანოთ / ჩავნიშნეთ / ბანაკზე გეუბნები / ბანაკის კონსულტაცი / …). When `segment=="ADULT"` and this matches, the segment is flipped to PARENT BEFORE routing — the lead's PARENT fields are preserved.
- [app/flows/parent_flow.py](app/flows/parent_flow.py) — `_strip_redundant_age_question_if_known` (never re-asks a known child age; replaces an age-only reply with a continue-the-flow line). `_repair_colloquial_hour_rejection` (+ `_resolve_repair_datetime_iso` + `_format_repaired_slot_response`): when the engine rejects an unqualified colloquial 1–9 hour (normalized to 13–21) as outside-hours/„არ ინიშნება", re-runs the deterministic `check_consultation_slot` on the PM-normalized datetime (date from the message, else the active reschedule/booked date) and answers from the REAL reason (available / weekend / busy / past). Both wired into the post-engine chain.
- [tests/test_parent_reschedule_state_and_time.py](tests/test_parent_reschedule_state_and_time.py) **(NEW)** — 25 tests: intent detection; sticky-ADULT→PARENT override preserves child_age/phone; genuine adult question stays ADULT; age-question stripped/replaced when known; datetime resolution (message date + time-only follow-up reuses active date); repair runs the check with 20:00 / reports weekend not hours / no-op for explicit morning / no-op without a rejection marker; Redis `from_dict` round-trip preserves child_age+name+phone+segment+pending reschedule, child_age and adult_age coexist.

Redis state-reuse audit result: ✅ connected; key `conversation:messenger:<sender_id>`; TTL refreshed to ~7 days (`settings.REDIS_TTL_SECONDS` on every `set_json`); `child_age` / `name` / `phone` / `segment` / `pending_booking` all present and round-trip through `Conversation.from_dict` (the restore path). Server/container restart preserves state (Redis persists; the in-memory dict re-hydrates on miss).

**Still pending before production (unchanged):** final live PARENT booking + reschedule smoke; adult subscription smoke; comment-routing smoke; Meta client asset transfer; WhatsApp; Railway. **Do NOT mark production green.** **Do NOT set `LIVE_BROADCAST_ENABLED=true` until intentionally broadcasting in production.**

**Adult Event Date Filter Patch (2026-06-10, pytest 1811 → 1840, +29 tests):**

Business rule: a PAST adult event must NEVER be offered to a user as available/current — even when `active=True` in the Admin Panel. Audit finding: `get_active_adult_events` filtered ONLY by `active` (and optional `min_age`); there was **no date comparison anywhere**, so a past-dated active event would surface in the adult DM list, the generic `#event` comment DM, the specific-event resolver, number selection, and broadcast. NOT a Calendar issue (Calendar is PARENT-only and untouched).

Files changed (5 production + 1 prompt + 2 tests):
- [app/services/admin_config_service.py](app/services/admin_config_service.py) — new deterministic date layer: `_parse_adult_event_datetime(date_text, now=)` parses Georgian „DD <month> [HH:MM]" / „<month>" / „2026 წლის ივლისი" returning `(datetime, granularity ∈ {time,date,month})` (stem-matched months tolerate declension/typos „ივნისიი"; explicit 4-digit year honoured; else current year, rolling +1 only when >180 days past — handles Dec→Jan). `is_adult_event_past(event, now=)` — past when: time < now / date's day ended / month ended. `_adult_event_visible_to_public(event, now=)` — hides inactive, past, AND non-empty-unparseable-date events (rule 6); EMPTY date_text shows (operator omitted deliberately; the section-fallback event can be dateless). `get_active_adult_events(user_age=None, *, include_past=False, now=None)` now excludes past by default (the chokepoint for the DM list + generic comment list + resolver pool); `include_past=True` keeps the full active pool so the comment resolver can still DETECT a past-event reference.
- [app/services/comment_service.py](app/services/comment_service.py) — `resolve_specific_adult_event` matches against `include_past=True` and downgrades a single match to reason `"past_event"` when the matched event is past; `send_dm_from_comment` sends the new ended-event DM (`_build_past_event_dm` → „ეს ღონისძიება უკვე დასრულებულია. შემიძლია მიმდინარე/მომდევნო ღონისძიებები გაგიზიაროთ." + the current future catalogue when one exists) and NEVER the past event's ticket link. The generic `#event` list builder uses the future-only chokepoint.
- [app/services/adult_event_broadcast_service.py](app/services/adult_event_broadcast_service.py) — `broadcast_event` blocks a past event with `reason="event_past"` (after the active check, before sending) — covers both the Admin manual/after-save broadcast AND the subscription „new event" fan-out.
- [app/agent/tools/adult_tool_executor.py](app/agent/tools/adult_tool_executor.py) — `_get_adult_event_details` returns `success=false, reason="event_past"` when a user names a past event by title (the future-only list never offered it, but a user can still type it) — never surfaces its ticket link.
- [app/agent/prompts/system_adult_v1.md](app/agent/prompts/system_adult_v1.md) — one new reason-branch line: `reason="event_past"` → send the ended-event message, never the ticket link/price.
- [app/routes/admin.py](app/routes/admin.py) — `_format_broadcast_summary` maps `event_past` to an operator-facing Georgian reason („ღონისძიების თარიღი უკვე გასულია…").
- [tests/test_adult_event_past_filtering.py](tests/test_adult_event_past_filtering.py) **(NEW)** — **29 tests** (frozen now = 2026-06-10 12:00 Tbilisi for pure fns; real-relative dates for integration): yesterday/today-date-only/today-earlier/today-later/tomorrow; Dec→Jan rollover; month-only & year+month („2026 წლის ივლისი") visible-as-future; visibility (active/past/inactive/empty/unparseable); `get_active_adult_events` future-only + `include_past`; number-selection future-only; generic comment list excludes past; all-past → empty list (fallback); specific past tag → `past_event` reason + ended-DM (no link); broadcast blocks past / allows future; executor details `event_past`.
- [tests/test_generic_adult_event_comment_list.py](tests/test_generic_adult_event_comment_list.py) — 1 stale test updated: the inactive-exclusion test's active event used a placeholder „1 იანვარი" (now correctly past-filtered); switched to a dateless active event so it tests inactive-exclusion as intended (date filtering has its own suite).

Behaviour: user-facing adult surfaces now show ONLY active + current/future events. A past event is hidden from the DM list, the generic `#event` comment DM, the specific resolver (which instead answers „this event has ended"), number selection, and all broadcasts. Month-only („ივლისი") and year+month („2026 წლის ივლისი") dates are supported (past once the month ends). Empty date_text still shows (operator's choice). Admin Panel still lists past events internally; only the user-facing agent excludes them.

Verification (real, this session): `pytest tests/ -q` → **1840 passed, 0 failed**; `test_agent.py` ✅. CRITICAL run (justification: this patch touches adult routing/tool core, so CRITICAL was run as a safety check even though the 22 CRITICAL scenarios contain no ADULT-event-list coverage): every scenario passes in isolation; per-sweep flakes were PARENT booking/difficult scenarios untouched by this patch (SC-11/12/46 each re-ran green isolated). booking 3/3, happy_path 6/6, comment 1/1, security 3/3 confirmed across runs.

Design note (rule 6): non-empty-but-UNPARSEABLE date_text is hidden from public lists (per spec) but NOT reported as „ended". The common legitimate formats (day+month, month-only, year+month, with optional time) all parse, so „unparseable" now means genuinely freeform prose. „All events past" falls through to the existing no-events fallback (`ADULT_NO_EVENTS_DM` — „ახლო მომავალში…"); the exact „ამ ეტაპზე აქტიური მომავალი ღონისძიება არ არის." wording was NOT swapped in to avoid touching the shared constant — the existing copy conveys the same „no current events".

NOT changed (explicitly protected): PARENT booking, Calendar service, Sheets schema, email/SMTP, webhook signature, OpenAI model, WhatsApp, Railway config.

**Georgian Colloquial Time Patch (2026-06-10, pytest 1768 → 1811, +43 tests):**

**Georgian Colloquial Time Patch (2026-06-10, pytest 1768 → 1811, +43 tests):**

Live bug: the SAME colloquial hour was interpreted inconsistently across two Messenger conversations. „12 ივნის 8 საათზე არის შესაძლებელი?" → 20:00 (correct) in account A, but „12 ივნის მინდა 8 სათზე თუ არის თავისუფალი" (typo „სათზე" + „მინდა" before the time) → 08:00 / outside-hours in account B. Root cause: the colloquial PM heuristic („1–9 → +12") lived ONLY in the legacy router (`parent_turn_router._parse_booking_datetime`); the live ENGINE path leaves the hour to the stochastic LLM, and NO deterministic code layer normalised the colloquial hour before `check_consultation_slot` / `book_consultation`. The typo „სათზე" (single „ა") was also unsupported by every parser. NOT a Calendar backend issue — Calendar is correct; the hour reaching it was wrong.

Files changed (3 production + 1 new test):
- [app/agent/services/timestamps.py](app/agent/services/timestamps.py) — new deterministic single source of truth: `extract_colloquial_hour(text) -> (hour24, minute) | None` and `apply_colloquial_time_to_iso(iso, text) -> iso`. Typo-tolerant `_COLLOQUIAL_HOUR_RE` covers საათზე / საათი / საათისთვის / საათისკენ / **სათზე / სათი (typo)** / სთ / სთ-ზე / სთზე / **8-ზე / 8ზე**. PM rule (PARENT booking, hours 10:00–21:00): unqualified 1–9 → +12 (13:00–21:00); 10/11/12 literal; explicit „დილ…"(morning) literal (08:00/09:00); explicit „საღამო…"(evening) 1–11 → +12 (საღამოს 8 → 20:00, საღამოს 10 → 22:00); explicit HH:MM always literal, never remapped. A bare hour with no suffix is trusted ONLY when a morning/evening qualifier is present („საღამოს 8" → 20:00), guarded against age phrases („8 წლის").
- [app/agent/tools/parent_tool_executor.py](app/agent/tools/parent_tool_executor.py) — `_normalise_datetime_iso_from_message` (the chokepoint called by `_check_consultation_slot`, `_book_consultation`, AND the reschedule branch — Part 2 #9) gains a SECOND deterministic pass after the existing relative-day override: `apply_colloquial_time_to_iso(iso, self.user_message)`. This corrects the hour even when the LLM passed 08:00, regardless of contact/booking state. Because `_check_consultation_slot` echoes the normalised `datetime_iso` in its result, the LLM's spoken reply now reflects 20:00 too.
- [app/flows/parent_turn_router.py](app/flows/parent_turn_router.py) — legacy `_parse_booking_datetime` (used by the engine's compound-booking fallback `_maybe_commit_pending_booking_engine`) now delegates its time parse to the shared `extract_colloquial_hour`, so the typo/variant + PM behaviour is identical everywhere. Date logic unchanged.
- [tests/test_georgian_colloquial_time_parsing.py](tests/test_georgian_colloquial_time_parsing.py) **(NEW)** — **43 tests**: the 14 spec cases + variants (8 საათზე / 8 სათზე / 8-ზე / 8 საათისთვის / 8 სთ-ზე / საღამოს 8 / 8 საათი); morning stays morning (დილის 8 → 08:00); საღამოს 10 → 22:00; 10/11/12 literal; explicit HH:MM literal; age phrases („8 წლის") never parsed as time; `apply_colloquial_time_to_iso` preserves date + overrides hour; executor chokepoint corrects typo hour to 20:00 + keeps correct LLM time + morning not remapped + active-date time-only follow-up + contact-state-irrelevant; legacy router parser parity.

Behaviour: in PARENT booking context the colloquial hour is now deterministic and identical across all users, all booking states (phone-known / phone-missing / name-from-Meta / booked-user reschedule), typo variants, date+time messages, and time-only follow-ups. „დილის 8" stays 08:00 (outside hours); „საღამოს 8" → 20:00; explicit „HH:MM" honoured literally. If only a time is given on a follow-up, the LLM-carried active date is preserved and only the hour is normalised; no date is invented.

Verification (real, this session): `pytest tests/ -q` → **1811 passed, 0 failed**; `test_agent.py` ✅; CRITICAL **22/22** clean (booking 3/3).

Prompt bloat audit (Part 5): `system_parent_v2.md` = 108,632 bytes ≈ **36K characters** (Georgian ≈ 3 bytes/char), 446 lines; the engine prompt-size cap test asserts `< 48,000 chars` and PASSES (~12K headroom). The prompt has NO explicit colloquial-PM rule (only examples like „3 საათზე") — which is exactly why the LLM was inconsistent; the new code layer is now the deterministic source of truth. **Prompt NOT cleaned** in this task: the time rules in the prompt also cover business hours / half-hour / relative dates / slot selection (not all code-backed), and the LLM still composes the spoken reply — removing guidance risks a spoken/checked mismatch. Per the task's guard ("if unsure, do not clean prompt; stabilizing time parsing is higher priority"), no prompt section was deleted.

NOT changed (explicitly protected): Calendar service, Sheets schema, adult events, comment routing, webhooks, OpenAI model, SMTP config. No Guardrails/token-waste reintroduction; no prompt deletion.

**Email Content Cleanup Patch (2026-06-10, pytest 1750 → 1768, +18 tests):**

**Email Content Cleanup Patch (2026-06-10, pytest 1750 → 1768, +18 tests):**

The manager notification email arrives, but `lead.challenge` (captured from natural chat) leaked filler + factual questions into the „ინტერესი / გამოწვევა" field and the „მოკლე რეზიუმე". Live bad output: „ინტერესი / გამოწვევა: მეგობრები, განვითარება, ასევე ეკრანიდან დისტანცია, ასევე მაინტერესებს ბანაკის დეტალებში როდის ტარდება…" with the same raw question repeated in the summary. Email-content formatting only — no Calendar / Sheets schema / adult / comment / webhook / OpenAI-model / SMTP / booking-flow change.

Files changed (1 production + 1 new test):
- [app/services/notification_service.py](app/services/notification_service.py) — new deterministic email-rendering helpers: `_clean_challenge_for_email(raw)` (splits on commas / „ასევე"; drops factual-question clauses via `_EMAIL_QUESTION_STEMS`; strips filler via `_EMAIL_CHALLENGE_FILLER` — „ასევე მაინტერესებს" / „მაინტერესებს" / „კი მინდა" / „ჩაწერა მინდა" / „კონსულტაცია მინდა" / „დეტალები" / „მომწერეთ" / „პირობებში რა იგულისხმება" / …; canonicalises a few noisy variants — any „ეკრან…" clause → „ეკრანთან დროის შემცირება"; dedupes; returns „" when nothing meaningful remains). `_extract_additional_question(raw)` pulls a cleaned factual question (trailing „?" ensured). `_parent_detail_lines` now renders the CLEANED challenge under „ინტერესი / გამოწვევა"; when empty it prints the explicit „არ არის მითითებული" placeholder (rule 7, never invents); a factual question (if any) is surfaced on a separate optional „დამატებითი კითხვა:" line (rule 4, never mixed into goals). `_build_parent_summary` weaves in the cleaned goals, not the raw chat text (no duplication). `lead.challenge` itself is NOT mutated — the Sheets/CRM write is unchanged.
- [tests/test_manager_email_content_cleanup.py](tests/test_manager_email_content_cleanup.py) **(NEW)** — **18 tests**: raw filler/question absent from cleaned challenge + email body; parent goals preserved normalised („მეგობრები, განვითარება, ეკრანთან დროის შემცირება"); clean phrase preserved verbatim (protects existing fixture); factual question separated into the optional field and absent from challenge; optional line present/absent correctly; summary excludes raw chat text + uses cleaned goals; unknown challenge → „არ არის მითითებული"; pure-filler challenge → placeholder (never invented); structured fields (age / name / phone / booked datetime) still present; `lead.challenge` not mutated; empty/None inputs clean to „".

Live test case (from the transcript): raw challenge „მეგობრები, განვითარება, ასევე ეკრანიდან დისტანცია, ასევე მაინტერესებს ბანაკის დეტალებში როდის ტარდება" →
- „ინტერესი / გამოწვევა: მეგობრები, განვითარება, ეკრანთან დროის შემცირება"
- „დამატებითი კითხვა: როდის ტარდება?"
- summary clean, no raw text, no duplication.

Verification (real, this session): `pytest tests/ -q` → **1768 passed, 0 failed**; `test_agent.py` ✅. CRITICAL NOT re-run — justification below.

CRITICAL not re-run: the change is confined to `notification_service.py` email-rendering helpers (string formatting of the manager email). No booking flow, engine, executor, Calendar, Sheets schema, prompt, or tool contract is touched, so the CRITICAL booking / objection / security buckets cannot be affected. The 29 existing email-wording tests + 13 notification tests + 18 new tests all pass. Layout note: the existing inline „label: value" format is preserved (the spec's multi-line mock is illustrative) to avoid regressing the 29 wording tests; all content rules (1–7) are satisfied.

**Still pending before production (unchanged):**
- ⏳ **Full live PARENT booking smoke (create path)** — busy-slot rejection confirmed live; a real confirmation must create Calendar event + Sheet row + fire the manager email end-to-end.
- ⏳ Adult subscription smoke, comment-routing smoke, Meta client asset transfer, WhatsApp live credentials, Railway deploy + env.
- **Do NOT mark production green** until the final live smoke confirms: Calendar event + Sheet row + manager email + adult subscription + comment routing.

**Live Smoke Followup Patch (2026-06-10, pytest 1717 → 1750, +33 tests):**

**Live booking smoke — partial (2026-06-10):** busy-slot rejection **worked live** — `11 ივნისს 16:00` was correctly detected as **unavailable** (overlaps the real busy block 13:15–17:45) and `11 ივნისს 18:00` was offered as free. Confirms the Calendar FreeBusy path end-to-end live. The two wording bugs below were the remaining live findings and are now fixed.

**Live Smoke Followup Patch (2026-06-10, pytest 1717 → 1750, +33 tests):**

Two PARENT booking-confirmation wording bugs from a live transcript. Smallest deterministic changes; no Calendar / Sheets / email / webhook / OpenAI-model / system-prompt change.

Files changed (2 production + 1 new test):
- [app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) — **Part 1**: `_user_confirmed_booking` no longer requires a whole-message exact match. It now also accepts a strong confirmation phrase at the START of the leading clause (new `_STRONG_CONFIRM_LEAD_PHRASES`), with a negation guard (new `_CONFIRM_NEGATION_TOKENS`: „არ "/„არა"/„ვერ "), so „კი მაწყობს ეს დრო, მენეჯერი რომელ საათამდე მუშაობს?" registers as a confirmation while „არ მინდა" / „კი, მაგრამ ჯერ ფასი…" / „მინდა ვიცოდე ფასი" do not. Bare „კი"/„დიახ"/„მინდა" stay exact-match only. `_BOOKING_OFFER_STEMS` extended with the real offer wording („ჩავნიშნავ", „დამიდასტურეთ", „თავისუფალია") so `_last_bot_offered_booking` recognises the brand slot offer („<date>, <time> საათი თავისუფალია. … დამიდასტურეთ და კონსულტაციას ჩავნიშნავ."). Together these make the existing „proceed directly to booking, do NOT re-ask" sales-context hint fire when the user confirms with a trailing question. **Part 3**: the eligible-age sales-context hint now asks ONE clean goal question („რა არის მთავარი, რის მიღებაც გსურთ ბანაკიდან — …") only when `lead.challenge` is empty, and explicitly tells the model not to let goal capture block an explicit booking; once the goal is known it instructs „მოტივაცია ხელახლა ნუ ჰკითხავ." (No system-prompt edit — this is the per-turn assembled context hint, so the 48 KB prompt-size cap test is unaffected.)
- [app/flows/parent_flow.py](app/flows/parent_flow.py) — **Part 2**: new `_strip_unwarranted_thanks_in_booking_confirmation(conversation, message, response)` + `_user_message_has_thanks` + `_THANKS_OPENER_PATTERNS`. Wired into the post-engine chain right after `_trim_booking_success_response`. Strips a leading „მადლობა თქვენ" / „გმადლობთ" / „დიდი მადლობა" opener from a **booking-confirmation** response when the user's current message contains NO thanks token. Pass-through when the user actually thanked (warm closing preserved) or when the response is not a booking confirmation. The deterministic commit path (`_maybe_commit_pending_booking_engine`) already produces „მივიღე, {name}. კონსულტაცია … ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ." (never „მადლობა თქვენ"), so this strip targets the LLM-generated confirmation path.
- [tests/test_parent_booking_live_smoke_followup.py](tests/test_parent_booking_live_smoke_followup.py) **(NEW)** — **33 tests**: offer-wording recognised as offer; confirmation+question detected (6 phrasings); bare confirmations still detected; non-confirmations / negations / soft-objections rejected (7); proceed-hint injected not re-ask; thanks opener stripped for non-thanks confirmation (3) / preserved when user thanked (4) / no-op on non-booking response; `_user_message_has_thanks`; eligible+no-challenge asks goal question; eligible+challenge does not re-ask; confirmation branch takes priority over goal question.

Root causes:
1. **Repeated confirmation ask** — `_user_confirmed_booking` matched the WHOLE message exactly, so a confirmation with an appended question never registered; AND `_BOOKING_OFFER_STEMS` did not contain the actual offer wording („ჩავნიშნავ"/„დამიდასტურეთ"/„თავისუფალია"), so `_last_bot_offered_booking` also returned False. With both False the „proceed directly" hint never fired → the LLM answered the question and re-asked for confirmation.
2. **„მადლობა თქვენ" on non-thanks confirmation** — the LLM occasionally prefixes a booking confirmation with „მადლობა თქვენ" even when the user only said „კი მინდა"; nothing stripped it on the LLM path.

Verification (real, this session): `pytest tests/ -q` → **1750 passed, 0 failed**; `test_agent.py` ✅; CRITICAL **22/22** clean.

**Still pending before production (unchanged + this session):**
- ⏳ **Manager notification email** — `MANAGER_EMAIL` env was corrected; SMTP send must be live re-tested (separate task; not part of this patch). NOTE: a standalone SMTP test on 2026-06-10 succeeded after the App Password was fixed, but the end-to-end booking→email path is not yet confirmed.
- ⏳ **Full live PARENT booking smoke** (Calendar event + Sheet row created on a real confirm). Busy-slot rejection is confirmed live; the create path on a real confirmation is the remaining check.
- ⏳ Meta client asset transfer, WhatsApp live credentials, Railway deploy + env.
- **Do NOT mark production green** until the final live smoke confirms: Calendar event + Sheet row + manager email + adult subscription + comment routing.

NOT changed (explicitly protected): Calendar service, Sheets schema, email/SMTP code, adult events / comment routing / webhooks / OpenAI model, system prompt. No broad prompt polish; no Guardrails/token-waste reintroduction.

**Pending before any production / Railway go:**
- ⏳ **Live PARENT booking through real Meta is NOT verified** — the LLM's tool-call discipline (calling `check_consultation_slot` before stating a time is free) must be smoke-tested against the real channel. See the booking-conflict smoke script below.
- ⏳ Railway deploy, Meta App Review (`pages_manage_engagement`), WhatsApp live credentials, client production assets — all unchanged, all operator action.
- **Do NOT mark production green until the live Meta booking-conflict smoke passes.**

**⚠️ Process warning — do NOT add broad prompt-polish patches before the production smoke.** A prior broad "Conversation Guardrails / token-waste" polish patch caused live PARENT booking regressions and had to be rolled back. The audit also found CRITICAL had silently drifted to 21/22 (SC-06) while docs claimed 22/22. Keep changes narrow, deterministic, and test-gated until the live smoke is done.

**Calendar audit note (2026-06-09):** the Calendar backend is **working and live-verified** (read-only FreeBusy against the client calendar correctly flagged a real busy block 2026-06-11 13:15–17:45; conflict logic, permissions, and timezone all correct; `check_consultation_slot` AND `book_consultation` both re-check availability — a busy slot cannot be booked). `GOOGLE_CALENDAR_ID`, `BOOKING_CALENDAR_ID`, `BUSY_CALENDAR_IDS` all point to the SAME client calendar. The reported "busy slot still bookable" issue did NOT reproduce at the backend level; the remaining unknown is purely live LLM behavior (does it call the check tool before saying "თავისუფალია"?) — that is what the live smoke must confirm. `calendar_service.py` was NOT modified.

**P0 Stabilization Patch (2026-06-09, pytest 1695 → 1717, +22 tests):**

Fixes the one flaky CRITICAL scenario surfaced by the full system audit: **SC-06 "Ineligible Age — 8 წლის"** (was ~40% pass). No Calendar / Sheets / Adult-subscription / Comment-routing / OpenAI-model change. No broad prompt polish.

Root cause: `parent_flow._strip_consultation_cta_if_ineligible` only appended the manager-handoff line (which carries both "ასაკი" and "მენეჯერ") WHEN a booking CTA was present in the LLM reply (early-return when no CTA matched). For a sub-minimum-age child, a CTA-free-but-vague LLM reply could omit the explicit age boundary and/or the manager offer, intermittently failing the assertion `("9" OR "ასაკი") AND "მენეჯერ"`.

Files changed (1 production + 1 new test):
- [app/flows/parent_flow.py](app/flows/parent_flow.py) — new `_camp_age_bounds()` helper + `_INELIGIBLE_YOUNG_MESSAGE_TEMPLATE` + `_ensure_ineligible_young_age_message(conversation, message, response)`. Wired into the post-engine chain immediately after `_strip_consultation_cta_if_ineligible`. On the turn the parent discloses a child age **below `age_min`** (gated on: lead age-status `ineligible` AND parsed age `< age_min` AND the CURRENT message carries that same age — the disclosure-turn guard), the response is replaced with a fixed message: „ბანაკში მონაწილეობა შესაძლებელია 9–17 წლის ბავშვებისთვის. ამ ასაკისთვის ბანაკში ჩაწერას ვერ შემოგთავაზებთ. თუ გსურთ, მენეჯერთან დაგაკავშირებთ და დამატებით ინფორმაციას მოგაწვდიან." Scope is intentionally narrow: only `age < age_min`. The over-age (18+) path is untouched (handled by the adult-switch / over-17 wording — SC-07 unaffected) and eligible 9–17 ages pass straight through. The disclosure-turn guard prevents the message repeating on later thank-you/follow-up turns.
- [tests/test_ineligible_young_age_p0.py](tests/test_ineligible_young_age_p0.py) **(NEW)** — **22 tests**: under-min ages 3–8 each return the canonical (with "9"/"17"/"ასაკი"/"მენეჯერ"/"ვერ შემოგთავაზებთ", no forbidden "ჩავნიშნ"/"კონსულტაციაზე ჩაგწერთ"); exact SC-06 assertion shape; eligible 9/10/14/16/17 pass through unchanged; boundary 9 and 17 eligible; over-age 18/25/40 pass through (adult path preserved); unknown age pass-through; no-over-fire on later thank-you turn / on a time message ("16 საათზე"); re-fires if age restated; end-to-end through `parent_flow.handle` with the engine mocked to the vague SC-06 failure mode → canonical fires; eligible 14 e2e not overwritten.

Verification (real, this session):
- `pytest tests/ -q` → **1717 passed, 0 failed**.
- `test_agent.py` → ✅ green.
- SC-06 isolated **5/5 PASS** (was ~40%).
- CRITICAL full sweep → **22/22** (clean run). One earlier sweep showed 21/22 due to a transient OpenAI **429 TPM rate-limit** on SC-12; SC-12 passes isolated and in the clean re-run — not a regression.

NOT changed (explicitly protected): Calendar service, Sheets service, Adult subscription/broadcast, Comment routing, Instagram webhook/signature, OpenAI model config. No broad prompt polish; no Guardrails/token-waste reintroduction.

**Live Polish Patch (2026-06-09, pytest 1668 → 1695, +27 tests):**

Wording and flow-polish fixes based on live PARENT booking session issues. No Calendar / Sheets / webhook / auth logic changed.

Files changed (3 production + 1 new test + 1 existing test update):

- [app/agent/llm/parent_llm_engine.py](app/agent/llm/parent_llm_engine.py) — **Part 1**: New `_BOOKING_CONFIRMATION_PHRASES` frozenset + `_BOOKING_OFFER_STEMS` + `_THANKS_PHRASES` constants. New helper functions `_last_bot_offered_booking()`, `_user_confirmed_booking()`, `_user_said_thanks()`. Updated `_build_sales_context()` to: (a) detect confirmation-after-offer and inject "proceed directly" hint when user says კი/მინდა/კიმინდა/etc. after bot offered booking — prevents repeated "გსურთ?" question; (b) detect "მადლობა" and inject correct context-aware closing hint (booked → "კონსულტაცია ჩანიშნულია…"; subscribed → new-event notification; general → "თუ კიდევ დაგჭირდებათ…"). **Part 3**: 3 new `FORBIDDEN_PHRASE_REPLACEMENTS` entries: "მიხარია ნომრის მიღება" → "ნომერი მივიღე", "მოხარული ვარ ნომრის მიღებით" → "ნომერი მივიღე", standalone "სიამოვნებით." → "" (stripped).
- [app/agent/llm/adult_llm_engine.py](app/agent/llm/adult_llm_engine.py) — **Part 3**: Added standalone "სიამოვნებით." → "" to `ADULT_FORBIDDEN_PHRASE_REPLACEMENTS` (mirrors parent engine).
- [app/agent/prompts/system_parent_v2.md](app/agent/prompts/system_parent_v2.md) — **Part 1**: Added "კიმინდა" (joined form) + additional confirmation phrases (მაწყობს, კი მაწყობს, ვადასტურებ, დამიდასტურეთ) to the Booking Intent Flow CRITICAL block; added explicit rule banning repeated confirmation question after user says yes. **Part 2**: New "კონტაქტ-ინფო კონფიდენციალობის წესი" section: whenever asking for phone, always include "თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის და საჯაროდ არ გამოქვეყნდება." — two variants (name known / name unknown), no duplication within one message. **Part 4**: Updated "მადლობის წესი" with specific context-aware closings (booked / subscription / general) and explicit ban on "სიამოვნებით." as standalone response.
- [tests/test_live_polish_booking_wording.py](tests/test_live_polish_booking_wording.py) **(NEW)** — **27 tests**: confirmation normalization (5); `_build_sales_context` confirmation-after-offer detection (3); privacy wording in system prompt (5); banned phrases in sanitiser (8); context-aware thank-you closings (6).
- [tests/test_parent_llm_engine.py](tests/test_parent_llm_engine.py) — prompt-size cap raised 46 KB → 48 KB to accommodate the ~0.7 KB of new wording policy text.

Issues resolved:
1. ✅ **"კიმინდა" normalized** — joined form treated identically to "კი მინდა" as booking confirmation.
2. ✅ **No repeated consultation confirmation** — after bot offered and user said yes, booking flow continues directly without re-asking.
3. ✅ **Privacy wording added to phone collection** — privacy sentence always included when asking for phone.
4. ✅ **"მიხარია ნომრის მიღება" removed** — replaced with "ნომერი მივიღე".
5. ✅ **"სიამოვნებით." standalone banned** — stripped in both PARENT and ADULT sanitisers; system prompt provides context-aware closing rules.
6. ✅ **Context-aware thank-you closings** — booked / subscription / general contexts each get specific closing hint.

NOT changed (explicitly protected):
- Calendar service, Sheets service, Adult event subscription/broadcast core.
- Comment routing, Instagram webhook/signature, OpenAI model config.
- Google env/config, Admin Panel logic, all guardrails/token-waste rollback state.

**Client Smoke Regression Patch (2026-06-09, pytest 1640 → 1668, +28 tests):**

Live bugs surfaced during client local smoke test. Five root causes identified and fixed:

Files changed (2 production + 1 new test + 1 existing test update):
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — **Fix 1**: 4 new entries in `FORBIDDEN_PHRASE_REPLACEMENTS` banning "კომპიუტერის მეხსიერების მიხედვით" and "ჩემი მეხსიერების მიხედვით" (LLM hallucination phrase exposing internal memory state). Both forms with and without trailing comma; replaced with "ამ ეტაპზე".
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — **Fix 2** (Booking Intent Flow CRITICAL block): when user confirms booking intent ("კი მინდა", "ჩამწერეთ", etc.) goal is `book_consultation`, NOT `request_manager_callback`. Two acceptable paths documented: (A) slots first → name/phone → book; (B) name/phone first → slots → book. FORBIDDEN: calling `request_manager_callback` after collecting contact info without a selected slot. **Fix 3** (Contact Info CRITICAL block): "phone + name text" in same message is valid (e.g., "595999733 ნიკა") — backend extracts phone automatically; LLM must NOT say "ნომერი სწორად ვერ ამოვიკითხე" in this case. If `name=X` is in context and X ≠ "—", name is already known; phone alone completes contact info.
- [tests/test_parent_client_booking_smoke_regression.py](ai-agent/tests/test_parent_client_booking_smoke_regression.py) **(NEW)** — **28 new tests**: parser handles phone-before-name and name-before-phone (10 tests); bad phrase banned from sanitiser (4 tests); system prompt contains required CRITICAL blocks (6 tests); "კი მინდა" calls `get_available_slots` not direct manager callback (2 tests); phone-only accepted when name already on lead (2 tests); no fake-booking claimed without Calendar success (2 tests); baseline parser / sanitiser sanity (2 tests).
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — prompt-size cap raised 44 KB → 46 KB to accommodate the new ~1.6 KB policy text. Comment documents the reason.

Root causes (all in LLM behavior, not service code):
1. **"კი მინდა" → manager callback**: LLM collected phone then called `request_manager_callback` because no slot was selected — it treated the booking as a manager callback request. Fixed by explicit rule: after booking intent confirmed, `request_manager_callback` is FORBIDDEN without a selected slot.
2. **"595999733 ტესტ" rejected**: LLM hallucinated "ნომერი სწორად ვერ ამოვიკითხე" when given phone + trailing name text, even though the parser would have accepted it. Fixed by explicit rule: "phone followed by name text is valid".
3. **"კომპიუტერის მეხსიერების მიხედვით"**: LLM hallucination phrase exposing internal state. Fixed by sanitiser entry.
4. **No Calendar event / Sheet row**: Direct consequence of Issue 1. `request_manager_callback` does write to Sheets but does NOT create a Calendar event. `book_consultation` was never reached. Fixed by Issue 1 fix.
5. **Meta/profile name not reused**: Added explicit rule that if `name=X` is in the context (not "—"), phone alone completes contact info — no re-asking for name.

Behaviour verified:
- `_parse_name_phone("595999733 ტესტ")` → ("ტესტ", "595999733") — parser was ALWAYS correct; the bug was LLM-side hallucination.
- Google Sheet append: `create_lead()` ✅ LIVE VERIFIED with client credentials.
- Google Calendar create/delete: `create_event()` + `cancel_calendar_event()` ✅ LIVE VERIFIED with client credentials.
- CRITICAL scenario sweep: **22/22 ✅** (re-run 2026-06-09 after patch, all pass).

**~~Conversation Guardrails + Token Waste Control + Adult Event Registration Clarification~~ — ROLLED BACK 2026-06-09:**

**Reason for rollback:** Live PARENT booking regression observed after the Guardrails patch shipped. User message `"კონსულტაციის ჩანიშვნა მინდა ბანაკთან დაკავშირებით"` triggered qualification/challenge questions instead of the booking flow. Root cause: the pre-LLM manager-request shortcut and low-value guard introduced hidden side-effects on PARENT booking flow paths. Decision: roll back entirely before client production setup; redesign as a smaller, isolated patch after production smoke test.

**What was rolled back (all 4 production files + tests):**
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — removed 15 scolding-phrase entries from `FORBIDDEN_PHRASE_REPLACEMENTS`; removed `_PARENT_EXPLICIT_MANAGER_REQUEST_PHRASES`, `_parent_is_explicit_manager_request()`, `_PARENT_LOW_VALUE_EXACT`, `_PARENT_EMOJI_ONLY_RE`, `_parent_is_low_value_message()`, `_LOW_VALUE_ACK_PARENT`; removed pre-LLM manager-request and low-value checks from `run_parent_llm_turn`.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — same removals for ADULT engine; `run_adult_llm_turn` restored to pre-Guardrails order.
- [app/services/adult_subscription_service.py](ai-agent/app/services/adult_subscription_service.py) — removed `_STANDALONE_CONSENT_TOKENS` frozenset and `_consent_phrase_matches()` helper; `is_subscription_consent_phrase` restored to plain `phrase in lowered` substring matching.
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — removed "სუბსქრიფციის vs კონკრეტულ ღონისძიებაზე რეგისტრაციის განსხვავება — CRITICAL" block.
- [tests/test_guardrails_token_waste.py](ai-agent/tests/test_guardrails_token_waste.py) — **deleted** (87 tests removed).
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — `test_manager_request_without_phone_does_not_notify` assertion restored to pre-Guardrails form: `"ნომერ" in out`.

**⏳ STILL OPEN — Guardrails / token-waste (postponed):**
- Conversation guardrails need redesign with narrower scope after client production setup and smoke test.
- Token-waste control (low-value message bypass) postponed until production baseline is confirmed.
- Manager handoff wording improvement postponed (can be done as isolated sanitiser-only patch later).
- Adult subscriber vs specific event registration clarification postponed (prompt-only, isolated patch later).

**Generic `#event` Comment → Active Adult Events List Patch (2026-06-09, pytest 1615 → 1640, +25 tests):**

Live-bug: a comment on a post tagged only with the generic `#event` hashtag (no specific event tag and no matching `facebook_post_id`) routed through `_build_adult_rich_dm()` which reads the legacy `data/events.txt`. With that file empty in production the agent answered with the misleading „ახლო მომავალში ღონისძიებების განრიგს გამოვაქვეყნებთ…" copy even though Admin Panel had ACTIVE adult events. The user-visible symptom: a comment of „ფასი?" / „სად ტარდება?" / „მაინტერესებს" / „ბმული?" under a `#event` post produced the no-schedule fallback while real events sat in `adult_events.events[]`.

Files changed (1 production + 2 test files):
- [app/services/comment_service.py](ai-agent/app/services/comment_service.py) — three new helpers: `_render_event_for_list(event, index)` renders ONE event entry (title / date / location / price / link) with the same `_format_event_price` price rule the specific-event DM uses (numeric `price_text` → „<n> ლარი", `price_gel` fallback); `_build_active_events_list_block(events)` joins up to 5 (`_ACTIVE_EVENT_LIST_MAX`) rendered entries; `_build_active_adult_events_list_dm()` is the public entry — loads active events via `admin_config_service.get_active_adult_events()` (when caller doesn't inject the list), renders the block, then substitutes it into the operator-editable `adult_events_comment_dm` template via the `{events_list}` placeholder. Defensive guard: empty render OR residual literal `{events_list}` token OR rendered text missing the events block → falls back to a hard-coded Georgian frame so the literal placeholder NEVER reaches the user. Returns `""` when no active titled events exist so the caller can fall through to `_build_adult_rich_dm()`. `send_dm_from_comment` now tries the new list helper BEFORE `_build_adult_rich_dm()` on BOTH branches: (a) admin-section path when `section.type == "adult_events"`, (b) legacy hashtag-fallback path. Generic `#event` + no specific match + active events present → list DM; generic `#event` + no specific match + no active events → existing fallback. Specific-event mapping (Priority A/B/C) runs FIRST and is untouched — `#event #fast` still wins.
- [tests/test_generic_adult_event_comment_list.py](ai-agent/tests/test_generic_adult_event_comment_list.py) **(NEW)** — **25 tests** across the list-builder unit surface (title / date / location / price / link rendering; numeric `price_text` → „<n> ლარი"; `price_gel` fallback; `payment_terms` link fallback; missing-field skipping; inactive-event exclusion; empty-list return); `{events_list}` placeholder substitution (template path renders correctly; missing template falls back to frame; operator-removed placeholder falls back; literal `{events_list}` NEVER survives; multi-event placeholder variants); `send_dm_from_comment` routing (generic `#event` + active events → list; generic `#event` + no active events → fallback; no fabricated schedule); specific-event priority regression (Priority A `facebook_post_id` still wins; Priority B tag-in-comment still wins; Priority C tag-in-caption still wins); Instagram + Facebook platform parity; camp routing untouched (`#ბანაკი` still uses `_build_parent_rich_dm`); interest-intent detector still matches the four live-bug example phrases.
- [tests/test_comment_flow.py](ai-agent/tests/test_comment_flow.py) — `_run_handle_comment` + `_run_handle_comment_for_platform` helpers gained a `monkeypatch.setattr(...admin_config_service, "get_active_adult_events", lambda *a, **kw: [])` line so the legacy `settings.EVENTS`-driven fallback path stays exercised by the existing 55 comment-flow tests (none of which had ever mocked admin_config). The new active-events list path only fires when admin config has events.

Behaviour change:
- Generic `#event` (or any active `adult_events`-tagged post) where the comment doesn't identify a specific event → DM lists every active adult event (capped at 5) with title / date / location / price / link per entry. The `adult_events_comment_dm` template's `{events_list}` placeholder is the single substitution point so the operator can edit the framing copy in Admin Panel without touching code.
- When NO active adult events exist (everything inactive OR `events[]` empty) the existing „ახლო მომავალში ღონისძიებების განრიგს გამოვაქვეყნებთ…" fallback fires — the patch deliberately does NOT promise events that don't exist.
- Specific-event priority order is unchanged: `facebook_post_id` (A) → tag-in-comment (B) → tag-in-caption (C) → generic active-events list (NEW D) → no-schedule fallback (legacy E, only when no active events). `#event #fast` still sends the exact „fast"-tagged event.
- No business logic outside `comment_service` changed. PARENT booking / Calendar / Sheets / OpenAI model / scenario runner / Instagram signature verifier / Adult event subscription + broadcast / WhatsApp manager notification all untouched.

CRITICAL re-run: NOT executed. Justification: the patch is comment-routing-only (new list builder + branch override in `send_dm_from_comment`); PARENT happy-path / objection / booking / security CRITICAL scenarios do not pass through `_build_active_adult_events_list_dm`. 25 dedicated tests cover the new surface; the 55 existing comment-flow tests cover the legacy fallback path (now via the `get_active_adult_events=[]` stub). Operator approval gate unchanged.

**Instagram Webhook Signature + Payload Diagnostic Patch (2026-06-09, pytest 1593 → 1615, +22 tests):**

Live-bug: with the Instagram product activated in Meta Developer dashboard and the `code.shelf` Instagram account connected, inbound Instagram webhook POSTs were returning 403 with `[webhook] signature rejected` — Meta signs Instagram callbacks with a DIFFERENT app secret than the Facebook Page callbacks, so the single-secret verifier ran HMAC against the wrong key and rejected every IG request.

Files changed (3 production + 1 new test file):
- [app/config.py](ai-agent/app/config.py) — two new `Settings` fields with `from_env` readers: `INSTAGRAM_APP_SECRET: str = ""` (read from `INSTAGRAM_APP_SECRET` env, falls back to `IG_APP_SECRET`) and `INSTAGRAM_ACCESS_TOKEN: str = ""` (read from `INSTAGRAM_ACCESS_TOKEN` env, falls back to `IG_ACCESS_TOKEN`). Existing `META_APP_SECRET` / `MESSENGER_APP_SECRET` plumbing untouched.
- [app/routes/webhook.py](ai-agent/app/routes/webhook.py) — new `_candidate_app_secrets()` helper returns the ordered `[(label, secret)]` list of configured secrets (privacy-safe labels — never the values). `_verify_meta_signature(raw, header)` rewritten to try each candidate via constant-time `hmac.compare_digest`; returns `(accepted, label)` where label is the privacy-safe id of the secret that matched. `receive_webhook` logs `[webhook] signature accepted via facebook_app_secret` / `instagram_app_secret` / `[webhook] signature rejected: no configured secret matched`. New `_summarise_payload_fields(payload)` returns a privacy-safe dict (`object` / `entries` / `fields` / `supported`) for a single post-acceptance log line. New `_SUPPORTED_PAYLOAD_FIELDS` frozenset (`messaging`, `messages`, `changes`, `standby`) defines which top-level entry keys the existing handler routes on. Instagram payloads with unsupported fields produce a single `[webhook] instagram payload accepted but unsupported fields=...` warning and the handler no-ops — Meta receives a 200 so it does not retry-storm. **Never logs**: the raw body, signature header value, computed digest, app secrets, access tokens, sender ids, message text, phone numbers.
- [app/main.py](ai-agent/app/main.py) — boot-time visibility lines: `🔐 webhook secrets: facebook_app_secret=set|NOT set instagram_app_secret=set|NOT set` and `🔐 instagram access token: set|NOT set (outbound DM disabled)`. Prints presence only — never the actual values.
- [tests/test_instagram_webhook_signature.py](ai-agent/tests/test_instagram_webhook_signature.py) — **22 new tests**: Facebook secret still accepted (incl. legacy `MESSENGER_APP_SECRET` alias); Instagram secret accepted via `INSTAGRAM_APP_SECRET`; Instagram-only configuration; wrong signature returns 403; missing signature returns 403 when at least one secret is set; wrong algo prefix (`sha1=...`) returns 403; both secrets configured — either signature valid; fail-open when no secret configured; `VERIFY_WEBHOOK_SIGNATURE=False` short-circuit accepts; privacy invariants (4 tests asserting that distinctive secret / signature / message text / sender id values NEVER appear in `caplog`); payload summary emitted with `object=instagram`; unsupported field returns 200 with the warning surfacing the unsupported field name; `_summarise_payload_fields` unit checks (FB / IG-unsupported / empty / non-dict).

Behaviour change:
- Inbound Instagram webhook POSTs now sign-verify against `INSTAGRAM_APP_SECRET` when present. A single endpoint accepts both Facebook Page callbacks AND Instagram Business callbacks without disabling verification globally.
- After signature acceptance, a single safe diagnostic line surfaces object + entries + sorted unique field names so the operator can see at a glance whether the IG payload carries `messaging` / `messages` / `changes` / something unsupported.
- Boot log surfaces secret + token presence so the operator can spot a misconfigured env at startup rather than at first 403.
- Unsupported Instagram payloads (e.g. `live_videos` notifications, mention webhooks not yet wired into the handler) get a single warning + 200 OK so Meta does not retry-storm.
- No business logic outside the webhook signature verifier + boot prints changed. PARENT booking / Calendar / Sheets / OpenAI model / scenario runner / Comment routing / Adult subscription / broadcast / WhatsApp manager notification all untouched.

**Status — live verification (updated 2026-06-09 after operator live test):**

- ✅ **Instagram local/live DM response WORKS after operator env setup.** Operator added `INSTAGRAM_APP_SECRET` (and the IG access token) to local `.env`, restarted the server, sent an Instagram DM, observed `[webhook] signature accepted via instagram_app_secret` (no 403). Agent responded successfully. Comment under Instagram post also passes signature verification.
- ✅ **Instagram payload routing OK for the common message + comment shape** observed in `code.shelf` live traffic — the existing handler routes via `messaging` / `messages` / `changes`. Unsupported fields (if/when Meta adds new field types) still produce a safe warning + 200 OK and the operator sees the field name in the diagnostic log.

**Status — STILL OPEN (Railway-env + operator actions, NOT local engineering tasks):**

- ⏳ **Railway env vars setup pending** — production env must include: `INSTAGRAM_APP_SECRET`, `INSTAGRAM_ACCESS_TOKEN` (the local secrets/tokens that unblocked the live test must be re-added on Railway), `META_APP_SECRET` (Facebook Page secret), Google credentials env, `REDIS_URL`, `WHATSAPP_TOKEN` if WhatsApp is used.
- ⏳ **Railway deploy, Meta App Review, WhatsApp live test, production smoke test** — unchanged, operator action.

CRITICAL re-run: NOT executed. Justification: the patch is webhook-signature-only; PARENT booking / objection / security CRITICAL scenarios never go through the signature verifier path under test (the test harness mocks the webhook). 22 dedicated tests cover the new signature surface. Operator approval gate unchanged.

**Adult Event Subscription + New-Event Broadcast Patch (2026-06-08, pytest 1520 → 1593, +73 tests):**

Implements a complete opt-in subscription + broadcast surface for adult/cultural events. Distinct from the 24/72/168h PARENT follow-up scheduler — that drives unconditional cadence per conversation; this one only fires when the operator activates a new adult event AND the user explicitly opted in.

Files changed (4 new + 6 production + 3 templates + 2 new test files + 1 doc):

- [app/services/sheets_service.py](ai-agent/app/services/sheets_service.py) — new `EVENTS_TAB = "events"` constant + `EVENT_SUBSCRIBER_HEADERS` (18 columns: Created At, Updated At, Platform, Sender ID, Name, Phone, Status, Consent, Consent At, Source Event ID, Source Event Title, Source Event Link, Age, Last Notified Event ID, Last Notified At, Notified Event IDs, Unsubscribe At, Notes). New helpers: `_event_subscribers_worksheet` (create-if-missing), `_ensure_event_subscriber_headers`, `_find_event_subscriber_row(platform, sender_id)`, `_event_subscriber_row` (dict→row), `_event_subscriber_row_to_dict` (row→dict with notified-ids parsed), `_normalise_notified_ids` (accepts CSV or JSON list), `_serialise_notified_ids` (CSV write). Public CRUD: `save_event_subscriber(data) → (bool, reason)` (upsert by platform+sender_id, merge over existing row, preserves `Notified Event IDs` on partial save), `get_event_subscriber(platform, sender_id) → dict | None`, `list_event_subscribers(*, status="subscribed", consent_required=True) → list[dict]`, `unsubscribe_event_subscriber(platform, sender_id) → (bool, reason)` (flips Status + Unsubscribe At + Updated At), `mark_event_subscriber_notified(platform, sender_id, event_id) → (bool, reason)` (appends to Notified Event IDs; returns `(False, "duplicate")` when already present). Phones masked via `_mask_phone` in log lines; sender ids masked via `sentry_service.mask_sender`.
- [app/services/adult_subscription_service.py](ai-agent/app/services/adult_subscription_service.py) **(NEW)** — orchestration layer between the LLM tool, the Sheets CRUD, and the broadcast service. Detects: `is_subscription_consent_phrase(text)` (closed-set Georgian + English positive phrases; negative phrases override so "არა, არ მინდა" never triggers consent via the "მინდა" substring), `is_negative_subscription_phrase(text)`, `is_unsubscribe_phrase(text)`. Operations: `is_already_subscribed(platform, sender_id)`, `subscribe(...) → dict` (validates phone via the existing `parent_flow._parse_name_phone` parser so behaviour matches PARENT booking; returns structured `missing_name` / `missing_phone` / `missing_name_and_phone` / `sheets_save_failed` reasons), `unsubscribe(platform, sender_id) → dict`. Never claims subscribed status unless Sheets returns `(True, "ok")`.
- [app/services/adult_event_broadcast_service.py](ai-agent/app/services/adult_event_broadcast_service.py) **(NEW)** — fan-out path. `build_broadcast_message(event)` renders the full event card (title / date / location / price / description / link + unsubscribe footer); skips empty fields; numeric `price_text` → "<n> ლარი" via the same `_format_event_price` helper as the comment DM. `broadcast_event(event_id_or_event)` returns a structured counters dict (`success`, `reason`, `event_id`, `event_title`, `sent`, `skipped_duplicate`, `skipped_no_consent`, `skipped_platform`, `failed`, `total_candidates`). Looks the event up via `get_adult_events()` (NOT `find_adult_event` — needs to detect inactive events to report the `inactive` reason explicitly). Blocked reasons: `kill_switch_disabled` / `missing_event` / `inactive` / `missing_link` / `subscriber_list_failed`. Per-subscriber failure isolated (counters track each branch); the dual layer of duplicate prevention (caller-side check on `notified_event_ids` AND `mark_event_subscriber_notified` re-check) prevents re-runs from doubling up.
- [app/agent/tools/adult_tools.py](ai-agent/app/agent/tools/adult_tools.py) — new `TOOL_SUBSCRIBE_TO_ADULT_EVENT_UPDATES = "subscribe_to_adult_event_updates"` constant + schema in the tool registry. Added to `ALLOWED_ADULT_TOOL_NAMES`.
- [app/agent/tools/adult_tool_executor.py](ai-agent/app/agent/tools/adult_tool_executor.py) — new `_subscribe_to_adult_event_updates(args)` method dispatched via the new tool name. Pulls name/phone from args first, falls back to `lead.name` / `lead.phone` so the LLM can call the tool right after "კი" without re-supplying. Calls `adult_subscription_service.subscribe(...)`. On success: mirrors collected data onto the Lead and sets `conversation.adult_subscription_status = "subscribed"` so the LLM doesn't re-ask in the same conversation. On failure: returns the structured reason verbatim — the LLM uses the prompt rules to ask for the missing data.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — deterministic unsubscribe-phrase short-circuit at turn entry. Runs BEFORE the LLM; on match, calls `adult_subscription_service.unsubscribe(...)` and returns the canned confirmation (`„კარგი, მომავალ ღონისძიებებზე შეტყობინებებს აღარ გამოგიგზავნით."`). Not-subscribed branch returns `„ამ სიაში ამ ეტაპზე არ ხართ დამატებული."`. Sheets failure degrades to manager-handoff offer.
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — new CRITICAL rule block „ფუტურული ღონისძიების შეტყობინებების წესი": triggers ONLY after event details + link were sent; uses the exact brand wording „გსურთ, როცა ახალი ზრდასრულთა ღონისძიება დაემატება, დეტალები და ბილეთის ბმული პირად შეტყობინებაში გამოგიგზავნოთ?"; bans the misleading „ახალი ღონისძიების სიაში დაგამატოთ" wording; explicit branches for missing name / missing phone / both; ban on „დაგიმატეთ" (incorrect form) in favour of „დაგამატეთ". `subscribe_to_adult_event_updates` listed in the tool registry block.
- [app/models/conversation.py](ai-agent/app/models/conversation.py) — new `adult_subscription_status: str = ""` field with full `to_dict` / `from_dict` round-trip support so the marker persists across Redis save/restore.
- [app/routes/admin.py](ai-agent/app/routes/admin.py) — both create-event and edit-event POST handlers accept a new `broadcast_after_save: str = Form("")` argument. New `_form_checkbox_set(value)` helper recognises the HTML checkbox semantics. New `_trigger_broadcast_after_save(event_id)` calls the broadcast service best-effort (failure logged, never blocks the save redirect). New `POST /admin/programs/adult_events/events/{event_id}/broadcast` route invokes the broadcast service and renders a results page. New `_format_broadcast_summary(result)` builds a single Georgian sentence with sent / skipped / failed counts and operator-friendly reasons for each failure mode.
- [templates/admin/adult_event_form.html](ai-agent/templates/admin/adult_event_form.html) — new "შენახვის შემდეგ გაუგზავნე subscribed მომხმარებლებს" checkbox with helper text explaining the active + link prerequisites.
- [templates/admin/adult_events.html](ai-agent/templates/admin/adult_events.html) — new green "გაგზავნა subscribed მომხმარებლებთან" manual broadcast button per active event row (with confirm dialog).
- [templates/admin/adult_event_broadcast_result.html](ai-agent/templates/admin/adult_event_broadcast_result.html) **(NEW)** — operator results page with the summary sentence + a compact counter table + a back link.
- [tests/test_adult_event_subscription.py](ai-agent/tests/test_adult_event_subscription.py) **(NEW)** — **42 tests** across consent / negative / unsubscribe phrase detection; Sheets row upsert / duplicate prevention / partial-update preservation; unsubscribe row flip; subscribe() missing_name / missing_phone / missing_name_and_phone branches; subscribe() Sheets failure surfaced as `sheets_save_failed`; executor tool behaviour including Lead-fallback for name/phone and conversation-marker writes; already-subscribed lookup; service-level unsubscribe; conversation field round-trip.
- [tests/test_adult_event_broadcast.py](ai-agent/tests/test_adult_event_broadcast.py) **(NEW)** — **31 tests** across broadcast happy path (sent count, message body); inactive event blocked; missing link blocked; missing event branch; duplicate-event prevention (caller-side + mark-side); re-run idempotence; unsubscribed user filtered; consent=false filtered; unsupported-platform filtered; per-subscriber failure isolation; kill switch blocks broadcast; message builder edge cases (skips missing fields, preserves FB-link inside description, numeric price → GEL); Admin Panel route renders result + missing-link message + no-subscribers message + checkbox / button presence asserted on templates.

Behaviour change:

- After the agent sends adult/cultural event details + a ticket link, it asks the brand-standard subscription question once. Positive consent → tool collects name + phone (uses Meta profile name and previous lead data when available), persists to the Sheets `events` tab, and confirms „დაგამატეთ სიაში…". Negative → no save, no re-ask.
- Adult event broadcast triggered EXPLICITLY via the Admin Panel — either the "შენახვის შემდეგ გაუგზავნე…" checkbox on the create/edit form (off by default) or the per-row "გაგზავნა subscribed მომხმარებლებთან" button. Active + has-link + kill-switch-on prerequisites are enforced at the service layer; failure modes surface operator-friendly Georgian messages on the results page.
- Per-subscriber duplicate prevention via the `Notified Event IDs` column. A re-run of the same broadcast counts as `skipped_duplicate=N`, never re-sends.
- Unsubscribe is deterministic — closed-set phrase detection runs BEFORE the LLM in the ADULT engine, hits Sheets directly, returns the canned confirmation. The user's PARENT booking flow is NOT affected (the unsubscribe path is ADULT-only).
- No business logic outside the new files + the ADULT engine entry + the Admin Panel adult event routes changed. PARENT booking / Calendar multi-busy / Sheets reschedule / PARENT follow-up scheduler / kill switch / Sentry / webhook signature / OpenAI model / scenario runner / Comment routing all untouched. WhatsApp manager notification logic untouched.

**Status — not implemented in this patch (intentional, documented as STILL OPEN):**

- ⏳ **Instagram reaction / DM issue** — agent does not currently respond on the connected Instagram account in the Meta app. **NEXT TASK.** Investigate Instagram webhook permissions / subscription / messaging permission state. Not touched in this patch.
- ⏳ **Railway deploy + Meta App Review + WhatsApp live test + production smoke test** — unchanged, operator action.

CRITICAL re-run: NOT executed. Justification: the patch is additive (new Sheets tab, new ADULT tool, new broadcast service, new Admin Panel routes); the existing CRITICAL scenarios exercise PARENT happy-path / objection / booking / security buckets, none of which are touched. The new ADULT subscription / broadcast surface has 73 dedicated unit tests covering its own behaviours. Operator approval gate unchanged.

**Comment → Specific Event Mapping Patch (2026-06-08, pytest 1465 → 1520, +55 tests):**

Live requirement: when a user comments under a Facebook post about a specific adult/cultural event, the agent should DM that exact event's details (title / date / location / price / link). Existing comment routing only hit the generic adult-events DM; the specific event was never identified.

Files changed (2 production + 1 template + 1 new test file + 3 existing test files):
- [app/services/comment_service.py](ai-agent/app/services/comment_service.py) — new deterministic `is_interest_intent(comment_text)` (Georgian + English broad-interest keyword shortcut so „ფასი?" / „ბმული?" / „price?" never need an LLM round-trip). New `resolve_specific_adult_event(comment_text, post_id, platform)` returns `(event, candidates, reason)` where `reason ∈ {facebook_post_id, comment_tag, caption_tag, ambiguous, no_match}` — Priority A (operator `facebook_post_id` exact match) → B (event tag found in comment text) → C (event tag found in post caption, soft-fail on Meta API errors) → D (no match) → E (multiple matches → ambiguous). New `_build_specific_adult_event_dm(event)` renders title / date / location / price / description / link with the existing price-rendering rules (numeric `price_text` → „<n> ლარი"; `price_gel` fallback). New `_build_ambiguous_adult_event_dm(candidates)` lists candidate titles for the clarification ask. `send_dm_from_comment(...)` accepts a new `comment_text=""` kwarg and tries the specific-event branch BEFORE falling through to the existing generic ADULT rich DM. `fetch_post_content` hardened: log lines no longer surface the access token, response body, or exception args — only status codes and the masked post id.
- [app/routes/webhook.py](ai-agent/app/routes/webhook.py) — `handle_comment` now checks `comment_service.is_interest_intent(comment_text)` BEFORE invoking the LLM classifier. When the deterministic check matches, `intent` is set to `"INTERESTED"` directly. Comments that don't match fall through to the existing LLM path so unrelated comments still get filtered as NOT_INTERESTED. The handler passes `comment_text=comment_text` to `send_dm_from_comment` so the specific-event resolver can use it.
- [templates/admin/adult_event_form.html](ai-agent/templates/admin/adult_event_form.html) — new helper text under the Facebook post ID + Tags inputs explaining that fb_post_id is optional and tags drive the comment-to-event mapping. Sample text shows the operator-facing format („ქართული პოეზია, ქართული_პოეზია, პოეზიის საღამო").
- [tests/test_comment_specific_event_mapping.py](ai-agent/tests/test_comment_specific_event_mapping.py) — **55 new tests**: 17-case parametrised broad-interest matcher + negative cases (Part 1); Priority B comment-tag match including underscore↔space normalisation + title-as-implicit-tag (Part 2); Priority C caption-tag match + skipped when B already resolved (Part 3); Priority A fb_post_id + wins-over-tag-ambiguity (Part 4); fb_post_id optional + YAML round-trip preservation (Part 5); ambiguous clarification DM (Part 6); inactive event exclusion via tag AND via fb_post_id (Part 7); specific-event DM content + numeric price → GEL + price_gel fallback + missing-field skip (Part 8); missing link handoff + payment_terms URL fallback (Part 9); no sold-out hallucination + explicit sold_out flag + `status: sold_out` shortcut (Part 10); camp broad-interest phrases (Part 11); caption-fetch soft-fail + exception non-propagation (Part 12); access-token-never-logged (4xx + exception paths) (Part 13); end-to-end integration tests for specific / generic / ambiguous DM routing through `send_dm_from_comment`; admin form helper-text presence.
- [tests/test_comment_flow.py](ai-agent/tests/test_comment_flow.py) — 2 NOT_INTERESTED tests + the shared `_run_handle_comment*` helpers gained a `comment_text=` kwarg so callers can pick a non-keyword phrase (e.g. „გილოცავ!") and exercise the LLM-mock path explicitly. Default kwarg remains „მაინტერესებს" so every existing INTERESTED test keeps its current behaviour (now via the deterministic shortcut, which is also the new live behaviour).
- [tests/test_kill_switch.py](ai-agent/tests/test_kill_switch.py) — `test_comment_flow_runs_normally_when_agent_on` now exercises the LLM path with `comment_text="ბანაკი"` (no interest keyword → falls through to the classifier mock).

Behaviour change:
- Short common-interest comments („ფასი?" / „ბმული?" / „სად ტარდება?" / „info" / „price" / 30+ other phrases — full closed set in `_INTEREST_KEYWORDS`) are now classified INTERESTED deterministically. No OpenAI call, no stochastic miss.
- A comment under a post for `adult_events` segment routes through `resolve_specific_adult_event` first. When a single active event matches the operator-saved `tags` (via comment OR caption substring, with underscore↔space normalisation) OR the `facebook_post_id` exactly matches the post id, the user receives THAT event's details — title, date_text, location, price (rendered per the ADULT price rule), description, reservation_url or payment_terms link, sold-out banner ONLY when operator flagged. Missing link → manager-handoff line. Missing operator data → field is skipped (no fabricated „ფასი: მითითებული არ არის" filler).
- Multiple events matching the same tag → short clarification DM („რამდენიმე მსგავსი ღონისძიება გვაქვს — „X" ან „Y". რომელი გაინტერესებთ?").
- Inactive events are excluded from every priority (even when `facebook_post_id` matches).
- `fetch_post_content` is the single shared helper for post-caption retrieval; failures (400 / 403 / network / exceptions) return `""` and never crash the webhook. Logs only emit status codes and exception class names — never the access token, response body, or exception args (which httpx redacts URLs that may contain tokens).
- Comment routing for `camp` / `kids_program` is unchanged. The broad-interest detector benefits camp comments equally — „ფასი?" under #ბანაკი now triggers the camp DM via the deterministic shortcut.
- No business logic outside the comment surface changed. PARENT booking / Calendar multi-busy / Sheets reschedule / follow-up scheduler / kill switch / Sentry / webhook signature / OpenAI model / scenario runner / Admin Panel auth all untouched.

**Status — not implemented in this patch (intentional, future scope):**
- ⏳ **Adult Event Subscription / future-event broadcast** — agent asks adult/cultural-event leads „გსურთ, მომავალ ღონისძიებებზე ინფორმაცია გამოგიგზავნოთ?", saves consent to a new Sheets tab, broadcasts a DM when operator activates a new event. Untouched.
- ⏳ **Railway deploy + Meta App Review + WhatsApp live test + production smoke test** — unchanged, operator action.
- ⏳ **Real Meta `pages_read_engagement` permission** — the post-caption fetch works today against the operator's existing tokens (Meta has historically allowed read on the Page's own posts), but the production deploy may need explicit `pages_read_engagement` to keep working at scale. Soft-fail path makes the patch safe even without it.

CRITICAL re-run: NOT executed. Justification: the patch is comment-surface-only (interest detection + specific-event resolver + DM builder); CRITICAL exercises PARENT happy-path / objection / booking / security buckets, none of which are touched. Operator approval gate unchanged.

**ADULT Live QA Patch — Price Hallucination (2026-06-08, pytest 1442 → 1465, +23 tests):**

Live-bug: Admin Panel event had `price_text = "150"` and `price_gel = 150`. The agent replied „დასწრების საფასური ღონისძიების კონფიგურაციაში მითითებული არაა.". Two root causes:
1. **Executor compact + details payloads omitted `price_gel`** — only `price_text` was surfaced to the LLM. A numeric-only `price_text` and an absent `price_gel` slot left the LLM uncertain about the value and prone to invent „missing" copy.
2. **Prompt had only the negative rule** („*არ* დაასახელო ფასი, თუ `price_text` ცარიელია") with no explicit positive rule on rendering numeric-only price strings as GEL and no instruction to fall back to `price_gel`.

Files changed (3 production + 1 prompt + 1 new test file):
- [app/agent/tools/adult_tool_executor.py](ai-agent/app/agent/tools/adult_tool_executor.py) — `_get_adult_events` compact and `_get_adult_event_details` both now surface `price_gel` (only when positive). New module-level `adult_price_disclosed_for_conversation: dict[str, bool]` + `mark_price_disclosed` / `is_price_disclosed` / `clear_price_disclosed` helpers, mirroring the sold-out pattern. Both tool handlers flip the flag when EITHER `price_text` is non-blank OR `price_gel > 0`. `reset_state()` clears the new dict too.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — new `_ADULT_PRICE_MISSING_INVENTED_PHRASES` list (12 variants including the literal live-bug phrasing); new `_strip_invented_price_missing_phrases` (sentence-level removal, same shape as the sold-out strip). `sanitise_adult_response(text, sender_id=...)` strips invented "price missing" copy ONLY when `is_price_disclosed(sender_id)` is true. `run_adult_llm_turn` clears the price flag at turn entry (so a previous turn's disclosure doesn't leak).
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — STRICT EVENT GROUNDING field list extended with `price_gel`, `payment_terms`. New CRITICAL block „ფასის რენდერინგის წესი — CRITICAL": decision tree (price_text non-blank → use it, append „ ლარი" when numeric-only; price_text blank + price_gel > 0 → render „{{price_gel}} ლარი"; only when BOTH are missing → say the canonical „ფასი ამ ეტაპზე მითითებული არ არის."). Explicit ban on the invented „დასწრების საფასური / ფასი კონფიგურაციაში მითითებული არ არის" wording. Multi-event-list line format updated to include price.
- [tests/test_adult_event_price_surfacing.py](ai-agent/tests/test_adult_event_price_surfacing.py) — **23 new tests**: YAML round-trip of price_text + price_gel; normaliser preserves both; compact payload includes price_text + price_gel; compact omits price_gel when zero; details payload includes both; details payload with only price_gel; details omits when both blank; disclosure flag flips on price_text-only, on price_gel-only, on details handler; flag stays off when no price; sanitiser strips 7 hallucinated phrasings (parametrised) when flag set; canonical „ფასი ამ ეტაპზე მითითებული არ არის." preserved when flag NOT set; sender_id=None opt-out path; disclosure flags are independent per-sender + per-purpose; reservation_url + price coexistence (no regression on Bug 3).

Behaviour change:
- Operator-saved `price_text` / `price_gel` always surface to the LLM. When the LLM sees them, the prompt's decision tree produces „ფასი: 150 ლარი." inline with the event detail; numeric-only `price_text` gets the „ ლარი" suffix automatically per prompt rule.
- The executor's per-conversation disclosure flag means the sanitiser cannot mistake a legitimate „price missing" fallback for a hallucination. When neither source surfaced a price for any event this turn, the canonical fallback phrasing passes through unchanged.
- No business logic outside ADULT executor + ADULT engine + ADULT prompt changed. PARENT booking, Calendar multi-busy, Sheets reschedule, follow-up scheduler, kill switch, Sentry, webhook signature, comment routing, OpenAI model, scenario runner, Admin Panel auth all untouched.

CRITICAL re-run: NOT executed. Justification: scope is ADULT-only and additive; the PARENT happy-path / objection / booking / security buckets that CRITICAL exercises are not at risk. Operator approval gate unchanged.

**ADULT Live QA Patch — Sold-Out Hallucination + Ticket Link + Partial Title (2026-06-08, pytest 1411 → 1442, +31 tests):**

Live-bugs surfaced after the multi-event roster landed:
1. **Agent invented „ადგილები ამოწურულია"** — bare `seats_available: 0` (the normaliser default) was triggering hallucinated sold-out copy. Operator-flagged sold-out events worked, but unflagged ones with the default 0 also got the sold-out treatment.
2. **Partial title rejection** — „ქართული პოეზია" did NOT match „ქართული პოეზიის საღამო" because the Georgian genitive suffix („ის") broke the substring check. `find_adult_event` had only an exact / `in`-substring matcher.
3. **Reservation link missing on event-selection turn** — the LLM had to call `provide_adult_reservation_link` as a separate tool round-trip; on selection it sent a generic „გსურთ, ბმული მოგწეროთ?" instead of including the URL inline.
4. **Filler „გმადლობთ. რამდენი წლის ბრძანდებით?"** — robotic opener on adult age question.
5. **„გინდა?" / „გნებავთ?" copy** — too informal for ADULT cultural-event tone; brand prefers „გსურთ?".

Files changed (4 production + 1 prompt + 1 new test file):
- [app/services/admin_config_service.py](ai-agent/app/services/admin_config_service.py) — `_normalize_adult_event` now surfaces a `sold_out` boolean (false by default; true when YAML has `sold_out: true` OR `status: sold_out`). New `_GEORGIAN_NOUN_SUFFIXES`, `_stem_token_for_match`, `_tokenize_for_match`, `_token_matches` helpers — strip the longest matching Georgian noun-case suffix per token, then stem-vs-stem prefix-match. New `find_adult_events_matching(needle, *, include_inactive=False)` returns ALL matches (exact id → exact title → casefolded substring with ≥3-char guard → stem-aware token overlap). `find_adult_event` becomes a thin wrapper that returns the unique match or `None` when zero or multiple match.
- [app/agent/tools/adult_tool_executor.py](ai-agent/app/agent/tools/adult_tool_executor.py) — new module-level `adult_sold_out_disclosed_for_conversation: dict[str, bool]` + `mark_sold_out_disclosed` / `is_sold_out_disclosed` / `clear_sold_out_disclosed` helpers. `_get_adult_events` compact: surfaces `sold_out`, OMITS `seats_available` entirely when zero (Bug 1), flips the per-conversation disclosure flag when ANY event has `sold_out=true`. `_get_adult_event_details` rewritten: uses `find_adult_events_matching` so multi-match returns `success=false, reason="ambiguous_event", candidates=[{id, title}…]` (Bug 2 — LLM asks the user to disambiguate); inactive-only match returns `reason="event_inactive", matched_titles=[…]` (Bug 2 — distinct from `unknown_event`); on a unique match, surfaces `reservation_url` AND `payment_terms` directly (Bug 3) alongside `has_reservation_url`; surfaces `sold_out` and flips the disclosure flag.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — sanitiser table extended: `_ADULT_WORDING_REWRITES` rewrites „გინდა" / „გინდათ" → „გსურთ" (Bug 5); `_ADULT_SOLD_OUT_INVENTED_PHRASES` list (Bug 1: „ადგილები ამოწურულია" / „ადგილები აღარ არის" / „ბილეთები ამოწურულია" / „sold out" + variants); `_ADULT_LEADING_THANKS_PATTERNS` strips „გმადლობთ. რამდენი წლის ბრძანდებით?" filler opener (Bug 4) while preserving legitimate mid-response thanks. `sanitise_adult_response(text, sender_id=None)` gains an optional `sender_id`; when provided AND the executor did NOT flag a sold-out disclosure for this turn, invented sold-out copy is stripped (sentence-level removal). `run_adult_llm_turn` clears the disclosure flag at turn-entry and threads `sender_id` to the sanitiser. Legacy callers that pass `sender_id=None` (unit tests, simulation tools) get the bare rewrite pipeline so the existing wording-table tests do not regress.
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — three new rule blocks: „ბილეთის ხელმისაწვდომობის (sold_out) წესი — CRITICAL" (never claim sold-out unless `sold_out=true` or `status="sold_out"` was returned — `seats_available` absence means the operator did not enter a number, NOT „no seats left"); „ღონისძიების შერჩევის (selection) წესი — CRITICAL" (call `get_adult_event_details` on a user title selection; handle the four success/failure branches — match / ambiguous / inactive / unknown — and include `reservation_url` inline on a unique match); „თავაზიანი ფორმის წესი" (no „გინდა?" / „გნებავთ?"; no „გმადლობთ." filler on the adult age question; multi-event list template). The example `event={{...}}` placeholder is double-braced so Python's `str.format()` passes through cleanly.
- [tests/test_adult_event_detail_selection_link.py](ai-agent/tests/test_adult_event_detail_selection_link.py) — **31 new tests**: compact-events seat-omission + positive-seat surfacing + sanitiser sold-out strip + alternate sold-out wordings + sender-id=None opt-out (Bug 1); explicit `sold_out=true` flag round-trip + `status: sold_out` shortcut + active-event sanitiser path + disclosure-flag turn lifecycle (Bug 1); reservation_url + payment_terms + missing-link branches (Bug 3); exact + partial + Latin + ambiguous + id-wins title matching (Bug 2); ambiguous-event executor branch + `find_adult_event` returns None when ambiguous (Bug 2); inactive event excluded + `include_inactive=True` retrieval + executor `event_inactive` reason (Bug 2); „გინდა" → „გსურთ" + „გინდათ" → „გსურთ" rewrites + leading thanks strip + alt punctuation + mid-response thanks preserved (Bugs 4 + 5); save_adult_event sold_out YAML round-trip; short-query no-overmatch + unknown-query empty result (matcher edge cases).

Behaviour change:
- A bare event with no `sold_out` operator flag and an absent / zero `seats_available` is NEVER described as sold out — the executor omits the seats field entirely (so the LLM can't infer „0 = empty"), and the sanitiser strips invented sold-out copy.
- Operator can flag a specific event sold-out via either `sold_out: true` or `status: sold_out` in YAML. When that event surfaces, the executor flips the per-conversation disclosure flag and the sanitiser permits the legitimate „ამ ღონისძიებაზე ადგილები ამ ეტაპზე ამოწურულია. თუ გსურთ, დაგაკავშირებთ მენეჯერთან." copy.
- „ქართული პოეზია" → „ქართული პოეზიის საღამო" is now a clean single match. Multi-match cases („პოეზიის საღამო" with two candidates) return `ambiguous_event` so the LLM asks „რომელს გულისხმობთ — X თუ Y?".
- Event-selection on a unique match includes `reservation_url` in the same response — no two-turn round trip. Missing link → manager-handoff offer.
- Adult age question opener is the bare „რამდენი წლის ბრძანდებით…" (no „გმადლობთ. " filler).
- „გინდა?" / „გინდათ?" → „გსურთ?" everywhere in the final output (rewrite table runs on every turn regardless of sold-out state).

CRITICAL re-run: NOT executed. Justification: scope is ADULT engine + ADULT executor + ADULT prompt + ADULT sanitiser; PARENT booking / Calendar / Sheets / OpenAI model / scenario runner are untouched, so the CRITICAL happy-path / objection / booking / security buckets are not at risk. Operator approval gate unchanged.

**Admin Panel Multi-Event UI Visibility Fix (2026-06-08, pytest 1402 → 1411, +9 tests):**
Live-bug after the multi-event backend patch landed: routes worked but operator could not discover them. The Programs list rendered the legacy "Edit" button only; the section-form for `adult_events` had no link to `/admin/programs/adult_events/events`. End result: operator opens Admin Panel → sees nothing changed → believes the patch never shipped.

Files changed (3 templates + 1 test file extension):
- [templates/admin/programs.html](ai-agent/templates/admin/programs.html) — the row for any section where `id == "adult_events"` OR `type == "adult_events"` now renders a prominent green "ღონისძიებების მართვა" button next to "Edit". Direct deep-link to `/admin/programs/adult_events/events`.
- [templates/admin/program_form.html](ai-agent/templates/admin/program_form.html) — when editing the adult_events section (`not is_new and section.id == "adult_events"`), a blue info banner at the top of the form explains: "სექციის მეტადატის გვერდი (hashtags, age_min, ნაგულისხმევი template) იცვლება ქვემოთ. ცალკეული ღონისძიებების სიის სამართავად: ღონისძიებების მართვა →". The banner is hidden for camp / sunday-school forms (verified by `test_other_section_forms_do_not_show_events_manager_banner`).
- [templates/admin/adult_events.html](ai-agent/templates/admin/adult_events.html) — top-action row renamed "+ ახალი ღონისძიება" → "ახალი ღონისძიების დამატება" (matches the spec); added a "← Programs" back-link alongside the existing "← სექციის რედაქტირება". Empty-state copy updated to the spec wording „ჯერ ღონისძიებები არ არის დამატებული." plus a CTA button.
- [tests/test_admin_multi_event_support.py](ai-agent/tests/test_admin_multi_event_support.py) — **9 new visibility tests**: programs page links to events manager / adult_events section form links to events manager / OTHER section forms do NOT show the banner / events-list returns 200 / empty page shows the spec wording / add form reachable + carries every spec field / save redirects to events-list / list shows saved event with edit+deactivate / inactive row shows activate button.

Behaviour change:
- Operator flow now reads: `/admin/programs` → click "ღონისძიებების მართვა" → `/admin/programs/adult_events/events` → click "ახალი ღონისძიების დამატება" → `/admin/programs/adult_events/events/new` → submit → 303 redirect to the events list with the new row.
- Editing the `adult_events` section metadata still works exactly as before; the new banner does not move any field, only adds a top link.
- Camp / sunday-school section forms are unchanged — no banner, no extra button.
- Exact route paths (these are the URLs the operator opens in the browser; **the spec asked for `/edit` suffixes — those do NOT exist, the actual route uses `/{event_id}`**):
  - `GET  /admin/programs/adult_events/events` (list)
  - `GET  /admin/programs/adult_events/events/new` (add form)
  - `POST /admin/programs/adult_events/events/new` (create)
  - `GET  /admin/programs/adult_events/events/{event_id}` (edit form)
  - `POST /admin/programs/adult_events/events/{event_id}` (save edits)
  - `POST /admin/programs/adult_events/events/{event_id}/delete` (hard remove)
  - `POST /admin/programs/adult_events/events/{event_id}/deactivate` (status → inactive)
  - `POST /admin/programs/adult_events/events/{event_id}/activate` (status → active)
- No business logic, no service-layer / executor-layer / agent / Calendar / Sheets / Redis / OpenAI / scenario-runner change.

**Admin Panel Multi-Event Patch (2026-06-08, pytest 1350 → 1402, +52 tests):**
1. `_normalize_adult_event` extended to preserve `description`, `facebook_post_id`, `tags`, `price_gel`, `payment_terms` so the operator-saved values round-trip through the editor and surface in the LLM tool layer. The 13-year `min_age` floor remains; `theme` continues to fall back to `description` for backward compat.
2. New service functions: `update_adult_event(event_id, patch)` (partial update; refuses unknown id), `deactivate_adult_event(event_id)` (status → inactive — keeps the row in YAML so the operator can re-enable), `activate_adult_event(event_id)`, and a public `normalize_adult_event(event, idx=None)` wrapper for tests/agent code.
3. `save_adult_event` now merges the operator-supplied dict over the existing entry so a "change one field" save NEVER drops a previously-saved field (e.g. `facebook_post_id`). Empty-string optional fields are pruned to keep the YAML clean. `tags` accepts either a list or a CSV string and persists as a list.
4. New routes: `POST /admin/programs/adult_events/events/{event_id}/deactivate` and `POST /admin/programs/adult_events/events/{event_id}/activate`. The existing list view (`/admin/programs/adult_events/events`) shows status-aware action buttons: active rows get "დეაქტივაცია"; inactive rows get "აქტივაცია"; both keep "რედაქტირება" + "წაშლა".
5. `AdultToolExecutor._get_adult_events` and `_get_adult_event_details` compact payloads now include the explicit `description` field alongside `theme`, so the LLM can answer „რა არის ეს ღონისძიება?" without falling back to the generic theme placeholder. No other tool / contract changed.
6. Multi-event listing in the ADULT prompt was already covered (Session 6 — see `system_adult_v1.md` „გადასვლის წესი" / event-listing rules). This patch surfaces ALL active eligible events through `get_active_adult_events(user_age)` with the existing `min_age >= user_age` comparison; LLM formats the list and asks „რომელი ღონისძიება გაინტერესებთ?" per prompt rules.

**Files changed (1 service + 1 route + 1 template + 1 executor + 1 new test file):**
- [app/services/admin_config_service.py](ai-agent/app/services/admin_config_service.py) — `_normalize_adult_event(raw, idx=None)` extended with description / facebook_post_id / tags / price_gel / payment_terms fields; new `normalize_adult_event` public wrapper; `save_adult_event` performs merge-over-existing + optional-field pruning + CSV-tag parsing; new `update_adult_event`, `_set_adult_event_status`, `deactivate_adult_event`, `activate_adult_event`. `get_adult_events` passes `idx` to the normaliser so the id auto-derivation lives in one place.
- [app/routes/admin.py](ai-agent/app/routes/admin.py) — two new `POST` routes (`/deactivate` + `/activate`). Auth + Jinja2 patterns unchanged.
- [templates/admin/adult_events.html](ai-agent/templates/admin/adult_events.html) — list row now branches on `e.status` to render either the "დეაქტივაცია" or the "აქტივაცია" button alongside edit / delete. The default-rendered status text falls back to `'active'` for legacy rows missing the field.
- [app/agent/tools/adult_tool_executor.py](ai-agent/app/agent/tools/adult_tool_executor.py) — compact event dict adds `description`. No other change.
- [tests/test_admin_multi_event_support.py](ai-agent/tests/test_admin_multi_event_support.py) — **52 new tests** across:
  - service CRUD (10): save / second-save preserves first / update partial / unknown id rejected / deactivate / activate / unknown id false / missing-title rejected / invalid-status rejected / 10-event bulk persistence
  - section metadata preservation (2)
  - min_age default + floor (4)
  - active/inactive filtering (2)
  - age eligibility matrix (4)
  - events[] vs section-level fallback contract (2)
  - facebook_post_id round-trip (4)
  - unicode Georgian round-trip (1)
  - executor multi-event surface (10) — multi-eligible, inactive excluded, age-ineligible excluded, title+date+location+price visible, lookup by title (exact + partial), reservation_url present, reservation_url missing → `link_missing`, no-active-events branch, description in compact
  - HTTP routes (10) — list rendering / new form / POST create / edit form / unknown id 404 / POST edit / deactivate route / activate route / inactive shown in list
  - public normalize wrapper (3)

**Behaviour change:**
- Operator can add unlimited adult/cultural events through `/admin/programs/adult_events/events/new`, edit any single field through `/admin/programs/adult_events/events/{id}`, deactivate without losing the row, and re-activate later.
- `events[]` in `data/admin_config/sections.yaml` is the source of truth for the LLM tool surface. The Session 6 section-level fallback (Bug 1A) remains intact ONLY when `events[]` is empty — populated `events[]` always wins and never produces a phantom duplicate.
- All section-level metadata (hashtags, age_min, auto_dm_template_id, description_short …) survives every event save / edit / activate / deactivate cycle. Verified by `test_section_metadata_preserved_after_event_save` and `test_section_metadata_preserved_across_multiple_events`.
- 13-year `min_age` floor still enforced — both on write (`save_adult_event` floors `min_age=8` → 13) AND on read (`_normalize_adult_event` floors legacy sub-13 YAML). Per-event `min_age` can override UPWARD only.
- `facebook_post_id` is captured + persisted but NOT YET consumed by the comment flow. Field is reserved for the future "Comment → Event Mapping" patch — current comment routing continues to use post hashtags only.
- No business logic outside admin_config_service + admin routes + adult_event templates + adult_tool_executor's compact payloads changed. PARENT booking / Calendar multi-busy / Sheets reschedule / follow-up scheduler / kill switch / Sentry / webhook signature / OpenAI model / comment routing / scenario runner all untouched.

**Status — not implemented in this patch (intentional, gated on multi-event landing):**
- ⏳ **Adult event subscription / future-event broadcast** — agent asks adult/cultural-event leads „გსურთ, მომავალ ზრდასრულთა ღონისძიებებზე ინფორმაცია გამოგიგზავნოთ?", saves consent to a new Sheets `Adult Subscribers` tab, and broadcasts a DM when the operator activates a new event in Admin Panel. NOT touched. See §7 Priority 2.C.
- ⏳ **Comment → Event Mapping via `facebook_post_id`** — when a comment lands on a post tied to a specific `facebook_post_id`, the rich first-contact DM should embed that specific event's title / date / link. The field is now captured + persisted; the mapping logic is the next patch. NOT touched.
- ⏳ **Railway deploy + Meta App Review + WhatsApp live test + production smoke test** — unchanged, operator action.

**Live verification status (2026-06-07/08 operator-driven testing):**
- ✅ **Reschedule Calendar behaviour LIVE VERIFIED.** Old Calendar event cancelled after new event_id verified.
- ✅ **Reschedule Sheets behaviour LIVE VERIFIED.** Screenshot confirmed: old Sheets row → `Status="Rescheduled"`, current row → `Status="Booked"`. One active `Booked` row per sender after reschedule.
- ✅ **Booking confirmation shortened LIVE VERIFIED.** No trailing „თუ კიდევ რაიმე…" / „თუ დამატებითი კითხვა გაქვთ…" filler after a successful booking.
- ✅ **PARENT follow-up Admin Panel template LIVE VERIFIED.** Operator-edited template text in `/admin/templates` is read at send-time and delivered through Messenger via `tools/run_followup_tick.py`.
- ✅ **Follow-up Redis hydrate CLI LIVE VERIFIED.** `python tools/run_followup_tick.py` hydrates conversations from Redis (Session 6/7/Hydrate Patch) and sends due follow-ups to PARENT conversations.
- ⏳ **Adult follow-up scheduler still NOT supported.** Current scheduler handles PARENT segment only — `_maybe_send_followup_for_conversation` short-circuits with `reason=non_parent_segment` for ADULT and UNCLEAR.
- ⏳ **Production follow-up tick interval still 1h.** Test mode shortens the FIRST-due delay only; it does NOT shorten the APScheduler interval. Operators must trigger via the CLI helper for tighter feedback than 1h.
- ⏳ Production deploy NOT done. Meta App Review NOT done. WhatsApp live test pending real credentials. Production smoke test NOT run.

**Session 8 LIVE QA Patch (2026-06-07, pytest 1333 → 1350) — 2 live-QA findings post Session 7:**
1. **Extra CTA filler after booking** — live model produced `"მადლობა თქვენ. თუ კიდევ რაიმე დაგაინტერესებთ, თუ კიდევ რაიმე გაგიჩნდებათ, მომწერეთ და დაგეხმარებით."` after a thank-you. The Session 7 trim helper handled only the immediate booking-success turn; subsequent booked-state turns kept appending the help-CTA filler via `_strip_consultation_cta_if_booked`.
2. **Sheets reschedule row update targeted the wrong row** — `sheets_service.update_lead(sender_id, {"status": "Rescheduled"})` used `_find_row_by_sender_id` which returns the FIRST sender_id match regardless of status. With a pre-booking discovery row in front of the actual old-booking row, the helper relabelled the discovery row and left the OLD booking row as `"Booked"`. Result in live CRM: two `"Booked"` rows per sender after reschedule.

**Files changed (3 production + 1 new test file + 2 existing test updates + 1 doc):**
- [app/services/sheets_service.py](ai-agent/app/services/sheets_service.py) — new `mark_old_booking_rescheduled(sender_id, *, new_status="Rescheduled", booked_status_label="Booked")` helper. Scans all rows for `sender_id`, filters to those whose Status cell equals `"Booked"`, updates the OLDEST (lowest row index) to `new_status` and leaves any LATER `"Booked"` row alone. Returns `(True, "ok")` on success / `(False, reason)` on failure — `reason ∈ {worksheet_unavailable, read_failed, no_booked_row, write_failed}`. Privacy-safe logging via `sentry_service.mask_sender`; raw sender ids never leak.
- [app/agent/tools/parent_tool_executor.py](ai-agent/app/agent/tools/parent_tool_executor.py) — `_reschedule_booking` now calls `sheets_service.mark_old_booking_rescheduled(sender_id, new_status="Rescheduled")` instead of the legacy `update_lead`. On Sheets failure: warning logged with masked sender + masked old_event_id, Sentry capture fires with `area=booking_reschedule, reason=sheets_old_row_update_failed`, Calendar success is NOT rolled back (the new booking is real even if CRM is briefly out of sync — operator can backfill from Calendar).
- [app/flows/parent_flow.py](ai-agent/app/flows/parent_flow.py) — `_BOOKED_NEW_BOOKING_CTA_PATTERNS` extended with 10 awkward-CTA-filler variants („თუ კიდევ რაიმე გაგიჩნდებათ, მომწერეთ…", „თუ კიდევ რაიმე დაგაინტერესებთ, შემეხმიანეთ…", „თუ დამატებითი კითხვა გაქვთ, მომწერეთ…"). `_strip_consultation_cta_if_booked` no longer auto-appends `_BOOKED_HELP_CTA` after stripping — the response stays short. `_BOOKING_SUCCESS_TRIM_PHRASES` extended with the same set so the immediate booking-success turn is also clean.
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — new `_DUP_TU_MIXED_PATTERN` regex collapses doubled „თუ X დაგაინტერესებთ, თუ Y გაგიჩნდებათ" (mixed-verb) clauses to a single one. The existing `_DUP_TU_PATTERN` (same-verb form) is kept; both run inside `_collapse_duplicated_tu`.
- [tests/test_session8_booking_confirmation_sheets_reschedule.py](ai-agent/tests/test_session8_booking_confirmation_sheets_reschedule.py) — **17 new tests**: doubled-clause sanitizer (2), booked-state stripper (3), success-turn trim (1), full-flow booking confirmation shape (2), Sheets helper happy path (3), Sheets helper failure modes (3), reschedule executor wiring (3).
- [tests/test_booked_state_polish.py](ai-agent/tests/test_booked_state_polish.py) — 4 tests updated to assert „თუ დამატებითი კითხვა გაქვთ" is NO LONGER appended to booked-state responses (it used to be the replacement filler after stripping a new-booking CTA).
- [tests/test_expired_booking_memory_fix.py](ai-agent/tests/test_expired_booking_memory_fix.py) — 1 test updated to match the new no-auto-append behaviour.

**Behaviour change:**
- Booked-state responses no longer trail with „თუ დამატებითი კითხვა გაქვთ, მომწერეთ და დაგეხმარებით." — the response is whatever the LLM produced minus the new-booking CTAs. If the LLM said „კონსულტაცია ჩანიშნულია 10 ივნისს 11:00 საათზე." the user sees exactly that.
- The doubled „თუ კიდევ რაიმე X, თუ კიდევ რაიმე Y" filler is collapsed to a single clause by the sanitizer, then if the lead is booked the whole clause is stripped by `_strip_consultation_cta_if_booked`.
- Reschedule success in Sheets: the OLDEST row for `sender_id` whose Status is `"Booked"` gets relabelled `"Rescheduled"`. Later `"Booked"` rows (the fresh booking just appended via `create_lead`) stay untouched. Single-active-booking invariant in CRM is now enforced even with pre-booking discovery rows in the row history.
- Calendar happy path unchanged. Sheets-write failures are logged + Sentry-captured but never roll back Calendar — operator can backfill from Calendar if CRM is briefly inconsistent.
- No business logic outside the booking-confirmation + sheets-reschedule paths changed.

**Follow-up Live-Test Hydrate Patch (2026-06-06, pytest 1320 → 1333) — fix for "one-off CLI tick sent no DM":**

**Follow-up Live-Test Hydrate Patch (2026-06-06, pytest 1320 → 1333) — fix for "one-off CLI tick sent no DM":**
Live-bug: operator set `FOLLOWUP_TEST_MODE=true` + `FOLLOWUP_FIRST_DELAY_SECONDS=120`, conversation with `last_bot_message_at` 120+ seconds ago, then ran `python -c "from app.services import followup_service; followup_service.check_and_send_followups()"` → no DM sent. Root cause: `get_all_conversations_snapshot()` reads ONLY the in-memory `conversation_service.conversations` dict; a fresh Python process starts with an empty dict and silently scans zero conversations.

Files changed (3 production + 1 new CLI tool + 1 new test file + 1 doc):
- [app/services/redis_state_service.py](ai-agent/app/services/redis_state_service.py) — new `scan_keys(pattern, count=200)` helper uses non-blocking SCAN (NOT KEYS — KEYS holds the Redis main thread for every match and is forbidden in production). Returns `[]` on Redis-disabled / failure. Never raises.
- [app/services/conversation_service.py](ai-agent/app/services/conversation_service.py) — new `hydrate_from_redis()` scans `conversation:*` keys, parses each payload via `Conversation.from_dict`, and loads into the in-memory dict. Idempotent: a sender that already lives in memory is left untouched (live state wins). Skipped counters surfaced via `[FOLLOWUP] hydrate complete keys=N loaded=N skipped_existing=N skipped_invalid=N`. Module docstring on `get_all_conversations_snapshot` updated to recommend hydrate before one-off CLI runs.
- [app/services/followup_service.py](ai-agent/app/services/followup_service.py) — enriched `check_and_send_followups()` logging: `[FOLLOWUP] scanning total=N parent=N with_marker=N` at tick start; `[FOLLOWUP] tick complete total=N due=N sent=N skipped=N` at tick end. Send failure path now returns `"due_send_failed"` so the due counter reflects "the cadence elapsed" regardless of send outcome.
- [tools/run_followup_tick.py](ai-agent/tools/run_followup_tick.py) — new CLI helper. `python tools/run_followup_tick.py` hydrates Redis → runs the scheduler tick once. `--dry-run` flag enumerates due conversations without sending. Logs go to stdout so the operator sees the same `[FOLLOWUP] …` lines the live server emits.
- [tests/test_followup_hydrate_patch.py](ai-agent/tests/test_followup_hydrate_patch.py) — **13 new tests**: scan_keys (3), hydrate (4), scheduler counter logging (4), end-to-end CLI simulation (1), CLI tool smoke import (1).

Behaviour change:
- One-off CLI invocation (`python tools/run_followup_tick.py`) now reproduces what the live APScheduler tick would have done. Without hydrate the scheduler still scans an empty dict — preserved so the live in-process scheduler keeps working exactly as before.
- A successful comment DM (Follow-up Test Mode Patch) writes through to Redis; the same Redis key is what the new hydrate path reads. End-to-end: comment → private DM → 120 seconds idle → operator runs the CLI helper → follow-up DM lands.
- Logs now surface `total / parent / with_marker / due / sent / skipped` per tick so an operator can debug "no DM sent" in one log line.
- No business logic outside the follow-up + hydrate paths changed.

**Follow-up Test Mode + Live-QA Compatibility Patch (2026-06-06, pytest 1290 → 1320, +30 tests):**

**Follow-up Test Mode + Live-QA Compatibility Patch (2026-06-06, pytest 1290 → 1320, +30 tests):**
1. `FOLLOWUP_ENABLED` master gate (defaults true). When false the scheduler tick is a single-line no-op.
2. `FOLLOWUP_TEST_MODE` + `FOLLOWUP_FIRST_DELAY_SECONDS` operator overrides — when both set the FIRST cadence step (24h) reduces to the override seconds so operators can live-test the scheduler in 2 minutes instead of waiting a day. Stages 2 (72h) and 3 (168h) NEVER take the override — operators cannot accidentally pummel a user with test cadence on subsequent reminders.
3. Invalid override (zero / negative / non-numeric) → silent fallback to the production 24-hour delay; scheduler never crashes.
4. Comment → private DM now stamps `conversation.last_bot_message_at` + Redis write-through so the same scheduler that drives organic Messenger DMs also drives the post-comment cadence. A failed DM send does NOT stamp the marker (the scheduler would otherwise chase a user who never received the first message).
5. Boot banner: `[FOLLOWUP] Test mode enabled: first delay = 120s` OR `[FOLLOWUP] Production cadence active` OR `[FOLLOWUP] disabled (FOLLOWUP_ENABLED=false) — tick skipped` (mutually exclusive — exactly one fires per tick).
6. Privacy-safe `[FOLLOWUP] marker_skipped sender=<masked> reason=<booked|declined|asked_no_more_messages|manager_handoff_completed>` logs when blocked-reason transitions happen. No raw sender IDs, no message bodies, no phone numbers.

**Files changed (3 production + 1 new test file + 2 existing test updates + 2 docs):**
- [app/config.py](ai-agent/app/config.py) — 3 new fields (`FOLLOWUP_ENABLED: bool = True`, `FOLLOWUP_TEST_MODE: bool = False`, `FOLLOWUP_FIRST_DELAY_SECONDS: int = 0`) + `from_env` parsing + `followup_enabled` property now folds in the master kill flag.
- [app/services/followup_service.py](ai-agent/app/services/followup_service.py) — new `_first_delay()` + `_effective_cadence()` resolvers. `_pick_due_cadence` reads from `_effective_cadence()` so the override takes effect at scheduler-tick time without mutating the module-level constant. `check_and_send_followups` short-circuits when `FOLLOWUP_ENABLED=false`; logs the one-line mode banner (test / production / disabled) every tick.
- [app/services/conversation_service.py](ai-agent/app/services/conversation_service.py) — `_record_pre_response_followup_markers` + `_record_post_response_followup_markers` emit a single masked-sender `[FOLLOWUP] marker_skipped` line when blocked-reason transitions from empty to `declined` / `asked_no_more_messages` / `booked` / `manager_handoff_completed`. Quiet otherwise (stopped_after / interest writes stay silent so per-turn log volume doesn't balloon).
- [app/services/comment_service.py](ai-agent/app/services/comment_service.py) — `send_dm_from_comment` now stamps `conversation.last_bot_message_at = utcnow().isoformat()` + writes through to Redis on successful DM send; emits `[FOLLOWUP] marker_created channel=comment_dm sender=<masked> stage=initial segment=...`. Failed send → no marker stamped.
- [tests/test_followup_test_mode_live_patch.py](ai-agent/tests/test_followup_test_mode_live_patch.py) — **30 new tests** across Part 1 (10 config / fallback / cadence-shape), Part 2 (5 scheduler skip rules), Part 3 (6 Messenger DM 2-min flow + idempotence + production guard), Part 4 (3 comment DM marker + private-DM channel), Part 5 (3 fallback text content safety), Part 6 (4 privacy logging + banners).
- [tests/test_followup_scheduler.py](ai-agent/tests/test_followup_scheduler.py) — `_swap_agent_enabled` helper now also pins `FOLLOWUP_TEST_MODE=False` + `FOLLOWUP_FIRST_DELAY_SECONDS=0` + `FOLLOWUP_ENABLED=True` so the existing 24h / 72h / 168h cadence assertions are not short-circuited by the live `.env`'s 120-second override.
- [tests/conftest.py](ai-agent/tests/conftest.py) — new autouse fixture `_force_followup_production_cadence` pins production cadence for the WHOLE suite by default. Tests that DO want the override (this patch's own file) layer their own monkeypatch on top.

**Behaviour change:**
- Production deploys with `FOLLOWUP_TEST_MODE` unset / false continue to follow the historic 24h → 72h → 168h cadence. The hard kill (`FOLLOWUP_ENABLED=false`) pauses the entire follow-up channel without touching any other service.
- Live operator can run a 2-minute follow-up QA by setting `FOLLOWUP_TEST_MODE=true` + `FOLLOWUP_FIRST_DELAY_SECONDS=120` in `.env`, then either waiting for the next hourly scheduler tick or invoking `check_and_send_followups()` directly from a console.
- Comment-originated conversations now participate in the follow-up cadence. Public comment replies never receive a follow-up — the follow-up message is sent through `messenger_service.send_message` (private DM channel) only.
- Logs are privacy-safe: sender IDs masked via `sentry_service.mask_sender` (first 6 chars + `***`). No raw phone numbers, no message bodies.
- No business logic outside the follow-up + comment-DM marker paths changed — Calendar booking / multi-busy / Email channel / WhatsApp guards / Redis core / Kill Switch / Sentry / Webhook signature / Admin auth / Comment flow architecture / OpenAI model / scenario runner / agent prompts all untouched.

**Test Stability Patch (2026-06-06, pytest 1289 → 1290) — weekend date fragility fix:**
- `tests/test_calendar_multi_busy_patch.py::test_busy_10_30_to_19_00_blocks_11_through_18` — `target_date = now_tbilisi() + 14 days` now advances past any weekend with a `while target_date.weekday() >= 5: target_date += timedelta(days=1)` loop. Docstring documents the fragility this loop guards against. Test-only change; no production code touched.

**Model:** active OpenAI model is **`gpt-4.1-mini`** (verified via the 2026-06-05 CRITICAL scenario runner output: every turn ran against gpt-4.1-mini; the `gpt-5.4-mini` references in §11 / CLAUDE.md feature-flags table describe a planned switch but the live `.env` is still on `gpt-4.1-mini`).

**Session 7 LIVE QA Patch (2026-06-06, pytest 1251 → 1290) — 6 live-QA findings post Session 6:**
1. **CRITICAL — Reschedule cleanup**: user with active booking proposed a different time, agent confirmed slot via `check_consultation_slot`, then booked the new slot via `book_consultation` — *but never cancelled the old one*. Result: two active Calendar events for one user. Root cause: pending_booking source was tagged "user_requested_exact_slot" (the standard exact-slot path), losing the reschedule intent across the confirmation turn.
2. **Adult transition still dead-ends from booked-parent state**: „თუ არის შესაძლებელი ზრდასრულთა ღონისძიებაც რომ გამაცნოთ" → bot replied „გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით." with no follow-up. The adult-engine's `_ensure_adult_intro_followup` only runs on the next ADULT turn; the PARENT engine's transition turn was uncovered.
3. **Adult target question wording revert**: brand owner reverted preference back to the original „თქვენთვის გსურთ თუ თქვენი შვილისთვის?". Session 6's „სხვა ადამიანისთვის?" wording is dropped.
4. **Manager email polish + dedupe**: subject was generic „ახალი ლიდი" even with `lead.name` populated; body duplicated challenge text (live: „კომუნიკაცია განვითარება კომუნიკაცია განვითარება"); summary was generic filler instead of a concrete manager-friendly sentence.
5. **WhatsApp `Illegal header value b'Bearer '` traceback**: `WHATSAPP_TOKEN` empty in live `.env` produced HTTP error + stacktrace. Email channel must stay independent.
6. **Booking confirmation too long**: live response included help CTA + privacy note on the immediate success turn — should be the short brand line „X საათზე ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ.".

**Files changed (4 production + 1 prompt + 1 new test file + 4 existing test updates + 1 doc):**
- [app/agent/tools/parent_tool_executor.py](ai-agent/app/agent/tools/parent_tool_executor.py) — new `_is_reschedule_scenario(lead, new_iso)` helper + `RESCHEDULE_INTENT_PHRASES` closed-set. `_check_consultation_slot` now marks `pending_booking["source"]="reschedule"` and stashes `old_event_id` + `old_booked_datetime_iso` when an already-booked lead picks a different free slot. `_book_consultation` detects the same scenario after validation passes and reroutes to `_reschedule_booking` instead of creating a second Calendar event — so the safe-ordering (book new → verify event_id → THEN cancel old) protection from Session 6 Bug 9 takes over. The reroute returns a unified result shape with `action="reschedule"`, `booked_date/_time` (legacy) and `new_date/_time` (reschedule-specific) so both the LLM path and the deterministic commit path read the same fields. `book_consultation_success_for_conversation` flag is set to True on success so the fake-booking guard accepts the confirmation.
- [app/flows/parent_flow.py](ai-agent/app/flows/parent_flow.py) — `_maybe_commit_pending_booking_engine` now branches on `result.get("action") == "reschedule"` to render „კონსულტაცია X, Y საათზე ჩაგინიშნეთ. ძველი კონსულტაცია გაუქმებულია. მენეჯერი დაგიკავშირდებათ." — and the partial-fail branch („ახალი დრო ჩაგინიშნეთ. ძველი კონსულტაციის გაუქმება ავტომატურად ვერ დადასტურდა.") when `old_cancel_failed=True`, plus the `old_booking_preserved` branch („ამ ეტაპზე ახალი დროის დადასტურება ვერ მოხერხდა. თქვენი არსებული კონსულტაცია ძალაში რჩება."). New `_ensure_adult_intro_followup_for_parent_flow(conv, response)` mirror catches the cross-flow dead-end on the PARENT engine path: short responses (≤120 chars, no `?`) that end in „დაგეხმარებით." + carry an adult-event keyword get the next-step question appended. New `_trim_booking_success_response(conv, response)` strips trailing help CTA + privacy note on the immediate booking-success turn (gated by `book_consultation_success_for_conversation`). All three helpers wire into `handle()` after the existing engine post-processors.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — `_ADULT_FOLLOWUP_QUESTION_WHO` + `_ADULT_FOLLOWUP_QUESTION_WHO_OR_OTHER` reverted to „ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?" (Session 7 Bug 3). The 5 Session 6 sanitizer entries that mapped to „სხვა ადამიანისთვის" are flipped — the sanitizer now normalizes the intermediate wording BACK to „თქვენი შვილისთვის".
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — target-question fallback wording updated to „თქვენი შვილისთვის?" (Session 7 Bug 3). „კულტურული საღამოები რა არის?" answer's target question also updated. Added explicit note that sister/brother/friend answers must still be accepted normally (relative-capture path is unchanged).
- [app/services/notification_service.py](ai-agent/app/services/notification_service.py) — new `_build_email_subject(lead)` returns `f"<first_name> — ახალი კონსულტაცია AI Agent-იდან"` for booked leads with name, `"ახალი ლიდი AI Agent-იდან"` otherwise. New `_dedupe_repeated_phrase(text)` collapses "X Y X Y" / "X X" patterns the LLM occasionally produced. `_manager_email_body` headline branches on `lead.calendly_booked` ("ახალი კონსულტაცია ჩაინიშნა" vs "ახალი ლიდი"). `_parent_detail_lines` runs the challenge through dedupe before printing. `_build_parent_summary` now weaves the deduped challenge into the manager-friendly sentence ("მთავარი ფოკუსი: X"). `_send_manager_whatsapp` short-circuits with a single log line when ANY of `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `MANAGER_WHATSAPP_NUMBER` is empty — no `httpx.post`, no stacktrace.
- [tests/test_live_qa_session7_reschedule_notification_patch.py](ai-agent/tests/test_live_qa_session7_reschedule_notification_patch.py) — **39 new tests** across Bug 1 (10), Bug 2 (4), Bug 3 (6), Bug 4 (10), Bug 5 (5), Bug 6 (3) + 1 helper.
- [tests/test_adult_live_qa_polish.py](ai-agent/tests/test_adult_live_qa_polish.py) — `test_sanitiser_rewrites_broken_who_question_long` updated to assert „თქვენი შვილისთვის" (Session 7 revert).
- [tests/test_live_qa_georgian_admin_booking_patch.py](ai-agent/tests/test_live_qa_georgian_admin_booking_patch.py) — `test_adult_followup_who_question_uses_skhva_adamianistvis` renamed to `_uses_shvilistvis`; `test_sanitizer_rewrites_old_who_question` rewritten to verify the inverse mapping.
- [tests/test_full_live_qa_session6_patch.py](ai-agent/tests/test_full_live_qa_session6_patch.py) — `test_3_followup_question_uses_skhva_adamianistvis` renamed to `_uses_shvilistvis`.
- [tests/test_manager_email_wording.py](ai-agent/tests/test_manager_email_wording.py) — `test_deeper_concern_line_omitted_when_empty` updated to allow free-form em-dash in prose (Session 7 summary uses " — " as sentence punctuation); `test_summary_does_not_repeat_challenge` relaxed to allow ≤2 occurrences (structured details + summary) but forbids the doubled live-bug pattern; `test_full_booked_email_structure` updated to assert the new „ახალი კონსულტაცია ჩაინიშნა" headline.

**Behaviour change:**
- Reschedule never leaves two active bookings. When `lead.calendly_booked=True` + `lead.calendar_event_id` non-empty AND the user's new `datetime_iso` differs from the current one, the executor reroutes through the safe-ordering reschedule path. The result-shape carries both legacy `booked_date` / `booked_time` AND reschedule-specific `new_date` / `new_time` / `old_cancel_failed` so callers can render the right wording. The pending_booking dict carries `source="reschedule"` + `old_event_id` + `old_booked_datetime_iso` across the confirmation turn — surviving Redis round-trip.
- Adult transition response on a PARENT turn no longer dead-ends. „გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით." → „გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით. ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?".
- Adult target question wording is „თქვენთვის გსურთ თუ თქვენი შვილისთვის?". Sister/brother/friend answers still parse via `_maybe_capture_adult_target` — the wording revert is purely conversational.
- Manager email subject names the lead and surfaces booked-vs-new status at first glance. Email body uses the dedupe helper so the LLM's repeated-phrase artefact never reaches the inbox. The summary sentence concretely names what the manager needs („მთავარი ფოკუსი: X").
- WhatsApp blank-credentials path is silent: a single `[NOTIFICATION][WHATSAPP] Skipped: missing credentials (...)` line, no `httpx.post`, no traceback. Email continues working independently.
- Booking confirmation on the immediate success turn is short: greeting + date+time + manager line. Help CTA + privacy note belong to subsequent turns / discovery turns.
- No business logic outside the 6 bug paths changed — Calendar multi-busy / booking calendar / Email channel itself / Redis / Follow-up / Kill Switch / Sentry / Webhook signature / Admin auth / Comment flow / scenario runner / OpenAI model untouched.

**FULL Live QA Patch (2026-06-05 Session 2, pytest 1196 → 1251, CRITICAL 22/22) — 12 live findings:**
1. **CRITICAL** — Admin Panel adult_events not visible to live agent. Section-level metadata was being saved (description_short, price_text, location, streams) but `get_adult_events()` only read `events[]`. Result: agent said „აქტიური ღონისძიებები არ გვაქვს" while the Admin Panel showed an active event.
2. „კულტურული საღამოები რა არის?" was answered with the bare target-question instead of an explanation.
3. ADULT target question wording — re-asserted „თქვენთვის თუ სხვა ადამიანისთვის?".
4. ADULT→PARENT carryover: agent re-asked „თქვენი შვილი რამდენი წლისაა?" when adult_target_age was already known.
5. ADULT/cultural event 13-year floor re-asserted; per-event min_age can override UPWARD only.
6. Manager handoff wording: „მენეჯერთან კავშირით" and bare „დაგაკავშირებთ." without noun.
7. Sibling discount offered on single-participant inquiries („ჩემი ძმისთვის, 17 წლის").
8. Name extraction captured filler words as names („კაი ფრიდონი 595999733" → name=„კაი").
9. **CRITICAL** — Reschedule order: old Calendar event was cancelled BEFORE new one was confirmed; if new failed, user lost their slot.
10. Redundant confirmation echo: „X საათზე ჩამწერეთ კონსულტაცია, თუ ეს დრო გაწყობთ, დამიდასტურეთ" after explicit „ჩამწერეთ".
11. Calendar re-check phrases were not exhaustive („შეამოწმე კალენდარი", „კალენდარში გადაამოწმე", „არ არის თავისუფალი").
12. Booking-question wording polish („რომელი დროა თქვენთვის მოსახერხებელი?").

**Files changed (6 production + 2 prompts + 2 new templates + 1 new test file + 2 existing test bumps + 1 runner mock + 2 docs):**
- [app/services/admin_config_service.py](ai-agent/app/services/admin_config_service.py) — new `_build_fallback_event_from_section(section)` derives a single event from section-level metadata when `events[]` is empty/missing (Bug 1A). Auto-id derivation for events with title but no explicit id. New `save_adult_event` / `delete_adult_event` / `_load_adult_events_raw` / `_save_adult_events_list` / `_slugify_for_id` (Bug 1B). New privacy-safe debug log per call: `[admin_config] adult_events_loaded source=... raw=N fallback=N active=N titles=[...]` (Bug 1D).
- [app/routes/admin.py](ai-agent/app/routes/admin.py) — section save now preserves `events` (Bug 1B). 6 new routes under `/admin/programs/adult_events/events/...` (list, new, edit, save, delete) backed by `save_adult_event` / `delete_adult_event`. New `_form_to_event_dict` form translator.
- [templates/admin/adult_events.html](ai-agent/templates/admin/adult_events.html), [templates/admin/adult_event_form.html](ai-agent/templates/admin/adult_event_form.html) — minimal events[] editor templates (list + form). Inherit from `admin/base.html`.
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — `_build_context_message` surfaces `adult_target_relation` + `adult_target_age` (Bug 4). 8 new sanitizer entries: 4 manager-handoff rewrites (Bug 6) + 4 redundant-confirmation echo strips (Bug 10).
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — 4 manager-handoff sanitizer entries mirrored from PARENT (Bug 6).
- [app/agent/tools/parent_tool_executor.py](ai-agent/app/agent/tools/parent_tool_executor.py) — `_BOOKING_VERIFICATION_PHRASES` extended with 10 new phrases (Bug 11). `_reschedule_booking` fully refactored to safe ordering (Bug 9): (1) stash old state, (2) book NEW, (3) verify new event_id, (4) ONLY THEN cancel old. On new-booking failure → restore old state, NEVER touch old Calendar event. On old-cancel failure after new succeeded → keep new, return `old_cancel_failed=True` + `manager_handoff_required=True` + Sentry capture. Sheets `update_lead` best-effort marks old row Rescheduled.
- [app/flows/parent_flow.py](ai-agent/app/flows/parent_flow.py) — new `_strip_unwarranted_sibling_discount` post-process scans conversation history + current message for closed-set 2+ children triggers; without one, strips the 10% discount sentence from the response (Bug 7). New `_strip_redundant_confirmation_after_command` post-process: when the user message carries an explicit booking command („ჩამწერეთ" / „ძველი წაშალეთ" / „გადამიტანეთ" / „შემიცვალეთ"), the trailing „თუ ეს დრო გაწყობთ, დამიდასტურეთ" is stripped (Bug 10 — context-aware so the same phrase stays in the discovery path). `NAME_FILLER_WORDS` extended with 14 Georgian confirmation / filler tokens (Bug 8: „კაი", „კარგი", „კარგად", „ცხადია", „სწორია", „დიახ", „კი", „ჰო", „ხო", „ახლა", „ლადნო", „იყოს", „ოკ", „okay", „მადლობა").
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — new sections: „ADULT→PARENT გადასვლის წესი" (Bug 4); „გადატანის წესი" with reschedule wording rules (Bug 9); „რამდენიმე შვილი" rewritten with closed-set trigger list + correct discount formulation (Bug 7).
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — new „კულტურული საღამოები რა არის?" section (Bug 2); target question wording explicitly normalized to „სხვა ადამიანისთვის?" (Bug 3).
- [tests/test_full_live_qa_session6_patch.py](ai-agent/tests/test_full_live_qa_session6_patch.py) — **56 new tests** covering all 12 bugs end-to-end.
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — prompt-cap 40 KB → 44 KB.
- [tools/scenario_runner_full.py](ai-agent/tools/scenario_runner_full.py) — `_book_slot` mock now also stamps `lead.calendar_event_id="evt_runner_mock_id"` to match the strict event_id contract added by the prior 2026-06-04 Live QA Bug Fix Patch (without this update SC-46 fails because the mock returns True but no event_id, which the executor correctly treats as silent failure).

**Behaviour change:**
- An adult event saved via the *existing* Admin Panel section form (writing to section-level fields rather than `events[]`) is now surfaced as a single fallback event in the adult flow — no operator data migration needed.
- Adult event list can be managed independently via `/admin/programs/adult_events/events` (list + add + edit + deactivate). Section metadata and the events list are now orthogonal.
- ADULT→PARENT carryover: when a previous ADULT turn captured `adult_target_relation=შვილი` + `adult_target_age=X` and the user switches to camp, the PARENT engine acknowledges the known age (in-range or out-of-range) without re-asking.
- Sibling discount line is only added when the conversation explicitly mentions 2+ children OR the user explicitly asks for a discount.
- Reschedule never sacrifices the user's existing slot. New booking is fully verified before old is touched. Old cancel failures after new success surface a manager handoff without claiming the old was cancelled.
- Filler / confirmation words („კაი", „კი", „დიახ", etc.) are no longer extracted as names — the agent confirms the real name or asks for it.
- Calendar re-check phrases („შეამოწმე კალენდარი", „კალენდარში გადაამოწმე", „არ არის თავისუფალი", etc.) force a fresh `check_consultation_slot` call before any booking.
- No business logic outside the 12 bug paths changed — Calendar multi-busy / booking calendar / Email / Redis / Follow-up / Kill Switch / Sentry architecture / Webhook signature / Admin auth / Comment flow / OpenAI model untouched.



**Live QA Patch (2026-06-05, pytest 1158 → 1196) — 6 live-QA findings on gpt-4.1-mini:**
1. Filler / awkward Georgian wording („გმადლობთ, რომ გაზიარეთ", „დასთვის", „მიმოწმების შედეგად", „სიამოვნებით დაგიდგებით გვერდში", „თუ დაგეხმაროთ სხვა გზით", „რომელი დრო გიჭერს მხარს", „რომელი დრო გჭირდებათ", „გნებავთ პირვანდელ დროზე დარჩეთ").
2. ADULT transition asked „თქვენი შვილისთვის?" — wrong context in the adult-events flow. Bare „ჩემი შვილისთვის" auto-switched to PARENT, dropping the adult inquiry.
3. Adult agent told users events are „18 წლიდან" — wrong, business rule is 13-year floor.
4. Operator saved an event via Admin Panel; agent still said „ღონისძიება არ გვაქვს." (missing `id` dropped the event; missing `min_age` raised it to 18).
5. CRITICAL: User selected „5 ივნისი 10:00" but agent confirmed „8 ივნისი 10:00" (offered list had 10:00 on both days; matcher returned the first list entry).
6. Calendar freshness — re-assertion of the 2026-06-04 verification-phrase guard.

**Files changed (4 production + 1 prompt + 1 new test file + 4 existing test updates + 2 docs):**
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — 8 new wording-fix sanitizer entries (12 actual phrase variants including trailing-period / no-period / suffix-stripping forms).
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — same 8 wording-fix entries replicated for ADULT replies + new entry rewriting „ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?" → „ღონისძიების შერჩევა თქვენთვის გსურთ თუ სხვა ადამიანისთვის?". `_ADULT_FOLLOWUP_QUESTION_WHO` updated to use „სხვა ადამიანისთვის". `_PARENT_SWITCH_KEYWORDS` tightened to HARD-camp-only (removed „ჩემი შვილის" / „შვილისთვის მინდა" / „ბავშვისთვის მინდა" soft cues). `_CHILD_AGE_HINT_RE`-based bare-age switch removed. „შვილისთვის" / „ბავშვისთვის" / „შვილის" added to `_ADULT_RELATIVE_PATTERNS` so the LLM still captures the relation + asks the child's age while STAYING in adult flow.
- [app/services/admin_config_service.py](ai-agent/app/services/admin_config_service.py) — `_normalize_adult_event` now applies the 13-year floor: `min_age = max(int(min_age), ADULT_EVENT_DEFAULT_MIN_AGE)`. An operator typo („min_age: 10") or missing value defaults to 13. `get_adult_events` no longer drops events with title-but-no-id — id is auto-derived from index (`event_{idx}`). `_safe_load_yaml` documented as cache-free + adds mtime debug log so an operator can verify the right file version is being read after Admin Panel save.
- [app/agent/tools/parent_tool_executor.py](ai-agent/app/agent/tools/parent_tool_executor.py) — `_book_consultation` adds a slot-mismatch guard: after `_book_selected_slot` returns truthy AND `event_id` is non-empty, the *actually* booked datetime (read back from `lead.booked_datetime_iso`) is compared with the requested ISO. Mismatch → `reason=slot_mismatch`, full state rollback (`calendly_booked` / `booked_datetime_iso` / `calendar_event_id` / `status`), Sentry capture with `area=booking` + slot ISO + actual ISO + masked sender, per-turn success flag forced False, `manager_handoff_required=True`. Success-path response now derives `booked_date` / `booked_time` from the actual lead datetime, not the input args.
- [app/flows/parent_flow.py](ai-agent/app/flows/parent_flow.py) — new `_extract_date_hint_from_message(text)` helper parses „5 ივნისი" / „ხვალ" forms. `_user_explicit_slot_choice` now uses the hint as an additional filter: a date hint MUST also match the slot's date. With a date hint but no offered-list match, returns None (deferring to `check_consultation_slot` instead of silently picking a wrong-day slot). The pending-commit failure branch surfaces the brand-standard manager handoff line for `slot_mismatch` / `calendar_booking_failed` reasons.
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — new top-level „შერჩეული სლოტის წესი (Selected Slot Preservation — CRITICAL 2026-06-05 Bug 5)" section; „ჯავშნის წარმატების წესი" expanded to require requested ↔ actual datetime match; new `slot_mismatch` reason branch.
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — „ასაკის შესახებ ზოგადი კითხვა" section rewritten to codify the 13-year global floor + explicit ban on the false „18 წლიდან" universal claim.
- [tests/test_live_qa_georgian_admin_booking_patch.py](ai-agent/tests/test_live_qa_georgian_admin_booking_patch.py) — **38 new tests** across Bug 1 (12), Bug 2 (8), Bug 3 (7), Bug 4 (5), Bug 5 (6), Bug 6 (1).
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — prompt-size cap raised 38 KB → 40 KB; existing test mocks already routed through `_mock_book_slot_ok` from the previous patch.
- [tests/test_adult_context_routing_fix.py](ai-agent/tests/test_adult_context_routing_fix.py) — `test_bare_age_with_child_keyword_no_adult_signal_switches` updated to assert the new ADULT-stay behavior.
- [tests/test_adult_live_qa_polish.py](ai-agent/tests/test_adult_live_qa_polish.py) — `test_sanitiser_rewrites_broken_who_question_long` updated to expect „სხვა ადამიანისთვის?" rewrite.
- [tests/test_adult_llm_engine.py](ai-agent/tests/test_adult_llm_engine.py) — `test_switch_to_parent_on_child_age_in_camp_range` updated to assert the new ADULT-stay behavior.
- [tests/test_booking_date_parse_patch.py](ai-agent/tests/test_booking_date_parse_patch.py) — `FIXED_NOW` and hardcoded ISOs floated 6 months forward to 2026-12-14/15 so the past-date guard in `_check_consultation_slot` / `_book_consultation` (which reads real `datetime.now`) no longer races the wall clock; added the `timestamps.now_tbilisi` patch so `resolve_relative_datetime` picks up the mocked now.

**Behaviour change:**
- 8 awkward Georgian phrases are now rewritten by both PARENT and ADULT sanitizers (idempotent — second pass is a no-op).
- ADULT transition question reads „თქვენთვის თუ სხვა ადამიანისთვის?" — the camp-only „თქვენი შვილისთვის?" wording is dead.
- Bare „ჩემი შვილისთვის" / „N წლის ბავშვისთვის" in ADULT flow stays in ADULT. The LLM/relative-capture asks the child's age and offers adult-event matches. „ბანაკი" / „საზაფხულო ბანაკი" / „ბავშვთა პროგრამა" remain the only auto-switch triggers.
- Adult-events global minimum age is 13. Per-event `min_age` can only override UPWARD. „min_age: 10" or missing → 13.
- Admin Panel `sections.yaml` is read fresh on every request (no module cache) — operator save is visible to the next agent reply.
- Operator-saved events without an explicit `id` still surface — id is auto-derived. Title is still required.
- Booking selected-slot mismatch is now backend-enforced. A user-named date+time selects the right offered slot even when an earlier-listed slot has the same hour on a different day. After Calendar write, the actual booked datetime is compared with the requested datetime — mismatch refuses confirmation and surfaces a manager handoff. Sentry alert fires with `area=booking` + reason.
- No business logic outside the 6 bug paths changed — Calendar multi-busy / booking calendar / Email / Redis / Follow-up / Kill Switch / Sentry architecture / Webhook signature / Admin auth / Comment flow / OpenAI model / scenario runner untouched.



**Live QA Bug Fix Patch (2026-06-04, pytest 1135 → 1158) — 3 live-QA findings post Booking Date Parse patch:**
1. PARENT Sheets row showed event_interest = „ზრდასრულთა საღამოები" leaked from an earlier ADULT turn (challenge column was fixed by the previous patch but the event_interest column was not).
2. ADULT transition still dead-ended: „ზრდასრულთა საღამოები მაინტერესებს" → bot replied „გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით." with no follow-up question. The previous bare-intro detector missed the gpt-5.4-mini variants (period separator, em-dash separator, leading „ზრდასრულთა…").
3. „კარგად შეამოწმე თავისუფალია?" triggered `book_consultation` instead of a re-check. AND `calendar_service.book_slot` returned True with an empty event_id (Google Calendar HTTP 200 empty body), the agent said „ჩაგინიშნეთ" but no event was created.

**Files changed (3 production + 1 prompt + 1 new test file + 1 existing test bump + 1 existing test helper + 2 docs):**
- [app/services/sheets_service.py](ai-agent/app/services/sheets_service.py) — new `_scrub_event_interest_for_segment(lead)` helper + closed-set adult-event vocabulary list (`_ADULT_EVENT_INTEREST_STEMS_FOR_SCRUB`). `_lead_to_row` routes the Event Interest cell through the scrub helper: PARENT segment + adult-vocab content → empty cell; any other shape (ADULT / UNCLEAR / non-matching text) passes through unchanged. The in-memory `lead.event_interest` is NOT mutated — the historical interest stays readable if the user re-enters the ADULT flow.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — `_ADULT_BARE_INTRO_PATTERNS` extended with 5 gpt-5.4-mini variants (period separator, em-dash separator, bare „კულტურულ ღონისძიებებზე დაგეხმარებით.", bare „ზრდასრულთა საღამოებზე დაგეხმარებით."). New `_ends_with_dagexmarebit(text)` catch-all helper. `_ensure_adult_intro_followup` now treats any short (≤120 char) response ending in „დაგეხმარებით." as a bare confirmation and appends the next-step question.
- [app/agent/tools/parent_tool_executor.py](ai-agent/app/agent/tools/parent_tool_executor.py) — new `_user_requested_verification(message)` helper + `_BOOKING_VERIFICATION_PHRASES` closed-set („კარგად შეამოწმე", „ნამდვილად თავისუფალია", „დარწმუნებული ხარ", „ზუსტი ინფორმაცია", „გადაამოწმე" + variants). `_book_consultation` rejects with `reason=verification_requested` + `next_action=check_consultation_slot` when the user message asks for a re-check, even if the LLM passed `user_confirmed_datetime=True`. The booking success branch is hardened: after `_book_selected_slot` returns, the executor also requires `lead.calendar_event_id` to be non-empty — an empty event_id (silent Google Calendar failure) yields `reason=calendar_booking_failed` + `manager_handoff_required=True`, half-written lead state (`calendly_booked`, `booked_datetime_iso`, `calendar_event_id`, `status`) is rolled back, and `sentry_service.capture_exception` is invoked with `area=booking` + slot ISO + masked sender (never the raw name / phone).
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — new top-level „გადამოწმების წესი (Verification Phrase — CRITICAL 2026-06-04)" section codifies the re-check contract + bans the booking shortcut. New „ჯავშნის წარმატების წესი (Booking Success Confirmation — CRITICAL 2026-06-04)" section codifies the event_id requirement. `book_consultation` reason table extended with `verification_requested` + `calendar_booking_failed` branches with brand-standard wording.
- [tests/test_live_qa_bug_fix.py](ai-agent/tests/test_live_qa_bug_fix.py) — **23 new tests** across PART 1 PARENT Sheets row scrub (5 cases), PART 2 adult intro followup detection (8 cases incl. period / em-dash variants + helper unit test), PART 3 verification-phrase routing (7 cases), PART 4 backend booking success/failure (6 cases incl. silent failure + Sentry capture + state rollback).
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — prompt-size cap raised 36 KB → 38 KB for the new policy text (~1.3 KB added); added `_mock_book_slot_ok` + `_mock_book_slot_capture` helpers + every `book_slot` mock that returns True now also stamps `lead.calendar_event_id = "evt_mock_test_id"` to match the new executor success contract.

**Behaviour change:**
- PARENT Sheets row Event Interest column is always blank when the only `lead.event_interest` content is adult-cultural-event vocabulary. ADULT segment rows preserve the same vocabulary unchanged. The scrub is segment-scoped — UNCLEAR / non-matching content passes through.
- Adult flow bare confirmations („ZRDASRULTA + დაგეხმარებით." / „KULTURUL + დაგეხმარებით.") always get a next-step question appended. Long answers (>120 chars) or answers that already have a `?` are untouched.
- „კარგად შეამოწმე" / „ნამდვილად თავისუფალია" / „დარწმუნებული ხარ" force a fresh `check_consultation_slot` call. The LLM cannot bypass this with `user_confirmed_datetime=True` — backend refuses the book with `reason=verification_requested`.
- A silent Calendar booking failure (HTTP 200 + empty body) is now detected and surfaced as `reason=calendar_booking_failed`. The agent's brand-standard reply is „სამწუხაროდ, ჩანიშვნა ვერ მოხერხდა. გთხოვთ, სცადოთ ან მომწერეთ და მენეჯერი დაგიკავშირდებათ." and the manager-callback CTA. The fake-booking guard in `parent_flow._sanitise_booking_confirmation` already prevents the LLM from hallucinating „ჩაგინიშნეთ" against a non-booked lead — now combined with the explicit backend reject + Sentry alert.
- Failed-booking telemetry now lands in Sentry (when DSN configured) with `area=booking`, slot ISO, masked sender, and reason — operator can spot Calendar outages without trawling logs.
- No business logic outside the 3 bug paths changed — Calendar multi-busy / booking calendar / Email / Redis / Follow-up / Kill Switch / Sentry architecture / Webhook signature / Admin auth / Comment flow / OpenAI model untouched.



**Booking Date Parse + Lead Field Separation Patch (2026-06-04, pytest 1105 → 1135) — 2 live-QA findings:**
1. „ხვალ" parsed as past date. User: „მოვიფიქრე კონსულტაცია და ხვალ მინდა 11 საათზე" → Agent: „წარსულ თარიღზე კონსულტაციას ვერ ჩავნიშნავთ…". Root cause: the LLM had no Tbilisi current-date context, so when it tried to resolve „ხვალ" → ISO it landed on a stale date that the past-date guard rejected.
2. ADULT event interest leaked into PARENT challenge in CRM. User first asked about adult cultural evenings for a sister, then switched to camp for child. The PARENT challenge column in Sheets showed „ზრდასრულთა საღამოები" — the prior ADULT event vocabulary was re-encoded by the LLM as the camp challenge.

**Files changed (4 production + 1 prompt + 1 new test file + 1 existing test bump + 2 docs):**
- [app/agent/services/timestamps.py](ai-agent/app/agent/services/timestamps.py) — new `resolve_relative_datetime(text, *, now=None)` helper resolves Georgian relative-date phrases („ხვალ" / „ზეგ" / „დღეს" / „გუშინ" / „დღევანდელ" / „ხვალინდელ" / „გუშინწინ" / „მაზეგ") plus optional time („11 საათზე" / „11:00" / „11-ზე" / „11 სთ-ზე") to a Tbilisi-aware datetime. Returns `None` when the message has no relative-day stem. Pure function; never raises.
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — `_build_context_message` always includes `today_iso_tbilisi=YYYY-MM-DD` + `now_iso_tbilisi=YYYY-MM-DDTHH:MM±04:00`; when the user's current message contains a Georgian relative-day phrase the resolved `resolved_relative_datetime_iso=...` is also surfaced so the LLM never has to guess. `maybe_capture_challenge_fallback` skip-tokens extended with adult cultural-event vocabulary so the fallback never grabs an ADULT phrase as a PARENT challenge.
- [app/agent/tools/parent_tool_executor.py](ai-agent/app/agent/tools/parent_tool_executor.py) — new `_normalise_datetime_iso_from_message` helper on `ParentToolExecutor` overrides the day of any LLM-supplied `datetime_iso` when the user message contains a relative-day phrase (preserving the LLM's HH:MM). Called at the entry of `_check_consultation_slot`, `_book_consultation`, and the reschedule branch of `_manage_consultation_booking`. New `user_message` field on the dataclass (defaults to `""`) wires it together. `_save_lead_info` rejects `challenge` / `notes` payloads that look like ADULT event vocabulary via the new `_looks_like_adult_event_interest` helper — the field stays untouched and `invalid_fields` reports the rejection.
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — new top-level „თარიღების წესი (Booking Date Parse — CRITICAL 2026-06-04)" section codifies the relative-date rules (use `today_iso_tbilisi`, map „ხვალ" / „ზეგ" / „გუშინ" verbatim, never use past wording for a future date, never re-resolve against an old booked date) and a new „ფლოუს გამიჯვნის წესი (Lead Field Separation — CRITICAL 2026-06-04)" section bans writing adult event vocabulary into `lead.challenge`.
- [tests/test_booking_date_parse_patch.py](ai-agent/tests/test_booking_date_parse_patch.py) — **30 new tests** across PART 1 relative-date parser (8 cases incl. „ხვალ მინდა", „ხვალ 11-ზე", „ზეგ 14:00", „დღეს 20:00", „გუშინ"), PART 2 context-message surface (3 cases), PART 3 executor normalisation override (5 cases incl. no-op safety), PART 4 past-date guard non-over-trigger (3 end-to-end cases through `_check_consultation_slot` / `_book_consultation`), PART 5 lead field separation (11 cases incl. `_save_lead_info` rejection / fallback skip / Lead dict round-trip / PARENT↔ADULT segment switch preserving both fields).
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — prompt-size cap raised 34 KB → 36 KB for the new policy text (~1.4 KB added).

**Behaviour change:**
- LLM now sees today's Tbilisi date in every turn — relative-date phrases like „ხვალ" resolve correctly regardless of the model's training cutoff. Backend re-resolves and overrides if the LLM still passes a stale ISO.
- The past-date guard („წარსულ თარიღზე კონსულტაციას ვერ ჩავნიშნავთ…") only fires when the resolved datetime is genuinely in the past against `now_tbilisi()`. „ხვალ" / „ზეგ" / a future date NEVER triggers it.
- PARENT `save_lead_info(challenge=…)` calls with ADULT event vocabulary („ზრდასრულთა საღამოები", „კულტურული საღამო", „პოეზიის საღამო", „ღონისძიება", „ბილეთი", etc.) are refused — the LLM gets `invalid_fields: ["challenge"]` back. `lead.event_interest` (owned by the ADULT executor) and `lead.challenge` (owned by the PARENT executor) stay strictly segment-separated in CRM exports.
- PARENT↔ADULT segment switches preserve both fields independently. Switching from ADULT to PARENT does not clear `lead.event_interest`; switching from PARENT to ADULT does not touch `lead.challenge`.
- No business logic outside the date-parse + field-separation path changed — Calendar multi-busy / booking calendar / Sheets core / Email / Redis / Follow-up / Kill Switch / Sentry / Webhook signature / Admin auth / Comment flow / OpenAI model untouched.



**Calendar Multi-Busy Check + Reschedule Wording Patch (2026-06-04, pytest 1076 → 1105) — 3 live-QA findings:**
1. Reschedule said „4 ივნისს, 14:00 თავისუფალია" then the very next check (user pressed back: „კარგად შეამოწმე თავისუფალია?") correctly said busy. Root cause — the manager's busy 10:30–19:00 was on a side calendar that the single-calendar FreeBusy query never consulted; the first "free" answer was an under-checked claim.
2. Booking calendar = where the agent creates events; the busy calendars need to be configured separately so an operator who places blocks on their main calendar (instead of the bookings calendar) doesn't get over-booked.
3. Reschedule opener „კონსულტაციის გადატანას დავეხმარები" is grammatically wrong — Georgian wants the locative case („გადატანაში დაგეხმარებით.").

**Files changed (3 production + 1 prompt + 1 env example + 1 new test file + 1 existing test bump + 2 docs):**
- [app/config.py](ai-agent/app/config.py) — added `BOOKING_CALENDAR_ID` + `BUSY_CALENDAR_IDS` settings (raw env values) and resolver methods `booking_calendar_id()` / `busy_calendar_ids()` with safe fallbacks: missing booking calendar → `GOOGLE_CALENDAR_ID`; missing busy list → `[booking_calendar_id()]`; comma-separated busy list stripped + deduped with booking calendar always at front.
- [app/services/calendar_service.py](ai-agent/app/services/calendar_service.py) — new `_BusyCalendarQueryError` exception; `_free_busy_intervals` rewritten to query EVERY id from `settings.busy_calendar_ids()` in one FreeBusy call (multi-item body), flatten busy intervals across calendars, and raise `_BusyCalendarQueryError` if ANY calendar's entry is missing OR carries a per-calendar `errors` block OR the HTTP call fails. Callers (`_get_free_slots_for_day`, `check_slot_available`, `check_slot_calendar_only`) catch the exception and treat it as fail-CLOSED ("not available"). Booking writes (`book_slot`, `cancel_calendar_event`, `create_event`, `_booked_ranges`) now target `settings.booking_calendar_id()` only — never any busy-only calendar.
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — 6 new sanitiser entries rewrite the awkward reschedule forms („კონსულტაციის გადატანას დავეხმარები" / „გადატანას დაგეხმარებით" / „გადატანას დაგეხმარები" / „გადატანას დავეხმარები" / „შეცვლას დაგეხმარებით" / „შეცვლას დაგეხმარები") → „გადატანაში დაგეხმარებით" / „შეცვლაში დაგეხმარებით".
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — `გაუქმება / გადატანის წესი` section opens with brand-standard wording, bans the awkward variants, and adds the explicit rule "never say „თავისუფალია" / „დამიდასტურეთ" / „ჩავნიშნავ" without `check_consultation_slot` calling backend first" — same rule applies to both new-booking and reschedule paths. New `reason=slot_unavailable` branch wording added.
- [.env.example](ai-agent/.env.example) — `BOOKING_CALENDAR_ID` + `BUSY_CALENDAR_IDS` block with operator guidance: comma-separated, every calendar must be shared with the service account, UI "My calendars" presence ≠ agent visibility.
- [tests/test_calendar_multi_busy_patch.py](ai-agent/tests/test_calendar_multi_busy_patch.py) — **29 new tests** covering all spec PART 6 requirements: 7 settings/fallback tests + 11 multi-calendar FreeBusy tests (queries all ids, returns union, busy on booking blocks, busy on side blocks, 10:30–19:00 blocks 11..18, 19:00/20:00 free, partial overlap, fail-CLOSED on errors block, fail-CLOSED on HTTP exception, fail-CLOSED on missing entry, get_free_slots_for_day uses multi-busy, returns empty on failure) + 3 booking-target tests (book_slot writes only to BOOKING_CALENDAR_ID, cancel targets booking calendar, legacy single-calendar deploy) + 5 sanitiser tests + 2 prompt evidence tests + 1 end-to-end reschedule executor test.
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — bumped prompt-size cap 32 KB → 34 KB for the new policy text in `system_parent_v2.md` (~700 chars added).

**Behaviour change:**
- Operators with calendar busy time spread across multiple calendars (very common — manager often blocks personal time on their main account, leaving the dedicated bookings calendar empty) must populate `BUSY_CALENDAR_IDS=<bookings>,<main>` — otherwise the agent will continue to see those slots as free.
- Bookings always go to `BOOKING_CALENDAR_ID` (or `GOOGLE_CALENDAR_ID` fallback). The agent will never write to a side calendar even if it appears in `BUSY_CALENDAR_IDS`.
- Fail-CLOSED on any per-calendar permission error (`errors` block in FreeBusy response). If the operator forgets to share a busy calendar with the service account, every availability call returns "not available" → manager handoff. Logs surface „[CALENDAR] check_slot_available freebusy failed" with the underlying reason.
- No business logic outside the calendar path changed — PARENT sales / ADULT routing / Sheets / Email / Redis / Follow-up / Kill Switch / Sentry / Webhook signature / Admin auth / Comment flow / scenario runner / OpenAI model untouched.

**Booking Availability Patch (2026-06-03, pytest 1044 → 1076) — consultation window + slot rules updated:**
1. Consultation window widened from 10:00–18:00 to **10:00–21:00** Asia/Tbilisi, weekdays only.
2. Slot duration standardised at **60 minutes** (was 30) — half-hour slots (10:30 / 11:30 / 20:30) are no longer offered or accepted.
3. First valid slot starts at **10:00**, last at **20:00** (20:00–21:00). 21:00 is closing time, never a valid start.
4. `is_within_business_hours` gains a new `half_hour_not_supported` reason that fires BEFORE the business-hours window check, so the LLM can give the brand-specific „კონსულტაციები ერთსაათიანი სლოტებით ინიშნება" wording instead of a generic out-of-hours redirect.
5. Final pre-booking re-check in `_book_selected_slot` now uses the production 60-minute duration AND fails CLOSED on Calendar API exceptions (previously fail-open). Race-condition busy-block surfaces as a refusal that the LLM routes to manager handoff.
6. Partial-overlap busy blocks correctly hide adjacent candidate slots (e.g. busy 12:30–13:30 blocks both 12:00 and 13:00; busy 12:00–17:00 hides 12/13/14/15/16, leaves 10/11/17/18/19/20).
7. Exact-boundary busy blocks do NOT spuriously block adjacent slots (busy 13:00–14:00 leaves 12:00 and 14:00 free — strict-inequality interval overlap).

**Files changed (3 production code + 1 prompt + 2 knowledge yamls + 4 existing tests + 1 new test file + 2 docs):**
- [app/services/calendar_service.py](ai-agent/app/services/calendar_service.py) — default `duration_minutes` flipped 30 → 60 on `get_free_slots`, `is_within_business_hours`, `check_slot_available`, `check_slot_calendar_only`, `book_slot`. `is_within_business_hours` adds the `half_hour_not_supported` reason. `check_slot_available` now fail-CLOSED on Free/Busy API exception.
- [app/flows/parent_flow.py](ai-agent/app/flows/parent_flow.py) — `_book_selected_slot` pre-check fail-CLOSED on exception (was fail-open); call uses default 60-min duration.
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — sanitiser entries rewriting old „10:00-დან 18:00-მდე" / „10:00-დან 19:00-მდე" → „10:00-დან 21:00-მდე" so cached LLM training-data echoes of the old hours don't ship.
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — new top-level „კონსულტაციის საათების წესი" section enumerates valid hours (10:00–20:00 start, 21:00 closing) + bans half-hour slots; `check_consultation_slot` reason table extended with `half_hour_not_supported`; outside-hours / busy / half-hour wording standardised per spec.
- [app/agent/knowledge/business_hours.yaml](ai-agent/app/agent/knowledge/business_hours.yaml) — canonical knowledge: `work_hours.end` 19:00 → 21:00, `business_hours.end` 18:00 → 21:00, `slot.duration_minutes` 30 → 60.
- [data/admin_config/business_hours.yaml](ai-agent/data/admin_config/business_hours.yaml) — admin mirror updated to same values.
- [tests/test_booking_availability_patch.py](ai-agent/tests/test_booking_availability_patch.py) — **32 new tests** across all spec PART 5 requirements: 11 valid/invalid hour matrix + 60-min event duration + 12:00–17:00 busy hiding + 12:30–13:30 partial overlap + exact-boundary non-block + whole-hour-only slot enumeration + 11-slot full window + pre-booking re-check race + Calendar API failure fail-CLOSED + Free/Busy API exception fail-CLOSED + 3 prompt/yaml documentation + 11-row reason matrix.
- [tests/test_knowledge_loader.py](ai-agent/tests/test_knowledge_loader.py) — business_hours expected values updated to match patch.
- [tests/test_template_render_equivalence.py](ai-agent/tests/test_template_render_equivalence.py) — `test_calendar_constants_unchanged` whitelists the 3 intentionally-changed constants (`WORK_END`, `BUSINESS_HOUR_END`, `SLOT_DURATION_seconds`).
- [tests/test_parent_llm_engine.py](ai-agent/tests/test_parent_llm_engine.py) — `test_patch4_get_free_slots_legacy_positional_signature` updated default 30 → 60; `test_patch6_is_within_business_hours_rejects_20_00` renamed `test_patch6_is_within_business_hours_rejects_22_00` since 20:00 is now VALID under the new window.

**Behaviour change:**
- Operator's manager calendar is now consulted for the full 10:00–21:00 window (was 10:00–18:00). Any busy event in that range blocks overlapping candidate slots.
- Half-hour booking requests (e.g. „10:30-ზე შეიძლება?") get a deterministic refusal with the half-hour-specific wording instead of a generic out-of-hours message.
- A Calendar API outage no longer fail-opens. The pre-booking re-check returns False and the booking path surfaces to the LLM as a `slot_unavailable` / manager-callback handoff. Operators must be aware that a Google Calendar outage now means consultation booking pauses — manual handoff is the fallback.
- No business logic outside booking-availability changed. Sheets/Email/Redis/Follow-up/Kill-Switch/Sentry/Webhook-signature/Admin-auth/Comment-flow/scenario-runner/OpenAI-model are untouched.

**Agent Wording Cleanup Patch (2026-06-03, pytest 1000 → 1044) — tone polish, no business logic change:**
1. Replaced awkward live-bug phrase „მენეჯერთან კავშირს მოგიწყობთ" / „კავშირსაც მოგიწყობთ" / „კავშირს მოგიწყობთ" / „მენეჯერთან დაკავშირებაში დაგეხმარებით" with the brand-standard „თუ გსურთ, დაგაკავშირებთ მენეჯერთან." everywhere.
2. Removed decorative emojis 🌿 / 😊 / ✨ / ✅ / ❌ from every user-facing surface — static templates, fallback constants, deterministic redirects, prompt example responses. Sanitisers strip them as a safety net.

**Files changed (3 production code + 5 prompts/policies + 4 static templates + 1 admin template + 5 tests + 1 new test file + 2 docs):**
- [app/agent/llm/parent_llm_engine.py](ai-agent/app/agent/llm/parent_llm_engine.py) — 7 new manager-handoff sanitiser entries + 10 emoji-removal entries (5 decorative × 2 leading-space variants); old in-replacement 🌿 in 2 places removed.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — same sanitiser additions; `_OFFTOPIC_REPLY_NAME_NOT_CONFIGURED` / `_OFFTOPIC_REPLY_GENERIC` rewritten emoji-free.
- [app/services/comment_service.py](ai-agent/app/services/comment_service.py) — `PARENT_FIRST_CONTACT_DM` / `ADULT_NO_EVENTS_DM` constants and the rich-DM builder lines emoji-free.
- [app/services/followup_service.py](ai-agent/app/services/followup_service.py) — `_FALLBACK_FOLLOWUP_24H` / `_3D` / `_7D` constants emoji-free.
- [app/flows/parent_flow.py](ai-agent/app/flows/parent_flow.py) — `_BOOKED_HELP_CTA` + decline/will-think wording + memory-info fallback emoji-free.
- [app/flows/adult_flow.py](ai-agent/app/flows/adult_flow.py) — decline / thanks / re-greet branches emoji-free.
- [app/agent/prompts/system_base.md](ai-agent/app/agent/prompts/system_base.md) — emoji rule replaced with "no emojis" instruction.
- [app/agent/prompts/system_parent_v2.md](ai-agent/app/agent/prompts/system_parent_v2.md) — emoji rule replaced; banned manager-handoff phrases added; sensitive-needs example rewritten to use the preferred phrase; example responses in DONE / decline / memory-info / age-eligibility blocks emoji-free.
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — same emoji rule replacement; new §"Manager handoff" preferred-phrase + ban list; off-topic redirect examples emoji-free; thanks/manager-data examples emoji-free.
- [app/agent/prompts/parent_communication_style.md](ai-agent/app/agent/prompts/parent_communication_style.md) — `## Emoji` section rewritten "no emojis" with explicit forbidden list.
- [app/agent/policies/parent_sales_policy.md](ai-agent/app/agent/policies/parent_sales_policy.md) — new §11.1 "Manager handoff preferred phrasing" + §11.2 "No emojis in production replies".
- [app/agent/policies/adult_sales_policy.md](ai-agent/app/agent/policies/adult_sales_policy.md) — new §7.1 "Preferred phrasing" + §7.2 "No emojis" + age-out-of-range example + off-topic example rewritten emoji-free.
- [app/agent/templates/common/routing.yaml](ai-agent/app/agent/templates/common/routing.yaml) / [parent/welcome.yaml](ai-agent/app/agent/templates/parent/welcome.yaml) / [parent/welcome_with_concern.yaml](ai-agent/app/agent/templates/parent/welcome.yaml) / [parent/price.yaml](ai-agent/app/agent/templates/parent/price.yaml) / [parent/booking.yaml](ai-agent/app/agent/templates/parent/booking.yaml) / [parent/followup.yaml](ai-agent/app/agent/templates/parent/followup.yaml) / [adult/welcome.yaml](ai-agent/app/agent/templates/adult/welcome.yaml) / [comments/replies.yaml](ai-agent/app/agent/templates/comments/replies.yaml) — every 🌿/✨ removed from user-facing text. Adult welcome's „კეთილი იყოს თქვენი ვიზიტი…" opener replaced with plain "გამარჯობა.".
- [data/admin_config/templates.yaml](ai-agent/data/admin_config/templates.yaml) — 12 default templates (welcome / camp / sunday school / adult / generic / 3× follow-ups) all 🌿-free.
- [tests/test_agent_wording_cleanup.py](ai-agent/tests/test_agent_wording_cleanup.py) — **44 new tests** covering: 11 emoji-free template checks + 5 sanitiser emoji-strip checks + 7 sanitiser manager-handoff-rewrite checks + 9 prompt/policy documentation checks + 4 sanitiser idempotency checks + 5 regression checks + 3 misc.
- [tests/test_wording_polish.py](ai-agent/tests/test_wording_polish.py) — 2 previously-emoji-preserving tests inverted to assert the sanitiser now strips 🌿.
- [tests/test_template_loader.py](ai-agent/tests/test_template_loader.py) — UTF-8 round-trip test no longer asserts 🌿 in the template (renamed accordingly).
- [tests/test_template_render_equivalence.py](ai-agent/tests/test_template_render_equivalence.py) — `ALLOWED_FULL_REWRITES` and `ALLOWED_FULL_PROMPT_REWRITES` extended with 11 templates + 4 prompts touched by the patch.
- [tests/test_comment_flow.py](ai-agent/tests/test_comment_flow.py) — 2 public-reply assertions updated to the new emoji-free wording.
- [tests/test_booked_state_polish.py](ai-agent/tests/test_booked_state_polish.py) — 1 raw test input updated to the new emoji-free CTA shape.

**Behaviour change:**
- Brand-standard manager handoff phrasing is now exactly „თუ გსურთ, დაგაკავშირებთ მენეჯერთან." Variants and the situational forms are documented in the policies (`adult_sales_policy.md` §7.1 / `parent_sales_policy.md` §11.1).
- User-facing replies no longer contain decorative emojis. Tone remains warm — carried by wording, not symbols. The sanitiser strips emojis even if the LLM produces them.
- No business logic, calendar, sheets, email, redis, scheduler, kill-switch, sentry, webhook-signature, admin-panel-auth, comment-flow, scenario-runner, or OpenAI model behaviour changed.

**ADULT Context Routing Fix (2026-06-02, pytest 956 → 1000) — 3 live-QA bugs after the model switch:**
1. `child_age` from a prior PARENT/camp turn leaked into ADULT event eligibility filtering. Live: user had `child_age=12` from camp flow, switched to ADULT and asked „რა კულტურული საღამოებია?" — agent replied „12 წლის ასაკისთვის შესაბამისი ღონისძიება არ ჩანს" instead of asking who the event is for.
2. Relative cues like „ჩემი დისთვის" / „ჩემი ძმისთვის" / „მეგობრისთვის" wrongly nudged the bot toward PARENT (camp). Live: „კულტურული საღამო მინდა ჩემი დისთვის" → „გასაგებია, ბანაკის შესახებ დაგეხმარებით."
3. ADULT transition follow-up still hit dead-ends on near-miss phrasings the original literal-pattern guard couldn't catch.

**Files changed (5 production + 1 test + 2 docs):**
- [app/models/lead.py](ai-agent/app/models/lead.py) — added `adult_target_relation` and `adult_target_age` fields; from_dict round-trips them.
- [app/agent/tools/adult_tool_executor.py](ai-agent/app/agent/tools/adult_tool_executor.py) — `_get_adult_events` gains a `child_age` leakage guard (refuses to filter when LLM-passed `user_age` matches `lead.child_age` AND `adult_age`/`adult_target_age` both empty AND no `adult_target_relation` ∈ {child, შვილი, ბავშვი}). Eligibility priority is now `user_age` → `adult_target_age` → `adult_age` (never falls back to `child_age`). `_save_adult_lead_info` accepts and validates `adult_target_relation` / `adult_target_age`.
- [app/agent/tools/adult_tools.py](ai-agent/app/agent/tools/adult_tools.py) — tool registry exposes the new parameters with docstrings.
- [app/agent/llm/adult_llm_engine.py](ai-agent/app/agent/llm/adult_llm_engine.py) — `_user_wants_parent_flow` now requires an explicit *hard camp keyword* (`ბანაკ` / `საზაფხულო` / `ბავშვთა პროგრამა`) to switch. Soft cues (`ჩემი შვილის` / `შვილისთვის მინდა` / `ბავშვისთვის მინდა`) paired with an adult-event signal (`ღონისძიებ` / `საღამო` / `კულტურულ` / `კონცერტ` / `ლიტერატურ` / `პოეტურ` / `პოეზი` / `ბილეთ`) STAY ADULT. New `_maybe_capture_adult_target` pre-LLM helper extracts „ჩემი 14 წლის დისთვის" → `(adult_target_relation="და", adult_target_age="14")` and stores on the lead BEFORE OpenAI is called. `_ensure_adult_intro_followup` gains a broader heuristic (`_looks_like_bare_intro`) that catches short ack responses (`გასაგებია` / `კარგი` / `მშვენიერია` / `კარგით` / `მადლობა` + adult-event keyword + no question + ≤120 chars). Follow-up branches: `adult_target_age` known → offer-list; `adult_target_relation` only → ask „თქვენი {relation} რამდენი წლისაა?"; `adult_age` known → offer-list; nothing → ask „ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?". `_build_context_message` surfaces the new fields.
- [app/agent/prompts/system_adult_v1.md](ai-agent/app/agent/prompts/system_adult_v1.md) — new ASAKIS memory rule for relative target; explicit "do NOT use child_age for adult events unless user said so"; relative cues stay ADULT; transition rule extended (4 branches: unknown / self / relative-known / age-known); parent-switch rule requires explicit camp keyword; `{relation}` template placeholder double-escaped for `.format()` safety.
- [app/agent/policies/adult_sales_policy.md](ai-agent/app/agent/policies/adult_sales_policy.md) — §3 phrasing table adds the relative row; new §3.1 documents THREE age fields and cross-assignment ban; new §3.2 (child_age leakage rule); new §3.3 (relative target rule); new §3.4 (transition follow-up rule); §8 (switch back to parent) tightened to require explicit camp keyword.
- [tests/test_adult_context_routing_fix.py](ai-agent/tests/test_adult_context_routing_fix.py) — **44 new tests** across all parts: 9 transition follow-up + 6 child_age leakage + 11 relative-intent routing + 6 target fields + 6 deterministic capture + 1 end-to-end + 4 prompt/policy documentation + 1 separation sanity.

**Behaviour change:**
- A child age captured during a PARENT turn (`child_age=12` from camp) CANNOT be re-used as ADULT event eligibility after a flow switch. The LLM must re-confirm who the event is for via the transition follow-up question.
- `lead.child_age` / `lead.adult_age` / `lead.adult_target_age` are three separate fields. Only `parent_tool_executor._switch_to_adult_flow` may move `child_age` → `adult_age` (when out-of-camp-range). NEVER assign from `child_age` to `adult_target_age` — the LLM must capture the target via `save_adult_lead_info`.
**Active model:** `gpt-5.4-mini` (switched from `gpt-4.1-mini`; backend `_build_completion_kwargs` sends `max_completion_tokens` for GPT-5.x / o1-o4 families; older models keep `max_tokens` — see [app/services/openai_service.py](ai-agent/app/services/openai_service.py)). Operator can flip `OPENAI_MODEL` in `.env` without code change; the boot log line `[openai] model=… token_param=…` confirms the shape in effect. ADULT sim 2026-06-02 post-patch: turn 1 now uses correct „ღონისძიების შერჩევა თქვენთვის გსურთ" phrasing (Bug 1 fixed); turn 2 with age 30 returns "no active events" since seed events are inactive (Bug 2 fixed — no invented dates / prices); turn 4 manager handoff returns manager phone correctly.
**Last 24 patches shipped this session (compact roll-up):** Georgian Wording Polish → Booking Notification QA → P3-B Redis → Admin Panel MVP → Config Unification → Admin Field Completion → Email Wording Patch → Parent Greeting Fix → Test Failures Fix → Scenario Runner Build → Scenario QA Bug Fix → Remaining Scenario Polish → Kill Switch Patch → Follow-up Scheduler Patch → Booked State Memory Response Polish Patch → Follow-up QA + Admin Template Verification → Basic Error Monitoring Patch → Comment Follow-up Logic Fix + Public Reply Ready Patch → Webhook Signature Verification Patch → ADULT LLM Engine + Cultural Events Patch (pytest 802 → 856) → Expired Booking Memory Fix Patch (856 → 873) → ADULT Off-Topic Guard + Event Grounding + Default Min-Age Fix Patch (873 → 896) → **ADULT Live QA Polish Patch (896 → 924)** — 4 live-bug fixes (broken "who is this for?" phrasing, event-detail hallucination, age re-asking, dead-end transition); new `lead.adult_age` field strictly separate from `child_age`; PARENT→ADULT switch transfers out-of-range child_age; seed events flipped to `status: inactive`; child-data privacy note added to PARENT prompt; 28 new tests → **OpenAI Model Compatibility Patch (924 → 956)** — live `BadRequestError: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.` after operator switched `OPENAI_MODEL=gpt-5.4-mini`. New `_uses_max_completion_tokens(model) → bool` + `_build_completion_kwargs(...)` route both call sites (`_chat_completion` retry loop + `chat_with_tools`) through a single chokepoint that selects EXACTLY ONE token-cap kwarg per request (never both — also a 400). Boot log `[openai] model=… token_param=…` confirms shape. 32 new tests. (2026-06-02; live `openai.BadRequestError: Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.` after the operator flipped `OPENAI_MODEL=gpt-5.4-mini` in `.env`. GPT-5.x / GPT-5.4-mini / o1 / o3 / o4-mini reject `max_tokens` — they require `max_completion_tokens`. New `_uses_max_completion_tokens(model) → bool` helper in `app/services/openai_service.py` checks the model name against a closed-set list of prefixes (`gpt-5`, `o1`, `o3`, `o4`) and fragments (`5.4` — covers `gpt-5.4-mini` and successors). New `_token_param_name(model)` exposes the selected kwarg name for the boot log. New `_build_completion_kwargs(model, messages, max_tokens, temperature?, tools?, tool_choice?)` assembles the request dict with the correct token-cap parameter name — and CRITICALLY never sends BOTH `max_tokens` AND `max_completion_tokens` in the same request (the API rejects that too). Both production call sites — `_chat_completion` (legacy retry path used by `detect_segment` / `detect_start_intent` / `generate_parent_value_response` / `generate_response` / `generate_summary` / `compose_reply` / `analyze_parent_turn`) and `chat_with_tools` (used by `parent_llm_engine` + `adult_llm_engine`) — now route through the builder. New one-time boot-log line `[openai] model=<model> token_param=max_tokens|max_completion_tokens` (never logs API key, never logs prompt content). Older production model `gpt-4.1-mini` keeps using `max_tokens` exactly as before — byte-compatible kwargs verified by `test_chat_completion_existing_legacy_path_byte_compatible`. 32 new tests in `tests/test_openai_model_compatibility.py` covering: 17-row parametrised matrix of model-name → expected kwarg shape (legacy / new family / case-insensitive / empty / None); `_build_completion_kwargs` legacy path; new-family path; tools+tool_choice pass-through; temperature=None omission; both call sites (legacy `_chat_completion` and `chat_with_tools`) send the correct kwarg under each model family; engine-integration tests confirm `parent_llm_engine.run_parent_llm_turn` and `adult_llm_engine.run_adult_llm_turn` drive a GPT-5.x request through `chat_with_tools` with `max_completion_tokens` (NOT `max_tokens`); byte-compatibility test asserts the legacy call-site shape under `gpt-4.1-mini` is exactly `{model, messages, max_tokens, temperature}`. Pytest 924 → 956. **Operator action:** to test the live `gpt-5.4-mini` switch end-to-end, restart the app with `OPENAI_MODEL=gpt-5.4-mini` in `.env` — the boot log will show `[openai] model=gpt-5.4-mini token_param=max_completion_tokens` confirming the new shape is in effect. No code changes, no prompt changes, no test-suite changes needed to flip models — the helper is data-driven.) (2026-06-02; 4 live-QA bugs surfaced after the off-topic patch went live). Bug 1 — bot was asking „თქვენთვისაა ღონისძიებები თუ თქვენი შვილისთვის?" (broken Georgian) → sanitiser rewrites it to „ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?" and the system_adult_v1.md ASAKIS section was rewritten with the three-branch rule (self-context / child-context / ambiguous). Bug 2 — bot was filling empty admin_config fields with placeholders like „თარიღები და ფასები ახლახან ზუსტდება" → new sanitiser entries strip „ახლახან ზუსტდება" family entirely; new STRICT EVENT GROUNDING section in system_adult_v1.md + adult_sales_policy.md §5 require the LLM to use ONLY configured fields and to say „ამ დეტალს მენეჯერი დაგიზუსტებთ." for empty fields; seed events `poetry_evening` + `book_club` in `data/admin_config/sections.yaml` flipped `status: active` → `status: inactive` so they don't surface placeholder shells until the operator populates them via Admin Panel. Bug 3 — bot was re-asking „რამდენი წლის ბრძანდებით?" after the user had already disclosed age → new `lead.adult_age: str` field (kept STRICTLY separate from `lead.child_age` — CRITICAL invariant documented in CLAUDE.md and lead.py docstring); `save_adult_lead_info` tool gains `adult_age` parameter with backend validation (range 0–120, refuses garbage); `_get_adult_events` executor reads `lead.adult_age` automatically when the LLM omits `user_age`; `_build_context_message` surfaces `adult_age=X` in the context block; `parent_tool_executor._switch_to_adult_flow` now transfers `child_age` to `adult_age` AND clears `child_age` when the value is outside the camp range [9, 17] (a 25-year-old misclassified as „ჩემი შვილისთვის" is rescued from the camp flow). Bug 4 — bot was producing just „გასაგებია, ზრდასრულთა ღონისძიებებზე დაგეხმარებით." and stopping (dead-end) → new `_ensure_adult_intro_followup(response, lead)` post-process in `adult_llm_engine` detects the bare-confirmation pattern (no `?`, ≤ 120 chars) and appends the appropriate next question: who-clarification if no `adult_age` known, "გნებავთ, აქტიური ღონისძიებები შემოგთავაზოთ?" if age is known; the system prompt's new გადასვლის წესი section guides the LLM toward the correct form on the first pass. Part 5 — child-data privacy note: new section in `system_parent_v2.md` instructs the LLM to append „თქვენი ინფორმაცია გამოიყენება მხოლოდ კონსულტაციისთვის და საჯაროდ არ გამოქვეყნდება." in 4 specific triggers (child age request / child challenge request / special-needs handoff / contact request after child-sensitive turn), with explicit DO-NOT rules (every turn / adult-self contexts / off-topic redirects / recent-repeat within 3 turns) and a dedicated „რატო გჭირდება ასაკი?" handler. Prompt-size cap raised 30 KB → 32 KB to accommodate the ~700 chars of new policy text. 28 new tests in `tests/test_adult_live_qa_polish.py` covering phrasing (4) / grounding (6) / age memory (5) / PARENT→ADULT switch transfer (3) / transition follow-up (5) / privacy note (3). Pytest 896 → 924; CRITICAL 22/22 preserved. (2026-06-02; live observation showed the bot explaining who Elton John is and answering "Mufasa is Simba's father" — bot is not a general ChatGPT, must stay bounded to სიტყვის აკადემიის events. New deterministic `_maybe_adult_offtopic_reply(user_message, conversation) → str | None` helper in `adult_llm_engine.py` runs BEFORE OpenAI is called for the camp-switch and off-topic redirect paths. The guard's decision tree: (1) length < 10 chars → None; (2) message contains any configured event term — title / guest / theme / format / location / description token (sourced live from `admin_config_service.get_adult_events()`) → None; (3) message contains in-scope domain stem (`ღონისძიებ`, `საღამო`, `ბილეთ`, `ჯავშნ`, `მენეჯერ`, `წლის`, `ფასი`, etc. — NOTE: `ფასი` 4 chars, NOT `ფას` 3 chars which falsely matches inside `მუფასა`) → None; (4) general-knowledge "ვინ არის / ვინაა / ვინ იყო" pattern → return „ამ სახელით ღონისძიება ჩვენს მიმდინარე პროგრამაში არ ჩანს. თუ გსურთ, შემიძლია არსებული კულტურული შეხვედრები გაგაცნოთ 🌿"; (5) "რა არის / რა იყო" pattern OR "მითხარი … შესახებ" pattern OR known off-topic topic stem (`კლიმატ`, `მათემატიკ`, `მუფასა`, `სიმბ`, `გენდალფ`, etc.) OR relation question (`მამაა / დედაა / მამა თუ / დედა თუ` + "?") → return „ამ კითხვაზე ვერ დაგეხმარები 😊\nთუ ჩვენს ღონისძიებებზე გაქვთ კითხვა, სიამოვნებით."; (6) otherwise → None (LLM handles). The guard NEVER calls OpenAI, NEVER asks „რომელ ღონისძიებასთან დაკავშირებით?" (the bug wording that implied unknown people might be in the program). New OFF-TOPIC section in `system_adult_v1.md` instructs the LLM to never explain celebrities / fictional characters / general knowledge unless they're configured as event guests, with explicit "name-not-configured" and "generic factual" reply variants. New §12 *Scope rule* in `adult_sales_policy.md` documents the bounded scope (configured events / event details / age eligibility / reservation / manager / camp switch) and disallowed scope (general knowledge / celebrity bios / fictional characters / movie trivia / religion / war). `ADULT_EVENT_DEFAULT_MIN_AGE` lowered 18 → 13 — per-event `min_age` STILL overrides (test `test_explicit_min_age_18_still_hides_age_13` asserts an event with explicit 18 is hidden from a 13-year-old). Seed events `poetry_evening` + `book_club` in `data/admin_config/sections.yaml` updated to `min_age: 13` (operator can raise per event). Existing `tests/test_adult_admin_config.py` updates: `defaults_to_18` renamed `defaults_to_13`, `boundary_equal_to_min_age` expected set updated, NEW `test_explicit_min_age_18_still_hides_age_13`. 22 new tests in `tests/test_adult_scope_guard.py` covering Mufasa block / Elton-John-not-configured block / Elton-John-configured allow / climate / math / fiction stems / in-scope conversational messages NOT blocked / short messages skip guard / configured guest allow / camp keyword still switches to PARENT / off-topic guard never calls OpenAI / off-topic guard never changes segment / default min_age constant is 13 / event without min_age defaults to 13 / age 13 sees default event. Pytest 873 → 896; test_agent.py ✅.) (2026-06-02; new `parent_flow._expire_past_booking_if_needed(lead) → bool` helper compares `lead.booked_datetime_iso` against Asia/Tbilisi "now" and demotes stale leads to `calendly_booked=False` + `booked_datetime_iso=""` without touching Calendar / Sheets / `calendar_event_id`; wired into `_run_llm_engine_safely` so the LLM's `_build_context_message` reads the refreshed `booked=no`, `_maybe_memory_info_reply` so a stale `2026-05-29` date is never echoed back as active, and `_strip_consultation_cta_if_booked` so a legitimate fresh-booking CTA for an expired lead isn't scrubbed; memory-info reply for expired booking now closes with the spec-prescribed line „კონსულტაციის აქტიური დრო ამ ეტაპზე არ ფიქსირდება. სურვილის შემთხვევაში, შემიძლია თავისუფალი დროები შემოგთავაზოთ.", never mentions the old date, never says „უკვე არის ჩანიშნული" / „გამოგიშლით"; new sanitiser entries replace „მენეჯერთან გავარკვევთ" → „მენეჯერი დეტალებს დაგიზუსტებთ" (3 variants + misspelled „გავარჩევთ"); new system_parent_v2.md sections for *sensitive needs* (manager-handoff for special-needs / medical / psychological mentions — never promise camp fits every need, never diagnose, manager OWNS the clarification) and *expired booking memory* (LLM told that backend already refreshes stale `calendly_booked` and to never echo the past date); `tests/test_booked_state_polish.py` `_make_booked_conversation` helper now computes a dynamic future ISO so booking tests stay green as wall-clock advances; `test_memory_info_includes_booked_datetime_in_georgian_format` pinned to 2030; engine-prompt size cap raised 28 KB → 30 KB to accommodate ~1.1 KB of new policy text; 17 new tests in `tests/test_expired_booking_memory_fix.py`; pytest 856 → 873) (5 new core files: `adult_llm_engine.py` + `adult_tools.py` + `adult_tool_executor.py` + `system_adult_v1.md` + `adult_sales_policy.md`; 6-tool registry — `get_adult_events`, `get_adult_event_details`, `save_adult_lead_info`, `request_adult_manager_callback`, `provide_adult_reservation_link`, `switch_to_parent_flow`; per-event `min_age` field in `data/admin_config/sections.yaml` with default-to-18 fallback in the loader; age-aware question phrasing („თქვენი შვილი რამდენი წლისაა?" vs „რამდენი წლის ბრძანდებით?"); deterministic adult-to-parent switch on camp keywords + child-age-in-range; system_parent_v2.md updated so age outside [9,17] uses a polite question BEFORE `switch_to_adult_flow` — never auto-pivot ≥ 18; ADULT engine sanitiser fixes `აკადემიაის` → `აკადემიის`, strips „კეთილი იყოს თქვენი ვიზიტი…" greeting, „სიამოვნებით გაგაცნობთ ჩვენს კულტურულ საღამოებს" opener, and the retail / pressure-word family („ბილეთი შეიძინეთ", „სალარო", „იჩქარეთ", „ბოლო ადგილები"); 3 new Lead fields — `preferred_event`, `seat_count`, `reservation_status` (CRM states New → Qualified → ManagerHandoff → ReservationRequested → LinkSent → Lost); ADULT flow CONFIRMED never books Calendar (regression test asserts no `book_slot` / `create_event` call); manager phone sourced from `admin_config_service.get_manager_phone()` chain — `manager_contacts.yaml` → `settings.MANAGER_PHONE_NUMBER` → `company.yaml` → adult section `manager_contact` — never hard-coded in Python; `tools/sim_adult_flow.py` 3-scenario QA helper (direct adult interest / child→adult switch / adult→parent switch) with all external sinks mocked; `USE_ADULT_LLM_ENGINE` flag defaults `True` (live setting); engine fail/empty → legacy `adult_flow.handle` state machine fallback preserved unchanged; `tests/conftest.py` autouse fixture pins flag OFF for the legacy ADULT tests so they continue to drive the state machine; 54 new tests across 4 files: `test_adult_admin_config.py` (13) + `test_adult_tool_executor.py` (18) + `test_adult_llm_engine.py` (18) + `test_adult_manager_notification.py` (5)).
**Next task:** Run full `scenario_runner_full.py --priority CRITICAL` (user permission required, ~3–5 min, $1) → Adult flow live audit on real Instagram (P3-E) → Railway deploy prep + client credentials handover + WhatsApp manager + App Review → `.gitignore` + secret rotation.

**Future verticals pattern** (documented for Sunday School / Emigrants / future):
The ADULT engine is the template. To stand up a new vertical, repeat:
1. `data/admin_config/sections.yaml` → new section entry with `events` list (if list-shaped) or scalar fields.
2. `data/admin_config/templates.yaml` → DM / public-reply templates.
3. `app/agent/prompts/system_<vertical>_v1.md` → vertical-specific system prompt.
4. `app/agent/policies/<vertical>_sales_policy.md` → operational rules.
5. `app/agent/tools/<vertical>_tools.py` → tool registry (data only).
6. `app/agent/tools/<vertical>_tool_executor.py` → backend validator/executor (security boundary).
7. `app/agent/llm/<vertical>_llm_engine.py` → tool-calling loop + sanitiser.
8. `app/services/conversation_service.py` → segment routing entry.
9. `app/flows/<vertical>_flow.py` → engine wrapper + legacy fallback.
10. New `USE_<VERTICAL>_LLM_ENGINE` flag in `app/config.py` + `.env.example`.
11. Tests under `tests/test_<vertical>_*.py`.

Sunday School + Emigrants intentionally NOT implemented in this patch.

A new Claude session should read this top-to-bottom once, then keep §12 (How to Resume) handy.

---

## 1. Project Overview

**What this is.** Python/FastAPI AI sales agent for "სიტყვის აკადემია" (Word Academy, Georgia). Answers inbound Instagram DM + Facebook Messenger in Georgian, 24/7, qualifies the lead, and books a free consultation on Google Calendar. Sales manager is notified by Email + WhatsApp + (optional) SMS.

**Client:** სიტყვის აკადემია
**Platforms:** Instagram DM, Facebook Messenger, WhatsApp (partial)
**Language:** Georgian (100% — the agent never replies in English)
**Availability:** 24/7

**Two product flows:**
- **PARENT** — children's summer camp (ages 9–17). LLM-driven sales engine (P3-C) when `USE_PARENT_LLM_ENGINE=true`; legacy state machine otherwise. Ends with a consultation booking + CRM save + manager notification.
- **ADULT** — adult cultural evenings. Shows event list, hands off via a booking link. **Untested live.**

**Also handles:**
- IG + FB public **comments** — hashtag-based segment hint, intent classification, DM trigger.
- **Calendar booking** (Google Calendar service account).
- **CRM save** to Google Sheets (`Leads` + `Comments` tabs).
- **Manager notification** (Email/SMTP + WhatsApp Cloud API + optional Twilio SMS).
- **48h cold-lead follow-up** (in-process APScheduler hourly tick).
- **5–15 s message debounce** so split DM fragments join into one logical turn.

**Tech stack:**
- FastAPI + Uvicorn (Python 3.10.11, system install — no venv currently)
- OpenAI `gpt-4.1-mini` — intent classifier, response composer, summary, adult event renderer, **tool-calling engine (P3-C)**
- Meta Graph API v19.0 (one stale v18 reference in `notification_service.py:28` — see §5)
- Google Calendar API + Google Sheets API (service account `credentials.json`)
- APScheduler 1h tick (in-process)
- PyYAML for templates + knowledge

**Template-ability.** Code generalises to any client by editing `.env` + `data/knowledge_base.txt` + `data/events.txt` + the camp YAML at `app/agent/knowledge/camp_2026.yaml`. No client-name strings hardcoded in Python (sourced from `settings.COMPANY_NAME`).

**Commercial package:**
- Setup: $1,000–1,500 (one-time)
- Monthly support: $200–250
- Tools (client side): $20–90/month (OpenAI + Railway + Twilio if used)

---

## 2. Phase History

| Phase | What shipped | Status | Tests |
|---|---|---|---|
| **Day 1** | FastAPI skeleton, Meta App, Page, IG, GCloud, ngrok, .env wiring | ✅ | — |
| **Day 2** | Live end-to-end: 10 bug fixes, webhook wire-up, Calendar booking, Sheets save. Root cause fix: AI was generating replies but Meta wasn't receiving them. | ✅ | — |
| **Day 3** | Booking fixes: false-availability bug, past-slot bug, custom-datetime parser (`22 მაისს 14:00`). | ✅ | — |
| **Day 4** | Contact info: ASK_NAME state, phone field, Calendar event with full lead context, prompts shortened. | ✅ | — |
| **Phase 3 — Migration** | Prompts → `app/agent/prompts/*.md`; templates → `app/agent/templates/**.yaml`; facts → `app/agent/knowledge/*.yaml`. Three byte-identity verifiers. | ✅ | 104 pytest |
| **Phase 3.6A/B** | Recoverable UNCLEAR segment + deterministic keyword classifier; `test_agent.py` rewrite to live 7-message flow. | ✅ | +7 / 61/0 |
| **Phase 3.8 — LLM Composer** | `parent_reply_composer.py` for the 4 PARENT discovery turns. `USE_LLM_COMPOSER` flag (default false). Fact-safety post-check. | ✅ | 104→127 |
| **Phase 3.9 — LLM Turn Analyzer** | `parent_turn_analyzer.py` + `parent_turn_router.py` (analyzer → router). Intent classification, factual Q&A, manager handoff. `USE_LLM_TURN_ANALYZER` flag (default false, `.env` set true). | ✅ | 127→146 |
| **P0 — Silent Intent Router + Premium tone** | `parent_intent_detector.py` (deterministic-first). Strict priority order. Premium response builders. Fake-booking guard. `parent_communication_style.md`. | ✅ | 146→160 |
| **P1 — Pending Booking + Redis-ready state** | `conversation.pending_booking` field. Multi-turn booking flow. `Conversation.to_dict/from_dict`. JSON-serialisable. | ✅ | 160→175 |
| **P2 — Composer + Timezone + UX** | `compose_post_booking_response`, `_classify_done_event` (7 events), `timestamps.py`, Sheets timestamps Asia/Tbilisi. Discovery rewritten neutral. | ✅ | 175→192 |
| **P3-C SAFE — LLM Tool-Calling Engine** | `parent_llm_engine.py` + `parent_tools.py` (5 tools: get_camp_info, get_available_slots, book_consultation, request_manager_callback, save_lead_info) + `parent_tool_executor.py` (backend validator/executor) + `system_parent_v2.md`. `USE_PARENT_LLM_ENGINE` flag (default `False`). Engine fail/empty → legacy fallback. Final-stage fake-booking guard runs on engine output. | ✅ | 192→213 |
| **P3-C PATCH 1** | `user_confirmed_datetime: bool` required in `book_consultation` (auto-booking blocked). Registration vs consultation explicitly separated. Cancel/reschedule (`manage_consultation_booking` tool) with manager-handoff fallback. Adult handoff (`switch_to_adult_flow` tool). `calendar_event_id` on Lead + `cancel_calendar_event` in calendar_service. `book_slot` now stashes event_id on the lead. | ✅ | 213→230 |
| **P3-C PATCH 2** | 14 forbidden-phrase rewrites (`გაიმეორეთ` / `განვადებაში` / `მენეჯერის კავშირი` / „რაც მალე იქნება შესაძლებელი" / …). CRM summaries Georgian-only with `_looks_like_english_summary` detector + Georgian fallback. Consultation CTA after factual answers. Soft DONE-state composer. `_chat_completion` with system message for `generate_summary`. | ✅ | 230→243 |
| **P3-C PATCH 3** | Source docs (PDF + DOCX + MD) read once and distilled into: `audience_segments.yaml` (4 segments + 3 micro), `parent_sales_policy.md`, `followup_strategy.yaml` (3 stages + scenario followups). Compact sales context block injected per turn (situation-aware: age unknown / eligible / ineligible, price asked, declined). Conversation gains 5 follow-up readiness fields: `last_bot_message_at`, `followup_stage`, `followup_blocked_reason`, `last_meaningful_interest`, `stopped_after`. Decline / will_think / price / asked_no_more_messages / booked / manager_handoff markers captured automatically by `conversation_service`. `tests/conftest.py` autouse fixture pins engine off for legacy tests. | ✅ | 243→259 |
| **P3-C PATCH 4** | Live-sales wording fixes: „ჩამოუყალიბეთ" → „მითხარით", „აზრი აქვს" → „გასაგებია", „დეტალებს ცოცხლად" → „დეტალურად", grammar fix for „რისი მიღება გსურთ თქვენი შვილისთვის". Camp interest opening = 1 value sentence + 1 age question (no FAQ dump, no price-first). Pain/challenge → concrete mechanisms („ეხმარება", „უწყობს ხელს"; never „მოაგვარებს" / „გადაჭრის"). Consultation date strictly separate from camp stream dates (consultation can happen before camp starts). Exact slot/date check via new `date_iso` param on `get_available_slots`; `calendar_service.get_free_slots(start_date=..., days=...)` keyword-only range form (back-compat with legacy positional `target_date`). Smart `save_lead_info` challenge preservation (substring no-op / richer promotion / unrelated append). | ✅ | 259→276 |
| **P3-C PATCH 5** | Live booking commit fix. New `_maybe_commit_pending_booking_engine()` in `parent_flow` runs BEFORE the engine, detects explicit slot selection from `_last_slots_by_sender`, records `conversation.pending_booking` with `user_confirmed_datetime=True` / `source="user_selected_slot"`, then deterministically commits booking when the next message supplies name+phone. Engine context now exposes `pending_booking_iso` so modality questions don't lose the slot. Fake-confirmation guard strengthened: tracks per-turn `book_consultation_success_for_conversation` flag — confirmation phrases pass only when the tool ACTUALLY succeeded this turn or `lead.calendly_booked` is True from a previous turn. Phone-masking in logs (`595***733`). 16 new sanitiser rewrites including „რომ სწორად გითხრათ" → drop, „გაგივლით" → „აგიხსნით", „დაგიბაროთ"/„დაგიბარებთ" → „ჩავნიშნოთ". | ✅ | 276→297 |
| **P3-C PATCH 6** | Exact-slot availability truth. New `check_consultation_slot(datetime_iso)` tool — bypasses the truncated `get_available_slots` list (capped at 6) and asks Calendar directly. Returns granular `{available, inside_business_hours, calendar_available, reason, alternative_slots}` with reasons `outside_business_hours` / `weekend` / `buffer_today` / `calendar_busy` / `past_datetime` / `invalid_datetime`. Fix to `_get_free_slots_for_day`: `SLOT_BUFFER` now applied ONLY when `target_date == today_tbilisi`. New shared helper `is_within_business_hours(dt) → (ok, reason)` used by `check_slot_available`, the new tool, and the executor's pre-booking gate. New `[slot_check]` log cascade. | ✅ | 297→311 |
| **P3-C PATCH 7** | Final QA edges. `_maybe_handle_time_change` detects "ახლა ვიფიქრე და 15:00 მირჩევნია" → re-runs exact slot check, updates pending_booking with `source="user_changed_slot"` on availability OR restores the snapshot when busy. Deterministic decline handler (`_maybe_handle_decline_engine`) for „დავფიქრდები" / „არა მადლობა" / „ვიფიქრებ" — short calm Georgian, no CTA, clears pending on hard decline. Adult flow global intent guard at top of `adult_flow.handle()` catches identity / human-vs-robot / greeting / thanks / decline / manager before the state machine loops. Sanitiser additions: drop `precisely`, fix „ეკრან რეჟიმიდან" → „ეკრანის რეჟიმიდან", naturalise „სრულად ერგება" → „შესაფერისია", collapse duplicated „თუ … თუ …" clauses. New `reset_conversation_for_sender(sender_id)` test-isolation helper. | ✅ | 311→334 |
| **P3-C PATCH 8** | Final wording cleanup. `_maybe_static_welcome` returns `UNCLEAR_ROUTING` (two-segment menu) at `state=START` + pure greeting — engine never consulted for bare „გამარჯობა" first turn. Adult-switch wording cleaned: „ერთ წუთში გავხსნი" / „გადაგამისამართებთ —" stripped (no false delayed-message promise). New `_strip_consultation_cta_if_ineligible` logic guard removes „კონსულტაციაზე ჩაგწერთ" CTAs whenever `lead.child_age` falls outside [9,17]. System prompt: screen-distance mechanism now CONDITIONAL on user actually mentioning screen / phone. Generic greetings „როგორ შემიძლია დაგეხმაროთ დღეს?" / „თუ რაიმეში დაგჭირდებათ დახმარება" stripped. | ✅ | 334→355 |
| **Comment Flow PATCH 1** | New `ENABLE_PUBLIC_COMMENT_REPLY: bool = False` config flag. Public reply (Meta replies API) now optional and its failure NEVER blocks the DM. Hashtag matching rewritten — `_normalize_hashtag` strips `#`, trims, casefolds on BOTH sides so „ბანაკი" / „#ბანაკი" / „BANAKI" / " ბანაკი " all normalise identically. `_has_adult_events_configured()` heuristic added. DM no longer gates on `has_dm_history`. Detailed `[COMMENT] Attempting DM` / `[COMMENT] DM sent` log cascade. | ✅ | 355→375 |
| **Comment Flow PATCH 2** | Fix Facebook comment DM routing. New `messenger_service.send_private_reply(comment_id, text)` posts to `/{PAGE_ID}/messages` with `recipient = {"comment_id": …}` — Meta's documented path for "DM after a public comment". `send_dm_from_comment` now routes `platform ∈ {facebook, instagram}` + non-empty `comment_id` through private reply; legacy `send_message(messenger)` path preserved for back-compat. The old `[send_message] Unsupported platform: facebook` log line is gone. **Live-tested ✅ — tester FB account received "Page responded privately" notification.** | ✅ | 375→387 |
| **Comment Flow PATCH 3** | Rich first-contact DM. PARENT pulls `location` (locative form), `duration_days`, `price_gel`, stream dates, and `registration_url` directly from `camp_2026.yaml` via new `_build_parent_rich_dm()`. ADULT lists up to 3 events from `data/events.txt` via `_parse_events_blocks()` with 📅 📍 💰 markers; no-events fallback is friendly. `_locative_location` duplicated into comment_service to avoid circular import. Both builders fall back safely on YAML / parser failure. Public reply template now uniform (no `{name}` placeholder): „გამარჯობა 🌿 დეტალები პირად შეტყობინებაში გამოგიგზავნეთ." | ✅ | 387→406 |
| **Booking Notification QA** | Manager email finally arrives. Added `ENABLE_EMAIL_NOTIFICATIONS` flag (default True) + `SMTP_FROM_EMAIL` + `SMTP_USERNAME` alias. Refactored `_send_email` with explicit gates (skip on disabled / missing MANAGER_EMAIL / missing SMTP creds), specific `SMTPAuthenticationError` → "Gmail App Password required" hint, connection-failure branch with host/port log. Wired `[notification]` cascade in `notify_manager` (independent per-channel try/except + result logs). Fixed pre-existing KeyError in `_segment_details` (missing `deeper_concern` / `desired_change` keys in `MANAGER_DETAILS_PARENT.format`). 13 new tests. | ✅ | 406→419 |
| **P3-B Redis Migration** | Restart-safe state persistence. New `app/services/redis_state_service.py` (lazy connect, safe fallback, never logs password). `conversation_service` write-through to Redis on every `process_message`; `_get_or_create_conversation` consults Redis on in-memory miss. `parent_tool_executor.manager_notified_for_conversation` mirrored to Redis. New `processed_comment:{comment_id}` guard in `webhook.handle_comment`. Config: `REDIS_URL`, `REDIS_ENABLED` (default True), `REDIS_TTL_SECONDS` (7d). conftest autouse fixture force-disables Redis for the entire test suite. 13 new tests + manual restart-sim with FakeRedis. **Live tested:** booking → server restart → name/phone arrive → booking completes ✅. | ✅ | 419→432 |
| **Georgian Wording Polish** | Sanitiser additions: `გეთანხმებით ამ დროით` → `თუ ეს დრო გაწყობთ, დამიდასტურეთ`; standalone `გეთანხმებით` → stripped; typo fixes `დაჭვება` / `დაეჭვება` → `კითხვა`; collapse double `თუ რამე დაგჭირდებათ, თუ კიდევ`; strip robotic `ყოველთვის მზად ვარ` / `აქ ვარ თქვენთვის`. System prompt: rewrote `available=true` slot-confirm template (handles known vs unknown name+phone separately), added `დახურვის წესი` section for `მადლობა` / `დავფიქრდები` / `არა მადლობა`. 16 new tests. | ✅ | 432→448 |
| **Admin Panel MVP** | Operator UI at `/admin` (Jinja2 + HTTP Basic Auth, default OFF via `ADMIN_PANEL_ENABLED`). `data/admin_config/{sections,templates,business_hours,manager_contacts}.yaml` schema. `app/services/admin_config_service.py` with loader, hashtag router, template renderer, validator, write API. `app/routes/admin.py` with 8 routes (dashboard, programs list, program edit, templates, settings). 3 canonical sections: summer_camp, sunday_school, adult_events. Post-caption hashtag routing now consults admin sections first (legacy `settings.PARENT/ADULT_HASHTAGS` is fallback). Comment rich DM tries `admin_config_service.build_section_dm` before the canonical YAML path. 51 new tests + manual sim. | ✅ | 448→499 |
| **Admin Panel TemplateResponse Bugfix** | Starlette 0.49 + FastAPI 0.121 broke the old `TemplateResponse(name, context)` positional form (compat shim raises `TypeError: unhashable type: 'dict'`). All 8 admin TemplateResponse calls now use `TemplateResponse(request, name, context)`. Added autouse `admin_disabled` fixture so `.env` flips don't leak between tests, parametrized "every admin GET route returns 200 not 500" regression sweep, static source check that `request` is the first positional arg. +9 tests. | ✅ | 499→508 |
| **Config Unification Patch** | Admin Panel becomes the source of truth for camp facts surfaced to the user. New `admin_config_service.get_camp_facts()` merges `data/admin_config/sections.yaml` (admin-first) with `app/agent/knowledge/camp_2026.yaml` (fallback). Updated `parent_tool_executor._get_camp_info` to call `get_camp_facts()` before the legacy YAML — operator price/streams/location edits flow into the LLM's `get_camp_info` tool immediately. Added `[parent_tool] get_camp_info_called=… source=… price_gel=…` and `[parent_flow] using_p3c_engine=…` debug logs. 9 new tests. | ✅ | 508→517 |
| **Admin Field Completion Patch** | Live-QA bug: operator changed `price_text` to 2200 but stale `price_gel: 2150` remained, and `get_camp_facts` preferred the int over the text. Fix at both layers: (1) form save derives `price_gel` from `price_text` via new `parse_price_gel()` helper; preserve list no longer keeps `price_gel`/`streams`/`included_items`/`discounts`; (2) `get_camp_facts` price branch now prefers `parse_price_gel(price_text)` over a stale `price_gel`. Added streams editor (textarea `name \| dates_text \| status`), `included_items_text` and `discounts_text` editors, "Normalized price_gel" preview, malformed-line validation. **Live tested:** price change → agent uses new price ✅. 26 new tests. | ✅ | 517→543 |
| **Email Wording Polish Patch** | Live email had `სიტყვის აკადემიაის` (wrong Georgian genitive) and a confusing `ღრმა ფესვი:` label. Programmatic body builder replaces the YAML format string: new `_georgian_genitive()` helper inflects multi-word brand names; `_segment_detail_lines()` conditionally includes `deeper_concern` only when meaningful AND not duplicate of challenge/desired_change; relabel `გამოწვევა` → `ინტერესი / გამოწვევა`; LLM narrative summary replaced with short fixed Georgian sentence keyed on booking state; new contact-info block; Georgian-formatted booking datetime (`27 მაისი, 10:00`). Updated `manager.yaml` template + `booking_text_no` from `არა` to `ჯერ არ არის დაჯავშნული`. 29 new tests. | ✅ | 543→572 |
| **Parent Greeting Fix** | Live conversations sometimes opened with the LLM-generated `მოგესალმებით! როგორ შემიძლია დაგეხმაროთ ბავშვთა საზაფხულო ბანაკის შესახებ?` and skipped straight to `რამდენი წლისაა შვილი?`. New `_maybe_static_welcome` fires on the bot's first reply at `state=START` regardless of message content (no longer pure-greeting-only) and returns the static two-option menu. `PARENT_WELCOME` template content swapped to the menu; new `PARENT_WELCOME_CAMP_OPENER` carries the original camp framing + age question for the legacy GREETING fallback. `_bot_has_replied` history guard. 7 new greeting-specific tests + sanitiser entry for the leaked greeting. | ✅ | 572→579 |
| **Test Failures Fix** | Cleaned the 5 pre-existing pytest failures: `test_get_camp_info_registration_returns_missing_when_url_absent` (test isolation — also stubs `admin_config_service.get_camp_facts`), 3 PATCH 7 time-change tests (env-date collision — switched test dates to safely-future July 28 + tightened `_next_year_iso` to compare by date), `test_all_templates_render_identical_except_allowed_location_correction` (added `notifications/*` Email-Wording-Patch entries + `parent/welcome` greeting-fix entry to `ALLOWED_FULL_REWRITES`). No production code touched; brought baseline to 572/572. | ✅ | 579→572 |
| **Scenario Runner Build** | 74-scenario end-to-end QA runner under `tools/scenario_runner_full.py` driving real OpenAI calls with only Calendar / Sheets / Notification / Meta mocked. Declarative `tools/scenario_library.py` (CRITICAL 22 / IMPORTANT 28 / NORMAL 24, across 7 categories: happy_path / booking / objection / adult / comment / difficult / security). Semantic-match `SAME_AS` groups for Georgian morphology, dynamic future-date placeholders, in-process fake-redis dedup, HTML report writer (`tools/reports/scenario_report_<ts>.html`), CLI flags (`--id / --category / --priority / --limit / --no-html`). First full run: **54/74**. | ✅ | 572→572 |
| **Scenario QA Bug Fix Patch** | Real production bugs surfaced by the scenario runner. `maybe_capture_challenge_fallback` deterministically captures parent concerns (screen / communication / confidence / development) when the LLM acknowledges them verbally but skips `save_lead_info`. Compound-booking hook: `_maybe_commit_pending_booking_engine` synthesises a pending booking when the current message contains both a parseable datetime AND a valid phone; `_parse_name_phone` rewritten to iterate every regex match and rescue a 9-digit local-prefix window from greedy captures. Adult pivot stabilised — system prompt now distinguishes age ≥ 18 (pivot to `switch_to_adult_flow` + offer `ზრდასრულთა კულტურული საღამოები`) from age < age_min (manager handoff only). DONE / booked state guard in `conversation_service.process_message` (booked lead never re-classifies to UNCLEAR). Identity-question short-circuit `_maybe_identity_reply` for `ბოტი ხარ? / AI ხარ?`. +6 sanitiser entries (`რომელი დრო რომელი დრო`, `ეს ბუნებრივია სრულად`, `ეს გასაგები მოტივაცია`, bureaucratic detail phrase, `გვითხარით თქვენი სახელი`, harsh `ჩაწერას ვერ დავადასტურებთ`). 22 new tests. CRITICAL **19/22 → 22/22 (100%)**. | ✅ | 572→615 |
| **Remaining Scenario Polish Patch** | Confirmed small wording / intent fixes. Four new compact system-prompt sections: price objection (empathic open + value reminder + payment split + soft CTA, bans `მოტივაცია` / `იაფია`), multi-child rule (when all 9–17 → confirm both eligible + always mention 10% დედმამიშვილების ფასდაკლება), angry user (exact opener `ბოდიშს გიხდით. ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ.` + continue current flow, bans `თუ პასუხი … მოგეჩვენათ`), past-date (`წარსულ თარიღზე კონსულტაციას ვერ ჩავნიშნავთ` + offer free slots, bans `უკვე გასულია`). Six new sanitiser entries (past-date 3 + defensive-apology 3). Minimal English camp intent: `camp / child / kid / summer` stems added to `CAMP_KEYWORDS`; `_has_explicit_english_camp_intent` helper + tightened `_maybe_static_welcome` so a plain English camp message yields to the engine (Georgian reply preserved by system prompt). Scenario calibration (SC-09 / SC-17 / SC-22 / SC-47 / SC-48 / SC-52 / SC-53) accepting natural LLM variants without weakening security `forbidden_in` lists. 12 new tests + smoke-cap raised 25 KB → 28 KB. Targeted sweep **7/7 PASSED**. | ✅ | 615→627 |
| **Kill Switch Patch** | Operator-controlled emergency disable resolved. New `AGENT_ENABLED` env flag (default `true`) parsed in `app/config.py`. New `app/services/kill_switch.py` exposes single Georgian `AGENT_DISABLED_MESSAGE` + `is_agent_enabled()` helper + `mask_sender()` PII-light logger. Three entry-point guards run BEFORE any OpenAI / Calendar / Sheets / email / Meta-send call: (1) `conversation_service.process_message` returns disabled message without creating a Conversation; (2) `webhook.handle_comment` skips intent classifier / public reply / private reply / DM / Sheets `save_comment`; (3) `followup_service.check_and_send_followups` skips `get_cold_leads` + send + `update_lead`. `/webhook` GET verify, `/health`, and `/admin` are NOT gated. Admin dashboard surfaces `Agent status: Enabled ✅ / Disabled 🔴` (read-only — env flag remains the toggle interface). Safe `[kill_switch]` log lines mask sender ids. `.env.example` updated. 21 new tests in `tests/test_kill_switch.py`. | ✅ | 627→648 |
| **Follow-up Scheduler Patch** | Sender wired to PATCH 3 Conversation markers — `check_and_send_followups()` now scans `conversation_service.get_all_conversations_snapshot()` instead of Sheets cold-lead rows. Cadence `"" → "first_24h" → "second_3d" → "third_7d"` matches `followup_strategy.yaml`; delays 24h / 72h / 168h. New `followup_exhausted` blocked reason at the 7-day terminal stage. Skips on every PATCH 3 marker (booked / registered / declined / manager_handoff_completed / asked_no_more_messages) + non-PARENT segment + missing sender_id / `last_bot_message_at` + unsupported platform. Admin templates `followup_24h` / `followup_3d` / `followup_7d` win; safe Georgian fallback constants used on miss / render error. `messenger_service.send_message` called with the Conversation's preserved `platform` so Instagram DMs route to `/me/messages` Instagram. Post-send: stage advances, `last_bot_message_at` resets to now, Redis write-through via `conversation_service._save_conversation_to_redis`. `sheets_service.get_cold_leads` timezone bug fixed (`now_tbilisi()` cutoff, naive→aware promotion); same fix applied to `get_pending_comment_followups`. `comment_service.check_comment_followups` also kill-switch gated. `get_all_conversations_snapshot()` returns a copy so APScheduler's iteration cannot race the live dict. Failed sends still advance the stage to avoid retry loops. 43 new tests in `tests/test_followup_scheduler.py`. | ✅ | 648→691 |
| **Booked State Memory Response Polish Patch** | Live observation (after 2 days running): the agent remembered the user (good) but offered ANOTHER consultation to a parent who already had one booked, used unnatural "მყარი ჯავშანი" wording, and the typo "ეკრანსიგან". Three-layer fix: (1) `parent_flow._maybe_memory_info_reply` deterministically answers "ჩემზე რა ინფორმაცია გაქვს?" / "რა გახსოვს ჩემზე?" / "ჩემზე რა იცი?" etc. with a structured Georgian summary BEFORE the engine runs — omits unknown fields, never exposes sender_id / phone / platform IDs / internal state, uses help-CTA not booking-CTA when booked, friendly fallback when nothing on record yet; (2) `parent_flow._strip_consultation_cta_if_booked` runs AFTER the engine alongside `_strip_consultation_cta_if_ineligible` to scrub any new-booking CTA the LLM leaks for a booked parent; (3) `sanitise_response_wording` rewrites "მყარი ჯავშანი გაქვთ" → "კონსულტაცია ჩანიშნულია" and "ეკრანსიგან" → "ეკრანისგან". System prompt updated with "დაჯავშნული მომხმარებლის წესი" + "მახსოვრობის შესახებ კითხვა" sections (the `{date_time}` example placeholder is double-braced as `{{date_time}}` so `_build_system_prompt`'s `.format()` doesn't raise `KeyError`). New `parent_flow._lead_is_booked` + `_format_booked_datetime_short_georgian` helpers. Privacy rule: phone deliberately omitted from the memory summary even though it's in `lead.phone` — we don't echo PII back over an unauthenticated channel. 41 new tests in `tests/test_booked_state_polish.py`. | ✅ | 691→732 |
| **Follow-up QA + Admin Template Verification** | QA + template verification only — no production logic change. `data/admin_config/templates.yaml` already had `followup_24h` / `followup_3d` / `followup_7d`; `/admin/templates` already iterates every template id into an editable textarea (so all three were already editable from the UI). Verified the live admin→scheduler round-trip: `admin_config_service.save_template("followup_24h", "...")` is read back by `followup_service._render_followup_text` on the next call with no process restart. New `tools/sim_followup.py` 8-scenario local QA helper drives `check_and_send_followups()` against seeded in-memory conversations with `messenger_service.send_message` fully mocked (no real Meta DM ever fires). Scenarios: 24h eligible, 3d eligible, 7d eligible (sets `followup_exhausted`), not-yet (<24h skip), booked skip, declined skip, kill-switch skip, messenger platform routing. Confirmed `followup_stage` is a STRING — `""` → `"first_24h"` → `"second_3d"` → `"third_7d"`, matching `followup_strategy.yaml`. +2 regression tests: admin save→render round-trip + sim_followup.py smoke import. | ✅ | 732→734 |
| **Basic Error Monitoring Patch** | Optional Sentry / structured logging — final pre-deploy blocker resolved. New `app/services/sentry_service.py` is the ONLY module that touches `sentry_sdk` directly; everywhere else calls `init_sentry`, `capture_exception`, `capture_message`, `set_tag`, `mask_sender`. Module-load `try: import sentry_sdk` flips `_SDK_AVAILABLE`; init success tracked in `_INITIALIZED`. Every public function degrades to a no-op when either flag is False — app boots normally whether or not `sentry-sdk` is installed AND whether or not `SENTRY_DSN` is set. `send_default_pii=False`, `attach_stacktrace=True`; FastApi + Asyncio integrations attempted best-effort (missing modules logged + skipped). `SENTRY_TRACES_SAMPLE_RATE` clamped to `[0.0, 1.0]`; `_parse_float_safe` helper added so a malformed env value cannot crash boot. Three capture points only — `conversation_service.process_message` (new thin wrapper around `_process_message_impl` that catches, captures with `{area, platform, sender(masked)}`, re-raises so the webhook's existing handler is unchanged), `parent_tool_executor.execute` (existing except block; captures `{area, tool}` only — tool args with PII are NOT forwarded), `followup_service.check_and_send_followups` per-conversation except (captures `{area, stage (STRING), platform, sender(masked)}`; stage values stay as `first_24h` / `second_3d` / `third_7d` — never coerced to int). Structured logs added: `[conversation] start/completed/error`, `[followup] sent/skipped/error reason=…`. `.env.example` block + HANDOFF.md `RESOLVED — Error Monitoring` section. 30 new tests in `tests/test_sentry_service.py`. Full 74-scenario sweep re-run: **74/74** (up from 67/74) with **CRITICAL 22/22** preserved. No production logic changed; only the conversation/process_message wrapper added a thin try/except + re-raise. | ✅ | 734→764 |
| **Comment Follow-up Logic Fix + Public Reply Ready Patch** | Live observation: hourly `[COMMENT] Follow-up attempt N failed (status 400)` retry-spam from ancient `CommentOnly` rows where the initial DM was never confirmed. **Eligibility:** `sheets_service.get_pending_comment_followups` now requires `DM Sent (col I) == TRUE` AND `Status (col J) == "DMSent"`; case-insensitive parse for the boolean string. `CommentOnly` / `FollowupSent` / `Expired` rows are skipped — fixes the loop at the source. **Active-conversation skip:** `comment_service.check_comment_followups` looks up `conversation_service.conversations.get(sender_id)` before each send; if found, the comment scheduler stays silent so DM follow-up owns the cadence (also respects `followup_blocked_reason` ∈ {`declined`, `asked_no_more_messages`, `manager_handoff_completed`, `booked`, `registered`, `followup_exhausted`}). **Meta 400 handling:** one attempt only, log once with truncated body (no tokens), mark the Sheets row `Expired`, prime the existing webhook `_processed_comments_lru` + Redis `processed_comment:<id>` guard so the same id is skipped on every subsequent tick. **Retry preserved:** HTTP 429 / 500 / 502 / 503 / network exceptions still get the 3-attempt × 2s-backoff loop. **Success:** marks Status `FollowupSent` (was: unmapped `CommentFollowUp` that the eligibility query couldn't filter). **Public reply ready:** `ENABLE_PUBLIC_COMMENT_REPLY` code default flipped from `False` to **`True`** — once Meta grants `pages_manage_engagement` and the Page Access Token is refreshed, public replies auto-activate on the next restart with no further code change. Until then Meta rejects with HTTP 400; the existing public-reply gate logs safely and the private DM still goes out. `.env` override to `false` still works per deploy. New `_DM_FOLLOWUP_OWNED_REASONS` frozenset, `_has_active_conversation`, `_mark_comment_expired` helpers in `comment_service`. 27 new tests in `tests/test_comment_followup_logic.py` + 1 updated default-test in `tests/test_comment_flow.py`. | ✅ | 764→791 |
| **Webhook Signature Verification Patch** | Final security blocker resolved. `POST /webhook` now runs `_verify_meta_signature(raw, header)` BEFORE the JSON parse + background task. HMAC-SHA256 keyed on `META_APP_SECRET` (with `MESSENGER_APP_SECRET` alias fallback) against the **RAW** request body (not a re-serialised JSON — Meta signs the bytes verbatim). `hmac.compare_digest` for constant-time compare. Verification failure → `403 Forbidden` with `[webhook] signature rejected` log; success → `[webhook] signature ok`; never logs raw body, header value, computed digest, app secret, or payload contents. Fail-open shape: `VERIFY_WEBHOOK_SIGNATURE=True` AND empty secret → one `[webhook] signature check skipped: META_APP_SECRET not set` warning + accept (protects legacy / local-dev installs and the existing 791-test suite that doesn't sign). Flag-off (`VERIFY_WEBHOOK_SIGNATURE=false`) is the explicit operator opt-out and stays silent. New flag in [app/config.py](ai-agent/app/config.py) + `.env.example` block. Existing `try / except` JSON-parse path preserved unchanged, so valid-signature + invalid-JSON behaves exactly as before (log + `{"status":"ok"}`). 11 new tests in `tests/test_webhook_signature.py`. **Zero existing tests modified** — no current webhook test sets `META_APP_SECRET` (verified `grep`), so fail-open keeps them green. | ✅ | 791→802 |

---

## 3. Current Architecture

### 3.1 Message lifecycle (step-by-step)

```
Meta webhook (POST /webhook)
    → return 200 immediately, defer to background_task
    → message_buffer (DEBOUNCE_SECONDS=5, MAX_WAIT_SECONDS=15)
    → conversation_service.process_message(sender_id, message, platform)
        → _record_pre_response_followup_markers (PATCH 3)
        → _classify_segment (deterministic keyword stems)
        → parent_flow.handle / adult_flow.handle / UNCLEAR_ROUTING
        → _record_post_response_followup_markers (PATCH 3)
        → final reply text
    → messenger_service.send_message (Meta Graph API, 3 retries × 2s)
```

### 3.2 PARENT flow priority order (parent_flow.handle)

```
0. P3-C engine gate
     → if settings.USE_PARENT_LLM_ENGINE:
         _run_llm_engine_safely(conversation, message)
         → parent_llm_engine.run_parent_llm_turn(...)
             system_prompt (v2 + age_min/age_max)
             + lead context block
             + sales context block (situation-aware)
             + last 10 history turns
             + current user message
             → OpenAI chat.completions.create with PARENT_TOOLS
             → tool-calling loop (max 5 iterations)
                 → ParentToolExecutor.execute(tool_name, args)
                     → backend-validated side effects
         → sanitise_response_wording (PATCH 1/2/4 rewrites)
       → engine response → _sanitise_booking_confirmation → return
       → empty / exception → fall through to legacy
1. DONE state check (legacy)
2. Profile fetch (state == START, lead.name empty)
3. pending_booking continuation hook (P1)
4. Silent intent router (deterministic-first, P0)
5. Price-escape keyword check
6. State machine: START → ASK_AGE → ASK_CHALLENGE → … → DONE
7. Final-stage fake-booking guard
```

### 3.3 P3-C Tool Registry (`PARENT_TOOLS`, 8 entries)

| Tool | Purpose | Backend validation |
|---|---|---|
| `get_camp_info(topic)` | Camp facts from `camp_2026.yaml`. Topics: price / dates / location / conditions / registration / age_range / all | Topic must be in closed enum. `registration` returns `registration_url_missing` when YAML lacks URL. |
| `get_available_slots(date_iso?, days?)` | Calendar slots. With `date_iso` → date-aware via `get_free_slots(start_date=..., days=...)`. Without → legacy `_load_available_slots`. | Invalid date_iso → `invalid_date_iso`. |
| `book_consultation(name, phone, datetime_iso, child_age, user_confirmed_datetime, notes?)` | Calendar booking. | `missing_*` → `datetime_not_confirmed` (PATCH 1) → `invalid_child_age` → `age_not_eligible` (9–17) → `invalid_phone` → `invalid_datetime` / `datetime_in_past` / `outside_business_hours` → `slot_unavailable` (with alternatives) → `calendar_error`. Success: sets `lead.calendly_booked`, `lead.calendar_event_id`, `lead.booked_datetime_iso`, `conversation.state = DONE`. |
| `manage_consultation_booking(action, old_datetime_iso?, new_datetime_iso?, phone?, reason?)` | Cancel or reschedule existing booking (PATCH 1). | Requires `lead.calendar_event_id`. Missing event_id / Calendar delete failure → `manager_handoff_required=true`. |
| `request_manager_callback(name?, phone?, notes?)` | Manager handoff. | Without valid phone → `missing_phone`. With phone → Sheets save + manager notify (idempotent per conversation via `manager_notified_for_conversation`). |
| `save_lead_info(name?, phone?, child_age?, challenge?, notes?)` | In-memory Lead update **only**. Never writes Sheets, never books, never notifies. | Phone parsed via existing flow parser. Challenge merge logic (PATCH 4): substring no-op / richer promotion / unrelated append capped at 300 chars. |
| `switch_to_adult_flow(reason?)` | Soft handoff (PATCH 1). Sets `conversation.segment = "ADULT"` + `state = "START"`. Next inbound message routes to `adult_flow`. | None — pure routing. |
| `check_consultation_slot(datetime_iso)` | Exact-slot availability check (PATCH 6). Bypasses the truncated `get_available_slots` cap. | Returns `{available, inside_business_hours, calendar_available, reason, alternative_slots}` with reasons `outside_business_hours` / `weekend` / `buffer_today` / `calendar_busy` / `past_datetime` / `invalid_datetime`. |

### 3.4 Legacy PARENT state machine

(Unchanged from pre-P3-C; runs only when `USE_PARENT_LLM_ENGINE=False`.)

| State | What it sends | Listens for | Transitions to |
|---|---|---|---|
| START | `PARENT_WELCOME` or intent variant | first user message | ASK_AGE |
| ASK_AGE | `PARENT_ASK_CHALLENGE` | child age | ASK_CHALLENGE |
| ASK_CHALLENGE | `PARENT_ASK_DEEPER` | what parent wants | ASK_DEEPER |
| ASK_DEEPER | `PARENT_ASK_DESIRE` | child personality | ASK_DESIRE |
| ASK_DESIRE | LLM `PRESENT_VALUE` + ask phone | future-state desire | ASK_NAME |
| ASK_NAME | ask phone | name + phone regex | PRESENT_VALUE |
| PRESENT_VALUE / OFFER_BOOKING | slot list | slot pick / custom datetime | DONE on success |
| DONE | composed reply per event (P2) | any post-booking message | DONE |

### 3.5 ADULT flow state machine

(Unchanged. Still untested live — P3-E.)

| State | What it sends | Listens for | Transitions to | LLM? |
|---|---|---|---|---|
| START | `ADULT_WELCOME` + event list | first message | SHOW_EVENTS | none |
| SHOW_EVENTS | event detail | event number or keyword | ANSWER_QUESTIONS | `generate_response` |
| ANSWER_QUESTIONS | LLM event answer + booking question | yes / link | SEND_BOOKING | `generate_response` |
| SEND_BOOKING | `ADULT_SEND_BOOKING` + Sheets save + notify | any | DONE | none |

### 3.6 Feature flags

| Flag | Default (code) | Default (.env) | Effect when true |
|---|---|---|---|
| `USE_LLM_TURN_ANALYZER` | `False` | **`true`** | LLM analyzer fallback when deterministic detector returns None |
| `USE_LLM_COMPOSER` | `False` | `false` | LLM rewrites the 4 discovery turns + powers `compose_post_booking_response` |
| `USE_PARENT_LLM_ENGINE` | `False` | **`true`** (live) | P3-C tool-calling engine handles PARENT flow first; legacy state machine is fallback. Tests pin OFF via `tests/conftest.py`. |
| `USE_ADULT_LLM_ENGINE` ⭐ ADULT Engine | **`True`** | **`true`** (live) | ADULT LLM tool-calling engine (`adult_llm_engine`) handles ADULT flow first; legacy `adult_flow` state machine + PATCH 7 global guard is fallback. Tests pin OFF via `tests/conftest.py` so the legacy ADULT state-machine tests still run unmodified. |
| `ENABLE_PUBLIC_COMMENT_REPLY` | **`True`** | **`true`** | Comment Follow-up Logic Fix (2026-05-31) flipped the code default to True so public replies auto-activate once Meta grants `pages_manage_engagement`. Until then Meta returns HTTP 400; handler logs safely and the private DM still goes out. `.env` set to `false` to force-disable per deploy. |
| `ENABLE_EMAIL_NOTIFICATIONS` | `True` | **`true`** (live) | Gmail SMTP manager-email after booking. Requires `SMTP_HOST/PORT/USERNAME/PASSWORD/FROM_EMAIL` + `MANAGER_EMAIL`. SMTP_PASSWORD must be a Gmail **App Password**. |
| `ADMIN_PANEL_ENABLED` | `False` | `true` (local) | Mounts `/admin` Jinja2 routes with HTTP Basic Auth via `ADMIN_USERNAME` / `ADMIN_PASSWORD`. Returns 404 when off, 503 when on+no-password. |
| `REDIS_ENABLED` | `True` | **`true`** (live) | Redis-backed persistence of Conversation, manager-notified guard, processed-comment guard. When OFF or `REDIS_URL` empty the app silently runs in-memory only. Tests pin OFF via conftest autouse fixture. |
| `AGENT_ENABLED` ⭐ Kill Switch | `True` | `true` (defaults on; `.env` key not currently present — see §5) | Emergency disable. False → DM/comment/follow-up entry points return `kill_switch.AGENT_DISABLED_MESSAGE` and skip every OpenAI / Calendar / Sheets / email / Meta-send call. `/webhook` GET verify, `/health`, `/admin` are NOT gated. |
| `VERIFY_WEBHOOK_SIGNATURE` ⭐ Signature | `True` | `true` | True AND `META_APP_SECRET` non-empty → enforce `X-Hub-Signature-256` HMAC-SHA256 with constant-time compare. Fail-open shape: True AND empty secret → one warning + accept (protects legacy installs). False → unconditional skip. |
| `SENTRY_DSN` ⭐ Sentry | `""` | `""` (key not in live `.env` — Sentry disabled) | When non-empty AND `sentry-sdk` installed, exceptions from `process_message`, `parent_tool_executor.execute`, and `check_and_send_followups` are forwarded with privacy-safe context. Missing key OR missing SDK → safe no-op. |
| `SENTRY_ENVIRONMENT` ⭐ Sentry | `"production"` | `"production"` | Forwarded to `sentry_sdk.init`. Operator can set `qa` / `staging` per deploy. |
| `SENTRY_TRACES_SAMPLE_RATE` ⭐ Sentry | `0.0` | `0.0` | Float in `[0.0, 1.0]`; clamped at init. Default 0.0 keeps performance tracing off. |

App boot prints engine-flag values + Redis connection status + Sentry status to stdout (see `app/main.py`).

---

## 4. Honest Status

### 4.1 PARENT flow

| Capability | Status |
|---|---|
| Webhook → conversation → response | ✅ live tested |
| Segment classification (PARENT/ADULT/UNCLEAR) | ✅ live tested |
| Calendar booking | ✅ live tested (engine path, PATCH 5) |
| Sheets CRM save | ✅ live tested |
| Phone validation | ✅ |
| Pending booking multi-turn | ✅ regression-tested (P1) |
| Manager handoff | ✅ regression-tested (P0) |
| Factual Q&A | ✅ regression-tested |
| DONE state natural replies | ✅ regression-tested (P2) |
| Fake booking guard (PATCH 5: tool-success gated) | ✅ regression-tested |
| **P3-C tool-calling engine** | ✅ live tested + 163 engine tests |
| **Auto-booking blocked** (`user_confirmed_datetime` required) | ✅ regression-tested (PATCH 1) |
| **Registration vs consultation separated** | ✅ regression-tested (PATCH 1) |
| **Cancel/reschedule + manager handoff fallback** | ✅ regression-tested (PATCH 1) |
| **Adult handoff via tool** | ✅ regression-tested (PATCH 1) |
| **Georgian wording sanitiser** (60+ rewrites across PATCH 1–8) | ✅ regression-tested |
| **Audience-aware sales context** | ✅ regression-tested (PATCH 3) |
| **CRM summaries Georgian-only** + English-fallback | ✅ regression-tested (PATCH 2) |
| **Follow-up readiness fields** (5 new, Conversation Redis-ready) | ✅ regression-tested (PATCH 3) |
| **Exact-slot date check** (`date_iso` on `get_available_slots`) | ✅ regression-tested (PATCH 4) |
| **Lead field preservation** (challenge merge, known-fields reuse) | ✅ regression-tested (PATCH 4) |
| **Pending-booking commit** (slot select → name/phone → Calendar) | ✅ live tested (PATCH 5) |
| **Tool-success gated confirmation** (no fake "ჩავნიშნე") | ✅ regression-tested (PATCH 5) |
| **Exact-slot availability** (`check_consultation_slot` tool) | ✅ regression-tested (PATCH 6) |
| **Today-only buffer** (future dates not pruned by buffer_minutes) | ✅ regression-tested (PATCH 6) |
| **Time-change before commit** (13:00 → 15:00 reroutes) | ✅ regression-tested (PATCH 7) |
| **Decline / will-think close** (deterministic, no LLM round-trip) | ✅ regression-tested (PATCH 7) |
| **Static welcome bypass** (state=START + bare greeting → menu) | ✅ regression-tested (PATCH 8) |
| **Ineligible-age CTA scrubber** (no booking offer if age outside [9,17]) | ✅ regression-tested (PATCH 8) |
| **Screen mention conditional on user input** | ✅ regression-tested (PATCH 8) |
| **Redis-backed Conversation persistence** | ✅ live tested (P3-B) — server restart → pending booking restored → name+phone arrive → booking completes |
| **Email notification to manager** | ✅ live tested — Gmail SMTP via app password; deeper_concern conditional; correct Georgian genitive; no duplicated challenge |
| **Admin Panel** (`/admin`) | ✅ live tested — operator changes price/streams/location, agent uses the new values without code edits |
| **Camp facts source-of-truth unification** | ✅ regression-tested — `get_camp_facts()` admin-first; `price_text`-derived integer wins over stale `price_gel` |
| **Parent greeting consistency** (state=START first reply → static menu) | ✅ regression-tested — `_maybe_static_welcome` fires regardless of message content; no `მოგესალმებით!` leak |
| **Challenge deterministic fallback** (`maybe_capture_challenge_fallback`) | ✅ regression-tested — captures screen / communication / confidence / development concerns when LLM skips `save_lead_info` |
| **child_age deterministic fallback** (`maybe_capture_child_age_fallback`) | ✅ regression-tested — captures 1–2-digit standalone age in range 5–20 |
| **Compound booking** (datetime + phone + name in one message) | ✅ regression-tested — pending booking synthesised on the fly; `_parse_name_phone` rescues 9-digit window from greedy captures |
| **Adult pivot** (age ≥ 18 → `switch_to_adult_flow` + `ზრდასრულთა კულტურული საღამოები`) | ✅ system-prompt rule + scenario-tested |
| **DONE / booked state guard** (booked lead never re-classifies to UNCLEAR) | ✅ regression-tested — `conversation_service.process_message` |
| **Identity short-circuit** (`ბოტი ხარ? / AI ხარ?` → brand-grounded answer) | ✅ regression-tested — `_maybe_identity_reply` |
| **English camp intent** (`Hello I want camp for my child` → Georgian age question) | ✅ regression-tested — `CAMP_KEYWORDS` + `_has_explicit_english_camp_intent` + static-welcome yield |
| **Price objection** (TBC / საქართველოს ბანკი + payment split + brief value reminder) | ✅ system-prompt rule + scenario-tested |
| **Multi-child sibling discount** (10% დედმამიშვილების ფასდაკლება auto-mentioned) | ✅ system-prompt rule + scenario-tested |
| **Angry user** (exact apology + continue current flow, no deflection) | ✅ system-prompt rule + sanitiser + scenario-tested |
| **Past date** (`წარსულ თარიღზე ვერ ჩავნიშნავთ` + free slots; no `უკვე გასულია`) | ✅ system-prompt rule + sanitiser + scenario-tested |

### 4.2 ADULT flow

**LLM Engine ✅ (P3-D shipped 2026-06-01)** — `app/agent/llm/adult_llm_engine.run_adult_llm_turn` is the primary handler when `USE_ADULT_LLM_ENGINE=true` (live default). 6-tool registry covers events list, event details, lead save, manager handoff (Sheets + manager email + returns manager phone to the LLM for the user reply), reservation link (no-invent guarantee), and parent-flow switch. Adult flow CONFIRMED never books Google Calendar (regression test). Per-event `min_age` in `data/admin_config/sections.yaml` drives age filtering — events the user is too young for are hidden before the LLM ever sees them. Manager phone is sourced from `admin_config_service.get_manager_phone()` chain (admin_config → settings → company.yaml → adult-section `manager_contact`) — never hard-coded. Deterministic adult-to-parent switch on camp-keyword + child-age-in-range; system_parent_v2.md updated so age outside [9,17] uses a polite question BEFORE `switch_to_adult_flow` (no auto-pivot). Legacy state machine + PATCH 7 global intent guard is the fallback when the engine returns empty / raises.

**Still never live-tested end-to-end on real Instagram (P3-E).** Engine is regression-tested (18 engine + 18 executor + 13 admin-config + 5 manager-notification = 54 new tests); next step is the live audit on real Instagram traffic.

**ADULT comment flow** now also has rich first-contact DM with event details (PATCH 3) or a friendly no-events fallback.

See §8 for the full ADULT analysis (unchanged from pre-P3-C; the state machine itself was not modified).

### 4.3 COMMENT flow

| Capability | Status |
|---|---|
| Facebook Page comment webhook ingestion | ✅ live tested |
| Hashtag detection (Georgian + Latin, case-insensitive) | ✅ live tested |
| `INTERESTED` / `NOT_INTERESTED` classifier | ✅ regression-tested |
| Public reply (gate: `ENABLE_PUBLIC_COMMENT_REPLY`) | ⏳ code default flipped to True (2026-05-31); waiting on Meta App Review `pages_manage_engagement` — until then HTTP 400 is logged safely and private DM still ships |
| Comment follow-up scheduler (Meta `/replies`) | ✅ live-tested 2026-05-31 — `DM Sent==TRUE` + `Status=="DMSent"` eligibility; active-conv skip; HTTP 400 → mark `Expired` + processed-guard + no retry; success → `FollowupSent` |
| Private reply (`recipient.comment_id`) via Page `/messages` endpoint | ✅ live tested — "Page responded privately" notification confirmed |
| **PARENT rich DM** (location + price + streams + URL from `camp_2026.yaml`) | ✅ regression-tested (PATCH 3) |
| **ADULT rich DM** (event list with 📅 📍 💰 markers from `data/events.txt`) | ✅ regression-tested (PATCH 3) |
| YAML / parser failure → safe fallback | ✅ regression-tested (PATCH 3) |
| Public reply failure never blocks DM | ✅ regression-tested (PATCH 1) |
| User replies in Messenger after DM → normal flow continues | ✅ existing behavior (no code change) |

---

## 5. Critical Issues

### BLOCKERS — must fix before production

(none currently open — see RESOLVED sections below)

### RESOLVED — Session 9-11 (2026-06-08 → 2026-06-09 patch wave, 1350 → 1615, +265 tests) — Admin Panel multi-event, Adult Live QA, Comment Mapping, Subscription + Broadcast, Instagram webhook signature

- ✅ ~~Admin Panel multi-event support not finished~~ → +52 tests (1350 → 1402). Full multi-event Admin Panel surface: add / edit / deactivate / activate. `adult_events.events[]` is source of truth. `_normalize_adult_event` preserves `description` / `facebook_post_id` / `tags` / `price_gel` / `payment_terms`. New `update_adult_event`, `deactivate_adult_event`, `activate_adult_event` service helpers. Section-level metadata preserved across event saves.
- ✅ ~~Multi-event UI visibility — operator could not discover the editor~~ → +9 tests (1402 → 1411). Programs list now shows green "ღონისძიებების მართვა" button next to "Edit" for adult_events; section-form blue banner links to the events manager; events list back-link added.
- ✅ ~~Adult Live QA bugs: sold-out hallucination, ticket link, partial title, wording polish~~ → +31 tests (1411 → 1442). `sold_out` flag in `_normalize_adult_event` + per-conversation `adult_sold_out_disclosed_for_conversation` sanitiser flag. `_get_adult_event_details` surfaces `reservation_url` + `payment_terms` directly. Georgian stem-aware `find_adult_events_matching` so „ქართული პოეზია" finds „ქართული პოეზიის საღამო". `ambiguous_event` reason for multi-match; `event_inactive` distinct from `unknown_event`. Sanitiser: „გინდა"→„გსურთ", leading „გმადლობთ." filler strip, sentence-level sold-out copy strip when flag not set.
- ✅ ~~Adult price hallucination (agent claimed "ფასი მითითებული არ არის" while `price_text="150"` and `price_gel=150`)~~ → +23 tests (1442 → 1465). Executor compact + details payloads surface `price_gel` (when positive); new `adult_price_disclosed_for_conversation` flag; sanitiser strips invented "price missing" copy ONLY when flag set; prompt's "ფასის რენდერინგის წესი" CRITICAL block formalises the decision tree (price_text → numeric → " ლარი" suffix; price_gel fallback; canonical missing only when both blank).
- ✅ ~~Comment → Specific Event Mapping~~ → +55 tests (1465 → 1520). New deterministic `is_interest_intent` (30+ Georgian + English broad-interest keywords; LLM-free shortcut). New `resolve_specific_adult_event(comment_text, post_id, platform)` with priority A (`facebook_post_id` exact) → B (event tag in comment) → C (event tag in caption) → D (no_match) → E (ambiguous). New `_build_specific_adult_event_dm(event)` renders title/date/location/price/description/link. `send_dm_from_comment` tries specific-event branch first; falls through to existing generic ADULT rich DM on no-match. `fetch_post_content` log lines hardened: never surface token, response body, or exception args. **Camp comment broad-interest routing benefits equally**: „ფასი?" / „სად ტარდება?" / „ბმული?" under #ბანაკი route through the existing camp DM via the deterministic shortcut.
- ✅ ~~Adult Event Subscription + New-Event Broadcast~~ → +73 tests (1520 → 1593). New `events` Sheets tab (18 columns; upsert by platform+sender_id). New `adult_subscription_service` (consent + unsubscribe phrase detection, `subscribe()` / `unsubscribe()` / `is_already_subscribed()`). New `adult_event_broadcast_service.broadcast_event()` with kill-switch + inactive + missing-link + per-subscriber failure isolation + dual-layer duplicate prevention via `Notified Event IDs`. New ADULT tool `subscribe_to_adult_event_updates` + executor handler. Deterministic unsubscribe phrase detection BEFORE the LLM in the ADULT engine. New `Conversation.adult_subscription_status` field. New prompt rule „ფუტურული ღონისძიების შეტყობინებების წესი" with exact brand wording + ban on misleading „ახალი ღონისძიების სიაში დაგამატოთ" / „დაგიმატეთ". Admin Panel: checkbox „შენახვის შემდეგ გაუგზავნე subscribed მომხმარებლებს" on create/edit form (default off); per-row manual "გაგზავნა subscribed მომხმარებლებთან" button; results page with operator-friendly Georgian summary + counter table. **✅ LIVE VERIFIED by operator (2026-06-09): a newly created adult event was successfully broadcast to a subscribed user via Messenger DM.**
- ✅ ~~Instagram webhook signature + payload diagnostics~~ → +22 tests (1593 → 1615). New `INSTAGRAM_APP_SECRET` + `INSTAGRAM_ACCESS_TOKEN` Settings fields (with `IG_APP_SECRET` / `IG_ACCESS_TOKEN` aliases). Multi-secret `_verify_meta_signature` rewritten: tries Facebook (`META_APP_SECRET` / `MESSENGER_APP_SECRET`) first, falls back to `INSTAGRAM_APP_SECRET`; returns `(accepted, label)`. New `_candidate_app_secrets()` helper. New `_summarise_payload_fields(payload)` + `_SUPPORTED_PAYLOAD_FIELDS` frozenset for privacy-safe diagnostic log lines. Boot log surfaces secret + token presence (`set` / `NOT set`). **✅ LIVE VERIFIED by operator (2026-06-09): operator added local `.env` `INSTAGRAM_APP_SECRET` + IG access token, restarted server, sent Instagram DM, observed `[webhook] signature accepted via instagram_app_secret` (no 403). Agent responded successfully. Comment under Instagram post also passes.** Existing Facebook signature path + tests preserved byte-for-byte.

### RESOLVED — Session 8 (2026-06-07 LIVE QA PATCH, +17 tests, 1333 → 1350) ✅ LIVE VERIFIED

- ✅ ~~Extra booking CTA filler („თუ კიდევ რაიმე…", „თუ დამატებითი კითხვა გაქვთ…")~~ → `_BOOKED_NEW_BOOKING_CTA_PATTERNS` extended with the awkward post-booking CTA variants; `_strip_consultation_cta_if_booked` no longer auto-appends `_BOOKED_HELP_CTA`; `_BOOKING_SUCCESS_TRIM_PHRASES` mirrors the new list for the immediate success turn; new `_DUP_TU_MIXED_PATTERN` regex collapses doubled mixed-verb „თუ X დაგაინტერესებთ, თუ Y გაგიჩნდებათ" clauses. **LIVE VERIFIED:** booking confirmation now stays „[date], [time] საათზე კონსულტაცია ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ." (or the reschedule variant with „ძველი კონსულტაცია გაუქმებულია.").
- ✅ ~~Old Sheets row remained `"Booked"` after successful reschedule~~ → new `sheets_service.mark_old_booking_rescheduled(sender_id, *, new_status="Rescheduled")` targets the OLDEST sender_id row whose Status cell is `"Booked"` and leaves any LATER `"Booked"` row alone. `parent_tool_executor._reschedule_booking` now calls this helper instead of the legacy `update_lead(sender_id, ...)` (which matched the first sender_id row regardless of status and relabelled pre-booking discovery rows). Sheets failure: warning logged with masked sender + masked old_event_id, Sentry capture (`area=booking_reschedule, reason=sheets_old_row_update_failed`), Calendar success NOT rolled back. **LIVE VERIFIED:** operator screenshot confirmed old row → `"Rescheduled"`, current row → `"Booked"`; exactly one active `"Booked"` row per sender after reschedule.

### RESOLVED — Follow-up Live-Test Hydrate Patch (2026-06-06, +13 tests, 1320 → 1333) ✅ LIVE VERIFIED

- ✅ ~~One-off CLI `python -c "from app.services import followup_service; followup_service.check_and_send_followups()"` scanned 0 conversations because the fresh process has empty in-memory state~~ → new `redis_state_service.scan_keys(pattern, count=200)` (non-blocking SCAN), new `conversation_service.hydrate_from_redis()` loads every `conversation:*` key into the in-memory dict (idempotent — in-memory wins), new `tools/run_followup_tick.py` CLI (`--dry-run` lists due, default sends). Enriched scheduler log: `[FOLLOWUP] scanning total=N parent=N with_marker=N` + `[FOLLOWUP] tick complete total=N due=N sent=N skipped=N`. **LIVE VERIFIED:** `python tools/run_followup_tick.py` hydrates the live PARENT conversation from Redis and delivers the follow-up Messenger DM after 120 seconds in test mode.

### RESOLVED — Follow-up Test Mode + Live-QA Compatibility Patch (2026-06-06, +30 tests, 1290 → 1320) ✅ LIVE VERIFIED

- ✅ ~~No 2-minute operator-side follow-up QA path~~ → new `FOLLOWUP_ENABLED` (default `True`) master gate + `FOLLOWUP_TEST_MODE` (default `False`) + `FOLLOWUP_FIRST_DELAY_SECONDS` (default `0`) operator overrides in `Settings`. `_first_delay()` returns the override only when `FOLLOWUP_TEST_MODE=true` AND `FOLLOWUP_FIRST_DELAY_SECONDS > 0`; otherwise production 24h. Stages 2 (72h) + 3 (168h) **NEVER overridden**. Invalid override (zero / negative / non-numeric) → silent fallback to production cadence. Scheduler banner: `[FOLLOWUP] Test mode enabled: first delay = 120s` / `[FOLLOWUP] Production cadence active` / `[FOLLOWUP] disabled (FOLLOWUP_ENABLED=false) — tick skipped` (mutually exclusive, one per tick). **LIVE VERIFIED:** PARENT follow-up Admin Panel template text (operator-edited) is read at send-time and delivered through Messenger; duplicate-prevention via stage advance verified.
- ✅ ~~Comment → private DM didn't participate in follow-up cadence~~ → `comment_service.send_dm_from_comment` now stamps `conversation.last_bot_message_at` + writes through to Redis on successful DM send; failed send does NOT stamp the marker (so the scheduler doesn't chase a user who never received the first message). Follow-ups always go through `messenger_service.send_message` (private DM) — never as public comment reply.

### RESOLVED — Test Stability Patch (2026-06-06) — weekend date fragility fix

- ✅ ~~`tests/test_calendar_multi_busy_patch.py::test_busy_10_30_to_19_00_blocks_11_through_18` failed on Sat/Sun runs~~ → `target_date = now_tbilisi() + 14 days` now advances past any weekend with a `while target_date.weekday() >= 5: target_date += timedelta(days=1)` loop. Test-only change; no production code touched. Clean pytest baseline restored on every weekday.

### RESOLVED — Session 7 (2026-06-06 LIVE QA PATCH, +39 tests, 1251 → 1290)

- ✅ ~~Reschedule pending state preserved across confirmation turn~~ → `_check_consultation_slot` marks `pending_booking["source"]="reschedule"` + stashes `old_event_id` + `old_booked_datetime_iso`; `_book_consultation` detects the already-booked-at-different-time scenario via `_is_reschedule_scenario` and reroutes through `_reschedule_booking`. Sample reschedule intent phrases live in `RESCHEDULE_INTENT_PHRASES`.
- ✅ ~~Old booking cancelled after successful reschedule confirmation~~ → safe-ordering preserved (book new → verify event_id → THEN cancel old, from Session 6 Bug 9); Session 7 reroute hooks the new booking into the same code path.
- ✅ ~~No two active consultations remain for one user after reschedule~~ → `_book_consultation` reroute marks `lead.calendar_event_id` to the NEW event after successful cancel of the old one; the failure branches keep the old booking intact when new fails, surface manager handoff when new succeeds but old cancel fails.
- ✅ ~~Adult transition from PARENT/booked state no longer dead-ends~~ → `parent_flow._ensure_adult_intro_followup_for_parent_flow` mirrors the adult-engine guard onto the PARENT response when the response is ≤120 chars, contains no `?`, ends in „დაგეხმარებით." and carries an adult-event keyword.
- ✅ ~~Adult target question updated back to „თქვენთვის თუ თქვენი შვილისთვის?"~~ → `_ADULT_FOLLOWUP_QUESTION_WHO` reverted; sanitizer entries flipped to map „სხვა ადამიანისთვის" back to „თქვენი შვილისთვის"; system_adult_v1.md target-question rule updated; sibling/brother/friend handling preserved via existing `_maybe_capture_adult_target`.
- ✅ ~~Manager notification email subject/body cleaned~~ → `_build_email_subject` returns „<name> — ახალი კონსულტაცია AI Agent-იდან" for booked leads with name, „<name> — ახალი ლიდი AI Agent-იდან" for new leads; body headline branches on booking state; structured detail block + summary share the deduped challenge.
- ✅ ~~Challenge/interest dedupe added~~ → `_dedupe_repeated_phrase` collapses "X Y X Y" and "X X" patterns before printing; applied in `_parent_detail_lines` and `_build_parent_summary`.
- ✅ ~~WhatsApp notification skips cleanly when credentials missing~~ → `_send_manager_whatsapp` early-returns with a single `[NOTIFICATION][WHATSAPP] Skipped: missing credentials (...)` log line when ANY of `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `MANAGER_WHATSAPP_NUMBER` is empty. No `httpx.post`, no traceback. Email channel stays independent and continues working.
- ✅ ~~Booking confirmation shortened~~ → `_trim_booking_success_response` strips trailing help CTA + privacy note when `book_consultation_success_for_conversation` is True for the sender. The pending-commit deterministic success message was already concise.

### STILL OPEN — Next engineering tasks (2026-06-09)

- **CURRENT LIVE BUG — Generic `#event` comment fails to send active adult events list.** When a comment lands on a post with the generic `#event` hashtag (no specific event tag and no matching `facebook_post_id`), the comment handler currently falls into the legacy "no schedule" copy / no-active-events fallback even though `adult_events.events[]` contains active events. The specific-event mapping (`#event #fast` → exact "fast" event) WORKS — verified live. The fix is: when `resolve_specific_adult_event` returns `no_match` AND `get_active_adult_events()` is non-empty, route through a new "show active adult events list" rich DM instead of the generic empty-roster fallback. **Priority 1 for the next session.**
- **Adult follow-up scheduler still NOT supported.** Current scheduler in `followup_service._maybe_send_followup_for_conversation` short-circuits with `reason=non_parent_segment` for ADULT and UNCLEAR. The PARENT cadence is unchanged; ADULT-flow follow-up (incl. „cold lead" re-engagement) is a separate future task — *distinct* from the operator-triggered Adult Event Subscription broadcast (which is already shipped + LIVE VERIFIED).
- **Production follow-up tick interval still 1h.** `BackgroundScheduler.add_job(..., 'interval', hours=1)` in `app/main.py`. `FOLLOWUP_TEST_MODE` shortens the FIRST-due delay only; it does NOT shorten the APScheduler interval. Operators must use `tools/run_followup_tick.py` for tighter feedback than 1h.

### STILL OPEN — Infrastructure / operator-action (carried over, updated 2026-06-09)

- **Railway deploy not yet performed.** Single-process target; Procfile + always-on plan + Redis add-on. See §7 Priority 1.
- **Railway env vars setup pending.** Production env must include AT MINIMUM: `INSTAGRAM_APP_SECRET` (the secret that unblocked the live IG webhook), `INSTAGRAM_ACCESS_TOKEN`, `META_APP_SECRET` (Facebook Page secret), Google credentials env (`GOOGLE_CREDENTIALS_JSON` / `GOOGLE_SHEETS_SPREADSHEET_ID` / `BOOKING_CALENDAR_ID` / `BUSY_CALENDAR_IDS`), `REDIS_URL`, `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `MANAGER_WHATSAPP_NUMBER` if WhatsApp is used. Local `.env` already has the working values from operator's live IG test.
- **Client production setup pending.** Operator action: provision the *client*'s Google Sheet, client Google Calendar, client email notification config, client WhatsApp manager-message config, client Facebook Page + Instagram asset connections. The current values are tester-account assets.
- **Meta App Review not yet submitted.** `pages_manage_engagement` permission must be granted before public comment replies actually fire. See §7 Priority 2.
- **WhatsApp live test pending real credentials.** Session 7 added the empty-token guard; operator must populate `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `MANAGER_WHATSAPP_NUMBER` once Meta WhatsApp Business credentials are issued.
- **`.gitignore` missing + `credentials.json` in working tree.** 30-min fix; do BEFORE any `git init && git push`. See §7 Priority 1.
- **`requirements.txt` missing dev/optional deps** — `pytest`, `sentry-sdk`, `redis`, `fakeredis`, `python-multipart`. 15-min fix.
- **SC-14 / SC-23 / SC-42 NORMAL scenario regressions still pending.** Re-run twice each to confirm LLM-stochasticity vs real regression. Not deploy-blocking; CRITICAL 22/22 + security 4/4 + adult 3/3 preserved throughout Sessions 7-11.
- **Production smoke test NOT run.** Gated on Railway deploy.

### RESOLVED — Session 6 (2026-06-05 FULL Live QA Patch, +55 tests, 1196 → 1251)

- ✅ ~~Admin Panel adult_events source mismatch~~ → section-level fallback `_build_fallback_event_from_section` + new events[] editor.
- ✅ ~~Fallback event from section-level metadata~~ → fires when events[] empty AND section status=active AND at least one event-like field populated.
- ✅ ~~events[] editor added to Admin Panel~~ → new `/admin/programs/adult_events/events` (list/new/edit/delete) routes + `admin/adult_events.html` + `admin/adult_event_form.html`.
- ✅ ~~Cultural evenings explanation added~~ → new system_adult_v1.md section requires a brief explanation BEFORE the target question.
- ✅ ~~Adult target question: "სხვა ადამიანისთვის?"~~ → SHIPPED in Session 6 (now flagged for revert in Session 7 per client preference — see STILL OPEN #3 above).
- ✅ ~~Adult-to-parent known age carryover~~ → context-message surfaces `adult_target_relation` + `adult_target_age`; system_parent_v2.md „ADULT→PARENT გადასვლის წესი" codifies the acknowledge-don't-re-ask rule.
- ✅ ~~13+ global age floor enforced~~ → `_normalize_adult_event` applies `max(13, min_age)`; per-event min_age can override UPWARD only.
- ✅ ~~Sibling discount guard~~ → `_strip_unwarranted_sibling_discount` scans conversation history for closed-set 2+ children triggers; without one, strips the 10% sentence.
- ✅ ~~"კაი/კარგი/კი" not extracted as name~~ → `NAME_FILLER_WORDS` extended with 14 Georgian confirmation/filler tokens.
- ✅ ~~Reschedule: new booking before old cancel~~ → `_reschedule_booking` refactored to safe ordering (stash old → book new → verify event_id → THEN cancel old). New-booking failure restores old state; old-cancel failure after new success surfaces `old_cancel_failed=True` + manager handoff. **NOTE: the pending-state continuation across user-confirmation turn was NOT addressed and surfaced as Session 7 OPEN #1.**
- ✅ ~~One active consultation per user rule~~ → codified in system_parent_v2.md „გადატანის წესი".
- ✅ ~~Calendar re-check phrases expanded (10 phrases)~~ → `_BOOKING_VERIFICATION_PHRASES` extended.
- ✅ ~~Manager handoff wording sanitized~~ → 4 sanitizer entries in PARENT + 4 mirrored in ADULT; brand-standard „დაგაკავშირებთ მენეჯერთან".
- ✅ ~~Redundant confirmation text removed~~ → unconditional sanitizer strips „X საათზე ჩამწერეთ კონსულტაცია"; context-aware `_strip_redundant_confirmation_after_command` strips „თუ ეს დრო გაწყობთ, დამიდასტურეთ" only when the user message has an explicit booking command.

### RESOLVED — Error Monitoring ✅

Optional Sentry wired via `app/services/sentry_service.py`. Empty `SENTRY_DSN` OR missing `sentry-sdk` → safe no-op, app boots normally. Three capture points (no other modules instrument Sentry directly):

| Capture point | Context forwarded | Privacy safety |
|---|---|---|
| `conversation_service.process_message` | `area`, `platform`, `sender` (masked: first 6 + `***`) | Raw user message, full sender id, and any error string containing them are NOT forwarded. Captures + re-raises so the webhook layer's existing exception handler still skips the send. |
| `parent_tool_executor.execute` | `area`, `tool` name | Tool args (which may contain phone / name / datetime) are NOT forwarded. Existing `{"success": False, "reason": "tool_error"}` contract preserved. |
| `followup_service.check_and_send_followups` | `area`, `stage` (STRING: `first_24h` / `second_3d` / `third_7d`), `platform`, `sender` (masked) | Stage stays string per `followup_strategy.yaml`; never coerced to int. Per-conversation loop continues on capture. |

Hard rules in `sentry_service`:
- `send_default_pii=False`, `attach_stacktrace=True` at init.
- `sentry_sdk.init` failure (bad DSN, network unreachable, etc.) does NOT crash boot — caught and logged.
- Every public function catches its own exceptions and degrades to a no-op.
- `SENTRY_TRACES_SAMPLE_RATE` is clamped to `[0.0, 1.0]` at init.
- `mask_sender()` keeps just `sender[:6] + "***"` for log correlation.

Structured logs added: `[conversation] start/completed/error platform=… sender=… reply_len=…`, `[followup] sent stage=… platform=… sender=…`, `[followup] skipped reason=… platform=… sender=…`, `[followup] error stage=… platform=… sender=… error=…`. Masked sender, no message body, no phone, no tokens.

### RESOLVED — Kill Switch ✅

Operator-controlled `AGENT_ENABLED` env flag (default `true`). When `false` the DM entry point (`conversation_service.process_message`), the comment entry point (`webhook.handle_comment`), and the follow-up scheduler (`followup_service.check_and_send_followups`) all short-circuit BEFORE any OpenAI / Calendar / Sheets / email / Meta-send call. The canonical Georgian `kill_switch.AGENT_DISABLED_MESSAGE` is returned to inbound DMs:

> "ამ მომენტში ავტომატური ასისტენტი დროებით გათიშულია. მოგვწერეთ და მენეჯერი დაგიკავშირდებათ."

`/webhook` GET verify, `/health`, and `/admin` are NOT gated — Meta must still see a live webhook, the operator must still reach the admin panel to flip the flag back. Admin dashboard surfaces `Agent status: Enabled ✅ / Disabled 🔴`. Toggling from the UI is intentionally NOT exposed yet (env flag + restart is the safer interface at this stage). 21 new tests in `tests/test_kill_switch.py`; full pytest suite at 648 passed.

### RESOLVED — Session 3 patches (2026-06-02 → 2026-06-04)

- ✅ ~~ADULT live-bug trio (transition dead-end / child_age leakage / „დის(თვის)" wrong PARENT switch)~~ → **ADULT Context Routing Fix (2026-06-02, pytest 956 → 1000, +44 tests)**. `_user_wants_parent_flow` now requires an explicit *hard camp keyword* (`ბანაკ` / `საზაფხულო` / `ბავშვთა პროგრამა`) to switch; soft cues paired with an adult-event signal stay ADULT. New `_maybe_capture_adult_target` pre-LLM helper records relative relation + age. `_ensure_adult_intro_followup` broadened with `_looks_like_bare_intro` heuristic that catches short ack responses + adult-event vocab + no question. New `lead.adult_target_relation` / `lead.adult_target_age` fields with strict separation from `child_age` / `adult_age`. `_get_adult_events` deterministic guard refuses to filter when LLM-passed `user_age` matches `lead.child_age` AND no relative target is on record.
- ✅ ~~Agent wording polish: live-bug „მენეჯერთან კავშირს მოგიწყობთ" + decorative 🌿 / 😊 / ✨ emojis cluttering replies~~ → **Agent Wording Cleanup Patch (2026-06-03, pytest 1000 → 1044, +44 tests)**. Standard manager handoff phrase „თუ გსურთ, დაგაკავშირებთ მენეჯერთან." documented in both prompts/policies; 7+7 sanitiser rewrites in PARENT/ADULT engines for the banned variants. Every user-facing template, fallback constant, deterministic redirect, and prompt example response is now emoji-free (🌿/😊/✨/✅/❌). Sanitisers strip emojis even if the LLM produces them. Tone remains warm — carried by wording, not symbols. No business logic changed.
- ✅ ~~Consultation booking window 10:00–18:00 + 30-min slots was too restrictive; partial-overlap busy events occasionally let slots through~~ → **Booking Availability Patch (2026-06-03, pytest 1044 → 1076, +32 tests)**. Window widened to **10:00–21:00** (last valid start 20:00, 21:00 is closing). Slot duration standardised at **60 minutes** — half-hour requests rejected with new `reason="half_hour_not_supported"`. Pre-booking re-check uses 60-min duration AND fails CLOSED on Calendar API exceptions (was fail-open). Partial-overlap busy blocks correctly hide adjacent candidate slots; exact-boundary busy blocks (e.g. 13:00–14:00) leave 12:00 and 14:00 free via strict-inequality interval overlap.
- ✅ ~~Manager places busy events on a side calendar; single-calendar FreeBusy query missed them and agent first said „14:00 თავისუფალია" then later admitted „დაკავებულია"~~ → **Calendar Multi-Busy Check + Reschedule Wording Patch (2026-06-04, pytest 1076 → 1105, +29 tests)**. New `BOOKING_CALENDAR_ID` + `BUSY_CALENDAR_IDS` env vars; `_free_busy_intervals` queries every busy calendar in a single multi-item FreeBusy call, flattens busy intervals across calendars, fail-CLOSED if ANY calendar's response is missing / has `errors` block / HTTP fails. Booking writes (`book_slot` / `cancel_calendar_event` / `create_event`) target `settings.booking_calendar_id()` only. Reschedule path uses the same `check_slot_available` — no weaker first-check path. Reschedule wording „კონსულტაციის გადატანას დავეხმარები" rewritten to brand-standard „კონსულტაციის გადატანაში დაგეხმარებით." (6 sanitiser entries).

### IMPORTANT — should fix soon

**1. Admin Panel adult events not populated yet.** Seed entries `poetry_evening` + `book_club` in `data/admin_config/sections.yaml` are `status: inactive` (correctly — they had no real dates/locations/prices/URLs, so they'd surface as hallucinated placeholders). Operator must use `/admin/programs/adult_events` to add real events before adult traffic produces anything other than the "no active events" handoff. Admin Panel multi-event editing UI is not yet built — operator can currently edit the YAML directly or use the existing single-event form.

**2. `BUSY_CALENDAR_IDS` not yet set in live `.env`.** The Calendar Multi-Busy Check Patch (2026-06-04) added env-var-driven multi-calendar FreeBusy. Until the operator populates `BUSY_CALENDAR_IDS` with the manager's actual side-calendar ids (e.g. „Nikoloz Analytics" calendar + any other calendar where the manager blocks personal time) and shares each with the Google service account, only the bookings calendar is consulted — same behaviour as the legacy single-calendar deploy. Code defaults are safe (no regression), but the live bug the patch was authored to prevent will recur until the operator acts.

**3. `.gitignore` missing + `credentials.json` in working tree.** Surfaced by 2026-06-01 REVIEW_PACK §8. The repo isn't currently a git repo (`Is a git repository: false`), but the moment the operator runs `git init && git push` without a `.gitignore`, the Google service account credentials would be exposed. **30-min fix; should precede Railway deploy.**

**4. `requirements.txt` missing dev/optional deps.** Production install does not pull `pytest`, `sentry-sdk`, `redis`, `fakeredis`, `python-multipart`. Sentry + redis are intentionally optional (safe no-op when missing); pytest + python-multipart should be in a `requirements-dev.txt`. **15-min fix.**

**5. `META_APP_SECRET` missing from live `.env`.** Verified `grep -oE "^[A-Z_]+=" .env`. The Webhook Signature Verification Patch fail-open shape means production currently logs one `[webhook] signature check skipped` warning per request but does NOT actually enforce HMAC. Single operator action ("paste app secret, restart") flips on enforcement. Same applies to `AGENT_ENABLED`, `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE` — defaults are safe but operator should sync `.env` from `.env.example`.

**6. ADULT flow live-tested PARTIALLY.** Multiple operator-driven live sessions completed 2026-06-02; the three live-bug-trio defects were resolved by the ADULT Context Routing Fix (Session 3 RESOLVED list above). Declaring "live-tested complete" is gated on one more operator-driven session confirming the routing-fix behaviour in real Instagram traffic.

**7. SC-14 / SC-23 / SC-42 NORMAL scenario regressions.** Three IMPORTANT/NORMAL-tier wording scenarios fail intermittently. CRITICAL 22/22 + security 4/4 + adult 3/3 preserved across all patches. Documented in REVIEW_PACK; not deploy-blocking. Re-run twice each to confirm LLM-stochasticity vs real regression before opening a fix task.

**8. WhatsApp manager notification untested live.** Email path works end-to-end; WhatsApp manager-side still untested. Needs `MANAGER_WHATSAPP_NUMBER` + `WHATSAPP_TOKEN`. Twilio SMS optional / untested.

**9. Meta API v18/v19 drift (MINOR).** `notification_service.py:28` hardcodes `https://graph.facebook.com/v18.0`. Manager-WhatsApp uses v18 while everything else uses v19. **15-min fix** (replace hardcoded URL with settings read); affects manager-WhatsApp delivery once Meta sunsets v18.

**10. `mask_sender` shape divergence (MINOR).** `kill_switch.mask_sender` returns `"***" + sid[-4:]`; `sentry_service.mask_sender` returns `sid[:6] + "***"`. Both still mask; standardize in a future quick-fix patch.

### RESOLVED — Follow-up Scheduler ✅

The scheduler is now driven by per-Conversation markers (`last_bot_message_at` + `followup_stage`) instead of the legacy Sheets cold-lead read. Cadence stages `"" → "first_24h" → "second_3d" → "third_7d"` match `app/agent/knowledge/followup_strategy.yaml` keys. Delays: 24h / 72h / 168h. Terminal stage sets `followup_blocked_reason="followup_exhausted"` so the lead is permanently excluded.

**Skip rules:** `followup_blocked_reason` ∈ {booked, registered, declined, asked_no_more_messages, manager_handoff_completed, followup_exhausted}; segment ≠ PARENT; `lead.calendly_booked`; missing `sender_id`; missing `last_bot_message_at`; unsupported `platform`.

**Templates:** admin `followup_24h` / `followup_3d` / `followup_7d` wins via `admin_config_service.render_template`. Safe Georgian fallback constants (`_FALLBACK_FOLLOWUP_24H` / `_3D` / `_7D` in `followup_service`) are used on miss or render exception. No fake urgency, no booking promise.

**Platform routing:** Conversation's `platform` (set on first inbound message by `webhook._extract_meta_messages` / `_extract_whatsapp_messages`) is passed verbatim to `messenger_service.send_message`. Instagram is the live-tested production channel; Messenger + WhatsApp are plumbed.

**Persistence:** after each successful (or attempted) send, the scheduler advances `followup_stage`, resets `last_bot_message_at` to "now", and write-throughs to Redis via `conversation_service._save_conversation_to_redis`.

**Kill switch:** `AGENT_ENABLED=false` short-circuits the tick BEFORE the snapshot scan. `comment_service.check_comment_followups` also respects the same flag.

**Bugs fixed alongside:** `sheets_service.get_cold_leads` cutoff now uses `now_tbilisi()` instead of naive `datetime.utcnow()` — eliminates the TypeError on aware-vs-naive comparison. Same fix applied to `get_pending_comment_followups`.

**11. Railway deploy not done.** Single-process only. P3-B made it safe to add more workers (state in Redis), but per-process in-memory dicts still race on the same sender across workers. Acceptable for v1 single-worker deploy.

**12. Public comment reply waiting on Meta App Review.** Code default is **`True`** — public replies auto-activate the moment `pages_manage_engagement` is granted on the production App AND the Page Access Token is refreshed. Until then Meta rejects the call with HTTP 400; the handler logs safely and the private reply still goes out unchanged. `.env` can force-disable per deploy.

**13. Legacy fallback paths still read `camp_2026.yaml` directly.** `parent_turn_router`, `parent_reply_composer`, `parent_turn_analyzer`, `parent_flow:2123` all call `load_knowledge("camp_2026")["camp"]` and would serve stale facts if `USE_PARENT_LLM_ENGINE=false`. Engine is `true` in live; legacy is dormant. Migrate when the legacy path is needed again.

**14. Admin Panel multi-event editor not built.** The existing `/admin/programs/<id>` UI edits ONE section at a time; for `adult_events` with multiple events the operator currently has to edit `data/admin_config/sections.yaml` directly or use a single-event form per event. A future patch should add a multi-event editor (list / add / edit / remove) to the Admin Panel.

### RESOLVED — Session 2 patches (2026-06-01 → 2026-06-02)

- ✅ ~~ADULT LLM Engine missing~~ — **ADULT LLM Engine + Cultural Events Patch (2026-06-01)** shipped `app/agent/llm/adult_llm_engine.py`, 6-tool `adult_tools` registry, `adult_tool_executor` security boundary, `system_adult_v1.md` + `adult_sales_policy.md`. Per-event `min_age` in `data/admin_config/sections.yaml`. Manager phone via `admin_config_service.get_manager_phone()` chain (never hard-coded). NO Calendar booking in adult flow. Pytest 802 → 856.
- ✅ ~~Expired booking memory was echoed back as active~~ — **Expired Booking Memory Fix Patch (2026-06-02)** added `parent_flow._expire_past_booking_if_needed(lead) → bool` helper that compares `lead.booked_datetime_iso` against Asia/Tbilisi "now" and demotes stale `calendly_booked=True` to `False` without touching Calendar / `calendar_event_id` / `status`. Wired into `_run_llm_engine_safely`, `_maybe_memory_info_reply`, `_strip_consultation_cta_if_booked`. Sensitive-needs sanitiser also added (`მენეჯერთან გავარკვევთ` → `მენეჯერი დეტალებს დაგიზუსტებთ`). Pytest 856 → 873.
- ✅ ~~ADULT bot answered general knowledge questions about Elton John / Mufasa / climate change~~ — **ADULT Off-Topic Guard + Event Grounding + Default Min-Age Fix Patch (2026-06-02)** added `_maybe_adult_offtopic_reply(user_message, conversation) → str | None` deterministic guard in `adult_llm_engine`. Guard runs BEFORE OpenAI; checks configured event content + in-scope domain stems + general-knowledge interrogative patterns. The fix wording „ამ სახელით ღონისძიება ჩვენს მიმდინარე პროგრამაში არ ჩანს" / „ამ კითხვაზე ვერ დაგეხმარები 😊" never asks „რომელ ღონისძიებასთან დაკავშირებით?" (the original bug). `ADULT_EVENT_DEFAULT_MIN_AGE` 18 → 13. 22 new tests. Pytest 873 → 896.
- ✅ ~~ADULT bot was asking broken "თქვენთვისაა ღონისძიებები"? / inventing event details / re-asking age / stopping after transition~~ — **ADULT Live QA Polish Patch (2026-06-02)** added 7 new sanitiser entries (3 for the broken who-question, 4 for `ახლახან ზუსტდება` family); STRICT EVENT GROUNDING section in `system_adult_v1.md` requires "ამ დეტალს მენეჯერი დაგიზუსტებთ." for empty fields; seed events flipped to `status: inactive`; new `Lead.adult_age: str` field STRICTLY separate from `child_age` (CRITICAL invariant); `save_adult_lead_info` tool accepts and validates `adult_age` (0–120); `_get_adult_events` reads stored `adult_age` when LLM omits `user_age`; `_build_context_message` surfaces `adult_age=X`; `parent_tool_executor._switch_to_adult_flow` transfers `child_age > 17` to `adult_age` + clears `child_age`; new `_ensure_adult_intro_followup` post-process appends next question when LLM produces just a bare confirmation; child-data privacy note section added to `system_parent_v2.md` with 4 triggers + DO-NOT list + „რატო გჭირდება ასაკი?" handler. 28 new tests. Pytest 896 → 924.
- ✅ ~~`openai.BadRequestError: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead.`~~ — **OpenAI Model Compatibility Patch (2026-06-02)** added `_uses_max_completion_tokens(model) → bool` helper + `_build_completion_kwargs(...)` single chokepoint. Routes both `_chat_completion` retry loop and `chat_with_tools` through the builder; selects EXACTLY ONE token-cap parameter per request (never both — also a 400). Boot log `[openai] model=… token_param=max_tokens|max_completion_tokens` confirms the shape in effect. Legacy `gpt-4.1-mini` is byte-compatible with pre-patch kwargs; new family (`gpt-5*`, `o1*`, `o3*`, `o4*`, anything containing `5.4`) uses `max_completion_tokens`. 32 new tests. Pytest 924 → 956.

### RESOLVED — Session 1 patches (2026-05-22 → 2026-05-31)

- ✅ ~~DONE-state greeting leak~~ — Parent Greeting Fix landed: `_maybe_static_welcome` fires regardless of inbound text on bot's first reply at `state=START`; sanitiser rewrites the leaked `მოგესალმებით!` family.
- ✅ ~~Challenge field not captured deterministically~~ — Scenario QA Bug Fix added `maybe_capture_challenge_fallback`.
- ✅ ~~Compound `{slot + name + phone}` slipped past PATCH 5 commit hook~~ — Scenario QA Bug Fix synthesises pending booking on the fly + `_parse_name_phone` rescues 9-digit window from greedy capture.
- ✅ ~~Adult pivot on age 18+ inconsistent~~ — Scenario QA Bug Fix tightened system prompt + `switch_to_adult_flow`.
- ✅ ~~Booked / DONE conversation re-routed to UNCLEAR menu~~ — Scenario QA Bug Fix added booked-state segment guard in `conversation_service`.
- ✅ ~~"ბოტი ხარ? / AI ხარ?" returned the menu~~ — Scenario QA Bug Fix added `_maybe_identity_reply` short-circuit.
- ✅ ~~Awkward Georgian leaks (`რომელი დრო რომელი დრო`, `ეს ბუნებრივია სრულად`, `ეს გასაგები მოტივაცია`, harsh ineligibility, defensive `თუ … მოგეჩვენათ`, `უკვე გასულია`)~~ — 12 new sanitiser entries across the two scenario patches.
- ✅ ~~Price objection mechanical~~ — Remaining Polish system-prompt rule (empathic open + value reminder + payment split + TBC / საქართველოს ბანკი).
- ✅ ~~Multi-child sibling discount not mentioned~~ — Remaining Polish system-prompt rule.
- ✅ ~~English camp intent → routing menu~~ — Remaining Polish: minimal English stems in `CAMP_KEYWORDS` + static-welcome yield.
- ✅ ~~Angry user got defensive deflection~~ — Remaining Polish system-prompt rule + sanitiser.
- ✅ ~~Past-date wording `უკვე გასულია`~~ — Remaining Polish system-prompt rule + sanitiser.

---

## 6. Architecture Direction — Path B (achieved for PARENT)

**Previous (pre-P3-C):**
The state machine was the brain. The deterministic keyword detector decided what to do. The LLM only wrote wording or classified intent as advisory input.

**Now (P3-C SAFE + PATCH 1–4):**
The LLM reasons over the conversation and **calls backend tools**. Backend validates + executes. The state machine survives as the fallback safety net (engine fail/empty → legacy). The final-stage fake-booking guard runs on engine output too.

**Engine architecture:**
```
parent_flow.handle
    if USE_PARENT_LLM_ENGINE:
        ParentToolExecutor + system_parent_v2.md
        → OpenAI chat.completions with PARENT_TOOLS
        → tool loop (≤ 5 iterations)
        → sanitise_response_wording (28+ rewrites)
        → _sanitise_booking_confirmation
        → return
    else:
        legacy state machine (P0/P1/P2 path)
```

**What backend ALWAYS owns (LLM never):**
- The Google Calendar API call itself.
- The Google Sheets row write.
- The manager notification send.
- The booking-confirmation template render (only after `calendar_service.book_slot` returns `True`).
- Phone validation.
- Age eligibility (9–17 from `camp_2026.yaml`).
- Datetime-confirmation gate (`user_confirmed_datetime`).
- Calendar event_id storage for cancel/reschedule.

**Next for ADULT (P3-D):**
Mirror the PARENT pattern: `events.yaml`, ADULT tools (`get_events`, `book_ticket`, `notify_manager`, `answer_from_knowledge`), system prompt. Then **P3-E** for the first live test.

---

## 7. Next Tasks

### Priority 1 — Next engineering tasks (2026-06-09 — Sessions 7-11 SHIPPED + Adult Subscription + Instagram Signature LIVE VERIFIED)

**A. Fix generic `#event` comment → active adult events list (~2–3 hours, IMMEDIATE).**
Current live bug: when a comment lands on a post with the generic `#event` hashtag and no specific event tag / no matching `facebook_post_id`, the comment handler falls into the "no schedule / empty roster" copy even though active events exist. The specific-event mapping (`#event #fast` → exact "fast" event) ALREADY WORKS (verified live).

Pickup:
- In `comment_service.send_dm_from_comment` (or its ADULT branch), when `resolve_specific_adult_event` returns `reason="no_match"` AND `admin_config_service.get_active_adult_events()` is non-empty, route through a NEW "list active events" rich DM (title + date + location + price per event, capped at top-3 by date).
- Specific-tag match must still beat the list (Priority A/B/C unchanged).
- Fallback "no schedule" copy only when `get_active_adult_events()` returns `[]`.
- Tests: add cases for (a) generic `#event` + 1 active event → 1-event list DM, (b) generic `#event` + 3 active events → 3-event list DM, (c) generic `#event` + 0 active events → existing fallback, (d) `#event #fast` + multiple events → still picks "fast" (specific wins).

**B. Full live QA sweep (~1 day, after #A lands).**
Operator-driven end-to-end smoke against the live `code.shelf` + Facebook page:
- `#camp` / `#ბანაკი` comment → camp DM
- `#event` (generic) comment → active adult events list (after #A fix)
- `#event` + specific tag comment → exact event DM
- Adult subscription opt-in via DM → `events` Sheets tab row created
- New event activation + Admin Panel broadcast button → DM lands on subscriber
- Re-run broadcast → duplicate prevented
- Unsubscribe phrase → status flipped to `unsubscribed`
- Instagram comment + DM → routes correctly through signature + handler

**C. Client production setup (~0.5–1 day, operator action).**
Provision the *client*'s real assets:
- Client Google Sheet (currently using tester account)
- Client Google Calendar (booking + busy calendars)
- Client email notification config (SMTP from address, manager recipient)
- Client WhatsApp manager-message config (`WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `MANAGER_WHATSAPP_NUMBER`)
- Client Facebook Page + Instagram asset connections (Meta App permissions)

**D. Railway deploy (~0.5 day).**
Procfile + always-on plan + Redis add-on. Single worker for v1. Sync ALL working `.env` to Railway env: `META_APP_SECRET`, `INSTAGRAM_APP_SECRET`, `INSTAGRAM_ACCESS_TOKEN`, `AGENT_ENABLED`, `VERIFY_WEBHOOK_SIGNATURE`, `BOOKING_CALENDAR_ID`, `BUSY_CALENDAR_IDS`, `SENTRY_DSN`, `OPENAI_MODEL`, Google credentials, `REDIS_URL`, WhatsApp creds when issued. Add `/health` route binding. Switch off ngrok; bind Meta webhook to Railway URL. Run production smoke test (DM + comment + booking + reschedule + IG + adult subscription + broadcast end-to-end).

### Priority 2 — Post-deploy / future iterations

**E. Meta App Review** — submit for `pages_manage_engagement` so public comment replies fire live (currently logs HTTP 400 + skips, DM still sent). SLA: 5+ business days.
**F. WhatsApp live test** — drive one end-to-end booking + manager-notification flow once `WHATSAPP_TOKEN` is in env.
**G. Adult follow-up scheduler** — extend `followup_service` to handle `segment == "ADULT"` with `adult_followup_24h` / `adult_followup_3d` / `adult_followup_7d` templates. Distinct from the operator-triggered Adult Event Subscription Broadcast (which is shipped + LIVE VERIFIED).
**H. SC-14 / SC-23 / SC-42 NORMAL scenario regressions** — re-run each twice to confirm LLM stochasticity vs real regression. Not deploy-blocking.

### Priority 3 — Session 7 engineering (live-QA pending — SHIPPED + VERIFIED)

These five tasks shipped in Sessions 7 + 8 and are now LIVE VERIFIED. Kept for historical context.

**1. Reschedule pending state fix (~1–1.5 hours).** ← SHIPPED Session 7. Live observation: user requested a reschedule, agent proposed a new slot, user confirmed, agent treated the confirmation as a fresh booking (the old Calendar event remained active). Root cause: `pending_reschedule` (or whatever shape carries the in-flight reschedule across turns) is not being persisted. Pickup:
   - Trace the reschedule turn end-to-end. Inspect `conversation.pending_booking` (does it get a `source="reschedule"` marker?) and the Redis write-through.
   - Decide between (a) reusing `pending_booking` with a new `source` value vs (b) adding a separate `pending_reschedule` field. The (a) path is cheaper but risks shape collision with the existing PATCH 5 commit hook.
   - Ensure the next-turn handler routes the user's confirmation back into `_reschedule_booking` (not `_book_consultation`).
   - Regression-test: an existing-booking user who says „გადამიტანეთ 10 ივნისს 10:00" + confirms must hit the safe-ordering reschedule path, old event must cancel, new event_id must persist, sanitizer must use the brand-standard reschedule confirmation.

**2. Adult transition dead-end fix (~30–45 min).** ← SHIPPED Session 7. `_ensure_adult_intro_followup` catch-all from Session 6 covers ≤120-char responses ending in „დაგეხმარებით." but a 2026-06-06 live response („ზრდასრულთა ღონისძიებებზე დაგეხმარებით.") still produced a dead-end. Pickup:
   - Read the live transcript / Sentry capture to confirm the exact bot output.
   - Verify whether the response actually reached the post-process (it should — no `?`, under 120 chars). If yes, the heuristic missed; broaden `_looks_like_bare_intro` or add the variant to `_ADULT_BARE_INTRO_PATTERNS`.
   - If the response did NOT reach the post-process, audit the sanitiser pipeline order and the early-return paths.
   - Test: add a regression case mirroring the exact live wording.

**3. Adult target wording: revert to „თქვენი შვილისთვის?" (~1 hour).** ← SHIPPED Session 7. Client preference confirmed 2026-06-06: the original wording is the brand-correct form. Sessions 6 + 7 standardised on „სხვა ადამიანისთვის?" — to be reverted. Pickup:
   - `app/agent/llm/adult_llm_engine.py`: revert `_ADULT_FOLLOWUP_QUESTION_WHO` to „ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?".
   - Revert the 5 sanitizer entries that rewrite the old form → new form. The remaining ADULT sanitizer (broken who-question family, period-/em-dash separators) stays.
   - `system_adult_v1.md`: revert the target-question rule.
   - Tests: invert the wording assertions in `test_adult_live_qa_polish.py::test_sanitiser_rewrites_broken_who_question_long`, `test_adult_context_routing_fix.py`, the Session-6 + Session-7 test files.
   - Confirm with client one more time before shipping.

**4. Manager email polish (~30–45 min).** ← SHIPPED Session 7. Two related bugs:
   - **Challenge duplicated in body.** The programmatic body builder (`notification_service._build_parent_summary`) writes the challenge, and the LLM-supplied conversation summary writes it again. De-dupe: when `lead.conversation_summary` contains the same Georgian challenge tokens as `lead.challenge`, strip the summary echo OR drop the programmatic line.
   - **Generic subject „ახალი ლიდი"** when `lead.name` is populated. Switch to `f"ახალი ლიდი — {lead.name}"` (or the existing template variant) when name is non-empty.
   - Pickup: live-fire a test booking with name populated; verify email subject + body have no duplicates.

**5. WhatsApp blank Bearer token guard (~15 min code + operator `.env` action).** ← SHIPPED Session 7. `notification_service._send_manager_whatsapp` currently posts the request even when `WHATSAPP_TOKEN` is empty, producing a Meta 400 + noisy traceback. Pickup:
   - Early-return guard: when `WHATSAPP_TOKEN` empty OR `MANAGER_WHATSAPP_NUMBER` empty, log a single `[notification] WhatsApp skipped — credentials missing` line and return cleanly. Email channel stays independent.
   - Operator: also populate `WHATSAPP_TOKEN` + `MANAGER_WHATSAPP_NUMBER` in `.env` once Meta WhatsApp Business credentials are issued for the production client.
   - Test: with empty token → no traceback, no Meta request fired; with valid token → existing path unchanged.

**Operator-action items for Session 7:**
- Confirm the adult-target-question revert with the brand owner one more time before shipping (#3).
- Populate `WHATSAPP_TOKEN` + `MANAGER_WHATSAPP_NUMBER` in live `.env` (#5).
- Re-run live ADULT smoke after #2 lands.

### Priority 4 — Historical: Adult event subscription spec (NOW SHIPPED Session 11)

**C. Adult event subscription (~1 day, blocked on Priority 1 #A).** ← SHIPPED 2026-06-08 in Session 11; LIVE VERIFIED 2026-06-09. Spec kept for historical context.
Operator-initiated broadcast channel for adult/cultural events. Distinct from the existing PARENT follow-up cadence (which is time-based per-conversation) — this is a one-to-many opt-in subscription list.

Conversation flow:
- Agent asks adult/cultural-event leads at end of conversation (or after a configurable inactivity window):
  „გსურთ, მომავალ ზრდასრულთა ღონისძიებებზეც გამოგიგზავნოთ ინფორმაცია, როცა ახალი ღონისძიება დაემატება?"
- If user agrees → save consent/subscription to Sheets.
- If user later writes „აღარ გამომიგზავნოთ" (or equivalents) → soft-unsubscribe.

Suggested Sheets storage: new `Adult Subscribers` tab (separate from the Leads tab so the broadcast cursor doesn't entangle with the lead-status workflow). Schema:
- `platform` (instagram / messenger / whatsapp)
- `sender_id`
- `name` (if available)
- `phone` (if available)
- `consent=true`
- `consent_at` (ISO Tbilisi)
- `source_event_id` (the event that prompted the opt-in, if any)
- `status` (subscribed / unsubscribed / bounced)

Broadcast trigger: when operator activates a new adult event in Admin Panel (`status: inactive → active`), an opt-in background job sends an automatic update DM to every `status=subscribed` subscriber. Must:
- Prevent duplicates (one DM per subscriber per event_id).
- Support unsubscribe via deterministic phrase scan.
- Mask sender ids in logs (existing `sentry_service.mask_sender`).
- Use the per-platform `messenger_service.send_message` channel (NEVER public comment).
- Respect `AGENT_ENABLED=false` master kill.

### Priority 3 — Session 7 engineering (live-QA pending — SHIPPED + VERIFIED)

These five tasks shipped in Sessions 7 + 8 and are now LIVE VERIFIED. Kept for historical context.

**1. Reschedule pending state fix (~1–1.5 hours).** Live observation: user requested a reschedule, agent proposed a new slot, user confirmed, agent treated the confirmation as a fresh booking (the old Calendar event remained active). Root cause: `pending_reschedule` (or whatever shape carries the in-flight reschedule across turns) is not being persisted. Pickup:
   - Trace the reschedule turn end-to-end. Inspect `conversation.pending_booking` (does it get a `source="reschedule"` marker?) and the Redis write-through.
   - Decide between (a) reusing `pending_booking` with a new `source` value vs (b) adding a separate `pending_reschedule` field. The (a) path is cheaper but risks shape collision with the existing PATCH 5 commit hook.
   - Ensure the next-turn handler routes the user's confirmation back into `_reschedule_booking` (not `_book_consultation`).
   - Regression-test: an existing-booking user who says „გადამიტანეთ 10 ივნისს 10:00" + confirms must hit the safe-ordering reschedule path, old event must cancel, new event_id must persist, sanitizer must use the brand-standard reschedule confirmation.

**2. Adult transition dead-end fix (~30–45 min).** `_ensure_adult_intro_followup` catch-all from Session 6 covers ≤120-char responses ending in „დაგეხმარებით." but a 2026-06-06 live response („ზრდასრულთა ღონისძიებებზე დაგეხმარებით.") still produced a dead-end. Pickup:
   - Read the live transcript / Sentry capture to confirm the exact bot output.
   - Verify whether the response actually reached the post-process (it should — no `?`, under 120 chars). If yes, the heuristic missed; broaden `_looks_like_bare_intro` or add the variant to `_ADULT_BARE_INTRO_PATTERNS`.
   - If the response did NOT reach the post-process, audit the sanitiser pipeline order and the early-return paths.
   - Test: add a regression case mirroring the exact live wording.

**3. Adult target wording: revert to „თქვენი შვილისთვის?" (~1 hour).** Client preference confirmed 2026-06-06: the original wording is the brand-correct form. Sessions 6 + 7 standardised on „სხვა ადამიანისთვის?" — to be reverted. Pickup:
   - `app/agent/llm/adult_llm_engine.py`: revert `_ADULT_FOLLOWUP_QUESTION_WHO` to „ღონისძიების შერჩევა თქვენთვის გსურთ თუ თქვენი შვილისთვის?".
   - Revert the 5 sanitizer entries that rewrite the old form → new form. The remaining ADULT sanitizer (broken who-question family, period-/em-dash separators) stays.
   - `system_adult_v1.md`: revert the target-question rule.
   - Tests: invert the wording assertions in `test_adult_live_qa_polish.py::test_sanitiser_rewrites_broken_who_question_long`, `test_adult_context_routing_fix.py`, the Session-6 + Session-7 test files.
   - Confirm with client one more time before shipping.

**4. Manager email polish (~30–45 min).** Two related bugs:
   - **Challenge duplicated in body.** The programmatic body builder (`notification_service._build_parent_summary`) writes the challenge, and the LLM-supplied conversation summary writes it again. De-dupe: when `lead.conversation_summary` contains the same Georgian challenge tokens as `lead.challenge`, strip the summary echo OR drop the programmatic line.
   - **Generic subject „ახალი ლიდი"** when `lead.name` is populated. Switch to `f"ახალი ლიდი — {lead.name}"` (or the existing template variant) when name is non-empty.
   - Pickup: live-fire a test booking with name populated; verify email subject + body have no duplicates.

**5. WhatsApp blank Bearer token guard (~15 min code + operator `.env` action).** `notification_service._send_manager_whatsapp` currently posts the request even when `WHATSAPP_TOKEN` is empty, producing a Meta 400 + noisy traceback. Pickup:
   - Early-return guard: when `WHATSAPP_TOKEN` empty OR `MANAGER_WHATSAPP_NUMBER` empty, log a single `[notification] WhatsApp skipped — credentials missing` line and return cleanly. Email channel stays independent.
   - Operator: also populate `WHATSAPP_TOKEN` + `MANAGER_WHATSAPP_NUMBER` in `.env` once Meta WhatsApp Business credentials are issued for the production client.
   - Test: with empty token → no traceback, no Meta request fired; with valid token → existing path unchanged.

**Operator-action items for Session 7:**
- Confirm the adult-target-question revert with the brand owner one more time before shipping (#3).
- Populate `WHATSAPP_TOKEN` + `MANAGER_WHATSAPP_NUMBER` in live `.env` (#5).
- Re-run live ADULT smoke after #2 lands.

### Priority 2 — Infrastructure / pre-deploy quick fixes (~1 hour)

**6. Quick fixes batch (~1 hour total).**
   - **Add `.gitignore`** at repo root: `.env`, `credentials.json`, `__pycache__/`, `.venv/`, `*.bak`, `data/admin_config/*.bak`. Verify nothing sensitive committed historically before any `git push`. **30 min.**
   - **`requirements-dev.txt`** with `pytest`, `pytest-asyncio`, `sentry-sdk[fastapi]`, `redis`, `fakeredis`, `python-multipart`. **15 min.**
   - **`notification_service.py:28` v18 → v19.** Replace hardcoded URL with `settings.META_GRAPH_API_VERSION` read. **5 min.**
   - **`mask_sender` standardization.** Unify on `sid[:6] + "***"` across `kill_switch.py` + `sentry_service.py`. **10 min.**

**7. Railway setup + Redis add-on + live deploy (~0.5 day).** Procfile + always-on plan + Redis add-on. Single worker for v1. Sync live `.env` from `.env.example` (`META_APP_SECRET`, `AGENT_ENABLED`, `VERIFY_WEBHOOK_SIGNATURE`, `BOOKING_CALENDAR_ID`, `BUSY_CALENDAR_IDS`, `SENTRY_DSN`, `OPENAI_MODEL` confirmation). Switch off ngrok; bind Meta webhook to Railway URL.

### Priority 3 — Post-deploy integrations (~1–2 days + Meta SLA)

**8. Meta App Review submission** — `pages_manage_engagement` so the already-on `ENABLE_PUBLIC_COMMENT_REPLY=True` actually fires for public replies. Client must complete Business Verification first; SLA can be 5+ business days.

**9. WhatsApp manager notification live test** — drive one end-to-end booking and confirm manager receives the WhatsApp message. Depends on Priority 1 #5 + `.env` credentials.

**10. SC-14 / SC-23 / SC-42 NORMAL-tier scenario regression fix** — re-run each twice to confirm LLM stochasticity vs real regression. CRITICAL 22/22 + security 4/4 + adult 3/3 preserved through all sessions; these three are wording-only.

**11. Adult follow-up scheduler** — current scheduler skips non-PARENT segments. Author `adult_followup_24h` / `_3d` / `_7d` templates in `data/admin_config/templates.yaml`; extend `followup_service` cadence to include `segment == "ADULT"` with adult-specific blocked-reasons.

**(legacy-numbered items below preserved for historical context)**

**1-old. Admin Panel multi-event support (~2–3 hours).** Build the list / add / edit / remove UI for `adult_events` (and any future multi-event section). Today the operator edits `data/admin_config/sections.yaml` directly — risky and slow. After this lands, the Admin Panel becomes the single source of truth for event content.

✅ **Session 6 update (2026-06-05):** A minimal events[] editor was shipped (`/admin/programs/adult_events/events` list + new + edit + delete) backed by `save_adult_event` / `delete_adult_event`. The remaining "multi-event UI polish" (richer table view, validation messages, drag-to-reorder) is deferred to a future quality-of-life batch — current functionality is sufficient for the operator's day-to-day workflow.

**2. Quick fixes (~1 hour total).**
   - **Add `.gitignore`** at repo root including `.env`, `credentials.json`, `__pycache__/`, `.venv/`, `*.bak`, `data/admin_config/*.bak`. Verify nothing sensitive has been committed historically before any `git push`. **30 min.**
   - **`requirements-dev.txt` + production install order.** Add `pytest`, `pytest-asyncio`, `sentry-sdk[fastapi]`, `redis`, `fakeredis`, `python-multipart`. **15 min.**
   - **`notification_service.py:28` v18 → v19.** Replace hardcoded URL with `settings.META_GRAPH_API_VERSION` read. **5 min.**
   - **`mask_sender` standardization.** Unify on `sid[:6] + "***"` across `kill_switch.py` + `sentry_service.py`. **10 min.**

**3. `BUSY_CALENDAR_IDS` operator action (~5 min).** Add the manager's actual side-calendar id(s) (e.g. „Nikoloz Analytics" calendar) to `BUSY_CALENDAR_IDS` in the live `.env`. Each calendar must be shared with the Google service account (`ai-agent-service@ai-agent-test-496312.iam.gserviceaccount.com`) — otherwise the FreeBusy query returns a per-calendar `errors` block and the agent fails CLOSED on every availability check. Required to make the Calendar Multi-Busy Check Patch (2026-06-04) effective against real side-calendar bookings.

### Priority 2 — Deploy (~0.5–1 day)

4. **Railway setup + Redis add-on** — Procfile + always-on plan + Redis add-on. Single worker for v1.
5. **Sync live `.env` from `.env.example`.** Add `META_APP_SECRET` (enforce signature), `AGENT_ENABLED`, `VERIFY_WEBHOOK_SIGNATURE`, `BOOKING_CALENDAR_ID`, `BUSY_CALENDAR_IDS`, `SENTRY_DSN` (if Sentry account ready), `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE`. Confirm `OPENAI_MODEL=gpt-5.4-mini` is set. **5 min + Sentry account setup if doing it.**
6. **Admin Panel: populate adult events.** Use `/admin/programs/adult_events` (or the new multi-event editor from Priority 1 #1 once built) to add real events with `date_text` / `location` / `theme` / `price_text` / `reservation_url` / `min_age` / `seats_available`. Flip `status: inactive` → `status: active` once filled. Without this, adult traffic produces only the "no active events" handoff.
7. **Client credentials handover** — Gmail / WhatsApp Business / Meta App / Google service account swap from "AI Agent Test" infra to the client's production accounts.
8. **Client Meta App + Business Verification** — kick off Business Verification immediately; can take 5+ business days.
9. **Live deploy + smoke test** — health check, ngrok-free webhook URL, end-to-end DM + comment flow on the production Meta App. Include a manual reschedule against a known side-calendar busy block to confirm the multi-busy check actually fires.

### Priority 3 — Post-deploy integrations

10. **Meta App Review submission** — `pages_manage_engagement` so the already-on `ENABLE_PUBLIC_COMMENT_REPLY=True` actually fires.
11. **WhatsApp manager notification live test** — set `MANAGER_WHATSAPP_NUMBER` + `WHATSAPP_TOKEN`, drive one booking, confirm manager receives WhatsApp.
12. **SC-14 / SC-23 / SC-42 scenario regression fix** — re-run each twice to confirm LLM-stochasticity vs real regression. If real, calibrate either the scenario assertion or the prompt + sanitiser.
13. **Adult follow-up scheduler** — current scheduler skips non-PARENT segments. Author `adult_followup_24h` / `_3d` / `_7d` templates in `data/admin_config/templates.yaml`; extend `followup_service` cadence to include `segment == "ADULT"` with adult-specific blocked-reasons.
14. **Payment integration (phase 2)** — for paid adult events. Currently `provide_adult_reservation_link` returns the configured `reservation_url`. Phase 2 wires a payment-provider webhook back into the bot for booking confirmation.
15. **Follow-up live monitoring** — confirm the 24h / 3d / 7d cadence fires correctly post-deploy and respects `followup_blocked_reason`.
16. **Legacy-fallback admin migration** — `parent_turn_router` + `parent_reply_composer` + `parent_turn_analyzer` → `get_camp_facts()`. Currently safe because engine is on; needed before any future legacy fallback.

**Total before deploy: Admin multi-event (~2–3 hours) + Quick Fixes (~1 hour) + operator BUSY_CALENDAR_IDS sync (~5 min) + Railway/.env sync/Admin populate (~0.5 day) + external Business Verification SLA.**

### Deploy risks

| Severity | Risk | Mitigation before deploy |
|---|---|---|
| 🟡 High | **`.gitignore` missing + `credentials.json` in tree** — Google service account exposure on first `git push` | Priority 1 #1 |
| 🟡 High | **`META_APP_SECRET` missing from live `.env`** — webhook signature fail-open until set | Priority 1 #5 |
| 🟡 High | **Meta App Business Verification** — client SLA | Start with client on Day 1 |
| 🟡 High | **Gmail 2FA + App Password** — client account setup | Client must enable 2FA + generate App Password |
| 🟡 Medium | **Railway paid plan** — always-on uptime | Choose hobby tier minimum |
| ✅ Done   | **Kill switch** — `AGENT_ENABLED` env flag | Patch landed 2026-05-30 |
| ✅ Done   | **Error monitoring** — optional Sentry, safe-fallback | Patch landed 2026-05-31 |
| ✅ Done   | **Follow-up scheduler** — wired to Conversation markers | Patch landed 2026-05-30 |
| ✅ Done   | **Comment follow-up 400 retry-loop** — eligibility tightened | Patch landed 2026-05-31 |
| ✅ Done   | **Webhook signature** — `X-Hub-Signature-256` HMAC verified | Patch landed 2026-06-01 |
| ✅ Done   | **Booked-state memory polish** — deterministic short-circuit + sanitiser | Patch landed 2026-05-30 |

---

## 8. Known Bugs

### IMPORTANT

1. **`.gitignore` missing + `credentials.json` in working tree** — Surfaced 2026-06-01 by REVIEW_PACK. Repo isn't currently a git repo, so nothing pushed yet; **30-min fix** before any `git init && git push`.

2. **`META_APP_SECRET` (and `AGENT_ENABLED`, `SENTRY_DSN`, `VERIFY_WEBHOOK_SIGNATURE`) missing from live `.env`** — `.env.example` documents them all; live `.env` (`grep -oE "^[A-Z_]+=" .env`) does not. Defaults are safe (kill-switch ON, signature verification fail-open, Sentry disabled) but enforcement / monitoring won't actually fire until operator syncs.

3. **`notification_service.py:28` v18.0 hardcoded** — manager-WhatsApp path lags behind everything else (v19). **15-min fix.**

4. **Adult flow never live-tested end-to-end** — state machine + PATCH 7 global guard work, but the full SHOW_EVENTS → SEND_BOOKING path has not been driven on real Instagram. **P3-D + P3-E.**

5. **Public comment reply waiting on Meta App Review** — `ENABLE_PUBLIC_COMMENT_REPLY` code default is `True`. Public replies auto-activate once `pages_manage_engagement` is granted AND the Page Access Token is refreshed; until then Meta returns HTTP 400 and the handler logs safely + still sends the private DM.

6. **Legacy fallback paths still read `camp_2026.yaml` directly** — `parent_turn_router`, `parent_reply_composer`, `parent_turn_analyzer`, `parent_flow:2123` all call `load_knowledge("camp_2026")["camp"]` and would serve stale facts if `USE_PARENT_LLM_ENGINE=false`. Engine is `true` in live; legacy is dormant.

7. **`requirements.txt` missing dev/optional deps** — `pytest`, `sentry-sdk`, `redis`, `fakeredis`, `python-multipart`. Production install needs separate `pip install` steps. **Add `requirements-dev.txt` (~15 min).**

### MINOR

8. **`mask_sender` shape divergence** — `kill_switch.mask_sender` returns `"***" + sid[-4:]`; `sentry_service.mask_sender` returns `sid[:6] + "***"`. Both still mask; standardize for consistent log correlation.

9. **`get_user_profile` 400 error** in test mode — Meta returns 400 for the test page. Not blocking production; gracefully falls back to empty profile.

10. **`adult_defaults.yaml`** duplicated against Python constants in `data/prompts.py`; adult_flow reads the Python ones.

11. **Comment post-content cache** is process-local with a 1h TTL — restart wipes; not a correctness bug, just an extra Graph API GET after restart.

12. **Dead code from AUDIT_REPORT.md §9 still present** — `OpenAIService`, `ContentRepository`, `FlowContext`, `SafeFormatter`, `MessengerService`, `SheetsService`, `NotificationService`, `FollowupService` class shells, plus `parent_flow._generate_parent_response` / `_end_with_consultation_offer` / `_format_available_slots` / `_wants_consultation`. ~600 LOC inert. Cleanup deferred.

### RESOLVED (moved out of this section)

- ✅ ~~`sheets_service.get_cold_leads` naive datetime bug~~ → Follow-up Scheduler Patch (2026-05-30): `cutoff = now_tbilisi() - 48h`.
- ✅ ~~Webhook signature unverified~~ → Webhook Signature Verification Patch (2026-06-01).
- ✅ ~~Kill switch missing~~ → Kill Switch Patch (2026-05-30).
- ✅ ~~Error monitoring weak~~ → Basic Error Monitoring Patch (2026-05-31).
- ✅ ~~Follow-up scheduler not wired to Conversation markers~~ → Follow-up Scheduler Patch (2026-05-30).
- ✅ ~~Comment follow-up 400 retry-loop~~ → Comment Follow-up Logic Fix (2026-05-31).
- ✅ ~~Booked-state memory response polish~~ → Booked State Memory Response Polish Patch (2026-05-30).

---

## 9. File Map (canonical, updated 2026-06-08)

**New files added Session 8 + Hydrate + Test Mode + Session 7 (2026-06-06 → 2026-06-07):**

| File | Purpose | Status | Notes |
|---|---|---|---|
| `tools/run_followup_tick.py` ⭐ **Follow-up Live-Test Hydrate Patch (2026-06-06)** | CLI helper: hydrate Redis-persisted conversations → run scheduler tick once. `--dry-run` lists due conversations without sending. | ✅ | Imports `sys` + `Path` bootstrap so `python tools/run_followup_tick.py` works without `python -m`. |
| `tests/test_session8_booking_confirmation_sheets_reschedule.py` ⭐ **Session 8 LIVE QA (2026-06-07)** | 17 tests across doubled-clause sanitizer (2) / booked-state stripper (3) / success-turn trim (1) / full-flow booking confirmation shape (2) / Sheets helper happy path (3) / Sheets helper failure modes (3) / reschedule executor wiring (3). | ✅ | All green; 17 new tests (1333 → 1350). |
| `tests/test_followup_hydrate_patch.py` ⭐ **Follow-up Live-Test Hydrate Patch (2026-06-06)** | 13 tests across scan_keys (3) / hydrate (4) / scheduler counter logging (4) / end-to-end CLI simulation (1) / CLI tool smoke import (1). | ✅ | 13 new tests (1320 → 1333). |
| `tests/test_followup_test_mode_live_patch.py` ⭐ **Follow-up Test Mode Patch (2026-06-06)** | 30 tests across config knobs (10) / scheduler skip rules (5) / Messenger DM 2-min flow (6) / comment DM marker (3) / fallback text safety (3) / privacy logging (3). | ✅ | 30 new tests (1290 → 1320). |
| `tests/test_live_qa_session7_reschedule_notification_patch.py` ⭐ **Session 7 LIVE QA (2026-06-06)** | 39 tests across reschedule pending state (10) / adult intro followup (4) / adult target wording revert (6) / manager email polish + dedupe (10) / WhatsApp blank-token (5) / booking confirmation trim (3) / helper (1). | ✅ | 39 new tests (1251 → 1290). |

**New files added Session 6 (2026-06-05 FULL Live QA Patch — Admin adult_events + 11 wording/routing/safety bugs):**

| File | Purpose | Status | Notes |
|---|---|---|---|
| `templates/admin/adult_events.html` ⭐ **Adult Events Editor (Session 6)** | Admin Panel list view for `adult_events.events[]` — table of events with edit / delete actions and a "+ ახალი ღონისძიება" link to the new-event form. | ✅ | Minimal styling per Session 6 spec ("Visual polish is NOT important"). Inherits from `admin/base.html`. |
| `templates/admin/adult_event_form.html` ⭐ **Adult Events Editor (Session 6)** | Add / edit form for a single adult event. Fields: id (optional, auto-derived), title (required), status, min_age (defaults 13), date_text, location, price_text, price_gel, description, reservation_url, facebook_post_id, tags. | ✅ | POSTs to `/admin/programs/adult_events/events/new` or `/{event_id}` per the routes in `app/routes/admin.py`. |
| `tests/test_full_live_qa_session6_patch.py` ⭐ **FULL Live QA Patch (Session 6)** | 12 bugs × multi-test groups: Bug 1A section fallback (5) + Bug 1B events CRUD (6) + Bug 2 prompt assertion (1) + Bug 3 wording + relative cue (4) + Bug 4 context surface + lead separation (3) + Bug 5 floor + filter (5) + Bug 6 manager handoff sanitizer (3) + Bug 7 sibling discount guard (6) + Bug 8 name filler-word extraction (7) + Bug 9 reschedule safe ordering (4) + Bug 10 confirmation strip (2) + Bug 11 verification phrase expansion (6) + Bug 12 wording polish (2) — **55 net new tests**. | ✅ | Pytest 1196 → 1251 net (1 test was a runner-mock fix in `tools/scenario_runner_full.py` plus updates to 4 existing test files; the net new test count from this single new file is 55). |

**New files added Session 3 (2026-06-02 → 2026-06-04):**

| File | Purpose | Status | Notes |
|---|---|---|---|
| `tests/test_adult_context_routing_fix.py` ⭐ **ADULT Context Routing Fix** | 9 transition follow-up + 6 child_age leakage + 11 relative-intent routing + 6 target fields + 6 deterministic capture + 1 end-to-end + 4 prompt/policy + 1 separation sanity (**44 tests**) | ✅ | |
| `tests/test_agent_wording_cleanup.py` ⭐ **Agent Wording Cleanup** | 11 emoji-free template checks + 5 sanitiser emoji-strip + 7 manager-handoff rewrites + 9 prompt/policy documentation + 4 sanitiser idempotency + 5 regression + 3 misc (**44 tests**) | ✅ | |
| `tests/test_booking_availability_patch.py` ⭐ **Booking Availability** | 11 valid/invalid hour matrix + 60-min event duration + 12:00–17:00 busy hiding + 12:30–13:30 partial overlap + exact-boundary non-block + whole-hour-only enumeration + 11-slot full window + pre-booking re-check race + Calendar API fail-CLOSED + Free/Busy exception fail-CLOSED + 3 prompt/yaml + 11-row reason matrix (**32 tests**) | ✅ | |
| `tests/test_calendar_multi_busy_patch.py` ⭐ **Calendar Multi-Busy Check** | 7 settings/fallback + 11 multi-calendar FreeBusy (queries all ids / union / busy on booking / busy on side / 10:30–19:00 blocks 11..18 / partial overlap / fail-CLOSED on errors / fail-CLOSED on HTTP / fail-CLOSED on missing entry / get_free_slots_for_day uses multi-busy / empty on failure) + 3 booking-target + 5 sanitiser + 2 prompt evidence + 1 end-to-end reschedule (**29 tests**) | ✅ | |

**New files added Session 2 (2026-06-01 → 2026-06-02):**

| File | Purpose | Status | Notes |
|---|---|---|---|
| `app/agent/llm/adult_llm_engine.py` ⭐ **ADULT Engine** | ADULT LLM tool-calling loop + `sanitise_adult_response` + `_ensure_adult_intro_followup` + `_maybe_adult_offtopic_reply` + `_user_wants_parent_flow` | ✅ | Fail/empty → legacy `adult_flow.handle` state machine. |
| `app/agent/tools/adult_tools.py` ⭐ **ADULT Engine** | 6 tool schemas (`get_adult_events`, `get_adult_event_details`, `save_adult_lead_info`, `request_adult_manager_callback`, `provide_adult_reservation_link`, `switch_to_parent_flow`) | ✅ | `save_adult_lead_info` accepts `adult_age` (Live QA Polish). |
| `app/agent/tools/adult_tool_executor.py` ⭐ **ADULT Engine** | Backend validator/executor for all 6 ADULT tools | ✅ | NEVER touches Calendar. Manager phone via `admin_config_service.get_manager_phone()`. |
| `app/agent/prompts/system_adult_v1.md` ⭐ **ADULT Engine** | ADULT LLM system prompt: refined / premium tone, age-aware question phrasing (3-branch rule), strict event grounding, transition rule, age memory, off-topic section, forbidden phrases | ✅ | Loaded once at engine boot. |
| `app/agent/policies/adult_sales_policy.md` ⭐ **ADULT Engine** | 13-section operational sales policy (role / conversation / age phrasing + memory / age outside camp range / facts / reservation / manager handoff / parent switch / decline / tone / grammar / scope rule / future verticals) | ✅ | |
| `tests/test_adult_llm_engine.py` ⭐ **ADULT Engine** | Engine routing + sanitizer + parent-switch detection (18 tests) | ✅ | |
| `tests/test_adult_tool_executor.py` ⭐ **ADULT Engine** | All 6 tools + idempotent manager-notified guard + no-Calendar invariant (18 tests) | ✅ | |
| `tests/test_adult_admin_config.py` ⭐ **ADULT Engine** | `get_adult_events` + age filter + min_age default 13 + summer_camp/sunday_school unchanged (14 tests after Default Min-Age Fix update) | ✅ | |
| `tests/test_adult_manager_notification.py` ⭐ **ADULT Engine** | ADULT labels in email (no `ბავშვის ასაკი` / `ღრმა ფესვი`) + no Calendar booking in handoff path (5 tests) | ✅ | |
| `tests/test_adult_scope_guard.py` ⭐ **ADULT Off-Topic Guard** | Mufasa / Elton / climate / fiction-stems blocked; in-scope conversation NOT blocked; configured guest allow; camp-switch precedence (22 tests) | ✅ | |
| `tests/test_adult_live_qa_polish.py` ⭐ **ADULT Live QA Polish** | Bug 1 phrasing (4) / Bug 2 grounding (6) / Bug 3 age memory + PARENT→ADULT transfer (8 + 3) / Bug 4 transition follow-up (5) / Part 5 privacy note (3) — **28 tests** | ✅ | |
| `tests/test_expired_booking_memory_fix.py` ⭐ **Expired Booking Memory Fix** | Helper expires past `booked_datetime_iso`; preserves `calendar_event_id` + `status`; memory-info reply uses spec-prescribed closing line; CTA stripper passes-through expired; `მენეჯერთან გავარკვევთ` sanitiser (17 tests) | ✅ | |
| `tests/test_openai_model_compatibility.py` ⭐ **OpenAI Model Compatibility** | `_uses_max_completion_tokens` matrix (17 names) + builder + both call sites + Parent+Adult engine integration + byte-compat legacy regression (32 tests) | ✅ | |

**Existing files canonical reference (Session 1, retained for context — patches above add to them):**



✅ = production-ready · ⚠️ = works with caveats · ❌ = broken/untested · ⏳ = planned

| File | Purpose | Status | Notes |
|---|---|---|---|
| `REVIEW_PACK.md` ⭐ **2026-06-01** | Read-only project audit — 12 sections (executive summary, architecture, capability matrix, tool registry, data model, tests & QA, security & ops, bugs, gaps backlog, "couldn't confirm from code alone", final verdict) | ✅ | Created 2026-06-01; updated with "Post-audit fixes applied" header. |
| `app/main.py` | FastAPI + scheduler boot | ✅ | Prints all engine flag values + Sentry status + Redis status at boot. cp1252 emoji issue on Windows (set `PYTHONIOENCODING=utf-8`). |
| `app/config.py` | Settings (.env reader) + flags | ✅ | Now includes `AGENT_ENABLED`, `VERIFY_WEBHOOK_SIGNATURE`, `SENTRY_DSN/ENVIRONMENT/TRACES_SAMPLE_RATE`. `ENABLE_PUBLIC_COMMENT_REPLY` default flipped to `True` (2026-05-31). |
| `app/routes/webhook.py` | Meta verify + receive + comments | ✅ | ⭐ **Webhook Signature Verification Patch (2026-06-01)** — `_verify_meta_signature(raw, header)` HMAC-SHA256 gate runs BEFORE the JSON parse + background task. `hmac.compare_digest` constant-time compare. Fail-open when secret empty. PATCH 1 debug logs + Comment Flow PATCH 1–2. |
| `app/services/openai_service.py` | All OpenAI surfaces | ✅ | + `chat_with_tools` (P3-C SAFE) + Georgian-only `generate_summary` with English-detection fallback (PATCH 2). |
| `app/services/conversation_service.py` | Routing + segment classifier + in-memory store + **follow-up marker capture (PATCH 3)** + **`reset_conversation_for_sender` (PATCH 7)** | ⚠️ | In-memory `conversations` dict. |
| `app/services/messenger_service.py` | Meta Graph send + profile fetch + **`send_private_reply(comment_id, text)` (Comment Flow PATCH 2)** | ✅ | 259 lines. 3 retries × 2s. |
| `app/services/sheets_service.py` | Google Sheets CRM | ✅ | Timestamps Asia/Tbilisi (P2). `get_cold_leads` + `get_pending_comment_followups` cutoff now tz-aware (`now_tbilisi()`) — bug fixed 2026-05-30. Comment Follow-up Logic Fix (2026-05-31) tightened pending-comment eligibility to `DM Sent==TRUE` + `Status=="DMSent"`. |
| `app/services/calendar_service.py` | Google Calendar booking | ✅ | 595 lines. + `cancel_calendar_event` (PATCH 1). `get_free_slots(start_date=…, days=…)` (PATCH 4). PATCH 6: today-only buffer + shared `is_within_business_hours` + `check_slot_calendar_only`. `book_slot` stashes `event_id` on lead. |
| `app/services/notification_service.py` ⭐ **Email Wording Patch** | Email/WhatsApp/SMS to manager — programmatic body builder with `_georgian_genitive`, conditional `deeper_concern`, fixed Georgian summary, contact-info block, Georgian-formatted booking datetime | ✅ | Email path live tested. WhatsApp + SMS still untested. v18 URL still hardcoded (issue #7). |
| `app/services/redis_state_service.py` ⭐ **P3-B** | Lazy-connect Redis client + `get_json / set_json / delete / exists / ping / log_startup_status`. Password never logged. Safe-fallback to no-op when disabled/unavailable. | ✅ | Live tested with restart sim + real local Redis. |
| `app/services/admin_config_service.py` ⭐ **Admin Panel MVP + Config Unification** | Loader, hashtag router, template renderer, validator, write API. `get_camp_facts()` admin-first merge over `camp_2026.yaml`. `parse_price_gel()` for form-save price sync. | ✅ | |
| `app/routes/admin.py` ⭐ **Admin Panel MVP** | 8 admin routes (dashboard / programs list / new / edit / delete / templates / settings) with HTTP Basic Auth. `_form_to_section_dict` derives `price_gel` + parses streams/included_items/discounts textareas. TemplateResponse uses Starlette 0.49 signature. | ✅ | |
| `templates/admin/*.html` ⭐ **Admin Panel MVP** | `base.html`, `dashboard.html`, `programs.html`, `program_form.html`, `templates.html`, `settings.html` — plain Jinja2 + inline CSS, no JS framework. | ✅ | |
| `data/admin_config/sections.yaml` ⭐ | summer_camp / sunday_school / adult_events registry. Operator-editable from `/admin`. | ✅ | |
| `data/admin_config/templates.yaml` ⭐ | `default_public_reply`, `summer_camp_comment_dm`, `sunday_school_comment_dm`, `adult_events_comment_dm`, `generic_section_comment_dm`, `followup_24h/3d/7d`. | ✅ | |
| `data/admin_config/business_hours.yaml`, `data/admin_config/manager_contacts.yaml` ⭐ | Operator-visible mirrors. Booking pipeline still reads canonical `app/agent/knowledge/business_hours.yaml`. | ✅ | |
| `app/services/followup_service.py` ⭐ **Follow-up Scheduler Patch (2026-05-30)** | Conversation-marker-driven 24h/72h/168h cadence | ✅ | Stages `"" → "first_24h" → "second_3d" → "third_7d"`. Skip rules: 6 blocked reasons + non-PARENT + missing fields + unsupported platform. Admin templates + safe Georgian fallback. Platform routing preserved. Redis write-through after each send. Kill-switch + Sentry capture gated. |
| `app/services/comment_service.py` ⭐ **Comment Follow-up Logic Fix (2026-05-31)** | Public IG/FB comment handler + private reply routing + rich first-contact DMs + comment follow-up scheduler | ✅ | Live tested. Builds PARENT DM from `camp_2026.yaml`, ADULT DM from `data/events.txt`. Follow-up loop: active-conversation skip, HTTP 400 → `Expired` + processed-guard + no retry, success → `FollowupSent`. |
| `app/services/kill_switch.py` ⭐ **Kill Switch Patch (2026-05-30)** | `AGENT_ENABLED` gate + `AGENT_DISABLED_MESSAGE` constant + `is_agent_enabled()` + `mask_sender()` + `log_disabled_skip()` | ✅ | Three entry-point guards: `process_message`, `handle_comment`, `check_and_send_followups`. |
| `app/services/sentry_service.py` ⭐ **Basic Error Monitoring Patch (2026-05-31)** | Optional Sentry wrapper. `init_sentry`, `capture_exception(exc, context)`, `capture_message`, `set_tag`, `mask_sender` | ✅ | Safe no-op when `SENTRY_DSN` empty OR `sentry-sdk` missing. Three capture points: conversation / executor / follow-up. Privacy-safe context only. `send_default_pii=False`. |
| `app/services/message_buffer.py` | 5–15s debounce | ✅ | Per-sender locks, in-memory. |
| `app/flows/parent_flow.py` | PARENT state machine + DONE handler + **P3-C engine gate** + **PATCH 5–8 hooks** | ✅ | 2201 lines. Static welcome bypass, decline handler, time-change handler, pending-booking commit, ineligible-age CTA scrubber. Engine runs first when flag is true; legacy fallback when engine empty/fails. |
| `app/flows/parent_turn_router.py` | Deterministic-first interrupt router + pending booking | ✅ | 1338 lines. Used by legacy fallback only. PATCH 5 added past-tense booking-confirmation stems to the fake-booking guard list. |
| `app/flows/adult_flow.py` | ADULT state machine + **PATCH 7 global intent guard** | ⚠️ | 511 lines. Still no LLM engine; never live-tested end-to-end. |
| `app/agent/intent/parent_intent_detector.py` | Closed-set Georgian stem detector (P0) | ✅ | 384 lines. |
| `app/agent/llm/parent_reply_composer.py` | Discovery + post-booking composer | ✅ | 789 lines. |
| `app/agent/llm/parent_turn_analyzer.py` | LLM JSON-classifier | ✅ | 398 lines. |
| `app/agent/llm/parent_llm_engine.py` ⭐ **P3-C** | LLM tool-calling loop + `sanitise_response_wording` (60+ rewrites across PATCH 1–8) + situation-aware sales context + pending_booking context exposure | ✅ | 841 lines. |
| `app/agent/llm/prompt_loader.py` | Markdown prompt loader | ✅ | |
| `app/agent/tools/parent_tools.py` ⭐ **P3-C** | 8 tool schemas (camp info, slots, book, cancel/reschedule, manager, save lead, adult switch, **check_consultation_slot — PATCH 6**) | ✅ | 411 lines. |
| `app/agent/tools/parent_tool_executor.py` ⭐ **P3-C** | Backend validator/executor for all 8 tools + per-conversation success flag + phone-mask logs | ✅ | 1371 lines. |
| `app/agent/services/knowledge_loader.py` | YAML knowledge loader | ✅ | |
| `app/agent/services/template_loader.py` | YAML template loader | ✅ | |
| `app/agent/services/timestamps.py` | Asia/Tbilisi formatter | ✅ | |
| `app/models/conversation.py` | Conversation dataclass + `to_dict` / `from_dict` + `pending_booking` + **PATCH 3 follow-up fields (5 new)** | ✅ | Redis-ready JSON. |
| `app/models/lead.py` | Lead dataclass + `from_dict` + `booked_datetime_iso` + **`calendar_event_id` (PATCH 1)** | ✅ | |
| `app/agent/prompts/system_base.md` | Brand voice + grammar rules | ✅ | |
| `app/agent/prompts/system_parent.md` | Legacy PARENT role + camp facts | ✅ | Used by legacy flow only. |
| `app/agent/prompts/system_parent_v2.md` ⭐ **P3-C** | LLM engine system prompt (audience-aware sales, age first, value mechanisms, exact-slot rules, `check_consultation_slot` rules, ineligible-age ban, screen-conditional, adult-switch wording, forbidden phrases) | ✅ | ~22 KB after PATCH 5–8 additions. Loaded once at engine boot. |
| `app/agent/prompts/system_adult.md` | ADULT role | ✅ | Untested live. |
| `app/agent/prompts/parent_turn_analyzer.md` | Analyzer JSON schema | ✅ | |
| `app/agent/prompts/parent_present_value.md` | PRESENT_VALUE LLM context | ✅ | |
| `app/agent/prompts/parent_communication_style.md` | Premium tone reference | ✅ | |
| `app/agent/prompts/detect_segment.md` | Legacy segment classifier | ⚠️ | Dead path. |
| `app/agent/prompts/detect_start_intent.md` | First-message intent | ✅ | |
| `app/agent/prompts/detect_comment_intent.md` | Public-comment intent | ✅ | |
| `app/agent/prompts/summary.md` | Manager-notification summary | ✅ | PATCH 2: Georgian-only header. |
| `app/agent/policies/parent_sales_policy.md` ⭐ **PATCH 3** | 12-rule sales policy (role, conversation principle, age first, motivation discovery, price rule, value before CTA, decline, adult, tone, audience-aware adapters) | ✅ | |
| `app/agent/knowledge/camp_2026.yaml` | Authoritative camp facts | ✅ | |
| `app/agent/knowledge/company.yaml` | Company name + phone | ✅ | |
| `app/agent/knowledge/business_hours.yaml` | TZ + work hours + slot config | ✅ | |
| `app/agent/knowledge/adult_defaults.yaml` | Adult event placeholders | ⚠️ | Duplicated vs `data/prompts.py`. |
| `app/agent/knowledge/i18n/ka_months.yaml` | Georgian month names + stems | ✅ | |
| `app/agent/knowledge/audience_segments.yaml` ⭐ **PATCH 3** | 4 segments + 3 micro-segments | ✅ | Distilled from PDF. |
| `app/agent/knowledge/followup_strategy.yaml` ⭐ **PATCH 3** | 3 cadence stages + scenario followups | ✅ | Distilled from DOCX + sales_agent_prompt.md. |
| `app/agent/templates/parent/*.yaml` | 24 PARENT templates | ✅ | |
| `app/agent/templates/adult/*.yaml` | 11 ADULT templates | ⚠️ | Untouched by P2/P3. |
| `app/agent/templates/common/*.yaml` | UNCLEAR_ROUTING, ERROR_MESSAGE | ✅ | |
| `app/agent/templates/comments/*.yaml` | Public-comment replies | ✅ | |
| `app/agent/templates/notifications/*.yaml` | Manager email/SMS/WhatsApp bodies | ✅ | |
| `app/agent/templates/calendar/*.yaml` | Calendar event summary + description | ✅ | |
| `data/prompts.py` | Backwards-compat alias layer | ✅ | Still imported by ~10 modules. |
| `tests/conftest.py` ⭐ **PATCH 3 + P3-B** | Autouse fixtures pinning `USE_PARENT_LLM_ENGINE=False` AND `REDIS_ENABLED=False` for all tests | ✅ | |
| `tests/test_parent_llm_engine.py` ⭐ **P3-C** | Engine + tools + executor + sanitiser + summary + PATCH 1–8 (214 tests) | ✅ | |
| `tests/test_comment_flow.py` ⭐ **Comment Flow PATCH 1/2/3** | Hashtag matching + public-reply gate + private-reply routing + rich DMs (50 tests) | ✅ | |
| `tests/test_booked_state_polish.py` ⭐ **Booked State Memory Patch** | Memory-info short-circuit + booked-state CTA stripper + sanitiser polish (36 tests) | ✅ | |
| `tests/test_followup_scheduler.py` ⭐ **Follow-up Scheduler Patch** | Conversation-marker scan + cadence + skip rules + admin templates + platform routing (35 tests) | ✅ | |
| `tests/test_sentry_service.py` ⭐ **Basic Error Monitoring** | Safe no-op when SDK missing / DSN empty + 3 capture-point integration (30 tests) | ✅ | |
| `tests/test_admin_config.py` ⭐ **Admin Panel MVP** | Loader / hashtag routing / templates / validation / write API (29 tests) | ✅ | |
| `tests/test_comment_followup_logic.py` ⭐ **Comment Follow-up Logic Fix** | Eligibility + active-conv skip + 400 handling + retry preservation + success (27 tests) | ✅ | |
| `tests/test_kill_switch.py` ⭐ **Kill Switch Patch** | `AGENT_ENABLED` gate + canonical Georgian message + admin dashboard status (21 tests) | ✅ | |
| `tests/test_webhook_signature.py` ⭐ **Webhook Signature Patch** | HMAC enforcement + fail-open + constant-time compare + privacy (11 tests) | ✅ | |
| `tests/test_p2.py` | P2 regression (17) | ✅ | |
| `tests/test_pending_booking.py` | P1 regression (15) | ✅ | |
| `tests/test_parent_intent_router.py` | P0 regression (16) | ✅ | |
| `tests/test_parent_flow_analyzer_integration.py` | Phase 3.9 integration (9) | ✅ | |
| `tests/test_parent_turn_analyzer.py` | Analyzer unit (31) | ✅ | |
| `tests/test_parent_reply_composer.py` | Composer unit (23) | ✅ | |
| `tests/test_template_loader.py` (22), `test_prompt_loader.py` (37), `test_knowledge_loader.py` (19), `test_template_render_equivalence.py` (3) | Migration tests | ✅ | |
| `test_agent.py` (root) | Mocked end-to-end (63 checks) | ✅ | |
| `tools/sim_followup.py` ⭐ **Follow-up QA Patch** | 8-scenario follow-up scheduler local QA (mocked Meta send) | ✅ | `--case 24h|3d|7d|not_yet|booked|declined|kill_switch|messenger|all`. Safe to run against live `.env`. |
| `tools/manual_simulation_part10.py` | P0 manual sim | ✅ | Engine flag pinned off internally. |
| `tools/manual_simulation_pending_booking.py` | P1 manual sim | ✅ | Engine flag pinned off internally. |
| `tools/manual_simulation_p2.py` | P2 manual sim | ✅ | Engine flag pinned off internally. |
| `tools/manual_simulation_p3c.py` ⭐ **P3-C SAFE** | 10-turn engine smoke | ✅ | |
| `tools/manual_simulation_p3c_live_patch.py` ⭐ **PATCH 1** | 12-turn live transcript | ✅ | |
| `tools/manual_simulation_p3c_georgian_polish.py` ⭐ **PATCH 2** | 5-turn polish + CRM Georgian assertion | ✅ | |
| `tools/manual_simulation_p3c_audience_sales.py` ⭐ **PATCH 3** | 8-turn audience sales + source-leak guards | ✅ | |
| `tools/manual_simulation_p3c_live_sales_patch.py` ⭐ **PATCH 4** | 8-turn live sales transcript replay | ✅ | |
| `tools/manual_simulation_p3c_booking_commit.py` ⭐ **PATCH 5** | 8-turn live booking-commit replay | ✅ | |
| `tools/manual_simulation_p3c_exact_slot_availability.py` ⭐ **PATCH 6** | 5-scenario exact-slot + buffer-today replay | ✅ | |
| `tools/manual_simulation_p3c_final_qa_edges.py` ⭐ **PATCH 7** | 5-scenario time-change + decline + adult intent + wording polish | ✅ | |
| `tools/manual_simulation_p3c_final_wording_cleanup.py` ⭐ **PATCH 8** | 8-scenario static welcome + ineligible CTA + screen conditional | ✅ | |
| `tools/manual_simulation_comment_rich_dm.py` ⭐ **Comment Flow PATCH 3** | 5-scenario rich DM + YAML fallback + public-reply uniform text | ✅ | |
| `tools/verify_prompt_migration.py`, `verify_template_migration.py`, `verify_knowledge_migration.py` | Byte-identity migration verifiers | ✅ | 8/8 + 54/54 + ALL CHECKS |

---

## 10. Test Status (as of 2026-06-09)

```
python test_agent.py                       63→68 checks ✅
pytest tests/                              1615 passed, 0 failed (3 cosmetic warnings) — last clean run
python tools/sim_followup.py --case all    8/8 scenarios ✅ (mocked Meta send)
python tools/sim_adult_flow.py --scenario all   3/3 scenarios ✅ (mocked externals)
python tools/run_followup_tick.py --dry-run     hydrates Redis + lists due conversations

Baseline progression (effective, all green):
  1251 (Session 6 close)
   → +39 Session 7  = 1290
   →   +1 weekend-date stability fix = 1290
   → +30 Follow-up Test Mode = 1320
   → +13 Follow-up Redis Hydrate CLI = 1333
   → +17 Session 8  = 1350
   → +52 Admin Panel Multi-Event (Session 9) = 1402
   →  +9 Admin Panel UI Visibility fix = 1411
   → +31 Adult Live QA sold-out/link/partial title = 1442
   → +23 Adult Price Hallucination fix = 1465
   → +55 Comment → Specific Event Mapping (Session 10) = 1520
   → +73 Adult Event Subscription + Broadcast (Session 11) = 1593
   → +22 Instagram Webhook Signature + Payload Diagnostics = 1615

Scenario suite (real OpenAI, operator-approved), last full run 2026-06-05 post FULL Live QA Patch:
  python tools/scenario_runner_full.py --priority CRITICAL    22/22 ✅
    happy_path                             6/6  (100%) ✅
    booking                                3/3  (100%) ✅
    objection                              3/3  (100%) ✅
    comment                                1/1  (100%) ✅
    difficult                              6/6  (100%) ✅
    security                               3/3  (100%) ✅
  Model: gpt-4.1-mini (verified by runner stdout)

Full sweep (74 scenarios) ran 2026-06-02 pre-Live-QA-Polish:
  71/74 passed — SC-14 / SC-23 / SC-42 NORMAL/IMPORTANT-tier
  wording regressions (re-run each twice to confirm LLM
  stochasticity vs real regression). CRITICAL 22/22 + security
  4/4 + adult 3/3 preserved across every Session 2 + Session 3 + Session 4 + Session 5 + Session 6 patch.

Per-file pytest breakdown updated 2026-06-04 (1105 = 956 baseline + 149 from Session 3 patches):
  ├─ test_parent_llm_engine.py            215+ (P3-C SAFE + PATCH 1–8 + cap raised 32 KB → 34 KB by Multi-Busy patch)
  ├─ test_comment_flow.py                  50  (Comment Flow PATCH 1/2/3, public-reply assertion updated to emoji-free wording)
  ├─ test_adult_context_routing_fix.py     44  ⭐ (ADULT Context Routing Fix — 2026-06-02)
  ├─ test_agent_wording_cleanup.py         44  ⭐ (Agent Wording Cleanup Patch — 2026-06-03)
  ├─ test_booked_state_polish.py           36  (Booked State Memory Patch)
  ├─ test_followup_scheduler.py            35  (Follow-up Scheduler Patch)
  ├─ test_booking_availability_patch.py    32  ⭐ (Booking Availability Patch — 2026-06-03)
  ├─ test_openai_model_compatibility.py    32  (OpenAI Model Compatibility Patch — 2026-06-02)
  ├─ test_parent_turn_analyzer.py          31  (Phase 3.9 unit)
  ├─ test_sentry_service.py                30  (Basic Error Monitoring)
  ├─ test_admin_config.py                  29  (Admin Panel MVP)
  ├─ test_calendar_multi_busy_patch.py     29  ⭐ (Calendar Multi-Busy Check + Reschedule Wording — 2026-06-04)
  ├─ test_adult_live_qa_polish.py          28  (ADULT Live QA Polish Patch — 2026-06-02)
  ├─ test_comment_followup_logic.py        27  (Comment Follow-up Logic Fix)
  ├─ test_adult_scope_guard.py             22  (ADULT Off-Topic Guard — 2026-06-02)
  ├─ test_kill_switch.py                   21  (Kill Switch Patch)
  ├─ test_manager_email_wording.py         20  (Email Wording Patch)
  ├─ test_parent_reply_composer.py         19  (Phase 3.8 unit)
  ├─ test_knowledge_loader.py              19  (business_hours expectation updated 10:00–21:00 / 60 min)
  ├─ test_adult_tool_executor.py           18  (ADULT Engine — 2026-06-01)
  ├─ test_adult_llm_engine.py              18  (ADULT Engine — 2026-06-01)
  ├─ test_admin_form_field_completion.py   18  (Admin Field Completion)
  ├─ test_p2.py                            17  (P2 regression)
  ├─ test_expired_booking_memory_fix.py    17  (Expired Booking Memory Fix — 2026-06-02)
  ├─ test_parent_intent_router.py          16  (P0 regression)
  ├─ test_pending_booking.py               15  (P1 regression)
  ├─ test_adult_admin_config.py            14  (ADULT Engine + Default Min-Age Fix — 2026-06-02)
  ├─ test_admin_comment_routing.py         13  (Admin Panel MVP)
  ├─ test_redis_persistence.py             13  (P3-B Redis)
  ├─ test_prompt_loader.py                 13
  ├─ test_template_loader.py               12  (UTF-8 roundtrip test no longer asserts 🌿)
  ├─ test_notification_service.py          11  (Booking Notification QA)
  ├─ test_admin_panel.py                   11  (Admin Panel MVP + 0.49 bugfix)
  ├─ test_wording_polish.py                11  (Georgian Wording Polish; emoji-preserving tests inverted)
  ├─ test_webhook_signature.py             11  (Webhook Signature Patch)
  ├─ test_camp_facts_unification.py         9  (Config Unification)
  ├─ test_parent_flow_analyzer_integration.py   9
  ├─ test_adult_manager_notification.py     5  (ADULT Engine — 2026-06-01)
  └─ test_template_render_equivalence.py    3  (whitelist updated for Booking Availability + Wording Cleanup + Multi-Busy)
                                          ────
                                          1105 (Session 1: 802 + Session 2: +154 + Session 3: +149)

Manual simulations (all pass — 15 total):
  tools/manual_simulation_part10.py                       — P0
  tools/manual_simulation_pending_booking.py              — P1
  tools/manual_simulation_p2.py                           — P2
  tools/manual_simulation_p3c.py                          — P3-C SAFE (10 turns)
  tools/manual_simulation_p3c_live_patch.py               — PATCH 1 (12 turns)
  tools/manual_simulation_p3c_georgian_polish.py          — PATCH 2 (5 turns + CRM)
  tools/manual_simulation_p3c_audience_sales.py           — PATCH 3 (8 turns)
  tools/manual_simulation_p3c_live_sales_patch.py         — PATCH 4 (8 turns)
  tools/manual_simulation_p3c_booking_commit.py           — PATCH 5 (8 turns)
  tools/manual_simulation_p3c_exact_slot_availability.py  — PATCH 6 (5 scenarios)
  tools/manual_simulation_p3c_final_qa_edges.py           — PATCH 7 (5 scenarios)
  tools/manual_simulation_p3c_final_wording_cleanup.py    — PATCH 8 (8 scenarios)
  tools/manual_simulation_comment_rich_dm.py              — Comment Flow PATCH 3 (5 scenarios)
  tools/manual_simulation_redis_restart.py                ⭐ — P3-B restart safety (3 scenarios)
  tools/manual_simulation_admin_config.py                 ⭐ — Admin Panel MVP (5 scenarios)

Migration verifiers:
  tools/verify_prompt_migration.py         8/8 byte-identical
  tools/verify_template_migration.py       54/54 byte-identical
  tools/verify_knowledge_migration.py      ALL CHECKS PASSED
```

The 1 pytest warning is a `FutureWarning` from `google.api_core` about Python 3.10 support ending in 2026-10. Cosmetic.

---

## 11. External Services

**Meta (App / Page / Instagram):**
- App: AI Agent Test · App ID: `1678764780034040` · Status: **Published (Live mode)** ✅
- Page ID: `986476147893240` · IG Account: `17841470720714831` (`code.shelf` connected 2026-06-09)
- Verify token: `sityvis_akademia_secret_2026`
- Webhook subscribes: `messages`, `messaging_postbacks`, `messaging_optins`, `feed` (FB), `comments` + `messages` (IG)
- Graph API: v19.0 (one stale v18.0 in `notification_service.py`)
- ngrok tunnel URL changes on every restart — re-paste into Meta webhook config
- `pages_manage_engagement`: ⏳ App Review pending (needed for live public comment reply)
- Private replies (DM after comment) confirmed live ✅ — tester FB account received "Page responded privately"
- **Instagram inbound webhook signature: ✅ LIVE VERIFIED 2026-06-09.** Operator added `INSTAGRAM_APP_SECRET` (and IG access token) to local `.env`, restarted server, sent IG DM, observed `[webhook] signature accepted via instagram_app_secret` (no 403). Multi-secret `_verify_meta_signature` in `app/routes/webhook.py` tries Facebook (`META_APP_SECRET` / `MESSENGER_APP_SECRET`) first, falls back to `INSTAGRAM_APP_SECRET`.
- **Instagram local/live DM response: ✅ LIVE VERIFIED 2026-06-09.** Agent responded to IG DM via existing handler routing. Comment under Instagram post also passes signature.
- **Instagram Railway env: ⏳ pending.** Production deploy must include `INSTAGRAM_APP_SECRET` + `INSTAGRAM_ACCESS_TOKEN` (mirrors of the working local values). See §7 Priority 1.D.

**Admin Panel — multi-event + broadcast (Session 9-11):**
- ✅ Multi-event editor live at `/admin/programs/adult_events/events` (list / new / edit / delete + activate/deactivate toggle). Operator can manage unlimited events.
- ✅ Per-event fields: `title`, `status` (active/inactive/sold_out), `min_age` (≥13 floor), `date_text`, `location`, `price_text`, `price_gel`, `description`, `reservation_url`, `payment_terms`, `facebook_post_id` (optional), `tags` (CSV).
- ✅ Manual broadcast button: per-row "გაგზავნა subscribed მომხმარებლებთან" on the events list — renders a results page with sent/skipped/failed counts.
- ✅ Broadcast-after-save checkbox on the create/edit form (default off; checked → broadcast fires after successful save when event is active + has link).
- ✅ Broadcast LIVE VERIFIED 2026-06-09 by operator — newly created adult event successfully reached a subscribed user via Messenger DM.

**Google Sheets — `events` subscriber tab (Session 11):**
- ✅ New `events` tab (18 columns: Created At, Updated At, Platform, Sender ID, Name, Phone, Status, Consent, Consent At, Source Event ID, Source Event Title, Source Event Link, Age, Last Notified Event ID, Last Notified At, Notified Event IDs, Unsubscribe At, Notes). Created on first write — operator doesn't need to pre-provision.
- ✅ Upsert by `(platform, sender_id)`; partial updates preserve `Notified Event IDs` (the duplicate-prevention column).
- ✅ Unsubscribe deterministic phrase detection BEFORE the LLM in ADULT engine; `Unsubscribe At` stamped on opt-out.



**Google Calendar:**
- Booking calendar (where agent creates events): `BOOKING_CALENDAR_ID` env var. Falls back to `GOOGLE_CALENDAR_ID` when unset.
  - Current test value: `69c8153679d9a6a762557c63f1d7caf2c8b004fa78ef2efa15a178beba5286ee@group.calendar.google.com`
- Busy calendars (consulted for availability — multi-item FreeBusy): `BUSY_CALENDAR_IDS` env var, comma-separated. Falls back to `[booking_calendar_id()]` when unset. **⏳ NOT YET SET in live `.env`** — operator must add manager's side-calendar id(s) (e.g. „Nikoloz Analytics" calendar) and share each with the service account. Calendar Multi-Busy Check Patch (2026-06-04) is in code; it has no effect against side-calendar bookings until the operator populates this env var.
- Credentials: `./credentials.json` (service account `ai-agent-service@ai-agent-test-496312.iam.gserviceaccount.com`)
- Timezone: `Asia/Tbilisi`
- Business hours: **10:00–21:00** (work + business-hour cap aligned by Booking Availability Patch 2026-06-03), **60-minute** slots, 120 min buffer (today only).
- Last valid slot start is 20:00 (20:00–21:00); 21:00 is closing time. Half-hour requests rejected with `reason="half_hour_not_supported"`.
- Multi-calendar busy check fails CLOSED on any per-calendar permission error or HTTP failure — booking pauses + manager handoff while operator fixes calendar sharing.
- Booking writes (`book_slot` / `cancel_calendar_event` / `create_event`) target `BOOKING_CALENDAR_ID` only — never any busy-only calendar.
- Status: ✅ live tested for both legacy and P3-C engine path (PATCH 5); multi-busy logic unit-tested + awaits operator BUSY_CALENDAR_IDS population for end-to-end live verification.

**Google Sheets:**
- Spreadsheet ID: `1jwVD9Drnt7Xc3Q4nkD28BQCXSnwaGvjmVYdLzATl0oI`
- Service Account: `ai-agent-service@ai-agent-test-496312.iam.gserviceaccount.com`
- Leads tab columns: ID, Sender ID, Platform, Segment, Name, Phone, Child Age, Challenge, Deeper Concern, Desired Change, Event Interest, Consultation Booked, Conversation Summary, Status, Created At, Last Activity, Follow-up Sent
- All timestamps Asia/Tbilisi (`+04:00`) — P2 fix
- Status: ✅ live tested. `get_cold_leads` naive-vs-aware datetime bug resolved by Follow-up Scheduler Patch (2026-05-30).
- **Reschedule Sheets consistency: ✅ LIVE VERIFIED (2026-06-07/08, Session 8).** `sheets_service.mark_old_booking_rescheduled(sender_id)` targets the OLDEST row whose Status is `"Booked"` and relabels it `"Rescheduled"`. The newly appended booking row stays `"Booked"`. Operator screenshot confirmed exactly one active `"Booked"` row per sender after reschedule. Sheets write failure does NOT roll back the Calendar success.
- **Reschedule Calendar consistency: ✅ LIVE VERIFIED (2026-06-07).** Old Calendar event cancelled after the new event_id is verified (safe-ordering preserved from Session 6 Bug 9).

**Follow-up scheduler:**
- ✅ **PARENT follow-up live verified (2026-06-07/08).** Operator-edited Admin Panel template (`/admin/templates` → `followup_24h` / `followup_3d` / `followup_7d`) is read at send-time and delivered through Messenger via `tools/run_followup_tick.py` after the 120-second test-mode delay.
- **Hydrate CLI:** `python tools/run_followup_tick.py` scans `conversation:*` Redis keys → loads conversations into the fresh process's in-memory dict → runs scheduler tick once. `--dry-run` lists due conversations without sending. Enriched log: `[FOLLOWUP] scanning total=N parent=N with_marker=N` + `[FOLLOWUP] tick complete total=N due=N sent=N skipped=N`.
- **Test mode** (`.env`): `FOLLOWUP_TEST_MODE=true` + `FOLLOWUP_FIRST_DELAY_SECONDS=120` shortens the FIRST-due delay only. Stages 2 (72h) + 3 (168h) NEVER overridden.
- **Production mode:** `FOLLOWUP_TEST_MODE=false` (or unset) restores the 24h → 72h → 168h cadence exactly as before. APScheduler tick interval remains 1h in `app/main.py` regardless of mode.
- **ADULT follow-up scheduler still NOT supported.** Current scheduler short-circuits with `reason=non_parent_segment` for ADULT / UNCLEAR. Future task.

**OpenAI:**
- Model: **`gpt-4.1-mini`** (live, verified by the 2026-06-05 CRITICAL scenario runner output and unchanged through Sessions 7 + 8). `_build_completion_kwargs` in `openai_service.py` automatically sends `max_completion_tokens` for GPT-5.x / o1 / o3 / o4 families and `max_tokens` for legacy — operator can flip `OPENAI_MODEL` in `.env` without touching code. Boot log `[openai] model=gpt-4.1-mini token_param=max_tokens` confirms the shape.
- `USE_LLM_TURN_ANALYZER=true` (.env)
- `USE_LLM_COMPOSER=false` (.env)
- `USE_PARENT_LLM_ENGINE=true` (.env, live)
- `USE_ADULT_LLM_ENGINE=true` (.env, live — code default `True` since 2026-06-01)
- `ENABLE_PUBLIC_COMMENT_REPLY=true` (.env + code default; auto-activates once Meta App Review grants `pages_manage_engagement`)
- Billing active.

**Admin Panel adult events:**
- ✅ **Working as of 2026-06-05 Session 6.** Three independent paths now surface adult events to the live agent:
  1. **Dedicated multi-event editor** at `/admin/programs/adult_events/events` (list / new / edit / delete) — primary path going forward. Backed by `admin_config_service.save_adult_event` / `delete_adult_event`. Auto-id derivation from title; min_age defaults to 13 (floor enforced); preserves existing section metadata.
  2. **Section-level fallback** for the legacy form. An operator who fills section-level fields (description_short, price_text, price_gel, location, streams, payment_terms) via the existing `/admin/programs/adult_events` form will surface as a single fallback event automatically (`_build_fallback_event_from_section`). No migration required.
  3. **Direct YAML edit** of `data/admin_config/sections.yaml` `adult_events.events[]` block — for power users / bulk imports. Cache-free reload means no server restart needed.
- The live agent reads via `admin_config_service.get_adult_events()` → `get_active_adult_events(user_age=...)` on every turn. Privacy-safe debug log: `[admin_config] adult_events_loaded source=... raw=N fallback=N active=N titles=[...]`.
- Currently populated with one event (verified from sections.yaml: section-level "maroon 5 კონცერტი" → fallback event with min_age=13, location "ბორის პაიჭაძის სტადიონი", price 200 GEL, date "23 ივნისიი — დასაწყისი 19:00 საათზე"). Per-event `min_age` defaults to 13 (lowered from 18 on 2026-06-02 + floor enforced 2026-06-05); operator can raise per event.

**WhatsApp manager notification:**
- ✅ **Missing-credentials skip live verified (Session 7).** `_send_manager_whatsapp` early-returns with a single `[NOTIFICATION][WHATSAPP] Skipped: missing credentials (...)` log line when ANY of `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `MANAGER_WHATSAPP_NUMBER` is empty. No `httpx.post`, no traceback. Email channel stays independent.
- ⏳ **Live WhatsApp send still pending real credentials.** Operator action: populate `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_NUMBER_ID` + `MANAGER_WHATSAPP_NUMBER` once Meta WhatsApp Business credentials are issued for the production client.

**Redis:** ✅ deployed (P3-B Redis Migration 2026-05-22). `REDIS_URL` configured in live `.env`; conversations + manager-notified + processed-comment guards mirrored. 7d sliding TTL.
**Railway:** ⏳ not deployed. Single-worker target for v1.
**Sentry:** ⏳ code ready (Basic Error Monitoring Patch 2026-05-31) but `SENTRY_DSN` not yet present in live `.env` — safe no-op until operator adds DSN.
**Webhook signature:** ✅ enforced when `META_APP_SECRET` set (Webhook Signature Verification Patch 2026-06-01). Currently fail-open in production because `META_APP_SECRET` not in live `.env` — one warning per request until operator syncs.

---

## 12. How to Resume (run/deploy steps)

**Step 1 — `.env`** (already populated; if rebuilding, required keys):
```
OPENAI_API_KEY
META_APP_ID, META_APP_SECRET, META_PAGE_ID, INSTAGRAM_ACCOUNT_ID
MESSENGER_PAGE_ACCESS_TOKEN, MESSENGER_VERIFY_TOKEN
GOOGLE_SHEET_ID, GOOGLE_CALENDAR_ID, GOOGLE_SHEETS_CREDENTIALS_JSON, GOOGLE_CALENDAR_CREDENTIALS_JSON

# Calendar Multi-Busy Check (2026-06-04). Empty BOOKING_CALENDAR_ID falls
# back to GOOGLE_CALENDAR_ID. Empty BUSY_CALENDAR_IDS falls back to
# [BOOKING_CALENDAR_ID]. Production should set both so the agent reads
# busy events from every calendar where the manager blocks time.
BOOKING_CALENDAR_ID=
BUSY_CALENDAR_IDS=

# Email — Gmail SMTP (App Password required, NOT regular Gmail password)
MANAGER_EMAIL=manager@example.com
ENABLE_EMAIL_NOTIFICATIONS=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=<gmail-address>
SMTP_PASSWORD=<Gmail App Password>
SMTP_FROM_EMAIL=<gmail-address>

# Redis — restart-safe state
REDIS_URL=redis://localhost:6379   # empty = in-memory mode
REDIS_ENABLED=true
REDIS_TTL_SECONDS=604800

# Admin Panel — operator UI
ADMIN_PANEL_ENABLED=true            # false = /admin returns 404
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<local-secret>

# Engine flags
USE_LLM_TURN_ANALYZER=true
USE_LLM_COMPOSER=false
USE_PARENT_LLM_ENGINE=true          # set false to use legacy P0/P1/P2 flow

# Kill Switch (operator emergency disable)
AGENT_ENABLED=true                  # false → DM/comment/follow-up return safe offline message

# Webhook signature verification (Meta HMAC-SHA256)
VERIFY_WEBHOOK_SIGNATURE=true       # requires META_APP_SECRET to actually enforce
# META_APP_SECRET=…                 # already in [META APP] block above

# Sentry / Error Monitoring (optional)
SENTRY_DSN=                         # empty → Sentry disabled, safe no-op
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.0       # clamped to [0.0, 1.0]

# Comment public reply (auto-activates once Meta grants pages_manage_engagement)
ENABLE_PUBLIC_COMMENT_REPLY=true

# Identity / behaviour
COMPANY_NAME=სიტყვის აკადემია
PORT=8006
DEBOUNCE_SECONDS=5
MAX_WAIT_SECONDS=15
```

**Step 2 — Python.** Currently using system Python 3.10.11 — no venv.

**Step 3 — boot uvicorn:**
```
PYTHONIOENCODING=utf-8 python -m uvicorn app.main:app --reload --port 8006
```
Expected stdout (Windows users: set `PYTHONIOENCODING=utf-8` first):
```
✅ სიტყვის აკადემია AI Agent started
📚 Knowledge base loaded: 319 chars
🎭 Events loaded: 219 chars
⚙️ USE_LLM_TURN_ANALYZER=True
⚙️ USE_LLM_COMPOSER=False
⚙️ USE_PARENT_LLM_ENGINE=True
[redis] enabled=True url_configured=True
[redis] connected=True
⏰ Follow-up scheduler started
⏰ Comment follow-up scheduler started
INFO:     Application startup complete.
```

**Step 4 — ngrok tunnel:**
```
ngrok.exe http 8006
```
Copy the `https://*.ngrok-free.app` URL.

**Step 5 — Meta webhook update:**
Open `https://developers.facebook.com/apps/1678764780034040/webhooks/` → Callback URL: `<ngrok-https>/webhook` → Verify Token: `sityvis_akademia_secret_2026` → Click "Verify and Save". Subscribe IG to: `messages`, `messaging_postbacks`, `comments`.

**Step 6 — Health check:**
```
curl http://127.0.0.1:8006/health
# → {"status":"ok","company":"სიტყვის აკადემია"}
```

**Step 7 — full test sweep (recommended before any session change):**
```
python test_agent.py                                          # 63→68 checks ✅
pytest tests/                                                 # 1615 passed, 0 failed (last clean run 2026-06-09)
python tools/sim_followup.py --case all                       # 8/8 (mocked Meta send)
python tools/verify_prompt_migration.py
python tools/verify_template_migration.py
python tools/verify_knowledge_migration.py
python tools/manual_simulation_part10.py
python tools/manual_simulation_pending_booking.py
python tools/manual_simulation_p2.py
python tools/manual_simulation_p3c.py
python tools/manual_simulation_p3c_live_patch.py
python tools/manual_simulation_p3c_georgian_polish.py
python tools/manual_simulation_p3c_audience_sales.py
python tools/manual_simulation_p3c_live_sales_patch.py
python tools/manual_simulation_p3c_booking_commit.py
python tools/manual_simulation_p3c_exact_slot_availability.py
python tools/manual_simulation_p3c_final_qa_edges.py
python tools/manual_simulation_p3c_final_wording_cleanup.py
python tools/manual_simulation_comment_rich_dm.py
```

---

## 13. Next Session — what to pick up

**Current baseline (2026-06-09):** pytest 1615/0, test_agent.py 63→68 checks ✅, CRITICAL 22/22 (real-OpenAI sweep 2026-06-05). PARENT engine + Comment flow + Booking + Calendar + Sheets + Email + Redis + Admin Panel + Kill Switch + Sentry + Follow-up Scheduler + Webhook Signature Verification + Admin Panel Multi-Event + Comment → Specific Event Mapping + Adult Event Subscription + Broadcast (LIVE VERIFIED) + Instagram Webhook Signature (LIVE VERIFIED) all in place. **All previous deploy blockers are resolved** — the gating items now are: (1) generic `#event` comment → active adult events list fix (current live bug), (2) Railway deploy + env setup, (3) client production handover.

**Priority order:**

1. **Quick fixes batch (~1 hour total)** — see §7 Priority 1:
   - Add `.gitignore` (30 min) — verify nothing sensitive committed before any push
   - `requirements-dev.txt` with pytest + sentry-sdk + redis + fakeredis + python-multipart (15 min)
   - `notification_service.py:28` v18 → v19 hardcoded URL fix (5 min)
   - `mask_sender` shape standardization (10 min)
   - Sync live `.env` from `.env.example` — `META_APP_SECRET`, `AGENT_ENABLED`, `VERIFY_WEBHOOK_SIGNATURE`, `SENTRY_*` (5 min)

2. **Railway setup + Redis add-on + live deploy (~0.5 day)** — Procfile + always-on plan. Single worker for v1.

3. **Client credentials handover** — Gmail + WhatsApp Business + Meta App + Google service account swap from "AI Agent Test" infra. Kick off Meta Business Verification with the client on Day 1 (SLA can be 5+ business days).

4. **Adult LLM engine (P3-D) + live audit (P3-E) (~3-5 days)** — mirror PARENT engine pattern: `events.yaml`, ADULT tools, system prompt. Then first real Instagram smoke test on ADULT (SHOW_EVENTS → SEND_BOOKING).

5. **WhatsApp manager notification live test** — wire `MANAGER_WHATSAPP_NUMBER` + `WHATSAPP_TOKEN`; drive one booking end-to-end.

6. **App Review — `pages_manage_engagement`** — submit on the client's production App so the already-on `ENABLE_PUBLIC_COMMENT_REPLY=True` actually fires for public replies.

7. **Legacy-fallback admin migration (0.5 day)** — `parent_turn_router`, `parent_reply_composer`, `parent_turn_analyzer` still read `camp_2026.yaml` directly. Engine is on in live, so they're dormant. Needed only before any future flag flip.

8. **Live monitoring confirmation** — after Railway deploy: verify `[followup] sent` log lines fire on the 24h/72h/168h cadence; verify `[webhook] signature ok` lines once `META_APP_SECRET` is set; verify Sentry receives test errors once `SENTRY_DSN` is set.

**Total realistic estimate: ~1 day focused work (quick fixes + Railway) + external Business Verification SLA + P3-D/E for ADULT.**

---

**End of HANDOFF.** A new session can read top-to-bottom and immediately know: where we are, what works, what's broken, what's next, and how to start.
