# Phase 3 Survey A — Factual / Policy Knowledge Inventory (LIVE vs DEAD)

**Date:** 2026-07-22
**Scope:** READ-ONLY survey. Facts & policy knowledge only (conversational
examples / follow-up cadence / audience-nurture belong to other agents).
**Method:** every allegation was verified by grepping for the *actual caller*
in running code; the caller line (or its absence) is quoted below. Nothing was
changed. No OpenAI call was made.

**Operating mode assumed:** live `.env` = `USE_PARENT_LLM_ENGINE=true`,
`USE_ADULT_LLM_ENGINE=true` (legacy state machines are dormant fallbacks).
A reader that fires only when an engine flag is OFF is therefore treated as
DEAD-for-live.

---

## 1. Classification table (with caller-grep evidence)

Legend — **LIVE**: a running path reads it and its content reaches a user reply
or tool result. **FALLBACK-ONLY**: read solely as a fallback behind admin_config
(or as an operator-UI mirror). **DEAD**: nothing in the live path reads it, OR
its value is hardcoded in Python instead.

| File | Class | Real caller (evidence) |
|---|---|---|
| `data/admin_config/sections.yaml` | **LIVE** | `admin_config_service.get_camp_facts()` reads `get_section("summer_camp")` (admin_config_service.py:733); `get_adult_events()` / `get_sunday_school_status()` / `get_manager_phone()` (`_manager_phone_from_section("summer_camp")`, :2010). This is the operator source of record. |
| `app/agent/knowledge/camp_topic_facts.yaml` | **LIVE** | `app/reasoning/camp_topic_facts.py:111` `load_knowledge("camp_topic_facts")` → `answer_for_topic` → `parent_flow._maybe_handle_camp_topic_facts` interceptor (parent_flow.py:1567), a **pre-LLM deterministic** short-circuit. 38 KB of customer-facing topic answers. |
| `app/agent/knowledge/business_hours.yaml` | **LIVE** | `calendar_service.py:30` `_BUSINESS = load_knowledge("business_hours")["business"]`; `parent_flow.py:362/365/8894`. Canonical booking window / slot / buffer / TZ. |
| `data/admin_config/templates.yaml` | **LIVE** | Admin templates for comment DM / public reply / follow-up (rendered by `admin_config_service` template renderer; followup_service admin-template-first). Wording, not facts, but operator-live. |
| `app/agent/knowledge/i18n/ka_months.yaml` | **LIVE (infra)** | `calendar_service.py:77`, `parent_flow.py:365`, `admin_config_service.py:1192`. Month-name parsing, not a "fact a customer asks", but live. |
| `app/agent/knowledge/camp_2026.yaml` | **FALLBACK-ONLY** | Read only as the fallback behind admin_config: `get_camp_facts()` `load_knowledge("camp_2026")["camp"]` (admin_config_service.py:724, merged UNDER the admin section); `_get_camp_info` tool fallback (parent_tool_executor.py:513); boot camp-price default (config.py:524); comment rich-DM step-2 fallback (comment_service.py:212). Also read by legacy engine-OFF paths (`parent_turn_router.py:150`, `parent_reply_composer.py:180`, `parent_turn_analyzer.py:146`). `parent_flow` has ZERO direct reads. |
| `data/admin_config/business_hours.yaml` | **FALLBACK-ONLY** | Read ONLY by the Admin Panel Settings page: `admin.py:754` `load_business_hours_mirror()`. Its own header says "for the operator UI only… canonical values from `app/agent/knowledge/business_hours.yaml`". Booking pipeline never reads it. |
| `data/admin_config/manager_contacts.yaml` | **FALLBACK-ONLY** | Read live at `admin.py:755` (Settings page) and `get_manager_phone()` (admin_config_service.py:2015) — but ONLY as an override behind `summer_camp.manager_contact`, and the shipped file holds **no phone** (only `email_placeholder` / `whatsapp_placeholder` / `notification_label`), so it contributes nothing to the live answer. |
| `app/agent/knowledge/company.yaml` | **DEAD (live)** | Live camp answers never read it. Only reader is the legacy engine-OFF path `parent_turn_router.py:154` `load_knowledge("company")["company"]`. Its `name` is **hardcoded** in `config.py:224/513`; its `phone` is duplicated in `camp_2026.yaml` + `sections.yaml`. |
| `app/agent/knowledge/adult_defaults.yaml` | **DEAD** | No `load_knowledge("adult_defaults")` anywhere in `app/` (only `tests/test_knowledge_loader.py:125`). Its values are hardcoded in `data/prompts.py:175-182` (`ADULT_EVENT_PLACEHOLDER` … `ADULT_DEFAULT_EVENT_ATMOSPHERE_TBD`), imported by the legacy `adult_flow.py:13-23`. |
| `app/agent/knowledge/audience_segments.yaml` | **DEAD** | No runtime reader in `app/`; only `tests/test_parent_llm_engine.py:1711`. (Nurture concern — out of this factual lens, but confirmed not read by any live path.) |
| `data/knowledge_base.txt` | **DEAD** | `ContentRepository` (conversation_service.py:710) reads it, but its only consumer `FlowContext` is built by `_flow_context()` (conversation_service.py:1545) which has **ZERO callers** in `app/`. The other reader, `FollowupService.build_followup` (followup_service.py:182→190 `content.knowledge_text("messages","followup")`), is a "compatibility shim" with **ZERO live callers** (live scheduler = `check_and_send_followups`, uses admin templates). File is empty bracket placeholders anyway. |
| `data/events.txt` | **DEAD** | Same dead `ContentRepository`/`FlowContext` path. Also read via `comment_service._parse_events_blocks()` → `_build_adult_rich_dm()` (comment_service.py:126/351), but that is a fallback behind the admin adult-events DM and the file is **all empty placeholders** (zero real event facts). |
| `app/agent/policies/parent_sales_policy.md` | **DEAD** | `prompt_loader.load_prompt` only reads `app/agent/prompts/*.md` (prompt_loader.py:28/46); policies live in `app/agent/policies/`. No `load_prompt` / `open()` of this file anywhere in `app/` — only `tests/test_agent_wording_cleanup.py`. |
| `app/agent/policies/adult_sales_policy.md` | **DEAD** | Same as above. Referenced only by `tests/test_adult_context_routing_fix.py:541` + `test_agent_wording_cleanup.py:334`. Never loaded into any runtime prompt. |

