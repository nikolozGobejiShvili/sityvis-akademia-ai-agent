# HANDOFF

## 2026-07-31 — live-test arc: 4 commits, merged (PR #18), deploy `d3eef9db`

Full detail is at the TOP of `CLAUDE.md` (section „🟢 CURRENT STATE — 2026-07-31"). Short form:

| commit | what it fixed |
|---|---|
| `3f3adee` | per-program follow-up was unreachable for every admin-panel program; the reply medium (Markdown) was never stated to the model |
| `cabfa84` | ⭐ adjacent same-role turns were GLUED for Anthropic — „კი"+„კი" arrived as „კიკი"; name+phone+age arrived as one unparsable run |
| `1e20a4d` | the test suite silently depended on the developer's `.env`; `test_agent.py` date-bomb + stale stub settings |
| `7ce29df` | literal example dates; past-day slots; business hours prompt-only; the lead's own booking reported as a conflict |

Gate on every commit: `pytest tests/ -q` = **1 failed / 5555 passed / 28 skipped** (the one failure,
`test_approved_copy_service_2026_07_11`, is pre-existing and unrelated). `evals` offline **93/100**.

**Binding operator rule this arc followed:** never fix by adding a prohibition or a new deterministic
path. Every change is a deletion, a symmetry restoration, or supplying a fact the model lacked.

### Start the next session here
1. Boot log of deploy `d3eef9db` — is `⚙️ USE_CONSULTATION_PROGRAM_NAME=…` present (new line ⇒ new
   code is live), and is `USE_PROGRAM_FOLLOWUP` true? Without it the follow-up fix is inert.
2. The Markdown fix is **unverified against a live model**.
3. A date defect may remain („ხვალ 12:00" → „წარსულ თარიღად ხედავს"); hypothesis is that `cabfa84`
   already covers it — **not proven**.
4. Pull `/data/admin_config/sections.yaml` off the Railway volume — Disneyland / Sunday School cannot
   be reproduced locally without it.
5. The camp is OFF **by operator decision**. `test_agent.py`'s 31 failures and 14 of the eval's 23
   are that single correct answer, not defects.

Railway MCP is connected (user scope). Project `brilliant-vision`, service `web`. OAuth ⇒
`list-variables` returns names only; flag VALUES come from the boot log.

---
# HANDOFF - AI Sales Agent / Word Academy

Last updated: 2026-07-14.

This handoff is current for Release Checkpoint #1. It intentionally summarizes the state needed for push/deploy approval and does not require reading the old chat history.

## Branch And Release Rule

- Branch: `feat/camp-topic-facts`
- Release candidate hash: `c1a30c334abb2a1b8d91ef5363a49330e08ce2b5`
- Railway deployment method: Railway UI only, Deploy Latest Commit.
- Do not run `railway up`.
- No push, deploy, restart, Railway action, Meta write, or external-account QA has been done.
- Next action requires explicit human approval: push `feat/camp-topic-facts`, then deploy Release Checkpoint #1.

## Current Lifecycle State

Local accessor verification under committed config:

- Camp program status: `active`
- Camp registration status: `closed`
- `is_camp_registration_open()`: `False`
- Camp ended: `False`
- Intended business state: Camp active, final stream in progress, registration closed, informational support still enabled.

## Latest Local Commits

Newest first:

- `c1a30c334abb2a1b8d91ef5363a49330e08ce2b5` - `test: stabilize closed camp regression suite`
  - Additional full-regression corrective test commit after the first full-suite pass exposed order/time/cache issues.
  - Files: 37 Python test/harness files.
  - Stat: 238 insertions, 189 deletions.
  - Scope: tests only. No runtime, config, prompt, approved-copy, knowledge YAML, or Georgian runtime copy changes.
- `beed093` - `config: close summer camp registration`
  - File: `data/admin_config/sections.yaml`.
  - Semantic change: `summer_camp.registration_status: closed`.
  - Camp `status` remains `active`; Camp is not ended; stream dates/status were not changed.
- `26e868d` - `test: isolate open camp scenarios from closed production config`
  - Tests-only isolation for open-registration historical scenarios.
- `e933df6` - `fix: enforce closed camp registration across runtime paths`
  - Runtime deterministic gate for closed Camp registration.
- `0c45d32` - `test: align legacy comment and llm expectations with canonical runtime`
- `9ff9290` - `fix: route camp medical clarification through approved copy`

No implementation/config/test diff remains after `c1a30c3`; only pre-existing `CLAUDE.md`, this uncommitted `HANDOFF.md`, and pre-existing report/docs/evals/tools artifacts remain dirty/untracked.

## Registration Gate Coverage

Closed registration blocks these paths without marking Camp ended:

- Direct registration request.
- Registration-link request.
- Parent-flow URL-first registration answer.
- Router consultation-first registration answer.
- START/BOOK fast-track registration answer.
- Parent tool `get_camp_info({topic: registration})` URL output.
- Booking/calendar entry and reschedule booking entry.
- Pending booking commit while registration is closed.
- Comment-origin Camp DM registration URL / active registration CTA.
- Open-registration follow-up sales CTA.
- Availability/places claim paths that would imply registration is open.

Informational paths remain enabled:

- Price and payment-process answers.
- Transport, location, duration, age, stream/date facts where visible.
- Program details and current-parent support.
- Medical/medication clarification.
- Parent call/visit support.
- Unknown exact-detail manager/detail fallbacks.
- Adult events behavior remains independent and unchanged.

## Test Isolation Strategy

No global/autouse open-registration fixture was added.

Local non-autouse fixtures now model legacy/open scenarios explicitly:

- `camp_registration_open`: patches canonical registration accessors to open only in tests that exercise historical registration, booking, or follow-up behavior.
- `camp_streams_visible`: deterministic Camp stream clock for comment/rich-DM tests that intentionally expect visible stream facts.
- `adult_events_june_2026_clock`: deterministic adult-event clock for legacy June 2026 event tests.

Additional full-regression corrections in `c1a30c3`:

- Root `test_agent.py` smoke harness now restores `sys.modules` after installing fake `app.services.*` modules, preventing cross-file leakage into Sheets/calendar/adult subscription tests.
- Historical booking/reschedule tests use future date anchors where the old June/July 2026 slots became past dates after 2026-07-14.
- Side-cache assertions use canonical conversation cache keys where runtime uses canonical session identity.
- Stale price/payment expectations now match the canonical split: price amount returns full block; pure payment-process does not mention `2150`.
- No tests were skipped, xfailed, deleted, or converted to trivial assertions.

## Validation Summary

Focused validation before the full-regression corrective commit:

- Exact corrected parent-LLM nodes: 36 passed.
- `tests/test_parent_llm_engine.py`: 214 passed.
- `tests/test_comment_flow.py`: 55 passed.
- Registration regression: 132 passed.
- Follow-up regression: 58 passed.
- `tests/test_admin_config.py`: 29 passed.
- Closed-registration tests: 8 passed.
- Price/Camp regression: 67 passed.
- RouteDecision regression: 33 passed.
- Adult-events regression: 106 passed.
- Collect-only before full-suite repairs: 4036 tests collected.

Final validation after `c1a30c3` repairs:

- Modified Python files compile: 37 compiled successfully.
- Collect-only: 4034 tests collected in 6.09s.
- Full repository regression: 4006 passed, 28 skipped, 3 warnings in 3140.88s (52m20s).
- `git diff --check --ignore-cr-at-eol`: passed; only existing `HANDOFF.md` CRLF warning before this rewrite.
- Cached diff: empty after commits.
- Generated pytest temp directories removed.

Removed generated temp directories:

- `.pytest_tmp_affected_after_batch6`
- `.pytest_tmp_diag_adult`
- `.pytest_tmp_full_after_leak_fix`
- `.pytest_tmp_full_after_repairs2`
- `.pytest_tmp_full_suite`
- `.pytest_tmp_leak_check`
- `.pytest_tmp_lf_after_batch1`
- `.pytest_tmp_lf_after_batch2`
- `.pytest_tmp_lf_after_batch3`
- `.pytest_tmp_lf_after_batch7`

## Rollback Points

Use both rollback concepts depending on the incident:

- Full registration-closure rollback baseline: `9ff9290`.
  - This is the last commit before the runtime registration gate sequence started.
  - Use if the deterministic registration-closure runtime behavior itself must be backed out.
- Config-only reopening point: `26e868d`, the commit immediately before `beed093 config: close summer camp registration`.
  - Use when runtime gate is acceptable but production should reopen registration by reverting or counteracting only the config activation.
  - Because `c1a30c3` is tests-only after config activation, a config-only revert on top of the release candidate is also possible if approved.

## Prepared Push / Deploy Plan

Do not execute without explicit approval.

1. Final local pre-push check:
   - `git status --short`
   - `git diff --cached --name-status --ignore-cr-at-eol`
   - Confirm only `CLAUDE.md`, `HANDOFF.md`, and pre-existing untracked artifacts are dirty.
2. Push command prepared:
   - `git push origin feat/camp-topic-facts`
3. Railway:
   - Open Railway UI.
   - Select project `brilliant-vision`, service `web`.
   - Deploy Latest Commit for `c1a30c334abb2a1b8d91ef5363a49330e08ce2b5`.
   - Do not run `railway up`.
4. Env/flag checklist without printing values:
   - `META_PAGE_ID` and any page-id aliases match the client page.
   - Messenger/Meta access tokens are present, not logged.
   - OpenAI key present if LLM features remain enabled.
   - Redis setting matches intended production state.
   - Registration config deployed with `summer_camp.registration_status: closed`.
5. Meta/webhook verification:
   - Verify webhook receives DMs/comments for the intended page.
   - No Meta config write without approval.
6. External QA after deployment only with approval.

## External QA Matrix

For each item, confirm no private values are printed in logs, duplicate messages dedupe correctly, and RouteDecision/trace remains redacted.

1. Price DM: parent/camp route, full price block allowed, registration URL forbidden, no booking state/tool.
2. Ask whether registration is possible now: closed-registration route, URL/CTA forbidden, no booking state/tool.
3. Ask for registration link: closed-registration route, URL forbidden, no booking state/tool.
4. Ask whether places are available: no availability claim; closed/manager-safe handling; rollback if it claims seats or open registration.
5. Ask next stream/date: answer only known visible facts; no invented future stream; no registration URL.
6. Price then registration follow-up: price allowed first; registration follow-up closed, URL forbidden.
7. Registration then consultation/booking follow-up: no Calendar booking, no pending booking commit while closed.
8. Parent call/visit: informational daily-update/support answer remains; no registration URL.
9. Medical/medication: approved medical clarification remains; no registration URL; no invented policy.
10. Transport: deterministic transport answer remains; no registration URL.
11. Unknown exact-detail: manager/detail fallback remains; no registration URL.
12. Old Camp post comment -> DM: comment DM must not include registration URL or active registration CTA.
13. Sticky ADULT user asks Camp registration: safe camp registration-closed handling; no adult event corruption.
14. Duplicate identical messages: dedupe still prevents duplicate sends/state churn.
15. Current-parent informational question: support remains; no registration URL.
16. Adult event question: adult route/admin-config behavior unaffected.
17. Unknown/ambiguous message: no Camp registration leak.
18. LLM-owned fallback phrasing: no URL, no availability claim, no booking promise.

Rollback condition: any registration URL/active-registration CTA, booking/calendar write, availability claim, invented future stream, raw ID/token/contact leak, or wrong page delivery in production QA.

## Remaining Work After Release Checkpoint #1

Do not start these before the approved release unless separately requested:

- Generic multi-program architecture / program registry.
- Generic lifecycle gate beyond the Camp-specific closure gate.
- Prompt reduction / hardcoded prompt fact cleanup.
- Comment-origin RouteDecision lifecycle.
- Broader source-of-truth cleanup for all programs.
- External live QA execution.

## Final Local Decision

Release Checkpoint #1 is locally ready. Explicit user approval is the only remaining requirement before push and Railway deployment.

