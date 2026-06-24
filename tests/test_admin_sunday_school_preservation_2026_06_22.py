"""Admin Panel must PRESERVE the Sunday-School config fields (2026-06-22).

Task 2 moved the Sunday-School status into Admin Config (`sections.yaml`
`sunday_school`): `availability_text` / `details_text` / `handoff_enabled` /
`lead_type`. The section FORM does not surface these fields, and a metadata
save (`POST /admin/programs/{id}`) rebuilds the section from the form, so
before this fix a panel save of `sunday_school` would silently DROP them.

Fix: `save_program` now preserves EVERY existing field the form does not
manage (everything except the form-managed list fields
`streams`/`included_items`/`discounts`, which keep their clear-on-empty
behaviour). These tests pin that contract end-to-end through the real route.

All offline — temp YAML, no real Calendar/Sheets/WhatsApp/Meta/network.
"""
from __future__ import annotations

import base64
import dataclasses

import pytest
from fastapi.testclient import TestClient

from app.config import settings as global_settings
from app.main import app
from app.routes import admin as admin_routes
from app.services import admin_config_service
from app.flows import parent_flow


def _basic_auth(u: str, p: str) -> dict[str, str]:
    raw = f"{u}:{p}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


@pytest.fixture
def admin_enabled(monkeypatch):
    swapped = dataclasses.replace(
        global_settings, ADMIN_PANEL_ENABLED=True,
        ADMIN_USERNAME="admin", ADMIN_PASSWORD="testpw",
    )
    monkeypatch.setattr(admin_routes, "settings", swapped)
    yield swapped


