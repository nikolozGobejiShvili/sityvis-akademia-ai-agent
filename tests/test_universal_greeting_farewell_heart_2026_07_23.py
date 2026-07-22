"""Universal greeting / farewell blue-heart 💙 — Step 2 (2026-07-23).

``parent_flow.apply_greeting_farewell_heart`` adds EXACTLY ONE 💙 on the opening
greeting (first reply) and on the farewell / thank-you close, for the flows that
lack PARENT's own emoji policy (the ADULT engine + the UNCLEAR routing menu).
``conversation_service`` applies it to every non-PARENT route. It reuses the same
``_CLIENT_EMOJI_ENABLED`` flag as PARENT (pinned OFF in conftest → existing tests
byte-identical); PARENT keeps its own richer policy and is excluded here.
"""
from __future__ import annotations

import pytest

from app.flows import adult_flow, parent_flow
from app.models.conversation import Conversation
from app.services import conversation_service, messenger_service

_HEART = "💙"


@pytest.fixture(autouse=True)
def _reset():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture
def emoji_on(monkeypatch):
    """Opt back in to the client heart policy (conftest pins it OFF)."""
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", True, raising=False)
    monkeypatch.setattr(messenger_service, "get_user_profile", lambda s, p: {})
    return monkeypatch


def _conv(history=None):
    c = Conversation(sender_id="x", platform="instagram", segment="ADULT")
    for t in history or []:
        c.history.append(t)
    return c


# ── unit: apply_greeting_farewell_heart ──────────────────────────────────────

def test_flag_off_is_noop(monkeypatch):
    monkeypatch.setattr(parent_flow, "_CLIENT_EMOJI_ENABLED", False, raising=False)
    out = parent_flow.apply_greeting_farewell_heart(
        _conv(), "გამარჯობა", "მოგესალმებით")
    assert _HEART not in out


def test_first_greeting_gets_heart(emoji_on):
    out = parent_flow.apply_greeting_farewell_heart(
        _conv(), "გამარჯობა", "როგორ დაგეხმაროთ")
    assert _HEART in out


def test_farewell_gets_heart(emoji_on):
    out = parent_flow.apply_greeting_farewell_heart(
        _conv(), "ნახვამდის", "კარგად იყავით")
    assert _HEART in out


def test_pure_thanks_gets_heart(emoji_on):
    out = parent_flow.apply_greeting_farewell_heart(
        _conv(), "მადლობა", "სიამოვნებით")
    assert _HEART in out


def test_midconvo_greeting_no_heart(emoji_on):
    # The bot has already replied → NOT the opening greeting → no heart (a mid-
    # conversation re-greeting is never hearted, matching the PARENT policy).
    conv = _conv(history=[{"role": "assistant", "content": "წინა პასუხი"}])
    out = parent_flow.apply_greeting_farewell_heart(
        conv, "გამარჯობა", "როგორ დაგეხმაროთ")
    assert _HEART not in out


def test_non_greeting_non_farewell_no_heart(emoji_on):
    out = parent_flow.apply_greeting_farewell_heart(
        _conv(), "ფასი რა არის?", "ფასი 100 ლარია")
    assert _HEART not in out


def test_already_has_heart_not_doubled(emoji_on):
    resp = f"გამარჯობა {_HEART}\n\nტექსტი"
    out = parent_flow.apply_greeting_farewell_heart(_conv(), "გამარჯობა", resp)
    assert out == resp
    assert out.count(_HEART) == 1


# ── integration: conversation_service wiring ─────────────────────────────────

def test_unclear_greeting_gets_heart_flag_on(emoji_on):
    out = conversation_service.process_message("u1", "გამარჯობა", "instagram")
    assert _HEART in out


def test_unclear_greeting_no_heart_flag_off():
    # Flag OFF (conftest default) → byte-identical: the UNCLEAR menu has no heart.
    out = conversation_service.process_message("u2", "გამარჯობა", "instagram")
    assert _HEART not in out


def test_adult_greeting_gets_heart_flag_on(emoji_on):
    # Sticky ADULT conversation + mocked adult engine → the universal heart wraps
    # the ADULT reply (route_segment != "PARENT").
    conversation_service.conversations["a1"] = Conversation(
        sender_id="a1", platform="instagram", segment="ADULT")
    emoji_on.setattr(adult_flow, "handle",
                     lambda c, m: "ღონისძიებებზე დაგეხმარებით")
    out = conversation_service.process_message("a1", "გამარჯობა", "instagram")
    assert _HEART in out


def test_parent_greeting_single_heart_not_doubled(emoji_on):
    # PARENT keeps its OWN policy; the universal wrap is skipped for route
    # "PARENT" → exactly one 💙 (regression guard against double-application).
    emoji_on.setattr(parent_flow, "_run_llm_engine_safely",
                     lambda c, m: "ბანაკზე დაგეხმარებით")
    out = conversation_service.process_message("p1", "გამარჯობა ბანაკი", "instagram")
    assert out.count(_HEART) == 1
