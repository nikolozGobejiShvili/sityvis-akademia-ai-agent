"""Manager-number disclosure + mid-conversation greeting fixes (2026-06-21).

Two live-demo bugs from a real PARENT/camp transcript:

  BUG A — a parent who EXPLICITLY asked for the MANAGER's phone number got
  refused ("მენეჯერის ნომერს ვერ გაგწიოთ") and was only re-asked for THEIR
  own number, because the PARENT flow had no disclosure route (only ADULT did).

  BUG B — the agent said "გამარჯობა" (hello) MID-conversation while handling
  the manager request — a scripted greeting that ignores conversation state.

FIX A: a deterministic pre-engine interceptor in parent_flow.handle that
discloses admin_config_service.get_manager_phone() (558 67 47 33) AND offers a
callback, fired ONLY on (manager-word + contact-word + no-own-phone).

FIX B: a conversation-aware sanitiser strip in the engine that removes a
sentence-initial greeting once the conversation already has an assistant turn.

Driven through the REAL parent flow (parent_flow.handle) with the engine ON and
a mocked OpenAI — no real OpenAI / Meta / Calendar / Sheets / network.
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

_MANAGER_NUMBER = "558 67 47 33"


@pytest.fixture(autouse=True)
def _reset():
    from app.services import conversation_service
    conversation_service.conversations.clear()
    parent_flow.invalid_phone_retries.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def engine_on(monkeypatch):
    swapped = dataclasses.replace(config_module.settings, USE_PARENT_LLM_ENGINE=True)
    monkeypatch.setattr(parent_flow, "settings", swapped)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda sid, plat: {})


def _mk_response(content):
    msg = SimpleNamespace(content=content or None, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _parent_conv(child_age="14", phone="", with_history=True):
    conv = Conversation(sender_id="mgr-u", platform="instagram")
    if with_history:
        conv.history.append({"role": "assistant", "content": "_prior_welcome"})
    conv.lead = Lead(
        sender_id="mgr-u", platform="instagram", segment="PARENT",
        child_age=child_age, phone=phone,
    )
    return conv


# ==========================================================================
# FIX A — manager-number detector
# ==========================================================================


@pytest.mark.parametrize("message", [
    "მენეჯერი ნომერი რომ მომწეროთ შეგიძლიათ?",
    "მეთვითონ მინდა მენეჯერთან დაკავშირება მომწერეთ ნომერი თუ შეიზლება",
    "მენეჯერის ტელეფონი მაინტერესებს",
    "მენეჯერის საკონტაქტო ნომერი მომეცით",
])
def test_manager_number_request_detected(message):
    assert parent_flow._is_explicit_manager_number_request(message) is True


@pytest.mark.parametrize("message", [
    "მენეჯერთან დაკავშირება მინდა, ჩემი ნომერია 595999733",  # supplies own phone
    "კი მინდა ჩამწერეთ",                                       # no manager word
    "მენეჯერი დამირეკავს?",                                    # no contact word
    "ბანაკის ფასი რა არის?",                                   # unrelated
])
def test_non_manager_number_requests_ignored(message):
    assert parent_flow._is_explicit_manager_number_request(message) is False


def test_render_manager_answer_no_phone_known_offers_callback():
    """Phone unknown → disclose the number AND offer to take theirs."""
    lead = Lead(sender_id="x", platform="instagram", segment="PARENT")
    answer = parent_flow._render_manager_number_answer(lead)
    assert _MANAGER_NUMBER in answer
    assert "დატოვეთ თქვენი ნომერი" in answer  # offers a callback


def test_render_manager_answer_phone_known_does_not_reask_number():
    """Context-aware (live bug): the parent already gave their number (booked
    consultation) → the disclosure must NOT ask „დატოვეთ თქვენი ნომერი" again."""
    lead = Lead(
        sender_id="x", platform="instagram", segment="PARENT", phone="595999733",
    )
    answer = parent_flow._render_manager_number_answer(lead)
    assert _MANAGER_NUMBER in answer
    assert "დატოვეთ თქვენი ნომერი" not in answer
    assert "თავად დაგიკავშირდებათ" in answer  # manager will reach out


# ==========================================================================
# FIX A — end to end through parent_flow.handle (engine ON)
# ==========================================================================


def test_manager_number_disclosed_engine_not_consulted(engine_on, monkeypatch):
    """The explicit manager-number request is answered deterministically with
    the number + a callback offer; the LLM is never consulted, and there is no
    mid-conversation greeting."""
    def _boom(**kw):
        raise AssertionError("engine must NOT be consulted for a manager-number request")
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)

    conv = _parent_conv()
    out = parent_flow.handle(conv, "მენეჯერი ნომერი რომ მომწეროთ შეგიძლიათ?")
    assert _MANAGER_NUMBER in out
    assert "გამარჯობა" not in out
    # never just re-asks for the parent's number INSTEAD of giving the manager's
    assert _MANAGER_NUMBER in out and "დაგიკავშირდებათ" in out


def test_manager_number_when_phone_known_does_not_reask(engine_on, monkeypatch):
    """Live transcript: the parent already booked (phone known) and then asks
    for the manager's number — the agent must give it WITHOUT re-asking for
    the number it already has."""
    def _boom(**kw):
        raise AssertionError("engine must NOT be consulted for a manager-number request")
    monkeypatch.setattr(openai_service, "chat_with_tools", _boom)

    conv = _parent_conv(child_age="14", phone="595999733")
    out = parent_flow.handle(conv, "მენეჯერის ნომერი რომ მომწეროთ შეგიძლიათ?")
    assert _MANAGER_NUMBER in out
    assert "დატოვეთ თქვენი ნომერი" not in out  # already known → not re-asked
    assert "გამარჯობა" not in out


