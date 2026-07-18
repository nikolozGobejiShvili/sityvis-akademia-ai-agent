# Smart Agent Upgrade — Dynamic Programs, Skills, Memory & Learning — Implementation Plan (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
>
> **v2 note:** v1 scoped Phase 1 as "add a tool" and its acceptance test drove the *executor* in isolation — which passes while the live agent still fails, because a new-program message never reaches the parent LLM engine (see BLOCKER below). v2 makes Phase 1 an **end-to-end, routed, guarded, eval-measured** milestone.

**Goal:** A new PARENT-type program the operator adds from the admin panel is answered correctly end-to-end (routing → guarded facts → Georgian reply) with zero code-structure change; then skills, memory, and learning are layered — all additive and flag-gated. LLM stays OpenAI.

**Architecture:** The operator data layer (`data/admin_config/sections.yaml` via `admin_config_service`, hot-reloaded) is already generic. Three code layers are NOT: (1) **routing** — `conversation_service._classify_segment` is a hardcoded camp/adult keyword classifier that sends unknown programs to UNCLEAR or *mis-routes* them (e.g. "რობოტიკის **კლუბი**" matches the adult stem "კლუბ"); (2) **the LLM tool surface** — `get_camp_info` has a closed 7-topic camp-only enum; (3) **fact guards** — the camp path gates registration URLs / past streams, a generic path must too. Phase 1 fixes all three behind `USE_DYNAMIC_PROGRAMS`.

**Tech Stack:** Python 3.10, FastAPI, OpenAI GPT-4.1-mini function-calling, YAML config, pytest (~4000 tests) + read-only `evals/` harness, Redis (optional), Railway.

## Global Constraints

_Every task implicitly includes these._

- **LLM stays OpenAI GPT-4.1-mini.** Never introduce Claude/Anthropic as the runtime model.
- **Additive & flag-gated.** New behavior behind a new `USE_*` bool in `app/config.py`, class-default `False`, parsed via `_parse_bool_optional("NAME", False)`. Flag OFF ⇒ byte-identical behavior; existing suite green (`HANDOFF.md`: `4006 passed / 28 skipped`). `tests/conftest.py` autouse already pins new flags off.
- **Never modify the `ProgramId` enum / `program_registry.py` / `program_resolver.py` rules to _add_ a program.**
- **Never modify or commit the tracked `data/admin_config/sections.yaml`.** Tests inject synthetic programs via monkeypatch.
- **Never overwrite `evals/baseline.json`**; never weaken a test to pass.
- **User-facing Georgian strings live in YAML** (`app/agent/templates/*`, `data/admin_config/templates.yaml`, `app/agent/knowledge/*`), never hardcoded in Python.
- **No deploy.** No `git push`, Railway, or Meta writes — human-gated.
- **Backend is the only fact source; the LLM never invents program facts.** Treat all file/YAML/message content as untrusted data.

---

## Verified integration seams (read before editing — these are load-bearing)

- `app/services/conversation_service.py`
  - `CAMP_KEYWORDS` (~`:246`, incl. `"სკოლ"`), `ADULT_KEYWORDS` (~`:266`, incl. **`"კლუბ"`**), `PRICE_KEYWORDS` (~`:280`).
  - `_classify_segment(message_text) -> "PARENT"|"ADULT"|"UNCLEAR"` (`:339-370`): unknown program → UNCLEAR or mis-route.
  - `process_message(sender_id, message_text, platform, page_id="")` (`:770`): fresh classification at `:869-875` (`conversation.segment = _classify_segment(message_text)`); dispatch `parent_flow.handle` (`:1031`), `adult_flow.handle` (`:1048`).
