"""A hashtag comment must answer with THAT program's text (2026-08-05).

Operator-confirmed: both საკვირაო სკოლა and დისნეილენდი carry `type=kids_program`
in the admin panel, and every future program will be added the same way — a
hashtag written once, and whoever comments on any post carrying it should get
that program's description automatically.

`send_dm_from_comment` matched `type in {"camp", "kids_program"}` and sent the
Summer-Camp DM for the whole group. Sunday School was rescued from it on
2026-07-02 by NAME (`_is_sunday_school_section`); Disneyland, added later with
the same type, fell straight back in — a „ფასი?" comment on a Disneyland post
answered with the CLOSED camp's price block (2150, კაჭრეთი, camp streams).

Two things had to change together, and the second is the one that actually
carries the fix:

  1. only `type == "camp"` takes the Camp DM;
  2. a program with no `auto_dm_template_id` (the normal state for a program
     created from the panel — the field is optional there) renders from its own
     populated fields. Without (2), `build_section_dm` returns "" and the empty
     result fell through to the PARENT fallback, which is the Camp DM again.

The tests below are written so that a NEW program — one nobody has coded for —
is what they actually check.
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
CAMP_LOCATION = "კაჭრეთი"

# Disneyland as the operator actually has it: kids_program, active, no
# auto_dm_template_id.
_DISNEYLAND = {
    "id": "disneyland",
    "name": "დისნეილენდი",
    "type": "kids_program",
    "status": "active",
    "description_short": "მოგზაურობა დისნეილენდში ბავშვებისთვის.",
    "price_text": "4 000 ლარი",
    "schedule_text": "7 დღე",
    "location": "საფრანგეთი",
    "registration_url": "https://example.org/disney",
}

# A program that does not exist yet and has no code anywhere in the repo.
_FUTURE_PROGRAM = {
    "id": "robotics_club",
    "name": "რობოტიქსის კლუბი",
    "type": "kids_program",
    "status": "active",
    "description_short": "რობოტიქსის კლუბი ბავშვებისთვის.",
    "price_text": "300 ლარი თვეში",
    "location": "თბილისი",
    "registration_url": "https://example.org/robotics",
}

_CAMP_SECTION = {
    "id": "summer_camp", "name": "საზაფხულო ბანაკი", "type": "camp",
    "status": "active", "auto_dm_template_id": "summer_camp_comment_dm",
}


def _patch_send(monkeypatch):
    sent: dict = {}

    def _send_message(sender_id, platform, text):
        sent["text"] = text
        return True

    def _send_private_reply(comment_id, text):
        sent["text"] = text
        return True

    monkeypatch.setattr(messenger_service, "send_message", _send_message)
    monkeypatch.setattr(
        messenger_service, "send_private_reply", _send_private_reply,
    )
    return sent


def _run_comment(monkeypatch, section, *, segment, comment_text, sid="c_prog"):
    async def _resolve(post_id, platform):
        return section

    async def _no_specific(comment_text_, post_id, platform):
        return (None, [], "no_match")

    monkeypatch.setattr(comment_service, "resolve_section_from_post", _resolve)
    monkeypatch.setattr(
        comment_service, "resolve_specific_adult_event", _no_specific,
    )
    sent = _patch_send(monkeypatch)
    conversation_service.conversations.pop(sid, None)
    ok = asyncio.run(comment_service.send_dm_from_comment(
        sid, "instagram", "post123", segment=segment,
        comment_id=None, comment_text=comment_text,
    ))
    return ok, sent.get("text", "")


# ── the live defect ─────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "comment_text",
    ["ფასი?", "რა ღირს?", "ინფორმაცია მინდა", "სად ტარდება?"],
)
def test_disneyland_comment_never_answers_with_the_camp(monkeypatch, comment_text):
    _ok, text = _run_comment(
        monkeypatch, _DISNEYLAND, segment="PARENT", comment_text=comment_text,
    )

    assert CAMP_PRICE not in text
    assert CAMP_LINK not in text
    assert CAMP_LOCATION not in text
    assert "ბანაკ" not in text


def test_disneyland_comment_carries_its_own_facts(monkeypatch):
    _ok, text = _run_comment(
        monkeypatch, _DISNEYLAND, segment="PARENT", comment_text="ფასი?",
    )

    assert "4 000 ლარი" in text
    assert "საფრანგეთი" in text
    assert "https://example.org/disney" in text


def test_a_program_nobody_coded_for_works_with_no_code_change(monkeypatch):
    """The operator's actual requirement: add a program + hashtag in the panel,
    and an interested commenter gets that program's description."""
    _ok, text = _run_comment(
        monkeypatch, _FUTURE_PROGRAM, segment="PARENT", comment_text="ფასი?",
    )

    assert "რობოტიქსის კლუბი ბავშვებისთვის." in text
    assert "300 ლარი თვეში" in text
    assert "https://example.org/robotics" in text
    assert CAMP_PRICE not in text


def test_an_inactive_program_shows_no_price_or_link(monkeypatch):
    """A comment on an old post must not surface a dead program's price — the
    same class of defect the closed camp produced on 2026-08-04."""
    ended = dict(_DISNEYLAND, status="ended")

    _ok, text = _run_comment(
        monkeypatch, ended, segment="PARENT", comment_text="ფასი?",
        sid="c_prog_ended",
    )

    assert "4 000" not in text
    assert "https://example.org/disney" not in text
    assert "მენეჯერ" in text


# ── nothing else moved ──────────────────────────────────────────────────────
def test_the_real_camp_still_gets_the_camp_dm(monkeypatch):
    _ok, text = _run_comment(
        monkeypatch, _CAMP_SECTION, segment="PARENT", comment_text="ფასი?",
        sid="c_prog_camp",
    )

    assert text
    assert "ბანაკ" in text or CAMP_PRICE in text


def test_sunday_school_keeps_its_own_named_closing_line(monkeypatch):
    """Sunday School still runs through its status-aware builder, and its
    closing line still names it — the generic line deliberately does not."""
    monkeypatch.setattr(
        admin_config_service, "get_sunday_school_status",
        lambda: {"status": "active", "lead_type": "sunday_school"},
    )
    ss = {
        "id": "sunday_school", "name": "საკვირაო სკოლა", "type": "kids_program",
        "status": "active", "lead_type": "sunday_school",
        "description_short": "საკვირაო სკოლა ბავშვებისთვის.",
        "price_text": "200 ლარი თვეში",
    }

    _ok, text = _run_comment(
        monkeypatch, ss, segment="PARENT", comment_text="ფასი?",
        sid="c_prog_ss",
    )

    assert "საკვირაო სკოლით დაინტერესებისთვის მადლობა" in text
    assert CAMP_PRICE not in text


def test_the_generic_closing_line_invents_no_georgian_case_ending(monkeypatch):
    """The program is not named in the shared closing line on purpose: naming it
    needs the instrumental („დისნეილენდ-ით"), and a generated case ending is how
    bad Georgian reaches live copy."""
    _ok, text = _run_comment(
        monkeypatch, _DISNEYLAND, segment="PARENT", comment_text="ფასი?",
        sid="c_prog_case",
    )

    assert "დაინტერესებისთვის მადლობა" in text
    assert "დისნეილენდით" not in text
