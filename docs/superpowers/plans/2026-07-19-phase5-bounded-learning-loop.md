# Phase 5 — Bounded Learning Loop (`USE_LEARNING`) — Implementation Plan (v2, critique-hardened)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
>
> **v2 changes (from the critique):** (#1) `build_active_tools` gets a DEFAULTED second param so the Phase-1 tests keep passing; (#2) a flag-gated prompt hint tells the LLM the `get_approved_answer` tool exists (else the reuse — Part B's whole value — never fires, the same "LLM won't know" gap Phase 1 hit); (#3) the outcome log applies a defensive PII mask so a phone number in the user message is never stored raw; and the classifier drops the unreliable `declined` label.

**Goal:** Let the agent improve over time — *safely, human-gated*. (A) Passively LOG each turn's coarse outcome so the operator sees what's working. (B) Let the operator promote good answers into an operator-editable **approved-answers** store that the agent REUSES via a tool. The agent NEVER auto-mutates prompts, NEVER auto-approves, NEVER deploys. Behind `USE_LEARNING` (default OFF) → flag-off byte-identical.

**Architecture:** Two additive, flag-gated pieces. **(A) Outcome log:** a pure `classify_outcome` + a capped, PII-masked `learning_log_service` appended at the post-response chokepoint in `conversation_service._process_message_impl` (beside the Phase-4 lead-memory save hook). Write-only; no answer-path change. **(B) Approved-answer reuse:** an operator-editable `data/admin_config/approved_answers.yaml` (mirrors `camp_topic_facts.yaml` triggers→answer + `admin_config_service` hot-reload) consulted through a NEW `get_approved_answer` LLM tool (mirrors Phase-1's `get_program_info`: the LLM proposes, the backend returns a vetted answer, the LLM decides how to use it — no deterministic override), with a flag-gated prompt hint so the model actually calls it. The operator fills the store by reviewing the log; the agent only READS it.

**Tech Stack:** Python 3.10, FastAPI, OpenAI GPT-4.1-mini function-calling, YAML, Redis (optional), pytest (~4929) + read-only `evals/` harness.

## Global Constraints

- **Bounded & human-gated:** the agent NEVER writes `approved_answers.yaml`, NEVER changes a prompt, NEVER deploys. It only appends outcome records and reads operator-approved answers. Every learned behavior change is operator-vetted.
- **Additive & flag-gated:** reached only when `USE_LEARNING` is True. Flag OFF ⇒ no logging, tool not offered, prompt suffix empty ⇒ byte-identical. **Phase 5 does NOT change the flag default or enable it.**
- **`Settings` is FROZEN.** Tests toggle via `dataclasses.replace(config.settings, USE_LEARNING=...)` + `monkeypatch.setattr(<module>, "settings", swapped)`.
- **Interpreter:** `.venv/Scripts/python.exe -m pytest ...`.
- **Privacy:** the log stores a PII-MASKED truncated question + a masked short answer preview + coarse outcome + segment/program. Bounded (capped ~500 records + ~90d TTL). `reset()` for erasure.
- Reuse `redis_state_service` (log) + `admin_config_service`/`knowledge_loader`/`camp_topic_facts` patterns. Degrade gracefully when Redis off. Never modify/commit `data/admin_config/sections.yaml`, `CLAUDE.md`, `HANDOFF.md`; never overwrite `evals/baseline.json`. Stage only your task's files (never `-a/-A`). **Do NOT push or deploy** (GitHub auto-deploys); all work stays local on `feat/dynamic-programs`.

## Verified current state (read before editing)

- `app/agent/llm/parent_llm_engine.py:46` — `def build_active_tools(use_dynamic: bool)` (ONE param); called at `:2076` `build_active_tools(settings.USE_DYNAMIC_PROGRAMS)`; the Phase-1 test `tests/test_dynamic_programs.py::test_build_active_tools_respects_flag` calls `build_active_tools(False)/(True)`. `_build_system_prompt` (~`:2212`) returns `base_prompt + _dynamic_programs_prompt_suffix()` — the Phase-1 hint pattern to MIRROR. `_strip_phone_numbers` (`:196`) exists (do NOT couple the log service to the engine — the log service defines its own mask).
- `app/services/conversation_service.py` — `_process_message_impl` (`:828`) EARLY-RETURNS on kill-switch (`:835-839`) and (confirm) dedup, before the post-response tail; the post-response tail (~`:1113-1160`) has `response`/`conversation`/`conversation.lead` in scope and holds the Phase-4 save hook. Outcome signals: `lead.calendly_booked`, `booked_datetime_iso`; `parent_tool_executor.manager_notified_for_conversation` (module dict at `:68`, keyed by `cache_key` — PARENT-only); `conversation.segment == "UNCLEAR"`.
- `app/reasoning/camp_topic_facts.py` — `_load_topics()` (YAML `{topic:{triggers,answer}}`), `_score(low, entry, ctx)` (trigger-substring count), `_is_excluded` — the matcher pattern to MIRROR.
- `app/agent/tools/parent_tools.py` — `DYNAMIC_PROGRAM_TOOLS`, `ALLOWED_TOOL_NAMES`, tool-schema shape — the Phase-1 tool pattern to MIRROR. `app/agent/tools/parent_tool_executor.py` — `execute` dispatch chain + `self.lead` (dataclass field). `app/services/redis_state_service.py` — `get_json/set_json(key,value,ttl_seconds)/delete/is_enabled`.
- `app/config.py` — `_parse_bool_optional` flag pattern.

## File Structure (Phase 5)

- `app/config.py` — `USE_LEARNING` flag.
- `app/reasoning/outcome_classifier.py` — NEW pure `classify_outcome`.
- `app/services/learning_log_service.py` — NEW capped, PII-masked log store.
- `app/services/conversation_service.py` — flag-gated log hook.
- `data/admin_config/approved_answers.yaml` (seed) + `app/services/approved_answers_service.py` — store + matcher.
- `app/agent/tools/{parent_tools,parent_tool_executor}.py` + `app/agent/llm/parent_llm_engine.py` — `get_approved_answer` tool + `build_active_tools` 2nd param + prompt hint.
- `tests/test_learning.py` — NEW.

---

## Task 1: Add the `USE_LEARNING` flag

**Files:** `app/config.py`; `tests/test_learning.py`. Mirror prior phases' Task-1 flag tests (`Settings().USE_LEARNING is False`; env-parse True; no `importlib.reload`). Add the class default near `USE_LEAD_MEMORY` + the `_parse_bool_optional("USE_LEARNING", False)` line in `from_env`.
- [ ] Steps: failing test → run FAIL → add flag → run PASS → **Commit** `feat(config): USE_LEARNING flag (default off)` (stage `app/config.py` + `tests/test_learning.py`).

---

## Task 2: Outcome classifier + PII-masked capped log store

**Files:** Create `app/reasoning/outcome_classifier.py`, `app/services/learning_log_service.py`; Test `tests/test_learning.py`.
**Interfaces:**
- `classify_outcome(conversation, lead, response, *, manager_notified=False) -> str` — PURE. Priority: empty `response` → `"empty"`; `lead.calendly_booked` or `booked_datetime_iso` set → `"booked"`; `manager_notified` → `"handed_off"`; `conversation.segment == "UNCLEAR"` → `"unclear"`; else `"answered"`. **(No `declined` — it is a user intent detected earlier and not reliably visible post-response; folded into `answered` for v1.)**
- `learning_log_service`: `MAX_RECORDS=500`, `LOG_TTL_SECONDS≈7_776_000` (90d), `LOG_KEY="learninglog"`. `log_turn(record: dict) -> None` — **PII-mask** `record["question"]`/`record["answer_preview"]` via a local `_mask_pii(text)` (regex: mask runs of ≥6 digits and spaced Georgian phone groups → `"[ტელეფონი]"`), then append to a capped JSON list (get_json → append → keep last `MAX_RECORDS` → set_json with `LOG_TTL_SECONDS`). No-op when Redis disabled. Never raises. `recent(n=50)->list`; `reset()->None`.

- [ ] **Failing tests:** classify each of the 5 outcomes from constructed `Conversation`/`Lead`; log roundtrip via mocked in-memory `redis_state_service`; **PII mask** — a record whose `question` contains `"ჩემი ნომერია 555123456"` is stored with the digits masked (assert the raw number is NOT in the stored record); cap enforced (600 appended → `recent(1000)` ≤ 500); redis-off graceful; never-raises on a bad record.
- [ ] Implement (classifier pure; log service mirrors `lead_memory_service`'s never-raises/graceful shape; record `{ts, session_key, segment, program_id, outcome, question, answer_preview}`). → run PASS → **Commit** `feat(learning): outcome classifier + PII-masked capped log store`.

---

## Task 3: Wire outcome logging at the chokepoint (flag-gated)

**Files:** Modify `app/services/conversation_service.py`; Test `tests/test_learning.py`.
**Interface:** After the response is final (right after the Phase-4 lead-memory save hook, ~`:1129`), if `USE_LEARNING`: compute `manager_notified` from `parent_tool_executor.manager_notified_for_conversation.get(conversation_cache_key(conversation))`, `classify_outcome(...)`, and `learning_log_service.log_turn({"session_key": conversation_cache_key(conversation), "segment": conversation.segment, "program_id": "", "outcome": outcome, "question": (message_text or "")[:200], "answer_preview": (response or "")[:200], "ts": ...})`. Wrap in try/except best-effort — a logging failure must NEVER affect the returned `response`.

- [ ] **Failing test:** drive `process_message` (flag on, in-memory Redis, `parent_flow.handle` stubbed) → one record logged with the right `outcome`/`segment`; flag off → 0 records. (Mirror the Phase-4 save-hook e2e idiom.)
- [ ] Implement. **Note (accepted):** the hook is at the common post-response tail, so kill-switch/dedup early-return turns and any UNCLEAR turns that return before the tail are NOT logged — acceptable for a coarse log; confirm which substantive turns reach the tail and note it in the report. → run PASS → then the FULL suite once (chokepoint change; the one pre-existing `fast_track` failure is expected). → **Commit** `feat(learning): log turn outcomes at the chokepoint (flag-gated)`.

---

## Task 4: Approved-answers store + matcher

**Files:** Create `data/admin_config/approved_answers.yaml` (seed `answers: []`), `app/services/approved_answers_service.py`; Test `tests/test_learning.py`.
**Interfaces:** YAML `answers: [{id, triggers:[substrings], answer, segment:"PARENT"|"ADULT"|"any", status:"active"|"hidden"}]`. `load_answers()->list` (fresh read, tolerant → `[]`). `find_approved_answer(message, segment)->dict|None` (lowercase; among `active` answers with matching/`any` segment, score by trigger-substring count mirroring `camp_topic_facts._score`, require ≥1 hit AND skip triggers <3 chars; return highest `{id, answer}` or None; never raises).

- [ ] **Failing tests:** match returned for a triggers+segment hit; no-match → None; hidden never returned; segment mismatch → None; malformed YAML → graceful; short-trigger (<3) never matches alone. Inject the list via monkeypatching `load_answers` (do NOT edit a tracked YAML in tests).
- [ ] Implement (mirror `camp_topic_facts` scoring + `admin_config_service` tolerant fresh-read). Note: committing a NEW seed `approved_answers.yaml` (empty) is fine — it is NOT the operator's live `sections.yaml`. → run PASS → **Commit** `feat(learning): operator-editable approved-answers store + matcher`.

---

## Task 5: `get_approved_answer` tool + prompt hint — the agent REUSES vetted answers (flag-gated)

**Files:** Modify `app/agent/tools/parent_tools.py`, `app/agent/tools/parent_tool_executor.py`, `app/agent/llm/parent_llm_engine.py`; Test `tests/test_learning.py`.
**Interfaces:**
- Tool `get_approved_answer` (schema in `parent_tools.py`, added to `ALLOWED_TOOL_NAMES`, in a `LEARNING_TOOLS` list). Param `question: str`.
- **`build_active_tools` gains a DEFAULTED second param:** `def build_active_tools(use_dynamic: bool, use_learning: bool = False)` — appends `DYNAMIC_PROGRAM_TOOLS` when `use_dynamic`, `LEARNING_TOOLS` when `use_learning`. The default keeps the Phase-1 test's `build_active_tools(False)/(True)` calls valid (learning off). Update the call site `:2076` → `build_active_tools(settings.USE_DYNAMIC_PROGRAMS, settings.USE_LEARNING)`.
- Executor `_get_approved_answer(args)` → `approved_answers_service.find_approved_answer(args.get("question",""), self.lead.segment)` → `{"success": True, "id":…, "answer":…}` or `{"success": False, "reason":"no_approved_answer"}`. NO deterministic override — the LLM decides.
- **Prompt hint (fixes the "LLM won't call it" gap):** add `_approved_answer_prompt_suffix() -> str` — flag-gated, returns `""` when `USE_LEARNING` off, else a short Georgian instruction ("გაურკვეველ/ვარიაციულ კითხვაზე ჯერ გამოიძახე get_approved_answer; თუ ოპერატორის დამტკიცებული პასუხი დაბრუნდა, გამოიყენე ის; თუ არა (success:false), უპასუხე ჩვეულებრივ"). Append it in `_build_system_prompt`: `return base_prompt + _dynamic_programs_prompt_suffix() + _approved_answer_prompt_suffix()` (flag-off ⇒ `""` ⇒ byte-identical).

- [ ] **Failing tests:** `build_active_tools(False)` == today (no `get_approved_answer`); `build_active_tools(False, True)` includes it; `build_active_tools(True, True)` includes BOTH generic-program AND learning tools (flags compose); executor `_get_approved_answer` returns the matched answer (monkeypatch `find_approved_answer`) and `no_approved_answer` on none; `_approved_answer_prompt_suffix()` is `""` when flag off, non-empty when on.
- [ ] **Step: confirm the Phase-1 test still passes** — `tests/test_dynamic_programs.py::test_build_active_tools_respects_flag` calls `build_active_tools(False)/(True)`; with the DEFAULTED `use_learning=False` it is unchanged. Do NOT edit that Phase-1 test.
- [ ] Implement (mirror Phase-1 tool wiring). → run focused PASS → **Commit** `feat(learning): get_approved_answer tool + prompt hint (USE_LEARNING)`.

---

## Task 6: e2e + verification gate

- [ ] **e2e:** (a) drive `process_message` (flag on) → a turn is logged with an outcome, and its logged `question` is PII-masked; (b) with an injected approved answer matching the question and a mocked LLM that calls `get_approved_answer`, assert the reply used the vetted answer AND the tool was offered AND the prompt suffix was present. RED: flag off ⇒ no log, tool not offered, suffix empty.
- [ ] **Full suite, flags OFF** `.venv/Scripts/python.exe -m pytest -q` — no NEW failures vs `~4929 passed / 28 skipped / 1 pre-existing`.
- [ ] **Scoped flag-ON** `tests/test_learning.py -q` + `-k "conversation or tools or build_active or system_prompt"`. Not the whole suite with the env flag on.
- [ ] **Eval gate READ-ONLY** `cp evals/baseline.json /tmp/ref; python -m evals.run_evals; diff` (identical; restore if changed; 0 external writes).

**Phase 5 DoD:** with `USE_LEARNING` on, every substantive turn's coarse outcome is logged (bounded, PII-masked, never breaks a turn) and the agent can REUSE an operator-approved answer via `get_approved_answer` (LLM-mediated + prompt-hinted, no forced override); the operator is the only writer of `approved_answers.yaml`; with `USE_LEARNING=false` no logging, tool not offered, suffix empty → byte-identical (full suite 0 new failures); logging degrades gracefully when Redis off; `evals/baseline.json` unchanged. **Flag still OFF — enablement is a separate operator step.**

---

## Self-Review — critique → fix mapping

| Prior finding | Severity | Fixed in |
|---|---|---|
| **#1 `build_active_tools` signature would break the Phase-1 test** | 🟠 | **Task 5** — DEFAULTED `use_learning=False`; Phase-1 test unchanged; a new test asserts both flags compose |
| **#2 LLM won't call `get_approved_answer` (reuse never fires)** | 🟠 | **Task 5** — flag-gated `_approved_answer_prompt_suffix()` appended in `_build_system_prompt` |
| **#3 raw phone could be logged** | 🟠 | **Task 2** — `_mask_pii` on `question`/`answer_preview` in `log_turn`; test asserts the number is masked |
| **#6 `declined` unreliable** | 🟡 | **Task 2** — dropped `declined` (folded into `answered`); noted as Phase-5b (needs a conversation-state signal) |
| **#4 not-every-turn-logged** | 🟡 | **Task 3** — documented: covers substantive turns reaching the post-response tail (kill-switch/dedup/early UNCLEAR skipped) |
| **#5 `handed_off` PARENT-biased** | 🟡 | documented residual: `manager_notified_for_conversation` is PARENT-only; ADULT `reservation_status` handoff not captured in v1 |
| **#7 tool is PARENT-only** | 🟡 | documented residual: `get_approved_answer` added to the PARENT executor only; ADULT mirror is a follow-up |

**Residuals (out of scope):** trigger-substring matching (not semantic) — Phase-5b embeddings; no admin-UI to promote a logged answer into `approved_answers.yaml` (operator edits YAML); coarse heuristic outcomes; PARENT-only reuse + handoff signal; log read-modify-write is not concurrency-safe (acceptable for a low-QPS bot). Enablement + a supervised staging smoke is a separate operator step.
