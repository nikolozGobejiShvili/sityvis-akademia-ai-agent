"""Comment → Specific Event Mapping Patch (2026-06-08) — tests.

Test groups (per task spec PART 8):
  1. broad interest intent detection
  2. event tag in comment
  3. event tag in post caption
  4. facebook_post_id exact match
  5. facebook_post_id optional
  6. ambiguous event clarification
  7. inactive event exclusion
  8. specific event DM content
  9. missing link handoff
 10. no sold-out hallucination
 11. camp comment broad interest phrases
 12. post caption fetch soft-fail
 13. no token logging
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

import pytest
import yaml

import app.config as config_module
from app.services import admin_config_service, comment_service


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _swap_settings(monkeypatch, **overrides):
    swapped = dataclasses.replace(config_module.settings, **overrides)
    monkeypatch.setattr(config_module, "settings", swapped)
    monkeypatch.setattr(comment_service, "settings", swapped)
    return swapped


@pytest.fixture
def sections_path(monkeypatch, tmp_path):
    path = tmp_path / "sections.yaml"
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", path)
    return path


def _seed_events(path, events: list[dict]) -> None:
    body = yaml.safe_dump(
        {"sections": [
            {
                "id": "adult_events",
                "name": "ზრდასრულთა ღონისძიებები",
                "type": "adult_events",
                "status": "active",
                "hashtags": ["ღონისძიება", "event"],
                "age_min": 13,
                "auto_dm_template_id": "adult_events_comment_dm",
                "events": events,
            },
        ]},
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    path.write_text(body, encoding="utf-8")


@pytest.fixture(autouse=True)
def clear_post_cache():
    comment_service.post_content_cache.clear()
    yield
    comment_service.post_content_cache.clear()


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. broad interest intent detection (PART 1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "ფასი?",
    "სად ტარდება?",
    "ბმული?",
    "მაინტერესებს",
    "როგორ დავრეგისტრირდე?",
    "ინფო",
    "info",
    "price",
    "where",
    "interested",
    "მინდა დეტალები",
    "მისამართი?",
    "რომელ საათზე",
    "ლინკი გამომიგზავნეთ",
    "ბილეთის ბმული?",
    "ასაკი?",
    "პირობები?",
])
def test_interest_intent_matches_broad_keywords(text):
    assert comment_service.is_interest_intent(text) is True


@pytest.mark.parametrize("text", [
    "გილოცავ!",
    "მშვენიერია",
    "კარგია",
    "ძალიან მაგარია",
    "nice",
    "",
])
def test_interest_intent_rejects_unrelated_comment(text):
    assert comment_service.is_interest_intent(text) is False


# ---------------------------------------------------------------------------
# 2. event tag in comment (Priority B)
# ---------------------------------------------------------------------------


def test_event_tag_in_comment_selects_event(sections_path):
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია", "ქართული_პოეზია"],
        },
        {
            "id": "maroon", "title": "Maroon 5 კონცერტი",
            "status": "active", "min_age": 13,
            "tags": ["maroon", "Maroon 5"],
        },
    ])
    event, candidates, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ქართული პოეზია მაინტერესებს",
            post_id="", platform="facebook",
        ),
    )
    assert event is not None
    assert event["id"] == "poetry"
    assert reason == "comment_tag"
    assert len(candidates) == 1


def test_event_tag_matches_underscore_to_space(sections_path):
    """A comment with the underscore form must still match a tag
    saved with spaces (operator convenience)."""
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "T",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია"],
        },
    ])
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ფასი #ქართული_პოეზია?",
            post_id="", platform="facebook",
        ),
    )
    assert event is not None
    assert reason == "comment_tag"


def test_event_title_falls_back_as_implicit_tag(sections_path):
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            # No explicit tags — title alone must still match.
        },
    ])
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ქართული პოეზიის საღამო რომელ საათზე?",
            post_id="", platform="facebook",
        ),
    )
    assert event is not None
    assert reason == "comment_tag"


# ---------------------------------------------------------------------------
# 3. event tag in post caption (Priority C)
# ---------------------------------------------------------------------------


def test_caption_tag_selects_event_when_comment_is_generic(
    sections_path, monkeypatch,
):
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია", "ქართული_პოეზია"],
        },
    ])

    async def fake_fetch(post_id: str, platform: str) -> str:
        return "#event #ქართული_პოეზია"

    monkeypatch.setattr(comment_service, "fetch_post_content", fake_fetch)
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ფასი?",
            post_id="post_42", platform="facebook",
        ),
    )
    assert event is not None
    assert event["id"] == "poetry"
    assert reason == "caption_tag"


def test_caption_tag_skipped_when_comment_already_matched(
    sections_path, monkeypatch,
):
    """Priority B beats C — when the comment already identifies the
    event, the caption is not consulted (no extra Meta Graph call)."""
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია"],
        },
    ])
    fetch_calls: list[str] = []

    async def fake_fetch(post_id: str, platform: str) -> str:
        fetch_calls.append(post_id)
        return ""

    monkeypatch.setattr(comment_service, "fetch_post_content", fake_fetch)
    _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ქართული პოეზია მაინტერესებს",
            post_id="post_42", platform="facebook",
        ),
    )
    assert fetch_calls == []


# ---------------------------------------------------------------------------
# 4. facebook_post_id exact match (Priority A) + 7. wins over tag ambiguity
# ---------------------------------------------------------------------------


def test_facebook_post_id_exact_match_selects_event(sections_path):
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "facebook_post_id": "fb_post_777",
        },
        {
            "id": "maroon", "title": "Maroon 5 კონცერტი",
            "status": "active", "min_age": 13,
            "facebook_post_id": "fb_post_999",
        },
    ])
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ფასი?",
            post_id="fb_post_777", platform="facebook",
        ),
    )
    assert event["id"] == "poetry"
    assert reason == "facebook_post_id"


def test_facebook_post_id_wins_over_tag_ambiguity(sections_path):
    _seed_events(sections_path, [
        {
            "id": "poetry_a", "title": "ქართული პოეზიის საღამო ერთი",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია"],
            "facebook_post_id": "fb_post_specific",
        },
        {
            "id": "poetry_b", "title": "ქართული პოეზიის საღამო ორი",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია"],
        },
    ])
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ქართული პოეზია",
            post_id="fb_post_specific", platform="facebook",
        ),
    )
    assert reason == "facebook_post_id"
    assert event["id"] == "poetry_a"


# ---------------------------------------------------------------------------
# 5. facebook_post_id optional
# ---------------------------------------------------------------------------


def test_facebook_post_id_is_optional_when_tag_matches(sections_path):
    """Event without facebook_post_id is still selectable via tag."""
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია"],
            # NO facebook_post_id
        },
    ])
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ქართული პოეზია მაინტერესებს",
            post_id="some_random_post", platform="facebook",
        ),
    )
    assert event is not None
    assert reason == "comment_tag"


def test_save_event_preserves_facebook_post_id_and_tags_round_trip(
    sections_path,
):
    """Editing other fields doesn't drop fb id / tags."""
    _seed_events(sections_path, [])
    admin_config_service.save_adult_event(
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "facebook_post_id": "fb_post_123",
            "tags": ["ქართული პოეზია", "პოეზიის საღამო"],
        },
    )
    # Now edit only the price.
    admin_config_service.update_adult_event(
        "poetry", {"price_text": "150"},
    )
    raw = yaml.safe_load(sections_path.read_text(encoding="utf-8"))
    saved = raw["sections"][0]["events"][0]
    assert saved["facebook_post_id"] == "fb_post_123"
    assert "ქართული პოეზია" in saved["tags"]
    assert saved["price_text"] == "150"


