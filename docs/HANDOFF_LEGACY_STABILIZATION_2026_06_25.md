# HANDOFF — Legacy/Giant-Prompt Stabilization (2026-06-25)

> Newest handoff. Read this FIRST. It supersedes the planner-focused
> 2026-06-24 handoffs **for the operating-mode decision**: we are deliberately
> running the **legacy/giant-prompt** path, with planner/slim **OFF**, because
> live answers were better there. The planner work is preserved but dormant.

---

## 1. Current status

- **Production is NOT declared green.** Open client test: NOT approved.
- **Legacy/giant-prompt mode is the active stabilization path.** The PARENT LLM
  engine runs (giant prompt + tools); the Conversation Planner and slim prompts
  are **disabled by operator decision** because live responses were better in
  legacy mode than in planner/slim mode.
- **Four production-risk legacy bugs were fixed and accepted** this session
  (contact-name extraction, child-age re-ask, topic-switch/action priority,
  consultation slot-merge). See §3.
- The planner/slim stack (Classes 1–6, selected-state, response_policy, Stage-3)
  remains in the codebase but **gated OFF**; do not re-enable it casually
  (see §8).
- HEAD after this session's accepted work: **`a2dcc5b`**.

---

## 2. Active flags (exact expected state)

The live `.env` is in LEGACY mode. Expected flag state:

```
USE_CONVERSATION_PLANNER=false
CONVERSATION_PLANNER_AUTHORITATIVE=false
CONVERSATION_TRACE_DEBUG=false
USE_SLIM_PROMPTS=false
USE_PARENT_LLM_ENGINE=true
```

> ⚠️ Earlier docs (e.g. `CLAUDE.md` / `HANDOFF_PLANNER_STABILIZATION_2026_06_24.md`)
> said the operator's `.env` had all four planner/slim/trace flags `true`. That
> is **superseded** — the operator reverted to legacy mode (the four above are
> off). `USE_PARENT_LLM_ENGINE` stays `true`.
>
> Do NOT turn planner/slim back on unless a future task explicitly requests it.

---

## 3. Accepted fixes (this session)

All four are LEGACY-path fixes (planner/slim OFF). Deterministic, no
phrase-specific input handlers, no `.env`/data changes.

### 1. `9dd0b84` — `fix: prevent Georgian relationship words from being saved as contact names`
- Georgian relationship/context words are no longer stored as the parent's name.
- `"10 წლის არის ჩემი შვილი ნიკოლოზი 595999733"` → `child_age=10`,
  `name=ნიკოლოზი`, `phone=595999733`; `"შვილი"` is no longer the name.
- Where: `parent_flow._name_token_is_valid` (new relationship/context reject set
  + safe stems), `_parse_name_phone` (prefers the name immediately before the
  phone), `_maybe_handle_contact_collection` (captures child_age independently).
- Tests: `tests/test_contact_name_extraction_2026_06_25.py`.

### 2. `68b0004` — `fix: suppress repeated child-age questions in legacy flow`
- If `child_age` is already known, the legacy path never re-asks it.
- Shared detector `app/reasoning/age_question.py` — `AGE_QUESTION_RE` +
  `contains_child_age_question` + `strip_child_age_questions` (sentence-level).
  Catches `რა წლისაა` / `რამდენ წლისაა` / `რამდენი წლისაა` / `რომელ კლასშია` /
  `ბავშვის ასაკი`; does NOT strip eligibility statements like
  `"ბანაკი 9–17 წლის ბავშვებისთვისაა"`.
- Where: `parent_flow._strip_redundant_age_question_if_known` (runs on the engine
  + legacy return paths; the planner validator is gated OFF in legacy),
  `_ensure_camp_age_question`, `parent_llm_engine._suppress_redundant_age_question`
  (now sentence-level — keeps the useful answer).
- Tests: `tests/test_legacy_child_age_no_reask_2026_06_25.py` (+
  `tests/test_child_age_no_reask_2026_06_24.py`).

### 3. `a3c5c17` — legacy topic switch / explicit-action priority
- After an adult-event context, an explicit camp action switches back to camp.
- `"ბანაკის სარეგისტრაციო ლინკი მომწერე"` now returns the registration link
  directly (`https://tinyurl.com/36jcae8z`), does NOT ask the child age, and does
  NOT stay stuck in adult-event context.
