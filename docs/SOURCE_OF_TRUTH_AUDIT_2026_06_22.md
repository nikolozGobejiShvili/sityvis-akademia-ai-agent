# 🔍 SOURCE-OF-TRUTH & RUNTIME-PATH AUDIT — სიტყვის აკადემია AI Sales Agent (2026-06-22, READ-ONLY)

> 🔄 **FORWARD POINTER (2026-06-23):** This is a dated 2026-06-22 snapshot. Current baseline is **2879 / 0 / 28** and the **Reasoning Layer is implemented (Phase 1, gated, default OFF)** — `app/reasoning/reasoning_layer.py` + flag `USE_REASONING_LAYER` (deterministic, metadata-only, no LLM). Any „Reasoning Layer not present / not implemented" statement in the sibling living docs' 2026-06-22 versions is superseded. Authoritative current state: `HANDOFF.md` „✅ CURRENT STATE (2026-06-23)" / `CLAUDE.md` / `REVIEW_PACK.md`. Next task: **Prompt Slimming**. **Production still NOT green.**

> **READ-ONLY audit.** No code, file, prompt, or YAML was changed; nothing was deleted; nothing was deployed. **Production is NOT green.** Every recommendation below is a *proposal* to be executed in a later, separately-gated task. Where a source mapper said `UNVERIFIED`, that uncertainty is carried forward verbatim and must NOT be upgraded to a "delete".
>
> ✅ **Adversarial verification (2026-06-22):** an independent read-only pass re-checked the 7 highest-stakes claims (the live fact-drift bug, the camp canonical/bypass readers, the legacy-fallback classifications, the conftest engine-OFF pinning, the two stale CLAUDE.md statements, the state-persistence split, the sanitiser safety/cosmetic split) — **7/7 confirmed against code; nothing marked ARCHIVE/LEGACY_OFF/DELETE_LATER is reachable on the live engine path.** One correction folded in below: `FORBIDDEN_PHRASE_REPLACEMENTS` is **184** entries (the audit first estimated ~95 — an undercount that does not change any decision). It also confirmed `detect_segment.md`'s only caller (`OpenAIService.generate_reply`) is never instantiated → genuinely unreached (LEGACY_OFF).
>
> ✅ **CLEANUP PROGRESS (2026-06-22, Tasks 1 → 5A-3 all DONE, test-gated, suite 2802/0):** the live source-of-truth fixes this audit recommended are complete — stream-date prompt literals removed (Task 1, → `get_camp_info`); Sunday-School „July" → `sections.yaml` (Task 2) + Admin-Panel field preservation (Task 3); manager phone unified on `get_manager_phone()` (Task 4); camp age band (all 6 live readers) → `get_camp_age_bounds()` (5A-1 + 5A-2); post-booking facts → `get_camp_facts()` + comment rich DM verified admin-first (5A-3). **`parent_flow` now has ZERO direct `camp_2026.yaml` reads; no LIVE PRIMARY camp-fact reader bypasses the canonical source.** Still open (behavioural / future, not in this audit's fact scope): router normalization + Latin-Georgian transliteration, adult-events source cleanup, the `price_text 5000` vs `price_gel 4999` operator-data mismatch, Sunday-School panel-UI, legacy archival. The canonical (dated) verification sweep tracks the same progress; a non-dated duplicate is pending docs cleanup (deletion needs approval).

---

## 1. Executive summary

**The 5–8 most important truths**

1. **The live DM brain is the LLM engine, not the state machine.** With `USE_PARENT_LLM_ENGINE=true` (set in `.env`) and `USE_ADULT_LLM_ENGINE=true` (code default; `.env` omits it), `parent_flow.handle` / `adult_flow.handle` run the LLM engine FIRST. The legacy P0/P1/P2 state machine (`parent_turn_router` / `parent_reply_composer` / `parent_turn_analyzer`) and the legacy `adult_flow` state machine are reached **only** when the engine returns `""` or raises. They are live-as-fallback, cold, and **must not be deleted** (CLAUDE.md forbids it).

2. **The single biggest bug-factory is `parent_flow.handle`'s ~15-deep ordered chain of deterministic pre-engine interceptors.** Each owns a slice of Georgian-substring intent, runs BEFORE the LLM, and short-circuits. **Order is load-bearing** (CLAUDE.md repeatedly says „ნუ გადაიტან" / don't reorder). Every live fix to date was a new guard bolted onto this chain. This is where shadow/overlap risk lives.

