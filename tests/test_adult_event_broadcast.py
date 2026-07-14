"""Adult Event Broadcast Patch (2026-06-08) — fan-out tests.

Test groups (per task spec PART 13):
  1. Broadcast triggers when checkbox set + event active + has link
  2. Inactive event blocked
  3. Missing link blocks broadcast
  4. Duplicate-event prevention via Notified Event IDs
  5. consent=false / unsubscribed users skipped
  6. Unsupported platforms skipped
  7. Per-subscriber send failure does not block others
  8. Kill switch disables broadcast
  9. Broadcast message includes full event card
 10. Messenger private DM only (no public reply)
 11. Admin Panel manual broadcast route renders result page
"""

from __future__ import annotations

import base64
import dataclasses
import textwrap
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agent.tools import adult_tool_executor
from app.config import settings as global_settings
from app.main import app
from app.routes import admin as admin_routes
from app.services import (
    adult_event_broadcast_service,
    admin_config_service,
    sheets_service,
)


# ---------------------------------------------------------------------------
# Fake worksheet + sections.yaml fixtures
# ---------------------------------------------------------------------------


class _FakeEventsWorksheet:
    def __init__(self):
        from app.services.sheets_service import EVENT_SUBSCRIBER_HEADERS
        self.rows: list[list[str]] = [list(EVENT_SUBSCRIBER_HEADERS)]

    def row_values(self, row_index: int) -> list[str]:
        if 1 <= row_index <= len(self.rows):
            return list(self.rows[row_index - 1])
        return []

    def col_values(self, col_index: int) -> list[str]:
        return [
            row[col_index - 1] if col_index - 1 < len(row) else ""
            for row in self.rows
        ]

    def get_all_values(self) -> list[list[str]]:
        return [list(r) for r in self.rows]

    def append_row(self, row, value_input_option: str = "RAW") -> None:
        from app.services.sheets_service import EVENT_SUBSCRIBER_HEADERS
        padded = [str(v) for v in row]
        while len(padded) < len(EVENT_SUBSCRIBER_HEADERS):
            padded.append("")
        self.rows.append(padded)

    def update_cell(self, row: int, col: int, value: Any) -> None:
        while len(self.rows) < row:
            self.rows.append([""] * len(self.rows[0]))
        target = self.rows[row - 1]
        while len(target) < col:
            target.append("")
        target[col - 1] = str(value)

    def update(self, rng: str, values) -> None:
        if not values:
            return
        row_values = [str(v) for v in values[0]]
        try:
            row_idx = int(
                "".join(ch for ch in rng.split(":")[0] if ch.isdigit()),
            )
        except ValueError:
            return
        from app.services.sheets_service import EVENT_SUBSCRIBER_HEADERS
        while len(row_values) < len(EVENT_SUBSCRIBER_HEADERS):
            row_values.append("")
        while len(self.rows) < row_idx:
            self.rows.append([""] * len(EVENT_SUBSCRIBER_HEADERS))
        self.rows[row_idx - 1] = row_values

    def resize(self, *, cols: int) -> None:
        pass


@pytest.fixture
def fake_events_ws(monkeypatch):
    ws = _FakeEventsWorksheet()
    monkeypatch.setattr(
        sheets_service, "_event_subscribers_worksheet", lambda: ws,
    )
    return ws


@pytest.fixture
def sections_path(monkeypatch, tmp_path):
    path = tmp_path / "sections.yaml"
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", path)
    return path


def _seed_event(sections_path, event: dict | list) -> None:
    if isinstance(event, list):
        events_list = event
    else:
        events_list = [event]
    body = yaml.safe_dump(
        {"sections": [
            {
                "id": "adult_events", "name": "ზრდასრულთა ღონისძიებები",
                "type": "adult_events", "status": "active",
                "hashtags": ["ღონისძიება"], "age_min": 13,
                "auto_dm_template_id": "adult_events_comment_dm",
                "events": events_list,
            },
        ]},
        allow_unicode=True, sort_keys=False, default_flow_style=False,
    )
    sections_path.write_text(body, encoding="utf-8")


@pytest.fixture
def kill_switch_on(monkeypatch):
    # Broadcast Safety Patch (2026-06-11): these tests exercise the SEND
    # logic with a MOCKED messenger, so they must enable
    # LIVE_BROADCAST_ENABLED (otherwise the new dry-run guard short-
    # circuits the send path). The transport is always mocked via
    # `_mock_messenger` — no real DM ever leaves a test.
    swapped = dataclasses.replace(
        global_settings, AGENT_ENABLED=True, LIVE_BROADCAST_ENABLED=True,
    )
    from app.services import kill_switch as ks_mod
    monkeypatch.setattr("app.config.settings", swapped)
    monkeypatch.setattr(ks_mod, "settings", swapped)
    return swapped


def _seed_subscriber(sub: dict) -> None:
    sheets_service.save_event_subscriber(sub)


