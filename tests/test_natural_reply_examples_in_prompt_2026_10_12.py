"""The live prompt teaches natural replies by example (2026-10-12).

Live, client Page, 2026-10-09 → 10-12, the model's own sentences included:
„გთხოვთ, ჰკითხეთ!", „გაგება მინდა — …", „გული გამიგია თქვენი სიტყვებით.",
„მენეჯერი უკვე შეტყობინებული აქვს …", „გასაოცარია!" (to „I have a second
child too") and „კარგი კითხვაა, <name>!" four replies in a row. None of these
strings exists in `app/`. The operator's rule: teach by example, not by
banning phrases — so the prompt shows short, polite, fact-free replies for
those moments, and the prompt's own „კარგი კითხვაა" suggestion stops inviting
it as every reply's opener.
"""
from __future__ import annotations

import re

from app.agent.llm.prompt_loader import load_prompt

PROMPT = load_prompt("system_parent_v2")
HEADER = "ასე ჟღერს ბუნებრივი პასუხი"


def _examples() -> list[str]:
    lines = PROMPT.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(HEADER))
    block = []
    for ln in lines[start + 1:]:
        if not ln.startswith("- "):
            break
        block.append(ln)
    return block


def test_the_prompt_shows_natural_replies_for_the_live_moments():
    examples = _examples()
    assert len(examples) >= 6
    assert all("→" in ln for ln in examples)


def test_the_examples_carry_no_facts_to_copy():
    """A digit in an example is a price, an age or a date the model would repeat
    for the wrong programme; facts come from the tools („…")."""
    assert not [ln for ln in _examples() if re.search(r"\d", ln)]


def test_good_question_is_not_offered_as_every_replys_opener():
    line = next(ln for ln in PROMPT.splitlines() if "გილოცავთ" in ln)
    assert "კარგი კითხვაა" in line and "ზედიზედ" in line
