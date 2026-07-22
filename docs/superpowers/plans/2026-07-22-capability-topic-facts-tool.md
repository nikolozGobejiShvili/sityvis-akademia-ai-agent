# Capability #1 — Topic-Facts Tool (`get_program_topic`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Convert the biggest customer-facing knowledge body — `camp_topic_facts.yaml` (502 lines: safety, food, gadgets, medical, daily schedule, parent communication) — from a deterministic pre-LLM interceptor that the model never sees into a flag-gated LLM **tool** (`get_program_topic`) the model reasons over, so a differently-phrased topic question gets a reasoned answer grounded in the topic facts instead of a substring-matched canned block.

**Architecture:** One new flag `USE_PROGRAM_TOPICS` (default OFF). When ON: the topic interceptor *yields* so the turn reaches the LLM engine, the engine sees a new `get_program_topic(topic)` tool (kept OUT of the always-on tool list, appended only under the flag), and a short prompt suffix tells the model to call it. When OFF: byte-identical — the interceptor answers exactly as today, the tool surface and system-prompt bytes are unchanged. The tool reuses the existing, LLM-free `camp_topic_facts.answer_for_topic(topic)` / `medical_answer()` readers, so facts still come from the backend YAML, not the model's memory.

**Tech Stack:** Python 3.10, OpenAI gpt-4.1-mini (unchanged). No new dependency.

## Global Constraints

- **Flag OFF ⇒ BYTE-IDENTICAL.** `USE_PROGRAM_TOPICS=False` ⇒ (a) `_maybe_handle_camp_topic_facts` runs its existing body unchanged, (b) `build_active_tools` returns the same list as today, (c) `_build_system_prompt` returns the same bytes (new suffix returns `""`). The full suite (~5150) stays green. **The single biggest risk is changing the flag-OFF tool surface or prompt bytes** — the new tool MUST live in a separate `TOPIC_TOOLS` list kept OUT of `PARENT_TOOLS` (mirror `LEARNING_TOOLS`/`DYNAMIC_PROGRAM_TOOLS`), and every flag-gated branch must default to the current behavior.
- **Do NOT break existing capabilities** (operator hard constraint): booking, lead capture, manager-number handoff are untouched. This plan adds a read-only info tool; it must not alter any booking/lead/handoff path.
- **Facts from the backend, not the model.** The tool returns YAML topic facts via `camp_topic_facts.answer_for_topic` / `medical_answer` (no LLM in the reader). The model reasons the wording; the facts are the tool's.
- **Camp-scoped pilot (per seam map §6).** `sections.yaml` has no per-program topic blocks, so a truly generic `get_program_topic(program, topic)` has no data for non-camp products today. Ship `get_program_topic(topic)` reading `camp_topic_facts.yaml`; the name leaves room to add `program_id` later without renaming. Generic-by-program is explicitly OUT of scope here.
- **No forbidden changes:** do NOT touch `OPENAI_MODEL`, `.env`, Calendar/Sheets/booking logic, the dormant slim/planner path, `data/admin_config/sections.yaml`, `evals/baseline.json`, `CLAUDE.md`, `HANDOFF.md`. Do NOT modify the SECOND `resolve_camp_answer` use at `parent_flow.py:4233` (multi-clause combiner) — gate ONLY inside `_maybe_handle_camp_topic_facts`.
- **LOCAL-only** branch `feat/dynamic-programs`; never push. **Interpreter** `.venv/Scripts/python.exe`. **No haiku.**
- **Expected pre-existing failure** (not in scope): `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`.

---

## File Structure