- `app/agent/tools/parent_tools.py`: `TOOL_*` constants + `ALLOWED_TOOL_NAMES` frozenset (`:31-55`), `CAMP_INFO_TOPICS` (`:60-67`), `PARENT_TOOLS` list (`:71+`).
- `app/agent/tools/parent_tool_executor.py`: `ParentToolExecutor` is a **@dataclass** with fields `conversation: Conversation, lead: Lead, sender_id: str, platform: str, user_message: str = ""` (`:215-234`). `execute(self, tool_name, tool_args)` dispatch chain (`:320-360`); `_get_camp_info` return shape `{"success": bool, "topic"|..., ...}` (`:387+`); camp registration gate `_is_camp_registration_open()` (`:396`).
- `app/agent/llm/parent_llm_engine.py`: `from app.config import settings` already imported (`:33`); `from app.agent.tools.parent_tools import PARENT_TOOLS` (`:32`); `system_prompt = _build_system_prompt()` (`:1991`, def `:2180`); `openai_service.chat_with_tools(messages=messages, tools=PARENT_TOOLS, ...)` (`:2042-2044`); `executor.execute(tool_name, parsed_args)` (`:2142`).
- `app/services/openai_service.py`: `chat_with_tools(*, messages, tools, tool_choice="auto", max_tokens=500, temperature=0.7)` — **keyword-only** (`:398-404`).
- `app/config.py`: `_parse_bool_optional(name, default)` (`:73`); flag defaults `~:313-364`; env parse `~:530-538`.
- `app/services/admin_config_service.py`: `get_active_sections()` (`:201`), `get_section(id)` (`:192`), `get_camp_registration_status()` open-values `_CAMP_REGISTRATION_OPEN_VALUES` (`:71`).
- Existing LLM-loop mock tests to mirror for the e2e test: `tests/test_adult_llm_engine.py`, `tests/test_adult_generic_discovery_2026_06_24.py`, `tests/corpus/test_live_conversation_corpus.py` (they monkeypatch `openai_service.chat_with_tools`).

---

## File Structure (Phase 1)

- `app/config.py` — `USE_DYNAMIC_PROGRAMS` flag.
- `app/agent/tools/parent_tools.py` — `TOOL_LIST_PROGRAMS`/`TOOL_GET_PROGRAM_INFO` + `DYNAMIC_PROGRAM_TOOLS` (separate list; flag-off surface unchanged).
- `app/agent/tools/parent_tool_executor.py` — **guarded** `_list_programs`/`_get_program_info` (denylist internal keys, gate registration URL, respect `status`, per-program log) + dispatch branches.
- `app/agent/llm/parent_llm_engine.py` — `build_active_tools(flag)` + flag-gated `_dynamic_programs_prompt_suffix()` so the LLM knows the generic tools exist.
- `app/services/conversation_service.py` — `_match_active_program_segment(message_text)` consulted before `_classify_segment` (data-driven routing; fixes the BLOCKER).
- `tests/test_dynamic_programs.py` — unit + **end-to-end** (via `process_message`, mocked `chat_with_tools`) + routing tests.
- `evals/cases.py` — one NEW eval case for a dynamic program (grammar-scored).

---

## PHASE 1 — A new PARENT-type admin program is answerable END-TO-END (`USE_DYNAMIC_PROGRAMS`)

### Task 1: Add the `USE_DYNAMIC_PROGRAMS` flag

**Files:** Modify `app/config.py` (class default `~:364`, env parse `~:538`); Test `tests/test_dynamic_programs.py`.
**Interfaces:** Produces `settings.USE_DYNAMIC_PROGRAMS: bool` (default `False`), env `USE_DYNAMIC_PROGRAMS`.

- [ ] **Step 1: Failing test** (no `importlib.reload` — `from_env` reads env at call time)

```python
# tests/test_dynamic_programs.py
def test_dynamic_programs_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_DYNAMIC_PROGRAMS is False


def test_dynamic_programs_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_DYNAMIC_PROGRAMS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_DYNAMIC_PROGRAMS is True
```

- [ ] **Step 2: Run — expect FAIL** `python -m pytest tests/test_dynamic_programs.py -q` → `AttributeError: USE_DYNAMIC_PROGRAMS`.
- [ ] **Step 3: Class default** (after `USE_ADULT_LLM_ENGINE: bool = True`, ~`:364`)

```python
    # Dynamic Programs (2026-07): offer the PARENT engine generic
    # list_programs/get_program_info tools + data-driven routing so an
    # admin-panel program is answerable with no code change. OFF ⇒ identical.
    USE_DYNAMIC_PROGRAMS: bool = False
```

- [ ] **Step 4: Env parse** (next to `USE_ADULT_LLM_ENGINE=_parse_bool_optional(...)`, ~`:538`)

```python
            USE_DYNAMIC_PROGRAMS=_parse_bool_optional("USE_DYNAMIC_PROGRAMS", False),
```

- [ ] **Step 5: Run — expect PASS.** `python -m pytest tests/test_dynamic_programs.py -q`
- [ ] **Step 6: Commit** `git commit -am "feat(config): USE_DYNAMIC_PROGRAMS flag (default off)"`

---

### Task 2: Generic tool schemas (data only)

