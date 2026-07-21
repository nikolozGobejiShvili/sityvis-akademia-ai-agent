# Phase 4 — Executor-Verified Guardrail-Coverage Map

**Read-only deliverable. No code, test, or prompt change made while producing this doc.**

## 1. Purpose & method

`app/agent/prompts/system_parent_v2.md` (468 lines) carries ~39–48 dated "CRITICAL" /
"წესი" guardrail blocks, each written to fix a specific live production bug. A later
task (Task 3) will replace it with a lean `parent_lean.md`. Before that rewrite happens,
this document maps **every** guardrail block to one of three treatments so the lean
prompt neither drops a real guarantee nor carries dead weight:

- **backend-enforced** — a real mechanism outside the prompt guarantees the outcome
  regardless of prompt wording. This document recognizes **two** kinds of backend
  mechanism, both verified by reading the code (not assumed):
  1. a `reason` code / success-contract in `app/agent/tools/parent_tool_executor.py`
     (the tool boundary — cannot be bypassed by any prompt wording), and
  2. a deterministic **post-LLM guard function in `app/flows/parent_flow.py`** that
     runs unconditionally in the `handle()` pipeline and rewrites/strips/short-circuits
     the reply regardless of what the LLM said (e.g. the fake-booking guard, the
     sibling-discount strip, the political/unclear pre-engine interceptors, the
     privacy-notice policy). These are just as unbypassable as a tool reason code, so
     they are treated as backend-enforced too, with the function name + line cited.
- **prompt-only-behavioral** — no backend/deterministic signal exists, but the
  guarantee is a *behavior* (not exact words) and survives a paraphrase.
- **prompt-only-verbatim** — no backend/deterministic signal, AND the guarantee
  depends on exact wording (a mandated Georgian sentence, a banned/approved phrase,
  a grammar form). **Important sub-case, called out explicitly per block:** several
  guardrails are *currently* also patched by `FORBIDDEN_PHRASE_REPLACEMENTS` in
  `app/agent/llm/parent_llm_engine.py::sanitise_response_wording` (a simple
  string-substitution safety net, not a hard technical gate). Per the brief's own
  rule, that safety net does **not** count as "backend-enforced" for this map,
  because Task 4 may thin the sanitizer and drop those very entries — so these
  guardrails are classified **prompt-only-verbatim** and additionally flagged in
  §5 ("sanitizer-coupled") so Task 4 knows dropping the sanitizer entry is unsafe
  unless the prompt still carries the rule verbatim.

Method: every guardrail-shaped heading in `system_parent_v2.md` (dated CRITICAL/Patch
tags plus every other distinct "...წესი:" / policy heading — 48 blocks, more than the
initial "~39" estimate because being inclusive is safer than dropping a real
guardrail) was read in full, then cross-checked against `parent_tool_executor.py`
(every reason code cited below was located and read at its exact line), against
`parent_flow.py` (every deterministic guard cited was located, read, and confirmed
wired into the `handle()` pipeline — not dead code), and against
`FORBIDDEN_PHRASE_REPLACEMENTS` in `parent_llm_engine.py` for sanitizer coupling.
The booking-SUCCESS contract in `_book_consultation` was read line-by-line (not
assumed): `success=true` requires a non-empty Calendar `event_id` (L1337–1403) **and**
the actually-booked datetime to equal the requested datetime, else `slot_mismatch`
with a full state rollback (L1415–1466) — confirmed exactly as the brief described.

Two headline findings surfaced during verification (see §5 and the notes on rows 8
and 43): the prompt's detailed, multi-trigger-moment privacy-notice rule is **stale**
— actual runtime behavior is fully controlled by `parent_flow._apply_privacy_notice_policy`,
which strips the notice from every turn and re-adds the canonical sentence exactly
once, only on a confirmed booking/reschedule success. The lean prompt should describe
the *current* behavior, not the old timing rule. Separately, the brief's steer listed
"რამდენიმე შვილი / sibling discount (L389)" as *likely prompt-only* — verification
found it is **actually backend-enforced** via `parent_flow._strip_unwarranted_sibling_discount`,
correcting the steer.

## 2. Guardrail-by-guardrail table

