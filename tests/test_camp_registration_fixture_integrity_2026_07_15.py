from __future__ import annotations

import pytest

from app.services import admin_config_service


def _assert_camp_active_not_ended() -> None:
    status = admin_config_service.get_camp_status()
    assert status == "active"
    assert status != "ended"


def _assert_registration_closed() -> None:
    assert admin_config_service.get_camp_registration_status() == "closed"
    assert admin_config_service.is_camp_registration_open() is False


def test_default_camp_registration_lifecycle_uses_real_closed_config():
    _assert_camp_active_not_ended()
    _assert_registration_closed()


def test_named_camp_registration_open_fixture_is_explicit_opt_in(camp_registration_open):
    _assert_camp_active_not_ended()
    assert admin_config_service.get_camp_registration_status() == "open"
    assert admin_config_service.is_camp_registration_open() is True


def test_registration_status_patch_restores_to_real_closed_config():
    _assert_registration_closed()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            admin_config_service,
            "get_camp_registration_status",
            lambda: "open",
        )
        assert admin_config_service.get_camp_registration_status() == "open"
        assert admin_config_service.is_camp_registration_open() is True

    _assert_registration_closed()