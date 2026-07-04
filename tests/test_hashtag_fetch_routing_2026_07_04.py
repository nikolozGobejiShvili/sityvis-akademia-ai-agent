"""Hashtag-based Comment → DM routing regression (2026-07-04).

Production bug: a Facebook Camp post whose caption carried #ბანაკი did NOT
route by hashtag because `fetch_post_content` returned HTTP 400, so the
extracted hashtags collapsed to `[]` and the segment fell to UNCLEAR.

These tests lock in the fixed `fetch_post_content`:
  * platform-correct Graph fields (Instagram → `caption`, Facebook → `message`
    with a `story` safe fallback),
  * a failed primary field request retries the safe fallback field instead of
    collapsing immediately,
  * caption-hashtag routing works for camp / adult / Sunday-School WITHOUT any
    manual `facebook_post_ids` mapping,
  * the section-level `facebook_post_ids` mapping still works as a fallback,
  * a fully failed fetch with no post_id mapping still yields UNCLEAR,
  * the access token is never logged, even when a Meta error body echoes it.

`httpx` is fully mocked; no network call is made. The section config is read
from the real `data/admin_config/sections.yaml` (camp/adult/Sunday-School
hashtags), so these tests also guard that the existing admin hashtag field
stays the primary routing source.
"""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
from typing import Any

import app.config as config_module
from app.services import comment_service


# -- helpers --------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


class _FieldResponse:
    """A pre-programmed httpx-like response for one `fields=` request."""

    def __init__(self, *, is_success=True, status_code=200, payload=None, text=""):
        self.is_success = is_success
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FieldRoutingClient:
    """Drop-in `httpx.AsyncClient` replacement that returns a response chosen
    by the requested `fields` param and records the field of every call.

    An unmapped field defaults to a 400 so a test can assert the fallback
    field path is taken."""

    def __init__(self, by_field: dict[str, _FieldResponse]):
        self.by_field = by_field
        self.calls: list[str] = []

    def __call__(self, *a, **kw):  # httpx.AsyncClient(timeout=15)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, params=None):
        field = (params or {}).get("fields")
        self.calls.append(field)
        resp = self.by_field.get(field)
        if resp is None:
            return _FieldResponse(is_success=False, status_code=400, payload={})
        return resp


def _patch(monkeypatch, client: _FieldRoutingClient):
    """Patch httpx, disable the retry sleep, and clear the post cache."""
    monkeypatch.setattr(
        comment_service, "httpx", SimpleNamespace(AsyncClient=client),
    )

    async def _no_sleep(*_a, **_k):
        return None

    monkeypatch.setattr(comment_service.asyncio, "sleep", _no_sleep)
    comment_service.post_content_cache.clear()


def _swap_token(monkeypatch, token: str):
    swapped = dataclasses.replace(config_module.settings, META_ACCESS_TOKEN=token)
    monkeypatch.setattr(config_module, "settings", swapped)
    monkeypatch.setattr(comment_service, "settings", swapped)
    return swapped


def _log_text(caplog) -> str:
    return "\n".join(rec.getMessage() for rec in caplog.records)


# -- 1. Facebook uses the message field ----------------------------------


def test_facebook_uses_message_field_and_extracts_hashtag(monkeypatch):
    client = _FieldRoutingClient({
        "message": _FieldResponse(payload={"message": "ზაფხულის ბანაკი 2026 #ბანაკი"}),
    })
    _patch(monkeypatch, client)

    text = _run(comment_service.fetch_post_content("fb_camp_1", "facebook"))

    assert "#ბანაკი" in text
    # Facebook-safe field first — never the Instagram-only `caption`.
    assert client.calls[0] == "message"
    assert "caption" not in client.calls
    assert comment_service.extract_hashtags(text) == ["ბანაკი"]


# -- 2. Instagram uses the caption field ---------------------------------


def test_instagram_uses_caption_field_and_extracts_hashtag(monkeypatch):
    client = _FieldRoutingClient({
        "caption": _FieldResponse(payload={"caption": "#ბანაკი დაიწყო"}),
    })
    _patch(monkeypatch, client)

    text = _run(comment_service.fetch_post_content("ig_camp_1", "instagram"))

    assert "#ბანაკი" in text
    # Instagram-safe field only — never the Facebook-only `message`.
    assert client.calls == ["caption"]
    assert comment_service.extract_hashtags(text) == ["ბანაკი"]


# -- 3. Facebook primary-field failure retries the safe fallback field ----


def test_facebook_primary_field_failure_falls_back_to_story(monkeypatch):
    client = _FieldRoutingClient({
        "message": _FieldResponse(
            is_success=False, status_code=400,
            payload={"error": {"code": 100, "message": "nonexisting field (message)"}},
        ),
        "story": _FieldResponse(payload={"story": "შემოდგომის ბანაკი #ბანაკი"}),
    })
    _patch(monkeypatch, client)

    text = _run(comment_service.fetch_post_content("fb_camp_2", "facebook"))

    assert "#ბანაკი" in text
    assert "message" in client.calls and "story" in client.calls
    # `story` is only tried AFTER `message` fails — not collapsing immediately.
    assert client.calls.index("story") > client.calls.index("message")


