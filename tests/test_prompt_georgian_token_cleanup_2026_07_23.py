"""Georgian token cleanup guard (Step 3, 2026-07-23).

Locks in the removal of the garbled / mixed-script / mistranslated tokens fixed
in the PARENT + ADULT system prompts, so they cannot silently reappear.
"""
from pathlib import Path

import pytest

_PROMPTS = Path(__file__).resolve().parents[1] / "app" / "agent" / "prompts"
_PARENT = (_PROMPTS / "system_parent_v2.md").read_text(encoding="utf-8")
_ADULT = (_PROMPTS / "system_adult_v1.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("token", [
    "bloки",                # Latin+Cyrillic garble → ბლოკის
    "ZUSTAD",               # Latin transliteration → ზუსტად
    "Calendar-ს კითხვის",   # ungrammatical → Calendar-ს ეკითხება
])
def test_parent_prompt_has_no_garbled_tokens(token):
    assert token not in _PARENT


@pytest.mark.parametrize("token", [
    "ფუტურულ",              # Latinate coinage → მომავალ
    "ASAKIS",               # Latin transliteration → ასაკის
    "ASAKI-ის",             # Latin transliteration → ასაკის
    "grammatical",          # English word spliced in → გრამატიკული
    "ცხადს ცხადს",          # broken repetition → reconstructed
    "aktiur",               # Latin transliteration → აქტიურ
    "გლობალური ფასად",      # "facade" mistranslation of floor → მინიმუმი
])
def test_adult_prompt_has_no_garbled_tokens(token):
    assert token not in _ADULT


def test_partial_title_mistranslation_replaced_in_adult():
    # „პარტიული" (partisan/political-party) was a mistranslation of "partial"
    # title; now „ნაწილობრივი". NOTE: the political „პარტიულ" in the PARENT
    # prompt (party-identity refusal rule) is a different, correct usage and is
    # intentionally left untouched.
    assert "პარტიული სათაური" not in _ADULT
    assert "პარტიული სახელით" not in _ADULT
    assert "ნაწილობრივი სათაური" in _ADULT