# ---------------------------------------------------------------------------
# 6. ambiguous event clarification (Priority E)
# ---------------------------------------------------------------------------


def test_ambiguous_tags_returns_clarification(sections_path):
    _seed_events(sections_path, [
        {
            "id": "morning", "title": "დილის პოეზია",
            "status": "active", "min_age": 13,
            "tags": ["პოეზია"],
        },
        {
            "id": "evening", "title": "საღამოს პოეზია",
            "status": "active", "min_age": 13,
            "tags": ["პოეზია"],
        },
    ])
    event, candidates, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="პოეზია მაინტერესებს",
            post_id="", platform="facebook",
        ),
    )
    assert event is None
    assert reason == "ambiguous"
    assert {c["id"] for c in candidates} == {"morning", "evening"}


def test_ambiguous_dm_lists_both_titles(sections_path):
    candidates = [
        {"id": "a", "title": "დილის პოეზია"},
        {"id": "b", "title": "საღამოს პოეზია"},
    ]
    dm = comment_service._build_ambiguous_adult_event_dm(candidates)
    assert "დილის პოეზია" in dm
    assert "საღამოს პოეზია" in dm
    assert "რომელი" in dm


# ---------------------------------------------------------------------------
# 7. inactive event exclusion
# ---------------------------------------------------------------------------


