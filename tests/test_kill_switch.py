"""Emergency Kill Switch tests.

Covers the safe-fallback shape required by the kill-switch brief:

  * Settings exposes ``AGENT_ENABLED`` (default-on).
  * ``kill_switch.is_agent_enabled()`` reads the live settings flag.
  * DM/message entry point returns ``AGENT_DISABLED_MESSAGE`` and skips
    every OpenAI / Calendar / Sheets / notification side-effect when
    disabled.
  * Comment flow skips every public reply / private reply / DM / Sheets
    write / LLM intent call when disabled.
  * Follow-up scheduler skips every send + Sheets read/write when
    disabled.
  * Admin dashboard shows Enabled / Disabled status correctly.

The check is intentionally trivial — these tests prove the agent
genuinely does nothing when the flag flips, which is the operator's
contract for the emergency switch.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.config as config_module
from app.config import Settings
from app.main import app
from app.routes import admin as admin_routes
from app.routes import webhook
from app.services import (
    comment_service,
    conversation_service,
    followup_service,
    kill_switch,
)


# -- helpers --------------------------------------------------------------


def _swap_agent_enabled(monkeypatch, enabled: bool) -> Settings:
    """Replace the canonical kill_switch.settings reference with one
    carrying the desired AGENT_ENABLED flag. Also swap conversation /
    webhook / followup / admin views so every callsite reads the same
    flipped flag — matches the existing test-suite pattern of replacing
    per-module ``settings`` references rather than mutating a frozen
    dataclass instance.
    """
    swapped = dataclasses.replace(config_module.settings, AGENT_ENABLED=enabled)
    monkeypatch.setattr(kill_switch, "settings", swapped)
    monkeypatch.setattr(conversation_service, "settings", swapped)
    monkeypatch.setattr(webhook, "settings", swapped)
    monkeypatch.setattr(followup_service, "settings", swapped)
    monkeypatch.setattr(admin_routes, "settings", swapped)
    return swapped


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


class _Tripwire:
    """Tracks calls so a test can prove the kill switch genuinely
    short-circuited. Every method records the call name and returns
    a benign value — but a test that asserts on `.calls` will fail
    fast if the kill switch is bypassed."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def track(self, name: str):
        def _inner(*_a, **_k):
            self.calls.append(name)
            return None
        return _inner

    def track_async(self, name: str):
        async def _inner(*_a, **_k):
            self.calls.append(name)
            return None
        return _inner


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    conversation_service.conversations.clear()
    comment_service.post_content_cache.clear()
    webhook._processed_comments_lru.clear()
    yield
    conversation_service.conversations.clear()
    comment_service.post_content_cache.clear()
    webhook._processed_comments_lru.clear()


# =========================================================================
# PART 1 — Config flag
# =========================================================================


def test_settings_default_agent_enabled_is_true():
    """A fresh Settings() with no env override must be live."""
    s = Settings()
    assert s.AGENT_ENABLED is True


def test_parse_bool_optional_missing_defaults_true():
    """The `.env` parse path defaults to True when AGENT_ENABLED is unset."""
    parsed = config_module._parse_bool_optional("AGENT_ENABLED_DEFINITELY_NOT_SET", True)
    assert parsed is True


