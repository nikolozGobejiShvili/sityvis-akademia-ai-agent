# Phase 3 Survey C — Follow-up, Audience Segmentation & Lead Lifecycle

READ-ONLY survey. Working directory: `ai-agent/`. No code changed, nothing committed, no OpenAI calls made.

Scope: follow-up cadence, audience segmentation, lead lifecycle state machine, per-product lead capture. Product facts / sales voice are out of scope (other survey lanes).

---

## 1. Follow-up cadence

### 1.1 `app/agent/knowledge/followup_strategy.yaml` — what it defines

- `global_rules`: `send_only_if_user_stopped`, `do_not_follow_up_if` (booked / registered / declined / asked_no_more_messages / manager_handoff_completed), a `tone` list.
- `stages`: `first_24h` (delay_hours: 24), `second_3d` (delay_hours: 72), `third_7d` (delay_hours: 168) — each with a `goal`, a `when` list, and a full Georgian `message_template` body.
- `scenario_followups`: three scenario keys (`stopped_after_price`, `stopped_after_age`, `said_will_think`) each with a `message_goal` + `suggested_message`.
- `after_7d`: `stop_followups: true` + `resume_only_if` conditions.
- The file's own header comment is candid about its status: *"This file is data for a future scheduler … the engine reads `global_rules.do_not_follow_up_if` and the `stages` keys to know which markers to record … no message is actually sent from this task."* That comment is now stale/aspirational — see 1.2.

### 1.2 `app/services/followup_service.py` — what actually runs

**Verdict: `followup_strategy.yaml` is DEAD for the actual cadence and message bodies. It is NEVER loaded, parsed, or read by any Python code.**

Caller evidence:
- `grep -n "load_knowledge|followup_strategy\.yaml|yaml\.safe_load" app/services/followup_service.py` → the file only *mentions* `followup_strategy.yaml` twice, both inside docstring/comments (lines 17, 58). There is no `load_knowledge("followup_strategy")` call anywhere in `app/`.
- Repo-wide `grep -rl "followup_strategy"` hits only: `followup_service.py` (comments only), `tests/test_followup_scheduler.py`, `app/models/conversation.py` (a comment), `tests/test_sentry_service.py`, `tools/sim_followup.py`, plus docs/CLAUDE.md prose. No production code path parses the YAML.
- The real cadence lives as a hardcoded Python list, `_FOLLOWUP_CADENCE` (followup_service.py:70-89): three dict entries with literal `timedelta(hours=24|72|168)` values and `template_id` strings (`followup_24h` / `followup_3d` / `followup_7d`). Stage *names* (`first_24h`/`second_3d`/`third_7d`) happen to match the YAML's `stages` keys, but that's convention, not a read.
- `_BLOCKED_REASONS` (line 133) is a second hardcoded Python frozenset that duplicates (does not read) `global_rules.do_not_follow_up_if`, plus one extra value `followup_exhausted` computed by the scheduler itself.
- The YAML's `scenario_followups` (stopped_after_price / stopped_after_age / said_will_think) are **never read anywhere in `app/`** — confirmed by grepping for the three scenario key names project-wide; only the YAML file itself contains them. `Conversation.stopped_after` (a string tag) is written by `conversation_service` but nothing branches on it to pick a scenario-specific message — the scheduler always sends the flat `followup_24h`/`followup_3d`/`followup_7d` template regardless of `stopped_after`.
- The YAML's `message_template` bodies (the actual Georgian follow-up copy per stage) are also never read — the live copy comes from `data/admin_config/templates.yaml` instead (see 1.3). The YAML bodies and the admin templates.yaml bodies are similar in spirit but are two independently-maintained copies of the same idea; only the admin one is live.

