"""WhatsApp manager-notification — env mapping + test isolation (2026-06-23).

Verifies:
  * `_send_manager_whatsapp` reads the correct env keys (token / phone-number-id /
    MANAGER_WHATSAPP), posts to the right endpoint with a Bearer token, and
    normalises the recipient (`+995595999733` → `995595999733`).
  * a REAL Meta POST happens ONLY when `ALLOW_LIVE_WHATSAPP=true`.
  * the scenario runner mocks `_send_manager_whatsapp`, so it can NEVER message
    the manager even with live credentials in `.env`.
"""

from __future__ import annotations

import dataclasses

import httpx

from app.config import normalize_whatsapp_number, Settings
from app.services import notification_service as n


def _live_cfg(**over):
    base = dict(
        WHATSAPP_TOKEN="tok123",
        WHATSAPP_PHONE_NUMBER_ID="PHONEID",
        MANAGER_WHATSAPP_NUMBER="+995595999733",
        ALLOW_LIVE_WHATSAPP=True,
    )
    base.update(over)
    return dataclasses.replace(n.settings, **base)


# ---------------------------------------------------------------------------
# PART B — recipient normalisation
# ---------------------------------------------------------------------------
def test_manager_whatsapp_plus_prefix_normalised():
    assert normalize_whatsapp_number("+995595999733") == "995595999733"
    assert normalize_whatsapp_number("995595999733") == "995595999733"
    assert normalize_whatsapp_number("595999733") == "995595999733"
    assert normalize_whatsapp_number("00995595999733") == "995595999733"


def test_settings_resolve_manager_whatsapp_from_MANAGER_WHATSAPP():
    cfg = dataclasses.replace(n.settings, MANAGER_WHATSAPP_NUMBER="+995595999733")
    assert cfg.get_manager_whatsapp_number() == "995595999733"


# ---------------------------------------------------------------------------
# PART D — live-send guard
# ---------------------------------------------------------------------------
def test_blocked_when_live_disabled(monkeypatch):
    """Configured WhatsApp BUT ALLOW_LIVE_WHATSAPP=False → no POST, returns False."""
    monkeypatch.setattr(n, "settings", _live_cfg(ALLOW_LIVE_WHATSAPP=False))

    def _explode(*a, **k):
        raise AssertionError("httpx.post MUST NOT be called when live is disabled")

    monkeypatch.setattr(httpx, "post", _explode)
    assert n._send_manager_whatsapp("body") is False


def test_blocked_when_not_configured(monkeypatch):
    """Missing credentials → no POST, returns False (even if the flag is on)."""
    monkeypatch.setattr(n, "settings", _live_cfg(WHATSAPP_TOKEN=""))

    def _explode(*a, **k):
        raise AssertionError("httpx.post MUST NOT be called when not configured")

    monkeypatch.setattr(httpx, "post", _explode)
    assert n._send_manager_whatsapp("body") is False


def test_posts_when_live_enabled_with_correct_mapping(monkeypatch):
    """ALLOW_LIVE_WHATSAPP=True + configured → posts to the correct endpoint with
    a Bearer token and the normalised recipient. (httpx is mocked — no real POST.)"""
    monkeypatch.setattr(n, "settings", _live_cfg())
    captured: dict = {}

    class _Resp:
        is_success = True
        status_code = 200
        text = "ok"

    def _fake_post(url, headers=None, json=None, timeout=None, **k):
        captured.update(url=url, headers=headers, json=json)
        return _Resp()

    monkeypatch.setattr(httpx, "post", _fake_post)

    assert n._send_manager_whatsapp("WhatsApp smoke test") is True
    assert "graph.facebook.com" in captured["url"]
    assert "PHONEID/messages" in captured["url"]              # phone-number-id in path
    assert captured["headers"]["Authorization"] == "Bearer tok123"  # token
    assert captured["json"]["to"] == "995595999733"          # recipient, no „+"
    assert captured["json"]["messaging_product"] == "whatsapp"
    assert captured["json"]["text"]["body"] == "WhatsApp smoke test"


# ---------------------------------------------------------------------------
# PART C — scenario-runner isolation
# ---------------------------------------------------------------------------
def test_scenario_runner_mocks_manager_whatsapp():
    """`scenario_runner.install_mocks()` must replace `_send_manager_whatsapp`
    so a CRITICAL/transcript run can NEVER reach Meta — even with live creds in
    `.env`. Snapshots + restores every module install_mocks touches so this test
    leaves no global side effect."""
    import tools.scenario_runner_full as R
    from app.services import (
        calendar_service, messenger_service, sheets_service,
    )

    mods = (n, calendar_service, sheets_service, messenger_service)
    snaps = {mod: dict(vars(mod)) for mod in mods}
    try:
        real_send = n._send_manager_whatsapp
        R.install_mocks()
        assert n._send_manager_whatsapp is not real_send          # replaced
        # Calling it must NOT hit httpx (the autouse guard would raise on a real
        # POST). A mock returns cleanly.
        assert n._send_manager_whatsapp("smoke") is True
    finally:
        for mod, snap in snaps.items():
            mod.__dict__.clear()
            mod.__dict__.update(snap)


# ---------------------------------------------------------------------------
# PART A — env-key wiring (default settings)
# ---------------------------------------------------------------------------
def test_default_allow_live_whatsapp_is_false():
    assert Settings().ALLOW_LIVE_WHATSAPP is False
