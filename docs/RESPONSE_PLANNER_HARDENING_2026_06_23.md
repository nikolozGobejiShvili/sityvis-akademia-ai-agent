# Response Planner Hardening — intent-aware answers, PII-safe recall, human tone (2026-06-23)

Builds on the Central Turn Intent Gateway (Phase 2). The handlers/templates now
USE the already-understood intent instead of answering robotically — without
adding new per-phrase paths. Six live findings, fixed centrally.

## A — PII leak (CRITICAL): full phone echoed in state recall
**Root cause:** the user's full phone is in the LLM context (`phone=595999733`),
and a typo'd recall („ემზე რა ინფრომაცია გაქვს?") bypassed the masked deterministic
handler and reached the LLM, which echoed the number. No final-output PII guard.
**Fix (central):** `conversation_service._mask_user_phone_in_response` runs at the
SINGLE chokepoint (before history append), masking `lead.phone` (any spacing /
`+995`) → „595***733" on EVERY reply (parent/adult/unclear). The manager phone (a
different number) is untouched; idempotent; never raises. The gateway also flags
`is_state_recall` typo-tolerantly („ემზე"/„ინფრომაცია").

## B — registration link returned for a consultation + child concern
**Root cause:** the live message had the typo „კოსულტაცია" (no „ნ"), so the
„კონსულტაც" defer-guard missed it and „ჩაწერა" matched the registration markers.
**Fix:** `_is_camp_registration_link_request` defers on „კონსულტ" OR „კოსულტ" OR
„ჯავშ". The gateway also exposes `is_consultation_request` / `is_child_concern`.

## C — redundant „თქვენთვის თუ შვილისთვის?" despite „ჩემთვის" + age
**Root cause:** the adult LLM never received the gateway's adult-self signal.
**Fix:** on `gateway.is_adult_self` (self-ref / adult age, no child), the adult
engine captures `lead.adult_age`, which routes `_ensure_adult_intro_followup` to
the „offer events" branch instead of the for-whom clarifier. Never overwrites an
existing adult_age / relative target / child_age.

## D — robotic tone meta-explanation
**Root cause:** no deterministic tone-request handler; the LLM explained its tone.
**Fix:** `parent_flow._maybe_handle_human_tone_request` returns a SHORT natural ack
for a PURE „be human / no scripted text" request (`gateway.is_human_tone_request`);
defers when the turn also carries a real business question.

## F — general-knowledge / insult treated as an event search
**Root cause:** no PARENT off-topic guard; the gateway didn't block event inquiry
on a general-knowledge „ვინაა?" / insult, so the sticky event interceptor fired
(„ამ სახელით ვერ ვპოულობ").
**Fix:** the gateway flags `is_off_topic` / `is_insult` (only when NO business
signal is present) → `block_event_inquiry` + `clear_event_context`. The ADULT
„who is X?" off-topic redirect was softened so it is not framed as an event-not-found.
„მუფასა ღონისძიება გაქვთ?" (a genuine event question) still resolves.

## PART G — centralization
All new signals live on `TurnIntent` (is_consultation_request, is_child_concern,
is_human_tone_request, is_off_topic, is_insult, is_state_recall, is_adult_self), so
handlers consult ONE gateway instead of re-detecting per phrase. No new domain
paths; the deterministic safety handlers (booking tool-success gate, PII masking,
manager-phone helper, contact/name validation) remain authoritative and unchanged.

## Gating
The gateway + PII mask are DETERMINISTIC and ALWAYS-ON. `USE_REASONING_LAYER`
stays default OFF (Phase-1 decline-defer only).

## Verification
- Full pytest **2949 passed / 0 failed / 28 skipped** (2923 + 26 new).
- corpus **9/9**, property **28/28**, `test_agent` **PASS**.
- CRITICAL **22/22**, transcript **3/3**.
- Live-LLM smoke of all six findings → **PASS** (no full phone; no registration link
  on consult+concern; no for-whom for adult-self; clean tone ack; off-topic/insult
  → no event search). No live WhatsApp/Meta.

## Data note (NOT a code change)
The „გია მურღულია" adult event was removed from the operator `sections.yaml` during
this session (the YAML is byte-identical to its `.bak`; I did NOT edit it). Two
unit tests + the SC-TX-03 transcript that depended on that live event were adapted:
a synthetic past-event fixture for the unit tests; SC-TX-03's gia turn now expects
the (correct) unknown-event response. **Recommended follow-up:** investigate whether
a non-isolated admin test wrote to the real `sections.yaml` (test-isolation), and
have the operator confirm/clean adult-event data before open testing.

## Files changed
`app/services/conversation_service.py`, `app/reasoning/reasoning_layer.py`,
`app/flows/parent_flow.py`, `app/agent/llm/adult_llm_engine.py`,
`tests/test_response_planner_hardening_2026_06_23.py` (new, 26),
`tests/test_adult_scope_guard.py` (3 assertion updates),
`tests/test_p1_live_polish_2026_06_16.py` (synthetic gia fixture),
`tools/scenario_library.py` (SC-TX-03 gia turn → current data). NO YAML/data,
NO prompt, NO Calendar/Sheets/WhatsApp/email, NO model change. Production NOT green.
