"""Live regression, client Page 2026-09-19 15:13 and 15:16 — two defects in
one conversation, both visible in the operator's screenshots.

1. A refusal read as a name correction.

    parent : არა . მადლიბა . ამომწურავად მიპასუხეთ ყველაფერზე
    agent  : გასაგებია, ყველაფერზე.

   Railway: „[parent_flow] name correction → 'ყველაფერზე'", reply_len=22,
   took_ms=211 — deterministic, no model involved. The agent took the parent's
   last word as her NAME and answered with the correction template
   `f"გასაგებია, {new_name}."`.

   `_has_name_correction_signal` fires on ANY message that starts with „არა"
   and has two or more tokens. The parent wrote „არა" because the previous reply
   had ended „გაქვთ სხვა შეკითხვა?" — a refusal, not a correction.

   The phone branch of the same handler has an anchor: it only fires when the
   message actually CONTAINS a phone number. The name branch has none. That
   asymmetry is the defect.

   Measured before the fix:
       არა . მადლიბა . ამომწურავად მიპასუხეთ ყველაფერზე -> name „ყველაფერზე"
       არა მადლობა ყველაფერზე ამომწურავად მიპასუხეთ     -> name „მიპასუხეთ"
       არა კიდევ მაქვს შეკითხვა                         -> name „შეკითხვა"

   The third is the dangerous one: a parent who says she still HAS a question is
   answered „გასაგებია, შეკითხვა." and her question is dropped.

   The fix reuses the cap that already governs `_parse_name_phone` (a real name
   is a few tokens; a longer run is a sentence that happened to start with
   „არა"), plus the explicit name anchors. „არა, მარიამი" and „არა, მარიამი ვარ"
   still correct the name — that contract is pinned by
   test_objection_and_corrections_2026_06_22 and must not move.

2. Georgian that does not exist.

    agent  : …უფასო კონსულტაცია დაჯავშნოთ — გადაგიხდიან ზარს და ყველა
             შეკითხვას ადგილზე გიპასუხებენ.

   „გადაგიხდიან ზარს" is not Georgian; the verb is „დაგირეკავენ". The phrase is
   nowhere in the repo — the model built it — and the grammar section is where
   the prompt already teaches this class of thing by example.
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as engine
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead

# The parent's own words, 15:13.
REFUSALS = (
    "არა . მადლიბა . ამომწურავად მიპასუხეთ ყველაფერზე",
    "არა მადლობა ყველაფერზე ამომწურავად მიპასუხეთ",
    "არა კიდევ მაქვს შეკითხვა",
    "არა, ჯერ არ გადამიწყვეტია, დაველოდები",
    "არა არ მჭირდება კონსულტაცია ამ ეტაპზე",
)

# Real corrections — these must keep working.
CORRECTIONS = (
    ("არა, მარიამი", "მარიამი"),
    ("არა, მარიამი ვარ", "მარიამი"),
    ("ნინო კი არა, მარიამი ვარ", "მარიამი"),
    ("სახელი შევცდი, მარიამი", "მარიამი"),
    ("არა, ჩემი სახელია მარიამი", "მარიამი"),
)


def _conv(name: str = "ნინო") -> Conversation:
    conv = Conversation(sender_id="corr", platform="messenger")
    conv.segment = "PARENT"
    lead = Lead(sender_id="corr", platform="messenger", segment="PARENT")
    lead.name = name
    conv.lead = lead
    return conv


@pytest.mark.parametrize("message", REFUSALS)
def test_a_refusal_is_not_a_name_correction(message):
    assert parent_flow._has_name_correction_signal(message) is False, (
        "a sentence that begins with a refusal is not a name correction"
    )


@pytest.mark.parametrize("message", REFUSALS)
def test_a_refusal_never_reaches_the_correction_template(message):
    conv = _conv()
    assert parent_flow._maybe_handle_contact_correction(conv, message) is None
    assert conv.lead.name == "ნინო", "the refusal overwrote the stored name"


@pytest.mark.parametrize("message, expected", CORRECTIONS)
def test_a_real_name_correction_still_works(message, expected):
    conv = _conv()
    out = parent_flow._maybe_handle_contact_correction(conv, message)
    assert out is not None, "a genuine correction stopped working"
    assert conv.lead.name == expected


def test_the_question_survives_the_refusal():
    """The live risk in one assertion: a parent who says she still has a
    question must not be answered with a name acknowledgement."""
    conv = _conv()
    out = parent_flow._maybe_handle_contact_correction(
        conv, "არა კიდევ მაქვს შეკითხვა")
    assert out is None


def test_the_prompt_teaches_the_verb_for_a_manager_call():
    """Live 15:16 — „გადაგიხდიან ზარს". Taught by example in the grammar
    section, the way the polite forms already are; no sanitiser entry."""
    prompt = engine._build_system_prompt(message="x", segment="PARENT")
    assert "დაგირეკავენ" in prompt
    assert "ზარს გადაგიხდიან" in prompt or "გადაგიხდიან ზარს" in prompt
