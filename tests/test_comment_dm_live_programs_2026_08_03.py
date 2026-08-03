"""A comment must never be answered with programs that have ended.

When the post caption cannot be fetched — Meta answers 400 for any page the app
is not yet approved to read, which is the current state — hashtag routing has
nothing to route on and `send_dm_from_comment` falls through to the UNCLEAR
branch. That branch sent the raw `UNCLEAR_ROUTING` menu, which names the summer
camp and the adult evenings. Both are `status: ended`; Sunday School and
Disneyland, the only programs on sale, were never mentioned (measured
2026-08-03).

`conversation_service` already wraps the same constant in
`_maybe_dynamic_welcome` so the DM greeting lists the ACTIVE programs. Only the
comment call site was missed. These tests pin that the two agree.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.services import comment_service as com
from app.services import conversation_service as cs

ENDED = ("საზაფხულო ბანაკი", "კულტურული საღამო")


@pytest.fixture
def live_programs(monkeypatch):
    """Two active programs, exactly as the admin panel would report them."""
    menu = ("გამარჯობა.\n\nგვითხარით, რა გაინტერესებთ:\n"
            "— საკვირაო სკოლა\n— დისნეილენდი")
    monkeypatch.setattr(
        cs, "settings", dataclasses.replace(cs.settings, USE_DYNAMIC_WELCOME=True))
    import app.flows.parent_flow as pf
    monkeypatch.setattr(pf, "_build_active_programs_welcome", lambda: menu)
    return menu


def test_unclear_comment_dm_lists_the_live_programs(live_programs):
    out = cs._maybe_dynamic_welcome("FALLBACK")
    assert "საკვირაო სკოლა" in out and "დისნეილენდი" in out
    assert not any(dead in out for dead in ENDED)


def test_comment_service_uses_the_same_wrapper_as_the_dm_greeting():
    """The fix is „call the existing helper", not „copy the menu"."""
    import inspect
    src = inspect.getsource(com.send_dm_from_comment)
    assert "_maybe_dynamic_welcome" in src, (
        "the UNCLEAR comment branch no longer routes through the shared "
        "live-programs helper — a second menu implementation has appeared")


def test_flag_off_keeps_the_hardcoded_menu_byte_identical(monkeypatch):
    """Flag off must change nothing — the guarantee that let this ship."""
    monkeypatch.setattr(
        cs, "settings", dataclasses.replace(cs.settings, USE_DYNAMIC_WELCOME=False))
    assert cs._maybe_dynamic_welcome("FALLBACK") == "FALLBACK"


def test_no_active_programs_falls_back_rather_than_promising_nothing(monkeypatch):
    """An empty active list must not yield an empty DM."""
    monkeypatch.setattr(
        cs, "settings", dataclasses.replace(cs.settings, USE_DYNAMIC_WELCOME=True))
    import app.flows.parent_flow as pf
    monkeypatch.setattr(pf, "_build_active_programs_welcome", lambda: None)
    assert cs._maybe_dynamic_welcome("FALLBACK") == "FALLBACK"


def test_helper_failure_never_breaks_the_comment_dm(monkeypatch):
    monkeypatch.setattr(
        cs, "settings", dataclasses.replace(cs.settings, USE_DYNAMIC_WELCOME=True))
    import app.flows.parent_flow as pf

    def boom():
        raise RuntimeError("admin config unreadable")

    monkeypatch.setattr(pf, "_build_active_programs_welcome", boom)
    assert cs._maybe_dynamic_welcome("FALLBACK") == "FALLBACK"