# -- 4. Facebook #ბანაკი → summer_camp WITHOUT post_id mapping ------------


def test_facebook_camp_hashtag_routes_to_parent_without_post_id_map(monkeypatch):
    client = _FieldRoutingClient({
        "message": _FieldResponse(payload={"message": "ბანაკი 2026 #ბანაკი #camp"}),
    })
    _patch(monkeypatch, client)

    segment = _run(
        comment_service.determine_segment_from_post("fb_camp_unmapped", "facebook"),
    )
    assert segment == "PARENT"

    section = _run(
        comment_service.resolve_section_from_post("fb_camp_unmapped", "facebook"),
    )
    assert section is not None and section.get("id") == "summer_camp"


# -- 5. Facebook adult hashtags → adult_events WITHOUT post_id mapping -----


def test_facebook_adult_hashtags_route_to_adult_without_post_id_map(monkeypatch):
    for tag in ("#ღონისძიება", "#საღამო", "#event"):
        client = _FieldRoutingClient({
            "message": _FieldResponse(payload={"message": f"დღეს {tag} გვაქვს"}),
        })
        _patch(monkeypatch, client)
        segment = _run(
            comment_service.determine_segment_from_post(f"fb_adult_{tag}", "facebook"),
        )
        assert segment == "ADULT", tag


# -- 6. Facebook Sunday-School hashtag → sunday_school section -------------


def test_facebook_sunday_school_hashtag_resolves_ss_section_without_map(monkeypatch):
    client = _FieldRoutingClient({
        "message": _FieldResponse(
            payload={"message": "საკვირაო სკოლა #საკვირაოსკოლა #sunday_school"},
        ),
    })
    _patch(monkeypatch, client)

    section = _run(
        comment_service.resolve_section_from_post("fb_ss_unmapped", "facebook"),
    )
    assert section is not None
    assert section.get("id") == "sunday_school"


# -- 7. Existing facebook_post_ids mapping still works as a fallback -------


def test_post_id_mapping_still_resolves_without_caption_fetch(monkeypatch):
    # Every field would 400 — proving the section-level post_id map
    # short-circuits BEFORE the caption fetch is even attempted.
    client = _FieldRoutingClient({})
    _patch(monkeypatch, client)

    section = _run(
        comment_service.resolve_section_from_post(
            "986476147893240_122113415120776096", "facebook",
        ),
    )
    assert section is not None and section.get("id") == "summer_camp"
    # post_id map short-circuited — the Graph caption fetch never ran.
    assert client.calls == []


# -- 8. Failed fetch + no post_id map → UNCLEAR ---------------------------


def test_failed_fetch_without_post_id_map_stays_unclear(monkeypatch):
    # All field requests fail; the post is not mapped and the caption is
    # unreachable, so routing must degrade to UNCLEAR (category menu).
    client = _FieldRoutingClient({})
    _patch(monkeypatch, client)

    segment = _run(
        comment_service.determine_segment_from_post("fb_unmapped_fail", "facebook"),
    )
    assert segment == "UNCLEAR"


# -- 9. The access token is never logged ---------------------------------


def test_no_access_token_logged_even_when_meta_error_echoes_it(monkeypatch, caplog):
    _swap_token(monkeypatch, "SECRET_TOKEN_XYZ")
    client = _FieldRoutingClient({
        "message": _FieldResponse(
            is_success=False, status_code=400,
            payload={"error": {
                "code": 190, "type": "OAuthException",
                "message": "Invalid OAuth access token: access_token=SECRET_TOKEN_XYZ",
                "fbtrace_id": "Abc123",
            }},
            text="raw body access_token=SECRET_TOKEN_XYZ",
        ),
        "story": _FieldResponse(
            is_success=False, status_code=400,
            payload={"error": {"code": 190, "message": "SECRET_TOKEN_XYZ leaked bare"}},
        ),
    })
    _patch(monkeypatch, client)

    caplog.set_level("INFO")
    out = _run(comment_service.fetch_post_content("fb_secret", "facebook"))

    assert out == ""
    text = _log_text(caplog)
    assert "SECRET_TOKEN_XYZ" not in text
    # The sanitized diagnostic (error code) IS surfaced for debuggability.
    assert "code=190" in text


def test_failed_fetch_is_not_cached_so_routing_recovers(monkeypatch):
    """A fully failed fetch must NOT be cached — the next comment re-fetches,
    so hashtag routing recovers the moment the Meta permission is fixed."""
    failing = _FieldRoutingClient({})
    _patch(monkeypatch, failing)
    assert _run(comment_service.fetch_post_content("fb_recover", "facebook")) == ""
    assert "fb_recover" not in comment_service.post_content_cache

    # Now the caption is reachable — same post id must resolve, not serve a
    # cached empty.
    ok = _FieldRoutingClient({
        "message": _FieldResponse(payload={"message": "ბანაკი #ბანაკი"}),
    })
    monkeypatch.setattr(
        comment_service, "httpx", SimpleNamespace(AsyncClient=ok),
    )
    text = _run(comment_service.fetch_post_content("fb_recover", "facebook"))
    assert "#ბანაკი" in text
