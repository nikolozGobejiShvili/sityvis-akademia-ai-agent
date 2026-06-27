# HANDOFF — Legacy/Giant-Prompt Stabilization (2026-06-28)

> **Newest handoff. Read this FIRST.** It supersedes
> [`HANDOFF_LEGACY_STABILIZATION_2026_06_25.md`](HANDOFF_LEGACY_STABILIZATION_2026_06_25.md)
> for current status. The planner/slim work in the older docs is **historical /
> dormant — NOT the active live path right now.** Do not delete old handoff
> history; it is preserved for reference.
>
> **HEAD after this session's accepted work: `01b0d2a`** (branch `master`).

---

## 1. Current live mode (legacy/giant-prompt)

The live runtime is the **legacy/giant-prompt** path. Planner + slim are **OFF**.

```
USE_PARENT_LLM_ENGINE=true
USE_CONVERSATION_PLANNER=false
CONVERSATION_PLANNER_AUTHORITATIVE=false
USE_SLIM_PROMPTS=false
```

- **Planner/slim must remain OFF** unless a separate, explicit migration task is
  created. Live answers were better in legacy mode; the planner stack (Classes
  1–6, selected-state, response_policy, Stage-3) is preserved but **dormant**.
- **`CONVERSATION_TRACE_DEBUG=true`** in the live `.env` is **observability-only**
  (per-turn structured trace logging). It does **not** change behaviour. It may
  be left on or turned off; it is not a planner/slim flag.
- Production is **NOT** declared green. Open client test: not approved.

---

## 2. Accepted / recent legacy fixes

All are LEGACY-path fixes (planner/slim OFF), deterministic, no phrase-specific
input handlers, no `.env`/data changes. Commit hashes on `master`.

| # | Commit | Fix |
|---|---|---|
| 1 | `9dd0b84` | relationship/name extraction |
| 2 | `68b0004` | child-age no re-ask |
| 3 | `a3c5c17` | topic-switch / explicit-action priority |
| 4 | `a2dcc5b` | consultation slot-merge |
| 5 | `97a2d66` | manager-contact-vs-decline priority |
| 6 | `bd368b2` | booking day/time reply not adult-event fallback |
| 7 | `01b0d2a` | Sunday-School coming_soon + out-of-range age + duplicate camp-price |

### 1. `9dd0b84` — relationship/name extraction
- Georgian relationship/context words (e.g. `„შვილი"`) are **not** saved as the
  parent's name. `„10 წლის არის ჩემი შვილი ნიკოლოზი 595999733"` →
  `child_age=10`, `name=ნიკოლოზი`, `phone=595999733`.

### 2. `68b0004` — child-age no re-ask
- When `conversation.lead.child_age` is already known, the agent does **not**
  ask the age again. Shared detector `app/reasoning/age_question.py`.

### 3. `a3c5c17` — topic-switch / explicit-action priority
- After an adult-event context, an explicit **camp registration-link** request
  returns the camp link (`https://tinyurl.com/36jcae8z`), does not re-ask the
  child age, and switches the topic back to camp. New
  `app/reasoning/legacy_actions.detect_legacy_explicit_action`.

### 4. `a2dcc5b` — consultation slot-merge
- Booking is a slot machine over `parent_name / phone / child_age /
  desired_date / desired_time`. A known slot is never re-asked; a complete set
  proceeds to booking; `„კი ჩანიშნეთ"` is a confirmation, not a name.
  `parent_flow.get_consultation_booking_slots`.

### 5. `97a2d66` — manager-contact-vs-decline priority
- `„კონსულტაცია არ მინდა მენეჯერის ნომერი რომ მომწეროთ და მე თვითონ დავურეკავ"`
  → `„მენეჯერის ნომერია: 558 67 47 33. შეგიძლიათ პირდაპირ დაუკავშირდეთ."`
- The manager-contact request **outranks** a generic decline when both occur in
  the same message. Decline-only is unchanged. Self-call (`„მე თვითონ
  დავურეკავ"`) never asks the user to leave their own number. `„მენეჯერის ნომერი
  არ მინდა"` (refusing the number) still closes politely. Manager number from
  `admin_config_service.get_manager_phone()` (never hard-coded).
- `parent_flow._maybe_handle_decline_engine` defers to
  `_maybe_handle_explicit_manager_request`.

