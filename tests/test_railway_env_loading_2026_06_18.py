"""Railway readiness — env loading, secrets protection, deploy deps (2026-06-18).

Pre-deploy (NO deploy in this task). Covers the Railway blockers:

  * `config._env` now reads `os.environ` FIRST, `.env` fallback second
    (Railway injects dashboard vars into `os.environ`; there is no `.env`
    file in the container — the old `.env`-only read crashed boot).
  * `REDIS_URL` loads from `os.environ`, with `.env` fallback; missing
    URL is a safe no-op (in-memory fallback, no crash).
  * `GOOGLE_CREDENTIALS_JSON` creds loader still reads `os.environ`
    (Railway-safe), local file fallback preserved.
  * `LIVE_BROADCAST_ENABLED` readable from env (staging expects False).
  * `requirements.txt` includes `redis` / `tzdata` / `python-multipart`.
  * `.gitignore` / `.railwayignore` cover `.env` + credential files.
  * No secret values are logged (Redis URL masked; creds error secret-free).
  * WhatsApp readiness is audited mocked-only (no real send).
  * Follow-up readiness: Redis-disabled is safe.

All tests are offline — no real Redis / Calendar / Sheets / Meta / email /
network. No live integrations touched.
"""

from __future__ import annotations

import dataclasses
import inspect
import pathlib

import pytest

import app.config as config


ROOT = pathlib.Path(__file__).resolve().parent.parent  # ai-agent/


# =========================================================================
# _env resolution order — os.environ first, .env fallback.
# =========================================================================


def test_os_environ_beats_dotenv(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {"RAILWAY_PROBE": "from_dotenv"})
    monkeypatch.setenv("RAILWAY_PROBE", "from_environ")
    assert config._env("RAILWAY_PROBE") == "from_environ"


def test_dotenv_fallback_when_not_in_environ(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {"RAILWAY_PROBE": "from_dotenv"})
    monkeypatch.delenv("RAILWAY_PROBE", raising=False)
    assert config._env("RAILWAY_PROBE") == "from_dotenv"


def test_empty_environ_value_falls_back_to_dotenv(monkeypatch):
    """An empty/blank process var must not shadow a real .env value."""
    monkeypatch.setattr(config, "ENV_VALUES", {"RAILWAY_PROBE": "from_dotenv"})
    monkeypatch.setenv("RAILWAY_PROBE", "")
    assert config._env("RAILWAY_PROBE") == "from_dotenv"


def test_missing_var_returns_empty_string(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {})
    monkeypatch.delenv("RAILWAY_PROBE", raising=False)
    assert config._env("RAILWAY_PROBE") == ""


def test_env_value_is_stripped(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {})
    monkeypatch.setenv("RAILWAY_PROBE", "  spaced  ")
    assert config._env("RAILWAY_PROBE") == "spaced"


# =========================================================================
# REDIS_URL — Railway env + .env fallback + safe-missing.
# =========================================================================


def test_redis_url_from_os_environ(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {})
    monkeypatch.setenv("REDIS_URL", "redis://railway-host:6379/0")
    assert config._env("REDIS_URL") == "redis://railway-host:6379/0"


def test_redis_url_dotenv_fallback(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {"REDIS_URL": "redis://localhost:6379"})
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert config._env("REDIS_URL") == "redis://localhost:6379"


def test_settings_from_env_picks_up_redis_url(monkeypatch):
    """End-to-end: a Railway-injected REDIS_URL reaches Settings."""
    monkeypatch.setenv("REDIS_URL", "redis://railway-host:6379/0")
    s = config.Settings.from_env()
    assert s.REDIS_URL == "redis://railway-host:6379/0"


def test_missing_redis_url_is_safe_no_crash(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {})
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert config._env("REDIS_URL") == ""

    from app.services import redis_state_service as r
    # Flag ON but URL empty → disabled, in-memory fallback, never connects.
    swapped = dataclasses.replace(r.settings, REDIS_URL="", REDIS_ENABLED=True)
    monkeypatch.setattr(r, "settings", swapped)
    assert r.is_enabled() is False


# =========================================================================
# GOOGLE credentials — Railway-safe env read not regressed.
# =========================================================================


def test_google_credentials_env_reads_os_environ(monkeypatch):
    from app.services import google_credentials as gc
    monkeypatch.setenv("GC_PROBE", "value-from-environ")
    assert gc._env("GC_PROBE") == "value-from-environ"
    monkeypatch.delenv("GC_PROBE", raising=False)
    assert gc._env("GC_PROBE") == ""