- Root cause: `_switch_to_adult_flow` makes `segment` sticky `ADULT`; the routing
  only flipped ADULT→PARENT for consultation/reschedule, so a camp registration
  request was routed to the adult flow.
- Where: new `app/reasoning/legacy_actions.detect_legacy_explicit_action`
  (intent/action-level); `conversation_service` ADULT→PARENT flip on an explicit
  camp action (camp-keyword/camp-context gated — a bare `"ლინკი მომწერე"` in
  adult context still stays adult); `parent_flow._maybe_handle_camp_registration_link`
  context-aware path. Link source: `admin_config_service.get_camp_facts()['registration_url']`.
- Tests: `tests/test_legacy_topic_switch_action_priority_2026_06_25.py`.

### 4. `a2dcc5b` — `fix: merge consultation booking slots so known slots are never re-asked`
- Booking is a slot machine over `parent_name / phone / child_age /
  desired_date / desired_time`. A known slot is never re-asked; a complete set
  proceeds to booking; a confirmation is never stored/echoed as a name.
- `"კი ჩანიშნეთ"` is treated as confirmation, not a name.
- Before: the agent re-asked name/phone after already receiving them, and echoed
  `"მივიღე, კიჩანიშნეთ"`. After:
  `"მივიღე, ნიკოლოზი. კონსულტაცია 26 ივნისი, 12:00 საათზე ჩაგინიშნეთ. მენეჯერი დაგიკავშირდებათ."`
- Where: new `parent_flow.get_consultation_booking_slots(conversation)` (slot
  source-of-truth merging lead + pending_booking);
  `_maybe_commit_pending_booking_engine` (captures child_age from the turn; asks
  only for the single missing slot when an OFFERED slot was explicitly chosen;
  compound all-in-one strips phone+age before the date parse);
  `_NAME_REJECT_STEMS` += booking-confirmation stems; `_maybe_handle_contact_collection`
  name-only capture (`_bot_last_reply_asked_for_name`).
- Tests: `tests/test_legacy_consultation_slot_merge_2026_06_25.py`;
  `tests/test_parent_llm_engine.py::test_patch5_guard_allows_chaginishnet_with_tool_success`
  updated (a one-shot complete booking now includes the age — the age is a
  required slot).

---

## 4. Known remaining full-suite failures (do NOT hide these)

`pytest tests/ -q` → **3108 passed / 28 skipped / 5 failed**. All 5 are
**pre-existing and unrelated to the four legacy fixes** (each verified failing on
HEAD with the legacy changes reverted):

- **2× `tests/test_p1_live_polish_2026_06_16.py`**
  (`test_b2_unknown_named_event_no_invention`,
  `test_wording_past_event_answer_has_paragraph_break`):
  caused by the operator's uncommitted `data/admin_config/sections.yaml` having
  **0 active adult events** (`_maybe_handle_event_inquiry` returns the
  no-active-events reply). With the committed `sections.yaml` (HEAD) both pass.
- **3× `tests/test_conversation_planner_authoritative_2026_06_24.py`**
  (`test_state_recall_typo_returns_summary_not_booking_question`,
  `test_booking_recall_uses_confirmed_booking`,
  `test_calm_correction_uses_existing_booking`):
  **date-bomb** — they hardcode `booked_datetime_iso="2026-06-25T12:00"`; once
  the wall clock passes 12:00 Tbilisi the booking auto-expires and recall returns
  the help CTA. These are **planner-authoritative** tests (not the legacy active
  path); fixing them is a separate test-hygiene task (make the dates
  clock-relative).

> **Production is NOT fully green until these are resolved or isolated.** They
> are known/unrelated, not silently passing.

Real-LLM `scenario_runner_full --priority CRITICAL` → **22/22** (booking 3/3;
SC-46 "Everything in One Message" passes) when run against the committed
`sections.yaml` (stash the operator edit for a clean run, then restore).

---

## 5. Operator data warning

- `data/admin_config/sections.yaml` is an **uncommitted operator edit**.
- It currently has **0 active adult events** (the single configured adult event
  is date-filtered out).
- **It must not be committed accidentally.** Every commit this session
  explicitly excluded it.
- **Before adult-event smoke testing, seed or restore a real active adult
  event** (otherwise the agent correctly says there are no active events — that
  is expected behaviour, not a bug). The committed `sections.yaml` (HEAD) carries
  test data.

