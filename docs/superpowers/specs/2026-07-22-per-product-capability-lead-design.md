# Capability #2 — Per-Product Function + Lead — Design Spec (for approval)

**Date:** 2026-07-22 · **Status:** DESIGN, awaiting operator approval before a plan is written. Prepared autonomously to gain time; **not executed** — this is a bigger architectural change than Capability #1 and must be green-lit and executed supervised.
**Grounds:** `docs/PHASE3_SURVEY_D_product_model_2026_07_22.md` (the seam map), `docs/PHASE3_KNOWLEDGE_LANDSCAPE_2026_07_22.md` §3.

---

## 1. Goal (operator's own words)

> "every sellable product should have its own function AND lead — like camp worked, but it depends on the product … whatever I add in the admin panel must be sold correctly."

Today a NEW admin-added product (a non-reserved "dynamic program") can be **answered** (info) but gets **zero lead capture, no booking/reservation action, no manager-handoff binding, no follow-up** — until an engineer hand-writes a fourth bespoke path. This capability closes that gap: a product declares its capabilities in data, and the agent captures a lead for it via ONE generic, config-driven path.

## 2. Grounding — the exact gap and the three seams (Survey D, verified)

- **`type` is decorative; capability is keyed on the reserved `id`.** `PROGRAM_REGISTRY` (`app/domain/decision/`) hard-raises unless exactly the 3 reserved ids exist, so a 4th product is structurally unrepresentable in the domain layer. **This is the first thing that must change** (stop hard-validating "exactly these three").
- **Capability matrix today:** camp = info + Calendar booking + Leads-tab lead + handoff + follow-up; sunday_school = info + email handoff + SS-tab lead; adult_events = info + subscription + events-tab lead; **new dynamic product = info only, zero lead.**
- **Three seams (where a per-product-type capability system attaches):**
  1. **Tool dispatch + reserved-id gate** — `parent_tool_executor.execute` / `_HARDCODED_PROGRAM_IDS` / `build_active_tools`: replace `if id == "summer_camp"` branching with a product-type → capability-set table (info | booking | reservation-link | lead | handoff).
  2. **Lead-store router** — three hardcoded parallel Sheets tabs (`sheets_service.create_lead` / `log_sunday_school_lead` / `save_event_subscriber`) generalise to ONE `save_program_lead(program, lead)` routed by the product's declared `lead_type`.
  3. **Action/handoff binding** — the Calendar/FreeBusy transport and `send_manager_notification` core are ALREADY product-agnostic; parameterise them by the product's declared action type instead of the reserved id.
- **Natural home:** `app/domain/decision/program_registry.py` (a "fully-tested but UNWIRED generic-program foundation" per project memory) — once it no longer hard-validates exactly three ids.

## 3. Scope for THIS capability (deliberately narrow)

Do the **lead-capture** seam first (seam 2 + the minimum of seam 1 to reach it). Booking/reservation actions and handoff binding (seam 3) are a LATER capability — booking especially is the guardrail zone (money/commitment) and must not be rushed.

**In scope:** a NEW admin-added product can capture a lead (name + phone + which-product-interest) via a generic `save_program_lead` tool + a generic lead store, keyed by the product's `lead_type` field, with zero code change to add the Nth product.
**Out of scope (later):** generic booking/reservation actions; generic manager-handoff; follow-up for non-camp products; touching the 3 reserved products' existing lead paths.

## 4. Approaches

- **(A) Extend the domain registry (recommended).** Un-gate `program_registry.py` so any active product is representable; add a `lead_type` field to the section schema; a generic `save_program_lead(program_id, lead)` in `sheets_service` routes to the right store by `lead_type` (defaulting to a generic "ProgramLeads" tab for new products); a flag-gated `save_program_lead` tool the engine offers for dynamic-program turns. Reuses the existing dynamic-programs hoist (a dynamic-program turn already reaches the engine). **Cleanest, uses the built-but-unwired foundation, additive.**
- **(B) A 4th bespoke path per product.** What we do today, repeated. Rejected — it is exactly the hand-coding the operator wants to eliminate.
- **(C) Full capability-descriptor rewrite (all 3 seams at once).** Too big, touches the guardrail (booking) zone; rejected for now — seam 3 is a later capability.

## 5. Design (Approach A, additive + flag-gated)

- **Flag** `USE_PROGRAM_LEADS` (default OFF; byte-identical off; pinned in conftest).
- **Schema:** sections gain an optional `lead_type` (e.g. `generic` | `none`; the 3 reserved keep their existing bespoke stores). No change to reserved products.
- **Lead store:** `sheets_service.save_program_lead(program_id, lead)` → routes by `lead_type`; a new product with `lead_type: generic` writes to ONE new "ProgramLeads" tab (created on first write, mirroring the existing tab-creation pattern). Reserved ids keep their current tabs (untouched).
- **Tool:** `save_program_lead` in a flag-gated `LEAD_TOOLS` list (kept OUT of `PARENT_TOOLS`, mirroring `TOPIC_TOOLS`/`LEARNING_TOOLS`); executor handler validates name/phone (reuse `is_valid_person_name` + phone parse) and writes via the store; prompt suffix tells the model to capture a lead when a parent shows interest in a dynamic program.
- **Registry:** `program_registry.py` stops hard-raising on non-3 ids — an active admin product becomes representable. This is the load-bearing change; it needs its own careful review (it currently guarantees "exactly three", and something may depend on that).
- **Guardrail zone untouched:** no booking, no money, no PII beyond the existing name/phone capture already done for camp; the 3 reserved products' lead/booking/handoff paths byte-identical.

## 6. Risks / open questions (for approval)

- **R1 — the registry hard-validation exists for a reason.** Something may rely on "exactly three ids". Un-gating it is the highest-risk change; it needs its own byte-identity proof (flag off ⇒ registry behaves exactly as today) and a careful review. **This is the crux.**
- **R2 — a new "ProgramLeads" Sheets tab** is a real external write; must be flag-gated and stubbed in tests, and (like all sends) never fire in eval/offline.
- **OQ-a — does a new product even NEED booking, or is lead-capture + manager-handoff enough for most?** If most new products are "capture interest → manager follows up", seam 2 alone delivers most of the value and seam 3 (booking) can wait indefinitely.
- **OQ-b — is a single generic "ProgramLeads" tab acceptable to the operator, or does each product need its own tab?** One tab with a product-id column is simpler and scales; per-product tabs match the current pattern but need UI.
- **R3 — this touches the domain layer, not just an additive tool** (unlike Capability #1). Higher blast radius; must be executed supervised, subagent-driven, with a whole-branch review.

## 7. Why this was prepared but NOT executed

Capability #1 was a clean additive tool (low blast radius) — safe to build autonomously behind a flag. This capability changes the **domain registry's core invariant** (R1) and adds an **external write path** (R2). Executing that unsupervised, on top of a first capability not yet human-reviewed, is the wrong risk (the project's history warns against rushing). So the design + grounding — the hard part — is done and ready; **execution awaits your approval and runs supervised.**

**Next step on approval:** resolve OQ-a/OQ-b, then a plan (`writing-plans`) for seam 2 + minimal seam 1, executed subagent-driven with a registry-focused whole-branch review.