What IS live and correctly engineered:
- `check_and_send_followups()` is an APScheduler tick (hourly, `app/main.py`) gated by the kill switch (`kill_switch.is_agent_enabled()`) and `FOLLOWUP_ENABLED`.
- It snapshots in-memory conversations (`conversation_service.get_all_conversations_snapshot()`), then per-conversation `_maybe_send_followup_for_conversation` enforces, in order: non-empty `sender_id` → `segment == "PARENT"` only (ADULT/UNCLEAR are hard-skipped, `reason=non_parent_segment`) → `admin_config_service.is_camp_registration_open()` → `followup_blocked_reason not in _BLOCKED_REASONS` → `lead.calendly_booked` double-check → supported platform (`instagram`/`messenger`/`whatsapp`) → parseable `last_bot_message_at` → `_pick_due_cadence(followup_stage, elapsed)` against the hardcoded `_FOLLOWUP_CADENCE`.
- `_first_delay()` supports an operator test-mode override (`FOLLOWUP_TEST_MODE` + `FOLLOWUP_FIRST_DELAY_SECONDS`) for the *first* stage only; stages 2/3 are never overridden — this override logic also lives only in Python, not the YAML.
- On send, `conversation.followup_stage` advances and `last_bot_message_at` resets (even on send failure, to avoid retry loops); stage `third_7d` additionally sets `followup_blocked_reason = "followup_exhausted"`.

### 1.3 Message bodies / channel / operator editability

- Channel: private DM only, via `messenger_service.send_message(sender_id, platform, text)`, using the Conversation's own `platform` field verbatim (instagram/messenger/whatsapp) — never a public reply.
- Body resolution: `_render_followup_text(template_id, conversation, lead)` calls `admin_config_service.render_template(template_id, context)` FIRST (template ids `followup_24h`, `followup_3d`, `followup_7d`, confirmed present in `data/admin_config/templates.yaml` lines ~49-61 with real Georgian copy). If that render fails or is empty, it falls back to one of three hardcoded Georgian constants in `followup_service.py` (`_FALLBACK_FOLLOWUP_24H/3D/7D`).
- Operator editability: **YES for the three admin templates** — `/admin/templates` (in `app/routes/admin.py`) lists every template id in `templates.yaml` and lets the operator edit + save its body; `admin_config_service.save_template` writes straight back to `templates.yaml`, which `_render_followup_text` reads on the very next call (no restart needed). `followup_strategy.yaml` itself has **no admin UI** and is not operator-editable at runtime — it is a source-of-truth *document*, not live config.
- Context placeholders available: `name`/`First_Name`, `company_name`, `followup_link`, `stopped_after`, `last_meaningful_interest`.
- Comment-originated conversations participate in the same cadence: `comment_service.send_dm_from_comment` stamps `last_bot_message_at` and writes through to Redis on a successful first-contact DM, so a comment-origin lead enters the same 24h/72h/168h clock as a direct-DM lead.

### 1.4 `docs/source/` follow-up source document

- `docs/source/სიტყვის_აკადემია_ფოლოუ_აფი.docx` exists (binary .docx — not read; this survey does not open binaries). Filename translates to "Speech Academy — Follow-up". Per `followup_strategy.yaml`'s own header comment, this docx was the human-authored source that was manually distilled into the YAML; the docx itself is never loaded by any code path (per CLAUDE.md: "Source docs are NEVER injected into runtime prompts").

---

## 2. Audience segmentation

### 2.1 `app/agent/knowledge/audience_segments.yaml` — what it defines

- `segments`: 4 personas — `parent_development_concern`, `teen_self_expression`, `adult_cultural_evenings`, `emigrant_parent` — each with `label`, optional `age_range`/`child_age_range`, `decision_maker`, `core_need`, `pain_points`, `desires`, optional `objections` (concern + response_angle), and `message_angles`.
- `micro_segments`: 3 — `premium_parent`, `values_oriented_parent`, `busy_parent` — each with `key_triggers` (Georgian keyword list) and one `message_angle` sentence.

### 2.2 Is it read anywhere at runtime?

**Verdict: DEAD. `audience_segments.yaml` is never loaded by any production code path, and is not personalisation at runtime — only aspirational documentation.**

