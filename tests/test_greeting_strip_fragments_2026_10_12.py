"""A removed greeting must not leave its fragments behind (2026-10-12).

Live, client Page, 2026-10-09 → 10-12: of 13 replies whose mid-conversation
greeting the engine stripped, 8 went out opening with what was left of it —
the parent's name alone („<name>! 👋", 5 times), a lone „🎉", and, after a
parent's thank-you, „გაგიმარჯოს 💙". The strip removed the greeting WORD only;
the model had written „გამარჯობა, <name>! 👋 …".

Two parents had greeted first („გამარჯობა" / „მოგესალმებით") and lost the
greeting back — then a greeting is the polite answer, not a scripted reset.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

import app.config as config_module
from app.agent.llm import parent_llm_engine as eng
from app.flows import parent_flow
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import messenger_service, openai_service


def _conv(name: str = "") -> Conversation:
    conv = Conversation(sender_id="greet-u", platform="messenger")
    conv.history.append({"role": "assistant", "content": "prior"})
    conv.lead = Lead(sender_id="greet-u", platform="messenger", segment="PARENT",
                     child_age="10", name=name)
    return conv


def test_the_parents_name_goes_with_the_greeting():
    out = eng._strip_mid_conversation_greeting(
        "გამარჯობა, ფატი! 👋\n\nრა თქმა უნდა — პირობებს მოგწერთ.",
        _conv("ფატი"), user_message="საკვირაო სკოლის პირობები მომწერეთ",
    )
    assert out == "რა თქმა უნდა — პირობებს მოგწერთ."


def test_the_vocative_form_of_the_name_goes_too():
    out = eng._strip_mid_conversation_greeting(
        "გამარჯობა, მარიამ!\nფასი 595 ლარია.", _conv("მარიამი"),
        user_message="რა ღირს?",
    )
    assert out == "ფასი 595 ლარია."


def test_the_emoji_on_the_greetings_line_goes_too():
    out = eng._strip_mid_conversation_greeting(
        "გამარჯობა 🎉\n\nშესანიშნავია, რომ დარეგისტრირდით!", _conv(),
        user_message="გავიარე რეგისტრაცია",
    )
    assert out == "შესანიშნავია, რომ დარეგისტრირდით!"


def test_a_greeting_reply_after_the_greeting_goes_too():
    out = eng._strip_mid_conversation_greeting(
        "გამარჯობა! გაგიმარჯოს 💙\n\nმადლობა თქვენ ინტერესისთვის.", _conv(),
        user_message="გმადლობთ ინფორმაციისთვის",
    )
    assert out == "მადლობა თქვენ ინტერესისთვის."


@pytest.mark.parametrize("greeting", ["გამარჯობა", "მოგესალმებით", "სალამი"])
def test_when_the_parent_greets_the_greeting_back_stays(greeting):
    text = "გამარჯობა, ფატი! 👋 რით შემიძლია დაგეხმაროთ?"
    assert eng._strip_mid_conversation_greeting(
        text, _conv("ფატი"), user_message=greeting,
    ) == text


def test_another_word_after_the_greeting_is_kept():
    """Only the lead's own name is the greeting's address."""
    out = eng._strip_mid_conversation_greeting(
        "გამარჯობა! შესანიშნავი კითხვაა.", _conv("ფატი"), user_message="ბარგი?",
    )
    assert out == "შესანიშნავი კითხვაა."


def test_a_content_emoji_on_a_later_line_is_kept():
    out = eng._strip_mid_conversation_greeting(
        "გამარჯობა!\n📍 Le Méridien Batumi", _conv(), user_message="სად?",
    )
    assert out == "📍 Le Méridien Batumi"


def test_a_reply_that_is_only_a_greeting_is_left_as_is():
    text = "გამარჯობა, ფატი! 👋"
    assert eng._strip_mid_conversation_greeting(
        text, _conv("ფატი"), user_message="ok",
    ) == text


# ── through the real engine (model mocked) ────────────────────────────────────

@pytest.fixture
def engine_on(monkeypatch):
    from app.services import conversation_service
    conversation_service.conversations.clear()
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})
    yield
    conversation_service.conversations.clear()


def _reply(content):
    msg = SimpleNamespace(content=content, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_the_engine_reply_opens_with_its_content(engine_on, monkeypatch):
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kw: _reply("გამარჯობა, ფატი! 👋\n\nბანაკი 13–17 წლის მოზარდებისთვისაა."),
    )
    out = parent_flow.handle(_conv("ფატი"), "ბანაკზე მეტი მინდა ვიცოდე")
    assert out.lstrip().startswith("ბანაკი")