**Files:** Modify `app/agent/tools/parent_tools.py`; Test `tests/test_dynamic_programs.py`.
**Interfaces:** Produces `TOOL_LIST_PROGRAMS="list_programs"`, `TOOL_GET_PROGRAM_INFO="get_program_info"`, `DYNAMIC_PROGRAM_TOOLS: list[dict]`; both names added to `ALLOWED_TOOL_NAMES`. Kept OUT of `PARENT_TOOLS` (flag-off surface unchanged).

- [ ] **Step 1: Failing test**

```python
def test_dynamic_program_tools_wellformed_and_not_in_base():
    from app.agent.tools import parent_tools as pt
    names = {t["function"]["name"] for t in pt.DYNAMIC_PROGRAM_TOOLS}
    assert names == {"list_programs", "get_program_info"}
    assert {"list_programs", "get_program_info"} <= pt.ALLOWED_TOOL_NAMES
    assert "get_program_info" not in {t["function"]["name"] for t in pt.PARENT_TOOLS}
    gpi = next(t for t in pt.DYNAMIC_PROGRAM_TOOLS if t["function"]["name"] == "get_program_info")
    assert gpi["function"]["parameters"]["required"] == ["program_id"]
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: DYNAMIC_PROGRAM_TOOLS`).
- [ ] **Step 3: Constants** (after `TOOL_CHECK_CONSULTATION_SLOT = "check_consultation_slot"`, ~`:44`)

```python
TOOL_LIST_PROGRAMS = "list_programs"
TOOL_GET_PROGRAM_INFO = "get_program_info"
```

- [ ] **Step 4: Register in `ALLOWED_TOOL_NAMES`** (add two members to the frozenset literal ~`:46-55`)

```python
    TOOL_CHECK_CONSULTATION_SLOT,
    TOOL_LIST_PROGRAMS,
    TOOL_GET_PROGRAM_INFO,
})
```

- [ ] **Step 5: Append `DYNAMIC_PROGRAM_TOOLS` at end of module**

```python
DYNAMIC_PROGRAM_TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": TOOL_LIST_PROGRAMS,
        "description": (
            "Return the currently ACTIVE programs the company offers "
            "(program_id + Georgian name + type). Call this before answering "
            "about any program you are not certain is offered. Only programs "
            "returned here exist — never invent one."
        ),
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": TOOL_GET_PROGRAM_INFO,
        "description": (
            "Return authoritative facts about ONE program from admin config. "
            "Use for ANY question about a program other than the 2026 summer "
            "camp (which still uses get_camp_info). program_id MUST come from "
            "list_programs. topic is a free-form hint; answer ONLY from the "
            "returned facts, never from memory. If success is false, tell the "
            "user the program is unavailable and offer the manager — do not invent."
        ),
        "parameters": {"type": "object", "properties": {
            "program_id": {"type": "string", "description": "id from list_programs"},
            "topic": {"type": "string", "description": "optional free-form topic hint"},
        }, "required": ["program_id"]},
    }},
]
```

- [ ] **Step 6: Run — expect PASS.** **Step 7: Commit** `git commit -am "feat(tools): generic program tool schemas"`

---

### Task 3: Guarded executor handlers (the security boundary)

**Files:** Modify `app/agent/tools/parent_tool_executor.py`; Test `tests/test_dynamic_programs.py`.
**Interfaces:** Consumes `TOOL_LIST_PROGRAMS`/`TOOL_GET_PROGRAM_INFO`, `admin_config_service.get_active_sections()`/`get_section()`. Produces `_list_programs(args)`, `_get_program_info(args)` returning `{"success": bool, ...}` mirroring `_get_camp_info`. **Guards:** only `status=="active"` programs; a `registration_url` is surfaced ONLY when the section's `registration_status` is open; operator-internal keys are never exposed.

- [ ] **Step 1: Failing tests** (correct dataclass ctor)

