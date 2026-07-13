"""COMMENT FLOW PATCH 1 — tests for the public-reply gate, the
Georgian-friendly hashtag matcher, and the new ADULT no-events DM
fallback.

These tests exercise `app/services/comment_service.py` and
`app/routes/webhook.py::handle_comment` with `httpx` / `messenger_service`
fully mocked. They do not depend on the live `test_agent.py` mock
harness.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest

import app.config as config_module
from app.routes import webhook
from app.services import admin_config_service, comment_service, conversation_service


# -- helpers --------------------------------------------------------------


def _swap_settings(monkeypatch, **overrides):
    """Patch the live `config.settings` (and the copies imported into
    `comment_service` / `webhook`) with a frozen Settings carrying the
    overrides."""
    swapped = dataclasses.replace(config_module.settings, **overrides)
    monkeypatch.setattr(config_module, "settings", swapped)
    monkeypatch.setattr(comment_service, "settings", swapped)
    monkeypatch.setattr(webhook, "settings", swapped)
    return swapped


class _FakeAsyncResponse:
    def __init__(self, *, is_success=True, status_code=200, text="",
                 payload=None):
        self.is_success = is_success
        self.status_code = status_code
        self.text = text
        self._payload = payload or {}

    def json(self):
        return self._payload


class _RecordingAsyncClient:
    """A drop-in replacement for `httpx.AsyncClient` that records every
    request and lets a test pre-program the response."""

    def __init__(self, *, post_response=None, get_response=None):
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[tuple[str, dict[str, Any]]] = []
        self._post_response = post_response or _FakeAsyncResponse()
        self._get_response = get_response or _FakeAsyncResponse(
            payload={"caption": ""},
        )

    def __call__(self, *args, **kwargs):
        # `httpx.AsyncClient(timeout=15)` — instance factory.
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, headers=None, json=None):
        self.posts.append((url, json or {}))
        if isinstance(self._post_response, Exception):
            raise self._post_response
        return self._post_response

    async def get(self, url, params=None):
        self.gets.append((url, params or {}))
        return self._get_response


def _patch_httpx(monkeypatch, client: _RecordingAsyncClient):
    """Patch comment_service.httpx so every `httpx.AsyncClient(...)`
    returns our recording client."""
    monkeypatch.setattr(
        comment_service, "httpx", SimpleNamespace(AsyncClient=client),
    )


def _patch_messenger(monkeypatch, *, private_reply_success: bool = True):
    """COMMENT FLOW PATCH 2 — both outbound channels (legacy DM and
    private reply) write into the same `sent` list with a `channel`
    key so existing assertions on len(sent) / sent[0]["text"] keep
    working. The mocked private reply can be forced to return False
    via `private_reply_success=False` to exercise the failure path.
    """
    sent: list[dict[str, Any]] = []

    def send_message(sender_id, platform, text):
        sent.append({
            "channel": "send_message",
            "sender_id": sender_id,
            "platform": platform,
            "text": text,
        })
        return True

    def send_private_reply(comment_id, text):
        sent.append({
            "channel": "private_reply",
            "comment_id": comment_id,
            "text": text,
        })
        return bool(private_reply_success)

    monkeypatch.setattr(
        comment_service, "messenger_service",
        SimpleNamespace(
            send_message=send_message,
            send_private_reply=send_private_reply,
        ),
    )
    return sent


def _patch_sheets(monkeypatch):
    saved: list[dict[str, Any]] = []
    monkeypatch.setattr(
        webhook, "sheets_service",
        SimpleNamespace(save_comment=lambda row: saved.append(dict(row)) or True),
    )
    return saved


@pytest.fixture(autouse=True)
def reset_state():
    conversation_service.conversations.clear()
    comment_service.post_content_cache.clear()
    # In-process duplicate-comment LRU is module-level; clear it so a
    # `comment_id` reused across tests is not silently deduplicated by
    # the previous test's run.
    webhook._processed_comments_lru.clear()
    yield
    conversation_service.conversations.clear()
    comment_service.post_content_cache.clear()
    webhook._processed_comments_lru.clear()


# =========================================================================
# PART 0 — hashtag normalisation
# =========================================================================


def test_hashtag_normaliser_strips_hash_and_trims():
    assert comment_service._normalize_hashtag("#ბანაკი") == "ბანაკი"
    assert comment_service._normalize_hashtag("  ბანაკი  ") == "ბანაკი"
    assert comment_service._normalize_hashtag(" #ბანაკი ") == "ბანაკი"
    assert comment_service._normalize_hashtag("BANAKI") == "banaki"
    assert comment_service._normalize_hashtag("") == ""
    assert comment_service._normalize_hashtag(None) == ""  # type: ignore[arg-type]


def test_extract_hashtags_uses_normaliser():
    out = comment_service.extract_hashtags("ბანაკი #ბანაკი #BANAKI #event")
    # Order preserved; '#' stripped; case-folded.
    assert out == ["ბანაკი", "banaki", "event"]


@pytest.mark.parametrize("post_tag,expected", [
    ("#ბანაკი", "PARENT"),
    ("#banaki", "PARENT"),
    ("#BANAKI", "PARENT"),
    ("#საღამო", "ADULT"),
    ("#sagamo", "ADULT"),
    ("#unknown", "UNCLEAR"),
])
def test_determine_segment_handles_case_and_hash(post_tag, expected, monkeypatch):
    """Georgian + Latin + mixed-case hashtags all match. Spec PART 0/5."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki", "ბანაკი"],
        ADULT_HASHTAGS=["event", "sagamo", "ღონისძიება", "საღამო"],
    )
    client = _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={"caption": f"text {post_tag}"}),
    )
    _patch_httpx(monkeypatch, client)

    out = asyncio.run(
        comment_service.determine_segment_from_post("post_x", "instagram"),
    )
    assert out == expected


