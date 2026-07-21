# Phase 3 — Knowledge Landscape (synthesis of surveys A–D)

**Date:** 2026-07-22 · **Inputs:** `PHASE3_SURVEY_A_knowledge_facts` · `_B_sales_voice` · `_C_followup_lifecycle` · `_D_product_model` (this session, read-only) · `PHASE3_0_INTERCEPTOR_INVENTORY` (T1/T3)
**Purpose:** ground the Phase 3.0 plan in what the project's knowledge/content actually IS, so the openclaw-like agent is fitted to it — not planned in the abstract.

---

## 1. The one finding that reshapes the plan

**The single largest body of customer-facing product knowledge is invisible to the model.**

`app/agent/knowledge/camp_topic_facts.yaml` — safety, food, gadgets/screens, medical, daily schedule, parent-communication, overview — is delivered by a **deterministic pre-LLM interceptor** (`parent_flow._maybe_handle_camp_topic_facts`, `parent_flow.py:1567`) that substring-matches the question and returns canned YAML text, **short-circuiting the engine.** The model never sees this knowledge and cannot reason over it (Survey A).

These are precisely the topics a parent most asks about a child going to a camp. So the "botlike" complaint — *varied questions get wrong/static answers* — is, in large part, **this one interceptor**: a differently-phrased safety question either hits the wrong canned fact or misses. This is not a guess; it is the biggest advisory knowledge asset (A), it is an ADVISORY-bucket interceptor (T3 — invertible), and it is provably short-circuited (A).

