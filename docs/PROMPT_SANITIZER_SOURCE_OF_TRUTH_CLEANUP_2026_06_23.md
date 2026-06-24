# Prompt + Sanitizer Source-of-Truth Cleanup — camp age/location (2026-06-23)

## Problem
The PARENT system prompt (`system_parent_v2.md`) and the `parent_llm_engine`
sanitizer (`FORBIDDEN_PHRASE_REPLACEMENTS`) still carried **hardcoded camp facts**:

- the age literal **„9–17"** (and the „9-დან 17 წლამდე" variant), and
- the location literal **„ამბასადორ კაჭრეთი"**.

Worse, the sanitizer's forbidden-phrase table **re-injected** those literals into
outgoing replies (e.g. a harsh under-age rejection was rewritten to
„ბავშვების ბანაკი **9–17** წლის ასაკისთვისაა"; an „ადგილი - X" line was rewritten to
„ლოკაცია — **ამბასადორ კაჭრეთი**"). This is a **write-side source-of-truth bypass**:
even after an operator edits Admin Config (age band / location), the prompt and
sanitizer could reinsert the stale value.

## Fix (narrow — prompt + sanitizer only)
Camp facts now flow **only** from the canonical sources:
`admin_config_service.get_camp_age_bounds()` (age band) and the `get_camp_info`
tool / `get_camp_facts()` (location). The prompt teaches behavior, not facts.

### `app/agent/prompts/system_parent_v2.md`
- Age literals replaced with the existing `{age_min}`/`{age_max}` format
  placeholders (already supplied by `_build_system_prompt` from
  `get_camp_age_bounds()`): the en-dash typography rule, the
  „9-დან 17 წლამდე" forbidden-phrase rule, and the sibling-discount range.
- Location literal replaced with a **`<ლოკაცია>` marker** — the same convention
  as the existing `<streams>` marker that the LLM fills from `get_camp_info`
  (NOT a `.format()` placeholder; angle brackets survive `.format()`). Three
  sites: the locative-format rule, the dates+location answer template, and the
  „ადგილი - …" forbidden-phrase rule. Each now says „ლოკაცია აიღე get_camp_info-დან".
- The adult-redirect „don't mention" list dropped the „9–17," example
  („ასაკი" / „ასაკობრივი ჩარჩო" already cover it).
- The owner-flagged guard „არასოდეს დაამატო „აკადემია" სიტყვა „კაჭრეთის" შემდეგ"
  (forbidding „კაჭრეთის აკადემია") was **generalized** to „არასოდეს დაამატო სიტყვა
  „აკადემია" ლოკაციის სახელს", removing the last residual location fragment
  („კაჭრეთის") while keeping the guard intent. (Surfaced by the adversarial review;
  the legacy-path negative-assertion tests for „კაჭრეთის აკადემია" still pass.)
- `.format()` placeholder set is unchanged: only `{company_name}`, `{age_min}`,
  `{age_max}`. Rendered prompt with the shipped config is unchanged for the age
  band (still „9–17"); the location is no longer named in the prompt text.

### `app/agent/llm/parent_llm_engine.py` (sanitizer)
- **Removed** 6 fact-injecting `FORBIDDEN_PHRASE_REPLACEMENTS` entries (2 location
  reformat, 2 age-range typography, 2 harsh-under-age-rejection) **plus** the one
  age-suitability needle that embedded „9–17".
- **Added** `_camp_age_bounds_safe()` — reads the canonical
  `get_camp_age_bounds()` (admin-first, safe 9/17 default, never raises), wrapped
  so a config read can never crash a reply.
- **Added** `_apply_dynamic_fact_normalisations()`, wired into
  `sanitise_response_wording()` **before** the static loop:
  - location label „ადგილი - X" / „ადგილი — X" → „ლოკაცია — X" — **location-agnostic**
    (keeps the model's own location text, sourced from `get_camp_info`);
  - age-range typography „N-დან M წლამდე [ბავშვებისთვის]" → „N–M წლის […]" —
    **number-agnostic** (preserves whatever band the model produced);
  - „სრულად ერგება N–M წლის ბავშვების ბანაკს" → fact-free sentence;
  - the harsh under-age softener states the band from the **canonical**
    `get_camp_age_bounds()`, never a sanitizer-local literal.
  Idempotent.

The sanitizer is now never a separate source of truth: it enforces
wording/typography only, and the single rewrite that needs the band reads it
from the canonical helper.

## Tests
New: `tests/test_prompt_sanitizer_source_of_truth_2026_06_23.py` (14 tests,
RED-first). Covers: prompt renders a *divergent* canonical band (10–16) with no
„9–17" leak; prompt names no location literal; sanitizer under-age softener uses
the divergent band and never reinserts „9–17"; age typography is number-agnostic;
location label fix is location-agnostic; a structural guard that **no** needle or
replacement in the forbidden-phrase table carries a camp fact; idempotency; and
real-config assertions sourced from `get_camp_age_bounds()` (not hardcoded).

## Verification
- `pytest tests/` → **2893 passed, 28 skipped, 0 failed** (2879 baseline + 14 new).
- corpus **9/9**, property **28/28**, `test_agent.py` **PASS**.
- `scenario_runner_full.py --priority CRITICAL` → **22/22**; `--category transcript` → **3/3**.
- Real-LLM smoke (throwaway): with the canonical location overridden to a sentinel
  „ტესტ ლოკაცია ქალაქი", the bot answered „ბანაკი ტარდება ტესტ ლოკაცია ქალაქიში" —
  it echoed the operator location (correctly inflected to locative) and never used
  „ამბასადორ" nor leaked the literal „<ლოკაცია>".
- Reasoning Layer untouched: `USE_REASONING_LAYER` default **OFF**; its test file
  passes with the flag ON and OFF.

## Scope / not touched
No change to: booking flow, Calendar/Sheets/WhatsApp/email dispatch, adult events
data, Admin Panel save, manager-phone helper, camp-facts helpers, Sunday-School
config, OpenAI model, or any YAML/data file. Out of scope (noted, not edited):
legacy `system_parent.md`, and the `app/agent/templates/parent/*.yaml` /
`templates/common/routing.yaml` which still carry the literals but are
operator-editable YAML data (not the LLM-engine live path). Production NOT marked green.
