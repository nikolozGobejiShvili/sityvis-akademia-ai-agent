"""Generic Adult Event Comment → Active Events List Patch (2026-06-09).

Live-bug: when a comment lands on a post tagged ONLY with the generic
adult-event hashtag (`#event`, `#ღონისძიება`, …) and no specific event
matches via Priority A (facebook_post_id) / B (tag in comment) /
C (tag in caption), the previous code path emitted the legacy
„ახლო მომავალში ღონისძიებების განრიგს გამოვაქვეყნებთ…" copy via
``_build_adult_rich_dm()`` even when ``adult_events.events[]`` had
active events.

This module exercises the new ``_build_active_adult_events_list_dm``
helper + the routing change in ``send_dm_from_comment`` that prefers
the active-events list over the legacy fallback whenever active events
exist. Includes integration tests for the Instagram + Facebook paths,
priority regressions (specific tag still wins over generic list), and
``{events_list}`` placeholder substitution invariants.
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


@pytest.fixture
def templates_path(monkeypatch, tmp_path):
    """Point the admin template loader at a temp file so each test can
    assert template-rendering behaviour in isolation."""
    path = tmp_path / "templates.yaml"
    monkeypatch.setattr(admin_config_service, "TEMPLATES_PATH", path)
    return path


def _seed_section(
    path,
    events: list[dict],
    *,
    section_status: str = "active",
) -> None:
    body = yaml.safe_dump(
        {"sections": [
            {
                "id": "adult_events",
                "name": "ზრდასრულთა ღონისძიებები",
                "type": "adult_events",
                "status": section_status,
                "hashtags": ["event", "ღონისძიება"],
                "age_min": 13,
                "auto_dm_template_id": "adult_events_comment_dm",
                "events": events,
            },
        ]},
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    path.write_text(body, encoding="utf-8")


def _seed_templates(path, **templates) -> None:
    body = yaml.safe_dump(
        {"templates": templates},
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    path.write_text(body, encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_post_cache():
    comment_service.post_content_cache.clear()
    yield
    comment_service.post_content_cache.clear()


@pytest.fixture(autouse=True)
def _reset_conversations():
    from app.services import conversation_service
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


def _run(coro):
    return asyncio.run(coro)


def _fake_section_adult():
    async def _impl(post_id, platform):
        return {
            "id": "adult_events", "type": "adult_events",
            "status": "active",
            "auto_dm_template_id": "adult_events_comment_dm",
        }
    return _impl


def _capture_private_reply():
    sent: list[tuple[str, str]] = []

    def _send(comment_id: str, message: str) -> bool:
        sent.append((comment_id, message))
        return True

    return sent, _send


# ---------------------------------------------------------------------------
# PART 1 — list-builder unit tests
# ---------------------------------------------------------------------------


def test_active_events_list_dm_includes_title_date_location_price_link(
    sections_path,
):
    _seed_section(sections_path, [
        {
            "id": "summer_fest", "title": "summer fest",
            "status": "active", "min_age": 13,
            "date_text": "28 აგვისტო 19:00",
            "location": "ლისი",
            "price_text": "100",
            "reservation_url": "https://example.com/sf",
        },
    ])
    dm = comment_service._build_active_adult_events_list_dm()
    assert dm
    assert "summer fest" in dm
    assert "28 აგვისტო 19:00" in dm
    assert "ლისი" in dm
    assert "100 ლარი" in dm
    assert "https://example.com/sf" in dm


def test_active_events_list_dm_returns_empty_when_no_active_events(
    sections_path,
):
    _seed_section(sections_path, [])
    assert comment_service._build_active_adult_events_list_dm() == ""


def test_active_events_list_dm_skips_missing_fields(sections_path):
    _seed_section(sections_path, [
        {
            "id": "minimal", "title": "მინიმალური",
            "status": "active", "min_age": 13,
            # no date, location, price, link
        },
    ])
    dm = comment_service._build_active_adult_events_list_dm()
    assert dm
    assert "მინიმალური" in dm
    # Skipped fields must NOT appear as empty "თარიღი:" labels.
    assert "თარიღი:" not in dm
    assert "ლოკაცია:" not in dm
    assert "ფასი:" not in dm
    assert "ბილეთის ბმული:" not in dm


def test_active_events_list_dm_inactive_events_excluded(sections_path):
    # NOTE: this test targets INACTIVE exclusion. Use a dateless active
    # event so the new past-date filter (2026-06-10) does not also hide
    # it — date filtering has its own dedicated suite
    # (test_adult_event_past_filtering.py).
    _seed_section(sections_path, [
        {
            "id": "active_one", "title": "active event",
            "status": "active", "min_age": 13,
        },
        {
            "id": "old", "title": "archived event",
            "status": "inactive", "min_age": 13,
            "date_text": "01 იანვარი 2020",
        },
    ])
    dm = comment_service._build_active_adult_events_list_dm()
    assert "active event" in dm
    assert "archived event" not in dm


def test_active_events_list_dm_numeric_price_text_rendered_as_gel(
    sections_path,
):
    _seed_section(sections_path, [
        {
            "id": "p", "title": "T",
            "status": "active", "min_age": 13,
            "price_text": "150",
        },
    ])
    dm = comment_service._build_active_adult_events_list_dm()
    assert "150 ლარი" in dm


def test_active_events_list_dm_uses_price_gel_when_price_text_blank(
    sections_path,
):
    _seed_section(sections_path, [
        {
            "id": "p", "title": "T",
            "status": "active", "min_age": 13,
            "price_gel": 200,
        },
    ])
    dm = comment_service._build_active_adult_events_list_dm()
    assert "200 ლარი" in dm


def test_active_events_list_dm_uses_payment_terms_when_reservation_url_blank(
    sections_path,
):
    _seed_section(sections_path, [
        {
            "id": "p", "title": "T",
            "status": "active", "min_age": 13,
            "payment_terms": "https://example.com/pay-here",
        },
    ])
    dm = comment_service._build_active_adult_events_list_dm()
    assert "https://example.com/pay-here" in dm


def test_active_events_list_dm_does_not_invent_schedule(sections_path):
    """No fabricated fields — only operator data shows up."""
    _seed_section(sections_path, [
        {
            "id": "p", "title": "ბუნდოვანი ღონისძიება",
            "status": "active", "min_age": 13,
        },
    ])
    dm = comment_service._build_active_adult_events_list_dm()
    assert "ბუნდოვანი ღონისძიება" in dm
    # No invented date / location / price strings.
    assert "მითითებული არ" not in dm
    assert "ახლო მომავალში" not in dm


# ---------------------------------------------------------------------------
# PART 2 — {events_list} placeholder substitution
# ---------------------------------------------------------------------------


def test_template_events_list_placeholder_replaced(
    sections_path, templates_path,
):
    _seed_section(sections_path, [
        {
            "id": "p", "title": "ჩემი ღონისძიება",
            "status": "active", "min_age": 13,
        },
    ])
    _seed_templates(
        templates_path,
        adult_events_comment_dm=(
            "გამარჯობა. ღონისძიებები:\n\n"
            "{events_list}\n\n"
            "სხვა კითხვა?"
        ),
    )
    dm = comment_service._build_active_adult_events_list_dm()
    # Header from template preserved.
    assert "გამარჯობა. ღონისძიებები" in dm
    # Footer from template preserved.
    assert "სხვა კითხვა?" in dm
    # Event title from list block substituted into placeholder.
    assert "ჩემი ღონისძიება" in dm
    # Raw placeholder MUST NOT survive into the user-facing DM.
    assert "{events_list}" not in dm


def test_template_without_placeholder_still_renders_with_fallback_frame(
    sections_path, templates_path,
):
    """If the operator removed `{events_list}` from the template, the
    rendered output still doesn't surface event details — fall back to
    the hard-coded frame so the user receives the catalogue."""
    _seed_section(sections_path, [
        {
            "id": "p", "title": "T",
            "status": "active", "min_age": 13,
        },
    ])
    _seed_templates(
        templates_path,
        adult_events_comment_dm="static text without placeholder",
    )
    dm = comment_service._build_active_adult_events_list_dm()
    # Event title must still appear (via the safety-net frame).
    assert "T" in dm


def test_template_missing_falls_back_to_hardcoded_frame(
    sections_path, templates_path,
):
    """When `adult_events_comment_dm` is absent from templates.yaml,
    the helper still renders an active-events list via the fallback
    frame instead of returning empty."""
    _seed_section(sections_path, [
        {
            "id": "p", "title": "fallback test",
            "status": "active", "min_age": 13,
        },
    ])
    # NB: templates_path is created empty → loader returns {}.
    _seed_templates(templates_path, other_template="ignored")
    dm = comment_service._build_active_adult_events_list_dm()
    assert dm
    assert "fallback test" in dm
    assert "{events_list}" not in dm


def test_raw_events_list_placeholder_never_appears_in_dm(
    sections_path, templates_path,
):
    """End-to-end invariant: under no template configuration may the
    literal `{events_list}` string survive into the outbound DM."""
    _seed_section(sections_path, [
        {
            "id": "p", "title": "T",
            "status": "active", "min_age": 13,
        },
    ])
    for tpl in (
        "{events_list}",
        "header\n\n{events_list}\n\nfooter",
        "{{events_list}}",
        "broken {events_list",
    ):
        _seed_templates(templates_path, adult_events_comment_dm=tpl)
        dm = comment_service._build_active_adult_events_list_dm()
        assert dm
        assert "{events_list}" not in dm


# ---------------------------------------------------------------------------
# PART 3 — send_dm_from_comment routes generic #event through the list
# ---------------------------------------------------------------------------


def test_generic_event_comment_with_active_events_sends_list(
    sections_path, monkeypatch,
):
    """Live-bug regression. Generic #event on a comment with broad
    interest and no specific tag match must send the active-events
    list, NOT the „ახლო მომავალში…" fallback."""
    _seed_section(sections_path, [
        {
            "id": "summer_fest", "title": "summer fest",
            "status": "active", "min_age": 13,
            "date_text": "28 აგვისტო 19:00",
            "location": "ლისი",
            "price_text": "100",
            "reservation_url": "https://example.com/sf",
        },
    ])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    async def _empty_caption(post_id, platform):
        return "#event"

    monkeypatch.setattr(
        comment_service, "fetch_post_content", _empty_caption,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_x", platform="facebook",
        post_id="post_p", segment="ADULT",
        comment_id="cm_1",
        comment_text="ფასი?",
    ))
    assert ok
    body = sent[0][1]
    assert "summer fest" in body
    assert "28 აგვისტო 19:00" in body
    assert "ლისი" in body
    assert "100 ლარი" in body
    assert "https://example.com/sf" in body
    # Critical negative assertion: the misleading no-schedule fallback
    # MUST NOT appear when active events exist.
    assert "ახლო მომავალში" not in body


