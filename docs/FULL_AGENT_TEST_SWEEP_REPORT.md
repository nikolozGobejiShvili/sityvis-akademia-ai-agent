# FULL AGENT TEST SWEEP — DIAGNOSTIC REPORT

**Date:** 2026-06-14 (run window ~22:00–23:55 Asia/Tbilisi, system clock GST)
**Scope:** Diagnostic only. NO production code / prompt / data / `.env` changed. Nothing live run.
**Model:** real OpenAI `gpt-4.1-mini`; externals mocked (Calendar/Sheets/Meta/Notification); Redis off.
**Harness:** offline pytest + the sanctioned `tools/scenario_runner_full.py` + a temporary scratch harness
(`_scratch_sweep_harness.py`, outside app/tests/tools/data, **deleted at end** — it only *imported*
`scenario_runner_full`'s `force_engine_on()/force_redis_off()/install_mocks()`, never edited it).

> **TL;DR.** One **P0 data-integrity bug CONFIRMED** (previously an unverified open question): a **booked**
> lead's `child_age` is **silently overwritten** by a direct age self-correction ("არა, 15"), with the
> booking left intact and **no manager handoff** — verified 5/5 runs. Two test-suite/data **date-bombs** are
> the only reason the green baseline broke today (the "გია მურღულია" event passed its `14 ივნისი 20:00` time).
> Plus several P1/P2 quality items (price-number omission on objection/manipulation turns; vague-event
> non-listing; two stale scenario assertions; one English-word leak). All scenario-runner failures were
> re-run 3× and classified stable vs stochastic.

---

## 0. SAFETY / INTEGRITY CONFIRMATION (verified)

| Check | Result |
|---|---|
| `app/agent/prompts/` byte-identical (before == after) | ✅ all 12 files identical (hashes below) |
| `tools/scenario_library.py` unchanged | ✅ `dbc6a068…e2ddcc` (identical) |
| `tools/scenario_runner_full.py` unchanged | ✅ `c55c26bf…40fc700` (identical) |
| `data/admin_config/templates.yaml` | ✅ `d0fdde74…3959ee` (identical — the "benign re-save" never fired) |
| `.env` unchanged | ✅ `e9600bea…e0503` (identical) |
| Full manifest diff over `app/ tests/ tools/ data/` (201 files) | ✅ **IDENTICAL — zero changes** |
| `tools/reports/` HTML files | ✅ still 19 (all scenario runs used `--no-html`; nothing written) |
| Scratch harness + scratch logs deleted | ✅ (see §6) |
| Only persistent file created | ✅ `docs/FULL_AGENT_TEST_SWEEP_REPORT.md` (this file) |
| Anything live run / production marked green | ❌ none — production NOT green |

**Prompt SHA-256 (before == after, byte-identical):**
```
e0466e0c…  detect_comment_intent.md      e857802c…  parent_communication_style.md
50cd689d…  detect_segment.md             b239f849…  parent_present_value.md
4d047e80…  detect_start_intent.md        fb0c0538…  parent_turn_analyzer.md
82a0aac6…  summary.md                    dbefaf42…  system_adult.md
b5c65a3f…  system_adult_v1.md            3cdd4755…  system_base.md
40fc1cf7…  system_parent.md              306c4369…  system_parent_v2.md
```

---

## 1. STEP 1 — EXISTING GATES AT MAX COVERAGE

| Gate | Result | Notes |
|---|---|---|
| `pytest tests/ -q` | **2332 passed, 2 failed, 28 skipped** | 2 failures = **date-bomb** (see below), NOT a logic regression |
| `pytest tests/corpus/ -q` | **9 / 9 passed** ✅ | matches baseline |
| `RUN_PROPERTY_TESTS=1 pytest tests/property/ -q` | **28 / 28 passed** ✅ | M1–M6 hold |
| `python test_agent.py` | **✅ all checks passed** | fully mocked; correctly lists only "fromula 1" for adult comments |
| `scenario_runner --priority CRITICAL --no-html` | **22 / 22 passed** ✅ | clean isolated run |
| `scenario_runner --no-html` (ALL = **77** scenarios) | **65 / 77 passed** | 12 failures, classified below (library grew 74→77) |
| `scenario_runner --category transcript` | covered in full run: **2 / 3** | SC-TX-03 fails (date-bomb) |

### 1a. The 2 pytest failures = date-bomb, not a regression
`tests/test_p0_live_hotfix.py::test_bug2_named_event_direct_no_target_no_age` and
`::test_bug2_named_event_answer_fields_and_no_subscription_cta` both hardcode the message
`"გია მურღულიას საღამო როდის არის"` and assert the LLM is bypassed with a direct answer containing
`14 ივნისი` / `29 ლარი` / `https://`.

That event (`date_text: "14 ივნისი  20:00"`) is now **past** the system clock (`Jun 14 22:05+`), so
`is_adult_event_past()` → `True`, `get_active_adult_events()` returns **only "fromula 1"**, and
`find_active_events_by_reference("გია მურღულია")` → `[]`. The named-event branch therefore correctly
defers (returns `None`) → the LLM is consulted → `llm_spy == [1]` → test fails. **The agent code is
behaving correctly** (a past event must not be answered as active). The tests are time-bombed against an
elapsed fixture. Deterministic — fails on every run while the clock is past `14 ივნისი 20:00`.

### 1b. Full-run failures — 3× re-run classification (stable vs stochastic)

Each failure re-run **3× in isolation** (no concurrency). `P`=pass, `F`=fail.

| ID | Cat / Prio | full run | rerun ×3 | Verdict |
|---|---|---|---|---|
| SC-08 Age Mentioned First | happy_path / IMPORTANT | F | P P F | **stochastic** (wording) |
| SC-09 Long Conversation Then Age | happy_path / IMPORTANT | F | P P F | **stochastic** (wording) |
| SC-14 Modality Question Mid-Booking | booking / IMPORTANT | F | P F P | **stochastic** (wording) |
| SC-16 Outside Hours (20:00) | booking / IMPORTANT | F | F F F | **STABLE — stale scenario** (not agent bug, see §4-F6) |
| SC-22 Price Objection | objection / IMPORTANT | F | P F P | **stochastic** |
| SC-23 Competition Mention | objection / NORMAL | F | P P P | **stochastic** (full-run fail was a 429) |
| SC-41 Age Approximate | difficult / NORMAL | F | P P P | **stochastic** (full-run fail was a 429) |
| SC-42 Age Range | difficult / NORMAL | F | P P F | **stochastic** |
| SC-44 Child Writes Themselves | difficult / NORMAL | F | F F F | **STABLE — stale scenario** (not agent bug, see §4-F6) |
| SC-47 Two Children | difficult / NORMAL | F | F P P | **stochastic** |
| SC-63 Price Manipulation | difficult / **CRITICAL** | F | F F F | **STABLE — real (price-omission), see §4-P1b** (note: PASSED in the earlier isolated CRITICAL gate → 1 pass / 4 fail overall) |
| SC-TX-03 Transcript event/date/guest | transcript / NORMAL | F | F F F | **STABLE — date-bomb** (see §4-P1c) |

**Rate-limit note (evidence):** the full run hit OpenAI TPM 429s (`Limit 200000 tokens/min`) because a brief
STEP-3 harness run overlapped it; `openai_service.chat_with_tools` does **not** retry on 429, so an
overlapped scenario can fall back and spuriously fail (this explains SC-22/SC-23/SC-41/SC-63's full-run
fails). All re-runs above were done **without** concurrency, which is why most flipped to PASS. Genuine
stochastic wording flakes (SC-08/09/14/42/47) still vary run-to-run with broad expected-token lists — this
matches the HANDOFF's documented happy_path/wording stochasticity (SC-14/SC-23/SC-42 explicitly tracked).

**CRITICAL gate is healthy:** the dedicated `--priority CRITICAL` run was **22/22**. The lone CRITICAL
miss in the full run (SC-63) is the price-omission quality issue (§4-P1b), not a crash/security failure;
security 4/4 and adult 3/3 passed.

---

## 2. STEP 2 — CONVERSATION-LEVEL CHAOTIC-USER RED-TEAM (real model, multi-turn)

All run via the scratch harness (real model, externals mocked, Redis off). Per scenario: behaviour vs
expectation, verdict, key turns.

| # | Scenario | Verdict | What happened (key turns) |
|---|---|---|---|
| 1 | Segment pivot camp→event→camp | **PASS** (minor) | camp→asks age; "ღონისძიება მაინტერესებს"→adult+target Q; "არა, ისევ ბანაკი…"→"ბანაკის შესახებ დაგეხმარებით. რამდენი წლისაა…". Pivot handled, no confusion. **Minor:** `conversation.segment` stayed `ADULT` while replying camp-correctly; one reply double-asked age. (P2) |
| 2 | Multi-question single msg | **PASS** | "რა ღირს, სად ტარდება და რამდენი დღეა?" → answered **all three**: ამბასადორ კაჭრეთი + 7-დღიანი + 2150 ლარი + payment split. |
| 3 | Messy age 13→15→9 (PARENT) | **PASS** | final `child_age = "9"` (correct). Corrections chained cleanly. |
| 4 | Name correction ლიზი→ნინო | **PASS** (minor) | reply addressed **"ნინო"** (not ლიზი) and offered slots. **Minor:** `lead.name`/`phone` not yet persisted at this pre-booking stage (P2). |
| 5 | Adult target self-revert | **PASS** | "შვილისთვის"→asks child age; "არა, ჩემთვის"→"რამდენი წლის ბრძანდებით…" (self). `adult_target_relation` cleared. (B4 holds) |
| 6 | Under/over-age + info (7/8/18/19) | **PASS** | 7 & 8 → fixed ineligible message (9–17 range, declines booking, offers manager), **no booking push**. 18 & 19 → routed to adult cultural events, no camp push. Eligibility correct. |
| 7 | Vague event ("მოწვეული სტუმრები" / "პოსტში ღონისძიება ვნახე") | **FAIL (P1)** | Both turns: explains what cultural evenings are + **asks the self/child target question**. Does **NOT** list the active event ("fromula 1"). No invention (good), but no list either. **Reproduces the tracked live behavior** (deflects rather than checking the active list). |
| 8 | Named event direct — "გია მურღულია" (now PAST) | **PASS** | "ღონისძიება … უკვე დასრულებულია. … მიმდინარე/მომდევნო გაგაცნოთ?" — correctly reports ended, no invention. |
| 8b | Named event direct — "fromula 1" (ACTIVE) | **PASS** | Direct deterministic answer: title/date/format-location/price/link + soft "სხვა ღონისძიებებიც ჩამოგითვალოთ?" — **no target/age question, no subscription CTA**. BUG-2 fix intact. |
| 9 | Off-topic / defer | **PASS** | "რა ამინდია…" → brand menu (graceful). "მოგვიანებით…" → "გასაგებია. … თავისუფლად მომწერეთ." No broken state. |
| 10 | Angry/frustrated | **PASS** | "ბოდიშს გიხდით. ვეცდები, სწრაფად და ზუსტად დაგეხმაროთ. …" — apologizes, stays helpful, not patronizing. |
| 11 | Price objection "ძვირია 2150" | **PASS** (P2 blemish) | empathy + value ("2150 ლარში შედის…") + payment split + soft CTA, in paragraphs, no aggressive push. **Blemish:** English word **"comprehensive"** leaked into the Georgian sentence (P2, §4-P2). |

---

## 3. STEP 3 — TARGETED PROBES OF KNOWN-OPEN ITEMS

| # | Probe | Verdict | Evidence |
|---|---|---|---|
| 1 | **B5 × B1** — booked lead (`child_age=10`, booked) + DIRECT first-child correction "არა, 15" | **❌ FAIL — booked age SILENTLY OVERWRITTEN 10→15** | **5/5 runs** (1 concurrent + 4 isolated). `child_age` → `"15"` every run; `calendly_booked/booked_datetime_iso/calendar_event_id` left intact (now mismatched). **No manager handoff.** See §4-P0. |
| 2 | Second child on booked lead ("ჩემი მეორე შვილი 14 წლისაა") | **✅ PASS** | child_age stayed **10**; reply = "თქვენი კონსულტაცია უკვე ჩანიშნულია. მეორე ბავშვისთვის ცალკე ჩაწერა სჭირდება — … მენეჯერთან." (B5 guard works) |
| 3 | Multi-child mixed eligibility ("ერთი 10, მეორე 18") | **✅ PASS** | "თქვენი 10 წლის შვილით ბანაკი სრულად შესაბამისია, ხოლო 18 წლის … 9–17 … ზრდასრულთა … დაგეხმარებით." Handled both; child_age captured as 10. |
| 4 | Event-price after camp context ("ღონისძიების ფასი რა არის?") | **✅ PASS** | Returned the **event** (fromula 1, 5000 ლარი + link), **never the camp 2150**. P0 ISSUE 4 holds. (camp price IS genuinely 2150 in all data sources — no price-discrepancy bug) |
| 5 | Unknown date/guest ("16-ში ღონისძიება", "გალაკტიონი") | **PARTIAL (P1)** | No invention (good): "16" → asks target instead of "no event on the 16th + active list"; "გალაკტიონი" → asks target instead of listing. Does **NOT** surface the active list. Same root cause as STEP 2-7 / AD-1. |

### 3.1 B5 × B1 VERDICT (the open question) — **CONFIRMED: a booked lead's age CAN be silently overwritten.**

- **Behavior:** Preset booked lead `child_age="10"`, `calendly_booked=True`, `booked_datetime_iso=2026-06-17T11:00`. User sends a bare self-correction **"არა, 15"** (not a second child). Result every run: `lead.child_age = "15"`. The booking fields are untouched, so the CRM/manager-email/follow-up now describe a **15-year-old for a consultation that was booked for a 10-year-old**, and **no manager handoff** is offered.
- **Determinism:** 5/5 (1 concurrent + 4 isolated, incl. 3 clean isolated re-confirms). The agent's surface reply varies (booking-confirm / value-pitch / eligibility note) but the overwrite happens regardless.
- **Root cause (code-read):**
  - `parent_llm_engine.run_parent_llm_turn` → after a no-tool LLM reply, calls
    `maybe_capture_child_age_fallback(lead, user_message, …)` at **`app/agent/llm/parent_llm_engine.py:1653`** with **no booked-state guard**.
  - `maybe_capture_child_age_fallback` treats "არა" as a STRONG correction marker → bypasses the
    "already-set → no overwrite" early return → writes `child_age="15"` (`parent_llm_engine.py:182–223`).
  - The **B5 guard** (`parent_flow._maybe_requalify_child` + `_lead_has_active_booking`) only protects the
    **requalify / second-child** path (it requires a phrase like "მეორე შვილ"); "არა, 15" never enters it.
- **This matches the HANDOFF "OPEN QUESTION — B5 × B1" exactly, and answers it: it is NOT safe.**

---

## 4. PRIORITIZED FINDINGS

### P0 — data-integrity / client-facing serious

**[P0] Booked lead's `child_age` silently overwritten by a direct age self-correction (B5×B1 gap).**
- One-line: On a booked/DONE lead, "არა, 15" (or any strong-marker age correction) silently rewrites the
  booked child's `child_age` with no manager handoff; the Calendar/CRM booking stays but now describes the
  wrong age.
- Trigger: STEP 3 probe S3-1 (5/5 runs).
- Likely fix layer: **deterministic**. Add a booked-state guard to the B1 fallback call at
  `parent_llm_engine.py:1653` (and/or inside `maybe_capture_child_age_fallback`): when
  `_lead_has_active_booking(lead)`, do **not** overwrite — route to the same `_BOOKED_SECOND_CHILD_MANAGER`
  handoff that B5 uses. (Pure deterministic change; no prompt edit.)

### P1 — quality / UX / conversion

**[P1a] Vague / unknown event mention does not surface the active event list.**
- One-line: "მოწვეული სტუმრები გყავთ?", "პოსტში ღონისძიება ვნახე", "16-ში ღონისძიება", "გალაკტიონის
  საღამო" → the agent explains cultural evenings and/or asks the self/child target, but never lists the
  active event(s) ("fromula 1") nor says "no event on the 16th — here's what's active". (No invention — safe.)
- Trigger: STEP 2-7a/b, STEP 3-5a/b.
- Likely fix layer: **prompt** (with small deterministic assist). This is the documented **AD-1** item:
  the ADULT flow asks the target before it can age-filter+list. Rework to "list active events after target
  known / offer to list", or have the deterministic layer surface the active list when
  `find_active_events_by_reference` returns `[]` for an event-ish query.

**[P1b] Price number omitted on objection / manipulation / follow-up turns (incl. price-manipulation defense).**
- One-line: On "თქვენ მითხარით 1000 ლარია" the agent neither echoes the false 1000 (good) **nor re-asserts
  the real 2150** — it drops the price number entirely and pivots to value/payment. Also observed on a plain
  "რა ღირს ბანაკი?" follow-up (no number). It states the price reliably on the *first* price ask, but not on
  these later turns.
- Trigger: SC-63 (CRITICAL, stable-fail 3×, §1b) + STEP 3 S3-4 A3 + REP-SC63.
- Likely fix layer: **prompt + optional deterministic**. Same class as the tracked SC-26 price-omission;
  strengthen the "always restate the price number when price is discussed/challenged" rule, or add a
  deterministic price-restate guard on price-objection/manipulation turns. (Per HANDOFF: do **not**
  re-introduce a price-reorder instruction — that caused SC-26.)

**[P1c] Date-bombed tests/scenario + stale operator event data (the "გია მურღულია" event has passed).**
- One-line: 2 pytest tests (§1a) and SC-TX-03 (§1b) hardcode the `14 ივნისი 20:00` "გია მურღულია" event as
  active; it is now past, so the agent correctly hides it and those fixtures fail. The active adult-event
  list is now down to a single event ("fromula 1", 28 აგვისტო). The agent code is correct; the
  tests/scenario and the operator data are stale.
- Trigger: `pytest tests/`, SC-TX-03.
- Likely fix layer: **neither agent code** — operator refreshes the event date in `sections.yaml` and the
  date-dependent fixtures are made relative (fixture/test change, not done here per task rules). Until then,
  the green baseline is time-dependent.

### P2 — polish

**[P2a] English word "comprehensive" leaked into a Georgian reply** (S2-11 A3). Prompt/model — occasional;
a sanitizer entry could strip, but it's whack-a-mole.
**[P2b] Pivot back to camp leaves `conversation.segment="ADULT"`** while replying camp-correctly (S2-1).
Deterministic — segment label lag; behaviorally masked by `_is_parent_consultation_intent`, but worth a guard.
**[P2c] Corrected name shown but not persisted** to `lead.name` pre-booking (S2-4). Deterministic — minor.
**[P2d] Child self-identifying ("მე ვარ ნიკა 13 წლის") framed as "თქვენი შვილის ასაკი"** (REP-SC44). Prompt —
parent-perspective assumption; minor.
**[P2e] Stale scenario assertions** (report-only; cannot edit per task): **SC-16** asserts 20:00 is "outside
hours" but the window is now 10:00–21:00 (20:00 is a valid start → agent says "თავისუფალია"); **SC-44** U1
expects the "გვითხარით" menu but explicit camp intent ("ბანაკი მინდა") now skips the menu (ISSUE-1 contract).
Both are deterministically-failing **scenario bugs**, not agent bugs.
**[P2f] Minor reply redundancy / over-asking** — double age question in one reply (S2-1 A2); asks age right
after a "later" deferral (S2-9b). Prompt-level polish.

---

## 5. NEW vs ALREADY-KNOWN / TRACKED

| Finding | Status |
|---|---|
| **P0** B5×B1 booked-age overwrite | **Tracked as an OPEN QUESTION (unverified) in HANDOFF/CLAUDE.md — now VERIFIED as a real bug (NEW confirmation).** |
| **P1a** vague/unknown event not listing active events | **Already tracked** (P1 "vague event deflects to manager" + AD-1). Reproduced/confirmed; refined (here it deflects to the *target question*, not always to a manager). |
| **P1b** price-number omission on objection/manipulation turns | **Partly known** (SC-26 price-omission class). The **price-manipulation** manifestation + SC-63 CRITICAL-tier stable-fail is **NEW evidence**. |
| **P1c** date-bomb tests/scenario + stale "გია მურღულია" data | **NEW today** (baseline was captured before the event time; the event elapsed during this session). Stale operator data was flagged generally; this specific breakage is new. |
| **P2a** English "comprehensive" leak | **NEW** (minor). |
| **P2b** segment label stays ADULT after pivot back | **NEW** (minor). |
| **P2c** corrected name not persisted pre-booking | **NEW** (minor). |
| **P2d** child-self-intro framed as parent | **NEW** (minor). |
| **P2e** SC-16 / SC-44 stale scenario assertions | **NEW** (SC-16 vs 10:00–21:00 window; SC-44 vs ISSUE-1). SC-14/SC-23/SC-42 flakiness was already tracked. |
| Stochastic flakes SC-08/09/14/22/23/41/42/47 | **Already tracked class** (happy_path/wording stochasticity). Not bugs. |

---

## 6. FINAL CONFIRMATIONS

- ✅ `app/agent/prompts/` **byte-identical** before/after (12 hashes in §0).
- ✅ No real scenario library changed: `tools/scenario_library.py` + `tools/scenario_runner_full.py`
  **byte-identical**.
- ✅ Scratch harness deleted: `_scratch_sweep_harness.py` and the two copied scratch logs
  (`_scratch_harness_main.log`, `_scratch_harness_step3.log`) removed; the only files they wrote to
  (`C:\tmp\*`, OS temp) are outside the repo.
- ✅ Only `docs/FULL_AGENT_TEST_SWEEP_REPORT.md` created/updated. **Full manifest diff over
  app/tests/tools/data = ZERO changes.**
- ✅ No code / test / data / `.env` changed. `data/admin_config/templates.yaml` byte-identical (the
  sanctioned re-save never fired).
- ✅ Rerun evidence provided for every scenario-runner failure (§1b, 3× isolated).
- ✅ Nothing live run (no Messenger/IG/Redis/Calendar/Sheets/email/Meta writes; `LIVE_BROADCAST_ENABLED=false`;
  scenario_runner used `--no-html`). **Production NOT green.**

---

## 7. RECOMMENDED TRIAGE ORDER (for the separate, gated fix task — NOT applied here)

1. **P0 B5×B1** — deterministic booked-state guard on the B1 fallback (`parent_llm_engine.py:1653` /
   `maybe_capture_child_age_fallback`); route a booked lead's age correction to the manager handoff
   (reuse `_BOOKED_SECOND_CHILD_MANAGER`). Add a regression test for the booked + "არა, 15" path.
2. **P1c** — operator refreshes the "გია მურღულია" event date (or deactivates it) and the date-dependent
   fixtures (`test_p0_live_hotfix.py` BUG-2 tests, SC-TX-03) are made clock-relative.
3. **P1b** — price re-assert rule/guard on price-objection & price-manipulation turns.
4. **P1a** — AD-1 rework so vague/unknown event queries surface the active list.
5. **P2** items as polish (incl. SC-16/SC-44 stale scenario assertions in the library).