def test_inactive_event_never_selected_even_when_tag_matches(sections_path):
    _seed_events(sections_path, [
        {
            "id": "archived", "title": "ძველი საღამო",
            "status": "inactive", "min_age": 13,
            "tags": ["ძველი საღამო"],
        },
    ])
    event, candidates, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ძველი საღამო",
            post_id="", platform="facebook",
        ),
    )
    assert event is None
    assert candidates == []
    assert reason == "no_match"


def test_inactive_event_never_selected_by_facebook_post_id(sections_path):
    _seed_events(sections_path, [
        {
            "id": "archived", "title": "ძველი",
            "status": "inactive", "min_age": 13,
            "facebook_post_id": "fb_old_post",
        },
    ])
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ფასი?",
            post_id="fb_old_post", platform="facebook",
        ),
    )
    assert event is None
    assert reason == "no_match"


# ---------------------------------------------------------------------------
# 8. specific event DM content
# ---------------------------------------------------------------------------


def test_specific_event_dm_includes_all_fields(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "poetry", "title": "ქართული პოეზიის საღამო",
        "status": "active", "min_age": 13,
        "date_text": "25 ივნისი, 20:00",
        "location": "ამბასადორი კაჭრეთი",
        "price_text": "150 ლარი",
        "description": "ქართველი პოეტების საღამო",
        "reservation_url": "https://example.com/p",
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "ქართული პოეზიის საღამო" in dm
    assert "25 ივნისი, 20:00" in dm
    assert "ამბასადორი კაჭრეთი" in dm
    assert "150 ლარი" in dm
    assert "ქართველი პოეტების საღამო" in dm
    assert "https://example.com/p" in dm


def test_specific_event_dm_renders_numeric_price_as_gel(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "active", "min_age": 13,
        "price_text": "150",
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "150 ლარი" in dm


def test_specific_event_dm_uses_price_gel_when_price_text_blank(
    sections_path,
):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "active", "min_age": 13,
        "price_gel": 200,
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "200 ლარი" in dm


def test_specific_event_dm_skips_missing_fields(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "active", "min_age": 13,
        # no date, location, price, description, link
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "T" in dm
    # Missing fields not echoed as blank "თარიღი: " lines.
    assert "თარიღი:" not in dm
    assert "ლოკაცია:" not in dm
    assert "ფასი:" not in dm
    # And the missing-link manager-handoff line fires.
    assert "ბილეთის ბმული ამ ეტაპზე არ არის მითითებული" in dm
    assert "მენეჯერთან" in dm


# ---------------------------------------------------------------------------
# 9. missing link handoff
# ---------------------------------------------------------------------------


def test_missing_link_triggers_manager_handoff_line(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T",
        "status": "active", "min_age": 13,
        "date_text": "25 ივნისი",
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "ბილეთის ბმული ამ ეტაპზე არ არის მითითებული" in dm
    assert "მენეჯერთან" in dm


def test_payment_terms_url_used_as_link_fallback(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "active", "min_age": 13,
        # no reservation_url, but payment_terms holds a link
        "payment_terms": "https://example.com/pay",
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "https://example.com/pay" in dm


# ---------------------------------------------------------------------------
# 10. no sold-out hallucination
# ---------------------------------------------------------------------------


def test_dm_does_not_say_sold_out_for_active_event(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T",
        "status": "active", "min_age": 13,
        # No sold_out flag — must NEVER produce sold-out copy.
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "ამოწურულია" not in dm
    assert "აღარ არის" not in dm


def test_dm_says_sold_out_only_when_explicit_flag(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T",
        "status": "active", "min_age": 13,
        "sold_out": True,
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "ადგილები ამ ეტაპზე ამოწურულია" in dm


def test_dm_status_sold_out_shortcut(sections_path):
    """`status: sold_out` is the operator shortcut for the boolean flag."""
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "sold_out", "min_age": 13,
    })
    dm = comment_service._build_specific_adult_event_dm(event)
    assert "ადგილები ამ ეტაპზე ამოწურულია" in dm


# ---------------------------------------------------------------------------
# 11. camp comment broad interest phrases (PART 6)
# ---------------------------------------------------------------------------


def test_camp_short_price_question_routed_as_interest():
    """The broad-interest detector benefits #ბანაკი comments equally."""
    assert comment_service.is_interest_intent("ფასი?") is True
    assert comment_service.is_interest_intent("სად ტარდება?") is True
    assert comment_service.is_interest_intent("როდის არის?") is True
    assert comment_service.is_interest_intent("ბმული?") is True
    assert comment_service.is_interest_intent("ასაკი?") is True
    assert comment_service.is_interest_intent("პირობები?") is True
    assert comment_service.is_interest_intent("დეტალები") is True
    assert comment_service.is_interest_intent("მინდა") is True
    assert comment_service.is_interest_intent(
        "როგორ დავრეგისტრირდე?",
    ) is True


def test_unrelated_camp_comment_not_routed_as_interest():
    assert comment_service.is_interest_intent("ლამაზია!") is False


# ---------------------------------------------------------------------------
# 12. post caption fetch soft-fail
# ---------------------------------------------------------------------------


def test_caption_fetch_soft_fail_returns_no_match(sections_path, monkeypatch):
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია"],
        },
    ])

    async def failing_fetch(post_id: str, platform: str) -> str:
        # fetch_post_content soft-fails by returning "".
        return ""

    monkeypatch.setattr(comment_service, "fetch_post_content", failing_fetch)
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ფასი?",
            post_id="post_unreachable", platform="facebook",
        ),
    )
    assert event is None
    assert reason == "no_match"