@pytest.fixture
def isolated_yaml(tmp_path, monkeypatch):
    """Temp admin_config seeded with summer_camp + sunday_school (with the
    Task-2 fields AND a custom unknown key) + adult_events (with an events
    list)."""
    cfg_dir = tmp_path / "admin_config"
    cfg_dir.mkdir()
    monkeypatch.setattr(admin_config_service, "ADMIN_CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(admin_config_service, "SECTIONS_PATH", cfg_dir / "sections.yaml")
    monkeypatch.setattr(admin_config_service, "TEMPLATES_PATH", cfg_dir / "templates.yaml")
    monkeypatch.setattr(admin_config_service, "BUSINESS_HOURS_PATH", cfg_dir / "business_hours.yaml")
    monkeypatch.setattr(admin_config_service, "MANAGER_CONTACTS_PATH", cfg_dir / "manager_contacts.yaml")
    (cfg_dir / "templates.yaml").write_text(
        "templates:\n"
        "  summer_camp_comment_dm: \"price {price_gel}\"\n"
        "  sunday_school_comment_dm: \"ss dm\"\n"
        "  adult_events_comment_dm: \"ae dm\"\n"
        "  default_public_reply: \"hi\"\n",
        encoding="utf-8",
    )
    (cfg_dir / "sections.yaml").write_text(
        "sections:\n"
        "  - id: summer_camp\n"
        "    name: საზაფხულო ბანაკი\n"
        "    type: camp\n"
        "    status: active\n"
        "    hashtags: ['ბანაკი']\n"
        "    auto_dm_template_id: summer_camp_comment_dm\n"
        "    price_text: '2150'\n"
        "    price_gel: 2150\n"
        "  - id: sunday_school\n"
        "    name: საკვირაო სკოლა\n"
        "    type: kids_program\n"
        "    status: coming_soon\n"
        "    hashtags: ['საკვირაოსკოლა']\n"
        "    auto_dm_template_id: sunday_school_comment_dm\n"
        "    availability_text: საკვირაო სკოლა ივლისში დაემატება.\n"
        "    details_text: დეტალები ზუსტდება\n"
        "    handoff_enabled: true\n"
        "    lead_type: sunday_school\n"
        "    custom_unknown_key: KEEPME\n"
        "  - id: adult_events\n"
        "    name: ზრდასრულთა ღონისძიებები\n"
        "    type: adult_events\n"
        "    status: active\n"
        "    hashtags: ['ღონისძიება']\n"
        "    auto_dm_template_id: adult_events_comment_dm\n"
        "    events:\n"
        "      - {id: e1, title: 'fromula 1', status: active}\n",
        encoding="utf-8",
    )
    return cfg_dir


def _ss_form_payload(**overrides) -> dict[str, str]:
    base = {
        "name": "საკვირაო სკოლა", "type": "kids_program", "status": "coming_soon",
        "hashtags": "საკვირაოსკოლა", "age_min": "", "age_max": "", "location": "",
        "duration_text": "", "price_text": "", "payment_terms": "",
        "description_short": "განახლებული აღწერა", "description_full": "",
        "registration_url": "", "manager_contact": "",
        "auto_dm_template_id": "sunday_school_comment_dm",
        "public_reply_template_id": "default_public_reply", "cta_text": "",
        "streams_text": "", "included_items_text": "", "discounts_text": "",
    }
    base.update(overrides)
    return base


def _camp_form_payload(**overrides) -> dict[str, str]:
    base = {
        "name": "საზაფხულო ბანაკი", "type": "camp", "status": "active",
        "hashtags": "ბანაკი", "age_min": "9", "age_max": "17",
        "location": "ამბასადორი კაჭრეთი", "duration_text": "",
        "price_text": "2150", "payment_terms": "", "description_short": "",
        "description_full": "", "registration_url": "", "manager_contact": "",
        "auto_dm_template_id": "summer_camp_comment_dm",
        "public_reply_template_id": "default_public_reply", "cta_text": "",
        "streams_text": "", "included_items_text": "", "discounts_text": "",
    }
    base.update(overrides)
    return base


def _save(client, section_id, payload):
    return client.post(
        f"/admin/programs/{section_id}", data=payload,
        headers=_basic_auth("admin", "testpw"), follow_redirects=False,
    )


# ===========================================================================
# (3,5,6,7,8) saving sunday_school via the form preserves its config fields
# ===========================================================================


def test_sunday_school_fields_survive_partial_form_save(admin_enabled, isolated_yaml):
    client = TestClient(app)
    resp = _save(client, "sunday_school", _ss_form_payload())
    assert resp.status_code == 303, resp.text[:400]

    saved = admin_config_service.get_section("sunday_school")
    assert saved["availability_text"] == "საკვირაო სკოლა ივლისში დაემატება."  # (#5)
    assert saved["details_text"] == "დეტალები ზუსტდება"                       # (#6)
    assert saved["handoff_enabled"] is True                                   # (#7)
    assert saved["lead_type"] == "sunday_school"                              # (#8)
    # form-surfaced field DID update
    assert saved["description_short"] == "განახლებული აღწერა"


def test_unknown_custom_key_survives(admin_enabled, isolated_yaml):           # (#4)
    client = TestClient(app)
    assert _save(client, "sunday_school", _ss_form_payload()).status_code == 303
    saved = admin_config_service.get_section("sunday_school")
    assert saved.get("custom_unknown_key") == "KEEPME"


# ===========================================================================
# (1,2) saving OTHER sections does not damage sunday_school
# ===========================================================================


def test_saving_summer_camp_does_not_drop_sunday_school(admin_enabled, isolated_yaml):  # (#1)
    client = TestClient(app)
    assert _save(client, "summer_camp", _camp_form_payload(price_text="2200")).status_code == 303
    ss = admin_config_service.get_section("sunday_school")
    assert ss["availability_text"] == "საკვირაო სკოლა ივლისში დაემატება."
    assert ss["handoff_enabled"] is True and ss["lead_type"] == "sunday_school"
    assert ss.get("custom_unknown_key") == "KEEPME"
    # and summer_camp itself re-derived price (existing behaviour unchanged) (#10)
    assert admin_config_service.get_section("summer_camp")["price_gel"] == 2200


def test_saving_adult_events_does_not_drop_sunday_school(admin_enabled, isolated_yaml):  # (#2,#11)
    client = TestClient(app)
    payload = {
        "name": "ზრდასრულთა ღონისძიებები", "type": "adult_events", "status": "active",
        "hashtags": "ღონისძიება", "age_min": "", "age_max": "", "location": "",
        "duration_text": "", "price_text": "", "payment_terms": "",
        "description_short": "ახალი", "description_full": "", "registration_url": "",
        "manager_contact": "", "auto_dm_template_id": "adult_events_comment_dm",
        "public_reply_template_id": "default_public_reply", "cta_text": "",
        "streams_text": "", "included_items_text": "", "discounts_text": "",
    }
    assert _save(client, "adult_events", payload).status_code == 303
    ss = admin_config_service.get_section("sunday_school")
    assert ss["availability_text"] == "საკვირაო სკოლა ივლისში დაემატება."
    # adult_events events list preserved across a metadata save (#11)
    ae = admin_config_service.get_section("adult_events")
    assert ae.get("events") and ae["events"][0]["title"] == "fromula 1"


# ===========================================================================
# (9) handler still reads config after a simulated admin save
# ===========================================================================


def test_handler_reads_config_after_admin_save(admin_enabled, isolated_yaml):
    client = TestClient(app)
    assert _save(client, "sunday_school", _ss_form_payload()).status_code == 303
    # status reader sees the preserved July text
    st = admin_config_service.get_sunday_school_status()
    assert "ივლის" in st["availability_text"] and st["handoff_enabled"] is True
    # and the deterministic handler renders it (reads the same isolated YAML)
    out = parent_flow._render_sunday_school_answer()
    assert "ივლის" in out and "სახელი" in out and "ნომერ" in out


def test_changed_config_month_then_save_reflects_new_month(admin_enabled, isolated_yaml):
    """Operator changes the month in YAML (availability_text), then saves
    metadata via the form — the new month survives and the handler reflects it."""
    client = TestClient(app)
    admin_config_service.update_section(
        "sunday_school", {"availability_text": "საკვირაო სკოლა სექტემბერში დაიწყება."},
    )
    assert _save(client, "sunday_school", _ss_form_payload()).status_code == 303
    out = parent_flow._render_sunday_school_answer()
    assert "სექტემბერ" in out and "ივლის" not in out


# ===========================================================================
# (13) a section save touches no Calendar / Sheets-booking / WhatsApp
# ===========================================================================


def test_section_save_touches_no_calendar_sheets_whatsapp(admin_enabled, isolated_yaml, monkeypatch):
    from app.services import calendar_service, sheets_service, messenger_service
    for mod, name in (
        (calendar_service, "book_slot"),
        (sheets_service, "save_lead"),
        (sheets_service, "create_lead"),
        (messenger_service, "send_message"),
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name,
                                lambda *a, **k: pytest.fail(f"{name} must not run on a section save"))
    client = TestClient(app)
    assert _save(client, "sunday_school", _ss_form_payload()).status_code == 303
    assert admin_config_service.get_section("sunday_school")["lead_type"] == "sunday_school"


# ===========================================================================
# update_section already deep-merges (preserves) — regression guard
# ===========================================================================


def test_update_section_preserves_unknown_fields(admin_enabled, isolated_yaml):
    errs = admin_config_service.update_section("sunday_school", {"status": "active"})
    assert errs == []
    ss = admin_config_service.get_section("sunday_school")
    assert ss["status"] == "active"
    assert ss["availability_text"] == "საკვირაო სკოლა ივლისში დაემატება."
    assert ss.get("custom_unknown_key") == "KEEPME"
