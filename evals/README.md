# Agent-understanding eval harness (`evals/`)

Measures **how well the agent understands free-form Georgian and chooses the
right decision** — intent understanding, entity extraction, parent/adult
routing, response quality, and follow-up logic. This is *not* a unit-test suite
for functions (those already pass); it scores the agent's **decision quality**.

## Run

```bash
# deterministic, FREE, fully offline (no OpenAI, no network)
python -m evals.run_evals

# + full_turn cases (drives the real engine via process_message → real OpenAI)
python -m evals.run_evals --llm

# + Claude LLM-as-judge for nuanced response quality (needs ANTHROPIC_API_KEY)
python -m evals.run_evals --llm --judge

python -m evals.run_evals --category routing      # one dimension
python -m evals.run_evals --case E1               # one case
```

Exit code `0` = all run checks passed **and** no READ-ONLY tripwire hit; `1` otherwise.

## What it scores (5 dimensions)

| dimension | what it checks | example case |
|---|---|---|
| understanding | free-form / non-standard phrasing intent | camp intent vs menu; parent→child contact vs socialization |
| extraction | age, Georgian relative dates/times, name | `ხვალ 11 საათზე`→tomorrow 11:00; `8 საათზე`→20:00 |
| routing | parent↔adult segment + action priority | camp action overrides sticky ADULT |
| response_quality | grounded (no invention), on-topic, polite | no invented room occupancy; price-objection value framing |
| followup | who/when/what (mocked clock) | +24h→`first_24h`; booked/declined→skip |

## Two check kinds

- **code** — objective, deterministic assertions. Most cases call the agent's
  real decision functions directly (no LLM) — cheap, exact, free.
- **judge** — Claude binary rubric (one criterion at a time) for the nuanced
  *response quality* dimension only. Disabled without `ANTHROPIC_API_KEY`
  (marked SKIPPED, never a silent pass).

## 🔴 READ-ONLY guarantee (`evals/safety.py`)

Every external side-effect is a recording **dry-run stub**: Calendar writes,
Sheets writes, manager email/WhatsApp, outbound Messenger/Instagram DM, and
follow-up sends. Hard tripwires that must stay at 0: **SMTP** (always) and raw
**httpx** (in deterministic-only mode). Live guards pinned:
`ALLOW_LIVE_WHATSAPP=False`, `LIVE_BROADCAST_ENABLED=False`, `REDIS_ENABLED=False`.
Every run ends with a `✅ READ-ONLY VERIFIED` line accounting for 0 live calls.

> OpenAI / Anthropic are the **models under test** (only with `--llm` / `--judge`)
> — not a side-effect. The default run touches neither.

## Layout

```
evals/
  safety.py     # READ-ONLY install + dry-run stubs + tripwires + banner
  judge.py      # Claude LLM-as-judge (binary rubric; skip if no key)
  harness.py    # Harness driver + runner + scoring + failure report
  cases.py      # ~18 cases across the 5 dimensions (mined from real live-QA bugs)
  run_evals.py  # CLI
```

Cases are sourced from real failures: `tests/test_legacy_*` / `*_patch` /
`*regression`, the dated rules in `app/agent/prompts/system_parent_v2.md`, and
HANDOFF/CLAUDE bug history. Add a case by appending an `EvalCase` to
`cases.CASES` with a `run(h)` that returns a `CaseOutcome`.
