"""Follow-up scheduler tests.

Covers the Follow-up Scheduler Patch (2026-05-30):

  * `get_cold_leads` cutoff is tz-aware (Asia/Tbilisi).
  * `conversation_service.get_all_conversations_snapshot()` returns a
    safe copy of the in-memory store.
  * `check_and_send_followups()` is driven by Conversation markers
    (not by Sheets cold-lead rows).
  * Cadence: 24h → 72h → 168h with stage transitions matching the
    keys in `followup_strategy.yaml`.
  * Skip rules: booked / declined / manager_handoff / no_more /
    exhausted / non-PARENT / no last_bot_message_at / missing
    sender_id / unsupported platform.
  * Platform routing: instagram + messenger both reach
    `messenger_service.send_message` with their original platform
    string.
  * Admin template wins when present; safe Georgian fallback when
    missing.
  * Kill switch short-circuits before any scan / send.
  * `check_comment_followups()` also respects the kill switch.

The scheduler is fully synchronous; the test suite manipulates the
in-memory `conversations` dict directly to seed deterministic
states.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import app.config as config_module
from app.agent.services.timestamps import TBILISI_TZ
from app.models.conversation import Conversation
from app.models.lead import Lead
from app.services import (
    comment_service,
    conversation_service,
    followup_service,
    kill_switch,
    messenger_service,
    sheets_service,
)


# -- helpers --------------------------------------------------------------


def _swap_agent_enabled(monkeypatch, enabled: bool):
    """Match the kill-switch test pattern.

    Follow-up Test Mode Patch (2026-06-06) — also pins
    ``FOLLOWUP_TEST_MODE=False`` + ``FOLLOWUP_FIRST_DELAY_SECONDS=0`` so
    the legacy 24h / 72h / 168h cadence assertions in this file are not
    short-circuited by the live ``.env``'s 120-second test override.
    """
    swapped = dataclasses.replace(
        config_module.settings,
        AGENT_ENABLED=enabled,
        FOLLOWUP_TEST_MODE=False,
        FOLLOWUP_FIRST_DELAY_SECONDS=0,
        FOLLOWUP_ENABLED=True,
    )
    monkeypatch.setattr(kill_switch, "settings", swapped)
    monkeypatch.setattr(followup_service, "settings", swapped)
    monkeypatch.setattr(comment_service, "settings", swapped)
    return swapped


def _make_conversation(
    *,
    sender_id: str = "user_x",
    platform: str = "instagram",
    segment: str = "PARENT",
    state: str = "ASK_NAME",
    last_bot_offset: timedelta | None = timedelta(hours=25),
    followup_stage: str = "",
    followup_blocked_reason: str = "",
    booked: bool = False,
    name: str = "ნინო",
) -> Conversation:
    """Build a Conversation pre-loaded with a recent bot message so
    the scheduler can compute elapsed time deterministically.
    """
    conv = Conversation(sender_id=sender_id, platform=platform)
    conv.segment = segment
    conv.state = state
    conv.followup_stage = followup_stage
    conv.followup_blocked_reason = followup_blocked_reason
    if last_bot_offset is not None:
        # `conversation_service.process_message` writes
        # `datetime.utcnow().isoformat()` — naive UTC. Match that shape
        # so the parser path is exercised end-to-end.
        ts = datetime.utcnow() - last_bot_offset
        conv.last_bot_message_at = ts.isoformat()
    lead = Lead(sender_id=sender_id, platform=platform, segment=segment)
    lead.name = name
    lead.calendly_booked = booked
    conv.lead = lead
    return conv


class _SendRecorder:
    """Capture every messenger_service.send_message call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.return_value = True

    def __call__(self, *, sender_id: str, platform: str, text: str) -> bool:
        self.calls.append({
            "sender_id": sender_id, "platform": platform, "text": text,
        })
        return self.return_value


@pytest.fixture
def send_recorder(monkeypatch) -> _SendRecorder:
    rec = _SendRecorder()
    monkeypatch.setattr(messenger_service, "send_message", rec)
    monkeypatch.setattr(followup_service, "messenger_service",
                        SimpleNamespace(send_message=rec))
    return rec


@pytest.fixture(autouse=True)
def _reset_conversation_state():
    conversation_service.conversations.clear()
    yield
    conversation_service.conversations.clear()


@pytest.fixture(autouse=True)
def _force_agent_enabled(monkeypatch):
    """Default to AGENT_ENABLED=true for every follow-up test. The
    kill-switch-specific tests in this file flip this on top via
    `_swap_agent_enabled`."""
    _swap_agent_enabled(monkeypatch, True)
    yield


# =========================================================================
# PART 1 — get_cold_leads timezone bug
# =========================================================================


