# AUDIT_REPORT — სიტყვის აკადემია AI Sales Agent

**Date:** 2026-05-22
**Scope:** Read-only architectural audit of `ai-agent/` working tree.
**Phase reference:** Phase 3.9 (LLM Parent Turn Analyzer, default OFF).

---

## 1. MESSAGE LIFECYCLE

ნაბიჯ-ნაბიჯ — Instagram DM → `POST /webhook` → გაგზავნილი პასუხი.

### 1.1 Webhook entry (sync)

`app/routes/webhook.py:38` `receive_webhook(request, background_tasks)`
1. `await request.json()` — payload-ის წაკითხვა.
2. `background_tasks.add_task(_process_payload, payload)` — ჩამოვა asyncio task-ად, Meta-ს დაუბრუნდება `{"status":"ok"}` სწრაფად (200 OK ≤ 5s, Meta-ს ლიმიტი).
3. ფუნქცია ბრუნდება. **Meta მიიღო 200, აღარ აქვს რეტრაი.**

### 1.2 Payload extraction (background)

`app/routes/webhook.py:66` `_process_payload(payload)`
1. `_extract_messages(payload)` ← `_extract_meta_messages` + `_extract_whatsapp_messages`. ამოიღება სია `[{sender_id, message_text, platform}, …]`.
2. თითო message → `await message_buffer.buffer_message(sender_id, message, platform, on_ready=_dispatch_buffered_reply)`.
3. ცალკე — `_process_comment_events(payload)` (იხ. §1.7).

### 1.3 Debounce (5-15s window)

`app/services/message_buffer.py:36` `buffer_message(...)`
1. `_pending_messages[sender_id].append(message)` — ფრაგმენტი ბუფერში.
2. ძველი `_pending_tasks[sender_id]` cancel-ი (თუ ეგ task ჯერ არ flush-ულა).
3. ახალი task → `_flush_after_delay` (`asyncio.sleep(min(DEBOUNCE_SECONDS, MAX_WAIT-elapsed))`).
4. **გადაწყვეტილება:** თუ ახალი message მოვიდა, ისევ cancel-ი → ისევ ფრაგმენტი დაემატება → ისევ ახალი timer. თუ 5წ გავიდა ბუფერით უმოძრაოდ — flush.
5. `_flush_after_delay`: ბუფერი pop, ფრაგმენტები ერთ string-ად შეერთება (space-ით), → `on_ready(sender_id, combined, platform)` → `_dispatch_buffered_reply`.

### 1.4 Dispatch (combined message)

`app/routes/webhook.py:93` `_dispatch_buffered_reply(sender_id, combined_message, platform)`
1. `conversation_service.process_message(sender_id, combined_message, platform)` (sync call).
2. პასუხის ცარიელობის ცეკი → `skip` თუ ცარიელია.
3. `messenger_service.send_message(sender_id, platform, response)` (3 retry × 2s sleep, httpx POST `me/messages` / WhatsApp endpoint).

### 1.5 Conversation routing

`app/services/conversation_service.py:189` `process_message(sender_id, message_text, platform)`
1. `_get_or_create_conversation(sender_id, platform)` — module-level `conversations: dict[str, Conversation]` (in-memory).
2. `conversation.history.append({"role": "user", "content": message_text})`.
3. სეგმენტის რესტრიქცია: თუ `conversation.segment not in {"PARENT", "ADULT"}` → `_classify_segment(message_text)` (deterministic keyword stems).
4. სეგმენტის მიხედვით:
   - `UNCLEAR` → `UNCLEAR_ROUTING` template (ერთი string, არც LLM).
   - `PARENT` → `parent_flow.handle(conversation, message_text)`.
   - `ADULT` → `adult_flow.handle(conversation, message_text)`.
5. `conversation.history.append({"role": "assistant", "content": response})`.
6. return response string.

### 1.6 PARENT flow execution (where the real logic lives)

