"""The customer must never see markup, and never be offered a closed program.

Both defects came out of the Railway logs of 2026-08-02:

* 13:12:40 — the agent sent „- **ბანაკი (2026)** — …". Messenger has no
  renderer, so the asterisks reached the parent literally. The per-turn context
  had said `reply_rendering=plain_text` since 2026-07-30 and the model still did
  it: guidance is probabilistic, so the guarantee belongs in the send layer.
* 13:09:27 / earlier — the „what can I help with" lines were frozen strings
  naming the summer camp and the adult evenings. The operator closed both; the
  two programs that are actually live were never mentioned.

These tests pin the CONTRACT (nothing renderable leaves; the offer equals the
active sections), never the sentence — a frozen sentence is what broke.
"""
from __future__ import annotations

import dataclasses

import pytest

from app.flows import parent_flow as pf
from app.services import conversation_service as cs
from app.services import messenger_service as ms

_ACTIVE = [
    {"id": "sunday_school", "name": "საკვირაო სკოლა", "status": "active"},
    {"id": "disneyland", "name": "დისნეილენდი", "status": "active"},
]


@pytest.fixture
def active_sections(monkeypatch):
    """Pin the admin panel to two live programs, camp and events closed."""
    from app.services import admin_config_service

    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: list(_ACTIVE))
    return _ACTIVE


# --- the send layer -------------------------------------------------------


def test_live_1312_reply_loses_its_asterisks():
    """The exact reply the parent received at 13:12:40."""
    sent = ms.to_plain_text(
        "- **ბანაკი (2026)** — ბანაკის ფასი? - **დისნეილენდი** — 4 000 ლარი"
    )
    assert "**" not in sent
    assert "ბანაკი (2026)" in sent and "4 000 ლარი" in sent


def test_table_becomes_readable_lines():
    out = ms.to_plain_text(
        "🏰 **დისნეილენდი**\n\n| | |\n|---|---|\n"
        "| 📍 **ადგილი** | საფრანგეთი |\n| 💰 **ფასი** | 4 000 ლარი |"
    )
    assert "|" not in out
    assert "📍 ადგილი — საფრანგეთი" in out
    assert "💰 ფასი — 4 000 ლარი" in out


def test_emoji_and_brand_bullets_survive():
    """Emoji are wanted; the „— " bullet is the brand's own menu shape."""
    clean = "გამარჯობა 💙\n\nგვითხარით, რა გაინტერესებთ:\n— საკვირაო სკოლა\n— დისნეილენდი"
    assert ms.to_plain_text(clean) == clean


def test_masked_phone_is_not_treated_as_bold():
    """`595***733` is the privacy masker's output, not markdown."""
    text = "ჩვენი კონსულტანტი დაგიკავშირდებათ ნომერზე 595***733."
    assert ms.to_plain_text(text) == text


def test_asterisk_bullet_is_not_read_as_italic():
    text = "* პირველი\n* მეორე"
    assert ms.to_plain_text(text) == text


def test_link_keeps_its_url():
    out = ms.to_plain_text("ბმული: [რეგისტრაცია](https://example.ge/a)")
    assert out == "ბმული: რეგისტრაცია (https://example.ge/a)"


def test_send_message_delivers_plain_text(monkeypatch):
    """The guarantee is only real if send_message applies it."""
    captured: dict = {}

    class _Resp:
        is_success = True
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    def _fake_post(url, **kwargs):
        captured["body"] = kwargs.get("json")
        return _Resp()

    monkeypatch.setattr(ms.httpx, "post", _fake_post)
    # `Settings` is a frozen dataclass, so swap a copy into the module — the
    # same idiom tests/conftest.py uses to pin flags.
    monkeypatch.setattr(
        ms, "settings",
        dataclasses.replace(ms.settings, MESSENGER_PAGE_ACCESS_TOKEN="t0ken"),
    )

    ms.send_message("sender-1", "messenger", "💰 **ფასი:** 4 000 ლარი")

    assert captured["body"]["message"]["text"] == "💰 ფასი: 4 000 ლარი"


# --- the offer is read, not frozen ----------------------------------------


def test_injection_redirect_offers_the_active_programs(active_sections):
    out = pf._render_offtopic_injection_reply()
    assert "საკვირაო სკოლა" in out and "დისნეილენდი" in out
    # The programs the operator ended must not be advertised.
    assert "ბანაკზე" not in out and "ღონისძიებებზე" not in out


def test_injection_redirect_still_declines(active_sections):
    assert "ვერ გაგიზიარებთ" in pf._render_offtopic_injection_reply()


def test_offer_follows_the_admin_panel(monkeypatch):
    """Close a program in the panel and it stops being offered — no code edit."""
    from app.services import admin_config_service

    monkeypatch.setattr(admin_config_service, "get_active_sections",
                        lambda: [{"id": "robotics", "name": "რობოტიკის კლუბი"}])
    out = pf._render_offtopic_injection_reply()
    assert "რობოტიკის კლუბი" in out
    assert "საკვირაო სკოლა" not in out


def test_no_active_programs_falls_back_safely(monkeypatch):
    from app.services import admin_config_service

    monkeypatch.setattr(admin_config_service, "get_active_sections", lambda: [])
    out = pf._render_offtopic_injection_reply()
    assert out == pf._PARENT_OFFTOPIC_INJECTION_REPLY
    assert "ვერ გაგიზიარებთ" in out


def test_active_names_survive_a_broken_admin_config(monkeypatch):
    from app.services import admin_config_service

    def _boom():
        raise RuntimeError("yaml unreadable")

    monkeypatch.setattr(admin_config_service, "get_active_sections", _boom)
    assert pf._active_program_names() == []


# --- identity -------------------------------------------------------------


def test_identity_says_ai_agent_and_lists_live_programs(active_sections):
    out = cs._maybe_identity_reply("ბოტი ხარ?")
    assert out is not None
    assert "AI აგენტი" in out
    assert "ვირტუალური ასისტენტი" not in out
    assert "საკვირაო სკოლა" in out and "დისნეილენდი" in out
    # The old text asked „ბავშვების საზაფხულო ბანაკი თუ ზრდასრულთა
    # კულტურული საღამოები?" — both closed.
    assert "საზაფხულო ბანაკი" not in out


def test_identity_still_returns_none_for_a_normal_question(active_sections):
    assert cs._maybe_identity_reply("რა ღირს დისნეილენდი?") is None
