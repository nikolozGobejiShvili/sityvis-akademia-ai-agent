# PHASE 3 — SURVEY D: Product / Offering Data Model

READ-ONLY survey (2026-07-22). No files changed, nothing committed, no OpenAI calls.
Lens: how a sellable product is represented in data today, per-product capabilities,
and what a brand-new admin-added product structurally gets vs lacks.

---

## 1. The product schema (a "section")

**Source of truth:** `data/admin_config/sections.yaml` → `sections:` list. Loaded/written by
`app/services/admin_config_service.py` (`load_sections` / `get_section` / `save_section` /
`update_section` / `delete_section`, `.bak` rotation, cache-free reads so admin edits are live).

**Fields on one section (from the live YAML + `_form_to_section_dict` in `app/routes/admin.py:773`):**

`id` (slug, `^[a-z0-9][a-z0-9_]*$`) · `name` (Georgian) · `type` (free-form string) ·
`status` (enum `active|hidden|full|coming_soon|ended`) · `hashtags[]` (routing) ·
`facebook_post_ids[]`/`post_ids`/`post_id` (comment routing) · `age_min`/`age_max` ·
`location` · `duration_text`/`duration_days` · `price_text` → `price_gel` (auto-derived via
`parse_price_gel` on every save; the two can't drift) · `payment_terms` · `description_short` ·
`description_full` · `registration_url` · `registration_status` (camp-only gate) ·
`manager_contact` · `auto_dm_template_id` · `public_reply_template_id` · `cta_text` ·
`streams[]` (`name|dates_text|status`) · `included_items[]` · `discounts[]` ·
`discovery_questions[]` · plus per-type extras: `availability_text`/`details_text`/
`handoff_enabled`/`lead_type` (sunday_school), `events[]` (adult_events sub-roster).

**Validation (`validate_section`)** requires: `id`, `name`, `type`, valid `status`, non-empty
`hashtags`, `auto_dm_template_id`. So `type` is *required* but **free-form** — it is NOT an enum.

### How "type" is determined — and why it barely matters
The live values are `type: camp` (summer_camp), `type: kids_program` (sunday_school),
`type: adult_events` (adult_events). **The reserved behaviours are keyed on the section `id`,
not on `type`.** The `type` field drives exactly ONE code branch:
`admin_config_service.build_section_dm` applies the camp stream-date filter only when
`type == "camp"`. Everything else keys off the hardcoded **id**:
`get_section("summer_camp")`, `get_sunday_school_status()` (reads `get_section("sunday_school")`),
`get_adult_events()` (reads `get_section("adult_events")`). The dynamic matcher passes `type`
through but never switches on it. **Net: `type` is essentially decorative today; capability is
bound to a closed set of three reserved ids.**

### The reserved-id / type enum
Canonical closed set = `app/domain/decision/models.py::ProgramId` (a `str, Enum`):
`SUMMER_CAMP="summer_camp"`, `SUNDAY_SCHOOL="sunday_school"`, `ADULT_EVENTS="adult_events"`.
- `parent_tool_executor._HARDCODED_PROGRAM_IDS = frozenset(p.value for p in ProgramId)` — the
  generic `get_program_info` tool **refuses** these three (`reason="use_specific_tool"`), forcing
  them onto their curated handlers.
- `app/domain/decision/program_registry.py::PROGRAM_REGISTRY` is an immutable registry whose
  constructor **raises `RegistryValidationError` if the definitions are not EXACTLY these three**
  (`missing`/`unsupported`). It records symbolic owners per program (lifecycle/facts/config).
- `app/domain/decision/program_resolver.py::DEFAULT_PROGRAM_RESOLUTION_POLICY` hardcodes Georgian
  phrase/stem rules for the same three ids. **This whole domain layer cannot represent a
  fourth product** — a new admin product has no `ProgramId`, no registry entry, no resolver rules.

---

## 2. The dynamic-programs mechanism (`USE_DYNAMIC_PROGRAMS`, default OFF)

For a NON-reserved admin-added program (e.g. "ფორმულა1"):
- `app/reasoning/dynamic_program_match.match_dynamic_program(msg, sections)` — pure matcher:
  returns `{program_id, type}` for the first ACTIVE section a message NAMES with specificity
  (non-ambiguous name token OR non-ambiguous hashtag; declension-tolerant; ambiguous common-word
  stems excluded). No IO, no settings.
- Two info-only tools, `parent_tools.DYNAMIC_PROGRAM_TOOLS` (added to the engine tool list only
  when `USE_DYNAMIC_PROGRAMS=true`, `parent_llm_engine.build_active_tools`):
  - `list_programs` → executor `_list_programs` = `get_active_sections()` mapped to
    `{program_id, name, type}`.
  - `get_program_info(program_id, topic)` → executor `_get_program_info`: refuses the 3 reserved
    ids; requires `status=="active"`; returns an **allowlisted** fact subset
    (`_PROGRAM_PUBLIC_FIELDS`: name/type/location/price_text/price_gel/payment_terms/age_min/
    age_max/description_short/description_full/schedule_text/duration_text/streams/included_items/
    discounts) + `registration_url` only if `registration_status` is open. New operator fields
    don't leak by default (allowlist).
- Gate: needs `USE_PARENT_LLM_ENGINE=true` AND `USE_DYNAMIC_PROGRAMS=true`; Phase-1 prompt suffix
  lists active non-camp programs; Phase-2 hoist guard routes a named-dynamic-program turn to the
  engine. Rollback = one env flag + restart (flag-off is byte-identical).

**A generic dynamic program CAN:** be discovered by name/hashtag; be listed; answer factual
questions (name, price, location, schedule, description, payment terms, included items, discounts)
strictly from its admin section; surface its registration URL when registration is open.

**A generic dynamic program CANNOT:** trigger any dedicated booking/reservation action; create a
product-specific lead or lead type; drive a product-specific manager handoff; be represented in
the typed domain/decision layer; get follow-up cadence keyed to it. Its tools are **read-only
info**. Any booking/handoff it reaches is the *shared camp-consultation* machinery (see §4), not
a per-product function.

---

## 3. Per-product CAPABILITY MATRIX

Columns: (a) info-answering, (b) booking/reservation action, (c) lead capture + store,
(d) manager handoff, (e) follow-up eligibility, (f) dedicated tools.

| Capability | summer_camp | sunday_school | adult_events | generic dynamic program |
|---|---|---|---|---|
| (a) Info answering | Yes — curated `get_camp_info` + `get_camp_facts()` merge, camp prompt, stream filter | Yes — deterministic `_render_sunday_school_answer` from `get_sunday_school_status()` (availability/details) | Yes — `get_adult_events`/`get_adult_event_details`, date-filtered active list, ADULT engine | Yes — `list_programs`+`get_program_info` allowlisted facts only |
| (b) Booking / reservation | **Yes** — `book_consultation` → Google Calendar event (`calendar_service.book_slot`) + slot check | No booking; email handoff only (planned/coming_soon) | No Calendar; `provide_adult_reservation_link` = operator `reservation_url` only | **None** — no booking/reservation action at all |
| (c) Lead capture + store | **Yes** — `create_lead` → Google Sheets **Leads** tab (17-col A–Q, `_lead_to_row`), camp Lead fields | **Yes** — `log_sunday_school_lead` → **SundaySchoolLeads** tab (separate) | Subscription → `save_event_subscriber` → **events** tab (`EVENT_SUBSCRIBER_HEADERS`) | **None** — no lead written; nothing persisted for the product |
| (d) Manager handoff | Yes — `request_manager_callback` + `_maybe_notify_manager_for_handoff` → `send_manager_notification` (email+WhatsApp) + Sheets lead | Yes — email-only `notify_sunday_school_handoff` (no Calendar/WhatsApp), consent-gated | Yes — `request_adult_manager_callback` (idempotent per conv) + manager phone disclosure | Only the shared/generic manager offer; no product-bound handoff or lead |
| (e) Follow-up eligibility | Yes — PARENT segment, `followup_service` 24h/72h/168h cadence | Partial — captured as PARENT/lead but SS is coming_soon; email handoff path | No — scheduler `reason=non_parent_segment` for ADULT/UNCLEAR (adult uses broadcast, not cadence) | No — not keyed to any segment/cadence |
| (f) Dedicated tools | 8 curated PARENT tools (camp info/slots/book/manage/callback/save_lead/check_slot/switch) | Deterministic handler in `parent_flow` + `notify_sunday_school_handoff` | 6 ADULT tools (events/details/save_lead/callback/reservation-link/switch) | 2 shared read-only tools (`list_programs`,`get_program_info`) |

**The gap in one line:** camp has a dedicated **action (Calendar booking)**, a dedicated **lead
row**, and a dedicated **handoff** — all keyed to its reserved id. A new admin product gets
**info-answering only**; every "sellable" verb (book, capture-lead, hand-off-with-a-product-lead,
follow-up) is missing or falls back to camp-consultation semantics.

---

## 4. What booking / lead / handoff are bound to (the SEAMS)

**Booking — camp-consultation-specific, but the transport is reusable.**
`book_consultation` (`parent_tool_executor._book_consultation`) is bound to camp: it books a
Google **Calendar consultation event** (`calendar_service.book_slot`), gates on camp eligibility
age (9–17 via `get_camp_age_bounds`), and confirms with camp consultation wording. The underlying
`calendar_service` (slots, FreeBusy, business hours, `book_slot`/`cancel_calendar_event`) is
product-agnostic and reusable — but there is **no product parameter**; it only ever books "camp
consultation". adult_events deliberately has **no Calendar path** (reservation = external URL);
sunday_school has none (email handoff). So booking is a single hardcoded camp function, not a
per-product capability.

**Lead store — three parallel hardcoded tabs, one per built-in product.**
- `sheets_service.create_lead` → **Leads** tab, camp Lead schema (`HEADERS`, 17 cols, `_lead_to_row`).
- `sheets_service.log_sunday_school_lead` → **SundaySchoolLeads** tab (`SUNDAY_SCHOOL_HEADERS`).
- `sheets_service.save_event_subscriber` → **events** tab (`EVENT_SUBSCRIBER_HEADERS`).
There is **no generic "lead for program X" store** and no `lead_type`-driven router (the
`lead_type` field exists on sunday_school config but only labels the SS handoff). A new product
has nowhere to write a lead.

**Handoff — a reusable notification core with per-product wrappers.**
`notification_service.send_manager_notification` (email + WhatsApp, gated) is the reusable core.
Wrappers differ per product: camp handoff also writes a Sheets lead
(`_maybe_notify_manager_for_handoff` → `create_lead`); `notify_sunday_school_handoff` is email-only
+ SundaySchoolLeads; ADULT executor discloses manager phone via `get_manager_phone()`. The core is
generalisable; the wrappers are hand-written per reserved product.

### Where a per-product-type capability abstraction would attach (2–3 seams)
1. **Tool dispatch + reserved-id gate** — `parent_tool_executor.execute` /
   `_HARDCODED_PROGRAM_IDS` / `build_active_tools`. Today capability is selected by hardcoded id.
   A "product-type → capability set (info | booking | reservation-link | lead | handoff)" table
   would attach here so `get_program_info`/a new `book_program`/`capture_program_lead` dispatch by
   the product's declared capabilities instead of `if id == "summer_camp"`.
2. **Lead store router** — `sheets_service.create_lead` / `log_sunday_school_lead` /
   `save_event_subscriber`. Generalise to a `save_program_lead(program_id/type, lead)` that routes
   to a per-product tab/schema (driven by section config, e.g. an extended `lead_type`), so a new
   product's lead has a home without a new hand-written function + tab.
3. **Action/handoff binding** — `book_consultation` (Calendar) + `_maybe_notify_manager_for_handoff`
   + `provide_*_reservation_link`. The Calendar/FreeBusy transport and `send_manager_notification`
   core are already product-agnostic; the seam is to parameterise them by product (which action a
   product supports: Calendar-consultation vs external reservation URL vs email-only handoff) —
   declared in the section, not hardcoded per reserved id.

The `ProgramRegistry` / `program_resolver` domain layer (closed 3-id enum, symbolic per-program
owners) is the natural home for a **generalised capability descriptor**, but it must first stop
hard-validating "exactly these three" before a new admin product can be a first-class citizen.
