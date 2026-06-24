# BRIEF: PARENT engine-ში reasoning ფენის დამატება (analyze → ground → answer → reflect)

> **STATUS UPDATE (2026-06-23):** **Phase 1 is IMPLEMENTED** as a gated, **DETERMINISTIC** intent analyzer — `app/reasoning/reasoning_layer.py` (+ `app/reasoning/__init__.py`), behind flag **`USE_REASONING_LAYER`** (default OFF, pinned OFF in `tests/conftest.py`). It returns structured METADATA only (no LLM call, no user-facing text, no side effects, fail-closed) and is wired narrowly for the decline+topic-switch case; it does NOT override deterministic handlers. **This brief below describes the FUTURE LLM-based `analyze→ground→answer→reflect` expansion** (a later phase) — note the flag here is named `USE_REASONING_PASS`, which is **superseded by `USE_REASONING_LAYER`**. The sibling `docs/reference/reasoning_layer.py` scaffold is **reference-only and is NOT imported into production.**

> Claude Code-სთვის. სამუშაო branch-ში გააკეთე, არა `main`-ზე.
> წინ წაკითხვა სავალდებულო: `CLAUDE.md` (არქიტექტურა + წესები), `tests/conftest.py` (flag-pinning პატერნი).

---

## 1. კონტექსტი

ცოცხალი PARENT ნაკადი არის P3-C LLM tool-calling engine (`USE_PARENT_LLM_ENGINE=true`).
`parent_llm_engine.run_parent_llm_turn` ერთ გასვლაში აგენერირებს პასუხს, მერე post-hoc
sanitizer-ებით ასწორებს (`sanitise_response_wording`, `_suppress_redundant_age_question`,
`_strip_mid_conversation_greeting`, `_format_multipoint_paragraphs`).

**პრობლემა:** მოდელი ჯერ არ „ფიქრობს" — აგენერირებს და მერე Python ასწორებს. ამიტომ ბევრი band-aid.

**უკვე არსებული, მაგრამ dormant:** `parent_turn_analyzer.py` აგებს რიცხ JSON-ს
(`primary_intent`, `provided_fields`, `fact_types_requested`, `confidence`...), მაგრამ
legacy state-machine-ზეა მიბმული და engine-ON რეჟიმში **არ ეშვება**.

## 2. მიზანი

`run_parent_llm_turn`-ში დაამატე ცხადი ოთხ-ნაბიჯიანი reasoning ფენა:

1. **ANALYZE** — იაფი strict-JSON call (`temperature=0`, `max_tokens≈300`), რომელიც აბრუნებს
   სტრუქტურირებულ გეგმას (user_goal, sentiment, needed_facts, missing_lead_fields,
   contradictions, suggested_tool, should_greet, plan). **იუზერისთვის ტექსტს არ აგენერირებს.**
2. **GROUND** — `needed_facts`-ის მიხედვით ჩატვირთე **მხოლოდ** ის ფაქტები `knowledge_loader`-იდან.
3. **ANSWER** — არსებული tool-loop, ოღონდ extra system-directive-ით (გეგმა + verified facts).
4. **REFLECT** — საბოლოო პასუხი გადაამოწმე grounded ფაქტებთან არსებული url/phone/price/date
   regex-ით; mismatch-ზე safe fallback, არა ჰალუცინაცია.

რეფერენს-skeleton: `reasoning_layer.py` (თან ახლავს). ლოგიკა იქ არის — შენ ფაილებს მიუსადაგე.

## 3. მკაცრი წესები (CONSTRAINTS — არ დაარღვიო)

- ⛔ **ახალი duplicate ფაილი არ შექმნა.** `parent_turn_analyzer.py` / `parent_llm_engine.py`
  უკვე არსებობს — გააფართოვე ისინი (იხ. `CLAUDE.md` ხაზი ~740). ანალიზის ლოგიკა harvest-ე
  არსებული `parent_turn_analyzer`-ის prompt-იდან/სქემიდან.
- 🚩 **Flag-gated:** ახალი `USE_REASONING_PASS`, code default **`False`**. დააპინე **OFF**
  `tests/conftest.py`-ში autouse fixture-ით — ზუსტად ისე, როგორც `USE_PARENT_LLM_ENGINE=False`
  და `REDIS_ENABLED=False` არის დაპინული. Flag OFF → ქცევა **byte-identical** დღევანდელს.
- ✅ **ყველა არსებული ტესტი მწვანე უნდა დარჩეს** (2753 passed, 28 skipped, 0 failed).
  არცერთი არსებული ტესტის ქცევა არ შეცვალო, გარდა ცალსახად ახალი flag-ის გამო.
