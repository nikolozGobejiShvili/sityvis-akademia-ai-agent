# Reasoning Layer Phase 2 — Central Turn Intent Gateway (2026-06-23)

## Problem (live test)
The agent behaved like a keyword bot in the adult/event tail:
- „მე ვარ 29 წლის და მინდა ღონისძიებებს გავეცნო" → „**29 რიცხვში** აქტიურ
  ღონისძიებას ვერ ვპოულობ" (the AGE 29 was read as calendar **day 29**).
- „მადლობა არ მინდა" / „აღარ მინდამადლობა" → „**ამ სახელით** აქტიურ ღონისძიებას
  ვერ ვპოულობ" (a DECLINE was read as an event-name **search**, looping forever).

**Root cause (architecture, not a one-off):** a domain handler consumed the
message *before global intent was understood*. `parent_flow._maybe_handle_event_inquiry`
runs at handle() line ~226, **before** the decline handler (~line 280); its
`_extract_event_day_reference` had no age-vs-date guard, and its sticky context
`_bot_recently_listed_events` re-armed itself on every „not found" reply. The
ADULT engine's `_maybe_handle_named_adult_event` had the same flaw via a loose
genuine-name gate (it accepted „გავეცნო" as an event name).

## Fix — a central Turn Intent Gateway (deterministic, always-on)
`app/reasoning/reasoning_layer.py` gains `analyze_turn_intent(message) -> TurnIntent`
— a DETERMINISTIC, metadata-only classifier that runs **before** the sticky
domain handlers and decides routing. It NEVER answers the user, NEVER invents
facts, NEVER causes side effects (no email/WhatsApp/Calendar/Sheets), and is
fail-closed (any error → low-confidence default → existing behaviour).

`TurnIntent` carries: `segment`, `topic`, `intent`, entities (`age`, `date_text`,
`phone`, `event_query`), `is_decline`/`is_affirmation`/`is_topic_switch`/
`is_age_statement`/`is_manager_phone_request`, and the two routing decisions the
caller acts on: **`block_event_inquiry`** and **`clear_event_context`**.

**Age-vs-date** is the central disambiguation: a number bound to „წლ…/წელ…" is an
AGE (never a day); a number adjacent to a month stem / „რიცხვ" / „-ში" is a DATE.

### Integration (always-on, fail-closed)
- `parent_flow.handle()` computes the gateway once and passes it to
  `_maybe_handle_event_inquiry`, which returns None when `block_event_inquiry`
  is True (decline / manager-phone / Sunday-School / registration / age-statement
  without a date). A genuine event name or a real date still resolves.
- `parent_flow._extract_event_day_reference` gained the age guard (defense in
  depth): „29 წლის" → None; „29 აგვისტოს" → 29.
- `adult_llm_engine.run_adult_llm_turn` gates `_maybe_handle_named_adult_event`
  with the same gateway, so an age-statement / decline no longer triggers the
  named-event search in the adult flow either.

### Priority (effective)
safety/injection (existing) → Sunday-School (existing) → PII state-recall
(existing) → **gateway** → event interceptor (now gated) → registration → engine
(decline / manager-phone / contact / booking handlers) → LLM. The gateway makes
intent the single source that gates the sticky handlers; the deterministic safety
handlers (booking tool-success gate, PII masking, manager-phone helper,
contact/name validation) remain authoritative and unchanged.

## Gating decision — Option A (deterministic, always-on)
The gateway is deterministic (no LLM), so it is **always-on**, NOT behind a
flag. `USE_REASONING_LAYER` stays **default OFF** and still gates ONLY the Phase-1
`analyze_parent_turn` decline-defer (unchanged, backward compatible).

## What is NOT touched
booking tool-success gate, Calendar/Sheets schema, WhatsApp/email logic, manager-
phone helper, camp-facts helpers, prompt/sanitizer, contact/name validation,
OpenAI model, YAML/data. No deploy; production NOT green.

## Adult operator-data risk (PART H) — unchanged, operator action
Only active adult event = **„fromula 1"** (typo) — `price_text`=5000 but
`price_gel`=4999 (conflict), date „28 აგვისტო". The gateway fix does NOT depend on
this. Per policy the adult surface is **not open-client-ready** until the operator
cleans/deactivates „fromula 1". (Camp flow is unaffected and clean.)

## Verification
- Full pytest **2923 passed / 0 failed / 28 skipped** (2893 baseline + 30 new).
- corpus **9/9**, property **28/28**, `test_agent` **PASS**.
- CRITICAL **22/22**, transcript **3/3**.
- Live-LLM smoke of the exact broken transcript → **PASS** (no „29 რიცხვში", no
  „ამ სახელით", no decline loop; declines → polite close). No live WhatsApp/Meta.
- Pre-existing wall-clock date-bomb fixed (`test_admin_multi_event_support`:
  hardcoded „23 ივნისი" collided with today → made clock-relative; unrelated to
  the gateway).

## Files changed
`app/reasoning/reasoning_layer.py`, `app/flows/parent_flow.py`,
`app/agent/llm/adult_llm_engine.py`, `tests/test_turn_intent_gateway_2026_06_23.py`
(new, 30 tests), `tests/test_admin_multi_event_support.py` (date-bomb fix).