def _mock_messenger(monkeypatch):
    """The broadcast service uses `from app.services import
    messenger_service` inline; patch the underlying module's
    `send_message` so the import-time binding picks up the fake."""
    from app.services import messenger_service as ms_module
    sent: list[tuple[str, str, str]] = []

    def fake_send(sender_id: str, platform: str, message: str) -> bool:
        sent.append((sender_id, platform, message))
        return True

    monkeypatch.setattr(ms_module, "send_message", fake_send)
    return sent


# ---------------------------------------------------------------------------
# 1. Broadcast happy path
# ---------------------------------------------------------------------------


def test_broadcast_sends_to_subscribed_users(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch, adult_events_june_2026_clock,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "ქართული პოეზიის საღამო",
        "status": "active", "min_age": 13,
        "date_text": "25 ივნისი, 20:00",
        "location": "ამბასადორი კაჭრეთი",
        "price_text": "150",
        "description": "პოეტური საღამო",
        "reservation_url": "https://example.com/p",
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u1",
        "name": "ნ", "phone": "595999733", "consent": True,
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u2",
        "name": "ნ", "phone": "595888222", "consent": True,
    })
    sent = _mock_messenger(monkeypatch)

    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert result["success"] is True
    assert result["sent"] == 2
    assert len(sent) == 2
    for _sender, platform, body in sent:
        assert platform == "messenger"
        assert "ქართული პოეზიის საღამო" in body
        assert "25 ივნისი, 20:00" in body
        assert "ამბასადორი კაჭრეთი" in body
        assert "150 ლარი" in body
        assert "პოეტური საღამო" in body
        assert "https://example.com/p" in body
        # Unsubscribe footer hint
        assert "აღარ გამომიგზავნოთ" in body


# ---------------------------------------------------------------------------
# 2 + 3. Blocked branches
# ---------------------------------------------------------------------------


def test_broadcast_blocks_inactive_event(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "ქართული პოეზიის საღამო",
        "status": "inactive", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    _mock_messenger(monkeypatch)
    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert result["success"] is False
    assert result["reason"] == "inactive"
    assert result["sent"] == 0


def test_broadcast_blocks_missing_link(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "T",
        "status": "active", "min_age": 13,
        # NO reservation_url AND NO payment_terms
    })
    _mock_messenger(monkeypatch)
    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert result["success"] is False
    assert result["reason"] == "missing_link"


def test_broadcast_missing_event_returns_missing_event(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, [])
    _mock_messenger(monkeypatch)
    result = adult_event_broadcast_service.broadcast_event("ghost_event")
    # The seeded section has no events; resolver returns None.
    assert result["success"] is False
    assert result["reason"] == "missing_event"


# ---------------------------------------------------------------------------
# 4. Duplicate-event prevention
# ---------------------------------------------------------------------------


def test_broadcast_skips_subscriber_already_notified(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "ქართული პოეზიის საღამო",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u1",
        "name": "ნ", "phone": "595999733", "consent": True,
        "notified_event_ids": "poetry",  # already notified
    })
    sent = _mock_messenger(monkeypatch)
    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert result["success"] is True
    assert result["sent"] == 0
    assert result["skipped_duplicate"] == 1
    assert sent == []


def test_re_running_broadcast_marks_notified(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "T",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u1",
        "name": "ნ", "phone": "595999733", "consent": True,
    })
    _mock_messenger(monkeypatch)
    first = adult_event_broadcast_service.broadcast_event("poetry")
    assert first["sent"] == 1
    # Re-run — must NOT send again.
    second = adult_event_broadcast_service.broadcast_event("poetry")
    assert second["sent"] == 0
    assert second["skipped_duplicate"] == 1


# ---------------------------------------------------------------------------
# 5. Consent / unsubscribed users filtered
# ---------------------------------------------------------------------------


def test_broadcast_skips_unsubscribed_user(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "T",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u1",
        "name": "ნ", "phone": "595999733", "consent": True,
    })
    sheets_service.unsubscribe_event_subscriber("messenger", "u1")
    sent = _mock_messenger(monkeypatch)
    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert result["sent"] == 0
    assert result["total_candidates"] == 0
    assert sent == []