```python
def _fake_sections():
    return [
        {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
         "status": "active", "price_text": "300 ლარი", "age_min": 8, "age_max": 14,
         "description_full": "ბავშვები ისწავლიან რობოტების აწყობას და პროგრამირებას.",
         "registration_url": "https://x/y", "registration_status": "closed",
         "auto_dm_template_id": "robo_dm", "hashtags": ["რობოტიკა", "robotics"]},
        {"id": "old", "name": "ძველი", "type": "kids_program", "status": "hidden"},
    ]


def _make_executor():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.lead import Lead
    from app.models.conversation import Conversation
    conv = Conversation(sender_id="t", platform="facebook")
    # ParentToolExecutor is a dataclass: conversation, lead, sender_id, platform, user_message=""
    return ParentToolExecutor(conversation=conv, lead=Lead(), sender_id="t", platform="facebook")


def test_list_programs_active_only(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [s for s in _fake_sections() if s["status"] == "active"])
    out = _make_executor().execute("list_programs", {})
    assert out["success"] and {p["program_id"] for p in out["programs"]} == {"robotics_club"}


def test_get_program_info_guards_and_facts(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: next((s for s in _fake_sections() if s["id"] == pid), None))
    out = _make_executor().execute("get_program_info", {"program_id": "robotics_club", "topic": "price"})
    assert out["success"] is True
    assert out["facts"]["price_text"] == "300 ლარი"
    assert "პროგრამირებას" in out["facts"]["description_full"]
    # registration_status is closed → the URL must NOT leak
    assert "registration_url" not in out["facts"]
    # operator-internal keys never exposed
    assert "auto_dm_template_id" not in out["facts"] and "hashtags" not in out["facts"]


def test_get_program_info_unknown_and_inactive(monkeypatch):
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: next((s for s in _fake_sections() if s["id"] == pid), None))
    ex = _make_executor()
    assert ex.execute("get_program_info", {"program_id": "nope"})["reason"] == "unknown_program"
    assert ex.execute("get_program_info", {"program_id": "old"})["reason"] == "program_not_active"
```

_(If `Conversation(sender_id=..., platform=...)` needs more required fields, read `app/models/conversation.py:38+` and pass them; the asserted behavior is independent of the ctor.)_

- [ ] **Step 2: Run — expect FAIL** (`unknown_tool`).
- [ ] **Step 3: Import constants** (with the other `from app.agent.tools.parent_tools import ...`)

```python
from app.agent.tools.parent_tools import TOOL_LIST_PROGRAMS, TOOL_GET_PROGRAM_INFO
```

- [ ] **Step 4: Dispatch branches** (after the `elif tool_name == TOOL_CHECK_CONSULTATION_SLOT:` block ~`:353`)

```python
            elif tool_name == TOOL_LIST_PROGRAMS:
                result = self._list_programs(args)
            elif tool_name == TOOL_GET_PROGRAM_INFO:
                result = self._get_program_info(args)
```

- [ ] **Step 5: Guarded handlers** (near `_get_camp_info`, ~`:387`)

```python
    # Operator-internal keys the LLM must never see or surface to a user.
    _PROGRAM_INTERNAL_KEYS = frozenset({
        "id", "status", "registration_status", "auto_dm_template_id",
        "public_reply_template_id", "facebook_post_ids", "facebook_post_id",
        "post_ids", "post_id", "hashtags", "cta_text", "lead_type",
        "handoff_enabled",
    })
    # Keys gated behind an OPEN registration/booking status.
    _PROGRAM_REGISTRATION_KEYS = frozenset({"registration_url"})
    _REGISTRATION_OPEN_VALUES = frozenset({
        "open", "active", "enabled", "on", "true", "1", "yes",
    })

    def _list_programs(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.services import admin_config_service
        try:
            sections = admin_config_service.get_active_sections()
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("[parent_executor] list_programs failed: %s", exc)
            return {"success": False, "reason": "config_error"}
        programs = [
            {"program_id": s.get("id"), "name": s.get("name"), "type": s.get("type")}
            for s in sections if s.get("id")
        ]
        logger.info("[parent_tool] list_programs count=%d", len(programs))
        return {"success": True, "programs": programs}

    def _get_program_info(self, args: dict[str, Any]) -> dict[str, Any]:
        program_id = str(args.get("program_id") or "").strip()
        if not program_id:
            return {"success": False, "reason": "missing_program_id"}
        from app.services import admin_config_service
        try:
            section = admin_config_service.get_section(program_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("[parent_executor] get_program_info failed: %s", exc)
            return {"success": False, "reason": "config_error"}
        if not isinstance(section, dict):
            return {"success": False, "reason": "unknown_program"}
        status = (section.get("status") or "").strip().lower()
        if status != "active":
            return {"success": False, "reason": "program_not_active", "status": status}
        reg_status = str(section.get("registration_status") or "open").strip().lower()
        reg_open = reg_status in self._REGISTRATION_OPEN_VALUES
        facts: dict[str, Any] = {}
        for key, value in section.items():
            if key in self._PROGRAM_INTERNAL_KEYS:
                continue
            if key in self._PROGRAM_REGISTRATION_KEYS and not reg_open:
                continue
            if value in (None, "", [], {}):
                continue
            facts[key] = value
        logger.info(
            "[parent_tool] get_program_info program_id=%s status=%s reg_open=%s fields=%d",
            program_id, status, reg_open, len(facts),
        )
        return {
            "success": True, "program_id": program_id,
            "topic": str(args.get("topic") or "all"),
            "name": section.get("name"), "type": section.get("type"),
            "registration_open": reg_open, "facts": facts,
        }
```