**Modify:**
- `app/config.py` — `USE_PROGRAM_TOPICS: bool = False` (~L382, near `USE_SKILLS`) + `from_env` reader (~L573).
- `tests/conftest.py` — pin `USE_PROGRAM_TOPICS=False` in the autouse `dataclasses.replace` (~L130).
- `app/agent/tools/parent_tools.py` — `TOOL_GET_PROGRAM_TOPIC` name constant (~L50) + add to `ALLOWED_TOOL_NAMES` (~L52) + new `TOPIC_TOOLS` list (~L476, after `LEARNING_TOOLS`, KEPT OUT of `PARENT_TOOLS`).
- `app/agent/tools/parent_tool_executor.py` — import the name (L42–56) + dispatch `elif` (after L363) + `_get_program_topic` handler (near `_get_approved_answer`, L482).
- `app/agent/llm/parent_llm_engine.py` — extend `build_active_tools` (L47) with `use_topics`; update call site (L2537); add `_topic_tool_prompt_suffix()` (mirror `_approved_answer_prompt_suffix` L97) + append in `_build_system_prompt` (L2720).
- `app/flows/parent_flow.py` — the yield gate inside `_maybe_handle_camp_topic_facts` (after the ADULT guard, ~L5044).

**Create:** `tests/test_program_topic_tool_2026_07_22.py`.

---

## Task 1: Flag `USE_PROGRAM_TOPICS` (default OFF) + conftest pin

**Files:** Modify `app/config.py`, `tests/conftest.py`; Test `tests/test_program_topic_tool_2026_07_22.py`.

**Interfaces:** Produces `settings.USE_PROGRAM_TOPICS: bool` (default False), consumed by Tasks 2–3.

- [ ] **Step 1: Failing test** — in `tests/test_program_topic_tool_2026_07_22.py`:
```python
from app.config import Settings

def test_program_topics_flag_defaults_off():
    assert Settings().USE_PROGRAM_TOPICS is False
```
- [ ] **Step 2: Run → fail.** `.venv/Scripts/python.exe -m pytest tests/test_program_topic_tool_2026_07_22.py -q`
- [ ] **Step 3: Add flag.** In `app/config.py` near `USE_SKILLS`: `USE_PROGRAM_TOPICS: bool = False`; in `from_env` (near the other `_parse_bool_optional` calls): `USE_PROGRAM_TOPICS=_parse_bool_optional("USE_PROGRAM_TOPICS", False),`. In `tests/conftest.py`, add `USE_PROGRAM_TOPICS=False,` to the autouse `dataclasses.replace(config_module.settings, ...)`.
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** — `feat(config): USE_PROGRAM_TOPICS flag (default off) + conftest pin`

---

## Task 2: The `get_program_topic` tool — schema, executor, wiring, prompt suffix (flag-gated, OUT of PARENT_TOOLS)

**Files:** Modify `app/agent/tools/parent_tools.py`, `app/agent/tools/parent_tool_executor.py`, `app/agent/llm/parent_llm_engine.py`; Test.

**Interfaces:**
- Consumes: `settings.USE_PROGRAM_TOPICS` (Task 1); `app.reasoning.camp_topic_facts.answer_for_topic(topic)`, `medical_answer()`, `TOPIC_PRIORITY` (existing).
- Produces: `TOOL_GET_PROGRAM_TOPIC` constant; `TOPIC_TOOLS: list[dict]`; `build_active_tools(use_dynamic, use_learning=False, use_topics=False)`; executor `_get_program_topic(args) -> {"success": bool, "topic": str, "facts": str}`; `_topic_tool_prompt_suffix() -> str`.

- [ ] **Step 1: Read the templates** — `app/agent/tools/parent_tools.py:459-475` (`LEARNING_TOOLS`), `parent_tool_executor.py:468-482` (`_get_approved_answer` + its dispatch elif ~L362-363), `parent_llm_engine.py:47-52` (`build_active_tools`) and `:97-108` (`_approved_answer_prompt_suffix`). Mirror these exactly.

