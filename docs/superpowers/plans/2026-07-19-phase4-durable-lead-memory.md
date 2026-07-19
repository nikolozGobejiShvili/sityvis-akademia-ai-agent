# Phase 4 — Durable Per-Lead Memory (`USE_LEAD_MEMORY`) — Implementation Plan (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
>
> **v2 change (from the critique — a BLOCKER):** v1 seeded `conversation.lead` right after `Conversation(...)` in `conversation_service`, but **`Conversation.lead` is `None` at construction** (`app/models/conversation.py:44`) — the `Lead` is created lazily by `_ensure_lead(conversation)` in **both** flows (`parent_flow.py:9947`, `adult_flow.py:444`). So the seed must move INTO `_ensure_lead`'s create branch. v2 also fixes: one consistent session-key source (`conversation_cache_key`) for load+save; a `lead is None` guard on save; and the acceptance test drives through `_ensure_lead`.

**Goal:** Remember a lead across conversations — a returning customer whose child's age (and name / interests) was captured earlier is **not re-asked** in a new conversation, even after the 8‑day session state expired. Behind a new `USE_LEAD_MEMORY` flag (default OFF) → flag‑off byte‑identical.

**Architecture:** Today `Conversation` (with its lazily-created `Lead`) is persisted to Redis under the canonical session key `platform:page_id:sender_id`, TTL ≈8 days. After 8 days idle it expires and a returning lead starts blank. Phase 4 adds a **separate, long‑lived durable memory record** (compact `Lead` identity facts, keyed by the SAME session key, ~1‑year TTL) that is **written after each turn** and **loaded to SEED the `Lead` at the moment `_ensure_lead` first creates it**. Because the engine's `_build_context_message` already surfaces `lead.child_age` ("instead of re-asking", `parent_llm_engine.py:2420`) and the deterministic handlers read `lead.child_age`, seeding reuses that machinery — no new prompt logic for the core DoD.

**Tech Stack:** Python 3.10, FastAPI, Redis (optional), OpenAI GPT‑4.1‑mini, pytest (~4913) + read‑only `evals/` harness.

## Global Constraints

- Additive & flag‑gated: all new behavior reached only when `USE_LEAD_MEMORY` is True. Flag OFF ⇒ no load, no seed, no store ⇒ byte‑identical output; the suite stays green. **Phase 4 does NOT change the flag default or enable it.**
- **`Settings` is FROZEN.** Toggle flags in tests via `dataclasses.replace(config.settings, USE_LEAD_MEMORY=...)` + `monkeypatch.setattr(<module>, "settings", swapped)`.
- **Interpreter:** `.venv/Scripts/python.exe -m pytest ...`.
- **Privacy:** the durable record stores the SAME lead PII the system already persists (child_age/name/phone in Redis 8d + Sheets CRM) — nothing new collected. (a) flag‑gated; (b) **bounded ~1‑year TTL** (not infinite); (c) `delete(session_key)` for erasure; (d) **never inject a raw phone into a prompt** (existing masking still applies); do not widen what reaches the LLM beyond what a same‑conversation `Lead` already surfaces.
- Reuse `redis_state_service`; **degrade gracefully** when `REDIS_ENABLED=false` (no memory).
- Never modify/commit `data/admin_config/sections.yaml`, `CLAUDE.md`, `HANDOFF.md`; never overwrite `evals/baseline.json`. Stage only your task's files (never `-a/-A`). **Do NOT push or deploy** (GitHub auto‑deploys the server); all work stays local on `feat/dynamic-programs`.
- **Never cross‑assign `child_age` ↔ `adult_age`** (the `Lead` invariant): `seed_lead` maps each durable field to its OWN `Lead` field only.

## Verified current state (read before editing)

