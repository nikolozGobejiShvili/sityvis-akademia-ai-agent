# Phase 3 — Skills Registry (`USE_SKILLS`) Implementation Plan (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the PARENT LLM engine a registry of operator/author-editable `SKILL.md` capability packs (objection-handling, price-framing, new-program-onboarding, …). The relevant pack(s) are selected **deterministically by situation** and injected into the system prompt, so a NEW capability is added by dropping a `SKILL.md` file — **zero Python change**. Files are data; selection is code (mirrors the Phase-1 tools/executor split and the Phase-5 approved-answers store/matcher).

**Architecture:** Additive, flag-gated on `USE_SKILLS` (default OFF). New `app/agent/skills/*.md` packs (YAML frontmatter + Markdown body) are read fresh + tolerantly by a new `app/services/skills_service.py` (parse → load → select). A new flag-gated `_skills_prompt_suffix(message, segment)` in `parent_llm_engine.py` appends the selected pack bodies to `_build_system_prompt`. **Flag OFF ⇒ suffix `""` ⇒ system prompt byte-identical.** PARENT-only in v1 (ADULT mirror is a documented residual). LLM stays OpenAI.

**Tech Stack:** Python 3.10 / FastAPI, `yaml` (already a dependency — `admin_config_service` imports it), pytest. No new dependency.

## Global Constraints

