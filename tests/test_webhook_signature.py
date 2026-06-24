"""Webhook signature verification tests.

Covers the X-Hub-Signature-256 HMAC enforcement added 2026-06-01:

  * `VERIFY_WEBHOOK_SIGNATURE` flag (code default True; off → skip).
  * `META_APP_SECRET` fail-open semantics (secret empty → warning +
    accept; protects legacy / local-dev / existing-test deploys).
  * Valid `sha256=<hex>` header → request accepted, background task
    scheduled.
  * Invalid digest / missing header / wrong algo prefix → 403 +
    background task NOT scheduled.
  * Constant-time compare via `hmac.compare_digest` (not `==`).
  * Privacy: no raw body, no header value, no computed digest, no
    app secret, no payload contents appear in logs.

Real Meta DSN / live Meta POST cannot be exercised here — verified by
fully-controlled HMAC fixtures.
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


# -- helpers --------------------------------------------------------------


def _swap_settings(monkeypatch, **overrides):
    """Replace the per-module `settings` reference webhook.py uses."""
    swapped = dataclasses.replace(config_module.settings, **overrides)
    monkeypatch.setattr(webhook_module, "settings", swapped)
    return swapped


def _sign(secret: str, body: bytes) -> str:
    """Produce a well-formed `sha256=<hex>` header value."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _block_background(monkeypatch):
    """Record every call to `_process_payload` (the background task)."""
    calls: list[dict] = []

    async def _fake(payload):
        calls.append(payload or {})

    monkeypatch.setattr(webhook_module, "_process_payload", _fake)
    return calls


_VALID_PAYLOAD = {
    "object": "instagram",
    "entry": [{"id": "page-x", "messaging": []}],
}


# =========================================================================
# PART 1 — Valid signature accepted
# =========================================================================


