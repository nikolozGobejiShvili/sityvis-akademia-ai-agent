# -*- coding: utf-8 -*-
"""Comment → DM routing (2026-07-04) — additive section-level post_id mapping.

A comment under a Camp post ("ფასი რა არის?") used to get the generic
category-choice menu because segment routing only used caption hashtags, and if
the Meta caption fetch failed (or the caption had no literal „#" hashtag) the
segment collapsed to UNCLEAR.

This adds an ADDITIVE `post_id → section` mapping (`admin_config_service.
find_section_from_post_id`, canonical field `facebook_post_ids`) consulted BEFORE
the caption fetch, plus a comment-aware Camp DM (`comment_service.
_build_camp_comment_dm`) that answers price / dates / location / info and bridges
into the Camp flow with the approved child-age question — instead of the menu.

CRITICAL: the existing caption-hashtag routing and the Sunday-School / Adult
branches are UNCHANGED. Hashtag routing still works with NO post_id mapping.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import admin_config_service, comment_service, messenger_service

_CATEGORY = "რა გაინტერესებთ"  # substring of the UNCLEAR category-choice menu


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def mapped_sections(monkeypatch):
    """Inject section-level post_id mappings into the REAL sections so
    `find_section_from_post_id` resolves them via the real logic. Uses all three
    accepted field shapes to prove the aliases. Does NOT touch section hashtags."""
    real = admin_config_service.load_sections()

    def _mapped():
        out = []
        for s in real:
            s = dict(s)
            if s.get("id") == "summer_camp":
                s["facebook_post_ids"] = ["CAMP_POST_1"]      # canonical (list)
            elif s.get("id") == "sunday_school":
                s["facebook_post_id"] = "SS_POST_1"           # singular alias
            elif s.get("id") == "adult_events":
                s["post_ids"] = ["ADULT_POST_1"]              # post_ids alias
            out.append(s)
        return out

    monkeypatch.setattr(admin_config_service, "load_sections", _mapped)
    return {"camp": "CAMP_POST_1", "ss": "SS_POST_1", "adult": "ADULT_POST_1"}


@pytest.fixture
def caption(monkeypatch):
    """Control the fetched post caption (default empty = fetch failed / no tag)."""
    state = {"text": ""}

    async def _fake_fetch(post_id, platform):
        return state["text"]

    monkeypatch.setattr(comment_service, "fetch_post_content", _fake_fetch)
    return state


@pytest.fixture
def sent(monkeypatch):
    """Capture the outbound DM (private reply or send_message)."""
    box = {"msg": None}

    def _priv(comment_id, message):
        box["msg"] = message
        return True

    def _send(sender_id, platform, message):
        box["msg"] = message
        return True

    monkeypatch.setattr(messenger_service, "send_private_reply", _priv)
    monkeypatch.setattr(messenger_service, "send_message", _send)
    return box


def _dm(post_id, comment_text, segment=None, comment_id="c1"):
    return _run(comment_service.send_dm_from_comment(
        "user1", "facebook", post_id, segment,
        comment_id=comment_id, comment_text=comment_text,
    ))


# ── find_section_from_post_id unit (field aliases) ───────────────────────────
def test_find_section_from_post_id_field_aliases(mapped_sections):
    assert admin_config_service.find_section_from_post_id("CAMP_POST_1")["id"] == "summer_camp"
    assert admin_config_service.find_section_from_post_id("SS_POST_1")["id"] == "sunday_school"
    assert admin_config_service.find_section_from_post_id("ADULT_POST_1")["id"] == "adult_events"
    assert admin_config_service.find_section_from_post_id("NOPE") is None
    assert admin_config_service.find_section_from_post_id("") is None


# ── Camp mapped post ─────────────────────────────────────────────────────────
def test_1_camp_mapped_price(mapped_sections, caption, sent):
    caption["text"] = ""  # caption fetch irrelevant — routed by post_id
    assert _dm("CAMP_POST_1", "ფასი რა არის?", "PARENT")
    m = sent["msg"]
    assert "2150" in m
    assert "რამდენი წლის არის თქვენი შვილი?" in m
    assert _CATEGORY not in m


def test_2_camp_mapped_generic_info(mapped_sections, caption, sent):
    assert _dm("CAMP_POST_1", "მინდა ინფორმაცია", "PARENT")
    m = sent["msg"]
    assert "ციფრულ ხმაურს" in m                       # approved Camp intro
    assert "რამდენი წლის არის თქვენი შვილი?" in m
    assert _CATEGORY not in m


def test_3_camp_mapped_dates(mapped_sections, caption, sent, monkeypatch):
    # Fixed visible stream so the assertion is not a wall-clock date-bomb.
    monkeypatch.setattr(
        admin_config_service, "get_visible_camp_streams",
        lambda streams=None, **k: [{"name": "II ნაკადი", "dates_text": "5-11 ივლისი"}],
    )
    assert _dm("CAMP_POST_1", "როდის იწყება?", "PARENT")
    m = sent["msg"]
    assert "5-11 ივლისი" in m                          # real visible stream date
    assert _CATEGORY not in m


def test_3b_camp_mapped_dates_never_invents_when_all_hidden(mapped_sections, caption, sent, monkeypatch):
    monkeypatch.setattr(
        admin_config_service, "get_visible_camp_streams",
        lambda streams=None, **k: [],  # all streams started → none visible
    )
    assert _dm("CAMP_POST_1", "როდის იწყება?", "PARENT")
    m = sent["msg"]
    # No stream-date tokens are invented; still not the category menu.
    for token in ("23-29 ივნისი", "5-11 ივლისი", "14-20 ივლისი"):
        assert token not in m
    assert _CATEGORY not in m


def test_4_camp_mapped_location(mapped_sections, caption, sent):
    assert _dm("CAMP_POST_1", "სად არის?", "PARENT")
    m = sent["msg"]
    assert "კაჭრეთ" in m                               # camp location
    assert _CATEGORY not in m


def test_5_camp_mapped_caption_fetch_empty_still_routes(mapped_sections, caption, sent):
    caption["text"] = ""  # simulate Meta caption fetch failure
    # Route with segment=None so send_dm_from_comment resolves it via post_id.
    assert _run(comment_service.send_dm_from_comment(
        "user5", "facebook", "CAMP_POST_1", None,
        comment_id="c5", comment_text="ფასი რა არის?",
    ))
    m = sent["msg"]
    assert "2150" in m
    assert _CATEGORY not in m


# ── Existing hashtag routing regression (NO post_id mapping) ──────────────────
def test_6_hashtag_camp_price_no_post_id_map(caption, sent):
    caption["text"] = "ბანაკის რეგისტრაცია #ბანაკი"
    assert _dm("H1", "ფასი რა არის?")   # segment=None → resolved via caption
    m = sent["msg"]
    assert "2150" in m
    assert _CATEGORY not in m


def test_7_hashtag_camp_info_no_post_id_map(caption, sent):
    caption["text"] = "camp info #camp"
    assert _dm("H2", "მინდა ინფორმაცია")
    m = sent["msg"]
    assert "ციფრულ ხმაურს" in m
    assert _CATEGORY not in m


def test_hashtag_segment_routing_unchanged(caption):
    caption["text"] = "ბანაკი #ბანაკი"
    assert _run(comment_service.determine_segment_from_post("h", "facebook")) == "PARENT"
    caption["text"] = "საკვირაო სკოლა #საკვირაოსკოლა"
    assert _run(comment_service.resolve_section_from_post("h", "facebook"))["id"] == "sunday_school"
    caption["text"] = "კულტურული საღამო #საღამო"
    assert _run(comment_service.determine_segment_from_post("h", "facebook")) == "ADULT"


# ── Unmapped post regression ─────────────────────────────────────────────────
def test_8_unmapped_empty_caption_category_remains(caption, sent):
    caption["text"] = ""  # no post_id map, no caption hashtag
    assert _dm("UNMAPPED", "ფასი რა არის?", None, comment_id=None)
    assert _CATEGORY in sent["msg"]


# ── Sunday School safety ─────────────────────────────────────────────────────
def test_9_ss_mapped_no_camp_content(mapped_sections, caption, sent):
    assert _dm("SS_POST_1", "ფასი რა არის?", "PARENT")
    m = sent["msg"]
    assert "საკვირაო" in m
    assert "2150" not in m
    assert "ციფრულ ხმაურს" not in m                    # not the camp intro
    assert "tinyurl" not in m.lower()                  # not the camp registration link


# ── Adult routing safety ─────────────────────────────────────────────────────
def test_11_adult_mapped_no_camp_content(mapped_sections, caption, sent):
    assert _dm("ADULT_POST_1", "ფასი რა არის?", "ADULT")
    m = sent["msg"]
    assert "2150" not in m
    assert "ციფრულ ხმაურს" not in m


def test_12_specific_adult_event_keeps_priority(mapped_sections, caption, sent, monkeypatch):
    # A specific adult event (event-level facebook_post_id, Priority A) must win
    # over the generic section-level adult_events mapping.
    fake_event = {"id": "ev1", "title": "სპეციფიკური ღონისძიება"}

    async def _fake_specific(comment_text, post_id, platform):
        return (fake_event, [], "facebook_post_id")

    monkeypatch.setattr(comment_service, "resolve_specific_adult_event", _fake_specific)
    monkeypatch.setattr(
        comment_service, "_build_specific_adult_event_dm",
        lambda ev: "SPECIFIC_EVENT_DM_SENTINEL",
    )
    assert _dm("ADULT_POST_1", "ინფო", "ADULT")
    assert sent["msg"] == "SPECIFIC_EVENT_DM_SENTINEL"  # specific event, not generic list
