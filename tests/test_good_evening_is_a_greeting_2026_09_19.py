"""Live regression, client Page 2026-09-19 19:29 and 19:33 — screenshots 36/37.

    19:29  parent : საღამომშვიდობის
           agent  : ამ სახელით ღონისძიება ვერ მოვძებნე.
                    ამ ეტაპზე აქტიური ღონისძიება სიაში არ მაქვს.

    19:33  parent : რადგან მეგობართან ერთად უნდა იაროს და შევათანხმებთ
           agent  : …თუ მეგობარიც ჩაერთვება, დედმამიშვილებზე და ახლობლებზე
                    10%-იანი ფასდაკლება მოქმედებს თითოეულ ბავშვზე.

1. „საღამო მშვიდობისა" is GOOD EVENING. Parents type it as one word as often as
   two. „საღამო" is an ADULT_KEYWORDS stem (a cultural evening really is a
   „საღამო"), so the greeting classified ADULT and the adult flow answered a
   hello with „no event by that name".

   The stem is not the problem this time — a soirée is a „საღამო". The greeting
   is: `GREETING_ONLY_KEYWORDS` is an exact list that never learned the Georgian
   time-of-day greetings. Every one of them carries „მშვიდობის" — „დილა
   მშვიდობისა", „საღამო მშვიდობისა", „ღამე მშვიდობისა" — and no event does.

   It also cost the whole conversation: the segment stuck on ADULT, so the next
   message („12 წლის ბიჭი მინდა მოვიყვანო თქვენს აკადემიაში") had to be handed
   across flows and came back „თქვენი შეკითხვა გადავამისამართე სწორ
   მიმართულებაზე!… გთხოვთ, მომდევნო შეტყობინებაში დამატებითი დეტალები
   გაგვიზიაროთ" — an apology for routing instead of an answer.

2. A friend is not a sibling. The discount belongs to the categories the
   programme's own panel data lists — for Sunday School, siblings and members of
   socially vulnerable families. The model turned that into „დედმამიშვილებზე და
   ახლობლებზე" and offered it because a FRIEND was coming: a false commercial
   promise to a customer.

   `_strip_unwarranted_sibling_discount` did not catch it — it matches four
   exact phrases, all in the „-ისთვის" form, and the model wrote „-ზე". An exact
   phrase list cannot keep up with a language model, so the fix is in the prompt
   rule the model reads, which was written for the camp („ეწერება ბანაკში") and
   said nothing at all about the programme actually on sale.
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as engine
from app.services import conversation_service as cs

# Georgian time-of-day greetings, as parents actually type them.
GREETINGS = (
    "საღამომშვიდობის",
    "საღამო მშვიდობისა",
    "საღამო მშვიდობის",
    "დილა მშვიდობისა",
    "ღამე მშვიდობისა",
    "დილამშვიდობისა",
)

# A cultural evening still announces itself.
REAL_ADULT = (
    "საღამოს ღონისძიება მაინტერესებს",
    "პოეზიის საღამო როდის არის",
    "კულტურული საღამო გაქვთ?",
)


@pytest.mark.parametrize("message", GREETINGS)
def test_good_evening_is_a_greeting(message):
    assert cs._is_pure_greeting(message) is True, (
        "a time-of-day greeting is a greeting, not an event search"
    )


@pytest.mark.parametrize("message", GREETINGS)
def test_a_greeting_never_classifies_as_an_event(message):
    assert cs._classify_segment(message) == "UNCLEAR", (
        "the greeting was answered with „no event by that name"
    )


@pytest.mark.parametrize("message", REAL_ADULT)
def test_a_cultural_evening_still_classifies_as_adult(message):
    assert cs._is_pure_greeting(message) is False
    assert cs._classify_segment(message) == "ADULT"


@pytest.mark.parametrize("message", ("გამარჯობა", "სალამი", "მოგესალმებით", "hello"))
def test_the_existing_greetings_are_untouched(message):
    assert cs._is_pure_greeting(message) is True
    assert cs._classify_segment(message) == "UNCLEAR"


def test_a_greeting_with_content_is_not_a_bare_greeting():
    """„საღამო მშვიდობისა, ბანაკი მაინტერესებს" carries a real question — the
    bare-greeting contract must not swallow it."""
    message = "საღამო მშვიდობისა, ბანაკი მაინტერესებს"
    assert cs._is_pure_greeting(message) is False
    # Camp AND adult stems both match here („ბანაკი" + „საღამო"), so the
    # shipped tie-break keeps it UNCLEAR rather than guessing — and the
    # sole-programme rule then routes it from the panel. What must never
    # happen is the adult flow claiming it outright.
    assert cs._classify_segment(message) != "ADULT"


# --------------------------------------------------------------------------
# 2. A friend is not a sibling.
# --------------------------------------------------------------------------

def test_the_discount_rule_is_not_written_for_the_camp_alone():
    """The rule the model reads said „ეწერება ბანაკში" — so on the programme
    that IS on sale it had no rule at all and improvised a category."""
    prompt = engine._build_system_prompt(message="x", segment="PARENT")
    marker = "დედმამიშვილების ფასდაკლება (10%) მოქმედებს"
    assert marker not in prompt, "the discount rule still speaks only for the camp"


def test_the_prompt_says_a_friend_earns_no_discount():
    prompt = engine._build_system_prompt(message="x", segment="PARENT")
    assert "მეგობარი" in prompt
