# Dynamic Programs — Phase 2: Pre-Enablement Gates — Implementation Plan (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
>
> **v2 changes** (from the critique): (#1) the flag-ON verification is now SCOPED, not a whole-suite run — conftest preserves `USE_DYNAMIC_PROGRAMS` from env, so a whole-suite flag-ON run is an unstable gate that depends on live `sections.yaml`; (#2) the gate-2 guard moves to right after the engine gate, BEFORE the deterministic interceptor chain, so camp-content handlers ABOVE the old insertion point (notably `_maybe_handle_out_of_range_age` at `:1395`) can no longer hijack an age-bearing dynamic-program message; (#3) the hardcoded-program-id set is derived once from the `ProgramId` enum, and the ambiguous-stem list is drift-guarded by a sync test against the real keyword tuples.

**Goal:** Close the three gates that must exist before `USE_DYNAMIC_PROGRAMS` can be safely turned on, so a new admin-panel program is answered for ALL question types without hijacking the camp/adult flows. Phase 2 makes the flag *enableable*; it does **not** enable it.

**Architecture:** Phase 1 shipped a flag-gated foundation proven end-to-end for info questions, with three flag-ON gaps. Phase 2: (1) replace the crude substring router with one **precise, shared** matcher; (2) add a single flag-gated **interceptor bypass** placed BEFORE the deterministic chain so dynamic-program questions reach the LLM engine; (3) convert `get_program_info` to an **allowlist** and refuse the 3 hardcoded programs. All behind `USE_DYNAMIC_PROGRAMS` (still default OFF) → flag-off byte-identical.

**Tech Stack:** Python 3.10, FastAPI, OpenAI GPT-4.1-mini function-calling, YAML config, pytest (~4900 tests) + read-only `evals/` harness.

## Global Constraints

- **LLM stays OpenAI.** Additive & flag-gated — every change is reached only when `USE_DYNAMIC_PROGRAMS` is True; flag OFF ⇒ byte-identical, suite green. **Phase 2 does NOT change the flag default or enable it.**
- **`Settings` is FROZEN.** Toggle flags in tests via `dataclasses.replace(config.settings, USE_X=...)` + `monkeypatch.setattr(<module>, "settings", swapped)` (conftest pattern) — never `setattr(mod.settings, attr, ...)`.
- **Interpreter:** `.venv/Scripts/python.exe -m pytest ...` (bare `python` is a dep-less 3.14).
- Never modify `ProgramId`/`program_registry`/`program_resolver` to add a program. Never modify/commit `data/admin_config/sections.yaml`, `CLAUDE.md`, `HANDOFF.md`. Never overwrite `evals/baseline.json`. Stage only your task's files (never `-a/-A`). Georgian strings in YAML. Backend is the only fact source.
- **Do NOT push or deploy.** The user's GitHub auto-deploys the server — all work stays local on `feat/dynamic-programs`.

## Verified current state (read before editing)

- `app/services/conversation_service.py` — `_match_active_program_segment` (Phase-1 substring heuristic), consumed at the fresh-classification line `... or _classify_segment(...)`. Keyword tuples `CAMP_KEYWORDS`/`ADULT_KEYWORDS`/`PRICE_KEYWORDS` (`:246-285`).
- `app/flows/parent_flow.py` — `_handle_core` (`:910`); engine gate `if engine_flag:` (`:1293`); per-turn book-success reset (`:1296-1304`); the deterministic interceptors run `:1314-1506`, incl. **camp-content** handlers `_maybe_handle_out_of_range_age` (`:1395`, camp eligibility — ABOVE the old v1 guard spot), `_maybe_handle_exact_detail` (`:1433`), `_maybe_handle_repeat_camp_price` (`:1441`), `_maybe_handle_camp_topic_facts` (`:1472`), `_maybe_handle_availability_question` (`:1487`), `_maybe_handle_camp_intro` (`:1502`); engine at `_run_llm_engine_safely` (`:1508`).
- `app/agent/tools/parent_tool_executor.py` — `_get_program_info` (denylist + copy-all loop).
- `app/domain/decision/models.py:16-21` — `class ProgramId(str, Enum)` with `SUMMER_CAMP`/`SUNDAY_SCHOOL`/`ADULT_EVENTS` (the single source for the hardcoded-program set; the package has zero imports from `app.flows`/`app.agent`, so importing it upward is cycle-free).
- `tests/conftest.py:98-146` — autouse `dataclasses.replace(config.settings, USE_PARENT_LLM_ENGINE=False, ...)` PRESERVES unnamed flags (incl. `USE_DYNAMIC_PROGRAMS`) and pins the swapped settings onto `config`/`parent_flow`/`conversation_service`/`parent_llm_engine`/`adult_llm_engine`. **Consequence:** `USE_DYNAMIC_PROGRAMS=true pytest` (whole suite) would change routing suite-wide against live `sections.yaml` — do NOT use it as a gate (see Task 6).

## File Structure (Phase 2)

- `app/reasoning/dynamic_program_match.py` — NEW. Pure matcher `match_dynamic_program(message, sections)` shared by routing (gate 1) and the bypass (gate 2). No `settings`, no IO.
- `app/services/conversation_service.py` — `_match_active_program_segment` delegates to the matcher (gate 1).
- `app/flows/parent_flow.py` — `_is_dynamic_program_turn` + one guard right after the engine gate (gate 2).
- `app/agent/tools/parent_tool_executor.py` — `_get_program_info` allowlist + hardcoded refusal (gate 3).
- `tests/test_dynamic_programs_phase2.py` — NEW Phase-2 tests.

---

## Task 1: Shared precise matcher (`dynamic_program_match.py`) + drift guard

**Files:** Create `app/reasoning/dynamic_program_match.py`; Test `tests/test_dynamic_programs_phase2.py`.
**Interfaces:** Produces `match_dynamic_program(message_text: str, sections: list[dict]) -> dict | None` → `{"program_id","type"}` for the first active section the message NAMES with sufficient specificity, else `None`. Pure.

- [ ] **Step 1: Failing tests** (incl. the drift-guard sync test that keeps `_AMBIGUOUS_TAG_STEMS` in step with the real classifier keywords — fix #3)

```python
# tests/test_dynamic_programs_phase2.py
from app.reasoning.dynamic_program_match import match_dynamic_program, _AMBIGUOUS_TAG_STEMS

_ROBOTICS = {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
             "status": "active", "hashtags": ["რობოტიკა", "robotics"]}
_ADULT = {"id": "adult_events", "name": "ზრდასრულთა ღონისძიება", "type": "adult_events",
          "status": "active", "hashtags": ["ღონისძიება", "საღამო"]}
_CAMP = {"id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
         "status": "active", "hashtags": ["ბანაკი", "camp"]}

def test_matches_inflected_program_name():
    assert match_dynamic_program("რობოტიკის კლუბი რა ღირს?", [_ROBOTICS, _ADULT, _CAMP]) \
        == {"program_id": "robotics_club", "type": "kids_program"}

def test_no_latin_substring_false_positive():
    assert match_dynamic_program("this is a campaign about prevention", [_CAMP]) is None

def test_bare_ambiguous_hashtag_does_not_hijack_to_adult():
    m = match_dynamic_program("ბანაკში საღამოს რა ხდება?", [_ADULT, _CAMP])
    assert m is None or m["program_id"] == "summer_camp"   # never adult via bare "საღამო"

def test_empty_and_no_match():
    assert match_dynamic_program("", [_ROBOTICS]) is None
    assert match_dynamic_program("ამინდი როგორია დღეს", [_ROBOTICS]) is None

def test_ambiguous_stems_cover_classifier_keywords():
    # Drift guard: every camp/adult/price keyword the router already owns must be
    # reflected in the matcher's ambiguous set, so a hashtag equal to one of them
    # can never trigger a dynamic override. Fails if someone adds a keyword to
    # conversation_service without updating _AMBIGUOUS_TAG_STEMS.
    from app.services.conversation_service import (
        CAMP_KEYWORDS, ADULT_KEYWORDS, PRICE_KEYWORDS,
    )
    amb = tuple(_AMBIGUOUS_TAG_STEMS)
    for kw in (*CAMP_KEYWORDS, *ADULT_KEYWORDS, *PRICE_KEYWORDS):
        k = kw.lower()
        assert any(k.startswith(a) or a.startswith(k) for a in amb), \
            f"classifier keyword {kw!r} not covered by _AMBIGUOUS_TAG_STEMS"
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`).
- [ ] **Step 3: Implement the module**

```python
# app/reasoning/dynamic_program_match.py
"""Precise, flag-agnostic matcher: does a message NAME an active admin program?

Pure — no settings, no IO (caller passes `sections`). Replaces the Phase-1
raw-substring heuristic. Fixes: Latin substring false-positives (camp∈campaign),
Georgian declension misses, and bare common-word hashtag hijacks (`საღამო`)."""
from __future__ import annotations

import re

# Ambiguous single-word stems that must NOT alone trigger a dynamic-program match
# (they overlap the camp/adult/price keyword classifier in conversation_service
# and would hijack routing). Kept in sync with those tuples by
# test_ambiguous_stems_cover_classifier_keywords. Only HASHTAG matches are gated
# by this set; program NAME tokens are treated as specific.
_AMBIGUOUS_TAG_STEMS: tuple[str, ...] = (
    # camp
    "ბანაკ", "ლაგერ", "ბავშვ", "შვილ", "საზაფხულო", "ეკრან", "მოზარდ", "სკოლ",
    "camp", "child", "kid", "summer",
    # adult
    "ღონისძიებ", "საღამო", "ბილეთ", "კულტურ", "პოეზი", "მუსიკ", "შეხვედრ", "კლუბ",
    "event", "events", "evening", "school",
    # price
    "ფასი", "ღირს", "რამდენი", "გადახდ",
)
_MIN_LEN = 4  # ignore tokens/tags shorter than this (kills 1-3 char noise)


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-zა-ჰ]+", (text or "").lower()) if t]


def _token_matches(msg_tokens: list[str], term: str) -> bool:
    """True when a message token equals `term`, or (for terms >= 6 chars) `term`
    is a declension-tolerant prefix of a token (`რობოტიკის` matches `რობოტიკა`).
    Short terms (< 6) require EXACT equality, so `camp` never matches `campaign`."""
    term = term.strip().lstrip("#").lower()
    if len(term) < _MIN_LEN:
        return False
    for tok in msg_tokens:
        if tok == term:
            return True
        if len(term) >= 6:
            shared = 0
            for a, b in zip(tok, term):
                if a != b:
                    break
                shared += 1
            if shared >= 5 and shared >= len(term) - 2:
                return True
    return False


def _is_ambiguous(tag: str) -> bool:
    tag = tag.strip().lstrip("#").lower()
    return any(tag.startswith(a) or a.startswith(tag) for a in _AMBIGUOUS_TAG_STEMS)


def match_dynamic_program(message_text: str, sections: list[dict]) -> dict | None:
    """Return {'program_id','type'} for the first active section the message NAMES
    with sufficient specificity, else None. Specificity = a NAME-token match OR a
    match on a non-ambiguous hashtag. Pure; iterates `sections` in given order."""
    toks = _tokens(message_text)
    if not toks:
        return None
    for s in sections:
        pid = (s.get("id") or "").strip()
        if not pid:
            continue
        name_hit = any(
            _token_matches(toks, nt)
            for nt in _tokens(s.get("name") or "")
            if len(nt) >= _MIN_LEN
        )
        specific_tags = [
            str(t) for t in (s.get("hashtags") or [])
            if len(str(t).strip().lstrip("#")) >= _MIN_LEN and not _is_ambiguous(str(t))
        ]
        tag_hit = any(_token_matches(toks, t) for t in specific_tags)
        if name_hit or tag_hit:
            return {"program_id": pid, "type": s.get("type")}
    return None
```

- [ ] **Step 4: Run — expect PASS** (5 tests). If the drift-guard fails, extend `_AMBIGUOUS_TAG_STEMS` to cover the missing keyword; if a match case fails, tune the prefix threshold — never weaken an assertion.
- [ ] **Step 5: Commit** `git add app/reasoning/dynamic_program_match.py tests/test_dynamic_programs_phase2.py && git commit -m "feat(reasoning): precise dynamic-program matcher + keyword drift guard"`

---

## Task 2: Gate 1 — route via the precise matcher

**Files:** Modify `app/services/conversation_service.py`; also UPDATE the Phase-1 routing regression in `tests/test_dynamic_programs.py`; Test `tests/test_dynamic_programs_phase2.py`.
**Interfaces:** Consumes `match_dynamic_program`. `_match_active_program_segment` keeps its signature/contract.

**Note (design shift):** the precise matcher deliberately does NOT match the 3 generic-named known programs via ambiguous tokens — they continue to route through `_classify_segment` (the `... or _classify_segment(...)` fallback). So the composed routing is unchanged for them, but `_match_active_program_segment("ბანაკი …")` now returns `None` (was `"PARENT"` under the Phase-1 substring version). Update the Phase-1 test accordingly (assert the composed segment, not the helper's isolated return).

- [ ] **Step 1: Failing tests** (frozen-settings pattern)

```python
def test_routing_prefers_dynamic_then_classifier(monkeypatch):
    import dataclasses
    from app import config
    from app.services import conversation_service as cs, admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [_ADULT, _CAMP, _ROBOTICS])
    monkeypatch.setattr(cs, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=True))
    # a genuine dynamic program routes PARENT via the matcher
    assert cs._match_active_program_segment("რობოტიკის კლუბი რა ღირს?") == "PARENT"
    # a camp-context message is NOT force-routed to ADULT by a bare adult hashtag
    assert cs._match_active_program_segment("ბანაკში საღამოს რა ხდება?") in ("PARENT", None)
    # flag off ⇒ None
    monkeypatch.setattr(cs, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=False))
    assert cs._match_active_program_segment("რობოტიკის კლუბი რა ღირს?") is None
```

- [ ] **Step 2: Run — expect FAIL** (substring version routes the camp-context message to ADULT).
- [ ] **Step 3: Reimplement `_match_active_program_segment`**

```python
def _match_active_program_segment(message_text: str) -> str | None:
    """USE_DYNAMIC_PROGRAMS: route a message that NAMES an active admin program by
    that program's type (adult_events → ADULT, else PARENT). None when flag off /
    no specific match — the caller falls back to _classify_segment, so flag-off
    routing is byte-identical and the 3 generic-named programs keep classifier
    routing. Precision lives in reasoning/dynamic_program_match (Phase 2)."""
    if not getattr(settings, "USE_DYNAMIC_PROGRAMS", False):
        return None
    if not (message_text or "").strip():
        return None
    try:
        from app.services import admin_config_service
        from app.reasoning.dynamic_program_match import match_dynamic_program
        match = match_dynamic_program(message_text, admin_config_service.get_active_sections())
    except Exception:  # pragma: no cover - defensive
        return None
    if not match:
        return None
    return "ADULT" if match.get("type") == "adult_events" else "PARENT"
```

- [ ] **Step 4: Update the Phase-1 regression** in `tests/test_dynamic_programs.py` — `test_existing_programs_unchanged_routing` asserted `_match_active_program_segment("ბანაკი მაინტერესებს") == "PARENT"`. Change it to assert the COMPOSED routing is unchanged (the helper may now return None; the classifier fallback yields PARENT/ADULT):

```python
    # v2: the matcher no longer owns the generic-named programs; the composed
    # routing (matcher or _classify_segment) still yields the same segment.
    assert (cs._match_active_program_segment("ბანაკი მაინტერესებს")
            or cs._classify_segment("ბანაკი მაინტერესებს")) == "PARENT"
    assert (cs._match_active_program_segment("ღონისძიება როდისაა")
            or cs._classify_segment("ღონისძიება როდისაა")) == "ADULT"
```

- [ ] **Step 5: Run — expect PASS** (`tests/test_dynamic_programs.py` + `tests/test_dynamic_programs_phase2.py`).
- [ ] **Step 6: Commit** `git add app/services/conversation_service.py tests/test_dynamic_programs.py tests/test_dynamic_programs_phase2.py && git commit -m "feat(routing): route dynamic programs via precise matcher (gate 1)"`

---

## Task 3: Gate 2 — interceptor bypass placed BEFORE the deterministic chain (fix #2)

**Files:** Modify `app/flows/parent_flow.py`; Test `tests/test_dynamic_programs_phase2.py`.
**Interfaces:** Produces `_is_dynamic_program_turn(message: str) -> bool` (True only when flag on AND the message names an ACTIVE program whose id is NOT one of the `ProgramId` enum values). The guard runs as the FIRST branch inside `if engine_flag:`, after the per-turn book-success reset and BEFORE `_maybe_reasoning_analysis` — so NO deterministic interceptor (including `_maybe_handle_out_of_range_age`) can hijack a dynamic-program turn.

**Trade-off (documented):** with the guard first, a dynamic-program turn also bypasses the cross-cutting contact/booking/decline handlers. That is acceptable and correct for Phase 2 — the guard fires ONLY when the message NAMES a dynamic program (a decline/contact-only message names no program → guard False → normal chain), and dynamic programs have no booking/contact flow yet.

- [ ] **Step 1: Failing tests**

```python
def test_is_dynamic_program_turn(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import admin_config_service
    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [_ROBOTICS, _CAMP, _ADULT])
    monkeypatch.setattr(pf, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=True))
    assert pf._is_dynamic_program_turn("რობოტიკის კლუბი რა ღირს?") is True
    assert pf._is_dynamic_program_turn("ბანაკი რა ღირს?") is False       # camp (hardcoded)
    assert pf._is_dynamic_program_turn("მადლობა, არ მინდა") is False     # names no program
    monkeypatch.setattr(pf, "settings", dataclasses.replace(config.settings, USE_DYNAMIC_PROGRAMS=False))
    assert pf._is_dynamic_program_turn("რობოტიკის კლუბი რა ღირს?") is False
```

- [ ] **Step 2: Run — expect FAIL** (`AttributeError`).
- [ ] **Step 3: Add the helper** (near the other module helpers; `settings` already imported)

```python
from app.domain.decision.models import ProgramId  # add with the other imports

_HARDCODED_PROGRAM_IDS = frozenset(p.value for p in ProgramId)  # single source of truth

def _is_dynamic_program_turn(message: str) -> bool:
    """True only when USE_DYNAMIC_PROGRAMS is on AND the message NAMES an active
    admin program that is NOT one of the hardcoded ProgramId programs (which keep
    their curated deterministic handlers). Flag off ⇒ False ⇒ interceptor chain
    unchanged. Fail-closed on any error."""
    if not getattr(settings, "USE_DYNAMIC_PROGRAMS", False):
        return False
    try:
        from app.services import admin_config_service
        from app.reasoning.dynamic_program_match import match_dynamic_program
        match = match_dynamic_program(message, admin_config_service.get_active_sections())
    except Exception:  # pragma: no cover - defensive
        return False
    return bool(match) and match.get("program_id") not in _HARDCODED_PROGRAM_IDS
```

- [ ] **Step 4: Insert the guard as the FIRST branch inside `if engine_flag:`** — READ `_handle_core` `:1293-1315` first; place it immediately AFTER the book-success reset (`:1296-1304`) and BEFORE `_maybe_reasoning_analysis` (`:1314`):

```python
        # Dynamic Programs (Phase 2) — a turn that NAMES a non-hardcoded admin
        # program goes straight to the generic-tool LLM engine, bypassing ALL
        # camp/consultation deterministic interceptors below (which would answer
        # with camp facts / eligibility). Placed first so even the early
        # camp-content handlers (e.g. _maybe_handle_out_of_range_age) can't
        # hijack it. Flag off / camp / adult / no-program-named ⇒ False ⇒ chain
        # unchanged (byte-identical).
        if _is_dynamic_program_turn(message):
            return _sanitise_booking_confirmation(
                conversation, _run_llm_engine_safely(conversation, message),
            )
```

- [ ] **Step 5: Write the routing-through tests** — a dynamic-program turn reaches the engine and is NOT hijacked, incl. the **age-bearing** case that the v1 placement would have missed:

```python
def _dyn_engine_conv(monkeypatch, msg_program_only=True):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import admin_config_service
    from app.models.conversation import Conversation
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [_ROBOTICS])
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_DYNAMIC_PROGRAMS=True, USE_PARENT_LLM_ENGINE=True))
    monkeypatch.setattr(pf, "_run_llm_engine_safely", lambda *a, **k: "ENGINE_ANSWER")
    # sentinels: NO camp-content interceptor may answer a dynamic-program turn
    for name in ("_maybe_handle_repeat_camp_price", "_maybe_handle_out_of_range_age",
                 "_maybe_handle_camp_intro", "_maybe_handle_camp_topic_facts"):
        monkeypatch.setattr(pf, name, lambda *a, **k: f"CAMP:{name}")
    return pf, Conversation(sender_id="t", platform="facebook", segment="PARENT")

def test_dynamic_price_reaches_engine(monkeypatch):
    pf, conv = _dyn_engine_conv(monkeypatch)
    out = pf._handle_core(conv, "რობოტიკის კლუბი რა ღირს?")
    assert out == "ENGINE_ANSWER" and "CAMP" not in out

def test_dynamic_age_bearing_not_hijacked_by_camp_eligibility(monkeypatch):
    # the v1 guard (below out_of_range_age) would have failed this
    pf, conv = _dyn_engine_conv(monkeypatch)
    out = pf._handle_core(conv, "ჩემი 5 წლის ბავშვისთვის რობოტიკის კლუბი?")
    assert out == "ENGINE_ANSWER" and "CAMP" not in out
```

_(Confirm `Conversation` required fields by reading `app/models/conversation.py`. If a handler ABOVE the engine gate `:1293` — i.e. `:910-1288` — intercepts first, read it and adjust the fixture; the guard is inside the `engine_flag` block, so those pre-gate handlers must be shown not to fire for a program-only message. If one does, that is a real finding — report it, don't paper over it.)_

- [ ] **Step 6: Camp regression** — assert a plain camp turn still reaches its interceptor:

```python
def test_camp_price_still_uses_camp_interceptor(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import admin_config_service
    from app.models.conversation import Conversation
    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [_CAMP])
    monkeypatch.setattr(pf, "settings", dataclasses.replace(
        config.settings, USE_DYNAMIC_PROGRAMS=True, USE_PARENT_LLM_ENGINE=True))
    monkeypatch.setattr(pf, "_maybe_handle_repeat_camp_price", lambda *a, **k: "CAMP_PRICE")
    conv = Conversation(sender_id="t", platform="facebook", segment="PARENT")
    assert pf._handle_core(conv, "ბანაკი რა ღირს?") == "CAMP_PRICE"   # guard False for camp
```

- [ ] **Step 7: Run — expect PASS.** **Step 8: Commit** `git add app/flows/parent_flow.py tests/test_dynamic_programs_phase2.py && git commit -m "feat(flow): dynamic-program interceptor bypass before the chain (gate 2)"`

---

## Task 4: Gate 3 — `get_program_info` allowlist + hardcoded refusal

**Files:** Modify `app/agent/tools/parent_tool_executor.py`; Test `tests/test_dynamic_programs_phase2.py`.
**Interfaces:** `_get_program_info` keeps its return shape; switches denylist → allowlist and refuses the hardcoded ids (derived from `ProgramId`).

- [ ] **Step 1: Failing tests**

```python
def _make_executor():
    from app.agent.tools.parent_tool_executor import ParentToolExecutor
    from app.models.lead import Lead
    from app.models.conversation import Conversation
    conv = Conversation(sender_id="t", platform="facebook", segment="PARENT")
    return ParentToolExecutor(conversation=conv,
                              lead=Lead(sender_id="t", platform="facebook", segment="PARENT"),
                              sender_id="t", platform="facebook")

def test_get_program_info_allowlist_excludes_internal(monkeypatch):
    from app.services import admin_config_service
    sec = {"id": "robotics_club", "name": "რობოტიკის კლუბი", "type": "kids_program",
           "status": "active", "price_text": "300 ლარი", "description_full": "აღწერა",
           "discovery_questions": ["შიდა?"], "events": [{"reservation_url": "https://secret"}],
           "cta_text": "შიდა"}
    monkeypatch.setattr(admin_config_service, "get_section",
                        lambda pid: sec if pid == "robotics_club" else None)
    out = _make_executor().execute("get_program_info", {"program_id": "robotics_club"})
    assert out["success"] and out["facts"]["price_text"] == "300 ლარი"
    for k in ("discovery_questions", "events", "cta_text"):
        assert k not in out["facts"]

def test_get_program_info_refuses_hardcoded(monkeypatch):
    out = _make_executor().execute("get_program_info", {"program_id": "summer_camp"})
    assert out["success"] is False and out["reason"] == "use_specific_tool"
```

- [ ] **Step 2: Run — expect FAIL** (denylist surfaces `discovery_questions`/`events`; `summer_camp` returns facts).
- [ ] **Step 3: Reimplement facts selection** — add class attributes and edit the handler (READ the current `_get_program_info` first so the `status`-active check, `reg_open`, logging, and return dict are preserved):

```python
    from app.domain.decision.models import ProgramId  # module-top import
    # Customer-safe fields the generic tool may surface. Allowlist ⇒ a new
    # operator field never leaks by default.
    _PROGRAM_PUBLIC_FIELDS: tuple[str, ...] = (
        "name", "type", "location", "price_text", "price_gel", "payment_terms",
        "age_min", "age_max", "description_short", "description_full",
        "schedule_text", "duration_text", "streams", "included_items", "discounts",
    )
    _HARDCODED_PROGRAM_IDS = frozenset(p.value for p in ProgramId)
```

In `_get_program_info`, right after resolving `program_id`:

```python
        if program_id in self._HARDCODED_PROGRAM_IDS:
            return {"success": False, "reason": "use_specific_tool",
                    "program_id": program_id}
```

and replace the field-copy loop with the allowlist (keep the registration-URL gate):

```python
        facts: dict[str, Any] = {}
        for key in self._PROGRAM_PUBLIC_FIELDS:
            value = section.get(key)
            if value in (None, "", [], {}):
                continue
            facts[key] = value
        if reg_open:
            url = section.get("registration_url")
            if url:
                facts["registration_url"] = url
```

- [ ] **Step 4: Run — expect PASS.** Also `tests/test_dynamic_programs.py -k program`: the Phase-1 guarded-facts test (`price_text` present, `registration_url` gated closed, `auto_dm_template_id`/`hashtags` absent) and the open-registration test (`registration_url` present when open) must still pass — all covered by the allowlist + reg gate. Update a Phase-1 test ONLY if it used `summer_camp` as the program id (it uses `robotics_club`/`chess_club`, so it won't hit the new refusal).
- [ ] **Step 5: Commit** `git add app/agent/tools/parent_tool_executor.py tests/test_dynamic_programs_phase2.py && git commit -m "feat(tools): get_program_info allowlist + hardcoded refusal (gate 3)"`

---

## Task 5: End-to-end — a dynamic-program PRICE question composes

**Files:** Test `tests/test_dynamic_programs_phase2.py`.
**Interfaces:** Consumes all Phase-1 + Phase-2 changes. Mirror the Phase-1 e2e mock idiom (`tests/test_dynamic_programs.py::test_e2e_new_program_answered_end_to_end`).

- [ ] **Step 1: Write the e2e test** — drive `conversation_service.process_message` with the LLM mocked (tool_call → final text derived from the tool result), flags `USE_DYNAMIC_PROGRAMS` + `USE_PARENT_LLM_ENGINE` enabled across `conversation_service`/`parent_flow`/`parent_llm_engine`/`app.config` (frozen-settings pattern); inject `robotics_club`; ask **"რობოტიკის კლუბი რა ღირს?"**; assert the reply carries the program's own price (from the executor tool-result) and NOT the camp `2150`, and that `_maybe_handle_repeat_camp_price` did not answer. **First check whether gate-1 routing now delivers this on turn 1** (it routes a named dynamic program to PARENT directly) — if so, assert the single-turn path; only fall back to the two-turn idiom if turn 1 is owned by the welcome menu. Copy the response-object shape + `dataclasses.replace` swaps from the Phase-1 e2e test verbatim.
- [ ] **Step 2: Run — expect PASS.** If it still routes to the camp interceptor, gate-2 placement is wrong — fix the guard, not the test.
- [ ] **Step 3: Commit** `git add tests/test_dynamic_programs_phase2.py && git commit -m "test: e2e — dynamic-program price question answered end-to-end (Phase 2)"`

---

## Task 6: Verification gate (SCOPED flag-ON — fix #1)

- [ ] **Step 1: Full suite, flags OFF** `.venv/Scripts/python.exe -m pytest -q` — no NEW failures vs the known-good `4893 passed / 28 skipped / 1 pre-existing fast_track`. (The Phase-2 tests self-enable the flag via monkeypatch, so they run here too.)
- [ ] **Step 2: SCOPED flag-ON regression — NOT the whole suite.** conftest preserves `USE_DYNAMIC_PROGRAMS` from env, so a whole-suite env-flag-ON run changes routing suite-wide against live `sections.yaml` (unstable, and the parent guard isn't even exercised because conftest pins `USE_PARENT_LLM_ENGINE=False`). Instead run the dynamic-program tests plus a NAMED routing/camp/adult regression subset:

```bash
.venv/Scripts/python.exe -m pytest \
  tests/test_dynamic_programs.py tests/test_dynamic_programs_phase2.py \
  tests/test_parent_llm_engine.py \
  -q -k "route or routing or segment or classify or price or program or camp or adult" || true
# then the focused routing/segment regression files that exist in the repo:
.venv/Scripts/python.exe -m pytest tests/ -q -k "classify_segment or route_decision" 
```
Confirm green. (These exercise the flag-ON matcher/guard/allowlist paths without the unstable whole-suite env-flag run.)

- [ ] **Step 3: Eval gate, READ-ONLY** `cp evals/baseline.json /tmp/ref; .venv/Scripts/python.exe -m evals.run_evals; diff evals/baseline.json /tmp/ref` (must be identical; restore if changed; confirm 0 external writes).
- [ ] **Step 4: Doc note commit** (docs only).

**Phase 2 DoD:** Tasks 1-6 green; a dynamic-program PRICE question composes end-to-end (no camp hijack), incl. an age-bearing dynamic message; routing no longer hijacks camp-context messages and no Latin-substring false positives; `get_program_info` is an allowlist and refuses the 3 hardcoded programs; with `USE_DYNAMIC_PROGRAMS=false` everything is byte-identical and the full suite has 0 new failures; the ambiguous-stem drift guard passes; `evals/baseline.json` unchanged. **The flag is still OFF — enablement + a supervised staging smoke is a separate operator step (the user's GitHub auto-deploys).**

---

## Self-Review — critique → fix mapping

| Critique (from the plan review) | Severity | Fixed in |
|---|---|---|
| #1 flag-ON whole-suite gate unstable (conftest preserves the flag; depends on live sections.yaml; guard not even exercised) | 🟠 MAJOR | **Task 6 Step 2** → scoped flag-ON regression, whole-suite env-flag run removed |
| #2 guard below `_maybe_handle_out_of_range_age` (:1395) → age-bearing dynamic message hijacked by camp eligibility | 🟠 MAJOR | **Task 3** → guard moved to FIRST branch inside `if engine_flag:` (before the whole chain) + age-bearing test |
| #3 DRY/drift: re-typed ambiguous list + duplicated hardcoded-id set | 🟠 MAJOR | **Task 1** drift-guard sync test; `_HARDCODED_PROGRAM_IDS` derived from `ProgramId` in Tasks 3 & 4 |
| #4 recall for short (<6-char) Georgian names | 🟡 residual | documented below (precision-over-recall is deliberate; `list_programs` + prompt hint aid discovery) |
| #5 redundant `get_active_sections()` reads per turn | 🟡 residual | accepted (no cache by design; small YAML) |
| #6 name tokens not specificity-gated | 🟡 residual | accepted + documented: names are inherently specific; operator guidance = name programs distinctively |
| #7 e2e turn-count assumption | 🟡 | **Task 5 Step 1** verifies turn-1 routing rather than assuming the two-turn idiom |
| #8 Phase 2 adds more hardcoded lists | 🟡 | acknowledged: these are safety/precision constraints, not program data; the id set now derives from the enum and the ambiguous set is drift-guarded |

**Residuals (intentionally out of scope):** short-name recall (#4); triple `get_active_sections` read per dynamic turn (#5); name-token over-match for a program deliberately named with a common word (#6); the full `ProgramId` enum-generalization (a larger refactor — the shared matcher is the pragmatic bridge); and enabling the flag + supervised staging smoke (an operator step, not this branch). Contact/booking handlers do not run for a dynamic-program turn (guard-first) — correct for Phase 2 (no dynamic booking flow yet).