def test_determine_segment_normalises_env_with_whitespace(monkeypatch):
    """Env values surrounded by whitespace must still match."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["  ბანაკი  ", " banaki"],
        ADULT_HASHTAGS=[],
    )
    client = _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={"caption": "#ბანაკი"}),
    )
    _patch_httpx(monkeypatch, client)
    out = asyncio.run(
        comment_service.determine_segment_from_post("post_x", "instagram"),
    )
    assert out == "PARENT"


# =========================================================================
# PART 1 + 2 + 3 — public reply must NOT block DM
# =========================================================================


def _run_handle_comment(monkeypatch, *, intent="INTERESTED",
                        segment="PARENT", caption="#banaki",
                        comment_text="მაინტერესებს",
                        adult_events: list[dict[str, Any]] | None = None):
    """Wire common mocks and invoke `handle_comment`."""
    async def _intent(_text):
        return intent

    monkeypatch.setattr(comment_service, "detect_comment_intent", _intent)
    _patch_sheets(monkeypatch)
    sent = _patch_messenger(monkeypatch)
    # Adult event comment DMs are now sourced from admin_config. Keep
    # tests deterministic by supplying the active-event list explicitly.
    monkeypatch.setattr(
        comment_service.admin_config_service,
        "get_active_adult_events", lambda *a, **kw: list(adult_events or []),
    )
    client = _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={"caption": caption}),
    )
    _patch_httpx(monkeypatch, client)
    asyncio.run(
        webhook.handle_comment(
            comment_id="c1", post_id="p1", sender_id="user_x",
            user_name="ნინო", comment_text=comment_text,
            platform="instagram",
        ),
    )
    return client, sent


def test_public_reply_disabled_by_default(monkeypatch):
    """ENABLE_PUBLIC_COMMENT_REPLY=False → no public-reply POST is
    made, but the DM still goes out via the private-reply channel."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    client, sent = _run_handle_comment(monkeypatch)
    # No public reply: only the GET for the post caption hit httpx.
    assert client.posts == []
    # DM was attempted via the new comment-private-reply channel.
    assert len(sent) == 1
    assert sent[0]["channel"] == "private_reply"
    assert sent[0]["comment_id"] == "c1"


def test_public_reply_enabled_calls_both(monkeypatch):
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )
    client, sent = _run_handle_comment(monkeypatch)
    assert len(client.posts) == 1
    assert "comments" in client.posts[0][0] or "replies" in client.posts[0][0]
    assert len(sent) == 1


def test_public_reply_failure_does_not_block_dm(monkeypatch):
    """Public reply returns an HTTP failure → DM still goes out."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )

    async def _intent(_text):
        return "INTERESTED"

    monkeypatch.setattr(comment_service, "detect_comment_intent", _intent)
    _patch_sheets(monkeypatch)
    sent = _patch_messenger(monkeypatch)
    # POST returns 500 → reply_to_comment will retry 3× and return False.
    client = _RecordingAsyncClient(
        post_response=_FakeAsyncResponse(is_success=False, status_code=500),
        get_response=_FakeAsyncResponse(payload={"caption": "#banaki"}),
    )
    # Speed up the retry loop.
    monkeypatch.setattr(comment_service.asyncio, "sleep",
                        lambda *_a, **_k: asyncio.sleep(0))
    _patch_httpx(monkeypatch, client)
    asyncio.run(
        webhook.handle_comment(
            comment_id="c1", post_id="p1", sender_id="user_x",
            user_name="ნინო", comment_text="მაინტერესებს",
            platform="instagram",
        ),
    )
    # Public reply attempted (3 retries), failed.
    assert len(client.posts) >= 1
    # DM still went out.
    assert len(sent) == 1


def test_public_reply_exception_does_not_block_dm(monkeypatch):
    """`reply_to_comment` raising an exception is logged and the DM
    is still attempted."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )

    async def _intent(_text):
        return "INTERESTED"

    async def _explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(comment_service, "detect_comment_intent", _intent)
    monkeypatch.setattr(comment_service, "reply_to_comment", _explode)
    _patch_sheets(monkeypatch)
    sent = _patch_messenger(monkeypatch)
    client = _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={"caption": "#banaki"}),
    )
    _patch_httpx(monkeypatch, client)
    asyncio.run(
        webhook.handle_comment(
            comment_id="c1", post_id="p1", sender_id="user_x",
            user_name="ნინო", comment_text="მაინტერესებს",
            platform="instagram",
        ),
    )
    assert len(sent) == 1, "DM must still fire after public-reply exception"