3. **The single canonical camp-fact chokepoint is `admin_config_service.get_camp_facts()`** — an admin-FIRST per-field merge of `data/admin_config/sections.yaml` (`summer_camp`) OVER `app/agent/knowledge/camp_2026.yaml` (fallback). **CANONICAL = `sections.yaml`.** Today `camp_2026.yaml` AGREES with it (2150 / 9–17 / „ამბასადორი კაჭრეთი" / 3 streams / `tinyurl.com/36jcae8z`), so there is **no live conflict today** — but multiple readers **bypass** the chokepoint and read `camp_2026.yaml` directly, so an Admin-Panel edit will silently NOT reach them.

4. **One genuine LIVE fact-drift bug exists in a prompt:** `system_parent_v2.md:293` HARDCODES the three stream dates (`23–29 ივნისი / 5–11 ივლისი / 14–20 ივლისი`). This is on the live path, bypasses both `sections.yaml` and the camp-stream date-filter (`is_camp_stream_visible`). Otherwise `system_parent_v2.md` is fact-clean and `system_adult_v1.md` is fully fact-clean.

5. **`sanitise_response_wording`'s `FORBIDDEN_PHRASE_REPLACEMENTS` table (184 entries, verified) is ~90% cosmetic Georgian grammar/wording rewrites.** The genuine SAFETY guards (fake-booking, never-2150-for-events, ineligible-age, privacy-notice, booked-CTA strip) live in SEPARATE functions and must STAY deterministic. The cosmetic majority is the strongest single candidate to move into the prompt.

6. **State is split across Redis-mirrored `Conversation`/`Lead` AND ~10 per-process module-level dicts/sets.** Only `manager_notified_for_conversation` is Redis-mirrored; `_sunday_school_notified_senders`, slot caches, `book_consultation_success_for_conversation`, `selected_events`, etc. are in-memory only. **Single-worker deploy is mandatory** — multiple Railway workers would race these dicts AND double-fire the APScheduler follow-up DMs.

7. **`pytest` greenness ≠ live-path correctness.** The autouse `conftest.py` fixtures pin BOTH engines OFF, so the bulk suite exercises the LEGACY deterministic state machine. The ONLY harness that runs the real live LLM path is `tools/scenario_runner_full.py` (74 scenarios, real OpenAI, engine forced ON). Treat **that** (not bulk pytest) as the simplification safety gate.

8. **Two doc-drift confusion sources are confirmed:** (a) CLAUDE.md says the follow-up scheduler "Sender NOT yet wired to PATCH 3 markers" — this is **STALE/WRONG**; it IS wired (`main.py:70-84`, `followup_service` reads `last_bot_message_at`/`followup_stage`). (b) CLAUDE.md claims `.env` sets `FOLLOWUP_TEST_MODE=true`/`FIRST_DELAY=120` "live" — `.env` does NOT set them, so live cadence is PRODUCTION 24h/72h/168h.

**Biggest single confusion source:** the **two-parent-prompt illusion** combined with the **15-deep interceptor chain**. `system_parent.md` (legacy, carries the full hardcoded fact set) and `system_parent_v2.md` (live, carries stream dates at line 293) look like "two parents"; only v2 is live. Meanwhile every live behaviour change has accreted as another order-sensitive Georgian-substring guard in `parent_flow.handle`, each re-implementing name/phone/intent parsing.

**Where to simplify first (one paragraph):** Start with **zero-code Phase 1** — consolidate the duplicated camp facts so `sections.yaml` is provably the only source, fix the two stale CLAUDE.md statements, and identify (do not yet remove) the dormant/empty files. The single highest-value *fact* fix is removing the literal stream dates from `system_parent_v2.md:293` and routing the direct `camp_2026.yaml` readers through `get_camp_facts()`. Only after `scenario_runner_full` CRITICAL stays green should you touch the interceptor chain.

**„Minimal viable agent" north star.** The leanest defensible target is:
> **one parent system prompt** (`system_parent_v2`, slimmed of facts) + **`knowledge`/`admin_config` as the single source of truth** (`get_camp_facts` / `get_active_adult_events` / `get_manager_phone` only) + **a SMALL set of hard-safety deterministic guards** (booking-commit, fake-booking guard, ineligible-age, privacy/PII, kill-switch, manager-number disclosure) + **the LLM owning language, name/phone extraction, intent and routing** (one `normalize_text_for_intent` + a thin `high_priority_intent_router`, instead of ~15 substring interceptors and 11 scattered `[ა-ჰ]` gates) + **`scenario_runner_full.py` (74 scenarios, CRITICAL set) as the regression net** that survives every guard→prompt migration.

---

## 2. Runtime file inventory

Legend — **live-path?**: YES = on the `USE_*_LLM_ENGINE=true` DM path; FALLBACK = reached only on engine fail/empty; COMMENT = comment pipeline (not DM); OPERATOR = admin/broadcast; NO = dead/empty/doc/test. **Rec.**: KEEP_PRIMARY / KEEP_FALLBACK / CANONICAL / CONSOLIDATE / MIGRATE_TO_LLM / LEGACY_OFF / DOC_ONLY / ARCHIVE / TEST_ONLY.

### 2.1 Code — live DM spine

| path | type | runtime-loaded? | loaded-by file:function | live-path? | controls | duplicates/conflicts | recommendation | risk-if-removed | migration-needed |
|---|---|---|---|---|---|---|---|---|---|
| `app/routes/webhook.py` | code | yes | Meta POST → `_process_payload` → `message_buffer.buffer_message` (:335) → `conversation_service.process_message` (:357) | YES (entry) | DM ingress + comment ingress (`handle_comment` :412, separate) | none | KEEP_PRIMARY | total outage | Cleanup-only: delete `[webhook_debug]`/`[comment_debug]` temp log blocks (269-299, 384-399) |
| `app/services/message_buffer.py` | code | yes | `webhook.py:335` | YES | per-sender 5–15s debounce, joins fragments | none | KEEP_PRIMARY | 3× duplicate replies to fragmented typing | none (single-worker); multi-worker → shared Redis buffer |
| `app/services/conversation_service.py` (`process_message`/`_process_message_impl`) | code | yes | `webhook.py:357` | YES (the only DM router) | kill-switch, get/create conversation, segment routing, dispatch, Redis write-through | `_classify_segment`+override+booked-guard are 3 interacting layers | KEEP_PRIMARY | no DM router | none; chokepoint to simplify later |
| `_classify_segment`/`_is_parent_consultation_intent`/`_is_registration_link_request`/`_maybe_identity_reply` | code | yes | within `_process_message_impl` | YES | deterministic Georgian keyword classify (4 English camp stems only) | „პროგრამა" deliberately excluded | KEEP_PRIMARY + MIGRATE_TO_LLM candidate | substring misfire | LLM intent extraction at this chokepoint |
| `app/flows/parent_flow.py` (`handle`) | code | yes | `conversation_service.py:516` | YES | ~15 ordered pre-engine interceptors → engine → ~13 post-engine sanitizers | order load-bearing; densest overlap zone | CONSOLIDATE | lose deterministic booking/handoff | route name/phone/intent to LLM tools; keep true-safety guards |
| `app/agent/llm/parent_llm_engine.py` (`run_parent_llm_turn`) | code | yes | `parent_flow._run_llm_engine_safely` (engine flag true) | YES (the brain) | system_parent_v2 + context + 5-iter tool loop | reads `camp_2026.yaml` directly (1924/2194) for prompt age band | KEEP_PRIMARY | PARENT degrades to legacy | route age band via `get_camp_facts` |
| `sanitise_response_wording` + `FORBIDDEN_PHRASE_REPLACEMENTS` | code | yes | `run_parent_llm_turn` post-chain | YES | 184 literal rewrites + `_strip_concern_wording` | ~90% cosmetic grammar | MIGRATE_TO_LLM (cosmetic majority) | minor wording regressions | move cosmetic rules into `system_parent_v2.md`; keep `_strip_concern_wording` (PII-preamble) |
| `_capture_turn_facts`/`_suppress_redundant_age_question`/`_strip_mid_conversation_greeting` | code | yes | `run_parent_llm_turn` | YES | pre-turn age/phone capture; anti-repeat | none | KEEP_FALLBACK | mild repetition | optional → prompt, low risk |
| `app/agent/tools/parent_tool_executor.py` (`ParentToolExecutor`) | code | yes | `run_parent_llm_turn` tool loop | YES (security boundary) | get_camp_info, slots, book_consultation, manage/cancel, request_manager_callback, save_lead_info, switch_to_adult_flow; age/phone/FreeBusy validation, fail-CLOSED | owns `manager_notified_for_conversation`, `book_consultation_success_for_conversation` | KEEP_PRIMARY / CANONICAL | false bookings / no side-effect gating | NEVER move validation to prompt |
| `app/agent/llm/adult_llm_engine.py` (`run_adult_llm_turn` + `sanitise_adult_response`) | code | yes | `adult_flow.handle` (flag true) | YES (adult brain) | unsubscribe → parent-switch → delivery → subscription → offtopic → named-event → tool loop; NO Calendar | sanitiser cosmetic like PARENT | KEEP_PRIMARY; sanitiser COSMETIC → MIGRATE_TO_LLM | ADULT degrades | move cosmetic entries to prompt |
| `app/agent/tools/adult_tool_executor.py` (`AdultToolExecutor`) | code | yes | `run_adult_llm_turn` tool loop | YES | 6 adult tools (no Calendar); `get_active_adult_events` (:299); manager phone (:641) | none | KEEP_PRIMARY | ADULT side-effects ungated | none |

### 2.2 Code — legacy / fallback (live only on engine fail)

| path | type | runtime-loaded? | loaded-by | live-path? | controls | duplicates/conflicts | recommendation | risk-if-removed | migration-needed |
|---|---|---|---|---|---|---|---|---|---|
| `app/flows/parent_flow._handle_impl` + `parent_reply_composer` + `parent_turn_analyzer` + `parent_turn_router` | code | imported at module top; called only on engine fallback | `parent_flow.py:403` + legacy calls (4661/4676/4926/5832/5928); `conversation_service.py:814` (`reset` uses `parent_turn_router`) | FALLBACK (cold, NOT dead) | legacy PARENT compose/analyze/route | reads `camp_2026.yaml` directly | KEEP_FALLBACK / LEGACY_OFF | PARENT breaks on OpenAI failure | ARCHIVE only after engine reliability proven via prod logs; CLAUDE.md forbids removal now |
| `app/flows/adult_flow.py` (state machine) | code | yes (engine-first) | `conversation_service.py:518` | FALLBACK | START/SHOW_EVENTS/ANSWER_QUESTIONS/SEND_BOOKING + `_maybe_handle_adult_global_intent` | none | KEEP_FALLBACK | ADULT outage on engine failure | "never live-tested end-to-end"; prove with logs before archive |
| `app/services/openai_service.py` (`generate_response`/`detect_*`/`generate_summary`) | code | yes | legacy composer + classifiers; `parent_flow.py:4874` (`detect_start_intent`); `generate_summary` uses inline `_SUMMARY_SYSTEM_MESSAGE` | FALLBACK + classifiers | legacy reply generation, segment/start-intent/comment-intent detection, CRM summary | `SUMMARY_PROMPT` alias imported but not used by `generate_summary` | KEEP_FALLBACK | legacy + classifier outage | none |

### 2.3 Prompts (`app/agent/prompts/*.md`)

| path | type | runtime-loaded? | loaded-by | live-path? | controls | duplicates/conflicts | recommendation | risk-if-removed | migration-needed |
|---|---|---|---|---|---|---|---|---|---|
| `app/agent/llm/prompt_loader.py` (`load_prompt`) | code | yes | the only prompt loader (engines + `data/prompts.py`) | YES | byte-identical cached read | none | CANONICAL / KEEP_PRIMARY | no prompts | none |
| `system_parent_v2.md` | prompt | yes | `parent_llm_engine.py:1922` `.format(company_name,age_min,age_max)` | YES (canonical parent) | 451 lines, CRITICAL rules; forces `get_camp_info` for facts | **line 293 HARDCODES 3 stream dates (LIVE fact-drift bug)** | KEEP_PRIMARY but MUST SLIM dates | none (get_camp_info supplies streams) | delete literal dates at :293; separately trim 451-line bloat (gated) |
| `system_adult_v1.md` | prompt | yes | `adult_llm_engine.py:2219` `.format(company_name)` | YES (canonical adult) | tone/behaviour | fact-clean (only `9–17` at :167 = parent-switch trigger) | KEEP_PRIMARY | adult brain | none |
| `system_parent.md` | prompt | yes (alias) | `data/prompts.SYSTEM_PROMPT_PARENT` → `openai_service` (legacy) | FALLBACK | legacy parent role | **HARDCODES full fact set lines 4-9** (2150/9-17/კაჭრეთი/streams/tinyurl/558 67 47 33) | LEGACY_OFF | matters only if flag flips false | strip facts before any flag flip OR retire legacy composer |
| `system_base.md` | prompt | yes (alias) | `data/prompts.SYSTEM_PROMPT_BASE` → legacy `_build_system_prompt` | FALLBACK | brand voice/grammar | none (fact-clean) | LEGACY_OFF / KEEP_FALLBACK | tone only | none |
| `system_adult.md` | prompt | yes (alias) | `SYSTEM_PROMPT_ADULT` → `adult_flow` fallback (449/466) | FALLBACK | legacy adult role; bans fact invention | none (fact-clean) | LEGACY_OFF / KEEP_FALLBACK | tone only | none |
| `parent_turn_analyzer.md` | prompt | yes | `parent_turn_analyzer.py:143` | FALLBACK (analyzer path) | JSON intent classifier; consumes injected facts, forbidden to copy | none (fact-clean) | KEEP_FALLBACK | classifier on legacy path | none |
| `parent_present_value.md` | prompt | yes (alias) | `PARENT_PRESENT_VALUE_CONTEXT` → `openai_service.generate_parent_value_response` | FALLBACK | discovery composer; line 18 bans price/link/date | none (fact-clean by design) | LEGACY_OFF | legacy discovery | none |
| `parent_communication_style.md` | prompt | **no runtime caller** | only its own docstring + CLAUDE.md/HANDOFF + `test_template_render_equivalence.py:96` | NO (DEAD) | tone reference; self-declares "not sent" (:4) | none | DOC_ONLY / ARCHIVE | only breaks byte-identity test (update it) | move to `docs/` (no behavioural impact) |
| `detect_segment.md` | prompt | yes (alias) | `DETECT_SEGMENT` → `openai_service.detect_segment` | LEGACY (LLM fallback to deterministic classifier) | segment label | none (keyword lists) | LEGACY_OFF / TEST_ONLY-ish | classifier fallback | **UNVERIFIED** whether any live caller still hits `detect_segment` — verify before archive |
| `detect_start_intent.md` | prompt | yes (alias) | `START_INTENT_DETECT` → `openai_service.detect_start_intent`; `parent_flow.py:4874` | FALLBACK-ish (routing label) | first-msg intent | none (fact-clean) | KEEP_FALLBACK | routing | none |
| `detect_comment_intent.md` | prompt | yes (alias) | `COMMENT_INTENT_PROMPT` → `comment_service.detect_comment_intent`; `webhook.py:518` | COMMENT (fallback to deterministic `is_interest_intent`) | comment INTERESTED/NOT | none (fact-clean) | KEEP_FALLBACK | comment classify | none |
| `summary.md` | prompt | imported alias only | `SUMMARY_PROMPT=_p('summary')` — `generate_summary` uses inline `_SUMMARY_SYSTEM_MESSAGE`, NOT this | NO (likely orphaned) | CRM summary (not used) | none (fact-clean) | ARCHIVE / DOC_ONLY | none | **UNVERIFIED**: grep `SUMMARY_PROMPT` consumers beyond the import before deleting |

### 2.4 Policies (`app/agent/policies/*.md`)

| path | type | runtime-loaded? | loaded-by | live-path? | controls | duplicates/conflicts | recommendation | risk-if-removed | migration-needed |
|---|---|---|---|---|---|---|---|---|---|
| `parent_sales_policy.md` | policy doc | **NO** (no Python loader; grep `sales_policy`/`policies` over `app/**.py` = no matches) | none | NO (reference doc) | behaviour/tone (205 lines) | header FALSELY claims "engine reads selected lines" | DOC_ONLY / KEEP | none | fix misleading header (no runtime read) |
| `adult_sales_policy.md` | policy doc | **NO** | none | NO (reference doc) | behaviour/tone (364 lines); `9–17` at :147/:259 = camp-redirect wording | header may imply runtime read | DOC_ONLY / KEEP | none | fix header |

### 2.5 Knowledge & admin-config YAML / data / templates

| path | type | runtime-loaded? | loaded-by | live-path? | controls | duplicates/conflicts | recommendation | risk-if-removed | migration-needed |
|---|---|---|---|---|---|---|---|---|---|
| `data/admin_config/sections.yaml` | yaml | yes | `admin_config_service.get_camp_facts` / `get_active_adult_events` / `build_section_dm` / sunday_school | YES (CANONICAL) | camp facts, sunday_school, adult_events[] | admin-wins merge over `camp_2026.yaml` | CANONICAL | no admin overrides | — |
| `app/agent/knowledge/camp_2026.yaml` | yaml | yes (fallback + direct) | `get_camp_facts` fallback; **DIRECT** by `parent_llm_engine` (1924/2194), `comment_service` (194), `parent_turn_router._camp` (118), `parent_reply_composer` (180), `parent_turn_analyzer` (146) | YES (fallback) + direct readers serve potential STALE | camp facts fallback + prompt age band | direct readers bypass `get_camp_facts` → invisible to admin edits | KEEP fallback; CONSOLIDATE direct readers | brand-new deploy loses facts | swap direct `load_knowledge('camp_2026')` → `get_camp_facts()` |
| `app/agent/knowledge/business_hours.yaml` | yaml | yes | `calendar_service.py:30`; `parent_flow.py:3881` (buffer) | YES (CANONICAL) | 10:00–21:00, slot 60, buffer 120 | `data/admin_config/business_hours.yaml` is a hand-synced display mirror | CANONICAL | booking hours lost | — |
| `data/admin_config/business_hours.yaml` | yaml | **not read by booking** | operator display only | OPERATOR (mirror) | display copy (comment: "Keep in sync manually") | duplicate of canonical | DOC_ONLY duplicate | none functional | operator hazard: edits don't change bookings |
| `app/agent/knowledge/i18n/ka_months.yaml` | yaml | yes | `admin_config_service._adult_event_month_stems` / `_find_month` | YES | Georgian month stems for date parsing | none | CANONICAL / KEEP_PRIMARY | date parsing breaks | — |
| `data/events.txt` | data | yes (loaded, empty) | `config.py:170` (`settings.EVENTS`); `conversation_service.py:344` (ContentRepository); parsed by `comment_service._parse_events_blocks()` → always `[]` | NO (dead/empty) | empty adult-event template | duplicate of `sections.yaml` adult_events[] (always preempted) | ARCHIVE / keep file as template | `config.EVENTS` read needs a guard | mark DOC_ONLY/template |
| `data/knowledge_base.txt` | data | yes (loaded, empty) | `conversation_service.py:343`; `config.py:166`; only `followup_service.py:190` reads → empty | NO (dead/empty) | empty placeholder | none | ARCHIVE / DOC_ONLY | read-crash if removed | keep file, mark template |
| `app/agent/knowledge/manager_contacts.yaml` | yaml | partial | `get_manager_phone()` chain | YES (one link) | `manager_phone`/`phone` (currently no phone key); `email_placeholder`/`whatsapp_placeholder` = display only | placeholders look editable but aren't the send source | CONSOLIDATE (phone chain); DOC_ONLY placeholders | none | — |
| `app/agent/knowledge/company.yaml` | yaml | yes | `get_manager_phone()` chain; `get_camp_facts` phone | YES | phone `558 67 47 33` (de-facto canonical) | one of 3 phone copies | CANONICAL (phone) | manager number lost | — |
| `app/agent/knowledge/audience_segments.yaml` | yaml | yes | distilled knowledge | supporting | 4 segments | none | KEEP_PRIMARY | — | — |
| `app/agent/knowledge/followup_strategy.yaml` | yaml | yes | matches `followup_service._FOLLOWUP_CADENCE` | supporting | cadence stages | none | KEEP_PRIMARY | — | — |
| `app/agent/knowledge/adult_defaults.yaml` | yaml | legacy | placeholder words for empty `events.txt` path; mirrored in `data/prompts.ADULT_DEFAULT_*` | NO (legacy) | placeholder words | tied to dead events.txt path | LEGACY_OFF | low | **UNVERIFIED** whether read on live ADULT engine path |
| `data/admin_config/templates.yaml` | yaml | yes | `build_section_dm` (sunday_school_comment_dm etc.) | COMMENT | comment DM templates | sunday_school fields empty in sections.yaml → renders blank | DOC_ONLY | blank DMs | populate fields |
| `data/prompts.py` | code (alias) | yes (import) | `conversation_service.py:12` (UNCLEAR_ROUTING); `parent_flow.py:35-62`; `adult_flow.py:8-27` | YES (alias layer) | re-exports prompt/template loads | NOT a fact source (only `ADULT_DEFAULT_*` literals) | KEEP_PRIMARY (back-compat) | ImportError across flows | — |

### 2.6 Feature flags (`app/config.py`, read once at import)

| flag | code default | `.env` | live effect | recommendation |
|---|---|---|---|---|
| `USE_PARENT_LLM_ENGINE` (:307) | False | **true** | LIVE = LLM engine; OFF → legacy parent state machine is only path | KEEP_PRIMARY; legacy = KEEP_FALLBACK |
| `USE_ADULT_LLM_ENGINE` (:322) | **True** | **omitted** → True | LIVE = adult engine | KEEP_PRIMARY; DOC fix: CLAUDE.md wrongly lists `.env=true` |
| `LIVE_BROADCAST_ENABLED` (:380) | False | false | OFF = DRY-RUN fan-out (safety net) | KEEP_PRIMARY; do not flip |
| `ADMIN_PANEL_ENABLED` (:360) | False | True | /admin routes; NOT kill-switch gated (intentional) | KEEP_PRIMARY (operator) |
| `AGENT_ENABLED` (:371) | True | omitted → True | single emergency stop | CANONICAL |
| `FOLLOWUP_ENABLED` (:240) | True | true | hourly follow-ups | KEEP_PRIMARY |
| `FOLLOWUP_TEST_MODE`/`FIRST_DELAY` (:241-242) | False/0 | **omitted** → prod cadence | CLAUDE.md WRONGLY says `.env=true/120` | DOC_ONLY fix; TEST_ONLY knobs |
| `REDIS_ENABLED` (:352) | True | true | persistence | KEEP_PRIMARY (infra) |
| `VERIFY_WEBHOOK_SIGNATURE` (:389) | True | true | HMAC (fail-open if secret empty) | KEEP_PRIMARY (infra) |
| `ENABLE_PUBLIC_COMMENT_REPLY` (:341) | True | true | comment flow only | KEEP_PRIMARY (comment) |
| `ENABLE_EMAIL_NOTIFICATIONS` (:212) | True | true | booking email | KEEP_PRIMARY |
| `SENTRY_DSN` (:394) | empty | — | disabled | DOC_ONLY (off) |
| `USE_LLM_COMPOSER` (:283) | False | false | DEAD (never on) | LEGACY_OFF / ARCHIVE candidate |
| `USE_LLM_TURN_ANALYZER` (:294) | False | true | inert while engine ON (legacy-only) | LEGACY_OFF effectively; **UNVERIFIED** if ever reached live |

### 2.7 Tests, tools, docs

| path family | type | runtime? | live-path? | recommendation |
|---|---|---|---|---|
| `tests/conftest.py` (autouse) | test | n/a | pins BOTH engines OFF, Redis OFF, prod cadence, blocks SMTP/Meta | KEEP_PRIMARY; **owner caveat: green pytest ≠ live path** |
| `tools/scenario_runner_full.py` (74 scenarios, `force_engine_on()`, real OpenAI) | tool | n/a | the ONLY live-path regression net (CRITICAL set = go/no-go) | KEEP_PRIMARY / CANONICAL net |
| `test_parent_llm_engine.py` (247) / `test_adult_llm_engine.py` | test | engine ON | covers live engines | KEEP_PRIMARY |
| ~17 dated guard-pinned files (`test_*_2026_06_*`, `test_redteam_*`, `test_p0_*`, `test_p1_*`, `test_name_capture*`, `test_wording_polish`, `test_state_reuse*`, `test_age_extraction*`, `test_ineligible_young_age_p0`) | test | n/a | pinned to specific deterministic guards | TEST_ONLY; retire in lockstep when matching guard migrates |
| loader/infra tests (`test_template_loader`, `test_knowledge_loader`, `test_prompt_loader`, `test_template_render_equivalence`, `test_comment_flow`, `test_admin_*`, `test_redis_persistence`, `test_notification_service`, `test_kill_switch`, `test_sentry_service`, `test_webhook_signature`) | test | n/a | durable contracts | KEEP_PRIMARY |
| `docs/LIVE_TEST_CHECKLIST_2026_06_22.md` + `docs/FULL_TEST_SCENARIOS_2026_06_22.md` | doc | n/a | CURRENT (today); base + extension | KEEP_PRIMARY both; optionally merge |
| `docs/FULL_AGENT_TEST_SWEEP_REPORT.md` (2026-06-14) | doc | n/a | superseded diagnostic | ARCHIVE / DOC_ONLY (keeps deferred-bug record) |
| `docs/REDTEAM_CONVERSATIONS.md` + `REDTEAM_FINDINGS.md` + `REDTEAM_FULL_SYSTEM_AUDIT.md` | doc | n/a | historical audit logs (mostly FIXED) | ARCHIVE / DOC_ONLY; consolidate into one history file |

---

## 3. Deterministic-guard ORDER map (`parent_flow.handle`)

This is the **#1 confusion source**. Every guard below is **deterministic Georgian-substring** (none call the LLM), runs **before** the LLM engine, and returns early on a hit. **Order is load-bearing.** The LLM is the LAST resort.

**Pre-engine interceptors (always run, in this exact order):**

| # | guard (def line) | trigger | det/LLM | shadow/overlap risk |
|---|---|---|---|---|
| 1 | `_maybe_handle_sunday_school` (2352) | „საკვირაო"+„სკოლ" | det | runs FIRST (before static welcome). Hardcoded „ივლისში დაემატება" (`:2299`) — does NOT read `sections.yaml` |
| 2 | `_maybe_static_welcome` (2848) | first reply, unless explicit GE/EN camp intent | det | yields to camp intent via `_has_explicit_georgian/english_camp_intent` |
| 3 | `_maybe_memory_info_reply` (3237) | „ჩემზე რა ინფორმაცია…" | det | privacy-critical: never exposes sender_id/phone/IDs |
| 4 | `_maybe_requalify_child` (1005) | requalify cues | det | — |
| 5 | `_maybe_acknowledge_stored_state` (1062) | resume-ack | det | — |
| 6 | `_maybe_handle_event_inquiry` (3097) | explicit event price/date or established event context | det (SAFETY: never 2150 for events) | **must run before engine** to stop camp price leaking onto event-price questions |
| 7 | `_maybe_handle_camp_registration_link` (2598) | registration/form/sign-up; „ფორმა" via word-boundary `_CAMP_FORM_TOKEN_RE` so „ინფორმაცია" never fires | det | returns Admin `registration_url` BEFORE engine (no age question) |

**Then, inside `if engine_flag:` (per-turn `book_consultation_success_for_conversation` reset first):**

| # | guard (def line) | trigger | det/LLM | shadow/overlap risk |
|---|---|---|---|---|
| 8 | `_maybe_handle_decline_engine` (3357) | `_DECLINE_PHRASES` („არ მინდა") | det | **SHADOW vs price-objection**: PATCHED — defers (None) when `_DECLINE_OVERRIDE_INTEREST` (მაგრამ/თუმცა/მაინც/ძვირ/მიჭირს) present (`:3386`) or „?" present (`:3396`). Still a substring race |
| 9 | `_maybe_handle_reschedule_intent_engine` (3642) | reschedule phrases | det | must run before commit (#14) |
| 10 | `_maybe_handle_underage_manager_handoff` (2126) | under-min-age + handoff context | det | **SHADOW vs #11**: PATCHED — at `:2184` it itself calls `_is_explicit_manager_number_request` → `_render_manager_number_answer`, so an under-age "give me the manager's number" is served instead of being mis-parsed as a name. Closed ONLY by duplicating the manager-number check |
| 11 | `_maybe_handle_explicit_manager_request` (2683) | manager-word AND contact-word AND no own phone (`_is_explicit_manager_number_request` :2634) | det | fires only for ELIGIBLE/unknown-age; under-age path handled inside #10. Does NOT call `request_manager_callback` that turn (accepted edge) |
| 12 | `_maybe_handle_contact_correction` (2753) | „შევცდი"/„ეს არა"/„სხვა ნომერ"/„კი არა" + last valid value | det (in-memory only; no Calendar/Sheets) | runs before #13 (which never overwrites a set field) |
| 13 | `_maybe_handle_contact_collection` (3942) | bot recently asked for contact OR pending_booking; `_parse_name_phone` | det | **densest overlap zone (13/14/15)**: defers (None) on future bookable confirmed slot so #14 can book |
| 14 | `_maybe_commit_pending_booking_engine` (4243) | future confirmed `pending_booking` | det (commits via executor) | defers stale/past pending (`:3971-3973`) |
| 15 | `_maybe_request_full_contact_on_intent` (4143) | ELIGIBLE known-age, no bookable slot | det | only-then defers (`:4160-4162`) |

**Then** `_run_llm_engine_safely` (310) → engine; on empty/raise → legacy `_handle_impl`.

**Post-engine sanitizer stack (on non-empty reply, in order; 318-401):** `_repair_colloquial_hour_rejection` → `_strip_consultation_cta_if_ineligible` → **`_ensure_ineligible_young_age_message` (SAFETY)** → **`_strip_consultation_cta_if_booked` (SAFETY)** → `_strip_unwarranted_sibling_discount` → `_strip_redundant_confirmation_after_command` → `_ensure_adult_intro_followup_for_parent_flow` → `_trim_booking_success_response` → `_strip_unwarranted_thanks_in_booking_confirmation` → `_strip_redundant_age_question_if_known` → `_ensure_camp_age_question` → `_format_multipoint_paragraphs` → **`_sanitise_booking_confirmation` (FINAL chokepoint)**.

**The two confirmed shadow risks (both currently PATCHED, architecture still fragile):**
- **#10 underage-handoff vs #11 manager-number** — closed only by duplicating `_is_explicit_manager_number_request` inside the underage guard.
- **#8 decline vs price-objection** — closed only by the `_DECLINE_OVERRIDE_INTEREST` set + „?" defer.

The **densest overlap zone is the contact/booking triad (#13/#14/#15)**: three consecutive guards each re-implement `_parse_name_phone` / `_distinct_valid_phones` / `_message_has_overlong_number` / `_looks_like_contact_disclosure` / `is_valid_person_name`. This is the prime consolidation target — collapse into one contact/booking resolver, or push name/phone extraction to the existing `save_lead_info`/`book_consultation` tools.

---

## 4. Duplicated source-of-truth tables

### A. Camp facts

| fact | sources (file:line) | WINS now | serves STALE / direct readers |
|---|---|---|---|
| Price `2150` | `sections.yaml:15-16` (`price_text:'2150'`+`price_gel:2150`); `camp_2026.yaml:18`; merge `admin_config_service.py:573-586`; `parent_tool_executor.py:311,335-356` | **`sections.yaml price_text`** (admin) via `get_camp_facts` | DIRECT `camp_2026.yaml` readers: `parent_llm_engine.py:1924/2194`, `comment_service.py:194`, `parent_turn_router.py:118`, `parent_reply_composer.py:180`, `parent_turn_analyzer.py:146` — invisible to admin price edits |
| Streams I/II/III (`23-29 ივნისი / 5-11 ივლისი / 14-20 ივლისი`) | `sections.yaml:25-34`; `camp_2026.yaml:20-23`; visibility `admin_config_service.py:1167-1222`; `parent_tool_executor.py:331` | **`sections.yaml` streams** (date-filtered: today 2026-06-22 all 3 visible; I auto-hides 2026-06-23) | **also HARDCODED in `system_parent_v2.md:293` (LIVE PROMPT) — bypasses both YAML and the date-filter** |
| Location „ამბასადორი კაჭრეთი" | `sections.yaml:13`; `camp_2026.yaml:14`; `admin_config_service.py:553-559`; `parent_tool_executor.py:369-374` | **`sections.yaml`** | (no live conflict) |
| Age `9–17` | `sections.yaml:11-12`; `camp_2026.yaml:15-16`; `parent_tool_executor.py:388-394`; PROMPT band via `parent_llm_engine.py:1924/2194` | TOOL band = **`sections.yaml`** (admin); PROMPT band = **`camp_2026.yaml`** (direct) | DIVERGENCE if operator edits age in admin only → prompt(camp_2026) ≠ tool(admin) |
| includes / discounts | `sections.yaml:35-42`; `camp_2026.yaml:19,24-26`; `admin_config_service.py:614-624` | **`sections.yaml`** | admin discounts are strings → lose numeric `percent` (None) vs `camp_2026` `percent:10` (shape divergence) |
| Registration URL `tinyurl.com/36jcae8z` | `sections.yaml:20`; `camp_2026.yaml:30`; consumers `parent_tool_executor.py:396-414` + `parent_flow.py:2563-2589` | **`sections.yaml`** | (no conflict; missing → manager fallback) |
| Camp manager phone `558 67 47 33` | `sections.yaml:21` (`summer_camp.manager_contact`); `camp_2026.yaml:31`; `company.yaml:6`; `admin_config_service.py:636-639` | **`sections.yaml manager_contact`** for camp-registration display | SEPARATE chain from handoff phone (`get_manager_phone`) — two phone chains converging on `company.yaml` today |

### B. Sunday School

| fact | sources | WINS now | STALE |
|---|---|---|---|
| Status / availability | `sections.yaml:47-74` (`status:coming_soon`, **no month**); live answer „ივლისში დაემატება" **HARDCODED** `parent_flow.py:2298-2302` | **Python hardcode** ("July") | YAML has no month → admin plan changes have ZERO effect on the live answer |
| Intent trigger | `parent_flow.py:2331-2336` („საკვირაო"+„სკოლ") | code | — |
| Handoff | EMAIL-ONLY `notification_service.notify_sunday_school_handoff`; lead → `sheets_service.log_sunday_school_lead` (`parent_flow:2420/2426`); idempotency `_sunday_school_notified_senders` set (`:2328`, in-memory) | code | **in-memory set → restart re-allows duplicate handoff**; cross-worker double-send |
| Comment DM | `templates.yaml:9-30` reads section fields | `sections.yaml:57-69` (EMPTY price/schedule/location/url) | template renders mostly blank |

### C. Adult events

| fact | sources | WINS now | STALE / dead |
|---|---|---|---|
| Active events | `sections.yaml:104-131` `adult_events.events[]`; `adult_tool_executor.py:299` → `get_active_adult_events` (`admin_config_service.py:1225-1257`) | **`sections.yaml events[]`** (active+future) | „გია მურღულია" (14 ივნისი) PAST → hidden; only „fromula 1" (28 აგვისტო) surfaces |
| Empty template | `data/events.txt` (all blank); loaded `config.py:170`, `conversation_service.py:344`; `_parse_events_blocks` → `[]` | (never wins) | always `[]` → fallback; preempted by active list (`comment_service.py:1177-1178`); **NOT read by live ADULT engine** |
| „fromula 1" price | `sections.yaml:126,131` (`price_text:'5000'` vs `price_gel:4999`) | display = `price_text` 5000 | **internal source CONFLICT** (5000 vs 4999) — operator data; HANDOFF marks it a test/demo to deactivate before launch |
| min_age | per-event 13 + hard floor `ADULT_EVENT_DEFAULT_MIN_AGE=13` (`admin_config_service.py:703-709`) | 13 | — |
| Section-level adult facts (price 200, „maroon 5", stadium, 23 ივნისი) | `sections.yaml:84-102` | **never fires** while `events[]` populated (`_build_fallback_event_from_section:774-863`) | DEAD shadow data; surfaces only if `events[]` cleared |

### D. Business hours

| fact | sources | WINS now | STALE |
|---|---|---|---|
| 10:00–21:00, slot 60, buffer 120 | `app/agent/knowledge/business_hours.yaml:11-29` (read by `calendar_service.py:30` + `parent_flow.py:3881`) | **`knowledge/business_hours.yaml`** | `data/admin_config/business_hours.yaml:6-15` = hand-synced display mirror, NOT read by booking — operator edits there do nothing |
| Sunday-closed / Saturday-open | CODE only: `calendar_service CLOSED_WEEKDAYS={6}` | **Python constant** (single source) | not in any YAML; not operator-editable by design |

### E. Manager notification

| channel | source | WINS now | STALE |
|---|---|---|---|
| Email | `settings.MANAGER_EMAIL` (.env) `notification_service.py:790-833`, `ENABLE_EMAIL_NOTIFICATIONS` gate | **`.env`** | `manager_contacts.yaml:8 email_placeholder` = display mirror, NOT read by sender |
| WhatsApp | `settings.get_whatsapp_access_token()` + `get_manager_whatsapp_number()` (`notification_service.py:866-868`); skips when empty | **`.env`** (pending real creds) | `manager_contacts.yaml:9-10` placeholders + `notification_label` = display only |
| Disclosed phone (callback) | `get_manager_phone()` chain: `manager_contacts.yaml manager_phone/phone` → `settings.MANAGER_PHONE_NUMBER` → `company.yaml:6 (558 67 47 33)` → `adult_events.manager_contact` (`admin_config_service.py:1754-1800`); consumers `parent_flow.py:2664`, `adult_tool_executor.py:641` | **`company.yaml` 558 67 47 33** (de-facto; mgr_contacts has no phone key, settings likely unset) | DIFFERENT chain from `get_camp_facts` phone (`summer_camp.manager_contact`) — two phone sources, divergence if either edited alone; hardcoded `558 67 47 33` fallback also in `parent_flow` |

---

## 5. Canonical source-of-truth proposal

For each domain: **PRIMARY** + **allowed (logged) fallback** + **"no mixed reading" rule**.

- **A. Camp facts** — PRIMARY: `data/admin_config/sections.yaml summer_camp` via **`admin_config_service.get_camp_facts()` only**. Allowed fallback: `camp_2026.yaml` (logged when admin field empty). **No mixed reading:** every camp-fact consumer (including the prompt age band and the 5 direct `load_knowledge('camp_2026')` readers) must call `get_camp_facts()`; **no module may read `camp_2026.yaml` directly.** Stream dates must come from `get_camp_info` only (date-filtered) — never from the prompt.

- **B. Sunday School** — PRIMARY: `sections.yaml sunday_school` (status + description + month). The live answer and handoff copy should READ the section, not hardcode „ივლისში". Allowed fallback: a static "coming soon" string when section empty. **No mixed reading:** „July" must not live in Python.

- **C. Adult events** — PRIMARY: **`sections.yaml adult_events.events[]` via `get_active_adult_events()` only.** Justification: it is the populated, date-filtered, schema-normalised source the live engine already reads; `data/events.txt` is empty and always preempted; section-level adult facts are dead shadow data. Allowed fallback: `_build_fallback_event_from_section` (logged, only when `events[]` empty). **No mixed reading:** retire `data/events.txt` as a fact source; resolve the per-event `price_text` 5000 vs `price_gel` 4999 conflict in admin_config (operator decision); operator should clear the dead section-level facts.

- **D. Business hours** — PRIMARY: **`app/agent/knowledge/business_hours.yaml` only** (read by `calendar_service` + `parent_flow` buffer). Weekday policy stays the code constant `CLOSED_WEEKDAYS`. **No mixed reading:** `data/admin_config/business_hours.yaml` is display-only — either wire it as the source or label it clearly non-authoritative to remove the manual-sync hazard.

- **E. Manager contact** — PRIMARY for **disclosure**: `admin_config_service.get_manager_phone()` resolving to `company.yaml 558 67 47 33`. PRIMARY for **email/WhatsApp send**: `.env`/`settings`. **No mixed reading:** unify the camp-registration phone and the handoff phone onto the single `get_manager_phone()` chain so editing one place changes both; `manager_contacts.yaml` placeholders remain display-only mirrors.

- **Prompts/policies** — PRIMARY for facts: **none**. Prompts and policy `.md` files carry **behaviour/tone only, zero volatile facts**. `system_parent_v2.md` must delegate ALL facts to `get_camp_info`. Policy headers claiming "the engine reads selected lines" are inaccurate and should be corrected (no runtime read).

---

## 6. Live path map

`webhook → message_buffer → conversation_service → segment routing → parent_flow/adult_flow → engine/tools → response`

| step | det / LLM | data read | state read/written | failure modes |
|---|---|---|---|---|
| 1. `webhook` → `message_buffer.buffer_message` (debounce 5–15s) | det | raw Meta payload | module dicts `_pending_messages`/`_pending_tasks`/`_buffer_started_at`/`_locks` (in-memory) | worker restart mid-debounce drops buffered fragments; cross-worker fragments never merge |
| 2. kill-switch (`_process_message_impl` top, `:443-447`) | det | `settings.AGENT_ENABLED` (default True) | none | OFF → fixed `AGENT_DISABLED_MESSAGE` before any work |
| 3. `_get_or_create_conversation` (`:770-789`) | det | Redis `conversation:{platform}:{sender_id}` | in-memory `conversations` dict (per-process) ↔ Redis restore; fresh `Conversation(state=START)` on miss | corrupt Redis JSON discarded → fresh conversation (state loss); each worker has its own dict |
| 4. segment routing (`:472-495`) | det | message text | `conversation.segment` (sticky once PARENT/ADULT); booked OR (in-flow AND lead)→force PARENT; else `_classify_segment`; then ADULT→PARENT via `_is_parent_consultation_intent` | sticky-ADULT swallows camp reschedule (closed by override set); no symmetric deterministic PARENT→ADULT |
| 5a. UNCLEAR dispatch (`:497-520`) | det | text | none beyond history | `_maybe_identity_reply` / `_REGISTRATION_LINK_CLARIFICATION` / `UNCLEAR_ROUTING` menu; recoverable next turn |
| 5b. PARENT → `parent_flow.handle` 15 interceptors → engine | det (interceptors) then **LLM** (engine) | lead state, `get_camp_facts`, calendar | `pending_booking`, `lead.*`, `book_consultation_success_for_conversation` (per-turn reset) | each interceptor short-circuits; engine empty/raise → legacy `_handle_impl` |
| 5b. `run_parent_llm_turn` | **LLM** (gpt-4.1-mini, `tool_choice=auto`, 5 iters) | system_parent_v2 + `_build_context_message` (booked/today_iso) + sales context + ~10 history | pre-turn `_capture_turn_facts` writes `lead.child_age`/`lead.phone`; tools via `ParentToolExecutor` (only Calendar/Sheets/notify writer) | exception/empty/iter-cap → `""` → legacy |
| 5b. post-engine sanitizers (`:318-401`) | det | engine output | none (cleanup) | `_sanitise_booking_confirmation` final chokepoint: privacy-notice policy + fake-booking guard |
| 5c. ADULT → `adult_flow.handle` (engine-first) | **LLM** then det fallback | events via `get_active_adult_events` | `selected_events` (in-memory) | engine empty → `_maybe_handle_adult_global_intent` + legacy state machine + `_ADULT_ENGINE_SAFE_FALLBACK`; "never live-tested end-to-end" |
| 6. response | det | — | append assistant turn, `last_bot_message_at`, post-followup markers, **Redis write-through** | `process_message` wraps in Sentry capture + re-raise (webhook logs/skips send) |

**Side-effect boundary:** ALL Calendar writes / Sheets writes / manager notifications gate through `ParentToolExecutor` (fail-CLOSED on Calendar error). The fake-booking guard (`_sanitise_booking_confirmation`) replaces any "ჩაგინიშნეთ" wording when the lead is NOT booked and there was no tool-success this turn.

---

## 7. Router priority audit

| intent | current handler | should-be-deterministic? | should-be-LLM? | priority | known conflict |
|---|---|---|---|---|---|
| pure greeting („გამარჯობა") | `_classify_segment`→UNCLEAR / `_maybe_static_welcome` | YES (is) | no | segment / interceptor #2 | none |
| camp info | `_classify_segment`→PARENT, then `get_camp_info` | route YES / answer LLM | answer YES | segment → engine | none |
| camp registration link/form | `_maybe_handle_camp_registration_link` (#7) | YES (is) | no | pre-engine #7 | „ფორმა" word-boundary so „ინფორმაცია" excluded; documented 06-19 bug if LLM takes it |
| price question | bare→UNCLEAR; camp→PARENT→engine; event→`_maybe_handle_event_inquiry` | mixed | answer LLM (camp) | segment + #6 | 2150-vs-event-price leak (closed by #6 before engine) |
| price objection („ძვირია") | `_maybe_handle_decline_engine` DEFERS to engine | no | YES (is) | #8 | shadow vs real decline (closed by `_DECLINE_OVERRIDE_INTEREST`) |
| real decline („არ მინდა") | `_maybe_handle_decline_engine` (#8) + followup marker | YES | no | #8 | resolved by override set |
| event interest | `_classify_segment`→ADULT, adult engine | route YES / answer LLM | answer YES | segment + #6 | bare „ღონისძიება" reaches engine (`switch_to_adult_flow`) |
| negated event interest | `_classify_segment` substring (no negation) → ADULT, then engine/decline | partial | YES | segment | **UNVERIFIED** at deterministic layer; negation left to LLM; negated mention may still flip segment ADULT first |
| Sunday School | `_maybe_handle_sunday_school` (#1, HIGHEST) | YES (is) | no | #1 | hardcoded „July"; in-memory idempotency set |
| manager phone request | `_maybe_handle_explicit_manager_request` (#11) / under-age via #10 | YES (is) | no | #11 (after #10) | does NOT call `request_manager_callback` that turn (accepted) |
| consultation booking + date/time | LLM tools (`get_available_slots`/`check`/`book`) + `_maybe_commit_pending_booking_engine` (#14) | commit YES | booking decision LLM | #14 + engine | stale/past pending defer; executor is single Calendar writer |
| contact capture (name/phone) | `_maybe_handle_contact_collection` (#13) + engine `_capture_turn_facts` | YES (is) | extraction could be LLM | #13 | densest overlap (#13/#14/#15); bare 9-digit phone was dropped to LLM (live bug → guard) |
| contact correction | `_maybe_handle_contact_correction` (#12) | YES (is) | no | #12 (before #13) | corrections ignored once field set if guard removed |
| state recall („ჩემზე რა გაქვს") | `_maybe_memory_info_reply` (#3) | YES (is, privacy-critical) | no | #3 | never expose PII |
| PARENT→ADULT switch | LLM `switch_to_adult_flow` tool | no | YES (is) | engine | no deterministic segment-level flip; **UNVERIFIED** if sticky-PARENT deterministically switches on a clear adult message |
| ADULT→PARENT switch | `_is_parent_consultation_intent` (segment) + `_user_wants_parent_flow` (engine, hard camp keyword) | YES (is) | partial | segment + engine | two mechanisms; „დის(თვის)"→wrong switch closed |
| gratitude only („მადლობა") | reaches LLM engine (PARENT); ADULT thanks branch in global-intent | no PARENT guard (rolled back) | YES | engine | **UNVERIFIED/MIXED**; post-engine `_strip_unwarranted_thanks_in_booking_confirmation` only strips unwarranted leading thanks; token-waste optimization deferred |
| gratitude + new question | LLM engine answers | no | YES (is) | engine | none |
| off-topic / prompt injection | ADULT: `_maybe_adult_offtopic_reply` (det, before OpenAI); PARENT: prompt + sanitizers only | ADULT YES | PARENT YES | ADULT pre-LLM / PARENT engine | PARENT injection resistance is **prompt-only, UNVERIFIED robustness** |

---

## 8. State/memory model + transliteration

### Conversation (canonical, Redis-persisted)
`conversation.py:36-160` — fields: `sender_id, platform, segment, state, history, lead, created_at, last_activity, pending_booking, last_bot_message_at, followup_stage, followup_blocked_reason, last_meaningful_interest, stopped_after, adult_subscription_status`. Persisted to `conversation:{platform}:{sender_id}` (sliding ~7d TTL), write-through every `process_message`. `last_activity` is reused as `last_user_message_at` (deliberate). The 5 follow-up fields ARE now read by the wired scheduler (`followup_service`), correcting the stale CLAUDE.md "data-only" claim.

### Lead (canonical, nested in Conversation)
`lead.py:18-151`. **CRITICAL INVARIANT:** `child_age` = PARENT/camp ONLY; `adult_age` = ADULT/self ONLY; `adult_target_age` = ADULT/relative ONLY; NEVER cross-assign (only `switch_to_adult_flow` may MOVE out-of-range `child_age`→`adult_age` then clear `child_age`). `to_sheet_row` has 16 cols and **excludes** `calendar_event_id`/`booked_datetime_iso`. Canonical booking fields: `calendly_booked + booked_datetime_iso + calendar_event_id + status`.

### In-memory module state (stale / cross-worker risk)
- **Redis-mirrored (restart-safe):** `manager_notified_for_conversation` (`manager_notified:{sender_id}`).
- **In-memory only (lost on restart, race across workers):** `_sunday_school_notified_senders` (duplicate handoff after restart), `_last_slots_by_sender` (slot cache), `book_consultation_success_for_conversation` (per-turn), `parent_flow.available_slots/ask_name_retries/invalid_phone_retries/slots_shown_for_state`, `parent_turn_router.manager_offer_shown`, `adult_flow.selected_events`, `message_buffer` dicts, `conversations` dict (mirrored to Redis but divergent between writes), `content_repository.events_data` (loads the EMPTY `data/events.txt`; **UNVERIFIED** whether any live PARENT/ADULT path reads it — `FlowContext.events` exists but the engine path does not use `FlowContext`).
- **Segment stickiness:** sticky once PARENT/ADULT; ADULT→PARENT deterministic (consultation/reschedule), PARENT→ADULT LLM-only. Lead PARENT fields preserved across a flip; only routing changes. Stale risk: a conversation that tested ADULT then asks a camp question stays ADULT unless it hits the narrow override set or the engine switches.
- **Mandatory single-worker** because these dicts race AND APScheduler (`main.py:70` `BackgroundScheduler`, no distributed lock) would double-fire follow-up DMs across workers.

### Transliteration (Latin-script Georgian) — where it breaks today
Latin-script intent is handled in **only two narrow spots**: (a) `conversation_service.CAMP_KEYWORDS` has 4 English stems (`camp/child/kid/summer`) so an English camp DM routes PARENT; (b) `parent_flow._has_explicit_english_camp_intent` lets static-welcome yield for a mostly-Latin camp enquiry. **Everywhere else** intent/name/correction gating is Georgian-only `[ა-ჰ]` substring — **11 occurrences in `parent_flow` alone** (e.g. `_extract_corrected_name` `:2744`, contact name `:4029`). A Latin-script Georgian name („Nino") or a Latin-script intent is NOT captured by the deterministic guards: it falls through to the LLM (acceptable) OR is dropped by name parsers requiring `[ა-ჰ]` (the deferred "F-D3 Latin name" gap in CLAUDE.md).

**Simplest fix direction (not more `[ა-ჰ]` gates):** a single **`normalize_text_for_intent`** (transliterate Latin→Georgian) at the `conversation_service` chokepoint, PLUS letting the LLM tools (`save_lead_info`) own name/phone extraction. This removes the need for `[ა-ჰ]` gates scattered across ~15 interceptors and closes the Latin-name gap. Risk of removing the gates today is "garbage names" only IF LLM extraction does not replace them — so the gates stay until extraction is in place.

---

## 9. Phased cleanup plan

Each phase lists concrete file-level actions + the gate that proves safety. **Never delete first — move to `archive/`.** Production is not green; the safety gate for any live-path change is `tools/scenario_runner_full.py` CRITICAL set staying green, never bulk pytest alone.

### PHASE 1 — no-code (ARCHIVE-identify / dormant / doc-merge / fact-consolidation)
Actions:
- **Doc fixes (zero behavioural risk):** correct CLAUDE.md (a) "Sender NOT yet wired to PATCH 3 markers" → it IS wired (`main.py:70-84`, `followup_service.py:351/361`); (b) `FOLLOWUP_TEST_MODE=true`/`FIRST_DELAY=120` → `.env` omits them (prod cadence); (c) `USE_ADULT_LLM_ENGINE` `.env=true` → `.env` omits it (code default True). Fix the policy headers in `parent_sales_policy.md`/`adult_sales_policy.md` that falsely claim "the engine reads selected lines".
- **Doc consolidation:** keep `LIVE_TEST_CHECKLIST_2026_06_22.md` + `FULL_TEST_SCENARIOS_2026_06_22.md` (base+extension); ARCHIVE `FULL_AGENT_TEST_SWEEP_REPORT.md` (06-14) + the 3 `REDTEAM_*.md` into one history file under `docs/`.
- **Identify (do NOT delete) dormant/empty:** `parent_communication_style.md` (no runtime caller — only `test_template_render_equivalence.py:96`), `data/events.txt` (empty, always `[]`), `data/knowledge_base.txt` (empty), `summary.md` alias (orphaned — **UNVERIFIED**, grep `SUMMARY_PROMPT` first), `USE_LLM_COMPOSER` (never on), section-level dead adult facts in `sections.yaml:84-102`.
- **Fact consolidation (data-level, no code path change):** confirm `sections.yaml` vs `camp_2026.yaml` agree (they do); document the „fromula 1" 5000-vs-4999 conflict for operator decision.

Gate: documentation diff review only; no test required (no code/data path changed). Re-run bulk pytest to confirm no accidental file removal broke an import/byte-identity test.

### PHASE 2 — source-of-truth routing
Actions: swap the direct `load_knowledge('camp_2026')` reads → `admin_config_service.get_camp_facts()` in `parent_llm_engine.py:1924/2194` (prompt age band), `comment_service.py:194`, and the legacy stack (`parent_turn_router.py:118`, `parent_reply_composer.py:180`, `parent_turn_analyzer.py:146`). Route the Sunday-School „July" answer to read `sections.yaml`. Unify the camp-registration phone onto `get_manager_phone()`.
Gate: `scenario_runner_full` CRITICAL stays green; an admin price/stream/age edit now provably reaches all readers (add a targeted scenario asserting an admin-edited price surfaces).

### PHASE 3 — prompt slimming
Actions: **delete the 3 literal stream dates at `system_parent_v2.md:293`** (rely on `get_camp_info`); move the ~90% cosmetic `FORBIDDEN_PHRASE_REPLACEMENTS` entries into `system_parent_v2.md` as style rules (keep `_strip_concern_wording` + the few genuine grammar fixes the model can't self-correct); mirror for `sanitise_adult_response`. Optionally trim the 451-line bloat (separate gated sub-task).
Gate: `scenario_runner_full` full run (real OpenAI) — wording scenarios + CRITICAL all green; the dated wording-pinned tests retired in lockstep with each migrated rule.

### PHASE 4 — router simplification
Actions: introduce **`normalize_text_for_intent`** (Latin→Georgian transliteration) at the `conversation_service` chokepoint; introduce a thin **`high_priority_intent_router`** that keeps ONLY hard-safety guards (Sunday-school handoff, camp-registration-link, manager-number, underage dispatch, booking-commit) and routes name/phone/intent extraction to the LLM tools; collapse the contact/booking triad (#13/#14/#15) into one resolver. Remove the now-dead `[ა-ჰ]` gates ONLY where LLM extraction replaces them.
Gate: `scenario_runner_full` CRITICAL 22–23/× stays green (CLAUDE.md says 22; mapper grep found 23 — treat the live count as the gate); each removed guard's dated test retired together.

### PHASE 5 — archive/delete (only after tests + live smoke)
Actions: after prod logs confirm engine reliability, move the legacy parent state machine (`parent_reply_composer`, `parent_turn_analyzer`, legacy `_handle_impl` branches) and legacy `adult_flow` state machine to `archive/`; archive `system_parent.md`/`system_base.md`/`system_adult.md`/`parent_present_value.md` and the dead files identified in Phase 1. **Never delete first.**
Gate: full `scenario_runner_full` + a live smoke pass on the staging webhook with the engine stubbed-to-fail to confirm the fallback still serves before its code is moved; CLAUDE.md explicitly forbids removing the legacy fallback until then.

---

## 10. Top 10 highest-risk confusion sources

1. **`system_parent_v2.md:293` hardcoded stream dates (LIVE fact-drift).** Fix: delete the literal dates; rely on `get_camp_info`. **quick-win.**
2. **15-deep order-sensitive interceptor chain in `parent_flow.handle`.** Fix: Phase-4 `high_priority_intent_router` keeping only hard-safety guards; collapse the contact/booking triad. **large.**
3. **5 direct `camp_2026.yaml` readers bypass `get_camp_facts`.** Fix: route through `get_camp_facts()`. **medium.**
4. **Prompt age band (camp_2026) vs tool age band (admin) divergence.** Fix: prompt band via `get_camp_facts`. **quick-win.**
5. **Two CLAUDE.md doc-drift statements (scheduler "not wired"; FOLLOWUP_TEST_MODE/120 "live").** Fix: correct the doc. **quick-win.**
6. **Sunday-School „July" hardcoded in Python, divergent from YAML.** Fix: read `sections.yaml`. **quick-win.**
7. **Two manager-phone chains (`get_camp_facts` vs `get_manager_phone`).** Fix: unify on `get_manager_phone()`. **medium.**
8. **`pytest` greenness ≠ live path (engines pinned OFF in conftest).** Fix: document that `scenario_runner_full` is the live gate; treat bulk pytest as legacy/unit coverage. **quick-win (doc) / medium (process).**
9. **`data/admin_config/business_hours.yaml` display mirror looks editable but doesn't change bookings.** Fix: label non-authoritative or wire it. **quick-win.**
10. **Two divergent `mask_sender` shapes (`kill_switch` `***+sid[-4:]` vs `sentry_service` `sid[:6]+***`), mixed in `followup_service`.** Fix: pick one shape. **quick-win.**

---

## 11. What NOT to delete yet

**Hard-safety deterministic guards (NEVER move to prompt, KEEP_PRIMARY/CANONICAL):**
- `_sanitise_booking_confirmation` + `_apply_privacy_notice_policy` (fake-booking guard, privacy notice).
- `_ensure_ineligible_young_age_message` + `_strip_consultation_cta_if_booked` + `_strip_consultation_cta_if_ineligible`.
- `_maybe_handle_event_inquiry` (never-2150-for-events).
- `ParentToolExecutor` / `AdultToolExecutor` validation (age-range, phone parse, FreeBusy, fail-CLOSED, side-effect gating).
- `_maybe_memory_info_reply` (PII redaction), `kill_switch`, `_maybe_handle_camp_registration_link`, the underage/manager-number dispatch.

**Live-as-fallback (cold, do NOT delete — CLAUDE.md forbids):**
- Legacy parent state machine (`parent_reply_composer`, `parent_turn_analyzer`, `parent_turn_router`, `_handle_impl` branches), legacy `adult_flow` state machine, `system_parent.md`/`system_base.md`/`system_adult.md`/`parent_present_value.md`, `openai_service` legacy path.
- `data/prompts.py` (load-bearing back-compat alias — removing it = ImportError across all flows).
- `data/events.txt` / `data/knowledge_base.txt` (empty but loaded at import — removing crashes the read).

**UNVERIFIED — carry forward as uncertainty, do NOT upgrade to delete:**
- `summary.md` alias (`SUMMARY_PROMPT`) consumer beyond the import.
- Whether `detect_segment` still has any live caller.
- Whether `USE_LLM_TURN_ANALYZER` / analyzer is ever reached on the live path.
- Whether `adult_defaults.yaml` is read on the live ADULT engine path.
- Whether any live PARENT/ADULT path reads `content_repository.events_data`.
- Whether a clear adult-event message in a sticky-PARENT conversation deterministically switches (currently LLM-only).
- PARENT prompt-injection robustness (prompt-only).
- The CRITICAL scenario count (CLAUDE.md says 22; mapper grep found 23 — off-by-one, likely a transcript/NORMAL reclass).

---

## 12. Exact next implementation task after this audit

**Task (smallest, safest, no live-code-path risk): the PHASE-1 no-code consolidation, scoped to the camp fact-drift and the two literal-fact bugs that have a zero-behaviour-change first step.**

Concretely, the single first change is the **camp source-of-truth doc-and-prompt consolidation prep**:
1. Correct the three stale CLAUDE.md statements (scheduler wired; `FOLLOWUP_TEST_MODE`/`FIRST_DELAY` not in `.env`; `USE_ADULT_LLM_ENGINE` not in `.env`).
2. Document (in this audit's wake, not in code) that `sections.yaml` is the camp PRIMARY and list the 5 direct `camp_2026.yaml` readers as the Phase-2 work item.
3. Flag `system_parent_v2.md:293` as the one live fact-drift to remove in Phase 3.

If the owner prefers a **one-line live fix with the highest fact payoff**, do the single edit **delete the literal stream dates at `system_parent_v2.md:293`** (replace with a non-fact reference to `get_camp_info`'s `<streams>`).

**Acceptance test for the one-line live fix:** run `tools/scenario_runner_full.py` with the engine ON (`force_engine_on()`, real OpenAI) and confirm:
- The CRITICAL set stays green (no regression).
- A camp-streams scenario shows the three streams sourced from `get_camp_info` (date-filtered: on 2026-06-22 all three visible; verify stream I auto-hides on/after 2026-06-23) and the reply contains NO hardcoded dates from the prompt.
- No new failure in the wording/date scenarios.

For the **pure no-code Phase 1**, the acceptance gate is a documentation-diff review plus a bulk `pytest` run to confirm no file was accidentally removed (byte-identity and loader tests still pass) — no live-path change, so `scenario_runner_full` is not required for that step.

---

*Relevant absolute paths for the follow-up tasks:*
- Target doc: `c:\Users\Greench Pc\Desktop\AI sales agent\ai-agent\docs\SOURCE_OF_TRUTH_AUDIT.md`
- Canonical camp source: `c:\Users\Greench Pc\Desktop\AI sales agent\ai-agent\data\admin_config\sections.yaml`
- Camp fallback: `c:\Users\Greench Pc\Desktop\AI sales agent\ai-agent\app\agent\knowledge\camp_2026.yaml`
- Live parent prompt (line 293 fix): `c:\Users\Greench Pc\Desktop\AI sales agent\ai-agent\app\agent\prompts\system_parent_v2.md`
- Interceptor chain: `c:\Users\Greench Pc\Desktop\AI sales agent\ai-agent\app\flows\parent_flow.py`
- Fact chokepoint: `c:\Users\Greench Pc\Desktop\AI sales agent\ai-agent\app\services\admin_config_service.py`
- Live regression net: `c:\Users\Greench Pc\Desktop\AI sales agent\ai-agent\tools\scenario_runner_full.py`
