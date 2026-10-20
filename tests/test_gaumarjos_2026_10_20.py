"""„გაუმარჯოს" went out the way „გაგიმარჯოს" did (2026-10-20).

The operator's rule of 2026-10-15 — „გაგიმარჯოს" is never sent — was written
for that one form. The same toast in the third person passed untouched:

* live 2026-10-20, client Page: a parent's thank-you, spelt with a typo so the
  fixed thank-you answer did not fire, got the model's farewell
  „…ნებისმიერ დროს მომწერეთ. გაუმარჯოს!";
* live 2026-09-20: a parent said the family had registered and the reply
  opened „გაუმარჯოს! 🎉".

As an exclamation it goes, like „გაგიმარჯოს". Followed by what it hails
(„გაუმარჯოს ქართულ ენას") it is a sentence and stays.

The texts here are synthetic. The conversation test runs through
``conversation_service.process_message`` with the production flags; only the
LLM's HTTP transport is scripted.
"""
from __future__ import annotations

import pytest

from app.agent.llm import parent_llm_engine as ple
from tests.test_programme_attribution_and_booking_2026_10_05 import (  # noqa: F401 — fixtures
    _SS_OFFER,
    _no_network,
    world,
)


def test_it_does_not_close_a_reply():
    out = ple._drop_reply_to_greeting(
        "გმადლობთ თქვენ! 🩵\n\nთუ კიდევ გაგიჩნდებათ კითხვა — ნებისმიერ დროს მომწერეთ. გაუმარჯოს!")
    assert out == "გმადლობთ თქვენ! 🩵\n\nთუ კიდევ გაგიჩნდებათ კითხვა — ნებისმიერ დროს მომწერეთ."


def test_it_does_not_open_a_reply():
    out = ple._drop_reply_to_greeting(
        "გაუმარჯოს! 🎉\n\nგილოცავთ! თუ კითხვა გაგიჩნდებათ, მომწერეთ.")
    assert out == "გილოცავთ! თუ კითხვა გაგიჩნდებათ, მომწერეთ."


def test_greeted_first_the_parent_is_greeted_back_with_gamarjoba():
    out = ple._drop_reply_to_greeting(
        "გაუმარჯოს! 💙 საკვირაო სკოლა შაბათობითაა.", user_message="გამარჯობა")
    assert out == "გამარჯობა! 💙 საკვირაო სკოლა შაბათობითაა."


@pytest.mark.parametrize("word", ["გაუმარჯოს", "გაუმარჯოთ"])
def test_a_reply_of_that_word_alone_becomes_gamarjoba(word):
    assert ple._drop_reply_to_greeting(f"{word}! 👋") == "გამარჯობა! 👋"


@pytest.mark.parametrize("text", [
    "გაუმარჯოს ქართულ ენას! 💙",
    "ჩვენი შეხვედრები ასე მთავრდება: გაუმარჯოს ქართულ სიტყვას!",
])
def test_a_toast_that_names_what_it_hails_stays(text):
    assert ple._drop_reply_to_greeting(text) == text


def test_the_model_s_farewell_reaches_the_parent_without_it(world):
    world.panel("SS")
    world.say("ფასი რა არის?", ("say", _SS_OFFER))
    reply = world.say("ონლაინაც შეიძლება?",
                      ("say", "კი, ონლაინაც შეიძლება. ნებისმიერ დროს მომწერეთ. გაუმარჯოს!"))
    assert "ნებისმიერ დროს მომწერეთ" in reply, reply
    assert "გაუმარჯო" not in reply, reply
