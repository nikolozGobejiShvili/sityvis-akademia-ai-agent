# HANDOFF — live-test arc, 2026-07-31

Four commits, merged as PR #18 into `feat/camp-topic-facts`, deploy `d3eef9db`.
**Full detail is at the TOP of `CLAUDE.md`** (section „🟢 CURRENT STATE — 2026-07-31") — that file is
loaded into every session, so it is the authoritative record. This is the short index.

| commit | what it fixed |
|---|---|
| `3f3adee` | per-program follow-up was unreachable for every admin-panel program; the reply medium (Markdown) was never stated to the model |
| `cabfa84` | ⭐ adjacent same-role turns were GLUED for Anthropic — „კი"+„კი" arrived as „კიკი"; name+phone+age arrived as one unparsable run |
| `1e20a4d` | the test suite silently depended on the developer's `.env`; `test_agent.py` date-bomb + stale stub settings |
| `7ce29df` | literal example dates; past-day slots; business hours prompt-only; the lead's own booking reported as a conflict |

Gate on every commit: `pytest tests/ -q` = **1 failed / 5555 passed / 28 skipped** — the one failure,
`test_approved_copy_service_2026_07_11::test_parent_flow_start_book_intent_uses_fast_track_and_advances_state`,
is pre-existing and unrelated. `python -m evals.run_evals` offline = **93/100**, unchanged.

**Binding operator rule this arc followed:** never fix by adding a prohibition or a new deterministic
path — that is what turned 1 bug into 2–10. Every change is a deletion, a symmetry restoration, or
supplying a fact the model lacked. Not one banned phrase was added.

## Start the next session here

1. **Read the boot log of deploy `d3eef9db`.** Is the line `⚙️ USE_CONSULTATION_PROGRAM_NAME=…`
   present? It did not exist before this arc, so its absence means an OLD container is still serving.
   And is `USE_PROGRAM_FOLLOWUP` true? Without it the follow-up fix is inert.
2. **The Markdown / reply-medium fix is UNVERIFIED against a live model.** Check a real reply for
   `**`, `|`, `#`.
3. **A date defect may remain.** Live docx: „ხვალ 12:00 თავისუფალია" → on confirm → „სისტემა წარსულ
   თარიღად ხედავს". „ხვალ" is future, so that answer is wrong. HYPOTHESIS ONLY: the „კიკი" corruption
   made the model lose the date thread, so `cabfa84` may already cover it. **NOT PROVEN** — re-test.
4. **Pull `/data/admin_config/sections.yaml` off the Railway volume.** It is not in the repo, so
   Disneyland and Sunday School cannot be reproduced locally without it.
5. **The camp is OFF by operator decision.** `test_agent.py`'s 31 failures and 14 of the eval's 23
   failing checks are that single correct answer („ბანაკის ბოლო ნაკადი უკვე დაიწყო…"), not defects.
   `--llm --judge` scored 84/100, but it is measuring a deliberately closed funnel — re-point the
   eval cases at the live programs before trusting that number.
6. `summary.md` was restructured, but the CRM „Conversation Summary" bloat it targets was **never
   reproduced** (12 live runs on claude-sonnet-4-6, old and new prompt, all clean). Do not claim it
   fixed.
7. `app/agent/skills/*.md` is a FOURTH live prompt layer (`USE_SKILLS=true`) the prompt audit never
   covered.

## Environment notes

* `.env` now mirrors the Railway boot log (14/14 flags). `pytest` is deliberately hermetic and can
  never show where the live agent is — that is correct and must stay. The tool that mirrors
  production is the eval harness (it starts from live settings via `dataclasses.replace`).
* Railway MCP is connected at user scope. Project `brilliant-vision`
  `fae52cbf-2960-45fb-bfd6-2908aebc9740`, service `web` `38c9f623-8555-423d-a5f6-3f2fa420de30`,
  env `production` `82c8602a-ed1f-4a43-bc5e-bd4e35c69a18`. Connected via OAuth, so `list-variables`
  returns **names only** (`valuesRedacted: true`) — flag VALUES still come from the boot log.

## Method notes that paid off

* The Railway logs and the live `.docx` transcript found root causes that screenshots and reasoning
  did not. **Ask for logs first.**
* Any character-level claim made through a shell pipe is inadmissible — Georgian mangles to cp1252.
  Read files in Python with explicit UTF-8.
* When a symptom is "new since `LLM_PROVIDER=anthropic`", suspect the provider translation layer in
  `app/services/anthropic_service.py` before suspecting the prompt.
