# Enablement — `USE_PROGRAM_TOPICS` (topic-facts tool, Capability #1)

**Status (2026-07-22):** built, reviewed, flag default **OFF**, LOCAL-only on `feat/dynamic-programs`. Live behavior UNCHANGED until an operator enables the flag. Not pushed.

## What it does

The biggest customer-facing knowledge body — `app/agent/knowledge/camp_topic_facts.yaml` (502 lines: safety, food, gadgets, medical, daily schedule, parent communication) — is answered today by a **deterministic pre-LLM interceptor** (`parent_flow._maybe_handle_camp_topic_facts`) that substring-matches the question and returns a canned block. **The model never sees this knowledge**, so a differently-phrased topic question either hits the wrong canned fact or misses.

With `USE_PROGRAM_TOPICS` ON (and the engine on), a camp-topic question instead **reaches the LLM**, which calls the new `get_program_topic(topic)` tool and reasons a natural answer from the returned YAML facts. **Facts still come from the backend** (the tool reuses the LLM-free `answer_for_topic`/`medical_answer` readers) — the model reasons the wording, not the facts.

## Flag-OFF guarantee (the default)

With `USE_PROGRAM_TOPICS=false`: **byte-identical to today.** Proven three ways (opus-reviewed): the interceptor runs unchanged; `build_active_tools(...)` returns the same tool list on every turn (the tool lives in a separate `TOPIC_TOOLS` list kept OUT of `PARENT_TOOLS`); `_build_system_prompt()` is byte-identical (the prompt suffix returns `""`). Full suite **5187 passed / 1 pre-existing / 28 skipped**; `evals/baseline.json` md5 `93973fcd10349b447f87fa320e0807f3` unchanged.

**No booking / lead / manager-handoff path is touched** — this is a read-only info tool.

## How to enable (operator)

1. Railway env: set **`USE_PROGRAM_TOPICS=true`** AND ensure **`USE_PARENT_LLM_ENGINE=true`** (the bypass requires BOTH — yielding to an engine that won't run would drop the answer).
2. Full restart (settings are `@lru_cache`d).
3. Camp-topic questions now reach the engine + `get_program_topic`. (Topic answers are **not** camp-season-gated — they work regardless of whether a stream is open; only camp price/registration answers depend on the season.)

## Rollback

Set `USE_PROGRAM_TOPICS=false` (or remove the line) + restart → byte-identical to today. No data migration, no state to unwind.

## Proof before broad enablement — the 20-conversation review (PAID, operator step)

The flag-OFF safety is proven. What is NOT yet proven is the **behavioral win**: does the LLM-reasoned answer actually beat the canned block on varied phrasing? That is the operator-judged **20-conversation review**:

- Question set: `evals/review_topic_questions_2026_07_22.yaml` (20 Georgian parent questions; `straight` = interceptor catches, no-regression checks; `varied` = oblique phrasing the interceptor likely misses, where the tool should win).
- Runner: `tools/review_topic_capability.py` — captures baseline (flag OFF, free) vs capability (flag ON, **real OpenAI, `--yes` gated**) replies side by side; `--compare` emits a markdown table with an operator-verdict column.
- **This makes real OpenAI calls (the capability config runs the LLM) → run it with intent, on a test Page / staging, not casually.** `evals/baseline.json` is snapshot+restored around the run.

**Open honest caveat (in the YAML):** the live corpus is mostly price/booking, not deep topic questions — so *how often parents actually ask these* is itself something the review must judge. The capability is low-risk (flag-gated, byte-identical off) and directly attacks the largest short-circuited knowledge body; whether it earns enablement is the review's call.

### ⚠️ Review-protocol fidelity note (decide together before running)

The runner's `baseline` mode blocks OpenAI to stay free. That is faithful for `straight` questions (the interceptor catches them → canned block, no engine). It is **NOT** faithful for `varied` questions: today (flag off) a varied question the interceptor *misses* falls through to the **engine** (real OpenAI, *without* the topic tool) — but with OpenAI blocked the runner instead records the free **legacy fallback**, which is not what production does. So `baseline`-varied **understates** the true "today" answer, and `varied` is exactly the bucket where the capability should win.

For a fair `varied` comparison, BOTH sides must call the engine (flag OFF = engine-without-tool, flag ON = engine-with-tool) — i.e. baseline is also paid for the varied bucket. Options to settle when we run it:
1. **Straight bucket only, free** — fully faithful (canned vs tool) and costs nothing; a real but partial signal.
2. **Both buckets, both paid** — run baseline AND capability with OpenAI live (external SENDS stubbed), so `varied` compares engine-without-tool vs engine-with-tool faithfully. Needs a small runner change (allow OpenAI, stub Meta/Calendar/Sheets sends) — do NOT run the current `baseline` as-is for a varied verdict.

The capability code is unaffected either way; this is only about how we MEASURE it.

## Files

Flag `app/config.py`; tool `app/agent/tools/parent_tools.py` (`TOPIC_TOOLS`) + `parent_tool_executor.py` (`_get_program_topic`); wiring `app/agent/llm/parent_llm_engine.py` (`build_active_tools(..., use_topics)`, `_topic_tool_prompt_suffix`); bypass `app/flows/parent_flow.py` (`_maybe_handle_camp_topic_facts` gate). Plan: `docs/superpowers/plans/2026-07-22-capability-topic-facts-tool.md`.

**Not generic yet:** `sections.yaml` has no per-program topic blocks, so `get_program_topic` is camp-scoped for now; the name leaves room for a `program_id` arg once other products grow topic knowledge (a later capability).
