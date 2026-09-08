"""A generic word could not reach the panel (2026-09-08).

`match_dynamic_program` refuses the words in `_AMBIGUOUS_TAG_STEMS` — „ბანაკი",
„სკოლა", „ღონისძიება" — because one of them alone cannot identify a programme.
That is right. It is also why the camp is unreachable from the admin panel:
its whole name, „საზაფხულო ბანაკი", is made of exactly those words, so the word
a parent actually types matches nothing:

    match_dynamic_program("ბანაკი მაინტერესებს", [camp])            → None
    match_dynamic_program("საზაფხულო ბანაკი მაინტერესებს", [camp])  → None

Every camp turn therefore fell through to answers written in code, and adding a
second camp („პარიზის ბანაკი", „ზამთრის ბანაკი") would have made „ბანაკი" mean
whichever one the code happened to name.

The narrower question — which ACTIVE programmes answer to the generic word —
is answered from the panel. One candidate is not ambiguous at all and names
that programme as precisely as its full title. Two or more genuinely need the
parent to say which, and until they do the turn belongs to the engine.
"""
import pytest

from app.flows import parent_flow as pf
from app.models.conversation import Conversation
from app.reasoning.dynamic_program_match import (
    match_dynamic_program, programs_answering_to_ambiguous_word,
)

_CAMP = {
    "id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
    "status": "active", "hashtags": ["ბანაკი", "banaki", "camp"],
    "description_short": "საზაფხულო ბანაკი — 7-დღიანი პროგრამა.",
}
_PARIS = {
    "id": "paris_camp", "name": "პარიზის ბანაკი", "type": "kids_program",
    "status": "active", "hashtags": [],
    "description_short": "პარიზის ბანაკი — 10-დღიანი მოგზაურობა.",
}
_SCHOOL = {
    "id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
    "status": "active", "hashtags": [],
    "description_short": "საკვირაო სკოლა — 3-თვიანი პროგრამა.",
}


# ── the gap this closes ────────────────────────────────────────────────────

@pytest.mark.parametrize("msg", [
    "ბანაკი მაინტერესებს",
    "საზაფხულო ბანაკი მაინტერესებს",
    "ბანაკის ფასი რა არის?",
])
def test_the_matcher_still_refuses_a_generic_word(msg):
    """Unchanged, and deliberately so — one generic word cannot identify a
    programme, and letting it would claim every camp at once."""
    assert match_dynamic_program(msg, [dict(_CAMP)]) is None


def test_one_active_programme_answers_to_the_word(ambiguous=None):
    hits = programs_answering_to_ambiguous_word(
        "ბანაკი მაინტერესებს", [dict(_CAMP), dict(_SCHOOL)])
    assert [h["id"] for h in hits] == ["summer_camp"]


def test_two_camps_are_genuinely_ambiguous():
    hits = programs_answering_to_ambiguous_word(
        "ბანაკი მაინტერესებს", [dict(_CAMP), dict(_PARIS)])
    assert {h["id"] for h in hits} == {"summer_camp", "paris_camp"}


def test_naming_one_of_them_ends_the_ambiguity():
    """The matcher wins whenever it can — a specific name is not a guess."""
    assert programs_answering_to_ambiguous_word(
        "პარიზის ბანაკი მაინტერესებს", [dict(_CAMP), dict(_PARIS)]) == []
    assert match_dynamic_program(
        "პარიზის ბანაკი მაინტერესებს",
        [dict(_CAMP), dict(_PARIS)])["program_id"] == "paris_camp"


def test_a_switched_off_programme_is_never_a_candidate():
    hits = programs_answering_to_ambiguous_word(
        "ბანაკი მაინტერესებს", [dict(_CAMP, status="ended"), dict(_PARIS)])
    assert [h["id"] for h in hits] == ["paris_camp"]


def test_the_word_that_matches_nothing_yields_nothing():
    assert programs_answering_to_ambiguous_word(
        "გამარჯობა", [dict(_CAMP), dict(_SCHOOL)]) == []


def test_it_holds_for_any_generic_word_not_just_camp():
    """Nothing here knows „ბანაკი" — „სკოლა" behaves the same way."""
    hits = programs_answering_to_ambiguous_word(
        "სკოლა მაინტერესებს", [dict(_CAMP), dict(_SCHOOL)])
    assert [h["id"] for h in hits] == ["sunday_school"]


# ── what the parent now gets ───────────────────────────────────────────────

def _ask(monkeypatch, sections, msg):
    monkeypatch.setattr("app.services.admin_config_service.get_active_sections",
                        lambda: [dict(s) for s in sections])
    conv = Conversation(sender_id="s", platform="messenger", segment="PARENT")
    return pf._maybe_handle_program_overview(conv, msg)


def test_the_camps_own_panel_text_answers_a_bare_camp_question(monkeypatch):
    """The point of the change: the answer comes from the panel, not code."""
    assert _ask(monkeypatch, [_CAMP, _SCHOOL],
                "ბანაკი მაინტერესებს") == _CAMP["description_short"]


def test_two_camps_defer_rather_than_guess(monkeypatch):
    """With a second camp added, „ბანაკი" must not pick one silently."""
    assert _ask(monkeypatch, [_CAMP, _PARIS], "ბანაკი მაინტერესებს") is None


def test_naming_the_camp_answers_that_camp(monkeypatch):
    assert _ask(monkeypatch, [_CAMP, _PARIS],
                "პარიზის ბანაკი მაინტერესებს") == _PARIS["description_short"]


def test_camp_switched_off_changes_nothing(monkeypatch):
    """Today's live configuration. The camp is not active, so it is not a
    candidate and the camp-status gate below still owns the turn."""
    assert _ask(monkeypatch, [dict(_CAMP, status="ended"), _SCHOOL],
                "ბანაკი მაინტერესებს") is None