def test_not_interested_short_circuits(monkeypatch):
    """NOT_INTERESTED → no DM, no public reply."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )
    # Comment → Specific Event Mapping Patch (2026-06-08): the
    # deterministic keyword shortcut now overrides the LLM for obvious
    # interest phrases. Use a non-keyword comment so the LLM mock's
    # NOT_INTERESTED verdict is the path under test.
    client, sent = _run_handle_comment(
        monkeypatch, intent="NOT_INTERESTED", comment_text="გილოცავ!",
    )
    assert client.posts == []
    assert sent == []


def test_dm_runs_even_without_dm_history(monkeypatch):
    """The new flow drops the `has_dm_history` gate — the DM goes out
    for a brand-new sender."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    # No conversation pre-seeded — user is new.
    assert conversation_service.conversations == {}
    _client, sent = _run_handle_comment(monkeypatch)
    assert len(sent) == 1


# =========================================================================
# PART 4 — first-contact DM text (PARENT)
# =========================================================================
#
# PATCH 3 — PARENT first-contact is now a RICH DM built from
# camp_2026.yaml. The exact-equality assertion against
# PARENT_FIRST_CONTACT_DM moved to the fallback test below; this
# test verifies the rich-DM key facts instead.


def test_parent_first_contact_dm_carries_camp_facts(monkeypatch):
    """PATCH 3 — the rich DM must contain location (locative form),
    price, at least one stream date, and the registration URL."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment(monkeypatch)
    assert len(sent) == 1
    text = sent[0]["text"]
    # Facts from camp_2026.yaml.
    assert "ამბასადორ კაჭრეთ" in text  # locative form of location
    assert "2150" in text  # price
    assert "ივნისი" in text or "ივლისი" in text  # at least one stream
    assert "tinyurl.com" in text or "https://" in text  # registration link
    # And the friendly opener / closer.
    assert "მოხარულები ვართ" in text
    assert "ბანაკით" in text


# =========================================================================
# PART 5 — ADULT hashtag detection + no-events DM fallback
# =========================================================================



def test_adult_first_contact_dm_with_no_events(monkeypatch):
    """ADULT segment + no active admin events -> canonical no-active DM."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=["event", "sagamo"],
        EVENTS="legacy settings event should be ignored",
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    monkeypatch.setattr(
        comment_service,
        "_parse_events_blocks",
        lambda: pytest.fail("legacy settings.EVENTS parser must not own adult DMs"),
    )
    _client, sent = _run_handle_comment(
        monkeypatch, segment="ADULT", caption="#event",
        adult_events=[],
    )
    assert len(sent) == 1
    assert sent[0]["text"] == admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY
    assert sent[0]["text"] == comment_service.ADULT_NO_EVENTS_DM


def test_adult_first_contact_dm_with_events(monkeypatch):
    """ADULT segment + active admin event -> rich DM listing events."""
    events = [{
        "id": "poetry",
        "title": "Poetry Evening",
        "date_text": "15 May 20:00",
        "location": "Rooms Tbilisi",
        "price_text": "120",
        "reservation_url": "https://example.com/poetry",
    }]
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=["event"],
        EVENTS="legacy settings event should be ignored",
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    monkeypatch.setattr(
        comment_service,
        "_parse_events_blocks",
        lambda: pytest.fail("legacy settings.EVENTS parser must not own adult DMs"),
    )
    _client, sent = _run_handle_comment(
        monkeypatch, segment="ADULT", caption="#event",
        adult_events=events,
    )
    assert len(sent) == 1
    text = sent[0]["text"]
    assert text != comment_service.ADULT_NO_EVENTS_DM
    assert "Poetry Evening" in text
    assert "15 May 20:00" in text
    assert "Rooms Tbilisi" in text
    assert "120" in text
    assert "https://example.com/poetry" in text

def test_has_adult_events_helper(monkeypatch):
    """PATCH 3 — helper now requires a populated `სახელი:` value, not
    just the label."""
    _swap_settings(monkeypatch, EVENTS="")
    assert comment_service._has_adult_events_configured() is False
    _swap_settings(monkeypatch, EVENTS="just a header, no events block")
    assert comment_service._has_adult_events_configured() is False
    # Placeholder-only block (label present, value empty) — PATCH 3
    # heuristic correctly treats this as "no events yet".
    _swap_settings(monkeypatch, EVENTS="=== EVENT 1 ===\nსახელი: \n")
    assert comment_service._has_adult_events_configured() is False
    _swap_settings(monkeypatch, EVENTS="=== EVENT 1 ===\nსახელი: X\n")
    assert comment_service._has_adult_events_configured() is True


