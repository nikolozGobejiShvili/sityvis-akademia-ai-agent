# ✅ SOURCE-OF-TRUTH VERIFICATION SWEEP — სიტყვის აკადემია AI Sales Agent (2026-06-22, READ-ONLY)

> 🔄 **FORWARD POINTER (2026-06-23):** Dated 2026-06-22 snapshot. Current baseline **2879 / 0 / 28**; **Reasoning Layer Phase 1 implemented** (gated, default OFF — `app/reasoning/reasoning_layer.py`, flag `USE_REASONING_LAYER`, deterministic/no-LLM). Also done since: free-form robustness + handoff/contact intent-priority fix. Authoritative current state: `HANDOFF.md` „✅ CURRENT STATE (2026-06-23)". Next task: **Prompt Slimming**. **Production still NOT green.**

> **READ-ONLY** — no code/prompt/YAML/data was changed, nothing was deleted or moved, nothing was deployed, **production is NOT green.** This sweep independently re-verifies `docs/SOURCE_OF_TRUTH_AUDIT_2026_06_22.md` against the live code under `ai-agent/` using 5 grounded read-only verifiers.
>
> ✅ **THIS DATED FILE IS CANONICAL.** A non-dated duplicate `docs/SOURCE_OF_TRUTH_VERIFICATION_SWEEP.md` exists (identical content, pending docs cleanup) — its deletion/archive requires explicit approval (not done).
>
> ✅ **UPDATE (2026-06-22, Tasks 1 → 5A-3 all DONE, each test-gated, suite 0-failed):** every recommended source-of-truth cleanup in this sweep is now complete:
> 1. **`system_parent_v2.md:293` hardcoded stream dates** → removed; stream dates come from `get_camp_info` / the visible-stream filter (Task 1).
> 2. **Sunday-School „July" hardcode** → `sections.yaml` `sunday_school` via `get_sunday_school_status()` (Task 2); Admin-Panel save now PRESERVES those fields + unknown keys (Task 3).
> 3. **Two manager-phone chains** → unified: `get_camp_facts()['phone']` defers to canonical `get_manager_phone()` (Task 4).
> 4. **Camp age band (6 live readers)** → canonical `get_camp_age_bounds()` (Tasks 5A-1 + 5A-2).
> 5. **Post-booking facts + comment rich DM** → `get_camp_facts()` / verified admin-first; `parent_flow` now has ZERO direct `camp_2026.yaml` reads (Task 5A-3).
>
> Latest baseline: suite **2802/0/28**, corpus 9/9, property 28/28, CRITICAL **22/22 clean**, transcript 3/3, **production NOT green.** Still pending (behavioural, not SoT): router normalization / Latin-Georgian transliteration, negated-event recovery, PARENT→ADULT deterministic switch, prompt-injection guard. Canonical facts confirmed unchanged: camp price `2150`, age `9-17`, location „ამბასადორი კაჭრეთი", manager phone `558 67 47 33`, registration `https://tinyurl.com/36jcae8z`, streams I `23-29 ივნისი` / II `5-11 ივლისი` / III `14-20 ივლისი`; `sunday_school` planned July (no month in YAML); adult „fromula 1" (`28 აგვისტო` / `monaco` / `5000` text vs `4999` gel / `min_age 13`) from `sections.yaml`; `data/events.txt` EMPTY. Live engine flags: `USE_PARENT_LLM_ENGINE=true`, `USE_ADULT_LLM_ENGINE=true`.

## 1. Executive summary

The prior audit is now **verified to a high degree** — the spine (webhook → message_buffer → conversation_service → parent_flow/adult_flow → engine/tools), the `camp_2026` direct readers, the live `system_parent_v2.md:293` hardcoded stream-date drift, the legacy/fallback classifications, the feature-flag defaults vs `.env` reality, conftest engine-OFF pinning, and the dead/empty data files are all CONFIRMED against `file:line`.

