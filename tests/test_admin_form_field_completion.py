"""Admin Panel field-completion regression tests.

Covers the live-QA findings:
  * `price_gel` was left stale at 2150 after the operator saved a
    new `price_text=2200` — because the form preserved the existing
    value instead of re-deriving it.
  * The form had no editor for `streams`, `included_items`, or
    `discounts`.

This file pins the contract: every save through the Admin Panel
re-derives `price_gel`, re-writes the three list fields, and the
combined data flows through `get_camp_facts()` → `_get_camp_info` so
the LLM never serves a stale number.
"""

from __future__ import annotations

import base64
import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings as global_settings
from app.main import app
from app.routes import admin as admin_routes
from app.services import admin_config_service


# -- shared fixtures ------------------------------------------------------


def _basic_auth(username: str, password: str) -> dict[str, str]:
    raw = f"{username}:{password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


@pytest.fixture
def admin_enabled(monkeypatch):
    swapped = dataclasses.replace(
        global_settings,
        ADMIN_PANEL_ENABLED=True,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD="testpw",
    )
    monkeypatch.setattr(admin_routes, "settings", swapped)
    yield swapped


@pytest.fixture
def isolated_yaml(tmp_path, monkeypatch):
    """Redirect admin_config writes/reads to a temp dir seeded with a
    summer_camp section that has a STALE price_gel — mirroring the
    live bug."""
    cfg_dir = tmp_path / "admin_config"
    cfg_dir.mkdir()
    monkeypatch.setattr(admin_config_service, "ADMIN_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(
        admin_config_service, "SECTIONS_PATH", cfg_dir / "sections.yaml",
    )
    monkeypatch.setattr(
        admin_config_service, "TEMPLATES_PATH", cfg_dir / "templates.yaml",
    )
    monkeypatch.setattr(
        admin_config_service, "BUSINESS_HOURS_PATH",
        cfg_dir / "business_hours.yaml",
    )
    monkeypatch.setattr(
        admin_config_service, "MANAGER_CONTACTS_PATH",
        cfg_dir / "manager_contacts.yaml",
    )
    # Seed templates so save_section's template_id check passes.
    (cfg_dir / "templates.yaml").write_text(
        "templates:\n"
        "  summer_camp_comment_dm: \"price {price_gel}\"\n"
        "  default_public_reply: \"hi\"\n",
        encoding="utf-8",
    )
    # Seed sections.yaml with the stale shape live QA captured.
    (cfg_dir / "sections.yaml").write_text(
        "sections:\n"
        "  - id: summer_camp\n"
        "    name: საზაფხულო ბანაკი\n"
        "    type: camp\n"
        "    status: active\n"
        "    hashtags: ['ბანაკი']\n"
        "    auto_dm_template_id: summer_camp_comment_dm\n"
        "    price_text: '2200'\n"
        "    price_gel: 2150\n"  # stale — this is what we must overwrite
        "    streams:\n"
        "      - {name: 'I ნაკადი', dates_text: '23-29 ივნისი', status: active}\n",
        encoding="utf-8",
    )
    return cfg_dir


# -- (1) parse_price_gel helper -----------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2200", 2200),
        ("2200 ლარი", 2200),
        ("2,200 ლარი", 2200),
        ("  2150  ", 2150),
        ("ფასი ზუსტდება", None),
        ("", None),
        (None, None),
        ("0", None),       # zero rejected
        ("1234567890123", None),  # > 10^9 rejected
    ],
)
def test_parse_price_gel(text, expected):
    assert admin_config_service.parse_price_gel(text) == expected


# -- (2) get_camp_facts: parsed price_text wins over stale price_gel ----


def test_get_camp_facts_price_text_wins_over_stale_price_gel(monkeypatch):
    """The live-QA bug: sections.yaml had `price_text: '2200'` AND
    `price_gel: 2150`. Before the fix, `price_gel` won. After the fix,
    the integer parsed from `price_text` wins."""
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "price_text": "2200",
            "price_gel": 2150,  # stale
        },
    )
    facts = admin_config_service.get_camp_facts()
    assert facts["price_gel"] == 2200, (
        "price_text-derived number must override stale price_gel"
    )
    assert facts["price_text"] == "2200"


