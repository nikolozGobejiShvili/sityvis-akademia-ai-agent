# HANDOFF — Planner-First Stabilization + Consultant-Quality Policy, 2026-06-24

> Continuation handoff. Implements the Class 1–6 fix plan from
> `docs/HANDOFF_LIVE_PLANNER_TRACE_2026_06_24.md`, then the adult generic-discovery
> fix, then the consultant-quality conversation policy (Stage 3). All new
> behaviour is behind the existing planner flags (`USE_CONVERSATION_PLANNER` +
> `CONVERSATION_PLANNER_AUTHORITATIVE`) plus `USE_SLIM_PROMPTS`. Default OFF +
> pinned OFF in tests → the planner-off suite is byte-identical.
> **Production is still NOT GREEN until the supervised staging smoke passes.**

## CURRENT STATE (READ FIRST after /clear)
* **HEAD = `70b2d8b`** (branch `master`). Commit timeline since the trace-only
  baseline `e67b1ab`:
  * `0897e08` — Planner-First Stabilization (Classes 1–6) — see "What changed".
  * `5aba5f3` — Adult generic-discovery vs named-event fix — see that section.
  * `70b2d8b` — Consultant-quality conversation policy (Stage 3) — see that section.
* **Gates at `70b2d8b`:** `pytest tests/` **3031 passed / 0 failed / 28 skipped**
  (run against the COMMITTED `sections.yaml`); corpus **9/9**; property **28/28**
  (`RUN_PROPERTY_TESTS=1`); `test_agent.py` PASS. Controlled real-LLM smoke
  (externals blocked) — all critical turns correct.
* **Operator `.env` has all four flags LIVE:** `USE_CONVERSATION_PLANNER=true`,
  `CONVERSATION_PLANNER_AUTHORITATIVE=true`, `CONVERSATION_TRACE_DEBUG=true`,
  `USE_SLIM_PROMPTS=true`. Settings are `@lru_cache`d → a flag change needs a
  FULL restart (not `--reload`).
* **Uncommitted working tree:** ONLY `data/admin_config/sections.yaml` — an
  operator admin-panel edit (active adult event = „maroon 5 კონცერტი", currently
  date-filtered → 0 active). Intentionally not committed. Committed HEAD still
  carries the test data (fromula 1).
* **New modules:** `app/reasoning/selected_state.py`, `app/reasoning/response_policy.py`,
  `app/agent/prompts/{parent_core,adult_core}.md`. New tests:
  `tests/test_planner_stabilization_2026_06_24.py`,
  `tests/test_adult_generic_discovery_2026_06_24.py`,
  `tests/test_conversation_policy_2026_06_24.py`. Offline smoke harness:
  `tools/trace_planner_smoke_2026_06_24.py`.
* **NEXT:** supervised STAGING smoke (full restart + `FLUSHALL`) → seed a real
  future active adult event → only then a controlled Meta test. Do NOT connect
  the client's real Page first.

## What changed (by Class)

**Class 1 — Planner-first / pre-handler protection.**
* The unified `TurnPlan` is now computed ONCE at the `conversation_service`
  routing chokepoint and stashed on the conversation (`_turn_plan`), so it is
  available BEFORE the Sunday-School / static / pending handlers (and reused by
  `parent_flow` — no drift).
* New planner intent `manager_phone_request`. `parent_flow.handle` answers it
  with the configured manager number at the TOP of the handler (before Sunday
  School) — so a pending Sunday-School collection can no longer swallow it.
* `_maybe_handle_sunday_school` takes the plan: a clear unrelated current intent
  mid-collection DEFERS; a KNOWN name+phone dispatches the handoff with the
  stored contact and never re-asks.

**Class 2 — Topic-routing authority.**
* `conversation_service._planner_route_decision` makes `plan.active_topic`
  control the route: `adult_event` → ADULT flow (sticky switch), `camp` /
  `consultation` → PARENT (override sticky ADULT), neutral intents
  (recall / manager / decline / registration) → PARENT for THIS turn without
  flipping the sticky segment. Adult-event questions are never answered by the
  parent camp engine.

**Class 3 — Selected-state contract.** New `app/reasoning/selected_state.py`:
given the plan + lead it returns ONLY the relevant state — `adult_event_for_self`
sees `adult_age` (child_age EXCLUDED); camp sees `child_age` (adult_age
EXCLUDED); `state_recall` sees both, separately; the phone is always masked.
Recorded in the trace (`selected_state`) on every authoritative turn; injected
into the slim-prompt context.

**Class 4 — Slim prompts.** New `USE_SLIM_PROMPTS` flag (default OFF). When ON
the engines load `parent_core.md` / `adult_core.md` (short core prompts) instead
of `system_parent_v2.md` / `system_adult_v1.md`, and inject only the planner
policy + selected_state. The old prompt files are NOT deleted. The trace records
`prompt_mode=slim|giant`.

**Class 5 — Planner state writebacks.**
* Adult-age self-correction: „ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია" →
  `plan.writeback_adult_age=29`; applied to `lead.adult_age` (child_age
  preserved); `active_topic` stays `adult_event`.
* Bare registration in an active camp context: „რეგისტრაცია მინდა" →
  `camp_registration` → returns the registration link, no age question.

**Class 6 — Expanded final validator.** `parent_flow.planner_final_validate`
(called centrally from `conversation_service` on BOTH routes) enforces:
child_age never shown as adult_age; adult-event never answered as camp; a
manager-phone request returns the number; a registration request returns the
link without an age question; known contact not re-asked; decline never uses the
robotic „სიამოვნებით."; full phone never leaked (central mask is the backstop).

