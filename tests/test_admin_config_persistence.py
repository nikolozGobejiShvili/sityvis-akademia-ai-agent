"""Phase 0b — admin-config persistence via an OVERLAY model (Railway volume).

Task 1: env-override config-dir resolution (`ADMIN_CONFIG_DIR`).
Task 2: read-overlay fallback (volume-then-default) — the C1/H2 fix.
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


def test_read_overlay_uses_volume_when_present(monkeypatch, tmp_path):
    from app.services import admin_config_service as acs
    src = tmp_path / "defaults"; src.mkdir()
    (src / "sections.yaml").write_text("sections: [DEFAULT]\n", encoding="utf-8")
    vol = tmp_path / "vol"; vol.mkdir()
    (vol / "sections.yaml").write_text("sections: [VOLUME]\n", encoding="utf-8")
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", src)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", vol)
    assert acs._config_read_path(vol / "sections.yaml") == vol / "sections.yaml"


def test_read_overlay_falls_back_to_default_when_volume_missing(monkeypatch, tmp_path):
    # C1: a fresh/empty volume must fall back to the repo default (never empty)
    from app.services import admin_config_service as acs
    src = tmp_path / "defaults"; src.mkdir()
    (src / "sections.yaml").write_text("sections: [DEFAULT]\n", encoding="utf-8")
    vol = tmp_path / "vol"; vol.mkdir()  # empty volume
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", src)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", vol)
    assert acs._config_read_path(vol / "sections.yaml") == src / "sections.yaml"


def test_read_overlay_noop_when_env_unset(monkeypatch, tmp_path):
    from app.services import admin_config_service as acs
    d = tmp_path / "same"; d.mkdir()
    p = d / "sections.yaml"  # missing
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", d)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", d)  # == default → no overlay
    assert acs._config_read_path(p) == p


def test_load_sections_falls_back_to_default_on_empty_volume(monkeypatch, tmp_path):
    # integration: load_sections must return the 3 built-ins via the read-fallback
    from app.services import admin_config_service as acs
    src = tmp_path / "defaults"; src.mkdir()
    (src / "sections.yaml").write_text(
        "sections:\n  - id: summer_camp\n    status: active\n", encoding="utf-8")
    vol = tmp_path / "vol"; vol.mkdir()  # empty
    monkeypatch.setattr(acs, "_DEFAULT_ADMIN_CONFIG_DIR", src)
    monkeypatch.setattr(acs, "ADMIN_CONFIG_DIR", vol)
    monkeypatch.setattr(acs, "SECTIONS_PATH", vol / "sections.yaml")
    ids = {s.get("id") for s in acs.load_sections()}
    assert "summer_camp" in ids  # never empty despite the empty volume
