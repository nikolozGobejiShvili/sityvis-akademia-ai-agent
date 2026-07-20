# Phase 1 — Behavioral Eval Safety Net (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the MEASUREMENT + SAFETY NET that gates every later reasoning-agent phase — cheaply and repeatably. Two layers: (A) a **free, deterministic, offline** signal we can run on every change — the interception rate (% of turns short-circuited by a `_maybe_*` interceptor before the LLM) + a canned/sanitizer footprint count; and (B) a **paid, operator-gated, noise-controlled** naturalness judge for the nuanced "botlike vs human consultant" read. Success is defined so that **reliability in the money/fact zone is a HARD constraint** and naturalness is maximized only subject to it.

**Architecture:** Purely additive to `evals/` (READ-ONLY harness). No agent behavior changes — it only observes. Layer A leans on the EXISTING `conversation_trace` (`_trace.set(answered_by=...)` already recorded at several routing points) and counts existing canned/sanitizer constants — deterministic, no API. Layer B mirrors the existing `judge.py` Claude judge but runs it at temperature 0 with an N-run majority to control stochasticity. Measured on BOTH synthetic cases AND the real `tests/corpus/` conversation corpus. The existing `evals/baseline.json` (90/100) is left UNTOUCHED — new metrics live in a separate report/field.

**Tech Stack:** Python 3.10, existing `evals/` + `conversation_trace`, pytest. Layer B judge needs `ANTHROPIC_API_KEY` (operator-run). No new dependency.

## Global Constraints

- **READ-ONLY, zero agent-behavior change.** Measurement only. No file under `app/` changes behavior. The existing agent suite (~5015 passing) stays green.
- **Layer A is FREE + DETERMINISTIC + in-CI.** The interception rate + canned-footprint metrics use no API and are byte-stable across runs — this is the gate we can run on every commit. Layer B (judge) is the paid, occasional, operator-triggered supplement.
- **The existing `evals/baseline.json` (90/100) is NOT overwritten (fix H1).** It is the pre-existing decision-quality reference. Phase-1 metrics are written to a SEPARATE artifact (`evals/phase1_baseline.json`) so the original reference is never lost. The offline free eval must still leave `evals/baseline.json` byte-identical.
- **% reaching-LLM is DIAGNOSTIC, not a success target (fix C2).** It describes the architectural balance (how much the LLM actually reasons); it is NOT rewarded on its own. Success = reliability (hard) + naturalness (soft, constrained). A change that raises %-reaching-LLM but doesn't improve naturalness is neutral, not a win.
- **Naturalness is a CONSTRAINED objective, not a raw maximization (fix S1).** The target is: *maximize naturalness on ADVISORY turns SUBJECT TO reliability = 100% on the money/fact guardrail turns (booking, price, contact/PII, fake-booking, ineligible-age).* Guardrail turns are scored on reliability ONLY; naturalness is never rewarded there at the cost of correctness.
- **Judge stochasticity is controlled (fix C1).** The naturalness judge runs at `temperature=0` and takes the majority/median of N=3 runs per case; a single-run score is never the gate. When the judge/key is unavailable, naturalness is `None` (skip), never a fake 0.
- **Measured on REAL transcripts too (fix H2).** Layer A runs over the `tests/corpus/` conversation corpus (real captured conversations), not only synthetic cases, so the interception picture reflects real user phrasing.
- **Instrument leans on existing trace, minimal monkeypatch (fix H3).** Prefer reading `conversation_trace`'s `answered_by`; only add lightweight instrumentation where the trace doesn't already record the handler. Do not hard-couple to the ~40-handler internal order of `parent_flow._handle_core`.
- **Interpreter:** `.venv/Scripts/python.exe`. **LOCAL-only** branch `feat/dynamic-programs`; touches only `evals/` + new modules → deploy-inert, but push only with explicit consent. **No haiku.**

---

## File Structure