def test_generic_event_comment_with_no_active_events_sends_fallback(
    sections_path, monkeypatch,
):
    """Operator deactivated everything → fallback/no-schedule copy is
    the correct response. This protects against accidentally promising
    events that no longer exist."""
    _seed_section(sections_path, [
        {
            "id": "old", "title": "archived",
            "status": "inactive", "min_age": 13,
        },
    ], section_status="active")
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    async def _empty_caption(post_id, platform):
        return "#event"

    monkeypatch.setattr(
        comment_service, "fetch_post_content", _empty_caption,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_y", platform="facebook",
        post_id="post_p", segment="ADULT",
        comment_id="cm_2",
        comment_text="მაინტერესებს",
    ))
    assert ok
    body = sent[0][1]
    # No fabricated event title from an inactive event.
    assert "archived" not in body
    # The fallback copy is permitted in this branch.
    assert (
        "ახლო მომავალში" in body
        or "ღონისძიებებით" in body
    )


def test_generic_event_comment_does_not_invent_schedule(
    sections_path, monkeypatch,
):
    """The DM body must NOT promise upcoming events when no active
    events exist in admin config."""
    _seed_section(sections_path, [])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    async def _empty_caption(post_id, platform):
        return "#event"

    monkeypatch.setattr(
        comment_service, "fetch_post_content", _empty_caption,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_z", platform="facebook",
        post_id="post_p", segment="ADULT",
        comment_id="cm_3",
        comment_text="ფასი?",
    ))
    assert ok
    body = sent[0][1]
    # No specific event titles fabricated.
    assert "summer fest" not in body