- **Flag OFF ⇒ byte-identical.** With `USE_SKILLS=False` (shipped default), `_skills_prompt_suffix(...)` returns `""`, so `_build_system_prompt()` output is unchanged char-for-char. The existing byte-exact tests that call `_build_system_prompt()` **zero-arg** (`tests/test_camp_age_bounds_migration_5a2_2026_06_22.py:59/66` assert `_build_system_prompt() == raw.format(...)`) MUST still pass — this is the load-bearing invariant.
- **Defaulted params only.** `_build_system_prompt` gains `(message: str = "", segment: str = "")` — the defaults keep every existing zero-arg caller and byte-exact test valid, exactly as `build_active_tools(use_dynamic, use_learning=False)` did in Phase 5. Do NOT make the params required.
- **Never raises on the reply path.** `skills_service.load_skills`/`select_skills` and `_skills_prompt_suffix` must swallow every exception and return `[]`/`""` — a malformed `SKILL.md` can never break a turn.
- **No new dependency.** Parse frontmatter with a manual `---` split + `yaml.safe_load` — do NOT add `python-frontmatter` or any package.
- **Additive, PARENT-only v1.** Only `parent_llm_engine._build_system_prompt` is touched. **`adult_llm_engine` ALSO has a `_build_system_prompt` (see `tests/test_planner_stabilization_2026_06_24.py:257`) — do NOT edit it.** ADULT injection is a documented Phase-3b residual. Do NOT wire skills into any other path.
- **Robust segment at the call site (C2).** The PARENT engine KNOWS its segment — pass the **literal `"PARENT"`**, NOT `conversation.segment`. Verified: `parent_flow.py:9956` sets `conversation.lead.segment = "PARENT"` (the LEAD's segment), so `conversation.segment` is not a reliable source at the engine; depending on it would let PARENT-only packs silently not fire.
- **Bounded injection.** `select_skills` returns at most `DEFAULT_SKILL_LIMIT = 2` packs (guard against prompt bloat / lost-in-the-middle). **The giant prompt is ALREADY near its own 56 KB cap** (`tests/test_parent_llm_engine.py:1848` asserts `< 56_000`, raised to "accept the current canonical size"), so at enablement injected packs eat scarce headroom — keep seed bodies SHORT; that cap test may need raising when the flag is turned on (flag-off it is unchanged and safe).
- **Committing NEW seed `app/agent/skills/*.md` is allowed** — they are new authored content, NOT the operator's live `data/admin_config/sections.yaml` or `evals/baseline.json` (those must NEVER be staged/overwritten).
- **Interpreter:** `.venv/Scripts/python.exe` for all test/eval runs (a bare `python` is a dep-less 3.14). **LOCAL-only** branch `feat/dynamic-programs` — commit, but never push/merge/deploy (GitHub auto-deploys the server). **No haiku** for any subagent.
- **Expected pre-existing failure:** the full suite has exactly ONE known-unrelated failure, `tests/test_approved_copy_service_2026_07_11.py::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`. Any OTHER failure is in scope.

---

## File Structure

**Create:**
- `app/services/skills_service.py` — `_parse_skill_md`, `load_skills`, `select_skills`, `SKILLS_DIR`, `DEFAULT_SKILL_LIMIT`. Read-only registry; no writer.
- `app/agent/skills/objection-handling.md` — seed pack (PARENT, price/hesitation objections).
- `app/agent/skills/new-program-onboarding.md` — seed pack (any-segment, answering about a newly-added program).
- `app/agent/skills/README.md` — one-paragraph operator note: how to add a pack (frontmatter fields + that no code change is needed). NOT loaded as a skill (loader skips `README.md`).

**Modify:**
- `app/config.py` — `USE_SKILLS: bool = False` class default (near the `USE_LEARNING` line 376) + `USE_SKILLS=_parse_bool_optional("USE_SKILLS", False)` in `from_env` (near line 553).
- `app/agent/llm/parent_llm_engine.py` — new `_skills_prompt_suffix(message="", segment="")`; `_build_system_prompt(message: str = "", segment: str = "")` appends it; call site (line 2043) passes `user_message` + `conversation.segment`.

**Test:**
- `tests/test_skills.py` — all Phase-3 tests (flag, parser, loader, selector, suffix, injection, e2e).

---

## Task 1: `USE_SKILLS` flag (default OFF)

**Files:**
- Modify: `app/config.py` (class default near `:376`; `from_env` near `:553`)
- Test: `tests/test_skills.py`

**Interfaces:**
- Produces: `settings.USE_SKILLS: bool` (default `False`); `Settings.from_env()` reads env `USE_SKILLS`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_skills.py
def test_use_skills_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_SKILLS is False


def test_use_skills_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_SKILLS", "true")
    from app.config import Settings
    assert Settings.from_env().USE_SKILLS is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: FAIL (`AttributeError: ... 'USE_SKILLS'`).

- [ ] **Step 3: Add the flag** — mirror `USE_LEARNING` exactly.

In `app/config.py`, next to `USE_LEARNING: bool = False` (line ~376):
```python
    USE_SKILLS: bool = False
```
In `Settings.from_env(...)`, next to the `USE_LEARNING=_parse_bool_optional("USE_LEARNING", False),` line (~553):
```python
            USE_SKILLS=_parse_bool_optional("USE_SKILLS", False),
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_skills.py
git commit -m "feat(config): USE_SKILLS flag (default off)"
```

---

## Task 2: `SKILL.md` parser + registry loader + seed packs

**Files:**
- Create: `app/services/skills_service.py`, `app/agent/skills/objection-handling.md`, `app/agent/skills/new-program-onboarding.md`, `app/agent/skills/README.md`
- Test: `tests/test_skills.py`

**Interfaces:**
- Produces:
  - `SKILLS_DIR: Path` — `app/agent/skills`.
  - `DEFAULT_SKILL_LIMIT: int = 2`.
  - `_parse_skill_md(text: str) -> tuple[dict, str]` — `(frontmatter_meta, body)`; no/blank frontmatter → `({}, text)`; never raises.
  - `load_skills() -> list[dict]` — fresh-read every `*.md` (except `README.md`); each → `{id, name, segment, status, priority, triggers, body}`; tolerant → `[]`; never raises.
- Consumes: `select_skills` (Task 3) reads `load_skills()` output shape.

- [ ] **Step 1: Write the seed packs.**

`app/agent/skills/objection-handling.md`:
```markdown
---
id: objection-handling
name: ფასის/ყოყმანის დაძლევა
segment: PARENT
status: active
priority: 20
triggers:
  - ძვირ
  - ფასი მაღალ
  - ვერ ვახერხებ
  - მიფიქრია
  - ეჭვი მაქვს
  - მოვიფიქრებ
---
როცა მშობელი ფასზე ან ღირებულებაზე ეჭვს გამოთქვამს:
- ჯერ თანაგრძნობა და პრობლემის აღიარება, არა თავდაცვა.
- დააკავშირე ფასი კონკრეტულ ღირებულებასთან (შვილის უნარები, გამოცდილება).
- საჭიროების შემთხვევაში ახსენე გადახდის შესაძლებლობა/განაწილება.
- არასოდეს დააჭირო („ბოლო ადგილები", „იჩქარეთ").
```

`app/agent/skills/new-program-onboarding.md`:
```markdown
---
id: new-program-onboarding
name: ახალ პროგრამაზე პასუხის გაცემა
segment: any
status: active
priority: 10
triggers:
  - ახალი პროგრამ
  - სხვა პროგრამ
  - კიდევ რა პროგრამ
---
როცა მომხმარებელი ბანაკის გარდა სხვა პროგრამას ეკითხება:
- ფაქტები მხოლოდ ხელსაწყოს პასუხიდან აიღე (list_programs → get_program_info), არასოდეს მეხსიერებიდან.
- თუ პროგრამა არ არსებობს, ღიად თქვი და შესთავაზე მენეჯერი — ნუ გამოიგონებ.
```

`app/agent/skills/README.md`:
```markdown
# Skills (capability packs)

Each `*.md` file here is a capability pack: YAML frontmatter
(`id`, `name`, `segment: PARENT|ADULT|any`, `status: active|hidden`,
`priority: <int>`, `triggers: [substrings]`) + a Markdown body of guidance.
When `USE_SKILLS` is on, the agent selects the best-matching active pack(s) by
trigger-substring match and injects the body into its system prompt.
**Adding a new pack needs NO code change** — drop a `SKILL.md` here.
`README.md` is ignored by the loader.
```

- [ ] **Step 2: Write the failing tests** (append to `tests/test_skills.py`).

```python
def test_parse_skill_md_frontmatter_and_body():
    from app.services.skills_service import _parse_skill_md
    meta, body = _parse_skill_md(
        "---\nid: x\nsegment: PARENT\ntriggers:\n  - ძვირ\n---\nსხეული აქ.\n"
    )
    assert meta["id"] == "x"
    assert meta["segment"] == "PARENT"
    assert meta["triggers"] == ["ძვირ"]
    assert body.strip() == "სხეული აქ."


def test_parse_skill_md_no_frontmatter_is_tolerant():
    from app.services.skills_service import _parse_skill_md
    meta, body = _parse_skill_md("plain body, no fence")
    assert meta == {}
    assert body == "plain body, no fence"


def test_parse_skill_md_malformed_never_raises():
    from app.services.skills_service import _parse_skill_md
    # unterminated fence + non-string
    assert _parse_skill_md("---\nnot closed") == ({}, "---\nnot closed")
    assert _parse_skill_md(None) == ({}, "")


def test_parse_skill_md_body_starting_with_dash_preserved():
    # critique M1: a body that starts with a markdown rule / bullet must survive
    from app.services.skills_service import _parse_skill_md
    meta, body = _parse_skill_md("---\nid: x\n---\n- პირველი პუნქტი\n- მეორე\n")
    assert meta["id"] == "x"
    assert body.startswith("- პირველი პუნქტი")


def test_load_skills_reads_seed_packs():
    from app.services import skills_service
    skills = skills_service.load_skills()
    ids = {s["id"] for s in skills}
    assert "objection-handling" in ids
    assert "new-program-onboarding" in ids
    # README.md is never loaded as a skill
    assert "README" not in ids
    # shape
    oh = next(s for s in skills if s["id"] == "objection-handling")
    assert oh["segment"] == "PARENT"
    assert oh["status"] == "active"
    assert isinstance(oh["priority"], int)
    assert "ძვირ" in oh["triggers"]
    assert oh["body"].strip()


def test_load_skills_missing_dir_is_graceful(monkeypatch, tmp_path):
    from app.services import skills_service
    monkeypatch.setattr(skills_service, "SKILLS_DIR", tmp_path / "nope")
    assert skills_service.load_skills() == []


def test_load_skills_malformed_file_skipped(monkeypatch, tmp_path):
    from app.services import skills_service
    d = tmp_path / "skills"
    d.mkdir()
    (d / "good.md").write_text(
        "---\nid: good\nsegment: any\ntriggers:\n  - აბ\n---\nსხეული", encoding="utf-8"
    )
    (d / "bad.md").write_text("\x00\x01 not yaml frontmatter", encoding="utf-8")
    monkeypatch.setattr(skills_service, "SKILLS_DIR", d)
    ids = {s["id"] for s in skills_service.load_skills()}
    assert "good" in ids  # the bad file must not crash the whole load
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.skills_service`).