**Create:**
- `evals/interception.py` — Layer A: `answered_by(...)` (read-only, trace-based) + `interception_rate(samples)` aggregator.
- `evals/botlike_proxy.py` — Layer A: `canned_footprint(response)` (counts sanitizer/canned markers in a reply) + `botlike_proxy_score(samples)` — a FREE deterministic proxy for "how templated is the output."
- `evals/naturalness.py` — Layer B: `grade_naturalness(context, response, *, runs=3)` (temp-0, N-run majority, judge-gated).
- `tests/test_phase1_eval_metrics.py` — offline tests (instrument + proxy are deterministic; judge is mocked).

**Modify:**
- `evals/cases.py` — add + TAG per-domain cases; also tag a sample of EXISTING cases with `domain` (fix M1) so per-domain aggregation isn't only the new ones.
- `evals/harness.py` — wire Layer A (always) + Layer B (judge-gated) into the report; write Phase-1 metrics to `evals/phase1_baseline.json` (NOT `baseline.json`).
- `evals/run_evals.py` + `evals/README.md` — document the two layers, the diagnostic-vs-target distinction, and the constrained-naturalness gate rule.

---

## Task 1: Layer A — interception rate (free, trace-based, on synthetic + corpus)

**Files:** Create `evals/interception.py`; Test `tests/test_phase1_eval_metrics.py`.

**Interfaces:**
- `answered_by(conversation, message: str) -> dict` → `{"handler": <name|"engine">, "reached_llm": bool}`. Reuses the harness READ-ONLY guard (Calendar/Sheets/DM/OpenAI intercepted). Reads `conversation_trace`'s `answered_by` after a `parent_flow.handle` turn; falls back to `"engine"` when the trace shows the engine answered. Minimal added instrumentation only where the trace lacks a handler name.
- `answered_by_message(message: str) -> dict` — convenience wrapper (fresh PARENT conversation).
- `interception_rate(samples: list[dict]) -> dict` → `{"intercepted": n, "reached_llm": m, "pct_reached_llm": float, "by_handler": {name: count}}`.

- [ ] **Step 1: Study the READ-ONLY guard** (`evals/harness.py` + `evals/safety.py`) and `conversation_trace` (`app/reasoning/conversation_trace.py` — `set(**kwargs)`, and confirm which routing points already record `answered_by=` — the audit found `conversation_service.py:622/656/1001` + `set_route_decision`). Document the exact interception + trace-read mechanism.

- [ ] **Step 2: Write the failing tests:**

```python
def test_answered_by_reports_interceptor_when_short_circuited():
    from evals import interception
    r = interception.answered_by_message("მენეჯერის ნომერი მინდა")
    assert r["reached_llm"] is False and r["handler"] != "engine"


def test_interception_rate_aggregates():
    from evals import interception
    s = [{"handler": "engine", "reached_llm": True},
         {"handler": "_maybe_handle_camp_intro", "reached_llm": False},
         {"handler": "engine", "reached_llm": True}]
    a = interception.interception_rate(s)
    assert a["reached_llm"] == 2 and a["intercepted"] == 1
    assert abs(a["pct_reached_llm"] - 2/3) < 1e-6
    assert a["by_handler"]["_maybe_handle_camp_intro"] == 1
```
> Pick a message a CURRENTLY-wired interceptor deterministically catches; the audit confirms `_maybe_handle_explicit_manager_request` catches "მენეჯერის ნომერი". Verify + document; swap if flaky.

- [ ] **Step 3: Run to verify fail** — `.venv/Scripts/python.exe -m pytest tests/test_phase1_eval_metrics.py -q` → FAIL.
- [ ] **Step 4: Implement** `evals/interception.py` (trace-based, READ-ONLY guard reused).
- [ ] **Step 5: Run to verify pass** — → PASS.
- [ ] **Step 6: Commit** — `git add evals/interception.py tests/test_phase1_eval_metrics.py` → `git commit -m "feat(evals): free trace-based interception-rate instrument (diagnostic)"`