def test_get_camp_facts_keeps_price_gel_when_text_unparseable(monkeypatch):
    """If `price_text` is non-numeric (e.g. "ფასი ზუსტდება"), keep
    whatever integer `price_gel` had — don't silently drop the
    number."""
    monkeypatch.setattr(
        admin_config_service, "get_section",
        lambda _sid: {
            "id": "summer_camp",
            "name": "x", "type": "camp", "status": "active",
            "hashtags": ["ბანაკი"],
            "auto_dm_template_id": "summer_camp_comment_dm",
            "price_text": "ფასი ზუსტდება",
            "price_gel": 2150,
        },
    )
    facts = admin_config_service.get_camp_facts()
    assert facts["price_gel"] == 2150
    assert facts["price_text"] == "ფასი ზუსტდება"


# -- (3) HTTP form save derives price_gel and persists streams ---------


def _summer_camp_form_payload(**overrides) -> dict[str, str]:
    base = {
        "name": "საზაფხულო ბანაკი",
        "type": "camp",
        "status": "active",
        "hashtags": "ბანაკი",
        "age_min": "9",
        "age_max": "17",
        "location": "ამბასადორი კაჭრეთი",
        "duration_text": "",
        "price_text": "2200",
        "payment_terms": "",
        "description_short": "",
        "description_full": "",
        "registration_url": "",
        "manager_contact": "",
        "auto_dm_template_id": "summer_camp_comment_dm",
        "public_reply_template_id": "default_public_reply",
        "cta_text": "",
        "streams_text": (
            "I ნაკადი | 23-29 ივნისი | active\n"
            "II ნაკადი | 5-11 ივლისი | active\n"
            "III ნაკადი | 14-20 ივლისი | active"
        ),
        "included_items_text": "ტრანსპორტი\nგანთავსება\nკვება\nპროგრამა",
        "discounts_text": (
            "10% დედმამიშვილებისთვის\n"
            "10% წინა ბანაკის მონაწილეებისთვის"
        ),
    }
    base.update(overrides)
    return base


def test_form_save_overwrites_stale_price_gel(admin_enabled, isolated_yaml):
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/summer_camp",
        data=_summer_camp_form_payload(price_text="2200"),
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    assert resp.status_code == 303, resp.text[:300]

    saved = admin_config_service.get_section("summer_camp")
    assert saved["price_text"] == "2200"
    assert saved["price_gel"] == 2200, (
        "form save must overwrite stale price_gel — got "
        f"{saved.get('price_gel')!r}"
    )


def test_form_save_with_non_numeric_price_sets_price_gel_null(
    admin_enabled, isolated_yaml,
):
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/summer_camp",
        data=_summer_camp_form_payload(price_text="ფასი ზუსტდება"),
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    saved = admin_config_service.get_section("summer_camp")
    assert saved["price_text"] == "ფასი ზუსტდება"
    assert saved.get("price_gel") is None


def test_form_save_with_price_text_and_unit_extracts_integer(
    admin_enabled, isolated_yaml,
):
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/summer_camp",
        data=_summer_camp_form_payload(price_text="2200 ლარი"),
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    saved = admin_config_service.get_section("summer_camp")
    assert saved["price_text"] == "2200 ლარი"
    assert saved["price_gel"] == 2200


def test_form_save_persists_streams_list(admin_enabled, isolated_yaml):
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/summer_camp",
        data=_summer_camp_form_payload(),
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    assert resp.status_code == 303

    saved = admin_config_service.get_section("summer_camp")
    streams = saved.get("streams") or []
    assert len(streams) == 3
    assert streams[0] == {
        "name": "I ნაკადი", "dates_text": "23-29 ივნისი", "status": "active",
    }
    assert streams[2]["dates_text"] == "14-20 ივლისი"


