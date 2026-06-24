# HANDOFF — Planner-First Stabilization Patch (Classes 1–6), 2026-06-24

> Continuation handoff. Implements the Class 1–6 fix plan from
> `docs/HANDOFF_LIVE_PLANNER_TRACE_2026_06_24.md`. All new behaviour is behind the
> existing planner flags (`USE_CONVERSATION_PLANNER` +
> `CONVERSATION_PLANNER_AUTHORITATIVE`) plus the new `USE_SLIM_PROMPTS`. Default
> OFF + pinned OFF in tests → the 2992-test baseline is byte-identical.
> **Production is still NOT GREEN until the live controlled smoke passes.**

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

## Remaining risks / NOT-GREEN items
* The adult-event turns are answered by the REAL adult LLM engine live — its
  prose quality is not asserted offline (only the route + selected_state +
  prompt mode are). A live operator smoke is still required before green.
* Slim prompts move camp/event facts from the prompt to the tools — the live
  smoke should confirm the LLM still calls `get_camp_info` / event tools.
* „fromula 1" dirty adult-event data + Meta App Review remain open (unchanged).