---

## Task 2: Layer A — canned/botlike proxy (free, deterministic)

**Files:** Create `evals/botlike_proxy.py`; Test `tests/test_phase1_eval_metrics.py`.

**Interfaces:**
- `canned_footprint(response: str) -> dict` → `{"sanitizer_hits": int, "canned_menu": bool, "stock_phrase_hits": int, "footprint": int}` — counts, in a given reply, how many known canned/stock markers appear (the static welcome menu text, and a curated subset of the `FORBIDDEN_PHRASE_REPLACEMENTS` *targets* — the pre-approved phrasings the sanitizer converges output toward). HIGHER footprint = more templated. Pure, deterministic, no API.
- `botlike_proxy_score(responses: list[str]) -> dict` → `{"avg_footprint": float, "canned_menu_rate": float, "n": int}`.

> Rationale (fix C1/M2): this is the FREE, deterministic, run-on-every-commit signal. It is a PROXY (correlate of "botlike"), not the ground truth — the judge (Task 3) is the ground truth, run occasionally. Two independent signals reduce reliance on the noisy/paid judge.

- [ ] **Step 1: Identify the marker source.** Read `data/prompts.py`/`welcome.yaml` for the static menu text and `parent_llm_engine.FORBIDDEN_PHRASE_REPLACEMENTS` for the canonical stock-phrase TARGETS. Choose a stable, curated subset (document which — do NOT depend on the full 191-entry table changing).

- [ ] **Step 2: Write the failing tests:**

```python
def test_canned_footprint_flags_menu_and_stock():
    from evals import botlike_proxy
    fp = botlike_proxy.canned_footprint("ბანაკი თუ ზრდასრულთა ღონისძიება?")  # menu-like
    assert fp["footprint"] >= 1
    natural = botlike_proxy.canned_footprint("რა თქმა უნდა, სიამოვნებით მოგიყვებით — რა გაინტერესებთ ბანაკზე?")
    assert natural["footprint"] == 0


def test_botlike_proxy_score_aggregates():
    from evals import botlike_proxy
    s = botlike_proxy.botlike_proxy_score(["ბანაკი თუ ღონისძიება?", "სუფთა ბუნებრივი პასუხი"])
    assert 0.0 <= s["canned_menu_rate"] <= 1.0 and s["n"] == 2
```

- [ ] **Step 3: Run fail → Step 4: Implement → Step 5: Run pass.**
- [ ] **Step 6: Commit** — `git add evals/botlike_proxy.py tests/test_phase1_eval_metrics.py` → `git commit -m "feat(evals): deterministic canned-footprint proxy (free botlike signal)"`

---

## Task 3: Layer B — naturalness judge (paid, temp-0, N-run majority, gated)

**Files:** Create `evals/naturalness.py`; Modify `evals/harness.py`, `evals/run_evals.py`; Test `tests/test_phase1_eval_metrics.py`.

**Interfaces:**
- `grade_naturalness(context, response, *, runs=3) -> {"score": int 0-4 | None, "issues": [str], "runs": int}` — STRICT rubric via the existing `judge.py` client at `temperature=0`, N=3 runs, take the MEDIAN/majority (fix C1). `score=None` when judge unavailable (skip, not fake-0). Criteria: (a) human-consultant not template; (b) no canned-menu phrasing; (c) varied/context-fit wording; (d) warm consultative tone.
- Harness: naturalness graded ONLY on ADVISORY full-turn cases (never the guardrail domains — fix S1); report block avg + per-case issues.

