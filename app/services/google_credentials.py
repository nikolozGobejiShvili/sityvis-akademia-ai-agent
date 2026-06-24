"""Railway-safe Google service-account credential loading.

A single resolver used by BOTH the Sheets and Calendar clients so the auth
logic lives in one place (no duplication). Resolution priority:

  1. ``GOOGLE_CREDENTIALS_JSON`` (process env) — the full service-account
     JSON as one env var. The Railway-safe path: Railway injects variables
     into ``os.environ`` (there is no ``.env`` file on the box), so this is
     read straight from ``os.environ``. Wins over everything.
  2. ``file_value`` — the per-service setting
     (``GOOGLE_SHEETS_CREDENTIALS_JSON`` / ``GOOGLE_CALENDAR_CREDENTIALS_JSON``),
     which may itself be inline JSON (starts with ``{``) or a file path.
     Preserves the existing local behaviour.
  3. ``GOOGLE_APPLICATION_CREDENTIALS`` (process env) — a credentials file
     path. The documented local fallback.
  4. Nothing configured → a clear error that NEVER contains credential
     contents.

This module NEVER logs and NEVER raises private_key / client_email / token
values — only a generic, secret-free message.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from google.oauth2 import service_account

from app.config import BASE_DIR

_NOT_CONFIGURED_MSG = (
    "Google credentials not configured: set GOOGLE_CREDENTIALS_JSON "
    "or GOOGLE_APPLICATION_CREDENTIALS"
)


def _env(name: str) -> str:
    """Read a variable straight from the process environment.

    Reads ``os.environ`` (not the ``.env``-file-only ``app.config._env``) so
    Railway-injected variables are visible — on Railway there is no ``.env``
    file, the values live only in ``os.environ``.
    """
    return (os.environ.get(name) or "").strip()


def _parse_service_account_json(raw: str) -> dict:
    """``json.loads`` the service-account JSON and repair escaped newlines.

    A very common env-var gotcha: the ``private_key`` PEM body arrives with
    the literal two characters ``\\n`` instead of real newlines (Railway and
    other dashboards escape the value). After parsing, if the key still
    carries literal ``\\n`` sequences, convert them to real newlines so the
    PEM is valid. A correctly-formatted key has real newlines already, so the
    repair is a harmless no-op there.
    """
    info = json.loads(raw)
    private_key = info.get("private_key")
    if isinstance(private_key, str) and "\\n" in private_key:
        info["private_key"] = private_key.replace("\\n", "\n")
    return info


def load_google_credentials(
    scopes: Sequence[str],
    *,
    file_value: str = "",
) -> service_account.Credentials:
    """Resolve Google service-account credentials for ``scopes``.

    See the module docstring for the resolution priority. The returned object
    is a ``google.oauth2.service_account.Credentials`` usable by BOTH
    ``googleapiclient.discovery.build`` (Calendar) and ``gspread.authorize``
    (Sheets). Raises ``RuntimeError`` with a secret-free message when no
    credential source is configured.
    """
    scope_list = list(scopes)

    # 1. Unified env JSON (Railway-safe) — wins over the file path.
    env_json = _env("GOOGLE_CREDENTIALS_JSON")
    if env_json:
        info = _parse_service_account_json(env_json)
        return service_account.Credentials.from_service_account_info(
            info, scopes=scope_list,
        )

    # 2. Per-service value: inline JSON (starts with "{") or a file path.
    candidate = (file_value or "").strip()
    if candidate.startswith("{"):
        info = _parse_service_account_json(candidate)
        return service_account.Credentials.from_service_account_info(
            info, scopes=scope_list,
        )

    # 3. A credentials file path: the per-service value, else the documented
    #    GOOGLE_APPLICATION_CREDENTIALS fallback. Relative paths resolve
    #    against the project root.
    file_path = candidate or _env("GOOGLE_APPLICATION_CREDENTIALS")
    if file_path:
        path = Path(file_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        return service_account.Credentials.from_service_account_file(
            str(path), scopes=scope_list,
        )

    # 4. Nothing configured — clear, secret-free error.
    raise RuntimeError(_NOT_CONFIGURED_MSG)
