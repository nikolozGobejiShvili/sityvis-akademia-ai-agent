"""Phase 0b — admin-config persistence via an OVERLAY model (Railway volume).

Task 1: env-override config-dir resolution (`ADMIN_CONFIG_DIR`).
"""


def test_resolve_admin_config_dir_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_CONFIG_DIR", raising=False)
    from app.services import admin_config_service as acs
    assert acs._resolve_admin_config_dir() == acs._DEFAULT_ADMIN_CONFIG_DIR


def test_resolve_admin_config_dir_uses_env_override(monkeypatch, tmp_path):
    from pathlib import Path
    monkeypatch.setenv("ADMIN_CONFIG_DIR", str(tmp_path / "vol"))
    from app.services import admin_config_service as acs
    assert acs._resolve_admin_config_dir() == Path(str(tmp_path / "vol"))
