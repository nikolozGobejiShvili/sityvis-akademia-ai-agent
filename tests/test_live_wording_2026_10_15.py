"""Three things the client Page showed on 2026-10-13 → 10-15.

* „გაგიმარჯოს" closed a reply to a thank-you. The operator: it is never used.
  It was stripped only as an opener, so it was free to close a reply.
* Camp ended, a parent deep in a Paris chat said the family would plan it for
  the summer holidays („საზაფხულო არდადეგები") and got the closed camp's status
  — the season word counted as the camp's name.
* After the agent asked for a contact, a number sent together with a question
  written without a „?" got „ნომერი მივიღე…" and the question was dropped.

The texts here are synthetic. The conversation tests run through
``conversation_service.process_message`` with the production flags; only the
LLM's HTTP transport is scripted.
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as ple
from app.flows import parent_flow
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _ASK_CONTACT,
    _PHONE,
    _SS_OFFER,
    _no_network,
    world,
)


# ═══ „გაგიმარჯოს" is never sent ═══════════════════════════════════════════

def test_it_does_not_close_a_reply():
    out = ple._drop_reply_to_greeting(
        "არაფრის. ნებისმიერ დროს დამიკავშირდით. გაგიმარჯოს! 👋")
    assert out == "არაფრის. ნებისმიერ დროს დამიკავშირდით."


def test_it_does_not_open_a_reply():
    out = ple._drop_reply_to_greeting("გაგიმარჯოს! 💙\n\nსაკვირაო სკოლა შაბათობითაა.")
    assert out == "საკვირაო სკოლა შაბათობითაა."


def test_greeted_first_the_parent_is_greeted_back_with_gamarjoba():
    out = ple._drop_reply_to_greeting(
        "გაგიმარჯოს! 💙 საკვირაო სკოლა შაბათობითაა.", user_message="გამარჯობა")
    assert out == "გამარჯობა! 💙 საკვირაო სკოლა შაბათობითაა."


@pytest.mark.parametrize("word", ["გაგიმარჯოს", "გაგიმარჯოთ"])
def test_a_reply_of_that_word_alone_becomes_gamarjoba(word):
    assert ple._drop_reply_to_greeting(f"{word}! 👋") == "გამარჯობა! 👋"


def test_a_reply_without_it_is_untouched():
    text = "გამარჯობა! 💙\n\nსაკვირაო სკოლის დეტალებს გეტყვით.\n\n📍 ონლაინ"
    assert ple._drop_reply_to_greeting(text, user_message="გამარჯობა") == text


def test_the_model_s_farewell_reaches_the_parent_without_it(world):
    world.panel("SS")
    world.say("ფასი რა არის?", ("say", _SS_OFFER))
    reply = world.say("ონლაინაც შეიძლება?",
                      ("say", "კი, ონლაინაც შეიძლება. ნებისმიერ დროს მომწერეთ. გაგიმარჯოს! 👋"))
    assert "ნებისმიერ დროს მომწერეთ" in reply, reply
    assert "გაგიმარჯო" not in reply, reply


# ═══ the summer holidays are not the summer camp ══════════════════════════

_PARIS_REPLY = "პარიზის ბანაკი საგანმანათლებლო პროგრამაა. რამდენი წლისაა ბავშვი?"
_HOLIDAYS = "ჯერ ვფიქრობთ, საზაფხულო არდადეგებისთვის დავგეგმავთ ალბათ"


def _paris_chat(world):
    world.panel("SS_PARIS")
    world.say("პარიზის ბანაკი მაინტერესებს", ("say", _PARIS_REPLY))


def test_summer_holidays_in_a_paris_chat_are_answered_by_the_model(world):
    _paris_chat(world)
    reply = world.say(_HOLIDAYS, ("say", "გასაგებია, პარიზის ბანაკზე დაგეხმარებით."))
    assert "უკვე გაიმართა" not in reply, reply
    assert "პარიზის ბანაკზე დაგეხმარებით" in reply, reply


def test_the_summer_camp_named_in_a_paris_chat_still_gets_its_status(world):
    _paris_chat(world)
    reply = world.say("საზაფხულო ბანაკი როდის იქნება?")
    assert "უკვე გაიმართა" in reply, reply


# ═══ a number with a question: the number is kept, the model answers ══════

_NUMBER_AND_QUESTION = (
    f"{_PHONE} ბავშვი უცხოეთში ცხოვრობს და ონლაინ ჩართვა თუ შეიძლება ეგეც მითხარით"
)


def _contact_asked(world):
    world.panel("SS")
    world.say("ფასი რა არის?", ("say", _SS_OFFER))
    world.say("10 წლისაა", ("say", "მადლობა. " + _ASK_CONTACT))


def test_a_number_sent_with_a_question_is_kept_and_the_question_answered(world):
    _contact_asked(world)
    reply = world.say(_NUMBER_AND_QUESTION,
                      ("say", "ონლაინ ჩართვაზე მენეჯერი დაგიზუსტებთ."))
    assert world.lead.phone == _PHONE
    assert (world.lead.name or "") == "", world.lead.name
    assert reply != parent_flow._CONTACT_GOT_NUMBER_ASK_NAME, reply
    assert "ონლაინ ჩართვაზე" in reply, reply


def test_a_name_and_number_alone_still_get_the_quick_reply(world):
    _contact_asked(world)
    reply = world.say(f"ნინო {_PHONE}")
    assert world.lead.phone == _PHONE and world.lead.name == "ნინო"
    assert reply == parent_flow._CONTACT_THANKS_NAME_ASK_TIME.format(name="ნინო"), reply


def test_a_number_alone_still_gets_the_quick_reply(world):
    _contact_asked(world)
    assert world.say(_PHONE) == parent_flow._CONTACT_GOT_NUMBER_ASK_NAME


def test_a_short_introduction_with_the_number_is_still_a_contact():
    assert not parent_flow._says_more_than_the_contact(f"ჩემი ნომერია {_PHONE}, სახელი ნინო")
    assert parent_flow._says_more_than_the_contact(_NUMBER_AND_QUESTION)