- [ ] **Step 2: Failing tests:**
```python
import dataclasses
import app.config as config_module
import app.agent.llm.parent_llm_engine as ple
from app.agent.tools import parent_tools as pt
from app.agent.tools.parent_tool_executor import ParentToolExecutor

def _on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PROGRAM_TOPICS=True)
    monkeypatch.setattr(ple, "settings", swapped)

def test_topic_tool_out_of_parent_tools():
    names = [t["function"]["name"] for t in pt.PARENT_TOOLS]
    assert pt.TOOL_GET_PROGRAM_TOPIC not in names          # never in the always-on list

def test_build_active_tools_appends_only_when_flag_on():
    off = ple.build_active_tools(use_dynamic=False, use_learning=False, use_topics=False)
    on = ple.build_active_tools(use_dynamic=False, use_learning=False, use_topics=True)
    off_names = [t["function"]["name"] for t in off]
    on_names = [t["function"]["name"] for t in on]
    assert pt.TOOL_GET_PROGRAM_TOPIC not in off_names
    assert pt.TOOL_GET_PROGRAM_TOPIC in on_names

def test_executor_returns_topic_facts_from_backend():
    ex = ParentToolExecutor(conversation=None)   # match _get_approved_answer's construction
    res = ex._get_program_topic({"topic": "safety"})
    assert res["success"] is True and res["topic"] == "safety" and res["facts"]

def test_executor_unknown_topic_fails_safely():
    ex = ParentToolExecutor(conversation=None)
    res = ex._get_program_topic({"topic": "not_a_topic"})
    assert res["success"] is False

def test_prompt_suffix_empty_when_flag_off(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PROGRAM_TOPICS=False)
    monkeypatch.setattr(ple, "settings", swapped)
    assert ple._topic_tool_prompt_suffix() == ""

def test_prompt_suffix_present_when_flag_on(monkeypatch):
    _on(monkeypatch)
    assert "get_program_topic" in ple._topic_tool_prompt_suffix()
```
(Adjust `ParentToolExecutor(...)` construction to match how `_get_approved_answer`'s tests build it — read the executor's `__init__`.)

- [ ] **Step 3: Run → fail.**

- [ ] **Step 4: Implement.**
  - **`parent_tools.py`:** add `TOOL_GET_PROGRAM_TOPIC = "get_program_topic"` near the other name constants; add it to `ALLOWED_TOOL_NAMES`; add after `LEARNING_TOOLS`:
    ```python
    TOPIC_TOOLS: list[dict[str, Any]] = [
        {"type": "function", "function": {
            "name": TOOL_GET_PROGRAM_TOPIC,
            "description": (
                "დააბრუნებს პროგრამის კონკრეტული თემის ფაქტებს (უსაფრთხოება, კვება, "
                "გაჯეტები, სამედიცინო, დღის განრიგი, მშობელთან კომუნიკაცია და სხვ.). "
                "გამოიძახე, როცა მშობელი ამ თემებზე კითხულობს — უპასუხე დაბრუნებული "
                "ფაქტებით, ბუნებრივად, არ გამოიგონო."
            ),
            "parameters": {"type": "object", "properties": {
                "topic": {"type": "string", "description": "თემის სახელი (safety/food/gadgets/medical/…)."},
            }, "required": ["topic"]},
        }},
    ]
    ```
    Keep `TOPIC_TOOLS` OUT of `PARENT_TOOLS`.
  - **`parent_tool_executor.py`:** import `TOOL_GET_PROGRAM_TOPIC`; add dispatch after the learning elif: `elif tool_name == TOOL_GET_PROGRAM_TOPIC: result = self._get_program_topic(args)`; add handler:
    ```python
    def _get_program_topic(self, args: dict) -> dict:
        from app.reasoning import camp_topic_facts as _ctf
        topic = (args or {}).get("topic", "").strip()
        if not topic:
            return {"success": False, "topic": "", "facts": ""}
        text = _ctf.medical_answer() if topic == "medical" else _ctf.answer_for_topic(topic)
        if not text:
            return {"success": False, "topic": topic, "facts": ""}
        return {"success": True, "topic": topic, "facts": text}
    ```
  - **`parent_llm_engine.py`:** extend `build_active_tools`:
    ```python
    def build_active_tools(use_dynamic: bool, use_learning: bool = False, use_topics: bool = False) -> list[dict]:
        tools = list(PARENT_TOOLS)
        if use_dynamic: tools = tools + DYNAMIC_PROGRAM_TOOLS
        if use_learning: tools = tools + LEARNING_TOOLS
        if use_topics: tools = tools + TOPIC_TOOLS
        return tools
    ```
    (import `TOPIC_TOOLS`.) Update the call site (~L2537) to `tools=build_active_tools(settings.USE_DYNAMIC_PROGRAMS, settings.USE_LEARNING, getattr(settings, "USE_PROGRAM_TOPICS", False))`. Add the suffix mirroring `_approved_answer_prompt_suffix`:
    ```python
    def _topic_tool_prompt_suffix() -> str:
        if not getattr(settings, "USE_PROGRAM_TOPICS", False):
            return ""
        return (
            "\n\nროცა მშობელი კითხულობს ბანაკის კონკრეტულ თემაზე (უსაფრთხოება, კვება, "
            "გაჯეტები, სამედიცინო, დღის განრიგი, მშობელთან კომუნიკაცია), გამოიძახე "
            "get_program_topic და უპასუხე დაბრუნებული ფაქტებით — ბუნებრივად, არ გამოიგონო."
        )
    ```
    Append it in `_build_system_prompt`'s return (after `_skills_prompt_suffix(...)`).

