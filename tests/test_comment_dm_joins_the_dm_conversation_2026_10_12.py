"""The comment's private message joins the person's DM conversation (2026-10-12).

Live, client Page, 2026-10-09 → 10-12: three parents who commented got the
private message „მოგესალმებით🩵 რომელი პროგრამით ხართ დაინტერესებული?", answered
it in Messenger, and were greeted again — „გამარჯობა!". The private message
was stored under the bare sender id, the DM under platform + page + sender, so
the DM conversation had no assistant turn: no strip of a repeated greeting, a
model that did not know it had asked anything, and two follow-up records for
one person (`platform=facebook` and `platform=messenger` in the follow-up log).

The comment webhook carries the Page id (entry.id) — the same id the DM
carries — so the private message is stored where the reply will arrive.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agent.llm import parent_llm_engine as eng
from app.flows import parent_flow
from app.routes import webhook
from app.services import comment_service, conversation_service

PAGE = "1716573211895723"
SENDER = "28617309384587134"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    conversation_service.conversations.clear()
    monkeypatch.setattr(comment_service, "resolve_section_from_post",
                        AsyncMock(return_value=None))
    monkeypatch.setattr(comment_service.messenger_service, "send_private_reply",
                        lambda comment_id, message: True)
    yield
    conversation_service.conversations.clear()


def _send(platform="facebook", page_id=PAGE, segment="UNCLEAR"):
    return asyncio.run(comment_service.send_dm_from_comment(
        SENDER, platform, f"{PAGE}_post", segment,
        comment_id="c-1", comment_text="ფასი?", page_id=page_id,
    ))


def test_the_private_message_is_in_the_messenger_conversation():
    assert _send() is True
    dm = conversation_service._get_or_create_conversation(SENDER, "messenger", PAGE)
    assistant = [t for t in dm.history if t.get("role") == "assistant"]
    assert len(assistant) == 1 and assistant[0]["content"]
    assert len(conversation_service.conversations) == 1  # one conversation, not two


def test_the_reply_to_it_is_not_greeted_again():
    _send()
    dm = conversation_service._get_or_create_conversation(SENDER, "messenger", PAGE)
    assert eng._conversation_has_assistant_turn(dm)
    assert parent_flow._maybe_static_welcome(dm, "გამარჯობა") is None
    assert eng._strip_mid_conversation_greeting(
        "გამარჯობა!\n\nსაკვირაო სკოლა 595 ლარია.", dm, user_message="რა ღირს?",
    ) == "საკვირაო სკოლა 595 ლარია."


def test_a_conversation_under_way_keeps_its_state():
    dm = conversation_service._get_or_create_conversation(SENDER, "messenger", PAGE)
    dm.segment, dm.state = "PARENT", "DONE"
    dm.history += [{"role": "user", "content": "საკვირაო სკოლა"},
                   {"role": "assistant", "content": "პასუხი"}]
    _send()
    assert (dm.segment, dm.state) == ("PARENT", "DONE")
    assert len(dm.history) == 3 and dm.history[-1]["role"] == "assistant"


def test_an_instagram_comment_joins_the_instagram_conversation():
    _send(platform="instagram")
    ig = conversation_service._get_or_create_conversation(SENDER, "instagram", PAGE)
    assert any(t.get("role") == "assistant" for t in ig.history)


def test_the_comment_follow_up_sees_the_dm_conversation():
    _send()
    assert comment_service._has_active_conversation(SENDER)


def test_without_a_page_id_the_per_sender_entry_is_kept():
    _send(page_id="")
    assert SENDER in conversation_service.conversations


def test_the_webhook_passes_the_page_id(monkeypatch):
    seen = {}

    async def _capture(*args, **kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(webhook, "handle_comment", _capture)
    webhook._process_comment_events({"entry": [{"id": PAGE, "changes": [{
        "field": "feed",
        "value": {"item": "comment", "verb": "add", "comment_id": "c-1",
                  "post_id": f"{PAGE}_post", "from": {"id": SENDER, "name": "x"},
                  "message": "ფასი?"},
    }]}]})
    assert seen.get("page_id") == PAGE
