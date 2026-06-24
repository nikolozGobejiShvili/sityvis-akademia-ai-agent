# CURRENT STATUS & LIVE REGRESSION — READ FIRST (2026-06-24)

This is the authoritative handoff state. Where any older doc disagrees (HANDOFF.md,
REVIEW_PACK.md, CLAUDE.md, LIVE_TEST_CHECKLIST, REDTEAM/SOURCE_OF_TRUTH audits),
**this file wins.**

> ⚠️ **Production is NOT green. Open client test is NOT approved. The live agent
> behaviour regressed after/around the Response Planner Hardening batch.** The
> next step is a **diagnostic trace audit**, NOT blind patching. **Do NOT say
> "only adult data remains" and do NOT say "ready for open client test."**

---

## 1. True current status (record as truth)
1. **Source-of-truth cleanup — COMPLETE** (camp age/location/streams/manager-phone/
   post-booking facts come from canonical helpers/config; `camp_2026.yaml` is
   fallback/legacy only).
2. **Central Turn Intent Gateway — IMPLEMENTED** (`reasoning_layer.analyze_turn_intent`,
   deterministic, always-on, fail-closed).
3. **Response Planner Hardening — IMPLEMENTED** (PII mask, consult-vs-registration,
   adult-self, human tone, off-topic/insult).