def test_caption_fetch_exception_does_not_break_resolver(
    sections_path, monkeypatch,
):
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "T",
            "status": "active", "min_age": 13,
            "tags": ["x"],
        },
    ])

    async def raising_fetch(post_id: str, platform: str) -> str:
        raise RuntimeError("Meta is down")

    monkeypatch.setattr(comment_service, "fetch_post_content", raising_fetch)
    event, _, reason = _run(
        comment_service.resolve_specific_adult_event(
            comment_text="ფასი?",
            post_id="p1", platform="facebook",
        ),
    )
    assert event is None
    assert reason == "no_match"


# ---------------------------------------------------------------------------
# 13. no token logging
# ---------------------------------------------------------------------------


def test_fetch_post_content_does_not_log_access_token(
    monkeypatch, caplog,
):
    """Privacy-safe log invariant: the access token must NEVER appear
    in [COMMENT] log lines, even when Meta returns 4xx or the call
    raises."""
    swapped = _swap_settings(monkeypatch, META_ACCESS_TOKEN="SUPER_SECRET_123")

    class _FailingClient:
        def __call__(self, *a, **kw):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url, params=None):
            class _Resp:
                is_success = False
                status_code = 400
                text = "an error containing SUPER_SECRET_123"

                def json(self):
                    return {}

            return _Resp()

    monkeypatch.setattr(
        comment_service.httpx, "AsyncClient", _FailingClient(),
    )

    caplog.set_level("WARNING")
    _run(comment_service.fetch_post_content("p1", "facebook"))
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "SUPER_SECRET_123" not in log_text


def test_fetch_post_content_does_not_log_token_on_exception(
    monkeypatch, caplog,
):
    swapped = _swap_settings(monkeypatch, META_ACCESS_TOKEN="ANOTHER_SECRET")

    class _RaisingClient:
        def __call__(self, *a, **kw):
            return self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url, params=None):
            raise RuntimeError("connection failed with ANOTHER_SECRET visible")

    monkeypatch.setattr(
        comment_service.httpx, "AsyncClient", _RaisingClient(),
    )

    caplog.set_level("WARNING")
    _run(comment_service.fetch_post_content("p1", "facebook"))
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "ANOTHER_SECRET" not in log_text


# ---------------------------------------------------------------------------
# 14. End-to-end — send_dm_from_comment routes through specific event
# ---------------------------------------------------------------------------