- [ ] **Step 5: Run → pass.**
- [ ] **Step 6: Flag-OFF byte-identity gate** — `build_active_tools(False,False,False)` equals `list(PARENT_TOOLS)`; `_topic_tool_prompt_suffix()==""` under the conftest default. Run `.venv/Scripts/python.exe -m pytest tests/test_program_topic_tool_2026_07_22.py tests/test_camp_age_bounds_migration_5a2_2026_06_22.py -q`.
- [ ] **Step 7: Commit** — `feat(tools): get_program_topic tool (flag-gated TOPIC_TOOLS, out of PARENT_TOOLS)`

---

## Task 3: Interceptor bypass gate + end-to-end

**Files:** Modify `app/flows/parent_flow.py` (`_maybe_handle_camp_topic_facts` only); Test.

**Interfaces:** Consumes `settings.USE_PROGRAM_TOPICS`, `settings.USE_PARENT_LLM_ENGINE`.

- [ ] **Step 1: Read** `parent_flow.py:5038-5059` (the function) + confirm the ADULT guard lines, and the call site at `:1567-1573`.

- [ ] **Step 2: Failing tests:**
```python
# flag OFF: the interceptor still answers a topic question deterministically (byte-identical)
def test_flag_off_interceptor_still_answers_topic():
    from app.flows import parent_flow
    from app.models.conversation import Conversation
    conv = Conversation(sender_id="t", platform="messenger")
    out = parent_flow._maybe_handle_camp_topic_facts(conv, "უსაფრთხოება როგორ არის ბანაკში?")
    assert out and out.strip()          # canned block returned, engine not consulted

# flag ON (engine on): the interceptor YIELDS so the turn falls through to the engine
def test_flag_on_interceptor_yields(monkeypatch):
    import dataclasses, app.config as config_module
    from app.flows import parent_flow
    from app.models.conversation import Conversation
    swapped = dataclasses.replace(config_module.settings,
                                  USE_PROGRAM_TOPICS=True, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    conv = Conversation(sender_id="t", platform="messenger")
    out = parent_flow._maybe_handle_camp_topic_facts(conv, "უსაფრთხოება როგორ არის ბანაკში?")
    assert out is None                  # yields → the turn will reach the engine + tool
```
- [ ] **Step 3: Run → fail** (`test_flag_on_interceptor_yields` fails — currently it returns the canned block).
- [ ] **Step 4: Implement** — inside `_maybe_handle_camp_topic_facts`, immediately after the ADULT guard:
```python
    # Topic-tool pilot (flag-gated): when USE_PROGRAM_TOPICS is on AND the engine
    # is available, YIELD so the turn reaches the LLM, which reasons over the
    # get_program_topic tool instead of returning this canned block. Flag OFF ⇒
    # this branch is never taken ⇒ the body below runs unchanged (byte-identical).
    if (getattr(settings, "USE_PROGRAM_TOPICS", False)
            and getattr(settings, "USE_PARENT_LLM_ENGINE", False)):
        return None
```
- [ ] **Step 5: Run → pass.**
- [ ] **Step 6: End-to-end (engine spied, no OpenAI).** Add a test that, with both flags on and `run_parent_llm_turn` replaced by a fake asserting the topic tool is offered, drives a topic question through `parent_flow.handle` and confirms it reaches the engine (reuse the `reach`/engine-spy pattern; reopen camp registration if needed so no dead-season interceptor pre-empts). Assert `build_active_tools(..., use_topics=True)` contains `get_program_topic`.
- [ ] **Step 7: Commit** — `feat(parent-flow): flag-gated topic-interceptor bypass so topic questions reach the engine`