- [ ] **Step 4: Implement `app/services/skills_service.py`** (mirror `admin_config_service._safe_load_yaml`'s tolerant fresh read + `approved_answers_service` house style).

```python
"""Skills registry (Phase 3, USE_SKILLS).

Reads operator/author-editable capability packs from ``app/agent/skills/*.md``
(YAML frontmatter + Markdown body), fresh each call, and selects the most
relevant active pack(s) for a turn. Read-only: the operator is the sole writer
of the pack files. Every public function is tolerant and NEVER raises.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# app/services/skills_service.py -> parents[1] == app/ ; skills live in app/agent/skills
SKILLS_DIR: Path = Path(__file__).resolve().parents[1] / "agent" / "skills"
DEFAULT_SKILL_LIMIT: int = 2


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_skill_md(text: str) -> tuple[dict, str]:
    """Split a SKILL.md into (frontmatter dict, body).

    Line-based (fixes critique M1 — no fragile ``lstrip("-")``): the first
    non-blank line must be exactly ``---``; the frontmatter is every line up to
    the next ``---`` line; the body is the remainder. Tolerant: not a string →
    ({}, ""); no opening fence or no closing fence → ({}, original text);
    frontmatter that isn't a mapping → ({}, body). Never raises. A body may
    legitimately start with a markdown ``---`` rule or a ``-`` bullet — those
    are preserved.
    """
    try:
        if not isinstance(text, str):
            return {}, ""
        lines = text.splitlines(keepends=True)
        i = 0
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i >= len(lines) or lines[i].strip() != "---":
            return {}, text
        close = -1
        for j in range(i + 1, len(lines)):
            if lines[j].strip() == "---":
                close = j
                break
        if close == -1:
            return {}, text
        fm_block = "".join(lines[i + 1:close])
        body = "".join(lines[close + 1:]).lstrip("\n")
        meta = yaml.safe_load(fm_block)
        if not isinstance(meta, dict):
            return {}, body
        return meta, body
    except Exception:  # pragma: no cover - defensive
        return {}, text if isinstance(text, str) else ""


def load_skills() -> list[dict]:
    """Return every ``app/agent/skills/*.md`` (except README.md) as a normalized
    dict {id, name, segment, status, priority, triggers, body}. Fresh read every
    call (operator edits take effect without a restart). Tolerant → [] on any
    error; a single malformed file is skipped, not fatal. Never raises.
    """
    try:
        skills: list[dict] = []
        if not SKILLS_DIR.is_dir():
            return []
        for path in sorted(SKILLS_DIR.glob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            meta, body = _parse_skill_md(text)
            if not isinstance(meta, dict):
                continue
            raw_triggers = meta.get("triggers")
            triggers = (
                [str(t).lower() for t in raw_triggers if t]
                if isinstance(raw_triggers, list)
                else []
            )
            sid = str(meta.get("id") or path.stem)
            skills.append({
                "id": sid,
                "name": str(meta.get("name") or sid),
                "segment": str(meta.get("segment") or "any"),
                "status": str(meta.get("status") or "active"),
                "priority": _safe_int(meta.get("priority"), 0),
                "triggers": triggers,
                "body": body if isinstance(body, str) else "",
            })
        return skills
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[skills] load_skills failed: %s", exc)
        return []
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: PASS (all Task-1 + Task-2 tests).

- [ ] **Step 6: Commit**

```bash
git add app/services/skills_service.py app/agent/skills/ tests/test_skills.py
git commit -m "feat(skills): SKILL.md parser + registry loader + seed packs"
```

---

## Task 3: `select_skills` matcher

**Files:**
- Modify: `app/services/skills_service.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Produces: `select_skills(message: str, segment: str, *, limit: int = DEFAULT_SKILL_LIMIT) -> list[dict]` — lowercased trigger-substring scoring (mirrors `approved_answers_service.find_approved_answer`): active-status only; segment exact-match or `"any"`; skip triggers `<3` chars; require score `≥1`; sort by `(score, priority)` descending; return top `limit`. Never raises.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_skills.py`).

```python
def _mk_skill(**kw):
    base = {"id": "s", "name": "S", "segment": "PARENT", "status": "active",
            "priority": 0, "triggers": ["ძვირ"], "body": "ტანი"}
    base.update(kw)
    return base


def test_select_skills_trigger_and_segment_hit(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(id="a", triggers=["ძვირ"])])
    got = ss.select_skills("ეს ძვირია ცოტა", "PARENT")
    assert [s["id"] for s in got] == ["a"]