- [ ] **Step 6: Run — expect PASS** (list + guards + unknown/inactive). **Step 7: Commit** `git commit -am "feat(tools): guarded generic program executor handlers"`

---

### Task 4: Wire tools + prompt hint into the LLM loop (flag-gated)

**Files:** Modify `app/agent/llm/parent_llm_engine.py` (import ~`:32`; helper near top; `chat_with_tools` call ~`:2044`; `_build_system_prompt` ~`:2180`); Test `tests/test_dynamic_programs.py`.
**Interfaces:** Produces `build_active_tools(use_dynamic: bool) -> list[dict]` and `_dynamic_programs_prompt_suffix() -> str` (empty when flag off or no non-camp active programs).

- [ ] **Step 1: Failing test**

```python
def test_build_active_tools_respects_flag():
    from app.agent.llm.parent_llm_engine import build_active_tools
    from app.agent.tools.parent_tools import PARENT_TOOLS, DYNAMIC_PROGRAM_TOOLS
    off = [t["function"]["name"] for t in build_active_tools(False)]
    assert off == [t["function"]["name"] for t in PARENT_TOOLS]
    on = {t["function"]["name"] for t in build_active_tools(True)}
    assert {"list_programs", "get_program_info"} <= on
    assert len(build_active_tools(True)) == len(PARENT_TOOLS) + len(DYNAMIC_PROGRAM_TOOLS)
```

- [ ] **Step 2: Run — expect FAIL** (`ImportError: build_active_tools`).
- [ ] **Step 3: Import** (`:32`) `from app.agent.tools.parent_tools import PARENT_TOOLS, DYNAMIC_PROGRAM_TOOLS`
- [ ] **Step 4: Helpers** (module level, after imports)

```python
def build_active_tools(use_dynamic: bool) -> list[dict]:
    """Flag-off ⇒ exactly PARENT_TOOLS (byte-identical). Flag-on ⇒ + generic program tools."""
    tools = list(PARENT_TOOLS)
    if use_dynamic:
        tools = tools + DYNAMIC_PROGRAM_TOOLS
    return tools


def _dynamic_programs_prompt_suffix() -> str:
    """Tell the LLM the generic tools exist and list active non-camp programs.
    Empty string when the flag is off or there are none (so flag-off prompt is unchanged)."""
    if not getattr(settings, "USE_DYNAMIC_PROGRAMS", False):
        return ""
    try:
        from app.services import admin_config_service
        others = [
            s for s in admin_config_service.get_active_sections()
            if s.get("id") != "summer_camp"
        ]
    except Exception:
        return ""
    if not others:
        return ""
    names = ", ".join(f"{s.get('name')} (id: {s.get('id')})" for s in others if s.get("id"))
    return (
        "\n\n[დინამიური პროგრამები] გარდა ბანაკისა, აქტიურია: " + names +
        ". ამ პროგრამებზე ნებისმიერ კითხვაზე ჯერ გამოიძახე list_programs, "
        "შემდეგ get_program_info(program_id). ფაქტები მხოლოდ ხელსაწყოს პასუხიდან "
        "აიღე — არასდროს მოიგონო."
    )
```

- [ ] **Step 5: Use `build_active_tools` at the `chat_with_tools` call (~`:2044`)** — change ONLY the `tools=` argument; keep `messages=messages` and every other kwarg exactly as-is (`chat_with_tools` is keyword-only):

```python
                tools=build_active_tools(settings.USE_DYNAMIC_PROGRAMS),
```

- [ ] **Step 6: Append the suffix in `_build_system_prompt` (~`:2180`)** — at the return, add the suffix so flag-off returns the identical string:

```python
    return base_prompt + _dynamic_programs_prompt_suffix()
```

_(Read `_build_system_prompt` first; bind whatever it currently returns to `base_prompt` and append. Flag-off ⇒ suffix is `""` ⇒ identical output.)_

- [ ] **Step 7: Run — expect PASS.** **Step 8: Commit** `git commit -am "feat(engine): offer generic program tools + prompt hint under USE_DYNAMIC_PROGRAMS"`

---

### Task 5: Data-driven routing — a new program REACHES the parent engine (fixes the BLOCKER)