**Counts:** LIVE = 4 factual (+1 infra `ka_months`)  ·  FALLBACK-ONLY = 3  ·  DEAD = 7.

---

## 2. Audit allegations — verified one by one

1. **"`adult_defaults.yaml` hardcoded in Python"** — **CONFIRMED.** Zero `load_knowledge("adult_defaults")` in `app/`; constants live in `data/prompts.py:175-182` and are imported by legacy `adult_flow.py:13-23`.
2. **"`company.yaml`'s COMPANY_NAME hardcoded in config.py:224"** — **CONFIRMED.** `config.py:224 COMPANY_NAME: str = "სიტყვის აკადემია"` and `config.py:513 COMPANY_NAME=_env("COMPANY_NAME") or "სიტყვის აკადემია"`. `config.py` imports `load_knowledge` but uses it only for camp price (config.py:524) — it never reads `company.yaml`. company.yaml's comment ("Settings.COMPANY_NAME default reads from here") is **false**.
3. **"`knowledge_base.txt`/`events.txt` via a ContentRepository with zero callers"** — **CONFIRMED.** `content_repository = ContentRepository()` is instantiated (conversation_service.py:765) but its `FlowContext` consumer builder `_flow_context()` has zero callers; `FollowupService.build_followup` shim is also uncalled. Both `.txt` files are empty bracket templates regardless.
4. **"both `*_sales_policy.md` never loaded by prompt_loader"** — **CONFIRMED.** prompt_loader targets `prompts/`, not `policies/`; no runtime loader/`open()` touches either policy file.

---

## 3. Per-file fact summary (LIVE / FALLBACK — what a customer could ask)

- **`sections.yaml` (LIVE, operator source of record):**
  - `summer_camp`: age 9–17; location `ამბასადორი კაჭრეთი`; `price_text/price_gel = 2150`; payment split ≤6 months; registration `https://tinyurl.com/36jcae8z`; **`registration_status: closed`**; `manager_contact 558 67 47 33`; 3 streams (23-29 ივნისი / 5-11 ივლისი / 14-20 ივლისი); included = transport/lodging/food/program; discounts = 10% siblings, 10% returning; duration_days 7.
  - `sunday_school`: `coming_soon`, "ივლისში დაემატება", handoff enabled, email-only lead.
  - `adult_events`: active, age_min 13, location `ბორის პაიჭაძის სტადიონი`, price 200, one stream "maroon 5 კონცერტი / 23 ივნისიი 19:00", `events: []` (⚠ looks like test/placeholder operator data; a typo "ივნისიი" and no reservation URL).
- **`camp_topic_facts.yaml` (LIVE, pre-LLM):** focused Georgian answers for camp SAFETY (24/7 medical, video monitoring, staff), parent communication / daily updates, food, gadgets ("გაჯეტებისგან განტვირთვა"), medical (defer to manager), general overview (templated `{price}/{duration}/{age_min}/{age_max}` pulled from `get_camp_facts()` at render). Selected deterministically by keyword-stem triggers; canonical flows (price/dates/link/Sunday-School/adult) are excluded before selection.
- **`business_hours.yaml` (LIVE):** TZ Asia/Tbilisi; work + business hours 10:00–21:00; slot 60 min (last start 20:00); buffer 120 min. (Booking days Mon–Sat is in `calendar_service` code, not this file.)
- **`camp_2026.yaml` (FALLBACK):** same camp facts as sections.yaml (age 9–17, 2150₾, location, 3 streams, discounts, registration URL, phone `558 67 47 33`, focus areas, activities). Only surfaces if the admin section is missing/malformed. Values here can silently drift from sections.yaml.
- **`manager_contacts.yaml` / admin `business_hours.yaml` (FALLBACK):** operator-UI mirrors; contribute nothing to live answers (placeholders / display-only).