def test_form_save_persists_included_items_and_discounts(
    admin_enabled, isolated_yaml,
):
    client = TestClient(app)
    resp = client.post(
        "/admin/programs/summer_camp",
        data=_summer_camp_form_payload(),
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    assert resp.status_code == 303
    saved = admin_config_service.get_section("summer_camp")
    assert saved["included_items"] == [
        "ტრანსპორტი", "განთავსება", "კვება", "პროგრამა",
    ]
    assert saved["discounts"] == [
        "10% დედმამიშვილებისთვის", "10% წინა ბანაკის მონაწილეებისთვის",
    ]


# -- (4) Malformed streams line rejected --------------------------------


def test_form_save_rejects_malformed_streams_line(
    admin_enabled, isolated_yaml,
):
    client = TestClient(app)
    payload = _summer_camp_form_payload(
        streams_text="I ნაკადი\nbroken_no_pipes",
    )
    resp = client.post(
        "/admin/programs/summer_camp",
        data=payload,
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    # Validation failure → form re-renders with 400, NOT a 303 redirect.
    assert resp.status_code == 400, resp.text[:300]
    assert "expected" in resp.text or "Line" in resp.text

    # Existing YAML must be unchanged (still has the seeded stale shape).
    saved = admin_config_service.get_section("summer_camp")
    assert saved["price_gel"] == 2150  # stale value preserved on validation failure


def test_form_save_rejects_invalid_stream_status(admin_enabled, isolated_yaml):
    client = TestClient(app)
    payload = _summer_camp_form_payload(
        streams_text="I ნაკადი | 23-29 ივნისი | nonsense",
    )
    resp = client.post(
        "/admin/programs/summer_camp",
        data=payload,
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "status" in resp.text.lower()


# -- (5) After save, get_camp_facts surfaces new price -----------------


def test_get_camp_facts_reflects_admin_save(admin_enabled, isolated_yaml):
    client = TestClient(app)
    client.post(
        "/admin/programs/summer_camp",
        data=_summer_camp_form_payload(price_text="2200"),
        headers=_basic_auth("admin", "testpw"),
        follow_redirects=False,
    )
    facts = admin_config_service.get_camp_facts()
    assert facts["price_gel"] == 2200
    assert facts["price_text"] == "2200"


# -- (6) Edit form renders existing streams in the textarea -----------


def test_edit_form_renders_streams_back_into_textarea(
    admin_enabled, isolated_yaml,
):
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/summer_camp",
        headers=_basic_auth("admin", "testpw"),
    )
    assert resp.status_code == 200
    assert "streams_text" in resp.text
    assert "I ნაკადი | 23-29 ივნისი" in resp.text


def test_edit_form_renders_normalized_price_gel_preview(
    admin_enabled, isolated_yaml,
):
    client = TestClient(app)
    resp = client.get(
        "/admin/programs/summer_camp",
        headers=_basic_auth("admin", "testpw"),
    )
    assert resp.status_code == 200
    # Stale seed has price_gel=2150 still; the form should display it
    # alongside the price_text input.
    assert "2150" in resp.text
    assert "Normalized" in resp.text


# -- (7) Streams parser unit tests -------------------------------------


def test_parse_streams_textarea_three_lines():
    from app.routes.admin import _parse_streams_textarea
    text = (
        "I ნაკადი | 23-29 ივნისი | active\n"
        "II ნაკადი | 5-11 ივლისი | active\n"
        "III ნაკადი | 14-20 ივლისი | active"
    )
    streams, errs = _parse_streams_textarea(text)
    assert errs == []
    assert len(streams) == 3
    assert streams[1] == {
        "name": "II ნაკადი", "dates_text": "5-11 ივლისი", "status": "active",
    }


def test_parse_streams_textarea_empty_returns_empty():
    from app.routes.admin import _parse_streams_textarea
    assert _parse_streams_textarea("") == ([], [])
    assert _parse_streams_textarea("\n\n") == ([], [])


def test_parse_streams_textarea_default_status_active():
    from app.routes.admin import _parse_streams_textarea
    streams, errs = _parse_streams_textarea("I ნაკადი | 23-29 ივნისი")
    assert errs == []
    assert streams[0]["status"] == "active"


def test_parse_streams_textarea_comment_lines_skipped():
    from app.routes.admin import _parse_streams_textarea
    streams, errs = _parse_streams_textarea(
        "# header comment\nI ნაკადი | 23-29 ივნისი | active",
    )
    assert errs == []
    assert len(streams) == 1


def test_parse_streams_textarea_one_pipe_fails():
    from app.routes.admin import _parse_streams_textarea
    _, errs = _parse_streams_textarea("just one part")
    assert len(errs) == 1
    assert "expected" in errs[0]