**Files:** Modify `app/services/conversation_service.py` (helper near the keyword blocks; consult it at `:875`); Test `tests/test_dynamic_programs.py`.
**Interfaces:** Produces `_match_active_program_segment(message_text) -> "PARENT"|"ADULT"|None` (None when flag off or no match). Consumed at the fresh-classification line so a message naming an active program routes by that program's `type`, overriding incidental keyword collisions (e.g. "კლუბ"→ADULT).

**Why:** verified — `_classify_segment` (`:339-370`) sends "რობოტიკის კლუბი" to ADULT (stem "კლუბ", `:274`); other novel programs go to UNCLEAR. Either way the parent engine + new tools are never reached. This task closes that gap.

- [ ] **Step 1: Failing tests**

```python
def test_match_active_program_segment(monkeypatch):
    from app.services import conversation_service as cs, admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [
        {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
         "status": "active", "hashtags": ["რობოტიკა", "robotics"]},
    ])
    # flag off → None (no behavior change)
    monkeypatch.setattr(cs.settings, "USE_DYNAMIC_PROGRAMS", False, raising=False)
    assert cs._match_active_program_segment("რობოტიკა რა ღირს?") is None
    # flag on → matched by hashtag/name → PARENT (overrides the incidental "კლუბ"→ADULT)
    monkeypatch.setattr(cs.settings, "USE_DYNAMIC_PROGRAMS", True, raising=False)
    assert cs._match_active_program_segment("რობოტიკის კლუბი მაინტერესებს") == "PARENT"
    assert cs._match_active_program_segment("ამინდი როგორია") is None
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError: _match_active_program_segment`).
- [ ] **Step 3: Add the helper** (below `_classify_segment`, ~`:371`)

```python
def _match_active_program_segment(message_text: str) -> str | None:
    """USE_DYNAMIC_PROGRAMS: if the message names an ACTIVE admin program
    (by name token or hashtag), return the segment for that program's type —
    adult_events → ADULT, otherwise PARENT. None when flag off / no match, so
    flag-off routing is byte-identical. Heuristic (substring); Phase 2 replaces
    it with the app/domain/decision resolver."""
    if not getattr(settings, "USE_DYNAMIC_PROGRAMS", False):
        return None
    text = (message_text or "").lower()
    if not text:
        return None
    try:
        from app.services import admin_config_service
        sections = admin_config_service.get_active_sections()
    except Exception:  # pragma: no cover - defensive
        return None
    for s in sections:
        name = (s.get("name") or "").lower()
        tags = [str(t).lower().lstrip("#") for t in (s.get("hashtags") or [])]
        if (name and name in text) or any(t and t in text for t in tags):
            return "ADULT" if (s.get("type") == "adult_events") else "PARENT"
    return None
```

- [ ] **Step 4: Consult it at fresh classification (`:875`)** — change `conversation.segment = _classify_segment(message_text)` to:

```python
            conversation.segment = (
                _match_active_program_segment(message_text)
                or _classify_segment(message_text)
            )
```

_(Only the fresh-classification branch `:869-875`; leave the sticky-segment override logic `:884-921` untouched — a returning known-program user is a Phase-2 edge case. Flag-off ⇒ helper returns None ⇒ identical.)_

- [ ] **Step 5: Verify existing programs still classify the same** — add a regression assert:

```python
def test_existing_programs_unchanged_routing(monkeypatch):
    from app.services import conversation_service as cs, admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [
        {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
         "status": "active", "hashtags": ["ბანაკი", "camp"]},
        {"id": "adult_events", "name": "ზრდასრულთა ღონისძიება", "type": "adult_events",
         "status": "active", "hashtags": ["ღონისძიება"]},
    ])
    monkeypatch.setattr(cs.settings, "USE_DYNAMIC_PROGRAMS", True, raising=False)
    assert cs._match_active_program_segment("ბანაკი მაინტერესებს") == "PARENT"
    assert cs._match_active_program_segment("ღონისძიება როდისაა") == "ADULT"
```

- [ ] **Step 6: Run — expect PASS.** **Step 7: Commit** `git commit -am "feat(routing): data-driven segment for active admin programs (flag-gated)"`

---

### Task 6: End-to-end acceptance via `process_message` (mocked LLM)

**Files:** Test `tests/test_dynamic_programs.py`.
**Interfaces:** Consumes everything above. Mirrors the `chat_with_tools` monkeypatch pattern in `tests/test_adult_llm_engine.py`.

- [ ] **Step 1: Write the e2e test** — inject a synthetic program, force the engine on, stub OpenAI to (a) call `get_program_info`, then (b) answer from the tool result. Assert the reply carries the program's fact and that the generic tool was actually offered.