---

## Task 4: Whole-suite verification + flag-ON smoke prep

- [ ] **Step 1: Full suite, flags OFF.** `.venv/Scripts/python.exe -m pytest -q` → only the declared pre-existing `fast_track` failure. Record counts.
- [ ] **Step 2: Flag-OFF byte-identity, focused.** `_build_system_prompt()` unchanged (byte-exact test green), `build_active_tools(False,False,False)==list(PARENT_TOOLS)`.
- [ ] **Step 3: Offline eval READ-ONLY + baseline intact.** `PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -m evals.run_evals` → READ-ONLY-clean; `md5sum evals/baseline.json` = `93973fcd10349b447f87fa320e0807f3`.
- [ ] **Step 4: Write `docs/ENABLEMENT_USE_PROGRAM_TOPICS.md`** — how to enable (env `USE_PROGRAM_TOPICS=true` + `USE_PARENT_LLM_ENGINE=true`, full restart, camp registration state), what changes (topic questions reach the engine + `get_program_topic`), the flag-off rollback, and that the paid flag-ON behavioral proof is the 20-conversation review (operator-approved, not run here).
- [ ] **Step 5: Commit** — `docs: USE_PROGRAM_TOPICS enablement + rollback runbook`

---

## Definition of Done

With `USE_PROGRAM_TOPICS` + `USE_PARENT_LLM_ENGINE` ON, a camp-topic question (safety/food/gadgets/medical/schedule/communication) reaches the LLM, which calls `get_program_topic(topic)` and reasons a natural answer from the returned YAML facts (facts still backend-sourced). With the flag OFF: byte-identical — the interceptor answers as today, the tool surface and system-prompt bytes are unchanged, full suite green but the one pre-existing failure, `evals/baseline.json` untouched. No booking/lead/handoff path changed. **The paid behavioral proof (does the reasoned answer beat the canned block on varied phrasing?) is the operator-approved 20-conversation review, prepared separately, not run here.**

**Explicitly NOT in scope:** generic-by-program topics (no data source yet); the `parent_flow.py:4233` multi-clause path; any model/prompt-consolidation change; enabling the flag.

## Self-Review
- Flag-off byte-identity: tool OUT of PARENT_TOOLS (Task 2), suffix `""` off, `build_active_tools` appends only under flag, interceptor gate defaults to current body (Task 3). ✅
- Facts from backend: executor calls `answer_for_topic`/`medical_answer` (LLM-free). ✅
- No booking/lead/handoff touch: read-only info tool only. ✅
- Type consistency: `TOOL_GET_PROGRAM_TOPIC`, `TOPIC_TOOLS`, `build_active_tools(...,use_topics=False)`, `_get_program_topic`, `_topic_tool_prompt_suffix` used verbatim across tasks. ✅
- Camp-scoped pilot per seam map §6; generic deferred. ✅
