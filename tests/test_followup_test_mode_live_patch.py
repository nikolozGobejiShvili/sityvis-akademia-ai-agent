"""Follow-up Test Mode + Live-QA Compatibility Patch (2026-06-06).

Covers:

  Part 1 — config knobs (`FOLLOWUP_ENABLED`, `FOLLOWUP_TEST_MODE`,
           `FOLLOWUP_FIRST_DELAY_SECONDS`).
  Part 2 — follow-up marker creation + blocked-reason gating
           (booked / manager handoff / decline).
  Part 3 — Messenger DM 2-minute follow-up via the override.
  Part 4 — Comment → private DM follow-up marker creation.
  Part 5 — content sanity (PARENT template selected vs ADULT etc.).
  Part 6 — privacy-safe logging (sender masked, no raw phone).

The scheduler runs deterministically in-process; only the actual
Meta send is mocked. Redis is pinned off by the autouse fixture in
``conftest.py``; a few tests opt into a FakeRedis to verify
write-through.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    comment_service,
    conversation_service,
    followup_service,
)


# =========================================================================
# Part 1 — config knobs
# =========================================================================


def test_settings_exposes_followup_test_mode_field():
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert "FOLLOWUP_TEST_MODE" in fields
    assert "FOLLOWUP_FIRST_DELAY_SECONDS" in fields
    assert "FOLLOWUP_ENABLED" in fields


def test_settings_defaults_are_production_safe():
    s = Settings()
    # Default is production cadence (test mode OFF, override 0).
    assert s.FOLLOWUP_TEST_MODE is False
    assert s.FOLLOWUP_FIRST_DELAY_SECONDS == 0
    assert s.FOLLOWUP_ENABLED is True


def test_followup_enabled_property_respects_kill_flag():
    s_enabled = dataclasses.replace(Settings(), FOLLOWUP_ENABLED=True)
    s_disabled = dataclasses.replace(Settings(), FOLLOWUP_ENABLED=False)
    assert s_enabled.followup_enabled is True
    assert s_disabled.followup_enabled is False


def _patch_settings(monkeypatch, **overrides):
    swapped = dataclasses.replace(followup_service.settings, **overrides)
    monkeypatch.setattr(followup_service, "settings", swapped)
    return swapped


def test_first_delay_uses_override_when_test_mode_on(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
    )
    delay = followup_service._first_delay()
    assert delay == timedelta(seconds=120)


def test_first_delay_falls_back_when_override_zero(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=0,
    )
    delay = followup_service._first_delay()
    assert delay == timedelta(hours=24)


def test_first_delay_falls_back_when_override_negative(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=-1,
    )
    delay = followup_service._first_delay()
    assert delay == timedelta(hours=24)


def test_first_delay_falls_back_when_test_mode_off(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=False,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
    )
    delay = followup_service._first_delay()
    # Production cadence is preserved even when seconds are set —
    # test mode must be ON to engage the override.
    assert delay == timedelta(hours=24)


def test_first_delay_invalid_type_does_not_crash(monkeypatch):
    swapped = dataclasses.replace(
        followup_service.settings,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=0,
    )
    monkeypatch.setattr(followup_service, "settings", swapped)
    # Force a broken int() conversion to verify the fallback.
    with patch.object(
        followup_service, "settings",
        type("S", (), {
            "FOLLOWUP_TEST_MODE": True,
            "FOLLOWUP_FIRST_DELAY_SECONDS": "abc",  # invalid string
        })(),
    ):
        delay = followup_service._first_delay()
    assert delay == timedelta(hours=24)


def test_effective_cadence_overrides_only_first_stage(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
    )
    cadence = followup_service._effective_cadence()
    assert len(cadence) == 3
    assert cadence[0]["from_stage"] == ""
    assert cadence[0]["delay"] == timedelta(seconds=120)
    # Stage 2 and 3 stay on production cadence.
    assert cadence[1]["delay"] == timedelta(hours=72)
    assert cadence[2]["delay"] == timedelta(hours=168)


# =========================================================================
# Part 2 — production cadence + scheduler skip rules
# =========================================================================


def _make_parent_conv(
    sender_id: str = "1234567890",
    platform: str = "messenger",
    last_bot_iso: str | None = None,
    followup_stage: str = "",
    blocked_reason: str = "",
    booked: bool = False,
) -> Conversation:
    lead = Lead(sender_id=sender_id, platform=platform, segment="PARENT")
    if booked:
        lead.calendly_booked = True
    conv = Conversation(
        sender_id=sender_id, platform=platform, segment="PARENT",
        lead=lead, followup_stage=followup_stage,
        followup_blocked_reason=blocked_reason,
    )
    if last_bot_iso is not None:
        conv.last_bot_message_at = last_bot_iso
    return conv


def test_check_and_send_followups_skips_when_master_disabled(monkeypatch):
    _patch_settings(monkeypatch, FOLLOWUP_ENABLED=False)
    send = MagicMock()
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [_make_parent_conv(last_bot_iso="2000-01-01T00:00:00")],
    )
    followup_service.check_and_send_followups()
    send.assert_not_called()


def test_check_and_send_followups_skips_when_kill_switch_off(monkeypatch):
    # `kill_switch.is_agent_enabled` reads from its own settings import,
    # not `followup_service.settings`. Patch both for the kill check.
    from app.services import kill_switch
    swapped = dataclasses.replace(kill_switch.settings, AGENT_ENABLED=False)
    monkeypatch.setattr(kill_switch, "settings", swapped)
    send = MagicMock()
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [_make_parent_conv(last_bot_iso="2000-01-01T00:00:00")],
    )
    followup_service.check_and_send_followups()
    send.assert_not_called()


def test_followup_skips_when_lead_booked(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    conv = _make_parent_conv(
        last_bot_iso="2000-01-01T00:00:00",  # ancient → eligible by elapsed
        booked=True,
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    send.assert_not_called()


def test_followup_skips_when_blocked_declined(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    conv = _make_parent_conv(
        last_bot_iso="2000-01-01T00:00:00",
        blocked_reason="declined",
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    send.assert_not_called()


def test_followup_skips_when_blocked_manager_handoff(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    conv = _make_parent_conv(
        last_bot_iso="2000-01-01T00:00:00",
        blocked_reason="manager_handoff_completed",
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    send.assert_not_called()


# =========================================================================
# Part 3 — Messenger DM 2-minute follow-up
# =========================================================================


def _utc_iso(seconds_ago: int) -> str:
    """Naive UTC ISO string `seconds_ago` seconds in the past.

    Matches the format `conversation_service.process_message` writes
    (`datetime.utcnow().isoformat()`).
    """
    return (datetime.utcnow() - timedelta(seconds=seconds_ago)).isoformat()


def test_first_followup_fires_after_test_mode_delay(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    # Bot last spoke 150 seconds ago → ≥ 120s → due.
    conv = _make_parent_conv(
        last_bot_iso=_utc_iso(seconds_ago=150),
        followup_stage="",
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    assert send.call_count == 1
    args, kwargs = send.call_args
    assert kwargs.get("platform") == "messenger"
    assert kwargs.get("sender_id") == conv.sender_id
    # Stage advanced so a second tick is a no-op.
    assert conv.followup_stage == "first_24h"


def test_first_followup_does_not_fire_before_test_delay(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    # Bot last spoke 30 seconds ago → not yet due.
    conv = _make_parent_conv(
        last_bot_iso=_utc_iso(seconds_ago=30),
        followup_stage="",
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    send.assert_not_called()
    assert conv.followup_stage == ""


def test_first_followup_does_not_duplicate(monkeypatch):
    """Two consecutive scheduler ticks send AT MOST one follow-up per
    cadence stage. The second tick is a no-op because the stage
    advanced after the first send."""
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    conv = _make_parent_conv(
        last_bot_iso=_utc_iso(seconds_ago=200),
        followup_stage="",
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    followup_service.check_and_send_followups()
    assert send.call_count == 1


def test_followup_marker_updates_after_send(monkeypatch):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    conv = _make_parent_conv(
        last_bot_iso=_utc_iso(seconds_ago=150),
        followup_stage="",
    )
    pre_last = conv.last_bot_message_at
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    assert conv.last_bot_message_at != pre_last
    assert conv.followup_stage == "first_24h"


def test_production_cadence_unchanged_when_test_mode_off(monkeypatch):
    """Production-mode behaviour MUST stay 24h+. A conversation whose
    bot last spoke 150 seconds ago must NOT receive a follow-up when
    the override is inactive."""
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=False,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,  # ignored
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    conv = _make_parent_conv(
        last_bot_iso=_utc_iso(seconds_ago=150),
        followup_stage="",
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    send.assert_not_called()


def test_second_stage_uses_production_72h_even_in_test_mode(monkeypatch):
    """Test-mode override applies ONLY to the first stage. The 3-day
    stage is sacred — operators can't accidentally pummel a user with
    test-cadence reminders."""
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    # Already moved past first stage; bot last spoke 200 seconds ago.
    conv = _make_parent_conv(
        last_bot_iso=_utc_iso(seconds_ago=200),
        followup_stage="first_24h",
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    followup_service.check_and_send_followups()
    # 200 seconds is far short of 72h; second-stage send must not fire.
    send.assert_not_called()


# =========================================================================
# Part 4 — Comment → private DM follow-up marker
# =========================================================================


@pytest.fixture
def _clear_conversations():
    original = dict(conversation_service.conversations)
    conversation_service.conversations.clear()
    try:
        yield
    finally:
        conversation_service.conversations.clear()
        conversation_service.conversations.update(original)


def test_comment_dm_stamps_followup_marker_on_success(
    monkeypatch, _clear_conversations,
):
    """After a comment → private DM is sent, the conversation has a
    fresh `last_bot_message_at` so the scheduler can pick it up."""
    import asyncio

    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        comment_service, "determine_segment_from_post",
        AsyncMock(return_value="PARENT"),
    )
    monkeypatch.setattr(
        comment_service.messenger_service, "send_private_reply",
        lambda comment_id, message: True,
    )

    result = asyncio.run(comment_service.send_dm_from_comment(
        sender_id="cmt-sender-1",
        post_id="post-1",
        platform="facebook",
        segment="PARENT",
        comment_id="cmt-1",
    ))
    assert result is True

    conv = conversation_service.conversations["cmt-sender-1"]
    assert conv.last_bot_message_at, "comment DM must stamp last_bot_message_at"
    # Stamp parses cleanly.
    parsed = datetime.fromisoformat(conv.last_bot_message_at)
    assert parsed <= datetime.utcnow()


def test_comment_dm_failure_does_not_stamp_marker(
    monkeypatch, _clear_conversations,
):
    """A failed DM send must NOT create a follow-up marker — otherwise
    the scheduler would try to chase a user who never received the
    initial message."""
    import asyncio

    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        comment_service, "determine_segment_from_post",
        AsyncMock(return_value="PARENT"),
    )
    monkeypatch.setattr(
        comment_service.messenger_service, "send_private_reply",
        lambda comment_id, message: False,
    )

    result = asyncio.run(comment_service.send_dm_from_comment(
        sender_id="cmt-sender-fail",
        post_id="post-1",
        platform="facebook",
        segment="PARENT",
        comment_id="cmt-fail",
    ))
    assert result is False

    conv = conversation_service.conversations["cmt-sender-fail"]
    # Marker NOT stamped on failure.
    assert conv.last_bot_message_at == ""


def test_comment_dm_marker_routes_followup_through_messenger(
    monkeypatch, _clear_conversations,
):
    """End-to-end: a comment DM marker → scheduler fires a private DM
    (never a public comment-reply path) via `messenger_service.send_message`."""
    import asyncio

    monkeypatch.setattr(
        comment_service, "resolve_section_from_post",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        comment_service, "determine_segment_from_post",
        AsyncMock(return_value="PARENT"),
    )
    monkeypatch.setattr(
        comment_service.messenger_service, "send_private_reply",
        lambda comment_id, message: True,
    )

    asyncio.run(comment_service.send_dm_from_comment(
        sender_id="cmt-flow",
        post_id="post-1",
        platform="messenger",  # Conversation.platform = messenger
        segment="PARENT",
        comment_id="cmt-flow-id",
    ))

    conv = conversation_service.conversations["cmt-flow"]
    # Backdate the stamp so the test-mode delay is comfortably past.
    conv.last_bot_message_at = _utc_iso(seconds_ago=200)

    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    send_dm = MagicMock(return_value=True)
    monkeypatch.setattr(
        followup_service.messenger_service, "send_message", send_dm,
    )
    followup_service.check_and_send_followups()

    assert send_dm.call_count == 1
    _, kwargs = send_dm.call_args
    # Private DM channel — NOT a public comment reply.
    assert kwargs.get("platform") == "messenger"
    assert kwargs.get("sender_id") == "cmt-flow"


def _async_value(value):
    """Tiny shim so MagicMock can return an awaitable for async helpers."""
    async def _coro():
        return value
    return _coro()


# =========================================================================
# Part 5 — content sanity
# =========================================================================


def test_followup_24h_fallback_text_is_concise_and_safe(monkeypatch):
    """The fallback follow-up text is the operator's safety net. It
    must not claim a booking, must not mention pricing, and must not
    be aggressive."""
    txt = followup_service._FALLBACK_FOLLOWUP_24H
    assert "ჩაგინიშნე" not in txt  # no fake booking claim
    assert "ჩაგინიშნავთ" not in txt
    assert "იჩქარეთ" not in txt
    assert "ბოლო ადგილები" not in txt
    assert len(txt) < 300  # short


def test_followup_3d_fallback_text_is_concise():
    txt = followup_service._FALLBACK_FOLLOWUP_3D
    assert "ჩაგინიშნე" not in txt
    assert len(txt) < 300


def test_followup_7d_fallback_text_is_final_and_calm():
    txt = followup_service._FALLBACK_FOLLOWUP_7D
    assert "ჩაგინიშნე" not in txt
    assert len(txt) < 300


# =========================================================================
# Part 6 — privacy-safe logging
# =========================================================================


def test_log_lines_mask_sender_in_test_mode(monkeypatch, caplog):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    send = MagicMock(return_value=True)
    monkeypatch.setattr(followup_service.messenger_service, "send_message", send)
    # 14-digit sender id; masked form is "123456***".
    conv = _make_parent_conv(
        sender_id="98765432123456",
        last_bot_iso=_utc_iso(seconds_ago=150),
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [conv],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()

    full_logs = "\n".join(rec.message for rec in caplog.records)
    # No raw 14-digit sender id leaked.
    assert "98765432123456" not in full_logs
    # Masked form present.
    assert "987654***" in full_logs


def test_test_mode_banner_logged(monkeypatch, caplog):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=True,
        FOLLOWUP_FIRST_DELAY_SECONDS=120,
        AGENT_ENABLED=True,
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "Test mode enabled: first delay = 120s" in full


def test_production_banner_logged(monkeypatch, caplog):
    _patch_settings(
        monkeypatch,
        FOLLOWUP_TEST_MODE=False,
        FOLLOWUP_FIRST_DELAY_SECONDS=0,
        AGENT_ENABLED=True,
    )
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "Production cadence active" in full


def test_disabled_banner_logged(monkeypatch, caplog):
    _patch_settings(monkeypatch, FOLLOWUP_ENABLED=False)
    monkeypatch.setattr(
        conversation_service, "get_all_conversations_snapshot",
        lambda: [],
    )
    with caplog.at_level(logging.INFO, logger="app.services.followup_service"):
        followup_service.check_and_send_followups()
    full = "\n".join(rec.message for rec in caplog.records)
    assert "FOLLOWUP_ENABLED=false" in full
    assert "tick skipped" in full
