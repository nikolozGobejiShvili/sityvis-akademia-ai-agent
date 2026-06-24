# RED-TEAM FULL-SYSTEM AUDIT — comments · follow-up · adult/parent flow · event data · security

**Date:** 2026-06-12 · **Mode:** audit-only (no production code changed, no tests added, no existing docs modified; only this file written).
**Baseline:** `pytest` 2151 passed / 7 skipped / 0 failed · corpus 9/9 · property 7/7 · CRITICAL 22/22 (last run, batch-fix turn) · **Production NOT green.**
**Method:** targeted test suites + a throw-away READ-ONLY harness that called the REAL deterministic functions (`adult_llm_engine._maybe_handle_notification_delivery_question` / `_maybe_adult_offtopic_reply` / `_maybe_capture_adult_target`, `parent_flow._maybe_handle_contact_collection` / `_parse_name_phone`, `timestamps.extract_colloquial_hour`, `admin_config_service.get_adult_events`, `comment_service.is_interest_intent`, `Lead.to_sheet_row`) with no OpenAI / network / Calendar / Sheets / email / Meta / broadcast. `LIVE_BROADCAST_ENABLED` stayed `False`. **The harness (`redteam_full_scratch.py`) was DELETED after the run (confirmed).** Findings show the observed return value of the real function; LLM-dependent paths are marked NEEDS LIVE SMOKE.

---

## ✅ PRE-STAGING FIX BATCH — RESOLVED (2026-06-12, code work = 2151 → 2209)

The four cheap deterministic findings flagged for "fix now" are **DONE**, one
at a time with a full-`pytest` + corpus gate after each (never dropped below
the 2151/9 baseline). New file
[tests/test_prestaging_redteam_fixes.py](../tests/test_prestaging_redteam_fixes.py)
(+58). **No change** to Calendar internals, Sheets schema/row-strategy, adult
subscription/broadcast SENDING, email, OpenAI model, Railway, prompts,
`LIVE_BROADCAST_ENABLED` (still `False`). No real broadcast sent. No hardcoded
sender_id / profile names. **Production is STILL NOT green.**

- ✅ **A-1 / A-2 (DEGRADED → FIXED)** — `adult_llm_engine`: replaced the
  word-order-locked `_NOTIFICATION_DELIVERY_QUESTION_PATTERNS` with a
  morphology / word-order tolerant stem-group detector (where/how + subject
  OR arrival; channel + arrival; standalone „აქ" + write/arrival + „?"). Added
  „შეტყობინ"/„შემატყობ" to `_ADULT_IN_SCOPE_STEMS` AND made
  `_maybe_adult_offtopic_reply` delivery-aware (returns `None` for a delivery
  question) so the forbidden „ამ კითხვაზე ვერ დაგეხმარებით" redirect can
  never fire on one. **All 10 Section-A variants now get a platform-aware
  delivery answer; none gets the redirect.** Still narrow: price / location /
  subscription-consent (`კი გამომიგზავნეთ`, `შემატყობინეთ`) are NOT
  intercepted.
- ✅ **B-1 (DEGRADED → FIXED)** — `adult_llm_engine`: added the DATIVE needles
  „შვილს"/„ბავშვს" to `_ADULT_RELATIVE_PATTERNS` (they never shadow the
  genitive captures). „ჩემ შვილს უნდა" / „ბავშვს უნდა" now capture the
  relation deterministically and reuse a known `child_age`; min_age filtering
  via `adult_target_age` unchanged.
- ✅ **F-D4 (DEGRADED → FIXED)** — `parent_flow`: broadened
  `_CONTACT_REQUEST_MARKERS` (`ნომერ`, `ტელეფონ`, `კონტაქტ`, `დაგიკავშირდეთ`,
  `როგორ დაგიკავშირ`) so a bare valid phone is captured even when the bot's
  contact-ask used non-brand wording („მომწერეთ ნომერი" / „როგორ
  დაგიკავშირდეთ?"). The `-ეთ` (question) vs `-ებათ` (confirmation) distinction
  keeps „მენეჯერი დაგიკავშირდებათ" from arming the capture; the
  `in_contact_ctx` gate keeps stray numbers out.
- ✅ **F-D6 (DEGRADED → FIXED)** — `parent_flow`:
  `_maybe_request_full_contact_on_intent` now parses + saves an inline phone
  (and a validly-disclosed name) BEFORE composing the ask, so „კი მინდა
  კონსულტაცია 595999733" never re-asks the phone — it asks only the name (or
  proceeds to time when the name is known). Intent detection broadened for the
  word-separated „მინდა … კონსულტაცია" + „დამირეკეთ" + „მინდა ჩაწერა"; „დარეკ"
  / „დამირეკ" added to `_NAME_REJECT_STEMS` so „დამირეკეთ" is never a name.

