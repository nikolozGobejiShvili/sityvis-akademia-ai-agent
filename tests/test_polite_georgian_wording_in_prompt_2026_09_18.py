"""Live-prompt wording regression — polite Georgian forms (2026-09-18).

Live evidence, client Page `1716573211895723`, 2026-09-17 21:20–21:33 (Sunday
School turns, no-role tester):

  21:29:54  „გილოცავთ კითხვა! 🙂 …"          (congratulating a question)
  21:21:26  „… მეტი ინფორმაცია გიამბობ!"      (singular, not the polite plural)
  21:33:02  „… გინდათ ჩავაწეროთ? 🙂"          (the prompt's own CTA wording)

None of these strings exist in `app/` — the model wrote them. The third one it
did NOT invent: the live prompt itself offered „თუ გინდათ, მენეჯერთან მოკლე
კონსულტაციაზე ჩაგწერთ." as an approved CTA example (and „რა გინდათ ბანაკიდან"
as a discovery example), while the ADULT engine rewrites „გინდათ" -> „გსურთ".
The model copied the example it was shown.

So this is fixed the way `system_parent_v2.md` already fixes wording — by
TEACHING the correct form next to the wrong one in the „გრამატიკა" section (the
same shape as the existing „გესმის / გვესმის" and „ჩავჯდეთ კონსულტაციაზე"
pairs) and by correcting the prompt's OWN examples — NOT by adding another
forbidden-phrase rewrite to the sanitiser.

Asserted against the prompt text the live engine actually loads.
"""
from __future__ import annotations

from app.agent.llm.prompt_loader import load_prompt

PROMPT = load_prompt("system_parent_v2")
LINES = PROMPT.splitlines()

CONGRATULATE = "გილოცავთ"       # გილოცავთ
GOOD_QUESTION = "კარგი კითხვაა"  # კარგი კითხვაა
TELL_POLITE = "გიამბობთ"        # გიამბობთ
WANT_FAMILIAR = "გინდათ"                  # გინდათ
WANT_POLITE = "გსურთ"                          # გსურთ


def test_prompt_teaches_that_congratulation_is_not_a_reaction_to_a_question():
    """The congratulation verb is never how a question is acknowledged."""
    teaching = [ln for ln in LINES if CONGRATULATE in ln]
    assert teaching, (
        "system_parent_v2.md must teach that the congratulation verb is not "
        "how a question is acknowledged — live 2026-09-17 21:29 the model "
        "opened a reply with it."
    )
    assert any(GOOD_QUESTION in ln for ln in teaching), (
        "the teaching must also SHOW the correct form (a direct answer or the "
        "approved acknowledgement), not only name the wrong one."
    )


def test_prompt_teaches_the_polite_verb_ending():
    """Polite plural verb endings, not the familiar singular."""
    assert any(TELL_POLITE in ln for ln in LINES), (
        "system_parent_v2.md must teach the polite verb ending — live "
        "2026-09-17 21:21 the model used the familiar singular form."
    )


def test_prompt_never_offers_the_familiar_want_verb_as_its_own_example():
    """Every familiar 'want' left in the prompt must sit beside the polite one.

    An approved CTA/discovery example written with the familiar verb is the
    wording the model copies into live replies, so the examples themselves must
    use the polite form.
    """
    offenders = [
        ln.strip() for ln in LINES
        if WANT_FAMILIAR in ln and WANT_POLITE not in ln
    ]
    assert not offenders, (
        "these prompt lines use the familiar 'want' verb without teaching the "
        "polite one beside it, so the model reuses them verbatim: "
        + " | ".join(offenders)
    )
