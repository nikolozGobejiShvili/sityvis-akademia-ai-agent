"""Instagram Webhook Signature Patch (2026-06-08) — tests.

Covers:
  1. Facebook app secret signature still accepted.
  2. Instagram app secret signature accepted via INSTAGRAM_APP_SECRET.
  3. Wrong signature returns 403.
  4. Missing signature returns 403 when at least one secret is set.
  5. Both secrets configured — either one passes.
  6. No configured secret → fail-open accept with warning.
  7. App secret / token / signature never appear in logs.
  8. Instagram payload accepted after valid signature.
  9. Unsupported Instagram field returns 200 with a safe diagnostic.
 10. Privacy-safe payload summary (no message text, no sender id leaks).
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import app.config as config_module
from app.main import app
from app.routes import webhook as webhook_module


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _swap_settings(monkeypatch, **overrides):
    swapped = dataclasses.replace(config_module.settings, **overrides)
    monkeypatch.setattr(webhook_module, "settings", swapped)
    monkeypatch.setattr(config_module, "settings", swapped)
    return swapped


def _sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _block_background(monkeypatch):
    calls: list[dict] = []

    async def _fake(payload):
        calls.append(payload or {})

    monkeypatch.setattr(webhook_module, "_process_payload", _fake)
    return calls


_INSTAGRAM_MESSAGE_PAYLOAD = {
    "object": "instagram",
    "entry": [{
        "id": "ig_page_x",
        "time": 1700000000,
        "messaging": [
            {
                "sender": {"id": "ig_user_secret_xyz"},
                "recipient": {"id": "ig_page_x"},
                "timestamp": 1700000001,
                "message": {
                    "mid": "mid_1",
                    "text": "SUPER SECRET MESSAGE TEXT 12345",
                },
            },
        ],
    }],
}

_INSTAGRAM_UNSUPPORTED_PAYLOAD = {
    "object": "instagram",
    "entry": [{
        "id": "ig_page_x",
        "time": 1700000000,
        # Field that the existing handler doesn't route on.
        "live_videos": [{"id": "video_42"}],
    }],
}

_FACEBOOK_MESSAGING_PAYLOAD = {
    "object": "page",
    "entry": [{
        "id": "fb_page_x",
        "messaging": [
            {
                "sender": {"id": "fb_sender_secret_abc"},
                "recipient": {"id": "fb_page_x"},
                "timestamp": 1700000001,
                "message": {"mid": "m1", "text": "FB SECRET MSG"},
            },
        ],
    }],
}


# ---------------------------------------------------------------------------
# 1. Facebook app secret still accepted
# ---------------------------------------------------------------------------


def test_facebook_signature_accepts_when_meta_app_secret_set(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="fb_secret_123",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="",
    )
    _block_background(monkeypatch)
    body = json.dumps(_FACEBOOK_MESSAGING_PAYLOAD).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": _sign("fb_secret_123", body),
        "Content-Type": "application/json",
    }
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200


def test_legacy_messenger_alias_still_works(monkeypatch):
    """`MESSENGER_APP_SECRET` was the original env name; still works."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="legacy_alias_secret",
        INSTAGRAM_APP_SECRET="",
    )
    _block_background(monkeypatch)
    body = json.dumps(_FACEBOOK_MESSAGING_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("legacy_alias_secret", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Instagram secret accepted
# ---------------------------------------------------------------------------


def test_instagram_signature_accepts_via_instagram_app_secret(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="some_fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret_456",
    )
    _block_background(monkeypatch)
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    # Sign with the Instagram secret — the Facebook one would mismatch.
    headers = {"X-Hub-Signature-256": _sign("ig_secret_456", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200


def test_instagram_signature_when_only_instagram_secret_set(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_only_789",
    )
    _block_background(monkeypatch)
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("ig_only_789", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 3 + 4. Wrong / missing signature
# ---------------------------------------------------------------------------


def test_wrong_signature_returns_403(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    calls = _block_background(monkeypatch)
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("WRONG_SECRET", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 403
    assert calls == []


def test_missing_signature_returns_403_when_secret_set(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="",
    )
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    resp = TestClient(app).post("/webhook", content=body)
    assert resp.status_code == 403


def test_wrong_signature_prefix_returns_403(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="",
    )
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    # sha1= instead of sha256=
    resp = TestClient(app).post(
        "/webhook", content=body,
        headers={"X-Hub-Signature-256": "sha1=abc123"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 5. Both secrets configured, either signature valid
# ---------------------------------------------------------------------------


def test_both_secrets_set_facebook_signature_valid(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    _block_background(monkeypatch)
    body = json.dumps(_FACEBOOK_MESSAGING_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("fb_secret", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200


def test_both_secrets_set_instagram_signature_valid(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    _block_background(monkeypatch)
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("ig_secret", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 6. Fail-open when no secret configured
# ---------------------------------------------------------------------------


def test_fail_open_when_no_secret_configured(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="",
    )
    _block_background(monkeypatch)
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    # No header — fail-open accepts.
    resp = TestClient(app).post("/webhook", content=body)
    assert resp.status_code == 200


def test_verification_disabled_short_circuit_accepts(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=False,
        META_APP_SECRET="fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    _block_background(monkeypatch)
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    # No header at all — accepts because verification is disabled.
    resp = TestClient(app).post("/webhook", content=body)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 7. Privacy — no secrets / tokens / payload bodies in logs
# ---------------------------------------------------------------------------


def test_no_secret_value_appears_in_logs_on_reject(monkeypatch, caplog):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="FB_SUPER_SECRET_VALUE_XYZ",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="IG_SUPER_SECRET_VALUE_QQQ",
    )
    caplog.set_level("INFO")
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("WRONG", body)}
    TestClient(app).post("/webhook", content=body, headers=headers)
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "FB_SUPER_SECRET_VALUE_XYZ" not in log_text
    assert "IG_SUPER_SECRET_VALUE_QQQ" not in log_text


def test_no_secret_value_appears_in_logs_on_accept(monkeypatch, caplog):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="FB_SUPER_SECRET_VALUE_XYZ",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="IG_SUPER_SECRET_VALUE_QQQ",
    )
    _block_background(monkeypatch)
    caplog.set_level("INFO")
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("IG_SUPER_SECRET_VALUE_QQQ", body)}
    TestClient(app).post("/webhook", content=body, headers=headers)
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "IG_SUPER_SECRET_VALUE_QQQ" not in log_text
    assert "FB_SUPER_SECRET_VALUE_XYZ" not in log_text
    # The acceptance label IS logged so the operator can correlate
    # which secret matched — but only the label, not the value.
    assert "instagram_app_secret" in log_text


def test_signature_header_value_not_logged(monkeypatch, caplog):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="fb_secret",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="",
    )
    caplog.set_level("INFO")
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    raw_header = "sha256=DISTINCTIVE_SIGNATURE_VALUE_DEADBEEF"
    TestClient(app).post(
        "/webhook", content=body,
        headers={"X-Hub-Signature-256": raw_header},
    )
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "DISTINCTIVE_SIGNATURE_VALUE_DEADBEEF" not in log_text


def test_message_text_not_logged(monkeypatch, caplog):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    _block_background(monkeypatch)
    caplog.set_level("INFO")
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("ig_secret", body)}
    TestClient(app).post("/webhook", content=body, headers=headers)
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "SUPER SECRET MESSAGE TEXT 12345" not in log_text


def test_sender_id_not_logged_in_summary(monkeypatch, caplog):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    _block_background(monkeypatch)
    caplog.set_level("INFO")
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("ig_secret", body)}
    TestClient(app).post("/webhook", content=body, headers=headers)
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "ig_user_secret_xyz" not in log_text


# ---------------------------------------------------------------------------
# 8. Instagram payload accepted after valid signature
# ---------------------------------------------------------------------------


def test_instagram_payload_summary_emitted(monkeypatch, caplog):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    _block_background(monkeypatch)
    caplog.set_level("INFO")
    body = json.dumps(_INSTAGRAM_MESSAGE_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("ig_secret", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200
    log_text = "\n".join(rec.message for rec in caplog.records)
    assert "object=instagram" in log_text
    # Field summary uses the actual entry key — at least one of these
    # should appear depending on Instagram payload shape.
    assert (
        "messaging" in log_text
        or "messages" in log_text
    )


# ---------------------------------------------------------------------------
# 9. Unsupported Instagram field returns 200 with safe diagnostic
# ---------------------------------------------------------------------------


def test_unsupported_instagram_field_returns_200(monkeypatch, caplog):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="ig_secret",
    )
    _block_background(monkeypatch)
    caplog.set_level("WARNING")
    body = json.dumps(_INSTAGRAM_UNSUPPORTED_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("ig_secret", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    # MUST NOT 403/500 — the existing handler is allowed to no-op.
    assert resp.status_code == 200
    log_text = "\n".join(rec.message for rec in caplog.records)
    # Operator-facing warning surfaces the unsupported field.
    assert "instagram payload accepted but unsupported" in log_text
    assert "live_videos" in log_text


# ---------------------------------------------------------------------------
# 10. _summarise_payload_fields direct unit checks
# ---------------------------------------------------------------------------


def test_summarise_payload_fields_facebook():
    summary = webhook_module._summarise_payload_fields(
        _FACEBOOK_MESSAGING_PAYLOAD,
    )
    assert summary["object"] == "page"
    assert summary["entries"] == 1
    assert "messaging" in summary["fields"]
    assert summary["supported"] is True


def test_summarise_payload_fields_instagram_unsupported():
    summary = webhook_module._summarise_payload_fields(
        _INSTAGRAM_UNSUPPORTED_PAYLOAD,
    )
    assert summary["object"] == "instagram"
    assert summary["supported"] is False
    assert "live_videos" in summary["fields"]


def test_summarise_payload_fields_empty_payload():
    summary = webhook_module._summarise_payload_fields({})
    assert summary == {
        "object": "", "entries": 0, "fields": [], "supported": False,
    }


def test_summarise_payload_fields_non_dict():
    summary = webhook_module._summarise_payload_fields(["array"])
    assert summary["object"] == ""
    assert summary["entries"] == 0