def test_select_skills_no_hit_returns_empty(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(triggers=["ძვირ"])])
    assert ss.select_skills("გამარჯობა", "PARENT") == []


def test_select_skills_hidden_never_selected(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(status="hidden", triggers=["ძვირ"])])
    assert ss.select_skills("ძვირია", "PARENT") == []


def test_select_skills_segment_mismatch_and_any(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [
        _mk_skill(id="p", segment="PARENT", triggers=["ძვირ"]),
        _mk_skill(id="a", segment="any", triggers=["ძვირ"]),
        _mk_skill(id="d", segment="ADULT", triggers=["ძვირ"]),
    ])
    ids = {s["id"] for s in ss.select_skills("ძვირია", "PARENT")}
    assert ids == {"p", "a"}  # ADULT-only excluded; "any" matches


def test_select_skills_short_trigger_never_matches_alone(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [_mk_skill(triggers=["აბ"])])  # 2-char
    assert ss.select_skills("აბგ დეფ", "PARENT") == []


def test_select_skills_bounded_and_ranked(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: [
        _mk_skill(id="low", priority=1, triggers=["ძვირ"]),
        _mk_skill(id="hi", priority=99, triggers=["ძვირ"]),
        _mk_skill(id="two", priority=5, triggers=["ძვირ", "ფასი მაღალ"]),
    ])
    got = ss.select_skills("ძვირია და ფასი მაღალია", "PARENT", limit=2)
    # "two" scores 2 (both triggers) → first; then higher-priority of the score-1 pair
    assert [s["id"] for s in got] == ["two", "hi"]