# ---------------------------------------------------------------------------
# PART 4 — Specific event tag still wins over generic list
# ---------------------------------------------------------------------------


def test_specific_event_tag_still_overrides_generic_list(
    sections_path, monkeypatch,
):
    """Priority B (event tag in comment) MUST stay above the new
    generic-list path. `#event #fast` → exact „fast"-tagged event,
    not the full catalogue."""
    _seed_section(sections_path, [
        {
            "id": "fast", "title": "summer fest",
            "status": "active", "min_age": 13,
            "date_text": "28 აგვისტო 19:00",
            "location": "ლისი",
            "price_text": "100",
            "tags": ["fast"],
            "reservation_url": "https://example.com/sf",
        },
        {
            "id": "other", "title": "სხვა ღონისძიება",
            "status": "active", "min_age": 13,
            "date_text": "10 სექტემბერი",
            "location": "თბილისი",
            "price_text": "50",
        },
    ])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_a", platform="facebook",
        post_id="post_p", segment="ADULT",
        comment_id="cm_a",
        # The comment text mentions the specific tag.
        comment_text="ფასი? #fast",
    ))
    assert ok
    body = sent[0][1]
    # Specific event details surface…
    assert "summer fest" in body
    assert "28 აგვისტო 19:00" in body
    # …and the OTHER event is NOT listed (proves priority).
    assert "სხვა ღონისძიება" not in body


