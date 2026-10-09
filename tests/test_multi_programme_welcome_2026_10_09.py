"""The opener with two or more programmes on sale is the operator's sentence
(2026-10-09): „მოგესალმებით🩵 რომელი პროგრამით ხართ დაინტერესებული?", without
a list. One programme on sale keeps its plain question.

The greeting heart policy must leave that sentence as it is: it opens with a
greeting word, and before this the policy replaced the word with „გამარჯობა 💙"
— „გამარჯობა 💙 🩵 რომელი…".
"""
from __future__ import annotations

import dataclasses

import app.config as config_module
from app.flows import parent_flow
from app.models.conversation import Conversation

_SENTENCE = "მოგესალმებით🩵 რომელი პროგრამით ხართ დაინტერესებული?"
_TWO = [{"name": "საკვირაო სკოლა", "status": "active"},
        {"name": "პარიზის ბანაკი", "status": "active"}]


def _fresh() -> Conversation:
    c = Conversation(sender_id="w", platform="messenger", segment="PARENT")
    c.state = "START"
    return c


def _on(monkeypatch, sections):
    import app.services.admin_config_service as acs
    monkeypatch.setattr(parent_flow, "settings",
                        dataclasses.replace(config_module.settings, USE_DYNAMIC_WELCOME=True))
    monkeypatch.setattr(acs, "get_active_sections", lambda: [dict(s) for s in sections])


def test_two_programmes_open_with_the_operator_sentence(monkeypatch):
    _on(monkeypatch, _TWO)
    assert parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა") == _SENTENCE


def test_one_programme_keeps_its_plain_question(monkeypatch):
    _on(monkeypatch, _TWO[:1])
    out = parent_flow._maybe_static_welcome(_fresh(), "გამარჯობა")
    assert out == "გამარჯობა.\n\nრით შემიძლია დაგეხმაროთ?"


def test_a_greeting_does_not_rewrite_the_sentence(monkeypatch):
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True)
    conv = _fresh()
    for policy in (parent_flow._apply_client_emoji_policy,
                   parent_flow.apply_greeting_farewell_heart):
        out = policy(conv, "გამარჯობა", _SENTENCE)
        assert out == _SENTENCE
        assert "💙" not in out


def test_the_plain_greeting_still_gets_its_heart(monkeypatch):
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True)
    out = parent_flow._apply_client_emoji_policy(
        _fresh(), "გამარჯობა", "გამარჯობა.\n\nრით შემიძლია დაგეხმაროთ?")
    assert out == "გამარჯობა 💙\n\nრით შემიძლია დაგეხმაროთ?"


def test_the_sent_opener_is_recognised_as_the_menu(monkeypatch):
    from app.services import conversation_service as cs
    _on(monkeypatch, _TWO)
    monkeypatch.setattr(cs, "settings",
                        dataclasses.replace(config_module.settings, USE_DYNAMIC_WELCOME=True))
    conv = _fresh()
    conv.history = [{"role": "user", "content": "გამარჯობა"},
                    {"role": "assistant", "content": _SENTENCE}]
    assert cs._menu_was_the_last_reply(conv) is True