def test_select_skills_never_raises(monkeypatch):
    from app.services import skills_service as ss
    monkeypatch.setattr(ss, "load_skills", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ss.select_skills("ძვირია", "PARENT") == []
    assert ss.select_skills(None, None) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: FAIL (`AttributeError: ... 'select_skills'`).

- [ ] **Step 3: Implement `select_skills`** (append to `app/services/skills_service.py`).

```python
def select_skills(
    message: str, segment: str, *, limit: int = DEFAULT_SKILL_LIMIT
) -> list[dict]:
    """Deterministically pick the most relevant ACTIVE skills for a turn.

    Lowercase the message; among active skills whose segment matches ``segment``
    or is ``"any"``, score by counting triggers (>=3 chars) that are substrings
    of the message; keep score>=1; sort by (score, priority) descending; return
    the top ``limit``. Never raises → [] on any error.
    """
    try:
        low = (message or "").lower().strip()
        if not low:
            return []
        seg = (segment or "").strip() or "any"
        scored: list[tuple[int, int, dict]] = []
        for sk in load_skills():
            if sk.get("status") != "active":
                continue
            sk_seg = sk.get("segment") or "any"
            if sk_seg != "any" and sk_seg != seg:
                continue
            score = sum(
                1 for t in sk.get("triggers", [])
                if isinstance(t, str) and len(t) >= 3 and t in low
            )
            if score >= 1:
                scored.append((score, _safe_int(sk.get("priority"), 0), sk))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        capped = max(0, int(limit)) if isinstance(limit, int) else DEFAULT_SKILL_LIMIT
        return [sk for _, _, sk in scored[:capped]]
    except Exception:  # pragma: no cover - defensive
        return []
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/skills_service.py tests/test_skills.py
git commit -m "feat(skills): situational select_skills matcher (scored, bounded)"
```

---

## Task 4: Inject selected skills into `_build_system_prompt` (flag-gated)

**Files:**
- Modify: `app/agent/llm/parent_llm_engine.py`
- Test: `tests/test_skills.py`

**Interfaces:**
- Produces: `_skills_prompt_suffix(message: str = "", segment: str = "") -> str` — flag-gated; `""` when `USE_SKILLS` off OR no pack matches; else a Georgian header + selected pack bodies. `_build_system_prompt(message: str = "", segment: str = "")` appends it. Call site at line 2043 passes `user_message` + the literal `"PARENT"` (critique C2).
- Consumes: `skills_service.select_skills`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_skills.py`). Use the frozen-`Settings` swap idiom already used across this repo.

```python
def _swap_flag(monkeypatch, **flags):
    import dataclasses
    from app import config
    from app.agent.llm import parent_llm_engine as ple
    swapped = dataclasses.replace(config.settings, **flags)
    monkeypatch.setattr(ple, "settings", swapped)
    return ple


def test_skills_suffix_empty_when_flag_off(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=False)
    assert ple._skills_prompt_suffix("ძვირია", "PARENT") == ""


def test_skills_suffix_empty_when_no_match(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=True)
    from app.services import skills_service
    monkeypatch.setattr(skills_service, "select_skills", lambda m, s, **k: [])
    assert ple._skills_prompt_suffix("გამარჯობა", "PARENT") == ""


def test_skills_suffix_injects_selected_body(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=True)
    from app.services import skills_service
    monkeypatch.setattr(
        skills_service, "select_skills",
        lambda m, s, **k: [{"id": "x", "name": "ტესტ-უნარი", "body": "გამოიყენე X მიდგომა."}],
    )
    out = ple._skills_prompt_suffix("ძვირია", "PARENT")
    assert "ტესტ-უნარი" in out
    assert "გამოიყენე X მიდგომა." in out


def test_build_system_prompt_byte_identical_when_flag_off(monkeypatch):
    # With USE_SKILLS off, adding the message/segment args must not change output.
    ple = _swap_flag(monkeypatch, USE_SKILLS=False)
    assert ple._build_system_prompt("ძვირია", "PARENT") == ple._build_system_prompt()


def test_build_system_prompt_appends_skill_when_on(monkeypatch):
    ple = _swap_flag(monkeypatch, USE_SKILLS=True)
    from app.services import skills_service
    monkeypatch.setattr(
        skills_service, "select_skills",
        lambda m, s, **k: [{"id": "x", "name": "N", "body": " B-guidance."}],
    )
    base = ple._build_system_prompt()  # no message → suffix "" (empty message)
    withskill = ple._build_system_prompt("ძვირია", "PARENT")
    assert "B-guidance." in withskill
    assert withskill.startswith(base)  # skills append at the end, base unchanged
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: FAIL (`AttributeError: ... '_skills_prompt_suffix'` / signature mismatch).

- [ ] **Step 3: Add `_skills_prompt_suffix`** next to `_approved_answer_prompt_suffix` in `parent_llm_engine.py` (mirror its flag-gated guard):

```python
def _skills_prompt_suffix(message: str = "", segment: str = "") -> str:
    """Inject the situational SKILL.md capability pack(s) selected for this turn.
    Empty string when USE_SKILLS is off OR nothing matches, so the flag-off (and
    no-match) prompt is byte-identical. Never raises."""
    if not getattr(settings, "USE_SKILLS", False):
        return ""
    try:
        from app.services import skills_service
        skills = skills_service.select_skills(message, segment)
    except Exception:
        return ""
    blocks = "\n\n".join(
        f"### {s.get('name')}\n{(s.get('body') or '').strip()}"
        for s in skills if (s.get("body") or "").strip()
    )
    if not blocks.strip():
        return ""
    return (
        "\n\n[სიტუაციური უნარები] ქვემოთ მოცემული სახელმძღვანელო(ები) "
        "მიესადაგება ამ საუბარს — გამოიყენე მათი მიდგომა პასუხში:\n\n" + blocks
    )
```

- [ ] **Step 4: Thread the params through `_build_system_prompt`** (line 2232) — change the signature and the return:

```python
def _build_system_prompt(message: str = "", segment: str = "") -> str:
    # ... body unchanged ...
    return (
        base_prompt
        + _dynamic_programs_prompt_suffix()
        + _approved_answer_prompt_suffix()
        + _skills_prompt_suffix(message, segment)
    )
```

- [ ] **Step 5: Update the call site** (line 2043 inside `run_parent_llm_turn`). Pass the **literal `"PARENT"`** (critique C2) — this IS the PARENT engine, and `conversation.segment` is not a reliable source here (`parent_flow.py:9956` sets the LEAD's segment, not the conversation's):

```python
        system_prompt = _build_system_prompt(user_message, "PARENT")
```

- [ ] **Step 6: Run to verify pass + confirm the Phase-1/5 byte-exact tests still pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py tests/test_camp_age_bounds_migration_5a2_2026_06_22.py tests/test_prompt_sanitizer_source_of_truth_2026_06_23.py -q`
Expected: PASS (the byte-exact `_build_system_prompt() == raw.format(...)` tests still hold because all suffixes are `""` when their flags are off).

- [ ] **Step 7: Commit**

```bash
git add app/agent/llm/parent_llm_engine.py tests/test_skills.py
git commit -m "feat(skills): inject selected packs into _build_system_prompt (USE_SKILLS)"
```

---

## Task 5: e2e + verification gate

**Files:**
- Test: `tests/test_skills.py`

> **Acceptance honesty (critique C1).** The master plan's acceptance is behavioral — "adding a `SKILL.md` **changes an eval scenario**." The free/offline eval gate is DETERMINISTIC and does NOT call the LLM (`run_evals` prints "OpenAI NOT called"), so it CANNOT observe a pack's behavioral effect. This task therefore proves the acceptance **structurally** — a newly-dropped pack's guidance reaches the assembled system prompt with zero Python change (Steps 1–2) — and the **behavioral** proof is explicitly deferred to a permissioned `--llm` smoke at enablement (Step 6, optional, NOT run in the gate). This is a deliberate, disclosed narrowing of the acceptance for the free gate; see the DoD.

- [ ] **Step 1: e2e — a NEW SKILL.md reaches the prompt with NO Python change (flag on).** Write a pack into a temp dir, point `SKILLS_DIR` at it (simulating the operator dropping a file — no code edit), and assert the selected body reaches `_build_system_prompt` with the flag on, and is absent with the flag off.

```python
def test_e2e_new_skill_file_reaches_prompt_without_code_change(monkeypatch, tmp_path):
    import dataclasses
    from app import config
    from app.agent.llm import parent_llm_engine as ple
    from app.services import skills_service

    d = tmp_path / "skills"
    d.mkdir()
    (d / "custom.md").write_text(
        "---\nid: custom\nname: მორგებული უნარი\nsegment: PARENT\n"
        "status: active\npriority: 50\ntriggers:\n  - სპეც-სიტყვა\n---\n"
        "ეს არის მორგებული სახელმძღვანელო.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skills_service, "SKILLS_DIR", d)  # operator "dropped" a file

    # Flag ON → the new pack's body is injected, purely from the data file.
    monkeypatch.setattr(ple, "settings", dataclasses.replace(config.settings, USE_SKILLS=True))
    on = ple._build_system_prompt("სპეც-სიტყვა მაინტერესებს", "PARENT")
    assert "ეს არის მორგებული სახელმძღვანელო." in on
    assert "მორგებული უნარი" in on

    # Flag OFF → byte-identical, pack absent.
    monkeypatch.setattr(ple, "settings", dataclasses.replace(config.settings, USE_SKILLS=False))
    off = ple._build_system_prompt("სპეც-სიტყვა მაინტერესებს", "PARENT")
    assert "მორგებული სახელმძღვანელო" not in off
    assert off == ple._build_system_prompt()
```

- [ ] **Step 2: e2e — the skill body reaches the engine's system message through the real turn (flag on).** Mirror the mocked-`chat_with_tools` pattern (see `tests/test_parent_llm_engine.py` `_chat`/`_mk_response`, and the Phase-5 reuse e2e in `tests/test_learning.py`). Enable the engine + `USE_SKILLS`, point `SKILLS_DIR` at a temp pack, capture the system messages passed to `chat_with_tools`, assert the pack body is present and the mocked LLM was actually driven.

```python
def test_e2e_skill_reaches_engine_system_message(monkeypatch, tmp_path):
    import dataclasses, json
    from app import config
    from app.agent.llm import parent_llm_engine as ple
    from app.flows import parent_flow as pf
    from app.services import openai_service, messenger_service, skills_service

    d = tmp_path / "skills"; d.mkdir()
    (d / "c.md").write_text(
        "---\nid: c\nname: N\nsegment: PARENT\nstatus: active\npriority: 5\n"
        "triggers:\n  - სპეცტრიგერი\n---\nუნიკალური-სხეული-42.\n", encoding="utf-8")
    monkeypatch.setattr(skills_service, "SKILLS_DIR", d)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    monkeypatch.setattr(pf, "settings", dataclasses.replace(config.settings, USE_PARENT_LLM_ENGINE=True))
    monkeypatch.setattr(ple, "settings", dataclasses.replace(config.settings, USE_PARENT_LLM_ENGINE=True, USE_SKILLS=True))

    captured = {}
    def _chat(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return _mk_response(content="პასუხი.")   # define/import _mk_response as in test_parent_llm_engine.py
    monkeypatch.setattr(openai_service, "chat_with_tools", _chat)

    conv = _fresh_parent_conversation()  # a PARENT conv (mirror the engine tests' fixture)
    out = pf.handle(conv, "სპეცტრიგერი მაინტერესებს")
    assert out == "პასუხი."
    system_blob = "\n".join(m["content"] for m in captured["messages"] if m["role"] == "system")
    assert "უნიკალური-სხეული-42." in system_blob   # the pack reached the prompt
```
> Implementer note: reuse the engine-test helpers (`_mk_response`, a PARENT-conversation fixture) — import them or replicate the minimal versions, exactly as the Phase-5 reuse e2e did. If a deterministic pre-engine handler would intercept the driving message, pick a neutral trigger word (as the Phase-5 e2e did with an English phrase) so `chat_with_tools` is actually reached; assert it was called.

- [ ] **Step 3: Full suite, flags OFF.**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: no NEW failures — exactly the one pre-existing `test_approved_copy_service_2026_07_11.py::...fast_track...` failure. Record the full `N passed / M skipped / K failed` line.

- [ ] **Step 4: Scoped flag-ON.**

Run: `.venv/Scripts/python.exe -m pytest tests/test_skills.py -q`
Expected: all green.

- [ ] **Step 5: Eval gate — READ-ONLY, baseline byte-identical.**

```bash
cp evals/baseline.json <scratchpad>/baseline_ref.json
.venv/Scripts/python.exe -m evals.run_evals    # offline, NO --llm/--judge
diff evals/baseline.json <scratchpad>/baseline_ref.json   # MUST be identical; restore if not
```
Expected: `run_evals` prints "READ-ONLY VERIFIED — 0 external writes"; baseline byte-identical (0 external writes). Restore from the copy if the run touched it.

- [ ] **Step 6 (OPTIONAL — behavioral acceptance, C1): permissioned `--llm` smoke.** NOT run in the automated gate (it calls OpenAI and costs money). Document the manual command for enablement time: with `USE_SKILLS=true` + a pack whose triggers match one eval case, run `.venv/Scripts/python.exe -m evals.run_evals --llm --judge` twice (with and without the pack present) and confirm the targeted scenario's judged output shifts toward the pack's guidance. This is the ONLY proof that a `SKILL.md` changes behavior; the free gate proves only that the text reaches the prompt. **Do NOT run this in CI or without explicit operator permission.**

- [ ] **Step 7: Commit**

```bash
git add tests/test_skills.py
git commit -m "test(skills): e2e new-pack-reaches-prompt + phase-3 verification gate"
```

---

## Phase 3 Definition of Done

With `USE_SKILLS` ON, the PARENT engine selects the most relevant active `SKILL.md` pack(s) by situation (trigger-substring, segment-filtered, bounded to 2) and injects their guidance into the system prompt — and a NEW pack is added by dropping a file with **zero Python change** (proven **structurally** in the gate: Task 5 Steps 1–2 show a freshly-dropped pack's body reaches the assembled system prompt). With `USE_SKILLS=false`: no selection, suffix `""`, **system prompt byte-identical** (full suite 0 new failures; the byte-exact `_build_system_prompt()` tests still pass). Loading/selection **never breaks a turn** (tolerant, never-raises). Operator is the sole writer of the pack files. `evals/baseline.json` unchanged. **Flag stays OFF — enablement is a separate operator step.**

**Acceptance narrowing (critique C1, disclosed).** The master plan's acceptance ("changes an eval scenario") is BEHAVIORAL; the free/offline gate is deterministic and never calls the LLM, so it proves only the STRUCTURAL half (text reaches the prompt). The behavioral half is deferred to the permissioned `--llm` smoke (Task 5 Step 6), run at enablement, not in CI. This is an accepted, explicit trade-off — the free gate cannot certify behavior change.

**Documented residuals (Phase-3b, not bugs):**
1. **PARENT-only injection** — no `adult_llm_engine` mirror (ADULT `_build_system_prompt` deliberately untouched).
2. **Substring, not semantic selection** — central to the "adaptive" goal (critique L4): an objection phrased with no trigger word fires no pack. Semantic/embedding matching is Phase-3b.
3. **Salience / lost-in-the-middle (critique M3)** — packs concatenate onto the END of the ~56 KB giant system message (message #1), before the separate `context_message`/`sales_context` system messages; effect may be blunted. Master plan mandates injection into `_build_system_prompt`, so honored; a separate LAST system message is a Phase-3b option. The structural test cannot catch a weak-effect pack — only the `--llm` smoke can.
4. **Prompt headroom (critique M2)** — the giant prompt is already near its 56 KB cap; at enablement, injected packs may require raising `tests/test_parent_llm_engine.py:1848`. Keep seed bodies short; top-2 cap is load-bearing.
5. **Per-turn disk I/O (critique L1)** — `select_skills`→`load_skills` globs+reads the dir every turn (matches `admin_config` cache-free contract; fine at low QPS). An mtime cache is a future optimization.
6. **Skills vs existing `policies/*.md` / `camp_topic_facts` (critique L3)** — conceptual overlap with no conflict-resolution story; in v1 a pack that contradicts a policy is the author's responsibility.
7. **No admin-UI** to author packs (operator hand-edits `.md`).

Enablement behind a supervised staging smoke.

---

## Appendix — Critique → Fix mapping (v1 → v2)

| Finding | Sev | Resolution |
|---|---|---|
| **C1 — acceptance softened from behavioral to structural** | 🔴 | DoD rewritten to disclose the narrowing; Task 5 Step 6 adds a permissioned `--llm` behavioral smoke (not in gate) as the behavioral proof at enablement. |
| **C2 — call-site `conversation.segment` unreliable → PARENT packs could silently not fire** | 🔴 | Call site passes the literal `"PARENT"` (Task 4 Step 5); grounded in `parent_flow.py:9956` (LEAD segment, not conversation). |
| **M1 — `_parse_skill_md` `lstrip("-")` can corrupt a body starting with `---`/`-`** | 🟠 | Parser rewritten line-based (Task 2 Step 4) + a `body_starting_with_dash_preserved` test (Task 2 Step 2). |
| **M2 — giant prompt already near its 56 KB cap** | 🟠 | Global Constraint + DoD residual #4; short seed bodies + top-2 cap load-bearing; cap-test raise deferred to enablement. |
| **M3 — salience / lost-in-the-middle** | 🟠 | DoD residual #3; honored master-plan injection point, disclosed trade-off, separate-message option noted for 3b. |
| **M4 — `adult_llm_engine` also has `_build_system_prompt`** | 🟠 | Global Constraint: explicit "do NOT edit adult's `_build_system_prompt`" with the test ref. |
| **L1 — per-turn disk I/O** | 🟡 | DoD residual #5. |
| **L2 — cross-module test-helper import in e2e Step 2** | 🟡 | Task 5 Step 2 implementer note: import or replicate `_mk_response` + PARENT fixture, as the Phase-5 reuse e2e did. |
| **L3 — skills vs policies/camp_topic_facts overlap** | 🟡 | DoD residual #6. |
| **L4 — substring not semantic (central to "adaptive")** | 🟡 | DoD residual #2, stated as the honest ceiling. |

---

## Self-Review

**Spec coverage:** Master-plan Phase-3 line — "registry of `SKILL.md` packs selected per situation, injected into `_build_system_prompt`; files data, selection code; off ⇒ prompt unchanged; acceptance: adding a `SKILL.md` changes an eval scenario with no Python change." → Task 2 (files=data registry) + Task 3 (selection=code) + Task 4 (injection into `_build_system_prompt`) + Task 5 Step 1 (new-file-reaches-prompt-without-code-change proves the acceptance as a pytest, since the offline eval gate is deterministic/no-LLM). ✅

**Placeholder scan:** every code step carries real code; every run step names the interpreter + expected result. No TBD/TODO. ✅

**Type consistency:** the skill dict shape `{id, name, segment, status, priority, triggers, body}` is defined in Task 2 (`load_skills`) and consumed unchanged in Task 3 (`select_skills`) and Task 4 (`_skills_prompt_suffix` reads `name`/`body`). `select_skills(message, segment, *, limit=DEFAULT_SKILL_LIMIT)` signature is identical in Task 3's interface and Task 4's call (`select_skills(message, segment)`). `_build_system_prompt(message="", segment="")` + call site agree. ✅

**Byte-identity invariant:** re-checked against the real dependency — `tests/test_camp_age_bounds_migration_5a2_2026_06_22.py:59` asserts `_build_system_prompt() == raw.format(...)`. All three suffixes return `""` when their flags are off (conftest pins them off), so the equality holds after adding the third suffix. Task 4 Step 6 runs that exact test. ✅