def test_swap_to_false_flips_is_agent_enabled(monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    assert kill_switch.is_agent_enabled() is False


def test_swap_to_true_flips_is_agent_enabled(monkeypatch):
    _swap_agent_enabled(monkeypatch, True)
    assert kill_switch.is_agent_enabled() is True


def test_is_agent_enabled_defaults_true_when_field_missing(monkeypatch):
    """Older Settings objects (constructed without the new field) must
    not accidentally trip the kill switch — `getattr` defaults to True."""
    stripped = SimpleNamespace()  # no AGENT_ENABLED attribute at all
    monkeypatch.setattr(kill_switch, "settings", stripped)
    assert kill_switch.is_agent_enabled() is True


# =========================================================================
# PART 2 — Safe offline message constant
# =========================================================================


def test_disabled_message_is_georgian_and_short():
    msg = kill_switch.AGENT_DISABLED_MESSAGE
    # Must contain key Georgian phrases — Georgian-only by spec.
    assert "ავტომატური ასისტენტი" in msg
    assert "მენეჯერი" in msg
    # No fake booking promise.
    assert "ჩავნიშნე" not in msg
    assert "დავჯავშნე" not in msg
    # Short. The brief says "Short and safe" — ~150 chars is generous.
    assert len(msg) <= 200


# =========================================================================
# PART 3 — DM/message entry point
# =========================================================================


def _block_downstream(monkeypatch) -> _Tripwire:
    """Patch every side-effecting downstream call so the test fails
    loudly if the kill switch lets execution leak through.
    """
    tw = _Tripwire()

    # Flow handlers — if either is called when disabled, the kill
    # switch is broken.
    from app.flows import parent_flow, adult_flow
    monkeypatch.setattr(parent_flow, "handle", tw.track("parent_flow.handle"))
    monkeypatch.setattr(adult_flow, "handle", tw.track("adult_flow.handle"))

    # OpenAI / Calendar / Sheets / notification / Meta send — never
    # any of these when the agent is off.
    from app.services import (
        calendar_service,
        messenger_service,
        notification_service,
        openai_service,
        sheets_service,
    )
    monkeypatch.setattr(openai_service, "chat_with_tools",
                        tw.track("openai.chat_with_tools"))
    monkeypatch.setattr(calendar_service, "book_slot",
                        tw.track("calendar.book_slot"))
    monkeypatch.setattr(sheets_service, "create_lead",
                        tw.track("sheets.create_lead"))
    monkeypatch.setattr(sheets_service, "update_lead",
                        tw.track("sheets.update_lead"))
    monkeypatch.setattr(notification_service, "notify_manager",
                        tw.track("notification.notify_manager"))
    monkeypatch.setattr(messenger_service, "send_message",
                        tw.track("messenger.send_message"))
    return tw


def test_process_message_returns_disabled_message_when_off(monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    _block_downstream(monkeypatch)

    out = conversation_service.process_message(
        sender_id="user_x", message_text="გამარჯობა", platform="messenger",
    )
    assert out == kill_switch.AGENT_DISABLED_MESSAGE


def test_process_message_does_not_create_conversation_when_off(monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    _block_downstream(monkeypatch)

    conversation_service.process_message(
        sender_id="user_x", message_text="გამარჯობა", platform="messenger",
    )
    # The kill switch must not even create a Conversation — that would
    # mutate sales state.
    assert "user_x" not in conversation_service.conversations


def test_process_message_no_downstream_calls_when_off(monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    tw = _block_downstream(monkeypatch)

    conversation_service.process_message(
        sender_id="user_x", message_text="რა ღირს ბანაკი?", platform="instagram",
    )
    # Hard guarantee: no LLM, no Calendar, no Sheets, no notification,
    # no Meta send.
    assert tw.calls == []


def test_process_message_when_enabled_still_routes_to_flow(monkeypatch):
    """Sanity: flipping AGENT_ENABLED back on must NOT leave a
    stale short-circuit; existing flow handlers still run.
    """
    _swap_agent_enabled(monkeypatch, True)

    from app.flows import parent_flow, adult_flow
    monkeypatch.setattr(parent_flow, "handle", lambda c, m: "PARENT_FLOW_REPLY")
    monkeypatch.setattr(adult_flow, "handle", lambda c, m: "ADULT_FLOW_REPLY")

    out = conversation_service.process_message(
        sender_id="user_y",
        message_text="ბანაკი მაინტერესებს",
        platform="messenger",
    )
    assert out == "PARENT_FLOW_REPLY"
    assert out != kill_switch.AGENT_DISABLED_MESSAGE


def test_process_message_when_enabled_unclear_still_returns_menu(monkeypatch):
    """Bare greeting → static UNCLEAR routing menu (existing behaviour)
    when AGENT_ENABLED=true."""
    _swap_agent_enabled(monkeypatch, True)
    out = conversation_service.process_message(
        sender_id="user_z", message_text="გამარჯობა", platform="messenger",
    )
    # The exact wording lives in data/prompts.UNCLEAR_ROUTING; we
    # only assert that we did NOT return the disabled message.
    assert out != kill_switch.AGENT_DISABLED_MESSAGE
    assert out.strip() != ""


# =========================================================================
# PART 4 — Comment flow
# =========================================================================


def _block_comment_downstream(monkeypatch) -> _Tripwire:
    tw = _Tripwire()

    async def _intent(_text):
        tw.calls.append("comment.detect_comment_intent")
        return "INTERESTED"

    async def _segment(_post_id, _platform):
        tw.calls.append("comment.determine_segment_from_post")
        return "PARENT"

    async def _public_reply(*_a, **_k):
        tw.calls.append("comment.reply_to_comment")
        return True

    async def _dm(*_a, **_k):
        tw.calls.append("comment.send_dm_from_comment")
        return True

    monkeypatch.setattr(comment_service, "detect_comment_intent", _intent)
    monkeypatch.setattr(comment_service, "determine_segment_from_post", _segment)
    monkeypatch.setattr(comment_service, "reply_to_comment", _public_reply)
    monkeypatch.setattr(comment_service, "send_dm_from_comment", _dm)

    # Sheets save_comment must not fire either — a "comment received"
    # row written while the agent claims to be silent would mislead
    # the operator's CRM view.
    monkeypatch.setattr(
        webhook, "sheets_service",
        SimpleNamespace(save_comment=tw.track("sheets.save_comment")),
    )
    return tw


def test_comment_flow_skipped_when_agent_off(monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    tw = _block_comment_downstream(monkeypatch)

    asyncio.run(
        webhook.handle_comment(
            comment_id="c_kill_1", post_id="p1", sender_id="user_x",
            user_name="ნინო", comment_text="მაინტერესებს",
            platform="instagram",
        ),
    )
    assert tw.calls == []


def test_comment_flow_no_dm_when_agent_off(monkeypatch):
    """The brief explicitly requires: no rich DM, no public reply, no
    private reply when AGENT_ENABLED=false."""
    _swap_agent_enabled(monkeypatch, False)
    tw = _block_comment_downstream(monkeypatch)

    asyncio.run(
        webhook.handle_comment(
            comment_id="c_kill_2", post_id="p1", sender_id="user_y",
            user_name="ნინო", comment_text="დიდი ინტერესით",
            platform="facebook",
        ),
    )
    assert "comment.send_dm_from_comment" not in tw.calls
    assert "comment.reply_to_comment" not in tw.calls


def test_comment_flow_runs_normally_when_agent_on(monkeypatch):
    """Sanity: existing comment flow keeps working when enabled."""
    _swap_agent_enabled(monkeypatch, True)
    tw = _block_comment_downstream(monkeypatch)

    # Comment → Specific Event Mapping Patch (2026-06-08): use a
    # non-keyword comment so the LLM classifier path is the one under
    # test. Short keyword comments like „მაინტერესებს" now skip the
    # LLM via the deterministic shortcut.
    asyncio.run(
        webhook.handle_comment(
            comment_id="c_kill_3", post_id="p1", sender_id="user_z",
            user_name="ნინო", comment_text="ბანაკი",
            platform="instagram",
        ),
    )
    # At minimum the intent classifier and the DM/private-reply path
    # MUST run when the agent is live. (Public reply is gated by
    # ENABLE_PUBLIC_COMMENT_REPLY, which is independent of the kill
    # switch — we don't assert on it here.)
    assert "comment.detect_comment_intent" in tw.calls
    assert "comment.send_dm_from_comment" in tw.calls


# =========================================================================
# PART 5 — Follow-up scheduler
# =========================================================================


def test_followup_skipped_when_agent_off(monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    tw = _Tripwire()
    monkeypatch.setattr(followup_service, "sheets_service", SimpleNamespace(
        get_cold_leads=tw.track("sheets.get_cold_leads"),
        update_lead=tw.track("sheets.update_lead"),
    ))
    monkeypatch.setattr(followup_service, "messenger_service", SimpleNamespace(
        send_message=tw.track("messenger.send_message"),
    ))

    followup_service.check_and_send_followups()
    # Hard guarantee: scheduler tick MUST NOT read cold leads, send
    # a follow-up DM, or write a Sheets update when disabled.
    assert tw.calls == []


def test_followup_runs_when_agent_on(monkeypatch):
    """When AGENT_ENABLED=true the scheduler must still iterate the
    conversation snapshot. After the Follow-up Scheduler Patch the
    source of truth is `get_all_conversations_snapshot()` (not the
    Sheets cold-lead read), so we assert the snapshot helper was
    consulted. The snapshot may legitimately be empty — we don't
    assert on outbound send, only that we got past the kill-switch
    gate."""
    _swap_agent_enabled(monkeypatch, True)
    seen: list[str] = []

    def _snapshot():
        seen.append("get_all_conversations_snapshot")
        return []  # empty: no sends fired.

    monkeypatch.setattr(
        followup_service.conversation_service,
        "get_all_conversations_snapshot", _snapshot,
    )
    monkeypatch.setattr(followup_service, "messenger_service", SimpleNamespace(
        send_message=lambda *_a, **_k: True,
    ))
    followup_service.check_and_send_followups()
    assert seen == ["get_all_conversations_snapshot"]


# =========================================================================
# PART 6 — Admin dashboard status
# =========================================================================


@pytest.fixture
def _admin_enabled_with_agent(monkeypatch):
    """Admin panel ON with a known password, kill switch independently
    controllable via the returned `flip` callable."""

    def flip(agent_enabled: bool):
        swapped = dataclasses.replace(
            config_module.settings,
            ADMIN_PANEL_ENABLED=True,
            ADMIN_USERNAME="admin",
            ADMIN_PASSWORD="testpw",
            AGENT_ENABLED=agent_enabled,
        )
        monkeypatch.setattr(admin_routes, "settings", swapped)
        monkeypatch.setattr(kill_switch, "settings", swapped)
        return swapped

    return flip


def test_admin_dashboard_shows_enabled_status(_admin_enabled_with_agent):
    _admin_enabled_with_agent(True)
    client = TestClient(app)
    resp = client.get("/admin", headers=_basic_auth_header("admin", "testpw"))
    assert resp.status_code == 200
    text = resp.text
    assert "Agent status" in text
    assert "Enabled" in text
    # Should NOT show "Disabled" line in the agent-status row.
    # (The word "Disabled" might appear elsewhere on other dashboards
    # in the future — be specific: the disabled status emoji must NOT
    # be present.)
    assert "Disabled" not in text


def test_admin_dashboard_shows_disabled_status(_admin_enabled_with_agent):
    _admin_enabled_with_agent(False)
    client = TestClient(app)
    resp = client.get("/admin", headers=_basic_auth_header("admin", "testpw"))
    assert resp.status_code == 200
    text = resp.text
    assert "Agent status" in text
    assert "Disabled" in text
    # And NOT the enabled status.
    assert "Enabled &#9989;" not in text


# =========================================================================
# PART 7 — mask_sender helper (PII-light logging)
# =========================================================================


def test_mask_sender_short_id_is_fully_masked():
    assert kill_switch.mask_sender("abcd") == "****"
    assert kill_switch.mask_sender("a") == "*"


def test_mask_sender_long_id_keeps_trailing_4():
    assert kill_switch.mask_sender("123456789012") == "***9012"


def test_mask_sender_handles_none_and_empty():
    assert kill_switch.mask_sender(None) == "?"
    assert kill_switch.mask_sender("") == "?"