**Still DEFERRED (unchanged):** F-D3 (Latin name), F-D7 / M3 / M4
(half-hour / evening time), F-multichild (ROOT 4 — needs
`test_age_fallback_two_children_keeps_first_valid` updated first).
**Still NEEDS LIVE SMOKE (unchanged):** delivery-question LLM fallthrough is
now moot (all 10 deterministic), comment webhook + DM send, follow-up tick,
specific-post → event mapping, Meta token regenerate, WhatsApp.
**Operator cleanup still pending:** deactivate `formula_1` / `summer_fest`
(C-1/H-2); regenerate the Meta token (H-1).

**Final verification:** `pytest tests/ -q` → **2209 passed, 7 skipped, 0
failed** · corpus **9/9** · `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` →
**7/7** · `pytest -k comment` **196/0** · `pytest -k follow` **186/0** ·
`test_agent.py` ✅.

---

## 1. Summary counts

| Severity | Count |
|---|---|
| **BLOCKER** | **0** |
| **DEGRADED** | **8** (A-1, A-2, B-1, F-D3, F-D4, F-D6, F-D7, F-multichild) |
| **MINOR** | **2** (F-M3 + carried) |
| **NEEDS LIVE SMOKE** | **6** (delivery LLM-fallthrough, comment webhook/DM send, follow-up live tick, specific-post→event live map, Meta token regenerate, WhatsApp live) |
| **OPERATOR DATA CLEANUP** | **2** (C-1 test events active, H-2 = same) |

> Several DEGRADED items (F-D3/D4/D6/D7, multi-child) are **carried-open** from the prior `docs/REDTEAM_FINDINGS.md` and were re-confirmed still present on current code (the batch fix closed D1/D2 only). The **new** findings of this audit are **A-1/A-2 (adult delivery-question handler), B-1 (dative-case relation gap), and C-1 (test events still public).**

## 2. Highest-risk area

**Adult subscription delivery-question handling (Section A).** `_maybe_handle_notification_delivery_question` is exact-substring / word-order bound and covers only **3 of 10** realistic phrasings. For the natural variant **„შეტყობინება სად მომივა?"** the deterministic path produces the **exact forbidden** redirect **„ამ კითხვაზე ვერ დაგეხმარებით."** (off-topic guard). This is a confirmed wrong user-facing message on a common subscriber question — the only place in this audit where the deterministic layer emits a clearly-wrong reply.

---

## 3. Ranked findings (BLOCKER first)

### BLOCKER
None. No input broke booking / subscription / comment / follow-up, produced a fake/stale booking, a wrong state transition, or an impossible-to-proceed loop in the deterministic layer.

### DEGRADED