```python
def test_e2e_new_program_answered(monkeypatch):
    from app.services import conversation_service as cs, admin_config_service
    from app.agent.llm import parent_llm_engine
    from app import config as app_config
    synthetic = {"id": "robotics_club", "name": "რობოტიკის კლუბი",
                 "type": "kids_program", "status": "active", "price_text": "300 ლარი",
                 "description_full": "რობოტების აწყობა და პროგრამირება.",
                 "hashtags": ["რობოტიკა", "robotics"]}
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [synthetic])
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: synthetic if pid == "robotics_club" else None)
    for mod in (cs, parent_llm_engine, app_config):
        monkeypatch.setattr(mod.settings, "USE_DYNAMIC_PROGRAMS", True, raising=False)
        monkeypatch.setattr(mod.settings, "USE_PARENT_LLM_ENGINE", True, raising=False)

    offered_tool_names = {}

    def fake_chat_with_tools(*, messages, tools, **kw):
        offered_tool_names["names"] = {t["function"]["name"] for t in tools}
        # First call → the model asks for get_program_info; second → final answer.
        if not any(m.get("role") == "tool" for m in messages):
            return _tool_call_response("get_program_info", {"program_id": "robotics_club"})
        return _final_text_response("რობოტიკის კლუბი ღირს 300 ლარი.")

    # _tool_call_response / _final_text_response: build minimal objects shaped like
    # the OpenAI response the engine reads (choices[0].message with .tool_calls or
    # .content). COPY the exact shape from tests/test_adult_llm_engine.py's existing
    # chat_with_tools stub so it matches what parent_llm_engine expects.
    monkeypatch.setattr("app.services.openai_service.chat_with_tools", fake_chat_with_tools)

    reply = cs.process_message(sender_id="u1", message_text="რობოტიკის კლუბი რა ღირს?",
                               platform="facebook", page_id="p1")

    assert "300" in reply                                   # answered from program data
    assert "get_program_info" in offered_tool_names["names"]  # generic tool was offered
```

- [ ] **Step 2: Run — expect PASS** (fix the response-shape helpers against the real engine reads if needed).
- [ ] **Step 3: Commit** `git commit -am "test: e2e — new admin program answered end-to-end"`

---

### Task 7: New eval case + zero-regression + read-only eval gate

**Files:** Modify `evals/cases.py` (one new dynamic-program case, grammar-scored); verification only otherwise.

- [ ] **Step 1: Add a dynamic-program eval case** — mirror an existing `evals/cases.py` case (read one first for the exact schema). It must: inject a synthetic active program, ask a Georgian question NOT expressible via the old 7 camp topics ("ბავშვი რას ისწავლის?"), and assert the answer uses the program's `description_full` and stays grammatical (the harness's Georgian-Grammar judge). Gate it behind `USE_DYNAMIC_PROGRAMS`.
- [ ] **Step 2: Full suite, flags OFF** `python -m pytest -q` — no NEW failures vs the `HANDOFF.md` known-good count (`4006 passed / 28 skipped`; pre-existing date/data-bomb failures excluded).
- [ ] **Step 3: Full suite, flag ON** `USE_DYNAMIC_PROGRAMS=true python -m pytest -q` — same pass set + the new Phase-1 tests green.
- [ ] **Step 4: Eval gate, READ-ONLY**

```bash
cp evals/baseline.json /tmp/baseline_ref.json
python -m evals.run_evals            # add --llm --judge if keys present
git diff --exit-code evals/baseline.json   # MUST be unchanged; if rewritten, restore:
#   cp /tmp/baseline_ref.json evals/baseline.json
```
Expected: score ≥ 90/100; Georgian Grammar not below its baseline; `baseline.json` unchanged in git.

- [ ] **Step 5: Commit** `git commit -am "test(evals): dynamic-program case; Phase 1 verified"`

**Phase 1 DoD:** Tasks 1–7 green; a program existing ONLY in admin config is **routed → answered end-to-end** in Georgian (incl. an off-old-whitelist question); a closed-registration program never leaks its URL and internal keys never surface; `USE_DYNAMIC_PROGRAMS=false` ⇒ routing, tool surface, prompt, and outputs byte-identical; `ProgramId`/registry/resolver untouched; `evals/baseline.json` unchanged, score ≥ 90, grammar not regressed.

---