Caller evidence:
- Repo-wide `grep -rl "audience_segments"` under `app/` hits exactly two files: `app/agent/policies/parent_sales_policy.md` (prose, §12 "Audience-aware tone adapters" — a markdown table of cue→adapter-name pairs that ends with *"The exact wording for each angle lives in `app/agent/knowledge/audience_segments.yaml`. Do not paste the YAML verbatim..."*) and the YAML file itself. No `.py` file references the filename.
- `grep` for every actual segment/micro-segment key name (`premium_parent`, `values_oriented_parent`, `busy_parent`, `teen_self_expression`, `adult_cultural_evenings`, `emigrant_parent`, `parent_development_concern`) across `app/` returns **zero matches outside the YAML file itself**. Nothing in Python constructs a segment lookup, nothing in a prompt template interpolates a segment's `message_angles`/`objections`/`key_triggers`.
- Critically, **`app/agent/policies/parent_sales_policy.md` itself is never loaded by any code.** `grep -rn "sales_policy\.md|policies/parent_sales|policies/adult_sales" app/` finds only a self-referential mention inside `adult_sales_policy.md`'s own text. There is no `load_policy`/`load_knowledge`/`prompt_loader` call anywhere that reads `app/agent/policies/*.md` into the LLM system prompt. These policy `.md` files are **human/developer reference documents only** — the same status as `docs/source/`, despite CLAUDE.md describing them as the canonical home for sales rules.
- Cross-checked the actual live system prompt `app/agent/prompts/system_parent_v2.md` (the file `parent_llm_engine._build_system_prompt` really sends to OpenAI) for "audience"/"segment" (case-insensitive): **zero matches.** So even the *idea* of segment-aware tone-adapting described in the dead policy doc never reaches the LLM's actual instructions.
- The only place `load_knowledge("audience_segments")` is called at all is a single unit test (`tests/test_parent_llm_engine.py::test_patch3_audience_segments_yaml_loads_with_required_keys`, line ~1707-1711) that merely asserts the YAML parses and has the expected keys — it does not exercise any live consumption path.

### 2.3 Is there live personalisation by audience today?

No. There is no code that classifies a user into one of the 6 segments/micro-segments and no code that injects segment-specific wording into a reply. What *does* exist and *is* live:
- A coarse **top-level classification** (`PARENT` / `ADULT` / `UNCLEAR`) done by `conversation_service`'s segment classifier — this routes to the PARENT vs ADULT flow/engine/prompt/tools, which is a real behavioural fork, but it is not the audience_segments.yaml taxonomy (development-concern parent vs. emigrant parent vs. premium parent, etc.).
- Within PARENT, `_build_sales_context`/`response_policy.py` composers adapt tone based on *conversation state* (e.g., price objection, eligible age, consultation CTA) — situational, not persona-based.
- So "audience-aware tone adapters" is currently aspirational: documented in a dead policy file, backed by a dead knowledge YAML, never wired into a prompt or a Python decision.

---

## 3. Lead lifecycle

### 3.1 State-tracking fields

