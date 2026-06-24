"""Railway-safe Google credential loading (2026-06-13).

Covers `app.services.google_credentials.load_google_credentials` and its use
by BOTH the Sheets (`_sheets_client`) and Calendar (`_calendar_service`)
clients. All credential loading is MOCKED — no real service account is read,
no network, no Google API call.

Scenarios:
  1. GOOGLE_CREDENTIALS_JSON set            → from_service_account_info.
  2. GOOGLE_APPLICATION_CREDENTIALS set     → from_service_account_file.
  3. Both set                               → env JSON wins; file NOT used.
  4. Neither set                            → clear, secret-free error.
  5. Applies to both clients                → Sheets + Calendar use env JSON.
  6. No credential contents logged / leaked → caplog + error message clean.
Plus: escaped-newline repair in private_key; per-service file_value (inline
JSON / path) fallback.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.services import google_credentials as gc


# A fake service-account document. `from_service_account_*` is always mocked,
# so the values never need to be real.
_FAKE_SA = {
    "type": "service_account",
    "project_id": "proj",
    "private_key_id": "kid",
    "private_key": "-----BEGIN PRIVATE KEY-----\nFAKELINE1\nFAKELINE2\n-----END PRIVATE KEY-----\n",
    "client_email": "fake-sa@proj.iam.gserviceaccount.com",
    "client_id": "123",
    "token_uri": "https://oauth2.googleapis.com/token",
}
_FAKE_SA_JSON = json.dumps(_FAKE_SA)


@pytest.fixture
def clean_google_env(monkeypatch):
    """Start each test with NO Google env vars (the dev's real .env may set
    them via load_dotenv at config import)."""
    monkeypatch.delenv("GOOGLE_CREDENTIALS_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    yield


@pytest.fixture
def mock_loaders(monkeypatch):
    """Mock both service_account loaders; record calls. Returns the call log."""
    calls = {"info": [], "file": []}

    def _info(info, scopes):
        calls["info"].append((info, list(scopes)))
        return "INFO_CREDS"

    def _file(path, scopes):
        calls["file"].append((path, list(scopes)))
        return "FILE_CREDS"

    monkeypatch.setattr(
        gc.service_account.Credentials, "from_service_account_info", _info,
    )
    monkeypatch.setattr(
        gc.service_account.Credentials, "from_service_account_file", _file,
    )
    return calls


# ---------------------------------------------------------------------------
# 1–4: the four resolution scenarios
# ---------------------------------------------------------------------------


def test_1_env_json_uses_from_service_account_info(
    monkeypatch, clean_google_env, mock_loaders,
):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", _FAKE_SA_JSON)
    creds = gc.load_google_credentials(["scopeA"])
    assert creds == "INFO_CREDS"
    assert len(mock_loaders["info"]) == 1
    assert mock_loaders["file"] == []
    parsed_info, scopes = mock_loaders["info"][0]
    assert parsed_info["client_email"] == _FAKE_SA["client_email"]  # json.loads ran
    assert scopes == ["scopeA"]


def test_2_app_creds_path_uses_from_service_account_file(
    monkeypatch, clean_google_env, mock_loaders,
):
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/sa-cred.json")
    creds = gc.load_google_credentials(["scopeA"])
    assert creds == "FILE_CREDS"
    assert len(mock_loaders["file"]) == 1
    assert mock_loaders["info"] == []


def test_3_both_set_env_json_wins(monkeypatch, clean_google_env, mock_loaders):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", _FAKE_SA_JSON)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/tmp/sa-cred.json")
    creds = gc.load_google_credentials(["scopeA"])
    assert creds == "INFO_CREDS"
    assert len(mock_loaders["info"]) == 1
    assert mock_loaders["file"] == []  # file path ignored when env JSON present


def test_4_neither_set_raises_clear_error(
    monkeypatch, clean_google_env, mock_loaders,
):
    with pytest.raises(RuntimeError) as exc:
        gc.load_google_credentials(["scopeA"])
    msg = str(exc.value)
    assert "GOOGLE_CREDENTIALS_JSON" in msg
    assert "GOOGLE_APPLICATION_CREDENTIALS" in msg
    assert mock_loaders["info"] == []
    assert mock_loaders["file"] == []


# ---------------------------------------------------------------------------
# per-service file_value fallback (path / inline JSON)
# ---------------------------------------------------------------------------


def test_file_value_inline_json_uses_info(
    monkeypatch, clean_google_env, mock_loaders,
):
    creds = gc.load_google_credentials(["scopeA"], file_value=_FAKE_SA_JSON)
    assert creds == "INFO_CREDS"
    assert len(mock_loaders["info"]) == 1
    assert mock_loaders["file"] == []


def test_file_value_path_uses_file(monkeypatch, clean_google_env, mock_loaders):
    creds = gc.load_google_credentials(["scopeA"], file_value="./credentials.json")
    assert creds == "FILE_CREDS"
    assert len(mock_loaders["file"]) == 1
    assert mock_loaders["info"] == []


def test_env_json_beats_file_value(monkeypatch, clean_google_env, mock_loaders):
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", _FAKE_SA_JSON)
    gc.load_google_credentials(["scopeA"], file_value="./credentials.json")
    assert len(mock_loaders["info"]) == 1
    assert mock_loaders["file"] == []  # GOOGLE_CREDENTIALS_JSON wins over path


# ---------------------------------------------------------------------------
# escaped-newline repair
# ---------------------------------------------------------------------------


def test_private_key_escaped_newlines_repaired():
    # Simulate the Railway double-escape: private_key carries literal `\n`.
    info_in = dict(_FAKE_SA)
    info_in["private_key"] = (
        "-----BEGIN PRIVATE KEY-----\\nLINE1\\nLINE2\\n-----END PRIVATE KEY-----\\n"
    )
    raw = json.dumps(info_in)
    out = gc._parse_service_account_json(raw)
    assert "\\n" not in out["private_key"]   # no literal backslash-n remains
    assert "\n" in out["private_key"]         # real newlines present
    assert out["private_key"].count("\n") == 4


def test_private_key_real_newlines_left_intact():
    out = gc._parse_service_account_json(_FAKE_SA_JSON)
    assert out["private_key"] == _FAKE_SA["private_key"]  # unchanged (no-op)


# ---------------------------------------------------------------------------
# 5: applies to BOTH clients
# ---------------------------------------------------------------------------


def test_5a_sheets_client_uses_env_json(
    monkeypatch, clean_google_env, mock_loaders,
):
    from app.services import sheets_service
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", _FAKE_SA_JSON)
    authorized = {}

    def _fake_authorize(creds):
        authorized["creds"] = creds
        return "SHEETS_CLIENT"

    monkeypatch.setattr(sheets_service.gspread, "authorize", _fake_authorize)
    client = sheets_service._sheets_client()
    assert client == "SHEETS_CLIENT"
    assert authorized["creds"] == "INFO_CREDS"           # from env JSON
    assert len(mock_loaders["info"]) == 1
    assert mock_loaders["file"] == []
    assert mock_loaders["info"][0][1] == sheets_service.SHEETS_SCOPES


def test_5b_calendar_service_uses_env_json(
    monkeypatch, clean_google_env, mock_loaders,
):
    from app.services import calendar_service
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", _FAKE_SA_JSON)
    built = {}
    monkeypatch.setattr(
        calendar_service, "build",
        lambda *a, **k: built.update(args=a, kwargs=k) or "CAL_SVC",
    )
    svc = calendar_service._calendar_service()
    assert svc == "CAL_SVC"
    assert built["kwargs"].get("credentials") == "INFO_CREDS"  # from env JSON
    assert len(mock_loaders["info"]) == 1
    assert mock_loaders["file"] == []
    assert mock_loaders["info"][0][1] == [calendar_service.CALENDAR_SCOPE]


# ---------------------------------------------------------------------------
# 6: no credential contents logged / leaked
# ---------------------------------------------------------------------------


def test_6_no_credential_contents_logged(
    monkeypatch, clean_google_env, mock_loaders, caplog,
):
    secret_key = (
        "-----BEGIN PRIVATE KEY-----\\nSUPER_SECRET_KEY_SENTINEL\\n-----END-----\\n"
    )
    info = dict(
        _FAKE_SA,
        private_key=secret_key,
        client_email="leaky-sa@proj.iam.gserviceaccount.com",
        private_key_id="SECRET_KID_SENTINEL",
    )
    raw = json.dumps(info)
    monkeypatch.setenv("GOOGLE_CREDENTIALS_JSON", raw)
    with caplog.at_level(logging.DEBUG):
        gc.load_google_credentials(["scopeA"])
    text = caplog.text
    for sentinel in (
        "SUPER_SECRET_KEY_SENTINEL",
        "leaky-sa@proj.iam",
        "SECRET_KID_SENTINEL",
        "BEGIN PRIVATE KEY",
    ):
        assert sentinel not in text


def test_6b_error_message_leaks_no_secret(monkeypatch, clean_google_env):
    with pytest.raises(RuntimeError) as exc:
        gc.load_google_credentials(["scopeA"])
    msg = str(exc.value)
    assert "private_key" not in msg.lower()
    assert "BEGIN" not in msg
    assert "@" not in msg  # no client_email
