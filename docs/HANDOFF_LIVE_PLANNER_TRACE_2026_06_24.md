# HANDOFF UPDATE — Live Planner/Route Trace Root-Cause, 2026-06-24

> Continuation handoff for the next Claude Code session (post-`/clear`). Read this
> together with `docs/CURRENT_STATUS_AND_LIVE_REGRESSION_2026_06_24.md` and
> `CLAUDE.md`. **Diagnostic only — no behaviour was patched in the trace task.**

## 1. Current status

Production is still **NOT GREEN**.

The latest task added **observability only**:

* `CONVERSATION_TRACE_DEBUG` flag
* `app/reasoning/conversation_trace.py`
* wiring (`conversation_service._process_message_impl`, `parent_flow.handle`)
* `tools/trace_live_debug_2026_06_24.py`
* test isolation fix in `tests/conftest.py`
* commit: **b703e22**

No behaviour, prompt, YAML, model, or live integration was changed.

## 2. Trace method

Trace was run with:

* `CONVERSATION_TRACE_DEBUG=true`
* offline replay via `tools/trace_live_debug_2026_06_24.py`
* real `process_message` path
* LLM + Calendar/Sheets/Meta/WhatsApp/email mocked
* flags matching live:
  * `USE_CONVERSATION_PLANNER=true`
  * `CONVERSATION_PLANNER_AUTHORITATIVE=true`

## 3. Per-turn root cause summary

**A. Sunday School inquiry:**
* route: parent_flow
* planner called: no
* responder: `_maybe_handle_sunday_school`
* result: wrong
* issue: asks for name+phone even though already known

**B. Manager phone request:**
* route: parent_flow
* planner called: no
* responder: Sunday School pending collection → `_SUNDAY_SCHOOL_SUCCESS`
* result: wrong
* issue: pending Sunday School state swallowed a manager phone request and did not provide 558 67 47 33

**C. „რა ღონისძიებები გაქვთ?"**
* route: sticky parent_flow
* planner called: yes
* planner intent: adult_event_discovery, correct
* responder: parent_llm_engine
* result: wrong
* issue: planner was correct but did not route away from camp/parent LLM

**D. „ზრდასრულთა ღონისძიებებს ვგულისხმობ"**
* route: sticky parent_flow
* planner called: yes
* planner intent: adult_event_discovery, correct
* responder: parent_llm_engine
* result: wrong
* issue: adult topic did not reroute to adult flow or adult context

**E. „ჩემთვის მინდა"**
* route: parent_flow
* planner called: yes
* planner intent: adult_event_for_self, correct
* responder: parent_llm_engine
* result: wrong
* issue: child_age=7 remained visible while adult_age=null

**F. „ჩემი ასაკია 29, ეგ ჩემი შვილის ასაკია"**
* route: parent_flow
* planner called: yes
* planner intent: unclear, wrong
* responder: parent_llm_engine
* result: wrong
* issue: adult age self-correction was not classified and adult_age was not stored

**G. „ჩემზე რა ინფორმაცია გაქვს?"**
* route: parent_flow
* planner called: yes
* planner intent: state_recall, correct
* responder: planner_pre_answer
* result: partially correct
* issue: adult_age missing because F failed

**H. „არ მინდა"**
* route: parent_flow
* planner called: yes
* planner intent: decline, correct
* responder: planner_pre_answer + adult context clear
* result: correct

**I. „ბანაკზე როგორ დავრეგისტრირდე?"**
* route: parent_flow
* planner called: yes
* planner intent: camp_info
* responder: `_maybe_handle_camp_registration_link`
* result: correct
* issue fixed/working: registration link returned without asking age

**J. „რეგისტრაცია მინდა"**
* route: parent_flow
* planner called: yes
* planner intent: unclear, wrong
* responder: parent_llm_engine
* result: wrong
* issue: bare registration intent is not classified as camp_registration in active camp context

## 4. Main technical root causes

1. **Planner runs too late for some deterministic handlers.**
   Sunday School/static/pending handlers can answer before planner is called. This caused A and B.