def test_valid_signature_accepts_request(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    headers = {
        "X-Hub-Signature-256": _sign("testsecret", body),
        "Content-Type": "application/json",
    }
    resp = TestClient(app).post("/webhook", content=body, headers=headers)

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert len(calls) == 1
    assert calls[0]["object"] == "instagram"


def test_valid_signature_via_messenger_app_secret_alias(monkeypatch):
    """`MESSENGER_APP_SECRET` is the historical alias — when
    `META_APP_SECRET` is empty, fallback to the alias."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="legacyalias",
    )
    calls = _block_background(monkeypatch)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("legacyalias", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)
    assert resp.status_code == 200
    assert len(calls) == 1


# =========================================================================
# PART 2 — Reject paths
# =========================================================================


def test_invalid_signature_returns_403(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    # Sign with the WRONG secret.
    headers = {"X-Hub-Signature-256": _sign("wrongsecret", body)}
    resp = TestClient(app).post("/webhook", content=body, headers=headers)

    assert resp.status_code == 403
    assert calls == []


def test_missing_header_returns_403(monkeypatch):
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    resp = TestClient(app).post("/webhook", content=body)  # no header
    assert resp.status_code == 403
    assert calls == []


def test_header_without_sha256_prefix_returns_403(monkeypatch):
    """`sha1=<hex>` (legacy Meta header) or unprefixed hex must be
    rejected — we ONLY accept `sha256=`."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    digest = hmac.new(b"testsecret", body, hashlib.sha256).hexdigest()
    for bad_header in (digest, f"sha1={digest}", "", "garbage"):
        resp = TestClient(app).post(
            "/webhook", content=body,
            headers={"X-Hub-Signature-256": bad_header},
        )
        assert resp.status_code == 403, bad_header

    assert calls == []


def test_body_tampered_after_signing_returns_403(monkeypatch):
    """A subtle tampering — extra whitespace — flips the digest."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    original = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    header = _sign("testsecret", original)
    tampered = original + b" "  # extra trailing space
    resp = TestClient(app).post(
        "/webhook", content=tampered,
        headers={"X-Hub-Signature-256": header},
    )
    assert resp.status_code == 403
    assert calls == []


# =========================================================================
# PART 3 — Fail-open shapes
# =========================================================================


def test_empty_secret_skips_verification(monkeypatch, caplog):
    """Secret missing → still accept, log ONE warning. Protects
    legacy deploys + existing test suite that never sets a secret.

    Instagram Webhook Signature Patch (2026-06-09): explicitly null
    `INSTAGRAM_APP_SECRET` too, otherwise the live `.env` value (if the
    operator has populated it for the Instagram flow) is inherited by
    `dataclasses.replace` and the multi-secret verifier finds a
    non-empty candidate, bypassing the fail-open branch this test
    exercises.
    """
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="",
        MESSENGER_APP_SECRET="",
        INSTAGRAM_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    with caplog.at_level("WARNING"):
        resp = TestClient(app).post("/webhook", content=body)

    assert resp.status_code == 200
    assert len(calls) == 1
    joined = "\n".join(r.message for r in caplog.records)
    assert "signature check skipped" in joined
    assert "META_APP_SECRET not set" in joined


def test_flag_off_skips_verification(monkeypatch, caplog):
    """`VERIFY_WEBHOOK_SIGNATURE=false` → unconditional skip, no
    warning (operator opt-out is explicit)."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=False,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    with caplog.at_level("WARNING"):
        # No header on purpose — flag off must bypass anyway.
        resp = TestClient(app).post("/webhook", content=body)

    assert resp.status_code == 200
    assert len(calls) == 1
    # Flag-off path must NOT spam the "secret missing" warning.
    joined = "\n".join(r.message for r in caplog.records)
    assert "META_APP_SECRET not set" not in joined


# =========================================================================
# PART 4 — Constant-time compare
# =========================================================================


def test_uses_constant_time_compare(monkeypatch):
    """The verification path MUST use `hmac.compare_digest` (timing-
    safe) — never raw `==` which leaks character-by-character
    comparison time and would enable a side-channel signature
    recovery attack. We tap the standard library function and
    confirm at least one call lands on it during a verification."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    _block_background(monkeypatch)

    seen: list[tuple[str, str]] = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(webhook_module.hmac, "compare_digest", spy)

    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    headers = {"X-Hub-Signature-256": _sign("testsecret", body)}
    TestClient(app).post("/webhook", content=body, headers=headers)

    assert seen, "hmac.compare_digest was never called"


# =========================================================================
# PART 5 — Privacy
# =========================================================================


def test_no_secret_or_digest_in_logs(monkeypatch, caplog):
    """Logs must never reveal the app secret, the computed digest,
    the raw body, the header value, or the payload contents — only
    the verdict (`ok` / `rejected`)."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="SUPERSECRET_DO_NOT_LEAK",
        MESSENGER_APP_SECRET="",
    )
    _block_background(monkeypatch)

    # First a rejection (will log "rejected").
    body = json.dumps(_VALID_PAYLOAD).encode("utf-8")
    with caplog.at_level("INFO"):
        TestClient(app).post(
            "/webhook", content=body,
            headers={"X-Hub-Signature-256": "sha256=deadbeef"},
        )

    serialised = "\n".join(r.message for r in caplog.records)
    assert "SUPERSECRET_DO_NOT_LEAK" not in serialised
    assert "deadbeef" not in serialised  # would expose attacker guess
    # Compute the digest to make sure we don't accidentally log the
    # ground-truth expected digest either.
    real_digest = hmac.new(
        b"SUPERSECRET_DO_NOT_LEAK", body, hashlib.sha256,
    ).hexdigest()
    assert real_digest not in serialised


# =========================================================================
# PART 6 — Malformed JSON with valid signature
# =========================================================================


def test_valid_signature_invalid_json_returns_200(monkeypatch, caplog):
    """Per the brief §B: valid-signature + invalid-JSON payload must
    behave EXACTLY as before — log the parse failure and return
    `{"status": "ok"}` (Meta retries are not desirable). Signature
    verification must succeed (we signed garbage), then the existing
    `try: json.loads` branch swallows the JSONDecodeError."""
    _swap_settings(
        monkeypatch,
        VERIFY_WEBHOOK_SIGNATURE=True,
        META_APP_SECRET="testsecret",
        MESSENGER_APP_SECRET="",
    )
    calls = _block_background(monkeypatch)

    body = b"{not-json}"
    headers = {"X-Hub-Signature-256": _sign("testsecret", body)}
    with caplog.at_level("ERROR"):
        resp = TestClient(app).post(
            "/webhook", content=body, headers=headers,
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    # Background task is NOT scheduled because the parse failed.
    assert calls == []
