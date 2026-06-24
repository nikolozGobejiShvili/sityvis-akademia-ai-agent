"""Tests for the manager email notification path.

Covers the booking-notification QA task:

  1. MANAGER_EMAIL is loaded from env into Settings.
  2. ENABLE_EMAIL_NOTIFICATIONS is loaded from env into Settings.
  3. _send_email attempts the send when enabled + MANAGER_EMAIL +
     SMTP creds are present.
  4. Missing MANAGER_EMAIL skips with a warning.
  5. ENABLE_EMAIL_NOTIFICATIONS=False skips with a warning.
  6. Missing SMTP config returns False (does not crash, does not log
     the password).
  7. Email exceptions never raise out of notify_manager — booking
     remains successful.
  8. WhatsApp failure does not block the email attempt and vice versa.
  9. Email and WhatsApp results are reported independently.

All tests pin the (frozen) settings dataclass via dataclasses.replace
to avoid mutating the global Settings instance.
"""

from __future__ import annotations

import dataclasses
import logging
import smtplib
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.models.lead import Lead
from app.services import notification_service


def _settings_with(**overrides) -> Settings:
    return dataclasses.replace(notification_service.settings, **overrides)


def _lead() -> Lead:
    return Lead(
        sender_id="test-sender-1",
        platform="instagram",
        segment="PARENT",
        name="ნიკოლოზი",
        phone="595999733",
        child_age="10",
        challenge="ეკრანისგან დისტანცია",
        calendly_booked=True,
        conversation_summary="ტესტი — booking notification QA",
        status="Booked",
    )


# --- (1) MANAGER_EMAIL is exposed on Settings -----------------------------


def test_settings_has_manager_email_field():
    s = _settings_with(MANAGER_EMAIL="ops@example.com")
    assert s.MANAGER_EMAIL == "ops@example.com"
    # Field must exist on the dataclass (catches accidental removal).
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert "MANAGER_EMAIL" in fields


# --- (2) ENABLE_EMAIL_NOTIFICATIONS exists on Settings (default True) -----


def test_settings_has_enable_email_notifications_field():
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert "ENABLE_EMAIL_NOTIFICATIONS" in fields
    # Default must be True so existing deployments with SMTP configured
    # keep sending emails after this change.
    bare = Settings()
    assert bare.ENABLE_EMAIL_NOTIFICATIONS is True
    # Flip works.
    s_off = _settings_with(ENABLE_EMAIL_NOTIFICATIONS=False)
    assert s_off.ENABLE_EMAIL_NOTIFICATIONS is False


# --- (2b) SMTP_FROM_EMAIL exists and falls back to SMTP_USER --------------


def test_settings_has_smtp_from_email_field():
    fields = {f.name for f in dataclasses.fields(Settings)}
    assert "SMTP_FROM_EMAIL" in fields
    assert Settings().SMTP_FROM_EMAIL == ""


# --- (3) Successful send attempt when fully configured --------------------


def test_send_email_attempts_when_fully_configured(monkeypatch, caplog):
    monkeypatch.setattr(
        notification_service, "settings",
        _settings_with(
            ENABLE_EMAIL_NOTIFICATIONS=True,
            MANAGER_EMAIL="manager@example.com",
            SMTP_HOST="smtp.gmail.com",
            SMTP_PORT=587,
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="app-password-here",
            SMTP_FROM_EMAIL="sender@example.com",
        ),
    )

    smtp_instance = MagicMock()
    smtp_cls = MagicMock(return_value=MagicMock(
        __enter__=MagicMock(return_value=smtp_instance),
        __exit__=MagicMock(return_value=False),
    ))
    monkeypatch.setattr(smtplib, "SMTP", smtp_cls)

    with caplog.at_level(logging.INFO):
        ok = notification_service._send_email("Subject", "Body")

    assert ok is True
    smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=15)
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with(
        "sender@example.com", "app-password-here",
    )
    smtp_instance.send_message.assert_called_once()
    # Password must never appear in the captured log records.
    for record in caplog.records:
        assert "app-password-here" not in record.getMessage()


# --- (4) MANAGER_EMAIL missing → skip with warning ------------------------


def test_send_email_skipped_when_manager_email_missing(monkeypatch, caplog):
    monkeypatch.setattr(
        notification_service, "settings",
        _settings_with(
            ENABLE_EMAIL_NOTIFICATIONS=True,
            MANAGER_EMAIL="",
            SMTP_HOST="smtp.gmail.com",
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="x",
        ),
    )

    smtp_cls = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", smtp_cls)

    with caplog.at_level(logging.WARNING):
        ok = notification_service._send_email("Subject", "Body")

    assert ok is False
    smtp_cls.assert_not_called()
    assert any(
        "MANAGER_EMAIL missing" in r.getMessage() for r in caplog.records
    )


# --- (5) ENABLE_EMAIL_NOTIFICATIONS=False → skip --------------------------


def test_send_email_skipped_when_flag_off(monkeypatch, caplog):
    monkeypatch.setattr(
        notification_service, "settings",
        _settings_with(
            ENABLE_EMAIL_NOTIFICATIONS=False,
            MANAGER_EMAIL="manager@example.com",
            SMTP_HOST="smtp.gmail.com",
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="x",
        ),
    )

    smtp_cls = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", smtp_cls)

    with caplog.at_level(logging.WARNING):
        ok = notification_service._send_email("Subject", "Body")

    assert ok is False
    smtp_cls.assert_not_called()
    assert any(
        "ENABLE_EMAIL_NOTIFICATIONS=false" in r.getMessage()
        for r in caplog.records
    )