4. **PII full-phone leak — FIXED centrally** via a final outgoing-response mask of
   the user's own `lead.phone` (manager phone untouched). **Must be re-verified**
   that the mask only touches the final user-facing text and does NOT mutate
   state/history used by routing (see hypothesis #10).
5. **WhatsApp env mapping + test isolation — FIXED** (see §WhatsApp Status).
6. **Standalone WhatsApp smoke SUCCEEDED:** `configured=True`, `allow_live=True`,
   `recipient=995595999733`, `sent=True`.
7. **Scenario runner now mocks `_send_manager_whatsapp`** (cannot reach Meta in tests).
8. **Tests after the WhatsApp isolation batch were GREEN:** `pytest tests/`
   **2956 passed / 0 failed / 28 skipped**, `test_agent.py` PASS, CRITICAL **22/22**.
9. **BUT the live agent behaviour regressed after/around Response Planner Hardening**
   (see §Current live regression). Green automated tests do NOT contradict this —
   the failures are live, multi-source state/handler-priority issues not covered by
   the current suite.
10. **Production is NOT green.**
11. **Open client test is NOT approved.**
12. **"Only adult data remains" is NO LONGER TRUE** — do not state it.
13. **"Ready for open client test" is NOT TRUE** — do not state it.
14. **Current next step is a diagnostic trace audit, not blind patching.**

---

## 2. IMPORTANT testing condition (operator-confirmed)
The operator confirms that **before each live test**:
- **Redis is cleared (FLUSHALL).**
- **The server is restarted.**

Therefore: **Do NOT assume stale Redis / old session pollution as the default root
cause.** Still inspect Redis/session state, but classify stale Redis as the root
cause **only if evidence proves it**.

Primary investigation focus instead:
1. current-conversation state transitions;
2. pending state not cleared within the SAME conversation;
3. handler priority overriding the current user intent;
4. confirmed booking stored in one place but read from another;
5. the LLM reply saying "confirmed" while the structured booking_state stays pending;
6. multiple state sources — lead state, booking state, conversation history,
   Calendar busy state, Sheets row, latest CTA / pending flow;
7. the current user message losing priority to older state from the same conversation;
8. possible guard overreach introduced by Response Planner Hardening.

---

## 3. Current live regression — State Authority / Handler Priority

**This is NOT only a booking issue.** Observed live failures:

1. **Name message misrouted.** User: "ჩემი სახელია ნიკოლოზი" → Agent: "თქვენი შვილის
   ასაკი 7 წელი მიუთითეთ. ჩვენი ბანაკი 9–17 წლის ბავშვებისთვისაა…". Expected: save /
   acknowledge the name (or answer name/state context); MUST NOT continue a stale
   underage/camp flow.
2. **Adult cultural-event question misrouted.** User: "ზრდასრულთა კულტურული
   ღონისძიებები 7 წლის ბავშვებისთვის არის?" → answered as camp underage. Expected:
   clarify that adult cultural events have an adult/event-specific `min_age`; do NOT
   treat this as camp eligibility.
3. **Known child age ignored.** Child age already given as 13; later "ბანაკში მოწვეული
   სტუმრები არიან?" → agent re-asked the child age. Expected: use `child_age=13` and
   answer the actual question; if exact guest info is unavailable, say so and offer
   manager clarification.
4. **Camp visit/call question answered with consultation framing.** User: "შემეძლება
   ბანაკის განმავლობაში ბავშვს დავურეკო?" / "უსაფრთხოება დაცულია?" / "შემეძლება ბავშვი
   მოვინახულო?" → agent mixed in "კონსულტაცია ძირითადად ტელეფონით ან ვიდეოზარით
   ტარდება…". Expected: answer the camp-safety/communication question directly; do NOT
   conflate camp-period child contact with the consultation FORMAT.
5. **Booking confirmed then dropped from general recall.** Agent confirmed
   "კონსულტაცია 25 ივნისს, 12:00-ზე ჩაგინიშნეთ."; later "ჩემზე რა ინფორმაცია გაქვს?"
   recalled only the child age and re-asked for the consultation date/time. Expected
   recall: name + masked phone + child age + confirmed booking date/time.
6. **Booking recall works only with narrow phrasing.** "კონსულტაცია როდის მაქვს
   შეგიძლია შემახსენო?" → correctly answered "კონსულტაცია ჩანიშნულია 25 ივნისს,
   12:00 საათზე." This PROVES the booking info exists somewhere, but general state
   recall / handler priority does not consistently use it.
7. **Adult self + child mixed intent still weak.** "ჩემთვის და ჩემი შვილისთვის მინდა
   ღონისძიება მე ვარ 30 წლის" → redundant clarifier. Expected: understand the mixed
   intent (adult user 30 + events for self AND child); `adult_age` and `child_age`
   must stay separate.
8. **WhatsApp standalone smoke works, but agent-flow WhatsApp did not arrive.** See
   §WhatsApp Status for the exact things to investigate.

---

## 4. Root hypothesis (strongest current, to be PROVEN by trace, not assumed)

This is most likely a **current-session State Authority / Handler Priority** problem,
**not simply stale Redis**. Possible root causes:
1. the current user message loses priority to pending state;
2. old state inside the same conversation is not cleared on a topic switch;
3. confirmed booking state is stored but not read by general recall;
4. a booking-confirmation TEXT can be produced without canonical `booking_state` authority;
5. `adult_age` and `child_age` are not cleanly separated in mixed intent;
6. deterministic handlers answer BEFORE the gateway / response planner can use the
   current intent;
7. the general-recall handler priority is too low;
8. notification policy is inconsistent between handoff and booking;
9. **Response Planner Hardening may have added an overbroad guard or changed handler
   priority** (regression source candidate #1);
10. the **PII final masking must be verified** to ensure it only masks the FINAL
    output and does NOT mutate state/history used by routing.

---

## 5. NEXT TASK (record exactly)

### State Poisoning & Guard Regression Audit after Response Planner Hardening

**Purpose:** trace the live failures BEFORE patching. The next task must:
- replay the exact live transcripts (§3);
- capture the `TurnIntent` per turn;
- capture state BEFORE/AFTER each turn (lead, booking_state, conversation history,
  Calendar busy, Sheets row, latest CTA / pending flow);
- capture which handler was selected;
- capture whether the reply came from a deterministic handler or the LLM;
- capture Calendar/Sheets/email/WhatsApp side effects per turn;
- verify whether Redis was truly clean;
- verify whether the server saw a fresh env;
- **avoid patching before the root cause is proven.**

**Do NOT recommend blind fixes. Do NOT add more keyword paths before trace evidence.**
After the trace proves the root cause, do **one targeted architectural fix** (e.g.
state-authority / handler-priority), then re-verify.

---

## 6. Readiness classification (current, correct)
- **WhatsApp standalone send:** WORKING.
- **WhatsApp test isolation:** FIXED.
- **Core automated tests:** GREEN after the isolation batch (2956/0; CRITICAL 22/22).
- **Live agent behaviour:** **NOT stable enough for open client test.**
- **Guided client test:** **PAUSED** until the diagnostic trace audit.
- **Open client test:** **NOT approved.**
- **Production:** **NOT green.**
- **Next step:** diagnostic trace audit, then one targeted architectural fix.

**Stale statements to treat as RETRACTED everywhere:** "READY FOR OPEN CLIENT TEST",
"only adult data remains", "agent quality stable", "production ready",
"client can test everything". Adult-event operator data ("fromula 1" price_text 5000
vs price_gel 4999, and the removed gia event) is STILL a problem — but it is **NOT
the only blocker** now.

---

## 7. WhatsApp status (current)
1. Standalone WhatsApp smoke WORKED (`sent=True`).
2. Env mapping is CORRECT — token ← `WHATSAPP_ACCESS_TOKEN`, phone id ←
   `WHATSAPP_PHONE_NUMBER_ID`, recipient ← `MANAGER_WHATSAPP`.
3. `MANAGER_WHATSAPP` is read correctly (`+995…` first, then `MANAGER_WHATSAPP_NUMBER`).
4. `+995595999733` is normalised → `995595999733` (no `+`).
5. `_send_manager_whatsapp` is MOCKED in the scenario runner (`install_mocks`).
6. Test isolation IMPROVED — new `ALLOW_LIVE_WHATSAPP` guard (real POST only when
   `=true`), conftest pins it OFF, autouse `_block_real_meta_http` blocks `httpx.post`.
7. **However, the agent-flow WhatsApp notification did NOT arrive in the live test.**
8. The next diagnostic must determine whether:
   - the running app process actually saw `ALLOW_LIVE_WHATSAPP=true` (env reload / restart);
   - the booking path calls WhatsApp at all;
   - WhatsApp is wired ONLY for the handoff path, not the booking notification;
   - a notification failure is swallowed (logged + degraded silently).

---

## 8. What is verified-good (do not re-litigate)
- Automated suite green (2956/0), test_agent PASS, CRITICAL 22/22, transcript 3/3.
- Gateway age-vs-date / decline / off-topic / PII-mask unit + integration tests pass.
- WhatsApp standalone send works; isolation is in place.
These do NOT certify live behaviour — they bound the regression to live, multi-source
state/handler-priority paths the suite does not yet replay.