| # | Block heading (line) | Guarantee / bug it fixed | Treatment | Backend evidence (reason code + executor line, or guard function + line) | Proposed lean text |
|---|---|---|---|---|---|
| 0 | `check_consultation_slot` reason→wording table (L18–31, tool-usage section) | LLM must react to the real availability reason, never guess "available" | **backend-enforced** | `_check_consultation_slot`, `parent_tool_executor.py` L720–927; reasons sourced from `calendar_service.is_within_business_hours` (`weekend`/`half_hour_not_supported`/`outside_business_hours`/`buffer_today`) and `calendar_busy` (L850–864) | "React honestly to `check_consultation_slot`'s `available`/`reason`; never state availability without calling the tool. Per-reason phrasing may be short." |
| 1 | თარიღების წესი — Booking Date Parse (L41–52) | "ხვალ/ზეგ/გუშინ" must resolve from real Tbilisi "today", never invented; past dates rejected | **backend-enforced** | `_normalise_datetime_iso_from_message`, `parent_tool_executor.py` L246–322 (overrides the LLM's date using `resolve_relative_datetime`); `datetime_in_past` reason, L1159 (book) / L1968 (reschedule) | "Trust the injected `today_iso_tbilisi`/`now_iso_tbilisi`/`resolved_relative_datetime_iso` context fields and pass them straight to tools — backend re-resolves relative dates and rejects past ones regardless of what you compute." |
| 2 | ADULT→PARENT გადასვლის წესი (L54–61) | Don't re-ask known `adult_target_age`; exact wording for in/out-of-range confirmation | **prompt-only-verbatim** | none found (context surfacing is code-side, but the response sentences are LLM-authored, unguarded) | Keep verbatim: the two exact sentences in L58–59 for in-range/out-of-range `adult_target_age`, and "never blindly copy adult_target_age → child_age without explicit confirmation." |
| 3 | ფლოუს გამიჯვნის წესი — Lead Field Separation (L63–66) | ADULT event interest must never land in PARENT `challenge`/`notes` | **backend-enforced** | `_save_lead_info` rejects via `_looks_like_adult_event_interest`, `parent_tool_executor.py` L1754 (challenge) / L1813 (notes), definition L2481–2520; write is refused, `invalid_fields` returned | "`challenge`/`notes` writes containing adult-event vocabulary are refused by the tool (`invalid_fields`) — state the two fields are segment-owned, no need to spell out the reject-list." |
| 4 | კონსულტაციის საათების წესი — Booking Availability (L68–75) | 10:00–21:00, 60-min slots only, no half-hour, Calendar busy always checked | **backend-enforced** | `outside_business_hours` L1190/L1986; half-hour rejected inside `is_within_business_hours` (`calendar_service.py` L269–270), surfaces as `slot_unavailable` L1231/L1999 via `check_slot_available`; `calendar_busy` in `_check_consultation_slot` L850–864 | "Hours 10:00–21:00 Mon–Sat, 60-min slots only — backend rejects anything else via reason codes; never invent an off-grid time." |
| 5 | რეგისტრაცია vs კონსულტაცია (L77–83) | Registration (link) ≠ Consultation (Calendar); never invent a link | **prompt-only-behavioral** | Partial: `registration_url_missing` (no reason-code number given, but verified at `_get_camp_info` L603–608) stops an invented URL; `camp_registration_closed` (L200) gates the topic. The *conceptual distinction itself* (don't conflate the two flows) is not tool-enforced. | "Registration = link (`get_camp_info('registration')`); Consultation = Calendar booking. Never invent a URL — tool returns `registration_url_missing` when none is configured." |
| 6 | კონსულტაციის მოსურვება — ფლოუს წესი / Booking Intent Flow (L85–92) | Recognize consultation-consent phrases incl. "კიმინდა"; never double-ask; `get_available_slots` before `request_manager_callback` | **prompt-only-verbatim** | none — a missed intent-recognition never reaches any tool, so nothing downstream can catch it | Keep verbatim: the consent-phrase list (incl. "კიმინდა" one-word) and the "*არ* ჰკითხო ხელახლა" / manager-before-slot ban. |
| 7 | კონტაქტ-ინფორმაციის შეგროვების წესი (L94–98) | Name known → don't re-ask; combined "phone+name" message parses correctly; 9-digit/5-7-8 validity | **backend-enforced** | Phone validity is deterministically parsed by `parent_flow._parse_name_phone` (L10546) and enforced via `invalid_phone`, `parent_tool_executor.py` L1134 | "Phone validity (9-digit local, 5/7/8 prefix) is backend-parsed and -validated — trust `invalid_phone`/success instead of re-deriving the regex in the reply." |
| 8 | კონტაქტ-ინფო კონფიდენციალობის წესი — Privacy Wording (L100–106) | Exact privacy sentence, mandated timing (every phone ask) | **backend-enforced (STALE PROMPT — see note)** | `_apply_privacy_notice_policy`, `parent_flow.py` L1813–1826, constant `_PRIVACY_NOTICE` L1784–1787: strips the notice from **every** turn's response and re-appends it **exactly once**, **only** on a confirmed booking/reschedule success (`_booking_success_this_turn`, L1797–1810, reads `book_consultation_success_for_conversation`) | "Privacy notice is fully backend-managed: stripped from every reply, re-appended verbatim exactly once, only on a real booking/reschedule success. The LLM must NOT try to add it manually — the old 'add it every time you ask for phone/age' timing in the current prompt is stale and should not be carried into the lean prompt." |
| 9 | ასაკის წესი (L108–121) | Under-min-age never booked; exact refusal message; CTA scrubbed | **backend-enforced** | `age_not_eligible`, `parent_tool_executor.py` L1118; `_ensure_ineligible_young_age_message`, `parent_flow.py` L3571 (forces exact refusal on disclosure turn); `_strip_consultation_cta_if_ineligible`, `parent_flow.py` L3497 (scrubs CTA) | "Under-`age_min` bookings are blocked (`age_not_eligible`) and the refusal wording + CTA-scrub are forced by deterministic post-processing — short behavioral rule only: never offer booking outside {age_min}–{age_max}; offer adult-flow or manager per disclosed age." |
| 10 | ფაქტების წესი (L122–123) | Never invent price/dates/location; never append "აკადემია" to location | **prompt-only-behavioral** | none generic; `get_camp_info` supplies the real values but nothing blocks an LLM sentence built without calling it | "Always source price/dates/location from `get_camp_info`; never invent or embellish a location name." |
| 11 | დაუდასტურებელი დეტალის წესი — ანტი-გამოგონება (L125–131) | Unknown operational detail → exact redirect phrase, never invented answer | **prompt-only-verbatim** | none | Keep verbatim: „რაც შეეხება [თემას], ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33" (and the topic-unknown fallback), plus "never swap 'გაგაცნობთ' for 'დაგიზუსტებთ'; no emoji." |
| 12 | პოლიტიკური/ოფ-თოფიკ პროვოკაცია (L133–134) | Political-identity bait → neutral fixed redirect, never engaged with | **backend-enforced** | `_maybe_handle_political`, `parent_flow.py` L4580–4594, wired **before the engine** at L1162–1164; returns `camp_topic_facts.political_reply(message)` directly — LLM is never invoked on a match | "Political-bait detection + exact reply is fully deterministic and pre-empts the LLM entirely — this heading can shrink to one line (or be dropped) in the lean prompt; canonical wording lives in `camp_topic_facts.yaml`, not the prompt." |
| 13 | გაუგებარი ფრაზის დაზუსტება (L136–137) | Unclear phrase → exact clarification question | **backend-enforced** | `_maybe_handle_unclear_phrase`, `parent_flow.py` L4597, wired pre-engine at L1165–1167 | "Deterministic pre-engine interceptor owns this — one-line note is enough in the lean prompt." |
| 14 | ფაქტური პასუხის სტრუქტურა (L139–146) | Structured price block; en-dash age format; exact payment-process sentence; exact booking-fee-unknown redirect | **prompt-only-verbatim** | Paragraph-break mechanic is separately backed by `_format_multipoint_paragraphs` (see row 15) — but the exact payment-process sentence (L144) and booking-fee redirect have no backend/sanitizer backing | Keep verbatim: the payment-process sentence, the booking-fee-unknown redirect, and the en-dash age format ("{age_min}–{age_max}" not "{age_min}-დან…"). |
| 15 | მრავალნაწილიანი პასუხის ფორმატირება (L147–150) | Multi-point answers get paragraph breaks; price digit always stated | **backend-enforced (partial)** | `_format_multipoint_paragraphs`, `parent_flow.py` L2482, confirmed wired post-engine (paragraph/whitespace only) | "Paragraph breaks are enforced by a deterministic post-processor regardless of prompt wording. The 'always include the numeric price' rule is NOT backend-checked — keep as an explicit short rule." |
| 16 | კონსულტაციის CTA წესი (L152–164) | CTA sentence appended only when appropriate; approved wording; 6 stop-conditions | **prompt-only-verbatim** | 2 of the 6 stop-conditions are backend-double-enforced: ineligible-age → `_strip_consultation_cta_if_ineligible` (L3497); booked-state → `_strip_consultation_cta_if_booked` (L3451). The other 4 (declined, registration-only, adult-switch, brief-clarification) and the approved sentence are unguarded. | Keep verbatim: the one approved CTA sentence. Short behavioral list for the other 4 stop-conditions; note ineligible-age/booked-state CTA is scrubbed regardless of prompt wording. |
| 17 | გადატანის წესი — Reschedule / One Active Consultation (L166–176) | One active consultation; exact confirmation sentences per `success`/`old_cancel_failed`; no echo of user's words | **backend-enforced** | Reroute logic verified in `_book_consultation` L1258–1309 and `_reschedule_booking` L1940–2225 (flags `old_cancel_failed` True@L2214/False@L2224, reasons `new_booking_failed_old_preserved`@L2089→returned as `calendar_error`@L2096); the specific "never re-ask confirmation after an explicit command" sub-rule is separately forced by `_strip_redundant_confirmation_after_command`, `parent_flow.py` L2850, wired L1627–1629 | "React honestly to `manage_consultation_booking`'s `action`/`success`/`old_cancel_failed` — flags are real; never claim the old booking was cancelled when `old_cancel_failed=true`. Redundant post-command confirmation is stripped by backend regardless." |
| 18 | გადამოწმების წესი — Verification Phrase (L178–181) | "შეამოწმე ისევ" ≠ confirmation; never books on a re-verify phrase | **backend-enforced** | `verification_requested`, `parent_tool_executor.py` L1080 (blocked at L1072–1083); driven by `_user_requested_verification` L2468–2478 over `_BOOKING_VERIFICATION_PHRASES` L2374–2402 | "Backend refuses to book on a re-verification phrase (`reason=verification_requested`) no matter what `user_confirmed_datetime` is sent — trust the tool's refusal; re-run `check_consultation_slot`." |
| 19 | ჯავშნის წარმატების წესი — Booking Success Confirmation (L183–187) | `success=true` only with real Calendar `event_id` matching requested datetime; never claim booking without it | **backend-enforced** | `_book_consultation`: empty `event_id` → `calendar_booking_failed`/`calendar_error` (L1337–1403); mismatch → `slot_mismatch` + full rollback (L1415–1466). Additionally the reply itself is guarded post-hoc: `_sanitise_booking_confirmation`, `parent_flow.py` L1829–1896, strips any "ჩაგინიშნეთ/ჩავნიშნე/ჩანიშნულია" text not backed by `book_consultation_success_for_conversation=True` this turn | "Never say booking is confirmed unless the tool returned `success=true` this turn — and even if you do, the backend guard scrubs it. Lean prompt needs only this one behavioral line — the double-gate is unconditional." |
| 20 | შერჩეული სლოტის წესი — Selected Slot Preservation (L189–193) | User's last explicit slot pick is canonical; never silently re-picked | **backend-enforced** | Same `slot_mismatch` check as row 19 (`parent_tool_executor.py` L1415–1466, actual vs requested ISO); pending-slot tracking in `_record_pending_booking_for_slot` / `_check_consultation_slot` L866–913 | "Pass the pending slot's exact `datetime_iso` unmodified — backend compares actual-booked vs requested and refuses (`slot_mismatch`) on any drift." |
| 21 | დაჯავშნის წესი (L195–212) | Master `reason`→wording map for `book_consultation` (10 branches) | **backend-enforced** | Every reason verified live in code: `datetime_not_confirmed` L1059, `missing_child_age` L1044, `missing_name` L1029, `missing_phone`/`invalid_phone` L1032/L1134, `invalid_datetime` L1143/L1151, `datetime_in_past` L1159, `verification_requested` L1080, `calendar_booking_failed` L1346/`calendar_error` L1349, `slot_mismatch` L1457, `outside_business_hours` L1190, `slot_unavailable` L1231, `age_not_eligible` L1118 | "React honestly to `book_consultation`'s `reason` — every value is a real, verified backend signal; map each to a short honest reply, never invent an unlisted reason." |
| 22 | გაუქმება / გადატანის წესი (L214–223) | Cancel/reschedule action integrity; never claim success without it | **backend-enforced (gap noted)** | `no_active_booking` L1882, `missing_event_id` L1904/L2014, `calendar_cancel_failed` L1922, `slot_unavailable` L1999, `old_cancel_failed_new_booking_active` L2203 (context)/exposed as `old_cancel_failed=True` L2214. **Gap:** unlike booking, there is NO `_sanitise_booking_confirmation`-style guard catching a hallucinated "გავაუქმე"/"გადავიტანე" wording on `success=false` (`FAKE_BOOKING_CONFIRMATION_STEMS` in `parent_turn_router.py` has no cancel/reschedule stems). The locative-form sub-rule ("გადატანაში" not "გადატანას") IS separately sanitizer-coupled (`parent_llm_engine.py` L1507–1532). | "Cancel/reschedule action integrity is backend-guaranteed — but keep the 'never claim success without success=true' line EXPLICIT in the lean prompt (no post-LLM safety net exists here, unlike booking). Locative wording may shorten only if Task 4 keeps the sanitizer entries." |
| 23 | მენეჯერის წესი (L225–226) | "მენეჯერი დაგიკავშირდებათ" only after real dispatch | **backend-enforced** | `_request_manager_callback`: `missing_phone` L1557, `already_notified` L1566, `dispatch_failed` L1612 (gates on real send, L1600–1612) | "'მენეჯერი დაგიკავშირდებათ' is true only when `request_manager_callback` returns `success=true` (real dispatch, phone-gated) — short honesty rule." |
| 24 | ზრდასრულთა ღონისძიების წესი (L228–229) | Never mention camp facts in ADULT context; never promise auto-follow-up | **prompt-only-behavioral** | `switch_to_adult_flow` only flips segment + optionally transfers age (`parent_tool_executor.py` L2288–2352) — no check on the reply's content | "On adult-event interest, call `switch_to_adult_flow` and stop discussing camp facts; never promise a delayed follow-up message." |
| 25 | უარის წესი (L231–232) | Plain decline → stop selling, one warm close | **backend-enforced (mostly)** | `_maybe_handle_decline_engine`, `parent_flow.py` L8312, deterministic pre-engine intercept (defers to engine only when a price-objection override marker co-occurs, per project docs) | "Plain decline is intercepted deterministically before the engine in the common case — short behavioral fallback rule for the LLM path is still needed for the override cases." |
| 26 | მადლობის წესი (L234–240) | Distinct thanks wording per context (booked/subscribed/general); "სიამოვნებით." alone banned | **prompt-only-verbatim (partial backend)** | Only the **general** thanks case is confirmed backend: `_maybe_handle_thanks_farewell`, `parent_flow.py` L8291–8309, constant `_THANKS_CLOSE_REPLY` L8257 matches L237 exactly. The booked-state (L235) and subscription (L236) variants, and the "სიამოვნებით." ban (L238), have no confirmed backend/sanitizer hook. | Keep verbatim: the booked/subscription thank-you sentences and the "სიამოვნებით." ban. Note the general-case sentence is backend-forced already (can shrink safely). |
| 27 | ისტორიის წესი (L242–245) | Never re-ask/re-state a known fact | **prompt-only-behavioral (partial backend)** | Confirmed only for age: `_strip_redundant_age_question_if_known`, `parent_flow.py` L2318, using shared `app/reasoning/age_question.py` helpers. No equivalent guard confirmed for name/phone/challenge re-asking in general. | "Never re-ask a known fact (name/phone/child_age/challenge) — age re-asks are additionally scrubbed by backend regardless." |
| 28 | აუდიტორიაზე მორგებული გაყიდვის წესი (L247–255) | Audience-aware sales sequencing (age→motivation→value→CTA) | **prompt-only-behavioral** | none | "Age first, then motivation, then value framing, then a soft CTA — never lead with price unless asked." |
| 29 | ბანაკის ინტერესის გახსნა — first message (L257–264) | Exact approved opening sentence; greeting prefix is automatic | **prompt-only-verbatim** | The "გამარჯობა 💙" prefix IS code-injected (not LLM-authored) per `_maybe_static_welcome`/greeting-strip machinery in `parent_flow.py` (L6521 area) — but the approved intro sentence itself is plain prompt text, unguarded. | Keep verbatim: the exact approved intro sentence (with its literal line break). Note the greeting prefix is backend-injected — the LLM must not add it itself (already partially enforced by greeting-strip, but the ban on inventing the OLD phrase is prompt-only). |
| 30 | ასაკის შემდეგ — grammar rules (L266–273) | Genitive form ("რისი მიღება გსურთ…", not "…გინდათ თქვენი შვილმა"); animate possession ("გყავთ" not "გაქვთ" for children) | **prompt-only-verbatim — sanitizer-coupled** | Currently ALSO patched by `FORBIDDEN_PHRASE_REPLACEMENTS`: "შვილები გაქვთ"→"…გყავთ" / "ბავშვები გაქვთ"→"…გყავთ" (`parent_llm_engine.py` L985–992); "რისი მიღებაც გინდათ…"→corrected form (L960–967). See §5. | Keep verbatim: both grammar rules, regardless of whether Task 4 keeps the sanitizer entries. |
| 31 | შეშფოთებაზე / pain-ზე პასუხი (incl. „შეშფოთების შენახვა" L298–300) (L275–300) | Empathy line + closed-set value-mechanism phrases; ban on "მოაგვარებს/გადაჭრის/განკურნავს"; conditional screen-mention | **prompt-only-verbatim** | none found | Keep verbatim: the approved mechanism-phrase list, the empathy openers ("გასაგებია"/"ეს გასაგებია"), the "never say resolve/cure/fix" ban, and the conditional screen-mention rule. |
| 32 | დეტალური თარიღი/ლოკაცია + კონსულტაცია vs ბანაკის ნაკადები (L302–311) | Consultation slot ≠ camp stream date; never invent stream dates | **prompt-only-behavioral** | `get_camp_info` supplies real stream dates via `get_visible_camp_streams`, but nothing blocks the LLM from conflating consultation date with stream date in prose | "Consultation booking and camp-stream dates are different things — stream dates only from `get_camp_info`, never invented; a consultation may be booked before the camp itself starts." |
| 33 | ზუსტი თარიღი/დროის შემოწმება (L313–320) | Always call `check_consultation_slot` for an exact date+time; never rely on the 6-slot cap of `get_available_slots` | **prompt-only-behavioral** | Tool-choice itself is not enforced; once called, reasons are backend-correct (row 0/4) | "Always call `check_consultation_slot` for an exact date+time; `get_available_slots` is capped at 6 and is for browsing only." |
| 34 | ცნობილი მონაცემების შენახვა (L322–324) | Never re-ask known fields; `book_consultation` auto-fills them | **backend-enforced** | Verified in `_book_consultation`: required-field checks fall back to `self.lead.name`/`.phone`/`.child_age` when args omit them (`parent_tool_executor.py` L1027–1046) | "Known name/phone/child_age/challenge are auto-filled by the tool when omitted from args — the LLM does not need to resend them, only avoid re-asking." |
| 35 | ცალსახად არჩეული სლოტი + `user_confirmed_datetime` (L326–340) | Precise example list of what counts as an explicit slot confirmation | **prompt-only-verbatim** | `datetime_not_confirmed` (L1059) only catches the flag being **False** — nothing validates that a **True** flag was set for a *good* reason (the LLM's own judgment is trusted); the `pending_booking["user_confirmed_datetime"]` cross-check (L997–1005) only helps when the LLM forgot to set it, not when it wrongly set it | Keep verbatim: the example phrase list (both the "set true" and "do NOT set true" examples) — the false-negative case is backend-caught but the false-positive (premature True) is not. |
| 36 | კონსულტაცია vs ფიზიკური ვიზიტი (L342–350) | Consultation is phone/video, never "in person"; exact clarification sentence | **prompt-only-verbatim** | none | Keep verbatim: "კონსულტაცია ძირითადად ტელეფონით ან ვიდეოზარით ტარდება." and the pending-slot preservation note. |
| 37 | აკრძალული ფრაზები — literal/რობოტული (L355–380) | ~20 banned robotic/awkward phrases with approved replacements | **prompt-only-verbatim — sanitizer-coupled (MAJOR)** | Nearly every banned phrase in this block has a matching `FORBIDDEN_PHRASE_REPLACEMENTS` entry in `parent_llm_engine.py` (L847–1254): "გაიმეორეთ ნომერი" L858, "შეკვეთოთ…" L866, "ყოველთვის მზად ვარ" L874/878, "დამიმტკიცეთ" L886, "მენეჯერის კავშირი" L912, "მენეჯერს გადასცე" L916, "გთხოვთ მომწერეთ" L922, "განვადებაში" L932, "ჩამოუყალიბეთ" L971–980, "აზრი აქვს"/"ეს გასაგები მოთხოვნაა" L999–1017, "დეტალებს ცოცხლად" L945–951, "რომ სწორად გითხრათ" L1040–1050, "გაგივლით" L1054–1068, "დაგიბაროთ/დაგიბარებთ" L1073–1102 (continues past L1102). See §5. | Keep the full banned-phrase list verbatim in the lean prompt; do not rely on the sanitizer alone. |
| 38 | დახურვის წესი — thanks/decline close (L382–385) | Exact short closes for "მადლობა"/"არა მადლობა"/"დავფიქრდები"; never resume selling after | **backend-enforced** | Same deterministic intercepts as rows 25/26: `_maybe_handle_decline_engine` (L8312) / `_maybe_handle_thanks_farewell` (L8291–8309) | "Decline/thanks closes are handled by deterministic pre-engine intercepts in the common case; short fallback line for the LLM path." |
| 39 | ფასის წინააღმდეგობა (L387) | 4-step price-objection script; ban on "მოტივაცია"/"იაფია" | **prompt-only-behavioral** (⚠️ SUPERSEDED 2026-07-21 — was `prompt-only-verbatim`, see note below) | none (a routing guard exists — `_DECLINE_OVERRIDE_INTEREST` markers keep price objections out of the decline path — but the *content* of the reply is unguarded) | Render behaviorally, keeping every guarantee explicit: empathize before any CTA; connect price to value/what's-included; mention the 6-month TBC/BoG split; one light CTA; always state the price digit; `*არ* გამოიგონო ფასდაკლება/ფასი`; banned words "მოტივაცია"/"იაფია". Do NOT reproduce the two fixed quoted sentences. |
| 40 | რამდენიმე შვილი — Sibling Discount (L389–399) | 10% discount mentioned only for 2+ children enrolling together; single-participant never gets it | **backend-enforced** (brief's steer said "likely prompt-only" — **corrected on verification**) | `_strip_unwarranted_sibling_discount`, `parent_flow.py` (defined ~L2898, wired into the reply pipeline at L1617–1619): strips the discount sentence whenever the conversation lacks an explicit 2+-children trigger | "Mention the 10% sibling discount only when 2+ children are explicitly enrolling together — backend deterministically scrubs any unwarranted mention regardless of what the LLM says." |
| 41 | გაბრაზებული მომხმარებელი (L401) | Exact opening apology; never defensive; never restart menu | **prompt-only-verbatim (likely sanitizer-coupled)** | Not found in the grep of `parent_llm_engine.py` FORBIDDEN_PHRASE_REPLACEMENTS entries read directly, but the project's own change-log (CLAUDE.md) documents this as "system-prompt rule + sanitiser" — treat as sanitizer-coupled pending Task 4's own audit; classify conservatively | Keep verbatim: "ბოდიშს გიხდით. ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ." plus the "never defensive / never restart menu" bans. |
| 42 | წარსული თარიღი — exact wording ban (L403) | Never say "უკვე გასულია"; exact replacement sentence | **prompt-only-verbatim** | The underlying FACT is backend-guaranteed (`datetime_in_past`, L1159/L1968 — a past date is genuinely rejected), but the specific banned/approved WORDING was not found in the sanitizer or any guard | Keep verbatim: the banned phrase and its exact replacement sentence; note the past-date *fact* itself is backend-guaranteed separately. |
| 43 | კონფიდენციალობის შენიშვნა — privacy note, child data (L405–424) | 4 specific trigger moments + exact phrase + Q&A script for "why age" | **backend-enforced (STALE PROMPT — MAJOR finding)** | Same mechanism as row 8: `_apply_privacy_notice_policy`, `parent_flow.py` L1813–1826, overrides this ENTIRE elaborate 4-trigger-moment scheme — the notice is stripped from every turn and shown exactly once, only on booking/reschedule success | "Do not carry forward the 4-trigger-moment timing rule into the lean prompt — it no longer matches runtime behavior. State only: privacy notice is backend-managed, appears once on real booking/reschedule success; keep the exact sentence text and the 'why age' Q&A script verbatim (those parts are still LLM-authored and unguarded)." |
| 44 | განსაკუთრებული საჭიროებების წესი — sensitive needs (L425–429) | Exact empathy+handoff sentence; ban on "მენეჯერთან გავარკვევთ" and variants | **prompt-only-verbatim — sanitizer-coupled** | "მენეჯერთან გავარკვევთ" family confirmed in `FORBIDDEN_PHRASE_REPLACEMENTS`, `parent_llm_engine.py` L1456–1464. See §5. | Keep verbatim: the exact handoff sentence and the banned-phrase list. |
| 45 | დაჯავშნული მომხმარებლის წესი + expired booking memory (L431–442) | Booked user never re-offered booking; expired booking silently demoted, never re-shown as active | **backend-enforced** | `_strip_consultation_cta_if_booked`, `parent_flow.py` L3451, wired L1611–1613; `_expire_past_booking_if_needed`, `parent_flow.py` L3349 (resets `calendly_booked=False` for a past `booked_datetime_iso`, called before context-build/CTA-scrub/memory-info per project docs) | "Booked-state CTA suppression and expired-booking demotion are both deterministic post-processing — short behavioral note only: never re-offer a booking to an already-booked user; never reference a booking date that has passed." |
| 46 | მახსოვრობის შესახებ კითხვა — memory-info (L444–456) | "What do you know about me?" → structured summary of known fields only, no PII/tech leakage, no LLM call | **backend-enforced** | `_maybe_memory_info_reply`, `parent_flow.py` L8074, deterministic pre-LLM handler (no OpenAI call), omits unknown fields, never surfaces sender_id/tokens/platform IDs | "Memory-info questions are answered deterministically before the LLM runs — lean prompt needs only a one-line note that this exists; the field-omission and privacy rules are already enforced in code." |
| 47 | არასოდეს — closing catch-all list (L458–468) | Summary re-statement: never invent facts, never confirm w/o success, never self-pick slot, never skip age check, never ask 2+ questions, never say "აირჩიეთ"/"გნებავთ A თუ B", never invent registration link, never confirm cancel/reschedule w/o success | **mixed → prompt-only-behavioral (as a block)** | Most sub-bullets duplicate already-backend-enforced rows (19/21 booking-success, 9 age-check, 5/10 registration link, 22 cancel/reschedule). Two sub-bullets have NO backend/sanitizer backing anywhere: "never ask 2+ questions at once" and "never say 'აირჩიეთ'/'გნებავთ A თუ B'". | "Collapse to the 2 items with no other coverage: never ask two questions in one turn; never use 'აირჩიეთ'/'გნებავთ A თუ B' phrasing. The rest is already guaranteed by the rows this list restates — safe to drop as a separate closing block." |

## 3. Summary counts

- **backend-enforced: 24** (rows 0, 1, 3, 4, 7, 8, 9, 12, 13, 15, 17, 18, 19, 20, 21, 22, 23, 25, 34, 38, 40, 43, 45, 46)
- **prompt-only-behavioral: 9** (rows 5, 10, 24, 27, 28, 32, 33, 39, 47) — *row 39 reclassified 2026-07-21, see §3a*
- **prompt-only-verbatim: 15** (rows 2, 6, 11, 14, 16, 26, 29, 30, 31, 35, 36, 37, 41, 42, 44)
- **Total guardrail blocks mapped: 48** (more than the "~39" estimate — every distinct rule-bearing heading was given its own row rather than risk dropping one by over-merging).

### 3a. Row 39 supersession — price objection (2026-07-21, human decision)

This map originally classified row 39 (`ფასის წინააღმდეგობა`, `system_parent_v2.md:387`)
as **prompt-only-verbatim** and prescribed keeping the 4-step script. Task 3's brief
(Step 1) explicitly ordered the opposite: render it behaviorally, because this is the
block the naturalness measurement targets — the live OB1 objection reply scores
**0.00/4** on the OpenAI judge, and the reply is so fully determined by this script
that the Phase-2/Phase-3 machinery produced a **byte-identical** reply with the
reasoning loop on and off (measured 2026-07-21).

The Task-3 review surfaced the map-vs-brief contradiction and it was escalated. The
**human decision-maker ruled the brief governs**, on this reasoning: the plan's global
constraint says to keep a rule verbatim *"if that's what makes it hold"* — and what
makes this block hold are its **guarantees** (state the price digit, never invent a
discount, banned words, payment split), not the 1)–4) **choreography**. The choreography
is sales sequencing, not a safety guarantee.

Net guardrail coverage of the price block is **strictly better** after the change, not
worse: `*არ* გამოიგონო ფასდაკლება/ფასი` (`system_parent_v2.md:150`) was absent from the
lean prompt **entirely** and is now restored as an explicit bullet.

Residual risk, to be watched by Task 5: with the choreography gone, objection wording
becomes model-chosen. The conversion-proxy assertions on OB1/OB2/OB3
(`require_any` = value/payment, `forbid_any` = pressure/invented-discount) are the gate
that confirms the reply still sells. **If correctness drops there, revert row 39 to
verbatim.**

#### ⚠️ 3a-UPDATE (2026-07-22) — THE REVERT TRIGGER FIRED. Row 39 must revert before enablement.

Task 5 measured it (`docs/MEASURE_PHASE4.md`). **Correctness dropped on a price
objection, exactly as the trigger anticipated — but on `Q2`, not on any of the three
case IDs the trigger enumerated.** Under `USE_LEAN_PROMPT`, Q2's
`value/payment framing present` check went **3/3 → 1/3 → 0/3 reps** (1/1 → 0/1).
`forbid_any` held throughout (0/15 failures — no invented discount, no pressure wording),
so the failure is *under*-selling, not a safety breach: the reply reads better and sells
less.

**Ruling: before `USE_LEAN_PROMPT` is ever enabled, row 39 reverts to
`prompt-only-verbatim`,** or its behavioral rendering must be re-validated and shown to
hold value/payment framing.

**Two lessons, both about the gate rather than the guardrail:**

1. **The trigger was written as a list of case IDs instead of a semantic condition, which
   made it near-unfalsifiable.** Two of its three enumerated cases cannot measure row 39
   at all: `OB1` never reaches the LLM (the deterministic `_camp_price_full_block()`
   interceptor answers it) and `OB3` hits the registration-closed fallback because the
   camp is over. Had we waited for "correctness drops on OB1/OB2/OB3" literally, the
   trigger could never have fired. **Write revert triggers as conditions
   ("any price-objection case loses value/payment framing"), not as case lists.**
2. **Leading mechanistic hypothesis for the regression:** `system_parent_v2.md:387`
   step 2 names the four inclusions explicitly (`ტრანსპორტი/განთავსება/კვება/პროგრამა`);
   `parent_lean.md:83` compresses them to `„დააკავშირე ფასი ღირებულებას (რა შედის)"`.
   Dropping the explicit enumeration is the most plausible cause of the model dropping
   value **and** payment framing. Restore the enumeration first if row 39 is retried.

---

Rows 15, 16, 22, 25, 26, 27, 38, 45 carry an explicit **partial/hybrid** note in their
evidence column (some but not all of the block's sub-rules are backend-covered) —
these are still counted once, in the bucket matching their dominant/most-conservative
verified guarantee.

## 4. BLOCKERS

**None.** Every one of the 48 rows above has a proposed lean text (either a short
behavioral rule or an explicit "keep verbatim: …" instruction) — no guardrail block
was left without a Task-3 disposition.

Two items are flagged for follow-up attention rather than blocking:
- Row 26 (მადლობის წესი) and row 27 (ისტორიის წესი) only have *partial* backend
  confirmation (one sub-case each) — Task 3 should keep the unconfirmed sub-cases
  verbatim (already reflected in the "proposed lean text" column) rather than assume
  full backend coverage.
- Row 22 (cancel/reschedule) has a real, verified **asymmetry** with row 19/21
  (booking): booking has a second-layer post-LLM guard (`_sanitise_booking_confirmation`)
  that catches a hallucinated success claim even if the tool result was ignored;
  cancel/reschedule has no equivalent guard. This is a genuine gap in current
  production code (not something this read-only task is authorized to fix), but the
  lean prompt for row 22 must NOT be shortened to rely on a safety net that doesn't
  exist.

## 5. Sanitizer-coupled guardrails

These guardrails' *current* production behavior is patched by
`FORBIDDEN_PHRASE_REPLACEMENTS` inside `parent_llm_engine.py::sanitise_response_wording`
— a simple exact-string substitution, not a technical gate. If Task 4 thins the
sanitizer and drops these entries, the **prompt is the only remaining defense** for
each. All are already classified `prompt-only-verbatim` above for this reason; this
section exists so Task 4 can cross-check its own drop-list against this table before
removing any of these specific entries.

| Guardrail (row #) | Banned/rewritten phrase(s) | Sanitizer location (`parent_llm_engine.py`) |
|---|---|---|
| 37 (აკრძალული ფრაზები) | "გაიმეორეთ ნომერი", "შეკვეთოთ…", "ყოველთვის მზად ვარ", "დამიმტკიცეთ", "მენეჯერის კავშირი", "მენეჯერს გადასცე", "გთხოვთ მომწერეთ", "განვადებაში", "ჩამოუყალიბეთ", "აზრი აქვს"/"ეს გასაგები მოთხოვნაა", "დეტალებს ცოცხლად", "რომ სწორად გითხრათ", "გაგივლით", "დაგიბაროთ"/"დაგიბარებთ" | L847–1254 (block start L843) |
| 37 / L377 (გეთანხმებით ban) | "გეთანხმებით ამ დროით", standalone "გეთანხმებით" | L1219–1243 |
| 37 / L378 (spelling) | "დაჭვება"/"დაეჭვება" | L1246–1254 |
| 44 (sensitive needs) | "ამ საკითხს მენეჯერთან გავარკვევთ", "მენეჯერთან გავარკვევთ" | L1456–1464 |
| 22 (cancel/reschedule locative) | "…გადატანას დავეხმარები/დაგეხმარებით" → "…გადატანაში დაგეხმარებით"; "…შეცვლას…" → "…შეცვლაში…" | L1507–1532 |
| 30 (grammar) | "შვილები/ბავშვები გაქვთ" → "…გყავთ"; "რისი მიღებაც გინდათ თქვენი შვილმა" → corrected genitive | L960–992 |
| — (tone, L16) | Emoji ban: 🌿 😊 ✨ ✅ ❌ | L1706–1715 (PARENT); mirrored in ADULT sanitizer |
| 41 (angry customer) | Fixed apology opener — sanitizer coupling asserted by project docs (CLAUDE.md), not independently re-confirmed by grep in this pass | flagged for Task 4's own audit |

**Recommendation for Task 4:** before dropping any `FORBIDDEN_PHRASE_REPLACEMENTS`
entry listed above, confirm the matching prompt text in the lean prompt still states
the rule verbatim (per §2's "keep verbatim" cells for rows 30, 37, 41, 44, and the
locative sub-rule of row 22). Rows already classified `backend-enforced` (via a real
`parent_tool_executor.py` reason code or a `parent_flow.py` deterministic guard) are
safe regardless of sanitizer thinning, since their guarantee does not depend on the
sanitizer at all.