## PHASE 1b — ADULT-type dynamic programs
_Scope honesty: Phase 1 covers PARENT-type programs. Mirror it for the adult persona: add `list_programs`/`get_program_info` (+ guards) to `app/agent/tools/adult_tools.py` / `adult_tool_executor.py`, offer them in `adult_llm_engine.py`, and let `_match_active_program_segment` route `type=="adult_events"` programs (already returns "ADULT"). Same flag; same e2e + eval discipline._

## PHASE 2 — Adaptivity hardening + generalize `app/domain/decision/*`
_Replace the Task-5 substring heuristic with the already-built-but-unwired `app/domain/decision/program_resolver.py` fed from `sections.yaml` (name/hashtags + optional new `aliases`), and route more off-whitelist questions through the LLM engine grounded on section data instead of the ~34 `_maybe_handle_*` interceptors in `app/flows/parent_flow.py`. Flag `USE_DYNAMIC_PROGRAM_ROUTING`. Prior-art template: `app/reasoning/reasoning_layer.py` (`USE_REASONING_LAYER`). Acceptance: the `evals/` adaptivity metric improves vs 90/100 with grammar ~100._

## PHASE 3 — Skills layer (`USE_SKILLS`)
_A registry of `SKILL.md` capability packs (objection-handling, price-framing, new-program-onboarding) selected per situation and injected into `_build_system_prompt`; files are data, selection is code (mirror the tools/executor split). Off ⇒ prompt unchanged. Acceptance: adding a `SKILL.md` changes an eval scenario with no Python change._

## PHASE 4 — Durable per-lead memory (`USE_LEAD_MEMORY`) — REQUIRED
_Persist per-lead facts (child age, interests, prior objections) keyed by a stable lead identity (not the 8-day session key) on `redis_state_service` (or a durable store), populated from the existing `parent_llm_engine` capture seams; inject a compact `memory_summary(lead)` into `_build_system_prompt`. Off ⇒ no reads/writes. Acceptance: a returning lead's known child age is not re-asked in a NEW conversation; PII masking preserved._

## PHASE 5 — Bounded learning loop (`USE_LEARNING`) — REQUIRED
_Log per-turn outcomes at the `conversation_service` chokepoint; an operator review queue promotes good answers into `data/admin_config/approved_answers.yaml` that the engine consults as an extra grounded source; feed the `evals/` harness. Bounded/safe: grows a REVIEWED store; never auto-mutates prompts or deploys. Off ⇒ no logging/reads._

---

## Self-Review — critique → fix mapping

| Critique | Severity | Fixed in |
|---|---|---|
| #1 New program never reaches the engine (routing sends "კლუბ"→ADULT / unknown→UNCLEAR) | 🔴 BLOCKER | **Task 5** (`_match_active_program_segment` at `:875`) + **Task 6** end-to-end acceptance via `process_message` |
| #2 Generic tool bypasses lifecycle/registration guards (URL leak) | 🟠 | **Task 3** — `status`-gated, `registration_status`-gated URL, internal-key denylist |
| #3 Field whitelist didn't match real non-camp sections | 🟠 | **Task 3** — denylist + all non-empty fields (future-proof for new fields) |
| #4 Grammar-drop risk; eval couldn't measure new capability | 🟠 | **Task 7** — new grammar-scored eval case for a dynamic program |
| #5 Scope overreach (parent-only claimed as "any program") | 🟠 | **Phase 1b** — explicit adult-persona follow-on |
| #6 Wrong `ParentToolExecutor` ctor in tests | 🟡 | **Task 3** — correct dataclass kwargs (`conversation/lead/sender_id/platform`) |
| #7 `chat_with_tools(messages, ...)` breaks (keyword-only) | 🟡 | **Task 4 Step 5** — change only `tools=`, keep `messages=messages` |
| #8 `importlib.reload(app.config)` poisons global settings | 🟡 | **Task 1** — `Settings()`/`from_env()` + `monkeypatch`, no reload |
| #9 Theatrical `grep robotics_club` assertion | 🟡 | Removed; replaced by the Task 6 end-to-end behavioral assertion |
| #10 No per-program observability | 🟡 | **Task 3** — `logger.info` per `list_programs`/`get_program_info` call |
| LLM wouldn't know the generic tools exist (giant camp prompt) | added | **Task 4** — `_dynamic_programs_prompt_suffix()` |

**Open confirmations for the implementer (cheap reads, not blockers):** exact `Conversation`/`Lead` required fields (`app/models/*.py`); the exact OpenAI response object shape the engine reads (copy the stub from `tests/test_adult_llm_engine.py`); what `_build_system_prompt` currently returns (bind to `base_prompt`). All verified by reading the named function before editing.