## Files changed
* `app/config.py` — `USE_SLIM_PROMPTS` flag.
* `app/main.py` — boot prints for `USE_SLIM_PROMPTS` / `CONVERSATION_TRACE_DEBUG`.
* `app/reasoning/conversation_planner.py` — manager_phone / adult_age_correction /
  bare-registration intents + writeback fields + new forbidden flags.
* `app/reasoning/selected_state.py` — NEW (Class 3 contract + formatters).
* `app/services/conversation_service.py` — compute plan once, topic-routing
  authority, writeback apply, central final validator, selected_state trace.
* `app/flows/parent_flow.py` — planner-first manager-phone protection;
  Sunday-School deferral + known-contact dispatch; `_planner_pre_answer` for
  manager/camp_registration; `planner_final_validate`.
* `app/agent/llm/parent_llm_engine.py` + `adult_llm_engine.py` — slim prompt
  build + selected_state injection + `prompt_mode` trace.
* `app/agent/prompts/parent_core.md` + `adult_core.md` — NEW core prompts.
* `tests/conftest.py` — pin the new flags OFF for `conversation_service` + engines.
* `tests/test_planner_stabilization_2026_06_24.py` — NEW (16 tests, Classes 1–6 +
  the full A–N replay).
* `tools/trace_planner_smoke_2026_06_24.py` — NEW offline smoke-trace harness.
* `.env.example` — documents the planner / trace / slim flags.

## Feature flags added / used
* NEW: `USE_SLIM_PROMPTS` (default False).
* USED (already existed): `USE_CONVERSATION_PLANNER`, `CONVERSATION_PLANNER_AUTHORITATIVE`,
  `CONVERSATION_TRACE_DEBUG`, `USE_PARENT_LLM_ENGINE`, `USE_ADULT_LLM_ENGINE`.

## Live controlled smoke (operator)
Flags ON: `USE_CONVERSATION_PLANNER=true`, `CONVERSATION_PLANNER_AUTHORITATIVE=true`,
`CONVERSATION_TRACE_DEBUG=true`, and (recommended) `USE_SLIM_PROMPTS=true`. FULL
restart (settings are `@lru_cache`d) + `FLUSHALL` Redis. Offline rehearsal:
`python tools/trace_planner_smoke_2026_06_24.py` (LLM mocked).

## Follow-up — adult generic-discovery vs named-event lookup (2026-06-24)
The controlled real-LLM smoke surfaced one residual: a GENERIC adult-events
question („ამ ეტაპზე რა ღონისძიებები გაქვთ?" / „ზრდასრულთა ღონისძიებებს
ვგულისხმობ") routed correctly to `adult_flow` but the adult route's
deterministic named-event interceptor could still answer „ამ სახელით ღონისძიება
ვერ მოვძებნე". Fixed (no new behavior beyond this):
* `adult_llm_engine.run_adult_llm_turn` now SKIPS `_maybe_handle_named_adult_event`
  when the authoritative planner flags `F_NO_NAMED_EVENT_LOOKUP`
  (`_planner_forbids_named_event_lookup`) — generic discovery is handled by the
  LLM via the `get_adult_events` tool (lists active events, or says none are
  active). Never „ვერ მოვძებნე".
* The planner classifies a GENUINE event-name reference as `adult_event_named`
  (no forbidden pattern) so the deterministic named-event resolver still runs for
  real named lookups.
* `_has_genuine_event_name_token` no longer treats the generic discourse words
  „ეტაპ" / „ვგულისხმ" or the CATEGORY word „ღონისძიებ*" as event names.
* Tests: `tests/test_adult_generic_discovery_2026_06_24.py` (generic → no
  „ვერ მოვძებნე"; named lookup still resolves; planner-off regression).

## Stage 3 — consultant-quality conversation policy (2026-06-24)
Refines answer/CTA/composition so the agent behaves like a thoughtful consultant
(source of truth: `docs/source/sales_agent_prompt.md` + the audience analysis).
Reasoning-driven (planner intent + selected_state + composer + validator), gated
on the AUTHORITATIVE planner; NO giant-prompt rules, NO per-phrase handlers.
New module `app/reasoning/response_policy.py` (config-driven composers — every
fact comes from `admin_config_service`).

* #1/#2 camp_info opens with a value intro + the child-age question (no price /
  link / manager phone); explicit price → value-framed price from config.
* #3 eligible child age → pain-point discovery (screen time / communication /
  interests / confidence), not generic qualification.
* #4 consultation CTA → the MANAGER explains the details (wording fix).
* #5 Sunday-School info → answer status + OFFER consent; dispatch ONLY after
  explicit consent (no auto-handoff, no needless „მადლობა"). Legacy collect-then-
  dispatch flow kept for planner-off so the existing SS suite is unaffected.
* #6 subscription consent → `subscription_request`/`subscription_save`: no
  adult-age ask, uses known name + MASKED phone, confirms, then saves via the
  existing `adult_subscription_service`.
* #7 manager phone shown in full (558 67 47 33); user phone always masked.
* #8 camp registration (incl. the „დარეგისტირება" typo) → link first, no forced
  consultation / no age question.
* #9 greeting after a closed/declined context → neutral menu (no stale camp/age).
* #11 concise: drop a redundant second „მადლობა".
* Tests: `tests/test_conversation_policy_2026_06_24.py` (16). Suite 3031/0/28.

## Remaining risks / NOT-GREEN items
* The adult-event turns are answered by the REAL adult LLM engine live — its
  prose quality is not asserted offline (only the route + selected_state +
  prompt mode are). A live operator smoke is still required before green.
* Slim prompts move camp/event facts from the prompt to the tools — the live
  smoke should confirm the LLM still calls `get_camp_info` / event tools.
* „fromula 1" dirty adult-event data + Meta App Review remain open (unchanged).
