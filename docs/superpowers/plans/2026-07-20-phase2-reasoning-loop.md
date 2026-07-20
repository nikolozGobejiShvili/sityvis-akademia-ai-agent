# Phase 2 — Reasoning Loop (analyze → ground → answer → reflect) Implementation Plan (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the PARENT engine *think before it answers*. Today `run_parent_llm_turn` single-shot generates a reply and Python sanitizers patch it afterward ("the model doesn't think first — it generates and then Python corrects it, hence all the band-aids" — `docs/REASONING_LAYER_BRIEF.md`). Add an explicit, flag-gated four-step loop — **ANALYZE** (cheap strict-JSON plan) → **GROUND** (load only the facts the plan needs, from the RIGHT source) → **ANSWER** (existing tool loop, plan + suggested tool injected) → **REFLECT** (verify ONLY the grounded fact-classes in the answer; on a clear contradiction, safe fallback not hallucination). Gated on a NEW `USE_REASONING_PASS` (default OFF ⇒ byte-identical). Tested with the CURRENT model (gpt-4.1-mini) — the loop is model-agnostic; the operator flips `OPENAI_MODEL` later if the measurement justifies it.

**Architecture:** Additive, flag-gated, wired ONLY into the live `parent_llm_engine.run_parent_llm_turn`. ANALYZE extends the EXISTING dormant `parent_turn_analyzer.py` (no duplicate file). GROUND reuses `admin_config_service.get_camp_facts()` + `get_manager_phone()`. REFLECT reuses the EXISTING fact regex in `parent_reply_composer.py`. **REFLECT is the money/fact reliability guard, and it is CAMP-SCOPED and needed-facts-scoped to avoid false positives** (see the critique fixes below). Every step fails safe (any error → today's behavior).

**Tech Stack:** Python 3.10, OpenAI gpt-4.1-mini (unchanged), existing `openai_service` + `admin_config_service`, pytest, the Phase-1 eval. No new dependency, no model change.

## Global Constraints

- **Flag OFF ⇒ byte-identical.** With `USE_REASONING_PASS=False` (shipped default), `run_parent_llm_turn` takes exactly today's path. The full suite (~5037 passing) stays green. Pin the flag OFF in `tests/conftest.py` (including on `parent_llm_engine.settings`).
- **Never breaks a turn (fail-safe).** ANALYZE / GROUND / REFLECT each swallow every exception → fall back to the normal ANSWER path. No new raise in `run_parent_llm_turn`.
- **REFLECT is CONSERVATIVE, camp-scoped, needed-facts-scoped (critique C1/H3/M2 — load-bearing).** REFLECT judges a fact-token in the answer ONLY when (a) that fact CLASS was in the plan's `needed_facts` AND (b) GROUND actually populated a trusted value for that class AND (c) the answer's token CONTRADICTS it. When a class was not grounded (e.g. a dynamic-program price, a booked-slot date, an event fact), REFLECT does NOT judge it — those turns already have their own guards. GROUND (and thus REFLECT) is SKIPPED entirely on a dynamic-program turn (`_is_dynamic_program_turn`). This prevents REFLECT from killing a CORRECT answer (a manager phone, a formula1 price, a Calendar slot) it lacks the ground truth for. Favor letting the answer through; a false-positive fallback both hurts naturalness AND is itself a reliability failure.
- **Latency budget is part of the gate (critique H1).** The pass adds ONE sequential ANALYZE call per engine turn. Enablement requires the measured added latency to be within budget: **ANALYZE p95 ≤ ~1.5 s added** (record it; if the pass roughly doubles perceived reply time, it is NOT worth enabling at the current interception rate — say so).
- **No duplicate files.** Extend `parent_turn_analyzer.py` + `parent_llm_engine.py`. The reference `docs/reference/reasoning_layer.py` is REFERENCE-ONLY (never import it).
- **Only two new artifacts.** The ANALYZE prompt (`app/agent/prompts/parent_reasoning.md`, NEW) + the `USE_REASONING_PASS` flag. **Do NOT change** any existing `*.md` prompt, knowledge/admin YAML, Calendar, Sheets schema, booking logic, `OPENAI_MODEL`, or `.env`.
- **Distinct flag name.** `USE_REASONING_PASS` — NOT `USE_REASONING_LAYER` (the shipped Phase-1 deterministic classifier; do not touch it).
- **Measurement is mandatory + gating, and honestly framed (critique C2/M3/S1).** Flag-ON is measured on MULTIPLE advisory full-turn cases (≥3 per advisory domain), each run N times (the judge + full-turn are stochastic), and reported as a **directional signal, not proof**. The permissioned `--llm --judge` run is the real gate; the offline suite only proves flag-ON *runs* + flag-OFF is inert. Gate: flag-ON keeps CRITICAL 22/22, does NOT lower reliability on the Phase-1 guardrail domains, and should raise naturalness on the advisory cases within the latency budget. If it does not, STOP — do not enable; report the numbers.
- **No secret/PII in logs.** Mask sender ids; never log price/phone/full answer.
- **Interpreter:** `.venv/Scripts/python.exe`. **LOCAL-only** branch `feat/dynamic-programs`; push only with explicit consent. **No haiku.**
- **Expected pre-existing failure:** `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`. Any OTHER failure is in scope.

---

## File Structure

**Create:** `app/agent/prompts/parent_reasoning.md` (ANALYZE prompt); `tests/test_reasoning_pass_2026_07_20.py`.
**Modify:** `app/config.py` (flag); `tests/conftest.py` (pin); `app/agent/llm/parent_turn_analyzer.py` (`analyze_for_engine`); `app/agent/llm/parent_llm_engine.py` (orchestration + `_reasoning_ground` + `_reasoning_reflect`).

---

## Task 1: `USE_REASONING_PASS` flag (default OFF) + conftest pin

**Files:** Modify `app/config.py`, `tests/conftest.py`; Test `tests/test_reasoning_pass_2026_07_20.py`.

- [ ] **Step 1: Failing tests**
```python
def test_use_reasoning_pass_defaults_false():
    from app.config import Settings
    assert Settings().USE_REASONING_PASS is False


def test_use_reasoning_pass_parses_env(monkeypatch):
    monkeypatch.setenv("USE_REASONING_PASS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_REASONING_PASS is True
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Add flag** — `app/config.py` near `USE_LEARNING: bool = False`: `USE_REASONING_PASS: bool = False`; in `from_env`: `USE_REASONING_PASS=_parse_bool_optional("USE_REASONING_PASS", False),`.
- [ ] **Step 4: Pin OFF in conftest** — add `USE_REASONING_PASS=False` to the autouse `dataclasses.replace(config_module.settings, ...)` (~line 105) AND `monkeypatch.setattr(parent_llm_engine, "settings", swapped)` so the pin reaches the engine (it reads `settings.USE_REASONING_PASS`). Verify the pin takes effect on the engine module.
- [ ] **Step 5: Run → pass.**
- [ ] **Step 6: Commit** — `feat(config): USE_REASONING_PASS flag (default off) + conftest pin`

---

## Task 2: ANALYZE — `analyze_for_engine` + the reasoning prompt

**Files:** Modify `app/agent/llm/parent_turn_analyzer.py`; Create `app/agent/prompts/parent_reasoning.md`; Test file.

**Interfaces:** `analyze_for_engine(*, user_message, lead, conversation, knowledge_keys, tool_names) -> dict | None` — strict-JSON plan: `user_goal: str`, `sentiment: str="neutral"`, `needed_facts: list[str]` (CLOSED set `price/dates/location/age/registration/conditions/phone`), `missing_lead_fields: list[str]`, `suggested_tool: str | None` (from `tool_names`), `should_greet: bool`, `plan: str` (≤200 chars). `None` on ANY failure. NEVER raises. Reuses `openai_service.analyze_parent_turn(system_prompt, user_payload, max_tokens=300, temperature=0)` + `_extract_json_blob`.

- [ ] **Step 1: Write `app/agent/prompts/parent_reasoning.md`** — strict-JSON instruction, exactly the 7 fields, rule: **"Do NOT decide any price/date/age/phone/link here — only NAME which facts the answer needs (needed_facts). JSON only, no prose."** `{knowledge_keys}`/`{tool_names}`/`{known_facts}` placeholders. Short.
- [ ] **Step 2: Failing tests** (mock `openai_service.analyze_parent_turn`): valid JSON → parsed 7-field dict; malformed JSON → `None`; OpenAI raises → `None`. (Exact code as in v1's Task 2 tests.)
- [ ] **Step 3: Run → fail → Step 4: Implement** `analyze_for_engine` (load `parent_reasoning.md` via `load_prompt`, `.format(...)`, call `openai_service.analyze_parent_turn`, parse with `_extract_json_blob`→`json.loads`, coerce the 7 fields to the closed sets + defaults, any exception → `None`). Do NOT touch `analyze_parent_turn`. → **Step 5: Run → pass.**
- [ ] **Step 6: Commit** — `feat(reasoning): ANALYZE — analyze_for_engine + strict-JSON reasoning prompt`

---

## Task 3: GROUND — preselect the needed facts from the RIGHT source (critique C1/H3)

**Files:** Modify `app/agent/llm/parent_llm_engine.py`; Test file.

**Interfaces:** `_reasoning_ground(needed_facts: list[str]) -> dict[str, str]` — returns a dict keyed by fact-CLASS (only the classes in `needed_facts` that we can trust-source), e.g. `{"price": "2150", "phone": "558 67 47 33"}`. Sources: `price/dates/location/age/registration/conditions` → `admin_config_service.get_camp_facts()`; `phone` → `admin_config_service.get_manager_phone()`. A class we cannot source → omitted (NOT guessed). Empty/None `needed_facts` → `{}`. NEVER raises → `{}`. Returning a per-CLASS dict (not one blob) is what lets REFLECT judge only the grounded classes.

Also add `_reasoning_ground_text(grounded: dict) -> str` — a compact Georgian block for the ANSWER directive (e.g. `"ფასი: 2150 ₾\nმენეჯერი: 558 67 47 33"`).

- [ ] **Step 1: Failing tests** (monkeypatch `get_camp_facts` + `get_manager_phone`):
```python
def test_reasoning_ground_selects_only_needed(monkeypatch):
    from app.agent.llm import parent_llm_engine as ple
    from app.services import admin_config_service as acs
    monkeypatch.setattr(acs, "get_camp_facts",
        lambda: {"price_gel": 2150, "price_text": "2150", "location": "კაჭრეთი"})
    monkeypatch.setattr(acs, "get_manager_phone", lambda: "558 67 47 33")
    g = ple._reasoning_ground(["price", "phone"])
    assert g["price"] == "2150" and g["phone"] == "558 67 47 33"
    assert "location" not in g   # not requested → not grounded

def test_reasoning_ground_empty_and_error_safe(monkeypatch):
    from app.agent.llm import parent_llm_engine as ple
    from app.services import admin_config_service as acs
    assert ple._reasoning_ground([]) == {}
    monkeypatch.setattr(acs, "get_camp_facts", lambda: (_ for _ in ()).throw(RuntimeError()))
    assert ple._reasoning_ground(["price"]) == {}   # never raises
```
- [ ] **Step 2: Run → fail → Step 3: Implement** (per-class dict, camp facts + manager phone, try/except → `{}`; + the `_reasoning_ground_text` formatter). → **Step 4: Run → pass.**
- [ ] **Step 5: Commit** — `feat(reasoning): GROUND — per-class preselect (camp facts + manager phone), source-correct`

---

## Task 4: REFLECT — verify ONLY grounded classes, conservative safe-fallback (critique C1/M2)

**Files:** Modify `app/agent/llm/parent_llm_engine.py`; Test file.

**Interfaces:** `_reasoning_reflect(answer: str, grounded: dict[str, str]) -> tuple[str, bool]` → `(final_answer, replaced)`. For EACH fact-class present in `grounded` (price/phone/date/url) — and ONLY those classes — extract that class's tokens from `answer` using the EXISTING regex reused from `parent_reply_composer` (`_URL_PATTERN`/`_PHONE_PATTERN`/`_PRICE_PATTERN`/date). If the answer contains a token of that class whose value CONTRADICTS the grounded value (present but different), that is a clear hallucination → replace the answer with a conservative safe fallback (offer to confirm with the manager, no invented fact) and `replaced=True`. A class NOT in `grounded` is never judged (we lack ground truth). No contradiction → `(answer, False)`. NEVER raises → `(answer, False)`.

- [ ] **Step 1: Failing tests:**
```python
def test_reflect_passes_grounded_answer():
    from app.agent.llm import parent_llm_engine as ple
    ans = "ბანაკის ფასია 2150 ₾."
    assert ple._reasoning_reflect(ans, {"price": "2150"}) == (ans, False)

def test_reflect_replaces_contradicted_price():
    from app.agent.llm import parent_llm_engine as ple
    out, replaced = ple._reasoning_reflect("ფასია 9999 ლარი.", {"price": "2150"})
    assert replaced is True and "9999" not in out

def test_reflect_does_not_judge_ungrounded_class():
    from app.agent.llm import parent_llm_engine as ple
    # a price token in the answer, but price was NOT grounded (e.g. dynamic program) → pass
    ans = "ფორმულა1-ის ფასია 5000 ლარი."
    assert ple._reasoning_reflect(ans, {"phone": "558 67 47 33"}) == (ans, False)

def test_reflect_never_raises():
    from app.agent.llm import parent_llm_engine as ple
    assert ple._reasoning_reflect(None, None) == (None, False)
```
- [ ] **Step 2: Run → fail → Step 3: Implement** (reuse the composer regex; per-grounded-class contradiction check; conservative; safe-fallback reuses an existing brand manager-handoff constant). → **Step 4: Run → pass.**
- [ ] **Step 5: Commit** — `feat(reasoning): REFLECT — verify only grounded classes, conservative safe-fallback`

---

## Task 5: ANSWER orchestration — wire the loop (flag-gated), suggested-tool soft-drive (critique H2)

**Files:** Modify `app/agent/llm/parent_llm_engine.py`; Test file.

**Interfaces:** In `run_parent_llm_turn`, after `_capture_turn_facts(...)` (line 2093) and before messages assembly (2095), all inside `if getattr(settings, "USE_REASONING_PASS", False):` and wrapped so any failure falls back to the normal path:
1. **Skip on dynamic-program turns** (critique H3): `if _is_dynamic_program_turn(user_message): <skip the pass>` — those turns aren't camp-groundable yet and have their own guards.
2. `plan = parent_turn_analyzer.analyze_for_engine(...)`; if `None` → skip the rest (normal path).
3. `grounded = _reasoning_ground(plan.get("needed_facts", []))`.
4. Build a `plan_directive` system message: the plan's `plan` string + `_reasoning_ground_text(grounded)` + **"answer ONLY from these verified facts for price/date/phone/link; if a needed fact is missing here, ask or offer the manager — never invent."** + a SOFT tool hint: **"the analysis suggests the `{suggested_tool}` tool is likely relevant — call it first if the question needs those facts."** Append as a SEPARATE `{"role":"system", "content": plan_directive}` after line 2115 (NOT concatenated into the 52 KB giant prompt). **Keep `tool_choice="auto"`** — do NOT hard-force the suggested tool (a wrong ANALYZE must not break the turn; the hint is advisory, addressing H2 without the hard-force risk).
5. After the tool loop, `answer, replaced = _reasoning_reflect(answer, grounded)`; use the (possibly replaced) answer. Trace `replaced` (masked, no PII) + an ANALYZE-latency marker.

Flag OFF ⇒ none runs ⇒ byte-identical.

- [ ] **Step 1: Failing e2e tests** (engine ON + flag ON, mock ANALYZE + `chat_with_tools`): flag ON → the ANALYZE mock is called ≥1 and a reply returns; flag OFF → ANALYZE mock call count == 0, reply still produced. Also: a dynamic-program message with flag ON → ANALYZE mock NOT called (skip path).
- [ ] **Step 2: Run → fail → Step 3: Implement** (every sub-step guarded; the ANSWER loop always runs). → **Step 4: Run → pass.**
- [ ] **Step 5: Byte-identity (flag OFF)** — `.venv/Scripts/python.exe -m pytest tests/test_parent_llm_engine.py tests/test_reasoning_pass_2026_07_20.py -q` → green.
- [ ] **Step 6: Commit** — `feat(reasoning): wire analyze->ground->answer->reflect into run_parent_llm_turn (USE_REASONING_PASS)`

---

## Task 6: Full-suite gate + reasoning measurement (critique C2/H1/M1/M3)

- [ ] **Step 1: Flag-OFF full suite (byte-identity).** `.venv/Scripts/python.exe -m pytest -q` → only the pre-existing `fast_track` fails. Record.
- [ ] **Step 2: Flag-ON focused.** `.venv/Scripts/python.exe -m pytest tests/test_reasoning_pass_2026_07_20.py -q` → green.
- [ ] **Step 3: Eval gate — READ-ONLY offline.** `.venv/Scripts/python.exe -m evals.run_evals` → READ-ONLY-clean, `evals/baseline.json` byte-identical.
- [ ] **Step 4: ANALYZE prompt real-JSON smoke (M1) + reasoning measurement (PERMISSIONED — operator step, costs tokens; do NOT run without explicit permission).** Document the commands:
  - **Prompt sanity (M1):** one `--llm` call through `analyze_for_engine` on a real message → assert it returns a valid 7-field dict (proves the new prompt yields parseable JSON, so the pass doesn't silently no-op).
  - **Advisory measurement (C2):** compare flag-OFF vs flag-ON on **≥3 advisory full-turn cases per advisory domain** (objection/camp_topic/program_info — extend `evals/cases.py` with a few more if only OB1/OB2/PI2 exist), each run **N=3** and median-aggregated (both the full-turn and the judge are stochastic). Report as a **directional signal, not statistical proof**.
  - **Guardrail + CRITICAL:** `python tools/scenario_runner_full.py --priority CRITICAL` flag-ON → **22/22**; Phase-1 guardrail domains (booking_reliability/contact_capture) reliability must NOT drop.
  - **Latency (H1):** record the added ANALYZE latency (p95); gate on ≤ ~1.5 s added.
  - **The binding gate:** flag-ON keeps CRITICAL 22/22 + guardrail reliability + within latency budget, and shows a directional naturalness gain on advisory cases. If not, **STOP — do not enable; report.**
- [ ] **Step 5: Commit** any changelog note.

---

## Phase 2 Definition of Done

With `USE_REASONING_PASS` ON, a CAMP PARENT turn that reaches the engine runs analyze→ground→answer→reflect: a structured plan, only the needed facts grounded from the RIGHT source (`get_camp_facts()` + `get_manager_phone()`), the answer generated with plan+facts+suggested-tool injected as a directive, and REFLECT verifying ONLY the grounded fact-classes — replacing a clearly-contradicted fact with a safe fallback (never inventing), and never judging a class it didn't ground (so a correct manager phone / dynamic-program price / Calendar slot is never killed). Dynamic-program turns skip the pass (their own guards apply). With `USE_REASONING_PASS=false`: byte-identical, full suite green. Every step fails safe. REFLECT is the conservative money/fact reliability guard.

**Honest scope (critique S1):** Phase 2 improves the QUALITY of the ~3% of turns that reach the engine — it does NOT change how many turns reach the engine (that is Phase 3, interceptors→tools). Its measurable value is therefore limited until Phase 3 opens the share. **Recommended sequencing after this plan lands + is measured:** rather than "all of Phase 2 then all of Phase 3," consider a **pilot domain** — take ONE advisory domain (e.g. objection), convert its interceptor(s) → a tool (Phase 3) so those turns reach the engine, and measure the reasoning loop on that domain's REAL traffic. That validates the loop on live turns, not just 3 synthetic cases, before scaling. **Flag stays OFF — enablement is a separate operator step gated on the measurement.**

**Explicitly NOT in Phase 2:** no interceptor removal (Phase 3); no prompt/YAML/model/.env change (only the new ANALYZE prompt + flag); no legacy-state-machine change; no dynamic-program grounding (follow-up); model stays gpt-4.1-mini.

---

## Appendix — Critique → Fix (v1 → v2)

| Finding | Sev | Resolution |
|---|---|---|
| **C1 — REFLECT kills correct answers it can't ground (manager phone, dynamic price, slot date all judged against camp facts)** | 🔴 | REFLECT judges ONLY the fact-classes GROUND actually populated (per-class `grounded` dict); GROUND sources each class correctly (camp facts + manager phone); ungrounded classes never judged. |
| **C2 — measurement surface too narrow (3 stochastic cases)** | 🔴 | ≥3 advisory cases/domain, N=3 median, framed as directional signal not proof; permissioned `--llm --judge` is the real gate. |
| **H1 — +1 ANALYZE call latency, no budget** | 🟠 | Explicit p95 latency budget (≤~1.5 s added) as part of the enablement gate. |
| **H2 — suggested_tool unused; ANALYZE just adds a directive on top of the tool loop** | 🟠 | The directive carries a SOFT suggested-tool hint (call it first if relevant); `tool_choice` stays `auto` so a wrong ANALYZE can't break the turn (hard-force rejected as too risky). |
| **H3 — needed_facts camp-centric; dynamic programs mis-grounded** | 🟠 | The pass SKIPS dynamic-program turns entirely (`_is_dynamic_program_turn`); Phase 2 grounds camp turns only (documented follow-up for dynamic programs). |
| **M1 — new prompt could silently yield unparseable JSON → pass no-ops** | 🟡 | Task 6 adds a permissioned real-`--llm` prompt-sanity smoke asserting `analyze_for_engine` returns a valid dict. |
| **M2 — REFLECT false-positive fallback reintroduces "botlike"** | 🟡 | REFLECT is conservative by construction (only clear contradictions on grounded classes) — folded into C1's fix. |
| **M3 — mocked e2e proves "runs" not "better"** | 🟡 | Documented: offline suite proves runs + flag-off inert; the permissioned `--llm --judge` advisory measurement is the "better" gate. |
| **S1 — Phase 2 alone touches only ~3%; sequencing** | ⚫ | DoD states the limited-until-Phase-3 scope honestly + recommends a pilot-domain (Phase 2+3 on one domain) as the validation path on real traffic. |

**Spec coverage / flag-off / fail-safe / type-consistency:** unchanged from v1's self-review (all ✅) — the v2 changes tighten REFLECT scoping, measurement honesty, latency, and sequencing without altering the analyze→ground→answer→reflect structure.