def test_get_cold_leads_uses_tz_aware_cutoff(monkeypatch):
    """The fixed cutoff uses Asia/Tbilisi, so a Tbilisi-aware row
    timestamp can be compared without TypeError."""
    # Row written by the live Sheets path: aware Tbilisi ISO string.
    tbilisi_old = datetime.now(TBILISI_TZ) - timedelta(hours=72)
    fake_rows = [{
        "Status": "New",
        "Follow-up Sent": "FALSE",
        "Last Activity": tbilisi_old.isoformat(),
        "Sender ID": "user_x",
        "Platform": "instagram",
        "Segment": "PARENT",
    }]

    class _FakeWorksheet:
        def get_all_records(self):
            return fake_rows

    monkeypatch.setattr(sheets_service, "_worksheet", lambda: _FakeWorksheet())
    # Should NOT raise TypeError.
    cold = sheets_service.get_cold_leads()
    assert len(cold) == 1
    assert cold[0].sender_id == "user_x"


def test_get_cold_leads_no_typeerror_on_aware_vs_naive(monkeypatch):
    """A mix of aware + naive parsed timestamps must not crash. The
    fix promotes naive datetimes to Tbilisi before comparison."""
    aware = (datetime.now(TBILISI_TZ) - timedelta(hours=72)).isoformat()
    naive = (datetime.utcnow() - timedelta(hours=72)).strftime("%Y-%m-%d %H:%M:%S")
    fake_rows = [
        {"Status": "New", "Follow-up Sent": "FALSE",
         "Last Activity": aware, "Sender ID": "u1", "Platform": "instagram"},
        {"Status": "New", "Follow-up Sent": "FALSE",
         "Last Activity": naive, "Sender ID": "u2", "Platform": "instagram"},
    ]

    class _FakeWorksheet:
        def get_all_records(self):
            return fake_rows

    monkeypatch.setattr(sheets_service, "_worksheet", lambda: _FakeWorksheet())
    cold = sheets_service.get_cold_leads()
    # Both rows are old enough; both should be cold without raising.
    assert len(cold) == 2


def test_get_cold_leads_skips_recent_rows(monkeypatch):
    """A row within the 48h window stays warm — confirms the cutoff
    direction is correct (not just absence of crash)."""
    recent = datetime.now(TBILISI_TZ) - timedelta(hours=1)
    fake_rows = [{
        "Status": "New", "Follow-up Sent": "FALSE",
        "Last Activity": recent.isoformat(), "Sender ID": "u_warm",
        "Platform": "instagram",
    }]

    class _FakeWorksheet:
        def get_all_records(self):
            return fake_rows

    monkeypatch.setattr(sheets_service, "_worksheet", lambda: _FakeWorksheet())
    cold = sheets_service.get_cold_leads()
    assert cold == []


# =========================================================================
# PART 2 — Conversation snapshot helper
# =========================================================================


def test_snapshot_returns_active_conversations():
    conversation_service.conversations["u1"] = _make_conversation(sender_id="u1")
    conversation_service.conversations["u2"] = _make_conversation(sender_id="u2")
    snap = conversation_service.get_all_conversations_snapshot()
    assert {c.sender_id for c in snap} == {"u1", "u2"}


def test_snapshot_is_a_copy_not_the_live_dict():
    conversation_service.conversations["u1"] = _make_conversation(sender_id="u1")
    snap = conversation_service.get_all_conversations_snapshot()
    snap.clear()  # Must NOT affect the live store.
    assert "u1" in conversation_service.conversations


def test_empty_snapshot_returns_empty_list():
    assert conversation_service.get_all_conversations_snapshot() == []


# =========================================================================
# PART 3 — Skip rules
# =========================================================================


@pytest.mark.parametrize("blocked_reason", [
    "booked", "declined", "manager_handoff_completed",
    "asked_no_more_messages", "followup_exhausted", "registered",
])
def test_skip_blocked_reasons(send_recorder, blocked_reason):
    conv = _make_conversation(followup_blocked_reason=blocked_reason)
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []
    # Stage MUST NOT advance.
    assert conv.followup_stage == ""


def test_skip_when_lead_calendly_booked(send_recorder):
    conv = _make_conversation(booked=True)
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []


@pytest.mark.parametrize("segment", ["ADULT", "UNCLEAR", ""])
def test_skip_non_parent_segments(send_recorder, segment):
    conv = _make_conversation(segment=segment)
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []


def test_skip_when_no_last_bot_message_at(send_recorder):
    conv = _make_conversation(last_bot_offset=None)
    conv.last_bot_message_at = ""
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []


def test_skip_when_sender_id_missing(send_recorder):
    conv = _make_conversation(sender_id="")
    conversation_service.conversations["pseudo_key"] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []


@pytest.mark.parametrize("platform", ["", "unknown", "telegram", "viber"])
def test_skip_unsupported_platform(send_recorder, platform):
    conv = _make_conversation(platform=platform)
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []


