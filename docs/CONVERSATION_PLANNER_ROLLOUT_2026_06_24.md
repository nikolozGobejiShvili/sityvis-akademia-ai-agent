# Conversation Planner — Rollout & Smoke Checklist (2026-06-24)

Two-flag, default-OFF rollout of the Conversation Planner (Reasoning Layer
Phase 3). **Shadow first → observe → authoritative.** No deploy, no live
Calendar/Sheets/Meta/WhatsApp/email. Production stays NOT green until live smoke
passes.

Code: `app/reasoning/conversation_planner.py` (contract), wired in
`app/flows/parent_flow.py`. Flags in `app/config.py`. Commits: `b402834`
(Stage 1) + `284b60b` (Stage 2).

---

## 0. Current state (already in `.env`)
- `USE_CONVERSATION_PLANNER=true` is **already set** (`.env` line ~112) → the
  planner will compute in **shadow** (log-only) once the server is restarted.
- `CONVERSATION_PLANNER_AUTHORITATIVE` is **absent** → defaults **False** →
  planner is **not** authoritative yet (replies unchanged).

So today you only need a **restart** to start observing the shadow logs.

---

## 1. Flags

### Phase A — SHADOW (observe only; replies do NOT change)
```
USE_CONVERSATION_PLANNER=true
# CONVERSATION_PLANNER_AUTHORITATIVE  -> leave UNSET or false
```

### Phase B — AUTHORITATIVE (planner constrains the reply)
```
USE_CONVERSATION_PLANNER=true
CONVERSATION_PLANNER_AUTHORITATIVE=true
```

### Rollback (instant)
```
CONVERSATION_PLANNER_AUTHORITATIVE=false   # back to shadow
# or
USE_CONVERSATION_PLANNER=false             # planner fully off
```
Then **full restart** (see §2).

---

## 2. Restart — MANDATORY (settings are import-time `@lru_cache`d)
`uvicorn --reload` is NOT enough — `settings` is built once at import.
Do a **full stop + start**:
```
# stop the running server (Ctrl+C), then:
PYTHONIOENCODING=utf-8 python -m uvicorn app.main:app --port 8006
```
Confirm at boot the new lines:
```
⚙️ USE_CONVERSATION_PLANNER=True
⚙️ CONVERSATION_PLANNER_AUTHORITATIVE=False   # (True in Phase B)
```
If you don't see them → the new code/flag isn't loaded (stale process).

Then clear Redis: `redis-cli FLUSHALL`.

---

## 3. Phase A — SHADOW smoke (replies unchanged; read the LOGS)
Send each message (fresh conversation per block) and read the server log line:
```
[planner][shadow] intent=<…> topic=<…> policy=<…> clear=<…> use_booking=<…> ask_clarify=<…> reason=<…>
```
Compare the logged decision against **Expected**:

| # | Message | Expected `intent` / `topic` |
|---|---|---|
| 1 | `ჩემი სახელია ნიკოლოზი` | `name_update` / `general_state` |
| 2 | `ზრდასრულთა კულტურული ღონისძიებები 7 წლის ბავშვებისთვის არის?` | `adult_event_for_child` / `adult_event` (NOT camp) |
| 3 | `ჩემთვის მინდა ღონისძიებები რას შემომთავაზებთ?` | `adult_event_for_self` / `adult_event` |
| 4 | `ჩემთვის და ჩემი შვილისთვის მინდა ღონისძიება, მე ვარ 30 წლის` | `adult_event_for_self_and_child` (look for adult_age=30, not child) |
| 5 | `ჩემზე რა ინფრომაცია გავქს?` (typo) | `state_recall` / `general_state` |
| 6 | `კონსულტაცია როდის მაქვს?` (after a booking) | `booking_recall` / `consultation`, `use_booking=True` |
| 7 | `არ მინდა მადლობა` | `decline` or `adult_event_decline`, `clear=['adult_event_target', …]` |
| 8 | `შემეძლება ბანაკის განმავლობაში ბავშვს დავურეკო?` | `camp_child_contact` / `camp` |
| 9 | `უსაფრთხოება დაცულია? რამდენი ზედამხედველი ეყოლებათ?` | `camp_safety` / `camp` |

✅ **Gate to Phase B:** the logged `intent`/`topic` match Expected on these turns
(replies are still the OLD behaviour — that's correct for shadow).

---

## 4. Phase B — AUTHORITATIVE smoke (replies SHOULD now change)
Set `CONVERSATION_PLANNER_AUTHORITATIVE=true` → full restart → `FLUSHALL`.
Replay; now the **replies** must satisfy:

1. **State recall** (`ჩემზე რა ინფრომაცია გავქს?`, with a prior booking) →
   a summary: name + **masked** phone (`595***733`) + child age + your age (if
   known) + the confirmed booking. **No** „რომელი დღე და საათი?" question.
2. **Booking recall** (`კონსულტაცია როდის მაქვს?`) → „კონსულტაცია ჩანიშნულია
   <date, time>. ახალ ჩაწერას აღარ გთავაზობთ." **No** new-consultation offer.
3. **Calm correction** (`აბა რატო მთავაზობ ახალ კონსულტაციას?`) → confirms the
   existing booking, does not offer a new one or say the slot is unavailable.
4. **Decline** (`არ მინდა მადლობა`) → polite close; the adult-event context is
   cleared (a follow-up camp question must not carry adult-event state).
5. **Name update** (`ჩემი სახელია ნიკოლოზი`, with a stale child_age=7) → a short
   ack; **never** the „9–17 ბანაკი / ვერ შემოგთავაზებთ" underage narrative.
6. **Camp safety/contact/visit** (`...დავურეკო?` / `უსაფრთხოება...ზედამხედველი?`)
   → answers the camp question; **no** consultation phone/video format; child age
   **not** re-asked; if exact supervisor count is unknown → „ზუსტი რაოდენობა
   მითითებული არ არის" + offer manager. (Phone/video framing is auto-stripped.)
7. **Generic adult discovery** (`ჩემთვის მინდა ღონისძიებები...`) → does **not**
   say „ამ სახელით ვერ ვპოულობ"; lists/handles events.

✅ **Live-green criteria:** 1–7 hold AND no full phone leaks AND no duplicate
booking/notification on recall.

If any turn regresses → set `CONVERSATION_PLANNER_AUTHORITATIVE=false`, restart,
report the turn (message + reply + the `[planner]` log line).

---

## 5. What this rollout does NOT change (out of scope)
- **ADULT-segment** turns routed straight to `adult_llm_engine` (the planner is
  authoritative only in `parent_flow`; sticky-PARENT discovery still benefits).
- **Trace 4** (child_age persistence) / **Trace 8** (WhatsApp `ALLOW_LIVE_WHATSAPP`
  + `@lru_cache` restart) — separate, not planner issues.
- **„fromula 1"** dirty adult-event data — operator admin_config cleanup.
- LLM context still receives cleaned state via **state-clears + post-validator**,
  not a full `state_to_use` prompt injection (Stage 2.1).

---

## 6. Safety invariants (unchanged by this rollout)
- PII final phone mask — active.
- WhatsApp isolation / `ALLOW_LIVE_WHATSAPP` / `_send_manager_whatsapp` mock — active.
- Surgical guard narrowing (adult-event age exemption; adult_age≠child_age) — active.
- Fake-booking guard — active.
- Tests: `pytest tests/` 2992/0/28 · corpus 9/9 · property 28/28 · test_agent PASS
  · CRITICAL 22/22 · transcript 3/3. **Production NOT green.**
