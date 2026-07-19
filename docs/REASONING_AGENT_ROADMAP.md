# Reasoning-Agent Roadmap — openclaw-style (v2, critique-hardened)

**What this is:** the strategic roadmap to evolve the სიტყვის აკადემია sales agent from a *deterministic keyword-router with an LLM bolted on as a last resort* into a *reasoning agent that works like openclaw* — the LLM reasons first, calls tools as first-class primitives to ground every answer in operator-editable knowledge, consults skills packs for situational capability, and deterministic code is a thin guardrail. This is a ROADMAP (phase intent + exit criteria), not a task-by-task implementation plan — each phase gets its own detailed plan (via the writing-plans skill) when we start it.

**Rewritten per the elite critique** (C1 sequencing, C2 safety, H1 persistence, H2 metric, H3 priority, M1 latency, M2 interceptor risk, M3 prompt risk, S1 narrow-agent framing).

---

## North Star — how openclaw works, applied here

From the openclaw model (local-first AI assistant framework): **LLM reasons → tools are first-class → skills registry provides capability → session routing → thin guardrails.** Applied to THIS narrow, high-stakes, transactional sales agent (camp registration, real money, bookings):

> **Target = grounded + natural tone, with hard guardrails preserved wherever money or facts are at stake.**

This is NOT "remove all determinism." Per critique S1: a narrow transactional agent SHOULD stay constrained where it quotes prices, commits bookings, or captures contact/PII. "Reasoning" means the model *thinks and grounds* — it does not mean *fewer safety guardrails*.

| openclaw concept | this agent's target (which phase) |
|---|---|
| LLM reasons first | reasoning loop — **Phase 2** |
| tools first-class (not last resort) | interceptors → tools — **Phase 3** |
| skills registry | built (Phase 3 of prior work); enable + semantic — **Phase 5** |
| knowledge/config editable & live | persistence + hygiene — **Phase 0b / Phase 4** |
| session-based routing | existing PARENT/ADULT engines; polish optional — **Phase 5c** |

---

## Guiding principles (the critique, encoded)

1. **Eval-first (H2).** Build a behavioral eval (`--llm --judge`, extend the 90/100 `evals/baseline.json`) as the measurement + safety net BEFORE touching anything. It is the gate for every interceptor removal.
2. **Domain-by-domain (C1).** Never "all reasoning then all interceptors." Take ONE conversational domain at a time; thin its interceptors + add reasoning + prove via eval; then the next.
3. **Guardrail-safe (C2, S1).** Determinism STAYS in the money/fact zone (booking commit, price quote, contact/PII, fake-booking guard). Relax only in advisory/conversational zones.
4. **Persistence-first (H1).** Railway admin-config persistence is a separate, prerequisite infra decision — without it, everything data-driven is ephemeral and the whole premise fails.
5. **Ship before architect (H3).** The agent must WORK in production (live-bug fixed, one flag enabled and proven) before the big reasoning pivot.
6. **Additive, flag-gated, staged.** No rewrite. Every step behind a flag with instant rollback. Every interceptor removal reversible.
7. **Latency budget (M1).** The reasoning loop adds LLM calls; measure and cap added latency; use cheap/small calls for analyze + reflect.

---

## Phase 0 — Make it WORK and SEE it (no architecture change)

The agent isn't successfully enabled in production yet; fix that first.

- **0a — Live-bug fix.** The admin "new program" form defaults Status to `coming_soon` and `get_active_sections()` filters an exact `status == "active"` with no normalization → an admin-added program is invisible. Fix: normalize status (`.strip().casefold()`, sensible default) AND/OR default the form to `active`; add a boot-log line printing `USE_DYNAMIC_PROGRAMS` (today only `USE_PARENT_LLM_ENGINE` is logged — no signal the flag is live).
- **0b — Railway admin-config PERSISTENCE (separate infra decision, possibly the most important item in this whole roadmap).** Admin-panel edits write `data/admin_config/sections.yaml` to the container's ephemeral disk → wiped on every redeploy/restart. Decide + implement ONE: (i) a Railway persistent volume mounted at `data/admin_config/`; (ii) move admin config to Redis/Postgres; (iii) commit-back-to-git on save. Until this exists, dynamic-programs / skills / approved-answers are all ephemeral and the "operator edits data" model is broken on Railway.
- **0c — Enable + supervised staging smoke of `USE_DYNAMIC_PROGRAMS`** (already built + reviewed). Prove ONE flag delivers value live (an operator-added program is answered AND survives a redeploy). Runbook: `docs/ENABLEMENT_USE_DYNAMIC_PROGRAMS.md`.
- **Exit:** an operator-added program is answerable live and persists across a redeploy.

## Phase 1 — Measurement + safety net (the gate for everything after)

Nothing gets migrated without this.

- **1a — Behavioral eval suite.** Extend `evals/` beyond the current 51 cases to cover the domains Phase 3 will touch (objections, camp-topic concerns, program info, booking, contact). Run `--llm --judge`; record the baseline score + per-domain **naturalness** and **reliability/grounding** sub-scores.
- **1b — Telemetry.** Add a "% turns intercepted vs reached-the-LLM" metric and a transcript-naturalness rubric, so we can see the balance shift as interceptors thin.
- **Exit:** a repeatable behavioral score + per-domain metrics we can regress against. This is the safety net (answers C2/H2).