# =========================================================================
# Settings — default value
# =========================================================================


def test_settings_default_enable_public_comment_reply_true():
    """Comment Follow-up Logic Fix + Public Reply Ready (2026-05-31):
    code default flipped to True so public replies auto-activate once
    Meta grants `pages_manage_engagement` on the Page Access Token —
    no further code change needed. `.env` override to False still
    works (see `test_public_reply_disabled_by_default` above)."""
    from app.config import Settings
    s = Settings()
    assert s.ENABLE_PUBLIC_COMMENT_REPLY is True


# =========================================================================
# COMMENT FLOW PATCH 2 — comment-origin DM routing
# =========================================================================


def _run_handle_comment_for_platform(
    monkeypatch,
    *,
    platform: str,
    intent: str = "INTERESTED",
    caption: str = "#banaki",
    comment_id: str = "c_routing",
    comment_text: str = "მაინტერესებს",
):
    async def _intent(_text):
        return intent

    monkeypatch.setattr(comment_service, "detect_comment_intent", _intent)
    _patch_sheets(monkeypatch)
    sent = _patch_messenger(monkeypatch)
    # Generic Adult Event Comment Patch (2026-06-09) — see the
    # matching stub in `_run_handle_comment` above. Force the admin
    # active-events lookup to return [] so the legacy `settings.EVENTS`
    # fallback path stays exercised by these legacy comment-flow tests.
    monkeypatch.setattr(
        comment_service.admin_config_service,
        "get_active_adult_events", lambda *a, **kw: [],
    )
    # `fetch_post_content` asks for `caption` on IG and `message` on
    # FB. Build the payload with both keys so the mock works either
    # way, no matter the platform under test.
    client = _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={
            "caption": caption,
            "message": caption,
        }),
    )
    _patch_httpx(monkeypatch, client)
    asyncio.run(
        webhook.handle_comment(
            comment_id=comment_id, post_id="p1", sender_id="user_routing",
            user_name="ნინო", comment_text=comment_text,
            platform=platform,
        ),
    )
    return client, sent


def test_facebook_comment_routes_to_private_reply_not_send_message(monkeypatch):
    """The live bug: platform=facebook used to hit send_message and
    bounce off the unsupported-platform branch. Now it MUST take the
    private-reply channel."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment_for_platform(
        monkeypatch, platform="facebook",
    )
    assert len(sent) == 1
    assert sent[0]["channel"] == "private_reply", (
        f"facebook comment must NOT hit send_message: {sent!r}"
    )
    # No legacy send_message at all.
    assert not any(s["channel"] == "send_message" for s in sent)


def test_instagram_comment_routes_to_private_reply(monkeypatch):
    """Instagram comments also use private reply by default (preferred
    Meta-documented path for comment-origin DMs)."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment_for_platform(
        monkeypatch, platform="instagram",
    )
    assert len(sent) == 1
    assert sent[0]["channel"] == "private_reply"


def test_send_dm_from_comment_without_comment_id_falls_back_to_send_message(
    monkeypatch,
):
    """Backwards-compat: if a caller (e.g. an internal admin trigger)
    invokes `send_dm_from_comment` without a comment_id, the legacy
    send_message channel is used so nothing crashes."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
    )
    sent = _patch_messenger(monkeypatch)
    _patch_httpx(
        monkeypatch,
        _RecordingAsyncClient(
            get_response=_FakeAsyncResponse(payload={"caption": "#banaki"}),
        ),
    )
    out = asyncio.run(
        comment_service.send_dm_from_comment(
            "user_legacy", "messenger", "p1", segment="PARENT",
        ),
    )
    assert out is True
    assert len(sent) == 1
    assert sent[0]["channel"] == "send_message"
    assert sent[0]["platform"] == "messenger"


def test_private_reply_returns_false_when_no_comment_id(monkeypatch):
    """messenger_service.send_private_reply must refuse to send with an
    empty comment_id (no recipient → Meta would 400). The function
    returns False without making the HTTP call."""
    from app.services import messenger_service as ms

    posts: list[Any] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append((url, json))
        raise AssertionError("httpx.post must not be invoked")

    monkeypatch.setattr(ms.httpx, "post", fake_post)
    out = ms.send_private_reply("", "hi")
    assert out is False
    assert posts == []


def test_private_reply_uses_page_id_endpoint(monkeypatch):
    """Verifies the request URL uses /{PAGE_ID}/messages and the body
    sets recipient.comment_id."""
    from app.services import messenger_service as ms

    captured: list[dict[str, Any]] = []

    class _Resp:
        is_success = True
        status_code = 200
        text = ""

        def json(self):
            return {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append({"url": url, "headers": headers or {}, "json": json or {}})
        return _Resp()

    monkeypatch.setattr(ms.httpx, "post", fake_post)
    # Use the real settings — META_PAGE_ID must be present for the
    # endpoint assertion; if it's empty the fallback "me" is used.
    out = ms.send_private_reply("comment_42", "hello")
    assert out is True
    assert len(captured) == 1
    url = captured[0]["url"]
    assert "/messages" in url, f"unexpected url: {url!r}"
    assert captured[0]["json"]["recipient"] == {"comment_id": "comment_42"}
    assert captured[0]["json"]["message"]["text"] == "hello"


def test_private_reply_failure_returns_false(monkeypatch):
    """3 non-success responses → returns False after retries."""
    from app.services import messenger_service as ms

    posts: list[Any] = []

    class _Resp:
        is_success = False
        status_code = 400
        text = "Bad Request"

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append(url)
        return _Resp()

    # Avoid the 2-second sleep between retries.
    monkeypatch.setattr(ms, "sleep", lambda _s: None)
    monkeypatch.setattr(ms.httpx, "post", fake_post)
    out = ms.send_private_reply("comment_x", "hi")
    assert out is False
    assert len(posts) == 3


def test_handle_comment_logs_dm_failure_when_private_reply_fails(monkeypatch):
    """Private-reply returning False must propagate to a [COMMENT] DM/
    private reply failed log, not crash the handler."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )

    async def _intent(_text):
        return "INTERESTED"

    monkeypatch.setattr(comment_service, "detect_comment_intent", _intent)
    _patch_sheets(monkeypatch)
    sent = _patch_messenger(monkeypatch, private_reply_success=False)
    _patch_httpx(
        monkeypatch,
        _RecordingAsyncClient(
            get_response=_FakeAsyncResponse(payload={"caption": "#banaki"}),
        ),
    )
    # Should not raise.
    asyncio.run(
        webhook.handle_comment(
            comment_id="c_fail", post_id="p1", sender_id="user_z",
            user_name="ნ.", comment_text="მაინტერესებს",
            platform="facebook",
        ),
    )
    assert len(sent) == 1
    assert sent[0]["channel"] == "private_reply"