def test_specific_event_via_facebook_post_id_still_overrides_generic_list(
    sections_path, monkeypatch,
):
    """Priority A (facebook_post_id) still wins over generic list."""
    _seed_section(sections_path, [
        {
            "id": "fast", "title": "summer fest",
            "status": "active", "min_age": 13,
            "facebook_post_id": "fb_post_999",
            "reservation_url": "https://example.com/sf",
        },
        {
            "id": "other", "title": "სხვა ღონისძიება",
            "status": "active", "min_age": 13,
        },
    ])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_b", platform="facebook",
        post_id="fb_post_999", segment="ADULT",
        comment_id="cm_b",
        comment_text="ფასი?",
    ))
    assert ok
    body = sent[0][1]
    assert "summer fest" in body
    assert "სხვა ღონისძიება" not in body


def test_specific_event_via_caption_tag_still_overrides_generic_list(
    sections_path, monkeypatch,
):
    """Priority C (event tag in post caption) still wins."""
    _seed_section(sections_path, [
        {
            "id": "fast", "title": "summer fest",
            "status": "active", "min_age": 13,
            "tags": ["fast"],
            "reservation_url": "https://example.com/sf",
        },
        {
            "id": "other", "title": "სხვა ღონისძიება",
            "status": "active", "min_age": 13,
        },
    ])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    async def _caption_with_fast(post_id, platform):
        return "#event #fast"

    monkeypatch.setattr(
        comment_service, "fetch_post_content", _caption_with_fast,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="user_c", platform="facebook",
        post_id="post_x", segment="ADULT",
        comment_id="cm_c",
        # Generic interest comment — caption tag does the work.
        comment_text="ფასი?",
    ))
    assert ok
    body = sent[0][1]
    assert "summer fest" in body
    assert "სხვა ღონისძიება" not in body


# ---------------------------------------------------------------------------
# PART 5 — Instagram + Facebook platform parity
# ---------------------------------------------------------------------------