def test_send_dm_from_comment_uses_specific_event_dm_when_tag_matches(
    sections_path, monkeypatch,
):
    """Integration: when a comment mentions an event tag, the DM sent
    to the user is the specific-event DM, not the generic catalogue."""
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "date_text": "25 ივნისი, 20:00",
            "location": "ამბასადორი კაჭრეთი",
            "price_text": "150",
            "reservation_url": "https://example.com/p",
            "tags": ["ქართული პოეზია"],
        },
    ])
    sent_messages: list[tuple[str, str]] = []

    def _fake_private_reply(comment_id: str, message: str) -> bool:
        sent_messages.append((comment_id, message))
        return True

    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _fake_private_reply,
    )

    async def fake_resolve_section(post_id, platform):
        # Force the section type to ADULT so the integration path
        # exercises the new specific-event branch.
        return {
            "id": "adult_events", "type": "adult_events",
            "status": "active",
            "auto_dm_template_id": "adult_events_comment_dm",
        }

    monkeypatch.setattr(
        comment_service, "resolve_section_from_post", fake_resolve_section,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_x", platform="facebook",
        post_id="post_p", segment="ADULT",
        comment_id="cm_1",
        comment_text="ქართული პოეზია მაინტერესებს",
    ))
    assert ok
    assert sent_messages, "send_private_reply was never called"
    _, body = sent_messages[0]
    assert "ქართული პოეზიის საღამო" in body
    assert "25 ივნისი, 20:00" in body
    assert "150 ლარი" in body
    assert "https://example.com/p" in body


def test_send_dm_falls_back_to_generic_when_no_specific_event(
    sections_path, monkeypatch,
):
    """Generic comment + no caption context → existing generic ADULT
    DM (no fabricated specific event)."""
    _seed_events(sections_path, [
        {
            "id": "poetry", "title": "ქართული პოეზიის საღამო",
            "status": "active", "min_age": 13,
            "tags": ["ქართული პოეზია"],
        },
    ])
    sent_messages: list[tuple[str, str]] = []

    def _fake_private_reply(comment_id: str, message: str) -> bool:
        sent_messages.append((comment_id, message))
        return True

    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _fake_private_reply,
    )

    async def fake_resolve_section(post_id, platform):
        return {
            "id": "adult_events", "type": "adult_events",
            "status": "active",
            "auto_dm_template_id": "adult_events_comment_dm",
        }

    monkeypatch.setattr(
        comment_service, "resolve_section_from_post", fake_resolve_section,
    )

    async def empty_caption(post_id, platform):
        return ""

    monkeypatch.setattr(comment_service, "fetch_post_content", empty_caption)

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_x", platform="facebook",
        post_id="post_p", segment="ADULT",
        comment_id="cm_1",
        comment_text="ფასი?",
    ))
    assert ok
    assert sent_messages
    _, body = sent_messages[0]
    # The generic builder does NOT include the specific event title or link.
    assert "https://example.com/p" not in body
    # Some generic text from `ADULT_NO_EVENTS_DM` or `_build_adult_rich_dm`
    # is present (we don't assert exact wording — only that we didn't
    # fabricate the specific event).
    assert body


def test_send_dm_emits_ambiguous_clarification(sections_path, monkeypatch):
    _seed_events(sections_path, [
        {
            "id": "a", "title": "დილის პოეზია",
            "status": "active", "min_age": 13,
            "tags": ["პოეზია"],
        },
        {
            "id": "b", "title": "საღამოს პოეზია",
            "status": "active", "min_age": 13,
            "tags": ["პოეზია"],
        },
    ])
    sent_messages: list[tuple[str, str]] = []

    def _fake_private_reply(comment_id, message):
        sent_messages.append((comment_id, message))
        return True

    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _fake_private_reply,
    )

    async def fake_resolve_section(post_id, platform):
        return {
            "id": "adult_events", "type": "adult_events",
            "status": "active",
            "auto_dm_template_id": "adult_events_comment_dm",
        }

    monkeypatch.setattr(
        comment_service, "resolve_section_from_post", fake_resolve_section,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_x", platform="facebook",
        post_id="post_p", segment="ADULT",
        comment_id="cm_1",
        comment_text="პოეზია",
    ))
    assert ok
    body = sent_messages[0][1]
    assert "დილის პოეზია" in body
    assert "საღამოს პოეზია" in body
    assert "რომელი" in body


# ---------------------------------------------------------------------------
# 15. Admin form helper-text label
# ---------------------------------------------------------------------------


def test_admin_event_form_template_has_tags_helper_text():
    """Operator-facing label text must be present in the event form."""
    from pathlib import Path

    template_text = Path("templates/admin/adult_event_form.html").read_text(
        encoding="utf-8",
    )
    assert "ქართული პოეზია" in template_text
    assert "ქართული_პოეზია" in template_text
    assert "კონკრეტული ღონისძიების" in template_text