def test_send_message_still_logs_unsupported_for_raw_facebook(monkeypatch):
    """Defensive: messenger_service.send_message itself still rejects
    platform="facebook" — the fix is at the routing layer, not by
    silently accepting bad platforms in send_message."""
    from app.services import messenger_service as ms

    def fake_post(*args, **kwargs):
        raise AssertionError("send_message must not POST for unsupported platform")

    monkeypatch.setattr(ms.httpx, "post", fake_post)
    out = ms.send_message("FBID_123", "facebook", "hi")
    assert out is False


def test_parent_first_contact_via_private_reply(monkeypatch):
    """End-to-end: a PARENT comment on a Facebook Page produces the
    rich first-contact DM (PATCH 3) through the private-reply
    channel."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment_for_platform(
        monkeypatch, platform="facebook", caption="#banaki",
    )
    assert len(sent) == 1
    assert sent[0]["channel"] == "private_reply"
    # PATCH 3 — rich DM with camp facts (not the short fallback).
    assert "ამბასადორ კაჭრეთ" in sent[0]["text"]
    assert "2150" in sent[0]["text"]


def test_adult_first_contact_via_private_reply_no_events(monkeypatch):
    """End-to-end: an ADULT comment with no events configured uses the
    PATCH 3 no-events fallback over the private-reply channel."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=["ღონისძიება"],
        EVENTS="",
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment_for_platform(
        monkeypatch, platform="facebook", caption="#ღონისძიება",
    )
    assert len(sent) == 1
    assert sent[0]["channel"] == "private_reply"
    assert sent[0]["text"] == comment_service.ADULT_NO_EVENTS_DM


def test_not_interested_facebook_comment_no_private_reply(monkeypatch):
    """NOT_INTERESTED comments must NOT trigger a private reply even
    on Facebook."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    # Use a non-keyword comment so the LLM mock's NOT_INTERESTED
    # verdict is the path under test (the deterministic keyword
    # shortcut bypasses the LLM for obvious interest phrases).
    _client, sent = _run_handle_comment_for_platform(
        monkeypatch, platform="facebook", intent="NOT_INTERESTED",
        comment_text="გილოცავ!",
    )
    assert sent == []


def test_legacy_messenger_dm_flow_unchanged(monkeypatch):
    """Non-comment-origin call to send_dm_from_comment (platform=
    "messenger", no comment_id) still uses send_message — proves the
    routing change doesn't disturb the legacy path."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
    )
    sent = _patch_messenger(monkeypatch)
    _patch_httpx(
        monkeypatch,
        _RecordingAsyncClient(
            get_response=_FakeAsyncResponse(payload={"caption": "#banaki"}),
        ),
    )
    asyncio.run(
        comment_service.send_dm_from_comment(
            "psid_legacy", "messenger", "p1", segment="PARENT",
        ),
    )
    assert len(sent) == 1
    assert sent[0]["channel"] == "send_message"
    assert sent[0]["platform"] == "messenger"
    assert sent[0]["sender_id"] == "psid_legacy"