- `app/models/conversation.py:44` — `lead: Lead | None = None` (**Lead is None at construction; created lazily**).
- `app/flows/parent_flow.py:9947` and `app/flows/adult_flow.py:444` — `def _ensure_lead(conversation)`: `if conversation.lead is None: conversation.lead = Lead(sender_id, platform, segment="PARENT"/"ADULT")`; then sets `.segment`; returns `conversation.lead`. Called 20+×; **idempotent** — the create runs once.
- `app/models/lead.py` — `@dataclass Lead` + `model_dump(mode="json")`/`from_dict`. Durable identity fields: `name, phone, child_age, challenge, deeper_concern, desired_change, event_interest, preferred_event, adult_age, adult_target_relation, adult_target_age`. (Exclude per‑booking: `booked_datetime_iso, calendar_event_id, calendly_booked, followup_sent, status`.)
- `app/services/session_key_service.py` — `conversation_cache_key(conversation)` returns `conversation.session_key` when set (it is, via `_ensure_conversation_identity` in `_get_or_create_conversation`), else derives the canonical key. **Use this ONE function for both load and save.**
- `app/services/conversation_service.py` — `_get_or_create_conversation` (`:1378`) sets `session_key` before the flow runs; `_save_conversation_to_redis(conversation)` called in `_process_message_impl` (`~:1123`). `session_key_service` is imported here.
- `app/services/redis_state_service.py` — `get_json/set_json(key,value,ttl_seconds)/delete/exists/is_enabled`.
- `app/agent/llm/parent_llm_engine.py:2420` — `_build_context_message` surfaces `child_age` to the model (confirms seeding achieves "don't re‑ask").
- `app/config.py` — `_parse_bool_optional` flag pattern; `tests/conftest.py` preserves unnamed flags.

## File Structure (Phase 4)

- `app/config.py` — `USE_LEAD_MEMORY` flag.
- `app/services/lead_memory_service.py` — NEW. `DURABLE_FIELDS`, `memory_key`, `load`, `save`, `delete`, `seed_lead`, and `maybe_seed_new_lead(conversation)` (the flag‑gated one‑liner both flows call).
- `app/flows/parent_flow.py` + `app/flows/adult_flow.py` — one line each in `_ensure_lead`'s create branch.
- `app/services/conversation_service.py` — persist memory after save (flag‑gated, `lead is None` guarded).
- `tests/test_lead_memory.py` — NEW.

---

## Task 1: Add the `USE_LEAD_MEMORY` flag

**Files:** Modify `app/config.py`; Test `tests/test_lead_memory.py`.

- [ ] **Step 1: Failing test**

```python
# tests/test_lead_memory.py
def test_use_lead_memory_flag_defaults_false():
    from app.config import Settings
    assert Settings().USE_LEAD_MEMORY is False

def test_use_lead_memory_flag_parses_env(monkeypatch):
    monkeypatch.setenv("USE_LEAD_MEMORY", "true")
    from app.config import Settings
    assert Settings.from_env().USE_LEAD_MEMORY is True
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Class default** (after `USE_DYNAMIC_PROGRAMS`):

```python
    # Durable per-lead memory (2026-07): a returning lead's captured facts
    # (child age / name / interests) survive past the 8-day session and seed a
    # new conversation so they are not re-asked. OFF ⇒ no store, identical.
    USE_LEAD_MEMORY: bool = False
```

- [ ] **Step 4: Env parse** (next to the other `_parse_bool_optional` lines):

```python
            USE_LEAD_MEMORY=_parse_bool_optional("USE_LEAD_MEMORY", False),
```

- [ ] **Step 5: Run — expect PASS. Step 6: Commit** `git add app/config.py tests/test_lead_memory.py && git commit -m "feat(config): USE_LEAD_MEMORY flag (default off)"`

---

## Task 2: The durable memory store + seed helper (`lead_memory_service.py`)

**Files:** Create `app/services/lead_memory_service.py`; Test `tests/test_lead_memory.py`.
**Interfaces:** `DURABLE_FIELDS`; `memory_key(session_key)`; `save(session_key, lead)`; `load(session_key)->dict|None`; `delete(session_key)->bool`; `seed_lead(lead, memory)`; **`maybe_seed_new_lead(conversation)->None`** (flag‑gated: no‑op unless `USE_LEAD_MEMORY` and `conversation.lead` exists; loads by `conversation_cache_key(conversation)` and seeds). All never raise.

- [ ] **Step 1: Failing tests**

```python
def _lead(**kw):
    from app.models.lead import Lead
    return Lead(sender_id="s", platform="facebook", segment="PARENT", **kw)