# --- (6) Missing SMTP config → False, no crash, no password in log --------


@pytest.mark.parametrize(
    "missing_field",
    ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"],
)
def test_send_email_skipped_when_smtp_missing(monkeypatch, caplog, missing_field):
    overrides = dict(
        ENABLE_EMAIL_NOTIFICATIONS=True,
        MANAGER_EMAIL="manager@example.com",
        SMTP_HOST="smtp.gmail.com",
        SMTP_USER="sender@example.com",
        SMTP_PASSWORD="super-secret-pw",
    )
    overrides[missing_field] = ""
    monkeypatch.setattr(
        notification_service, "settings", _settings_with(**overrides),
    )

    smtp_cls = MagicMock()
    monkeypatch.setattr(smtplib, "SMTP", smtp_cls)

    with caplog.at_level(logging.WARNING):
        ok = notification_service._send_email("Subject", "Body")

    assert ok is False
    smtp_cls.assert_not_called()
    assert any(
        "missing SMTP config" in r.getMessage() for r in caplog.records
    )
    # Password must never appear in logs even when partial config is set.
    for r in caplog.records:
        assert "super-secret-pw" not in r.getMessage()


# --- (7) SMTP auth failure → clear Gmail App Password message -------------


def test_send_email_gmail_app_password_hint_on_auth_error(monkeypatch, caplog):
    monkeypatch.setattr(
        notification_service, "settings",
        _settings_with(
            ENABLE_EMAIL_NOTIFICATIONS=True,
            MANAGER_EMAIL="manager@example.com",
            SMTP_HOST="smtp.gmail.com",
            SMTP_PORT=587,
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="wrong-pw",
        ),
    )

    fake_smtp = MagicMock()
    fake_smtp.login.side_effect = smtplib.SMTPAuthenticationError(
        535, b"5.7.8 Username and Password not accepted",
    )
    smtp_ctx = MagicMock(
        __enter__=MagicMock(return_value=fake_smtp),
        __exit__=MagicMock(return_value=False),
    )
    monkeypatch.setattr(smtplib, "SMTP", MagicMock(return_value=smtp_ctx))

    with caplog.at_level(logging.ERROR):
        ok = notification_service._send_email("Subject", "Body")

    assert ok is False
    assert any(
        "Gmail App Password required" in r.getMessage()
        for r in caplog.records
    )


# --- (8) Email exception does not raise out of notify_manager -------------


def test_notify_manager_swallows_email_failure(monkeypatch):
    monkeypatch.setattr(
        notification_service, "settings",
        _settings_with(
            ENABLE_EMAIL_NOTIFICATIONS=True,
            MANAGER_EMAIL="manager@example.com",
            SMTP_HOST="smtp.gmail.com",
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="x",
            MANAGER_WHATSAPP_NUMBER="",
            WHATSAPP_TOKEN="",
        ),
    )

    monkeypatch.setattr(
        notification_service, "_send_email",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(
        notification_service, "_send_manager_whatsapp",
        MagicMock(return_value=False),
    )

    # Must not raise.
    result = notification_service.notify_manager(_lead(), "lead")
    assert result is False


# --- (9) WhatsApp failure does not block email attempt --------------------


def test_notify_manager_runs_email_when_whatsapp_fails(monkeypatch):
    monkeypatch.setattr(
        notification_service, "settings",
        _settings_with(
            ENABLE_EMAIL_NOTIFICATIONS=True,
            MANAGER_EMAIL="manager@example.com",
            SMTP_HOST="smtp.gmail.com",
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="x",
        ),
    )

    email_mock = MagicMock(return_value=True)
    whatsapp_mock = MagicMock(side_effect=RuntimeError("network down"))
    monkeypatch.setattr(notification_service, "_send_email", email_mock)
    monkeypatch.setattr(
        notification_service, "_send_manager_whatsapp", whatsapp_mock,
    )

    result = notification_service.notify_manager(_lead(), "lead")

    email_mock.assert_called_once()
    whatsapp_mock.assert_called_once()
    # Whatsapp failed → overall result is False, but email_ok was True.
    assert result is False


# --- (10) Email + WhatsApp results are reported independently in logs -----


def test_notify_manager_logs_independent_results(monkeypatch, caplog):
    monkeypatch.setattr(
        notification_service, "settings",
        _settings_with(
            ENABLE_EMAIL_NOTIFICATIONS=True,
            MANAGER_EMAIL="manager@example.com",
            SMTP_HOST="smtp.gmail.com",
            SMTP_USER="sender@example.com",
            SMTP_PASSWORD="x",
            MANAGER_WHATSAPP_NUMBER="",
        ),
    )

    monkeypatch.setattr(
        notification_service, "_send_email", MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        notification_service, "_send_manager_whatsapp",
        MagicMock(return_value=False),
    )

    with caplog.at_level(logging.INFO):
        notification_service.notify_manager(_lead(), "lead")

    messages = [r.getMessage() for r in caplog.records]
    assert any("email_ok=True" in m for m in messages)
    assert any("whatsapp_ok=False" in m for m in messages)
    assert any("[notification] manager notification start" in m for m in messages)
    assert any("[notification] email result=True" in m for m in messages)
    assert any("[notification] webhook/WhatsApp result=False" in m for m in messages)
