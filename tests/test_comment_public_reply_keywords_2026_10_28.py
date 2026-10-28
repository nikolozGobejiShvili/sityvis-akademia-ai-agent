"""Public comment reply only for a comment that asks something (2026-10-28).

Operator: on Instagram the public „გამარჯობა. დეტალები პირად შეტყობინებაში
გამოგიგზავნეთ." went under comments where parents asked for nothing — a story
about their child, a warm word. The public reply now follows the operator's own
keyword list (`comment_service.is_interest_intent`); every comment still gets
the DM. Applied to the 72 real comments of 2026-10-20..28: 10 match, 9 of them
real questions; neither Instagram comment matches.

And Facebook: the reply was POSTed to /{comment-id}/replies, which is the
Instagram edge — 71 of 71 Facebook public replies came back 400 „Unsupported
post request". A Facebook comment is answered at /{comment-id}/comments.
"""
from __future__ import annotations

import asyncio

import pytest

from app.routes import webhook
from app.services import comment_service
from tests.test_comment_flow import (  # noqa: F401 — reset_state is a fixture
    _FakeAsyncResponse,
    _patch_httpx,
    _patch_messenger,
    _patch_sheets,
    _RecordingAsyncClient,
    _swap_settings,
    reset_state,
)


def _comment(monkeypatch, text: str, platform: str):
    _patch_sheets(monkeypatch)
    sent = _patch_messenger(monkeypatch)
    monkeypatch.setattr(
        comment_service.admin_config_service,
        "get_active_adult_events", lambda *a, **kw: [],
    )
    client = _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={"caption": "#banaki"}),
    )
    _patch_httpx(monkeypatch, client)
    asyncio.run(
        webhook.handle_comment(
            comment_id="c1", post_id="p1", sender_id="user_x",
            user_name="ნინო", comment_text=text, platform=platform,
        ),
    )
    return client, sent


@pytest.fixture(autouse=True)
def _public_reply_on(monkeypatch):
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )


@pytest.mark.parametrize("text", [
    "ბაღის შემდეგ გზაში ჯერ ვეუბნები რომ ძალიან მომენატრა 🤷",
    "ანა შენ საუკეთესო ხარ ❤️❤️❤️",
    "წარმატებები🥰",
])
@pytest.mark.parametrize("platform", ["instagram", "facebook"])
def test_a_comment_that_asks_nothing_gets_no_public_reply_but_still_the_dm(
        monkeypatch, text, platform):
    client, sent = _comment(monkeypatch, text, platform)
    assert client.posts == []
    assert len(sent) == 1


@pytest.mark.parametrize("text", ["ფასი?", "მომწერეთ პირობები", "რომელი ასაკიდანაა?"])
def test_a_comment_with_a_keyword_gets_the_public_reply_and_the_dm(monkeypatch, text):
    client, sent = _comment(monkeypatch, text, "instagram")
    assert len(client.posts) == 1
    assert len(sent) == 1


def test_an_instagram_comment_is_answered_on_the_replies_edge(monkeypatch):
    client, _sent = _comment(monkeypatch, "ფასი?", "instagram")
    assert client.posts[0][0].endswith("/c1/replies")


def test_a_facebook_comment_is_answered_on_the_comments_edge(monkeypatch):
    client, _sent = _comment(monkeypatch, "ფასი?", "facebook")
    assert client.posts[0][0].endswith("/c1/comments")


def test_the_switch_off_still_means_no_public_reply_at_all(monkeypatch):
    _swap_settings(monkeypatch, ENABLE_PUBLIC_COMMENT_REPLY=False)
    client, sent = _comment(monkeypatch, "ფასი?", "facebook")
    assert client.posts == []
    assert len(sent) == 1