### 6. `bd368b2` — booking day/time reply must not fall into adult events
- When the agent asks the consultation day/time and the user replies
  `„ორშაბათს, საღამოს საათებში"`, the conversation **stays in consultation
  booking**. It no longer falls into adult events with
  `„ამ ეტაპზე აქტიური ღონისძიება სიაში არ მაქვს."`.
- Root cause: `„საღამოს"` (evening daypart) matched the `„საღამო"` adult-event
  word inside `_maybe_handle_event_inquiry`. Fix: that interceptor steps aside in
  consultation-booking context for a date/time/daypart reply; a broad daypart
  with no exact time **asks for the exact hour** (daypart-aware: evening →
  18:00/19:00/20:00), an exact time defers to the existing booking commit/engine.
  General day/time-in-booking-context detection — not phrase-specific. Adult-event
  queries (`„ზრდასრულთა ღონისძიებები რა გაქვთ?"`) still work.

### 7. `01b0d2a` — Sunday-School coming_soon + out-of-range age + duplicate camp-price
Three deterministic legacy fixes (current behaviour):
- **Sunday-School intent routes to Sunday-School, not camp.** While status is
  `coming_soon` the response is:
  `„საკვირაო სკოლის დეტალები ჯერ ზუსტდება. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."`
  It does **not** reveal the month, price, registration link, locations, or full
  program, and does not demand the parent's name/phone — it **offers** the
  manager. (`parent_flow._render_sunday_school_answer`, gated on
  `status == "coming_soon"`.)
- **Out-of-range child age** (below the 9–17 camp band, e.g. `6`) returns the
  9–17 eligibility + manager-consultation wording and is **never** stored as the
  parent's name. `„6 წლის არის მაგრამ 10 წლის ბავშვივით აზროვნებს"` →
  eligibility answer, `name` not set. (`parent_flow._maybe_handle_out_of_range_age`,
  before contact collection.)
- **Duplicate camp price:** the FIRST camp-price question gives the full answer
  (with `2150₾`); a SECOND same-intent camp-price question gives a short repeat
  (`„როგორც ზემოთ მოგწერეთ, ბანაკის ღირებულებაა 2150₾."`). A different question
  after price (e.g. dates, payment-method) is **not** suppressed. Sunday-School
  and adult-event price questions are **not** treated as camp_price.
  (`parent_flow._maybe_handle_repeat_camp_price`, history-based count of
  camp_price user turns — no module state, survives Redis reload.)
- **Note — webhook dedupe deferred:** there is no DM message-id/event-id dedupe
  today (only `processed_comment:{id}` for comments), so an identically
  re-delivered webhook *event* is not suppressed at the transport layer. The
  duplicate-price fix is **semantic** shortening only; transport-level dedupe is
  deferred.
- Tests: `tests/test_legacy_sunday_school_and_duplicate_age_guard_2026_06_27.py`
  (+19). Three existing Sunday-School tests + two admin Sunday-School tests were
  updated to the new coming_soon contract.

---

## 3. Known full-suite failures (known, unrelated — do NOT hide)

`pytest tests/ -q` → **3147 passed / 28 skipped / 14 failed** (today 2026-06-28).
The +19 over the prior baseline are the new combined-fix tests. The 14 failures
are **pre-existing, unrelated test-hygiene / operator-data issues — NOT caused by
the legacy fixes** (each reproduces with the legacy code reverted):

- **3× `test_conversation_planner_authoritative_2026_06_24`** — date-bomb,
  hardcoded past date `2026-06-25T12:00`. **Planner-authoritative path — OFF in
  live mode.**
- **5× `test_legacy_consultation_slot_merge_2026_06_25`** — hardcoded `2026-06-26`
  (now past) date-bomb.
- **4× adult-event tests** (`test_adult_event_broadcast`,
  `test_adult_event_detail_selection_link` ×2, `test_comment_specific_event_mapping`)
  — past-date / dirty-config data-bombs.
- **2× `test_p1_live_polish_2026_06_16`** — caused by the dirty/operator
  `data/admin_config/sections.yaml` having **0 active adult events**.

Make clear:
- These are **not** caused by the latest legacy fixes.
- The **planner path is OFF** in live mode (the 3 planner failures are off-path).
- A clock-relative test-hygiene pass would clear the date-bombs; seeding a real
  active adult event would clear the adult/`p1` failures. **Do NOT fix the `p1` /
  adult failures by committing operator `sections.yaml`.**

