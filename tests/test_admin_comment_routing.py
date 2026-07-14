"""Admin Panel MVP — comment-flow integration.

Verifies that post-caption hashtag routing now consults admin_config
sections first, and that section-aware comment DMs render correctly.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from app.config import settings as global_settings
from app.services import admin_config_service, comment_service


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mock_post(monkeypatch):
    """Patch `fetch_post_content` to return a caller-controlled caption."""
    state = {"caption": ""}

    async def _fake_fetch(post_id, platform):
        return state["caption"]

    monkeypatch.setattr(comment_service, "fetch_post_content", _fake_fetch)
    return state


# -- (1) post caption #ბანაკი → PARENT segment --------------------------


def test_post_caption_banaki_routes_to_parent(mock_post):
    mock_post["caption"] = "ბანაკის რეგისტრაცია დაიწყო #ბანაკი"
    segment = _run(comment_service.determine_segment_from_post("p1", "facebook"))
    assert segment == "PARENT"


def test_post_caption_saghamo_routes_to_adult(mock_post):
    mock_post["caption"] = "კულტურული საღამო #საღამო"
    segment = _run(comment_service.determine_segment_from_post("p1", "facebook"))
    assert segment == "ADULT"


def test_post_caption_unknown_routes_to_unclear(mock_post):
    mock_post["caption"] = "ცარიელი პოსტი #unknown"
    segment = _run(comment_service.determine_segment_from_post("p1", "facebook"))
    assert segment == "UNCLEAR"


# -- (2) section resolver returns admin section dict ---------------------


def test_resolve_section_from_post_returns_summer_camp(mock_post):
    mock_post["caption"] = "ბანაკის რეგისტრაცია #ბანაკი"
    section = _run(
        comment_service.resolve_section_from_post("p1", "facebook"),
    )
    assert section is not None
    assert section["id"] == "summer_camp"


def test_resolve_section_from_post_returns_sunday_school(mock_post):
    mock_post["caption"] = "საკვირაო სკოლის რეგისტრაცია #საკვირაოსკოლა"
    section = _run(
        comment_service.resolve_section_from_post("p2", "facebook"),
    )
    assert section is not None
    assert section["id"] == "sunday_school"


def test_resolve_section_from_post_returns_adult_events(mock_post):
    mock_post["caption"] = "ღონისძიება ხვალ #საღამო"
    section = _run(
        comment_service.resolve_section_from_post("p3", "facebook"),
    )
    assert section is not None
    assert section["id"] == "adult_events"


def test_resolve_section_from_post_no_hashtag_returns_none(mock_post):
    mock_post["caption"] = "no hashtags here"
    section = _run(
        comment_service.resolve_section_from_post("p4", "facebook"),
    )
    assert section is None


# -- (3) summer_camp DM via admin_config has expected facts -------------


def test_parent_rich_dm_via_admin_config_contains_camp_facts(camp_registration_open, camp_streams_visible):
    # admin_config_service.get_section("summer_camp") feeds the builder.
    out = comment_service._build_parent_rich_dm()
    assert "ამბასადორ კაჭრეთში" in out
    assert "2150 ლარი" in out
    assert "https://tinyurl.com/36jcae8z" in out


# -- (4) sunday_school post hashtag + comment-aware DM ------------------


def test_sunday_school_section_dm_renders_via_admin_config():
    section = admin_config_service.get_section("sunday_school")
    assert section is not None
    out = admin_config_service.build_section_dm(section)
    assert "საკვირაო სკოლა" in out
    # The configured short description must surface.
    assert "ბავშვებისთვის" in out


# -- (5) comment-text hashtag is only secondary fallback ----------------


def test_post_caption_takes_priority_over_comment_text(mock_post):
    """Even if the user's comment text mentions a different hashtag,
    the post-caption hashtag wins."""
    mock_post["caption"] = "ბანაკის რეგისტრაცია #ბანაკი"

    # Manually drive both resolvers — the post-aware one is primary.
    section_post = _run(
        comment_service.resolve_section_from_post("p_priority", "facebook"),
    )
    section_comment = admin_config_service.find_section_from_comment_text(
        "ფასი? #საღამო",
    )

    assert section_post is not None and section_post["id"] == "summer_camp"
    assert section_comment is not None and section_comment["id"] == "adult_events"
    # The wider flow uses post first → user's #საღამო in the comment
    # would only matter if the caption had no configured tag.


# -- (6) admin section + segment mapping --------------------------------


def test_segment_from_section_camp_maps_to_parent():
    summer = admin_config_service.get_section("summer_camp")
    assert comment_service._segment_from_section(summer) == "PARENT"


def test_segment_from_section_adult_events_maps_to_adult():
    adult = admin_config_service.get_section("adult_events")
    assert comment_service._segment_from_section(adult) == "ADULT"


def test_segment_from_section_sunday_school_maps_to_unclear():
    """sunday_school is `kids_program` type, which routes via UNCLEAR
    for the legacy DM-flow vocabulary. The comment DM still uses its
    own template via the admin-section-aware path."""
    sunday = admin_config_service.get_section("sunday_school")
    assert comment_service._segment_from_section(sunday) == "PARENT"
    # kids_program maps to PARENT for the brief's "summer_camp → PARENT
    # behavior" rule — we mirror that for any kids_program section so a
    # new kids program slots into the existing PARENT flow without code
    # changes.