# =========================================================================
# PART 4 — Stage timing
# =========================================================================


def test_stage_1_not_sent_before_24h(send_recorder):
    conv = _make_conversation(last_bot_offset=timedelta(hours=23))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []
    assert conv.followup_stage == ""


def test_stage_1_sent_at_24h(send_recorder):
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert len(send_recorder.calls) == 1
    assert conv.followup_stage == "first_24h"


def test_stage_2_not_sent_before_72h_after_stage_1(send_recorder):
    conv = _make_conversation(
        followup_stage="first_24h", last_bot_offset=timedelta(hours=70),
    )
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []
    assert conv.followup_stage == "first_24h"


def test_stage_2_sent_at_72h_after_stage_1(send_recorder):
    conv = _make_conversation(
        followup_stage="first_24h", last_bot_offset=timedelta(hours=73),
    )
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert len(send_recorder.calls) == 1
    assert conv.followup_stage == "second_3d"


def test_stage_3_sent_at_168h_after_stage_2(send_recorder):
    conv = _make_conversation(
        followup_stage="second_3d", last_bot_offset=timedelta(hours=170),
    )
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert len(send_recorder.calls) == 1
    assert conv.followup_stage == "third_7d"
    assert conv.followup_blocked_reason == "followup_exhausted"


def test_no_send_after_stage_3(send_recorder):
    conv = _make_conversation(
        followup_stage="third_7d", last_bot_offset=timedelta(days=30),
    )
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []


def test_second_tick_is_idempotent(send_recorder):
    """Two ticks within the same window must not double-send."""
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    followup_service.check_and_send_followups()
    assert len(send_recorder.calls) == 1


def test_last_bot_message_at_resets_after_send(send_recorder):
    """The brief's "If no followup_sent_at exists, use
    last_bot_message_at consistently and document that follow-up
    sends update it" — verify behaviour."""
    old_ts = (datetime.utcnow() - timedelta(hours=25)).isoformat()
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conv.last_bot_message_at = old_ts
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert conv.last_bot_message_at != old_ts


# =========================================================================
# PART 5 — Templates
# =========================================================================


def test_admin_template_used_when_present(send_recorder, monkeypatch):
    captured: dict[str, Any] = {}

    def fake_render(template_id, context):
        captured["template_id"] = template_id
        captured["context"] = dict(context)
        return f"ADMIN_RENDERED::{template_id}::{context.get('name', '')}"

    monkeypatch.setattr(
        followup_service.admin_config_service, "render_template", fake_render,
    )
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert len(send_recorder.calls) == 1
    assert send_recorder.calls[0]["text"].startswith("ADMIN_RENDERED::followup_24h")
    assert captured["template_id"] == "followup_24h"
    assert captured["context"]["name"] == "ნინო"


def test_fallback_used_when_admin_template_empty(send_recorder, monkeypatch):
    monkeypatch.setattr(
        followup_service.admin_config_service,
        "render_template",
        lambda _tid, _ctx: "",
    )
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert len(send_recorder.calls) == 1
    body = send_recorder.calls[0]["text"]
    # Fallback is Georgian and contains the camp/clarification hook.
    assert "ბანაკთან" in body or "კითხვა" in body


def test_render_exception_falls_back_safely(send_recorder, monkeypatch):
    """A template render that raises must not kill the tick."""
    def boom(*_a, **_k):
        raise RuntimeError("YAML broken")

    monkeypatch.setattr(
        followup_service.admin_config_service, "render_template", boom,
    )
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    # Still sent via the safe Georgian fallback constant.
    assert len(send_recorder.calls) == 1


# =========================================================================
# PART 6 — Platform routing
# =========================================================================


def test_instagram_routes_through_send_message(send_recorder):
    conv = _make_conversation(
        platform="instagram", last_bot_offset=timedelta(hours=25),
    )
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls[0]["platform"] == "instagram"
    assert send_recorder.calls[0]["sender_id"] == conv.sender_id


def test_messenger_routes_through_send_message(send_recorder):
    conv = _make_conversation(
        platform="messenger", last_bot_offset=timedelta(hours=25),
    )
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls[0]["platform"] == "messenger"


def test_platform_serializes_and_deserializes_via_to_dict():
    """Platform must survive Conversation.to_dict / from_dict so the
    Redis write-through path preserves it."""
    conv = _make_conversation(platform="instagram", sender_id="u_persist")
    payload = conv.to_dict()
    assert payload["platform"] == "instagram"
    restored = Conversation.from_dict(payload)
    assert restored.platform == "instagram"