`app/flows/parent_flow.py:74` `handle(conversation, message)`
1. `_ensure_lead(conversation)` — თუ `conversation.lead is None`, ახალი Lead.
2. `lead.last_message_at = conversation.last_activity`.
3. **DONE შემოწმება** → `PARENT_DONE_RESPONSE` (no LLM).
4. **Profile fetch (state=START, lead.name ცარიელია)** → `_fetch_profile_into_lead` → `messenger_service.get_user_profile(sender_id, platform)` (httpx GET, Meta Graph). შედეგი → `lead.name`.
5. **Phase 3.9 analyzer hook** → `maybe_handle_analyzer_interrupt(conversation, lead, message)`:
   - თუ `USE_LLM_TURN_ANALYZER == False` (default) → ბრუნდება `None`, ფლოუ აგრძელებს.
   - თუ `True` → იხ. §2 (LLM call #2-ის ცხრილში) → თუ analyzer intercept-ი მოხდა, ბრუნდება string და parent_flow აბრუნებს მას.
6. **Price escape (keyword-based)** → თუ state ∉ {START, DONE} და მესიჯში არის "ფასი/ღირს/რამდენი/...", → `PARENT_PRICE_IN_FLOW` template, state უცვლელია.
7. **State machine** (იხ. §3-ში სრული ცხრილი):
   - `START` → `_detect_safe_intent` (LLM, იხ. §2) → branch by intent → render template + advance to ASK_AGE.
   - `ASK_AGE` → `lead.child_age = message`; advance to ASK_CHALLENGE; render template (optional composer).
   - `ASK_CHALLENGE` → store challenge; advance ASK_DEEPER; template.
   - `ASK_DEEPER` → store deeper_concern; advance ASK_DESIRE; template.
   - `ASK_DESIRE` → store desired_change; `_generate_present_value(lead)` (LLM, იხ. §2) → state=`ASK_NAME`; append phone-ask.
   - `ASK_NAME` → `_parse_name_phone` (regex parser); validates phone; advance PRESENT_VALUE; render slots.
   - `PRESENT_VALUE`/`OFFER_BOOKING` → slot pick → `_attempt_booking` → calendar.book_slot → sheets.create_lead → notification.send_manager_notification (LLM summary call, იხ. §2) → state=DONE.

### 1.7 Comment events (parallel path)

`app/routes/webhook.py:126` `_process_comment_events(payload)`
1. გადახედავს `entry[*].changes[*]` — `field == "comments"` (Instagram) ან `field == "feed"` + `verb == "add"` (Facebook).
2. `handle_comment(comment_id, post_id, sender_id, user_name, comment_text, platform)`:
   - `comment_service.detect_comment_intent(comment_text)` → LLM (იხ. §2) → `INTERESTED` / `NOT_INTERESTED`.
   - თუ `NOT_INTERESTED` → skip.
   - `comment_service.determine_segment_from_post(post_id, platform)` → cache-ი 1h, Meta GET, hashtag extract → PARENT/ADULT/UNCLEAR.
   - `sheets_service.save_comment(...)` (Comments tab).
   - `comment_service.reply_to_comment(comment_id, user_name, has_dm_history)` → public reply via Meta POST `/<comment_id>/replies`.
   - თუ `has_dm_history` → `comment_service.send_dm_from_comment(...)` (Welcome DM).

### 1.8 Summary

ერთ მესიჯზე (DM): **1 webhook POST → 1 Meta send_message POST** (typical). შუაში — 0-3 OpenAI calls (იხ. §2). შენახვა — Sheets-ში მხოლოდ ჯავშნისას.

---

## 2. LLM CALL MAP

ერთ PARENT მესიჯზე LLM call-ების რაოდენობა დამოკიდებულია state-ზე **და** feature-flag-ებზე. ცხრილში — ყველა შესაძლო call.

| # | Where (file:func) | When triggered | Prompt (system + user) | Response | Decision |
|---|---|---|---|---|---|
| 1 | `openai_service.detect_start_intent` ← `parent_flow._detect_safe_intent` | სტეიტი=START, ანალიზერმა არ ჩაერია | `app/agent/prompts/detect_start_intent.md` (system) + raw user message (user) | ერთი სიტყვა: `GREETING` / `PRICE` / `BOOK` / `INFO` / `CONCERN` | parent_flow აირჩევს რომელი template-ი გადასცეს (`PARENT_WELCOME` / `PARENT_PRICE_FIRST_RESPONSE` / …); transition ASK_AGE-ზე. Fallback → `GREETING`. |
| 2 | `openai_service.analyze_parent_turn` ← `parent_turn_analyzer.analyze_parent_turn` | **`USE_LLM_TURN_ANALYZER=true` ONLY** (default false → never called). სტეიტი ∉ {PRESENT_VALUE, OFFER_BOOKING, ASK_NAME, DONE}. | `app/agent/prompts/parent_turn_analyzer.md` (system) + user payload (state + user_message + lead fields + camp_2026 summary + last 6 history turns) | strict JSON: `{primary_intent, provided_fields, user_wants_human, user_rejects_discovery, fact_types_requested, suggested_backend_action, confidence, reason_short}` | `parent_turn_router.maybe_handle_analyzer_interrupt` ვალიდაცია (closed whitelists). თუ confidence < 0.65 → clarifying question. თუ `ask_manager` → phone reply ან soft offer. თუ `answer_facts` → fact builder camp_2026.yaml-დან. `continue_flow` → fall through to state machine. **Backend აიღებს გადაწყვეტილებას, არა LLM.** |
| 3 | `openai_service.compose_reply` ← `parent_reply_composer.compose_parent_reply` | **`USE_LLM_COMPOSER=true` ONLY** (default false). მხოლოდ 4 PARENT discovery state: ASK_AGE (welcome), ASK_CHALLENGE, ASK_DEEPER, ASK_DESIRE. | `app/agent/prompts/system_base.md` + `system_parent.md` (system) + payload (state + lead + camp facts + next_action + tone anchor template) | natural Georgian reply text | fact-safety post-check (URL/phone/price/date regex). თუ ჩავარდა — fallback template. Composer **არ ცვლის state-ს**, არ წერს lead-ში, არ ჯავშნის. |
| 4 | `openai_service.generate_parent_value_response` ← `parent_flow._generate_present_value` | სტეიტი=ASK_DESIRE, user-მა "desired change" გასცა, advance ASK_NAME-ზე. | `app/agent/prompts/system_base.md` + `system_parent.md` + `parent_present_value.md` formatted with `{child_age, challenge, deeper_concern, desired_change}` | 3-აბზაცი insight + offer of consultation | text გადადის next_response-ში, შემდეგ append `_handle_ask_name(conv, lead, "")` (PARENT_ASK_PHONE_ONLY). Fallback → `PARENT_PRESENT_VALUE_FALLBACK` template. |
| 5 | `openai_service.generate_summary` ← `parent_flow._generate_summary` (also adult_flow) | ბრონირების შემდეგ, `_book_selected_slot` შიგნით (state→DONE-ის წინ). | `app/agent/prompts/summary.md` formatted with `{conversation_history}` | 3-წინადადებიანი ქართული რეზიუმე | ↓ `lead.conversation_summary`. შემდეგ → `notification_service.send_manager_notification(lead, summary)` (Email + WhatsApp + SMS). Fallback → `PARENT_SUMMARY_FALLBACK` template. |
| 6 | `openai_service.generate_response` ← `adult_flow._generate_event_response` / `_generate_done_response` | მხოლოდ ADULT flow (`SHOW_EVENTS` / `ANSWER_QUESTIONS` / `DONE` states). | `system_base.md` + `system_adult.md` + ADULT_EVENT_CONTEXT (event facts, history). | natural Georgian event answer | text → reply. Fallback → `_premium_event_response` template. **PARENT flow-ში არც ერთხელ არ გამოიძახება (dead path — იხ. §9).** |
| 7 | `comment_service.detect_comment_intent` | Comment event (Instagram/Facebook public comment) | `COMMENT_INTENT_PROMPT` (system) + comment text (user) | `INTERESTED` / `NOT_INTERESTED` | თუ `NOT_INTERESTED` → skip the comment, no reply, no DM. თუ `INTERESTED` → ცალკე path (segment-from-post + Sheets + reply + DM). |

### LLM call count per PARENT message (გრძელი ცხრილი):

| State | flags=off | analyzer=on | composer=on | both=on |
|---|---|---|---|---|
| START | 1 (detect_start_intent) | 1-2 (analyzer + maybe detect_start_intent if continue_flow) | 1-2 (detect + composer if GREETING branch) | 2-3 |
| ASK_AGE → ASK_CHALLENGE | 0 (template) | 1 (analyzer) | 1 (composer) | 2 |
| ASK_CHALLENGE → ASK_DEEPER | 0 (template) | 1 | 1 | 2 |
| ASK_DEEPER → ASK_DESIRE | 0 (template) | 1 | 1 | 2 |
| ASK_DESIRE → ASK_NAME | 1 (present_value) | 2 (analyzer + present_value) | 1 (present_value, no composer) | 2 |
| ASK_NAME → PRESENT_VALUE | 0 (regex parser) | **0** (analyzer skipped per router rule) | 0 | 0 |
| PRESENT_VALUE → DONE | 1 (summary at booking) | **1** (analyzer skipped, summary only) | 1 | 1 |

**Default (flags=off):** 7-message PARENT booking flow = **2 LLM calls** (detect_start_intent + summary).
**Composer on:** 7-message = **5 LLM calls** (detect_start + 3 composer + present_value + summary).
**Analyzer on:** 7-message = **7 LLM calls** (5 analyzer + detect_start + present_value + summary).
**Both on:** 7-message = **10 LLM calls**.

---

## 3. STATE MACHINE

`app/flows/parent_flow.py` state-ები — სრული ცხრილი.

| State | რას აგზავნის | რა input-ს ელოდება | transition next | LLM? | Static template? |
|---|---|---|---|---|---|
| **START** | `PARENT_WELCOME` (GREETING) / `PARENT_WELCOME_WITH_CONCERN` (CONCERN) / `PARENT_PRICE_FIRST_RESPONSE` (PRICE) / `PARENT_BOOK_FAST_TRACK` (BOOK) / `PARENT_INFO_FIRST_RESPONSE` (INFO) | ნებისმიერი first message | ASK_AGE | **იყენებს**: `openai_service.detect_start_intent` (intent detection). Composer (only GREETING branch). | YAML template branch-ის მიხედვით. |
| **ASK_AGE** | `PARENT_ASK_CHALLENGE` (default), or `PARENT_ASK_DEEPER` (when CONCERN intent pre-filled challenge) | child age (raw text) | ASK_CHALLENGE (default) / ASK_DEEPER (CONCERN branch) | Composer (optional). | YAML template. |
| **ASK_CHALLENGE** | `PARENT_ASK_DEEPER` | challenge text (stored raw) | ASK_DEEPER | Composer (optional). | YAML template. |
| **ASK_DEEPER** | `PARENT_ASK_DESIRE` | deeper concern text | ASK_DESIRE | Composer (optional). | YAML template. |
| **ASK_DESIRE** | LLM-generated PRESENT_VALUE + `\n\n` + `PARENT_ASK_PHONE_ONLY` (if name) ან `PARENT_ASK_NAME` (no name) | desired-change text | ASK_NAME | **იყენებს**: `generate_parent_value_response` (insight). | Fallback: `PARENT_PRESENT_VALUE_FALLBACK`. |
| **ASK_NAME** | `PARENT_OFFER_CONSULTATION` (with slots, after phone accepted) ან `PARENT_ASK_NAME_RETRY` / `PARENT_ASK_PHONE_RETRY_INVALID` | `name phone` strings, regex-parsed | PRESENT_VALUE (success) ან stays ASK_NAME (1 retry) | არ იყენებს LLM-ს. Regex parser. | YAML templates. |
| **PRESENT_VALUE** | First entry: `PARENT_OFFER_CONSULTATION` with 3 slot lines. | სლოტის არჩევანი ("1", "2", "3", time "14:00", date "22 მაისი 15:00") | OFFER_BOOKING (slot shown) → DONE (slot picked) ან PRESENT_VALUE-ში დარჩება (clarify). | არ იყენებს LLM-ს. **იყენებს**: `calendar_service.get_free_slots` (Google Calendar API). | YAML templates. |
| **OFFER_BOOKING** | `PARENT_BOOKING_CONFIRMED` (success) ან `PARENT_BOOKING_FAILED` / `PARENT_SLOT_UNAVAILABLE` / `PARENT_CLARIFY_SLOT_CHOICE` | სლოტის არჩევანი (იგივე) | DONE (success) ან stays OFFER_BOOKING | **იყენებს** (booking-ის შემდეგ): `generate_summary`. Plus `calendar_service.book_slot`, `sheets_service.create_lead`, `notification_service.send_manager_notification`. | YAML templates. |
| **DONE** | `PARENT_DONE_RESPONSE` | ნებისმიერი message | DONE (terminal) | არა. | YAML template. |

### Module-level conversation tracking dicts (`parent_flow.py`):

- `available_slots: dict[sender_id, list[slot]]` — current 3 slots shown to user.
- `ask_name_retries: dict[sender_id, bool]` — has retry been shown.
- `invalid_phone_retries: dict[sender_id, bool]` — same.
- `slots_shown_for_state: dict[sender_id, bool]` — guard to render slots once.
- `parent_turn_router.manager_offer_shown: dict[sender_id, bool]` — Phase 3.9 escalation flag.

ეს ყველაფერი **module-level globals, in-memory only.** პროცესის რესტარტი → ცარიელია.

---

## 4. LLM VS STATIC

### Default state (after `git pull`, no env vars set):

| Component | State |
|---|---|
| `USE_LLM_COMPOSER` | **OFF** (`bool = False` default in `app/config.py:193`) |
| `USE_LLM_TURN_ANALYZER` | **OFF** (`bool = False` default in `app/config.py:203`) |

### Which replies are LLM-generated vs static (defaults):

| Reply | Source |
|---|---|
| Initial intent classification | **LLM** (`detect_start_intent`) |
| `PARENT_WELCOME` ("რამდენი წლისაა შვილი?") | **YAML template** (`templates/parent/welcome.yaml`) |
| `PARENT_ASK_CHALLENGE` | **YAML template** |
| `PARENT_ASK_DEEPER` | **YAML template** |
| `PARENT_ASK_DESIRE` | **YAML template** |
| PRESENT_VALUE (insight reply at ASK_DESIRE) | **LLM** (`generate_parent_value_response`). Fallback: template. |
| `PARENT_ASK_PHONE_ONLY` ("ანა — გვითხარით ნომერი...") | **YAML template** (appended after LLM PRESENT_VALUE) |
| Slot list ("1️⃣ 15 მაისი - 14:00 …") | Deterministic (Google Calendar API + template) |
| `PARENT_BOOKING_CONFIRMED` ("დაჯავშნილია 🌿") | **YAML template** |
| Manager email/WhatsApp body | **YAML template** (notifications/manager.yaml). **შიგ summary — LLM.** |
| Conversation summary (manager notification) | **LLM** (`generate_summary`). Fallback: template. |
| Adult event description | **LLM** (`generate_response`). Fallback: template. |
| `UNCLEAR_ROUTING` | **YAML template** (deterministic keyword classifier in `conversation_service._classify_segment`) |
| Price escape (`PARENT_PRICE_IN_FLOW`) | **YAML template** (keyword-detected mid-flow) |

### What changes when flags flip on:

**`USE_LLM_COMPOSER=true`:**
- 4 PARENT discovery replies (GREETING/welcome, ASK_CHALLENGE, ASK_DEEPER, ASK_DESIRE) გადადის LLM-ზე — natural Georgian rewrite.
- Composer იღებს `camp_2026.yaml` ფაქტებს ყოველ turn-ზე.
- Fact-safety post-check: თუ LLM-ის output-ში URL/phone/price/Georgian-date დაფიქსირდა, output discard-ი + YAML template რენდერდება.
- Composer-ი **არ ცვლის state-ს**, არ ჯავშნის, არ წერს lead-ის ფსიქოლოგიურ ველებში.
- ცვლის: მხოლოდ ფრაზინგი. ბოტი იქცევა "უფრო ბუნებრივ" თუმცა — backend მაინც იღებს გადაწყვეტილებას.

**`USE_LLM_TURN_ANALYZER=true`:**
- ყოველ PARENT message-ზე (გარდა PRESENT_VALUE/OFFER_BOOKING/ASK_NAME/DONE) ერთვება analyzer LLM.
- Analyzer აბრუნებს structured JSON: intent (`ask_manager` / `ask_price` / `ask_dates` / …), `provided_fields`, `confidence`.
- Backend (`parent_turn_router.maybe_handle_analyzer_interrupt`) ვალიდირებს და გადაწყვეტს action-ს closed whitelist-ით.
- ცვლის: ბოტი **მართლა იწყებს მომხმარებლის intent-ის გაგებას** — manager-ის თხოვნა, ფასი, თარიღი, ლოკაცია, რეგისტრაცია → შესაბამისი deterministic answer camp_2026.yaml/company.yaml-დან.
- Low-confidence (< 0.65) → clarifying question (არა scripted discovery).
- Phone parsing **მაინც** existing regex-ის ხელშია (analyzer-ი ვერ ჩაანაცვლებს).

**ორივე ჩართული:**
- analyzer აიღებს გადაწყვეტილებას (continue_flow / answer_facts / …).
- თუ analyzer ამბობს `continue_flow` → composer გადააფერადებს scripted template-ს.
- თუ analyzer იჭერს (`answer_facts`, `offer_manager` …) → deterministic fact reply YAML-დან, composer **არ ერთვება** ამ path-ში.
- 2 LLM calls per typical discovery turn.

---

## 5. BRAIN QUESTION — ვინ იღებს გადაწყვეტილებებს

| გადაწყვეტილება | ვინ იღებს | სად |
|---|---|---|
| **სეგმენტი (PARENT / ADULT / UNCLEAR)** | **Backend** (deterministic keyword stems). LLM-ის `detect_segment` არსებობს მაგრამ live routing-ში **არ გამოიყენება**. | `conversation_service._classify_segment` (camp/adult/greeting stem matching) |
| **START intent (GREETING / PRICE / BOOK / INFO / CONCERN)** | **LLM** (`detect_start_intent`). | `parent_flow._detect_safe_intent` → `openai_service.detect_start_intent`. Fallback → GREETING. |
| **რომელი template ჩაიწეროს თითო state-ზე** | **Backend** (state machine if-blocks). | `parent_flow.handle()` — სტრუქტურული branch-ი. |
| **რომელ state-ზე გადადეს** | **Backend** (state machine). LLM-ი ვერ ცვლის state-ს. | `parent_flow.handle()` — `conversation.state = "ASK_X"`. **Composer და analyzer ვერ ცვლიან state-ს.** |
| **რა პასუხი გაიგზავნება** | **ჰიბრიდი:** გადაწყვეტილებას (რა შინაარსი) იღებს **backend** (state machine + price-escape keyword + analyzer's whitelist action). **ფრაზინგი (რა სიტყვებით)** — YAML template ან composer LLM ან deterministic fact builder. | `parent_flow.handle()` + `parent_turn_router.maybe_handle_analyzer_interrupt` + composer/template. |
| **booking გაკეთდეს თუ არა** | **Backend.** Slot picker (regex/string match), `_book_selected_slot`, `calendar_service.check_slot_available` (Google API), `calendar_service.book_slot` (Google API). LLM-ი ვერ ჯავშნის. | `parent_flow._handle_slot_selection` → `_attempt_booking` → `_book_selected_slot`. |
| **booking თარიღი/დროა მიღებული თუ არა** | **Backend** — `check_slot_available` Google Calendar Free/Busy API-ით. | `calendar_service.check_slot_available` |
| **lead Sheets-ში შენახული თუ არა** | **Backend.** მხოლოდ ჯავშნის შემდეგ. | `_book_selected_slot` → `sheets_service.create_lead` |
| **manager notify** | **Backend.** Email + WhatsApp + Twilio SMS. | `notification_service.send_manager_notification` |
| **ფასი უპასუხოს თუ discovery გააგრძელოს** | **ჰიბრიდი:** keyword-based "price escape" — backend (deterministic). Analyzer-ით (თუ ჩართულია) — analyzer ამბობს `ask_price`, backend ვალიდირებს და გადაწყვეტს. | `parent_flow._is_price_question` (PRICE_KEYWORDS tuple) → `PARENT_PRICE_IN_FLOW` template, OR `parent_turn_router._build_price_answer`. |
| **manager-ის request-ის ცნობა** | **Default OFF**: არ ცნობს, message-ი ინახება როგორც challenge/deeper_concern. **Analyzer ON**: LLM ცნობს intent-ს, backend ვალიდირებს `_is_explicit_contact_request` regex-ით (deterministic safety net), გადაწყვეტს soft offer ან phone reply. | `parent_turn_router._handle_manager_request` |
| **phone validation** | **Backend.** Regex parser, 9-digit check, valid local prefix (5/7/8). LLM-მა შეუძლია phone candidate-ი ამოიღოს, მაგრამ **backend-ი მაინც გადაატარებს** parser-ში. | `parent_flow._parse_name_phone` (`PHONE_CANDIDATE_PATTERN`, `VALID_LOCAL_PREFIXES`) |
| **slot choice (1/2/3, "14:00", "22 მაისს 15:00")** | **Backend.** Regex (`TIME_PATTERN`, `HOUR_SPELLING_PATTERN`, `_parse_custom_datetime`). LLM-ი ვერ ირჩევს slot-ს. | `parent_flow._handle_slot_selection` → `_parse_slot` / `_handle_custom_slot_request` |
| **low-confidence handling (analyzer ჩართულია)** | **Backend.** თუ confidence < 0.65 → clarifying question, არა scripted discovery. | `parent_turn_router.maybe_handle_analyzer_interrupt:` confidence threshold check before action branch. |
| **comment intent (public IG/FB comments)** | **LLM** (`detect_comment_intent`). | `comment_service.detect_comment_intent` |
| **comment segment (PARENT/ADULT) — from post hashtags** | **Backend.** Regex hashtag extraction + env-config matching. | `comment_service.determine_segment_from_post` |
| **PRESENT_VALUE insight content (ASK_DESIRE → ASK_NAME)** | **LLM** (`generate_parent_value_response`). 3-paragraph insight. | `parent_flow._generate_present_value` |
| **conversation summary for manager** | **LLM** (`generate_summary`). | `parent_flow._generate_summary` / `adult_flow._generate_summary` |
| **adult flow event details** | **LLM** (`generate_response`). | `adult_flow._generate_event_response` |
| **debounce decision (5s vs flush now)** | **Backend.** `DEBOUNCE_SECONDS=5`, `MAX_WAIT_SECONDS=15`. | `message_buffer._flush_after_delay` |

### კონცეპტუალური დასკვნა:

**Brain ≠ LLM.** Brain = Backend Python (state machine, regex parsers, validators, scheduling, integrations).
**LLM = სპეციალიზებული მუშა** რომელიც:
- აანალიზებს მესიჯის intent-ს (`detect_start_intent`, `analyze_parent_turn`, `detect_comment_intent`),
- წერს ბუნებრივ ქართულ ტექსტს (`generate_parent_value_response`, `compose_reply`, `generate_response`, `generate_summary`).

**Backend ვერასოდეს დათანხმდება**: LLM-მა state შეცვალოს, slot აირჩიოს, phone მიიღოს parser-ის გარეშე, lead შეინახოს, manager notify-ი ჩართოს.

---

## 6. DATA FLOW

### 6.1 Lead object

**Defined:** `app/models/lead.py` — `@dataclass`-ი.

ველები:
- სტრუქტურა: `sender_id`, `platform`, `segment`, `name`, `phone`, `child_age`, `challenge`, `deeper_concern`, `desired_change`, `event_interest`, `calendly_booked`, `conversation_summary`, `status`, `followup_sent`, `created_at`, `last_message_at`.

**Created at:** `parent_flow._ensure_lead(conversation)` ან `adult_flow._ensure_lead(conversation)` — ეცემა conversation.lead = None-ის შემთხვევაში (პირველი message ფლოუში).

**Populated at:**

| ველი | სად ივსება |
|---|---|
| `name` | START state, `_fetch_profile_into_lead` (Meta profile fetch) ან ASK_NAME-ის `_parse_name_phone` |
| `phone` | ASK_NAME, `_parse_name_phone` (regex), მხოლოდ თუ valid |
| `child_age` | ASK_AGE handler (`lead.child_age = message.strip()`), ან analyzer-ის `provided_fields.child_age` |
| `challenge` | ASK_CHALLENGE handler, ან CONCERN intent at START |
| `deeper_concern` | ASK_DEEPER handler |
| `desired_change` | ASK_DESIRE handler |
| `event_interest` | adult_flow SHOW_EVENTS — `lead.event_interest = event["name"]` |
| `calendly_booked` | `_book_selected_slot` → `lead.calendly_booked = True` (after successful Google Calendar insert) |
| `conversation_summary` | `_book_selected_slot` → `lead.conversation_summary = _generate_summary(conv)` (LLM) |
| `status` | "New" (default) → "Booked" (post-calendar) → "FollowUp" (after 48h cold reminder) |
| `last_message_at` | every `handle()` invocation — `lead.last_message_at = conversation.last_activity` |
| `followup_sent` | `followup_service.check_and_send_followups` (sheets update after sending) |

**Stored at (Sheets):** მხოლოდ ჯავშნის შემდეგ.
- `_book_selected_slot` → `sheets_service.create_lead(lead)` → `save_lead` → `append_row` (`Leads` tab, 17 columns).
- ADULT: `_finalize_booking` → `sheets_service.create_lead(lead)`.

**Used at:** Calendar event description (`_build_event_description`), manager notification (`MANAGER_DETAILS_PARENT`/`ADULT`), summary generation prompt.

**Not stored:** lead არ ინახება Sheets-ში discovery turn-ების დროს — მხოლოდ booking event-ის შემდეგ. **48h cold-lead followup ვერ აღმოაჩენს** lead-ს რომელიც discovery-ში გაიჭედა და restart-მდე იყო, რადგან Sheets-ში არ ჩაიწერა.

### 6.2 Conversation object

**Defined:** `app/models/conversation.py` — `@dataclass`-ი.

ველები: `sender_id`, `platform`, `segment`, `state` (default "START"), `history` (list of `{role, content}`), `lead` (Lead | None), `created_at`, `last_activity`.

**Created at:** `conversation_service._get_or_create_conversation(sender_id, platform)`.

**Stored at:**
- **In-memory only** — `conversation_service.conversations: dict[sender_id, Conversation]` (module-level global).
- **არც Redis, არც DB, არც persistence.**

**Cleared at:**
- **არასოდეს** (აპლიკაცია გადატვირთვამდე). Process restart → ცარიელია, ყველა in-flight საუბარი იკარგება (state, history, lead).
- `tests/test_parent_flow_analyzer_integration.py:reset_module_state` fixture-ი იწმინდება ტესტებში — production code-ში არც ერთი წერტილი არ აქვს cleanup-ი.
- `comment_service.send_dm_from_comment` — სტეიტი START-ზე იცვლება, history-ში assistant message-ი ემატება, მაგრამ conversation-ი არ წაიშლება.

**Multiple processes:** workers > 1 → ცალკე in-memory dict თითო process-ში → conversation-ი შეიძლება სხვადასხვა process-ში გადანაწილდეს → state ცარიელია. **Production-ში 1 process-ით უნდა იყოს, ან Redis-ით ცვლა.**

### 6.3 module-level globals (in-memory only)

`parent_flow.py`-ში:
- `available_slots: dict[str, list[dict]]`
- `ask_name_retries: dict[str, bool]`
- `invalid_phone_retries: dict[str, bool]`
- `slots_shown_for_state: dict[str, bool]`

`parent_turn_router.py`-ში:
- `manager_offer_shown: dict[str, bool]`

`adult_flow.py`-ში:
- `selected_events: dict[str, dict]`

`comment_service.py`-ში:
- `post_content_cache: dict[str, tuple[str, datetime]]` (1h TTL)

`message_buffer.py`-ში:
- `_pending_messages`, `_pending_tasks`, `_buffer_started_at`, `_locks`.

ყველაფერი **in-memory only**, process restart → ცარიელია.

---

## 7. EXTERNAL INTEGRATIONS

### 7.1 Google Sheets

**Files:** `app/services/sheets_service.py`.
**Client:** `gspread.service_account_from_dict(_load_credentials_info(...))`.
**Credentials:** `settings.GOOGLE_SHEETS_CREDENTIALS_JSON` — JSON-string ან path (`credentials.json`).
**Spreadsheet:** `settings.GOOGLE_SHEETS_SPREADSHEET_ID` (env), tabs: `Leads` (17 cols), `Comments` (11 cols).

**Operations implemented:**
- `save_lead(lead)` / `create_lead` / `append_lead` — შენახვა (`append_row`).
- `update_lead(sender_id, updates)` — column-level cell update (`update_cell`).
- `get_cold_leads()` — 48h+ inactivity, status ∈ {New, Qualified}, not followup_sent.
- `get_lead(sender_id)` — read by sender_id.
- `save_comment(...)`, `update_comment(...)`, `get_pending_comment_followups()`.
- Auto-header repair: თუ row 1 ჰედერი არ ემთხვევა — გადააწერს. **Risk:** human ჰედერების მოდიფიკაცია → silently overwritten.

**Status:** **Works** (lazy connection per call — credentials მოწმდება ყოველი save-ის დროს). 104+ pytest pass-ად მუშავდება (mocked). Live verification (real Sheets append) **არ მოწმდება ტესტებში** — `gspread` import-ი iznorms-ი ხდება (აქამდე იყო broken, ახლა fixed pip-ით).

**Potential issue:** ყოველი ჯავშნისას `_worksheet()` ხელახლა აშენებს client-ს — Google ბრუნდება ` "Resource exhausted: Rate Limit Exceeded"` თუ load მაღალია. Single-process-ი 100 lead/h-ისთვის OK.

### 7.2 Google Calendar

**Files:** `app/services/calendar_service.py`.
**Client:** `googleapiclient.discovery.build("calendar", "v3", credentials=…)` — service account.
**Calendar:** `settings.GOOGLE_CALENDAR_ID`.

**Operations:**
- `get_available_slots()` — top 5 slots scanning 30 days, weekdays only, work hours (10:00–19:00, თუ `business_hours.yaml`-დან).
- `get_free_slots(target_date, duration_minutes)` — single-day, business hours (10:00–18:00), uses FreeBusy API.
- `check_slot_available(slot_datetime)` — pre-check before booking. 2h buffer, weekday/business-hours check, FreeBusy.
- `book_slot(datetime_iso, lead)` — calendar event create. Description ჩაშენებული lead-ის ფონის ფაქტებით (phone, child_age, challenge).

**Status:** **Works** (assumed — `googleapiclient` import-ი არ ჩავარდა test-ში). End-to-end live booking **არ ვერიფიცირებულა.**

**Risk:** `_calendar_service()` ყოველი call-ის დროს ხელახლა აშენებს client-ს. Slot scanning 30 დღეზე — 30 Free/Busy API calls. ეფექტური load high traffic-ზე — გადახედვა საჭიროა.

**Important:** event title-ში lead.name + child_age-ი ჩაშენებულია → თუ lead.name = "OTHER" (debug), Calendar event-ი ცუდად ფორმდება. ვერიფიკაცია არ ხდება.

### 7.3 Meta Graph API

**Files:** `app/services/messenger_service.py` + `app/routes/webhook.py` (verify+receive) + `app/services/comment_service.py` (comment replies).

**Endpoints:**
- `GET /webhook` — `hub.verify_token` challenge response.
- `POST /webhook` — incoming DM + comment events.
- `POST {graph}/me/messages` — DM send (Instagram/Messenger).
- `POST {graph}/{whatsapp_phone_id}/messages` — WhatsApp send (different shape).
- `GET {graph}/{sender_id}?fields=name,username,profile_pic` — Instagram profile fetch.
- `GET {graph}/{sender_id}?fields=first_name,last_name,profile_pic` — Messenger profile fetch.
- `POST {graph}/{comment_id}/replies` — comment reply (public).
- `GET {graph}/{post_id}?fields=caption|message` — post content for hashtag/segment detection.

**API Versions:**
- `settings.META_GRAPH_API_VERSION = "v19.0"` (`app/config.py:181`, env-overridable).
- `comment_service._graph_base_url` reads settings ✅.
- `messenger_service._graph_base_url` reads settings ✅.
- **BUG:** `notification_service.py:28` — `GRAPH_API_BASE_URL = "https://graph.facebook.com/v18.0"` hardcoded. ერთი stale reference დარჩა v18-ზე (HANDOFF.md §8 item 4-ში დაფიქსირებული). Manager-WhatsApp notification-ი ამ stale URL-ით იგზავნება. Production-ში — შესაძლოა მუშაობდეს, შესაძლოა Meta-მ v18 უკვე გათიშოს.

**Status:** **Send + receive — works** (3-retry × 2s sleep). **Comment handling — works.** Production-ში untested manager-WhatsApp path-ი (v18 drift).

### 7.4 Email / SMTP

**Files:** `app/services/notification_service.py`.
**Code:** `smtplib.SMTP(host, port).starttls() + login + send_message`.
**Configuration:** `SMTP_HOST`, `SMTP_PORT=587`, `SMTP_USER`, `SMTP_PASSWORD`, `MANAGER_EMAIL` (env).
**Status:** **Implemented**, **not stub**. Live SMTP delivery **untested in tests**. დასაჭერია live smoke test (manager inbox-ში მისვლა) — HANDOFF.md item 9.

### 7.5 WhatsApp (Meta Business)

**Files:** `messenger_service.send_message` (path="whatsapp") + `notification_service._send_manager_whatsapp`.
**Endpoint:** `POST {GRAPH_API_BASE_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages`.
**Configuration:** `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `MANAGER_WHATSAPP_NUMBER`.
**Status:** **Implemented**, **not stub**. იყენებს v18 URL manager notification-ში (იხ. 7.3 ბაგი). Live delivery untested.

### 7.6 Twilio SMS (manager fallback)

**Files:** `notification_service._send_sms` (`twilio.rest.Client`).
**Configuration:** `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `MANAGER_PHONE_NUMBER`.
**Status:** **Optional** (configured თუ ყველა env var დაყენებულია). Live SMS untested.

### 7.7 Follow-up scheduler

**Files:** `app/services/followup_service.py`, scheduled via `apscheduler.schedulers.background.BackgroundScheduler` in `app/main.py`.
**Trigger:** every 1 hour.
**Logic:** `sheets_service.get_cold_leads()` (48h inactivity, status="New") → `messenger_service.send_message` (`PARENT_FOLLOWUP` ან `ADULT_FOLLOWUP`) → `sheets_service.update_lead(status="FollowUp", follow_up_sent=True)`.

**Status:** **Implemented**, untested end-to-end in production (run-time scheduling unit tests არ აქვს).

**Risk:** lead Sheets-ში მხოლოდ ჯავშნის შემდეგ ინახება → discovery-ში გაჭედილი მომხმარებლები **არ ემართება follow-up-ი**. ეს არ არის bug — სავარაუდოდ owner intent (followup მხოლოდ booked-ისთვის), მაგრამ ღირს დადასტურება.

### 7.8 Comment follow-up scheduler

**Files:** `comment_service.check_comment_followups`, scheduled hourly.
**Trigger:** `_run_comment_followups` ← `asyncio.run(check_comment_followups())` every 1h.
**Logic:** comments with status="CommentOnly" + 24h+ age → POST reply → update status="CommentFollowUp".

**Status:** **Implemented**, untested in production.

---

## 8. KNOWN BUGS

### 8.1 Meta API v18/v19 drift (HANDOFF §8 item 4)

[notification_service.py:28](app/services/notification_service.py#L28):
```python
GRAPH_API_BASE_URL = "https://graph.facebook.com/v18.0"
```

Hardcoded v18. ყველა სხვა adapter (`messenger_service`, `comment_service`, `webhook`) v19 settings-ით ფუნქციონირებს. Manager-WhatsApp notification-ი ერთადერთი place-ი, რომელიც v18-ით ლაპარაკობს. **Fix:** წაკითხვა settings-დან.

### 8.2 `.env.example` stale `CAMP_PRICE=2200`

HANDOFF §8 item 5. Knowledge YAML-ში 2150 ლარია (camp_2026.yaml). `.env.example` ჯერ კიდევ 2200-ს აჩვენებს. Runtime-ი YAML-დან კითხულობს, ამიტომ ეფექტური ღირებულება სწორია — მაგრამ `.env.example` shoulder-სტარტერებს შეცდომაში შეიყვანს.

### 8.3 In-memory conversation state (HANDOFF §8 item 2)

`conversation_service.conversations` — module-level dict, process-local, **no persistence.** Restart → ყველაფერი ცარიელია (state, history, lead, slot promo flag, manager-offer flag, debounce buffers). Production reliability-ისთვის Redis ან DB საჭიროა.

### 8.4 Lead არ ინახება Sheets-ში discovery-ის დროს

`sheets_service.create_lead` მხოლოდ ჯავშნისას ხდება. თუ მომხმარებელი ASK_DEEPER-ში გაიჭედა და process restart-ი მოხდა — lead-ი დაიკარგა Sheets-ში. **Followup scheduler** ვერ აღმოაჩენს.

შესაძლოა owner intent ("followup only for booked leads") — დაუდასტურებელია.

### 8.5 Windows cp1252 emoji print (HANDOFF §8 item 10)

`app/main.py:20-22, 37-38` — `print("✅ ... started")` cp1252 default Windows console-ზე → UnicodeEncodeError. App-ი ჯერ კიდევ ბრუნდება startup complete, მაგრამ console-ში traceback-ი ჩანს. `PYTHONIOENCODING=utf-8` ან `logger.info` ცვლის გადადგას — სხვა საქმე.

### 8.6 Composer/analyzer cost when both on

რეალურ ტრაფიკზე გაუმოწმებელია (HANDOFF §8 item 6). Both flags on = 2 OpenAI calls/turn = ~1-3s latency.

### 8.7 `_send_manager_whatsapp` and `messenger_service.send_message(platform="whatsapp")` share base URL with drift

Manager-WhatsApp use v18 (notification_service hardcoded); user-WhatsApp send_message uses v19 (settings-based). იგივე API-ის ცალკეული შესვლა.

### 8.8 No CSRF / webhook signature verification

`receive_webhook` accepts any POST without verifying `X-Hub-Signature-256` header. Production-ში — Meta-ს ჯანმრთელად დაუცავი ენდპოინტი. Local dev OK, production attack surface.

### 8.9 `_send_sms` import inside function (suboptimal)

`notification_service._send_sms`: `from twilio.rest import Client` ფუნქციის შიგნით. Lazy import OK, მაგრამ თუ Twilio არ არის installed-ი, ფუნქცია crash-ით ჩავარდება ერთხელ. Caller-მა მოწმდება `_twilio_configured()` — env-based, არა import-based. ნაკლები concern.

### 8.10 Calendar lazy client per call

`_calendar_service()` ყოველი API call-ის დროს ხელახლა აშენებს client-ს და credentials-ს. Slot scanning 30 დღეზე → 30+ rebuilds. Performance + rate-limit risk.

### 8.11 Sheets lazy client per call

იგივე, `_worksheet()` და `_comments_worksheet()` ხელახლა აშენებენ gspread client-ს.

### 8.12 `parent_flow._handle_ask_name` retry logic — შესაძლო bug

Lines 686-698: phone invalid retry-ის შემდეგ, "blank phone accepted" path-ი — სტეიტი transition-ი PRESENT_VALUE-ზე ხდება მაგრამ name-ი blank-ი მაინც შეიძლება იყოს. Manager notification-ი → empty name. **Risk:** half-validated lead საქმეში.

### 8.13 Adult flow `_booking_question` — fragile

`adult_flow.py:274` — `ADULT_EVENT_DETAILS.format(event_name="", ...).splitlines()[-1]` — template-ის ბოლო ხაზის ამოღება booking question-ად. თუ template-ი დარედაქტირდება — silently broken.

### 8.14 ADULT KNOWLEDGE_FACT-ები ჯერ კიდევ `data/prompts.py`-ში (HANDOFF §8 item 8)

`ADULT_DEFAULT_ATMOSPHERE`, `ADULT_DEFAULT_EVENT_NAME` etc. ჯერ კიდევ Python constants-ია, არ migrated to `adult_defaults.yaml` (YAML-ში არსებობს, მაგრამ adult_flow-ი მაინც Python-დან კითხულობს).

### 8.15 Composer/analyzer flag-off byte-identity claim

HANDOFF §2 ამბობს "flag off → byte-identical to Phase 3.6B." მცირე exception: `parent_flow.handle()` ახლა შეიცავს `_fetch_profile_into_lead` call-ს როცა state=START. Behavior **functionally identical** (idempotent if name already set), მაგრამ profile fetch-ი ერთხელ მაინც ხდება analyzer hook-ის წინ, არა START handler-ის შიგნით. Side-effect: თუ Meta profile API ცარიელია, საუბრის log-ი ერთი extra warning-ით (`Profile fetch failed`) დაიწერება. ეფექტური response არ იცვლება.

### 8.16 Test environment is system Python (no venv)

ეს არ არის code bug, არამედ environment fragility. `gspread` package was just reinstalled in previous task. Python 3.10.11 + system-wide site-packages → easy to lose. **Risk:** dependency drift.

### 8.17 Dead `data/prompts.py` constants reference each other

- `PARENT_CHALLENGE_OPTIONS: list[str] = []` — ცარიელი, არსად გამოყენებული.
- `OLD_SYSTEM_PROMPT` comment block in openai_service.py — rollback note.

ეს არ არის ბაგი, მაგრამ კოდის zwiebel-ი.

### 8.18 Comments segment detection cache key collision risk

`post_content_cache` key = `post_id` only. Two platforms (IG vs FB) could in theory share a post_id (unlikely but undefined behavior). Low risk.

### 8.19 `webhook._extract_meta_messages` ignores `messaging_postbacks` and `attachments`

მხოლოდ `event["message"]["text"]` ამოიღება. Image/Voice/Sticker/Postback → skip silently. პრობლემა მაშინ თუ მომხმარებელი ფოტოს გადააგზავნის → ბოტი არ უპასუხებს. Owner intent-ი დასადასტურებელია.

---

## 9. DEAD CODE

### 9.1 `data/prompts.py:106`

```python
PARENT_CHALLENGE_OPTIONS: list[str] = []
```

ცარიელი list — backwards-compat-ისთვის დარჩა, არსად გამოყენებული.

### 9.2 `app/services/conversation_service.py`

- `class ContentRepository` (lines 130-155) — `content_repository = ContentRepository()` მოდულ-ლეველზე იქმნება, მაგრამ **არასოდეს გამოყენებული** `process_message`-ში.
- `class FlowContext` (lines 159-183) — `_flow_context(...)` helper-ი არსად არ ეძახდება.
- `class SafeFormatter` — defined, არასოდეს called.
- `_extract_template_section` — used only by `ContentRepository._section_text`, რომელიც dead path-ი.

### 9.3 `app/services/openai_service.py`

- `class OpenAIService` (line 227) — defined for some legacy injection pattern, never instantiated by production code.
- `detect_segment` function — defined (lines 60-74) ე.ი. PARENT/ADULT classification via LLM, **მაგრამ** `conversation_service._classify_segment` deterministic keyword classifier-ით ჩანაცვლდა. `detect_segment`-ი `OpenAIService.generate_reply`-ით კი ერთხელ called-ია (line 238), მაგრამ `generate_reply` თვითონ არ called-ია არსად.
- `# OLD_SYSTEM_PROMPT` comment block (lines 244-258) — rollback note, dead.

### 9.4 `app/flows/parent_flow.py`

- `_generate_parent_response(conversation, message)` (lines 340-361) — defined but **never called** by handle(). Phase 3.5 audit-ში fixed-ი იყო (HANDOFF §8 item 7).
- `_end_with_consultation_offer(response, sender_id)` (lines 364-375) — defined but **never called**.
- `_format_available_slots(sender_id)` (lines 805-813) — defined, never called.
- `_wants_consultation(message)` (lines 760-763) — defined, never called by parent_flow (ADULT uses `_wants_booking` separately).

### 9.5 `app/services/messenger_service.py`

- `class MessengerService` (lines 137-174) — legacy injection pattern, never instantiated.

### 9.6 `app/services/sheets_service.py`

- `class SheetsService` — same.

### 9.7 `app/services/calendar_service.py`

- `class CalendarService.create_consultation` — uses `lead.preferred_time` attribute which isn't on Lead dataclass. Never called.
- `create_event(...)` helper-ი — used in tests but not in production `handle()` path.

### 9.8 `app/services/notification_service.py`

- `class NotificationService` — legacy, never instantiated.

### 9.9 `app/services/followup_service.py`

- `class FollowupService` — legacy, never instantiated. `build_followup` method ContentRepository-ის ცოცხალ pattern-ს იყენებს რომელიც dead.

### 9.10 `app/agent/templates/...`

YAML templates `parent/fallback_response.yaml`, `parent/context.yaml` — გადადიოდა `_generate_parent_response`-ისთვის, რომელიც dead. Templates ცოცხალია (data/prompts.py გადააფერადებს), მაგრამ caller dead.

### 9.11 `ADULT_DEFAULT_*` constants (data/prompts.py:174-181)

ცოცხალია (`adult_flow._empty_event` და `_current_event` იყენებენ), მაგრამ duplicated against `app/agent/knowledge/adult_defaults.yaml` (HANDOFF §8 item 8). YAML migrated, Python-ი არ ცვლის — yet.

### 9.12 dead branch in `_handle_ask_name`

ASK_NAME retry path-ი — `ask_name_retries[sender_id]` ცოცხალია მაგრამ test-ში არ მუშავდება. ფაქტობრივად retry შემთხვევები (`PARENT_ASK_NAME_RETRY`) live-ში არ ვერიფიცირდება.

---

## 10. HONEST ASSESSMENT

### ა) ახლა LLM არის brain თუ state machine?

**State machine. Backend არის brain.**

LLM-ის როლი — სპეციალისტი მუშა რომელიც:
1. **აანალიზებს** მესიჯის intent-ს (`detect_start_intent` ალბათ, `analyze_parent_turn` + opt-in flag-ით, `detect_comment_intent`).
2. **წერს** ბუნებრივ ქართულ ტექსტს (`generate_parent_value_response`, opt-in `compose_reply`, `generate_response`, `generate_summary`).

**Backend** state machine (`parent_flow.handle`) გადაწყვეტს:
- რომელ state-ზე გადადეს,
- რომელი template/builder იუნდა გამოყენდეს,
- booking-ი გასაკეთებელია თუ არა (Google Calendar API),
- lead Sheets-ში შენახული თუ არა,
- manager-ი notify-ი ჩართოს თუ არა.

LLM-ი **ვერ ცვლის state-ს, ვერ ჯავშნის, ვერ წერს lead-ში** (გარდა analyzer-ის `provided_fields` — და ეგ აიგზავნება მკაცრი whitelist-ით სუბენ `_apply_safe_fields`-ში; ფსიქოლოგიური ველები მხოლოდ `primary_intent == "answer_flow_question"`-ის შემთხვევაში).

**კარგი archi**: backend decides, LLM writes/analyzes. ეს არის Phase 3.8/3.9 explicit goal-ი ("Backend stays the brain. LLM analyzes and writes. Backend validates and executes.").

### ბ) თუ ვინმე script-გარეთ ესაუბრება — რა ხდება?

**Default (flags off)**:
- "მენეჯერი მინდა" at ASK_CHALLENGE → message ინახება `lead.challenge`-ში (rule violation — operational request stored as psychological). Bot აგრძელებს `PARENT_ASK_DEEPER` ("შინაგანი მიზეზი დგას უკან..."). Robotic, ignores intent. **Live finding-ი HANDOFF §2-ში.**
- "ფასი რა არის?" mid-flow → keyword price-escape მუშავდება, `PARENT_PRICE_IN_FLOW` template რენდერდება, state უცვლელია. **OK** (ერთადერთი mid-flow detour-ი default-ში).
- "სად ტარდება ბანაკი?" → არ აჩერებს. Message ინახება როგორც current state's field. Ignored intent.
- "თარიღები?" → იგივე, ignored.
- "არაფერი არ აწუხებს" at ASK_CHALLENGE → ინახება `lead.challenge="არაფერი არ აწუხებს"`, აგრძელებს `ASK_DEEPER`. Awkward.

**Analyzer on (`USE_LLM_TURN_ANALYZER=true`)**:
- Manager request → phone reply ან soft offer (escalation 2-step).
- "ფასი რა არის?" → builder camp_2026.yaml-დან, no state advance.
- "თარიღები?" → 3 streams (23-29 ივნისი / 5-11 ივლისი / 14-20 ივლისი).
- "სად?" → "ამბასადორი კაჭრეთი".
- "რეგისტრაცია?" → URL.
- "არაფერი არ აწუხებს" → clarifying question.

**Composer on (separately)**: ცვლის სიტყვების სტილს PARENT discovery-ში (4 state). იგივე intent ignoring problem-ი — composer-ი მხოლოდ ფრაზინგი, არა intent.

**Conclusion**: default-ში flow **შესაძლოა "გატყდეს" UX-ად** (psychological discovery despite explicit user intent). State machine **ფუნქციურად არ ცდილდება** (booking-ი მუშავდება, lead საქმდება). Phase 3.9 analyzer-ი specifically ამისთვის შეიქმნა — მაგრამ defaults-ით OFF, ე.ი. owner-მა ცნობიერად უნდა ჩართოს live-ში.

### გ) რა არის ყველაზე დიდი არქიტექტურული პრობლემა?

**In-memory conversation state.**

ერთი restart → ყველაფერი იკარგება:
- ცარიელია `conversations` dict → ყველა in-flight საუბარი იწყება `START`-ით.
- ცარიელია `available_slots` → მომხმარებელი ვერ აირჩევს უკვე ნანახ სლოტს.
- ცარიელია `manager_offer_shown` → soft offer ხელახლა იჩვენება.
- ცარიელია `message_buffer` → ფრაგმენტი იკარგება.
- ცარიელია `post_content_cache` → ხელახლა Meta API call-ი (rate limit).
- ცარიელია `slots_shown_for_state` → slot promo ხელახლა იჩვენება.

**Production-ში** — Railway / docker auto-restart / OOM kill → ეფექტური UX disaster.
**Multi-worker** (uvicorn workers > 1) → თითო worker-ი ცალკე dict → conversation cross-worker გადანაცვლება → reset state.
**Scaling** — vertical only (1 process). Horizontal scaling impossible.

ეს არის ერთადერთი **fundamental** არქიტექტურული პრობლემა — დანარჩენი (LLM-ი brain-ი თუ არა, intent recognition, integration completeness) — გადაიჭრება feature flag-ით ან code cleanup-ით. **Persistence-ი arch-ის გადაწერას მოითხოვს**: `ConversationRepository` interface, Redis/SQLite backend, eviction strategy.

დაშვილებული პრობლემები:
1. Lead არ ინახება discovery-ის დროს Sheets-ში → restart-ი დაიკარგება.
2. Followup scheduler მხოლოდ booked-ისთვის → discovery-ში გაჭედილი მომხმარებლები არ მიიღებენ რეიმინდერს.
3. Multiple workers-ით cross-worker conversation drift.

რანგი — სიდიდის მიხედვით:
1. **In-memory state** (production blocker for scale)
2. **Lead persistence** (no recovery for in-flight discovery)
3. **Webhook signature unverified** (security)
4. **Hardcoded v18 in notification_service** (silent breakage if Meta deprecates v18)
5. **In-process scheduler** (single point of failure for follow-ups)

---

**End of audit. No code modified.**