## Phase 2 — Reasoning core (openclaw's "reason first"), flag-gated

- **2a — Implement `analyze → ground → answer → reflect`** inside `run_parent_llm_turn`, gated `USE_REASONING_LAYER` (the documented-but-unimplemented `docs/REASONING_LAYER_BRIEF.md` vision, superseding today's deterministic Phase-1 classifier). ANALYZE = cheap small-model strict-JSON (goal, sentiment, needed_facts, missing_lead_fields, suggested_tool); GROUND = load only the needed knowledge; ANSWER = existing tool loop with the plan injected; REFLECT = verify the final answer against grounded facts.
- **2b — Make REFLECT robust (M1/C2).** Not regex-only — a grounded-fact check plus a cheap LLM self-check specifically on money/fact claims (price, availability, booking). Cap tool iterations; measure added latency vs the Phase-1 budget.
- **Exit:** flag-on, the engine reasons before answering; eval shows no regression + better naturalness on engine-reached turns; latency within budget.

## Phase 3 — Domain-by-domain rebalancing (the hard part, done safely)

Per critique C1/M2: interleave interceptor-thinning WITH reasoning, one domain at a time, gated by the Phase-1 eval. NEVER a big-bang interceptor deletion.

**The per-domain loop (repeat for each low-stakes domain first):**
1. Pick ONE domain (start with **advisory/low-stakes**: objection-handling, then camp-topic concerns, then program info).
2. Convert its deterministic interceptor(s) → a TOOL the reasoning loop calls (e.g. `get_camp_topic(topic)`), so the LLM decides *when* to consult knowledge instead of Python substring-matching on its behalf.
3. Move that domain's knowledge into an operator-editable file the tool reads.
4. Gate the migration behind a flag.
5. Prove via the Phase-1 eval that the tool-path **matches or beats** the interceptor on that domain's cases.
6. Only THEN retire/soften the interceptor.

- **Money/fact GUARDRAIL zone stays deterministic** (booking commit, price quote, contact/PII capture, fake-booking guard, ineligible-age refusal). Explicitly OUT of scope for relaxation (C2/S1). These interceptors are features, not bugs.
- **Exit per domain:** interceptor thinned, knowledge tool-grounded, eval green, guardrail zone untouched.

## Phase 4 — Knowledge & prompt hygiene

- **4a — Dead-file triage (M3).** For each dead file (`audience_segments.yaml`, `adult_defaults.yaml`, `followup_strategy.yaml` bodies, `knowledge_base.txt`, `events.txt`, both `*_sales_policy.md`, `company.yaml` divergence): DELETE if superseded, WIRE only if it adds value — decide each explicitly. Fix hardcoded-vs-YAML divergences (`COMPANY_NAME`, manager-phone, adult_defaults placeholders). Goal: no dead file creating false "we configured it" confidence.
- **4b — Slim `system_parent_v2.md` (122KB) carefully.** Every rule removal gated by the Phase-1 eval. Move FACT-rules into tool results; keep only tone/process in the prompt. Never bulk-delete (each rule fixed a live bug).
- **Exit:** smaller prompt; every knowledge source either live or deleted.

## Phase 5 — Capabilities & skills (openclaw's skills-registry + tools-first), LAST

- **5a — Enable `USE_SKILLS` + `USE_LEARNING`** after staging smokes — now meaningful because reasoning-first + tools-first make them actually consulted (they were inert before because the LLM was the last resort).
- **5b — Semantic selection.** Upgrade skills + approved-answers matching from substring → embeddings (closes the "adaptive ceiling" from the prior critique). THIS is openclaw's skills-registry realized properly — the operator authors capability packs, the agent semantically matches them.
- **5c — (Optional) session-routing polish** (openclaw concept) if PARENT/ADULT routing needs it.
- **Exit:** operator-authored skills + learned answers genuinely steer a reasoning agent.

---

## Success metric (H2)

The Phase-1 behavioral eval score (naturalness + reliability + grounding) **improves domain-by-domain**, with **ZERO regression in the money/fact guardrail zone**. If a domain migration doesn't beat its interceptor on the eval, the interceptor stays. "Botlike" is measured as: % of turns reaching the reasoning loop (up) + judged naturalness (up) + grounding/reliability (held or up).

## What this roadmap deliberately does NOT do

- No big-bang rewrite; no bulk interceptor/sanitizer deletion.
- No relaxation of money/fact guardrails.
- No architecture pivot before Phase 0 (ship + persistence) succeeds.
- No enabling of unproven capabilities before the eval safety net (Phase 1) exists.

## Immediate next step

**Phase 0a (live-bug fix) + 0b decision (persistence).** These are concrete and unblock everything. Phase 0a is a small, safe, flag-independent fix; Phase 0b is an infra decision you (operator) must make. Everything after Phase 0 is gated on Phase 1's eval existing.