def test_followup_markers_serialize_via_to_dict():
    """The 5 follow-up fields must round-trip through Redis."""
    conv = _make_conversation()
    conv.followup_stage = "second_3d"
    conv.followup_blocked_reason = "declined"
    conv.last_meaningful_interest = "price"
    conv.stopped_after = "price"
    payload = conv.to_dict()
    restored = Conversation.from_dict(payload)
    assert restored.followup_stage == "second_3d"
    assert restored.followup_blocked_reason == "declined"
    assert restored.last_meaningful_interest == "price"
    assert restored.stopped_after == "price"
    assert restored.last_bot_message_at == conv.last_bot_message_at


# =========================================================================
# PART 7 — Kill switch
# =========================================================================


def test_kill_switch_skips_followup_tick(send_recorder, monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert send_recorder.calls == []
    # Stage must NOT advance when killed.
    assert conv.followup_stage == ""


def test_kill_switch_skips_comment_followup_tick(monkeypatch):
    _swap_agent_enabled(monkeypatch, False)
    called = []
    monkeypatch.setattr(
        comment_service.sheets_service, "get_pending_comment_followups",
        lambda: called.append("get") or [],
    )
    asyncio.run(comment_service.check_comment_followups())
    assert called == []


# =========================================================================
# PART 8 — Persistence write-through after send
# =========================================================================


def test_save_to_redis_called_after_send(send_recorder, monkeypatch):
    saved: list[Conversation] = []

    def fake_is_enabled():
        return True

    def fake_save(conv):
        saved.append(conv)

    monkeypatch.setattr(
        followup_service.redis_state_service, "is_enabled", fake_is_enabled,
    )
    monkeypatch.setattr(
        conversation_service, "_save_conversation_to_redis", fake_save,
    )
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert len(saved) == 1
    assert saved[0].sender_id == conv.sender_id
    assert saved[0].followup_stage == "first_24h"


def test_save_to_redis_skipped_when_disabled(send_recorder, monkeypatch):
    saved: list[Conversation] = []
    monkeypatch.setattr(
        followup_service.redis_state_service, "is_enabled", lambda: False,
    )
    monkeypatch.setattr(
        conversation_service, "_save_conversation_to_redis",
        lambda conv: saved.append(conv),
    )
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    # Send still happened.
    assert len(send_recorder.calls) == 1
    # But Redis write-through was a no-op.
    assert saved == []


def test_send_failure_still_advances_stage(send_recorder):
    """A failed send must NOT trigger an infinite retry loop on the
    next tick. The stage advances; the operator sees the WARN line."""
    send_recorder.return_value = False
    conv = _make_conversation(last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[conv.sender_id] = conv
    followup_service.check_and_send_followups()
    assert len(send_recorder.calls) == 1
    assert conv.followup_stage == "first_24h"


def test_admin_template_edit_is_picked_up_by_renderer():
    """End-to-end Admin Panel ↔ scheduler round-trip: a save_template
    write is read back by `followup_service._render_followup_text` on
    the next call, with no process restart. Covers the operator's
    promise that follow-up text is editable without code."""
    from app.services import admin_config_service

    src = admin_config_service.TEMPLATES_PATH
    bak = src.read_bytes()
    try:
        new_body = "QA_EDIT_MARKER გამარჯობა 🌿 ახალი ფოლოუ-აპ."
        admin_config_service.save_template("followup_24h", new_body)

        conv = _make_conversation()
        rendered = followup_service._render_followup_text(
            "followup_24h", conv, conv.lead,
        )
        assert "QA_EDIT_MARKER" in rendered
    finally:
        src.write_bytes(bak)


def test_sim_followup_script_imports():
    """The `tools/sim_followup.py` QA helper must stay importable so a
    future restructure doesn't silently break the documented manual
    QA command (`python tools/sim_followup.py --case all`)."""
    import importlib
    import sys
    from pathlib import Path

    repo_root = str(Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    # tools/ isn't a package — import by file location.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "sim_followup_qa_only",
        Path(repo_root) / "tools" / "sim_followup.py",
    )
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    # The eight documented case ids must be wired.
    assert set(mod._CASES.keys()) == {
        "24h", "3d", "7d", "not_yet", "booked",
        "declined", "kill_switch", "messenger",
    }


def test_one_bad_conversation_does_not_kill_the_tick(send_recorder, monkeypatch):
    """If conversation A raises during processing, conversation B
    still gets its follow-up."""
    bad = _make_conversation(sender_id="bad")
    good = _make_conversation(sender_id="good", last_bot_offset=timedelta(hours=25))
    conversation_service.conversations[bad.sender_id] = bad
    conversation_service.conversations[good.sender_id] = good

    original = followup_service._maybe_send_followup_for_conversation

    def explode_for_bad(conv, now):
        if conv.sender_id == "bad":
            raise RuntimeError("simulated")
        return original(conv, now)

    monkeypatch.setattr(
        followup_service, "_maybe_send_followup_for_conversation", explode_for_bad,
    )
    followup_service.check_and_send_followups()
    assert any(call["sender_id"] == "good" for call in send_recorder.calls)
