"""A detail the agent does not know: the operator's sentence, with the number of
that programme's own manager (2026-10-09).

Live 2026-10-09 the agent answered questions the panel does not cover with
„ეს კონკრეტული დეტალი ჩემთვის ხელმისაწვდომ ინფორმაციაში არ არის…" before the
number. The operator's answer for such a detail, on every programme, is one
sentence: „აღნიშნულ საკითხთან დაკავშირებით დეტალური ინფორმაციის მისაღებად
დაგვიკავშირდით ნომერზე: <the programme's number from the panel>".
"""
from __future__ import annotations

from app.agent.llm import parent_llm_engine
from app.flows import parent_flow
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _conversation,
    _no_network,
    _panel_only,
)

_SENTENCE = (
    "აღნიშნულ საკითხთან დაკავშირებით დეტალური ინფორმაციის მისაღებად "
    "დაგვიკავშირდით ნომერზე: "
)
_CAMP_NUMBER = "500 00 00 01"
_SCHOOL_NUMBER = "500 00 00 02"
_PARIS_NUMBER = "500 00 00 03"
_AGE_QUESTION = "რამდენი წლისაა"


def _prompt(panel: str, turns: list[tuple[str, str]], message: str) -> str:
    with _panel_only(panel):
        conv = _conversation(turns)
        conv.segment = "PARENT"
        return parent_llm_engine._build_system_prompt(
            message, "PARENT", conversation=conv, lead=conv.lead)


def test_a_paris_chat_is_taught_the_sentence_with_the_paris_number():
    prompt = _prompt("SS_PARIS", [
        ("user", "პარიზის ბანაკი მაინტერესებს"),
        ("assistant", "პარიზის ბანაკი 6-დღიანი საგანმანათლებლო ბანაკია."),
    ], "ოთახში რამდენი ბავშვი იქნება?")
    assert _SENTENCE + _PARIS_NUMBER in prompt


def test_a_sunday_school_chat_is_taught_the_sentence_with_its_own_number():
    prompt = _prompt("SS_PARIS", [
        ("user", "საკვირაო სკოლა მაინტერესებს"),
        ("assistant", "საკვირაო სკოლის ფასი 595 ლარია."),
    ], "მასწავლებლები ვინ არიან?")
    assert _SENTENCE + _SCHOOL_NUMBER in prompt


def test_the_old_redirect_wording_is_no_longer_taught():
    prompt = _prompt("SS", [("user", "საკვირაო სკოლა მაინტერესებს")], "ჯავშანი რამდენია?")
    assert "ამ დეტალებს მენეჯერი გაგაცნობთ" not in prompt
    assert "რაც შეეხება ჯავშნის საფასურს" not in prompt


def test_the_sentence_is_read_as_the_manager_defer():
    assert parent_flow._is_unknown_detail_manager_defer(_SENTENCE + _PARIS_NUMBER)
    assert parent_flow._is_unknown_detail_manager_defer(
        "ფრენა პირდაპირია.\n\n" + _SENTENCE + _PARIS_NUMBER)
    assert not parent_flow._is_unknown_detail_manager_defer(
        "საკვირაო სკოლის ფასია 595 ლარი.")


def test_no_age_question_is_grafted_onto_the_sentence():
    with _panel_only("CAMP_ONLY"):
        conv = _conversation([("user", "საზაფხულო ბანაკი მაინტერესებს")])
        conv.segment = "PARENT"
        reply = _SENTENCE + _CAMP_NUMBER
        out = parent_flow._ensure_camp_age_question(
            conv, "ოთახში რამდენი ბავშვი იქნება?", reply)
    assert out == reply
    assert _AGE_QUESTION not in out