2. **Planner is authoritative only for a narrow set of intents.**
   It directly controls only `state_recall`, `booking_recall`, `decline`, and `name_update`. Adult discovery/self intent is recognized but then ignored by final routing/answer generation.

3. **Segment stickiness overrides current topic.**
   The session remained sticky parent_flow after Sunday School/camp, even when planner `active_topic=adult_event`. Planner currently does not control route/segment switching.

4. **Adult event turns can be answered by parent camp LLM.**
   C/D/E were classified correctly as adult_event, but final answer still came from `parent_llm_engine`.

5. **Giant prompt is still active.**
   LLM turns still send `system_parent_v2.md`:
   * 111,675 bytes
   * 451 lines

   Adult prompt is also still large:
   * `system_adult_v1.md`
   * 54,636 bytes
   * 244 lines

   This supports over-scripted/copying behavior and makes the LLM ignore clean intent.

6. **Validator is too narrow.**
   Post-validator currently checks only one forbidden pattern: `do_not_use_consultation_format`. It does not enforce the other critical forbidden patterns, such as:
   * adult event answered as camp
   * child_age used as adult_age
   * manager phone request swallowed by pending state
   * registration request answered without link
   * known contact asked again

7. **Planner is read-only for state updates.**
   The adult age correction „ჩემი ასაკია 29, ეგ ჩემი შვილის ასაკია" was not captured and did not update adult_age while preserving child_age.

8. **Bare registration intent is not context-aware.**
   „რეგისტრაცია მინდა" should resolve to camp_registration when active context is camp/registration, but currently becomes unclear and falls to parent LLM.

## 5. Exact files/functions implicated

**A:**
* `parent_flow._maybe_handle_sunday_school`
* called before planner
* `_SUNDAY_SCHOOL_OFFER_TAIL` asks for contact even when known

**B:**
* Sunday School pending-collection handler
* returns `_SUNDAY_SCHOOL_SUCCESS`
* swallows manager phone request

**C/D/E/F/J:**
* `parent_flow._run_llm_engine_safely`
* `parent_llm_engine.run_parent_llm_turn`
* `system_parent_v2.md` giant prompt

**F:**
* `conversation_planner._plan` misclassifies adult-age self-correction as unclear
* no state-capture path writes adult_age

**J:**
* `conversation_planner._plan` misclassifies bare registration as unclear
* `_maybe_handle_camp_registration_link` does not trigger on bare registration in active camp context

## 6. What NOT to do next

Do not:

* add phrase-specific handlers for every failed line
* keep adding rules to `system_parent_v2.md`
* make full rollback
* claim production green because tests pass
* patch Sunday School only and ignore routing/prompt
* build full vector DB today
* expose full phone numbers in logs or responses
* change admin-managed Sunday School into code-hardcoded content

## 7. Next implementation direction

The next task should implement the following classes of fixes under flags:

### Class 1 — Planner first / pre-handler intent protection
Planner must run before Sunday School/pending/static handlers, or those handlers must receive planner intent and refuse to swallow unrelated turns.

Examples:
* `manager_phone_request` must override Sunday School pending collection
* known contact must not be re-asked

### Class 2 — Topic-routing authority
Planner `active_topic` must control route/segment switching.

Examples:
* `active_topic=adult_event` must not be answered by camp parent LLM
* `adult_event_discovery` / `adult_event_for_self` should route to adult flow or adult context

### Class 3 — Selected-state contract
LLM must receive `selected_state`, not raw/polluted state.

Examples:
* `adult_event_for_self` sees adult_age only
* child_age excluded unless explicitly relevant
* camp sees child_age only
* state_recall sees both separately

### Class 4 — Slim prompt / topic-scoped context
Add `USE_SLIM_PROMPTS` flag. When enabled:
* do not load `system_parent_v2.md` or `system_adult_v1.md`
* load short parent/adult core prompt
* inject planner policy + selected_state + topic-scoped knowledge only