def test_parent_supplying_own_number_not_intercepted(engine_on, monkeypatch):
    """When the parent gives their OWN number alongside a manager mention, the
    manager-number interceptor must NOT fire (the normal contact/handoff flow
    owns that). We assert the deterministic disclosure text is NOT returned."""
    monkeypatch.setattr(openai_service, "chat_with_tools",
                        lambda **kw: _mk_response("გასაგებია."))
    conv = _parent_conv()
    out = parent_flow.handle(conv, "მენეჯერი მინდა, ჩემი ნომერია 595999733")
    # The fixed disclosure sentence must not appear (the number may legitimately
    # echo elsewhere, so assert on the disclosure-specific phrasing).
    assert "შეგიძლიათ პირდაპირ დაუკავშირდეთ" not in out


# ==========================================================================
# FIX B — greeting strip (component)
# ==========================================================================


def test_greeting_kept_on_first_reply():
    conv = Conversation(sender_id="g", platform="instagram")  # no assistant turn
    text = "გამარჯობა, ბანაკი 7-დღიანია."
    assert eng._strip_mid_conversation_greeting(text, conv) == text


def test_greeting_stripped_mid_conversation():
    conv = Conversation(sender_id="g", platform="instagram")
    conv.history.append({"role": "assistant", "content": "prior"})
    out = eng._strip_mid_conversation_greeting(
        "გამარჯობა, თუ გსურთ მენეჯერთან დაკავშირება, მომწერეთ ნომერი.", conv,
    )
    assert not out.startswith("გამარჯობა")
    assert "მენეჯერთან დაკავშირება" in out  # rest of the reply intact


def test_non_greeting_untouched():
    conv = Conversation(sender_id="g", platform="instagram")
    conv.history.append({"role": "assistant", "content": "prior"})
    text = "ფასი 2150 ლარია."
    assert eng._strip_mid_conversation_greeting(text, conv) == text


def test_mid_sentence_greeting_not_stripped():
    conv = Conversation(sender_id="g", platform="instagram")
    conv.history.append({"role": "assistant", "content": "prior"})
    text = "ვუთხარი გამარჯობა და გავაგრძელე."
    assert eng._strip_mid_conversation_greeting(text, conv) == text


# ==========================================================================
# FIX B — end to end through the engine
# ==========================================================================


def test_engine_strips_mid_conversation_greeting(engine_on, monkeypatch):
    """If the (mocked) model opens a LATER-turn reply with „გამარჯობა", the
    final outgoing text must not start with it.

    NB (Client follow-up hotfix 2026-06-29): the trigger message is a substantive
    continuation („ბანაკზე მეტი მინდა ვიცოდე"), NOT a thanks/close — a pure
    thanks/close („კარგი, გასაგებია მადლობა") now warm-closes deterministically
    and never reaches the engine (client requirement: closes must not continue
    the funnel). This test targets the greeting-strip, so a continuation message
    exercises exactly that path."""
    monkeypatch.setattr(
        openai_service, "chat_with_tools",
        lambda **kw: _mk_response("გამარჯობა, ბანაკი მართლაც მშვენიერი გამოცდილებაა."),
    )
    conv = _parent_conv(child_age="14", phone="595999733")
    out = parent_flow.handle(conv, "ბანაკზე მეტი მინდა ვიცოდე")
    assert not out.strip().startswith("გამარჯობა")
    assert "ბანაკი" in out  # the substantive reply survived


# ==========================================================================
# #2 — anti-repeat: a repeated contact-ask varies its wording (no flow change)
# ==========================================================================


def _intent_conv(history=None):
    conv = Conversation(sender_id="rep-u", platform="instagram")
    conv.lead = Lead(
        sender_id="rep-u", platform="instagram", segment="PARENT", child_age="14",
    )
    for h in (history or []):
        conv.history.append(h)
    return conv


def test_first_contact_ask_uses_original_wording():
    conv = _intent_conv()
    out = parent_flow._maybe_request_full_contact_on_intent(conv, "კი მინდა ჩამწერეთ")
    assert out == parent_flow._CONTACT_REQUEST_NAME_AND_PHONE


def test_repeated_contact_ask_is_varied_not_identical():
    first = parent_flow._CONTACT_REQUEST_NAME_AND_PHONE
    conv = _intent_conv(history=[{"role": "assistant", "content": first}])
    out = parent_flow._maybe_request_full_contact_on_intent(conv, "კი მინდა")
    assert out is not None
    assert out != first                       # not a robotic byte-identical repeat
    assert "ნომერ" in out                     # still asks for the contact
    assert out == parent_flow._CONTACT_REQUEST_NAME_AND_PHONE_RETRY


def test_contact_ask_marker_detection():
    ask = parent_flow._CONTACT_REQUEST_PHONE_ONLY
    assert parent_flow._bot_last_reply_asked_for_contact(
        _intent_conv(history=[{"role": "assistant", "content": ask}]),
    ) is True
    assert parent_flow._bot_last_reply_asked_for_contact(
        _intent_conv(history=[{"role": "assistant", "content": "ფასი 2150 ლარია."}]),
    ) is False