# =========================================================================
# COMMENT FLOW PATCH 3 — public reply text + rich DMs
# =========================================================================


# -- PATCH 3.A — public reply text ---------------------------------------


def test_patch3_public_reply_text_template_updated():
    """The template used by reply_to_comment for the dm-sent path must
    now be the uniform PATCH 3 text (no `{name}` placeholder).
    Agent Wording Cleanup Patch (2026-06-03): emoji-free."""
    from data.prompts import COMMENT_REPLY_DM_SENT
    expected = "გამარჯობა. დეტალები პირად შეტყობინებაში გამოგიგზავნეთ."
    assert COMMENT_REPLY_DM_SENT == expected


def test_patch3_public_reply_uses_uniform_text(monkeypatch):
    """End-to-end: when ENABLE_PUBLIC_COMMENT_REPLY=true and the
    public reply succeeds, the POSTed message matches the uniform
    PATCH 3 text exactly."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )
    client, _sent = _run_handle_comment(monkeypatch)
    # Exactly one POST = the public reply (the rich DM goes through
    # our mocked `send_private_reply`, not through httpx).
    assert len(client.posts) == 1
    url, body = client.posts[0]
    assert "/replies" in url
    # Agent Wording Cleanup Patch (2026-06-03): public reply template
    # is emoji-free.
    expected = "გამარჯობა. დეტალები პირად შეტყობინებაში გამოგიგზავნეთ."
    assert body.get("message") == expected


# -- PATCH 3.B — PARENT rich private reply --------------------------------


def test_patch3_parent_rich_dm_contains_location(monkeypatch):
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment(monkeypatch)
    assert "ამბასადორ კაჭრეთ" in sent[0]["text"]


def test_patch3_parent_rich_dm_contains_price(monkeypatch):
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment(monkeypatch)
    assert "2150" in sent[0]["text"]


def test_patch3_parent_rich_dm_contains_registration_url(monkeypatch):
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment(monkeypatch)
    text = sent[0]["text"]
    # YAML default registration URL.
    assert "https://" in text


def test_patch3_parent_rich_dm_contains_stream_dates(monkeypatch):
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment(monkeypatch)
    text = sent[0]["text"]
    # At least one Georgian stream date should appear.
    assert any(month in text for month in ("ივნისი", "ივლისი"))


def test_patch3_parent_rich_dm_builder_fallback_on_yaml_failure(monkeypatch):
    """When the camp YAML loader raises, the rich-DM builder must
    return the safe `PARENT_FIRST_CONTACT_DM` fallback — no crash.

    Admin Panel MVP added a new primary source for the PARENT DM. We
    explicitly disable it here so the test exercises the LEGACY YAML
    failure path the way it was originally written.
    """
    from app.services import admin_config_service

    def _boom(_name):
        raise RuntimeError("yaml missing")

    monkeypatch.setattr(comment_service, "load_knowledge", _boom)
    monkeypatch.setattr(
        admin_config_service, "get_section", lambda _sid: None,
    )
    out = comment_service._build_parent_rich_dm()
    assert out == comment_service.PARENT_FIRST_CONTACT_DM
    assert "მოხარულები ვართ" in out


def test_patch3_parent_rich_dm_builder_fallback_when_facts_missing(monkeypatch):
    """If camp_2026.yaml exists but is missing critical fields
    (location / duration / price), the builder still falls back
    gracefully — legacy path only, admin_config disabled here.
    """
    from app.services import admin_config_service

    monkeypatch.setattr(
        comment_service, "load_knowledge",
        lambda _name: {"camp": {"streams": [], "registration_url": ""}},
    )
    monkeypatch.setattr(
        admin_config_service, "get_section", lambda _sid: None,
    )
    out = comment_service._build_parent_rich_dm()
    assert out == comment_service.PARENT_FIRST_CONTACT_DM


# -- PATCH 3.C — ADULT rich private reply --------------------------------



def test_patch3_adult_rich_dm_lists_event_facts(monkeypatch):
    events = [{
        "id": "chamber",
        "title": "Chamber Music Evening",
        "date_text": "20 June 19:30",
        "location": "Stamba Lounge",
        "price_text": "150",
        "reservation_url": "https://example.com/chamber",
    }]
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=["event"],
        EVENTS="legacy settings event should be ignored",
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    monkeypatch.setattr(
        comment_service,
        "_parse_events_blocks",
        lambda: pytest.fail("legacy settings.EVENTS parser must not own adult DMs"),
    )
    _client, sent = _run_handle_comment(
        monkeypatch, segment="ADULT", caption="#event",
        adult_events=events,
    )
    text = sent[0]["text"]
    assert "Chamber Music Evening" in text
    assert "20 June 19:30" in text
    assert "Stamba Lounge" in text
    assert "150" in text
    assert "https://example.com/chamber" in text

def test_patch3_adult_rich_dm_uses_no_events_fallback(monkeypatch):
    """Even with the new builder, an empty events config still routes
    to ADULT_NO_EVENTS_DM."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=["ღონისძიება"],
        EVENTS="",
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment(
        monkeypatch, segment="ADULT", caption="#ღონისძიება",
    )
    assert sent[0]["text"] == comment_service.ADULT_NO_EVENTS_DM