`app/models/conversation.py` (`Conversation` dataclass) — the 5 follow-up readiness fields (P3-C PATCH 3), all plain strings, Redis-JSON safe:
- `last_bot_message_at: str` — ISO timestamp of the last outbound message; the scheduler's clock anchor.
- `followup_stage: str` — `"" → "first_24h" → "second_3d" → "third_7d"` (or `"stopped"`, though the scheduler code path never actually writes `"stopped"` — see `_pick_due_cadence`, which treats `third_7d`/`stopped` identically as terminal).
- `followup_blocked_reason: str` — one of `"" | booked | registered | declined | asked_no_more_messages | manager_handoff_completed | followup_exhausted` (the last value is scheduler-computed, not in the YAML's list).
- `last_meaningful_interest: str` — free tag (e.g. "price", "dates") — written but not read by any branching logic found in this survey (candidate for the scenario-based follow-up that was never wired).
- `stopped_after: str` — free tag for what the user last disclosed before going silent — same status: written, exposed to the template context, but not used to *select* a different template.

Also on `Conversation`: `segment`, `state` (legacy PARENT state machine: START/…/DONE), `pending_booking` (dict — in-flight booking capture), `adult_subscription_status` ("" / "asked" / "subscribed" / "declined" / "unsubscribed").

`app/models/lead.py` (`Lead` dataclass) — booking/contact state: `calendly_booked: bool`, `booked_datetime_iso`, `calendar_event_id`, `status: str` (free string, e.g. `"New"`/`"Booked"`/`"Rescheduled"`), `followup_sent: bool` (legacy, appears superseded by the Conversation markers), plus segment-specific fields (`child_age`, `adult_age`, `adult_target_age/relation`, `preferred_event`, `seat_count`, `reservation_status` for the ADULT flow).

### 3.2 Terminal / blocked states

Blocking follow-up (`_BLOCKED_REASONS` in `followup_service.py`, hardcoded — see §1.2): `booked`, `registered`, `declined`, `asked_no_more_messages`, `manager_handoff_completed`, `followup_exhausted`. There is no single central lifecycle state machine — these are simply reasons that gate the *follow-up scheduler specifically*; the underlying "is this lead done" concept is inferred ad hoc from `lead.calendly_booked`, `lead.status`, and `conversation.followup_blocked_reason` in different code paths (booking flow, Sunday-School handoff, ADULT manager handoff, subscription flow) rather than one canonical status enum.

### 3.3 Per-product lead capture, as it exists today

Each of the three current products has its own **hand-written, product-specific** capture path — there is no shared "register a lead for product X" abstraction:

1. **Camp (summer_camp, type `camp`)** — captured via **Calendar booking**. `parent_tool_executor.book_consultation` → `calendar_service.book_slot` (Google Calendar event) → on verified `event_id`, `lead.calendly_booked=True` / `booked_datetime_iso` / `calendar_event_id` / `status="Booked"` are set, and the lead row is appended to the **Google Sheets "Leads" tab** (A–Q columns, `sheets_service.save_lead` / `_append_lead_row_aligned`) + a manager notification email (`notification_service`) + optional WhatsApp. This is the most fully-built path (Calendar + CRM + email + reschedule/cancel).

2. **Sunday School (sunday_school, type `kids_program`, status `coming_soon`)** — captured via **email-only manager handoff**, hardcoded to this specific section id in `parent_flow.py` (`_render_sunday_school_answer` reads `admin_config_service.get_sunday_school_status()` for the "ივლისში დაემატება" copy, then a dedicated handoff path collects name+phone and calls `notification_service.notify_sunday_school_handoff(lead)`). On confirmed email dispatch, the lead is also appended to a **separate Google Sheets tab, `SundaySchoolLeads`** (`sheets_service.log_sunday_school_lead`, 
`SUNDAY_SCHOOL_TAB` constant) — intentionally isolated from the booking "Leads" tab schema. No Calendar event, no booking.

3. **Adult events (adult_events, type `adult_events`)** — captured via **subscription**, not per-event registration. `adult_llm_engine`'s deterministic consent layer (`_deterministic_subscribe`) calls `AdultToolExecutor` → `adult_subscription_service.subscribe` → `sheets_service.save_event_subscriber`, writing to a third, separate **Google Sheets tab, `events`** (18 columns, subscriber-style: consent, notified_event_ids, etc.). This records "notify me about future adult events," not a reservation for a specific event — actual registration for a specific event is just a `reservation_url`/`payment_terms` link surfaced in the chat, with no CRM row at all unless the user also separately subscribes or a manager handoff is triggered.

### 3.4 What a NEW admin-added product would get

**Confirmed: effectively nothing.** The Admin Panel (`/admin/programs`) lets an operator add a new `section` to `sections.yaml` with an arbitrary `id`/`type`, and the generic fact/Q&A surface (comment DM templates, discovery_questions, price/description fields) would render for it. But:
- There is no generic "book this product" tool — `book_consultation` is PARENT/camp-specific (hardcoded Calendar semantics, age-band checks tied to camp's `age_min`/`age_max`).
- There is no generic "hand this product's lead to the manager via email + separate Sheets tab" — the Sunday-School path is wired by literal section-id checks in `parent_flow.py`, not by `type`.
- There is no generic "subscribe me to updates for this product" — the ADULT subscription tool/executor/Sheets-tab triad is hardcoded to the `adult_events` type end-to-end (tool schemas in `app/agent/tools/adult_tools.py`, executor in `adult_tool_executor.py`).
- A brand-new `type` value (e.g. `"workshop"`) would fall through to no PARENT/ADULT specialized flow at all — it would only get whatever the generic camp-vs-adult top-level segment router chooses, i.e., most likely nothing captures a lead for it; at best a human operator would have to notice the conversation manually. This is confirmed by the fact that every lead-capture code path found in this survey is gated on either a hardcoded section id (`sunday_school`) or a hardcoded `type` string (`camp`'s booking tools, `adult_events`'s subscription tools) — there is no dispatch-by-arbitrary-type mechanism.

---

## Synthesis

**Nurture — LIVE vs DEAD:**
- LIVE: the 24h/72h/168h follow-up *scheduler mechanics* (APScheduler tick, kill-switch/`FOLLOWUP_ENABLED` gating, PARENT-only, blocked-reason gating, platform-aware send, admin-editable `templates.yaml` bodies (`followup_24h`/`followup_3d`/`followup_7d`), stage advancement + Redis write-through).
- DEAD: `app/agent/knowledge/followup_strategy.yaml` in its entirety as a runtime input — cadence numbers, blocked-reason list, and message bodies are all independently hardcoded/duplicated in Python (`followup_service._FOLLOWUP_CADENCE`, `_BLOCKED_REASONS`) or in `data/admin_config/templates.yaml`; the YAML's `scenario_followups` (price/age/said-will-think branches) are never read by anything. `app/agent/knowledge/audience_segments.yaml` is fully dead — not loaded by any Python code, referenced only in prose inside `app/agent/policies/parent_sales_policy.md`, which is *itself* never loaded into any prompt. No live audience-based personalisation exists beyond the coarse PARENT/ADULT/UNCLEAR segment router.

**Lead lifecycle (one line):** `Conversation.followup_stage` cycles `"" → first_24h → second_3d → third_7d`, gated by `Conversation.followup_blocked_reason ∈ {"", booked, registered, declined, asked_no_more_messages, manager_handoff_completed, followup_exhausted}` (the last set by the scheduler itself after stage 3), with `Lead.calendly_booked`/`status` and `adult_subscription_status` as parallel, product-specific completion signals rather than one unified state machine.

**Per-product lead capture:** camp → Calendar booking + Sheets "Leads" tab + email/WhatsApp; Sunday School → hardcoded email handoff (`notify_sunday_school_handoff`) + separate Sheets "SundaySchoolLeads" tab; adult events → subscription consent + Sheets "events" tab (notify-me list, not per-event registration). All three are bespoke, hand-wired to a specific section id or `type` string.

**Biggest gap for "every product gets its own function AND lead":** there is no generic, data-driven lead-capture dispatch keyed off an admin-configurable product `type`. Every one of the three existing capture mechanisms (Calendar-booking tool, email-handoff-with-dedicated-Sheets-tab, subscription-tool-with-dedicated-Sheets-tab) is a separate hardcoded Python code path tied to a literal section id or type string, each with its own tool schema, executor, and Sheets tab. A new admin-added product today gets fact/Q&A surfacing only — zero lead capture — until an engineer hand-writes a fourth bespoke path. The rebuild needs one generic "product" abstraction (tool schema + executor + CRM sink, parameterised by the product's declared capture mode — e.g. `booking` / `handoff` / `subscription` — read from `sections.yaml`) so a newly admin-added product automatically gets a function *and* a lead-capture path without a code change.
