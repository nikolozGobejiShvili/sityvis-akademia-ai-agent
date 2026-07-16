from __future__ import annotations

import dataclasses
import inspect
import smtplib
from pathlib import Path

import pytest

from app.config import Settings
from app.models.lead import Lead
from app.services import notification_service


OBSERVED_PHONE_SENTINEL = "599123456"


def _settings_with(**overrides) -> Settings:
    return dataclasses.replace(notification_service.settings, **overrides)


def _configured_email_settings() -> Settings:
    return _settings_with(
        ENABLE_EMAIL_NOTIFICATIONS=True,
        MANAGER_EMAIL="manager@example.com",
        SMTP_HOST="smtp.example.com",
        SMTP_PORT=587,
        SMTP_USER="sender@example.com",
        SMTP_PASSWORD="test-password",
        SMTP_FROM_EMAIL="sender@example.com",
        MANAGER_WHATSAPP_NUMBER="",
        WHATSAPP_TOKEN="",
    )


class FakeEmailTransport:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, email, smtp_host, smtp_port, smtp_user, smtp_password) -> None:
        self.calls.append({
            "email": email,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_user": smtp_user,
            "smtp_password": smtp_password,
        })


def _sunday_school_lead() -> Lead:
    return Lead(
        sender_id="observed-ss-test",
        platform="instagram",
        segment="PARENT",
        name="Test Parent",
        phone=OBSERVED_PHONE_SENTINEL,
    )


def _parent_lead() -> Lead:
    return Lead(
        sender_id="observed-parent-test",
        platform="instagram",
        segment="PARENT",
        name="Test Parent",
        phone=OBSERVED_PHONE_SENTINEL,
        child_age="10",
        challenge="test interest",
        status="Qualified",
    )


def _body(call: dict) -> str:
    return call["email"].get_content()


def test_observed_sunday_school_payload_uses_fake_sender(monkeypatch):
    fake = FakeEmailTransport()
    monkeypatch.setattr(notification_service, "settings", _configured_email_settings())
    monkeypatch.setattr(notification_service, "_email_transport", fake)

    ok = notification_service.notify_sunday_school_handoff(_sunday_school_lead())

    assert ok is True
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["smtp_host"] == "smtp.example.com"
    assert call["email"]["To"] == "manager@example.com"
    assert "sunday_school" in _body(call)
    assert "instagram" in _body(call)
    assert "PARENT" in _body(call)
    assert OBSERVED_PHONE_SENTINEL in _body(call)


def test_real_email_transport_is_forbidden_by_default(monkeypatch):
    monkeypatch.setattr(notification_service, "settings", _configured_email_settings())

    with pytest.raises(notification_service.ExternalEmailDeliveryBlocked):
        notification_service._send_email("Subject", "Body")


def test_sunday_school_handoff_does_not_silently_swallow_blocked_transport(monkeypatch):
    monkeypatch.setattr(notification_service, "settings", _configured_email_settings())

    with pytest.raises(notification_service.ExternalEmailDeliveryBlocked):
        notification_service.notify_sunday_school_handoff(_sunday_school_lead())


def test_manager_notification_payload_contract_uses_fake_transport(monkeypatch):
    fake = FakeEmailTransport()
    monkeypatch.setattr(notification_service, "settings", _configured_email_settings())
    monkeypatch.setattr(notification_service, "_email_transport", fake)
    monkeypatch.setattr(notification_service, "_send_manager_whatsapp", lambda text: False)

    ok = notification_service.send_manager_notification(_parent_lead(), "summary")

    assert ok is True
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["email"]["From"] == "sender@example.com"
    assert call["email"]["To"] == "manager@example.com"
    assert "Test" in call["email"]["Subject"]
    body = _body(call)
    assert "instagram" in body
    assert "PARENT" in body
    assert OBSERVED_PHONE_SENTINEL in body


def test_zero_delivery_when_notification_config_is_incomplete(monkeypatch):
    fake = FakeEmailTransport()
    monkeypatch.setattr(
        notification_service,
        "settings",
        dataclasses.replace(_configured_email_settings(), MANAGER_EMAIL=""),
    )
    monkeypatch.setattr(notification_service, "_email_transport", fake)

    ok = notification_service._send_email("Subject", "Body")

    assert ok is False
    assert fake.calls == []


def test_multiple_fake_executions_never_use_real_transport(monkeypatch):
    fake = FakeEmailTransport()
    monkeypatch.setattr(notification_service, "settings", _configured_email_settings())
    monkeypatch.setattr(notification_service, "_email_transport", fake)

    assert notification_service.notify_sunday_school_handoff(_sunday_school_lead()) is True
    assert notification_service.notify_sunday_school_handoff(_sunday_school_lead()) is True

    assert len(fake.calls) == 2
    assert all(call["smtp_host"] == "smtp.example.com" for call in fake.calls)


def test_direct_smtplib_use_is_forbidden_under_test_guard():
    with pytest.raises(notification_service.ExternalEmailDeliveryBlocked):
        smtplib.SMTP("smtp.example.com", 587)


def test_notification_service_has_single_email_transport_boundary():
    send_src = inspect.getsource(notification_service._send_email)
    smtp_src = inspect.getsource(notification_service._smtp_email_transport)

    assert "_email_transport(" in send_src
    assert "smtplib.SMTP(" not in send_src
    assert "smtplib.SMTP(" in smtp_src
    assert notification_service._email_transport is not notification_service._smtp_email_transport


def test_conftest_uses_fail_loud_email_guard_not_inert_smtp():
    conftest_src = Path("tests/conftest.py").read_text(encoding="utf-8")

    assert "def _block_real_email_delivery" in conftest_src
    assert "ExternalEmailDeliveryBlocked" in conftest_src
    assert "_InertSMTP" not in conftest_src
    assert "def _block_real_smtp" not in conftest_src