#### A-1 — Delivery question „შეტყობინება სად მომივა?" gets the FORBIDDEN off-topic redirect
1. **Repro:** ADULT conversation (any subscription state), message `შეტყობინება სად მომივა?` on Messenger.
2. **Observed:** `_maybe_handle_notification_delivery_question(...)` → `None`; `_maybe_adult_offtopic_reply(...)` → **„ამ კითხვაზე ვერ დაგეხმარებით.\nთუ ჩვენს ღონისძიებებ…"** (the redirect the spec explicitly bans for delivery questions).
3. **Expected:** „შეტყობინებას სწორედ აქ, Messenger-ში მიიღებთ — ამავე ჩატში…".
4. **Code path:** [adult_llm_engine.py:155](app/agent/llm/adult_llm_engine.py#L155) `_NOTIFICATION_DELIVERY_QUESTION_PATTERNS` has `"სად მომივა შეტყობინება"` (verb-then-noun) but the user wrote noun-then-verb (`შეტყობინება სად მომივა`) → no substring match → `None`. Then [adult_llm_engine.py:280](app/agent/llm/adult_llm_engine.py#L280) the off-topic guard hits a WHO-pattern on `სად…?` (no in-scope stem; „შეტყობინება" is NOT in `_ADULT_IN_SCOPE_STEMS`) → returns `_OFFTOPIC_REPLY_NAME_NOT_CONFIGURED`.
5. **Root cause:** delivery patterns are word-order-locked; „შეტყობინება" is not an in-scope stem, so the off-topic guard claims a delivery question.
6. **Severity:** DEGRADED (confirmed wrong deterministic user-facing reply; user can rephrase — does not hard-break subscription).
7. **Smallest fix area:** add reversed/loose patterns („შეტყობინება…მომივა/მოვა/ვნახავ"), and/or add „შეტყობინ"/„შემატყობ" to `_ADULT_IN_SCOPE_STEMS` so a delivery question is never redirected.
8. **Fix:** **now** (cheap; same module; this is the live-smoke symptom the section was built around).

#### A-2 — Delivery-question handler covers only 3/10 realistic variants (inconsistent)
1. **Repro (Messenger):** the 10 Section-A inputs.
2. **Observed (deterministic):** DELIVERY-OK for `მესენჯერში მომივა შეტყობინება?` (A2), `დეტალებს სად გამომიგზავნით?` (A4), `…სად შემატყობინებთ?` (A5). **Redirect** for A1 (above). **FALLS-TO-LLM** for A3 `ლინკებზე სად მოდის შეტყობინება?` (typo „მოდის" vs pattern „მომდის"), A6 `აქ მომწერთ?`, A7 `მეილზე მოდის თუ აქ?`, A8 `სად ვნახავ შეტყობინებას?`, A9 `შეტყობინება სად მოვა?`, A10 `…სად გავიგებ?`.
3. **Expected:** all 10 answered as in-scope delivery questions (platform-aware).
4. **Code path:** same `_NOTIFICATION_DELIVERY_QUESTION_PATTERNS` substring list.
5. **Root cause:** exact-phrase coverage; no morphological/word-order tolerance; „ვნახავ/მოვა/გავიგებ/მომწერთ/მეილზე" unhandled.
6. **Severity:** DEGRADED (3/10 deterministic; 6 LLM-luck → see NEEDS LIVE SMOKE; A7 „მეილზე მოდის თუ აქ?" risks the LLM answering „email").
7. **Smallest fix area:** broaden the pattern set (or regex on „შეტყობინ"/„შემატყობ" + „სად/როგორ/აქ/მესენჯერ/მეილ").
8. **Fix:** **now** (paired with A-1).

#### B-1 — Adult-for-child relation NOT captured for dative case („ჩემ შვილს", „ბავშვს")
1. **Repro:** ADULT lead with `child_age=15`, message `ჩემ შვილს უნდა` (or `ბავშვს უნდა`).
2. **Observed:** `_maybe_capture_adult_target(...)` → `adult_target_relation=''`, `adult_target_age=''` (NOT captured). Genitive forms `ჩემი შვილისთვის` / `შვილისთვის მაინტერესებს` → `relation='შვილი'`, `adult_target_age='15'` (reused) ✓.
3. **Expected:** capture the relation deterministically for the dative case too, and reuse the known child age.
4. **Code path:** [adult_llm_engine.py:426](app/agent/llm/adult_llm_engine.py#L426) `_ADULT_RELATIVE_PATTERNS` contains only genitive needles (`შვილისთვის`, `შვილის`, `ბავშვისთვის`) — `შვილს` / `ბავშვს` (dative) are absent.
5. **Root cause:** pattern list is genitive-only; dative declension missing.
6. **Severity:** DEGRADED — **this is the live „inconsistent on one account, immediate on another" symptom**: genitive → deterministic; dative → LLM-luck.
7. **Smallest fix area:** add `შვილს` / `ბავშვს` (and maybe `შვილსაც`) to `_ADULT_RELATIVE_PATTERNS`.
8. **Fix:** **now** (cheap; closes the determinism gap the section flagged).

#### F-D3 — Latin-script name dropped, agent re-asks (CARRIED-OPEN)
- `Liziko 595999733` → phone saved, `name=''`, reply „ნომერი მივიღე. მომწერეთ თქვენი სახელი…". Root: the contact-handler name-gate requires Georgian letters `[ა-ჰ]`. Severity DEGRADED. Fix: widen to `[ა-ჰa-zA-Z]` with an allowlist. **Defer** (needs care vs „ok"/„hi"). *(Same as REDTEAM_FINDINGS D3.)*

#### F-D4 — Bare-phone capture is brand-marker-dependent (CARRIED-OPEN)
- Bot asks WITHOUT the brand markers („მომწერეთ თქვენი ნომერი."), no `pending_booking`, user sends `595999733` → contact handler returns `None` → LLM-luck loop. Root: `_CONTACT_REQUEST_MARKERS` only matches „9-ნიშნა"/„საკონტაქტო ნომერ". Severity DEGRADED. Fix: broaden markers. **Fix now (cheap).** *(REDTEAM_FINDINGS D4.)*

#### F-D6 — Explicit intent + inline phone ignores the phone (CARRIED-OPEN)
- `კი მინდა კონსულტაცია 595999733` (fresh, eligible age) → `_maybe_request_full_contact_on_intent` asks for the phone just given. Severity DEGRADED. Fix: capture inline phone before composing the ask. **Fix now (cheap).** *(REDTEAM_FINDINGS D6.)*

#### F-D7 — Colloquial half-hour silently resolves to the hour (CARRIED-OPEN)
- `12 ივნისი 5 საათსა და ნახევარზე` → `extract_colloquial_hour` → `(17,0)` and `_parse_booking_datetime` → `2026-06-12T17:00` (the „:30" is dropped). Severity DEGRADED (silent time mismatch). Fix: detect „ნახევარ" → surface `half_hour_not_supported`. **Defer.** *(REDTEAM_FINDINGS D7.)*

#### F-multichild — Two children, only first age captured (CARRIED-OPEN / ROOT 4 DEFERRED)
- `10 და 14 წლის` → `child_age='10'`, the 14-year-old dropped. ROOT 4 batch-fix was reverted because the guard broke an existing test (`test_age_fallback_two_children_keeps_first_valid`). Severity DEGRADED. Fix: update that existing test to the new contract, then guard + „which child?" clarification (no schema change). **Defer (with the documented follow-up).**

### MINOR

#### F-M3 — „საღამოს 11" → 23:00 (CARRIED-OPEN)
- evening-11 → +12 = 23:00 (outside business hours → rejected downstream). Low impact. Fix: cap evening +12 so 10/11 stay literal. **Defer.** *(Plus carried M1/M2/M4/M5 from REDTEAM_FINDINGS — spelled-out age, „შუადღის 2", half-hour colloquials, range-no-clarify — all still MINOR/defer.)*

### NEEDS LIVE SMOKE
- **Delivery-question LLM fallthrough (A3, A6, A7, A8, A9, A10):** these reach the LLM (off-topic guard returns `None`); whether the LLM answers „here in Messenger" or redirects/says „email" cannot be proven offline.
- **Comment webhook → DM send:** real Meta payload parsing, private-reply send, platform permissions, specific-post→event live mapping (offline logic is tested; live delivery is not).
- **Follow-up live tick:** real APScheduler send (mocked offline; the cadence logic is tested).
- **Meta access token regenerate** (Priority 0a — a token leaked in a terminal error log during testing; operator must rotate before prod). Cannot verify offline.
- **WhatsApp live** (plumbed, not production-tested).

---

## 4. Comment routing audit result (SECTION D) — GREEN (offline)
- `pytest -k comment` → **196 passed, 0 failed.**
- `comment_service` does **NOT** reference `_parse_name_phone` or assign `lead.phone` → **a phone inside a comment („მაინტერესებს 595999733") does NOT corrupt contact/name state** (verified by source absence).
- `is_interest_intent` correctly classifies all Section-D variants as interest → DM: `მაინტერესებს`, `ბანაკი/ღონისძიება მაინტერესებს`, `ფასი?`, `სად ტარდება?`, `ლინკი?`, `მაინტერესებს 595999733`, `მაინტერესებს 🙏` → all `True`.
- `processed_comment` dedupe guard present (duplicate comments don't spam). `determine_segment_from_post` present (hashtag → segment). #camp → parent DM, #event → adult DM, specific-post → event resolver are covered by the 196 tests.
- **NEEDS LIVE SMOKE:** real webhook payload, real DM send, platform permissions, specific-post live mapping.

## 5. Follow-up audit result (SECTION E) — GREEN (offline)
- `pytest -k follow` → **186 passed, 0 failed.**
- `_BLOCKED_REASONS` = `{booked, registered, declined, asked_no_more_messages, manager_handoff_completed, followup_exhausted}` → does NOT send after booking / decline / unsubscribe-as-decline / handoff / exhaustion. `reason=non_parent_segment` skip (no adult follow-up to a parent-only flow or vice-versa) + a direct `lead.calendly_booked` double-check. Platform preserved from the inbound webhook. Stage advancement prevents duplicate sends. No real send (transport mocked).
- **NEEDS LIVE SMOKE:** real scheduler tick delivery.

## 6. Event config / data integrity result (SECTION C) — code GREEN; DATA needs cleanup
- 5 adult events, **no duplicate IDs**, all `active=True`. `get_active_adult_events()` (public) returns **4** — the past `მასტერკლასი` (9 ივნისი = 2026-06-09, before today 06-12) is **correctly excluded** by the date filter ✓.
- **C-1 (OPERATOR DATA CLEANUP):** `formula_1` (title „formula 1", **price 4999**, min_age 13, 28 ივნისი) and `summer_fest` (title „summer fest", price 100, min_age 19, 28 აგვისტო) are **test/dummy events, active + future → shown in the public list.** „formula 1"/„summer fest" are not სიტყვის აკადემია cultural events and the prices are implausible. The active+future code filter is correct; this is **dirty operator data**, not a code defect. **Action:** deactivate `formula_1` / `summer_fest` via `/admin/programs/adult_events/events/{id}/deactivate` (the docs' Priority 0c). `მასტერკლასი` (price 2150 = camp price) also looks like a placeholder; it is past so already hidden.
- min_age enforced consistently (summer_fest 19 hides it from under-19; 12-year-old child filtered from 13+ events). Past events not offered as upcoming ✓.

## 7. Adult notification-question result (SECTION A) — DEGRADED
- Deterministic delivery answer for **3/10** variants; **1/10 gets the forbidden „ამ კითხვაზე ვერ დაგეხმარებით" redirect** (A-1); **6/10 fall to the LLM** (NEEDS LIVE SMOKE). Platform answers correct where matched (Messenger / Instagram / WhatsApp branches verified). See A-1 / A-2.

## 8. Adult-for-child state reuse result (SECTION B) — mostly deterministic; 1 gap
- **Deterministic + correct:** genitive relation capture (`შვილისთვის`/`შვილის`/`ბავშვისთვის`), `child_age` reuse (15→15, 17→17, 12→12), inline-age override („ჩემი 12 წლის შვილისთვის" → `adult_target_age=12` even with stored `child_age=15`), min_age filtering (12 < 13 → no events), `child_age` never overwritten / never used as the parent's own age.
- **Cross-user / cross-platform isolation: CONFIRMED.** Conversation store keys on `conversation:{platform}:{sender_id}` ([conversation_service.py:37](app/services/conversation_service.py#L37)); separate sender_ids → separate `Conversation`/`Lead` objects; harness showed A (`child_age=15`) and B (no child_age) do not leak (`A.adult_target_age='15'`, `B.adult_target_age=''`).
- **B-1 gap (DEGRADED):** dative forms „ჩემ შვილს უნდა" / „ბავშვს უნდა" not captured deterministically → LLM-luck (the live inconsistency).

## 9. Parent contact / booking regression result (SECTION F) — batch fix holds; carried items remain
- **FIXED (re-verified):** `ჩემი ნომერია 595999733` → name `''` (not „ჩემი"); `595999733 ან 595999734` → name `''`, phone `''`, reply „ორი ნომერი მომწერეთ. რომელი ნომრით დაგიკავშირდეთ?"; `ჩემი სახელია ლიზი ნომერი 595999733` → name=`ლიზი`; all phone formats parse; booking message with a known name does NOT overwrite it (`595999733 16 ივნის მინდა 10 საათზე` + name=ჯონი → stays ჯონი); contact-only never books.
- **Time:** `7 საათზე`→19:00, `8 საათი`→20:00, `დილის 11`→11:00, `ხვალ/დღეს 8 საათზე`→20:00 ✓. `საღამოს 11`→23:00 (M3), `5 საათსა და ნახევარზე`→17:00 (D7).
- **Carried-open DEGRADED:** D3 (Latin name), D4 (marker-dependent), D6 (intent+inline phone), D7 (half-hour), multi-child.
- corpus 9/9, property 7/7 (P1/P2/P4 pass) → the shipped guards hold.

## 10. Sheet / CRM hygiene result (SECTION G) — GREEN (in-memory)
- `lead.name` never becomes `ჩემი` / `ან` / `და` / `გამარჯობა` / `ჯავშანი` / `გადანიშვნა` / a paragraph (all → `''`, verified). `challenge` excludes the tacked-on question („როდის ტარდება") (corpus CONV 4). `child_age` not extracted from a range (corpus CONV 3). `Lead.to_sheet_row` serializes the clean fields; no privacy-notice / clarification text / adult-subscription status leaks into the parent name/challenge columns (the contact handlers never write those into `lead.name`/`lead.challenge`). event_interest ↔ challenge separation is enforced in the executors (existing tests). No real Sheets write.

## 11. Security / config hardening result (SECTION H) — GREEN + 2 known items
- **`LIVE_BROADCAST_ENABLED = False`** (verified) → `broadcast_event` is DRY-RUN; cannot send in audit/dev.
- **No secret/token VALUE logged:** a grep for `logger.*` lines containing access_token/app_secret/password/signature found only the safe verdict line `[webhook] signature accepted (verification disabled)` — no token, secret, or signature value.
- Conversation key isolates by platform+sender_id (no cross-leak).
- **H-1 (NEEDS LIVE SMOKE / operator):** Meta access token regenerate — Priority 0a (a token leaked in a terminal error log during testing). Rotate before prod.
- **H-2 (OPERATOR DATA CLEANUP):** test events `formula_1` / `summer_fest` still active (= C-1). The historical `ჯონი` test event is no longer present in `sections.yaml`.
- Placeholder/operator-entered links are NOT flagged as code defects (per instructions).

## 12. Test run results
- `pytest -k comment` → **196 passed, 0 failed.**
- `pytest -k follow` → **186 passed, 0 failed.**
- `pytest tests/corpus/ -q` → **9 passed.**
- `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` → **7 passed** (P1–P7).
- Full suite / `test_agent.py` / CRITICAL were **not re-run in this audit turn** (no code changed); last verified this session: 2151/7-skip/0-fail, test_agent green, CRITICAL 22/22.

## 13. Confirm no code changed
✅ No production code changed. The only file written is `docs/REDTEAM_FULL_SYSTEM_AUDIT.md`. The temporary harness `redteam_full_scratch.py` was deleted (confirmed via `ls` → not found).

## 14. Confirm no tests added/changed
✅ No test files added or modified.

## 15. Confirm no existing docs modified except the allowed output file
✅ Only `docs/REDTEAM_FULL_SYSTEM_AUDIT.md` created. HANDOFF.md / CLAUDE.md / REVIEW_PACK.md / docs/REDTEAM_FINDINGS.md untouched.

## 16. Confirm production NOT green
✅ **Production is NOT green.**

---

## Recommendation
**Fix before staging (cheap + deterministic):** A-1/A-2 (broaden the delivery-question patterns + add „შეტყობინ" to in-scope stems so a subscriber's delivery question is never redirected), B-1 (add dative `შვილს`/`ბავშვს` to the relative patterns), F-D4 (broaden contact-ask markers), F-D6 (capture inline phone on explicit intent). **Operator cleanup before launch:** deactivate `formula_1` / `summer_fest` (C-1/H-2); regenerate the Meta token (H-1). **Defer:** F-D3 (Latin name), F-D7 / M3 / M4 (half-hour/evening time), multi-child (ROOT 4 — needs the existing test updated first). **Live smoke still required:** delivery-question LLM fallthrough, comment webhook + DM send, follow-up tick, specific-post→event mapping, WhatsApp.