---

## 4. Operator data warning (STRONG)

⚠️ **`data/admin_config/sections.yaml` may be dirty and contains operator/admin
data. Do NOT stage or commit it unless explicitly requested.** Every commit this
stabilization arc has explicitly excluded it.

- Current known issue: **active adult events may be 0** in the local operator
  data, which causes the adult-event / `test_p1_live_polish` tests to fail.
- **Do NOT "fix" this by committing operator data.** Seed a real future active
  adult event (via the Admin Panel / a local-only edit) before adult-event smoke;
  do not commit that seed.

---

## 5. Sunday School status

- Sunday School has existing status support (`sections.yaml` `sunday_school` via
  `admin_config_service.get_sunday_school_status()`).
- **Current status: `coming_soon`.**
- While `coming_soon`, the agent **must hide** all of:
  - the **195₾ monthly price**
  - **4 meetings**
  - **1h45 duration**
  - **locations**
  - the **Google Form registration link**
  - **full program details**
- The only coming_soon response is:
  `„საკვირაო სკოლის დეტალები ჯერ ზუსტდება. თუ გსურთ, მენეჯერთან დაგაკავშირებთ."`
- When Sunday School becomes **active** in the future, structured facts can be
  enabled **separately** (a dedicated active-status task).
- Sunday School must **not** mix with camp or adult events.
- **Do NOT add full Sunday-School facts** (price / meetings / duration /
  locations / form link / program) until a separate active-status task is
  approved.

---

## 6. Next planned task (run AFTER `/clear`, after the new session reads this handoff)

**`Structured Camp Topic Facts by Question Category`** — already prepared.

Purpose: add camp facts **by category**, answered only for the relevant category
(not a full fact dump):

- safety
- parent communication
- food
- gadgets
- confidence / motivation
- communication / socialization
- bullying / empathy
- emotional intelligence
- thinking / expression
- independence / responsibility
- interests / orientation
- values / identity
- activities / creativity
- sports / health
- rest / environment
- general overview

Rules:
- Answer **only** the relevant category, not all facts.
- **Max 1–2 topic blocks per answer.**
- Do **not** override the canonical flows: price, dates, registration link,
  booking, manager phone, adult events, Sunday School.

This task is prepared and should be run after the new session reads this handoff.

---

## 7. User-facing wording rules

**Do NOT use:**
- `„დაგიტოვებთ ინტერესს"`
- `„ინტერესი დაფიქსირდა"`
- `„lead"`
- `„ლიდი"`
- `„ლიდი შეიქმნა"`

**Use instead:**
- `„მენეჯერთან დაგაკავშირებთ"`
- `„მენეჯერი დაგიკავშირდებათ"`
- `„მენეჯერის ნომერია: 558 67 47 33"`

**Gadgets:**
- Use `„გაჯეტებისგან განტვირთვა"`.
- Do **not** use `„ეკრანისგან დისტანცია"`.

---

## 8. Quick reference — commits & files this arc

| Commit | Title | Key files |
|---|---|---|
| `9dd0b84` | contact-name extraction | `app/flows/parent_flow.py` |
| `68b0004` | child-age no re-ask | `app/reasoning/age_question.py`, `app/flows/parent_flow.py`, `app/agent/llm/parent_llm_engine.py` |
| `a3c5c17` | topic-switch / action priority | `app/reasoning/legacy_actions.py`, `app/services/conversation_service.py`, `app/flows/parent_flow.py` |
| `a2dcc5b` | consultation slot-merge | `app/flows/parent_flow.py`, `tests/...` |
| `97a2d66` | manager-contact-vs-decline priority | `app/flows/parent_flow.py`, `app/reasoning/legacy_actions.py`, `tests/...` |
| `bd368b2` | booking daypart not adult-event fallback | `app/flows/parent_flow.py`, `tests/test_legacy_booking_daypart_not_adult_events_2026_06_27.py` |
| `01b0d2a` | SS coming_soon + out-of-range age + duplicate price | `app/flows/parent_flow.py`, `tests/test_legacy_sunday_school_and_duplicate_age_guard_2026_06_27.py`, `tests/test_sunday_school_handoff_2026_06_22.py`, `tests/test_admin_sunday_school_preservation_2026_06_22.py` |

All legacy/deterministic; planner/slim OFF throughout. `data/admin_config/sections.yaml`
never committed.
