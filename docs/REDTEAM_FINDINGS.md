# RED-TEAM FINDINGS — PARENT/ADULT agent (adversarial audit)

**Date:** 2026-06-12 · **Mode:** audit-only (no code changed, no tests added, no existing docs modified).
**Baseline:** `pytest` 2120 passed / 0 failed · CRITICAL 22/22 · **Production NOT green.**
**Method:** every input below was traced through the ACTUAL deterministic code path via a throw-away read-only harness (constructed `Conversation`/`Lead`, called the real `parent_flow` / `parent_llm_engine` / `parent_turn_router` / `timestamps` functions; no OpenAI, no network). The harness was deleted after capturing output. Findings are falsifiable: each shows the observed return value of the real function.

> **Scope caveat (not a hedge, a boundary):** these are defects in the **deterministic** layer. Several inputs *defer to the stochastic LLM* (handler returns `None`); for those the deterministic layer is correct-by-design and the LLM may or may not recover — that is called out per finding and is NOT counted as a deterministic defect unless the deterministic layer itself misbehaves.

---

## Summary

| Severity | Count |
|---|---|
| **BLOCKER** | **0** |
| **DEGRADED** | **7** (D1–D7) |
| **MINOR** | **5** (M1–M5) |

**Highest-risk area:** the **contact-name capture path** — `_parse_name_phone` + `_looks_like_contact_disclosure` + `_maybe_handle_contact_collection`. On common real inputs it writes **garbage into `lead.name`** (a pronoun, a conjunction, or an entire paragraph), which then flows verbatim into the Sheets CRM name column, the manager email, and the user-facing greeting („მადლობა, ჩემი."). Booking still completes, so it is not a blocker — but it is silent data corruption on inputs a real parent will send.

No input produced an exception, a fake booking, a wrong booking-state transition, or an impossible-to-proceed loop in the deterministic layer, so **no BLOCKER is claimed.** (Inflating severity would be dishonest — the failures are wrong-data / re-ask / silent-pick, not hard failures.)

---

## BLOCKER

None found in this pass.

---

## DEGRADED

### D1 — Junk leading words captured as `lead.name` when a phone is present
**Inputs (minimal):**
- `ჩემი ნომერია 595999733` → `_parse_name_phone` → name=**`'ჩემი'`**, phone=`'595999733'`; handler saves `lead.name='ჩემი'`, replies **„მადლობა, ჩემი. რომელი დღე…"**
- `ჩემი სახელია ლიზი ნომერი 595999733` → name=**`'ჩემი ლიზი'`** (should be `ლიზი`), reply „მადლობა, ჩემი."
- `გამარჯობა, ძალიან მაინტერესებს … დამირეკავთ ნომერზე 595999733 …` (long ramble) → name=**`'გამარჯობა ძალიან მაინტერესებს თქვენი ბანაკი ჩემი შვილისთვის და ვფიქრობ რომ იქნება თუ დამირეკავთ ნომერზე რომ დეტალები განვიხილოთ'`** (a whole paragraph) saved as the name; reply „მადლობა, გამარჯობა."

**Trace / path:**
1. [`_parse_name_phone`](app/flows/parent_flow.py#L3767) strips the phone, splits the remainder, and joins **every** token that survives [`_name_token_is_valid`](app/flows/parent_flow.py#L3830) with no length cap. `_name_token_is_valid('ჩემი')` = **True** (it is not in `NAME_FILLER_WORDS`, not a reject stem) — confirmed. `'გამარჯობა'`, `'ვფიქრობ'`, `'მაინტერესებს'`, etc. are likewise not filtered.
2. In [`_maybe_handle_contact_collection`](app/flows/parent_flow.py#L2456) the name-write guard is `is_valid_person_name(cand_name) and re.search(r"[ა-ჰ]") and _looks_like_contact_disclosure(...)`. [`_looks_like_contact_disclosure`](app/flows/parent_flow.py#L3148) **early-returns `True` whenever a phone is present** ([line 3154](app/flows/parent_flow.py#L3154)) — bypassing its own `?`/conversational-stem/4-token-cap guards. So a paragraph-as-name passes.

**Should:** drop pronoun/greeting chatter; capture only a plausible name (`ლიზი`) or nothing. Never store a multi-clause sentence as a name.
**Severity:** DEGRADED (silent CRM + email + greeting corruption; common input).
**Smallest fix area:** add `ჩემი`/`გამარჯობა`/`ვფიქრობ`/… to `NAME_FILLER_WORDS`, **and/or** cap captured-name length (e.g. ≤ 3 tokens) inside `_parse_name_phone`, **and/or** stop `_looks_like_contact_disclosure` from short-circuiting `True` on a phone when the remainder has > N tokens or a conversational stem.
**Fix:** **now** (cheap, high data-quality value).

### D2 — Two phone numbers in one message: second silently dropped, no clarification
**Input:** `595999733 ან 595999734`
**Trace:** [`_parse_name_phone`](app/flows/parent_flow.py#L3767) returns the **first** valid 9-digit window (`595999733`) and stops; the leftover `ან` survives `_name_token_is_valid` (= **True**, confirmed) so name=**`'ან'`**. Handler saves phone=`595999733`, name=`ან`, replies „მადლობა, ან."
**Should:** detect 2+ distinct valid numbers → ask which to use (or at least not invent a name from `ან`).
**Severity:** DEGRADED (manager may be handed the wrong number; „ან" as a name).
**Smallest fix area:** count valid 9-digit windows in `_parse_name_phone`/the contact handler; on ≥ 2, return a clarify reply. Add `ან`/`არა` to the name reject set.
**Fix:** **defer** (needs a small clarify-UX branch; lower frequency than D1).

### D3 — Latin / mixed-script name silently dropped, agent re-asks
**Input:** `Liziko 595999733`
**Trace:** `_parse_name_phone` → name=`'Liziko'`, phone=`595999733`; but the handler name-gate `re.search(r"[ა-ჰ]", cand_name)` ([line 2472](app/flows/parent_flow.py#L2472)) requires **Georgian** letters, so `Liziko` is rejected → `lead.name=''`, reply „**ნომერი მივიღე. მომწერეთ თქვენი სახელი**…" (asks for the name the user just gave).
**Should:** accept a Latin-script name, or acknowledge it; not silently re-ask.
**Severity:** DEGRADED (re-ask loop for Latin-typed names — common in Georgian DMs).
**Smallest fix area:** widen the gate to `[ა-ჰa-zA-Z]` in the contact handler (the parser already accepts Latin), or transliterate.
**Fix:** **defer** (intentional guard against eating „ok"/„hi"; needs a careful allowlist so it doesn't regress).

### D4 — BUG-1 capture is brand-marker-dependent → bare phone can still loop
**Input:** bot asks **without** the brand markers (e.g. „მომწერეთ თქვენი ნომერი."), no `pending_booking`, user sends bare `595999733`.
**Trace:** [`_bot_recently_asked_for_contact`](app/flows/parent_flow.py#L2456) only matches `_CONTACT_REQUEST_MARKERS` = `("საკონტაქტო ნომერ","9-ნიშნა","9 ნიშნა","ცხრანიშნა","ცხრა ნიშნა")` ([line 2523](app/flows/parent_flow.py#L2523)). „მომწერეთ თქვენი ნომერი." contains none → `in_contact_ctx=False` → `_maybe_handle_contact_collection` returns **`None`** → bare phone falls through to the stochastic LLM = **the original BUG 1 loop can recur**. (Confirmed: with `pending_booking` set it works; without markers AND without pending it does not.)
**Should:** capture a bare valid Georgian phone during PARENT contact collection regardless of the exact wording of the ask.
**Severity:** DEGRADED (the BUG 1 fix only closes the brand-phrased path; LLM-phrased asks reopen it).
**Smallest fix area:** broaden `_CONTACT_REQUEST_MARKERS` (add „ნომერ"+request-verb), or arm the capture on any bare 9-digit Georgian phone while `state` is a contact/booking state.
**Fix:** **now** (cheap marker broadening; this is the residual risk already flagged in the prior handoff).

### D5 — Two children, one message: only the first age captured
**Input:** `და-ძმა მყავს 10 და 14 წლის`
**Trace:** [`maybe_capture_child_age_fallback`](app/agent/llm/parent_llm_engine.py) captures the first standalone 1–2 digit number → `child_age='10'`; `14` is dropped. (Confirmed: `child_age='10'`.)
**Should:** detect multiple ages → ask which child, or qualify both.
**Severity:** DEGRADED (silently qualifies only one of two siblings; mis-handles the 14-year-old).
**Smallest fix area:** in the age fallback, detect ≥ 2 age-context numbers → defer/ask instead of grabbing the first.
**Fix:** **defer** (pre-existing limitation; needs multi-child UX, out of the contact-capture scope).

### D6 — Explicit consultation request WITH a phone in the same message ignores the phone
**Input:** `კი მინდა კონსულტაცია 595999733` as a fresh turn (eligible known age, no prior contact-ask, no `pending_booking`).
**Trace:** `_maybe_handle_contact_collection` returns `None` (no `in_contact_ctx` — bot hadn't asked, no pending). Then [`_maybe_request_full_contact_on_intent`](app/flows/parent_flow.py) matches the enrol stem and replies **„მომწერეთ თქვენი სახელი და 9-ნიშნა საკონტაქტო ნომერი…"** — asking for the phone the user **just provided** (confirmed: bug4 reply ignores the inline `595999733`).
**Should:** capture the inline phone first, then ask only for the still-missing field (the name).
**Severity:** DEGRADED (re-asks for a just-given phone; mild loop). Edge: requires eligible-age-known + intent + phone in one fresh message.
**Smallest fix area:** have `_maybe_request_full_contact_on_intent` parse+save an inline phone before composing the ask (or let the contact handler also fire on an explicit-intent message that carries a phone).
**Fix:** **now** (cheap; same module).

### D7 — Colloquial half-hour „5 საათსა და ნახევარზე" silently resolves to 17:00 (drops the :30)
**Input:** `5 საათსა და ნახევარზე` (the user means 17:30).
**Trace:** [`extract_colloquial_hour`](app/agent/services/timestamps.py) → **`(17, 0)`** — it parsed „5 საათ" → unqualified 5 → +12 = 17:00 and **ignored „ნახევარზე"**. (Half-hour slots are unsupported by design, but the :30 is dropped *silently* rather than routed to the `half_hour_not_supported` message.) Only bites when combined with a date (standalone `booking_dt=None` here).
**Should:** recognise the half-hour and return the existing „we book whole hours only" response, not a silent shift to :00.
**Severity:** DEGRADED (latent silent time mismatch when a date is also present).
**Smallest fix area:** make `extract_colloquial_hour`/the booking normaliser detect „ნახევარ"/„:30" and surface `half_hour_not_supported` instead of dropping the minutes.
**Fix:** **defer** (low frequency; half-hours are rejected downstream anyway, so the worst case is a confusing offer, not a wrong booking).

---

## MINOR

### M1 — Spelled-out age not captured
**Input:** `თორმეტი წლის` (twelve years) → `child_age=''` (unknown). The deterministic fallback only reads digits; the LLM may recover, but the deterministic booking path that relies on `child_age` misses it → likely a re-ask.
**Severity:** MINOR. **Fix area:** add a small Georgian number-word map (ერთი…ოცი) to the age fallback. **Fix:** defer.

### M2 — „შუადღის 2" (afternoon 2 / 14:00) not parsed deterministically
**Input:** `შუადღის 2` → `extract_colloquial_hour=None` (the „შუადღ" qualifier is unrecognised; it neither maps to PM nor lets the bare-9 rule run). Without a date, no harm; with a date it would fall to the LLM.
**Severity:** MINOR. **Fix area:** add „შუადღ" (noon/afternoon) to the colloquial qualifier table. **Fix:** defer.

### M3 — „საღამოს 11" → 23:00
**Input:** `საღამოს 11` → `(23, 0)` (evening 11 → +12). 23:00 is correctly outside business hours (10:00–21:00) so it is rejected downstream — but a user who meant „11 (in the evening, i.e. 23:00)" gets a rejection with no nuance, and a user who loosely said „საღამოს 11" meaning 11:00 is surprised.
**Severity:** MINOR (correctly rejected, low impact). **Fix area:** cap evening +12 so 10/11 stay literal, mirroring the morning rule. **Fix:** defer.

### M4 — Half-hour colloquials „ნახევარი ხუთის" / „ხუთის ნახევარი" → None
**Input:** `ნახევარი ხუთის` / `ხუთის ნახევარი` (4:30) → `extract_colloquial_hour=None`. Not understood deterministically; deferred to the LLM. Half-hours unsupported anyway.
**Severity:** MINOR. **Fix area:** same as D7 (recognise „ნახევარ" → half-hour message). **Fix:** defer.

### M5 — „12-13 წლის" range not captured (by-design) but no clarify
**Input:** `12-13 წლის` → `child_age=''` (the range guard `_contains_age_range` correctly refuses to read „12" out of a range — this is the intended fix for the „9-17" live bug). Correct, but the agent then relies on the LLM to ask „which exact age"; there is no deterministic clarify.
**Severity:** MINOR (correct rejection; only the follow-up is LLM-dependent). **Fix area:** optional deterministic „please give one exact age" when a range is detected in an age-context message. **Fix:** defer.

---

## Inputs that are handled CORRECTLY (verified, for completeness)

These adversarial inputs did **not** break the deterministic layer:

- **Phone formats:** `595 999 733`, `595-999-733`, `+995595999733`, `595999733.` → all parse to the phone and reply „ნომერი მივიღე…" / save correctly. (`+995595999733` is stored with the `+995` prefix; `_message_has_overlong_number` correctly treats 12 digits as valid, 15 as invalid.)
- **`ნომერი: 595999733`** → name correctly **empty** (`ნომერი` is in `NAME_FILLER_WORDS`), phone saved.
- **`595999733-ლიზი`, `ლიზი:595999733`, `მე ვარ ლიზი, 595999733`, `ლიზი 595999733`** → name=`ლიზი`, phone saved, „მადლობა, ლიზი…" (`მე`/`ვარ` are filler and correctly dropped).
- **Emoji message `მინდა 😊 595999733 კონსულტაცია`** → phone saved, name correctly **empty** (`😊` fails the Georgian-letter / `is_valid_person_name` gate), replies „ნომერი მივიღე. მომწერეთ თქვენი სახელი…".
- **Question during contact collection `რა ღირს ბანაკი?`** → contact handler returns `None` (has `?`) → deferred to the LLM (BUG-4 boundary respected; not hijacked).
- **`დილის 11`** → `(11, 0)` (morning 11 literal — correct).
- **Contact-only with future bookable confirmed slot** → contact handler defers so the commit helper books the slot (verified in the shipped tests).
- **Name correction `ლიზი... არა ნინო` (no phone)** → contact handler returns `None` (no phone) → deferred to the LLM; existing `lead.name` untouched. (Note: if a phone were appended, `_parse_name_phone` would mis-join `ლიზი არა ნინო` — same root as D1/D2; latent.)

---

## Recommendation (do NOT mark production green)

Fix-now candidates are cheap and isolated: **D1** (name-token filler/length), **D4** (broaden contact-ask markers), **D6** (capture inline phone on explicit intent). **D2/D3/D5/D7 + all MINOR** are deferrable (need small UX/clarify branches or number-word/qualifier tables). The dominant risk is **D1** — garbage names reaching the CRM and manager email on everyday inputs („ჩემი ნომერია …", a rambling first message). Production remains **NOT green**.