def test_generic_event_works_for_instagram_platform(
    sections_path, monkeypatch,
):
    _seed_section(sections_path, [
        {
            "id": "summer_fest", "title": "summer fest",
            "status": "active", "min_age": 13,
            "date_text": "28 აგვისტო 19:00",
            "location": "ლისი",
            "price_text": "100",
            "reservation_url": "https://example.com/sf",
        },
    ])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    async def _empty_caption(post_id, platform):
        return "#event"

    monkeypatch.setattr(
        comment_service, "fetch_post_content", _empty_caption,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="ig_user", platform="instagram",
        post_id="ig_post_p", segment="ADULT",
        comment_id="ig_cm",
        comment_text="ფასი?",
    ))
    assert ok
    body = sent[0][1]
    assert "summer fest" in body
    assert "ახლო მომავალში" not in body


def test_generic_event_works_for_facebook_platform(
    sections_path, monkeypatch,
):
    _seed_section(sections_path, [
        {
            "id": "summer_fest", "title": "summer fest",
            "status": "active", "min_age": 13,
            "price_text": "100",
        },
    ])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )
    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        _fake_section_adult(),
    )

    async def _empty_caption(post_id, platform):
        return "#event"

    monkeypatch.setattr(
        comment_service, "fetch_post_content", _empty_caption,
    )

    ok = _run(comment_service.send_dm_from_comment(
        sender_id="fb_user", platform="facebook",
        post_id="fb_post_p", segment="ADULT",
        comment_id="fb_cm",
        comment_text="სად ტარდება?",
    ))
    assert ok
    body = sent[0][1]
    assert "summer fest" in body


# ---------------------------------------------------------------------------
# PART 6 — Camp routing is untouched
# ---------------------------------------------------------------------------


def test_camp_segment_routing_still_uses_parent_rich_dm(
    sections_path, monkeypatch,
):
    """#ბანაკი / #camp paths route through `_build_parent_rich_dm` —
    the new active-adult-events list path must NOT interfere."""
    _seed_section(sections_path, [
        {
            "id": "summer_fest", "title": "summer fest",
            "status": "active", "min_age": 13,
            "price_text": "100",
        },
    ])
    sent, _send = _capture_private_reply()
    monkeypatch.setattr(
        comment_service.messenger_service,
        "send_private_reply", _send,
    )

    async def fake_section_camp(post_id, platform):
        return {
            "id": "summer_camp", "type": "camp",
            "status": "active",
            "auto_dm_template_id": "summer_camp_comment_dm",
        }

    monkeypatch.setattr(
        comment_service, "resolve_section_from_post", fake_section_camp,
    )

    # Provide a stub parent rich DM so we don't depend on the
    # canonical camp_2026.yaml fixture in this test.
    monkeypatch.setattr(
        comment_service, "_build_parent_rich_dm",
        lambda: "PARENT RICH DM STUB",
    )

    # A bare interest comment exercises the default first-contact path (the
    # rich DM); price/date/location/info comments are covered by the comment-
    # aware tests in test_comment_post_id_section_mapping_2026_07_04.py. This
    # test only asserts camp SEGMENT routing (camp DM, never the adult list).
    ok = _run(comment_service.send_dm_from_comment(
        sender_id="camp_user", platform="facebook",
        post_id="post_camp", segment="PARENT",
        comment_id="cm_camp",
        comment_text="მაინტერესებს",
    ))
    assert ok
    body = sent[0][1]
    assert "PARENT RICH DM STUB" in body
    # Adult-event title MUST NOT leak into the camp DM.
    assert "summer fest" not in body


# ---------------------------------------------------------------------------
# PART 7 — Interest intent detection still routes generic #event
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "ფასი?",
    "სად ტარდება?",
    "მაინტერესებს",
    "ბმული?",
])
def test_interest_intent_phrases_still_match(text):
    """The deterministic broad-interest detector must still classify
    the four live-bug example phrases as INTERESTED."""
    assert comment_service.is_interest_intent(text) is True