def test_google_credentials_json_env_path_wins(monkeypatch):
    """GOOGLE_CREDENTIALS_JSON (os.environ) is used and `\\n` is repaired,
    without a real Google call."""
    from app.services import google_credentials as gc

    captured = {}

    class _FakeCreds:
        pass

    def _from_info(info, scopes=None):
        captured["info"] = info
        return _FakeCreds()

    monkeypatch.setattr(
        gc.service_account.Credentials, "from_service_account_info", _from_info,
    )
    monkeypatch.setenv(
        "GOOGLE_CREDENTIALS_JSON",
        '{"type":"service_account","private_key":"-----BEGIN-----\\nKEY\\n-----END-----","client_email":"x@y.z"}',
    )
    creds = gc.load_google_credentials(["scope1"], file_value="./credentials.json")
    assert isinstance(creds, _FakeCreds)
    # Escaped \n repaired to real newlines so the PEM is valid.
    assert "\\n" not in captured["info"]["private_key"]
    assert "\n" in captured["info"]["private_key"]


def test_google_credentials_local_file_fallback(monkeypatch):
    """With no env JSON, a path file_value resolves to a file load."""
    from app.services import google_credentials as gc

    monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
    captured = {}

    class _FakeCreds:
        pass

    def _from_file(path, scopes=None):
        captured["path"] = path
        return _FakeCreds()

    monkeypatch.setattr(
        gc.service_account.Credentials, "from_service_account_file", _from_file,
    )
    creds = gc.load_google_credentials(["scope1"], file_value="credentials.json")
    assert isinstance(creds, _FakeCreds)
    assert str(captured["path"]).endswith("credentials.json")


# =========================================================================
# LIVE_BROADCAST_ENABLED — readable from env; staging default False.
# =========================================================================


def test_live_broadcast_enabled_reads_env_true(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {})
    monkeypatch.setenv("LIVE_BROADCAST_ENABLED", "true")
    assert config._parse_bool_optional("LIVE_BROADCAST_ENABLED", False) is True


def test_live_broadcast_enabled_defaults_false(monkeypatch):
    monkeypatch.setattr(config, "ENV_VALUES", {})
    monkeypatch.delenv("LIVE_BROADCAST_ENABLED", raising=False)
    assert config._parse_bool_optional("LIVE_BROADCAST_ENABLED", False) is False


# =========================================================================
# Dependencies / ignore files.
# =========================================================================


@pytest.mark.parametrize("dep", ["redis", "tzdata", "python-multipart"])
def test_requirements_include_runtime_deps(dep):
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert dep in reqs, f"requirements.txt is missing runtime dep: {dep}"


def test_gitignore_covers_secrets():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi
    assert ("credentials.json" in gi) or ("*credentials*.json" in gi)
    assert "!.env.example" in gi  # template stays tracked


def test_railwayignore_covers_secrets():
    ri = (ROOT / ".railwayignore").read_text(encoding="utf-8")
    assert ".env" in ri
    assert ("credentials.json" in ri) or ("*credentials*.json" in ri)


# =========================================================================
# No secret values logged.
# =========================================================================


def test_redis_url_never_logged_in_clear(monkeypatch):
    from app.services import redis_state_service as r
    swapped = dataclasses.replace(
        r.settings, REDIS_URL="redis://user:supersecretpw@host:6379",
    )
    monkeypatch.setattr(r, "settings", swapped)
    masked = r._safe_url_log_value()
    assert masked in {"True", "False"}
    assert "supersecretpw" not in masked


def test_google_creds_error_is_secret_free():
    from app.services import google_credentials as gc
    assert "private_key" not in gc._NOT_CONFIGURED_MSG
    assert "BEGIN" not in gc._NOT_CONFIGURED_MSG


def test_config_module_does_not_log_env_values():
    """config.py must not emit env values — it imports no logging at all."""
    src = inspect.getsource(config)
    assert "import logging" not in src


# =========================================================================
# WhatsApp readiness — audit only, mocked (NO real send).
# =========================================================================


def test_whatsapp_skipped_when_unconfigured(monkeypatch):
    """Unconfigured WhatsApp short-circuits to False before any network."""
    from app.services import notification_service as n
    swapped = dataclasses.replace(n.settings, WHATSAPP_TOKEN="")
    monkeypatch.setattr(n, "settings", swapped)
    assert n._send_manager_whatsapp("body") is False


def test_email_dispatch_works_when_whatsapp_unconfigured(monkeypatch):
    """Manager handoff still succeeds via email alone when WhatsApp is off."""
    from app.models.lead import Lead
    from app.services import notification_service as n

    monkeypatch.setattr(n, "_send_email", lambda subject, body: True)
    monkeypatch.setattr(n, "_send_manager_whatsapp", lambda body: False)
    lead = Lead(sender_id="s1", platform="instagram", segment="PARENT",
                name="ნიკოლოზი", phone="595999733")
    assert n.notify_manager_handoff(lead, "reason") is True


# =========================================================================
# Follow-up readiness — audit only, mocked.
# =========================================================================


def test_followup_redis_disabled_is_safe(monkeypatch):
    """Follow-up state falls back to memory safely when Redis is off."""
    from app.services import redis_state_service as r
    swapped = dataclasses.replace(r.settings, REDIS_URL="", REDIS_ENABLED=True)
    monkeypatch.setattr(r, "settings", swapped)
    assert r.is_enabled() is False  # no URL → safe no-op, no crash