**Implication:** the natural first target of the polarity inversion is *topic-facts-as-a-tool* — the model calls `get_program_topic(topic)` and reasons over the returned facts, instead of Python substring-matching on its behalf. And because a generic topic-facts tool is **product-agnostic**, it directly serves the operator's OQ1 goal: any product's topic knowledge (Sunday-School safety, an event's details) becomes answerable the same way.

**Open sequencing question (do NOT pre-decide — for the plan):** `camp_topic_facts` is the richest, best-understood body and the cleanest demonstration of the mechanism, **but it is a dead-season product** (camp ended 2026-07-20). Proving the mechanism on it optimises an off-season offering; proving it on a live product (Sunday School / adult events / a dynamic product) tests thinner knowledge. The plan must choose: demonstrate on the richest knowledge, or validate on a live product first. Flagged, not resolved.

---

## 2. Knowledge inventory — LIVE / FALLBACK / DEAD (Survey A, grep-verified)

| Bucket | Files |
|---|---|
| **LIVE (4)** | `data/admin_config/sections.yaml` (the operator's live product data) · `camp_topic_facts.yaml` (biggest advisory body, but interceptor-delivered) · `business_hours.yaml` · `templates.yaml` (DM / follow-up wording, operator-editable) |
| **FALLBACK-ONLY (3)** | `camp_2026.yaml` (parallel copy of structured facts behind `sections.yaml`) · admin `business_hours.yaml` mirror · `manager_contacts.yaml` |
| **DEAD (7)** | `company.yaml` · `adult_defaults.yaml` · `audience_segments.yaml` · `knowledge_base.txt` · `events.txt` · `parent_sales_policy.md` · `adult_sales_policy.md` |

All four "dead-file" allegations from the prior audit are **confirmed by caller-grep** (hardcoded-in-Python or zero callers). Details + line numbers in Survey A.

**Two consequences for an "operator edits data → no code change" product:**
1. **Dead config is an active hazard.** If the operator (or we) "configure" `audience_segments` / `followup_strategy` / a `*_sales_policy.md`, **nothing changes** — the files look live and are not. False confidence is worse than an empty file. (Roadmap Phase 4a — dead-file triage — matters more now that the whole premise is data-driven.)
2. **Fact duplication = grounding risk.** The manager phone lives in 3 places (`sections.yaml` `manager_contact`, `camp_2026.yaml`, `company.yaml`); camp facts live in 2 (`sections.yaml` + the parallel `camp_2026.yaml`). An agent whose selling point is *"facts from the backend"* must be grounded on ONE canonical source, or it can quote a stale copy. Canonicalisation is a rebuild prerequisite, not a nicety.

---

## 3. The product/offering model — the generalisation gap (Survey D)

- A product is a "section" in `sections.yaml` with a rich field set, but **`type` is decorative** — capability is keyed on the reserved **id**. `PROGRAM_REGISTRY` (`app/domain/decision/`) **hard-raises unless exactly the 3 reserved ids exist**, so a 4th product is structurally unrepresentable in the domain layer.
- Capability matrix (today):

| Capability | summer_camp | sunday_school | adult_events | **new dynamic product** |
|---|---|---|---|---|
| info-answering | ✅ curated | ✅ deterministic | ✅ ADULT tools | ✅ generic tool |
| booking/reservation | ✅ Calendar | ✕ (email) | ✕ (external URL) | **✕** |
| lead capture | ✅ Leads tab | ✅ SS tab | ✅ subscriber tab | **✕ none** |
| manager handoff | ✅ | ✅ email-only | ✅ | shared generic only |
| follow-up cadence | ✅ | partial | ✕ | **✕** |
| dedicated tools | 8 | deterministic | 6 | 2 read-only |

- **A new admin product gets info-answering only — zero lead capture** — until an engineer hand-writes a fourth bespoke path. That is the exact gap behind "every sellable product should have its own function AND lead."
- **Three seams** where a per-product-type capability system attaches (D): (1) tool dispatch + the reserved-id gate; (2) the lead-store router (`create_lead` / `log_sunday_school_lead` / `save_event_subscriber` → one `save_program_lead(program, lead)`); (3) action/handoff binding (the Calendar/FreeBusy transport and `send_manager_notification` core are already product-agnostic — parameterise by declared action type). Natural home: `program_registry.py`, once it stops hard-validating exactly three ids.

---

## 4. Sales voice & "what good looks like" (Survey B)

- **Persona:** სიტყვის აკადემიის consultant, explicitly *not a FAQ bot* — 70% intellectual/emotional depth, 20% warmth, 10% expertise; Georgian only, 1–3 sentences, no emojis. North star: the parent should feel *"a person who truly understands my child."*
- **Durable methodology (8 steps):** value-open → age-first branch → discover motivation → value-before-price → price only when asked (value-framed: digit + inclusions + 6-month TBC/საქართველოს ბანკი split + discount) → soft CTA → respect decline / mark "will think" → never invent, route unknowns to the manager.
- **Ground-truth examples exist:** 9 real-bug corpus conversations (`tests/corpus/`) + 3 real-client transcripts (SC-TX-01/02/03) + 71 scenarios spanning real phrasings (`tools/scenario_library.py`).
- **The central tension (B, independently matching the operator's OQ2 answer):** "good" is currently encoded as **exact scripted strings + a forbidden-phrase blocklist**, and the whole harness enforces those literals — but a reasoning agent paraphrases, which the codebase scores as regression. The rebuild must triage each scripted element into **load-bearing** (facts/anti-invention; the value→age→motivation→price→CTA sequence; the price-objection 4-beat with the payment split; manager-handoff wording + "558 67 47 33"; grammar/no-emoji) vs **incidental** (~30 dated CRITICAL band-aids whose *intent* a reasoning model re-derives), **and re-base the harness from literal-string checks to facts / sequence / tool-decision assertions.** This is exactly Phase 3.0-T2/T4.
- `parent_lean.md` already proves the durable core fits in ~140 lines (vs 473). Follow the refined live prompt, not the owner's blunter draft.

---

## 5. Nurture & lifecycle (Survey C)

- **LIVE:** the follow-up scheduler mechanics (hourly tick, PARENT-only, blocked-reason gating, stage advance, Redis write-through) with bodies from operator-editable `templates.yaml`.
- **DEAD:** `followup_strategy.yaml` (cadence hardcoded in Python; `scenario_followups` never read) and `audience_segments.yaml` (zero callers). No live persona-based personalisation beyond the coarse PARENT/ADULT/UNCLEAR router.
- **Lead lifecycle:** `followup_stage` `"" → first_24h → second_3d → third_7d`, gated by `followup_blocked_reason`, with per-product completion signals (`calendly_booked`, `adult_subscription_status`) rather than one unified machine.
- **Biggest gap:** no generic, data-driven lead-capture dispatch keyed off a product `type`. Same conclusion as §3 from the nurture side.

---

## 6. What this changes in the Phase 3 plan

1. **Phase 3.2's first-domain candidate is now data-identified, not guessed:** *topic-facts-as-a-tool* (`camp_topic_facts` → generic `get_program_topic`). It is the biggest advisory body, provably short-circuited, and product-agnostic. Subject to the §1 dead-season sequencing decision.
2. **Phase 3.0-T2/T4 (eval rebuild + metric) is confirmed as the crux, and its shape is now concrete:** re-base the harness from literal-string assertions to *facts-grounding + sequence + tool-decision* assertions; ground truth = product facts, not hand-written answers (matches the operator's OQ2). Multi-turn (T1 lesson) and multi-product (OQ1).
3. **Canonicalise fact sources before grounding the model on them** (§2.2) — one owner per fact; retire or clearly demote the parallel copies. Fold the dead-file triage (§2.1) in, because a data-driven product cannot ship live-looking dead config.
4. **The "every product its own function + lead" work (§3) is well-defined and seam-located** — a Phase 3.2/3.3 capability-descriptor on `program_registry.py`, not a rewrite. Out of scope for 3.0.
5. **Nurture generalisation (§5) is greenfield** beyond PARENT camp — defer to Phase 5, but note it shares the §3 lead-store seam.

Nothing here changes the architecture decision (polarity inversion) or the guardrail zone. It sharpens *what to invert first*, *what "correct" means*, and *what must be canonicalised first*.