---

## 6. Next required step — ONE full real legacy-mode smoke

The next step is **NOT another patch.** Run one full real legacy-mode smoke that
proves the four recent commits work together. Flags must be the §2 legacy state.

Smoke transcript (one clean conversation):

1. `გამარჯობა ბანაკის რეგისტრაციის ლინკი მინდა`
2. `მადლობა, ბანაკზე მაინტერესებს ინფორმაცია, პირობები, ფასი რა არის და როდის ტარდება?`
3. `უსაფრთხოების ზომები დაცულია? ბავშვთან კომუნიკაციას შევძლებ?`
4. `კი მინდა კონსულტაცია`
5. `595999733`
6. `ნიკოლოზი`
7. `ჩემი შვილი 14 წლის არის და 26-ში 12:00 საათზე მაწყობს`
8. `კი ჩანიშნეთ`
9. `ზრდასრულთა ღონისძიებები მაინტერესებს ჩემთვის`
10. `ბანაკის სარეგისტრაციო ლინკი მომწერე`

Expected:
- registration link returned directly when requested (turns 1 and 10);
- no child-age re-ask once `child_age` is known;
- name / phone / age / time preserved during booking (no re-ask);
- `"კი ჩანიშნეთ"` treated as confirmation (clean booking confirmation, NOT echoed
  as a name);
- adult topic switch works (turn 9);
- camp topic switch back works (turn 10);
- no private phone leak;
- no hallucinated adult event when 0 active events exist (with the current
  operator `sections.yaml`, "no active events" + optional manager/subscription is
  the correct answer).

Run with externals mocked + REAL OpenAI (model `gpt-4.1-mini`). A controlled
harness pattern exists at `tools/diagnose_trace_2026_06_24.py` (forces flags via
`os.environ`, mocks externals via the scenario runner). For a clean adult-event
result, seed an active event or stash the operator `sections.yaml`.

---

## 7. Next likely fix AFTER the smoke passes

Answer-quality / factual grounding for camp safety + child-contact questions,
e.g. turn 3: `"უსაფრთხოების ზომები დაცულია? ბავშვთან კომუნიკაციას შევძლებ?"`.

Expected future work:
- answer safety / child-contact questions from `admin_config` / tool data;
- if the data is not configured, say it is **not specified** and offer the
  manager to explain;
- **do not invent** safety details, supervisor counts, or communication policy.

This is a content/grounding task, not another routing patch. Source facts only
from `admin_config_service` / tools / config — never hardcode them in code or
prompt.

---

## 8. What NOT to do next

- **Do NOT immediately return to planner/slim** unless a future task explicitly
  requests it. Live answers were worse there.
- **Do NOT re-enable all four flags** (`USE_CONVERSATION_PLANNER`,
  `CONVERSATION_PLANNER_AUTHORITATIVE`, `USE_SLIM_PROMPTS`,
  `CONVERSATION_TRACE_DEBUG`) without a dedicated migration plan + supervised
  smoke.
- **Do NOT add phrase-specific handlers.** Keep detection intent/action-level
  (e.g. `legacy_actions.detect_legacy_explicit_action`, `age_question` helpers).
- **Do NOT commit `data/admin_config/sections.yaml`** (operator data) by accident.
- **Do NOT treat `"ღონისძიებები ჩემი შვილისთვის"` as a bug** when no child events
  are active — the current behaviour (no active events → say so / offer manager)
  is acceptable when there are no active child events.

---

## Quick reference — commits & files

| Commit | Title | Key files |
|---|---|---|
| `9dd0b84` | contact-name extraction | `app/flows/parent_flow.py` |
| `68b0004` | child-age no re-ask | `app/reasoning/age_question.py`, `app/flows/parent_flow.py`, `app/agent/llm/parent_llm_engine.py`, `app/agent/prompts/parent_core.md` |
| `a3c5c17` | topic-switch / action priority | `app/reasoning/legacy_actions.py`, `app/services/conversation_service.py`, `app/flows/parent_flow.py` |
| `a2dcc5b` | consultation slot-merge | `app/flows/parent_flow.py`, `tests/...` |

New shared modules this stabilization arc: `app/reasoning/age_question.py`,
`app/reasoning/legacy_actions.py`. Both are deterministic, dependency-free of the
planner, and safe to use from the legacy path.