**Roughly 90%+ of the audit is CONFIRMED.** What remains genuinely STILL_UNKNOWN is small and carried forward (Section 8): live-LLM tool-call discipline (e.g. whether the model calls `check_consultation_slot` before saying „თავისუფალია"), PARENT prompt-injection robustness against novel/non-Georgian phrasings, and the exact reconciliation of the CRITICAL scenario count (raw `priority` field lines = **23**; distinct-ID mapping + the in-file comment + CLAUDE.md = **22**).

**Prior claims that CHANGED (corrections to the audit):**
1. **`summary.md` is LIVE, not orphaned (audit was WRONG).** `generate_summary` uses BOTH the inline `_SUMMARY_SYSTEM_MESSAGE` (system role) AND `SUMMARY_PROMPT` = `summary.md` (user message), and is reached on the live PARENT engine path via the `request_manager_callback` tool → `parent_tool_executor._request_manager_callback:1365`. **Do NOT archive `summary.md`.**
2. **`adult_defaults.yaml` is fully DEAD, and the audit's "mirrored in `data/prompts.ADULT_DEFAULT_*`" is IMPRECISE.** Those constants are independent hardcoded Python literals (`data/prompts.py:177-182`), not loaded from the YAML. The YAML has ZERO app readers (only a test + a migration tool).
3. **`content_repository.events_data` / `data/events.txt` are loaded-at-import but unreachable on the live flow** — `FlowContext` / `_flow_context` / `parent_flow.run` / `adult_flow.run` have ZERO callers; the live handlers take `(conversation, message)`.
4. **CRITICAL count discrepancy CONFIRMED-as-discrepancy** (not resolved): raw field count = 23, distinct/documented = 22. Carried forward.
5. **Direct `camp_2026.yaml` reader count was UNDERCOUNTED** by the audit (it lists 5; a full grep shows 10+), but only the 2 in `parent_llm_engine` are on the live engine path, so the audit's live-impact conclusion holds.
6. **Scheduler "Sender NOT yet wired" (CLAUDE.md) is STALE** — `main.py:70-84` wires `followup_service.check_and_send_followups`, which fires real DMs.

**The single safest next action:** add a date-frozen, engine-ON, OpenAI-mocked **prompt-leak regression test** for camp stream dates, then remove the hardcoded stream dates from `system_parent_v2.md:293` (the #1 live fact-drift). This is independent of router normalization and is the only change that improves ACTUAL agent correctness with HIGH confidence. Everything else stays untouched until `scenario_runner_full --priority CRITICAL` + the live Meta booking-conflict smoke are green.

## 2. The 8 UNVERIFIED items — resolution

| # | Item | Verdict | Evidence (file:line) | Runtime impact | Safe-now? | More testing? |
|---|---|---|---|---|---|---|
| 1 | `summary.md` consumer — orphaned vs live manager-handoff | **REFUTED** (audit WRONG; it IS live) | `data/prompts.py:146`; `openai_service.py:348,352-353`; `parent_tool_executor.py:1365`; `parent_tools.py:34` | LIVE — feeds `lead.conversation_summary` → manager email/handoff | **NO** — do NOT archive | Keep `scenario_runner_full` `request_manager_callback` path + `test_parent_llm_engine` summary tests green |
| 2 | `detect_segment.md` live caller | **CONFIRMED** dead | `openai_service.py:163,166,482,493`; repo grep: no `OpenAIService(` instantiation | None (caller class never instantiated) | Archive only if `DETECT_SEGMENT` import handled; otherwise NO | `test_prompt_loader` byte-identity; import-clean check |
| 3 | `USE_LLM_TURN_ANALYZER` reachability | **CONFIRMED** flag-gated AND fallback-only | `config.py:294`(default False); `.env`=true; `parent_turn_router.py:877,944,948`; `parent_flow.py:310,401,403,4632` | Inert under live config (engine returns first) | NO removal | Legacy `parent_turn_router`/`parent_turn_analyzer` suites (engine-OFF conftest) |
| 4 | `adult_defaults.yaml` read by live adult engine | **CONFIRMED** dead (audit "mirrored" claim IMPRECISE) | `adult_llm_engine.py` (no match); `:1859`+`adult_tool_executor.py:299` (= `sections.yaml`); `data/prompts.py:177-182` (hardcoded literals); only `test_knowledge_loader.py:125` + `verify_knowledge_migration.py:124` | None on live path | NO (keep the `ADULT_DEFAULT_*` constants — legacy fallback imports them) | Update those 2 references before archiving the YAML |
| 5 | `content_repository.events_data` reachability | **CONFIRMED** loaded-but-dead | `conversation_service.py:344,353,390,396,867`; `data/events.txt:1-22` (blank fields) | None (`FlowContext` never constructed) | NO deletion (config.EVENTS read at import) | Import smoke + comment-flow tests |
| 6 | Sticky PARENT→ADULT switch (deterministic vs LLM) | **CONFIRMED** LLM-tool-only; no deterministic flip | `conversation_service.py:472-478,486-495,242-254`; `parent_tools.py:39`; `parent_tool_executor.py:2077` | Real gap — trap risk if engine short-circuited | NO code change without tests | New scenario: sticky-PARENT + clear adult-event message |
| 7 | PARENT prompt-injection guard | **CONFIRMED** prompt+sanitizer-only; no deterministic guard, no explicit anti-injection rule | `parent_flow.py` (grep clean); `system_parent_v2.md` (no injection/jailbreak match); `scenario_library.py:1176/1207/1320/1333/1346` (SC-62/64/71/72/73) | LLM-compliance-only resistance | NO removal of any sanitizer | SC-62/64/71/72/73 must stay green; adversarial suite before hardening |
| 8 | CRITICAL scenario count 22 vs 23 | **PARTIAL / STILL_UNKNOWN reconciliation** | `scenario_library.py` 22 distinct mapped IDs vs **23 `"priority":"CRITICAL"` field lines (grep confirms 23; 24 total occurrences, 1 non-field)**; comment `:1385` says "exactly 22"; CLAUDE.md says 22 | Gate counts dynamically → live count is whatever the file holds | Informational only | Re-run flaky CRITICALs twice; reconcile `:1385` comment vs raw count before relying on "22/22" |

**Note on item 8:** the two inventory verifiers disagree (one maps 22 distinct IDs; the other counts 23 `priority` fields). My direct grep returns **23** `"priority": "CRITICAL"` lines and **24** total `CRITICAL` occurrences (one is the non-field schema comment at `:78`). The in-file comment at `:1385` and CLAUDE.md both assert **22**. This is a real doc/comment-vs-field-count discrepancy; it is **carried forward as STILL_UNKNOWN** (Section 8) and must NOT be treated as resolved.

## 3. Corrected runtime inventory table

Every verifier row is preserved. **CORRECTED** marks where this sweep changes the audit's recommendation.

| Path | Previous rec. | VERIFIED rec. | Evidence (file:line) | Conf. | Action-now? | Notes |
|---|---|---|---|---|---|---|
| `app/routes/webhook.py` | KEEP_PRIMARY | KEEP_PRIMARY | `webhook.py:335,357,452` | HIGH | Only delete `[webhook_debug]`/`[comment_debug]` temp logs | Live DM + comment entry |
| `app/services/message_buffer.py` | KEEP_PRIMARY | KEEP_PRIMARY | `webhook.py:335` | HIGH | No | Per-process debounce (single-worker only) |
| `app/services/conversation_service.py` | KEEP_PRIMARY | KEEP_PRIMARY | `conversation_service.py:443,472-495,516,518` | HIGH | No | Sole DM router chokepoint |
| `app/flows/parent_flow.py` `handle` | KEEP_PRIMARY | MERGE_LATER_WITH_TESTS | `parent_flow.py:92,205,310,403,440` | HIGH | No | 15-interceptor chain; engine-first |
| `app/agent/llm/parent_llm_engine.py` | KEEP_PRIMARY | KEEP_PRIMARY | `parent_llm_engine.py:1922,1924,2194` | HIGH | No | Brain; 2 direct `camp_2026` reads bypass `get_camp_facts` |
| `FORBIDDEN_PHRASE_REPLACEMENTS` (184) | KEEP/MERGE | MERGE_LATER_WITH_TESTS | `parent_llm_engine.py:655,1598,1619` | HIGH | No | AST-confirmed exactly 184 |
| `_capture_turn_facts`/`_suppress_redundant_age_question`/`_strip_mid_conversation_greeting` | KEEP_PRIMARY | KEEP_PRIMARY / MERGE_LATER | `parent_llm_engine.py:1742,1795,1683,1721` | HIGH | No | Pre-turn capture + anti-repeat |
| `app/agent/tools/parent_tool_executor.py` | KEEP_PRIMARY | DO_NOT_TOUCH_PROTECTED | `parent_tool_executor.py:141,64,120,68` | HIGH | No | Security boundary / side-effect gate |
| `app/agent/llm/adult_llm_engine.py` | KEEP_PRIMARY | KEEP_PRIMARY | `adult_llm_engine.py:2219,2221,1961,1359,1859` | HIGH | No | Adult brain; no Calendar |
| `app/agent/tools/adult_tool_executor.py` | KEEP_PRIMARY | KEEP_PRIMARY | `adult_tool_executor.py:299,641,52,122` | HIGH | No | `get_active_adult_events` = `sections.yaml` |
| Legacy: `_handle_impl`/`parent_reply_composer`/`parent_turn_analyzer`/`parent_turn_router` | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `parent_flow.py:4632,403,5928`; `conversation_service.py:820` | HIGH | No | Cold, NOT dead |
| `app/flows/adult_flow.py` | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `adult_flow.py:200,422`; `conversation_service.py:518` | HIGH | No | Never live-tested e2e |
| `app/services/openai_service.py` `generate_*` | KEEP_FALLBACK (audit imprecise on summary) | **CORRECTED** KEEP_FALLBACK; `generate_summary` uses BOTH `_SUMMARY_SYSTEM_MESSAGE` + `SUMMARY_PROMPT` | `openai_service.py:337,348,352,495,493`; `parent_flow.py:4964,4874` | HIGH | No | Audit's "inline NOT this" sentence is wrong |
| `app/agent/llm/prompt_loader.py` | KEEP_PRIMARY | KEEP_PRIMARY / CANONICAL | `prompt_loader.py:49,57,76` | HIGH | No | Single cached prompt loader |
| `system_parent_v2.md` (451 lines) | KEEP_PRIMARY | KEEP_PRIMARY but **REMOVE_FROM_LIVE_PROMPT** line 293 (gated) | `system_parent_v2.md:293` (en-dash streams) | HIGH | Yes, **with test** | #1 live fact-drift |
| `system_adult_v1.md` (244 lines) | KEEP_PRIMARY | KEEP_PRIMARY | `adult_llm_engine.py:2219` | HIGH | No | Fact-clean |
| `system_parent.md` (legacy, full facts) | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `system_parent.md:4-9`; `data/prompts.py:36` | HIGH | No | Hardcodes all facts; legacy-only |
| `system_base.md` | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `data/prompts.py:35` | HIGH | No | Fact-clean legacy |
| `system_adult.md` | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `data/prompts.py:37` | HIGH | No | Legacy adult role |
| `parent_turn_analyzer.md` | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `parent_turn_analyzer.py:289` | HIGH | No | Analyzer JSON classifier |
| `parent_present_value.md` | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `data/prompts.py:80`; `parent_flow.py:4939` | HIGH | No | Legacy discovery path |
| `parent_communication_style.md` | DEAD/no caller | ARCHIVE_SAFE_NO_RUNTIME_IMPACT | `parent_communication_style.md:3-6`; no app caller | HIGH | Only with byte-identity test update | Self-declares reference-only |
| `detect_segment.md` | UNVERIFIED → | **CONFIRMED** ARCHIVE_SAFE_NO_RUNTIME_IMPACT (dead) | `openai_service.py:493,486`; no instantiation | HIGH | No (carry as gated cleanup) | Caller class never instantiated |
| `detect_start_intent.md` | KEEP_FALLBACK | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `parent_flow.py:4874`; `openai_service.py:180` | HIGH | No | Legacy routing label |
| `detect_comment_intent.md` | KEEP | KEEP_FALLBACK / KEEP_PRIMARY (comment) | `webhook.py:518`; `comment_service.py:820` | HIGH | No | Comment pipeline |
| `summary.md` | ARCHIVE (audit) | **CORRECTED** KEEP_PRIMARY / KEEP_FALLBACK (LIVE) | `openai_service.py:348`; `parent_tool_executor.py:1365`; `data/prompts.py:146` | HIGH | **No — do NOT archive** | Biggest section-2 correction |
| `parent_sales_policy.md` + `adult_sales_policy.md` | reference | ARCHIVE_SAFE / DOC_ONLY (fix false header) | grep `sales_policy` empty; `parent_sales_policy.md:4-6` | HIGH | Yes (header text fix only) | "engine reads" claim is false |
| `data/admin_config/sections.yaml` | KEEP_PRIMARY | KEEP_PRIMARY / CANONICAL / DO_NOT_TOUCH_PROTECTED (values) | `sections.yaml:13-34,47-74`; `admin_config_service.py:494` | HIGH | No (operator data) | All canonical facts |
| `app/agent/knowledge/camp_2026.yaml` | KEEP fallback | KEEP_FALLBACK_DO_NOT_TOUCH_YET | `camp_2026.yaml`; `parent_llm_engine.py:1924/2194`; `comment_service.py:194`; `parent_turn_router.py:118`; `parent_reply_composer.py:180`; `parent_turn_analyzer.py:146` | HIGH | No | Agrees w/ sections today; MERGE direct readers later |
| `app/agent/knowledge/business_hours.yaml` | KEEP_PRIMARY | KEEP_PRIMARY / CANONICAL | `calendar_service.py:30,35-36` | HIGH | No | Booking source of truth |
| `data/admin_config/business_hours.yaml` | display mirror | DOC_ONLY (label non-authoritative) | `admin_config_service.py:1803,63`; `admin.py:749` | HIGH | Yes (label only) | Operator hazard |
| `app/agent/knowledge/i18n/ka_months.yaml` | KEEP_PRIMARY | KEEP_PRIMARY / CANONICAL | `calendar_service.py:64` | HIGH | No | Date parsing dependency |
| `data/events.txt` | loaded-but-empty | KEEP_FALLBACK_DO_NOT_TOUCH_YET (mark DOC_ONLY) | `config.py:170`; `conversation_service.py:344`; `comment_service.py:111`; `data/events.txt:1-22` | HIGH | No removal | Read at import; blank templates |
| `data/knowledge_base.txt` | loaded-but-empty | KEEP_FALLBACK_DO_NOT_TOUCH_YET (mark template) | `config.py:166`; `conversation_service.py:343`; `followup_service.py:190` | HIGH | No removal | Bracket placeholders only |
| `content_repository.events_data` plumbing | UNVERIFIED → | **CONFIRMED** ARCHIVE_SAFE (dead `run()`/`FlowContext`) | `conversation_service.py:396,867,4850`; `adult_flow.py:271` | HIGH | No | Separate gated cleanup |
| `app/agent/knowledge/manager_contacts.yaml` | placeholders | CONSOLIDATE (phone chain) / DOC_ONLY | `admin_config_service.py:1768,1810`; `admin.py:750` | HIGH | No | No phone key; chain falls through |
| `app/agent/knowledge/company.yaml` | KEEP_PRIMARY | KEEP_PRIMARY / CANONICAL (phone) | `admin_config_service.py:1787`; `parent_turn_router.py:122` | HIGH | No | De-facto canonical `558 67 47 33` |
| `audience_segments.yaml` + `followup_strategy.yaml` | KEEP_PRIMARY | KEEP_PRIMARY | `followup_service.py:70`; both present | MED | No | `audience_segments` readers not exhaustively traced |
| `app/agent/knowledge/adult_defaults.yaml` | UNVERIFIED → | **CONFIRMED/CORRECTED** ARCHIVE_SAFE (dead; "mirrored" reversed) | grep empty in app/; only `verify_knowledge_migration.py:124-127`; `data/prompts.py:177-182` | HIGH | No removal yet | Update verify-tool first |
| `data/admin_config/templates.yaml` | DOC_ONLY | DOC_ONLY / KEEP (comment) | `templates.yaml:9,34`; `comment_service.py:180` | HIGH | Yes (operator may populate) | `{events_list}` placeholder |
| `data/prompts.py` | alias layer | KEEP_PRIMARY / DO_NOT_TOUCH_PROTECTED | `data/prompts.py:177-182`; `conversation_service.py:12` | HIGH | No | Holds hardcoded `ADULT_DEFAULT_*` literals |
| Feature flags (`config.py`) | confirmed | KEEP_PRIMARY; DOC_ONLY fix CLAUDE.md drift | `config.py:307/322/380/360/371/240-242/352/389/341/486/212/394/283/294`; `.env:84,85` | HIGH | Yes (doc fix) | `.env` OMITS `USE_ADULT`/`FOLLOWUP_TEST_MODE`/`FOLLOWUP_FIRST_DELAY_SECONDS` |
| `USE_LLM_TURN_ANALYZER` | UNVERIFIED → | **CONFIRMED** LEGACY_OFF effectively | `parent_turn_analyzer.py:289`; `parent_turn_router.py:877` | HIGH | No | Reachable only via fallback |
| `USE_LLM_COMPOSER` | DEAD | KEEP_FALLBACK_DO_NOT_TOUCH_YET (LEGACY_OFF) | `config.py:283`; `.env:83`; `parent_reply_composer.py:294` | HIGH | No | Never on |
| `tests/conftest.py` autouse pinning | KEEP_PRIMARY | KEEP_PRIMARY / DO_NOT_TOUCH_PROTECTED | `conftest.py:34-120` (5 autouse fixtures) | HIGH | No | Bulk pytest = legacy path, not live gate |
| `tools/scenario_runner_full.py` | KEEP_PRIMARY | KEEP_PRIMARY / CANONICAL net | `scenario_runner_full.py:81,317-334,621,735,1172` | HIGH | No (use as gate) | Only real-LLM live gate |
| CRITICAL scenario count | off-by-one | **STILL_UNKNOWN** (23 raw fields vs 22 distinct/doc) | `scenario_library.py` grep=23; `:1385` comment="22"; CLAUDE.md="22" | HIGH (count) / — (reconciliation) | Yes (doc reconcile only) | See Section 8 |
| Test families + docs | classified | TEST_ONLY / KEEP_PRIMARY / ARCHIVE_SAFE (historical docs) | file listing | MED | Docs archive yes | Not every test body opened |
| Scheduler doc-drift | confirms audit | DOC_ONLY fix CLAUDE.md; `followup_service.py` KEEP_PRIMARY | `main.py:70-84`; `followup_service.py:351,259` | HIGH | Yes (doc) | "Sender NOT yet wired" is STALE |

## 4. Corrected router priority table (25 intents)

Pre-engine interceptor order in `parent_flow.handle` (lines 92-404): **#1** Sunday → **#2** static-welcome → **#3** memory-info → **#4** requalify → **#5** resume-ack → **#6** event-inquiry → **#7** camp-registration; then inside `if engine_flag:` → **#8** decline → **#9** reschedule → **#10** underage-handoff → **#11** explicit-manager → **#12** contact-correction → **#13** contact-collection → **#14** commit-booking (`handle:291`) → **#15** full-contact-on-intent (`handle:302`) → engine → 13 post-engine sanitizers → final `_sanitise_booking_confirmation`.

| Intent | Handler (file:function) | Priority order | Det. vs LLM | Overlap / conflict | Status | Live coverage |
|---|---|---|---|---|---|---|
| 1 greeting | `conversation_service._is_pure_greeting` + `parent_flow._maybe_static_welcome` (#2) | classify→UNCLEAR; #2 | Deterministic | none | fixed | row 278 |
| 2 camp info | classify(CAMP) → engine `get_camp_info` | route det / answer LLM | LLM answer | none | fixed | row 279 |
| 3 camp registration | `_maybe_handle_camp_registration_link` (#7) | #7 pre-engine | Deterministic | `ფორმა` token-bounded | fixed | well-tested |
| 4 price | classify; camp→engine; event→#6 | mixed | det route / LLM answer | 2150-vs-event leak closed by #6 | fixed | row 281 |
| 5 price objection | `_maybe_handle_decline_engine` defers (#8) | #8 (defers) | LLM by design | substring race w/ #6 decline | open-but-patched (quick-win override set) | row 282 |
| 6 real decline | `_maybe_handle_decline_engine` (#8) | #8 | Deterministic | override-interest defers | fixed | row 283 |
| 7 event interest | classify(ADULT) → `adult_flow.handle` | route det / answer LLM | none | fixed | row 284 |
| 8 negated event („ღონისძიება არ მინდა") | `_classify_segment` (no negation) | classify→ADULT | LLM-only recovery | flips to ADULT first | **open / architecture** (negation is LLM-only) | row 285 (now CONFIRMED-as-gap) |
| 9 Sunday School | `_maybe_handle_*sunday*` / `_is_sunday_school_intent` (#1) | **#1 highest** | Deterministic | hardcoded „ივლისი" not from YAML | fixed (data-truth = architecture) | 34 tests |
| 10 manager phone (eligible) | `_maybe_handle_explicit_manager_request` (#11) | #11 | Deterministic | #10/#11 shadow | quick-win (duplicated check) | tested |
| 10b manager phone (under-age) | `_maybe_handle_underage_manager_handoff` (#10) | #10 | Deterministic | duplicates #11 number-check | quick-win | tested |
| 11 consultation booking | `_maybe_commit_pending_booking_engine` (#14) + executor `book_consultation` | #14 / LLM tools | det commit / LLM decision | densest triad #13/#14/#15 | fixed | row 288 |
| 12 date/time | det timestamps + `_repair_colloquial_hour_rejection` (post `handle:318`) | post-engine | det parse / LLM slot | folded into #14 | fixed | row 288 |
| 13 contact capture | `_maybe_handle_contact_collection` (#13) | #13 | Deterministic | **densest overlap** #13/#14/#15 | **open / architecture** (consolidate) | tested |
| 14 contact correction | `_maybe_handle_contact_correction` (#12) | #12 (before #13) | Deterministic | must precede #13 | fixed | tested |
| 15 state recall | `_maybe_memory_info_reply` (#3) | #3 | Deterministic | privacy-critical (omits PII) | fixed | row 291 |
| 16 PARENT→ADULT | `switch_to_adult_flow` tool → `_switch_to_adult_flow:2077` | LLM-only | **LLM-only** | no deterministic flip | open (intended; flagged gap) | row 292 (UNVERIFIED→CONFIRMED LLM-only) |
| 17 ADULT→PARENT | `_is_parent_consultation_intent` (`conversation_service:486-495`) + engine `_user_wants_parent_flow` | deterministic override | Deterministic + LLM | asymmetric (only flip) | fixed | row 293 |
| 18 gratitude only | none (PARENT); `_strip_unwarranted_thanks…` (post `handle:378`) | post-engine strip only | LLM (PARENT) / det (ADULT) | token-cost only | open / deferred (operator) | row 294 (CONFIRMED mixed) |
| 19 gratitude + question | engine answers | engine | LLM | none | fixed | row 295 (MED — stochastic) |
| 20 off-topic / injection | ADULT `_maybe_adult_offtopic_reply` (det); PARENT none | asymmetric | det (ADULT) / prompt-only (PARENT) | PARENT unguarded | **open / architecture** (PARENT gap) | row 296 |
| 21 underage handoff | `_maybe_handle_underage_manager_handoff` (#10) | #10 | Deterministic + real dispatch | #10/#11 shadow closed | fixed | 28 tests |
| 22 booking confirmation | `_sanitise_booking_confirmation:515` (final chokepoint) | final | Deterministic SAFETY | fake-booking guard | fixed / DO_NOT_TOUCH_PROTECTED | §6 boundary |
| 23 reschedule/cancel | `_maybe_handle_reschedule_intent_engine` (#9) + `_manage_consultation_booking:1587` | #9 entry / LLM execute | det entry / LLM execute | safe-ordering | fixed | interceptor #9 |
| 24 stream dates | classify(camp) → engine `get_camp_info` (date-filtered) | engine | LLM (filtered) | **prompt-hardcoded streams `system_parent_v2.md:293`** | open / MERGE (see §6) | row 192 (MED) |
| 25 registration-vs-info overfire | `_CAMP_FORM_TOKEN_RE` (#7) + `conversation_service._is_registration_link_request:315` | #7 | Deterministic | „ინფორმაცია" ⊃ „ფორმა" closed | fixed / tested | row 280 |

## 5. Duplicate fact source verification (A–O)

| Fact | Canonical source | Current direct readers | Stale-source risk | In prompt? | In YAML? | In admin_config? | Migration rec. |
|---|---|---|---|---|---|---|---|
| **A. price 2150** | `sections.yaml:15-16` via `get_camp_facts` (`admin_config_service.py:573-586`) | `parent_tool_executor:335-356` (via chokepoint); legacy direct: `comment_service:194`, `parent_turn_router:118`, `parent_reply_composer:180`, `parent_turn_analyzer:146` | Admin-only edit invisible to legacy direct readers | No (prompt forces tool) | `camp_2026.yaml:18` (fallback) | `sections.yaml` (canonical) | MERGE direct readers → `get_camp_facts` (Phase 2) |
| **B. streams I/II/III** | `sections.yaml:25-34` via `get_camp_info` date-filter (`admin_config_service.py:1126-1222`) | `parent_tool_executor:358-367,428-431` (filtered) | **`system_parent_v2.md:293` hardcodes all 3 (en-dash), bypasses filter** | **YES (`:293`)** | `camp_2026.yaml:20-23` | `sections.yaml` | **REMOVE_FROM_LIVE_PROMPT `:293`** + MERGE legacy readers |
| **C. location ამბასადორი კაჭრეთი** | `sections.yaml:13` via `get_camp_facts:553-559` | `parent_tool_executor:369-374` | none today | `:288` (example tone only, not a source) | `camp_2026.yaml:14` | `sections.yaml` | None (KEEP_PRIMARY) |
| **D. included items** | `sections.yaml:35-39` via `get_camp_facts:614-624` (dual-key) | `parent_tool_executor:344,384,427` | none | No | `camp_2026.yaml:19` | `sections.yaml` | KEEP_PRIMARY |
| **E. discounts (10%/10%)** | `sections.yaml:40-42` (strings) via `get_camp_facts:614-624` | `parent_tool_executor:345-349` (coerces) | shape divergence (strings → `percent=None`; dicts → `percent:10`) | No | `camp_2026.yaml:24-26` (dicts) | `sections.yaml` | Cosmetic-only; MERGE if numeric needed |
| **F. registration URL** | `sections.yaml:20` via `get_camp_facts:553-559` | `parent_tool_executor:396-414`; `parent_flow:2563-2595` | none | No | `camp_2026.yaml:30` | `sections.yaml` | KEEP_PRIMARY |
| **G. age 9-17** | `sections.yaml:11-12` via `get_camp_facts` | TOOL band `parent_tool_executor:381-394`; **PROMPT band + eligibility `parent_llm_engine:1924,2194` read `camp_2026` DIRECTLY** | Admin-only age edit → prompt(camp_2026) ≠ tool(admin) | YES (`{age_min}{age_max}` from `camp_2026`) | both `:11-12` / `:15-16` | `sections.yaml` | MERGE the 2 live-path direct reads → `get_camp_facts` |
| **H. manager phone 558 67 47 33** | disclosure: `company.yaml:6` via `get_manager_phone:1754-1800`; camp-display: `sections.yaml:21` via `get_camp_facts:632-639` | both chains | two independent chains (divergence if either edited alone) | No | `company.yaml` / `sections.yaml` | `manager_contacts.yaml` has NO phone key | CONSOLIDATE onto `get_manager_phone` |
| **I. manager email** | `.env MANAGER_EMAIL` via `notification_service:790-833` | sender only | mirror `manager_contacts.yaml:8 email_placeholder` NOT read | No | No | display-only placeholder | DOC_ONLY (operator hazard) |
| **J. business hours 10-21 / slot 60 / buffer 120** | `app/agent/knowledge/business_hours.yaml:11-29` (booking reads) | `calendar_service`; `parent_flow` buffer | mirror `data/admin_config/business_hours.yaml` NOT read (manual-sync hazard) | No | both (canonical + mirror) | display mirror via `:1803-1807` | Label mirror non-authoritative |
| **K. Sunday-closed / Sat-open** | `calendar_service.py:48 CLOSED_WEEKDAYS={6}` (code only) | `is_closed_booking_day:51-57` | none (intentional code-only) | No | No | No | KEEP_PRIMARY / DO_NOT_TOUCH |
| **L. adult „fromula 1"** | `sections.yaml:121-131` via `get_active_adult_events:1225-1257` | `adult_tool_executor:298-299` | internal `price_text 5000` vs `price_gel 4999`; section-level adult facts `:84-101` are dead shadow; `data/events.txt` EMPTY | No | `sections.yaml` | `sections.yaml` | Operator data fix (price conflict); `events.txt` ARCHIVE_SAFE |
| **M. Sunday-School (planned July)** | YAML `sections.yaml:47-74 status:coming_soon` (no month); **live answer Python-hardcoded „ივლისი" `parent_flow.py:2298-2302`** | `_is_sunday_school_intent:2331-2338` | „July" only in Python — admin plan changes have ZERO effect | No (Python const) | `sections.yaml` (status only, no month) | `sections.yaml` | MERGE month → YAML (KEEP_PRIMARY hardcode today) |
| **N. follow-up cadence 24/72/168h** | `followup_service.py:69-89 _FOLLOWUP_CADENCE` (code) | scheduler | aligned w/ `followup_strategy.yaml:14-58` | No | `followup_strategy.yaml` | No | KEEP_PRIMARY both (stage names load-bearing) |
| **O. WhatsApp enablement** | `.env`/settings via `notification_service:861-879` (`is_whatsapp_configured` gate) | sender only | mirror `manager_contacts.yaml:9-10` placeholders NOT read | No | No | display-only | DOC_ONLY / ARCHIVE_SAFE |

**Precision correction:** the audit lists **5** direct `camp_2026.yaml` readers; a full `app/` grep shows **10+** (`config.py:446`, `parent_tool_executor.py:313/873/2041`, `parent_llm_engine.py:1924/2194`, `parent_flow.py:1689/1948/5856`, `parent_turn_router.py:118`, `parent_reply_composer.py:180`, `parent_turn_analyzer.py:146`, `comment_service.py:194`). Only `parent_llm_engine:1924/2194` are on the live engine path; the rest are legacy/fallback/comment/boot. The audit's live-path conclusion stands; plan the migration against **10+**, not 5.

## 6. line-293 cleanup safety verdict

**Exact line — `app/agent/prompts/system_parent_v2.md:293` (single occurrence, confirmed by grep):**

```
ბანაკის ნაკადები (23–29 ივნისი / 5–11 ივლისი / 14–20 ივლისი) = მხოლოდ პროგრამის თარიღები.
```

It sits inside the „კონსულტაცია vs ბანაკის ნაკადები" teaching block (`:291-295`) whose purpose is to teach the model that a consultation date ≠ a camp stream date. The dates are **illustrative**, use an **en-dash** (`–`) while `sections.yaml`/`camp_2026.yaml` use a hyphen (`-`), and **bypass both `sections.yaml` and the `is_camp_stream_visible` date-filter** — so the prompt can still emit a stale stream (e.g. „23–29 ივნისი" on/after Jun 23 when the tool would hide it).

**VERDICT: `SAFE_WITH_TEST`.**
- Behavioral risk of removal is LOW and a net correctness gain — the answer template at `:286-288` already mandates `get_camp_info("dates")`/`"conditions"` and the tool reliably returns date-filtered `visible_streams` (`parent_tool_executor.py:331-367,428-431`; `admin_config_service.py:1126-1222`; year resolves via `camp_2026.yaml:10 year:2026` → merged → current Tbilisi year).
- **BUT** the only live-LLM net (`scenario_runner_full`) has **zero** stream-date assertions (every camp first-turn asserts `AGE_ASKED`; date tokens appear only in mocked `manual_simulation_*` scripts + `verify_knowledge_migration` + stale HTML). `test_camp_stream_date_filter_2026_06_20.py` covers the FILTER helper + `get_camp_info`, not the PROMPT-leak path.

**Required test before touching `:293`:** a date-frozen, **engine-ON, OpenAI-mocked** prompt-leak regression that drives `run_parent_llm_turn` for a „ნაკადები როდისაა" turn and asserts the reply's stream dates equal `get_visible_camp_streams` output (NOT a hardcoded literal) — frozen to a date where a stream has hidden (e.g. `2026-06-23` → „23-29 ივნისი" must NOT appear). Plus one `scenario_runner_full` CRITICAL/IMPORTANT date scenario forbidding a started/stale stream. Do NOT rely on bulk pytest (conftest pins engines OFF).

**Before or after router normalization:** **INDEPENDENT — do it BEFORE / regardless of router normalization.** Line 293 is purely prompt-internal and orthogonal to `_classify_segment`, the 15 interceptors, and the booking/name/decline guards. The audit's own phased plan treats prompt fact-slimming as an earlier, lower-risk step. **Sequence:** add the prompt-leak test → replace the parenthetical literal dates with a generic phrase (e.g. „ბანაკის ნაკადების თარიღები") so the consultation-vs-stream lesson survives → run the new test + `scenario_runner_full --priority CRITICAL`.

## 7. Test / gate reliability

**RELIABLE gates (meaningful alone):**
- `tools/scenario_runner_full.py --priority CRITICAL` — the ONLY real-LLM live gate (`USE_REAL_LLM=True:81`, `force_engine_on():317-334`, `force_redis_off()`, real OpenAI, only Calendar/Sheets/Notification/Meta mocked; exit 1 iff any CRITICAL fails `:1172`).
- Loader/contract suites: `test_template_loader`, `test_knowledge_loader`, `test_prompt_loader`, `test_template_render_equivalence` (byte-identity).
- `test_redis_persistence`, `test_notification_service`, `test_kill_switch`, `test_sentry_service`, `test_webhook_signature`, `test_admin_*`, follow-up cadence math.

**WEAK / misleading-if-run-alone:**
- The **16** engine-ON parent test files + `test_adult_llm_engine.py` — they set `USE_PARENT_LLM_ENGINE=True` but still **stub** `openai_service.chat_with_tools` / `run_parent_llm_turn` with scripted replies. Green here proves engine **WIRING** (tool dispatch, executor validation, sanitizers, interceptor order) but NOT real-model wording or tool-call discipline.
- **Bulk `pytest tests/` green is MISLEADING as live-readiness** — the 5 autouse conftest fixtures pin `USE_PARENT_LLM_ENGINE=False`, `USE_ADULT_LLM_ENGINE=False`, prod follow-up cadence, Redis OFF, and block SMTP/Meta HTTP → the bulk suite exercises the LEGACY state machine, not the live brain.

**Required live-smoke list (before any production go):**
1. `scenario_runner_full.py --priority CRITICAL` green (real OpenAI, ~3-5 min).
2. Live Meta booking-conflict smoke (CLAUDE.md): „გამარჯობა" → „ბანაკი" → „14 წლის" → „კონსულტაცია" → phone → „16 საათზე" on a busy date; agent must NOT confirm a busy slot (real tool-call discipline is only provable live).

**Required scenario_runner list:** at minimum `--priority CRITICAL` (the CRITICAL set — see Section 8 count caveat). Full 74-scenario run only with explicit permission ($1-3).

**conftest engine-OFF confirmation:** CONFIRMED — `tests/conftest.py` `_force_adult_llm_engine_off` (`:34-52`), `_force_parent_llm_engine_off` (`:55-67`), `_force_followup_production_cadence` (`:70-92`), `_force_redis_disabled` (`:95-120`, `REDIS_ENABLED=False` at `:117`), `_block_real_smtp` (`:123-157`), `_block_real_meta_http` (`:160-190`). Note: the `:75` comment claims `.env` keeps `FOLLOWUP_TEST_MODE=true` but `.env` actually OMITS it (stale, like CLAUDE.md).

## 8. Remaining uncertainties (STILL_UNKNOWN — carry forward, do NOT act on)

1. **CRITICAL scenario count reconciliation.** Raw grep = **23** `"priority": "CRITICAL"` field lines (24 total `CRITICAL` occurrences, 1 non-field at `:78`); the in-file comment `scenario_library.py:1385` and CLAUDE.md both assert **22**; one verifier maps 22 distinct IDs (treating one as non-distinct), the other counts 23 fields. The runner counts dynamically, so the enforced gate is whatever the file holds. **Do NOT treat as resolved.** Reconcile the `:1385` comment vs the raw field count before relying on "22/22" phrasing.
2. **Real-LLM tool-call discipline** — whether the live model actually calls `check_consultation_slot` before saying „თავისუფალია" is provable ONLY by the live Meta booking-conflict smoke (stubbed engine-ON tests do not cover it).
3. **PARENT prompt-injection robustness** — resistance is prompt+sanitizer-only with no deterministic guard; novel/non-Georgian/Latin injection phrasings beyond SC-62/64/71/72/73 rely entirely on LLM compliance.
4. **Sticky-PARENT→ADULT trap** — an explicit adult-event message in a sticky-PARENT conversation switches only if the LLM chooses `switch_to_adult_flow`; if a pre-engine interceptor short-circuits, it may be answered in PARENT context. No deterministic guarantee.
5. **Negated event interest** („ღონისძიება არ მინდა") flips segment to ADULT at the deterministic substring layer; negation recovery is LLM-only.
6. **`audience_segments.yaml` readers** not exhaustively traced this pass (audit lists it as supporting/KEEP_PRIMARY; no contradiction found — MEDIUM confidence).
7. **Per-file test-body classification** — the ~96 test files were classified by the verified conftest/stub pattern + audit cross-check, not an exhaustive per-file read (MEDIUM confidence on the bucket feed).

## 9. CLEANUP DECISION MATRIX

> Only HIGH-confidence, code-grounded files appear in `REMOVE_FROM_LIVE_PROMPT_NOW` or `ARCHIVE_SAFE_NO_RUNTIME_IMPACT`. Anything STILL_UNKNOWN → `KEEP_FALLBACK_DO_NOT_TOUCH_YET`.

| Path | Current role | Bucket | Why | Evidence (file:line) | Behavior-impact-if-removed | Expected-benefit-if-cleaned | Required-test-before-touching | Safe-next-action | Conf. |
|---|---|---|---|---|---|---|---|---|---|
| `system_parent_v2.md:293` (stream dates) | Live PARENT prompt teaching block w/ hardcoded streams | **REMOVE_FROM_LIVE_PROMPT_NOW** | Hardcoded en-dash streams bypass YAML + date-filter; can emit stale stream | `system_parent_v2.md:293` | Forces tool call for dates (desired); kills stale-date leak | #1 fact-drift fixed; single source = `get_camp_info` | Prompt-leak regression (engine-ON, mocked, date-frozen) + 1 scenario | Add test → replace literal w/ generic phrase → run CRITICAL | HIGH |
| `app/agent/prompts/parent_communication_style.md` | Reference-only prompt, no caller | **ARCHIVE_SAFE_NO_RUNTIME_IMPACT** | Zero app callers; self-declares reference material | `parent_communication_style.md:3-6`; grep empty | None | Repo clarity | Update `test_template_render_equivalence.py:96` in lockstep | Move to `docs/` w/ test update | HIGH |
| `app/agent/prompts/detect_segment.md` | Legacy classifier prompt | **ARCHIVE_SAFE_NO_RUNTIME_IMPACT** | Caller `OpenAIService.generate_reply` never instantiated | `openai_service.py:493,486,482`; grep no `OpenAIService(` | None | Removes dead path | `test_prompt_loader` byte-identity; handle `DETECT_SEGMENT` import | Leave import; archive `.md` only w/ tests | HIGH |
| `app/agent/knowledge/adult_defaults.yaml` | Dead adult placeholder YAML | **ARCHIVE_SAFE_NO_RUNTIME_IMPACT** | No app reader; only test + verify-tool | grep empty in app/; `verify_knowledge_migration.py:124-127` | None on live or fallback path | Removes confusing dead YAML | Update `test_knowledge_loader.py:125` + `verify_knowledge_migration.py:124-127` | Archive after updating those 2 | HIGH |
| `app/agent/policies/parent_sales_policy.md` | Reference doc (false "engine reads" header) | **ARCHIVE_SAFE_NO_RUNTIME_IMPACT** / DOC_ONLY | No Python loader reads it | grep `sales_policy` empty; `:4-6` false claim | None | Removes misleading header | None | Fix header text (zero runtime impact) | HIGH |
| `app/agent/policies/adult_sales_policy.md` | Reference doc | **ARCHIVE_SAFE_NO_RUNTIME_IMPACT** / DOC_ONLY | No loader reads it | grep `sales_policy` empty | None | Repo clarity | None | DOC_ONLY label | HIGH |
| Historical docs: `FULL_AGENT_TEST_SWEEP_REPORT.md`, `REDTEAM_CONVERSATIONS.md`, `REDTEAM_FINDINGS.md`, `REDTEAM_FULL_SYSTEM_AUDIT.md` | Historical reports | **ARCHIVE_SAFE_NO_RUNTIME_IMPACT** | Not imported by `app/`; mostly FIXED | file listing | None | Repo clarity | None | Archive | MED |
| `app/flows/parent_flow.py` (interceptor chain) | Live PARENT flow | **MERGE_LATER_WITH_TESTS** | 15-interceptor + 13-sanitizer chain; consolidatable | `parent_flow.py:92-404` | High risk if mishandled | Maintainability | `scenario_runner_full` CRITICAL green | No change now | HIGH |
| `parent_llm_engine.FORBIDDEN_PHRASE_REPLACEMENTS` (184) | Live sanitizer | **MERGE_LATER_WITH_TESTS** | Cosmetic majority → prompt; keep PII-preamble strip | `parent_llm_engine.py:655` | Wording regressions | Less code | `scenario_runner_full` wording+CRITICAL | No change now | HIGH |
| `camp_2026.yaml` direct readers (10+) | Fallback + bypass reads | **MERGE_LATER_WITH_TESTS** | Bypass `get_camp_facts` chokepoint | `parent_llm_engine.py:1924,2194` (live) +8 legacy | Admin edits invisible to readers | Single fact source | Admin-divergence unit test + CRITICAL | Route through `get_camp_facts` (Phase 2) | HIGH |
| Sunday-School „July" hardcode | Live deterministic answer | **MERGE_LATER_WITH_TESTS** | „July" in Python, not YAML | `parent_flow.py:2298-2302` | Admin plan changes do nothing | Operator-editable month | `test_sunday_school_handoff_2026_06_22.py` | Read month from YAML later | HIGH |
| `manager_contacts.yaml` / two phone chains | Display placeholders + camp-display chain | **MERGE_LATER_WITH_TESTS** (CONSOLIDATE) | Two independent phone chains | `admin_config_service.py:1754-1800,632-639` | Divergence if edited alone | One chain | Phone-disclosure tests | No change now | HIGH |
| `app/routes/webhook.py` | Live entry | **KEEP_PRIMARY** | Live DM/comment ingress | `webhook.py:335,357,452` | App breaks | — | scenario_runner CRITICAL | Delete only temp debug logs | HIGH |
| `message_buffer.py`, `conversation_service.py`, `parent_llm_engine.py`, `adult_llm_engine.py`, `prompt_loader.py` | Live spine | **KEEP_PRIMARY** | Live brain/router/loader | per Section 3 | App breaks | — | scenario_runner CRITICAL | None | HIGH |
| `parent_tool_executor.py`, `adult_tool_executor.py`, `data/prompts.py` | Security boundary / load-bearing aliases | **DO_NOT_TOUCH_PROTECTED** | Side-effect gating; ImportError if removed | `parent_tool_executor.py:141`; `data/prompts.py:177-182` | Booking safety / module load breaks | — | full pytest + CRITICAL | None | HIGH |
| `sections.yaml` (values) | Canonical operator facts | **DO_NOT_TOUCH_PROTECTED** | Source of truth | `sections.yaml:13-34` | Wrong facts to users | — | operator review | None (operator-only edits) | HIGH |
| `_sanitise_booking_confirmation` fake-booking guard | Safety chokepoint | **DO_NOT_TOUCH_PROTECTED** | Prevents fake confirmations | `parent_flow.py:515,545-582` | False bookings | — | booking scenarios | None | HIGH |
| `tests/conftest.py` autouse fixtures | Test safety floor | **DO_NOT_TOUCH_PROTECTED** | Prevents real Redis/SMTP/Meta/live-engine hits | `conftest.py:34-120` | Tests hit real services | — | — | None | HIGH |
| `summary.md` | Live manager-handoff prompt | **KEEP_PRIMARY** (audit said ARCHIVE — CORRECTED) | LIVE via `request_manager_callback` | `openai_service.py:348`; `parent_tool_executor.py:1365` | Manager email summary breaks | — | summary tests + handoff scenario | None — do NOT archive | HIGH |
| `business_hours.yaml` (knowledge), `i18n/ka_months.yaml`, `company.yaml` | Canonical booking/date/phone | **KEEP_PRIMARY** | Booking/date/phone source | `calendar_service.py:30,64`; `company.yaml:6` | Booking/date breaks | — | booking tests | None | HIGH |
| `followup_service.py`, `followup_strategy.yaml`, `audience_segments.yaml`, `main.py` scheduler | Live follow-up | **KEEP_PRIMARY** | Wired + fires real DMs | `main.py:70-84`; `followup_service.py:69-89,386` | Follow-ups stop | — | follow-up tests | DOC-fix CLAUDE.md "not wired" | HIGH |
| `tools/scenario_runner_full.py`, `tools/scenario_library.py` | Live regression net | **KEEP_PRIMARY** / CANONICAL | Only real-LLM gate | `scenario_runner_full.py:81,317` | Lose the gate | — | — | Reconcile `:1385` count comment (doc) | HIGH |
| Legacy: `_handle_impl`, `parent_reply_composer.py`, `parent_turn_analyzer.py`, `parent_turn_router.py`, `adult_flow.py`, `openai_service.generate_*` | Cold fallback | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** | CLAUDE.md forbids removal until engine proven in prod | `parent_flow.py:4632,403`; `adult_flow.py:200` | Lose fallback safety net | — | engine-OFF suites + staging smoke | None | HIGH |
| `system_parent.md`, `system_base.md`, `system_adult.md`, `parent_present_value.md`, `parent_turn_analyzer.md`, `detect_start_intent.md` | Legacy prompts | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** | Reached on legacy/fallback path | `data/prompts.py:35,36,37,80`; `parent_turn_analyzer.py:289` | Fallback wording breaks | — | full pytest byte-identity | None (strip facts only before flag flip) | HIGH |
| `data/events.txt`, `data/knowledge_base.txt` | Loaded-but-empty (read at import) | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** | `config.EVENTS`/`KNOWLEDGE_BASE` read at boot; crash if absent | `config.py:166,170`; `conversation_service.py:343,344` | Boot read may crash | — | import smoke + comment flow | Mark DOC_ONLY/template; no deletion | HIGH |
| `content_repository.events_data` / `_flow_context` / `run()` plumbing | Loaded-at-import, dead on flow | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** | Dead but entangled w/ import-time load | `conversation_service.py:396,867,4850` | Possible import-time effects | — | full pytest | Separate gated cleanup (not now) | HIGH |
| `USE_LLM_TURN_ANALYZER`, `USE_LLM_COMPOSER` flags + analyzer/composer | Legacy-off | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** | Fallback-only / never on | `config.py:283,294`; `parent_reply_composer.py:294` | Lose fallback | — | engine-OFF suites | None | HIGH |
| `data/admin_config/business_hours.yaml` (mirror) | Display mirror | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** / DOC_ONLY | Operator UI display; manual-sync hazard | `admin_config_service.py:1803,63`; `admin.py:749` | Admin settings page display breaks | Clarity | display tests | Label non-authoritative (no wiring) | HIGH |
| `data/admin_config/templates.yaml`, `manager_contacts.yaml` (display fields) | Comment templates / display placeholders | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** / DOC_ONLY | Comment path / display-only | `templates.yaml:9,34`; `manager_contacts.yaml:8-10` | Comment DM / display breaks | Clarity | comment flow tests | Operator may populate; label placeholders | HIGH |
| Dated guard-pinned tests (`test_*_2026_06_*`, `test_redteam_*`, `test_p0_*`, `test_p1_*`, `test_name_capture*`, `test_state_reuse*`, `test_age_extraction*`, `test_ineligible_young_age_p0`, `test_wording_polish`) | Guard regression pins | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** (TEST_ONLY, retire in lockstep) | Pin specific deterministic guards | CLAUDE.md test table | Lose guard coverage | — | scenario_runner CRITICAL + guard migration | Retire only with matching guard migration | MED |
| 16 engine-ON test files + `test_adult_llm_engine.py` | Engine-wiring coverage (OpenAI stubbed) | **KEEP_PRIMARY** (TEST_ONLY) | Prove wiring, not real-LLM behavior | `test_parent_llm_engine.py:257,299`; `test_p0_live_hotfix.py:52-54` | Lose wiring regressions | — | — | Keep; do NOT treat green as live proof | HIGH |
| Migration/sim helpers (`verify_*_migration.py`, `manual_simulation_*.py`, `sim_*.py`, `run_followup_tick.py`, `snapshot_templates.py`) | Dev tools / one-shot verifiers | **KEEP_FALLBACK_DO_NOT_TOUCH_YET** (TEST_ONLY; ARCHIVE candidates once migrations settle) | Harmless dev tooling; some still referenced | file listing | None on app | Repo clarity | none for app | Defer | MED |

**A. Can archive now (no runtime behavior change):**
- `app/agent/prompts/parent_communication_style.md` (update `test_template_render_equivalence.py:96` in lockstep).
- `app/agent/prompts/detect_segment.md` (leave the `DETECT_SEGMENT` import; archive the `.md` only with prompt-loader byte-identity tests updated).
- `app/agent/knowledge/adult_defaults.yaml` (update `test_knowledge_loader.py:125` + `verify_knowledge_migration.py:124-127` first).
- `app/agent/policies/parent_sales_policy.md` + `adult_sales_policy.md` (fix the false "engine reads" header; DOC_ONLY).
- Historical docs: `FULL_AGENT_TEST_SWEEP_REPORT.md`, `REDTEAM_CONVERSATIONS.md`, `REDTEAM_FINDINGS.md`, `REDTEAM_FULL_SYSTEM_AUDIT.md`.

**B. Actually confusing the agent / clean first:**
- `system_parent_v2.md:293` hardcoded stream dates — the #1 live fact-drift (bypasses YAML + date-filter, can emit a stale stream). Clean first (SAFE_WITH_TEST).
- Sunday-School „July" hardcode (`parent_flow.py:2298-2302`) — admin plan changes have zero effect (MERGE_LATER).
- `sections.yaml` adult „fromula 1" internal `price_text 5000` vs `price_gel 4999` — operator data conflict (admin fix, not code).
- Two phone chains (`get_manager_phone` vs `get_camp_facts['phone']`) — divergence risk (CONSOLIDATE later).

**C. Looks messy but must NOT be touched yet:**
- All legacy fallback (`_handle_impl`, `parent_reply_composer`, `parent_turn_analyzer`, `parent_turn_router`, `adult_flow`, `openai_service.generate_*`, legacy prompts) — CLAUDE.md forbids removal until engine reliability is proven in prod logs.
- `summary.md` — LIVE on the manager-handoff path (audit's archive call REFUTED).
- `data/events.txt`, `data/knowledge_base.txt`, `content_repository`/`_flow_context`/`run()` plumbing — read at import; deleting risks a boot read.
- `data/prompts.py` `ADULT_DEFAULT_*` literals, `parent_tool_executor`/`adult_tool_executor`, `sections.yaml` values, conftest fixtures — protected.

## 10. Recommended next action + what NOT to touch yet

**Single safest cleanup implementation after this verification:** remove the hardcoded stream dates from `system_parent_v2.md:293` — replace the parenthetical `(23–29 ივნისი / 5–11 ივლისი / 14–20 ივლისი)` with a generic phrase (e.g. „ბანაკის ნაკადების თარიღები") so the consultation-vs-stream teaching survives — but **only after** adding the date-frozen, engine-ON, OpenAI-mocked prompt-leak regression test, and confirming `scenario_runner_full --priority CRITICAL` stays green. This is independent of router normalization and is the only code change that improves ACTUAL agent correctness at HIGH confidence.

**Protected set (do NOT touch yet):** all legacy fallback code + legacy prompts; `summary.md`; `parent_tool_executor`/`adult_tool_executor`; `_sanitise_booking_confirmation` fake-booking guard; `sections.yaml` fact values; `data/prompts.py` literals; `tests/conftest.py` autouse fixtures; `data/events.txt`/`data/knowledge_base.txt`/`content_repository` import-time plumbing; the 15-interceptor chain and the 184-entry sanitizer (MERGE_LATER, not now).

## 11. Final explicit answer

**1. Removals that would improve ACTUAL agent behavior:**
- Removing the hardcoded stream dates at **`system_parent_v2.md:293`** (the only live fact-drift; eliminates a stale-date leak that bypasses the date-filter). This is the one behavior-improving change — and it is `SAFE_WITH_TEST`, not safe-blind.
- (Later, MERGE not delete) routing the 10+ direct `camp_2026.yaml` readers + the PROMPT/eligibility age band + the Sunday-School „July" month + the two phone chains through their chokepoints would prevent silent admin-edit divergence — but these are migrations, not removals, and require tests.

**2. Removals that are only cosmetic / repo cleanup (no behavior change):**
- `parent_communication_style.md`, `detect_segment.md`, `adult_defaults.yaml`, `parent_sales_policy.md`/`adult_sales_policy.md` (header fix), and the historical redteam/sweep docs. All ARCHIVE_SAFE with the noted test/reference updates; none affect runtime.

**3. Files that must NOT be removed yet:**
- All legacy fallback (`_handle_impl`, `parent_reply_composer`, `parent_turn_analyzer`, `parent_turn_router`, `adult_flow`, `openai_service.generate_*`) and legacy prompts (`system_parent.md`, `system_base.md`, `system_adult.md`, `parent_present_value.md`, `parent_turn_analyzer.md`, `detect_start_intent.md`).
- `summary.md` (LIVE — audit's archive recommendation is REFUTED).
- `data/events.txt`, `data/knowledge_base.txt`, `content_repository`/`_flow_context`/`run()` plumbing (read at import).
- `data/prompts.py` (`ADULT_DEFAULT_*` literals + aliases), `parent_tool_executor`/`adult_tool_executor`, `sections.yaml` values, `_sanitise_booking_confirmation`, conftest fixtures.
- Anything STILL_UNKNOWN (Section 8), including any change premised on a fixed CRITICAL count until 22-vs-23 is reconciled.

**4. The single safest cleanup implementation after verification:** add the prompt-leak regression test (engine-ON, OpenAI mocked, date-frozen to a date where a stream has hidden), then remove/genericize the `system_parent_v2.md:293` literal stream dates, then run the new test + `scenario_runner_full --priority CRITICAL`. Do it before/independent of any interceptor-chain (router) work. Ship nothing on bulk-pytest-green alone — the conftest pins the live engines OFF.