## 3b. DEAD files — what knowledge is stranded, and is it available elsewhere?

- **`company.yaml`** — company name + phone. Name is available (hardcoded config.py); phone available in sections.yaml + camp_2026.yaml. Nothing lost, but it is a 3rd competing copy of the phone.
- **`adult_defaults.yaml`** — adult-event placeholder strings ("დასაზუსტებელია", fallback event name/theme/guest/location/atmosphere). Live equivalent = the hardcoded constants in `data/prompts.py` (used only by dormant `adult_flow`). Editing the YAML changes nothing.
- **`audience_segments.yaml`** — audience segment descriptions (nurture domain, not product facts).
- **`knowledge_base.txt` / `events.txt`** — intended as company/camp/FAQ/sales and event templates but shipped **empty** (bracket placeholders); no real facts stranded.
- **`parent_sales_policy.md` / `adult_sales_policy.md`** — the operational sales rules (age-first, price rule, decline rule, manager-handoff wording, Georgian genitive, etc.). These are **not injected into any runtime prompt**; the equivalent rules live embedded in `app/agent/prompts/system_parent_v2.md` / `system_adult_v1.md`. Editing the policy .md files changes nothing in production.

---

## 4. Where does a factual answer's data actually come from today?

Two competing live pipelines, plus stranded copies:

**Pipeline A — structured facts (price / dates / age / location / registration / manager phone):**
```
data/admin_config/sections.yaml  (summer_camp)
   → admin_config_service.get_camp_facts()      # admin-first merge OVER camp_2026.yaml fallback (admin_config_service.py:724/733)
   → ParentToolExecutor._get_camp_info()         # get_camp_info tool (parent_tool_executor.py:486/511)
   → LLM composes the reply
```
Age band: `get_camp_age_bounds()` (all 6 live readers). Manager phone:
`get_manager_phone()` → `summer_camp.manager_contact` → manager_contacts mirror →
adult_events → "" (callers hardcode `558 67 47 33`). `camp_2026.yaml` sits UNDER
this as fallback only.

**Pipeline B — qualitative topic facts (safety / food / gadgets / medical / daily updates / overview):**
```
user question
   → parent_flow._maybe_handle_camp_topic_facts()   # PRE-LLM interceptor (parent_flow.py:1567)
   → app/reasoning/camp_topic_facts.answer_for_topic()
   → app/agent/knowledge/camp_topic_facts.yaml       # deterministic, LLM NEVER sees it
```

**Is there ONE canonical source per fact? No.**
- Structured facts have one live canonical owner (`sections.yaml` via `get_camp_facts`), but `camp_2026.yaml` is a full parallel copy behind it and can drift; `company.yaml` is a third copy of the phone; the legacy engine-OFF readers still read `camp_2026.yaml` directly.
- Qualitative facts live entirely in `camp_topic_facts.yaml` and are delivered **around** the LLM (deterministic interceptor), so they are NOT reachable through any tool today.

---

## 5. Single most important finding for the rebuild

**The largest body of customer-facing product knowledge — `camp_topic_facts.yaml`
(safety, food, gadgets, medical, daily schedule, parent communication, overview)
— is served DETERMINISTICALLY by a pre-LLM interceptor that short-circuits the
engine; the model never sees it and cannot reason over it.** If the goal is
"the LLM answers from tools," this corpus is the #1 thing to expose as a tool
(e.g. a `get_camp_topic` / knowledge-retrieval tool backed by the same YAML),
and `sections.yaml` (via `get_camp_facts`) must remain the single backing source
for the structured facts. Retiring the drift risk means collapsing `camp_2026.yaml`
+ `company.yaml` into the one source rather than keeping them as parallel copies.

---

## 6. Status I could NOT determine with full confidence

- **`camp_2026.yaml` LIVE-vs-FALLBACK is mode-dependent, not absolute.** With the
  engine ON it is fallback-only for structured facts, BUT it is still a *direct
  primary* read inside `comment_service._build_parent_rich_dm` step-2 fallback and
  is the boot-time camp-price default. I classified it FALLBACK-ONLY; if the
  admin section were ever absent it would become the live primary. Flag for the
  rebuild owner.
- Everything else (LIVE / DEAD / FALLBACK) was determined confidently from the
  quoted caller lines.