- 🔒 **არ შეცვალო:** prompt-ები (`*.md`), knowledge/admin YAML, Calendar, Sheets schema,
  booking ლოგიკა, model სახელი, `.env` მნიშვნელობები. ერთადერთი ახალი არტეფაქტი —
  ANALYZE-ის prompt (ცალკე `.md` ფაილი) + `USE_REASONING_PASS` flag config-ში.
- 🎯 **wiring მხოლოდ ცოცხალ engine-ში:** `parent_llm_engine.run_parent_llm_turn`.
  legacy state-machine ნუ შეეხები (dormant-ია).
- 🧪 **გაზომვა სავალდებულო:** `python tools/scenario_runner_full.py`. flag-ON რანი
  **CRITICAL 22/22 უნდა იყოს** და overall ≥ ახლანდელი 67/74. სტოქასტიკურ fail-ებზე rerun.
  თუ flag-ON ვერ აჯობებს flag-OFF-ს — შეჩერდი და მომახსენე, ნუ შეიტან.
- 🔐 **ლოგებში secret/PII არ გაჟონო:** sender id მასკირებული, ფასი/ნომერი არ დაბეჭდო.
  გამოიყენე არსებული mask helper-ები.
- 🆕 **ახალი ტესტები** ცალკე ფაილში: `tests/test_reasoning_pass_<YYYY_MM_DD>.py`.
  დაფარე: ANALYZE JSON-ის პარსინგი + malformed-JSON fallback; GROUND მხოლოდ needed_facts-ს
  ტვირთავს; REFLECT mismatch-ზე fallback-ს აბრუნებს; flag-OFF byte-identity; end-to-end
  `parent_flow.handle` engine-ON + flag-ON + mocked OpenAI.

## 4. იმპლემენტაცია ფაილების მიხედვით

| ნაბიჯი | ფაილი | ცვლილება |
|---|---|---|
| flag | `app/config.py` | `USE_REASONING_PASS: bool = False` (env-reader-ით, არასდროს ლოგავს) |
| ANALYZE | `app/agent/llm/parent_turn_analyzer.py` | გააფართოვე: დაამატე engine-ისთვის განკუთვნილი always-on entrypoint (მაგ. `analyze_for_engine(...) -> dict`), რომელიც აბრუნებს §2-ის სქემას. arsебულ legacy entrypoint-ს ნუ შეცვლი. |
| ANALYZE prompt | `app/agent/prompts/parent_reasoning.md` (ახალი) | strict-JSON instruction; knowledge keys + tool names + known lead facts placeholder-ებით. სცენარები მოარგე `audience_segments.yaml`-ის სეგმენტებს. |
| GROUND | `app/agent/services/knowledge_loader.py` (reuse) | preselect helper, თუ არ არსებობს; cached loader-ს ეყრდნობა. |
| ANSWER + orchestration | `app/agent/llm/parent_llm_engine.py` | `run_parent_llm_turn`-ში: `_capture_turn_facts` შემდეგ — `if settings.USE_REASONING_PASS:` ანალიზი → ground → directive-ის ინექცია tool-loop-ში → reflect. flag-OFF → არსებული გზა უცვლელად. |
| REFLECT | `app/agent/llm/parent_llm_engine.py` | reuse url/phone/price/date regex (fact-safety) → grounded facts-თან შედარება → mismatch → safe fallback + masked log. |
| tests-pin | `tests/conftest.py` | autouse fixture-ში `USE_REASONING_PASS=False`. |

## 5. Acceptance criteria (Definition of Done)

- [ ] `USE_REASONING_PASS=False` → `pytest` სრულად მწვანე (2753/28/0), ქცევა byte-identical.
- [ ] `USE_REASONING_PASS=True` → ANALYZE/GROUND/REFLECT მუშაობს; ახალი ტესტები გადის.
- [ ] `scenario_runner_full.py` flag-ON: CRITICAL **22/22**, overall ≥ 67/74.
- [ ] არცერთი prompt/YAML/Calendar/Sheets/model/.env ცვლილება (გარდა ახალი flag + ახალი reasoning `.md`).
- [ ] duplicate engine/analyzer ფაილი არ შექმნილა.
- [ ] HANDOFF.md / CLAUDE.md-ში მოკლე changelog ჩანაწერი ამ batch-ისთვის.

## 6. რეფერენსი

`reasoning_layer.py` — სქემა, ANALYZE prompt-ის ნიმუში, orchestration-ის ფორმა.
`# ── WIRE ──` ხაზები ზუსტად აჩვენებს სად დაუკავშირდე არსებულ ფუნქციებს.