- [ ] **Step 1: Study `evals/judge.py`** (`judge()`, `judge_available()`, grammar-grader's separate-rubric + retry-parse). Reuse its client; do NOT invent a new one. Confirm how to force `temperature=0`.
- [ ] **Step 2: Write the failing tests** (mock the judge → offline/free):

```python
def test_grade_naturalness_majority_of_runs(monkeypatch):
    from evals import naturalness
    calls = {"n": 0}
    def _one(ctx, resp):
        calls["n"] += 1
        return [("a", True, ""), ("b", True, ""), ("c", True, ""), ("d", False, "flat")]
    monkeypatch.setattr(naturalness, "_judge_naturalness_once", _one)
    monkeypatch.setattr(naturalness, "_judge_available", lambda: (True, ""))
    out = naturalness.grade_naturalness("ctx", "resp", runs=3)
    assert out["score"] == 3 and calls["n"] == 3


def test_grade_naturalness_unavailable_is_skip(monkeypatch):
    from evals import naturalness
    monkeypatch.setattr(naturalness, "_judge_available", lambda: (False, "no key"))
    assert naturalness.grade_naturalness("c", "r")["score"] is None
```

- [ ] **Step 3: Run fail → Step 4: Implement (temp-0, N-run median, skip-not-fail) → Step 5: Wire into harness (advisory-only, judge-gated) + document in run_evals → Step 6: Run pass.**
- [ ] **Step 7: Commit** — `git add evals/naturalness.py evals/harness.py evals/run_evals.py tests/test_phase1_eval_metrics.py` → `git commit -m "feat(evals): naturalness judge (temp-0, N-run, advisory-only, constrained)"`

---

## Task 4: Per-domain cases (new + tag existing) — the per-domain gate

**Files:** Modify `evals/cases.py`; Test `tests/test_phase1_eval_metrics.py`.

**Interfaces:** add a `domain` tag to cases; new cases for `objection`, `camp_topic`, `program_info`, plus GUARDRAIL domains `booking_reliability`, `contact_capture`. ALSO tag a representative sample of the EXISTING `CASES` with the matching domain (fix M1) so per-domain coverage isn't only the ~10 new ones.

- [ ] **Step 1: Study the existing case schema** (`cases.py:618` `CASES`; dataclass vs dict; how `category`/checks/full-turn-vs-deterministic are declared). Extend, don't replace.
- [ ] **Step 2: Write the smoke test:**

```python
def test_domain_coverage_present():
    from evals import cases
    doms = {getattr(c, "domain", None) if not isinstance(c, dict) else c.get("domain")
            for c in cases.CASES}
    for d in ("objection","camp_topic","program_info","booking_reliability","contact_capture"):
        assert d in doms
```

- [ ] **Step 3: Run fail → Step 4:** add ≥2 new cases/domain + tag existing ones. Advisory domains → naturalness+correctness; GUARDRAIL domains → reliability/grounding ONLY (no fake booking; admin price not hardcoded; no filler-word-as-name). **Step 5:** run pass + `.venv/Scripts/python.exe -m evals.run_evals` (offline) stays READ-ONLY-clean and does NOT modify `evals/baseline.json`.
- [ ] **Step 6: Commit** — `git add evals/cases.py tests/test_phase1_eval_metrics.py` → `git commit -m "feat(evals): per-domain tags + guardrail-vs-advisory coverage cases"`

---

## Task 5: Phase-1 baseline artifact + gate doc + verification (baseline.json UNTOUCHED)

**Files:** Modify `evals/harness.py` (write `evals/phase1_baseline.json`), `evals/README.md`.

- [ ] **Step 1: Separate artifact (fix H1).** The Phase-1 metrics (interception rate, canned footprint, naturalness, per-domain) are written to `evals/phase1_baseline.json` — the original `evals/baseline.json` (90/100) is NEVER overwritten by this phase.
- [ ] **Step 2: Document the gate** in `README.md`: (a) Layer A (free, in-CI) = interception rate [DIAGNOSTIC] + canned footprint; Layer B (paid, occasional) = naturalness. (b) **The gate rule:** a Phase 2–4 change MUST hold reliability = 100% on guardrail domains and MUST NOT lower any domain's correctness; it SHOULD lower canned footprint + raise naturalness on advisory domains; %-reaching-LLM is reported as diagnostic, not a pass/fail. (c) naturalness is constrained, not maximized (S1).
- [ ] **Step 3: Offline regression (free, in-CI):** `.venv/Scripts/python.exe -m pytest -q` → only the pre-existing `fast_track` fails. `.venv/Scripts/python.exe -m evals.run_evals` (offline) → READ-ONLY-clean, `evals/baseline.json` byte-identical. Record both. Also compute Layer-A metrics over `tests/corpus/` and record them in `phase1_baseline.json` (free).
- [ ] **Step 4: Permissioned full run (operator step — do NOT run without explicit permission; costs OpenAI + Anthropic).** `.venv/Scripts/python.exe -m evals.run_evals --llm --judge` → fills the naturalness numbers in `phase1_baseline.json`. Document the command as the pre-Phase-2 reference capture.
- [ ] **Step 5: Commit** — `git add evals/harness.py evals/README.md evals/phase1_baseline.json` → `git commit -m "docs(evals): phase-1 gate + separate phase1_baseline (baseline.json untouched)"`

---

## Phase 1 Definition of Done

The harness now has: (Layer A, FREE + deterministic + in-CI) an **interception rate** (diagnostic: % of turns reaching the LLM, over synthetic AND real `tests/corpus/` transcripts) + a **canned footprint** proxy; (Layer B, paid + occasional + operator-gated) a **naturalness** judge run at temp-0 with N-run majority, scored on advisory turns only. Per-domain correctness/reliability across the five Phase-3 domains, guardrail domains scored on reliability only. Metrics are recorded in a NEW `evals/phase1_baseline.json`; the original `evals/baseline.json` (90/100) is untouched. No agent behavior changed. The gate for Phases 2–4: reliability=100% on guardrails is a HARD constraint; naturalness↑ + footprint↓ on advisory domains is the objective; %-reaching-LLM is diagnostic only.

**Explicitly NOT done here:** no agent change (Phases 2–3); the model-tier question (gpt-4.1-mini vs stronger) is left open, but Layer A (free) + Layer B (paid) now give the naturalness+reliability data to decide, before Phase 2, whether the ceiling is architecture or model.

## Self-Review / Critique → Fix

| v1 finding | Sev | Fixed in v2 |
|---|---|---|
| **C1 — judge noisy + paid → weak gate** | 🔴 | Layer A free/deterministic proxy (Task 1-2) is the in-CI gate; judge (Task 3) is temp-0 + N-run median, occasional/gated. |
| **C2 — %-reaching-LLM wrongly used as success** | 🔴 | Reclassified as DIAGNOSTIC (Global Constraints + DoD); success = reliability(hard)+naturalness(soft). |
| **H1 — regenerating baseline destroys the reference** | 🟠 | New `evals/phase1_baseline.json`; original `baseline.json` never overwritten (Task 5). |
| **H2 — synthetic-only, not real turns** | 🟠 | Layer A also runs over `tests/corpus/` real transcripts (Task 1/5). |
| **H3 — fragile interceptor instrumentation** | 🟠 | Lean on existing `conversation_trace.answered_by`; minimal monkeypatch (Task 1). |
| **M1 — only new cases tagged** | 🟡 | Tag a sample of EXISTING cases too (Task 4). |
| **M2 — Phase 1 too heavy** | 🟡 | Right-sized: cheap deterministic core first (Task 1-2); paid judge is a separate, optional layer. |
| **S1 — naturalness as raw target risks reliability** | ⚫ | Naturalness is a CONSTRAINED objective — maximized subject to reliability=100% on guardrail domains (Global Constraints + gate rule). |

**Spec coverage:** roadmap Phase 1 (behavioral eval + %-intercepted + naturalness + recorded gate) → Tasks 1-5. ✅
**READ-ONLY invariant:** instrument reuses the harness guard; offline run never rewrites `baseline.json`; only `phase1_baseline.json` is new; paid run is operator-gated. ✅
