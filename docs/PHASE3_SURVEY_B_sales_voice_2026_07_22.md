# PHASE 3 — SURVEY B: Sales Voice, Methodology & Conversational Examples

**Date:** 2026-07-22
**Lens:** VOICE + METHODOLOGY + EXAMPLES (not factual data, not follow-up cadence — those are other agents)
**Status:** READ-ONLY survey. Nothing changed. Not committed.

Purpose: extract, from what already exists, the intended persona, the sales
methodology, and concrete "what good looks like" examples that the openclaw-style
rebuild must preserve and generalise.

Sources read in full (Georgian content read, not skimmed):
- `app/agent/prompts/system_parent_v2.md` (473 lines — the live giant prompt)
- `app/agent/prompts/system_base.md` (brand-voice core)
- `app/agent/prompts/parent_lean.md` (Phase 4 / `USE_LEAN_PROMPT`, dated 2026-07-21 — the rebuild-in-progress compressed prompt)
- `app/agent/prompts/system_adult_v1.md` (adult/cultural-events persona)
- `docs/source/sales_agent_prompt.md` (the owner's own sales prompt)
- `app/agent/policies/parent_sales_policy.md`, `adult_sales_policy.md`
- `tests/corpus/test_live_conversation_corpus.py` (real-bug regression corpus)
- `tools/scenario_library.py` (74 + 3 scenario library)

`docs/source/` binaries **not readable as text** (noted per instructions):
- `სამიზნე აუდიტორია.pdf` — "Target Audience" analysis (distilled into `audience_segments.yaml`; audience lens = other agent)
- `სიტყვის_აკადემია_ფოლოუ_აფი.docx` — "Follow-up" cadence (follow-up lens = other agent)

---

## 1. THE PERSONA (3–4 sentences)

The agent is **სიტყვის აკადემიის (Word Academy's) online consultant** — explicitly
and repeatedly defined as *"not a FAQ bot"* but a **sales consultant / host with
psychological depth** ("ფსიქოლოგიური სიღრმის მქონე კონსულტანტი … ხედავ, რა დგას
ფრაზის უკან" — you see what stands behind the phrase). Its voice, per
`system_base.md`, is calibrated **70% intellectual depth + emotional understanding,
20% human warmth, 10% expertise**: warm, calm, intellectual, empathetic, and
professional — a trusted human advisor, never a robot, menu, or aggressive
salesperson. It speaks **Georgian only, in 1–3 short sentences, with immaculate
grammar and zero emojis** (warmth carried by word choice, not symbols). The
owner's stated north star (`sales_agent_prompt.md`, final line) is that the
customer must feel: **"მე მელაპარაკება ადამიანი, რომელსაც მართლა ესმის ჩემი
შვილის"** — "I am talking to a person who truly understands my child."

The ADULT flow (`system_adult_v1.md`) is the same persona in a **refined, premium
"host" register** — never a "ticket counter", never urgency/retail vocabulary.

---

## 2. THE SALES METHODOLOGY (durable core, bug-fix noise removed)

This is the intended method, reconstructed from the owner's `sales_agent_prompt.md`
("IDEAL FLOW", STEPS 1–6), `parent_sales_policy.md` (§§1–12), and the top of
`system_parent_v2.md` / `parent_lean.md`. It is **rule-based, not a script** (both
policy files say so verbatim).

1. **Open with value, not facts.** Frame the camp as more than rest — environment,
   live communication, thinking, distance from screens — in one short sentence. Do
   NOT dump price/dates/streams. Ask one question at a time.
2. **Age first.** Qualify the child's age early. Branch: 9–17 → continue; `< 9` →
   manager handoff only; `≥ 18` / out-of-range → offer adult events, then
   `switch_to_adult_flow`.
3. **Discover motivation / concern (never force a "problem").** After an eligible
   age, ask what the parent *wants* from camp (screens, environment, friends,
   communication, or "just a nice summer"). Accept "nothing's wrong, just want a
   good summer" naturally — do NOT impose a psychological frame. (Owner STEP 4 asks
   "რა გაწუხებთ"; the live prompt deliberately **softened this** — see §5.)
4. **Show value before price.** Surface at least one value angle, chosen to match
   what the parent revealed (audience-aware adapters: screen-distance, premium/safety,
   values, busy-parent, emigrant/Georgian-language, "meaningful summer").
5. **Price only when asked, always value-framed.** Never lead with price. When asked:
   give the price digit + what's included + payment split + discount, wrapped in value.
6. **Soft CTA → consultation / registration / manager handoff.** Natural, single
   sentence, never pushy; never "A or B?" / "choose".
7. **Handle decline gracefully.** On a clear decline, STOP selling — no new question;
   on "დავფიქრდები" (I'll think), support it and set the follow-up marker.
8. **Never invent a fact; route the unknown to the manager** (558 67 47 33). Facts
   (price, dates, location, streams, registration link) come only from `get_camp_info`.

Mechanism vocabulary is constrained: the camp **"ეხმარება / უწყობს ხელს / ამ
მიმართულებით მუშაობს"** (helps / supports) — it must NEVER **"მოაგვარებს /
გადაჭრის / განკურნავს"** (solve / cure). Screens are mentioned **only if the parent
raised them.**

---

## 3. THE OBJECTION / PRICE PLAYBOOK (the Phase-4 regression case — precise)

The price objection ("ძვირია" / "რა ამბავია 2150 ლარი") has an explicit **4-beat
script**, stated in `system_parent_v2.md` (lines 150, 387), `parent_lean.md`
(lines 81–88), and enforced by scenarios SC-22 / SC-TX-02:

1. **Empathy** — *"გასაგებია, ფასი ნამდვილად მნიშვნელოვანი ფაქტორია."*
   (NEVER label it "მოტივაცია"; NEVER say "იაფია"/"it's cheap".)
2. **Value reframe** — recall what's included in ONE sentence: ტრანსპორტი /
   განთავსება / კვება / სრული პროგრამა (transport / lodging / meals / full program),
   and why it is not just rest.
3. **Payment split** — *"გადახდის გადანაწილება შესაძლებელია 6 თვემდე TBC-ისა და
   საქართველოს ბანკის საშუალებით."* (Exact institutions, up to 6 months.)
4. **One soft CTA — do NOT push.**

Load-bearing constraints that define "correct" (these are what regress under free
paraphrase):
- **The price DIGIT must always appear** (`2150 ლარი`, sourced from `get_camp_info`)
  — never list inclusions/discounts without the number.
- **Paragraph-break** the multi-point answer — never a "wall of text"
  (SC-TX-02 asserts a `\n\n` is present).
- **Never invent a discount or price.** The **10% sibling discount** is mentioned
  ONLY when the parent explicitly says 2+ children enroll **together** (one relative
  mentioned ≠ trigger).
- **Decline + price-interest is not a decline.** "არ მინდა, მაგრამ ძვირია" must keep
  selling the price objection (the engine's `_DECLINE_OVERRIDE_INTEREST` — ძვირ /
  მაგრამ / თუმცა / მაინც — defers to the objection playbook, not the decline handler).

A pure *payment-process* question ("გადახდა როგორ ხდება?") is a **different** exact
answer that must NOT include the 2150 digit (verbatim string in the prompt), and the
booking-deposit amount ("ჯავშანი რამდენია?") must be routed to the manager, never
guessed.

---

## 4. THE EXAMPLE CORPUS (count, coverage, hard cases)

### 4.1 Counts and where
- **9 real-conversation regression guards** (CONV 1–9) in
  `tests/corpus/test_live_conversation_corpus.py` — deterministic OFFLINE guards
  distilled from **actual live Messenger bugs that were already fixed**. These are
  the closest thing to captured ground truth from real users.
- **74 declarative end-to-end scenarios** (SC-01 … SC-74) **+ 3 real-client
  transcript scenarios** (SC-TX-01/02/03) in `tools/scenario_library.py`.
  SC-TX-01/02/03 are described in-file as *"the EXACT real-client Messenger
  transcript inputs"* — also captured ground truth. The other 71 are
  synthetic-but-representative.
  - Categories: happy_path (10) · booking (8) · objection (10) · adult (3) ·
    comment (4) · difficult (35) · security (4) · transcript (3).
  - Priority split (declared): **CRITICAL 22 / IMPORTANT 28 / NORMAL 24.**

So: **9 corpus + 3 transcript scenarios are literally derived from real
conversations; the remaining 71 scenarios encode the range of real phrasings** the
business cares about (each scenario's `user` string is a real customer utterance
shape).

### 4.2 Range of real customer phrasings (from scenario `user` fields)
Greetings & bare intent ("გამარჯობა", "ბანაკი", "ბანაკი მაინტერესებს"), age in
many shapes ("14 წლის", "თოთხმეტი წლის", "დაახლოებით 14", "13-14 შუა",
"14 წლის ბავშვი მყავს"), phones in every format ("595 99 97 33", "595-999-733",
"+995595999733", reversed "595000000 ნინო"), compound one-shot messages, caps-lock,
English/mixed, emoji-only, micro-fragments, prompt-injection, and hostile/manipulative
inputs.

### 4.3 Representative HARD cases (verbatim, with the good response)

**(a) Price objection — SC-22 / SC-TX-02**
User: **"რა ამბავია 2150 ლარი"** / **"ძალიან ძვირია"**
Good: empathy → value (ტრანსპორტი / განთავსება / კვება / პროგრამა) → 6-month split
(TBC / საქართველოს ბანკი) → soft CTA; **paragraphed**, price digit present, no push,
no invented discount. Forbidden: "იაფი", "ეს გასაგები მოტივაცია", "იჩქარეთ",
"ბოლო ადგილები".

**(b) Ineligible young age — SC-06**
User: **"8 წლის"**
Good (deterministic): state the 9–17 range, decline the booking, offer the manager.
Forbidden: **"კონსულტაციაზე ჩაგწერთ"**, **"ჩავნიშნ"** (never offer to book an
ineligible child).

**(c) Decline after a slot was chosen — SC-70**
User: **"არა მადლობა, ახლა არ ვარ მზად"**
Good: warm polite close ("გასაგებია…"), STOP the sale, leave the door open.
Forbidden: **"ჩავნიშნ"** (must not book after a decline).

**(d) Everything in one message — SC-46 (CRITICAL)**
User: **"ჩემი შვილი 14 წლისაა ეკრანისგან დისტანცია მჭირდება {DATE} 15:00 საათზე
ჩამიწერე სახელია ნინო ნომერია 595000000"**
Good: book directly and confirm — must **NOT re-ask** age / name / phone (all four
facts are present in one turn). This is the hardest "smart extraction" case.

**(e) Anti-invention handoff (the load-bearing exact form)**
When asked an unverified operational detail (exact remaining seats, room layout,
transport pickup point, daily schedule, menu):
Good (exact): **"რაც შეეხება [თემას], ამ დეტალებს მენეჯერი გაგაცნობთ : 558 67 47 33"**
— note the **hair-space before the colon**, the verb "გაგაცნობთ" (not
"დაგიზუსტებთ"), no emoji, no follow-up age question, no CTA appended.

**(f) The approved first-message intro (exact brand opener)**
Good (verbatim): **"სიტყვის აკადემიის ბანაკი 7-დღიანი გამოცდილებაა, სადაც ბავშვები
ისვენებენ და, ამავდროულად, სწავლობენ საკუთარი აზრებისა და ემოციების გამოხატვას.\n\n
რამდენი წლის არის თქვენი შვილი?"** — value in one line, then age, no facts, no price.

---

## 5. VOICE METHODOLOGY vs. BUG-FIX BAND-AIDS (durable vs. incidental)

`system_parent_v2.md` is **473 lines**; roughly **30 dated "CRITICAL" / "Live QA
Patch" blocks** and **~60+ literal forbidden-phrase rewrites** were each added to
kill ONE live LLM misfire (documented across the CLAUDE.md "RESOLVED" log). The
**durable methodology** is small and stable (owner's `sales_agent_prompt.md` +
`parent_sales_policy.md` §§1–12 + `system_base.md` voice); it is **already
distilled** in `parent_lean.md` (the Phase-4 lean prompt), which proves the durable
core fits in ~140 lines. Everything in the giant prompt beyond that lean core is
incident-specific defense (colloquial-time parsing, name/phone extraction edge
cases, ADULT↔PARENT leakage, slot-mismatch, verification-phrase guards, ~60
grammar/wording rewrites).

Notable owner-vs-live drift (methodology, not bug): the **owner's STEP 4 asks the
blunt "თქვენ ყველაზე მეტად რა გაწუხებთ?"** (what worries you most); the live prompt
**forbids "რა გაწუხებთ"** and replaces it with an open, non-pressuring
"რას ელოდებით ბანაკისგან / რისი მიღება გსურთ თქვენი შვილისთვის" — the business's
voice evolved toward *softer discovery*. Any rebuild should follow the live/refined
version, not the owner draft's literal wording.

---

## 6. THE SHARPEST TENSION FOR THE REBUILD

**The business has encoded "what good looks like" as exact scripted strings plus a
forbidden-phrase blocklist, and the entire regression harness (9-conversation corpus
+ 74 scenarios) enforces those literals — but a free-reasoning (openclaw-like)
agent's core strength is generating fresh, context-fit wording. Free reasoning will
paraphrase, and paraphrase is exactly what this codebase classifies as a
regression.**

Concretely: much of the ground truth lives as **exact approved wording** — the
first-message intro verbatim, the 4-beat price-objection script, the manager-handoff
phrase "თუ გსურთ, დაგაკავშირებთ მენეჯერთან.", the anti-invention redirect with its
hair-space colon and "558 67 47 33", the payment-process answer, en-dash age
formatting, and 60+ "never say X, say Y" rewrites enforced by `forbidden_in` checks
and a deterministic sanitiser.

The rebuild must therefore **triage every scripted element into load-bearing vs.
incidental**:

- **LOAD-BEARING — must survive verbatim or via tool-grounding (these are correctness
  or the business's insisted-upon frame):**
  - Facts & anti-invention: the price digit, streams/dates/location only from
    `get_camp_info`, manager phone `558 67 47 33` + the exact redirect form, never
    confirming a booking without backend `success=true`, never inventing a
    registration link.
  - The sales **sequence**: value → age → motivation → value → price → soft CTA;
    age-first; price-only-when-asked; ineligible-age never offered a booking;
    stop-on-decline.
  - The price-objection **structure** (empathy → value → 6-month split via
    TBC/საქართველოს ბანკი → soft CTA) and the sibling-discount trigger rule.
  - Georgian grammar, the no-emoji rule, and warm-through-text tone.

- **INCIDENTAL — preserve only the *intent*, let the model re-derive the wording:**
  - The ~30 dated CRITICAL blocks and ~60 literal phrase rewrites — each patched a
    specific old-model misfire. A model that genuinely reasons about natural, warm,
    polite ("თქვენ", locative forms) Georgian would not emit most of them; forcing it
    to memorise them recreates the brittle template the rebuild is trying to escape.
  - Exact closings and the verbatim intro: the business wants a *consistent brand
    voice*, but any single string is one valid realization, not the only one — the
    danger is that whoever validates the rebuild grades any deviation from the exact
    string as a failure.

**If the rebuild preserves every literal, it re-creates the memorised template it is
replacing; if it preserves none, it regresses the exact price-objection framing and
manager-handoff wording the business explicitly insists on.** Resolving this — deciding,
phrase by phrase, which strings are load-bearing facts/sequence/frame vs. incidental
voice band-aids, and re-basing the regression harness accordingly (fewer literal
`forbidden_in` string checks, more assertions on facts/sequence/tool-decisions) — is
the single central problem the rebuild must solve.