def test_save_and_load_roundtrip(monkeypatch):
    from app.services import lead_memory_service as lm, redis_state_service as rss
    store = {}
    monkeypatch.setattr(rss, "is_enabled", lambda: True)
    monkeypatch.setattr(rss, "set_json", lambda k, v, ttl=None, **kw: store.__setitem__(k, v) or True)
    monkeypatch.setattr(rss, "get_json", lambda k: store.get(k))
    lm.save("facebook:P:s", _lead(child_age="10", name="ნინო"))
    mem = lm.load("facebook:P:s")
    assert mem["child_age"] == "10" and mem["name"] == "ნინო" and "updated_ts" in mem

def test_seed_only_fills_empty_fields():
    from app.services import lead_memory_service as lm
    lead = _lead(child_age="")
    lm.seed_lead(lead, {"child_age": "12", "name": "გია"})
    assert lead.child_age == "12" and lead.name == "გია"
    lead2 = _lead(child_age="7")
    lm.seed_lead(lead2, {"child_age": "12"})   # must NOT overwrite a known fact
    assert lead2.child_age == "7"

def test_seed_never_cross_assigns():
    from app.services import lead_memory_service as lm
    lead = _lead(child_age="", adult_age="")
    lm.seed_lead(lead, {"child_age": "10", "adult_age": "30"})
    assert lead.child_age == "10" and lead.adult_age == "30"   # each to its own field

def test_redis_disabled_is_graceful(monkeypatch):
    from app.services import lead_memory_service as lm, redis_state_service as rss
    monkeypatch.setattr(rss, "is_enabled", lambda: False)
    lm.save("facebook:P:s", _lead(child_age="10"))
    assert lm.load("facebook:P:s") is None

def test_booking_fields_not_persisted():
    from app.services import lead_memory_service as lm
    for f in ("booked_datetime_iso", "calendar_event_id", "calendly_booked"):
        assert f not in lm.DURABLE_FIELDS

def test_maybe_seed_new_lead_flag_off_is_noop(monkeypatch):
    import dataclasses
    from app import config
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=False))
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    conv.lead = _lead(child_age="")
    called = {"load": 0}
    monkeypatch.setattr(lm, "load", lambda k: called.__setitem__("load", called["load"] + 1))
    lm.maybe_seed_new_lead(conv)
    assert called["load"] == 0 and conv.lead.child_age == ""

