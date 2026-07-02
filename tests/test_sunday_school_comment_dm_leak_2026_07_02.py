"""Sunday School comment DM must NOT leak the Summer Camp DM (2026-07-02).

Scoped fix: a comment on a Sunday-School post (`type=kids_program`) previously
fell into the shared camp/kids_program branch of `send_dm_from_comment` and sent
the Summer-Camp rich DM (`_build_parent_rich_dm`, hardcoded summer_camp — price
2150 + camp registration link + stream dates). It must now send Sunday-School-
specific, status-aware wording with NO camp content. Camp + Adult comment paths
must be unaffected.

Live mode: engine ON / planner OFF (the comment path never invokes the LLM).
All external I/O (Meta send, post fetch) is mocked — nothing hits the network.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import (
    admin_config_service,
    comment_service,
    conversation_service,
    messenger_service,
)

CAMP_PRICE = "2150"
CAMP_LINK = "36jcae8z"
SS_COMING_SOON = "საკვირაო სკოლის დეტალები ჯერ ზუსტდება"
CAMP_STREAM_DATES = ("23-29 ივნისი", "5-11 ივლისი", "14-20 ივლისი")

_SS_SECTION = {
    "id": "sunday_school",
    "name": "საკვირაო სკოლა",
    "type": "kids_program",
    "status": "coming_soon",
    "lead_type": "sunday_school",
    "auto_dm_template_id": "sunday_school_comment_dm",
    "description_short": "საკვირაო სკოლა ბავშვებისთვის.",
    "price_text": "",
    "schedule_text": "",
    "location": "",
    "registration_url": "",
}
_CAMP_SECTION = {
    "id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
    "status": "active", "auto_dm_template_id": "summer_camp_comment_dm",
}
_ADULT_SECTION = {
    "id": "adult_events", "name": "ზრდასრულთა ღონისძიებები", "type": "adult_events",
    "status": "active", "auto_dm_template_id": "adult_events_comment_dm",
}


def _set_ss_status(monkeypatch, status):
    monkeypatch.setattr(
        admin_config_service, "get_sunday_school_status",
        lambda: {
            "status": status, "availability_text": "", "details_text": "",
            "handoff_enabled": True, "lead_type": "sunday_school",
        },
    )


def _patch_send(monkeypatch):
    sent: dict = {}

    def _send_message(sender_id, platform, text):
        sent["text"] = text
        sent["channel"] = "send_message"
        return True

    def _send_private_reply(comment_id, text):
        sent["text"] = text
        sent["channel"] = "private_reply"
        return True

    monkeypatch.setattr(messenger_service, "send_message", _send_message)
    monkeypatch.setattr(messenger_service, "send_private_reply", _send_private_reply)
    return sent


def _patch_section(monkeypatch, section):
    async def _resolve(post_id, platform):
        return section
    monkeypatch.setattr(comment_service, "resolve_section_from_post", _resolve)


def _patch_adult_resolver(monkeypatch):
    # Keep the ADULT specific-event resolver offline (no Meta post fetch).
    async def _no_specific(comment_text, post_id, platform):
        return (None, [], "no_match")
    monkeypatch.setattr(comment_service, "resolve_specific_adult_event", _no_specific)


def _run_comment(monkeypatch, section, *, segment, status=None, sid="c_ss_leak"):
    if status is not None:
        _set_ss_status(monkeypatch, status)
    _patch_section(monkeypatch, section)
    _patch_adult_resolver(monkeypatch)
    sent = _patch_send(monkeypatch)
    conversation_service.conversations.pop(sid, None)
    ok = asyncio.run(comment_service.send_dm_from_comment(
        sid, "instagram", "post123", segment=segment,
        comment_id=None, comment_text="ინფორმაცია მინდა",
    ))
    return ok, sent.get("text", "")


# ── Direct builder tests (status-aware, no async) ───────────────────────────
@pytest.mark.parametrize(
    "status", ["coming_soon", "hidden", "ended", "full", "active", "weird_value"],
)
def test_ss_comment_dm_never_contains_camp(monkeypatch, status):
    _set_ss_status(monkeypatch, status)
    out = comment_service._build_sunday_school_comment_dm(_SS_SECTION)
    assert CAMP_PRICE not in out
    assert CAMP_LINK not in out
    assert "ბანაკი" not in out
    assert "ბანაკის" not in out
    assert out.strip()  # never empty → fallback never reaches camp DM


def test_is_sunday_school_section_detection():
    assert comment_service._is_sunday_school_section(_SS_SECTION) is True
    assert comment_service._is_sunday_school_section(_CAMP_SECTION) is False
    assert comment_service._is_sunday_school_section(_ADULT_SECTION) is False
    assert comment_service._is_sunday_school_section(None) is False


def test_ss_active_uses_only_populated_fields_no_empty_labels(monkeypatch):
    _set_ss_status(monkeypatch, "active")
    out = comment_service._build_sunday_school_comment_dm(_SS_SECTION)
    assert "საკვირაო სკოლა ბავშვებისთვის." in out   # populated description used
    assert "ფასი:" not in out                        # empty fields → no blank labels
    assert "გრაფიკი:" not in out
    assert "ლოკაცია:" not in out
    assert CAMP_PRICE not in out


# ── End-to-end send_dm_from_comment tests ───────────────────────────────────
def test_1_ss_coming_soon_no_camp_price(monkeypatch):
    ok, text = _run_comment(monkeypatch, _SS_SECTION, segment="PARENT", status="coming_soon")
    assert ok is True
    assert CAMP_PRICE not in text


def test_2_ss_coming_soon_no_camp_link(monkeypatch):
    ok, text = _run_comment(monkeypatch, _SS_SECTION, segment="PARENT", status="coming_soon")
    assert CAMP_LINK not in text


def test_3_ss_coming_soon_no_camp_streams(monkeypatch):
    ok, text = _run_comment(monkeypatch, _SS_SECTION, segment="PARENT", status="coming_soon")
    for d in CAMP_STREAM_DATES:
        assert d not in text


def test_4_ss_coming_soon_contains_expected_wording(monkeypatch):
    ok, text = _run_comment(monkeypatch, _SS_SECTION, segment="PARENT", status="coming_soon")
    assert SS_COMING_SOON in text
    assert "მენეჯერთან დაგაკავშირებთ" in text


def test_5_ss_hidden_and_ended_no_camp_dm(monkeypatch):
    for st in ("hidden", "ended"):
        ok, text = _run_comment(monkeypatch, _SS_SECTION, segment="PARENT", status=st)
        assert ok is True
        assert CAMP_PRICE not in text
        assert CAMP_LINK not in text
        assert "აქტიური არ არის" in text


def test_6_ss_full_no_camp_dm(monkeypatch):
    ok, text = _run_comment(monkeypatch, _SS_SECTION, segment="PARENT", status="full")
    assert ok is True
    assert CAMP_PRICE not in text
    assert "შევსებულია" in text


def test_7_camp_comment_still_sends_camp_dm(monkeypatch):
    # Camp section (type=camp) must STILL render the Summer-Camp rich DM (2150).
    ok, text = _run_comment(monkeypatch, _CAMP_SECTION, segment="PARENT")
    assert ok is True
    assert CAMP_PRICE in text
    assert SS_COMING_SOON not in text


def test_8_adult_comment_not_impacted(monkeypatch):
    ok, text = _run_comment(monkeypatch, _ADULT_SECTION, segment="ADULT")
    assert ok is True
    assert SS_COMING_SOON not in text
    assert text.strip()  # adult path still produces a DM