def test_patch3_adult_rich_dm_with_only_placeholder_blocks(monkeypatch):
    """Blocks that exist but have empty `სახელი:` value count as no
    events and produce the fallback."""
    events = (
        "=== EVENT 1 ===\n"
        "სახელი: \n"
        "თარიღი: \n"
    )
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=["ღონისძიება"],
        EVENTS=events,
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    _client, sent = _run_handle_comment(
        monkeypatch, segment="ADULT", caption="#ღონისძიება",
    )
    assert sent[0]["text"] == comment_service.ADULT_NO_EVENTS_DM



def test_patch3_adult_rich_dm_caps_at_active_event_list_max(monkeypatch):
    """The DM lists at most the configured active-event cap."""
    events = [
        {
            "id": f"event_{i}",
            "title": f"Evening #{i}",
            "date_text": "1 June",
            "location": "Hall",
            "price_text": "50",
        }
        for i in range(1, comment_service._ACTIVE_EVENT_LIST_MAX + 2)
    ]
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=[],
        ADULT_HASHTAGS=["event"],
        EVENTS="legacy settings event should be ignored",
        ENABLE_PUBLIC_COMMENT_REPLY=False,
    )
    monkeypatch.setattr(
        comment_service,
        "_parse_events_blocks",
        lambda: pytest.fail("legacy settings.EVENTS parser must not own adult DMs"),
    )
    _client, sent = _run_handle_comment(
        monkeypatch, segment="ADULT", caption="#event",
        adult_events=events,
    )
    text = sent[0]["text"]
    for i in range(1, comment_service._ACTIVE_EVENT_LIST_MAX + 1):
        assert f"Evening #{i}" in text
    assert f"Evening #{comment_service._ACTIVE_EVENT_LIST_MAX + 1}" not in text

def test_patch3_adult_rich_dm_handles_parser_exception(monkeypatch):
    """If _parse_events_blocks raises, the builder still returns the
    safe fallback."""
    def _boom():
        raise RuntimeError("events broken")

    monkeypatch.setattr(comment_service, "_parse_events_blocks", _boom)
    out = comment_service._build_adult_rich_dm()
    assert out == comment_service.ADULT_NO_EVENTS_DM


# -- PATCH 3.D — events parser helper -----------------------------------


def test_patch3_parse_events_blocks_filters_empty_names(monkeypatch):
    text = (
        "=== EVENT 1 ===\n"
        "სახელი: Real\n"
        "თარიღი: 1 May\n"
        "\n"
        "=== EVENT 2 ===\n"
        "სახელი: \n"
        "თარიღი: 2 May\n"
    )
    _swap_settings(monkeypatch, EVENTS=text)
    out = comment_service._parse_events_blocks()
    assert len(out) == 1
    assert out[0]["name"] == "Real"
    assert out[0]["date"] == "1 May"


def test_patch3_parse_events_blocks_empty_when_no_events(monkeypatch):
    _swap_settings(monkeypatch, EVENTS="")
    assert comment_service._parse_events_blocks() == []
    _swap_settings(monkeypatch, EVENTS="no events here")
    assert comment_service._parse_events_blocks() == []


# -- PATCH 3.E — locative helper ----------------------------------------


def test_patch3_locative_location_matches_router_helper():
    """Sanity check on the duplicated `_locative_location` —
    "ამბასადორი კაჭრეთი" → "ამბასადორ კაჭრეთში"."""
    assert comment_service._locative_location("ამბასადორი კაჭრეთი") == (
        "ამბასადორ კაჭრეთში"
    )
    assert comment_service._locative_location("თბილისი") == "თბილისში"
    assert comment_service._locative_location("") == ""


# -- PATCH 3.F — public reply enabled + rich DM still flows -------------


def test_patch3_public_reply_enabled_does_not_block_rich_dm(monkeypatch):
    """End-to-end PATCH 1 + 3: both channels fire when public reply is
    enabled. The rich DM still carries camp facts."""
    _swap_settings(
        monkeypatch,
        PARENT_HASHTAGS=["banaki"],
        ADULT_HASHTAGS=[],
        ENABLE_PUBLIC_COMMENT_REPLY=True,
    )
    client, sent = _run_handle_comment(monkeypatch)
    # Public reply attempted (one POST to /replies).
    assert len(client.posts) == 1
    # Rich DM delivered through private_reply channel.
    assert len(sent) == 1
    assert sent[0]["channel"] == "private_reply"
    assert "2150" in sent[0]["text"]


# -- PATCH 3.G — fallback content texts ---------------------------------


def test_patch3_parent_fallback_constant_uses_new_text():
    text = comment_service.PARENT_FIRST_CONTACT_DM
    assert "მოხარულები ვართ" in text
    assert "ბანაკით" in text
    # The PATCH 1 short text "ბანაკის შესახებ დეტალებს …" is gone.
    assert "ბანაკის შესახებ დეტალებს" not in text



