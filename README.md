# AI Sales Agent — სიტყვის აკადემია

A production conversational agent that handles inbound sales on **Facebook Messenger and
Instagram** for a Georgian education business: it answers questions about programs, books
consultations into a real calendar, writes leads to a CRM, notifies a human manager, and
follows up on conversations that go quiet.

It has been running against real customers, in Georgian, and it is maintained the way a
system that can quote prices on a company's behalf has to be maintained.

---

## Why this is harder than a chatbot

An agent that talks to customers on a company's public page can commit that company to
things. It quotes prices, promises availability, books time in a shared calendar, and speaks
in the brand's voice to someone who may never have spoken to a human there.

That constraint drove almost every design decision in this repository:

- **Bounded autonomy.** Business-critical paths — booking, registration links, manager
  contact, eligibility — run through deterministic handlers with explicit state guards. The
  model composes language; it does not decide policy.
- **No invented facts.** Program dates, prices, age bands, manager contact and registration
  links are read from canonical config helpers at request time. The model is given facts
  rather than trusted to remember them.
- **Everything user-facing is testable.** ~5,500 automated tests, a scenario corpus, property
  tests, transcript replays, and an offline/LLM eval harness.

And the principle the project actually runs on, written into its own docs:

> **Green tests do not certify live behaviour.**

That line was earned. On one release the CRITICAL scenario gate passed 22/22 while live
behaviour had regressed after a hardening change. Finding that gap was the real work.

---

## Architecture

```
Facebook Messenger / Instagram  (webhooks: DMs + comments)
        │
        ▼
FastAPI  ──────────────────────────────────────────────┐
        │                                              │
        ├─ turn intent analysis (deterministic)         │
        ├─ deterministic handlers                       │  Admin panel
        │    booking · registration · manager handoff   │  (Jinja2)
        │    eligibility · state recall · off-topic      │  programs, streams,
        │                                                │  prices, availability
        ├─ LLM engine  (OpenAI / Anthropic, switchable)  │        │
        │    per-turn context: live facts, business      │        ▼
        │    hours, slot length, reply medium            │  sections.yaml
        │                                                │  (canonical config)
        ▼                                                │
  Tool layer ──────────────────────────────────────────┘
        │
        ├─ Google Calendar   book / reschedule / free-slot search
        ├─ Google Sheets     lead rows (CRM)
        ├─ Twilio WhatsApp   manager notification + handoff
        ├─ Redis             conversation + booking state
        └─ APScheduler       staged follow-up for idle leads
```

Deployed on Railway. Operator-editable program config lives on a mounted volume, so the
business can change programs, dates and availability without a deploy.

---

## Engineering decisions worth explaining

**Policy in code, tone in the model.**
Prompt instructions are a suggestion; a handler is a control. Anything that can create an
obligation — a booking, a price, an eligibility answer — is decided deterministically and
only *phrased* by the model.

**Facts travel with the turn.**
Business hours, slot length, valid dates and the reply medium are injected into per-turn
context from the same services the executor enforces, so what the agent says and what the
backend will accept cannot drift apart. This came from a live failure: the prompt stated
business hours twice, 15% into a 52k-character document, and the model announced hours that
appear nowhere in the repository.

**Never fix a bug by adding a prohibition.**
A binding operator rule in this project. Adding a banned phrase or a new special-case path
reliably turned one bug into several. Fixes are deletions, symmetry restorations, or
supplying a fact the model was missing.

**Examples must be relative, not literal.**
`"27 მაისს"` appeared nine times in a prompt and became its most-repeated string; the model
copied it into a tool call and the executor rejected it as a past date. Examples are now
relative (`"ხვალ"`) and resolved by the backend, so a copied example degrades into a valid
future date. A test fails if any literal month-and-day returns to a live prompt.

**One canonical source per fact.**
Camp dates, age bands, manager phone and post-booking facts were each read from several
places. They now resolve through single canonical helpers, with a test suite that fails if a
live path reads the legacy YAML directly.

**A provider-switch bug that only existed on one vendor.**
Anthropic requires alternating roles, so consecutive same-role turns are merged. The merge
concatenated content blocks, and two adjacent text blocks read contiguously — silently
deleting the turn boundary:

```
"კი" + "კი"                       ->  "კიკი"
"name" + "phone" + "age"          ->  "namephoneage"
```

One defect produced three unrelated-looking live symptoms: confirmations misread as name
changes, bookings that never completed, and the agent re-asking for details the user had
already given. Adjacent text blocks are now joined with a newline; non-text blocks are left
untouched.

---

## Testing and evaluation

| Layer | What it covers |
|---|---|
| `pytest tests/` | ~5,500 tests — handlers, state machine, extraction, tools, config |
| Scenario corpus | End-to-end conversations across segments |
| CRITICAL gate | 22 scenarios that must stay green before any release |
| Transcript replays | Real conversations replayed against the current build |
| Property / metamorphic | Invariants that must hold under input rewrites |
| Red-team batches | Adversarial input, prompt injection, off-topic, PII probing |
| Eval harness | Offline scoring, plus optional live-model and LLM-judge runs |

The test suite is deliberately hermetic and can never tell you where the live agent is —
that is correct, and it must stay that way. The tool that mirrors production is the eval
harness, which starts from live settings.

Two audit reports in `docs/` verify claimed behaviour against the actual implementation at
file-and-line level. Both surfaced places where documentation and code had drifted apart.

---

## Stack

`Python` · `FastAPI` · `OpenAI API` · `Anthropic API` · `Redis` · `Google Calendar API` ·
`Google Sheets API` · `Twilio` · `APScheduler` · `Jinja2` · `pytest` · `Railway`

---

## Notes

- The agent operates in **Georgian**. Prompt design, extraction and evaluation all had to
  work in a language most models handle less reliably than English.
- Operator configuration (active programs, dates, availability) lives outside the repository
  on a mounted volume, so some live program states cannot be reproduced from a clean clone.
- This repository is published as a portfolio reference. Business data, credentials and
  customer conversations are not included.

---

**Nikoloz Gobejishvili** — AI Engineer
[GitHub](https://github.com/nikolozGobejiShvili) ·
[LinkedIn](https://www.linkedin.com/in/nikoloz-gobejishvili-5323a9258/)
