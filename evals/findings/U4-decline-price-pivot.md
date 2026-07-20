# FINDING U4 — free-form decline + price-pivot is hijacked into contact collection

**Status:** documented only — **NOT fixed** (surfaced by the eval harness, 2026-06-29).
**Dimension:** understanding · **Severity:** medium (real, deterministic UX bug)
**Mode:** legacy live (`USE_PARENT_LLM_ENGINE=true`, planner/slim OFF).

## Input / context
- Prior bot turn: „გსურთ კონსულტაციაზე ჩაგწეროთ?" · lead `child_age=13` (eligible), contact unknown.
- **User:** „არ მინდა კონსულტაცია, მაგრამ ფასი მაინც მაინტერესებს"
  (= "I don't want a consultation, **but I'm still interested in the price**").

## Observed (wrong)
Agent (byte-identical every run):
> „მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი, რომ კონსულტაცია ჩავნიშნოთ."

It (a) ignores the explicit refusal of the consultation and (b) never answers the
price question — instead it pushes contact collection to book a consultation.

## Reproduction — deterministic, NOT stochastic
`python -m evals.run_evals --case U4 --llm` → **0/5 passed** across 5 consecutive
runs, with the **identical** response each time (and **0/3** under best-of-3
majority vote). The byte-identical wording confirms a deterministic pre-engine
interceptor catches it — the LLM is never reached.

## Root cause (which interceptor catches it before the LLM)
Traced in `app/flows/parent_flow.py` `handle()` interceptor chain:

| interceptor | result for this message |
|---|---|
| `_maybe_handle_decline_engine` | `None` ✓ (correctly defers — „მაგრამ"/„მაინც" are in `_DECLINE_OVERRIDE_INTEREST`) |
| `_maybe_handle_contact_collection` | `None` ✓ (no phone in message) |
| **`_maybe_request_full_contact_on_intent`** | **returns the contact-ask** ✗ ← the culprit |

`_maybe_request_full_contact_on_intent` fires because
**`parent_flow._is_explicit_consultation_request("არ მინდა კონსულტაცია, მაგრამ ფასი მაინც მაინტერესებს")` returns `True`.**
Its negation guard recognises `„კონსულტაცია არ მინდა"` (negation **after** the
keyword) but **not** the `„არ მინდა <…> კონსულტაცია"` word order (negation
**before**). With an eligible `child_age` and missing contact, the handler then
asks for name+phone and the turn never reaches the price answer.

Note: `USE_REASONING_LAYER` (the decline+topic-switch analyzer) is **OFF** in the
current legacy mode, so nothing rescues the price-pivot intent downstream either.

## Expected (correct) behaviour
The agent should understand this as **decline-of-consultation + price question**:
1. NOT push contact collection / consultation booking (the user just declined it).
2. **Answer the price** („ბანაკის ღირებულებაა 2150₾ …", value-framed), and may
   softly leave the door open — without re-asking to book.

## Suggested fix direction (for a later, separate task — do NOT apply now)
⚠️ **NOT a new regex/substring guard.** Earlier this note suggested making
`_is_explicit_consultation_request` "negation-aware" for the
`„არ/ვერ <…> კონსულტაცია"` order — that guidance is **OUTDATED**. A per-phrasing
substring guard is exactly the bug (and a death spiral): the eval shows `U8`
(same `„არ მინდა …, მაგრამ <manager-number>"` shape) PASSES while `U4`
(`…მაგრამ <price>`) FAILS, purely on word order.

Fix at the **understanding layer with structured intent-extraction**: parse the
turn into `{decline: yes/no, declined_target: consultation, topic_pivot: price,
target_intent: ask_price}` and route on that structure — so a declined
consultation that co-occurs with a price (or any topic) question answers the
question and does NOT push contact collection. Then prove it with the eval
(`U4` 0/3 → 3/3, no other case regresses) and add a legacy regression test.

## Eval case
`evals/cases.py::_u4_decline_pivot` (id `U4`, `stochastic=True`, best-of-3).