def test_broadcast_skips_consent_false_user(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "T",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    sheets_service.save_event_subscriber({
        "platform": "messenger", "sender_id": "u1",
        "name": "ნ", "phone": "595999733",
        "status": "subscribed", "consent": False,
    })
    sent = _mock_messenger(monkeypatch)
    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert sent == []
    assert result["total_candidates"] == 0


# ---------------------------------------------------------------------------
# 6. Unsupported platform skipped
# ---------------------------------------------------------------------------


def test_broadcast_skips_unsupported_platform(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "T",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    _seed_subscriber({
        "platform": "tiktok", "sender_id": "u1",
        "name": "ნ", "phone": "595999733", "consent": True,
    })
    sent = _mock_messenger(monkeypatch)
    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert sent == []
    assert result["skipped_platform"] == 1


# ---------------------------------------------------------------------------
# 7. Per-subscriber failure isolation
# ---------------------------------------------------------------------------


def test_broadcast_continues_on_per_subscriber_failure(
    sections_path, fake_events_ws, kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "T",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u1",
        "name": "ნ", "phone": "595999733", "consent": True,
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u2",
        "name": "ნ", "phone": "595999734", "consent": True,
    })
    call_log: list[str] = []

    def flaky_send(sender_id, platform, message):
        call_log.append(sender_id)
        return sender_id == "u2"  # u1 fails, u2 succeeds

    from app.services import messenger_service as ms_module
    monkeypatch.setattr(ms_module, "send_message", flaky_send)
    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert call_log == ["u1", "u2"]
    assert result["sent"] == 1
    assert result["failed"] == 1


# ---------------------------------------------------------------------------
# 8. Kill switch
# ---------------------------------------------------------------------------


def test_broadcast_blocked_by_kill_switch(
    sections_path, fake_events_ws, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "T",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    swapped = dataclasses.replace(global_settings, AGENT_ENABLED=False)
    from app.services import kill_switch as ks_mod
    monkeypatch.setattr("app.config.settings", swapped)
    monkeypatch.setattr(ks_mod, "settings", swapped)

    result = adult_event_broadcast_service.broadcast_event("poetry")
    assert result["success"] is False
    assert result["reason"] == "kill_switch_disabled"


# ---------------------------------------------------------------------------
# 9. Message builder content checks
# ---------------------------------------------------------------------------


def test_build_broadcast_message_skips_missing_fields(sections_path):
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
        # NO date, location, price, description
    })
    msg = adult_event_broadcast_service.build_broadcast_message(event)
    assert "T" in msg
    assert "თარიღი:" not in msg
    assert "ლოკაცია:" not in msg
    assert "ფასი:" not in msg
    assert "აღწერა:" not in msg
    assert "https://example.com/p" in msg


def test_build_broadcast_message_preserves_description_with_fb_link(
    sections_path,
):
    """A description that includes a Facebook post URL must round-trip
    verbatim — operator may include a post-link in their description."""
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "active", "min_age": 13,
        "description": "ვრცლად: https://www.facebook.com/page/posts/123",
        "reservation_url": "https://example.com/p",
    })
    msg = adult_event_broadcast_service.build_broadcast_message(event)
    assert "https://www.facebook.com/page/posts/123" in msg


def test_build_broadcast_message_numeric_price_appended_lari():
    event = admin_config_service.normalize_adult_event({
        "id": "p", "title": "T", "status": "active", "min_age": 13,
        "price_text": "150",
        "reservation_url": "https://example.com/p",
    })
    msg = adult_event_broadcast_service.build_broadcast_message(event)
    assert "150 ლარი" in msg


# ---------------------------------------------------------------------------
# 10. Admin route — manual broadcast endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_enabled(monkeypatch):
    swapped = dataclasses.replace(
        global_settings,
        ADMIN_PANEL_ENABLED=True,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="testpw",
    )
    monkeypatch.setattr(admin_routes, "settings", swapped)
    return swapped


def _auth():
    raw = b"admin:testpw"
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def test_admin_manual_broadcast_route_renders_result(
    admin_enabled, sections_path, fake_events_ws,
    kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "poetry", "title": "ქართული პოეზიის საღამო",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    _seed_subscriber({
        "platform": "messenger", "sender_id": "u1",
        "name": "ნ", "phone": "595999733", "consent": True,
    })
    _mock_messenger(monkeypatch)

    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/poetry/broadcast",
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert "გაგზავნილია" in resp.text


def test_admin_manual_broadcast_route_renders_missing_link_message(
    admin_enabled, sections_path, fake_events_ws,
    kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "p", "title": "T",
        "status": "active", "min_age": 13,
        # NO link
    })
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/p/broadcast",
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert "ბილეთის ბმული" in resp.text
    assert "ვერ მოხერხდა" in resp.text


def test_admin_manual_broadcast_route_renders_no_subscribers(
    admin_enabled, sections_path, fake_events_ws,
    kill_switch_on, monkeypatch,
):
    _seed_event(sections_path, {
        "id": "p", "title": "T",
        "status": "active", "min_age": 13,
        "reservation_url": "https://example.com/p",
    })
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/adult_events/events/p/broadcast",
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert "subscribed მომხმარებლები ჯერ არ არიან" in resp.text


def test_admin_event_form_has_broadcast_checkbox():
    """The create / edit form must expose the broadcast-after-save
    checkbox so the operator can opt in per save."""
    from pathlib import Path
    text = Path("templates/admin/adult_event_form.html").read_text(
        encoding="utf-8",
    )
    assert "broadcast_after_save" in text
    assert "subscribed მომხმარებლებს" in text


def test_admin_event_list_has_manual_broadcast_button():
    from pathlib import Path
    text = Path("templates/admin/adult_events.html").read_text(
        encoding="utf-8",
    )
    assert "/broadcast" in text
    assert "გაგზავნა subscribed მომხმარებლებთან" in text