### Class 5 — State writebacks from planner
Planner/classifier must support:
* adult age self-correction:
  „ჩემი ასაკია 29, ეგ ჩემი შვილის ასაკია" → adult_age=29, child_age preserved
* bare registration intent in active camp context:
  „რეგისტრაცია მინდა" → camp_registration

### Class 6 — Final validator expansion
Validator must enforce critical classes:
* child_age must not be used as adult_age
* adult event must not be answered as camp
* manager phone request must return 558 67 47 33
* registration request must return registration link and not append age question
* known name/phone must not be asked again
* decline must not use robotic forbidden phrase „სიამოვნებით."

## 8. Production-ready smoke test after next patch

After the next implementation task:
* restart server
* clear Redis/test session
* flags ON:
  * `USE_CONVERSATION_PLANNER=true`
  * `CONVERSATION_PLANNER_AUTHORITATIVE=true`
  * `CONVERSATION_TRACE_DEBUG=true`
  * `USE_SLIM_PROMPTS=true`, if implemented

Run this controlled smoke:

```
გამარჯობა ბანაკზე ინფრომაციამაინტერესებს
7 წლის არის
კი დამაკავშირეთ
ჯონი 595999733
მადლობა და კიდევ მაინტერესებს საკვირაო სკოლა როდის ემატება?
მენეჯერის ნომერი მომწერეთ და მეთვითონ დავურეკავ
ამ ეტაპზე რა ღონისძიებები გაქვთ?
ზრდასრულთა ღონისძიებებს ვგულისხმობ
ჩემთვის მინდა
ჩემი ასაკი 29 წელია, ეგ ჩემი შვილის ასაკია
ჩემზე რა ინფრომაცია გაქვს?
არ მინდა მადლობა
გამარჯობა ბანაკზე როგორ დავრეგისტრირდე?
რეგისტრაცია მინდა
```

Pass criteria:
* child_age=7 remains child_age
* adult_age=29 is separate
* adult self never uses child_age as adult_age
* manager phone request immediately returns 558 67 47 33
* Sunday School does not ask known name/phone again
* adult event questions do not get camp answer
* state recall includes name, masked phone, child_age, adult_age, handoff/booking summary if present
* decline does not use „სიამოვნებით."
* registration link answer does not append age question
* no full phone leak
* no invented facts
* trace proves final route/handler/prompt/context/validator behavior

## 9. Final conclusion

The trace proved the problem is not that the LLM is „stupid."
The system still gives control to:
* pre-planner deterministic handlers
* sticky parent route
* giant camp prompt
* raw polluted state/history
* weak validator

The fix must move the agent from:
**large prompt + sticky handler bot**

to:
**planner-first + topic routing + selected state + slim prompt + final validator.**

---

## Appendix — commit timeline (for `git log` navigation)

* `68c81f7` — baseline (pre-surgical-rollback snapshot; git initialized + safe `.gitignore`)
* `69582fa` — surgical guard narrowing (adult-event age exemption; adult_age≠child_age)
* `b402834` — Conversation Planner Stage 1 (contract + shadow, default OFF)
* `284b60b` — Conversation Planner Stage 2 (authoritative mode, default OFF)
* `373ff24` — boot-flag visibility + `docs/CONVERSATION_PLANNER_ROLLOUT_2026_06_24.md`
* `b703e22` — **this task:** live trace diagnostics + test-isolation fix

Gates at `b703e22`: `pytest tests/` **2992 passed / 0 failed / 28 skipped**; corpus **9/9**;
property **28/28**; `test_agent.py` PASS; CRITICAL **22/22**; transcript **3/3**
(CRITICAL/transcript last run at `284b60b`, unaffected by the trace-only change).

**Operator `.env` note:** `USE_CONVERSATION_PLANNER=true` AND
`CONVERSATION_PLANNER_AUTHORITATIVE=true` are currently set live (lines 112–113).
`CONVERSATION_TRACE_DEBUG` is NOT yet in `.env` — add it + full restart to capture
live `[trace]` blocks.