def test_maybe_seed_new_lead_flag_on_seeds(monkeypatch):
    import dataclasses
    from app import config
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    monkeypatch.setattr(lm, "load", lambda k: {"child_age": "9"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    conv.lead = _lead(child_age="")
    lm.maybe_seed_new_lead(conv)
    assert conv.lead.child_age == "9"
```

- [ ] **Step 2: Run — expect FAIL** (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** (READ `redis_state_service.set_json` to confirm the TTL arg):

```python
# app/services/lead_memory_service.py
"""Durable per-lead memory (USE_LEAD_MEMORY). A compact, long-lived record of a
lead's identity facts, keyed by the canonical session key, so a returning lead's
child age / name / interests survive past the 8-day conversation TTL and seed a
new conversation. Wraps redis_state_service; never raises; no-op when Redis off
or the flag is off."""
from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.models.lead import Lead
from app.services import redis_state_service, session_key_service

logger = logging.getLogger(__name__)

# Identity facts worth remembering across conversations. EXCLUDES per-booking /
# calendar state — that is conversation-scoped, not durable identity.
DURABLE_FIELDS: tuple[str, ...] = (
    "name", "phone", "child_age", "challenge", "deeper_concern",
    "desired_change", "event_interest", "preferred_event",
    "adult_age", "adult_target_relation", "adult_target_age",
)
LEAD_MEMORY_TTL_SECONDS: int = 31_536_000  # ~1 year (bounded, not infinite)
_PREFIX = "leadmem:"


def memory_key(session_key: str) -> str:
    return _PREFIX + (session_key or "")


def save(session_key: str, lead: Lead) -> None:
    if not session_key or lead is None or not redis_state_service.is_enabled():
        return
    try:
        record: dict[str, Any] = {
            f: getattr(lead, f) for f in DURABLE_FIELDS if getattr(lead, f, "")
        }
        if not record:
            return
        record["updated_ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        redis_state_service.set_json(memory_key(session_key), record, LEAD_MEMORY_TTL_SECONDS)
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[lead_memory] save failed for %s: %s", session_key, exc)


def load(session_key: str) -> dict | None:
    if not session_key or not redis_state_service.is_enabled():
        return None
    try:
        data = redis_state_service.get_json(memory_key(session_key))
        return data if isinstance(data, dict) else None
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[lead_memory] load failed for %s: %s", session_key, exc)
        return None


def delete(session_key: str) -> bool:
    if not session_key or not redis_state_service.is_enabled():
        return False
    try:
        return bool(redis_state_service.delete(memory_key(session_key)))
    except Exception:  # pragma: no cover - best-effort
        return False


def seed_lead(lead: Lead, memory: dict | None) -> None:
    """Fill ONLY empty Lead fields from memory (never overwrite a fact the
    current turn already established; each field maps to itself — no cross-
    assign)."""
    if lead is None or not memory:
        return
    for field in DURABLE_FIELDS:
        if getattr(lead, field, ""):
            continue
        value = memory.get(field)
        if value:
            setattr(lead, field, str(value))


def maybe_seed_new_lead(conversation) -> None:
    """Called by `_ensure_lead` right after it creates a fresh Lead. Flag-gated
    no-op: seeds the new lead from durable memory keyed by the conversation's
    session key. Never raises."""
    if not getattr(settings, "USE_LEAD_MEMORY", False):
        return
    lead = getattr(conversation, "lead", None)
    if lead is None:
        return
    try:
        key = session_key_service.conversation_cache_key(conversation)
        seed_lead(lead, load(key))
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("[lead_memory] maybe_seed_new_lead failed: %s", exc)
```

- [ ] **Step 4: Run — expect PASS. Step 5: Commit** `git add app/services/lead_memory_service.py tests/test_lead_memory.py && git commit -m "feat(services): durable lead-memory store + maybe_seed_new_lead helper"`

---

## Task 3: Seed on lead creation (both flows) + persist after save (flag‑gated)

**Files:** Modify `app/flows/parent_flow.py`, `app/flows/adult_flow.py`, `app/services/conversation_service.py`; Test `tests/test_lead_memory.py`.
**Interfaces:** Each `_ensure_lead` calls `lead_memory_service.maybe_seed_new_lead(conversation)` INSIDE its create branch (fires once, when the lead is first created). `conversation_service` writes memory after `_save_conversation_to_redis` (flag‑gated, `lead is None` guarded), using `conversation_cache_key(conversation)` — the SAME key `maybe_seed_new_lead` loads from.

- [ ] **Step 1: Failing tests**

```python
def test_parent_ensure_lead_seeds_on_create(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    monkeypatch.setattr(lm, "load", lambda k: {"child_age": "8", "name": "ანა"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    lead = pf._ensure_lead(conv)         # first creation → seeded
    assert lead.child_age == "8" and lead.name == "ანა" and lead.segment == "PARENT"

def test_adult_ensure_lead_seeds_on_create(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import adult_flow as af
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    monkeypatch.setattr(lm, "load", lambda k: {"adult_age": "34"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    lead = af._ensure_lead(conv)
    assert lead.adult_age == "34" and lead.segment == "ADULT"

def test_ensure_lead_flag_off_not_seeded(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=False))
    monkeypatch.setattr(lm, "load", lambda k: {"child_age": "8"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    assert pf._ensure_lead(conv).child_age == ""     # flag off ⇒ blank

def test_ensure_lead_does_not_reseed_existing(monkeypatch):
    import dataclasses
    from app import config
    from app.flows import parent_flow as pf
    from app.services import lead_memory_service as lm
    from app.models.conversation import Conversation
    monkeypatch.setattr(lm, "settings", dataclasses.replace(config.settings, USE_LEAD_MEMORY=True))
    calls = {"n": 0}
    monkeypatch.setattr(lm, "load", lambda k: calls.__setitem__("n", calls["n"] + 1) or {"child_age": "8"})
    conv = Conversation(sender_id="s", platform="facebook", page_id="P")
    pf._ensure_lead(conv); pf._ensure_lead(conv); pf._ensure_lead(conv)
    assert calls["n"] == 1                            # seed only on first creation
```

- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Add the seed to BOTH `_ensure_lead`s.** In `app/flows/parent_flow.py:9948-9953`, inside the `if conversation.lead is None:` branch, AFTER the `conversation.lead = Lead(...)` assignment:

```python
    if conversation.lead is None:
        conversation.lead = Lead(
            sender_id=conversation.sender_id,
            platform=conversation.platform,
            segment="PARENT",
        )
        from app.services import lead_memory_service
        lead_memory_service.maybe_seed_new_lead(conversation)
```

Do the IDENTICAL insertion in `app/flows/adult_flow.py:445-450` (segment `"ADULT"`). (Import locally to avoid any import-cycle at module load.)

- [ ] **Step 4: Persist memory after save** in `conversation_service._process_message_impl`, immediately AFTER `_save_conversation_to_redis(conversation)` (`~:1123`):

```python
    if getattr(settings, "USE_LEAD_MEMORY", False) and conversation.lead is not None:
        try:
            from app.services import lead_memory_service
            lead_memory_service.save(
                session_key_service.conversation_cache_key(conversation),
                conversation.lead,
            )
        except Exception:  # pragma: no cover - best-effort
            pass
```

_(Confirm `settings` and `session_key_service` are imported in `conversation_service` — they are.)_

- [ ] **Step 5: Run — expect PASS.** Then the full suite ONCE (`.venv/Scripts/python.exe -m pytest -q`) — this touches both flows + the routing chokepoint; the one pre-existing `fast_track` failure is expected, no OTHER new failures.
- [ ] **Step 6: Commit** `git add app/flows/parent_flow.py app/flows/adult_flow.py app/services/conversation_service.py tests/test_lead_memory.py && git commit -m "feat(memory): seed lead from durable memory on creation; persist after save (flag-gated)"`

---

## Task 4: Acceptance — returning lead's child age is remembered across conversations

**Files:** Test `tests/test_lead_memory.py`.
**Interfaces:** Consumes all of the above; drives `process_message` twice with the SAME sender, an in‑memory Redis backing.

- [ ] **Step 1: Write the acceptance test.** Back `redis_state_service.get_json/set_json/delete/is_enabled` with an in‑memory dict (so both the conversation store and the `leadmem:` store live in it). `USE_LEAD_MEMORY=True` on all modules the path reads (`lead_memory_service`, `parent_flow`, `conversation_service`) via `dataclasses.replace`. **Conversation A:** create the conversation, get its lead via `parent_flow._ensure_lead`, set `lead.child_age="10"`, then call the memory `save` (or drive a turn that reaches the post‑save hook). **Simulate 8‑day expiry:** clear the `conversation:*` entry (or the in‑memory `conversations` dict + the conversation Redis key) but KEEP the `leadmem:` entry. **Conversation B (same sender):** call `parent_flow._ensure_lead(fresh_conversation)` and assert `lead.child_age == "10"` (seeded), and — building context via `parent_llm_engine._build_context_message(convB, convB.lead, "…")` — assert the rendered context string contains `10` (proving the model is told the age, i.e. the "don't re‑ask" precondition). Mirror the mock/flag‑swap idiom from `tests/test_dynamic_programs_phase2.py`.
- [ ] **Step 2: Run — expect PASS.** If the seeded age doesn't reach `_build_context_message`, fix the wiring (seed happens in `_ensure_lead`, which the engine path calls before building context), not the test.
- [ ] **Step 3: Commit** `git add tests/test_lead_memory.py && git commit -m "test: e2e — returning lead's child age remembered across conversations"`

---

## Task 5: Verification gate

- [ ] **Step 1: Full suite, flags OFF** `.venv/Scripts/python.exe -m pytest -q` — no NEW failures vs `~4913 passed / 28 skipped / 1 pre-existing fast_track`.
- [ ] **Step 2: Scoped flag‑ON** `.venv/Scripts/python.exe -m pytest tests/test_lead_memory.py -q` (self‑enables) + a lifecycle regression subset (`-k "conversation or redis or session or ensure_lead"`). Do NOT run the whole suite with the env flag on (conftest preserves it → unstable).
- [ ] **Step 3: Eval gate, READ‑ONLY** `cp evals/baseline.json /tmp/ref; .venv/Scripts/python.exe -m evals.run_evals; diff evals/baseline.json /tmp/ref` (identical; restore if changed; 0 external writes).

**Phase 4 DoD:** a returning lead's `child_age`/`name`/interests captured earlier seed a fresh `Lead` at `_ensure_lead` creation and reach `_build_context_message` so they aren't re‑asked; with `USE_LEAD_MEMORY=false` there is no load/seed/store and behavior is byte‑identical (full suite 0 new failures); the store degrades gracefully when Redis is off; booking/calendar fields are never persisted; seeding never overwrites a live fact and never cross‑assigns; `delete(session_key)` exists for erasure; `evals/baseline.json` unchanged. **Flag still OFF — enablement is a separate operator step.**

---

## Self‑Review — critique → fix mapping

| Prior finding | Severity | Fixed in |
|---|---|---|
| **#1 seed hook wrong — `Conversation.lead` is None at create** | 🔴 BLOCKER | **Task 3** — seed moved INTO `_ensure_lead`'s create branch (both flows), verified `parent_flow.py:9948`/`adult_flow.py:445` |
| **#2 two `_ensure_lead`; seed only on create** | 🟠 | **Task 3** — identical one‑liner in both, inside `if conversation.lead is None:`; `test_ensure_lead_does_not_reseed_existing` pins single‑seed |
| **#3 key inconsistency (save vs load)** | 🟠 | one source: `session_key_service.conversation_cache_key(conversation)` used by BOTH `maybe_seed_new_lead` (load) and the save hook |
| **#4 save must guard `lead is None`** | 🟠 | `save` early‑returns on `lead is None`; the call site also guards `conversation.lead is not None` |
| **#5 `delete_lead_memory` vs `delete` naming** | 🟡 | standardized on `delete(session_key)` everywhere (DoD updated) |
| **#6 acceptance test complexity** | 🟡 | Task 4 drives through `_ensure_lead` + `_build_context_message` explicitly |
| **#7 segment‑mixing** | 🟡 | `seed_lead` maps each field to its own; a PARENT `child_age` seeded into an ADULT lead is stored‑unused (adult flow reads `adult_age`); `test_seed_never_cross_assigns` pins no cross‑assign |

**Residuals (out of scope):** the *real* not‑re‑asked behavior is validated by the eval harness / staging, not fully by a mocked‑LLM unit test; no "returning lead" greeting/personalization prompt yet (Phase‑4b: inject a compact memory note); cross‑page identity is page‑scoped; no consent/erasure UI (operator‑level `delete()` only). Enablement + a supervised staging smoke is a separate operator step.