def test_patch3_adult_no_events_fallback_constant_uses_admin_config_text():
    text = comment_service.ADULT_NO_EVENTS_DM
    assert text == admin_config_service.ADULT_NO_ACTIVE_EVENTS_REPLY


# =========================================================================
# In-process duplicate-comment guard (Redis fallback)
# =========================================================================


@pytest.fixture
def _clear_local_lru():
    """Reset the in-process LRU before and after each test so cases
    can't bleed into each other."""
    webhook._processed_comments_lru.clear()
    yield
    webhook._processed_comments_lru.clear()


def test_local_lru_blocks_duplicate_when_redis_disabled(
    monkeypatch, _clear_local_lru,
):
    """With Redis off, a second delivery of the same comment_id must
    still be short-circuited by the in-process LRU."""
    _swap_settings(monkeypatch, ENABLE_PUBLIC_COMMENT_REPLY=False)
    monkeypatch.setattr(
        webhook.redis_state_service, "is_enabled", lambda: False,
    )
    monkeypatch.setattr(
        webhook.redis_state_service, "exists", lambda key: False,
    )
    monkeypatch.setattr(
        webhook.redis_state_service, "set_json",
        lambda key, value=None, ttl=None: True,
    )
    sent = _patch_messenger(monkeypatch)
    _patch_sheets(monkeypatch)
    _patch_httpx(monkeypatch, _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={"caption": "ბანაკი #ბანაკი"}),
    ))
    monkeypatch.setattr(
        comment_service, "detect_comment_intent",
        lambda text: _async_value("INTERESTED"),
    )

    asyncio.run(webhook.handle_comment(
        comment_id="cmt-lru-1", post_id="p1", sender_id="s1",
        user_name="QA", comment_text="ბანაკი მაინტერესებს",
        platform="facebook",
    ))
    first_count = len(sent)
    assert first_count >= 1

    asyncio.run(webhook.handle_comment(
        comment_id="cmt-lru-1", post_id="p1", sender_id="s1",
        user_name="QA", comment_text="ბანაკი მაინტერესებს",
        platform="facebook",
    ))
    assert len(sent) == first_count, "second delivery must be deduplicated"


def test_local_lru_blocks_duplicate_when_redis_enabled(
    monkeypatch, _clear_local_lru,
):
    """LRU also short-circuits when Redis is enabled (cheaper than the
    Redis round-trip on the second delivery)."""
    _swap_settings(monkeypatch, ENABLE_PUBLIC_COMMENT_REPLY=False)
    monkeypatch.setattr(
        webhook.redis_state_service, "is_enabled", lambda: True,
    )
    seen: set[str] = set()
    monkeypatch.setattr(
        webhook.redis_state_service, "exists", lambda key: key in seen,
    )
    monkeypatch.setattr(
        webhook.redis_state_service, "set_json",
        lambda key, value=None, ttl=None: (seen.add(key) or True),
    )
    sent = _patch_messenger(monkeypatch)
    _patch_sheets(monkeypatch)
    _patch_httpx(monkeypatch, _RecordingAsyncClient(
        get_response=_FakeAsyncResponse(payload={"caption": "ბანაკი #ბანაკი"}),
    ))
    monkeypatch.setattr(
        comment_service, "detect_comment_intent",
        lambda text: _async_value("INTERESTED"),
    )

    asyncio.run(webhook.handle_comment(
        comment_id="cmt-lru-2", post_id="p1", sender_id="s1",
        user_name="QA", comment_text="ბანაკი", platform="facebook",
    ))
    first_count = len(sent)
    assert first_count >= 1

    asyncio.run(webhook.handle_comment(
        comment_id="cmt-lru-2", post_id="p1", sender_id="s1",
        user_name="QA", comment_text="ბანაკი", platform="facebook",
    ))
    assert len(sent) == first_count


def test_local_lru_caps_at_1000(_clear_local_lru):
    """LRU must evict the oldest entries past the cap so process memory
    stays bounded."""
    for i in range(1100):
        webhook._mark_comment_processed_local(f"cmt-{i}")
    assert len(webhook._processed_comments_lru) == 1000
    # Oldest 100 evicted; newest 1000 retained.
    assert "cmt-0" not in webhook._processed_comments_lru
    assert "cmt-1099" in webhook._processed_comments_lru


def test_local_lru_ignores_empty_comment_id(_clear_local_lru):
    """Empty / None comment_id must not pollute the LRU."""
    webhook._mark_comment_processed_local("")
    webhook._mark_comment_processed_local(None)  # type: ignore[arg-type]
    assert len(webhook._processed_comments_lru) == 0
    assert webhook._is_comment_processed_local("") is False
    assert webhook._is_comment_processed_local(None) is False  # type: ignore[arg-type]


async def _async_value(value):  # tiny helper for the detect_comment_intent mock
    return value