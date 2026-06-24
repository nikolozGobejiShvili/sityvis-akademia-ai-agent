"""Admin Panel MVP — HTTP route + auth tests.

Uses FastAPI's TestClient against ``app.main.app`` so the full route
registration + Jinja2 template rendering path is exercised.
"""

from __future__ import annotations

import base64
import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.config import settings as global_settings
from app.routes import admin as admin_routes
from app.main import app


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


@pytest.fixture
def admin_enabled(monkeypatch):
    """Flip the admin panel ON with a known password for one test."""
    swapped = dataclasses.replace(
        global_settings,
        ADMIN_PANEL_ENABLED=True,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="testpw",
    )
    monkeypatch.setattr(admin_routes, "settings", swapped)
    yield swapped


@pytest.fixture
def admin_enabled_no_password(monkeypatch):
    """ENABLED=true but no password set — must refuse access."""
    swapped = dataclasses.replace(
        global_settings,
        ADMIN_PANEL_ENABLED=True,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="",
    )
    monkeypatch.setattr(admin_routes, "settings", swapped)
    yield swapped


@pytest.fixture
def admin_disabled(monkeypatch):
    """Force ADMIN_PANEL_ENABLED=False regardless of .env."""
    swapped = dataclasses.replace(
        global_settings,
        ADMIN_PANEL_ENABLED=False,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="",
    )
    monkeypatch.setattr(admin_routes, "settings", swapped)
    yield swapped


# -- (1) Default (disabled) ------------------------------------------------


def test_admin_disabled_returns_404(admin_disabled):
    client = TestClient(app)
    resp = client.get("/admin", headers=_basic_auth_header("admin", "x"))
    assert resp.status_code == 404


# -- (2) Enabled but missing password → 503 -------------------------------


def test_admin_enabled_without_password_returns_503(admin_enabled_no_password):
    client = TestClient(app)
    resp = client.get("/admin", headers=_basic_auth_header("admin", "x"))
    assert resp.status_code == 503
    assert "ADMIN_PASSWORD" in resp.text or "password" in resp.text.lower()


# -- (3) Enabled + wrong password → 401 -----------------------------------


def test_admin_wrong_password_returns_401(admin_enabled):
    client = TestClient(app)
    resp = client.get("/admin", headers=_basic_auth_header("admin", "wrong"))
    assert resp.status_code == 401


# -- (4) Enabled + no auth header → 401 -----------------------------------


def test_admin_missing_auth_returns_401(admin_enabled):
    client = TestClient(app)
    resp = client.get("/admin")
    assert resp.status_code == 401


# -- (5) Enabled + correct credentials → dashboard rendered ---------------


def test_admin_dashboard_renders(admin_enabled):
    client = TestClient(app)
    resp = client.get("/admin", headers=_basic_auth_header("admin", "testpw"))
    # Hard guard against the TemplateResponse-argument-order regression
    # ("unhashable type: 'dict'" 500 error from passing context where
    # the request should be).
    assert resp.status_code != 500, resp.text[:500]
    assert resp.status_code == 200
    # Page should mention the company name and show "Programs".
    assert "Dashboard" in resp.text
    assert "Programs" in resp.text


# -- (6) Programs list page renders --------------------------------------


def test_admin_programs_list_renders(admin_enabled):
    client = TestClient(app)
    resp = client.get(
        "/admin/programs", headers=_basic_auth_header("admin", "testpw"),
    )
    assert resp.status_code == 200
    # Canonical sections should be listed.
    assert "summer_camp" in resp.text
    assert "sunday_school" in resp.text


# -- (7) Templates page renders ------------------------------------------


def test_admin_templates_list_renders(admin_enabled):
    client = TestClient(app)
    resp = client.get(
        "/admin/templates",
        headers=_basic_auth_header("admin", "testpw"),
    )
    assert resp.status_code == 200
    assert "summer_camp_comment_dm" in resp.text
    assert "default_public_reply" in resp.text


# -- (8) Settings page renders ------------------------------------------


def test_admin_settings_renders(admin_enabled):
    client = TestClient(app)
    resp = client.get(
        "/admin/settings",
        headers=_basic_auth_header("admin", "testpw"),
    )
    assert resp.status_code == 200
    assert "Business hours" in resp.text or "business" in resp.text.lower()


# -- (9) Program edit form renders for known section ---------------------


def test_admin_edit_form_renders_for_summer_camp(admin_enabled):
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/summer_camp",
        headers=_basic_auth_header("admin", "testpw"),
    )
    assert resp.status_code != 500, resp.text[:500]
    assert resp.status_code == 200
    assert "summer_camp" in resp.text
    assert "ამბასადორი კაჭრეთი" in resp.text


# -- (10) Regression sweep — every GET admin route returns 200, not 500 ---


@pytest.mark.parametrize(
    "path",
    [
        "/admin",
        "/admin/programs",
        "/admin/programs/new",
        "/admin/programs/summer_camp",
        "/admin/programs/sunday_school",
        "/admin/programs/adult_events",
        "/admin/templates",
        "/admin/settings",
    ],
)
def test_every_admin_get_route_renders_without_500(admin_enabled, path):
    """Catches the `TemplateResponse(name, context)` → 500 regression.

    Starlette 0.49+ expects `TemplateResponse(request, name, context)`.
    If any route reverts to passing context as the second positional
    arg, Starlette raises `TypeError: unhashable type: 'dict'` and the
    page returns 500. This parametrized test asserts every Admin
    Panel GET route returns 200 with valid credentials.
    """
    client = TestClient(app)
    resp = client.get(path, headers=_basic_auth_header("admin", "testpw"))
    assert resp.status_code != 500, (
        f"{path} returned 500:\n{resp.text[:500]}"
    )
    assert resp.status_code == 200, (
        f"{path} returned {resp.status_code} (expected 200)"
    )


# -- (11) No TemplateResponse call passes a dict as the template name ----


def test_no_admin_template_response_misuse():
    """Static check: every `_jinja.TemplateResponse(...)` invocation in
    admin.py must pass `request` (a Request) as the first positional
    argument, never a dict. This catches the bug at code-review level."""
    import re
    from pathlib import Path

    text = Path(__file__).resolve().parent.parent.joinpath(
        "app", "routes", "admin.py",
    ).read_text(encoding="utf-8")

    # Find every `_jinja.TemplateResponse(<first_token>` and assert the
    # first token after the open paren is `request` (not a string and
    # not a dict literal).
    for match in re.finditer(
        r"_jinja\.TemplateResponse\(\s*([^,)\s]+)", text,
    ):
        first_arg = match.group(1).strip()
        assert first_arg == "request", (
            f"TemplateResponse first positional arg was {first_arg!r} "
            f"— must be the Request instance "
            f"(see Starlette 0.49+ deprecation)"
        )
