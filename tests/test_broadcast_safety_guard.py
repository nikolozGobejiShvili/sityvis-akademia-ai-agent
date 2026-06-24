"""Broadcast Safety Patch (2026-06-11).

Incident: a real Messenger DM was sent to a subscribed user during test
work because a broadcast test called the REAL `broadcast_event` without
mocking `messenger_service.send_message` / `sheets_service.list_event_
subscribers`, so it hit the live Sheet + live Meta token.

Safety net: `broadcast_event` is now DRY-RUN by default and only sends
when `settings.LIVE_BROADCAST_ENABLED=true`. These tests prove:
  * dry-run default never sends, even with a subscriber present;
  * the live flag (with a MOCKED transport) does send;
  * the broadcast `source` is recorded;
  * the after-save broadcast is gated behind the operator checkbox.

No test in this file ever performs a real network send — the transport
is always mocked AND the default is dry-run.
"""

from __future__ import annotations

import dataclasses

import pytest
import yaml

import app.config as config_module
from app.services import adult_event_broadcast_service as bsvc
from app.services import admin_config_service, messenger_service, sheets_service


@pytest.fixture
def future_event_config(monkeypatch, tmp_path):
    path = tmp_path / "sections.yaml"
    body = yaml.safe_dump({"sections": [{
        "id": "adult_events", "name": "ზრდასრულთა", "type": "adult_events",
        "status": "active", "hashtags": ["event"], "age_min": 13,
        "auto_dm_template_id": "adult_events_comment_dm",
        "events": [{
            "id": "fest", "title": "summer fest", "status": "active",
            "min_age": 13, "date_text": "28 აგვისტო 19:00",
            "location": "ლისი", "price_text": "100",
            "reservation_url": "https://example.com/fest",
        }],
    }]}, allow_unicode=True, sort_keys=False)
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", path)
    return path


@pytest.fixture
def one_subscriber(monkeypatch):
    monkeypatch.setattr(
        sheets_service, "list_event_subscribers",
        lambda **kw: [{"platform": "messenger", "sender_id": "subscriber_1",
                       "notified_event_ids": []}],
        raising=False,
    )
    marked: list = []
    monkeypatch.setattr(
        sheets_service, "mark_event_subscriber_notified",
        lambda *a, **k: (marked.append(a) or (True, "ok")),
        raising=False,
    )
    return marked


@pytest.fixture
def captured_sends(monkeypatch):
    sent: list = []
    monkeypatch.setattr(
        messenger_service, "send_message",
        lambda *a, **k: (sent.append(a) or True),
    )
    return sent


def _set_live(monkeypatch, value: bool):
    swapped = dataclasses.replace(
        config_module.settings, AGENT_ENABLED=True,
        LIVE_BROADCAST_ENABLED=value,
    )
    monkeypatch.setattr("app.config.settings", swapped)
    from app.services import kill_switch as ks
    monkeypatch.setattr(ks, "settings", swapped)
    return swapped


# ===========================================================================
# 1. dry-run default — never sends
# ===========================================================================


def test_default_is_dry_run_no_send(
    future_event_config, one_subscriber, captured_sends, monkeypatch,
):
    _set_live(monkeypatch, False)  # explicit: the production-safe default
    result = bsvc.broadcast_event("fest", source="test")
    assert result["dry_run"] is True
    assert result["sent"] == 0
    assert captured_sends == []     # NO real DM
    assert one_subscriber == []     # NOT marked notified
    assert result.get("dry_run_would_send", 0) == 1


def test_unmocked_default_still_cannot_send(future_event_config, monkeypatch):
    """Even if a careless test forgets to mock the transport, the dry-run
    default means `send_message` is never reached for a real send. We
    assert by making a real send RAISE — it must never be called."""
    _set_live(monkeypatch, False)
    monkeypatch.setattr(
        sheets_service, "list_event_subscribers",
        lambda **kw: [{"platform": "messenger", "sender_id": "x",
                       "notified_event_ids": []}],
        raising=False,
    )
    monkeypatch.setattr(
        messenger_service, "send_message",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("real send must not happen in dry-run")),
    )
    result = bsvc.broadcast_event("fest", source="test")
    assert result["dry_run"] is True and result["sent"] == 0


# ===========================================================================
# 2. live flag enables sending (mocked transport)
# ===========================================================================


def test_live_flag_sends_with_mocked_transport(
    future_event_config, one_subscriber, captured_sends, monkeypatch,
):
    _set_live(monkeypatch, True)
    result = bsvc.broadcast_event("fest", source="admin_manual")
    assert result["dry_run"] is False
    assert result["sent"] == 1
    assert len(captured_sends) == 1
    assert captured_sends[0][0] == "subscriber_1"
    assert one_subscriber  # marked notified


# ===========================================================================
# 3. source is recorded; payload comes from Admin config (not a fixture)
# ===========================================================================


def test_source_recorded_in_result(
    future_event_config, one_subscriber, captured_sends, monkeypatch,
):
    _set_live(monkeypatch, False)
    result = bsvc.broadcast_event("fest", source="after_save")
    assert result["source"] == "after_save"


def test_broadcast_payload_matches_admin_event(
    future_event_config, one_subscriber, captured_sends, monkeypatch,
):
    """The broadcast message is built from the resolved Admin event —
    proving there is no stale/duplicate source. (The incident's „15 June"
    came from a TEST FIXTURE, not from production config.)"""
    _set_live(monkeypatch, True)
    bsvc.broadcast_event("fest", source="admin_manual")
    assert captured_sends, "expected one mocked send"
    body = captured_sends[0][2]
    assert "summer fest" in body
    assert "28 აგვისტო" in body            # the Admin date, not a fixture date
    assert "https://example.com/fest" in body


# ===========================================================================
# 4. past event still blocked (regression guard) + after-save checkbox gate
# ===========================================================================


def test_past_event_still_blocked(monkeypatch, tmp_path, captured_sends):
    path = tmp_path / "sections.yaml"
    body = yaml.safe_dump({"sections": [{
        "id": "adult_events", "name": "ზრდასრულთა", "type": "adult_events",
        "status": "active", "hashtags": ["event"], "age_min": 13,
        "auto_dm_template_id": "adult_events_comment_dm",
        "events": [{
            "id": "old", "title": "ძველი", "status": "active", "min_age": 13,
            "date_text": "1 იანვარი 2020", "reservation_url": "https://x/o",
        }],
    }]}, allow_unicode=True, sort_keys=False)
    path.write_text(body, encoding="utf-8")
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", path)
    _set_live(monkeypatch, True)  # even live, a past event must be blocked
    result = bsvc.broadcast_event("old", source="admin_manual")
    assert result["reason"] == "event_past"
    assert captured_sends == []


def test_after_save_checkbox_gate():
    from app.routes.admin import _form_checkbox_set
    assert _form_checkbox_set("on") is True
    assert _form_checkbox_set("") is False
    assert _form_checkbox_set(None) is False
